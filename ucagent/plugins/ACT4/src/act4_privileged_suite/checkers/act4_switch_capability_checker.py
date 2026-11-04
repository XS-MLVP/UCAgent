"""Validate the version-specific ACT4 switch and capability audit."""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - reported by the checker.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker


CONTROL_CLASSES = {
    "runtime_selection",
    "suite_opt_in",
    "suite_metadata",
    "build_owned",
    "dut_capability",
    "framework_guard",
    "dut_adapter",
    "reference_model",
}
DEFINED_BY = {
    "command_line",
    "new_suite_generator",
    "act4_build",
    "udb",
    "framework",
    "dut_config",
    "validation_config",
}
DECISIONS = {
    "allowed",
    "allowed_with_limitations",
    "framework_blocked",
    "not_applicable",
}
OWNER_BY_CLASS = {
    "runtime_selection": {"command_line"},
    "suite_opt_in": {"new_suite_generator"},
    "suite_metadata": {"new_suite_generator"},
    "build_owned": {"act4_build"},
    "dut_capability": {"udb", "dut_config", "framework"},
    "framework_guard": {"framework"},
    "dut_adapter": {"dut_config"},
    "reference_model": {"validation_config"},
}


class ACT4SwitchCapabilityChecker(Checker):
    """Check audit schema, ownership, and baseline-integrity decisions."""

    def __init__(
        self,
        audit_file: str,
        expected_suite: str | None = None,
        baseline_manifest: str | None = None,
        verify_audited_source_paths: bool = False,
        required_capability_names: Any = None,
        output_dir: str | None = None,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                "unsupported ACT4SwitchCapabilityChecker arguments: "
                f"{sorted(kwargs)}"
            )
        self.audit_file = audit_file
        self.expected_suite = expected_suite
        self.baseline_manifest = baseline_manifest
        self.verify_audited_source_paths = bool(verify_audited_source_paths)
        self.required_capability_names = {
            str(name).strip() for name in (required_capability_names or [])
            if str(name).strip()
        }
        self.output_dir = output_dir
        self._last_report: dict[str, Any] = {}
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    def _root(self) -> Path:
        return Path(getattr(self, "workspace", None) or os.getcwd()).resolve()

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self._root() / path).resolve()

    @staticmethod
    def _add(
        findings: list[dict[str, Any]], severity: str, check: str, message: str, **details: Any
    ) -> None:
        findings.append({"severity": severity, "check": check, "message": message, **details})

    def _load(self, path: Path, findings: list[dict[str, Any]], label: str) -> Any:
        if not path.is_file():
            self._add(findings, "error", f"{label}_exists", f"missing YAML file: {path}")
            return None
        if yaml is None:
            self._add(findings, "error", f"{label}_parser", "PyYAML is required")
            return None
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(findings, "error", f"{label}_parse", str(exc), file=str(path))
            return None

    @staticmethod
    def _nonempty_list(value: Any) -> bool:
        return isinstance(value, list) and any(str(item).strip() for item in value)

    @staticmethod
    def _nonempty(value: Any) -> bool:
        return value is not None and bool(str(value).strip())

    def _validate_control(
        self,
        control: Any,
        index: int,
        findings: list[dict[str, Any]],
    ) -> str:
        label = f"controls[{index}]"
        if not isinstance(control, dict):
            self._add(findings, "error", "switch_control_schema", f"{label} must be a mapping")
            return ""
        required = (
            "name",
            "class",
            "defined_by",
            "effective_state",
            "supported_entrypoint",
            "permitted_action",
            "baseline_edit_required",
            "decision",
            "evidence",
            "affected_profiles",
            "limitations",
            "blocked_reason",
        )
        missing = [key for key in required if key not in control]
        if missing:
            self._add(findings, "error", "switch_control_schema", f"{label} is missing {missing}")

        name = str(control.get("name", "")).strip()
        control_class = str(control.get("class", "")).strip()
        defined_by = str(control.get("defined_by", "")).strip()
        decision = str(control.get("decision", "")).strip()
        baseline_edit = control.get("baseline_edit_required")
        entrypoint = control.get("supported_entrypoint")
        action = str(control.get("permitted_action", "")).strip()
        limitations = control.get("limitations")
        affected = control.get("affected_profiles")

        if not name:
            self._add(findings, "error", "switch_control_schema", f"{label}.name must be non-empty")
        if control_class not in CONTROL_CLASSES:
            self._add(findings, "error", "switch_control_class", f"{label}.class is invalid")
        if defined_by not in DEFINED_BY:
            self._add(findings, "error", "switch_control_owner", f"{label}.defined_by is invalid")
        elif control_class in OWNER_BY_CLASS and defined_by not in OWNER_BY_CLASS[control_class]:
            self._add(
                findings,
                "error",
                "switch_control_ownership",
                f"{label}: {control_class} cannot be defined by {defined_by}",
            )
        if decision not in DECISIONS:
            self._add(findings, "error", "switch_control_decision", f"{label}.decision is invalid")
        if not str(control.get("effective_state", "")).strip():
            self._add(findings, "error", "switch_effective_state", f"{label}.effective_state must be non-empty")
        if not isinstance(baseline_edit, bool):
            self._add(findings, "error", "switch_baseline_edit", f"{label}.baseline_edit_required must be boolean")
        if not self._nonempty_list(control.get("evidence")):
            self._add(findings, "error", "switch_evidence", f"{label}.evidence must be non-empty")
        if not isinstance(affected, list) or not isinstance(limitations, list):
            self._add(findings, "error", "switch_control_schema", f"{label}.affected_profiles and limitations must be lists")

        if decision == "allowed":
            if baseline_edit is not False:
                self._add(findings, "error", "switch_allowed_baseline", f"{label}: allowed cannot require a baseline edit")
            if entrypoint is None or not str(entrypoint).strip():
                self._add(findings, "error", "switch_allowed_entrypoint", f"{label}: allowed requires a supported entrypoint")
            if not action or action.lower() == "none":
                self._add(findings, "error", "switch_allowed_action", f"{label}: allowed requires a permitted action")
            if isinstance(limitations, list) and limitations:
                self._add(findings, "error", "switch_allowed_limitations", f"{label}: use allowed_with_limitations when limitations exist")
        elif decision == "allowed_with_limitations":
            if baseline_edit is not False:
                self._add(findings, "error", "switch_allowed_baseline", f"{label}: limited use cannot require a baseline edit")
            if entrypoint is None or not str(entrypoint).strip():
                self._add(findings, "error", "switch_allowed_entrypoint", f"{label}: limited use requires a supported entrypoint")
            if not self._nonempty_list(limitations):
                self._add(findings, "error", "switch_limitations", f"{label}: limitations must explain the restricted use")
        elif decision == "framework_blocked":
            if not self._nonempty(control.get("blocked_reason")):
                self._add(findings, "error", "switch_blocked_reason", f"{label}: framework_blocked requires blocked_reason")
            if not self._nonempty_list(affected):
                self._add(findings, "error", "switch_blocked_scope", f"{label}: framework_blocked requires affected_profiles")
            if action and action.lower() != "none":
                self._add(findings, "error", "switch_blocked_action", f"{label}: framework_blocked permitted_action must be none")

        if name.endswith("_SUPPORTED"):
            if control_class != "dut_capability":
                self._add(findings, "error", "switch_capability_class", f"{label}: *_SUPPORTED must be a dut_capability")
            if defined_by not in {"udb", "dut_config", "framework"}:
                self._add(findings, "error", "switch_capability_owner", f"{label}: *_SUPPORTED cannot be defined by a suite or command line")
        if name == "RVTEST_SELFCHECK" and control_class != "build_owned":
            self._add(findings, "error", "switch_build_owned", f"{label}: RVTEST_SELFCHECK must be build_owned")
        return name

    def _validate_required_capabilities(
        self, capabilities: Any, findings: list[dict[str, Any]]
    ) -> set[str]:
        if not isinstance(capabilities, list):
            self._add(findings, "error", "switch_audit_schema", "required_capabilities must be a list")
            return set()
        names: set[str] = set()
        for index, capability in enumerate(capabilities):
            label = f"required_capabilities[{index}]"
            if not isinstance(capability, dict):
                self._add(findings, "error", "required_capability_schema", f"{label} must be a mapping")
                continue
            missing = [key for key in ("name", "required_by", "evidence") if key not in capability]
            if missing:
                self._add(findings, "error", "required_capability_schema", f"{label} is missing {missing}")
            name = str(capability.get("name", "")).strip()
            if not name:
                self._add(findings, "error", "required_capability_schema", f"{label}.name must be non-empty")
            elif name in names:
                self._add(findings, "error", "required_capability_duplicate", f"duplicate capability name: {name}")
            names.add(name)
            if not self._nonempty_list(capability.get("required_by")):
                self._add(findings, "error", "required_capability_scope", f"{label}.required_by must be non-empty")
            if not self._nonempty_list(capability.get("evidence")):
                self._add(findings, "error", "required_capability_evidence", f"{label}.evidence must be non-empty")
        missing = sorted(self.required_capability_names - names)
        if missing:
            self._add(
                findings,
                "error",
                "required_capability_missing",
                f"required_capabilities omits workflow-required capabilities: {missing}",
            )
        return names

    def _validate_audited_sources(
        self, sources: Any, findings: list[dict[str, Any]]
    ) -> int:
        if not self._nonempty_list(sources):
            self._add(
                findings,
                "error",
                "switch_audit_sources",
                "audited_sources must be non-empty",
            )
            return 0
        verified = 0
        for index, source in enumerate(sources):
            if isinstance(source, dict):
                kind = str(source.get("kind", "")).strip()
                value = str(source.get("value", "")).strip()
                if kind not in {"file", "command", "tool_result"} or not value:
                    self._add(
                        findings,
                        "error",
                        "switch_audited_source_schema",
                        f"audited_sources[{index}] requires kind=file|command|tool_result and a non-empty value",
                    )
                    continue
                if kind != "file":
                    continue
                if glob.has_magic(value):
                    self._add(
                        findings,
                        "error",
                        "switch_audited_source_glob",
                        f"audited_sources[{index}] file evidence must name an exact path",
                        source=value,
                    )
                    continue
                text = value
            else:
                self._add(
                    findings,
                    "error",
                    "switch_audited_source_schema",
                    f"audited_sources[{index}] must be a typed evidence mapping",
                )
                continue
            if not self.verify_audited_source_paths:
                continue
            match = re.match(r"^((?:riscv-arch-test|unity_test)/[^:\s]+)", text)
            if not match:
                continue
            verified += 1
            path = self._resolve(match.group(1))
            if not path.exists():
                self._add(
                    findings,
                    "error",
                    "switch_audited_source_path",
                    f"audited_sources[{index}] references a missing workspace path",
                    source=text,
                    file=str(path),
                )
        if self.verify_audited_source_paths and verified == 0:
            self._add(
                findings,
                "error",
                "switch_audited_source_path",
                "audited_sources must include at least one verifiable workspace path",
            )
        return verified

    def do_check(self, timeout=0, is_complete=False, **kwargs: Any) -> tuple[bool, object]:
        """Validate the configured switch/capability audit."""
        findings: list[dict[str, Any]] = []
        audit_path = self._resolve(self.audit_file)
        audit = self._load(audit_path, findings, "switch_audit")
        controls_count = 0
        verified_sources = 0
        if isinstance(audit, dict):
            required = (
                "schema_version",
                "suite",
                "act4_git_head",
                "audited_sources",
                "required_capabilities",
                "controls",
                "decision_summary",
            )
            missing = [key for key in required if key not in audit]
            if missing:
                self._add(findings, "error", "switch_audit_schema", f"audit is missing {missing}")
            if audit.get("schema_version") != 1:
                self._add(findings, "error", "switch_audit_version", "schema_version must be 1")
            if not str(audit.get("suite", "")).strip():
                self._add(findings, "error", "switch_audit_schema", "suite must be non-empty")
            elif self.expected_suite and str(audit.get("suite")) != self.expected_suite:
                self._add(
                    findings,
                    "error",
                    "switch_audit_suite",
                    "audit suite does not match the configured suite",
                    expected=self.expected_suite,
                    actual=audit.get("suite"),
                )
            verified_sources = self._validate_audited_sources(
                audit.get("audited_sources"), findings
            )
            self._validate_required_capabilities(audit.get("required_capabilities"), findings)
            controls = audit.get("controls")
            if not isinstance(controls, list) or not controls:
                self._add(findings, "error", "switch_audit_schema", "controls must be a non-empty list")
                controls = []
            names: set[str] = set()
            decision_by_name: dict[str, str] = {}
            for index, control in enumerate(controls):
                name = self._validate_control(control, index, findings)
                if name and name in names:
                    self._add(findings, "error", "switch_control_duplicate", f"duplicate control name: {name}")
                names.add(name)
                if name and isinstance(control, dict):
                    decision_by_name[name] = str(control.get("decision", ""))
            controls_count = len(controls)
            summary = audit.get("decision_summary")
            if not isinstance(summary, dict) or any(
                not isinstance(summary.get(key), list)
                for key in ("allowed_controls", "limited_controls", "blocked_capabilities")
            ):
                self._add(findings, "error", "switch_summary_schema", "decision_summary must contain three lists")
            else:
                expected_summary = {
                    "allowed_controls": {
                        name for name, decision in decision_by_name.items() if decision == "allowed"
                    },
                    "limited_controls": {
                        name
                        for name, decision in decision_by_name.items()
                        if decision == "allowed_with_limitations"
                    },
                    "blocked_capabilities": {
                        name
                        for name, decision in decision_by_name.items()
                        if decision == "framework_blocked"
                    },
                }
                for key, expected in expected_summary.items():
                    values = summary.get(key, [])
                    actual = {str(value) for value in values}
                    if len(actual) != len(values) or actual != expected:
                        self._add(
                            findings,
                            "error",
                            "switch_summary_consistency",
                            f"decision_summary.{key} does not match controls",
                            expected=sorted(expected),
                            actual=sorted(actual),
                        )

            if self.baseline_manifest:
                manifest_path = self._resolve(self.baseline_manifest)
                manifest = self._load(manifest_path, findings, "baseline_manifest")
                baseline = manifest.get("baseline") if isinstance(manifest, dict) else None
                if isinstance(baseline, dict):
                    expected_head = baseline.get("git_head")
                    actual_head = audit.get("act4_git_head")
                    if expected_head and actual_head != expected_head:
                        self._add(
                            findings,
                            "error",
                            "switch_audit_git_head",
                            "audit act4_git_head does not match the frozen baseline",
                            expected=expected_head,
                            actual=actual_head,
                        )
                elif manifest is not None:
                    self._add(findings, "error", "baseline_manifest_schema", "baseline manifest must contain baseline")
        elif audit is not None:
            self._add(findings, "error", "switch_audit_schema", "audit must be a YAML mapping")

        errors = sum(item["severity"] == "error" for item in findings)
        warnings = sum(item["severity"] == "warning" for item in findings)
        report = {
            "status": "failed" if errors else "complete",
            "summary": {"errors": errors, "warnings": warnings},
            "checks": {
                "audit_file": str(audit_path),
                "controls": controls_count,
                "verified_source_paths": verified_sources,
            },
            "findings": findings,
        }
        if self.output_dir:
            output_dir = self._resolve(self.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "switch-capability-audit.json"
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            report["report_file"] = str(report_path)
        self._last_report = report
        return errors == 0, report


__all__ = ["ACT4SwitchCapabilityChecker"]
