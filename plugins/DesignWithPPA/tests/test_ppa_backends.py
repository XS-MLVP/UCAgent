"""Backend/PDK extension, measurement identity, and process lifecycle regressions."""

from __future__ import annotations

import helpers  # noqa: F401

from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import threading
import time

import pytest
from pydantic import ValidationError

from design_with_ppa.ppa import (
    AnalyzePPA, AnalyzePPAArgs, PPABackend, PPAConfig, PPAContext, PPARequest,
    PPAResult, compare_ppa_reports, resolve_ppa_config,
)
from design_with_ppa.ppa.backends.yosys_opensta import YosysOpenSTABackend
from design_with_ppa.ppa.config import resolve_pdk
from design_with_ppa.ppa.process import ProcessRunner
from design_with_ppa.checkers.ppa_iteration import _resolved_workflow_ppa_config
from design_with_ppa.plugin import create_tools, get_plugin
from helpers import _config
from test_repo_module import repo_case  # noqa: F401
from design_with_ppa.repo.validation import read_contract
from ucagent.plugins import PluginContext


class IndependentBackend(PPABackend):
    """Controlled external-backend double using a technology model and Python."""

    name = "independent_test_backend"
    version = "1"

    def analyze(self, request: PPARequest, context: PPAContext) -> PPAResult:
        """Exercise resolved inputs, options, progress, runner, and normalized output."""

        context.check_deadline()
        context.progress("Independent backend: reading technology model")
        assert all(path.is_absolute() for path in request.rtl_files)
        completed = context.run_process(
            [sys.executable, "-c", "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
             str(request.pdk.files["model"][0])], context.run_dir, context.deadline,
        )
        assert completed.returncode == 0
        result = PPAResult(
            summary={"design_type": "combinational",
                     "area": {"total": float(completed.stdout) * request.options.get("scale", 1), "unit": "um^2"},
                     "timing": {"critical_path_delay_ns": 2.0, "maximum_frequency_hz": 5e8, "metric_kind": "critical_path_delay"},
                     "power": {"total_w": 0.001}},
            waveform_aggregation={"method": "duration_weighted_independent_tc_activity", "reliable": True,
                                  "test_cases": [{"path": row["path"], "sha256": row["sha256"], "status": "valid"}
                                                 for row in request.waveform_provenance],
                                  "merged_input_bits": [{"input_bit": "a", "density_hz": 1e6, "duty_cycle": 0.5}]},
            tools={"test_process": {"version": "1"}}, waveform_scope="tb.dut",
        )
        if request.options.get("invalid"):
            result.summary["power"]["total_w"] = float("nan")
        if request.options.get("missing_tc"):
            result.waveform_aggregation["test_cases"] = []
        return result


@pytest.fixture
def independent_case(tmp_path: Path) -> tuple[AnalyzePPA, AnalyzePPAArgs]:
    """Create a custom PDK with no Liberty dependency and a selectable backend."""

    (tmp_path / "dut.v").write_text("module dut(input a, output y); assign y=a; endmodule\n")
    (tmp_path / "tc.vcd").write_text("controlled backend waveform input\n")
    (tmp_path / "technology.model").write_text("12.5\n")
    config = {"backend": f"{__name__}:IndependentBackend", "backend_options": {"scale": 2},
              "pdk": {"name": "custom_process", "corner": "ss_0p8v_125c", "files": {"model": ["technology.model"]}}}
    tool = AnalyzePPA(workspace=str(tmp_path), analysis_config=config)
    args = AnalyzePPAArgs(rtl_files=["dut.v"], top_module="dut", waveform_files=["tc.vcd"], waveform_scope="tb.dut")
    return tool, args


