"""Thin UCAgent adapters around deterministic project and test automation."""

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, WithJsonSchema, model_validator
import yaml

from ucagent.core.tools.uctool import UCTool
from ucagent.core.stage.vmanager import ManagerTool
from ucagent.util.config import load_runtime_config
from ucagent.util.file_policy import deepest_matching_write_entry, is_file_writeable, wildcard_entry_overlaps

from .audit import audit_project, summarize
from .build import build_dut
from .coverage import coverage_data
from .coverage_preflight import check_coverage_batch
from .layout import project_layout
from .paths import local_path, write_json
from .project import inspect_inputs, scaffold
from .runner import archived_run, current_run, default_targets, run_tests
from .sources import capture_source_documents, record_source_documents
from .waveform import WaveInfo


def require_writable(workspace, cfg, paths, *, tree=False):
    """Check both link names and resolved targets, including protected output descendants."""
    root = Path(workspace).resolve()
    protected = list(cfg.get_value("un_write_dirs", []))
    writable = list(cfg.get_value("write_dirs", []))
    for path in paths:
        relative = path.relative_to(root).as_posix()
        local_path(root, relative)
        for name in {relative, path.resolve().relative_to(root).as_posix()}:
            allowed, reason = is_file_writeable(name, protected, writable)
            if not allowed:
                raise ValueError(reason)
            if tree:
                write_depth, _ = deepest_matching_write_entry(name, writable)
                for entry in protected:
                    if len(Path(entry).parts) > write_depth and wildcard_entry_overlaps(entry, name):
                        if not is_file_writeable(entry, protected, writable)[0]:
                            raise ValueError(f"Output directory {name} overlaps protected path {entry}")


