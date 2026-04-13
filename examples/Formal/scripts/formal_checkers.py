#coding=utf-8
"""Formal verification checkers for the Formal workflow example.

Each Checker class implements a ``do_check(timeout, **kwargs)`` method that
returns ``(success: bool, result: object)``.

Classes are ordered by pipeline stage:

Infrastructure
--------------
FormalStageContext          — shared mtime-cached data (log / doc / checker.sv)
IterationTracker           — tracks verification iterations and convergence

Checker → Stage mapping
-----------------------
EnvSyntaxChecker            — Stage 4  : pyslang syntax validation of checker.sv
WrapperTimingChecker        — Stage 4  : wrapper.sv has clk / rst_n
PropertyStructureChecker    — Stage 5  : SVA properties match spec CK-* entries
ScriptGenerationChecker     — Stage 6  : TCL keyword check + formal execution
EnvironmentAnalysisChecker  — Stage 7  : validates 07_env_analysis.md completeness
                                         (also emits TT/FALSE diagnostic report)
CoverageAnalysisChecker     — Stage 8  : COI coverage from fanin.rep
CounterexampleTestgenChecker— Stage 9  : counterexample Python test file validation
BugReportConsistencyChecker — Stage 10 : bug_report.md covers all RTL_BUG entries
StaticFormalBugLinkageChecker— Stage 11: links static-analysis bugs to formal results

Design principles:
- RTL bug classification is document-driven: the environment analysis
  document (``07_{DUT}_env_analysis.md``) is the single source of truth.
- Log parsing is centralised in ``parse_avis_log()`` (``formal_tools.py``)
  and cached via ``FormalStageContext`` across checkers in the same stage.
- All return values use ``_pass(msg)`` / ``_fail(err, details, suggestion)``
  helpers for consistency.  Complex results use ``return True/False, dict``.
- Parsing and execution logic lives in ``formal_tools.py`` — checkers only
  orchestrate validation.
"""

import json
import os
import re
import time

import pyslang
from ucagent.checkers.base import Checker
from ucagent.util.log import info, warning

# Shared utilities – single source of truth
from examples.Formal.scripts.formal_tools import (
    parse_avis_log,
    resolve_paths as _resolve_paths,
    extract_property_code,
    strip_prop_prefix,
    extract_property_details,
    run_formal_verification,
    extract_rtl_bug_from_analysis_doc,
    extract_static_bugs,
    summarize_execution,
)
from examples.Formal.scripts.formal_adapter import get_adapter

def _pass(msg: str) -> tuple[bool, str]:
    return True, msg

def _fail(err: str, details: str = "", suggestion: str = "") -> tuple[bool, dict]:
    return False, {"error": err, "details": details, "suggestion": suggestion}

def _ensure_tcl_executed(checker_instance, target_log_path: str, dep_paths: list, tcl_script_path: str, dut_name: str, timeout: int = 300) -> tuple[bool, dict, bool]:
    """
    Ensures that the TCL script is executed if any dependency file is newer than the target log file.
    Returns: (is_success, error_result_or_none, was_executed)
    """
    need_rerun = False
    rerun_reason = ""

    if not os.path.exists(target_log_path):
        need_rerun = True
        rerun_reason = f"{os.path.basename(target_log_path)} does not exist, TCL execution required"
    else:
        log_mtime = os.path.getmtime(target_log_path)
        for dep in dep_paths:
            if os.path.exists(dep) and os.path.getmtime(dep) > log_mtime:
                need_rerun = True
                rerun_reason = f"{os.path.basename(dep)} has been updated (newer than {os.path.basename(target_log_path)}), verification needs to be re-executed"
                break

    if need_rerun:
        info(f"🚀 {rerun_reason}, executing TCL script...")
        res = run_formal_verification(tcl_script_path, timeout)
        if not res["success"]:
            return False, {
                "error": "❌ TCL script execution failed",
                "details": f"{res['error']}\n{summarize_execution(res.get('stdout', ''), res.get('stderr', ''))}",
                "suggestion": "Please check the TCL script, checker.sv, and wrapper.sv for syntax errors"
            }, True
            
        info("✅ TCL execution successful, logs updated")
        
    return True, {}, need_rerun




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
        self._doc_cache = {}        # path -> {"mtime": float, "data": dict}

    def get_analysis_doc_parsed(self, doc_path: str) -> dict:
        """Parse analysis document with mtime-based cache invalidation."""
        if self._is_stale(self._doc_cache, doc_path):
            from examples.Formal.scripts.formal_tools import parse_env_analysis_doc
            result = parse_env_analysis_doc(doc_path)
            self._doc_cache[doc_path] = {
                "mtime": os.path.getmtime(doc_path) if os.path.exists(doc_path) else 0,
                "data": result,
            }
        return self._doc_cache[doc_path]["data"]

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
            self._doc_cache.clear()
        else:
            self._log_cache.pop(path, None)
            self._checker_cache.pop(path, None)
            self._doc_cache.pop(path, None)

    def get_rtl_bug_properties(self, analysis_path: str) -> list:
        """Extract property names judged as RTL_BUG from the analysis document.

        Delegates to ``formal_tools.extract_rtl_bug_from_analysis_doc`` as the
        single source of truth, returning only property names (without FA IDs).
        """
        try:
            return [prop for _, prop in extract_rtl_bug_from_analysis_doc(analysis_path)]
        except Exception:
            return []




