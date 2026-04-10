#coding=utf-8
"""Formal verification checkers for the Formal workflow example.

Each Checker class implements a ``do_check(timeout, **kwargs)`` method that
returns ``(success: bool, result: object)``.

Design principles:
- RTL bug classification is document-driven: the environment analysis
  document (``07_{DUT}_env_analysis.md``) is the single source of truth.
  ``checker.sv`` is NOT used for ``[RTL_BUG]`` markers.
- Log parsing is centralised in ``parse_avis_log()`` (``formal_tools.py``)
  and cached via ``FormalStageContext`` across checkers in the same stage.
- ``EnvSyntaxChecker`` uses ``pyslang`` for real SV syntax validation.
- ``PropertyStructureChecker`` validates that *Comb*-style properties contain
  no temporal operators.
"""

import os
import re
import glob
import subprocess
import pyslang
from ucagent.checkers.base import Checker
from ucagent.util.log import info, warning
import psutil

# Shared utilities – single source of truth
from examples.Formal.scripts.formal_tools import parse_avis_log, extract_rtl_bug_from_analysis_doc


# =============================================================================
# Stage Context — shared, cached data across checkers in the same stage
# =============================================================================

class FormalStageContext:
    """Caches parsed verification data and shares it across checkers.

    Avoids redundant parsing of avis.log and checker.sv when multiple
    checkers (e.g. EnvironmentDebuggingChecker + EnvironmentAnalysisChecker)
    run sequentially in the same stage.

    Usage in any checker's do_check::

        ctx = FormalStageContext.get_or_create(self)
        parsed_log = ctx.get_parsed_log(log_path)
        checker_content = ctx.get_checker_content(checker_path)

    Data is stored via ``smanager_set_value`` so all checkers sharing the
    same ``stage_manager`` see the same cache.  Mtime-based invalidation
    ensures stale data is never reused.
    """

    _SMANAGER_KEY = "_formal_stage_context"

    def __init__(self):
        self._log_cache = {}        # path -> {"mtime": float, "data": dict}
        self._checker_cache = {}    # path -> {"mtime": float, "content": str}

    @classmethod
    def get_or_create(cls, checker_instance, *_args):
        """Retrieve or create a shared context from stage_manager."""
        if checker_instance.stage_manager is not None:
            try:
                ctx = checker_instance.smanager_get_value(cls._SMANAGER_KEY)
                if ctx is not None:
                    return ctx
            except (RuntimeError, AttributeError):
                pass

        ctx = cls()

        if checker_instance.stage_manager is not None:
            try:
                checker_instance.smanager_set_value(cls._SMANAGER_KEY, ctx)
            except (RuntimeError, AttributeError):
                pass  # Fallback: local-only cache, still avoids intra-checker redundancy

        return ctx

    def _is_stale(self, cache_dict: dict, path: str) -> bool:
        """Check if cached data for a path is stale (file modified since cache)."""
        if path not in cache_dict:
            return True
        if not os.path.exists(path):
            return True
        return os.path.getmtime(path) > cache_dict[path]["mtime"]

    def get_parsed_log(self, log_path: str) -> dict:
        """Get parsed avis.log data with mtime-based cache invalidation."""
        if self._is_stale(self._log_cache, log_path):
            data = parse_avis_log(log_path)
            self._log_cache[log_path] = {
                "mtime": os.path.getmtime(log_path),
                "data": data,
            }
        return self._log_cache[log_path]["data"]

    def get_checker_content(self, checker_path: str) -> str:
        """Get checker.sv file content with mtime-based cache."""
        if self._is_stale(self._checker_cache, checker_path):
            content = ""
            if os.path.exists(checker_path):
                with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            self._checker_cache[checker_path] = {
                "mtime": os.path.getmtime(checker_path) if os.path.exists(checker_path) else 0,
                "content": content,
            }
        return self._checker_cache[checker_path]["content"]

    def invalidate(self, path: str = None):
        """Force invalidate cache for a specific path or all."""
        if path is None:
            self._log_cache.clear()
            self._checker_cache.clear()
        else:
            self._log_cache.pop(path, None)
            self._checker_cache.pop(path, None)