class ProjectArgs(BaseModel):
    """Select a deterministic operation on the active UT project."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["inspect", "scaffold", "audit", "summary"] = Field(description="Inspect inputs, create only missing files, audit a phase, or derive the delivery summary.")
    phase: Literal["inputs", "design", "plan", "environment", "tests", "triage", "final",
                   "requirements", "dut", "groups", "points", "checkpoints", "line_map",
                   "refine", "static", "wrapper", "fixture", "coverage_groups",
                   "coverage_points", "coverage_checks", "env_spec_review", "bundle", "mock",
                   "mock_fixture", "mock_tests", "mock_batch", "environment_impl",
                   "env_selftest", "env_review", "api", "model", "model_fixture",
                   "api_tests", "templates", "case_batch", "refine_tests",
                   "static_validation", "line_coverage", "random", "review", "comprehensive"] = Field(
                       default="tests", description="Named phase or original UT audit phase to validate.")


class UTProject(UCTool):
    """Create and inspect project artifacts without requiring a generation Skill."""

    name: str = "UTProject"
    description: str = "Inspect the active DUT inputs; scaffold missing ucv4xs-style project files without overwriting existing work; audit artifacts; derive a report from actual tests. Call inspect and scaffold first. Summary preserves raw failures and unresolved scope."
    args_schema: type[BaseModel] = ProjectArgs
    workspace: str
    project: str
    dut: str
    cfg: Any
    _source_documents: dict = PrivateAttr(default_factory=dict)

    def __init__(self, **data):
        """Capture configured sources before the model can write task artifacts."""
        super().__init__(**data)
        self._source_documents = capture_source_documents(
            self.workspace, self.dut, self.project, self.cfg.get_value("runtime_options.ut_documents", None))

    def _run(self, action, phase="tests", run_manager=None):
        """Dispatch a fixed operation under the configured workspace write policy."""
        try:
            args = ProjectArgs(action=action, phase=phase)
            if args.action == "audit":
                return audit_project(self.workspace, self.dut, self.project, args.phase,
                                     line_coverage_required=self.cfg.get_value("runtime_options.ut_line_coverage", True))
            root = local_path(self.workspace, self.project, allow_root=True)
            if action == "scaffold":
                return {"ok": True, **scaffold(self.workspace, self.dut, self.project,
                                               self.cfg.get_value("runtime_options.ut_dut_package", None),
                                               authorize=lambda paths: require_writable(self.workspace, self.cfg, paths))}
            candidates = [root / "results/input_inventory.json"] if action == "inspect" else [root / "docs/README.md"]
            require_writable(self.workspace, self.cfg, candidates)
            if action == "inspect":
                data = inspect_inputs(self.workspace, self.dut, self.project,
                                      self.cfg.get_value("runtime_options.ut_documents", None),
                                      self.cfg.get_value("runtime_options.ut_rtl_dirs", None),
                                      self.cfg.get_value("runtime_options.ut_document_mode", "auto"))
                record_source_documents(self.workspace, self.dut, self.project, self._source_documents)
                write_json(root / "results/input_inventory.json", data)
                return {"ok": True, **data}
            data = summarize(self.workspace, self.dut, self.project,
                             line_coverage_required=self.cfg.get_value("runtime_options.ut_line_coverage", True))
            return {"ok": True, "status": data["status"], "run": data["run"], "tests": data["tests"],
                    "report": f"{self.project}/docs/README.md", "problems": data["problems"],
                    "missing_scenarios": data["missing_scenarios"][:12],
                    "unconfirmed_requirements": data["unconfirmed_requirements"][:12],
                    "scope_exclusions": data["scope_exclusions"][:12], "issues_total": len(data["issues"])}
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
            return {"ok": False, "error_code": "UT_PROJECT_ERROR", "error": str(error)[:2000],
                    "next_action": "Check the named path or project setting, then retry this operation."}


class NativeBatchPoint(BaseModel):
    """An exact CoverageInfo point; source-line groups are not point evidence."""

    model_config = ConfigDict(extra="forbid")
    metric: Literal["line", "branch", "toggle"]
    build: str = Field(min_length=1)
    source: str = Field(min_length=1)
    line: int = Field(ge=0, strict=True)
    point: str | None = Field(default=None, description="Exact native point from CoverageInfo; omit for a physical line.")

    @model_validator(mode="after")
    def exact_point(self):
        if self.metric == "line" and self.point is not None or self.metric != "line" and not self.point:
            raise ValueError("Use one physical line or one exact branch/toggle point")
        return self


class CoverageBatch(BaseModel):
    """The evidence for promoting one native coverage batch to a full selection."""

    model_config = ConfigDict(extra="forbid")
    baseline: str = Field(min_length=1, description="Previous signed full run, results/<run-id>.")
    targeted: str = Field(min_length=1, description="Current signed targeted run of impacted exact nodeids, results/<run-id>.")
    # Inline this finite inner type so CLI MCP clients get no nested $ref.
    expect_hits: list[Annotated[NativeBatchPoint, WithJsonSchema(NativeBatchPoint.model_json_schema())]] = Field(
        min_length=1, description="Exact baseline zeros this batch must hit, not unrelated net coverage.")
    retain_hits: list[Annotated[NativeBatchPoint, WithJsonSchema(NativeBatchPoint.model_json_schema())]] = Field(
        description="Affected existing hits that must stay nonzero in the targeted run; supply [] only if none are affected.")


class RunArgs(BaseModel):
    """Use explicit test selectors rather than arbitrary shell or pytest options."""

    model_config = ConfigDict(extra="forbid")
    targets: list[str] = Field(default_factory=list, description="Paths or exact node IDs relative to the UT project, below testbenches. Empty runs the current DUT plus shared tests.")
    keyword: str = Field(default="", description="Optional pytest -k selection expression; empty for final full regression.")
    markers: str = Field(default="", description="Optional pytest -m expression; empty for final full regression.")
    timeout: int = Field(default=0, ge=0, le=3600, description="Seconds; zero uses the configured test timeout.")
    seed: int | None = Field(default=None, ge=1, le=2147483647, description="Requested native seed; null uses the task seed. The project fixture must pass this seed to the native constructor.")
    waveforms: bool = Field(default=True, description="Capture native DUT waveforms before test execution. Does not advance simulation or change pin writes; false explicitly omits waveform capture.")
    coverage_batch: CoverageBatch | None = Field(default=None, description="Required for full RunToffee in native coverage review when the workflow preflight is enabled; omit for targeted runs.")


class CoverageArgs(BaseModel):
    """Page actual uncovered counters without substituting hand-authored percentages."""

    model_config = ConfigDict(extra="forbid")
    metric: Literal["line", "branch", "toggle"] = Field(default="line", description="Metric whose uncovered physical counters to inspect; absent metrics remain not_collected.")
    view: Literal["points", "groups"] = Field(default="points", description="Read exact zero points, or the source-line directory with real zero-point counts and review selectors.")
    build: str | None = Field(default=None, min_length=1, description="Optional exact native build ID filter; never a glob.")
    source: str | None = Field(default=None, min_length=1, description="Optional exact counter source path filter; no path rewriting or globbing.")
    line: int | None = Field(default=None, ge=0, description="Optional exact native source line filter.")
    offset: int = Field(default=0, ge=0, description="Offset into the selected zero points or source-line directory.")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum points or directory entries to return.")
    run: str | None = Field(default=None, min_length=1, description="Read the exact signed project-relative results/<run-id> for unchanged inputs, without updating latest or passing a stage.")


class CoverageInfo(UCTool):
    """Inspect signed simulator counters and the current line-gap review."""

    name: str = "CoverageInfo"
    description: str = "Read signed line/branch/toggle zero points or a bounded source-line directory with exact counts and review selectors. Optionally select an exact archived run for current inputs. Supports exact build/source/line filters. Distinguishes not_collected from zero/full coverage; a group is not a justification. Never runs tests or changes targets."
    args_schema: type[BaseModel] = CoverageArgs
    workspace: str
    project: str
    dut: str
    cfg: Any

    def _run(self, metric="line", offset=0, limit=50, run_manager=None, view="points", build=None, source=None, line=None, run=None):
        """Return bounded native metrics and gap locations from the signed run only."""
        try:
            args = CoverageArgs(metric=metric, offset=offset, limit=limit, view=view, build=build, source=source,
                                line=line, run=run)
            checked = (current_run(self.workspace, self.project) if args.run is None
                       else archived_run(self.workspace, self.project, args.run))
            if checked["record"]["dut"] != self.dut:
                raise ValueError("Current run belongs to another DUT")
            filters = {name: getattr(args, name) for name in ("build", "source", "line") if getattr(args, name) is not None}
            directory = (args.metric, filters, args.offset, args.limit) if args.view == "groups" else None
            data = coverage_data(self.workspace, self.project, self.dut, checked, directory=directory)
            if args.view == "groups":
                page = data["directory"]
            else:
                rows = data[args.metric]["uncovered"]
                if filters:
                    rows = [row for row in rows if all(row[name] == value for name, value in filters.items())]
                page = {"uncovered_total": len(rows), "uncovered": rows[args.offset:args.offset + args.limit],
                        "next_offset": args.offset + args.limit if args.offset + args.limit < len(rows) else None}
            result = {"ok": True, "run": checked["record"]["run"], "artifacts": data["artifacts"],
                     "full_selection": checked["record"]["full_selection"], "explicit_archive": args.run is not None,
                    "metrics": {name: {key: value for key, value in data[name].items() if key != "uncovered"}
                                 for name in ("line", "branch", "toggle")},
                    "review": {**data["review"], "gaps_total": len(data["review"]["gaps"]), "gaps": data["review"]["gaps"][:12]},
                    "metric": args.metric, "view": args.view, "filters": filters, "offset": args.offset, **page}
            return result
        except (ValueError, KeyError, TypeError, OSError) as error:
            return {"ok": False, "error_code": "UT_COVERAGE_INVALID", "error": str(error)[:1800],
                    "next_action": "Read Guide_Doc/ut-coverage.md; obtain current native coverage, then review the actual uncovered counters. Do not substitute a zero/full percentage for missing data."}


class BuildArgs(BaseModel):
    """Select existing workspace RTL, not shell commands or arbitrary build flags."""

    model_config = ConfigDict(extra="forbid")
    source_file: str = Field(description="Workspace-relative top-level .v or .sv source.")
    top: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="RTL top name; defaults to the active DUT name.")
    filelist: list[str] = Field(default_factory=list, description="Additional explicit workspace-relative .v/.sv dependencies.")
    jobs: int = Field(default=2, ge=1, le=32, description="Native build parallelism.")
    build_timeout: int | None = Field(default=None, ge=1, le=14400, strict=True, description="Positive native build budget in seconds, at most 14400; null uses the configured ut_timeout. Independent of test budgets. Ask the operator for a sufficient call window before a long build.")
    timing: bool = Field(default=False, strict=True, description="Allow RTL delays during Verilator compilation; does not modify RTL.")
    rtl_defines: list[str] = Field(default_factory=list, description="Unique NAME or NAME=VALUE RTL macros for both frontend and simulator; values must be safe single-token literals.")
    include_dirs: list[str] = Field(default_factory=list, description="Workspace-relative include directories; files and linked inputs must remain inside the workspace and are fingerprinted before/after building.")


class BuildToffeeDUT(UCTool):
    """Build the actual supplied DUT package with predictable, bounded Picker options."""

    name: str = "BuildToffeeDUT"
    description: str = "Build supplied RTL into the active project's dut directory with Verilator. Supports an explicit bounded build_timeout independent of tests, timing, shared RTL macros and workspace-local include directories. Inputs/options and effective budget are recorded with build logs. Refuses to replace existing packages; never builds an example design."
    args_schema: type[BaseModel] = BuildArgs
    workspace: str
    project: str
    dut: str
    cfg: Any

    def _run(self, source_file, top=None, filelist=None, jobs=2, run_manager=None,
             timing=False, rtl_defines=None, include_dirs=None, build_timeout=None):
        """Validate arguments and native-output permissions before invoking Picker."""
        try:
            args = BuildArgs(source_file=source_file, top=top,
                              filelist=[] if filelist is None else filelist, jobs=jobs,
                              timing=timing, rtl_defines=[] if rtl_defines is None else rtl_defines,
                              include_dirs=[] if include_dirs is None else include_dirs, build_timeout=build_timeout)
            require_writable(self.workspace, self.cfg, [local_path(self.workspace, relative) for relative in
                             (f"{self.project}/dut/{self.dut}", f"{self.project}/results")], tree=True)
            timeout = self.cfg.get_value("runtime_options.ut_timeout", 1200) if args.build_timeout is None else args.build_timeout
            if args.build_timeout is not None and self.get_call_time_out() < timeout + 60:
                raise ValueError(f"Build budget {timeout}s needs a BuildToffeeDUT call window of at least {timeout + 60}s; "
                                 "ask the operator to grant that window, then retry without shortening the build budget")
            return build_dut(self.workspace, self.dut, self.project, args.source_file,
                             top=args.top, filelist=args.filelist, jobs=args.jobs, timing=args.timing,
                             rtl_defines=args.rtl_defines, include_dirs=args.include_dirs,
                              timeout=timeout,
                             cancelled=self.is_force_exit, progress=lambda message: self.stream_queue.put(message))
        except (ValueError, OSError) as error:
            return {"ok": False, "error_code": "UT_BUILD_ERROR", "error": str(error),
                    "next_action": "Check source_file/filelist/include_dirs, timing, rtl_defines and build_timeout, then read Guide_Doc/ut-project.md. Preserve existing packages and failure logs; ask the operator for a sufficient call window or an unavailable toolchain."}


class RunToffee(ManagerTool):
    """Run real tests with the selected interpreter and expose verifiable outcomes."""

    name: str = "RunToffee"
    description: str = "Execute actual DUT tests and collect exact case outcomes, native and functional coverage. Targets are project-relative testbenches paths. Empty targets select the entire active DUT. Native coverage review can require signed targeted evidence (coverage_batch) before full execution. Fix verification errors; retain reproducible DUT failures. UNCERTAIN is not PASS."
    args_schema: type[BaseModel] = RunArgs
    manager: Any = None
    workspace: str = ""
    project: str = ""
    dut: str = ""

    def bind(self, manager):
        """Bind once to resolved task configuration and stage cancellation ownership."""
        self.manager = manager
        self.workspace = manager.workspace
        values = manager.cfg.get_value("_temp_cfg")
        self.project = values["OUT"]
        self.dut = values["DUT"]
        return self

    def _run(self, targets=None, keyword="", markers="", timeout=0, seed=None, waveforms=True, run_manager=None,
             coverage_batch=None):
        """Run a bounded selection; force-exit also terminates pytest workers."""
        try:
            args = RunArgs(targets=targets or [], keyword=keyword, markers=markers, timeout=timeout, seed=seed,
                           waveforms=waveforms, coverage_batch=coverage_batch)
            root = local_path(self.workspace, self.project, allow_root=True)
            require_writable(self.workspace, self.manager.cfg, [root / "results"], tree=True)
            cfg = self.manager.cfg
            requested_seed = args.seed if args.seed is not None else cfg.seed
            line_required = cfg.get_value("runtime_options.ut_line_coverage", True)
            expected_sources = None
            if cfg.get_value("runtime_options.ut_coverage_batch_preflight", False) and line_required:
                stage = self.manager.get_current_stage()
                if (getattr(stage, "name", None) == "line_coverage_analysis_and_improvement"
                        and not args.keyword and not args.markers):
                    defaults = default_targets(root, project_layout(self.workspace, self.dut, self.project))
                    if not args.targets or set(args.targets) == set(defaults):
                        try:
                            if args.coverage_batch is None:
                                raise ValueError("A full native coverage rerun needs a signed full baseline, a current exact-node targeted run, and expected native points")
                            expected_sources = check_coverage_batch(self.workspace, self.project, self.dut,
                                                                    requested_seed, args.coverage_batch)
                        except (ValueError, KeyError, TypeError, OSError) as error:
                            return {"ok": False, "error_code": "UT_COVERAGE_PREFLIGHT", "error": str(error)[:1800],
                                    "next_action": "Reuse valid full evidence for review-only work. Otherwise verify the changed batch with exact targeted nodeids and compare signed expected and retained points before requesting full. Ask the operator if there is no comparable native baseline or a documented full-only reason."}
            runtime = load_runtime_config(self.workspace)
            return run_tests(self.workspace, self.dut, self.project, args.targets,
                             keyword=args.keyword, markers=args.markers,
                             workers=self.manager.cfg.get_value("runtime_options.ut_workers", 1),
                             timeout=args.timeout or self.manager.cfg.get_value("runtime_options.ut_timeout", 1200),
                               seed=requested_seed,
                               waveforms=args.waveforms,
                               line_coverage_required=line_required,
                              expected_sources=expected_sources,
                             python_paths=[runtime["ucagent_python_path"], *runtime.get("plugin_python_paths", [])],
                             cancelled=lambda: self.is_force_exit() or self.manager.agent.is_break(),
                             progress=lambda message: self.stream_queue.put(message))
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
            return {"ok": False, "error_code": "UT_RUN_ERROR", "error": str(error)[:2000],
                    "next_action": "Check project configuration and test target; ask the operator if the runtime is unavailable."}


def create_tools(context):
    """Build task-bound tools without registering any Legacy workflow capability."""
    values = dict(workspace=str(context.workspace), project=context.output_dir, dut=context.dut_name, cfg=context.cfg)
    return [UTProject(**values), BuildToffeeDUT(**values), WaveInfo(**values), CoverageInfo(**values)]
