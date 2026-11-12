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

from ucagent.core.checkers.base import Checker
from ucagent.util.log import info, warning


# Shared utilities – single source of truth
from formal.execution import FormalExecution
from formal.skills.lib.formal_paths import FormalPaths
from formal.skills.lib.models import normalize_summary, normalize_author_section, missing_author_fields
from formal.skills.lib.formal_tools import (
    parse_avis_log,
    typed_run_results,
    validate_analysis_evidence,
    refresh_analysis_references,
    bug_root_groups,
    extract_property_code,
    strip_prop_prefix,
    extract_property_details,
    extract_rtl_bug_from_analysis_doc,
    extract_static_bugs,
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
    generate_planning_doc,
    generate_basic_info_doc,
    generate_summary_doc,
    get_primary_clock_reset,
    validate_extra_config_against_design,
)

class BaseFormalChecker(Checker):
    """Base class for formal verification checkers."""
    def __init__(self, dut_name, cfg=None, **kwargs):
        """Store the resolved configuration supplied by stage construction."""
        super().__init__()
        self.cfg = cfg
        self.dut_name = dut_name
        self.paths = None

    def _resolve_paths(self):
        """Honor the final CLI/workflow OUT template value rather than process environment."""
        values = self.cfg._temp_cfg if self.cfg.has_attr("_temp_cfg") else {}
        if hasattr(values, "as_dict"):
            values = values.as_dict()
        output = values.get("OUT") or self.cfg.get_value("output", None) or "output"
        return FormalPaths(dut=self.dut_name, out=output, workspace=self.workspace)

    def on_init(self):
        """Resolve the active output directory from the assembled workflow config."""
        self.paths = self._resolve_paths()
        return super().on_init()

    def _execution(self) -> FormalExecution:
        """Read the current Formal execution evidence using resolved config."""
        if not getattr(self, "workspace", None) or not getattr(self, "cfg", None):
            raise ValueError("Formal checker requires initialized workspace and configuration")
        if self.paths is None or self.paths.workspace != self.workspace:
            self.paths = self._resolve_paths()
        return FormalExecution(
            workspace=self.workspace,
            output_dir=self.paths.out,
            dut=self.dut_name,
            cfg=self.cfg,
            write_dirs=self.cfg.get_value("write_dirs", None),
            un_write_dirs=self.cfg.get_value("un_write_dirs", None),
        )

    def _pass(self, msg: str) -> tuple[bool, str]:
        return True, msg

    def _fail(self, err: str, details: str = "", suggestion: str = "") -> tuple[bool, dict]:
        return False, {"error": err, "details": details, "suggestion": suggestion}

    def _check_author_section(self, section, value):
        """Return the complete author checklist rather than leaking render-time exceptions."""
        action = f"Fill the {section} author fields in {self.paths.records_yaml} using ordinary file tools or the optional ext/formal/data Skill, then call Complete. See Guide_Doc/formal_data.md for the shared contract."
        try:
            normalized = normalize_author_section(section, value)
            missing = missing_author_fields(section, normalized)
        except ValueError as exc:
            return None, {"error_code": "formal_author_section_invalid", "error": str(exc)[:2000],
                          "artifact": self.paths.records_yaml, "section": section, "next_action": action}
        if missing:
            return None, {"error_code": "formal_author_fields_missing", "error": f"Required author fields are incomplete in {section}.",
                          "artifact": self.paths.records_yaml, "section": section,
                          "missing_fields": missing[:40], "missing_total": len(missing), "next_action": action}
        return normalized, None

    def _require_execution(self) -> tuple[bool, dict]:
        """Require current-input proof evidence without launching a proof from Check."""
        passed, result = self._execution().check()
        if not passed:
            return False, {
                "error_code": "formal_execution_pending",
                "error": "Formal proof batch is not ready for analysis",
                "details": result,
                "next_action": (
                    "Call RunFormal(action='run'), then RunFormal(action='status'). "
                    "For unresolved properties call RunFormal(action='review', "
                    "property_names=[...], disposition='defer' or 'retry', "
                    "reason='...', next_action='...')."
                ),
            }
        return True, result


