"""Best-version finalization, documentation sync, and delivery gates."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
from typing import Any
import yaml
from ucagent.checkers.base import Checker
from ucagent.util.log import info
from ..contracts import (
    atomic_json,
    atomic_text,
    diagnostic,
    finite_number,
    load_fenced_yaml,
    load_json,
    no_improvement_patience,
    no_regression_metric_categories,
    optimization_limits,
    ppa_score_weights,
    resolve_workspace_path,
    resolved_output,
    sha256_file,
)
from ..rtl import (
    discover_rtl_libraries,
    discover_rtl_sources,
    resolve_rtl_config,
)

from .common import (
    _inline_reason,
    _cfg_dut,
    _contract_identity,
    _hash_rows,
    _rows_sha256,
    _validated_file_rows,
    _validated_input_identity,
)
from .evidence import (
    _load_final_toffee_report,
    _public_evidence_error,
    _pytest_evidence,
    _redact_backend_output,
    _write_toffee_snapshot,
)
from .ppa_iteration import (
    _PPA_SCORE_ID,
    _embed_dashboard_snapshot,
    _load_bound_ledger,
    _load_cached_ppa,
    _ppa_primary_metrics,
    _ppa_score_formula,
    _ppa_selection_score,
    _resolved_workflow_ppa_config,
    _restore_rtl_snapshot,
    select_best_accepted_record,
)
from .runtime import (
    _parse_collected_final_nodes,
)
from . import runtime  # qualified so tests patch one runtime module


class PPABestVersionChecker(Checker):
    """Restore and bind the deterministic best accepted version after optimization."""

    def __init__(
        self,
        ledger_file: str,
        final_report_file: str,
        cfg: Any,
        **kwargs: Any,
    ) -> None:
        """Store finalization artifact paths without inspecting optimization state."""

        super().__init__()
        del kwargs
        self.ledger_file = ledger_file
        self.final_report_file = final_report_file
        self.cfg = cfg
        self.rtl_config, self.rtl_language_backend = resolve_rtl_config(cfg)

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Select the best accepted record, restore its snapshot, and bind final PPA."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        state_path = workspace / ".ucagent" / "design_with_ppa" / "state.json"
        try:
            state = load_json(state_path)
            ledger = _load_bound_ledger(workspace, state, self.ledger_file)
            if (
                state.get("schema_version") != "1.5"
                or ledger.get("schema_version") != "1.5"
            ):
                raise ValueError("optimization state schema_version is invalid")
            if state.get("status") != "complete":
                raise ValueError("candidate optimization has not reached a terminal state")
            records = ledger.get("records")
            if not isinstance(records, list) or not records:
                raise ValueError("optimization ledger contains no evaluated versions")
            tolerance = ledger.get("tolerance")
            if not isinstance(tolerance, dict):
                raise ValueError("optimization ledger tolerance is invalid")
            best = select_best_accepted_record(
                records,
                rel_tol=finite_number(
                    tolerance.get("relative"), "relative tolerance"
                ),
                abs_tol=finite_number(
                    tolerance.get("absolute"), "absolute tolerance"
                ),
                categories=no_regression_metric_categories(self.cfg),
            )
            if (
                state.get("best_iteration") != best.get("iteration")
                or state.get("best_report_id") != best.get("ppa_report_id")
                or ledger.get("best_iteration") != best.get("iteration")
                or ledger.get("best_report_id") != best.get("ppa_report_id")
            ):
                raise ValueError(
                    "persisted best-version identity differs from Pareto selection"
                )
            snapshot_value = best.get("accepted_snapshot") or best.get("snapshot")
            if not isinstance(snapshot_value, str) or not snapshot_value:
                raise ValueError("best accepted version has no immutable RTL snapshot")
            snapshot = resolve_workspace_path(
                workspace, snapshot_value, must_exist=True
            )
            snapshot_manifest = load_json(snapshot / "snapshot.json")
            snapshot_rows = snapshot_manifest.get("rtl_sources")
            if (
                snapshot_manifest.get("schema_version") != "1.1"
                or snapshot_manifest.get("rtl_language") != self.rtl_config.language
                or snapshot_manifest.get("snapshot_sha256") != best.get("rtl_sha256")
                or not isinstance(snapshot_rows, list)
                or not snapshot_rows
                or _rows_sha256(snapshot_rows) != best.get("rtl_sha256")
            ):
                raise ValueError("best accepted RTL snapshot manifest is invalid")
            for row in snapshot_rows:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("path"), str)
                    or not isinstance(row.get("sha256"), str)
                ):
                    raise ValueError("best accepted RTL snapshot source row is invalid")
                snapshot_source = resolve_workspace_path(
                    snapshot, row["path"], must_exist=True
                )
                if sha256_file(snapshot_source) != row["sha256"]:
                    raise ValueError(
                        f"best accepted RTL snapshot hash mismatch: {row['path']}"
                    )
            cached_report = _load_cached_ppa(
                workspace, best.get("ppa_report_id")
            )
            if cached_report.get("status") != "success":
                raise ValueError("best accepted PPA report is incomplete")
            final_report_path = resolve_workspace_path(
                workspace, self.final_report_file
            )
            current_files = list(
                discover_rtl_sources(
                    workspace, self.rtl_config, self.rtl_language_backend
                )
            )
            current_hash = _rows_sha256(_hash_rows(workspace, current_files))
            finalized_identity = (
                state.get("finalized_iteration"),
                state.get("finalized_report_id"),
                state.get("finalized_rtl_sha256"),
            )
            expected_identity = (
                best["iteration"],
                best["ppa_report_id"],
                best["rtl_sha256"],
            )
            identity_is_present = any(value is not None for value in finalized_identity)
            if identity_is_present and finalized_identity != expected_identity:
                raise ValueError(
                    "persisted finalized identity differs from the selected best version"
                )
            history_commit = state.get("finalized_history_commit")
            history_has_commit = getattr(self.stage, "hist_has_commit", None)
            if history_commit is not None and (
                not callable(history_has_commit)
                or not history_has_commit(history_commit)
            ):
                raise ValueError("best-version finalization history commit is invalid")
            if (
                finalized_identity == expected_identity
                and history_commit is not None
                and current_hash == best["rtl_sha256"]
                and final_report_path.is_file()
                and load_json(final_report_path) == cached_report
            ):
                return True, {
                    "message": "The verified best accepted RTL and PPA report are finalized.",
                    "best_iteration": best["iteration"],
                    "best_report_id": best["ppa_report_id"],
                    "rtl_source_sha256": current_hash,
                    "final_report": final_report_path.relative_to(workspace).as_posix(),
                }
            restored_hash = _restore_rtl_snapshot(
                workspace, snapshot, current_files
            )
            if restored_hash != best.get("rtl_sha256"):
                raise ValueError(
                    "restored best RTL hash differs from the accepted record"
                )
            final_report_path.parent.mkdir(parents=True, exist_ok=True)
            cached_report_path = (
                workspace
                / ".ucagent"
                / "ppa_reports"
                / f"{best['ppa_report_id']}.json"
            )
            shutil.copy2(cached_report_path, final_report_path)
            if load_json(final_report_path) != cached_report:
                raise ValueError(
                    "final PPA report copy differs from immutable cache"
                )
            state["finalized_iteration"] = best["iteration"]
            state["finalized_rtl_sha256"] = restored_hash
            state["finalized_report_id"] = best["ppa_report_id"]
            state["finalized_history_commit"] = None
            atomic_json(state_path, state)
            history_commit = self.stage.hist_snapshot(
                f"DesignWithPPA best version {best['iteration']:03d} finalized"
            )
            state["finalized_history_commit"] = history_commit
            atomic_json(state_path, state)
        except (OSError, ValueError, FileNotFoundError, KeyError, RuntimeError) as exc:
            return False, diagnostic(
                "ppa_best_version_finalization_invalid",
                "The verified best accepted RTL and its final PPA report could not be finalized.",
                (
                    "Do not edit optimization records, preserved versions, or PPA reports. "
                    "Call Check once so the workflow can select and restore the verified best "
                    "version. If the same diagnostic repeats, restart "
                    "ppa_best_version_finalization; return to ppa_candidate_optimization only "
                    "when its public Check result is itself incomplete."
                ),
                artifact=self.final_report_file,
                location="ppa_best_version_finalization",
                observed={"reason": _public_evidence_error(str(exc))},
                expected="The unique best accepted all-pass version is restored and its complete PPA report is copied without modification.",
            )
        return True, {
            "message": "The verified best accepted RTL and PPA report are finalized.",
            "best_iteration": best["iteration"],
            "best_report_id": best["ppa_report_id"],
            "rtl_source_sha256": restored_hash,
            "final_report": final_report_path.relative_to(workspace).as_posix(),
        }


_FINAL_RTL_SYNC_BLOCK_RE = re.compile(
    r"\n## Final RTL synchronization\s*\n\n```yaml\n.*?\n```\n?",
    re.DOTALL,
)


def _render_final_rtl_sync_block(payload: dict[str, Any]) -> str:
    """Render the deterministic final-RTL identity appendix for one Markdown document."""

    body = yaml.safe_dump(
        {"rtl_synchronization": payload},
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    return f"\n\n## Final RTL synchronization\n\n```yaml\n{body}\n```\n"


def _replace_final_rtl_sync_block(
    content: str, payload: dict[str, Any]
) -> str:
    """Replace or append exactly one generated final-RTL identity appendix."""

    heading_count = len(
        re.findall(r"(?m)^## Final RTL synchronization\s*$", content)
    )
    matches = list(_FINAL_RTL_SYNC_BLOCK_RE.finditer(content))
    if heading_count > 1 or len(matches) > 1:
        raise ValueError("document contains more than one final RTL synchronization section")
    block = _render_final_rtl_sync_block(payload)
    if matches:
        match = matches[0]
        return content[: match.start()] + block + content[match.end() :]
    if heading_count:
        raise ValueError(
            "final RTL synchronization heading must be followed by one fenced YAML block"
        )
    return content.rstrip() + block


class DesignDocumentationSyncChecker(Checker):
    """Synchronize design documents with the final RTL and all-pass receipt."""

    def __init__(
        self,
        documentation_files: list[str],
        rtl_manifest_file: str,
        final_validation_file: str,
        sync_manifest_file: str,
        cfg: Any,
        **kwargs: Any,
    ) -> None:
        """Store document and evidence paths without scanning authored files."""

        super().__init__()
        del kwargs
        if not isinstance(documentation_files, list) or not documentation_files:
            raise ValueError("documentation_files must be a non-empty list")
        if any(not isinstance(path, str) or not path for path in documentation_files):
            raise ValueError("documentation_files entries must be non-empty strings")
        if len(set(documentation_files)) != len(documentation_files):
            raise ValueError("documentation_files must not contain duplicates")
        for name, value in (
            ("rtl_manifest_file", rtl_manifest_file),
            ("final_validation_file", final_validation_file),
            ("sync_manifest_file", sync_manifest_file),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        self.documentation_files = list(documentation_files)
        self.rtl_manifest_file = rtl_manifest_file
        self.final_validation_file = final_validation_file
        self.sync_manifest_file = sync_manifest_file
        self.cfg = cfg

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require final RTL identity, all passing tests, and synchronized documents."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        failure_artifact = self.rtl_manifest_file
        failure_location = self.rtl_manifest_file
        try:
            manifest_path = resolve_workspace_path(
                workspace, self.rtl_manifest_file, must_exist=True
            )
            manifest = load_json(manifest_path)
            if manifest.get("schema_version") != "1.4":
                raise ValueError("RTL backend manifest schema_version is invalid")
            top_module = manifest.get("top_module")
            rtl_language = manifest.get("rtl_language")
            if not isinstance(top_module, str) or not top_module:
                raise ValueError("RTL backend manifest top_module is missing")
            if not isinstance(rtl_language, str) or not rtl_language:
                raise ValueError("RTL backend manifest rtl_language is missing")
            source_rows = manifest.get("rtl_sources")
            source_files = _validated_file_rows(
                workspace, source_rows, "RTL backend manifest rtl_sources"
            )
            current_source_rows = _hash_rows(workspace, source_files)
            if source_rows != current_source_rows:
                raise ValueError("final RTL source hashes do not match the backend identity")
            source_sha256 = _rows_sha256(current_source_rows)

            failure_artifact = self.final_validation_file
            failure_location = self.final_validation_file
            validation_path = resolve_workspace_path(
                workspace, self.final_validation_file, must_exist=True
            )
            validation = load_json(validation_path)
            if validation.get("schema_version") != "1.0":
                raise ValueError("final all-TC validation schema_version is invalid")
            if validation.get("status") != "pass":
                raise ValueError("final all-TC validation did not pass")
            if validation.get("same_test_cases") is not True:
                raise ValueError("final Python and RTL test-case sets differ")
            python_result = validation.get("python")
            rtl_result = validation.get("rtl")
            if (
                not isinstance(python_result, dict)
                or python_result.get("status") != "pass"
                or not isinstance(rtl_result, dict)
                or rtl_result.get("status") != "pass"
            ):
                raise ValueError("final Python and RTL regression status is incomplete")
            test_case_count = validation.get("test_case_count")
            test_source_sha256 = validation.get("test_source_sha256")
            if (
                isinstance(test_case_count, bool)
                or not isinstance(test_case_count, int)
                or test_case_count < 1
                or not isinstance(test_source_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", test_source_sha256)
            ):
                raise ValueError("final test-source identity is invalid")
            toffee_report = validation.get("toffee_report")
            if (
                not isinstance(toffee_report, dict)
                or toffee_report.get("all_test_cases") is not True
                or not isinstance(toffee_report.get("report_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", toffee_report["report_sha256"])
            ):
                raise ValueError("final Toffee report does not cover all test cases")

            output_root = resolve_workspace_path(workspace, resolved_output(self.cfg))
            unwanted_bug_documents = sorted(
                path.relative_to(workspace).as_posix()
                for path in output_root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and (
                    path.name.endswith("_bug_analysis.md")
                    or path.name.endswith("_static_bug_analysis.md")
                )
            )
            if unwanted_bug_documents:
                failure_artifact = unwanted_bug_documents[0]
                failure_location = unwanted_bug_documents[0]
                raise ValueError(
                    "design workflows must not publish Bug-analysis documents: "
                    + ", ".join(unwanted_bug_documents[:20])
                )

            sync_payload = {
                "schema_version": "1.0",
                "status": "pass",
                "rtl_language": rtl_language,
                "top_module": top_module,
                "source_files": [row["path"] for row in current_source_rows],
                "rtl_source_sha256": source_sha256,
                "all_test_cases_passed": True,
                "test_case_count": test_case_count,
                "test_source_sha256": test_source_sha256,
                "toffee_report_sha256": toffee_report["report_sha256"],
            }
            document_rows = []
            for document_file in self.documentation_files:
                failure_artifact = document_file
                failure_location = document_file
                document_path = resolve_workspace_path(
                    workspace, document_file, must_exist=True
                )
                if document_path.is_symlink() or not document_path.is_file():
                    raise ValueError(
                        f"documentation file is not a regular file: {document_file}"
                    )
                content = document_path.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError(f"documentation file is empty: {document_file}")
                synchronized = _replace_final_rtl_sync_block(content, sync_payload)
                if synchronized != content:
                    atomic_text(document_path, synchronized)
                document_rows.append(
                    {
                        "path": document_path.relative_to(workspace).as_posix(),
                        "sha256": sha256_file(document_path),
                    }
                )
            sync_manifest = {
                "schema_version": "1.0",
                "status": "pass",
                "rtl": {
                    "language": rtl_language,
                    "top_module": top_module,
                    "source_files": current_source_rows,
                    "source_sha256": source_sha256,
                    "manifest_sha256": sha256_file(manifest_path),
                },
                "final_validation": {
                    "path": validation_path.relative_to(workspace).as_posix(),
                    "test_case_count": test_case_count,
                    "test_source_sha256": test_source_sha256,
                    "toffee_report_sha256": toffee_report["report_sha256"],
                },
                "documents": document_rows,
                "bug_documents": [],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            sync_path = resolve_workspace_path(workspace, self.sync_manifest_file)
            atomic_json(sync_path, sync_manifest)
        except (OSError, ValueError, FileNotFoundError, KeyError) as exc:
            reason = _public_evidence_error(str(exc))
            if failure_artifact in self.documentation_files:
                next_action = (
                    f"Open {failure_artifact} and update its interface, implementation, and "
                    "final-design sections from the current selected-language RTL and public "
                    "all-TC validation summary. Preserve the functional contract, then call "
                    "Check; the final identity appendix is maintained automatically."
                )
                expected = (
                    "A non-empty design document describing the unchanged required function "
                    "and the final implementation/interface."
                )
            elif str(failure_artifact).endswith(("_bug_analysis.md", "_static_bug_analysis.md")):
                next_action = (
                    f"Remove {failure_artifact}; a delivered design must pass every shared TC "
                    "and must not publish Bug-analysis artifacts. Then call Check again."
                )
                expected = "No *_bug_analysis.md or *_static_bug_analysis.md exists in the design output."
            elif failure_artifact == self.final_validation_file:
                next_action = (
                    "Run RunDesignConsistency with its defaults. Start with the first reported "
                    "Python/RTL node or Toffee report mismatch, repair the shared test/API/env, "
                    "reference model, or selected-language RTL as indicated, and rerun it until "
                    "both backends pass the identical complete TC set. Then call Check again."
                )
                expected = "Python and RTL pass the identical complete TC set and the RTL Toffee report contains every TC."
            else:
                next_action = (
                    "Call the RTL validation-stage Check to refresh the final RTL identity, then "
                    "run RunDesignConsistency with defaults. Do not edit generated manifests or "
                    "receipts. Return here and call Check after both operations pass."
                )
                expected = "Current final RTL identity plus a passing same-TC Python/RTL validation receipt."
            return False, diagnostic(
                "design_documentation_sync_invalid",
                "Final design documentation cannot yet be bound to the verified delivered RTL.",
                next_action,
                artifact=failure_artifact,
                location=failure_location,
                observed={"reason": reason},
                expected=expected,
            )
        return True, {
            "message": "Design documents are synchronized with the final all-pass RTL.",
            "documents": document_rows,
            "rtl_source_sha256": source_sha256,
            "test_case_count": test_case_count,
            "sync_manifest": sync_path.relative_to(workspace).as_posix(),
        }


class DesignFinalDeliveryChecker(Checker):
    """Verify final delivery and derive version curves from the bound machine ledger."""

    def __init__(
        self,
        ledger_file: str,
        final_report_file: str,
        design_summary_file: str,
        cfg: Any,
        performance_curve_json_file: str | None = None,
        dashboard_file: str | None = None,
        input_manifest_file: str | None = None,
        design_contract_files: list[str] | None = None,
        test_dir: str | None = None,
        test_glob: str | None = None,
        rtl_manifest_file: str | None = None,
        final_validation_file: str | None = None,
        require_design_summary: bool = True,
        timeout: int = 600,
        ret_std_out: bool = True,
        ret_std_error: bool = True,
        **kwargs: Any,
    ) -> None:
        """Store final artifact locations for live validation."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        if (test_dir is None) != (test_glob is None):
            raise ValueError("test_dir and test_glob must be provided together")
        for name, value in (
            ("test_dir", test_dir),
            ("test_glob", test_glob),
            ("rtl_manifest_file", rtl_manifest_file),
            ("final_validation_file", final_validation_file),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be a non-empty string")
        self.cfg = cfg
        self.rtl_config, self.rtl_language_backend = resolve_rtl_config(cfg)
        self.ledger_file = ledger_file
        self.final_report_file = final_report_file
        self.design_summary_file = design_summary_file
        output_root = resolved_output(cfg)
        dut = _cfg_dut(cfg)
        self.performance_curve_json_file = performance_curve_json_file or str(
            Path(output_root) / f"{dut}_performance_curve.json"
        )
        self.dashboard_file = dashboard_file
        self.input_manifest_file = input_manifest_file
        self.design_contract_files = list(design_contract_files or [])
        self.test_dir = test_dir
        self.test_glob = test_glob
        self.rtl_manifest_file = rtl_manifest_file
        dut = _cfg_dut(cfg)
        self.final_validation_file = final_validation_file or str(
            Path(output_root) / "reports" / f"{dut}_final_all_tc_validation.json"
        )
        if not isinstance(require_design_summary, bool):
            raise ValueError("require_design_summary must be a bool")
        self.require_design_summary = require_design_summary
        self.timeout = timeout
        for field, value in (
            ("ret_std_out", ret_std_out),
            ("ret_std_error", ret_std_error),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
        self.ret_std_out = ret_std_out
        self.ret_std_error = ret_std_error

    def _validate_final_all_test_cases(self, workspace: Path) -> dict[str, Any] | None:
        """Run both backends on one collected suite and bind the final Toffee report."""

        # Direct users of this checker may only request ledger/curve validation.  The
        # workflow always supplies test_dir and test_glob, which activates this final
        # all-TC gate without changing the lightweight unit-test construction contract.
        if self.test_dir is None or self.test_glob is None:
            return None
        test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
        pattern = Path(self.test_glob)
        if pattern.is_absolute() or ".." in pattern.parts:
            raise ValueError("test_glob must remain workspace-relative")
        test_files = sorted(
            path.resolve()
            for path in workspace.glob(self.test_glob)
            if path.is_file() and not path.is_symlink()
        )
        if not test_files:
            raise ValueError(f"no test files matched {self.test_glob}")
        if any(test_dir not in path.parents and path != test_dir for path in test_files):
            raise ValueError("final test_glob selected a file outside test_dir")

        collected = runtime._run_pytest(
            workspace,
            test_dir,
            "python",
            self.timeout,
            ["--collect-only"],
            test_files=test_files,
        )
        if collected.returncode != 0:
            collection_evidence = _pytest_evidence(
                collected,
                ret_std_out=self.ret_std_out,
                ret_std_error=self.ret_std_error,
                sensitive_paths=(workspace,),
            )
            raise ValueError(
                f"final test collection failed: {collection_evidence}"
            )
        expected_nodes = _parse_collected_final_nodes(
            collected.stdout, workspace, test_files
        )
        if not expected_nodes:
            raise ValueError("final test collection produced no pytest node IDs")

        manifest_path = self.rtl_manifest_file or ".ucagent/design_with_ppa/rtl_backend_manifest.json"
        rtl_manifest = load_json(
            resolve_workspace_path(workspace, manifest_path, must_exist=True)
        )
        rtl_dut_identity = runtime._validate_workspace_python_dut(workspace, rtl_manifest)
        source_rows = _hash_rows(workspace, test_files)
        source_hash = _rows_sha256(source_rows)
        backend_results: dict[str, dict[str, Any]] = {}
        final_report_path: Path | None = None
        final_report_hash: str | None = None
        report_dir = workspace / "uc_test_report"
        for backend, dut_identity in (("python", None), ("rtl", rtl_dut_identity)):
            info(
                f"[RunDesignConsistency] Step 3/4: running {len(expected_nodes)} TC on "
                f"the {backend} backend..."
            )
            if report_dir.is_symlink():
                raise ValueError("uc_test_report must not be a symbolic link")
            if report_dir.exists():
                if not report_dir.is_dir():
                    raise ValueError("uc_test_report must be a regular directory")
                shutil.rmtree(report_dir)
            completed = runtime._run_pytest(
                workspace,
                test_dir,
                backend,
                self.timeout,
                [
                    "--toffee-report",
                    "--report-dump-json",
                    "--report-dir",
                    "uc_test_report",
                    "--report-name",
                    "index.html",
                ],
                test_files=test_files,
                rtl_dut_identity=dut_identity,
            )
            if completed.returncode != 0:
                regression_evidence = _pytest_evidence(
                    completed,
                    ret_std_out=self.ret_std_out,
                    ret_std_error=self.ret_std_error,
                    sensitive_paths=(workspace,),
                )
                raise ValueError(
                    f"final {backend} regression failed: {regression_evidence}"
                )
            report_path, _report, cases, report_hash = _load_final_toffee_report(
                workspace, test_files
            )
            observed_nodes = set(cases)
            if observed_nodes != expected_nodes:
                missing = sorted(expected_nodes - observed_nodes)
                extra = sorted(observed_nodes - expected_nodes)
                raise ValueError(
                    f"final {backend} Toffee report test set differs from collection; "
                    f"missing={missing[:20]}, extra={extra[:20]}"
                )
            nonpassing = sorted(
                node for node, status in cases.items() if status != "PASSED"
            )
            if nonpassing:
                raise ValueError(
                    f"final {backend} Toffee report contains non-passing test cases: "
                    f"{nonpassing[:20]}"
                )
            snapshot_path, snapshot_hash = _write_toffee_snapshot(
                workspace,
                _report,
                workspace
                / resolved_output(self.cfg)
                / "reports"
                / "design_with_ppa"
                / f"{backend}_toffee_report.json",
            )
            info(
                f"[RunDesignConsistency] Step 3/4: {backend} backend done, "
                f"{len(cases)} TC all PASSED."
            )
            backend_results[backend] = {
                "status": "pass",
                "test_cases": [
                    {"node_id": node, "status": cases[node]}
                    for node in sorted(cases)
                ],
                "test_case_count": len(cases),
                "report_path": report_path.relative_to(workspace).as_posix(),
                "report_sha256": report_hash,
                "snapshot_path": snapshot_path,
                "snapshot_sha256": snapshot_hash,
                "source_sha256": source_hash,
                # Keep the final receipt self-diagnosing.  The complete gate
                # deliberately bounds and sanitizes both streams, while the
                # raw Toffee report remains the authoritative test evidence.
            }
            if self.ret_std_out:
                backend_results[backend]["stdout_tail"] = _redact_backend_output(
                    completed.stdout, 4000, (workspace,)
                )
            if self.ret_std_error:
                backend_results[backend]["stderr_tail"] = _redact_backend_output(
                    completed.stderr, 4000, (workspace,)
                )
            if backend == "rtl":
                final_report_path = report_path
                final_report_hash = report_hash
                html_path = report_dir / "index.html"
                if html_path.is_symlink() or not html_path.is_file():
                    raise ValueError("final RTL Toffee HTML report is missing")

        if final_report_path is None or final_report_hash is None:
            raise ValueError("final RTL Toffee report was not retained")
        receipt = {
            "schema_version": "1.0",
            "status": "pass",
            "test_cases": sorted(expected_nodes),
            "test_case_count": len(expected_nodes),
            "test_source_rows": source_rows,
            "test_source_sha256": source_hash,
            "same_test_cases": backend_results["python"]["test_cases"]
            == backend_results["rtl"]["test_cases"],
            "python": backend_results["python"],
            "rtl": backend_results["rtl"],
            "toffee_report": {
                "backend": "rtl",
                "report_path": final_report_path.relative_to(workspace).as_posix(),
                "report_sha256": final_report_hash,
                "all_test_cases": True,
                "html_path": (report_dir / "index.html").relative_to(workspace).as_posix(),
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if receipt["same_test_cases"] is not True:
            raise ValueError("Python and RTL final test case sets differ")
        receipt_path = resolve_workspace_path(workspace, self.final_validation_file)
        atomic_json(receipt_path, receipt)
        return {
            "path": receipt_path.relative_to(workspace).as_posix(),
            "test_case_count": len(expected_nodes),
            "report_path": final_report_path.relative_to(workspace).as_posix(),
            "report_sha256": final_report_hash,
        }

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require final delivery to be the best accepted all-pass design version."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        failure_artifact = self.final_report_file
        failure_location = "ppa_result_artifacts"
        try:
            design_inputs = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            design_contracts = (
                _contract_identity(workspace, self.design_contract_files)
                if self.design_contract_files
                else None
            )
            state = load_json(
                workspace / ".ucagent" / "design_with_ppa" / "state.json"
            )
            ledger = _load_bound_ledger(workspace, state, self.ledger_file)
            if state.get("schema_version") != "1.5":
                raise ValueError("private iteration state schema_version is invalid")
            if ledger.get("schema_version") != "1.5":
                raise ValueError("optimization ledger schema_version is invalid")
            if state.get("rtl_config") != self.rtl_config.identity():
                raise ValueError("private iteration RTL configuration is stale")
            if ledger.get("rtl_language") != self.rtl_config.language:
                raise ValueError("optimization ledger RTL language is stale")
            if state.get("ppa_config") != _resolved_workflow_ppa_config(
                self.cfg, ledger.get("top_module")
            ):
                raise ValueError("private iteration PPA configuration is stale")
            if state.get("status") != "complete":
                raise ValueError("PPA iteration state has not reached complete")
            configured_minimum, configured_maximum = optimization_limits(self.cfg)
            if state.get("min_optimization_iterations") != configured_minimum:
                raise ValueError("private state minimum optimization bound is stale")
            if state.get("max_optimization_iterations") != configured_maximum:
                raise ValueError("private state maximum optimization bound is stale")
            if ledger.get("min_optimization_iterations") != configured_minimum:
                raise ValueError("optimization ledger minimum bound is stale")
            if ledger.get("max_optimization_iterations") != configured_maximum:
                raise ValueError("optimization ledger maximum bound is stale")
            configured_patience = no_improvement_patience(self.cfg)
            if state.get("no_improvement_patience") != configured_patience:
                raise ValueError("private state no-improvement patience is stale")
            if ledger.get("no_improvement_patience") != configured_patience:
                raise ValueError("optimization ledger no-improvement patience is stale")
            configured_no_regression = list(
                no_regression_metric_categories(self.cfg)
            )
            if state.get("no_regression_metrics") != configured_no_regression:
                raise ValueError("private state no-regression scope is stale")
            if ledger.get("no_regression_metrics") != configured_no_regression:
                raise ValueError("optimization ledger no-regression scope is stale")
            configured_score_weights = ppa_score_weights(self.cfg)
            if state.get("score_weights") != configured_score_weights:
                raise ValueError("private state PPA score weights are stale")
            if ledger.get("score_weights") != configured_score_weights:
                raise ValueError("optimization ledger PPA score weights are stale")
            no_improvement_count = state.get("no_improvement_count")
            if (
                isinstance(no_improvement_count, bool)
                or not isinstance(no_improvement_count, int)
                or no_improvement_count < 0
                or no_improvement_count > configured_patience
            ):
                raise ValueError("private state no-improvement count is invalid")
            if ledger.get("no_improvement_count") != no_improvement_count:
                raise ValueError("optimization ledger no-improvement count is stale")
            if ledger.get("tolerance") != {
                "relative": 1e-6,
                "absolute": 1e-12,
            }:
                raise ValueError("optimization ledger tolerance is invalid")
            if ledger.get("stop_reason") not in {
                "base_only",
                "no_pareto_improvement",
                "max_iterations_reached",
            }:
                raise ValueError("optimization ledger stop_reason is invalid")
            records = ledger.get("records")
            if not isinstance(records, list) or not records:
                raise ValueError("optimization ledger records are empty")
            candidates = [record for record in records if record.get("kind") == "candidate"]
            if len(candidates) > configured_maximum:
                raise ValueError("optimization ledger exceeds the configured maximum iteration bound")
            if len(candidates) < configured_minimum and state.get("stop_reason") != "base_only":
                raise ValueError("optimization stopped before the configured minimum iteration bound")
            expected_versions = list(range(len(records)))
            if [record.get("iteration") for record in records] != expected_versions:
                raise ValueError("optimization ledger iteration sequence is not contiguous")
            if [record.get("version") for record in records] != expected_versions:
                raise ValueError("optimization ledger version sequence is not contiguous")
            history_has_commit = getattr(self.stage, "hist_has_commit", None)
            if not callable(history_has_commit):
                raise ValueError("internal history verification is unavailable")
            for record in records:
                iteration = record.get("iteration")
                history_commit = record.get("internal_history_commit")
                if not history_has_commit(history_commit):
                    raise ValueError(
                        f"iteration {iteration} internal_history_commit is not present "
                        "in stage history"
                    )
                if record.get("kind") == "candidate":
                    candidate_commit = record.get("candidate_history_commit")
                    if not history_has_commit(candidate_commit):
                        raise ValueError(
                            f"iteration {iteration} candidate_history_commit is not "
                            "present in stage history"
                        )
            accepted = [record for record in records if record.get("accepted") is True]
            if not accepted or accepted[0].get("kind") != "base":
                raise ValueError("optimization ledger has no accepted base record")
            selected_best = select_best_accepted_record(
                records,
                rel_tol=ledger["tolerance"]["relative"],
                abs_tol=ledger["tolerance"]["absolute"],
                categories=no_regression_metric_categories(self.cfg),
            )
            best_iteration = state.get("best_iteration")
            best = next(
                (record for record in accepted if record.get("iteration") == best_iteration),
                None,
            )
            if best is None:
                raise ValueError("private state best_iteration is not an accepted record")
            if best is not selected_best:
                raise ValueError("private state does not select the best accepted record")
            if state.get("best_report_id") != best.get("ppa_report_id"):
                raise ValueError("private state best_report_id is stale")
            if state.get("best_rtl_sha256") != best.get("rtl_sha256"):
                raise ValueError("private state best_rtl_sha256 is stale")
            best_snapshot_value = best.get("accepted_snapshot") or best.get("snapshot")
            if state.get("best_snapshot") != best_snapshot_value:
                raise ValueError("private state best_snapshot is stale")
            if ledger.get("best_iteration") != best.get("iteration"):
                raise ValueError("optimization ledger best_iteration is stale")
            if ledger.get("best_report_id") != best.get("ppa_report_id"):
                raise ValueError("optimization ledger best_report_id is stale")
            if (
                state.get("finalized_iteration") != best.get("iteration")
                or state.get("finalized_report_id") != best.get("ppa_report_id")
                or state.get("finalized_rtl_sha256") != best.get("rtl_sha256")
            ):
                raise ValueError("best accepted version has not been deterministically finalized")
            if not history_has_commit(state.get("finalized_history_commit")):
                raise ValueError("best-version finalization history commit is missing")
            last = best
            if last.get("design_inputs") != design_inputs or state.get(
                "base_design_inputs"
            ) != design_inputs:
                raise ValueError("final design input identity differs from the base")
            if (
                self.design_contract_files
                and (
                    last.get("design_contracts") != design_contracts
                    or state.get("base_design_contracts") != design_contracts
                )
            ):
                raise ValueError("final generated contract identity differs from the base")
            if last.get("iteration") != state.get("best_iteration"):
                raise ValueError("private state and ledger disagree on best iteration")
            if state.get("accepted_iteration") != accepted[-1].get("iteration"):
                raise ValueError("private state and ledger disagree on accepted iteration")
            if state.get("accepted_report_id") != accepted[-1].get("ppa_report_id"):
                raise ValueError("private state and ledger disagree on accepted PPA report")
            rtl_files = list(
                discover_rtl_sources(
                    workspace, self.rtl_config, self.rtl_language_backend
                )
            )
            rtl_rows = _hash_rows(workspace, rtl_files)
            rtl_hash = _rows_sha256(rtl_rows)
            _, final_library_provenance = discover_rtl_libraries(
                workspace, self.rtl_config, self.rtl_language_backend
            )
            final_library_rows = list(final_library_provenance)
            if rtl_rows != last.get("rtl_sources"):
                raise ValueError("final RTL file provenance differs from the last accepted record")
            if (
                final_library_rows != last.get("rtl_libraries")
                or final_library_rows != state.get("base_rtl_libraries")
                or final_library_rows != ledger.get("rtl_libraries")
            ):
                raise ValueError(
                    "final RTL library provenance differs from the accepted base contract"
                )
            if rtl_hash != best.get("rtl_sha256") or rtl_hash != state.get(
                "best_rtl_sha256"
            ):
                raise ValueError("final RTL does not match the selected best record")
            if last.get("functional_regression", {}).get("pass") is not True:
                raise ValueError("last accepted RTL lacks an all-pass functional regression")
            snapshot_value = state.get("best_snapshot")
            if not isinstance(snapshot_value, str):
                raise ValueError("private state has no best RTL snapshot")
            snapshot = resolve_workspace_path(
                workspace, snapshot_value, must_exist=True
            )
            snapshot_manifest = load_json(snapshot / "snapshot.json")
            if (
                snapshot_manifest.get("schema_version") != "1.1"
                or snapshot_manifest.get("rtl_language") != self.rtl_config.language
                or snapshot_manifest.get("rtl_sources") != rtl_rows
                or snapshot_manifest.get("snapshot_sha256") != rtl_hash
            ):
                raise ValueError("best RTL snapshot differs from final RTL")
            final_report = load_json(
                resolve_workspace_path(workspace, self.final_report_file, must_exist=True)
            )
            if final_report.get("report_id") != state.get("best_report_id"):
                raise ValueError("final PPA report is not the selected best report")
            cached_final = _load_cached_ppa(workspace, final_report["report_id"])
            if cached_final != final_report:
                raise ValueError("final PPA report differs from its cache entry")
            final_report_hash = sha256_file(
                workspace
                / ".ucagent"
                / "ppa_reports"
                / f"{final_report['report_id']}.json"
            )
            if final_report_hash != sha256_file(
                workspace / ".ucagent" / "ppa_reports" / f"{state['best_report_id']}.json"
            ) or (
                final_report_hash != last.get("ppa_report_sha256")
            ):
                raise ValueError("final PPA report hash differs from accepted state")
            final_metrics = _ppa_primary_metrics(final_report)
            if final_metrics != last.get("ppa_metrics"):
                raise ValueError("final PPA metrics differ from the accepted ledger record")
            if final_report.get("waveform_aggregation", {}).get("reliable") is not True:
                raise ValueError("final PPA report waveform activity is not reliable")
            report_rtl_rows = [
                {"path": row.get("path"), "sha256": row.get("sha256")}
                for row in final_report.get("provenance", {}).get("rtl_files", [])
                if isinstance(row, dict)
            ]
            if report_rtl_rows != rtl_rows:
                raise ValueError("final PPA report RTL provenance is stale")
            hard_failures = []
            for metric_id, metric in last["performance_metrics"].items():
                if not metric.get("hard_requirement"):
                    continue
                value = finite_number(metric.get("value"), metric_id)
                target = finite_number(metric.get("target"), f"{metric_id}.target")
                tolerance = max(
                    1e-12,
                    1e-6 * max(abs(target), abs(value)),
                )
                if (metric["direction"] == "min" and value - target > tolerance) or (
                    metric["direction"] == "max" and target - value > tolerance
                ):
                    hard_failures.append(metric_id)
            if hard_failures:
                raise ValueError(f"final hard performance targets failed: {hard_failures}")
            stop_reason = state.get("stop_reason")
            if stop_reason == "base_only" and candidates:
                raise ValueError("base_only state must not contain candidate records")
            if stop_reason == "no_pareto_improvement" and (
                not candidates
                or candidates[-1].get("rejection_reason")
                not in {"no_pareto_improvement", "pareto_regression"}
            ):
                raise ValueError("no_pareto_improvement state lacks its rejecting candidate")
            if stop_reason == "no_pareto_improvement" and no_improvement_count < configured_patience:
                raise ValueError("no_pareto_improvement state has not consumed patience")
            if stop_reason == "max_iterations_reached" and len(candidates) != configured_maximum:
                raise ValueError("max_iterations_reached candidate count is inconsistent")

            failure_artifact = self.final_validation_file
            failure_location = self.final_validation_file
            final_validation = self._validate_final_all_test_cases(workspace)

            failure_artifact = self.performance_curve_json_file
            failure_location = "ppa_result_artifacts"
            curve_json_path = resolve_workspace_path(
                workspace, self.performance_curve_json_file
            )
            if curve_json_path.suffix.lower() != ".json":
                raise ValueError("performance curve data path must use a .json suffix")
            ledger_path = resolve_workspace_path(
                workspace, self.ledger_file, must_exist=True
            )
            base_metrics = {
                **records[0].get("ppa_metrics", {}),
                **records[0].get("performance_metrics", {}),
            }
            base_ppa_metrics = records[0].get("ppa_metrics", {})
            if not isinstance(base_ppa_metrics, dict) or not base_ppa_metrics:
                raise ValueError("base record has no PPA metrics for the selection score")
            if not base_metrics:
                raise ValueError("base record has no complete metrics for the performance curve")
            metric_order = sorted(base_metrics)
            metric_contracts: dict[str, dict[str, str]] = {}
            for metric_id in metric_order:
                metric = base_metrics[metric_id]
                if not isinstance(metric, dict):
                    raise ValueError(f"base curve metric is invalid: {metric_id}")
                unit = metric.get("unit")
                direction = metric.get("direction")
                if not isinstance(unit, str) or not unit:
                    raise ValueError(f"base curve metric unit is invalid: {metric_id}")
                if direction not in {"min", "max"}:
                    raise ValueError(f"base curve metric direction is invalid: {metric_id}")
                finite_number(metric.get("value"), f"base curve metric {metric_id}")
                metric_contracts[metric_id] = {
                    "unit": unit,
                    "direction": direction,
                }

            curve_iterations = []
            omitted_iterations = []
            for record in records:
                iteration = record.get("iteration")
                version = record.get("version", iteration)
                if version != iteration:
                    raise ValueError(
                        f"iteration/version mismatch at iteration {iteration}"
                    )
                accepted_version = record.get("accepted") is True
                if accepted_version:
                    snapshot_value = record.get("accepted_snapshot") or record.get(
                        "snapshot"
                    )
                    expected_snapshot_hash = record.get(
                        "accepted_snapshot_sha256"
                    ) or record.get("snapshot_sha256")
                else:
                    snapshot_value = record.get("candidate_snapshot")
                    expected_snapshot_hash = record.get("candidate_snapshot_sha256")
                if not isinstance(snapshot_value, str) or not snapshot_value:
                    raise ValueError(
                        f"iteration {iteration} has no immutable RTL snapshot"
                    )
                snapshot_path = resolve_workspace_path(
                    workspace, snapshot_value, must_exist=True
                )
                snapshot_manifest_path = resolve_workspace_path(
                    snapshot_path, "snapshot.json", must_exist=True
                )
                snapshot_manifest = load_json(snapshot_manifest_path)
                snapshot_sources = snapshot_manifest.get("rtl_sources")
                if (
                    snapshot_manifest.get("schema_version") != "1.1"
                    or snapshot_manifest.get("rtl_language")
                    != self.rtl_config.language
                    or not isinstance(snapshot_sources, list)
                    or not snapshot_sources
                    or snapshot_sources != record.get("rtl_sources")
                    or snapshot_manifest.get("snapshot_sha256")
                    != expected_snapshot_hash
                    or expected_snapshot_hash != record.get("rtl_sha256")
                ):
                    raise ValueError(
                        f"iteration {iteration} RTL snapshot manifest is invalid"
                    )
                artifact_sources = []
                for source_row in snapshot_sources:
                    if (
                        not isinstance(source_row, dict)
                        or not isinstance(source_row.get("path"), str)
                        or not isinstance(source_row.get("sha256"), str)
                    ):
                        raise ValueError(
                            f"iteration {iteration} RTL snapshot source row is invalid"
                        )
                    snapshot_source = resolve_workspace_path(
                        snapshot_path, source_row["path"], must_exist=True
                    )
                    if sha256_file(snapshot_source) != source_row["sha256"]:
                        raise ValueError(
                            f"iteration {iteration} RTL snapshot source hash is invalid"
                        )
                    artifact_sources.append(
                        {
                            "path": snapshot_source.relative_to(workspace).as_posix(),
                            "original_path": source_row["path"],
                            "sha256": source_row["sha256"],
                        }
                    )
                iteration_report_path = resolve_workspace_path(
                    workspace,
                    Path(resolved_output(self.cfg))
                    / "reports"
                    / "ppa"
                    / "iterations"
                    / f"iteration-{iteration:03d}.json",
                    must_exist=True,
                )
                if iteration_report_path.is_symlink() or not iteration_report_path.is_file():
                    raise ValueError(
                        f"iteration {iteration} report is not a regular file"
                    )
                artifacts = {
                    "rtl_sources": artifact_sources,
                    "snapshot_manifest": snapshot_manifest_path.relative_to(
                        workspace
                    ).as_posix(),
                    "iteration_report": iteration_report_path.relative_to(
                        workspace
                    ).as_posix(),
                }
                ppa_metrics = record.get("ppa_metrics")
                performance_metrics = record.get("performance_metrics")
                report_id = record.get("ppa_report_id")
                if (
                    not isinstance(ppa_metrics, dict)
                    or not ppa_metrics
                    or not isinstance(performance_metrics, dict)
                    or not performance_metrics
                    or not isinstance(report_id, str)
                    or not report_id
                ):
                    rejection_code = record.get("rejection_reason") or (
                        "incomplete_functional_or_ppa_evidence"
                    )
                    functional_regression = record.get("functional_regression")
                    pytest_evidence = (
                        functional_regression.get("pytest", {})
                        if isinstance(functional_regression, dict)
                        else {}
                    )
                    omitted_iterations.append(
                        {
                            "iteration": iteration,
                            "version": version,
                            "kind": record.get("kind"),
                            "accepted": record.get("accepted"),
                            "reason": "incomplete_functional_or_ppa_evidence",
                        }
                    )
                    curve_iterations.append(
                        {
                            "iteration": iteration,
                            "version": version,
                            "kind": record.get("kind"),
                            "accepted": record.get("accepted"),
                            "best": False,
                            "status": "omitted",
                            "rejection_reason": rejection_code,
                            "rejection": {
                                "code": rejection_code,
                                "compared_to_iteration": record.get(
                                    "parent_accepted_iteration"
                                ),
                                "metrics": [],
                                "test_summary": pytest_evidence.get("summary"),
                                "evidence_status": "incomplete",
                            },
                            "artifacts": artifacts,
                            "selection_eligible": False,
                            "ppa_score": {
                                "metric_id": _PPA_SCORE_ID,
                                "value": None,
                                "unit": "x_base",
                                "direction": "max",
                                "status": "incomplete_evidence",
                            },
                            "metrics": {},
                        }
                    )
                    continue
                current_metrics = {**ppa_metrics, **performance_metrics}
                if set(current_metrics) != set(metric_order):
                    raise ValueError(
                        f"curve metric set changed at iteration {iteration}"
                    )
                curve_metrics = {}
                for metric_id in metric_order:
                    current = current_metrics[metric_id]
                    base = base_metrics[metric_id]
                    contract = metric_contracts[metric_id]
                    if not isinstance(current, dict):
                        raise ValueError(
                            f"curve metric is invalid at iteration {iteration}: {metric_id}"
                        )
                    if (
                        current.get("unit") != contract["unit"]
                        or current.get("direction") != contract["direction"]
                    ):
                        raise ValueError(
                            f"curve metric contract changed at iteration {iteration}: {metric_id}"
                        )
                    base_value = finite_number(
                        base.get("value"), f"base curve metric {metric_id}"
                    )
                    value = finite_number(
                        current.get("value"),
                        f"curve metric {metric_id} iteration {iteration}",
                    )
                    if value == base_value:
                        improvement = 0.0
                        normalization_status = "normalized"
                    elif base_value == 0.0:
                        improvement = None
                        normalization_status = "zero_baseline"
                    else:
                        directional_delta = (
                            value - base_value
                            if contract["direction"] == "max"
                            else base_value - value
                        )
                        improvement = round(
                            finite_number(
                                directional_delta / abs(base_value) * 100.0,
                                f"normalized curve metric {metric_id}",
                            ),
                            12,
                        )
                        normalization_status = "normalized"
                    curve_metrics[metric_id] = {
                        "value": value,
                        "unit": contract["unit"],
                        "direction": contract["direction"],
                        "normalized_improvement_percent": improvement,
                        "normalization_status": normalization_status,
                    }
                rejection_code = record.get("rejection_reason")
                rejection = None
                if isinstance(rejection_code, str) and rejection_code:
                    changes = record.get("metric_changes_to_previous")
                    changes = changes if isinstance(changes, dict) else {}
                    if rejection_code == "pareto_regression":
                        relevant_assessments = {"regressed"}
                    elif rejection_code == "no_pareto_improvement":
                        relevant_assessments = {"unchanged"}
                    else:
                        relevant_assessments = set()
                    rejection_metrics = []
                    for metric_id, change in sorted(changes.items()):
                        if (
                            not isinstance(change, dict)
                            or change.get("assessment") not in relevant_assessments
                        ):
                            continue
                        rejection_metrics.append(
                            {
                                "metric_id": metric_id,
                                "assessment": change.get("assessment"),
                                "previous_value": change.get("baseline"),
                                "current_value": change.get("current"),
                                "delta": change.get("delta"),
                                "percent_change": change.get("percent_change"),
                                "unit": change.get("unit"),
                                "direction": change.get("direction"),
                            }
                        )
                    if rejection_code == "hard_performance_target_failed":
                        tolerance_config = ledger.get("tolerance", {})
                        relative_tolerance = finite_number(
                            tolerance_config.get("relative", 1e-6),
                            "ledger relative tolerance",
                        )
                        absolute_tolerance = finite_number(
                            tolerance_config.get("absolute", 1e-12),
                            "ledger absolute tolerance",
                        )
                        for metric_id, metric in sorted(performance_metrics.items()):
                            if not isinstance(metric, dict) or metric.get(
                                "hard_requirement"
                            ) is not True:
                                continue
                            value = finite_number(metric.get("value"), metric_id)
                            target = finite_number(
                                metric.get("target"), f"{metric_id}.target"
                            )
                            tolerance = max(
                                absolute_tolerance,
                                relative_tolerance * max(abs(target), abs(value)),
                            )
                            direction = metric.get("direction")
                            failed = (
                                direction == "min" and value - target > tolerance
                            ) or (
                                direction == "max" and target - value > tolerance
                            )
                            if failed:
                                rejection_metrics.append(
                                    {
                                        "metric_id": metric_id,
                                        "assessment": "hard_target_failed",
                                        "current_value": value,
                                        "target_value": target,
                                        "unit": metric.get("unit"),
                                        "direction": direction,
                                    }
                                )
                    rejection = {
                        "code": rejection_code,
                        "compared_to_iteration": record.get(
                            "parent_accepted_iteration"
                        ),
                        "metrics": rejection_metrics,
                        "test_summary": None,
                        "evidence_status": "complete",
                    }
                curve_iterations.append(
                    {
                        "iteration": iteration,
                        "version": version,
                        "kind": record.get("kind"),
                        "accepted": record.get("accepted"),
                        "best": iteration == state.get("best_iteration"),
                        "status": "complete",
                        "rejection_reason": rejection_code,
                        "rejection": rejection,
                        "artifacts": artifacts,
                        "selection_eligible": record.get("accepted") is True,
                        "ppa_score": _ppa_selection_score(
                            base_ppa_metrics,
                            ppa_metrics,
                            weights=ppa_score_weights(self.cfg),
                        ),
                        "metrics": curve_metrics,
                    }
                )
            if [row["iteration"] for row in curve_iterations] != list(
                range(len(curve_iterations))
            ):
                raise ValueError("performance curve version sequence is not contiguous")
            if not curve_iterations or curve_iterations[0]["iteration"] != 0:
                raise ValueError("performance curve lacks a complete base point")
            if state.get("accepted_iteration") not in {
                row["iteration"]
                for row in curve_iterations
                if row["accepted"] is True
            }:
                raise ValueError("performance curve lacks the final accepted iteration")

            # The PPA score is a diagnostic ranking over accepted versions.
            # The delivered best version is chosen by Pareto dominance over
            # the protected no-regression categories, so the score maximum may
            # legitimately differ from the delivered best when an accepted
            # candidate trades away unprotected area or power.
            scored_accepted = [
                row
                for row in curve_iterations
                if row["selection_eligible"] is True
                and row["ppa_score"].get("status") == "available"
            ]
            score_best = (
                max(
                    scored_accepted,
                    key=lambda row: (row["ppa_score"]["value"], row["iteration"]),
                )
                if scored_accepted
                else None
            )

            series = []
            for metric_id in metric_order:
                series.append(
                    {
                        "metric_id": metric_id,
                        **metric_contracts[metric_id],
                        "points": [
                            {
                                "iteration": row["iteration"],
                                "version": row["version"],
                                "accepted": row["accepted"],
                                "best": row["best"],
                                "value": row["metrics"][metric_id]["value"],
                                "normalized_improvement_percent": row["metrics"][metric_id][
                                    "normalized_improvement_percent"
                                ],
                                "normalization_status": row["metrics"][metric_id][
                                    "normalization_status"
                                ],
                            }
                            for row in curve_iterations
                            if metric_id in row["metrics"]
                        ],
                    }
                )

            curve_json_relative = curve_json_path.relative_to(workspace).as_posix()
            selection_points = [
                {
                    "iteration": row["iteration"],
                    "version": row["version"],
                    "accepted": row["accepted"],
                    "eligible": row["selection_eligible"],
                    "best": row["best"],
                    "value": row["ppa_score"].get("value"),
                    "status": row["ppa_score"].get("status"),
                }
                for row in curve_iterations
            ]
            curve_payload = {
                "schema_version": "1.3",
                "dut": ledger.get("dut"),
                "top_module": ledger.get("top_module"),
                "stop_reason": stop_reason,
                "accepted_iteration": state.get("accepted_iteration"),
                "best_iteration": state.get("best_iteration"),
                "no_regression_metrics": ledger.get("no_regression_metrics"),
                "metric_order": metric_order,
                "iterations": curve_iterations,
                "omitted_iterations": omitted_iterations,
                "series": series,
                "selection_metric": {
                    "metric_id": _PPA_SCORE_ID,
                    "label": "PPA score",
                    "unit": "x_base",
                    "direction": "max",
                    "formula": _ppa_score_formula(configured_score_weights),
                    "weights": dict(configured_score_weights),
                    "timing_policy": (
                        "frequency ratio when timing direction is max; "
                        "inverse critical-delay ratio when timing direction is min"
                    ),
                    "baseline_iteration": 0,
                    "baseline_value": 1.0,
                    "eligibility": (
                        "accepted versions only after functional, hard-target, "
                        "comparability, and no-regression acceptance gates over "
                        "the configured no_regression_metrics categories"
                    ),
                    "selection_policy": (
                        "diagnostic ranking only; the delivered best version is "
                        "chosen by Pareto dominance over the protected "
                        "no-regression categories (marked by iterations[].best "
                        "and the top-level best_iteration) and may differ from "
                        "the score maximum when unprotected categories regress"
                    ),
                    "tie_break": "newest eligible iteration",
                    "best_iteration": (
                        score_best["iteration"] if score_best is not None else None
                    ),
                    "best_value": (
                        score_best["ppa_score"]["value"]
                        if score_best is not None
                        else None
                    ),
                    "status": "available" if score_best is not None else "unavailable",
                    "points": selection_points,
                },
                "normalization": {
                    "baseline_iteration": 0,
                    "unit": "percent",
                    "formula_max": "(current - base) / abs(base) * 100",
                    "formula_min": "(base - current) / abs(base) * 100",
                    "zero_baseline": "null unless current also equals zero",
                },
            }
            atomic_json(curve_json_path, curve_payload)
            final_report_relative = resolve_workspace_path(
                workspace, self.final_report_file, must_exist=True
            ).relative_to(workspace).as_posix()
            summary_path: Path | None = None
            summary_text = ""
            if self.require_design_summary:
                failure_artifact = self.design_summary_file
                failure_location = self.design_summary_file
                summary = load_fenced_yaml(
                    resolve_workspace_path(
                        workspace, self.design_summary_file, must_exist=True
                    ),
                    "design_summary",
                )
                if summary.get("schema_version") != "1.2":
                    raise ValueError("design summary schema_version must be 1.2")
                if summary.get("dut") != ledger.get("dut"):
                    raise ValueError("design summary dut is stale")
                if summary.get("top_module") != ledger.get("top_module"):
                    raise ValueError("design summary top_module is stale")
                if summary.get("stop_reason") != state.get("stop_reason"):
                    raise ValueError("design summary stop_reason is stale")
                if summary.get("accepted_iteration") != state.get("accepted_iteration"):
                    raise ValueError("design summary accepted_iteration is stale")
                if summary.get("min_optimization_iterations") != configured_minimum:
                    raise ValueError("design summary minimum optimization bound is stale")
                if summary.get("max_optimization_iterations") != configured_maximum:
                    raise ValueError("design summary maximum optimization bound is stale")
                if summary.get("best_iteration") != state.get("best_iteration"):
                    raise ValueError("design summary best_iteration is stale")
                if summary.get("best_report_id") != state.get("best_report_id"):
                    raise ValueError("design summary best_report_id is stale")
                if summary.get("no_improvement_patience") != configured_patience:
                    raise ValueError("design summary no-improvement patience is stale")
                if summary.get("no_regression_metrics") != configured_no_regression:
                    raise ValueError("design summary no-regression scope is stale")
                if summary.get("no_improvement_count") != no_improvement_count:
                    raise ValueError("design summary no-improvement count is stale")
                if summary.get("performance_curve_json") != curve_json_relative:
                    raise ValueError("design summary performance_curve_json is stale")
                if summary.get("final_ppa_report") != final_report_relative:
                    raise ValueError("design summary final_ppa_report is stale")
                summary_path = resolve_workspace_path(
                    workspace, self.design_summary_file, must_exist=True
                )
                summary_text = summary_path.read_text(encoding="utf-8")
            if self.dashboard_file is not None:
                failure_artifact = self.dashboard_file
                failure_location = self.dashboard_file
                dashboard_path = resolve_workspace_path(
                    workspace, self.dashboard_file, must_exist=True
                )
                if dashboard_path.suffix.lower() != ".html":
                    raise ValueError("design dashboard path must use an .html suffix")
                dashboard_text = dashboard_path.read_text(encoding="utf-8")
                dashboard_snapshot = {
                    "schema_version": "1.0",
                    "runtime": {
                        "plugin_options": {
                            "design_with_ppa.min_optimization_iterations": configured_minimum,
                            "design_with_ppa.max_optimization_iterations": configured_maximum,
                            "design_with_ppa.no_improvement_patience": configured_patience,
                            "design_with_ppa.no_regression_metrics": configured_no_regression,
                            "design_with_ppa.score_weights": configured_score_weights,
                            "design_with_ppa.rtl.language": self.rtl_config.language,
                        }
                    },
                    "state": {
                        key: state.get(key)
                        for key in (
                            "schema_version",
                            "status",
                            "candidate_count",
                            "accepted_iteration",
                            "best_iteration",
                            "min_optimization_iterations",
                            "max_optimization_iterations",
                            "no_improvement_patience",
                            "no_regression_metrics",
                            "score_weights",
                            "no_improvement_count",
                            "stop_reason",
                        )
                    },
                    "finalPpa": {
                        "schema_version": final_report.get("schema_version"),
                        "report_id": final_report.get("report_id"),
                        "status": final_report.get("status"),
                        "summary": final_report.get("summary"),
                    },
                    "curve": curve_payload,
                }
                dashboard_text = _embed_dashboard_snapshot(
                    dashboard_text, dashboard_snapshot
                )
                atomic_text(dashboard_path, dashboard_text)
                required_dashboard_contracts = (
                    'data-dashboard-contract="design-with-ppa/v2"',
                    'id="design-with-ppa-snapshot"',
                    "EMBEDDED_SNAPSHOT",
                    "EMBEDDED_SNAPSHOT[source.snapshotKey]",
                    'id="ppa-score-chart"',
                    'id="ppa-score-value"',
                    ".ucagent/runtime_config.json",
                    ".ucagent/design_with_ppa/state.json",
                    ".ucagent/current_test_report.json",
                    "uc_test_report/index.html",
                    "deriveToffeeReportPath",
                    "file.text()",
                    "fetch(source.href",
                    'getContext("2d")',
                    "REFRESH_INTERVAL_MS = 15000",
                    'id="iteration-page-size"',
                    'id="iteration-page-size-custom"',
                    'id="iteration-prev"',
                    'id="iteration-next"',
                    "iterationPageSize = 50",
                    'id="filter-accepted"',
                    'id="filter-rejected"',
                    'id="metric-filters"',
                    'id="dashboard-theme-toggle"',
                    'data-theme-option="dark"',
                    'data-theme-option="light"',
                    'data-theme-option="graphite"',
                    "const applyTheme = (name, persist = true)",
                    "const PREFERENCES_KEY = `design-with-ppa.dashboard.v2.preferences:${DUT}:${OUTPUT_PATH}`",
                    "window.localStorage.getItem(PREFERENCES_KEY)",
                    "window.localStorage.setItem(PREFERENCES_KEY, serialized)",
                    'window.location.hash.startsWith("#dwp=")',
                    'window.history.replaceState(null, "", fragment)',
                    "const persistPreferences =",
                    "const displayFilters = { accepted: true, rejected: true, metrics: new Map() }",
                    "const visibleSeries = (series)",
                    "tr.rejected-row",
                    'chip.dataset.state = iteration.accepted ? "accepted" : "rejected"',
                    "segmentAccepted = previous.accepted === true && point.accepted === true",
                    "context.setLineDash(segmentAccepted ? [] : [4, 4])",
                    "context.strokeStyle = point.accepted ? color : muted",
                    f"{ledger['dut']}_performance_curve.json",
                )
                missing_contracts = [
                    value
                    for value in required_dashboard_contracts
                    if value not in dashboard_text
                ]
                if missing_contracts:
                    raise ValueError(
                        f"design dashboard is missing required contracts: {missing_contracts}"
                    )
                if re.search(r"{{\s*[^{}]+\s*}}", dashboard_text):
                    raise ValueError("design dashboard contains unresolved template values")
                if str(workspace) in dashboard_text:
                    raise ValueError("design dashboard contains an absolute workspace path")
                if re.search(
                    r"(?:href|src)\s*=\s*[\"'](?:https?:)?//",
                    dashboard_text,
                    flags=re.IGNORECASE,
                ):
                    raise ValueError("design dashboard contains an external network resource")
                forbidden_browser_writes = (
                    ".innerHTML",
                    "XMLHttpRequest",
                    "WebSocket",
                    "sendBeacon",
                    "createWritable",
                    "showSaveFilePicker",
                    "localStorage.removeItem",
                    "localStorage.clear",
                    "sessionStorage.setItem",
                )
                found_writes = [
                    value for value in forbidden_browser_writes if value in dashboard_text
                ]
                if found_writes:
                    raise ValueError(
                        f"design dashboard contains unsafe browser operations: {found_writes}"
                    )
                if len(re.findall(r"(?:window\.)?localStorage\.setItem\s*\(", dashboard_text)) != 1:
                    raise ValueError(
                        "design dashboard must contain exactly one namespaced UI-preference write"
                    )
                if len(re.findall(r"(?:window\.)?history\.replaceState\s*\(", dashboard_text)) != 1:
                    raise ValueError(
                        "design dashboard must contain exactly one file-mode UI-preference URL update"
                    )
                if summary_path is not None:
                    dashboard_link = os.path.relpath(
                        dashboard_path, start=summary_path.parent
                    ).replace(os.sep, "/")
                    failure_artifact = self.design_summary_file
                    failure_location = self.design_summary_file
                    if re.search(
                        rf"\[[^\]\n]+\]\({re.escape(dashboard_link)}\)", summary_text
                    ) is None:
                        raise ValueError(
                            "design summary must link to the result dashboard as "
                            f"{dashboard_link}"
                        )
        except (OSError, ValueError, FileNotFoundError, KeyError) as exc:
            raw_reason = str(exc)
            reason = _public_evidence_error(raw_reason)
            if failure_artifact == self.dashboard_file:
                public_error = (
                    "The PPA dashboard is missing or does not match its read-only "
                    f"template contract. First problem: {_inline_reason(reason)}"
                )
                next_action = (
                    f"Restore {self.dashboard_file} from the rendered workflow template without "
                    "adding external resources or browser writes, then call Check. Its embedded "
                    "PPA data is refreshed automatically."
                )
                expected = "The canonical local, read-only PPA dashboard template with no unresolved values."
            elif failure_artifact == self.design_summary_file:
                public_error = (
                    "The authored design summary does not match the finalized public PPA "
                    f"result. First problem: {_inline_reason(reason)}"
                )
                next_action = (
                    f"Open {self.design_summary_file}, use observed.reason to correct the first "
                    "stale schema field or relative link from the public PPA finalization result, "
                    "and call Check. Do not copy private optimization data into the summary."
                )
                expected = "Schema-1.1 design_summary values match the finalized public PPA result and link to the dashboard relatively."
            elif failure_artifact == self.final_validation_file:
                public_error = (
                    "The final same-TC Python/RTL validation or Toffee report is "
                    f"incomplete. First problem: {_inline_reason(reason)}"
                )
                next_action = (
                    "Run RunDesignConsistency with its default arguments. Start with the first "
                    "failed/extra/missing pytest node in that result; repair the shared TC/API/env, "
                    "reference model, or selected-language RTL as indicated, then rerun until "
                    "Python and RTL pass the identical complete TC set. Call Check afterward."
                )
                expected = "Python and RTL pass the same complete TC set and the final RTL Toffee HTML report contains every TC."
            elif "final RTL file provenance differs" in raw_reason:
                public_error = (
                    "The authored RTL files on disk are not the finalized best accepted version."
                )
                next_action = (
                    "Call the ppa_best_version_finalization Check to atomically restore the "
                    "verified best RTL from its preserved snapshot, then rerun this Check. Do "
                    "not hand-copy, edit, or regenerate RTL files here."
                )
                expected = (
                    "The authored RTL files equal the finalized best accepted version "
                    "preserved by the optimization run."
                )
            else:
                public_error = (
                    "The final PPA report no longer matches the verified best accepted version."
                    if "final ppa" in raw_reason.lower()
                    else "The finalized optimization evidence cannot prove one contiguous, untampered best-version selection."
                )
                next_action = (
                    "Do not edit the generated curve, PPA report, optimization records, or "
                    "preserved versions. Call the failed PPA-stage Check again to regenerate its "
                    "derived artifact. If observed.reason reports an authored RTL, performance "
                    "contract, or TC mismatch, repair that exact source first; if it repeats as "
                    "generated-evidence inconsistency, restart PPA finalization."
                )
                expected = "A contiguous verified optimization run whose finalized best RTL, PPA metrics, curve, and provenance agree."
            return False, diagnostic(
                "design_final_delivery_invalid",
                public_error,
                next_action,
                artifact=failure_artifact,
                location=failure_location,
                observed={"reason": reason},
                expected=expected,
            )
        return True, {
            "message": "Final RTL and design/PPA delivery are complete.",
            "accepted_iteration": state["accepted_iteration"],
            "best_iteration": state["best_iteration"],
            "stop_reason": state["stop_reason"],
            "performance_curve_json": curve_json_relative,
            "final_ppa_report": final_report_relative,
            "final_all_tc_validation": (
                final_validation["path"] if final_validation is not None else None
            ),
            "final_test_case_count": (
                final_validation["test_case_count"]
                if final_validation is not None
                else None
            ),
            "design_dashboard": (
                resolve_workspace_path(workspace, self.dashboard_file)
                .relative_to(workspace)
                .as_posix()
                if self.dashboard_file is not None
                else None
            ),
        }


class PPAResultArtifactsChecker(DesignFinalDeliveryChecker):
    """Generate and validate final PPA curve/dashboard artifacts before documentation."""

    def __init__(self, **kwargs: Any) -> None:
        """Disable authored-summary and all-test requirements for machine PPA results."""

        kwargs.pop("require_design_summary", None)
        super().__init__(require_design_summary=False, **kwargs)

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Validate finalized PPA state and derive its versioned presentation data."""

        passed, result = super().do_check(is_complete=is_complete, **kwargs)
        if passed and isinstance(result, dict):
            result = {
                **result,
                "message": "Final PPA report, version curve, and dashboard are complete.",
            }
        return passed, result