class PropertyStructureChecker(Checker):
    """Validates the consistency of SVA property structure with the specification document.

    Enhancements (compared to previous version):
    - For Comb-style properties, checks if temporal operators are misused.
    """
    def __init__(self, property_file, spec_file=None, **kwargs):
        self.property_file = property_file
        self.spec_file = spec_file

    # Temporal operators that must NOT appear in Comb-style properties
    _TEMPORAL_OPS = (
        '@(posedge', '@(negedge', '##', '$past', '$rose', '$fell',
        '$changed', '$stable',  # $stable is temporal in Comb context
        '|=>', 's_eventually',
    )

    def _extract_property_details(self, file_path: str) -> dict:
        """
        Extract property details including names, content, and instantiation type.
        Returns: { 'CK_NAME': {'body': '...', 'type': 'assert|assume|cover'} }
        """
        details = {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 1. Extract property blocks: property NAME; ... endproperty
            prop_blocks = re.findall(r'property\s+(CK_[A-Za-z0-9_]+)\s*;(.*?)\bendproperty', content, re.DOTALL)
            for name, body in prop_blocks:
                details[name] = {'body': body, 'type': None}

            # 2. Extract instantiation statements: label: (assert|assume|cover) property (NAME);
            stmt_matches = re.findall(r'(\w+)\s*:\s*(assert|assume|cover)\s+property\s*\((CK_[A-Za-z0-9_]+)\)', content)
            for inst_label, p_type, prop_name in stmt_matches:
                if prop_name in details:
                    details[prop_name]['type'] = p_type
                else:
                    # Direct definition in assert/assume/cover without separate property block
                    details[prop_name] = {'body': '', 'type': p_type}

            return details
        except Exception as e:
            warning(f"Failed to extract property details from {file_path}: {e}")
            return {}

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Performs structured validation of SVA properties against spec requirements."""
        prop_path = self.get_path(self.property_file)
        if not os.path.exists(prop_path):
            return False, {"error": f"Property file {self.property_file} not found."}

        # Parse Property Implementation
        implemented_map = self._extract_property_details(prop_path)
        if not implemented_map:
            return False, {"error": "No SVA properties (CK_...) found in implementation file."}

        if not self.spec_file:
            return True, f"Found {len(implemented_map)} properties. No spec file provided for consistency check."

        spec_path = self.get_path(self.spec_file)
        if not os.path.exists(spec_path):
            return False, {"error": f"Spec file {self.spec_file} not found."}

        # Parse Spec Requirements
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_content = f.read()

        # Regex to find: <CK-NAME> or <CK_NAME> (Style: STYLE_STR), allowing optional markdown bold/italic markers
        # Supports both CK- (document-side) and CK_ (legacy) formats
        spec_items = re.findall(r'<(CK[-_][A-Za-z0-9_-]+)>\s*[*_]*\((Style:\s*[^)]+)\)[*_]*', spec_content)
        if not spec_items:
            return False, {"error": f"No valid CK tags with (Style: ...) found in spec file {self.spec_file}."}

        errors = []
        warnings_list = []

        for ck_name_raw, style_str in spec_items:
            style = style_str.lower()

            # Normalize: convert document-side CK- format to code-side CK_ format
            # e.g., CK-DATA-STABILITY -> CK_DATA_STABILITY
            ck_name = ck_name_raw.replace('-', '_')

            # Check for Existence
            if ck_name not in implemented_map:
                errors.append(f"Missing implementation for '{ck_name_raw}' ({style_str})")
                continue

            impl = implemented_map[ck_name]

            # 1. Check Keyword Consistency (Type Check)
            if 'assume' in style and impl['type'] != 'assume':
                errors.append(f"'{ck_name}' is marked as 'Assume' in spec, but implemented as '{impl['type'] or 'unknown'}'")
            elif 'cover' in style and impl['type'] != 'cover':
                errors.append(f"'{ck_name}' is marked as 'Cover' in spec, but implemented as '{impl['type'] or 'unknown'}'")
            elif ('comb' in style or 'seq' in style) and impl['type'] not in ['assert', None]:
                # If it's Comb/Seq but uses assume/cover, it's an error
                if impl['type'] in ['assume', 'cover']:
                    errors.append(f"'{ck_name}' is marked as assertion style ({style_str}), but implemented as '{impl['type']}'")

            # 2. Comb-style temporal operator check (NEW)
            if 'comb' in style and impl['body']:
                for op in self._TEMPORAL_OPS:
                    if op in impl['body']:
                        errors.append(
                            f"'{ck_name}' is Comb style but contains temporal operator '{op}'. "
                            f"Comb properties must be purely combinational."
                        )
                        break  # one error per property is enough

            # 3. Check Symbolic Indexing Usage (Advanced Feature Check)
            if 'symbolic' in style:
                # Must use fv_idx or fv_mon_
                if not re.search(r'fv_(idx|mon_)', impl['body']):
                    errors.append(f"'{ck_name}' is marked as 'Symbolic', but its implementation does not use 'fv_idx' or 'fv_mon_' signals.")

            # 4. Placeholder Detection (Quality Check)
            if re.search(r'\|->\s*(1\'b1|1|true)\s*;', impl['body']):
                warnings_list.append(f"'{ck_name}' implementation appears to be a vacuous placeholder (... |-> 1'b1).")

        if errors:
            error_msg = f"Property Structure Consistency Check Failed for '{self.property_file}':\n"
            error_msg += "\n".join([f"  [ERROR] {e}" for e in errors])
            if warnings_list:
                error_msg += "\n" + "\n".join([f"  [WARN]  {w}" for w in warnings_list])
            return False, {"error": error_msg}

        success_msg = f"All {len(spec_items)} CKs from spec are correctly implemented."
        if warnings_list:
            success_msg += "\nWarnings:\n" + "\n".join([f"  - {w}" for w in warnings_list])

        return True, success_msg


class EnvSyntaxChecker(Checker):
    """Validates the SystemVerilog syntax of the environment file.

    Enhancements (compared to previous version):
    - Uses pyslang for true SV syntax parsing validation.
    - Checks if the module name follows the {dut}_checker format.
    """
    def __init__(self, env_file, **kwargs):
        self.env_file = env_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the environment file for valid SystemVerilog module syntax."""
        path = self.get_path(self.env_file)
        if not os.path.exists(path):
            return False, {"error": f"Environment file {self.env_file} not found."}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Basic structure check
        if "module" not in content or "endmodule" not in content:
            return False, {"error": "Environment file does not look like a valid SystemVerilog module."}

        # Verify module name follows convention (optional but recommended)
        module_match = re.search(r'\bmodule\s+(\w+)', content)
        if module_match:
            module_name = module_match.group(1)
            if not module_name.endswith('_checker'):
                # Warning, not error — the module might have a valid alternative name
                info(f"Warning: checker module name '{module_name}' does not end with '_checker'")

        # Use pyslang for real syntax validation
        errors = []
        try:
            tree = pyslang.SyntaxTree.fromText(content)
            # Check for syntax diagnostics
            for diag in tree.diagnostics:
                diag_str = str(diag).strip()
                if diag_str:
                    errors.append(diag_str)
        except Exception as e:
            errors.append(f"pyslang parse error: {e}")

        if errors:
            error_msg = f"SystemVerilog syntax errors in {self.env_file}:\n"
            error_msg += "\n".join([f"  - {e}" for e in errors[:10]])  # Cap at 10 errors
            if len(errors) > 10:
                error_msg += f"\n  ... and {len(errors) - 10} more errors"
            return False, {"error": error_msg}

        return True, "Environment syntax check passed (pyslang validated)."


class WrapperTimingChecker(Checker):
    def __init__(self, wrapper_file, rtl_path, **kwargs):
        self.wrapper_file = wrapper_file
        self.rtl_path = rtl_path

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks if wrapper includes clk and rst_n for formal verification."""
        wrapper_path = self.get_path(self.wrapper_file)
        if not os.path.exists(wrapper_path):
            return False, {"error": f"Wrapper file {self.wrapper_file} not found."}

        # Read wrapper content
        with open(wrapper_path, 'r', encoding='utf-8') as f:
            wrapper_content = f.read()

        errors = []

        # Check if wrapper has clk and rst_n
        if not re.search(r'input\s+clk', wrapper_content):
            errors.append("Wrapper must include 'input clk' for formal verification.")

        if not re.search(r'input\s+rst_n', wrapper_content):
            errors.append("Wrapper must include 'input rst_n' for formal verification.")

        if errors:
            error_msg = "Wrapper timing check failed:\n" + "\n".join(f"  - {e}" for e in errors)
            return False, {"error": error_msg}

        return True, "Wrapper timing check passed. Wrapper includes clk and rst_n for formal verification."


# =============================================================================
# Script / Execution Checkers
# =============================================================================

class FormalScriptChecker(Checker):
    def __init__(self, script_file, **kwargs):
        self.script_file = script_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the formal script for required commands."""
        path = self.get_path(self.script_file)
        if not os.path.exists(path):
            return False, {"error": f"Formal script file {self.script_file} not found."}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        required_cmds = ["read_design", "prove", "def_clk", "def_rst"]
        missing = [k for k in required_cmds if k not in content]

        if missing:
            return False, {"error": f"Formal script missing commands: {missing}"}

        return True, "Formal script check passed."


class TclExecutionChecker(Checker):
    def __init__(self, tcl_script, dut_name, **kwargs):
        self.tcl_script = tcl_script
        self.dut_name = dut_name

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """
        Runs the TCL script using FormalMC and checks the output log for failures.
        The command is executed in the same directory as the tcl script.
        """
        tcl_path = self.get_path(self.tcl_script)
        if not os.path.exists(tcl_path):
            return False, {"error": f"TCL script not found at '{self.tcl_script}'. Cannot run verification."}

        # Use the TCL script's directory as the execution and work directory
        exec_dir = os.path.dirname(tcl_path)

        # The log file is now relative to the execution directory
        log_file_name = "avis.log"
        log_path = os.path.join(exec_dir, log_file_name)

        # The -work_dir argument tells FormalMC where to place its output files.
        cmd = ["FormalMC", "-f", tcl_path, "-override", "-work_dir", exec_dir]
        info(f"Running command: {' '.join(cmd)} in directory {exec_dir}")

        stdout_log = ""
        stderr_log = ""
        try:
            worker = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=exec_dir  # Execute from the script's directory
            )
            self.set_check_process(worker, timeout)
            stdout_log, stderr_log = worker.communicate(timeout=timeout)

            if worker.returncode != 0:
                return False, {
                    "error": f"FormalMC execution failed with return code {worker.returncode}.",
                    "details": "This might indicate an issue with the tool, script, or environment.",
                    "stdout": stdout_log,
                    "stderr": stderr_log
                }

        except FileNotFoundError:
            return False, {"error": "The 'FormalMC' command was not found. Please ensure it is installed and in your PATH."}
        except subprocess.TimeoutExpired:
            try:
                # Import shared helper for robust cleanup
                from examples.Formal.scripts.formal_tools import _terminate_process_tree
                _terminate_process_tree(worker, timeout=5)
            except Exception as ex:
                warning(f"Error terminating process after timeout: {ex}")
            stdout_log, stderr_log = worker.communicate()
            return False, {
                "error": f"Formal verification timed out after {timeout} seconds.",
                "stdout": stdout_log,
                "stderr": stderr_log
            }

        # --- Analyze the log to see if verification ran and produced results ---
        if not os.path.exists(log_path):
            return False, {"error": f"Log file '{log_file_name}' was not generated in '{os.path.dirname(self.tcl_script)}' by the verification run."}

        with open(log_path, 'r', encoding='utf-8') as f:
            log_content = f.read()

        # Check for non-zero blackboxes in log statistics
        blackbox_stats = re.search(r"blackboxes\s*:\s*(\d+)", log_content, re.IGNORECASE)
        if blackbox_stats:
            count = int(blackbox_stats.group(1))
            if count > 0:
                return False, {
                    "error": f"Design contains {count} blackboxes which is not allowed for complete formal verification.",
                    "details": "The log file indicates that some modules were treated as blackboxes. Please modify your formal TCL script to ensure all RTL files are correctly included and correctly identified.",
                    "stdout": stdout_log,
                    "stderr": stderr_log
                }

        # Per user request, check passes if ANY result is found, indicating a successful run.
        if re.search(r"Info-P016: property .* is (?:TRIVIALLY_)?(?:TRUE|FALSE)", log_content):
            failed_properties = re.findall(r"Info-P016: property ([\w_.]+) is (?:TRIVIALLY_)?FALSE", log_content)
            if failed_properties:
                return True, {
                    "message": f"Verification run completed, but {len(failed_properties)} properties failed. This check passes as the script executed correctly.",
                    "details": "The next stage will involve analyzing these failures.",
                    "failed_properties": failed_properties
                }
            else:
                 return True, "Verification run completed successfully. All properties passed."

        # If no TRUE or FALSE results, it's a failure of the run itself.
        return False, {
            "error": "TCL script execution failed to produce results.",
            "details": "The log file was generated, but it contains no conclusive '... is TRUE' or '... is FALSE' messages. This may indicate a syntax error in the SVA or TCL files that prevented the 'prove' command from completing.",
            "stdout": stdout_log,
            "stderr": stderr_log
        }