class PlanningStructureChecker(BaseFormalChecker):
    """Validates YAML-backed planning data and renders the planning doc."""

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validate planning fields in .formal_records.yaml and render the planning markdown."""
        records = load_records(self.paths.records_yaml)
        planning, diagnostic = self._check_author_section("planning", records.planning if records else None)
        if diagnostic:
            return False, diagnostic
        records.planning = planning
        try:
            generate_planning_doc(records, self.paths.planning)
        except ValueError as exc:
            return False, {"error_code": "formal_report_render_failed", "error": str(exc)[:2000],
                           "artifact": self.paths.planning,
                           "next_action": "Review planning in the task records using ordinary file tools or the optional data Skill; correct the named fields before Complete."}
        info(f"Auto-generated planning doc: {self.paths.planning}")
        return self._pass("✅ Planning section is complete and rendered.")


class BasicInfoStructureChecker(BaseFormalChecker):
    """Validates YAML-backed basic info data and renders the basic info doc."""

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validate basic_info fields in .formal_records.yaml and render the basic info markdown."""
        records = load_records(self.paths.records_yaml)
        basic_info, diagnostic = self._check_author_section("basic_info", records.basic_info if records else None)
        if diagnostic:
            return False, diagnostic
        records.basic_info = basic_info
        try:
            generate_basic_info_doc(records, self.paths.basic_info)
        except ValueError as exc:
            return False, {"error_code": "formal_report_render_failed", "error": str(exc)[:2000],
                           "artifact": self.paths.basic_info,
                           "next_action": "Review basic_info in the task records using ordinary file tools or the optional data Skill; correct the named fields before Complete."}
        info(f"Auto-generated basic info doc: {self.paths.basic_info}")
        return self._pass("✅ Basic info section is complete and rendered.")


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
        fc_ids = set()
        ck_ids = set()
        fc_count = 0
        ck_count = 0

        for fg in groups:
            fg_id = fg.id
            if not fg_id:
                errors.append("A function group is missing 'id' field.")
                continue
            if fg_id in fg_ids:
                errors.append(f"Duplicate function group ID: {fg_id}")
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
                if fc_id in fc_ids:
                    errors.append(f"Duplicate function point ID: {fc_id}")
                fc_ids.add(fc_id)
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
                        if ck_id in ck_ids:
                            errors.append(f"Duplicate check point ID: {ck_id}")
                        ck_ids.add(ck_id)
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

        self._counts = {"fg": len(fg_ids), "fc": fc_count, "ck": ck_count}

        if errors:
            return self._fail(
                f"❌ Spec structure validation failed ({len(errors)} issues)",
                details="\n".join(f"  - {e}" for e in errors),
            )

        # Auto-generate Spec Markdown doc only at ck level (final sub-stage)
        if self._check_level == "ck":
            try:
                from formal.skills.lib.formal_tools import generate_spec_doc
                generate_spec_doc(records, self.paths.spec)
                info(f"Auto-generated spec doc: {self.paths.spec}")
            except Exception as exc:
                return self._fail("Specification report generation failed", details=str(exc), suggestion="Repair the report inputs and call Check again.")

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
                    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", ck.sva_body or "", flags=re.DOTALL).strip()
                    expression = body.rstrip(";").strip()
                    while expression.startswith("(") and expression.endswith(")"):
                        depth = 0
                        outer = True
                        for index, char in enumerate(expression):
                            depth += (char == "(") - (char == ")")
                            if depth == 0 and index < len(expression) - 1:
                                outer = False
                                break
                        if not outer:
                            break
                        expression = expression[1:-1].strip()
                    literal = re.fullmatch(r"(?:(\d+)?'[sS]?([bBdDhH])([0-9a-fA-F_]+)|(\d+))", expression)
                    constant_true = expression.lower() in {"true", "'1"}
                    if literal:
                        base = {"b": 2, "d": 10, "h": 16}.get((literal.group(2) or "d").lower())
                        try:
                            value = int((literal.group(3) or literal.group(4)).replace("_", ""), base)
                            if literal.group(1):
                                value &= (1 << int(literal.group(1))) - 1
                            constant_true = value != 0
                        except ValueError:
                            constant_true = False
                    no_op = re.search(r"\|(?:->|=>)\s*\(*\s*(?:1|true|1'[bBdDhH]1)\s*\)*$", expression, re.IGNORECASE)
                    if not expression or re.search(r"\[LLM-TODO\]|\bTODO\b", expression) or constant_true or no_op:
                        errors.append(f"Missing or constant-true placeholder SVA body for '{ck.id}'")
                        continue
                    if ck.style.lower() == "comb":
                        # Same-cycle boolean |-> is accepted; delayed sequences are not.
                        temporal = any(token in body for token in self._TEMPORAL_OPS)
                        if temporal or re.search(r"@|\[\s*(?:\*|=|->)", body):
                            errors.append(f"Comb property '{ck.id}' uses a clock, sampled history, or delayed sequence; use a current-state boolean expression or same-cycle boolean implication.")
                            continue
                    implemented_count += 1


        if errors:
            return self._fail(
                f"❌ SVA Implementation incomplete ({implemented_count}/{ck_count} implemented)",
                details="\n".join(f"  - {e}" for e in errors),
                suggestion="Use 'update_sva_body.py' skill to fill 'sva_body' for each checkpoint in YAML."
            )

        # All CKs have implementation in YAML -> Trigger Rendering
        try:
            from formal.tools import render_environment
            render_environment(
                self.workspace, self.paths.out, self.dut_name,
                write_dirs=self.cfg.get_value("write_dirs", None),
                un_write_dirs=self.cfg.get_value("un_write_dirs", None),
            )
        except Exception as exc:
            return self._fail(
                "Formal environment generation failed",
                details=str(exc),
                suggestion="Correct .formal_records.yaml and run Check again.",
            )

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
        records = load_records(self.paths.records_yaml)
        if not records:
            return self._fail("❌ .formal_records.yaml not found", suggestion="Run previous stages first.")

        clock_cfg, reset_cfg = get_primary_clock_reset(records)
        mismatches = validate_extra_config_against_design(records)
        if mismatches:
            return self._fail(
                "❌ basic_info.clock_reset does not match DUT interface description",
                details="\n".join(f"  - {item}" for item in mismatches),
                suggestion="Update .formal_records.yaml.basic_info.clock_reset and related input port signal_type fields before rendering formal.tcl and wrapper.",
            )

        try:
            from formal.tools import render_environment
            render_environment(
                self.workspace, self.paths.out, self.dut_name,
                write_dirs=self.cfg.get_value("write_dirs", None),
                un_write_dirs=self.cfg.get_value("un_write_dirs", None),
            )
        except Exception as exc:
            return self._fail(
                "Formal environment could not be rendered from current records",
                details=str(exc),
                suggestion="Correct .formal_records.yaml, then call RunFormal(action='run').",
            )

        # --- Step 1: TCL keyword check ---
        info("📝 Step 1/2: Checking TCL script keywords...")
        tcl_path = self.paths.tcl
        if not os.path.exists(tcl_path):
            return self._fail(f"TCL script not found: {tcl_path}")

        with open(tcl_path, 'r', encoding='utf-8') as f:
            tcl_content = f.read()

        required_cmds = ["read_design", "prove"]
        if clock_cfg.get("signal"):
            required_cmds.append("def_clk")
        if reset_cfg.get("signal"):
            required_cmds.append("def_rst")
        missing = [k for k in required_cmds if k not in tcl_content]
        if missing:
            return self._fail(
                f"❌ Step 1/2 Failed: TCL script missing required commands: {missing}",
                details=f"Please add the missing commands to {tcl_path}",
            )
        info("✅ Step 1/2 Passed: TCL script keywords OK")

        # An explicit RunFormal run owns proof execution and its auditable results.
        passed, evidence = self._execution().check()
        if not passed:
            return False, {
                "error": "Formal script is valid, but current-input proof evidence is incomplete",
                "diagnostic": evidence,
                "next_action": (
                    "Call RunFormal(action='run'), inspect RunFormal(action='status'), "
                    "and review unresolved properties before Complete."
                ),
            }
        if evidence.get("proof_complete") is False:
            return True, {
                "message": "Formal proof batch is reviewed, but deferred properties remain UNPROVEN.",
                "proof_complete": False,
                "evidence": evidence,
            }
        return True, {
            "message": "Formal script and current-input proof batch are verified.",
            "proof_complete": evidence.get("proof_complete"),
            "evidence": evidence,
        }