# =============================================================================
# Environment Analysis Document Checker (Dual-source Validation)
# =============================================================================


class IterationTracker:
    """Tracks verification iterations and checks for convergence."""
    def __init__(self, dut_name, log_file):
        self.dut_name = dut_name
        self.log_file = log_file

    def get_log_path(self) -> str:
        import os
        return os.path.join(os.path.dirname(self.log_file), f".{self.dut_name}_iteration_history.json")

    def record_iteration(self, stats: dict) -> list:
        import json, time, os
        log_path = self.get_log_path()
        history = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    history = json.load(f)
            except Exception: pass
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
            with open(log_path, "w") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception: pass
        return history

    def check_convergence(self, history: list) -> tuple:
        if len(history) < 2: return True, ""
        prev, curr = history[-2], history[-1]
        prev_fail = prev.get("fail_count", 0) + prev.get("cover_fail", 0)
        curr_fail = curr.get("fail_count", 0) + curr.get("cover_fail", 0)
        prev_pass = prev.get("pass_count", 0) + prev.get("cover_pass", 0)
        curr_pass = curr.get("pass_count", 0) + curr.get("cover_pass", 0)
        curr_tt, prev_tt = curr.get("tt_count", 0), prev.get("tt_count", 0)

        msgs = []
        if curr_pass < prev_pass: msgs.append(f"⚠️  REGRESSION: Pass count decreased ({prev_pass} → {curr_pass}). Consider reverting the last modification to checker.sv/wrapper.sv.")
        if curr_fail >= prev_fail and curr_tt >= prev_tt and len(history) >= 3:
            prev2_fail = history[-3].get("fail_count", 0) + history[-3].get("cover_fail", 0)
            if prev2_fail <= prev_fail: msgs.append(f"⚠️  STAGNATION: Fail count has not decreased for 3 consecutive iterations ({prev2_fail} → {prev_fail} → {curr_fail}). Try a different fix strategy — perhaps the root cause is in wrapper.sv signal mapping.")
        if curr_fail > prev_fail: msgs.append(f"⚠️  DEGRADATION: Fail count increased ({prev_fail} → {curr_fail}). The last modification may have introduced new failures.")

        is_ok = not any("REGRESSION" in m for m in msgs)
        return is_ok, "\n".join(msgs)



class EnvSyntaxChecker(Checker):
    """Validates the SystemVerilog syntax of the environment file.

    Enhancements (compared to previous version):
    - Uses pyslang for true SV syntax parsing validation.
    - Checks if the module name follows the {dut}_checker format.
    """
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.env_file = paths["checker_file"]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks the environment file for valid SystemVerilog module syntax."""
        path = self.env_file
        if not os.path.exists(path):
            return _fail(f"Environment file {self.env_file} not found.")

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

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
            return _fail(error_msg, suggestion="Please fix SV syntax errors in checker.sv")

        return _pass("Environment syntax check passed (pyslang validated).")



class WrapperTimingChecker(Checker):
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.wrapper_file = paths["wrapper_file"]
        self.rtl_path = paths["rtl_path"]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Checks if wrapper includes clk and rst_n for formal verification."""
        wrapper_path = self.wrapper_file
        if not os.path.exists(wrapper_path):
            return _fail(f"Wrapper file {self.wrapper_file} not found.")

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
            return _fail(error_msg)

        return _pass("Wrapper timing check passed. Wrapper includes clk and rst_n for formal verification.")