# =============================================================================
# Composite Checkers
# =============================================================================

class BugReportConsistencyChecker(Checker):
    """
    Bug report consistency checker for the formal_execution stage.

    Extracts all properties judged as RTL_BUG from the environment analysis
    document (07_{DUT}_env_analysis.md), and validates that a corresponding
    section has been created for each RTL defect in bug_report.md.
    """
    def __init__(self, dut_name, analysis_doc, bug_report_file, log_file=None, **kwargs):
        self.dut_name = dut_name
        self.analysis_doc = analysis_doc
        self.bug_report_file = bug_report_file
        self.log_file = log_file if log_file else f"avis/{self.dut_name}.log"

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        Validates the consistency between the bug report and RTL defects.
        Extracts RTL_BUG properties from the analysis document,
        and verifies that bug_report.md has a section for each defect.
        """
        analysis_path = self.get_path(self.analysis_doc)

        # Step 1: Extract RTL defects from analysis document
        rtl_defect_tuples = extract_rtl_bug_from_analysis_doc(analysis_path)
        # Extract just property names for comparison
        rtl_defects = [prop_name for _fa_id, prop_name in rtl_defect_tuples]
        info(f"Extracted {len(rtl_defects)} RTL_BUG properties from analysis document")

        if not rtl_defects:
            return True, {
                "message": "✅ No RTL defects to report",
                "note": "No properties judged as RTL_BUG in the analysis document"
            }

        # Step 2: Check if bug report exists
        bug_report_path = self.get_path(self.bug_report_file)
        if not os.path.exists(bug_report_path):
            return False, {
                "error": "❌ Bug report file does not exist",
                "details": f"Please create '{self.bug_report_file}' and write reports for the following {len(rtl_defects)} RTL defects:",
                "rtl_defects": rtl_defects
            }

        with open(bug_report_path, 'r', encoding='utf-8') as f:
            bug_report_content = f.read()

        # Step 3: Parse bug report to extract recorded properties
        # Supports various formats: ## Failed Property: `A_CK_XXX` or ## ❌ Failed Property: A_CK_XXX
        report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`?([\w.]+)`?', bug_report_content)

        if len(report_sections) <= 1:
            return False, {
                "error": "❌ Bug report format is incorrect",
                "details": "No sections found in the '## Failed Property: `prop_name`' format",
                "expected_format": "## Failed Property: `A_CK_XXX`"
            }

        reported_props = set()
        for i in range(1, len(report_sections), 2):
            prop_name = report_sections[i].strip()
            # Remove potential module prefix (checker_inst.A_CK_XXX -> A_CK_XXX)
            short_name = prop_name.split('.')[-1] if '.' in prop_name else prop_name
            reported_props.add(short_name)

        # Step 4: Compare RTL defects with bug report
        missing_in_report = [d for d in rtl_defects if d not in reported_props]
        extra_in_report = [r for r in reported_props if r not in rtl_defects]

        # Step 5: Generate check results
        if missing_in_report or extra_in_report:
            issues = []
            if missing_in_report:
                issues.append(f"Missing reports for RTL defects ({len(missing_in_report)}): {', '.join(missing_in_report)}")
            if extra_in_report:
                issues.append(f"Extra properties in the report ({len(extra_in_report)}): {', '.join(extra_in_report)}")

            return False, {
                "error": "❌ Bug report is inconsistent with RTL defects",
                "details": issues,
                "missing_in_report": missing_in_report,
                "extra_in_report": extra_in_report,
                "rtl_defects_total": len(rtl_defects)
            }

        return True, {
            "message": f"✅ Bug report consistency check passed: {len(rtl_defects)} RTL defects have been recorded",
            "rtl_defects": rtl_defects
        }


class ScriptGenerationChecker(Checker):
    """
    Integrated script generation checker for the script_generation stage.
    Executes in order:
    1. FormalScriptChecker - TCL script syntax check
    2. PropertyStructureChecker - Property structure check
    3. TclExecutionChecker - TCL script execution validation
    """
    def __init__(self, dut_name, property_file, spec_file, script_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.script_file = script_file
        self.tcl_script = tcl_script

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Performs a three-stage integrated check"""

        # Stage 1: Formal Script Check
        info("📝 Stage 1/3: Checking TCL script syntax...")
        script_checker = FormalScriptChecker(self.script_file)
        script_checker.get_path = self.get_path
        success, result = script_checker.do_check(timeout)

        if not success:
            return False, {
                "error": "❌ Stage 1/3 Failed: TCL script check did not pass",
                "details": result
            }

        info(f"✅ Stage 1/3 Passed: {result}")

        # Stage 2: Property Structure Check
        info("🔍 Stage 2/3: Checking property structure consistency...")
        prop_checker = PropertyStructureChecker(self.property_file, self.spec_file)
        prop_checker.get_path = self.get_path
        success, result = prop_checker.do_check(timeout)

        if not success:
            return False, {
                "error": "❌ Stage 2/3 Failed: Property structure check did not pass",
                "details": result
            }

        info(f"✅ Stage 2/3 Passed: {result}")

        # Stage 3: TCL Execution Check
        info("🚀 Stage 3/3: Executing TCL script and validating...")
        exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
        exec_checker.get_path = self.get_path
        success, result = exec_checker.do_check(timeout)

        if not success:
            return False, {
                "error": "❌ Stage 3/3 Failed: TCL execution validation did not pass",
                "details": result
            }

        info(f"✅ Stage 3/3 Passed")

        return True, {
            "message": "✅ All checks in the script generation stage passed",
            "details": result
        }


# =============================================================================
# Coverage Analysis
# =============================================================================