class EnvironmentAnalysisChecker(BaseFormalChecker):
    """Validates the environment analysis document against log results."""

    VALID_TT_ROOT_CAUSES = {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}
    VALID_TT_ACTIONS = {"FIXED", "ACCEPTED"}
    VALID_FA_RESOLUTIONS = {"RTL_BUG", "ENV_FIXED", "ENV_PENDING", "COVER_EXPECTED_FAIL"}

    def __init__(self, dut_name, accepted_ratio_threshold=100.0, **kwargs):
        super().__init__(dut_name, **kwargs)
        self.accepted_ratio_threshold = accepted_ratio_threshold

    # _extract_prop_code is replaced by extract_property_code() from formal_tools.


    # -------------------------------------------------------------------------
    # Validation sub-methods (extracted from do_check step 6)
    # -------------------------------------------------------------------------
    def _validate_completeness(self, tt_props, false_props, cover_fail, tt_entries, fa_entries):
        """Require exact current machine identities with no stale or aliased entries."""
        errors = []
        for kind, expected, observed in (("TT", set(tt_props), set(tt_entries)),
                                         ("FA", set(false_props + cover_fail), set(fa_entries))):
            missing, extra = expected - observed, observed - expected
            if missing:
                errors.append(f"{kind} analysis missing exact property IDs: {sorted(missing)}")
            if extra:
                errors.append(f"{kind} analysis contains unknown property IDs: {sorted(extra)}")
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
                    f"  Review current tool reasons and evidence, or adjust the configured acceptance threshold when the proof is legitimate."
                )

        # 6d: Field completeness, [LLM-TODO] detection, and enum validity
        _TT_REQUIRED = ["root_cause", "action", "analysis"]
        for prop, entry in tt_entries.items():
            for field_key in _TT_REQUIRED:
                val = entry.get(field_key, "")
                if val is None or self._is_unfilled(str(val)):
                    errors.append(
                        f"❌ <TT> entry '{prop}': field '{field_key}' "
                        f"is unfilled. Fill this in .formal_records.yaml → analysis.tt_entries."
                    )

            root_cause = entry.get("root_cause")
            action     = entry.get("action")
            if str(action or "").upper() == "FIXED":
                errors.append(f"TT property {prop} is still present in current machine results; FIXED requires corrected inputs and a new run where it is no longer abnormal.")
            if str(action or "").upper() == "ACCEPTED" and str(root_cause or "").upper() != "DESIGN_EXPECTED":
                errors.append(f"TT property {prop} can be ACCEPTED only with DESIGN_EXPECTED and current tool evidence; otherwise repair the environment and rerun.")
            if root_cause and not self._is_unfilled(str(root_cause)):
                if str(root_cause) not in self.VALID_TT_ROOT_CAUSES:
                    errors.append(f"TT property {prop} has invalid root_cause: {root_cause}")
            if action and not self._is_unfilled(str(action)):
                if str(action) not in self.VALID_TT_ACTIONS:
                    errors.append(f"❌ <TT> entry '{prop}' has invalid action: '{action}'.")

        _FA_REQUIRED = ["resolution", "analysis"]
        for prop, entry in fa_entries.items():
            for field_key in _FA_REQUIRED:
                val = entry.get(field_key, "")
                if val is None or self._is_unfilled(str(val)):
                    errors.append(
                        f"❌ <FA> entry '{prop}': field '{field_key}' "
                        f"is unfilled. Fill this in .formal_records.yaml → analysis.fa_entries."
                    )

            resolution = entry.get("resolution")
            if str(resolution or "").upper() == "ENV_FIXED":
                errors.append(f"Failed property {prop} is still present in current machine results; ENV_FIXED requires a new run after repairing its inputs.")
            if str(resolution or "").upper() == "COVER_EXPECTED_FAIL" and entry.get("prop_type") != "cover":
                errors.append(f"Property {prop} is not a typed cover; COVER_EXPECTED_FAIL cannot classify an assertion failure.")
            if str(resolution or "").upper() == "RTL_BUG" and entry.get("prop_type") != "assert":
                errors.append(f"Property {prop} is not a typed assertion; RTL_BUG cannot classify a cover result.")
            if resolution and not self._is_unfilled(str(resolution)):
                if str(resolution) not in self.VALID_FA_RESOLUTIONS:
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
                f"then update the 'resolution' field to 'ENV_FIXED'."
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
        exec_success, exec_result = self._require_execution()
        if not exec_success:
            return False, exec_result

        # Step 1: Load records (which now contains proactive run_results)
        records_path = self.paths.records_yaml
        records = load_records(records_path)
        if not records or not records.run_results:
            return self._fail("❌ No run results found in .formal_records.yaml. Ensure TCL has been executed.")

        run_res = records.run_results
        tt_props = run_res.tt_properties
        all_fail = run_res.failing_properties
        if run_res.assert_failing_properties is None or run_res.cover_failing_properties is None:
            return self._fail(
                "Current Formal evidence has no assertion/cover classification",
                suggestion="RunFormal(action='run') must produce typed current-input results before analysis.",
            )
        false_props = run_res.assert_failing_properties
        cover_fail = run_res.cover_failing_properties
        
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
        try:
            if auto_scaffold_analysis_entries(records, typed_run_results(records), checker_content):
                save_records(records_path, records)
                info("Current machine analysis queue synchronized")
        except ValueError as exc:
            return False, {"error_code": "formal_analysis_identity_invalid", "error": str(exc),
                           "next_action": "Use exact current property IDs from RunFormal; remove duplicate or unknown analysis entries without renaming machine identities."}

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


        try:
            if refresh_analysis_references(records):
                save_records(records_path, records)
            validate_analysis_evidence(records)
        except ValueError as exc:
            return False, {"error_code": "formal_analysis_evidence_invalid", "error": str(exc),
                           "next_action": "Call RunFormal action=evidence for each RTL_BUG property; use the returned current evidence_ref and verify its inputs and outputs."}

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
            from formal.skills.lib.formal_tools import generate_env_analysis_doc
            generate_env_analysis_doc(records, log_result_dict, self.paths.analysis)
            info(f"Auto-regenerated analysis doc: {self.paths.analysis}")
        except Exception as exc:
            return self._fail("Environment analysis report generation failed", details=str(exc), suggestion="Repair the report input and call Check again.")

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
        exec_success, exec_result = self._require_execution()
        if not exec_success:
            return False, exec_result
        if not exec_result.get("coverage_artifact"):
            return False, {
                "error_code": "formal_coverage_missing",
                "error": "Current proof run did not produce a COI coverage report.",
                "observed": {"run_id": exec_result.get("run_id"), "coverage_artifact": None},
                "next_action": "Inspect RunFormal(action='status') report and rerun after fixing coverage generation.",
            }

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
                        "the file should contain a comment explaining that no RTL defects "
                        "were found and no counterexample tests are required."
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

        # Step 3: No RTL bugs case
        if not rtl_bugs:
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
            normalized = re.sub(r"[^a-z0-9_]", "_", bug_prop.lower())

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

        evidence_ok, evidence = self._execution().check()
        if not evidence_ok:
            return False, {"error_code": "formal_bug_evidence_pending", "error": "Bug reporting requires current completed machine evidence.",
                           "next_action": "Call RunFormal and complete current-input review before writing Bug conclusions.", "diagnostic": evidence}

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
        except Exception as exc:
            return self._fail("Bug identities are invalid", details=str(exc), suggestion="Use exact machine property identities and current analysis.")

        try:
            validate_analysis_evidence(records)
        except ValueError as exc:
            return self._fail("Bug analysis evidence is invalid", details=str(exc), suggestion="Review current machine evidence before writing Bug conclusions.")

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

        # Full machine identities are authoritative, including repeated leaf labels.
        if len(reported_props) != len(set(reported_props)) or len({bug.id for bug in records.bugs}) != len(records.bugs):
            return self._fail("Duplicate Bug property or ID", suggestion="Keep one entry per exact machine property ID.")
        missing = sorted(set(rtl_defects) - set(reported_props))
        extra = sorted(set(reported_props) - set(rtl_defects))
        if missing or extra:
            issues = []
            if missing:
                issues.append(f"Missing reports ({len(missing)}): {', '.join(missing)}")
            if extra:
                issues.append(f"Extra reports ({len(extra)}): {', '.join(extra)}")
            return self._fail("❌ Bug report inconsistent", details="\n".join(issues))

        # Step 4: Check for unfilled [LLM-TODO] fields in bugs
        _BUG_REQUIRED = ["description", "root_cause", "trigger", "expected_requirement", "expected", "actual", "fix", "severity", "confidence"]
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

        try:
            roots = bug_root_groups(records)
        except ValueError as exc:
            return self._fail("Shared root-cause contract is invalid", details=str(exc), suggestion="Assign explicit root_cause_id values; properties sharing one root must use the same root_cause, fix, and severity.")

        # Step 5: Auto-regenerate markdown from JSON on pass
        try:
            from formal.skills.lib.formal_tools import generate_bug_report_doc
            generate_bug_report_doc(records, self.paths.bug_report)
            info(f"Auto-regenerated bug report: {self.paths.bug_report}")
        except Exception as exc:
            return self._fail("Bug report generation failed", details=str(exc), suggestion="Repair report fields and call Check again.")

        return True, {
            "message": "Bug report observations and explicit shared root causes are validated.",
            "property_count": len(rtl_defects),
            "root_cause_count": len(roots),
            "rtl_defects": rtl_defects,
        }


