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
- All return values use ``self._pass(msg)`` / ``self._fail(err, details, suggestion)``
  helpers for consistency.  Complex results use ``return True/False, dict``.
- Parsing and execution logic lives in ``formal_tools.py`` — checkers only
  orchestrate validation.
"""

import json
import os
import re
import time

from ucagent.checkers.base import Checker
from ucagent.util.log import info, warning


# Shared utilities – single source of truth
from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import (
    parse_avis_log,
    extract_property_code,
    strip_prop_prefix,
    extract_property_details,
    run_formal_verification,
    extract_rtl_bug_from_analysis_doc,
    extract_static_bugs,
    summarize_execution,
    extract_python_test_functions,
    analyze_signal_coverage_usage,
    FormalStageContext,
    log_filename,
    coverage_report_path,
    parse_coverage,
    required_script_commands,
    load_records,
    get_all_ck_from_records,
    update_records_sva_body,
    save_records,
    auto_scaffold_analysis_entries,
    auto_scaffold_bug_entries,
)

class BaseFormalChecker(Checker):
    """Base class for formal verification checkers."""
    def __init__(self, dut_name, **kwargs):
        self.dut_name = dut_name
        self.paths = FormalPaths(dut=dut_name)

    def _pass(self, msg: str) -> tuple[bool, str]:
        return True, msg

    def _fail(self, err: str, details: str = "", suggestion: str = "") -> tuple[bool, dict]:
        return False, {"error": err, "details": details, "suggestion": suggestion}

    def _ensure_tcl_executed(self, dep_paths: list, tcl_script_path: str, timeout: int = 300) -> tuple[bool, dict, bool]:
        """
        Ensures that the TCL script is re-executed if any dependency file
        has uncommitted changes (detected via git dirty-file list).

        When source files (checker.sv, wrapper.sv) are dirty, re-running the
        EDA tool is mandatory and the log is guaranteed to be regenerated.

        Returns: (is_success, error_result_or_none, was_executed)
        """
        need_rerun = False
        rerun_reason = ""

        # Check if any dependency file has uncommitted changes
        try:
            from ucagent.util import diff_ops
            dirty_files = set(diff_ops.get_dirty_files(self.workspace))
            for dep in dep_paths:
                rel_dep = os.path.relpath(dep, self.workspace)
                if rel_dep in dirty_files:
                    need_rerun = True
                    rerun_reason = f"{os.path.basename(dep)} has uncommitted changes"
                    break
        except (ValueError, Exception):
            # Not a git repo or workspace not set — fallback: always rerun
            need_rerun = True
            rerun_reason = "Git status unavailable, running verification to be safe"

        if need_rerun:
            info(f"🚀 {rerun_reason}, executing TCL script...")
            res = run_formal_verification(tcl_script_path, timeout, records_path=self.paths.records_yaml)
            if not res["success"]:
                return False, {
                    "error": "❌ TCL script execution failed",
                    "details": f"{res['error']}\n{summarize_execution(res.get('stdout', ''), res.get('stderr', ''))}",
                    "suggestion": "Please check the TCL script, checker.sv, and wrapper.sv for syntax errors"
                }, True
                
            info("✅ TCL execution successful, logs updated")
            
        return True, {}, need_rerun


class FormalSpecJsonChecker(BaseFormalChecker):

    """Validates the spec structure in .formal_records.yaml."""

    _VALID_STYLES = {"assume", "comb", "seq", "cover"}

    def __init__(self, dut_name, check_level="ck", **kwargs):
        super().__init__(dut_name, **kwargs)
        self._counts = {"fg": 0, "fc": 0, "ck": 0}
        self._check_level = check_level.lower() if check_level else "ck"

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates the formal specification structure and content."""
        records_path = self.paths.records_yaml
        if not os.path.exists(records_path):
            return self._fail(
                f"❌ .formal_records.yaml not found at {records_path}",
                suggestion=(
                    "Use RunSkillScript to call update_spec.py to create spec entries. "
                    "See func-spec skill for details."
                ),
            )

        records = load_records(records_path)
        if not records or not records.spec:
            return self._fail(
                "❌ Spec structure missing in .formal_records.yaml",
                suggestion="Use update_spec.py -action add_fg to create function groups.",
            )

        groups = records.spec.function_groups
        if not groups:
            return self._fail("❌ spec.function_groups is empty. Define at least one function group (FG).")

        errors = []
        fg_ids = set()
        fc_count = 0
        ck_count = 0

        for fg in groups:
            fg_id = fg.id
            if not fg_id:
                errors.append("A function group is missing 'id' field.")
                continue
            fg_ids.add(fg_id)

            functions = fg.functions

            # FC-level checks (fc and ck levels)
            if self._check_level in ("fc", "ck"):
                if not functions:
                    errors.append(f"{fg_id}: No functions (FC) defined.")
                    continue

            for fc in functions:
                fc_id = fc.id
                if not fc_id:
                    errors.append(f"{fg_id}: A function is missing 'id' field.")
                    continue
                fc_count += 1

                # CK-level checks (ck level only)
                if self._check_level == "ck":
                    cks = fc.check_points
                    if not cks:
                        errors.append(f"{fc_id}: No check_points (CK) defined.")
                        continue

                    for ck in cks:
                        ck_id = ck.id
                        style = ck.style
                        if not ck_id:
                            errors.append(f"{fc_id}: A check_point is missing 'id' field.")
                            continue
                        if not ck_id.startswith("CK-"):
                            errors.append(f"{ck_id}: CK id must start with 'CK-'.")
                        if style.lower() not in self._VALID_STYLES:
                            errors.append(
                                f"{ck_id}: Invalid style '{style}'. "
                                f"Must be one of: {', '.join(sorted(self._VALID_STYLES))}"
                            )
                        ck_count += 1
                else:
                    # Count CKs for display even if not validating
                    ck_count += len(fc.check_points)

        # FG-API is required at ck level
        if self._check_level == "ck":
            if not any(fid.startswith("FG-API") for fid in fg_ids):
                errors.append("Missing required 'FG-API' function group (环境约束).")

        self._counts = {"fg": len(fg_ids), "fc": fc_count, "ck": ck_count}

        if errors:
            return self._fail(
                f"❌ Spec structure validation failed ({len(errors)} issues)",
                details="\n".join(f"  - {e}" for e in errors),
            )

        # Auto-generate Spec Markdown doc only at ck level (final sub-stage)
        if self._check_level == "ck":
            try:
                from ucagent.lang.zh.skills.formal.lib.formal_tools import generate_spec_doc
                generate_spec_doc(records, self.paths.spec)
                info(f"Auto-generated spec doc: {self.paths.spec}")
            except Exception as e:
                info(f"Warning: Could not auto-generate spec doc: {e}")

        level_label = {"fg": "FG", "fc": "FG+FC", "ck": "FG+FC+CK"}[self._check_level]
        return self._pass(
            f"Spec structure valid ({level_label}): {len(fg_ids)} FG, {fc_count} FC, {ck_count} CK"
        )


    def get_template_data(self):
        return {
            "COUNT_FG": f"[FG:{self._counts['fg']}]" if self._counts["fg"] else "",
            "COUNT_FC": f"[FC:{self._counts['fc']}]" if self._counts["fc"] else "",
            "COUNT_CK": f"[CK:{self._counts['ck']}]" if self._counts["ck"] else "",
        }