class CoverageAnalysisChecker(Checker):
    """
    Coverage analysis checker for the coverage_analysis_and_optimization stage.

    Only parses fanin.rep and extracts four COI (Cone of Influence) coverage metrics:
      Inputs / Outputs / Dffs / Nets
    Dff COI (register coverage) and Net COI (combinational logic coverage) are formal verification 
    equivalents to "line coverage" in simulation, and both must meet the threshold.

    Auto-rerun logic:
      If checker.sv is newer than fanin.rep (or fanin.rep does not exist), 
      it automatically re-executes the TCL script to refresh the coverage data.

    fanin.rep format example:
         Inputs :     3 / 3      100%
        Outputs :     4 / 4      100%
           Dffs :    10 / 10     100%
           Nets :    30 / 30     100%
    """
    def __init__(self, dut_name, fanin_rep, tcl_script, checker_file, coi_threshold=100.0, **kwargs):
        self.dut_name = dut_name
        self.fanin_rep = fanin_rep
        self.tcl_script = tcl_script
        self.checker_file = checker_file
        self.coi_threshold = float(coi_threshold)

    def _need_rerun(self, fanin_path: str, checker_path: str) -> tuple[bool, str]:
        """If fanin.rep does not exist or checker.sv is newer, TCL needs to be re-executed."""
        if not os.path.exists(fanin_path):
            return True, "fanin.rep does not exist, TCL execution required to generate coverage report"
        if os.path.exists(checker_path) and os.path.getmtime(checker_path) > os.path.getmtime(fanin_path):
            return True, "checker.sv has been updated (newer than fanin.rep), verification needs to be re-executed"
        return False, "Coverage report is up to date, reading fanin.rep directly"

    def _parse_fanin_report(self, fanin_path: str) -> dict:
        """
        Parses fanin.rep and extracts all COI coverage metrics and the list of uncovered signals.

        Returns:
          {
            "inputs":  {"covered": N, "total": N, "pct": N},
            "outputs": {...},
            "dffs":    {...},
            "nets":    {...},
            "uncovered": [signal, ...]   # lines starting with "- " in fanin -list
          }
        """
        empty = {"covered": 0, "total": 0, "pct": 0.0}
        result = {
            "inputs": dict(empty), "outputs": dict(empty),
            "dffs": dict(empty), "nets": dict(empty),
            "uncovered": []
        }
        if not os.path.exists(fanin_path):
            return result

        with open(fanin_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        metric_re = re.compile(
            r'(Inputs?|Outputs?|Dffs?|Nets?)\s*:\s*(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%',
            re.IGNORECASE
        )
        name_map = {
            'input': 'inputs', 'inputs': 'inputs',
            'output': 'outputs', 'outputs': 'outputs',
            'dff': 'dffs', 'dffs': 'dffs',
            'net': 'nets', 'nets': 'nets',
        }
        for m in metric_re.finditer(content):
            key = name_map.get(m.group(1).lower())
            if key:
                result[key] = {
                    "covered": int(m.group(2)),
                    "total":   int(m.group(3)),
                    "pct":     float(m.group(4))
                }

        # fanin -list output: uncovered signals are listed in the format "- signal_name"
        result["uncovered"] = re.findall(r'^\s*-\s+(\S+)', content, re.MULTILINE)
        return result

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Performs COI coverage check"""

        fanin_path   = self.get_path(self.fanin_rep)
        checker_path = self.get_path(self.checker_file)

        # Step 1: Determine if TCL re-execution is needed
        need_rerun, rerun_reason = self._need_rerun(fanin_path, checker_path)
        if need_rerun:
            info(f"🚀 {rerun_reason}, executing TCL script...")
            exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
            exec_checker.get_path = self.get_path
            exec_success, exec_result = exec_checker.do_check(timeout)
            if not exec_success:
                return False, {
                    "error": "❌ TCL script execution failed, unable to generate coverage report",
                    "details": exec_result,
                    "suggestion": "Please check checker.sv and wrapper.sv for syntax errors"
                }
            info("✅ TCL execution successful, fanin.rep updated")
        else:
            info(f"📋 {rerun_reason}")

        # Step 2: Parse fanin.rep
        info(f"🔍 Parsing COI coverage report: {fanin_path}")
        coi = self._parse_fanin_report(fanin_path)

        def fmt(d):
            if d["total"] == 0:
                return "N/A (no such signals)"
            return f"{d['covered']}/{d['total']}  ({d['pct']:.1f}%)"

        net_pct = coi["nets"]["pct"]
        dff_pct = coi["dffs"]["pct"]
        net_ok = coi["nets"]["total"] == 0 or net_pct >= self.coi_threshold
        dff_ok = coi["dffs"]["total"] == 0 or dff_pct >= self.coi_threshold
        all_ok = net_ok and dff_ok

        report = {
            "fanin_rep": fanin_path,
            "Threshold": f">= {self.coi_threshold:.0f}%",
            "Inputs  COI": fmt(coi["inputs"]),
            "Outputs COI": fmt(coi["outputs"]),
            "Dffs    COI (Register State Coverage)": fmt(coi["dffs"]),
            "Nets    COI (Combinational Logic Coverage)":   fmt(coi["nets"]),
            "Uncovered Signal Count": len(coi["uncovered"]),
            "Uncovered Signals (First 30)": coi["uncovered"][:30],
        }

        if all_ok:
            return True, {
                "message": (
                    f"✅ COI coverage reached threshold\n"
                    f"  Dff COI (Register): {fmt(coi['dffs'])}\n"
                    f"  Net COI (Logic): {fmt(coi['nets'])}"
                ),
                "report": report
            }
        else:
            issues = []
            if not dff_ok:
                issues.append(
                    f"Insufficient Dff COI: {dff_pct:.1f}% < {self.coi_threshold:.0f}%\n"
                    f"  → Some register states are not reached by any assertion; add (Style: Seq) assertions"
                )
            if not net_ok:
                issues.append(
                    f"Insufficient Net COI: {net_pct:.1f}% < {self.coi_threshold:.0f}%\n"
                    f"  → Some combinational logic paths are not covered; add (Style: Comb) assertions"
                )
            return False, {
                "error": "\n".join(issues),
                "report": report,
                "suggestion": f"View complete list of uncovered signals: {fanin_path}"
            }


# =============================================================================
# Environment Debugging (main iteration checker)
# =============================================================================

class EnvironmentDebuggingChecker(Checker):
    """
    Environment debugging checker for the environment_debugging_iteration stage.

    This checker **always passes** — it provides diagnostic information for
    the LLM agent to iterate on.  Gate-keeping is handled by
    ``EnvironmentAnalysisChecker`` via the analysis document.

    Workflow:
    1. Check if the log exists; if not, execute the TCL script to generate it.
    2. If checker.sv or wrapper.sv is newer than the log, re-execute TCL.
    3. Parse the log to extract TRIVIALLY_TRUE and FALSE properties.
    4. Report all abnormal properties with SVA code snippets.
    5. Classification of FALSE properties (RTL_BUG vs ENV_ISSUE) is done
       exclusively in the environment analysis document (07_env_analysis.md),
       NOT via markers in checker.sv.
    """
    def __init__(self, dut_name, property_file, spec_file, log_file, checker_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.log_file = log_file
        self.checker_file = checker_file
        self.tcl_script = tcl_script

    def _extract_prop_code(self, prop_name: str, checker_content: str) -> str:
        """
        Extracts SVA code snippets of a property from checker.sv (5 lines before and after).
        """
        lines = checker_content.split('\n')
        for i, line in enumerate(lines):
            if prop_name in line and ('assert' in line or 'property' in line or ':' in line):
                start = max(0, i - 3)
                end = min(len(lines), i + 6)
                return '\n'.join(lines[start:end])
        # Fallback: only find lines where the property name appears
        for i, line in enumerate(lines):
            if prop_name in line:
                start = max(0, i - 2)
                end = min(len(lines), i + 4)
                return '\n'.join(lines[start:end])
        return "(Property definition not found)"

    def _need_rerun(self, log_path: str, checker_path: str, wrapper_path: str) -> tuple[bool, str]:
        """
        Determines if the TCL script needs to be re-executed.
        If checker.sv or wrapper.sv is newer than avis.log, a rerun is required.
        """
        if not os.path.exists(log_path):
            return True, "Log file does not exist, TCL execution required"

        log_mtime = os.path.getmtime(log_path)

        for fpath, label in [(checker_path, "checker.sv"), (wrapper_path, "wrapper.sv")]:
            if os.path.exists(fpath) and os.path.getmtime(fpath) > log_mtime:
                return True, f"{label} has been updated (newer than log), verification needs to be re-executed"

        return False, "Code not updated, reading existing log directly"

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Performs environment debugging check"""
        log_path = self.get_path(self.log_file)
        checker_path = self.get_path(self.checker_file)

        # Infer wrapper path (same directory as checker, name is {dut}_wrapper.sv)
        tests_dir = os.path.dirname(log_path)
        wrapper_path = os.path.join(tests_dir, f"{self.dut_name}_wrapper.sv")

        # Step 1: Determine if TCL re-execution is needed
        need_rerun, rerun_reason = self._need_rerun(log_path, checker_path, wrapper_path)

        if need_rerun:
            info(f"🚀 {rerun_reason}, executing TCL script...")
            exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
            exec_checker.get_path = self.get_path
            exec_success, exec_result = exec_checker.do_check(timeout)

            if not exec_success:
                return False, {
                    "error": "❌ TCL script execution failed",
                    "details": exec_result,
                    "suggestion": "Please check the TCL script, checker.sv, and wrapper.sv for syntax errors"
                }
            info("✅ TCL execution successful, log updated")
        else:
            info(f"📋 {rerun_reason}")

        # Step 2: Parse log (via shared stage context for cache reuse)
        info("🔍 Parsing verification log...")
        ctx = FormalStageContext.get_or_create(self)
        if need_rerun:
            ctx.invalidate(log_path)  # Force re-parse after TCL rerun
        raw_parsed = ctx.get_parsed_log(log_path)

        # Re-key to match this checker's expected format
        parsed = {
            "trivially_true": raw_parsed["trivially_true"],
            "false_props":    raw_parsed["false"],
            "pass_props":     raw_parsed["pass"],
            "cover_pass":     raw_parsed["cover_pass"],
            "cover_fail":     raw_parsed["cover_fail"],
            "summary": {
                "assert_pass":            len(raw_parsed["pass"]),
                "assert_trivially_true":  len(raw_parsed["trivially_true"]),
                "assert_false":           len(raw_parsed["false"]),
                "cover_pass":             len(raw_parsed["cover_pass"]),
                "cover_fail":             len(raw_parsed["cover_fail"]),
            },
        }
        trivially_true = parsed["trivially_true"]
        false_props = parsed["false_props"]
        summary = parsed["summary"]

        # Step 3: Read checker.sv for SVA code display only
        checker_content = ctx.get_checker_content(checker_path)

        # Step 4: Build report
        has_tt = len(trivially_true) > 0
        has_false = len(false_props) > 0 or len(parsed.get("cover_fail", [])) > 0

        report = {"summary": summary, "log_path": log_path}

        if has_tt:
            tt_list = "\n".join(f"  - {p}" for p in trivially_true)
            report["warning_trivially_true"] = {
                "count": len(trivially_true),
                "props": trivially_true,
                "analysis": (
                    f"⚠️  The following {len(trivially_true)} properties are TRIVIALLY_TRUE (environment over-constrained, fix suggested):\n{tt_list}\n"
                    "Fix Directions:\n"
                    "  1. Check if the corresponding assume constraints are too strong (excluding legal inputs).\n"
                    "  2. Check if $isunknown / !$isunknown assertions are correct—if a signal can't be X, it will be constant-folded.\n"
                    "  3. Check if wrapper.sv signal mapping is incorrect, leading to constant propagation."
                )
            }

        if has_false:
            all_fail = false_props + parsed.get("cover_fail", [])
            fail_details = []
            for prop in all_fail:
                code = self._extract_prop_code(prop, checker_content)
                fail_details.append({"property": prop, "sva_code": code})
            report["false_properties"] = {
                "count": len(all_fail),
                "props": all_fail,
                "details": fail_details,
                "hint": (
                    "For each FALSE property, analyze whether it is:\n"
                    "  - Environment issue (missing assume) → fix checker.sv constraints\n"
                    "  - RTL defect → record in the environment analysis document (07_env_analysis.md)\n"
                    "Classification is done in the analysis document, NOT in checker.sv."
                )
            }

        # This checker always passes — EnvironmentAnalysisChecker handles gate-keeping
        msg = "✅ Environment debugging check completed"
        if has_tt or has_false:
            msg += f" ({len(trivially_true)} TT, {len(false_props)} assert fail, {len(parsed.get('cover_fail', []))} cover fail remaining)"
        report["message"] = msg
        return True, report


# =============================================================================
# Environment Analysis Document Checker (Dual-source Validation)
# =============================================================================

class EnvironmentAnalysisChecker(Checker):
    """Validates the environment analysis document against log results.

    Implements a dual-source validation strategy:
      1. **avis.log** → Source of truth for TRIVIALLY_TRUE / FALSE property lists.
      2. **07_{DUT}_env_analysis.md** → Structured analysis document produced by LLM,
         and the single source of truth for RTL bug classification.

    Note: ``checker_file`` is accepted only for mtime-based rerun detection
    (re-execute TCL when source files change).  Its content is NOT parsed.

    Pass conditions (ALL must be satisfied):
      - Every TRIVIALLY_TRUE property has a corresponding <TT-NNN> entry in the doc.
      - Every FALSE property (assert + cover) has a <FA-NNN> entry in the doc.
      - ACCEPTED ratio for TRIVIALLY_TRUE does not exceed the configured threshold.
      - All required fields are filled in each TT/FA entry.
      - Iteration convergence: fail count should not increase across consecutive checks.
    """

    VALID_TT_ROOT_CAUSES = {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}
    VALID_FA_JUDGMENTS = {"RTL_BUG", "ENV_ISSUE", "COVER_EXPECTED_FAIL"}
    VALID_TT_ACTIONS = {"FIXED", "ACCEPTED"}
    VALID_FA_ACTIONS = {"MARKED_RTL_BUG", "ASSUME_ADDED", "ASSUME_MODIFIED", "COVER_EXPECTED_FAIL"}

    def __init__(self, dut_name, log_file, checker_file, analysis_doc,
                 tcl_script, accepted_ratio_threshold=50.0, **kwargs):
        self.dut_name = dut_name
        self.log_file = log_file
        self.checker_file = checker_file  # used only for mtime rerun detection
        self.analysis_doc = analysis_doc
        self.tcl_script = tcl_script
        self.accepted_ratio_threshold = accepted_ratio_threshold

    # -------------------------------------------------------------------------
    # Parsing helpers
    # -------------------------------------------------------------------------
    def _parse_analysis_doc(self, doc_path: str) -> dict:
        """Parse the environment analysis markdown document.

        Returns:
            {
                "tt_entries": { "A_CK_XXX": { "root_cause": ..., "action": ..., ... }, ... },
                "fa_entries": { "A_CK_YYY": { "judgment": ..., "action": ..., ... }, ... },
                "raw_content": str,
            }
        """
        result = {"tt_entries": {}, "fa_entries": {}, "raw_content": ""}

        if not os.path.exists(doc_path):
            return result

        with open(doc_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        result["raw_content"] = content

        # Parse <TT-NNN> entries
        tt_pattern = re.compile(
            r'###\s*<TT-\d+>\s*(\S+)\s*\n'   # ### <TT-001> A_CK_XXX
            r'(.*?)(?=###\s*<(?:TT|FA)-\d+>|^---$|^## \d+\.|\Z)',  # until next entry or section
            re.DOTALL | re.MULTILINE
        )
        for match in tt_pattern.finditer(content):
            prop_name = match.group(1).strip()
            body = match.group(2)
            entry = self._parse_entry_body(body, is_tt=True)
            entry["prop_name"] = prop_name
            result["tt_entries"][prop_name] = entry

        # Parse <FA-NNN> entries
        fa_pattern = re.compile(
            r'###\s*<FA-\d+>\s*(\S+)\s*\n'
            r'(.*?)(?=###\s*<(?:TT|FA)-\d+>|^---$|^## \d+\.|\Z)',
            re.DOTALL | re.MULTILINE
        )
        for match in fa_pattern.finditer(content):
            prop_name = match.group(1).strip()
            body = match.group(2)
            entry = self._parse_entry_body(body, is_tt=False)
            entry["prop_name"] = prop_name
            result["fa_entries"][prop_name] = entry

        return result

    def _parse_entry_body(self, body: str, is_tt: bool) -> dict:
        """Extract structured fields from a TT or FA entry body."""
        entry = {}

        def _extract(field_name, text):
            # Match "- **FieldName**: value" pattern
            pattern = re.compile(
                rf'[-*]*\s*\*\*{re.escape(field_name)}\*\*\s*:\s*(.*?)(?=\n\s*[-*]*\s*\*\*|\n```|\Z)',
                re.DOTALL
            )
            m = pattern.search(text)
            return m.group(1).strip() if m else None

        entry["prop_name_field"] = _extract("属性名", body) or _extract("Property", body)

        if is_tt:
            entry["root_cause"] = _extract("根因分类", body) or _extract("Root Cause", body) or ""
            entry["related_assume"] = _extract("关联 Assume", body) or _extract("Related Assume", body) or ""
            entry["action"] = _extract("修复动作", body) or _extract("Fix Action", body) or ""
            entry["action_detail"] = _extract("修复说明", body) or _extract("Fix Detail", body) or ""
        else:
            entry["judgment"] = _extract("判定结果", body) or _extract("Judgment", body) or ""
            entry["action"] = _extract("修复动作", body) or _extract("Fix Action", body) or ""
            entry["action_detail"] = _extract("修复说明", body) or _extract("Fix Detail", body) or ""
            entry["prop_type"] = _extract("属性类型", body) or _extract("Property Type", body) or ""

        entry["analysis"] = _extract("分析", body) or _extract("Analysis", body) or _extract("反例/分析", body) or ""

        return entry


    # -------------------------------------------------------------------------
    # Iteration convergence tracking
    # -------------------------------------------------------------------------
    def _get_iteration_log_path(self) -> str:
        """Return path for the iteration history JSON file."""
        tests_dir = os.path.dirname(self.get_path(self.log_file))
        return os.path.join(tests_dir, f".{self.dut_name}_iteration_history.json")

    def _record_iteration(self, stats: dict) -> list:
        """Append current stats to iteration history and return full history."""
        import json
        import time

        log_path = self._get_iteration_log_path()
        history = []

        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    history = json.load(f)
            except (json.JSONDecodeError, IOError):
                history = []

        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pass_count": stats.get("pass_count", 0),
            "fail_count": stats.get("fail_count", 0),
            "tt_count": stats.get("tt_count", 0),
            "cover_pass": stats.get("cover_pass", 0),
            "cover_fail": stats.get("cover_fail", 0),
        }
        history.append(entry)

        try:
            with open(log_path, 'w') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except IOError:
            pass

        return history

    def _check_convergence(self, history: list) -> tuple:
        """Check if iterations are converging.

        Returns: (is_ok, message)
        - is_ok=True means either improving or first iteration.
        - is_ok=False means regression detected (fail count increased).
        """
        if len(history) < 2:
            return True, ""

        prev = history[-2]
        curr = history[-1]

        prev_fail = prev.get("fail_count", 0) + prev.get("cover_fail", 0)
        curr_fail = curr.get("fail_count", 0) + curr.get("cover_fail", 0)
        prev_tt = prev.get("tt_count", 0)
        curr_tt = curr.get("tt_count", 0)
        prev_pass = prev.get("pass_count", 0) + prev.get("cover_pass", 0)
        curr_pass = curr.get("pass_count", 0) + curr.get("cover_pass", 0)

        messages = []

        # Check regression
        if curr_pass < prev_pass:
            messages.append(
                f"⚠️  REGRESSION: Pass count decreased ({prev_pass} → {curr_pass}). "
                f"Consider reverting the last modification to checker.sv/wrapper.sv."
            )

        # Check stagnation
        if curr_fail >= prev_fail and curr_tt >= prev_tt and len(history) >= 3:
            # Check 3-iteration stagnation
            prev2 = history[-3]
            prev2_fail = prev2.get("fail_count", 0) + prev2.get("cover_fail", 0)
            if prev2_fail <= prev_fail:
                messages.append(
                    f"⚠️  STAGNATION: Fail count has not decreased for 3 consecutive iterations "
                    f"({prev2_fail} → {prev_fail} → {curr_fail}). "
                    f"Try a different fix strategy — perhaps the root cause is in wrapper.sv signal mapping."
                )

        if curr_fail > prev_fail:
            messages.append(
                f"⚠️  DEGRADATION: Fail count increased ({prev_fail} → {curr_fail}). "
                f"The last modification may have introduced new failures."
            )

        is_ok = curr_pass >= prev_pass  # Only fail on pass regression
        return is_ok, "\n".join(messages)

    # -------------------------------------------------------------------------
    # Main check
    # -------------------------------------------------------------------------
    def do_check(self, timeout=300, **kwargs) -> tuple:
        """Perform tri-source environment analysis validation."""
        log_path = self.get_path(self.log_file)
        checker_path = self.get_path(self.checker_file)
        analysis_path = self.get_path(self.analysis_doc)

        # Infer wrapper path
        tests_dir = os.path.dirname(log_path)
        wrapper_path = os.path.join(tests_dir, f"{self.dut_name}_wrapper.sv")

        # Step 0: Check if re-execution needed (same logic as EnvironmentDebuggingChecker)
        need_rerun = False
        if not os.path.exists(log_path):
            need_rerun = True
        else:
            log_mtime = os.path.getmtime(log_path)
            for fpath in [checker_path, wrapper_path]:
                if os.path.exists(fpath) and os.path.getmtime(fpath) > log_mtime:
                    need_rerun = True
                    break

        if need_rerun:
            info("🚀 Source files updated, re-executing TCL script...")
            exec_checker = TclExecutionChecker(self.tcl_script, self.dut_name)
            exec_checker.get_path = self.get_path
            exec_success, exec_result = exec_checker.do_check(timeout)
            if not exec_success:
                return False, {
                    "error": "❌ TCL script execution failed",
                    "details": exec_result,
                    "suggestion": "Check TCL script, checker.sv, and wrapper.sv for syntax errors"
                }
            info("✅ TCL execution successful, log updated")

        # Step 1: Parse avis.log (via shared stage context — reuses cache from EnvironmentDebuggingChecker)
        info("🔍 Parsing verification log...")
        ctx = FormalStageContext.get_or_create(self)
        if need_rerun:
            ctx.invalidate(log_path)
        raw = ctx.get_parsed_log(log_path)
        tt_props = raw.get("trivially_true", [])
        false_props = raw.get("false", [])
        cover_fail = raw.get("cover_fail", [])
        parsed = {
            "pass": raw.get("pass", []),
            "cover_pass": raw.get("cover_pass", []),
        }
        all_abnormal_assert = tt_props + false_props
        all_abnormal = all_abnormal_assert + cover_fail

        # Step 2: Record iteration stats
        stats = {
            "pass_count": len(parsed["pass"]),
            "fail_count": len(false_props),
            "tt_count": len(tt_props),
            "cover_pass": len(parsed["cover_pass"]),
            "cover_fail": len(cover_fail),
        }
        history = self._record_iteration(stats)

        # Step 3: Check convergence
        conv_ok, conv_msg = self._check_convergence(history)

        # Step 4: Check if analysis document exists
        if not os.path.exists(analysis_path):
            summary_lines = [
                f"📊 Log Summary: {len(parsed['pass'])} pass, {len(tt_props)} TT, "
                f"{len(false_props)} assert fail, {len(cover_fail)} cover fail",
            ]
            if conv_msg:
                summary_lines.append(f"\n{conv_msg}")

            return False, {
                "error": "❌ Environment analysis document not found",
                "details": (
                    f"Please create '{self.analysis_doc}' following the template "
                    f"'Guide_Doc/dut_env_analysis_template.md'.\n\n"
                    f"The document must contain analysis entries for:\n"
                    f"  - {len(tt_props)} TRIVIALLY_TRUE properties (each needs a <TT-NNN> entry)\n"
                    f"  - {len(false_props)} FALSE assert properties (each needs a <FA-NNN> entry)\n"
                    f"  - {len(cover_fail)} FALSE cover properties (each needs a <FA-NNN> entry)\n\n"
                    f"Problematic properties:\n"
                    + "\n".join(f"  [TT] {p}" for p in tt_props)
                    + ("\n" if tt_props else "")
                    + "\n".join(f"  [FAIL-Assert] {p}" for p in false_props)
                    + ("\n" if false_props else "")
                    + "\n".join(f"  [FAIL-Cover] {p}" for p in cover_fail)
                ),
                "log_summary": "\n".join(summary_lines),
                "iteration": len(history),
            }

        # Step 5: Parse analysis document
        info("📄 Parsing environment analysis document...")
        doc = self._parse_analysis_doc(analysis_path)
        tt_entries = doc["tt_entries"]
        fa_entries = doc["fa_entries"]


        # Step 6: Dual-source validation (log × analysis doc)
        # Note: checker.sv is no longer a validation source — analysis doc is sole truth for bug classification
        errors = []
        warnings = []

        # --- 6a: Completeness — every TT prop must have a <TT-*> entry ---
        missing_tt = []
        for prop in tt_props:
            if prop not in tt_entries:
                missing_tt.append(prop)
        if missing_tt:
            errors.append(
                f"❌ {len(missing_tt)} TRIVIALLY_TRUE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <TT-NNN> entry)" for p in missing_tt)
            )

        # --- 6b: Completeness — every FALSE prop must have a <FA-*> entry ---
        all_false = false_props + cover_fail
        missing_fa = []
        for prop in all_false:
            if prop not in fa_entries:
                missing_fa.append(prop)
        if missing_fa:
            errors.append(
                f"❌ {len(missing_fa)} FALSE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <FA-NNN> entry)" for p in missing_fa)
            )

        # --- 6c: ACCEPTED ratio threshold ---
        if tt_entries:
            accepted_count = sum(
                1 for e in tt_entries.values()
                if e.get("action", "").strip().upper() == "ACCEPTED"
            )
            total_tt = len(tt_entries)
            accepted_ratio = (accepted_count / total_tt * 100) if total_tt > 0 else 0

            if accepted_ratio > self.accepted_ratio_threshold:
                errors.append(
                    f"❌ ACCEPTED ratio for TRIVIALLY_TRUE too high: "
                    f"{accepted_count}/{total_tt} = {accepted_ratio:.0f}% "
                    f"(threshold: {self.accepted_ratio_threshold:.0f}%)\n"
                    f"  → Too many TRIVIALLY_TRUE properties accepted without fixing. "
                    f"Review and fix the underlying assume constraints."
                )

        # --- 6d: Field completeness check ---
        for prop, entry in tt_entries.items():
            if not entry.get("root_cause", "").strip():
                errors.append(f"❌ <TT> entry '{prop}' missing '根因分类' field")
            elif entry["root_cause"].strip().upper() not in self.VALID_TT_ROOT_CAUSES:
                warnings.append(
                    f"⚠️  <TT> entry '{prop}' has unknown root cause: '{entry['root_cause']}'. "
                    f"Valid: {self.VALID_TT_ROOT_CAUSES}"
                )
            if not entry.get("action", "").strip():
                errors.append(f"❌ <TT> entry '{prop}' missing '修复动作' field")
            if not entry.get("analysis", "").strip():
                errors.append(f"❌ <TT> entry '{prop}' missing '分析' field")

        for prop, entry in fa_entries.items():
            if not entry.get("judgment", "").strip():
                errors.append(f"❌ <FA> entry '{prop}' missing '判定结果' field")
            if not entry.get("action", "").strip():
                errors.append(f"❌ <FA> entry '{prop}' missing '修复动作' field")
            if not entry.get("analysis", "").strip():
                errors.append(f"❌ <FA> entry '{prop}' missing '分析/反例' field")

        # --- 6e: Convergence warnings ---
        if conv_msg:
            warnings.append(conv_msg)

        # Build report
        report = {
            "log_summary": {
                "assert_pass": len(parsed["pass"]),
                "assert_trivially_true": len(tt_props),
                "assert_fail": len(false_props),
                "cover_pass": len(parsed["cover_pass"]),
                "cover_fail": len(cover_fail),
            },
            "doc_summary": {
                "tt_entries": len(tt_entries),
                "fa_entries": len(fa_entries),
                "rtl_bug_count": sum(1 for e in fa_entries.values()
                                     if e.get("judgment", "").strip().upper() == "RTL_BUG"),
            },
            "iteration": len(history),
        }

        if warnings:
            report["warnings"] = warnings

        if errors:
            report["errors"] = errors
            report["error"] = (
                f"❌ Environment analysis validation failed ({len(errors)} issues)\n\n"
                + "\n\n".join(errors)
            )
            return False, report

        # All checks passed
        # Build summary
        tt_fixed = sum(1 for e in tt_entries.values()
                       if e.get("action", "").strip().upper() == "FIXED")
        tt_accepted = sum(1 for e in tt_entries.values()
                          if e.get("action", "").strip().upper() == "ACCEPTED")
        fa_rtl_bug = sum(1 for e in fa_entries.values()
                         if e.get("judgment", "").strip().upper() == "RTL_BUG")
        fa_env_issue = sum(1 for e in fa_entries.values()
                           if e.get("judgment", "").strip().upper() == "ENV_ISSUE")
        fa_cover_expected = sum(1 for e in fa_entries.values()
                                if e.get("judgment", "").strip().upper() == "COVER_EXPECTED_FAIL")

        report["message"] = (
            f"✅ Environment analysis validation passed (iteration #{len(history)})\n"
            f"  TRIVIALLY_TRUE: {len(tt_entries)} analyzed "
            f"({tt_fixed} fixed, {tt_accepted} accepted)\n"
            f"  FALSE: {len(fa_entries)} analyzed "
            f"({fa_rtl_bug} RTL bugs, {fa_env_issue} env issues, "
            f"{fa_cover_expected} expected cover fails)"
        )
        if warnings:
            report["message"] += "\n  " + "\n  ".join(warnings)

        return True, report