class FormalSummaryChecker(BaseFormalChecker):
    """Validates YAML-backed summary data and renders final summary markdown."""

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """Validate summary against current machine proof evidence and render it."""
        evidence_ok, proof = self._execution().check()
        if not evidence_ok:
            return False, {
                "error": "Summary needs current completed Formal proof evidence",
                "diagnostic": proof,
                "next_action": "Call RunFormal(action='run'), then review every unresolved property.",
            }
        records = load_records(self.paths.records_yaml)
        summary, diagnostic = self._check_author_section("summary", records.summary if records else None)
        if diagnostic:
            return False, diagnostic
        records.summary = summary
        errors = []
        if proof.get("proof_complete") is False:
            gap_text = f"{summary.get('overall_result', '')} {summary.get('acceptance_conclusion', '')}".upper()
            if "UNPROVEN" not in gap_text:
                errors.append("Deferred properties remain UNPROVEN; overall_result or acceptance_conclusion must disclose the validation gap")

        if errors:
            return self._fail(
                f"❌ summary validation failed ({len(errors)} issues)",
                details="\n".join(f"  - {e}" for e in errors),
            )

        coverage = parse_coverage(self.paths.tests)
        try:
            generate_summary_doc(records, self.paths.summary, coverage=coverage, machine=proof)
        except Exception as exc:
            return False, {"error_code": "formal_summary_delivery_invalid", "error": str(exc)[:2000],
                           "artifact": self.paths.summary,
                           "next_action": "Review summary and Bug records using ordinary file tools or the optional data Skill. Complete current verified Bug observations and correct the named author fields, then Complete; do not submit derived severe_bugs rows."}
        dashboard = None
        try:
            from formal.dashboard import FormalDashboard
            from ucagent.util.file_policy import is_file_writeable

            relative = f"{self.paths.out}/formal_view.json"
            allowed, _ = is_file_writeable(relative, self.cfg.get_value("un_write_dirs", None),
                                            self.cfg.get_value("write_dirs", None))
            if allowed:
                dashboard = FormalDashboard(self.paths.workspace, archived=True, cfg=self.cfg,
                                            output=self.paths.out).export()
        except (ValueError, OSError) as exc:
            warning(f"Formal summary was validated; dashboard export failed: {exc}")
        info(f"Auto-generated summary doc: {self.paths.summary}")
        return True, {
            "message": "Summary section rendered with current machine proof status.",
            "proof_complete": proof.get("proof_complete"),
            "deferred_total": proof.get("deferred_total", 0),
            "evidence_report": proof.get("report"),
            "dashboard": dashboard,
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
        dispositions = extract_static_bugs(static_path)
        issues = [f"{candidate}: choose a disposition" for candidate, _ in dispositions["pending"]]
        if dispositions["confirmed"] or dispositions["ruled_out"]:
            execution = self._execution()
            evidence_ok, proof = execution.check()
            if not evidence_ok:
                return False, {"error_code": "formal_static_linkage_evidence", "diagnostic": proof}
            from formal.execution import read_run
            from formal.skills.lib.formal_tools import summary_bug_rows
            _, _, root = execution._paths(create=False)
            _, run = read_run(root, proof["run_id"])
            records = load_records(self.paths.records_yaml)
            accepted = {row["bug_id"] for row in summary_bug_rows(records)} if dispositions["confirmed"] else set()
            for candidate, targets in dispositions["confirmed"]:
                if not set(targets).issubset(accepted):
                    issues.append(f"{candidate}: confirmation must cite exact current verified Bug IDs")
            for candidate, evidence in dispositions["ruled_out"]:
                item = run["properties"].get(evidence[0]) if evidence else None
                if not item or item["result"] != "PROVEN" or item["kind"] != "assert":
                    issues.append(f"{candidate}: use Evidence: `<full property>` — <reason> with a current proved assertion")
        if issues:
            return False, {"error_code": "formal_static_linkage_invalid", "issues": issues[:32]}
        return True, {
            "message": "Static candidate dispositions were validated.",
            "statistics": {key: len(dispositions[key]) for key in ("confirmed", "ruled_out", "unverified")},
            "candidates": {key: dispositions[key] for key in ("confirmed", "ruled_out", "unverified")},
            "static_doc": static_path,
        }
