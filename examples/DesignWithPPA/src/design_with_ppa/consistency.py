"""One-call backend consistency validation for the DesignWithPPA plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ucagent.tools.uctool import UCTool
from ucagent.util.log import info

from .checkers import (
    DesignFinalDeliveryChecker,
    PerformanceArtifactChecker,
    RTLBackendBuildChecker,
    _bounded_checker_value,
    _hash_rows,
    _redact_backend_output,
    _run_workflow_ppa,
)
from .contracts import diagnostic, load_fenced_yaml, load_json, resolve_workspace_path
from .rtl import discover_rtl_libraries, discover_rtl_sources, resolve_rtl_config


def consistency_failure_diagnostic(exc: Exception, artifact: str) -> dict[str, Any]:
    """Bound and redact one consistency failure without flooding the context.

    Final-delivery failures embed several kilobytes of pytest evidence in the
    exception text; returning it verbatim would blow the caller's context.
    The tail-aligned excerpt keeps the root cause while observed preserves a
    bounded structured projection.
    """

    reason = _redact_backend_output(str(exc), 4000)
    return diagnostic(
        "design_consistency_failed",
        reason[-1200:] if len(reason) > 1200 else reason,
        "Repair the reported backend, test, report, RTL, or performance "
        "artifact and invoke RunDesignConsistency again.",
        artifact=artifact,
        observed={
            "reason": reason,
            "exception_type": type(exc).__name__,
            "exception_attributes": _bounded_checker_value(
                getattr(exc, "__dict__", {})
            ),
        },
    )


class RunDesignConsistencyArgs(BaseModel):
    """Public arguments for one complete reference/RTL consistency run."""

    model_config = ConfigDict(extra="forbid")

    test_dir: str = Field(
        default="{OUT}/tests",
        description="Workspace-relative directory containing the shared pytest suite.",
    )
    test_glob: str = Field(
        default="{OUT}/tests/test_{DUT}_*.py",
        description="Workspace-relative glob selecting every shared test_*.py file.",
    )
    architecture_file: str = Field(
        default="{OUT}/{DUT}_architecture.md",
        description="Architecture document with the machine-readable top_module contract.",
    )
    rtl_manifest_file: str = Field(
        default=".ucagent/design_with_ppa/rtl_backend_manifest.json",
        description="Managed RTL backend manifest; normally leave this at its default.",
    )
    performance_manifest_file: str = Field(
        default="{OUT}/performance/performance_manifest.json",
        description="Validated performance sidecar manifest used for PPA waveforms.",
    )
    ppa_report_file: str | None = Field(
        default=None,
        description="Optional workspace-relative PPA JSON destination.",
    )
    baseline_report_id: str | None = Field(
        default=None,
        description="Optional cached PPA report ID for the generated diff.",
    )
    run_ppa: bool = Field(
        default=True,
        description="Also analyze the validated performance waveforms and return a PPA report.",
    )
    timeout: int = Field(
        default=600,
        ge=10,
        le=3600,
        description="Per-command timeout in seconds.",
    )


def _format_path(value: str, cfg: Any) -> str:
    """Resolve a public path template using the active DUT and output values."""

    values = cfg.get_value("_temp_cfg", {})
    dut = values.get("DUT") if isinstance(values, dict) else None
    output = values.get("OUT") if isinstance(values, dict) else None
    if not isinstance(dut, str) or not dut:
        raise ValueError("resolved configuration DUT is unavailable")
    if not isinstance(output, str) or not output:
        raise ValueError("resolved configuration OUT is unavailable")
    return value.replace("{DUT}", dut).replace("{OUT}", output)


class RunDesignConsistency(UCTool):
    """Run the shared suite on reference and RTL backends and optionally produce PPA."""

    name: str = "RunDesignConsistency"
    description: str = (
        "With no arguments, run the resolved output tests in reference and RTL modes; "
        "with paths supplied, run that shared pytest suite. Require every collected "
        "test to pass in both modes, publish the complete Toffee report for the RTL run, "
        "and optionally analyze the validated performance waveforms into a PPA report. "
        "The same test files, node IDs, and source hashes are used for both backends."
    )
    args_schema: Optional[type[BaseModel]] = RunDesignConsistencyArgs
    return_direct: bool = False
    workspace: str = Field(default=".", exclude=True, repr=False)
    output_dir: str = Field(default="output", exclude=True, repr=False)
    write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    un_write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    _cfg: Any = PrivateAttr()

    def __init__(
        self,
        workspace: str = ".",
        output_dir: str = "output",
        write_dirs: list[str] | None = None,
        un_write_dirs: list[str] | None = None,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        """Bind the active plugin workspace and resolved configuration."""

        super().__init__(
            workspace=str(Path(workspace).resolve()),
            output_dir=output_dir,
            write_dirs=write_dirs,
            un_write_dirs=un_write_dirs,
            **kwargs,
        )
        if cfg is None:
            raise ValueError("RunDesignConsistency requires the resolved plugin configuration")
        self._cfg = cfg

    def _run(
        self,
        test_dir: str = "{OUT}/tests",
        test_glob: str = "{OUT}/tests/test_{DUT}_*.py",
        architecture_file: str = "{OUT}/{DUT}_architecture.md",
        rtl_manifest_file: str = ".ucagent/design_with_ppa/rtl_backend_manifest.json",
        performance_manifest_file: str = "{OUT}/performance/performance_manifest.json",
        ppa_report_file: str | None = None,
        baseline_report_id: str | None = None,
        run_ppa: bool = True,
        timeout: int = 600,
        **_: Any,
    ) -> dict[str, Any]:
        """Execute the consistency gate without importing any user-authored module."""

        workspace = Path(self.workspace).resolve()
        try:
            test_dir = _format_path(test_dir, self._cfg)
            test_glob = _format_path(test_glob, self._cfg)
            architecture_file = _format_path(architecture_file, self._cfg)
            rtl_manifest_file = _format_path(rtl_manifest_file, self._cfg)
            performance_manifest_file = _format_path(performance_manifest_file, self._cfg)
            info("[RunDesignConsistency] Step 1/4: rebuilding the managed RTL backend (this can take several minutes)...")
            build = RTLBackendBuildChecker(
                architecture_file=architecture_file,
                manifest_file=rtl_manifest_file,
                timeout=timeout,
                cfg=self._cfg,
                input_manifest_file=None,
                contract_files=[],
            ).set_workspace(str(workspace))
            build_passed, build_result = build.do_check()
            if not build_passed:
                info("[RunDesignConsistency] Step 1/4 FAILED: RTL backend rebuild.")
                return build_result
            info("[RunDesignConsistency] Step 1/4 done: RTL backend rebuilt.")

            result: dict[str, Any] = {"status": "pass"}
            if run_ppa:
                info("[RunDesignConsistency] Step 2/4: rerunning all performance tests (RTL backend)...")
                performance = PerformanceArtifactChecker(
                    test_dir=test_dir,
                    results_glob=_format_path(
                        "{OUT}/performance/results/*.json", self._cfg
                    ),
                    contract_file=_format_path(
                        "{OUT}/{DUT}_performance_contract.yaml", self._cfg
                    ),
                    manifest_file=performance_manifest_file,
                    timeout=timeout,
                    cfg=self._cfg,
                    pytest_args=["-m", "performance"],
                    rtl_manifest_file=rtl_manifest_file,
                ).set_workspace(str(workspace))
                performance_passed, performance_result = performance.do_check(
                    run_tests=True
                )
                if not performance_passed:
                    info("[RunDesignConsistency] Step 2/4 FAILED: performance test rerun.")
                    return performance_result
                info("[RunDesignConsistency] Step 2/4 done: all performance tests passed.")

            info("[RunDesignConsistency] Step 3/4: running the full shared TC suite on both Python reference and RTL backends...")
            gate = DesignFinalDeliveryChecker(
                ledger_file=str(
                    Path(self.output_dir) / ".consistency-placeholder-ledger.yaml"
                ),
                final_report_file=str(
                    Path(self.output_dir) / ".consistency-placeholder-ppa.json"
                ),
                design_summary_file=str(
                    Path(self.output_dir) / ".consistency-placeholder-summary.md"
                ),
                cfg=self._cfg,
                test_dir=test_dir,
                test_glob=test_glob,
                rtl_manifest_file=rtl_manifest_file,
                final_validation_file=str(
                    Path(self.output_dir) / "reports" / "final_all_tc_validation.json"
                ),
                timeout=timeout,
            ).set_workspace(str(workspace))
            validation = gate._validate_final_all_test_cases(workspace)
            if validation is None:
                raise ValueError("final consistency test paths were not activated")
            info(
                "[RunDesignConsistency] Step 3/4 done: "
                f"python={validation.get('python', {}).get('status', '?')} "
                f"({validation.get('python', {}).get('test_case_count', '?')} TC), "
                f"rtl={validation.get('rtl', {}).get('status', '?')} "
                f"({validation.get('rtl', {}).get('test_case_count', '?')} TC)."
            )
            result["validation"] = validation
            if not run_ppa:
                return result

            architecture = load_fenced_yaml(
                resolve_workspace_path(workspace, architecture_file, must_exist=True),
                "architecture",
            )
            performance_manifest = load_json(
                resolve_workspace_path(
                    workspace, performance_manifest_file, must_exist=True
                )
            )
            rtl_config, rtl_backend = resolve_rtl_config(self._cfg)
            rtl_files = list(discover_rtl_sources(workspace, rtl_config, rtl_backend))
            rtl_rows = _hash_rows(workspace, rtl_files)
            library_files, library_rows = discover_rtl_libraries(
                workspace, rtl_config, rtl_backend
            )
            manifest = load_json(
                resolve_workspace_path(workspace, rtl_manifest_file, must_exist=True)
            )
            prepared_content = manifest.get("prepared_content")
            if not isinstance(prepared_content, dict):
                raise ValueError("RTL backend manifest has no prepared content identity")
            dut = self._cfg.get_value("_temp_cfg", {}).get("DUT")
            if not isinstance(dut, str) or not dut:
                raise ValueError("resolved configuration DUT is unavailable")
            report_file = (
                _format_path(ppa_report_file, self._cfg)
                if ppa_report_file
                else str(Path(self.output_dir) / "reports" / f"{dut}_consistency_ppa.json")
            )
            info(f"[RunDesignConsistency] Step 4/4: PPA analysis (yosys synthesis + OpenSTA timing/power, writing to {report_file})...")
            report = _run_workflow_ppa(
                workspace,
                self._cfg,
                architecture,
                rtl_config,
                rtl_backend,
                rtl_files,
                rtl_rows,
                library_files,
                list(library_rows),
                prepared_content,
                performance_manifest,
                report_file,
                baseline_report_id,
                timeout,
            )
            result["ppa"] = {
                "status": report.get("status"),
                "report_id": report.get("report_id"),
                "report_path": report_file,
                "summary": report.get("summary"),
            }
            info(
                "[RunDesignConsistency] COMPLETE: status=pass, "
                f"ppa={result.get('ppa', {}).get('status', 'skipped')}."
            )
            return result
        except Exception as exc:
            info(f"[RunDesignConsistency] FAILED: {exc}")
            return consistency_failure_diagnostic(exc, test_glob)
