"""Workspace-confined PPA tool, provenance, report publication, and backend dispatch."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Optional
import json
import re
import tempfile
import time

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import ArgsSchema
from pydantic import Field, PrivateAttr
from ucagent.tools.uctool import UCTool
from ucagent.tools.fileops import is_file_writeable
from ucagent.util.functions import make_llm_tool_ret
from ucagent.util.log import info

from .models import AnalyzePPAArgs
from .common import _diagnostic, _sha256_file, _json_safe, _redact_private_paths
from .comparison import _compare_reports, _nested_value
from .config import PPAConfig, resolve_pdk
from .backend import PPARequest, PPAContext, PPAResult, load_backend, backend_identity
from .process import ProcessRunner
from .storage import ReportStore
from .dashboard import refresh_dashboard_snapshot


class AnalyzePPA(UCTool):
    """Analyze pre-layout area, timing, and waveform-driven power for Verilog RTL."""

    name: str = "AnalyzePPA"
    description: str = (
        "Synthesize one Verilog design and produce a structured pre-layout PPA report. "
        "Provide all .v RTL sources, the exact top module, a common DUT waveform scope, "
        "and a list of independent .vcd/.fst performance-test TC waveforms. The tool "
        "validates every TC, merges input activity by total simulated duration, runs "
        "the configured analysis backend, determines whether the design is "
        "combinational or sequential, and reports area, timing or equivalent maximum "
        "frequency, power, detailed breakdowns, hotspots, diagnostics, and provenance. "
        "Every report receives a unique report_id and is retained in the internal cache; "
        "provide baseline_report_id to compare the current metrics with a cached report. "
        "The cache retains the newest 100 reports by default. Paths must be workspace-relative. "
        "Do not concatenate waveforms before calling."
    )
    args_schema: Optional[ArgsSchema] = AnalyzePPAArgs
    return_direct: bool = False
    call_lock_arguments: tuple[str, ...] = ()

    workspace: str = Field(default=".", description="UCAgent workspace root.")
    output_dir: str = Field(default="output", description="Default report directory.")
    cache_limit: int = Field(
        default=100,
        exclude=True,
        repr=False,
        description="Maximum number of recent reports retained in the internal cache.",
    )
    write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    un_write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    analysis_config: PPAConfig = Field(default_factory=PPAConfig, exclude=True, repr=False)
    _runner: ProcessRunner = PrivateAttr(default_factory=ProcessRunner)
    _reports: ReportStore = PrivateAttr()

    def __init__(
        self,
        workspace: str = ".",
        output_dir: str = "output",
        cache_limit: int = 100,
        write_dirs: list[str] | None = None,
        un_write_dirs: list[str] | None = None,
        analysis_config: PPAConfig | dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """Configure workspace confinement and report write permissions."""

        super().__init__(**kwargs)
        self.workspace = str(Path(workspace).resolve())
        output = Path(output_dir)
        if output.is_absolute():
            try:
                output = output.resolve(strict=False).relative_to(self.workspace)
            except ValueError as exc:
                raise ValueError("output_dir must be inside the workspace") from exc
        self.output_dir = output.as_posix()
        if isinstance(cache_limit, bool) or not isinstance(cache_limit, int):
            raise ValueError("cache_limit must be an integer")
        if cache_limit < 1 or cache_limit > 10000:
            raise ValueError("cache_limit must be between 1 and 10000")
        self.cache_limit = cache_limit
        self.analysis_config = PPAConfig.model_validate(analysis_config or {})
        self._reports = ReportStore(self.workspace, cache_limit)
        self.write_dirs = list(write_dirs) if write_dirs is not None else None
        self.un_write_dirs = list(un_write_dirs) if un_write_dirs is not None else None

    def cb_force_exit(self) -> None:
        """Cancel all external processes launched by the configured backend."""

        self._runner.cb_force_exit()

    def analysis_identity(self, liberty_file: str | None = None) -> dict[str, Any]:
        """Resolve backend selection and hash all technology inputs for workflow history."""

        backend = load_backend(self.analysis_config.backend)
        pdk = resolve_pdk(self.analysis_config.pdk, self._resolve_input, liberty_file)
        return {"backend": backend_identity(backend, self.analysis_config), "pdk": pdk.provenance}

    def _resolve_input(self, value: str, suffixes: set[str] | None) -> Path:
        """Resolve an existing regular file without allowing workspace escape."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError("input paths must be non-empty strings")
        normalized = value.replace("\\", "/")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError(f"input path contains a control character: {value!r}")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"path must remain relative to the workspace: {value}")
        lexical = Path(self.workspace) / pure
        resolved = lexical.resolve(strict=True)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError(f"path escapes the workspace: {value}") from exc
        if resolved != lexical.absolute() and any(
            parent.is_symlink()
            for parent in [lexical, *lexical.parents]
            if parent != Path(self.workspace).parent
        ):
            raise ValueError(f"symbolic links are not accepted for input paths: {value}")
        if not resolved.is_file():
            raise ValueError(f"input is not a regular file: {value}")
        if suffixes is not None and resolved.suffix.lower() not in suffixes:
            raise ValueError(
                f"input has unsupported extension {resolved.suffix!r}: {value}; "
                f"expected one of {sorted(suffixes)}"
            )
        return resolved

    def _resolve_report(self, value: str) -> tuple[Path, str]:
        """Resolve a writable JSON destination and reject symlink traversal."""

        normalized = value.replace("\\", "/")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("report_path contains a control character")
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() in {"", "."}:
            raise ValueError("report_path must be a workspace-relative file path")
        if pure.suffix.lower() != ".json":
            raise ValueError("report_path must end with .json")
        allowed, reason = is_file_writeable(
            pure.as_posix(), self.un_write_dirs, self.write_dirs
        )
        if not allowed:
            raise ValueError(reason)
        lexical = Path(self.workspace) / pure
        current = Path(self.workspace)
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"report_path traverses a symbolic link: {value}")
        resolved_parent = lexical.parent.resolve(strict=False)
        try:
            resolved_parent.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("report_path escapes the workspace") from exc
        return lexical, pure.as_posix()

    def analyze(
        self,
        arguments: AnalyzePPAArgs,
        *,
        rtl_provenance: list[dict[str, str]] | None = None,
        rtl_library_provenance: list[dict[str, Any]] | None = None,
        trusted_rtl_library_files: tuple[Path, ...] | None = None,
        trusted_rtl_files: tuple[Path, ...] | None = None,
        rtl_systemverilog: bool = False,
    ) -> dict[str, Any]:
        """Execute PPA with optional trusted inputs and authored provenance.

        ``rtl_systemverilog`` must be set when trusted RTL files were emitted
        in SystemVerilog form by a language backend, so Yosys reads them with
        SystemVerilog mode enabled.
        """

        diagnostics: list[dict[str, Any]] = []
        info(
            f"[AnalyzePPA] Starting: top={arguments.top_module}, "
            f"{len(arguments.rtl_files or [])} RTL files, "
            f"{len(arguments.waveform_files or [])} waveforms, "
            f"scope={arguments.waveform_scope}"
        )
        default_report = f"{self.output_dir}/{arguments.top_module}_ppa_report.json"
        report_value = arguments.report_path or default_report
        report_path, report_relative = self._resolve_report(report_value)
        report_id = self._reports._new_report_id()
        authored_rtl_paths: set[Path] = set()
        published_libraries: list[dict[str, Any]] = []
        report: dict[str, Any] = {
            "schema_version": "1.2",
            "report_id": report_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "summary": {
                "design_type": "unknown",
                "area": None,
                "timing": None,
                "power": None,
            },
            "comparison": {
                "status": "not_requested",
                "baseline_report_id": None,
                "current_report_id": report_id,
            },
            "hotspots": {
                "timing_paths": [],
                "power_instances": [],
                "findings": [],
            },
            "waveform_aggregation": {
                "method": "duration_weighted_independent_tc_activity",
                "formula": {
                    "density_hz": "sum(tc_transition_count) / sum(tc_duration_seconds)",
                    "duty_cycle": "sum(tc_high_duration_seconds) / sum(tc_duration_seconds)",
                },
                "reliable": False,
                "test_cases": [],
                "merged_input_bits": [],
            },
            "details": {
                "classification": None,
                "area_by_cell_type": {},
                "timing_paths": [],
                "power_groups": [],
            },
            "diagnostics": diagnostics,
            "provenance": {
                "rtl_files": [],
                "rtl_libraries": [],
                "waveform_files": [],
                "top_module": arguments.top_module,
                "waveform_scope": arguments.waveform_scope,
                "liberty_file": None,
                "liberty_sha256": None,
                "sdc_file": arguments.sdc_file,
                "sdc_sha256": None,
                "clock_constraint": (
                    {
                        "clock_port": arguments.clock_port,
                        "clock_period_ns": arguments.clock_period_ns,
                    }
                    if arguments.clock_port is not None
                    else None
                ),
                "tools": {},
            },
            "cache": {
                "stored": False,
                "limit": self.cache_limit,
            },
            "report_path": report_relative,
        }
        deadline = time.monotonic() + arguments.timeout
        try:
            if not arguments.rtl_files or not arguments.waveform_files or not arguments.top_module:
                raise ValueError("analysis requires nonempty rtl_files, waveform_files, and top_module")
            if len(set(arguments.rtl_files)) != len(arguments.rtl_files):
                raise ValueError("rtl_files contains duplicate paths")
            if len(set(arguments.waveform_files)) != len(arguments.waveform_files):
                raise ValueError("waveform_files contains duplicate paths")
            if trusted_rtl_files is None:
                rtl_files = [
                    self._resolve_input(path, {".v"}) for path in arguments.rtl_files
                ]
            else:
                rtl_files = []
                for path in trusted_rtl_files:
                    if not isinstance(path, Path) or not path.is_absolute():
                        raise ValueError(
                            "trusted_rtl_files must contain absolute Path values"
                        )
                    resolved = path.resolve()
                    if path.is_symlink() or not resolved.is_file() or resolved.suffix != ".v":
                        raise ValueError(
                            "trusted_rtl_files must contain regular Verilog files"
                        )
                    rtl_files.append(resolved)
                if (
                    not rtl_files
                    or len(set(rtl_files)) != len(rtl_files)
                    or rtl_files != sorted(rtl_files, key=lambda item: item.as_posix())
                ):
                    raise ValueError(
                        "trusted_rtl_files must be a non-empty unique path-sorted tuple"
                    )
            if (rtl_library_provenance is None) != (
                trusted_rtl_library_files is None
            ):
                raise ValueError(
                    "RTL library provenance and trusted source files must be provided together"
                )
            if rtl_library_provenance is not None:
                if len(rtl_library_provenance) != len(trusted_rtl_library_files):
                    raise ValueError(
                        "RTL library provenance and trusted source file counts differ"
                    )
                for index, (row, source) in enumerate(
                    zip(rtl_library_provenance, trusted_rtl_library_files)
                ):
                    if (
                        not isinstance(row, dict)
                        or set(row) != {"library_index", "path", "sha256"}
                        or isinstance(row["library_index"], bool)
                        or not isinstance(row["library_index"], int)
                        or row["library_index"] < 0
                        or not isinstance(row["path"], str)
                        or not row["path"]
                        or Path(row["path"]).is_absolute()
                        or ".." in Path(row["path"]).parts
                        or not isinstance(row["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    ):
                        raise ValueError(
                            f"rtl_library_provenance[{index}] is invalid"
                        )
                    if (
                        not isinstance(source, Path)
                        or not source.is_absolute()
                        or source.is_symlink()
                        or not source.is_file()
                    ):
                        raise ValueError(
                            f"trusted_rtl_library_files[{index}] is invalid"
                        )
                    resolved_source = source.resolve()
                    if _sha256_file(resolved_source) != row["sha256"]:
                        raise ValueError(
                            f"rtl_library_provenance[{index}] hash differs from the trusted source"
                        )
                    published_libraries.append(dict(row))
                report["provenance"]["rtl_libraries"] = published_libraries
            waveform_files = [
                self._resolve_input(path, {".vcd", ".fst"})
                for path in arguments.waveform_files
            ]
            hashes: dict[str, str] = {}
            for label, path in zip(arguments.waveform_files, waveform_files):
                digest = _sha256_file(path)
                if digest in hashes:
                    raise ValueError(
                        "waveform_files contains duplicate SHA-256 content: "
                        f"{hashes[digest]} and {label}"
                    )
                hashes[digest] = label
                report["provenance"]["waveform_files"].append(
                    {
                        "path": label,
                        "format": path.suffix.lower().lstrip("."),
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
                )
            if trusted_rtl_files is None:
                for label, path in zip(arguments.rtl_files, rtl_files):
                    report["provenance"]["rtl_files"].append(
                        {
                            "path": label,
                            "sha256": _sha256_file(path),
                            "size_bytes": path.stat().st_size,
                        }
                    )
            pdk = resolve_pdk(self.analysis_config.pdk, self._resolve_input, arguments.liberty_file)
            sdc = self._resolve_input(arguments.sdc_file, {".sdc"}) if arguments.sdc_file else None
            report["provenance"]["pdk"] = pdk.provenance
            libraries = pdk.provenance["files"].get("liberty", [])
            report["provenance"]["liberty_file"] = libraries[0]["path"] if len(libraries) == 1 else None
            report["provenance"]["liberty_sha256"] = libraries[0]["sha256"] if len(libraries) == 1 else None
            report["provenance"]["sdc_sha256"] = _sha256_file(sdc) if sdc else None
            backend = load_backend(self.analysis_config.backend)
            report["provenance"]["backend"] = backend_identity(backend, self.analysis_config)
            with tempfile.TemporaryDirectory(prefix="ucagent-ppa-") as temporary:
                request = PPARequest(
                    arguments=arguments, rtl_files=tuple(rtl_files),
                    waveform_files=tuple(waveform_files),
                    waveform_provenance=tuple(report["provenance"]["waveform_files"]),
                    sdc_file=sdc, pdk=pdk, systemverilog=rtl_systemverilog,
                    options=self.analysis_config.model_dump()["backend_options"],
                )
                context = PPAContext(Path(temporary), deadline, self._runner._run_process, self.put_alive_data)
                result = backend.analyze(request, context)
                if not isinstance(result, PPAResult):
                    raise TypeError("PPA backend must return a validated PPAResult")
                # Revalidate at the boundary, including instances constructed without validation.
                result = PPAResult.model_validate(result.model_dump())
                if resolve_pdk(self.analysis_config.pdk, self._resolve_input, arguments.liberty_file).provenance != pdk.provenance:
                    raise ValueError(
                        "PPA technology inputs changed while analysis was running; "
                        "finish the edits and rerun AnalyzePPA"
                    )
                if result.waveform_aggregation["reliable"]:
                    cases = result.waveform_aggregation["test_cases"]
                    if [row.get("path") for row in cases] != arguments.waveform_files:
                        raise ValueError("reliable backend activity must cover the complete ordered waveform_files set")
                for field in ("summary", "details", "hotspots", "waveform_aggregation"):
                    report[field] = getattr(result, field)
                diagnostics.extend(result.diagnostics)
                report["provenance"]["tools"] = result.tools
                report["provenance"]["waveform_scope"] = result.waveform_scope or arguments.waveform_scope
                report["status"] = "success" if result.complete else "partial"
                try:
                    context.check_deadline()
                except TimeoutError:
                    # Keep completed measurements, but never accept an over-budget run.
                    report["status"] = "partial"
                    diagnostics.append(_diagnostic(
                        "analysis", "ppa_deadline_exceeded",
                        "PPA analysis exceeded the overall deadline; available measurements were retained.",
                        "Resolve the slow analysis phase or increase timeout, then rerun AnalyzePPA.",
                    ))
                if not result.complete and not diagnostics:
                    diagnostics.append(_diagnostic(
                        "analysis", "ppa_measurement_incomplete",
                        "The analysis did not provide every required PPA metric and reliable waveform activity.",
                        "Check the selected analysis inputs and constraints, then rerun AnalyzePPA with complete performance waveforms.",
                    ))
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "analysis",
                    "ppa_analysis_failed",
                    str(exc),
                    "Fix the exact input, dependency, synthesis, or path error reported above and rerun AnalyzePPA with the same complete input contract.",
                )
            )
            report["status"] = "error"

        if rtl_provenance is not None:
            published_rtl = []
            if not isinstance(rtl_provenance, list) or not rtl_provenance:
                raise ValueError("rtl_provenance must be a non-empty source list")
            for index, row in enumerate(rtl_provenance):
                if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
                    raise ValueError(f"rtl_provenance[{index}] is invalid")
                source = self._resolve_input(row["path"], None)
                authored_rtl_paths.add(source.resolve())
                digest = _sha256_file(source)
                if digest != row["sha256"]:
                    raise ValueError(
                        f"rtl_provenance[{index}] hash differs from the authored source"
                    )
                published_rtl.append(
                    {
                        "path": row["path"],
                        "sha256": digest,
                        "size_bytes": source.stat().st_size,
                    }
                )
            report["provenance"]["rtl_files"] = published_rtl

        if trusted_rtl_files is not None:
            private_rtl_files = tuple(
                path.resolve()
                for path in trusted_rtl_files
                if path.resolve() not in authored_rtl_paths
            )
            report = _redact_private_paths(report, private_rtl_files)
            report["provenance"]["rtl_libraries"] = published_libraries
            diagnostics = report["diagnostics"]

        if arguments.baseline_report_id is not None:
            try:
                baseline = self._reports._load_cached_report(arguments.baseline_report_id)
                report["comparison"] = _compare_reports(baseline, report)
            except Exception as exc:
                try:
                    available_report_ids = self._reports._available_report_ids()
                except Exception:
                    available_report_ids = []
                report["comparison"] = {
                    "status": "error",
                    "baseline_report_id": arguments.baseline_report_id,
                    "current_report_id": report_id,
                    "error": str(exc),
                    "available_report_ids": available_report_ids,
                }
                diagnostics.append(
                    _diagnostic(
                        "comparison",
                        "baseline_report_unavailable",
                        str(exc),
                        "Rerun with baseline_report_id set to one of available_report_ids, or omit it to create a new baseline.",
                        artifact=f".ucagent/ppa_reports/{arguments.baseline_report_id}.json",
                        observed={
                            "baseline_report_id": arguments.baseline_report_id,
                            "available_report_ids": available_report_ids,
                        },
                    )
                )
                if report["status"] == "success":
                    report["status"] = "partial"

        try:
            self._reports._store_cached_report(report)
        except Exception as exc:
            report["cache"] = {
                "stored": False,
                "limit": self.cache_limit,
                "error": str(exc),
            }
            diagnostics.append(
                _diagnostic(
                    "report_cache",
                    "report_cache_failed",
                    str(exc),
                    "Fix workspace .ucagent/ppa_reports permissions or integrity, then rerun AnalyzePPA to create a reusable report_id.",
                    artifact=".ucagent/ppa_reports",
                )
            )
            if report["status"] == "success":
                report["status"] = "partial"
                comparison_status = _nested_value(
                    report, ("comparison", "detail_changes", "status")
                )
                if isinstance(comparison_status, dict):
                    comparison_status["current"] = "partial"
                    comparison_status["changed"] = (
                        comparison_status.get("baseline") != "partial"
                    )
        report = _json_safe(report)
        info(f"[AnalyzePPA] Phase 4/4: writing report to {report_path} and refreshing dashboard...")
        self._reports._write_report(report_path, report)
        refresh_dashboard_snapshot(self.workspace, self.output_dir, report)
        info(
            f"[AnalyzePPA] COMPLETE: status={report.get('status')}, "
            f"report_id={report.get('report_id')}"
        )
        return report

    def _derive_workspace_arguments(
        self,
        rtl_files: list[str] | None,
        top_module: str | None,
        waveform_files: list[str] | None,
        waveform_scope: str | None,
    ) -> tuple[list[str], str, list[str], str]:
        """Fill omitted required arguments from the current workspace state.

        The RTL backend manifest supplies the authored sources and top module;
        the performance manifest supplies the ordered waveform list and scope.
        This lets ``tool_invoke AnalyzePPA`` regenerate a report without
        hand-copying paths that the workflow already recorded.
        """

        import json as _json
        from ucagent.util.functions import load_json_file
        workspace = Path(self.workspace).resolve()
        if not rtl_files or not top_module:
            manifest_path = workspace / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
            if not manifest_path.is_file():
                raise ValueError(
                    "rtl_files/top_module omitted but no RTL backend manifest found at "
                    ".ucagent/design_with_ppa/rtl_backend_manifest.json; "
                    "pass them explicitly or run the RTL stage first."
                )
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            if not rtl_files:
                rtl_files = [
                    row["path"]
                    for row in manifest.get("rtl_sources", [])
                    if isinstance(row, dict) and isinstance(row.get("path"), str)
                ]
                if not rtl_files:
                    raise ValueError("RTL backend manifest has no rtl_sources paths.")
            if not top_module:
                top_module = manifest.get("top_module") or ""
                if not top_module:
                    raise ValueError("RTL backend manifest has no top_module.")
        waveform_files = list(waveform_files or [])
        if not waveform_files or not waveform_scope:
            perf_path = workspace / "output" / "performance" / "performance_manifest.json"
            if self.output_dir:
                perf_path = workspace / self.output_dir / "performance" / "performance_manifest.json"
            if not perf_path.is_file():
                raise ValueError(
                    "waveform_files/waveform_scope omitted but no performance manifest "
                    "found at the configured output's performance/performance_manifest.json; "
                    "pass them explicitly or run the performance evidence stage first."
                )
            perf = _json.loads(perf_path.read_text(encoding="utf-8"))
            if not waveform_files:
                for entry in perf.get("tests", []):
                    if not isinstance(entry, dict):
                        continue
                    wave = entry.get("waveform")
                    if isinstance(wave, dict) and isinstance(wave.get("path"), str):
                        waveform_files.append(wave["path"])
                    elif isinstance(wave, str):
                        waveform_files.append(wave)
                if not waveform_files:
                    raise ValueError("Performance manifest has no waveform paths.")
            if not waveform_scope:
                waveform_scope = perf.get("waveform_scope") or ""
            if not waveform_scope:
                # The workflow default is TOP.<top_module>; the analysis also
                # auto-discovers a deeper wrapper scope from the VCD header
                # when this default does not cover the top-level input bits.
                waveform_scope = f"TOP.{top_module}"
        return rtl_files, top_module, waveform_files, waveform_scope

    def _run(
        self,
        rtl_files: list[str] | None = None,
        top_module: str | None = None,
        waveform_files: list[str] | None = None,
        waveform_scope: str | None = None,
        liberty_file: str | None = None,
        sdc_file: str | None = None,
        clock_port: str | None = None,
        clock_period_ns: float | None = None,
        report_path: str | None = None,
        baseline_report_id: str | None = None,
        max_timing_paths: int = 10,
        max_power_instances: int = 10,
        timeout: int = 300,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Validate public arguments, execute analysis, and return the structured report."""

        del run_manager
        rtl_files, top_module, waveform_files, waveform_scope = (
            self._derive_workspace_arguments(
                rtl_files, top_module, waveform_files, waveform_scope
            )
        )
        arguments = AnalyzePPAArgs(
            rtl_files=rtl_files,
            top_module=top_module,
            waveform_files=waveform_files,
            waveform_scope=waveform_scope,
            liberty_file=liberty_file,
            sdc_file=sdc_file,
            clock_port=clock_port,
            clock_period_ns=clock_period_ns,
            report_path=report_path,
            baseline_report_id=baseline_report_id,
            max_timing_paths=max_timing_paths,
            max_power_instances=max_power_instances,
            timeout=timeout,
        )
        return make_llm_tool_ret(self.analyze(arguments), check_pass=False)
