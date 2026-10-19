"""Static checks for ACT4-generated privileged assembly and ELF assets."""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from . import act4_testcase_reachability as reachability

try:
    import yaml
except ImportError:  # pragma: no cover - reported when header validation runs.
    yaml = None  # type: ignore[assignment]

from ucagent.checkers.base import Checker


class ACT4TestAssetChecker(Checker):
    """Validate generated ACT4 test sources and their compiled ELF artifacts.

    This checker is intentionally static: compilation and simulator execution
    remain responsibilities of the preceding stage. It verifies that the stage
    produced non-empty, structurally recognizable ACT4 sources, matching ELF
    files, generation reports, and no unresolved placeholders.
    """

    def __init__(
        self,
        source_files: Any = None,
        source_patterns: Any = None,
        elf_files: Any = None,
        elf_patterns: Any = None,
        signature_files: Any = None,
        signature_patterns: Any = None,
        result_files: Any = None,
        result_patterns: Any = None,
        reference_model_log_files: Any = None,
        reference_model_log_patterns: Any = None,
        source_markers: Any = None,
        source_marker_any: Any = None,
        forbidden_patterns: Any = None,
        report_files: Any = None,
        report_patterns: Any = None,
        validate_test_config: bool = True,
        require_matching_stems: bool = True,
        require_matching_xlen: bool = False,
        require_nonempty: bool = True,
        require_reports: bool = False,
        require_signature: bool = False,
        require_results: bool = False,
        require_reference_model_logs: bool = False,
        require_signature_completeness: bool = False,
        signature_progress_mode: str = "off",
        max_testcases_per_source: int | None = None,
        derive_priv_testcase_limit: bool = False,
        check_testcase_reachability: bool = False,
        nm_executable: str | None = None,
        validation_state: str | None = None,
        require_self_checking_status: bool = False,
        require_sail_coverage: bool = False,
        require_contribution_ready: bool = False,
        allow_sail_coverage_blocked: bool = False,
        require_reference_model_evaluation: bool = False,
        vm_resource_contract: str | None = None,
        validate_vm_contract: bool = False,
        require_scoped_vm_contract: bool = False,
        require_generation_scope: bool = False,
        experimental_manifest: str | None = None,
        validate_experimental_assets: bool = False,
        act4_root: str | None = None,
        output_dir: str | None = None,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4TestAssetChecker arguments: {sorted(kwargs)}"
            )
        self.source_files = source_files or []
        self.source_patterns = source_patterns or []
        self.elf_files = elf_files or []
        self.elf_patterns = elf_patterns or []
        self.signature_files = signature_files or []
        self.signature_patterns = signature_patterns or []
        self.result_files = result_files or []
        self.result_patterns = result_patterns or []
        self.reference_model_log_files = reference_model_log_files or []
        self.reference_model_log_patterns = reference_model_log_patterns or []
        self.source_markers = [str(item) for item in self._listify(source_markers)]
        self.source_marker_any = [str(item) for item in self._listify(source_marker_any)]
        self.forbidden_patterns = [
            re.compile(str(item), re.IGNORECASE)
            for item in self._listify(forbidden_patterns)
        ]
        self.report_files = report_files or []
        self.report_patterns = report_patterns or []
        self.validate_test_config = bool(validate_test_config)
        self.require_matching_stems = bool(require_matching_stems)
        self.require_matching_xlen = bool(require_matching_xlen)
        self.require_nonempty = bool(require_nonempty)
        self.require_reports = bool(require_reports)
        self.require_signature = bool(require_signature)
        self.require_results = bool(require_results)
        self.require_reference_model_logs = bool(require_reference_model_logs)
        self.require_signature_completeness = bool(
            require_signature_completeness
        )
        progress_mode = str(signature_progress_mode).strip().lower()
        if progress_mode not in {"off", "warning", "error"}:
            raise ValueError(
                "signature_progress_mode must be off, warning, or error"
            )
        self.signature_progress_mode = progress_mode
        self.max_testcases_per_source = (
            int(max_testcases_per_source)
            if max_testcases_per_source is not None
            else None
        )
        self.derive_priv_testcase_limit = bool(derive_priv_testcase_limit)
        self.check_testcase_reachability = bool(check_testcase_reachability)
        self.nm_executable = nm_executable
        self.validation_state = validation_state
        self.require_self_checking_status = bool(require_self_checking_status)
        self.require_sail_coverage = bool(require_sail_coverage)
        self.require_contribution_ready = bool(require_contribution_ready)
        self.allow_sail_coverage_blocked = bool(allow_sail_coverage_blocked)
        self.require_reference_model_evaluation = bool(
            require_reference_model_evaluation
        )
        self.vm_resource_contract = vm_resource_contract
        self.validate_vm_contract = bool(validate_vm_contract)
        self.require_scoped_vm_contract = bool(require_scoped_vm_contract)
        self.require_generation_scope = bool(require_generation_scope)
        self.experimental_manifest = experimental_manifest
        self.validate_experimental_assets = bool(validate_experimental_assets)
        self.act4_root = act4_root
        self.output_dir = output_dir

    @staticmethod
    def _listify(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    @classmethod
    def _string_set(cls, value: Any) -> set[str]:
        return {str(item).strip() for item in cls._listify(value) if str(item).strip()}

    @staticmethod
    def _nonempty_string_list(value: Any) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value)
        )

    def _workspace_root(self) -> Path:
        return Path(os.getcwd() if not getattr(self, "workspace", None) else self.workspace).resolve()

    def _artifact_root(self) -> Path:
        """Resolve ACT4 artifacts inside the active workspace when available.

        Generation runs from ``workspace_{DUT}``, so a relative ``act4_root``
        must not escape that workspace merely because an older config used
        ``../../riscv-arch-test``. An explicitly configured path remains a
        fallback for standalone invocations without a workspace-local checkout.
        """
        workspace = self._workspace_root()
        local_root = workspace / "riscv-arch-test"
        if local_root.is_dir():
            return local_root.resolve()
        configured = Path(str(self.act4_root)).expanduser() if self.act4_root else Path("riscv-arch-test")
        if configured.is_absolute():
            return configured.resolve()
        return (workspace / configured).resolve()

    def _discover(self, explicit: Any, patterns: Any, root: Path | None = None) -> list[Path]:
        root = (root or self._workspace_root()).resolve()
        paths: list[Path] = []
        for raw in self._listify(explicit):
            value = str(raw)
            path = Path(value).expanduser()
            if path.is_absolute():
                if any(char in value for char in "*?["):
                    paths.extend(Path(item).resolve() for item in path.parent.glob(path.name))
                elif path.is_file():
                    paths.append(path.resolve())
                continue
            if any(char in value for char in "*?["):
                paths.extend(Path(item).resolve() for item in root.glob(value))
            else:
                candidate = (root / path).resolve()
                if candidate.is_file():
                    paths.append(candidate)
        for raw in self._listify(patterns):
            paths.extend(Path(item).resolve() for item in root.glob(str(raw)))
        return sorted(set(path for path in paths if path.is_file()))
    @staticmethod
    def _discover_sibling_assets(sources: list[Path], suffix: str) -> list[Path]:
        """Find canonical delivered ACT4 assets when configured paths are absent."""
        paths: list[Path] = []
        for source in sources:
            tests_dir = next((parent for parent in source.parents if parent.name == "tests"), None)
            if tests_dir is None:
                continue
            candidate = tests_dir.parent / "elfs" / f"{source.stem}{suffix}"
            if candidate.is_file():
                paths.append(candidate.resolve())
        return sorted(set(paths))

    @staticmethod
    def _elf_xlen(path: Path) -> int | None:
        try:
            elf_class = path.read_bytes()[4]
        except (OSError, IndexError):
            return None
        return 32 if elf_class == 1 else 64 if elf_class == 2 else None

    def _resolve_source_xlen(
        self,
        path: Path,
        text: str,
        contract_xlens: set[int],
        elf_xlens: set[int],
        findings: list[dict[str, Any]],
    ) -> tuple[set[int], dict[str, Any]]:
        """Resolve XLEN from independent source, contract, and ELF evidence."""
        literal = {
            int(value)
            for value in re.findall(
                r"(?im)^\s*#\s*MARCH\s*:\s*rv(32|64)(?!\d)",
                text,
            )
        }
        templated = bool(
            re.search(
                r"(?im)^\s*#\s*MARCH\s*:\s*rv\$\{XLEN\}",
                text,
            )
        )
        evidence: dict[str, Any] = {
            "source_march": sorted(literal),
            "source_uses_xlen_template": templated,
            "contract_target_xlen": sorted(contract_xlens),
            "elf_class_xlen": sorted(elf_xlens),
        }
        candidates: list[set[int]] = []
        if literal:
            candidates.append(literal)
        if contract_xlens:
            candidates.append(contract_xlens)
        if elf_xlens:
            candidates.append(elf_xlens)
        known = set().union(*candidates) if candidates else set()
        if len({frozenset(values) for values in candidates}) > 1 or len(known) > 1:
            self._add(
                findings,
                "error",
                "source_xlen_conflict",
                "source, VM contract, and ELF XLEN evidence conflict",
                file=str(path),
                evidence=evidence,
            )
        elif not known and self.require_matching_xlen:
            self._add(
                findings,
                "warning",
                "source_xlen_unknown",
                "XLEN was not proven; provide a literal MARCH, an ${XLEN} MARCH with contract selected_target.XLEN, or a matching ELF",
                file=str(path),
                evidence=evidence,
            )
        return known, evidence


    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _add(findings: list[dict[str, Any]], severity: str, check: str, message: str, **details: Any) -> None:
        findings.append({"severity": severity, "check": check, "message": message, **details})

    def _check_test_config(self, text: str, path: Path, findings: list[dict[str, Any]]) -> None:
        start_marker = "##### START_TEST_CONFIG #####"
        end_marker = "##### END_TEST_CONFIG #####"
        start = text.find(start_marker)
        end = text.find(end_marker)
        code_markers = ("RVTEST_CODE_BEGIN", "RVTEST_BEGIN")
        code_positions = [text.find(marker) for marker in code_markers if text.find(marker) >= 0]
        code = min(code_positions) if code_positions else -1
        if start < 0 or end < 0 or end <= start:
            return
        if code >= 0 and end > code:
            self._add(
                findings,
                "error",
                "test_config_order",
                "ACT4 YAML test header must precede RVTEST_BEGIN/RVTEST_CODE_BEGIN",
                file=str(path),
            )
        if yaml is None:
            self._add(findings, "error", "test_config_parser", "PyYAML is required to validate ACT4 test headers", file=str(path))
            return
        header_lines = []
        for line in text[start + len(start_marker) : end].splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                header_lines.append(stripped[1:].lstrip())
        try:
            header = yaml.safe_load("\n".join(header_lines))
        except yaml.YAMLError as exc:
            self._add(findings, "error", "test_config_parse", f"invalid ACT4 YAML test header: {exc}", file=str(path))
            return
        if not isinstance(header, dict) or not header:
            self._add(findings, "error", "test_config_schema", "ACT4 YAML test header must be a non-empty mapping", file=str(path))

    def _check_reports(self, findings: list[dict[str, Any]]) -> list[Path]:
        reports = self._discover(self.report_files, self.report_patterns)
        if self.require_reports and not reports:
            self._add(findings, "error", "test_reports_exist", "no generation reports were found")
            return reports

        for path in reports:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self._add(findings, "error", "test_report_read", str(exc), file=str(path))
                continue
            if self.require_nonempty and not text.strip():
                self._add(findings, "error", "test_report_nonempty", "generation report is empty", file=str(path))
        return reports

    def _check_validation_state(self, root: Path, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Check explicit source, self-checking, Sail-coverage, and contribution states."""
        if not self.validation_state:
            if (
                self.require_self_checking_status
                or self.require_sail_coverage
                or self.require_contribution_ready
                or self.require_generation_scope
                or self.require_reference_model_evaluation
            ):
                self._add(findings, "error", "validation_state_exists", "validation_state is required for the selected verification gate")
            return None
        path = Path(self.validation_state).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            self._add(findings, "error", "validation_state_exists", f"validation state is missing: {path}", file=str(path))
            return None
        if yaml is None:
            self._add(findings, "error", "validation_state_parse", "PyYAML is required to validate verification state", file=str(path))
            return None
        try:
            state = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(findings, "error", "validation_state_parse", str(exc), file=str(path))
            return None
        if not isinstance(state, dict):
            self._add(findings, "error", "validation_state_schema", "validation state must be a YAML mapping", file=str(path))
            return None
        required = (
            "source_generated",
            "supported_xlens",
            "self_checking",
            "sail_coverage",
            "generation_scope",
            "contribution_ready",
        )
        if self.require_reference_model_evaluation:
            required += ("reference_model_evaluation",)
        missing = [key for key in required if key not in state]
        if missing:
            self._add(findings, "error", "validation_state_schema", f"validation state is missing required keys: {missing}", file=str(path))
            return state
        supported_xlens = state.get("supported_xlens")
        if (
            not isinstance(supported_xlens, list)
            or not supported_xlens
            or any(value not in {32, 64} for value in supported_xlens)
        ):
            self._add(
                findings,
                "error",
                "validation_supported_xlens",
                "supported_xlens must be a non-empty list containing only 32 and/or 64",
                file=str(path),
            )
        source_generated = state.get("source_generated")
        if not isinstance(source_generated, bool):
            self._add(findings, "error", "validation_state_schema", "source_generated must be boolean", file=str(path))
        elif not source_generated:
            self._add(findings, "error", "validation_source_generated", "validation state does not confirm generated source")

        self_checking = state.get("self_checking")
        model: str | None = None
        self_checking_passed = False
        self_checking_keys = ["passed", "model", "command"]
        if (
            self.require_reference_model_logs
            or self.require_signature_completeness
            or self.signature_progress_mode != "off"
        ):
            self_checking_keys.extend(["executable", "config_file"])
        if not isinstance(self_checking, dict) or not all(
            key in self_checking for key in self_checking_keys
        ):
            self._add(findings, "error", "validation_self_check_schema", "self_checking must record model, passed, and command", file=str(path))
        else:
            model = str(self_checking.get("model", "")).strip().lower()
            passed_value = self_checking.get("passed")
            if not model:
                self._add(findings, "error", "validation_self_check_model", "self_checking.model must name the reference model used", file=str(path))
            if not isinstance(passed_value, bool):
                self._add(findings, "error", "validation_self_check_schema", "self_checking.passed must be boolean", file=str(path))
            else:
                self_checking_passed = passed_value
            if not str(self_checking.get("command", "")).strip():
                self._add(findings, "error", "validation_self_check_command", "self_checking.command must record the ACT4 build command", file=str(path))
            else:
                self._check_reference_model_identity(
                    model or "",
                    str(self_checking.get("executable", "")),
                    str(self_checking.get("config_file", "")),
                    str(self_checking.get("command")),
                    findings,
                    path,
                )
            if self.require_self_checking_status and not self_checking_passed:
                self._add(findings, "error", "validation_self_check", "self-checking build has not passed", model=model)

        sail_coverage = state.get("sail_coverage")
        sail_coverage_passed = False
        if not isinstance(sail_coverage, dict) or not all(key in sail_coverage for key in ("passed", "command", "blocked_reason")):
            self._add(findings, "error", "validation_sail_coverage_schema", "sail_coverage must record passed, command, and blocked_reason", file=str(path))
        else:
            coverage_value = sail_coverage.get("passed")
            if not isinstance(coverage_value, bool):
                self._add(findings, "error", "validation_sail_coverage_schema", "sail_coverage.passed must be boolean", file=str(path))
            else:
                sail_coverage_passed = coverage_value
            if sail_coverage_passed:
                if not str(sail_coverage.get("command", "")).strip():
                    self._add(findings, "error", "validation_sail_coverage_command", "passing Sail coverage must record its ACT4 coverage command", file=str(path))
            elif not str(sail_coverage.get("blocked_reason", "")).strip():
                self._add(findings, "error", "validation_sail_coverage_block", "blocked Sail coverage must include blocked_reason", file=str(path))
            if self.require_sail_coverage and not sail_coverage_passed:
                self._add(findings, "error", "validation_sail_coverage", "ACT4 Sail/RVVI coverage has not passed", blocked_reason=sail_coverage.get("blocked_reason"))

        contribution_value = state.get("contribution_ready")
        contribution_ready = contribution_value is True
        if not isinstance(contribution_value, bool):
            self._add(findings, "error", "validation_state_schema", "contribution_ready must be boolean", file=str(path))
        sail_blocked = (
            isinstance(sail_coverage, dict)
            and not sail_coverage_passed
            and bool(str(sail_coverage.get("blocked_reason", "")).strip())
        )
        if contribution_ready and (not model or not self_checking_passed):
            self._add(findings, "error", "validation_contribution_inconsistent", "contribution_ready requires a named, passing self-checking reference model", file=str(path), model=model)
        if contribution_ready and sail_blocked and not (
            self.allow_sail_coverage_blocked and bool(model) and self_checking_passed
        ):
            self._add(findings, "error", "validation_contribution_sail", "contribution_ready with blocked Sail coverage requires a passing reference model and allow_sail_coverage_blocked", file=str(path), model=model)
        if self.require_contribution_ready and not contribution_ready:
            self._add(findings, "error", "validation_contribution_ready", "asset is not contribution-ready; a passing self-checking model is required (Sail coverage may be BLOCKED when configured)")

        generation_scope = state.get("generation_scope")
        if not isinstance(generation_scope, dict):
            self._add(
                findings,
                "error",
                "validation_generation_scope",
                "generation_scope must be a mapping",
                file=str(path),
            )
        else:
            required_scope_keys = {
                "status",
                "generated_targets",
                "partial_targets",
                "blocked_targets",
            }
            if not required_scope_keys.issubset(generation_scope):
                self._add(
                    findings,
                    "error",
                    "validation_generation_scope",
                    "generation scope must record status, generated_targets, partial_targets, and blocked_targets",
                    file=str(path),
                )
            else:
                status = str(generation_scope.get("status", "")).strip()
                generated = self._string_set(generation_scope.get("generated_targets"))
                partial = self._string_set(generation_scope.get("partial_targets"))
                blocked_targets = self._string_set(generation_scope.get("blocked_targets"))
                if status not in {"complete", "partial"}:
                    self._add(findings, "error", "validation_generation_scope", "generation scope status must be complete or partial", file=str(path))
                if not partial.issubset(generated):
                    self._add(findings, "error", "validation_generation_scope", "partial_targets must also be listed in generated_targets", file=str(path), targets=sorted(partial - generated))
                if partial & blocked_targets:
                    self._add(findings, "error", "validation_generation_scope", "partial_targets and blocked_targets must be disjoint", file=str(path), targets=sorted(partial & blocked_targets))
                expected_status = "partial" if partial or blocked_targets else "complete"
                if status != expected_status:
                    self._add(findings, "error", "validation_generation_scope", f"generation scope status must be {expected_status!r} for the declared target sets", file=str(path))
        if self.require_reference_model_evaluation:
            self._check_reference_model_evaluation(
                state.get("reference_model_evaluation"),
                model or "",
                generation_scope,
                findings,
                path,
            )
        return state

    def _check_reference_model_evaluation(
        self,
        evaluation: Any,
        final_model: str,
        generation_scope: Any,
        findings: list[dict[str, Any]],
        state_path: Path,
    ) -> None:
        """Reject an unproven or scope-reducing reference-model fallback."""
        if not isinstance(evaluation, dict):
            self._add(
                findings,
                "error",
                "reference_model_evaluation_schema",
                "reference_model_evaluation must be a mapping",
                file=str(state_path),
            )
            return

        preferred = evaluation.get("preferred")
        attempts = evaluation.get("attempts")
        fallback = evaluation.get("fallback")
        if not isinstance(preferred, dict):
            self._add(findings, "error", "reference_model_preferred_schema", "preferred must be a mapping", file=str(state_path))
            preferred = {}
        preferred_model = str(preferred.get("model", "")).strip().lower()
        preferred_config = str(preferred.get("config_file", "")).strip()
        if (
            not preferred_model
            or not str(preferred.get("executable", "")).strip()
            or not preferred_config
            or not self._nonempty_string_list(preferred.get("selection_basis"))
        ):
            self._add(
                findings,
                "error",
                "reference_model_preferred_schema",
                "preferred must record model, executable, config_file, and non-empty selection_basis",
                file=str(state_path),
            )

        if not isinstance(attempts, list) or not attempts:
            self._add(findings, "error", "reference_model_attempts_schema", "attempts must be a non-empty list", file=str(state_path))
            attempts = []

        global_failures = {
            "tool_unavailable",
            "version_mismatch",
            "configuration_mismatch",
        }
        target_failures = {
            "test_asset_defect",
            "framework_gap",
            "model_capability_gap",
            "unknown",
        }
        valid_failures = {"none", *global_failures, *target_failures}
        required_alternatives = {
            "suite_local_resources",
            "positive_subset",
            "native_entrypoint",
            "generation_vs_validation_scope",
        }
        preferred_attempts: list[dict[str, Any]] = []
        preferred_passed_targets: set[str] = set()
        diagnosed_outcomes: dict[str, str] = {}
        passed_targets_by_model: dict[str, set[str]] = {}

        for index, attempt in enumerate(attempts):
            label = f"attempts[{index}]"
            if not isinstance(attempt, dict):
                self._add(findings, "error", "reference_model_attempt_schema", f"{label} must be a mapping", file=str(state_path))
                continue
            required = {
                "model", "executable", "config_file", "command", "status",
                "tested_targets", "passed_targets", "failed_targets",
                "failure_class", "evidence", "diagnoses",
            }
            missing = sorted(required - set(attempt))
            if missing:
                self._add(findings, "error", "reference_model_attempt_schema", f"{label} is missing {missing}", file=str(state_path))
            model = str(attempt.get("model", "")).strip().lower()
            config = str(attempt.get("config_file", "")).strip()
            status = str(attempt.get("status", "")).strip()
            failure_class = str(attempt.get("failure_class", "")).strip()
            tested = self._string_set(attempt.get("tested_targets"))
            passed = self._string_set(attempt.get("passed_targets"))
            failed = self._string_set(attempt.get("failed_targets"))
            if (
                status not in {"passed", "failed", "not_run"}
                or failure_class not in valid_failures
                or not str(attempt.get("executable", "")).strip()
                or not config
                or not self._nonempty_string_list(attempt.get("evidence"))
            ):
                self._add(findings, "error", "reference_model_attempt_schema", f"{label} has an invalid status, identity, failure_class, or evidence", file=str(state_path))
            if status != "not_run" and not str(attempt.get("command", "")).strip():
                self._add(findings, "error", "reference_model_attempt_command", f"{label} must record the executed command", file=str(state_path))
            if passed - tested or failed - tested or passed & failed:
                self._add(findings, "error", "reference_model_attempt_scope", f"{label} passed/failed targets must be disjoint subsets of tested_targets", file=str(state_path))
            if status == "passed" and (failure_class != "none" or failed):
                self._add(findings, "error", "reference_model_attempt_result", f"{label} passed attempts cannot record failures", file=str(state_path))
            if status == "failed" and failure_class == "none":
                self._add(findings, "error", "reference_model_attempt_result", f"{label} failed attempt requires a failure_class", file=str(state_path))
            if status == "failed" and failure_class in target_failures and not failed:
                self._add(findings, "error", "reference_model_attempt_result", f"{label} target-level failure requires failed_targets", file=str(state_path))
            if status == "not_run" and failure_class not in global_failures:
                self._add(findings, "error", "reference_model_attempt_result", f"{label} not_run requires a tool, version, or configuration failure", file=str(state_path))

            diagnoses = attempt.get("diagnoses")
            if not isinstance(diagnoses, list):
                self._add(findings, "error", "reference_model_diagnosis_schema", f"{label}.diagnoses must be a list", file=str(state_path))
                diagnoses = []
            diagnosed_targets: set[str] = set()
            # Retries may fix one failure and expose another for the same target.
            attempt_outcomes: dict[str, str] = {}
            for diagnosis_index, diagnosis in enumerate(diagnoses):
                diagnosis_label = f"{label}.diagnoses[{diagnosis_index}]"
                target = str(diagnosis.get("target", "")).strip() if isinstance(diagnosis, dict) else ""
                affected_targets = self._string_set(
                    diagnosis.get("affected_targets")
                ) if isinstance(diagnosis, dict) else set()
                capability = str(diagnosis.get("capability", "")).strip() if isinstance(diagnosis, dict) else ""
                alternatives = self._string_set(diagnosis.get("alternatives_evaluated")) if isinstance(diagnosis, dict) else set()
                grouped = bool(affected_targets)
                diagnosis_targets = affected_targets if grouped else {target} if target else set()
                if (
                    not isinstance(diagnosis, dict)
                    or not diagnosis_targets
                    or bool(target) == grouped
                    or not str(diagnosis.get("first_failure", "")).strip()
                    or alternatives != required_alternatives
                    or str(diagnosis.get("outcome", "")).strip()
                    not in {"fixed", "retained", "experimental", "blocked"}
                    or not self._nonempty_string_list(diagnosis.get("evidence"))
                ):
                    self._add(findings, "error", "reference_model_diagnosis_schema", f"{diagnosis_label} must record bounded alternative analysis and evidence", file=str(state_path))
                if grouped and (
                    failure_class != "model_capability_gap"
                    or len(affected_targets) < 2
                    or not capability
                    or not self._nonempty_string_list(
                        diagnosis.get("common_cause_evidence")
                    )
                ):
                    self._add(
                        findings,
                        "error",
                        "reference_model_capability_group",
                        f"{diagnosis_label} grouped diagnosis requires model_capability_gap, at least two targets, capability, and common_cause_evidence",
                        file=str(state_path),
                    )
                if diagnosis_targets - failed:
                    self._add(
                        findings,
                        "error",
                        "reference_model_diagnosis_scope",
                        f"{diagnosis_label} targets must be listed in failed_targets",
                        file=str(state_path),
                        targets=sorted(diagnosis_targets - failed),
                    )
                outcome = str(diagnosis.get("outcome", "")).strip() if isinstance(diagnosis, dict) else ""
                for diagnosis_target in diagnosis_targets:
                    if (
                        diagnosis_target in attempt_outcomes
                        and attempt_outcomes[diagnosis_target] != outcome
                    ):
                        self._add(findings, "error", "reference_model_diagnosis_conflict", f"{label}: {diagnosis_target} has conflicting diagnosis outcomes", file=str(state_path))
                    diagnosed_targets.add(diagnosis_target)
                    attempt_outcomes[diagnosis_target] = outcome
            diagnosed_outcomes.update(attempt_outcomes)
            if failure_class in target_failures and failed - diagnosed_targets:
                self._add(
                    findings,
                    "error",
                    "reference_model_failure_diagnosis",
                    f"{label} lacks a diagnosis for every failed target",
                    file=str(state_path),
                    targets=sorted(failed - diagnosed_targets),
                )
            if model == preferred_model and config == preferred_config:
                preferred_attempts.append(attempt)
                preferred_passed_targets.update(passed)
            if status == "passed" and model:
                passed_targets_by_model.setdefault(model, set()).update(passed)

        if preferred_model and not preferred_attempts:
            self._add(findings, "error", "reference_model_preferred_attempt", "the preferred model/config must have an explicit attempt", file=str(state_path))

        if not isinstance(fallback, dict):
            self._add(findings, "error", "reference_model_fallback_schema", "fallback must be a mapping", file=str(state_path))
            return
        required_fallback = {
            "used", "model", "reason", "scope_reduction",
            "affected_targets", "evidence",
        }
        missing_fallback = sorted(required_fallback - set(fallback))
        if missing_fallback:
            self._add(findings, "error", "reference_model_fallback_schema", f"fallback is missing {missing_fallback}", file=str(state_path))
        fallback_used = fallback.get("used")
        scope_reduction = fallback.get("scope_reduction")
        if not isinstance(fallback_used, bool) or not isinstance(scope_reduction, bool):
            self._add(findings, "error", "reference_model_fallback_schema", "fallback.used and scope_reduction must be boolean", file=str(state_path))
            return

        generated = self._string_set(generation_scope.get("generated_targets")) if isinstance(generation_scope, dict) else set()
        blocked = self._string_set(generation_scope.get("blocked_targets")) if isinstance(generation_scope, dict) else set()
        if preferred_passed_targets - generated:
            self._add(
                findings,
                "error",
                "reference_model_passing_scope_preserved",
                "targets that passed on the preferred model were removed from generation_scope",
                file=str(state_path),
                targets=sorted(preferred_passed_targets - generated),
            )
        for target, outcome in diagnosed_outcomes.items():
            if outcome in {"fixed", "retained"} and target not in generated:
                self._add(findings, "error", "reference_model_diagnosis_scope", f"{target} has outcome {outcome!r} but is absent from generated_targets", file=str(state_path))
            if outcome == "blocked" and target not in blocked:
                self._add(findings, "error", "reference_model_diagnosis_scope", f"{target} has outcome 'blocked' but is absent from blocked_targets", file=str(state_path))
        expected_fallback = bool(preferred_model and final_model and preferred_model != final_model)
        if fallback_used != expected_fallback:
            self._add(findings, "error", "reference_model_fallback_consistency", "fallback.used must match the final and preferred model identities", file=str(state_path))
        if fallback_used:
            affected = self._string_set(fallback.get("affected_targets"))
            if not any(
                str(attempt.get("status", "")).strip() in {"failed", "not_run"}
                for attempt in preferred_attempts
            ):
                self._add(findings, "error", "reference_model_fallback_unnecessary", "fallback requires a failed or not-run preferred-model attempt", file=str(state_path))
            if str(fallback.get("model", "")).strip().lower() != final_model:
                self._add(findings, "error", "reference_model_fallback_consistency", "fallback.model must match self_checking.model", file=str(state_path))
            fallback_passed = passed_targets_by_model.get(final_model, set())
            if not fallback_passed or affected - fallback_passed:
                self._add(
                    findings,
                    "error",
                    "reference_model_fallback_attempt",
                    "fallback affected_targets must be covered by a passing final-model attempt",
                    file=str(state_path),
                    missing_targets=sorted(affected - fallback_passed),
                )
            if not str(fallback.get("reason", "")).strip() or not self._nonempty_string_list(fallback.get("evidence")):
                self._add(findings, "error", "reference_model_fallback_evidence", "a used fallback must record reason and evidence", file=str(state_path))
            if scope_reduction:
                self._add(findings, "error", "reference_model_fallback_scope_reduction", "changing reference models must not reduce generation scope", file=str(state_path))
            if generated and (not affected or not affected.issubset(generated)):
                self._add(findings, "error", "reference_model_fallback_scope", "affected_targets must name generated targets validated only by the fallback", file=str(state_path))
            if any(
                str(attempt.get("status", "")).strip() == "failed"
                and str(attempt.get("failure_class", "")).strip() == "unknown"
                for attempt in preferred_attempts
            ):
                self._add(findings, "error", "reference_model_fallback_unresolved", "fallback is not allowed while the preferred-model failure is unknown", file=str(state_path))
        elif scope_reduction:
            self._add(findings, "error", "reference_model_fallback_scope_reduction", "scope_reduction cannot be true when fallback.used is false", file=str(state_path))

    def _check_reference_model_identity(
        self,
        declared_model: str,
        declared_executable: str,
        declared_config_file: str,
        command: str,
        findings: list[dict[str, Any]],
        state_path: Path,
    ) -> None:
        """Cross-check the declared model against the selected ACT4 config."""
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            self._add(
                findings,
                "error",
                "validation_self_check_command",
                f"cannot parse self-checking command: {exc}",
                file=str(state_path),
            )
            return
        config_value = next(
            (
                token.split("=", 1)[1]
                for token in tokens
                if token.startswith("CONFIG_FILES=")
            ),
            None,
        )
        if not config_value:
            if (
                self.require_reference_model_logs
                or self.require_signature_completeness
                or self.signature_progress_mode != "off"
            ):
                self._add(
                    findings,
                    "error",
                    "validation_self_check_config",
                    "self-checking command must select CONFIG_FILES explicitly",
                    file=str(state_path),
                )
            return
        config_path = Path(config_value).expanduser()
        if not config_path.is_absolute():
            config_path = self._artifact_root() / config_path
        if not config_path.is_file() or yaml is None:
            self._add(
                findings,
                "error",
                "validation_self_check_config",
                f"CONFIG_FILES does not resolve to a readable ACT4 config: {config_path}",
                file=str(state_path),
            )
            return
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(
                findings,
                "error",
                "validation_self_check_config",
                str(exc),
                file=str(config_path),
            )
            return
        executable = (
            str(config.get("ref_model_exe", "")).strip()
            if isinstance(config, dict)
            else ""
        )
        executable_token = executable.lower()
        expected_token = (
            "sail"
            if "sail" in executable_token
            else "spike"
            if "spike" in executable_token
            else Path(executable_token).name
        )
        if expected_token and expected_token not in declared_model:
            self._add(
                findings,
                "error",
                "validation_self_check_model_mismatch",
                "declared reference model does not match CONFIG_FILES.ref_model_exe",
                file=str(state_path),
                declared_model=declared_model,
                ref_model_exe=executable,
                config_file=str(config_path),
            )
        if (
            self.require_reference_model_logs
            or self.require_signature_completeness
            or self.signature_progress_mode != "off"
        ):
            if not declared_executable.strip():
                self._add(
                    findings,
                    "error",
                    "validation_self_check_executable",
                    "self_checking.executable must record CONFIG_FILES.ref_model_exe",
                    file=str(state_path),
                )
            elif declared_executable.strip() != executable:
                self._add(
                    findings,
                    "error",
                    "validation_self_check_executable_mismatch",
                    "declared executable does not match CONFIG_FILES.ref_model_exe",
                    file=str(state_path),
                    declared_executable=declared_executable,
                    ref_model_exe=executable,
                )
            declared_path = Path(declared_config_file).expanduser()
            if not declared_config_file.strip():
                self._add(
                    findings,
                    "error",
                    "validation_self_check_config_file",
                    "self_checking.config_file must record the selected CONFIG_FILES path",
                    file=str(state_path),
                )
            else:
                if not declared_path.is_absolute():
                    declared_path = self._artifact_root() / declared_path
                if declared_path.resolve() != config_path.resolve():
                    self._add(
                        findings,
                        "error",
                        "validation_self_check_config_file_mismatch",
                        "declared config_file does not match command CONFIG_FILES",
                        file=str(state_path),
                        declared_config_file=str(declared_path),
                        command_config_file=str(config_path),
                    )

    def _selected_build_root(self, state: Any) -> Path | None:
        """Keep complete evidence chains within the explicitly selected native build."""
        if not isinstance(state, dict) or yaml is None:
            return None
        selection = state.get("self_checking")
        if not isinstance(selection, dict):
            return None
        try:
            tokens = shlex.split(str(selection.get("command", "")))
        except ValueError:
            return None  # Command validation reports malformed input separately.
        values = dict(token.split("=", 1) for token in tokens if "=" in token)
        if not values.get("CONFIG_FILES") or not values.get("WORKDIR"):
            return None
        root = self._artifact_root()
        config_path = root / values["CONFIG_FILES"]
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return None
        name = config.get("name") if isinstance(config, dict) else None
        if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
            return None
        return (root / values["WORKDIR"] / name).resolve()

    def _check_vm_contract(self, root: Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
        summary = {
            "no_vm": False,
            "allowed_targets": set(),
            "blocked_targets": set(),
            "experimental_targets": set(),
            "target_xlen": set(),
            "supported_xlens": set(),
        }
        if not self.validate_vm_contract or not self.vm_resource_contract:
            return summary
        path = Path(self.vm_resource_contract).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            severity = "error" if self.require_scoped_vm_contract else "warning"
            self._add(
                findings,
                severity,
                "vm_contract_absent",
                f"VM contract was configured but is absent: {path}",
                file=str(path),
            )
            return summary
        if yaml is None:
            self._add(findings, "error", "vm_contract_parser", "PyYAML is required to validate VM resource contracts", file=str(path))
            return summary
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(findings, "error", "vm_contract_parse", str(exc), file=str(path))
            return summary
        if isinstance(data, dict):
            target = data.get("selected_target")
            if not isinstance(target, dict):
                self._add(
                    findings,
                    "error",
                    "vm_contract_selected_target",
                    "selected_target must be a mapping",
                    file=str(path),
                )
            if isinstance(target, dict):
                target_xlen = target.get("XLEN")
                if target_xlen in {32, 64}:
                    summary["target_xlen"].add(int(target_xlen))
            supported_xlens = data.get("supported_xlens")
            if supported_xlens is not None:
                if not isinstance(supported_xlens, list) or any(
                    value not in {32, 64} for value in supported_xlens
                ):
                    self._add(
                        findings,
                        "error",
                        "vm_contract_supported_xlens",
                        "supported_xlens must contain only 32 and/or 64",
                        file=str(path),
                    )
                else:
                    summary["supported_xlens"] = {
                        int(value) for value in supported_xlens
                    }
                    if not summary["target_xlen"].issubset(
                        summary["supported_xlens"]
                    ):
                        self._add(
                            findings,
                            "error",
                            "vm_contract_supported_xlens",
                            "selected_target.XLEN must be listed in supported_xlens",
                            file=str(path),
                        )
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if profiles is None:
            # A no_vm decision is valid for suites without translation tests.
            if isinstance(data, dict) and data.get("decision") == "no_vm":
                summary["no_vm"] = True
                return summary
            self._add(findings, "error", "vm_contract_schema", "VM contract must contain profiles or an explicit decision: no_vm", file=str(path))
            return summary
        if isinstance(profiles, dict):
            profiles = list(profiles.values())
        if not isinstance(profiles, list):
            self._add(findings, "error", "vm_contract_schema", "VM contract profiles must be a list or mapping", file=str(path))
            return summary
        modes = {"bare_or_csr_only", "single_stage", "g_stage_only", "two_stage"}
        if not self.require_scoped_vm_contract:
            modes.add("blocked")
        decisions = {
            "allowed",
            "allowed_with_limitations",
            "blocked",
            "experimental",
        }
        execution_contexts = {"host_execution", "explicit_guest_memory_access", "guest_execution"}
        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                self._add(findings, "error", "vm_profile_schema", f"profile[{index}] must be a mapping", file=str(path))
                continue
            missing = [key for key in ("profile_id", "resource_mode", "requires_page_tables") if key not in profile]
            if self.require_scoped_vm_contract:
                missing.extend(
                    key
                    for key in (
                        "coverage_targets",
                        "decision",
                        "execution_context",
                        "capability_dependencies",
                    )
                    if key not in profile
                )
            if missing:
                self._add(findings, "error", "vm_profile_schema", f"profile[{index}] is missing {sorted(set(missing))}", file=str(path))
            mode = str(profile.get("resource_mode", ""))
            decision = str(profile.get("decision", ""))
            execution_context = str(profile.get("execution_context", ""))
            targets = self._string_set(profile.get("coverage_targets"))
            if mode and mode not in modes:
                self._add(findings, "error", "vm_profile_mode", f"unknown VM resource_mode: {mode}", file=str(path))
            if self.require_scoped_vm_contract and decision not in decisions:
                self._add(findings, "error", "vm_profile_decision", f"profile[{index}] has invalid decision: {decision!r}", file=str(path))
            if self.require_scoped_vm_contract and execution_context not in execution_contexts:
                self._add(findings, "error", "vm_profile_execution_context", f"profile[{index}] has invalid execution_context: {execution_context!r}", file=str(path))
            if decision in {"allowed", "allowed_with_limitations"}:
                summary["allowed_targets"].update(targets)
            elif decision == "blocked":
                summary["blocked_targets"].update(targets)
            elif decision == "experimental":
                summary["experimental_targets"].update(targets)
            if mode == "bare_or_csr_only" and bool(profile.get("requires_page_tables")):
                self._add(findings, "error", "vm_profile_bare_pages", "bare_or_csr_only profile cannot require page tables", file=str(path))
            if (mode == "blocked" or decision == "blocked") and not str(profile.get("blocked_reason", "")).strip():
                self._add(findings, "error", "vm_profile_blocked_reason", "blocked VM profile must include blocked_reason", file=str(path))
            if self.require_scoped_vm_contract and decision == "blocked":
                blockers = profile.get("blocking_dependencies")
                alternatives = profile.get("alternative_analysis")
                if not isinstance(blockers, list) or not blockers:
                    self._add(findings, "error", "vm_profile_blocking_dependencies", "blocked profile must contain non-empty blocking_dependencies", file=str(path), profile=profile.get("profile_id"))
                else:
                    for blocker_index, blocker in enumerate(blockers):
                        required = {"capability", "required_for", "evidence", "reason", "upstream_action"}
                        if not isinstance(blocker, dict) or not required.issubset(blocker):
                            self._add(findings, "error", "vm_profile_blocking_dependencies", f"blocking_dependencies[{blocker_index}] is missing scoped blocker fields", file=str(path), profile=profile.get("profile_id"))
                            continue
                        required_for = self._string_set(blocker.get("required_for"))
                        if not required_for:
                            self._add(findings, "error", "vm_profile_blocking_dependencies", "blocking dependency required_for must identify affected operations/subcases", file=str(path), profile=profile.get("profile_id"))
                required_alternatives = {"evaluated", "conclusion"}
                missing_alternatives = (
                    sorted(required_alternatives - set(alternatives))
                    if isinstance(alternatives, dict)
                    else sorted(required_alternatives)
                )
                if missing_alternatives:
                    profile_id = profile.get("profile_id") or index
                    self._add(
                        findings,
                        "error",
                        "vm_profile_alternative_analysis",
                        f"profiles[{profile_id}].alternative_analysis is missing {missing_alternatives}",
                        file=str(path),
                        profile=profile.get("profile_id"),
                        field_path=f"profiles[{index}].alternative_analysis",
                        missing=missing_alternatives,
                        expected={
                            "evaluated": [
                                "suite_local_resources",
                                "positive_subset",
                                "native_entrypoint",
                                "generation_vs_validation_scope",
                            ],
                            "conclusion": "why only this profile/subcase remains blocked",
                        },
                    )
            page_table_modes = {
                "single_stage": {"s_stage"},
                "g_stage_only": {"g_stage"},
                "two_stage": {"vs_stage", "g_stage"},
            }
            requires_page_tables = bool(profile.get("requires_page_tables"))
            if mode in page_table_modes and not requires_page_tables:
                self._add(
                    findings,
                    "error",
                    "vm_profile_page_tables",
                    f"{mode} profile must set requires_page_tables=true",
                    file=str(path),
                    profile=profile.get("profile_id"),
                )
            if self.require_scoped_vm_contract and requires_page_tables and mode in page_table_modes:
                translation = profile.get("translation")
                required_translation = {
                    *page_table_modes[mode],
                    "activation_order",
                    "bare_restore_order",
                }
                missing_translation = (
                    sorted(required_translation - set(translation))
                    if isinstance(translation, dict)
                    else sorted(required_translation)
                )
                if missing_translation:
                    profile_id = profile.get("profile_id") or index
                    self._add(
                        findings,
                        "error",
                        "vm_profile_translation",
                        f"profiles[{profile_id}].translation is missing {missing_translation}",
                        file=str(path),
                        profile=profile.get("profile_id"),
                        field_path=f"profiles[{index}].translation",
                        missing=missing_translation,
                        expected={
                            "required_stages": sorted(page_table_modes[mode]),
                            "activation_order": "ordered table and control-register activation",
                            "bare_restore_order": "ordered restoration to framework state",
                        },
                    )
                if not self._string_set(profile.get("fences")):
                    profile_id = profile.get("profile_id") or index
                    self._add(
                        findings,
                        "error",
                        "vm_profile_translation",
                        f"profiles[{profile_id}].fences must be a non-empty list",
                        file=str(path),
                        profile=profile.get("profile_id"),
                        field_path=f"profiles[{index}].fences",
                        expected="fences required by the selected manual translation mode",
                    )
            if self.require_scoped_vm_contract and decision == "experimental":
                required_experimental = {
                    "validation_status",
                    "limitations",
                    "promotion_requirements",
                    "alternative_analysis",
                }
                missing_experimental = sorted(required_experimental - set(profile))
                if missing_experimental:
                    self._add(
                        findings,
                        "error",
                        "vm_profile_experimental_schema",
                        f"profiles[{profile.get('profile_id') or index}] is missing {missing_experimental}",
                        file=str(path),
                        profile=profile.get("profile_id"),
                        field_path=f"profiles[{index}]",
                        missing=missing_experimental,
                    )
                alternatives = profile.get("alternative_analysis")
                evaluated = (
                    self._string_set(alternatives.get("evaluated"))
                    if isinstance(alternatives, dict)
                    else set()
                )
                expected_evaluated = {
                    "suite_local_resources",
                    "positive_subset",
                    "native_entrypoint",
                    "generation_vs_validation_scope",
                }
                if (
                    evaluated != expected_evaluated
                    or not isinstance(alternatives, dict)
                    or not str(alternatives.get("conclusion", "")).strip()
                ):
                    self._add(
                        findings,
                        "error",
                        "vm_profile_experimental_alternative_analysis",
                        "experimental profile must evaluate all four alternatives and record a conclusion",
                        file=str(path),
                        profile=profile.get("profile_id"),
                    )
                if (
                    not self._nonempty_string_list(profile.get("limitations"))
                    or not self._nonempty_string_list(
                        profile.get("promotion_requirements")
                    )
                ):
                    self._add(
                        findings,
                        "error",
                        "vm_profile_experimental_schema",
                        "experimental profile limitations and promotion_requirements must be non-empty",
                        file=str(path),
                        profile=profile.get("profile_id"),
                    )
        return summary

    def _check_experimental_manifest(
        self,
        root: Path,
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate isolated, non-gating candidate assets without pairing them to main ELFs."""
        summary = {"assets": 0, "unverified": 0, "missing_files": 0}
        if not self.validate_experimental_assets or not self.experimental_manifest:
            return summary
        path = Path(self.experimental_manifest).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            self._add(
                findings,
                "error",
                "experimental_manifest_exists",
                f"experimental asset validation was requested but the manifest is absent: {path}",
                file=str(path),
            )
            return summary
        if yaml is None:
            self._add(findings, "error", "experimental_manifest_parse", "PyYAML is required", file=str(path))
            return summary
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            self._add(findings, "error", "experimental_manifest_parse", str(exc), file=str(path))
            return summary
        assets = data.get("assets") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(assets, list):
            self._add(
                findings,
                "error",
                "experimental_manifest_schema",
                "experimental manifest must contain schema_version: 1 and an assets list",
                file=str(path),
            )
            return summary
        allowed_statuses = {
            "generated",
            "static_checked",
            "build_blocked",
            "runtime_blocked",
            "coverage_blocked",
        }
        allowed_kinds = {
            "generator_fragment",
            "assembly_candidate",
            "auxiliary_config",
            "coverage_candidate",
            "analysis",
        }
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                self._add(findings, "error", "experimental_asset_schema", f"assets[{index}] must be a mapping", file=str(path))
                continue
            required = {"id", "path", "kind", "validation_status", "limitations", "promotion_requirements", "affected_targets"}
            missing = sorted(required - set(asset))
            if missing:
                self._add(
                    findings,
                    "error",
                    "experimental_asset_schema",
                    f"assets[{index}] is missing {missing}",
                    file=str(path),
                    field_path=f"assets[{index}]",
                    missing=missing,
                )
                continue
            summary["assets"] += 1
            status = str(asset.get("validation_status", "")).strip()
            kind = str(asset.get("kind", "")).strip()
            if status not in allowed_statuses:
                self._add(
                    findings,
                    "error",
                    "experimental_asset_status",
                    f"assets[{index}].validation_status must be one of {sorted(allowed_statuses)}",
                    file=str(path),
                    field_path=f"assets[{index}].validation_status",
                )
            if kind not in allowed_kinds:
                self._add(
                    findings,
                    "error",
                    "experimental_asset_kind",
                    f"assets[{index}].kind must be one of {sorted(allowed_kinds)}",
                    file=str(path),
                    field_path=f"assets[{index}].kind",
                )
            limitations = self._string_set(asset.get("limitations"))
            promotions = self._string_set(asset.get("promotion_requirements"))
            targets = self._string_set(asset.get("affected_targets"))
            if not limitations or not promotions or not targets:
                self._add(
                    findings,
                    "error",
                    "experimental_asset_scope",
                    f"assets[{index}] must record non-empty limitations, promotion_requirements, and affected_targets",
                    file=str(path),
                )
            asset_path = Path(str(asset.get("path", ""))).expanduser()
            if not asset_path.is_absolute():
                workspace_candidate = root / asset_path
                manifest_candidate = path.parent / asset_path
                asset_path = (
                    workspace_candidate
                    if workspace_candidate.is_file()
                    else manifest_candidate
                )
            experimental_root = path.parent.resolve()
            try:
                asset_path.resolve().relative_to(experimental_root)
            except ValueError:
                self._add(
                    findings,
                    "error",
                    "experimental_asset_isolation",
                    f"assets[{index}].path must be under {experimental_root}",
                    file=str(path),
                    asset_path=str(asset_path),
                )
            if not asset_path.is_file():
                summary["missing_files"] += 1
                self._add(
                    findings,
                    "error",
                    "experimental_asset_exists",
                    f"experimental asset is missing: {asset_path}",
                    file=str(path),
                    asset_path=str(asset_path),
                )
            summary["unverified"] += 1
        if summary["unverified"]:
            self._add(
                findings,
                "warning",
                "experimental_assets_limited",
                f"{summary['unverified']} experimental asset(s) remain isolated and not fully validated; main contribution gates ignore them",
                file=str(path),
                unverified=summary["unverified"],
            )
        return summary

    def _check_generation_scope_consistency(
        self,
        state: dict[str, Any] | None,
        contract: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> None:
        if not self.require_generation_scope or not state or contract.get("no_vm"):
            return
        scope = state.get("generation_scope")
        if not isinstance(scope, dict):
            return
        allowed = set(contract.get("allowed_targets", set()))
        blocked = set(contract.get("blocked_targets", set()))
        expected_partial = allowed & blocked
        expected_blocked = blocked - allowed
        generated = self._string_set(scope.get("generated_targets"))
        partial = self._string_set(scope.get("partial_targets"))
        blocked_targets = self._string_set(scope.get("blocked_targets"))
        comparisons = (
            ("generated_targets", generated, allowed),
            ("partial_targets", partial, expected_partial),
            ("blocked_targets", blocked_targets, expected_blocked),
        )
        for field, actual, expected in comparisons:
            if actual != expected:
                self._add(
                    findings,
                    "error",
                    "validation_coverage_contract",
                    f"generation scope {field} does not match VM/resource profile decisions",
                    field=field,
                    missing=sorted(expected - actual),
                    extra=sorted(actual - expected),
                )

    def _check_elf_files(
        self,
        paths: list[Path],
        findings: list[dict[str, Any]],
        prefix: str,
    ) -> set[str]:
        stems: set[str] = set()
        for path in paths:
            stems.add(path.stem)
            try:
                data = path.read_bytes()
            except OSError as exc:
                self._add(findings, "error", f"{prefix}_read", str(exc), file=str(path))
                continue
            if self.require_nonempty and not data:
                self._add(findings, "error", f"{prefix}_nonempty", "ELF is empty", file=str(path))
            if data[:4] != b"\x7fELF":
                self._add(findings, "error", f"{prefix}_format", "artifact is not an ELF file", file=str(path))
            elif len(data) < 5 or data[4] not in (1, 2):
                self._add(findings, "error", f"{prefix}_class", "ELF has an invalid or missing EI_CLASS (expected RV32 or RV64)", file=str(path))
        return stems

    def _check_data_files(
        self,
        paths: list[Path],
        findings: list[dict[str, Any]],
        prefix: str,
    ) -> None:
        for path in paths:
            try:
                data = path.read_bytes()
            except OSError as exc:
                self._add(findings, "error", f"{prefix}_read", str(exc), file=str(path))
                continue
            if self.require_nonempty and not data:
                self._add(findings, "error", f"{prefix}_nonempty", "file is empty", file=str(path))

    @staticmethod
    def _testcase_descriptor_count(source_text: str) -> int:
        return len(
            set(
                re.findall(
                    r'(?m)^\s*([A-Za-z_][\w$]*_str):\s*\.string\s+.*?\bcp:\s*[^;\"]+;\s*bin:',
                    source_text,
                )
            )
        )

    def _check_signature_progress(
        self,
        source: Path,
        result: Path | None,
        findings: list[dict[str, Any]],
        *,
        severity: str = "error",
    ) -> dict[str, Any]:
        """Estimate progress from ACT4 sentinel values.

        This is deliberately not a proof that individual testcase slots were
        written: framework records may precede testcase data and a valid result
        may equal the sentinel.  Workflows should therefore use warning mode
        unless the generated format supplies explicit testcase slot metadata.
        """
        try:
            source_text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._add(findings, severity, "signature_progress_source", str(exc), file=str(source))
            return {"testcases": 0, "completed_prefix": 0}
        testcase_count = self._testcase_descriptor_count(source_text)
        if testcase_count == 0:
            self._add(
                findings,
                severity,
                "signature_progress_source",
                "generated source has no testcase descriptors for progress validation",
                file=str(source),
            )
            return {"testcases": 0, "completed_prefix": 0}
        if result is None:
            self._add(
                findings,
                severity,
                "signature_progress_result",
                f"source has no matching .results file: {source.stem}",
                file=str(source),
            )
            return {"testcases": testcase_count, "completed_prefix": 0}
        try:
            result_text = result.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._add(findings, severity, "signature_progress_result", str(exc), file=str(result))
            return {"testcases": testcase_count, "completed_prefix": 0}
        main_region = result_text.split("final_trap_sig_offset:", 1)
        if len(main_region) != 2:
            self._add(
                findings,
                severity,
                "signature_progress_boundary",
                "results file lacks final_trap_sig_offset boundary",
                file=str(result),
            )
            return {"testcases": testcase_count, "completed_prefix": 0}
        records = [
            value.lower().lstrip("0") or "0"
            for value in re.findall(
                r"(?m)^\s*\.(?:quad|word)\s+0x([0-9a-fA-F]+)\b",
                main_region[0],
            )
        ]
        unwritten = {"deadbeef", "deadbeefdeadbeef"}
        completed_prefix = 0
        for value in records:
            if value in unwritten:
                break
            completed_prefix += 1
        if completed_prefix < testcase_count:
            self._add(
                findings,
                severity,
                "signature_progress",
                "reference result reached SUCCESS before the minimum testcase signature progress",
                file=str(result),
                expected_minimum=testcase_count,
                completed_prefix=completed_prefix,
            )
        return {
            "testcases": testcase_count,
            "completed_prefix": completed_prefix,
            "main_region_records": len(records),
        }

    def _check_reference_model_outputs(
        self,
        sources: list[Path],
        signatures: list[Path],
        results: list[Path],
        logs: list[Path],
        findings: list[dict[str, Any]],
        *,
        native_elfs: list[Path] | None = None,
    ) -> dict[str, Any]:
        """Prove that each reference run filled its complete signature region."""
        signature_by_stem = {path.stem: path for path in signatures}
        result_by_stem = {path.stem: path for path in results}
        log_by_stem = {
            path.name.removesuffix(".sig.log"): path
            for path in logs
            if path.name.endswith(".sig.log")
        }
        checked = 0
        complete = 0
        progress: dict[str, dict[str, Any]] = {}
        widths: dict[str, dict[str, Any]] = {}
        elf_xlens: dict[str, set[int]] = {}
        for elf in native_elfs or []:
            xlen = self._elf_xlen(elf)
            if xlen is not None:
                elf_xlens.setdefault(elf.stem, set()).add(xlen)
        for source in sources:
            stem = source.stem
            log_path = log_by_stem.get(stem)
            if log_path is None:
                if self.require_reference_model_logs:
                    self._add(
                        findings,
                        "error",
                        "reference_model_log_match",
                        f"source has no matching .sig.log: {stem}",
                        stem=stem,
                    )
                continue
            checked += 1
            finding_start = len(findings)
            try:
                log_text = log_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self._add(
                    findings,
                    "error",
                    "reference_model_log_read",
                    str(exc),
                    file=str(log_path),
                )
                continue
            marker = (
                f'RVCP-SUMMARY: TEST SIGRUN - Test File "{source.name}"'
            )
            if marker not in log_text:
                self._add(
                    findings,
                    "error",
                    "reference_model_log_marker",
                    f"reference-model log does not identify {source.name}",
                    file=str(log_path),
                )
            success_count = len(re.findall(r"(?m)^[ \t]*SUCCESS[ \t\r]*$", log_text))
            if success_count != 1:
                self._add(
                    findings,
                    "error",
                    "reference_model_log_success",
                    "reference-model log must contain exactly one terminal SUCCESS",
                    file=str(log_path),
                    success_count=success_count,
                )
            if re.search(
                r"(?im)^.*(?:timed?\s*out|timeout|fatal|segmentation fault|failure).*$",
                log_text,
            ):
                self._add(
                    findings,
                    "error",
                    "reference_model_log_failure",
                    "reference-model log contains an abnormal termination marker",
                    file=str(log_path),
                )
            result = result_by_stem.get(stem)
            if self.signature_progress_mode != "off":
                progress[stem] = self._check_signature_progress(
                    source,
                    result,
                    findings,
                    severity=self.signature_progress_mode,
                )
            if not self.require_signature_completeness:
                continue
            granularity = re.search(
                r"signature-granularity to\s+(\d+)\s+bytes",
                log_text,
            )
            begin = re.search(r"(?m)^begin_signature:\s*(0x[0-9a-fA-F]+)", log_text)
            end = re.search(r"(?m)^end_signature:\s*(0x[0-9a-fA-F]+)", log_text)
            matched_xlens = elf_xlens.get(stem, set())
            native_width = next(iter(matched_xlens)) // 8 if len(matched_xlens) == 1 else None
            # ACT4 build_plan._ref_model_sig_cmd passes xlen // 8 to both
            # supported models. Sail 0.14 no longer echoes that flag in its log.
            # Use the matching native ELF class, never infer width from record count.
            width = int(granularity.group(1)) if granularity else native_width
            if width is None or not (begin and end):
                self._add(
                    findings,
                    "error",
                    "signature_region_evidence",
                    "signature needs begin/end addresses and granularity from the log or a matching native ELF",
                    file=str(log_path),
                )
                continue
            if native_width is not None and width != native_width:
                self._add(
                    findings, "error", "signature_granularity_conflict",
                    "logged granularity disagrees with ACT4's native XLEN/8 signature command",
                    file=str(log_path), logged_width=width, native_width=native_width,
                )
            widths[stem] = {
                "bytes": width, "source": "log" if granularity else "native_elf_xlen",
                "native_elfs": [str(p) for p in native_elfs or [] if p.stem == stem],
            }
            byte_count = int(end.group(1), 16) - int(begin.group(1), 16)
            if width <= 0 or byte_count <= 0 or byte_count % width:
                self._add(
                    findings,
                    "error",
                    "signature_region_evidence",
                    "signature region is empty or not divisible by granularity",
                    file=str(log_path),
                    bytes=byte_count,
                    granularity=width,
                )
                continue
            expected_records = byte_count // width
            signature = signature_by_stem.get(stem)
            if signature is not None:
                try:
                    signature_text = signature.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    self._add(
                        findings,
                        "error",
                        "signature_read",
                        str(exc),
                        file=str(signature),
                    )
                    continue
                records = [line.strip() for line in signature_text.splitlines() if line.strip()]
                actual_records = len(records)
                invalid_records = [
                    index for index, record in enumerate(records, 1)
                    if not re.fullmatch(r"[0-9a-fA-F]+", record) or len(record) > width * 2
                ]
                if invalid_records:
                    self._add(
                        findings,
                        "error",
                        "signature_record_format",
                        "signature records must be hexadecimal values fitting the declared granularity",
                        file=str(signature),
                        invalid_records=len(invalid_records),
                        first_invalid_record=invalid_records[0],
                    )
                if actual_records != expected_records:
                    self._add(
                        findings,
                        "error",
                        "signature_record_count",
                        "signature record count does not fill the declared region",
                        file=str(signature),
                        expected=expected_records,
                        actual=actual_records,
                    )
            if result is not None:
                try:
                    result_text = result.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    self._add(
                        findings,
                        "error",
                        "signature_results_read",
                        str(exc),
                        file=str(result),
                    )
                    continue
                # sig_modify emits literal data with optional labels and comments.
                data_text = re.sub(r"/\*.*?\*/", "", result_text, flags=re.DOTALL)
                actual_records = 0
                invalid_records = 0
                for line in data_text.splitlines():
                    line = re.split(r"#|//", line, maxsplit=1)[0].strip()
                    line = re.sub(r"^(?:(?:[A-Za-z_.$][\w.$]*|\d+):\s*)+", "", line)
                    directive = re.match(r"^\.(?:quad|word)\b(.*)$", line)
                    if directive is None:
                        continue
                    operands = directive.group(1).split(",")
                    actual_records += len(operands)
                    invalid_records += sum(
                        re.fullmatch(r"[+-]?(?:0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)", value.strip()) is None
                        for value in operands
                    )
                if invalid_records:
                    self._add(
                        findings,
                        "error",
                        "signature_results_record_format",
                        "results data directives must contain integer literals",
                        file=str(result),
                        invalid_records=invalid_records,
                    )
                if actual_records != expected_records:
                    self._add(
                        findings,
                        "error",
                        "signature_results_record_count",
                        "results record count does not fill the declared region",
                        file=str(result),
                        expected=expected_records,
                        actual=actual_records,
                    )
            if signature is not None and result is not None and not any(
                item["severity"] == "error" for item in findings[finding_start:]
            ):
                complete += 1
        return {
            "logs": len(logs),
            "runs_checked": checked,
            "complete_runs_checked": complete,
            "signature_progress": progress,
            "signature_granularity": widths,
        }

    def _read_priv_testcase_limit(
        self, findings: list[dict[str, Any]]
    ) -> int | None:
        """Read the split ceiling from the exact ACT4 source under test."""
        path = (
            self._artifact_root()
            / "generators/testgen/src/testgen/constants.py"
        )
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            self._add(
                findings,
                "error",
                "test_source_split_limit_source",
                f"cannot read TESTCASES_PER_PRIV_FILE: {exc}",
                file=str(path),
            )
            return None
        for node in tree.body:
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "TESTCASES_PER_PRIV_FILE"
                for target in node.targets
            ):
                value = node.value
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "TESTCASES_PER_PRIV_FILE"
            ):
                value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and value.value > 0
            ):
                return value.value
        self._add(
            findings,
            "error",
            "test_source_split_limit_source",
            "current ACT4 does not expose TESTCASES_PER_PRIV_FILE as a positive integer constant",
            file=str(path),
        )
        return None

    def _check_testcase_reachability(
        self,
        sources: list[Path],
        elfs: list[Path],
        findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Reject proved dead source cases and disclose target-specific exclusions."""
        summary: dict[str, Any] = {
            "enabled": self.check_testcase_reachability,
            "source_descriptors": 0,
            "impossible_testcases": 0,
            "sources": {},
            "elfs": [],
            "note": "Compiled labels are not execution hits or functional coverage.",
        }
        if not self.check_testcase_reachability:
            return summary
        nm = reachability.find_nm(self.nm_executable)
        elf_by_stem: dict[str, list[Path]] = {}
        for elf in elfs:
            elf_by_stem.setdefault(elf.stem, []).append(elf)
        unresolved = []
        empty = []
        unavailable = []
        for path in sources:
            try:
                source = reachability.inspect_source(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue  # The ordinary source check reports the read error.
            summary["sources"][str(path)] = {
                key: value for key, value in source.items() if key != "linked_labels"
            }
            summary["sources"][str(path)]["linked_testcases"] = len(source["linked_labels"])
            summary["source_descriptors"] += source["descriptor_count"]
            summary["impossible_testcases"] += len(source["impossible"])
            if source["impossible"]:
                self._add(
                    findings, "error", "testcase_guard_unsatisfiable",
                    "testcase labels are unreachable for both RV32 and RV64; fix generator bounds/guards and regenerate",
                    file=str(path), count=len(source["impossible"]),
                    examples=source["impossible"][:3],
                )
            if source["unresolved_descriptors"] or source["parse_issues"] or not source["descriptor_count"]:
                unresolved.append(str(path))
            if not source["linked_labels"] or source["unresolved_descriptors"] or source["parse_issues"]:
                continue
            if nm:
                for elf in elf_by_stem.get(path.stem, []):
                    record = reachability.inspect_elf(elf, source["linked_labels"], nm)
                    record.update(source=str(path), xlen=self._elf_xlen(elf))
                    summary["elfs"].append(record)
                    if record["compiled_testcases"] is None:
                        unavailable.append(str(elf))
                    elif record["compiled_testcases"] == 0:
                        empty.append(str(elf))
        if unresolved:
            self._add(
                findings, "warning", "testcase_reachability_unverified",
                "some sources lack provable descriptor/label linkage or conditional structure; inspect native preprocessed code",
                files=unresolved,
            )
        if elfs and not nm:
            self._add(
                findings, "warning", "testcase_symbols_unavailable",
                "nm is unavailable; compiled testcase counts are unverified, not zero",
            )
        elif unavailable:
            self._add(
                findings, "warning", "testcase_symbols_unavailable",
                "some ELFs lack readable testcase symbols; compiled counts remain unverified",
                files=unavailable,
            )
        if empty:
            self._add(
                findings, "warning", "testcase_empty_for_target",
                "ELFs contain no recognized testcase entry labels; framework SUCCESS must not count as exercised testcases",
                files=empty,
            )
        summary["empty_elf_files"] = empty
        summary["unverified_source_files"] = unresolved
        summary["compiled_counts_complete"] = bool(elfs) and len(summary["elfs"]) == len(elfs) and not unavailable
        return summary

    def do_check(self, timeout=0, **kwargs: Any) -> tuple[bool, object]:
        """Validate generated ACT4 source files, ELF files, and test headers."""
        root = self._workspace_root()
        findings: list[dict[str, Any]] = []
        sources = self._discover(self.source_files, self.source_patterns)
        elfs = self._discover(self.elf_files, self.elf_patterns)
        artifact_root = self._artifact_root()
        signatures = self._discover(self.signature_files, self.signature_patterns, artifact_root)
        results = self._discover(self.result_files, self.result_patterns, artifact_root)
        reference_logs = self._discover(
            self.reference_model_log_files,
            self.reference_model_log_patterns,
            artifact_root,
        )
        if not signatures:
            signatures = self._discover_sibling_assets(sources, ".sig")
        if not results:
            results = self._discover_sibling_assets(sources, ".results")
        reports = self._check_reports(findings)
        validation_state = self._check_validation_state(root, findings)
        selected_build_root = self._selected_build_root(validation_state)
        selection_unresolved = (
            self.validation_state is not None
            and (
                self.require_reference_model_logs
                or self.require_signature_completeness
                or self.signature_progress_mode != "off"
            )
            and selected_build_root is None
        )
        if selection_unresolved:
            self._add(
                findings,
                "error",
                "validation_self_check_build_root",
                "cannot select reference artifacts: self_checking.command must specify "
                "CONFIG_FILES and WORKDIR, and the readable config must contain a valid name",
            )
            elfs, signatures, results, reference_logs = [], [], [], []
        if selected_build_root is not None:
            elfs, signatures, results, reference_logs = [
                [path for path in paths if path.resolve().is_relative_to(selected_build_root)]
                for paths in (elfs, signatures, results, reference_logs)
            ]
        vm_contract_summary = self._check_vm_contract(root, findings)
        if self.require_matching_xlen and isinstance(validation_state, dict):
            state_xlens = {
                int(value)
                for value in validation_state.get("supported_xlens", [])
                if value in {32, 64}
            }
            contract_xlens = set(vm_contract_summary.get("supported_xlens", set()))
            selected_xlens = set(vm_contract_summary.get("target_xlen", set()))
            expected_xlens = contract_xlens or selected_xlens
            if expected_xlens and state_xlens != expected_xlens:
                self._add(
                    findings,
                    "error",
                    "validation_xlen_contract",
                    "validation supported_xlens does not match the VM/resource contract",
                    missing=sorted(expected_xlens - state_xlens),
                    extra=sorted(state_xlens - expected_xlens),
                )
        self._check_generation_scope_consistency(validation_state, vm_contract_summary, findings)
        experimental_summary = self._check_experimental_manifest(root, findings)
        testcase_limit = self.max_testcases_per_source
        if self.derive_priv_testcase_limit:
            testcase_limit = self._read_priv_testcase_limit(findings)

        if not sources:
            self._add(findings, "error", "test_sources_exist", "no generated ACT4 source files were found")
        if not elfs and not selection_unresolved:
            self._add(findings, "error", "test_elfs_exist", "no compiled ACT4 ELF files were found")
        if self.require_signature and not signatures and not selection_unresolved:
            self._add(findings, "error", "signature_files_exist", "no reference-model signature files were found")
        if self.require_results and not results and not selection_unresolved:
            self._add(findings, "error", "signature_results_exist", "no processed reference-model results were found")

        source_stems: set[str] = set()
        source_xlen: dict[str, set[int]] = {}
        xlen_evidence: dict[str, dict[str, Any]] = {}
        elf_xlen_by_stem: dict[str, set[int]] = {}
        for path in elfs:
            elf_xlen = self._elf_xlen(path)
            if elf_xlen is not None:
                elf_xlen_by_stem.setdefault(path.stem, set()).add(elf_xlen)
        for path in sources:
            source_stems.add(path.stem)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self._add(findings, "error", "test_source_read", str(exc), file=str(path))
                continue
            if self.require_nonempty and not text.strip():
                self._add(findings, "error", "test_source_nonempty", "generated source is empty", file=str(path))
            if testcase_limit is not None:
                testcase_count = len(
                    re.findall(
                        r"(?m)^\s*[A-Za-z_][\w$]*_str:\s*\.string\b",
                        text,
                    )
                )
                if testcase_count > testcase_limit:
                    self._add(
                        findings,
                        "warning" if self.derive_priv_testcase_limit else "error",
                        "test_source_split_limit",
                        "source exceeds the split limit; review whether one native indivisible chunk requires it",
                        file=str(path),
                        actual=testcase_count,
                        maximum=testcase_limit,
                    )
            resolved_xlen, evidence = self._resolve_source_xlen(
                path,
                text,
                set(vm_contract_summary.get("target_xlen", set())),
                elf_xlen_by_stem.get(path.stem, set()),
                findings,
            )
            if resolved_xlen:
                source_xlen[path.stem] = resolved_xlen
            xlen_evidence[str(path)] = evidence
            if self.validate_test_config:
                self._check_test_config(text, path, findings)
            for marker in self.source_markers:
                if marker not in text:
                    self._add(
                        findings,
                        "error",
                        "test_source_marker",
                        f"generated source is missing required marker {marker!r}",
                        file=str(path),
                    )
            if self.source_marker_any and not any(marker in text for marker in self.source_marker_any):
                self._add(
                    findings,
                    "error",
                    "test_source_marker_any",
                    f"generated source is missing all accepted ACT4 entry markers: {self.source_marker_any!r}",
                    file=str(path),
                )
            for pattern in self.forbidden_patterns:
                if pattern.search(text):
                    self._add(
                        findings,
                        "error",
                        "test_source_placeholder",
                        f"generated source contains forbidden placeholder pattern {pattern.pattern!r}",
                        file=str(path),
                    )

        elf_stems = self._check_elf_files(elfs, findings, "test_elf")
        if self.require_matching_xlen:
            for path in elfs:
                expected = source_xlen.get(path.stem)
                if not expected or len(expected) != 1:
                    continue
                actual = self._elf_xlen(path)
                if actual is not None and actual not in expected:
                    self._add(findings, "error", "elf_xlen_match", f"test_elf XLEN ({actual}) does not match source MARCH ({sorted(expected)})", file=str(path), expected=sorted(expected), actual=actual)
        self._check_data_files(signatures, findings, "signature")
        self._check_data_files(results, findings, "signature_results")
        reference_summary = self._check_reference_model_outputs(
            sources if not selection_unresolved else [],
            signatures,
            results,
            reference_logs,
            findings,
            native_elfs=elfs,
        )
        testcase_reachability = self._check_testcase_reachability(
            sources, elfs, findings,
        )

        if self.require_matching_stems and sources and elfs:
            for stem in sorted(source_stems - elf_stems):
                self._add(findings, "error", "test_elf_match", f"source has no matching ELF: {stem}", stem=stem)
            for stem in sorted(elf_stems - source_stems):
                self._add(findings, "error", "test_source_match", f"ELF has no matching source: {stem}", stem=stem)
        if self.require_matching_stems and sources:
            for label, paths in (("signature", signatures), ("result", results)):
                if not paths:
                    continue
                stems = {path.stem.removesuffix(".sig") for path in paths}
                for stem in sorted(source_stems - stems):
                    self._add(findings, "error", f"{label}_match", f"source has no matching {label} artifact: {stem}", stem=stem)
                for stem in sorted(stems - source_stems):
                    self._add(findings, "error", f"{label}_source_match", f"{label} artifact has no matching source: {stem}", stem=stem)
        errors = sum(item["severity"] == "error" for item in findings)
        warnings = sum(item["severity"] == "warning" for item in findings)
        report = {
            "status": "failed" if errors else "complete",
            "summary": {"errors": errors, "warnings": warnings},
            "checks": {
                "artifact_root": str(artifact_root),
                "source_files": len(sources),
                "elf_files": len(elfs),
                "signature_files": len(signatures),
                "result_files": len(results),
                "reference_model_logs": reference_summary["logs"],
                "reference_runs_checked": reference_summary["runs_checked"],
                "complete_reference_runs": reference_summary[
                    "complete_runs_checked"
                ],
                "signature_progress": reference_summary["signature_progress"],
                "signature_granularity": reference_summary["signature_granularity"],
                "report_files": len(reports),
                "source_stems": sorted(source_stems),
                "elf_stems": sorted(elf_stems),
                "validation_state": self.validation_state,
                "self_check_model": (validation_state or {}).get("self_checking", {}).get("model"),
                "sail_coverage_passed": (validation_state or {}).get("sail_coverage", {}).get("passed"),
                "contribution_ready": (validation_state or {}).get("contribution_ready"),
                "generation_scope": (validation_state or {}).get("generation_scope"),
                "vm_contract_targets": {
                    "allowed": sorted(vm_contract_summary.get("allowed_targets", set())),
                    "blocked": sorted(vm_contract_summary.get("blocked_targets", set())),
                    "experimental": sorted(vm_contract_summary.get("experimental_targets", set())),
                },
                "xlen_evidence": xlen_evidence,
                "experimental_assets": experimental_summary,
                "max_testcases_per_source": testcase_limit,
                "testcase_reachability": testcase_reachability,
            },
            "findings": findings,
        }
        if self.output_dir:
            output_dir = Path(self.output_dir).expanduser()
            if not output_dir.is_absolute():
                output_dir = root / output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "test-assets.json"
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            report["report_file"] = str(report_path)
        if errors:
            return False, {"error": findings, "report": report}
        return True, {"message": "ACT4 generated test asset check passed", "report": report}


__all__ = ["ACT4TestAssetChecker"]