def test_independent_backend_without_default_toolchain(independent_case, monkeypatch):
    """An external toolchain works even when Yosys/OpenSTA execution is forbidden."""

    tool, args = independent_case

    def forbidden(*args, **kwargs):
        """Fail if dispatch reaches any default synthesis implementation."""

        pytest.fail("default backend must not run")

    monkeypatch.setattr(YosysOpenSTABackend, "analyze", forbidden)
    report = tool.analyze(args)
    assert report["status"] == "success"
    assert report["summary"]["area"] == {"total": 25.0, "unit": "um^2"}
    assert report["provenance"]["liberty_sha256"] is None
    assert report["provenance"]["pdk"]["corner"] == "ss_0p8v_125c"
    assert report == json.loads((Path(tool.workspace) / report["report_path"]).read_text())
    second = tool.analyze(args.model_copy(update={"baseline_report_id": report["report_id"]}))
    assert second["comparison"]["compatibility"]["overall"] is True
    assert second["comparison"]["metrics"]["area"]["total"]["unit"] == "um^2"


@pytest.mark.parametrize("change,reason", [
    ("corner", "pdk_changed_or_unknown"), ("asset", "pdk_changed_or_unknown"),
    ("mapping", "pdk_changed_or_unknown"), ("options", "backend_changed_or_unknown"),
    ("backend", "backend_changed_or_unknown"), ("version", "tool_versions_changed"),
    ("unit", "area_unit_changed"),
])
def test_measurement_conditions_prevent_false_improvements(independent_case, change, reason):
    """Every measurement-affecting selection invalidates metric comparability."""

    tool, args = independent_case
    baseline = tool.analyze(args)
    current = deepcopy(baseline)
    current["summary"]["area"]["total"] /= 2
    if change == "corner":
        current["provenance"]["pdk"]["corner"] = "ff"
    elif change == "asset":
        current["provenance"]["pdk"]["files"]["model"][0]["sha256"] = "b" * 64
    elif change == "mapping":
        current["provenance"]["pdk"]["tie_high"] = {"cell": "TIEHI", "port": "Y"}
    elif change == "options":
        current["provenance"]["backend"]["options"]["scale"] = 3
    elif change == "backend":
        current["provenance"]["backend"]["version"] = "2"
    elif change == "version":
        current["provenance"]["tools"]["test_process"]["version"] = "2"
    else:
        current["summary"]["area"]["unit"] = "mm^2"
    comparison = compare_ppa_reports(baseline, current)
    assert reason in comparison["compatibility"]["area"]["reasons"]
    assert comparison["metrics"]["area"]["total"]["assessment"] == "not_comparable"


@pytest.mark.parametrize("selection", ["unknown", "missing_package:Backend", "json:loads", "json:Missing"])
def test_backend_selection_failure_is_published(independent_case, selection):
    """Configuration errors still yield durable, actionable error reports."""

    tool, args = independent_case
    tool.analysis_config = tool.analysis_config.model_copy(update={"backend": selection})
    report = tool.analyze(args)
    assert report["status"] == "error"
    assert report["cache"]["stored"] is True
    assert report["diagnostics"][0]["next_action"]


@pytest.mark.parametrize("option", ["invalid", "missing_tc"])
def test_invalid_backend_output_cannot_succeed(independent_case, option):
    """Post-construction result mutations cannot bypass the publication boundary."""

    tool, args = independent_case
    tool.analysis_config = tool.analysis_config.model_copy(update={"backend_options": {option: True}})
    report = tool.analyze(args)
    assert report["status"] == "error"
    assert report["diagnostics"][0]["error_code"] == "ppa_analysis_failed"


def test_empty_backend_result_is_partial_with_recovery(independent_case, monkeypatch):
    """A backend without measurements cannot publish success or omit recovery guidance."""

    tool, args = independent_case
    monkeypatch.setattr(IndependentBackend, "analyze", lambda self, request, context: PPAResult())
    report = tool.analyze(args)
    assert report["status"] == "partial"
    assert report["diagnostics"][0]["error_code"] == "ppa_measurement_incomplete"
    assert report["cache"]["stored"] is True