class PropertyStructureChecker(BaseFormalChecker):
    """Validates the consistency of SVA property structure with the specification document."""

    # Temporal operators that must NOT appear in Comb-style properties
    _TEMPORAL_OPS = (
        '@(posedge', '@(negedge', '##', '$past', '$rose', '$fell',
        '$changed', '$stable',  # $stable is temporal in Comb context
        '|=>', 's_eventually',
    )

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates that SVA properties are defined in YAML and then renders SV files."""
        records_path = self.paths.records_yaml
        if not os.path.exists(records_path):
            return self._fail(f"Records file {records_path} not found.")

        records = load_records(records_path)
        if not records or not records.spec:
            return self._fail("No spec found in records.")

        errors = []
        ck_count = 0
        implemented_count = 0

        for fg in records.spec.function_groups:
            for fc_item in fg.functions:
                for ck in fc_item.check_points:
                    ck_count += 1
                    body = ck.sva_body or ""
                    if body and "[LLM-TODO]" not in body and "1'b1;" not in body:
                        implemented_count += 1
                    else:
                        errors.append(f"Missing or placeholder SVA implementation in YAML for '{ck.id}'")


        if errors:
            return self._fail(
                f"❌ SVA Implementation incomplete ({implemented_count}/{ck_count} implemented)",
                details="\n".join(f"  - {e}" for e in errors),
                suggestion="Use 'update_sva_body.py' skill to fill 'sva_body' for each checkpoint in YAML."
            )

        # Determine Rendering Mode based on stage name
        # Stages 3-5 (foundational) use 'full', Stage 6+ (iterative) use 'append'
        mode = "full"
        stage_name = getattr(self.stage, "name", "").lower()
        if any(s in stage_name for s in ["debugging", "optimization", "audit", "iteration"]):
            mode = "append"

        # All CKs have implementation in YAML -> Trigger Rendering
        try:
            import subprocess
            env_script = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "lang", "zh", "skills", "formal", "sva-gen",
                "scripts", "generate_formal_env.py"
            )
            env_script = os.path.normpath(env_script)
            if os.path.exists(env_script):
                result = subprocess.run(
                    ["python3", env_script, "--mode", mode],
                    capture_output=True, text=True,
                    env={**os.environ, "DUT": self.dut_name},
                    timeout=30,
                )

                if result.returncode == 0:
                    info(f"Successfully rendered checker/wrapper artifacts from YAML.")
                else:
                    return self._fail(f"Render failed: {result.stderr[:200]}")
            else:
                return self._fail(f"Render script not found at {env_script}")
        except Exception as e:
            return self._fail(f"Error during rendering: {e}")

        return self._pass(
            f"✅ All {ck_count} SVA properties implemented in YAML and rendered to SV files."
        )

    def get_template_data(self):
        return {}


# =============================================================================
# Script Generation Checker  (Stage 6)
# =============================================================================

class ScriptGenerationChecker(BaseFormalChecker):
    """Integrated checker for the script_generation stage."""
    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Validates the formal verification script (TCL)."""

        # --- Step 1: TCL keyword check ---
        info("📝 Step 1/2: Checking TCL script keywords...")
        tcl_path = self.paths.tcl
        if not os.path.exists(tcl_path):
            return self._fail(f"TCL script not found: {tcl_path}")

        with open(tcl_path, 'r', encoding='utf-8') as f:
            tcl_content = f.read()

        required_cmds = required_script_commands()
        missing = [k for k in required_cmds if k not in tcl_content]
        if missing:
            return self._fail(
                f"❌ Step 1/2 Failed: TCL script missing required commands: {missing}",
                details=f"Please add the missing commands to {tcl_path}",
            )
        info("✅ Step 1/2 Passed: TCL script keywords OK")

        # --- Step 2: Execute formal verification ---
        info("🚀 Step 2/2: Executing TCL script and validating...")
        res = run_formal_verification(tcl_path, timeout,
                                      on_start=lambda w: self.set_check_process(w, timeout),
                                      records_path=self.paths.records_yaml)

        if not res["success"]:
            err = res.get("error", "Unknown error")
            return self._fail(
                "❌ Step 2/2 Failed: FormalMC execution did not produce results",
                details=f"{err}\n{summarize_execution(res.get('stdout', ''), res.get('stderr', ''))}",
                suggestion="Please check the TCL script, checker.sv, and wrapper.sv for syntax errors",
            )

        # Blackbox check
        if res.get("blackbox_count", 0) > 0:
            return self._fail(
                f"Design contains {res['blackbox_count']} blackboxes which is not allowed for complete formal verification.",
                details="Please modify your formal TCL script to ensure all RTL files are correctly included.",
            )

        # Log result analysis
        parsed = res.get("parsed_log") or {}
        failed_count = len(parsed.get("false", [])) + len(parsed.get("cover_fail", []))
        if failed_count > 0:
            return self._pass(
                f"✅ Script generation checks passed. "
                f"Verification completed, but {failed_count} properties failed. "
                f"The next stage will involve analyzing these failures."
            )

        return self._pass("✅ Script generation checks passed. All properties passed.")