class PropertyStructureChecker(Checker):
    """Validates the consistency of SVA property structure with the specification document.

    Enhancements (compared to previous version):
    - For Comb-style properties, checks if temporal operators are misused.
    """
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.property_file = paths["checker_file"]
        self.spec_file = paths["spec_file"]

    # Temporal operators that must NOT appear in Comb-style properties
    _TEMPORAL_OPS = (
        '@(posedge', '@(negedge', '##', '$past', '$rose', '$fell',
        '$changed', '$stable',  # $stable is temporal in Comb context
        '|=>', 's_eventually',
    )

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Performs structured validation of SVA properties against spec requirements."""
        prop_path = self.property_file
        if not os.path.exists(prop_path):
            return _fail(f"Property file {self.property_file} not found.")

        # Parse Property Implementation
        with open(prop_path, 'r', encoding='utf-8') as f:
            prop_content = f.read()
            
        implemented_map = extract_property_details(prop_content)
        if not implemented_map:
            return _fail("No SVA properties (CK_...) found in implementation file.")

        if not self.spec_file:
            return _pass(f"Found {len(implemented_map)} properties. No spec file provided for consistency check.")

        spec_path = self.spec_file
        if not os.path.exists(spec_path):
            return _fail(f"Spec file {self.spec_file} not found.")

        # Parse Spec Requirements
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_content = f.read()

        # Regex to find: <CK-NAME> or <CK_NAME> (Style: STYLE_STR), allowing optional markdown bold/italic markers
        # Supports both CK- (document-side) and CK_ (legacy) formats
        spec_items = re.findall(r'<(CK[-_][A-Za-z0-9_-]+)>\s*[*_]*\((Style:\s*[^)]+)\)[*_]*', spec_content)
        if not spec_items:
            return _fail(f"No valid CK tags with (Style: ...) found in spec file {self.spec_file}.")

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

            # 4. Unfilled scaffold / placeholder detection (hard error for Stage 5)
            # Matches: `1; // TODO` or bare `true;` that formal_tools.py emits as skeleton
            if re.search(r'^\s*(1|1\'b1|true)\s*;\s*(?://.*)?$', impl['body'], re.MULTILINE) or "[LLM-TODO]" in impl['body']:
                errors.append(
                    f"'{ck_name}' contains an unfilled scaffold body ('1; // TODO' or [LLM-TODO]). "
                    f"Please implement the actual property expression before running verification."
                )
            # 5. Vacuous implication (warning)
            elif re.search(r'\|->\s*(1\'b1|1|true)\s*;', impl['body']):
                warnings_list.append(f"'{ck_name}' implementation appears to be a vacuous placeholder (... |-> 1'b1).")

        if errors:
            error_msg = f"Property Structure Consistency Check Failed for '{self.property_file}':\n"
            error_msg += "\n".join([f"  [ERROR] {e}" for e in errors])
            if warnings_list:
                error_msg += "\n" + "\n".join([f"  [WARN]  {w}" for w in warnings_list])
            return _fail(error_msg)

        result = {"message": f"All {len(spec_items)} CKs from spec are correctly implemented."}
        if warnings_list:
            result["warnings"] = warnings_list
            result["message"] += "\nWarnings:\n" + "\n".join([f"  - {w}" for w in warnings_list])

        return True, result



# =============================================================================
# Script Generation Checker  (Stage 6)
# =============================================================================

class ScriptGenerationChecker(Checker):
    """
    Integrated checker for the script_generation stage.

    Runs two checks in order:
      1. TCL script keyword validation (read_design / prove / def_clk / def_rst must exist).
      2. FormalMC execution — runs the TCL script and validates that at least one
         property result (TRUE/FALSE) appears in the output log.

    Note: PropertyStructureChecker already ran in Stage 5; it is NOT repeated here.
    """
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.tcl_script = paths["tcl_script"]

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Validates TCL syntax then runs formal verification."""

        # --- Step 1: TCL keyword check ---
        info("📝 Step 1/2: Checking TCL script keywords...")
        tcl_path = self.tcl_script
        if not os.path.exists(tcl_path):
            return _fail(f"TCL script not found: {tcl_path}")

        with open(tcl_path, 'r', encoding='utf-8') as f:
            tcl_content = f.read()

        adapter = get_adapter()
        required_cmds = adapter.required_script_commands()
        missing = [k for k in required_cmds if k not in tcl_content]
        if missing:
            return _fail(
                f"❌ Step 1/2 Failed: TCL script missing required commands: {missing}",
                details=f"Please add the missing commands to {tcl_path}",
            )
        info("✅ Step 1/2 Passed: TCL script keywords OK")

        # --- Step 2: Execute formal verification ---
        info("🚀 Step 2/2: Executing TCL script and validating...")
        res = run_formal_verification(tcl_path, timeout,
                                      on_start=lambda w: self.set_check_process(w, timeout))

        if not res["success"]:
            err = res.get("error", "Unknown error")
            return _fail(
                "❌ Step 2/2 Failed: FormalMC execution did not produce results",
                details=f"{err}\n{summarize_execution(res.get('stdout', ''), res.get('stderr', ''))}",
                suggestion="Please check the TCL script, checker.sv, and wrapper.sv for syntax errors",
            )

        # Blackbox check
        if res.get("blackbox_count", 0) > 0:
            return _fail(
                f"Design contains {res['blackbox_count']} blackboxes which is not allowed for complete formal verification.",
                details="Please modify your formal TCL script to ensure all RTL files are correctly included.",
            )

        # Log result analysis
        parsed = res.get("parsed_log") or {}
        failed_count = len(parsed.get("false", [])) + len(parsed.get("cover_fail", []))
        if failed_count > 0:
            return _pass(
                f"✅ Script generation checks passed. "
                f"Verification completed, but {failed_count} properties failed. "
                f"The next stage will involve analyzing these failures."
            )

        return _pass("✅ Script generation checks passed. All properties passed.")



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
      - All required fields are filled in each TT/FA entry (no [LLM-TODO] placeholders).
      - Each FA entry must have a valid resolution status.
      - Properties marked as ENV_PENDING (environment issue identified but not yet fixed)
        will block the checker until they are fixed and updated to ENV_FIXED.
      - Iteration convergence: fail count should not increase across consecutive checks.
    """

    VALID_TT_ROOT_CAUSES = {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}
    VALID_TT_ACTIONS = {"FIXED", "ACCEPTED"}
    VALID_FA_RESOLUTIONS = {"RTL_BUG", "ENV_FIXED", "ENV_PENDING", "COVER_EXPECTED_FAIL"}

    def __init__(self, dut_name, accepted_ratio_threshold=50.0, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.log_file = paths["log_file"]
        self.checker_file = paths["checker_file"]  # used only for mtime rerun detection
        self.wrapper_file = paths["wrapper_file"]
        self.analysis_doc = paths["analysis_doc"]
        self.tcl_script = paths["tcl_script"]
        self.accepted_ratio_threshold = accepted_ratio_threshold

    # _extract_prop_code is replaced by extract_property_code() from formal_tools.


    # -------------------------------------------------------------------------
    # Validation sub-methods (extracted from do_check step 6)
    # -------------------------------------------------------------------------
    def _validate_completeness(self, tt_props, false_props, cover_fail, tt_entries, fa_entries):
        """Validate that every abnormal log property has a corresponding doc entry.

        Returns a list of error strings (empty if all complete).
        """
        errors = []

        # 6a: every TT prop must have a <TT-*> entry
        missing_tt = [p for p in tt_props if p not in tt_entries]
        if missing_tt:
            errors.append(
                f"❌ {len(missing_tt)} TRIVIALLY_TRUE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <TT-NNN> entry)" for p in missing_tt)
            )

        # 6b: every FALSE prop must have a <FA-*> entry
        missing_fa = [p for p in (false_props + cover_fail) if p not in fa_entries]
        if missing_fa:
            errors.append(
                f"❌ {len(missing_fa)} FALSE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <FA-NNN> entry)" for p in missing_fa)
            )

        return errors

    def _validate_entry_quality(self, tt_entries, fa_entries):
        """Validate field completeness, enum values, ACCEPTED ratio, and ENV_PENDING gate.

        Returns ``(errors, warnings)`` — both lists of strings.
        """
        errors = []
        warnings = []

        # 6c: ACCEPTED ratio threshold
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

        # 6d: Field completeness and enum validity
        for prop, entry in tt_entries.items():
            root_cause = entry.get("root_cause", "").strip()
            action     = entry.get("action",     "").strip()
            analysis   = entry.get("analysis",   "").strip()

            if not root_cause:
                errors.append(f"❌ <TT> entry '{prop}' missing '根因分类' field")
            elif root_cause.upper() not in self.VALID_TT_ROOT_CAUSES:
                warnings.append(
                    f"⚠️  <TT> entry '{prop}' has unknown root cause: '{root_cause}'. "
                    f"Valid values: {self.VALID_TT_ROOT_CAUSES}"
                )
            if not action:
                errors.append(f"❌ <TT> entry '{prop}' missing '修复动作' field")
            elif action.upper() not in self.VALID_TT_ACTIONS:
                errors.append(
                    f"❌ <TT> entry '{prop}' has invalid action: '{action}'. "
                    f"Valid values: {self.VALID_TT_ACTIONS}"
                )
            if not analysis:
                errors.append(f"❌ <TT> entry '{prop}' missing '分析' field")

        for prop, entry in fa_entries.items():
            resolution = entry.get("resolution", "").strip()
            analysis   = entry.get("analysis", "").strip()
            if not resolution:
                errors.append(f"❌ <FA> entry '{prop}' missing '解决状态' field")
            elif resolution.upper() not in self.VALID_FA_RESOLUTIONS:
                errors.append(
                    f"❌ <FA> entry '{prop}' has invalid resolution: '{resolution}'. "
                    f"Valid values: {self.VALID_FA_RESOLUTIONS}"
                )
            if not analysis:
                errors.append(f"❌ <FA> entry '{prop}' missing '分析/反例' field")

        # 6e: ENV_PENDING resolution gate
        unresolved_env = [
            prop for prop, entry in fa_entries.items()
            if entry.get("resolution", "").strip().upper() == "ENV_PENDING"
        ]
        if unresolved_env:
            errors.append(
                f"❌ {len(unresolved_env)} ENV_PENDING properties are analyzed but NOT yet resolved:\n"
                + "\n".join(f"  - '{p}'" for p in unresolved_env) + "\n"
                f"  Hint: Re-run verification after adding/modifying assume constraints, "
                f"then update the '解决状态' field to 'ENV_FIXED'."
            )

        return errors, warnings

    # -------------------------------------------------------------------------
    # Main check
    # -------------------------------------------------------------------------
    def do_check(self, timeout=300, **kwargs) -> tuple:
        """Perform tri-source environment analysis validation."""
        log_path = self.log_file
        checker_path = self.checker_file
        analysis_path = self.analysis_doc
        wrapper_path = self.wrapper_file

        # Step 0: Check if re-execution needed
        exec_success, exec_result, was_rerun = _ensure_tcl_executed(
            self, log_path, [checker_path, wrapper_path], self.tcl_script, self.dut_name, timeout
        )
        if not exec_success:
            return _fail(**exec_result)

        # Step 1: Parse avis.log and emit diagnostic report (formerly EnvironmentDebuggingChecker)
        info("🔍 Parsing verification log...")
        ctx = FormalStageContext.get_or_create(self)
        if was_rerun:
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

        # --- Diagnostic report (always emitted, same info EnvironmentDebuggingChecker used to provide) ---
        checker_content = ctx.get_checker_content(checker_path)
        if tt_props:
            tt_list = "\n".join(f"  - {p}" for p in tt_props)
            info(
                f"⚠️  {len(tt_props)} TRIVIALLY_TRUE properties (env over-constrained):\n{tt_list}\n"
                "Fix: relax assume constraints or check wrapper.sv signal mapping."
            )
        if false_props or cover_fail:
            all_fail = false_props + cover_fail
            for prop in all_fail:
                code = extract_property_code(checker_content, prop)
                info(f"❌ FALSE: {prop}\n  SVA code:\n{code}")
            info("Hint: classify each FALSE property as RTL_BUG or ENV_ISSUE in 07_env_analysis.md.")

        # Step 2: Record iteration stats
        stats = {
            "pass_count": len(parsed["pass"]),
            "fail_count": len(false_props),
            "tt_count": len(tt_props),
            "cover_pass": len(parsed["cover_pass"]),
            "cover_fail": len(cover_fail),
        }
        tracker = IterationTracker(self.dut_name, self.log_file)
        history = tracker.record_iteration(stats)

        # Step 3: Check convergence
        conv_ok, conv_msg = tracker.check_convergence(history)

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
                    f"'Guide_Doc/env_analysis.md'.\n\n"
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

        # Step 5: Parse analysis document using Context Cache
        info("📄 Parsing environment analysis document...")
        doc = ctx.get_analysis_doc_parsed(analysis_path)
        tt_entries = doc["tt_entries"]
        fa_entries = doc["fa_entries"]


        # Step 6: Dual-source validation (log × analysis doc)
        # Note: checker.sv is no longer a validation source — analysis doc is sole truth for bug classification
        errors = self._validate_completeness(tt_props, false_props, cover_fail, tt_entries, fa_entries)
        quality_errors, warnings = self._validate_entry_quality(tt_entries, fa_entries)
        errors.extend(quality_errors)

        # --- 6f: Convergence warnings ---
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
                                     if e.get("resolution", "").strip().upper() == "RTL_BUG"),
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
                         if e.get("resolution", "").strip().upper() == "RTL_BUG")
        fa_env_fixed = sum(1 for e in fa_entries.values()
                           if e.get("resolution", "").strip().upper() == "ENV_FIXED")
        fa_env_pending = sum(1 for e in fa_entries.values()
                             if e.get("resolution", "").strip().upper() == "ENV_PENDING")
        fa_cover_expected = sum(1 for e in fa_entries.values()
                                if e.get("resolution", "").strip().upper() == "COVER_EXPECTED_FAIL")

        report["message"] = (
            f"✅ Environment analysis validation passed (iteration #{len(history)})\n"
            f"  TRIVIALLY_TRUE: {len(tt_entries)} analyzed "
            f"({tt_fixed} fixed, {tt_accepted} accepted)\n"
            f"  FALSE: {len(fa_entries)} analyzed "
            f"({fa_rtl_bug} RTL_BUG, "
            f"{fa_env_fixed} ENV_FIXED, {fa_env_pending} ENV_PENDING, "
            f"{fa_cover_expected} COVER_EXPECTED_FAIL)"
        )
        if warnings:
            report["message"] += "\n  " + "\n  ".join(warnings)

        return True, report




# =============================================================================
# Coverage Analysis  (Stage 8)
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
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.tests_dir = os.path.dirname(paths["tcl_script"])
        self.tcl_script = paths["tcl_script"]
        self.checker_file = paths["checker_file"]
        self.coi_threshold = float(kwargs.get("coi_threshold", 100.0))

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Performs COI coverage check using the tool adapter."""

        checker_path = self.checker_file
        adapter = get_adapter()
        fanin_path = adapter.coverage_report_path(self.tests_dir)

        # Step 1: Ensure TCL is executed if needed
        # Fallback to checking the main log file's modification time if there is no distinct explicit report
        tracking_path = fanin_path or os.path.join(self.tests_dir, adapter.log_filename())
        exec_success, exec_result, was_rerun = _ensure_tcl_executed(
            self, tracking_path, [checker_path], self.tcl_script, self.dut_name, timeout
        )
        if not exec_success:
            exec_result["suggestion"] = "Please check checker.sv and wrapper.sv for syntax errors"
            return _fail(**exec_result)

        # Step 2: Parse coverage via adapter
        info(f"🔍 Parsing COI coverage report...")
        coi = adapter.parse_coverage(self.tests_dir)

        overall_pct = coi.get("overall_pct", 0.0)
        uncovered = coi.get("uncovered", [])
        all_ok = overall_pct >= self.coi_threshold

        report = {
            "Threshold": f">= {self.coi_threshold:.0f}%",
            "Overall COI Pct": f"{overall_pct:.1f}%",
            "Uncovered Signal Count": len(uncovered),
            "Uncovered Signals (First 30)": uncovered[:30],
        }

        # Add detailed metrics if explicitly populated (e.g. FormalMC)
        if "nets" in coi:
            report["Nets COI"] = f"{coi['nets']['pct']:.1f}% ({coi['nets']['covered']}/{coi['nets']['total']})"
        if "dffs" in coi:
            report["Dffs COI"] = f"{coi['dffs']['pct']:.1f}% ({coi['dffs']['covered']}/{coi['dffs']['total']})"

        if all_ok:
            return True, {
                "message": f"✅ COI coverage reached threshold: {overall_pct:.1f}%",
                "report": report
            }
        else:
            issues = [
                f"Insufficient COI: {overall_pct:.1f}% < {self.coi_threshold:.0f}%\n"
                f"  → Check the '{adapter.tool_display_name()}' output to find which logic is not influenced by assertions.\n"
                f"  → Typically, you should write assertions monitoring the uncovered signals, or trace to find unused logic."
            ]
            if uncovered:
                signal_list = "\n".join(f"    - {s}" for s in uncovered[:20])
                issues.append(
                    f"Uncovered signals ({len(uncovered)} total, showing first 20):\n"
                    f"{signal_list}\n"
                    f"  → Write assert/cover properties that reference these signals to increase COI.\n"
                    f"  → If a signal is genuinely unreachable from the checker module ports, mark it as [UNREACHABLE] in the spec."
                )

            # Check if RTL_BUG exists — provide context but do NOT auto-bypass
            try:
                ctx = FormalStageContext.get_or_create(self)
                paths = _resolve_paths(self.dut_name)
                rtl_bugs = ctx.get_rtl_bug_properties(paths["analysis_doc"])
                if rtl_bugs:
                    issues.append(
                        f"ℹ️  Note: {len(rtl_bugs)} RTL_BUG(s) confirmed in env analysis ({', '.join(rtl_bugs[:5])}).\n"
                        f"  COI is a structural metric and is NOT affected by property pass/fail status.\n"
                        f"  If coverage is still low, add assertions referencing the uncovered signals listed above."
                    )
            except Exception:
                pass  # Don't let context lookup failure block the checker

            # Add property count context to help LLM understand the current state
            try:
                checker_path = self.checker_file
                if os.path.exists(checker_path):
                    with open(checker_path, 'r', encoding='utf-8', errors='ignore') as f:
                        checker_content = f.read()
                    n_assert = len(re.findall(r'\bassert\s+property\b', checker_content))
                    n_cover  = len(re.findall(r'\bcover\s+property\b', checker_content))
                    n_assume = len(re.findall(r'\bassume\s+property\b', checker_content))
                    report["property_counts"] = {
                        "assert": n_assert, "cover": n_cover, "assume": n_assume
                    }
                    # Check if uncovered signals only appear in cover but not assert
                    if uncovered:
                        cover_only_signals = []
                        for sig in uncovered[:10]:
                            # Strip bit range for matching (e.g., "timer_count[4:0]" -> "timer_count")
                            base_name = re.sub(r'\[.*\]', '', sig).strip()
                            # Remove checker_inst. prefix
                            base_name = base_name.replace("checker_inst.", "")
                            if not base_name:
                                continue
                            in_assert = bool(re.search(
                                rf'\bassert\s+property\b.*?{re.escape(base_name)}',
                                checker_content, re.DOTALL
                            )) or bool(re.search(
                                rf'{re.escape(base_name)}.*?\bassert\s+property\b',
                                checker_content, re.DOTALL
                            ))
                            in_cover = bool(re.search(rf'\bcover\s+property\b.*?{re.escape(base_name)}', checker_content, re.DOTALL))
                            if in_cover and not in_assert:
                                cover_only_signals.append(base_name)
                        if cover_only_signals:
                            unique_sigs = list(dict.fromkeys(cover_only_signals))  # dedupe
                            issues.append(
                                f"⚠️  These uncovered signals appear in cover but NOT in any assert:\n"
                                + "\n".join(f"    - {s}" for s in unique_sigs[:10]) + "\n"
                                f"  Cover properties provide WEAK COI contribution.\n"
                                f"  → Write assert properties that verify the behavioral correctness of these signals."
                            )
            except Exception:
                pass

            return False, {
                "error": "\n".join(issues),
                "report": report,
                "suggestion": f"View complete list of uncovered signals: {fanin_path}"
            }



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
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.analysis_doc = paths["analysis_doc"]
        self.test_file = paths["test_file"]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates counterexample test file against RTL_BUG properties from analysis doc."""
        analysis_path = self.analysis_doc
        test_path = self.test_file

        # Step 1: Extract RTL bugs from analysis document
        # We can extract from parse tree cleanly
        ctx = FormalStageContext.get_or_create(self)
        rtl_bugs = ctx.get_rtl_bug_properties(analysis_path)
        info(f"Found {len(rtl_bugs)} RTL_BUG properties from analysis document")

        # Step 2: Check test file existence
        if not os.path.exists(test_path):
            if not rtl_bugs:
                return _fail(
                    "❌ Test file does not exist",
                    details=(
                        f"Please create '{self.test_file}'. "
                        "Since no RTL_BUG properties were found, "
                        "the file should contain a comment: "
                        "'# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例'"
                    ),
                )
            return _fail(
                "❌ Test file does not exist",
                details=(
                    f"Please create '{self.test_file}' with test functions "
                    f"for the following {len(rtl_bugs)} RTL_BUG properties: "
                    f"{', '.join(rtl_bugs)}"
                ),
            )

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

        # Step 3: Extract implemented test functions
        from examples.Formal.scripts.formal_tools import extract_python_test_functions
        impl_functions = extract_python_test_functions(test_path)
        if not impl_functions:
            return _fail(
                f"❌ No test_cex_* functions found in {self.test_file}",
                details=(
                    f"Found {len(rtl_bugs)} RTL_BUG properties but no "
                    "counterexample test functions. Each RTL_BUG property "
                    "needs a corresponding test_cex_* function."
                ),
            )

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
            for func_name in impl_functions:
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
        for func_name, info_dict in impl_functions.items():
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
                "test_functions_found": list(impl_functions.keys()),
            }
            if quality_warnings:
                result["warnings"] = quality_warnings
            return False, result

        # All checks passed
        result = {
            "message": (
                f"✅ Counterexample test generation passed: "
                f"{len(rtl_bugs)} RTL_BUG properties covered by "
                f"{len(impl_functions)} test functions"
            ),
            "rtl_bugs": rtl_bugs,
            "test_functions": list(impl_functions.keys()),
        }
        if quality_warnings:
            result["warnings"] = quality_warnings
        return True, result



# =============================================================================
# Bug Report Checker  (Stage 10)
# =============================================================================

class BugReportConsistencyChecker(Checker):
    """
    Bug report consistency checker for the formal_execution stage.

    Extracts all properties judged as RTL_BUG from the environment analysis
    document (07_{DUT}_env_analysis.md), and validates that a corresponding
    section has been created for each RTL defect in bug_report.md.
    """
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.analysis_doc = paths["analysis_doc"]
        self.bug_report_file = paths["bug_report_doc"]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """
        Validates the consistency between the bug report and RTL defects.
        Extracts RTL_BUG properties from the analysis document,
        and verifies that bug_report.md has a section for each defect.
        """
        analysis_path = self.analysis_doc

        # Step 1: Extract RTL defects from analysis document
        ctx = FormalStageContext.get_or_create(self)
        rtl_defects = ctx.get_rtl_bug_properties(analysis_path)
            
        info(f"Extracted {len(rtl_defects)} RTL_BUG properties from analysis document")

        if not rtl_defects:
            return True, {
                "message": "✅ No RTL defects to report",
                "note": "No properties judged as RTL_BUG in the analysis document"
            }

        # Step 2: Check if bug report exists
        bug_report_path = self.bug_report_file
        if not os.path.exists(bug_report_path):
            return _fail(
                "❌ Bug report file does not exist",
                details=f"Please create '{self.bug_report_file}' and write reports for the following {len(rtl_defects)} RTL defects: {', '.join(rtl_defects)}",
            )

        with open(bug_report_path, 'r', encoding='utf-8') as f:
            bug_report_content = f.read()

        # Step 3: Parse bug report to extract recorded properties
        # Supports various formats: ## Failed Property: `A_CK_XXX` or ## ❌ Failed Property: A_CK_XXX
        report_sections = re.split(r'##\s*❌?\s*Failed Property:\s*`?([\w.]+)`?', bug_report_content)

        if len(report_sections) <= 1:
            return _fail(
                "❌ Bug report format is incorrect",
                details="No sections found in the '## Failed Property: `prop_name`' format. Expected: ## Failed Property: `A_CK_XXX`",
            )

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

            return _fail(
                "❌ Bug report is inconsistent with RTL defects",
                details="\n".join(issues),
                suggestion=f"Missing: {missing_in_report}, Extra: {extra_in_report}",
            )

        return True, {
            "message": f"✅ Bug report consistency check passed: {len(rtl_defects)} RTL defects have been recorded",
            "rtl_defects": rtl_defects
        }



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
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        paths = _resolve_paths(dut_name, **kwargs)
        self.static_doc = paths["static_doc"]
        self.bug_report_doc = paths["bug_report_doc"]
        self.log_file = paths["log_file"]

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Performs static bug and formal verification results linkage check"""

        static_path = self.static_doc
        bug_report_path = self.bug_report_doc
        log_path = self.log_file

        # Step 1: Parse static bug analysis document (delegated to formal_tools)
        info("🔍 Parsing static bug analysis document...")
        static_bugs = extract_static_bugs(static_path)

        pending = static_bugs["pending"]
        confirmed = static_bugs["confirmed"]
        false_positive = static_bugs["false_positive"]

        info(f"  - Pending Linkage: {len(pending)}")
        info(f"  - Confirmed: {len(confirmed)}")
        info(f"  - False Positives: {len(false_positive)}")

        # Step 2: Check for pending linkage bugs
        if pending:
            pending_list = "\n".join(f"  - {bg_id}: {link_tag}" for bg_id, link_tag in pending)
            return _fail(
                f"❌ Found {len(pending)} static bugs not yet linked to formal verification results",
                details=(
                    f"The following static bug entries still have <LINK-BUG-[BG-TBD]> tags and need to be updated based on formal verification results:\n{pending_list}\n\n"
                    "Linkage Rules:\n"
                    "  - If formal verification confirms the bug → Replace with <LINK-BUG-[BG-XXX-NNN]>\n"
                    "  - If formal verification does not find the bug → Replace with <LINK-BUG-[BG-NA]>\n\n"
                    "Reference Documents:\n"
                    f"  - Formal Verification Results: {log_path}\n"
                    f"  - Bug Report: {bug_report_path}"
                ),
            )

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

