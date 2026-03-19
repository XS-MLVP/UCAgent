#coding=utf-8
"""Formal verification checkers for the Formal workflow example.

Each Checker class implements a ``do_check(timeout, **kwargs)`` method that
returns ``(success: bool, result: object)``.

Changes from previous version:
- Removed unused ``EnvironmentIterationChecker`` (superseded by
  ``EnvironmentDebuggingChecker``).
- ``EnvSyntaxChecker`` now performs real SystemVerilog syntax validation via
  ``pyslang`` instead of a naive string search.
- ``PropertyStructureChecker`` validates that *Comb*-style properties contain
  no temporal operators.
- Bare ``except:`` clauses replaced with ``except Exception as e:`` and logged.
- ``EnvironmentDebuggingChecker._parse_log()`` now delegates to the shared
  ``parse_avis_log()`` utility in ``formal_tools``.
"""

import os
import re
import glob
import subprocess
import pyslang
from ucagent.checkers.base import Checker
from ucagent.util.log import info, warning
import psutil

# Shared log parser – single source of truth
from examples.Formal.scripts.formal_tools import parse_avis_log


# =============================================================================
# Basic Checkers
# =============================================================================

class FormalAnalysisChecker(Checker):
    """Checks the basic structure of the formal analysis file (verification planning document).

    .. deprecated::
        This Checker is currently not referenced by formal.yaml and is kept only for backward compatibility.
    """
    def __init__(self, analysis_file, **kwargs):
        self.analysis_file = analysis_file

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the formal analysis file for required keywords."""
        path = self.get_path(self.analysis_file)
        if not os.path.exists(path):
            return False, {"error": f"Formal analysis file {self.analysis_file} not found."}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        required_keywords = ["Verification Goal", "Verification Scope", "Properties", "FormalMC"]
        missing = [k for k in required_keywords if k not in content]

        if missing:
            return False, {"error": f"Formal analysis file missing keywords: {missing}"}

        return True, "Formal analysis file check passed."


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

    Extracts all properties marked with // [RTL_BUG] from checker.sv,
    and validates that a corresponding section has been created for each RTL defect in bug_report.md.
    """
    def __init__(self, dut_name, property_file, bug_report_file, log_file=None, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.bug_report_file = bug_report_file
        self.log_file = log_file if log_file else f"avis/{self.dut_name}.log"

    def _extract_rtl_defects_from_checker(self, checker_path: str) -> list:
        """
        Extracts all properties marked with [RTL_BUG] from checker.sv.

        Format:
        // [RTL_BUG] Description...
        A_CK_XXX: assert property(...);

        Returns: List of property names.
        """
        if not os.path.exists(checker_path):
            return []

        with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        rtl_defects = []
        for i, line in enumerate(lines):
            # Search for [RTL_BUG] marker
            if '[RTL_BUG]' in line:
                # Search for property definition in subsequent lines (up to 5 lines)
                for j in range(i, min(i + 6, len(lines))):
                    # Match property_name: assert property(...) or assert property @(...) property_name
                    match = re.search(r'([A-Z_][A-Z0-9_]*)\s*:\s*assert\s+property', lines[j])
                    if match:
                        rtl_defects.append(match.group(1))
                        break

        return rtl_defects

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        Validates the consistency between the bug report and RTL defects.
        Extracts properties marked with [RTL_BUG] from checker.sv,
        and verifies that bug_report.md has a section for each defect.
        """
        checker_path = self.get_path(self.property_file)

        # Step 1: Extract RTL defects from checker.sv
        rtl_defects = self._extract_rtl_defects_from_checker(checker_path)
        info(f"Extracted {len(rtl_defects)} properties marked with [RTL_BUG] from checker.sv")

        if not rtl_defects:
            return True, {
                "message": "✅ No RTL defects to report",
                "note": "No properties marked with [RTL_BUG] were found in checker.sv"
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

    Workflow:
    1. Check if the log exists; if not, execute the TCL script to generate the log.
    2. If checker.sv or wrapper.sv is newer than the log file, re-execute the TCL script.
    3. Parse the log to extract TRIVIALLY_TRUE and FALSE properties.
    4. Categorize FALSE properties:
       - Properties marked with // [RTL_BUG] in checker.sv → Confirmed RTL defects, ignored in this stage.
       - Unmarked FALSE properties → Possible environment issues (under-constraint), requiring LLM analysis and decision.
    5. Pass condition: No TRIVIALLY_TRUE and no unclassified FALSE properties.

    FALSE property categorization convention (LLM adds markers in checker.sv):
    - Confirmed RTL defect: Add // [RTL_BUG] comment before or on the same line as the property definition.
      Example: // [RTL_BUG] counter does not increment correctly, see counter.v:42
               A_CK_COUNT_MAX_REACHED: assert property(...);
    - Confirmed environment issue: After fixing the assume constraints, the property should become PASS.
    """
    def __init__(self, dut_name, property_file, spec_file, log_file, checker_file, tcl_script, **kwargs):
        self.dut_name = dut_name
        self.property_file = property_file
        self.spec_file = spec_file
        self.log_file = log_file
        self.checker_file = checker_file
        self.tcl_script = tcl_script

    def _parse_log(self, log_path: str) -> dict:
        """Parse avis.log using the shared parser, returning a structured result.

        Delegates to ``parse_avis_log`` for the heavy lifting, then adds a
        summary dict for convenience.
        """
        parsed = parse_avis_log(log_path)

        # Re-key to match previous API expected by do_check
        result = {
            "trivially_true": parsed["trivially_true"],
            "false_props":    parsed["false"],
            "pass_props":     parsed["pass"],
            "cover_pass":     parsed["cover_pass"],
            "cover_fail":     parsed["cover_fail"],
            "summary": {
                "assert_pass":            len(parsed["pass"]),
                "assert_trivially_true":  len(parsed["trivially_true"]),
                "assert_false":           len(parsed["false"]),
                "cover_pass":             len(parsed["cover_pass"]),
                "cover_fail":             len(parsed["cover_fail"]),
            },
        }
        return result

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

    def _classify_false_props(self, false_props: list, checker_content: str) -> tuple[list, list]:
        """
        Categorizes FALSE properties into confirmed RTL defects and unclassified ones.

        Criterion: Whether there is an [RTL_BUG] marker within the corresponding property...endproperty block or its preceding comment area.
        Search range: From 3 lines before the `property CK_XXX;` definition line to 2 lines after the assert statement line.
        This ensures correct detection regardless of whether the LLM places [RTL_BUG] before the property block or before the assert line.

        Returns: (rtl_defects, unclassified)
        """
        lines = checker_content.split('\n')
        rtl_defects = []
        unclassified = []

        for prop in false_props:
            found_marker = False

            # Derive property block name CK_XXX from A_CK_XXX (remove A_ prefix)
            ck_name = prop[2:] if prop.startswith('A_') else prop

            # 1. Find assert line: A_CK_XXX: assert property(...)
            assert_idx = None
            for i, line in enumerate(lines):
                if prop in line and 'assert' in line:
                    assert_idx = i
                    break

            # 2. Find property definition line: property CK_XXX; or property CK_XXX (
            prop_def_idx = None
            for i, line in enumerate(lines):
                if re.search(rf'\bproperty\s+{re.escape(ck_name)}\b', line):
                    prop_def_idx = i
                    break

            # 3. Determine search range
            if prop_def_idx is not None:
                # 3 lines before property definition (covering [RTL_BUG] comment area)
                search_start = max(0, prop_def_idx - 3)
            elif assert_idx is not None:
                # If property definition not found, fallback to 10 lines before assert line
                search_start = max(0, assert_idx - 10)
            else:
                # Not found at all, mark as unclassified
                unclassified.append(prop)
                continue

            search_end = min(len(lines), (assert_idx if assert_idx is not None else prop_def_idx + 10) + 3)

            window = '\n'.join(lines[search_start:search_end])
            if '[RTL_BUG]' in window:
                found_marker = True

            if found_marker:
                rtl_defects.append(prop)
            else:
                unclassified.append(prop)

        return rtl_defects, unclassified

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

        # Step 2: Parse log
        info("🔍 Parsing verification log...")
        parsed = self._parse_log(log_path)
        trivially_true = parsed["trivially_true"]
        false_props = parsed["false_props"]
        summary = parsed["summary"]

        # Step 3: Read checker.sv for FALSE property analysis
        checker_content = ""
        if os.path.exists(checker_path):
            with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
                checker_content = f.read()

        # Step 4: Categorize all Fail properties (assert fail + cover fail)
        # Criterion: presence of [RTL_BUG] comment in checker.sv
        #   - With [RTL_BUG] marker → Confirmed RTL defect, allow passing in this stage, deep analysis in formal_execution
        #   - No marker             → Unclassified, must be handled (fix environment or mark RTL_BUG)
        rtl_defects_assert, unclassified_false = self._classify_false_props(false_props, checker_content)
        rtl_defects_cover, unclassified_cover_fail = self._classify_false_props(parsed["cover_fail"], checker_content)

        all_rtl_defects = rtl_defects_assert + rtl_defects_cover
        all_unclassified = unclassified_false + unclassified_cover_fail

        # Step 5: Determine pass condition
        # TRIVIALLY_TRUE is a warning (does not block pass); any unclassified Fail blocks (must fix environment or mark RTL_BUG)
        has_tt = len(trivially_true) > 0
        has_unclassified = len(all_unclassified) > 0

        # Build common report body
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
                    "  3. Check if wrapper.sv signal mapping is incorrect, leading to constant propagation.\n"
                    "Note: TRIVIALLY_TRUE does not block stage completion, but it's recommended to fix them to improve verification effectiveness."
                )
            }

        def _build_unclassified_detail(props, prop_kind):
            details = []
            for prop in props:
                code = self._extract_prop_code(prop, checker_content)
                details.append({"property": prop, "sva_code": code})
            prop_list = "\n".join(f"  - {p}" for p in props)
            if prop_kind == "assert":
                hint = (
                    f"The following {len(props)} assert Fail properties have not been categorized and need to be analyzed one by one:\n{prop_list}\n\n"
                    "Analysis Steps (for each property):\n"
                    "  1. Read the SVA code shown above to understand what this property is verifying.\n"
                    "  2. Use the ReadTextFile tool to examine the RTL code and analyze why this property failed.\n"
                    "  3. Decision: Is this an RTL bug? Or an environmental issue where insufficient constraints allowed the tool to find an unrealistic counterexample?\n"
                    "     Environment Issue Characteristics: Counterexample shows unreasonable input combinations; or assume constraints are obviously missing.\n"
                    "     RTL Defect Characteristics: Counterexample demonstrates a real RTL functional error (e.g., bit-width error, arithmetic error, logic error).\n"
                    "  4. If confirmed as an RTL defect: Add the following before the property definition in checker.sv:\n"
                    "       // [RTL_BUG] <Short Description>\n"
                    "  5. If confirmed as an environment issue: Fix the corresponding assume constraint; the property should become PASS after the fix.\n"
                    "  6. After completing all markings/fixes, call Check again."
                )
            else:
                hint = (
                    f"The following {len(props)} cover Fail properties have not been categorized and need to be analyzed one by one:\n{prop_list}\n\n"
                    "cover Fail means the scenario was never reached. Analysis steps:\n"
                    "  1. Read the SVA code shown above to understand what state this cover is supposed to reach.\n"
                    "  2. Use the ReadTextFile tool to examine the RTL code and assume constraints.\n"
                    "  3. Decision: Is this scenario unreachable due to an RTL bug? Or is the assume too strong, excluding this scenario?\n"
                    "     Environment Over-constraint Characteristics: Scenario becomes reachable after relaxing the assume.\n"
                    "     RTL Defect Characteristics: Logically should be reachable, but RTL implementation is incorrect.\n"
                    "  4. If confirmed as an RTL defect: Add the following before the property definition in checker.sv:\n"
                    "       // [RTL_BUG] <Short Description>\n"
                    "  5. If confirmed as an environment over-constraint: Fix the corresponding assume; the cover should become PASS after the fix.\n"
                    "  6. After completing all markings/fixes, call Check again."
                )
            return {"count": len(props), "props": props, "details": details, "analysis_required": hint}

        if unclassified_false:
            report["unclassified_assert_fail"] = _build_unclassified_detail(unclassified_false, "assert")

        if unclassified_cover_fail:
            report["unclassified_cover_fail"] = _build_unclassified_detail(unclassified_cover_fail, "cover")

        if all_rtl_defects:
            report["rtl_defects_already_marked"] = all_rtl_defects

        if has_unclassified:
            parts = []
            if unclassified_false:
                parts.append(f"{len(unclassified_false)} assert Fail unclassified")
            if unclassified_cover_fail:
                parts.append(f"{len(unclassified_cover_fail)} cover Fail unclassified")
            report["error"] = (
                "❌ Environment debugging incomplete: " + ", ".join(parts) +
                ".\nPlease analyze each Fail property: add // [RTL_BUG] if it's an RTL defect; fix the assume constraint if it's an environment issue."
            )
            if has_tt:
                report["error"] += f"\n(Additionally, there are {len(trivially_true)} TRIVIALLY_TRUE warnings, suggested to fix but not blocking)"
            return False, report

        # Pass: All Fails categorized (TRIVIALLY_TRUE is warning only)
        rtl_list = "\n".join(f"  - {p}" for p in all_rtl_defects)
        result = {
            "summary": summary,
            "rtl_defects_confirmed": all_rtl_defects,
            "note": (
                f"Confirmed {len(all_rtl_defects)} RTL defects (marked [RTL_BUG]), "
                "which will be analyzed in depth during the formal_execution stage:\n" + rtl_list
                if all_rtl_defects else "No unclassified Fail properties, verification environment quality is good"
            ),
            "log_path": log_path
        }
        if has_tt:
            result["message"] = f"✅ Environment debugging stage passed (with {len(trivially_true)} TRIVIALLY_TRUE warnings, fix suggested)"
            result["warning_trivially_true"] = report["warning_trivially_true"]
        else:
            result["message"] = "✅ Environment debugging stage passed"
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
                log_content = f.read()
            # Extract FALSE properties
            false_props = re.findall(r'Info-P016: property [\w.]+ is (?:TRIVIALLY_)?FALSE', log_content)

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