class EnvironmentAnalysisChecker(BaseFormalChecker):
    """Validates the environment analysis document against log results."""

    VALID_TT_ROOT_CAUSES = {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}
    VALID_TT_ACTIONS = {"FIXED", "ACCEPTED"}
    VALID_FA_RESOLUTIONS = {"RTL_BUG", "ENV_FIXED", "ENV_PENDING", "COVER_EXPECTED_FAIL"}

    def __init__(self, dut_name, accepted_ratio_threshold=50.0, **kwargs):
        super().__init__(dut_name, **kwargs)
        self.accepted_ratio_threshold = accepted_ratio_threshold

    # _extract_prop_code is replaced by extract_property_code() from formal_tools.


    # -------------------------------------------------------------------------
    # Validation sub-methods (extracted from do_check step 6)
    # -------------------------------------------------------------------------
    def _validate_completeness(self, tt_props, false_props, cover_fail, tt_entries, fa_entries):
        """Validate that every abnormal log property has a corresponding doc entry.

        Uses strip_prop_prefix() to normalize both sides before comparison,
        so 'A_CK_X', 'CK_X', and 'M_CK_X' all match the same core name.

        Returns a list of error strings (empty if all complete).
        """
        errors = []

        # Build normalized lookup: core_name -> original entry key
        tt_core = {strip_prop_prefix(k): k for k in tt_entries}
        fa_core = {strip_prop_prefix(k): k for k in fa_entries}

        # 6a: every TT prop must have a <TT-*> entry
        missing_tt = [p for p in tt_props if strip_prop_prefix(p) not in tt_core]
        if missing_tt:
            errors.append(
                f"❌ {len(missing_tt)} TRIVIALLY_TRUE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <TT-NNN> entry)" for p in missing_tt)
                + f"\n  Log properties (normalized): {[strip_prop_prefix(p) for p in tt_props]}"
                + f"\n  Doc entries (normalized):     {list(tt_core.keys())}"
            )

        # 6b: every FALSE prop must have a <FA-*> entry
        missing_fa = [p for p in (false_props + cover_fail) if strip_prop_prefix(p) not in fa_core]
        if missing_fa:
            errors.append(
                f"❌ {len(missing_fa)} FALSE properties missing analysis in document:\n"
                + "\n".join(f"  - {p} (needs a <FA-NNN> entry)" for p in missing_fa)
                + f"\n  Log properties (normalized): {[strip_prop_prefix(p) for p in (false_props + cover_fail)]}"
                + f"\n  Doc entries (normalized):     {list(fa_core.keys())}"
            )

        return errors

    @staticmethod
    def _is_unfilled(value: str) -> bool:
        """Check if a field value is an unfilled scaffold placeholder."""
        v = value.strip()
        return not v or v == "[LLM-TODO]" or v.startswith("[LLM-TODO")

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

        # 6d: Field completeness, [LLM-TODO] detection, and enum validity
        _TT_REQUIRED = ["root_cause", "action", "analysis"]
        _TT_LABELS = {"root_cause": "根因分类", "action": "修复动作", "analysis": "分析"}
        for prop, entry in tt_entries.items():
            for field_key in _TT_REQUIRED:
                val = entry.get(field_key, "")
                if val is None or self._is_unfilled(str(val)):
                    errors.append(
                        f"❌ <TT> entry '{prop}': field '{_TT_LABELS[field_key]}' "
                        f"is unfilled. Fill this in .formal_records.yaml → analysis.tt_entries."
                    )

            root_cause = entry.get("root_cause")
            action     = entry.get("action")
            if root_cause and not self._is_unfilled(str(root_cause)):
                if str(root_cause).upper() not in self.VALID_TT_ROOT_CAUSES:
                    warnings.append(
                        f"⚠️  <TT> entry '{prop}' has unknown root cause: '{root_cause}'."
                    )
            if action and not self._is_unfilled(str(action)):
                if str(action).upper() not in self.VALID_TT_ACTIONS:
                    errors.append(f"❌ <TT> entry '{prop}' has invalid action: '{action}'.")

        _FA_REQUIRED = ["resolution", "analysis"]
        _FA_LABELS = {"resolution": "解决状态", "analysis": "分析/反例"}
        for prop, entry in fa_entries.items():
            for field_key in _FA_REQUIRED:
                val = entry.get(field_key, "")
                if val is None or self._is_unfilled(str(val)):
                    errors.append(
                        f"❌ <FA> entry '{prop}': field '{_FA_LABELS[field_key]}' "
                        f"is unfilled. Fill this in .formal_records.yaml → analysis.fa_entries."
                    )

            resolution = entry.get("resolution")
            if resolution and not self._is_unfilled(str(resolution)):
                if str(resolution).upper() not in self.VALID_FA_RESOLUTIONS:
                    errors.append(f"❌ <FA> entry '{prop}' has invalid resolution: '{resolution}'.")

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
        """Validates the formal environment analysis report."""
        log_path = self.paths.log
        checker_path = self.paths.checker
        analysis_path = self.paths.analysis
        wrapper_path = self.paths.wrapper

        # Step 0: Ensure TCL is executed (updates records.run_results)
        exec_success, exec_result, was_rerun = self._ensure_tcl_executed(
            [checker_path, wrapper_path], self.paths.tcl, timeout
        )
        if not exec_success:
            return self._fail(**exec_result)

        # Step 1: Load records (which now contains proactive run_results)
        records_path = self.paths.records_yaml
        records = load_records(records_path)
        if not records or not records.run_results:
            return self._fail("❌ No run results found in .formal_records.yaml. Ensure TCL has been executed.")

        run_res = records.run_results
        tt_props = run_res.tt_properties
        all_fail = run_res.failing_properties
        # Distinguish between failing asserts and failing covers
        false_props = [p for p in all_fail if not (p.startswith("C_") or "COVER" in p.upper())]
        cover_fail = [p for p in all_fail if (p.startswith("C_") or "COVER" in p.upper())]
        
        # Reconstruct parsed log dict for downstream tools
        log_result_dict = {
            "pass": [], # We don't track passing ones explicitly in run_results for space
            "trivially_true": tt_props,
            "false": false_props,
            "cover_pass": [], 
            "cover_fail": cover_fail,
        }

        info(f"🔍 Analysis data loaded from YAML (Timestamp: {run_res.timestamp})")

        # --- Diagnostic output ---
        checker_content = FormalStageContext.get_or_create(self).get_checker_content(checker_path)
        if tt_props:
            info(f"⚠️  {len(tt_props)} TRIVIALLY_TRUE properties detected.")
        if all_fail:
            for prop in all_fail:
                code = extract_property_code(checker_content, prop)
                info(f"❌ FALSE: {prop}\n  SVA code:\n{code}")

        # Step 2: Convergence Check
        history = run_res.iteration_history
        conv_msg = ""
        if len(history) >= 2:
            prev, curr = history[-2], history[-1]
            prev_fail = prev.fail_count + prev.cover_fail
            curr_fail = curr.fail_count + curr.cover_fail
            prev_pass = prev.pass_count + prev.cover_pass
            curr_pass = curr.pass_count + curr.cover_pass
            
            if curr_pass < prev_pass:
                conv_msg += f"⚠️  REGRESSION: Pass count decreased ({prev_pass} → {curr_pass}).\n"
            if curr_fail > prev_fail:
                conv_msg += f"⚠️  DEGRADATION: Fail count increased ({prev_fail} → {curr_fail}).\n"
            if curr_fail >= prev_fail and len(history) >= 3:
                # Basic stagnation check
                p2_fail = history[-3].fail_count + history[-3].cover_fail
                if p2_fail <= prev_fail:
                    conv_msg += "⚠️  STAGNATION: Fail count has not decreased for 3 iterations.\n"

        # --- Auto Scaffolding: YAML analysis entries ---
        # Note: raw log_result converted back to dict for the helper if needed, 
        # or update helper to accept RunResults.
        log_result_dict = {
            "trivially_true": tt_props,
            "false": false_props,
            "cover_fail": cover_fail
        }
        if auto_scaffold_analysis_entries(records, log_result_dict, checker_content):
            save_records(records_path, records)
            info("🏗️ Automatically scaffolded [LLM-TODO] entries in .formal_records.yaml")

        # Step 4-5: Load entries for validation
        json_has_analysis = False
        tt_entries = {}
        fa_entries = {}
        
        if records.analysis:
            json_has_analysis = True
            tt_entries = {e.prop_name: e.model_dump() for e in records.analysis.tt_entries}
            fa_entries = {e.prop_name: e.model_dump() for e in records.analysis.fa_entries}

        if not json_has_analysis:
            summary_lines = [
                f"📊 Log Summary: {run_res.stats.get('pass_count')} pass, {run_res.stats.get('tt_count')} TT, "
                f"{run_res.stats.get('fail_count')} assert fail, {run_res.stats.get('cover_fail_count')} cover fail",
            ]
            if conv_msg: summary_lines.append(f"\n{conv_msg}")

            return False, {
                "error": "❌ Environment analysis not found in .formal_records.yaml",
                "details": f"Run sva-audit to fill analysis entries.",
                "log_summary": "\n".join(summary_lines),
                "iteration": len(history),
            }


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
                "assert_pass": run_res.stats.get("pass_count", 0),
                "assert_trivially_true": len(tt_props),
                "assert_fail": len(false_props),
                "cover_pass": run_res.stats.get("cover_pass_count", 0),
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

        # All checks passed — auto-regenerate markdown from YAML
        try:
            from ucagent.lang.zh.skills.formal.lib.formal_tools import generate_env_analysis_doc
            generate_env_analysis_doc(records, log_result_dict, self.paths.analysis)
            info(f"Auto-regenerated analysis doc: {self.paths.analysis}")
        except Exception as e:
            info(f"Warning: Could not regenerate analysis doc: {e}")

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