def test_backend_return_type_is_validated(independent_case, monkeypatch):
    """Returning an unvalidated report mapping cannot bypass the result contract."""

    tool, args = independent_case
    monkeypatch.setattr(IndependentBackend, "analyze", lambda self, request, context: {"status": "success"})
    report = tool.analyze(args)
    assert report["status"] == "error"
    assert "PPAResult" in report["diagnostics"][0]["error"]


def test_over_budget_backend_retains_available_measurements(independent_case, monkeypatch):
    """An expired overall budget prevents success without dropping measured results."""

    tool, args = independent_case
    valid_report = tool.analyze(args)
    result = PPAResult(**{key: valid_report[key] for key in (
        "summary", "details", "hotspots", "waveform_aggregation", "diagnostics",
    )})
    monkeypatch.setattr(IndependentBackend, "analyze", lambda self, request, context: result)
    times = iter((0.0, 11.0))
    monkeypatch.setattr("design_with_ppa.ppa.tool.time.monotonic", lambda: next(times))
    report = tool.analyze(args.model_copy(update={"timeout": 10}))
    assert report["status"] == "partial"
    assert report["summary"]["area"]["total"] == 25.0
    assert report["diagnostics"][0]["error_code"] == "ppa_deadline_exceeded"


@pytest.mark.parametrize("asset", ["missing.model", "../escape.model", "/outside.model", "linked.model"])
def test_all_pdk_files_are_confined(independent_case, asset):
    """Custom asset categories obey the same workspace restrictions as RTL."""

    tool, args = independent_case
    (Path(tool.workspace) / "linked.model").symlink_to(Path(tool.workspace) / "technology.model")
    pdk = tool.analysis_config.pdk.model_copy(update={"files": {"model": [asset]}})
    tool.analysis_config = tool.analysis_config.model_copy(update={"pdk": pdk})
    assert tool.analyze(args)["status"] == "error"


def test_technology_changes_invalidate_workflow_history(independent_case):
    """The unit workflow binds technology content, rather than just filenames."""

    tool, _ = independent_case
    root = Path(tool.workspace)
    cfg = _config()
    cfg.set_value("design_with_ppa.ppa", tool.analysis_config.model_dump())
    before = _resolved_workflow_ppa_config(cfg, "dut", root)
    (root / "technology.model").write_text("18.0\n")
    after = _resolved_workflow_ppa_config(cfg, "dut", root)
    assert before != after


def test_technology_changes_during_analysis_cannot_publish_success(independent_case, monkeypatch):
    """A measured result cannot retain a stale identity after a technology input changes."""

    tool, args = independent_case
    original = IndependentBackend.analyze

    def analyze(self, request, context):
        """Change the technology after measuring but before returning the result."""

        result = original(self, request, context)
        request.pdk.files["model"][0].write_text("18.0\n")
        return result

    monkeypatch.setattr(IndependentBackend, "analyze", analyze)
    report = tool.analyze(args)
    assert report["status"] == "error"
    assert "technology inputs changed while analysis was running" in report["diagnostics"][0]["error"]
    assert report["summary"]["area"] is None
    assert report["cache"]["stored"] is True


def test_repo_contract_freezes_backend_and_technology(repo_case):
    """Repository measurements freeze content and options even with custom resources."""

    paths = repo_case
    asset = paths.workspace / "process.model"
    asset.write_text("12.5\n")
    config = {"backend": f"{__name__}:IndependentBackend", "backend_options": {"scale": 2},
              "pdk": {"name": "custom", "files": {"model": ["process.model"]}}}
    paths.cfg.set_value("design_with_ppa.ppa", config)
    before = read_contract(paths)[2]["ppa"]["analysis"]
    asset.write_text("20.0\n")
    changed_file = read_contract(paths)[2]["ppa"]["analysis"]
    assert before != changed_file
    paths.cfg.set_value("design_with_ppa.ppa.backend_options.scale", 3)
    assert changed_file != read_contract(paths)[2]["ppa"]["analysis"]