# =============================================================================
# Counterexample Python Test Generation Checker
# =============================================================================

class CounterexampleTestgenChecker(Checker):
    """Validates generated Python counterexample test cases for the
    counterexample_python_testgen stage.

    Checks:
    1. Test file exists.
    2. If RTL_BUG properties exist in the analysis document, each must have a
       corresponding ``test_cex_`` function in the test file.
    3. Each test function must contain at least one ``assert`` statement
       and a ``dut.Finish()`` call.
    4. If no RTL_BUG properties exist, the test file should contain a
       "no defects" comment.
    """

    def __init__(self, dut_name, analysis_doc, test_file, log_file=None, **kwargs):
        self.dut_name = dut_name
        self.analysis_doc = analysis_doc
        self.test_file = test_file
        self.log_file = log_file

    def _extract_test_functions(self, test_path: str) -> dict:
        """Extract test function details from the Python test file.

        Returns a dict: { 'test_cex_ck_xxx': {'has_assert': bool, 'has_finish': bool} }
        """
        if not os.path.exists(test_path):
            return {}

        with open(test_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        functions = {}
        # Find all test_cex_ function definitions
        func_pattern = re.compile(r'^def\s+(test_cex_\w+)\s*\(', re.MULTILINE)
        func_matches = list(func_pattern.finditer(content))

        for idx, match in enumerate(func_matches):
            func_name = match.group(1)
            # Get the function body (until the next def or end of file)
            start = match.start()
            if idx + 1 < len(func_matches):
                end = func_matches[idx + 1].start()
            else:
                end = len(content)
            func_body = content[start:end]

            functions[func_name] = {
                'has_assert': 'assert ' in func_body,
                'has_finish': 'Finish()' in func_body,
            }

        return functions

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates counterexample test file against RTL_BUG properties from analysis doc."""
        analysis_path = self.get_path(self.analysis_doc)
        test_path = self.get_path(self.test_file)

        # Step 1: Extract RTL bugs from analysis document
        rtl_bug_tuples = extract_rtl_bug_from_analysis_doc(analysis_path)
        # Extract just property names for comparison
        rtl_bugs = [prop_name for _fa_id, prop_name in rtl_bug_tuples]
        info(f"Found {len(rtl_bugs)} RTL_BUG properties from analysis document")

        # Step 2: Check test file existence
        if not os.path.exists(test_path):
            if not rtl_bugs:
                return False, {
                    "error": "❌ Test file does not exist",
                    "details": (
                        f"Please create '{self.test_file}'. "
                        "Since no RTL_BUG properties were found, "
                        "the file should contain a comment: "
                        "'# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例'"
                    ),
                }
            return False, {
                "error": "❌ Test file does not exist",
                "details": (
                    f"Please create '{self.test_file}' with test functions "
                    f"for the following {len(rtl_bugs)} RTL_BUG properties:"
                ),
                "rtl_bugs": rtl_bugs,
            }

        with open(test_path, 'r', encoding='utf-8', errors='ignore') as f:
            test_content = f.read()

        # Step 3: No RTL bugs case
        if not rtl_bugs:
            # Just verify the file exists and has the no-defects comment
            if '无需生成反例测试' in test_content or '未发现 RTL 缺陷' in test_content or 'no RTL defect' in test_content.lower():
                return True, {
                    "message": "✅ No RTL_BUG properties found; test file correctly indicates no defects",
                }
            return True, {
                "message": "✅ No RTL_BUG properties found; test file exists",
                "note": "Consider adding a comment indicating no RTL defects were found",
            }

        # Step 4: Extract test functions
        test_funcs = self._extract_test_functions(test_path)
        if not test_funcs:
            return False, {
                "error": f"❌ No test_cex_* functions found in {self.test_file}",
                "details": (
                    f"Found {len(rtl_bugs)} RTL_BUG properties but no "
                    "counterexample test functions. Each RTL_BUG property "
                    "needs a corresponding test_cex_* function."
                ),
                "rtl_bugs": rtl_bugs,
            }

        # Step 5: Check coverage — each RTL bug should have a test
        # Normalize names: A_CK_XXX -> ck_xxx for matching test_cex_ck_xxx
        errors = []

        # Build a mapping from normalized CK name to test function
        covered_bugs = set()
        for bug_prop in rtl_bugs:
            # Normalize: A_CK_XXX -> ck_xxx
            normalized = bug_prop.lower()
            if normalized.startswith('a_'):
                normalized = normalized[2:]

            # Check if any test function name contains the normalized property name
            found = False
            for func_name in test_funcs:
                # test_cex_ck_xxx should contain ck_xxx
                if normalized in func_name:
                    found = True
                    covered_bugs.add(bug_prop)
                    break

            if not found:
                errors.append(
                    f"Missing test for RTL_BUG property '{bug_prop}': "
                    f"expected a function like 'test_cex_{normalized}'"
                )

        # Step 6: Validate test function quality
        quality_warnings = []
        for func_name, info_dict in test_funcs.items():
            if not info_dict['has_assert']:
                errors.append(
                    f"Function '{func_name}' has no assert statement. "
                    "Each counterexample test must verify expected vs actual output."
                )
            if not info_dict['has_finish']:
                quality_warnings.append(
                    f"Function '{func_name}' missing dut.Finish() call. "
                    "This may cause resource leaks."
                )

        if errors:
            result = {
                "error": f"❌ Counterexample test validation failed ({len(errors)} issues)",
                "issues": errors,
                "rtl_bugs_total": len(rtl_bugs),
                "covered": len(covered_bugs),
                "test_functions_found": list(test_funcs.keys()),
            }
            if quality_warnings:
                result["warnings"] = quality_warnings
            return False, result

        # All checks passed
        result = {
            "message": (
                f"✅ Counterexample test generation passed: "
                f"{len(rtl_bugs)} RTL_BUG properties covered by "
                f"{len(test_funcs)} test functions"
            ),
            "rtl_bugs": rtl_bugs,
            "test_functions": list(test_funcs.keys()),
        }
        if quality_warnings:
            result["warnings"] = quality_warnings
        return True, result


# =============================================================================
# Static Bug - Formal Bug Linkage Checker
# =============================================================================

class StaticFormalBugLinkageChecker(Checker):
    """
    Static Bug and Formal Verification Linkage Checker, used for the static_bug_validation stage.

    Workflow:
    1. Parse the static bug analysis document to extract all <BG-STATIC-*> entries and their <LINK-BUG-[BG-TBD]> tags.
    2. Parse the formal verification results (avis.log and bug_report.md).
    3. Check if all <LINK-BUG-[BG-TBD]> tags have been correctly replaced with:
       - Specific bug tags (e.g., <LINK-BUG-[BG-SUM-WIDTH-001]>).
       - Or false positive tags (<LINK-BUG-[BG-NA]>).
    4. Pass condition: No <LINK-BUG-[BG-TBD]> remains in the document.

    Tag Formats:
    - Static Bug Entry: <BG-STATIC-001-NAME>
    - Pending Linkage Tag: <LINK-BUG-[BG-TBD]>
    - Confirmed Tag: <LINK-BUG-[BG-SUM-WIDTH-001]> or <LINK-BUG-[BG-XXX][BG-YYY]>
    - False Positive Tag: <LINK-BUG-[BG-NA]>
    """
    def __init__(self, static_doc, bug_report_doc, log_file, **kwargs):
        self.static_doc = static_doc
        self.bug_report_doc = bug_report_doc
        self.log_file = log_file

    def _extract_static_bugs(self, static_path: str) -> dict:
        """
        Extracts all static bug entries and their linkage status from the static bug analysis document.

        Returns:
        {
            "pending": [(bg_id, link_tag), ...],  # Bugs pending linkage
            "confirmed": [(bg_id, link_tag), ...], # Confirmed
            "false_positive": [(bg_id, link_tag), ...],  # False positives
        }
        """
        result = {
            "pending": [],
            "confirmed": [],
            "false_positive": [],
        }

        if not os.path.exists(static_path):
            return result

        with open(static_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Find all <BG-STATIC-...> tags
        bg_pattern = re.compile(r'(<BG-STATIC-[A-Za-z0-9_-]+>)')
        bg_matches = bg_pattern.findall(content)

        # Find all <LINK-BUG-[...]> tags
        link_pattern = re.compile(r'(<LINK-BUG-\[([^\]]+)\]>)')

        for bg_id in bg_matches:
            # Find corresponding LINK-BUG tag after BG tag
            bg_pos = content.find(bg_id)
            if bg_pos == -1:
                continue

            # Search within a reasonable range (e.g., 500 chars) after the BG tag
            search_range = content[bg_pos:bg_pos + 500]
            link_matches = link_pattern.findall(search_range)

            if link_matches:
                for full_tag, link_value in link_matches:
                    if link_value == "BG-TBD":
                        result["pending"].append((bg_id, full_tag))
                    elif link_value == "BG-NA":
                        result["false_positive"].append((bg_id, full_tag))
                    else:
                        result["confirmed"].append((bg_id, full_tag))

        return result

    def _extract_formal_bugs(self, bug_report_path: str, log_path: str) -> set:
        """
        Extracts all confirmed bug tags from the formal verification results.

        Returns: A set of bug tags, e.g., {"BG-SUM-WIDTH-001", "BG-XXX-002"}.
        """
        formal_bugs = set()

        # 1. Extract bug tags from bug_report.md
        if os.path.exists(bug_report_path):
            with open(bug_report_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # Match <BG-XXX-NNN> format
            bg_pattern = re.compile(r'<(BG-[A-Za-z0-9_-]+)>')
            formal_bugs.update(bg_pattern.findall(content))

        # 2. Extract detection points corresponding to FALSE properties from avis.log
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                pass  # Reserved for future: extract FALSE properties to enrich linkage

        return formal_bugs

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Performs static bug and formal verification results linkage check"""

        static_path = self.get_path(self.static_doc)
        bug_report_path = self.get_path(self.bug_report_doc)
        log_path = self.get_path(self.log_file)

        # Step 1: Parse static bug analysis document
        info("🔍 Parsing static bug analysis document...")
        static_bugs = self._extract_static_bugs(static_path)

        pending = static_bugs["pending"]
        confirmed = static_bugs["confirmed"]
        false_positive = static_bugs["false_positive"]

        info(f"  - Pending Linkage: {len(pending)}")
        info(f"  - Confirmed: {len(confirmed)}")
        info(f"  - False Positives: {len(false_positive)}")

        # Step 2: Check for pending linkage bugs
        if pending:
            pending_list = "\n".join(f"  - {bg_id}: {link_tag}" for bg_id, link_tag in pending)
            return False, {
                "error": f"❌ Found {len(pending)} static bugs not yet linked to formal verification results",
                "pending_bugs": pending,
                "details": (
                    f"The following static bug entries still have <LINK-BUG-[BG-TBD]> tags and need to be updated based on formal verification results:\n{pending_list}\n\n"
                    "Linkage Rules:\n"
                    "  - If formal verification confirms the bug → Replace with <LINK-BUG-[BG-XXX-NNN]>\n"
                    "  - If formal verification does not find the bug → Replace with <LINK-BUG-[BG-NA]>\n\n"
                    "Reference Documents:\n"
                    f"  - Formal Verification Results: {log_path}\n"
                    f"  - Bug Report: {bug_report_path}"
                ),
                "static_doc": static_path,
            }

        # Step 3: Statistics
        total = len(confirmed) + len(false_positive)
        confirmed_rate = len(confirmed) / total * 100 if total > 0 else 0
        false_positive_rate = len(false_positive) / total * 100 if total > 0 else 0

        # Step 4: Build pass report
        result = {
            "message": "✅ Static bug and formal verification results linkage check passed",
            "statistics": {
                "Total Static Bugs": total,
                "Confirmed": len(confirmed),
                "False Positives": len(false_positive),
                "Confirmation Rate": f"{confirmed_rate:.1f}%",
                "False Positive Rate": f"{false_positive_rate:.1f}%",
            },
            "confirmed_bugs": confirmed,
            "false_positive_bugs": false_positive,
            "static_doc": static_path,
        }

        return True, result