class CoverageAnalysisChecker(BaseFormalChecker):
    """Coverage analysis checker for the coverage_analysis_and_optimization stage."""

    def __init__(self, dut_name, **kwargs):
        super().__init__(dut_name, **kwargs)
        self.coi_threshold = float(kwargs.get("coi_threshold", 100.0))

    def do_check(self, timeout=300, **kwargs) -> tuple[bool, object]:
        """Validates formal verification COI coverage."""


        checker_path = self.paths.checker
        fanin_path = coverage_report_path(self.paths.tests)

        # Step 1: Ensure TCL is executed if dependency files changed
        exec_success, exec_result, was_rerun = self._ensure_tcl_executed(
            [checker_path], self.paths.tcl, timeout
        )
        if not exec_success:
            exec_result["suggestion"] = "Please check checker.sv and wrapper.sv for syntax errors"
            return self._fail(err=exec_result.get("error", ""), details=exec_result.get("details", ""), suggestion=exec_result.get("suggestion", ""))

        # Step 2: Parse coverage via adapter
        info(f"🔍 Parsing COI coverage report...")
        coi = parse_coverage(self.paths.tests)

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
                f"  → Check the 'FormalMC' output to find which logic is not influenced by assertions.\n"
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
                rtl_bugs = ctx.get_rtl_bug_properties(self.paths.analysis)
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
                checker_path = self.paths.checker
                if os.path.exists(checker_path):
                    ctx = FormalStageContext.get_or_create(self)
                    checker_content = ctx.get_checker_content(checker_path)
                    n_assert = len(re.findall(r'\bassert\s+property\b', checker_content))
                    n_cover  = len(re.findall(r'\bcover\s+property\b', checker_content))
                    n_assume = len(re.findall(r'\bassume\s+property\b', checker_content))
                    report["property_counts"] = {
                        "assert": n_assert, "cover": n_cover, "assume": n_assume
                    }
                    # Check if uncovered signals only appear in cover but not assert
                    if uncovered:
                        issues.extend(analyze_signal_coverage_usage(checker_content, uncovered))
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