@pytest.mark.parametrize("files", [{"model": []}, {"model": ["technology.model", "./technology.model"]}])
def test_invalid_pdk_file_sets_fail(independent_case, files):
    """Empty resources and repeated resolved paths cannot produce valid evidence."""

    tool, args = independent_case
    pdk = tool.analysis_config.pdk.model_copy(update={"files": files})
    tool.analysis_config = tool.analysis_config.model_copy(update={"pdk": pdk})
    assert tool.analyze(args)["status"] == "error"


def test_plugin_factory_uses_resolved_backend_settings(independent_case):
    """Direct tool calls and workflow measurements consume the same selection."""

    tool, _ = independent_case
    cfg = _config()
    cfg.set_value("design_with_ppa.ppa", tool.analysis_config.model_dump())
    context = PluginContext(workspace=Path(tool.workspace), plugin_root=Path(__file__).resolve().parents[1], output_dir="output", write_dirs=("output",), un_write_dirs=(), cfg=cfg)
    created = create_tools(context)[0]
    assert created.analysis_config == resolve_ppa_config(cfg)
    assert not get_plugin().command_requirements
    for workflow in get_plugin().workflows:
        assert {"design_with_ppa.ppa.backend", "design_with_ppa.ppa.pdk.name", "design_with_ppa.ppa.pdk.corner"} <= set(workflow.runtime_config_keys)


def test_default_backend_uses_configured_constant_cells(independent_case, monkeypatch):
    """A custom process uses only its declared technology mapping cell names."""

    tool, args = independent_case
    root = Path(tool.workspace)
    (root / "cells.lib").write_text("library(custom) {}")
    config = PPAConfig(pdk={"name": "custom", "files": {"liberty": ["cells.lib"]},
                            "tie_high": {"cell": "TIEHI", "port": "Y"}, "tie_low": {"cell": "TIELO", "port": "Y"}})
    backend = YosysOpenSTABackend()
    backend._pdk = resolve_pdk(config.pdk, tool._resolve_input)

    def process(command, cwd, deadline):
        """Supply minimal synthesis artifacts while retaining the generated script."""

        for name in ("generic_stats", "generic", "mapped_stats", "mapped"):
            (cwd / f"{name}.json").write_text("{}")
        return subprocess.CompletedProcess(command, 0, "", "")

    backend._context = PPAContext(root, time.monotonic() + 20, process, lambda value: None)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/yosys")
    backend._synthesize([root / "dut.v"], args.top_module, root / "cells.lib", root, time.monotonic() + 20)
    script = (root / "synth.ys").read_text()
    assert "hilomap -hicell TIEHI Y -locell TIELO Y" in script
    assert "LOGIC1_X1" not in script
    assert "TIEHIx1_ASAP7_75t_R" not in script


@pytest.mark.parametrize("config", [{"backend_options": {"bad": float("nan")}}, {"pdk": {"extra": 1}}, {"pdk": {"tie_high": {"cell": "x;exec", "port": "Y"}}}])
def test_invalid_configuration_rejected(config):
    """Only finite, declared configuration and safe mapping identifiers are accepted."""

    with pytest.raises((ValueError, ValidationError)):
        PPAConfig.model_validate(config)


def test_process_runner_deadline_and_cancellation(tmp_path):
    """Both deadline expiry and user cancellation terminate backend subprocesses."""

    runner = ProcessRunner()
    with pytest.raises(TimeoutError):
        runner._run_process([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, time.monotonic() + 0.05)
    results = []

    def run():
        """Start a long tool call so the test can cancel its process group."""

        results.append(runner._run_process([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, time.monotonic() + 20))

    thread = threading.Thread(target=run)
    thread.start()
    limit = time.monotonic() + 5
    while not runner._active_processes and time.monotonic() < limit:
        time.sleep(0.01)
    runner.cb_force_exit()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert results[0].returncode != 0
    assert not runner._active_processes