class CounterexampleTestgenChecker(BaseFormalChecker):
    """Validates generated Python counterexample test cases."""

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates that counterexample test cases are correctly generated."""
        analysis_path = self.paths.analysis
        test_path = self.paths.test_file

        # Step 1: Extract RTL bugs from analysis document
        ctx = FormalStageContext.get_or_create(self)
        rtl_bugs = ctx.get_rtl_bug_properties(analysis_path)
        info(f"Found {len(rtl_bugs)} RTL_BUG properties from analysis document")

        # --- Auto Scaffolding: Counterexample test file ---
        if rtl_bugs and not os.path.exists(test_path):
            try:
                import subprocess
                cex_script = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..", "lang", "zh", "skills", "formal", "cex-gen",
                    "scripts", "init_test_file.py"
                )
                cex_script = os.path.normpath(cex_script)
                if os.path.exists(cex_script):
                    result = subprocess.run(
                        ["python3", cex_script],
                        capture_output=True, text=True,
                        env={**os.environ, "DUT": self.dut_name},
                        timeout=30,
                    )
                    if result.returncode == 0:
                        info(f"🏗️ Automatically scaffolded counterexample test file: {test_path}")
                    else:
                        info(f"Warning: cex-gen init script returned {result.returncode}: {result.stderr[:200]}")
            except Exception as e:
                warning(f"Failed to auto-scaffold counterexample test file: {e}")

        # Step 2: Check test file existence
        if not os.path.exists(test_path):
            if not rtl_bugs:
                return self._fail(
                    "❌ Test file does not exist",
                    details=(
                        f"Please create '{self.paths.test_file}'. "
                        "Since no RTL_BUG properties were found, "
                        "the file should contain a comment: "
                        "'# 形式化验证未发现 RTL 缺陷，无需生成反例测试用例'"
                    ),
                )
            return self._fail(
                "❌ Test file does not exist",
                details=(
                    f"Please create '{self.paths.test_file}' with test functions "
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
        impl_functions = extract_python_test_functions(test_path)
        if not impl_functions:
            return self._fail(
                f"❌ No test_cex_* functions found in {self.paths.test_file}",
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
            # Normalize: A_CK_XXX -> ck_xxx (strip prefix then lowercase)
            normalized = strip_prop_prefix(bug_prop).lower()

            # Exact matching: test function name must end with the normalized property name
            # e.g., test_cex_ck_core_arith_result should match ck_core_arith_result
            found = False
            for func_name in impl_functions:
                func_suffix = func_name.lower().removeprefix('test_cex_')
                if func_suffix == normalized or func_name.lower().endswith('_' + normalized):
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

class BugReportConsistencyChecker(BaseFormalChecker):
    """Bug report consistency checker for the formal_execution stage."""

    def __init__(self, dut_name, **kwargs):
        super().__init__(dut_name, **kwargs)

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates the consistency of the formal verification bug report."""

        records_path = self.paths.records_yaml
        if not os.path.exists(records_path):
            return self._fail(
                "❌ .formal_records.yaml not found",
                suggestion="Run previous stages to create .formal_records.yaml.",
            )

        records = load_records(records_path)
        if not records:
            return self._fail(f"❌ .formal_records.yaml not found at {records_path}")

        # --- Auto Scaffolding: YAML bug entries ---
        try:
            if auto_scaffold_bug_entries(records):
                save_records(records_path, records)
                info("🏗️ Automatically scaffolded [LLM-TODO] bug entries in .formal_records.yaml")
        except Exception as e:
            warning(f"Failed to auto-scaffold bug entries: {e}")

        # Step 1: Extract RTL defects from analysis
        if not records or not records.analysis:
            return self._fail("❌ No analysis in .formal_records.yaml. Run sva-audit first.")

        if not isinstance(records.analysis, dict):
            fa_list = records.analysis.fa_entries
            rtl_defects = [e.prop_name for e in fa_list if e.resolution and e.resolution.upper() == "RTL_BUG"]
        else:
            fa_list = records.analysis.get("fa_entries", [])
            rtl_defects = [e["prop_name"] for e in fa_list if e.get("resolution", "").upper() == "RTL_BUG"]
            
        info(f"Extracted {len(rtl_defects)} RTL_BUG properties")

        if not rtl_defects:
            return True, {
                "message": "✅ No RTL defects to report",
                "note": "No properties judged as RTL_BUG",
            }

        # Step 2: Extract reported bugs
        if not records.bugs:
            return self._fail(
                "❌ No bugs field in .formal_records.yaml",
                details=f"Run bug-report to fill bugs for: {', '.join(rtl_defects)}",
            )

        reported_props = [b.property for b in records.bugs]

        # Step 3: Compare using normalized names
        defect_core = {strip_prop_prefix(d): d for d in rtl_defects}
        report_core = {strip_prop_prefix(r): r for r in reported_props}

        missing = [defect_core[k] for k in defect_core if k not in report_core]
        extra = [report_core[k] for k in report_core if k not in defect_core]

        if missing or extra:
            issues = []
            if missing:
                issues.append(f"Missing reports ({len(missing)}): {', '.join(missing)}")
            if extra:
                issues.append(f"Extra reports ({len(extra)}): {', '.join(extra)}")
            return self._fail("❌ Bug report inconsistent", details="\n".join(issues))

        # Step 4: Check for unfilled [LLM-TODO] fields in bugs
        _BUG_REQUIRED = ["description", "root_cause", "trigger", "expected", "actual", "fix", "severity", "confidence"]
        unfilled_errors = []
        for bug in records.bugs:
            bug_id = bug.id
            bug_dict = bug.model_dump()
            for field_key in _BUG_REQUIRED:
                val = str(bug_dict.get(field_key, "")).strip()
                if not val or val == "[LLM-TODO]" or val.startswith("[LLM-TODO"):
                    unfilled_errors.append(
                        f"❌ Bug '{bug_id}' ({bug.property}): "
                        f"field '{field_key}' is unfilled (value: '{val}'). "
                        f"Fill this field in .formal_records.yaml → bugs."
                    )
        if unfilled_errors:
            return self._fail(
                f"❌ Bug report has {len(unfilled_errors)} unfilled fields",
                details="\n".join(unfilled_errors),
            )

        # Step 5: Auto-regenerate markdown from JSON on pass
        try:
            from ucagent.lang.zh.skills.formal.lib.formal_tools import generate_bug_report_doc
            generate_bug_report_doc(records, self.paths.bug_report)
            info(f"Auto-regenerated bug report: {self.paths.bug_report}")
        except Exception as e:
            info(f"Warning: Could not regenerate bug report: {e}")

        return True, {
            "message": f"✅ Bug report check passed: {len(rtl_defects)} RTL defects reported",
            "rtl_defects": rtl_defects,
        }



# =============================================================================
# Static Bug - Formal Bug Linkage Checker
# =============================================================================

class StaticFormalBugLinkageChecker(BaseFormalChecker):
    """Static Bug and Formal Verification Linkage Checker."""

    def __init__(self, dut_name, **kwargs):
        super().__init__(dut_name, **kwargs)

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validates the linkage between static bugs and formal verification results."""


        static_path = self.paths.static_doc
        bug_report_path = self.paths.bug_report
        log_path = self.paths.log

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
            return self._fail(
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

