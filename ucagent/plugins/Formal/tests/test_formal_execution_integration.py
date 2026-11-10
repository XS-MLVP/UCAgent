"""Integration tests for the managed Formal workflow boundary."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from formal import tools as formal_tools
from formal.checkers.formal import (
    BaseFormalChecker, CoverageAnalysisChecker, FormalSummaryChecker, ScriptGenerationChecker,
)
from formal.plugin import create_tools
from formal.skills.lib.formal_tools import generate_summary_doc
from formal.skills.lib.models import FormalRecords
from ucagent.core.plugins import PluginContext
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


class FakeExecution:
    """Record dispatch and return bounded machine-style summaries."""

    calls = []

    def __init__(self, **kwargs):
        """Keep the resolved input context for assertions."""
        self.calls.append(("init", kwargs))

    def run(self):
        """Pretend to enqueue an asynchronous proof batch."""
        self.calls.append(("run",))
        return {"status": "RUNNING"}

    def status(self, wait_s=0):
        """Return a bounded status response."""
        self.calls.append(("status",))
        return {"status": "RUNNING"}

    def cancel(self):
        """Mark the fake task cancelled."""
        self.calls.append(("cancel",))
        return {"status": "CANCELLED"}

    def review(self, **kwargs):
        """Record unresolved-property disposition arguments."""
        self.calls.append(("review", kwargs))
        return {"status": "AWAITING_REVIEW"}

    def check(self):
        """Return a current-evidence gate result without executing a batch."""
        self.calls.append(("check",))
        return False, {"error_code": "formal_execution_pending", "proof_complete": False}


def test_machine_summary_exposes_deferred_without_relabeling_as_proven(tmp_path):
    """Derived summary keeps deferred proof gaps visible alongside human conclusions."""
    records = FormalRecords(dut="DUT", summary={
        "core_function": "queue", "overall_result": "一条属性未证明",
        "acceptance_conclusion": "存在暂缓属性，验证不完整",
        "coi_assessment": {"unreachable_notes": []}, "severe_bugs": [],
        "completeness": {"safety": "partial", "liveness": "partial", "cover": "partial"},
    })
    output = tmp_path / "summary.md"
    generate_summary_doc(records, str(output), machine={
        "proof_complete": False, "counts": {"PROVEN": 3, "UNPROVEN": 1},
        "deferred_total": 1, "deferred_properties": ["DUT_checker.A_CK_SLOW"],
        "report": "proof_output/formal_runs/123/report.md",
    })
    text = output.read_text()
    assert "**未证明**: 1" in text
    assert "**暂缓**: 1" in text
    assert "DUT_checker.A_CK_SLOW" in text
    assert "proof_output/formal_runs/123/report.md" in text


def test_renderer_runs_from_resolved_workspace_without_copied_skills(tmp_path):
    """The public run path renders managed sources directly from current YAML."""
    dut = tmp_path / "DUT"
    dut.mkdir()
    (dut / "DUT.sv").write_text("module DUT(input logic clk, input logic rst_n, input logic a, output logic b); assign b = a; endmodule\n")
    out = tmp_path / "proof_output"
    out.mkdir()
    (out / ".formal_records.yaml").write_text(yaml.safe_dump({
        "dut": "DUT", "basic_info": {"clock_reset": {
            "clock_signal": "clk", "clock_count": "1", "reset_signal": "rst_n", "reset_type": "低有效同步",
        }},
        "spec": {"function_groups": [{"id": "FG-FUNC", "functions": [{
            "id": "FC-FUNC", "check_points": [{"id": "CK-FUNC", "style": "Comb",
                "description": "output equals input", "sva_body": "b == a"}],
        }]}]},
        "extra_config": {"tcl": {"timeout": 100000, "extra_commands": []}},
    }, sort_keys=False))
    formal_tools.render_environment(str(tmp_path), "proof_output", "DUT")
    for suffix in ("checker.sv", "wrapper.sv", "formal.tcl"):
        assert (out / "tests" / f"DUT_{suffix}").is_file()
    first = {suffix: (out / "tests" / f"DUT_{suffix}").read_bytes()
             for suffix in ("checker.sv", "wrapper.sv", "formal.tcl")}
    formal_tools.render_environment(str(tmp_path), "proof_output", "DUT")
    assert first == {suffix: (out / "tests" / f"DUT_{suffix}").read_bytes()
                     for suffix in first}
    assert "# UCAGENT_PROOF_BEGIN" in (out / "tests" / "DUT_formal.tcl").read_text()


def test_renderer_rejects_protected_descendants_before_generation(tmp_path, monkeypatch):
    """No generated destination bypasses a more specific no-write rule."""
    invoked = []
    monkeypatch.setattr(formal_tools.subprocess, "run", lambda *args, **kwargs: invoked.append(args))
    with pytest.raises(ValueError, match="not allowed to write"):
        formal_tools.render_environment(
            str(tmp_path), "proof_output", "DUT", write_dirs=["proof_output"],
            un_write_dirs=["proof_output/tests"],
        )
    assert not invoked


def test_renderer_rejects_symlinked_records_and_source(tmp_path, monkeypatch):
    """The generator cannot follow attacker-selected source or record links."""
    invoked = []
    monkeypatch.setattr(formal_tools.subprocess, "run", lambda *args, **kwargs: invoked.append(args))
    external = tmp_path / "elsewhere"
    external.mkdir()
    (tmp_path / "DUT").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be symlinks"):
        formal_tools.render_environment(str(tmp_path), "proof_output", "DUT")
    (tmp_path / "DUT").unlink()
    (tmp_path / "DUT").mkdir()
    (tmp_path / "proof_output").mkdir()
    (tmp_path / "proof_output" / ".formal_records.yaml").symlink_to(external / "records.yaml")
    with pytest.raises(ValueError, match="must not be symlinks"):
        formal_tools.render_environment(str(tmp_path), "proof_output", "DUT")
    assert not invoked


def test_runformal_plugin_factory_dispatch_and_mcp_contract(tmp_path, monkeypatch):
    """One plugin tool exposes strict local and MCP argument contracts."""
    monkeypatch.setattr(formal_tools, "FormalExecution", FakeExecution)
    monkeypatch.setattr(formal_tools, "render_environment", lambda *args, **kwargs: None)
    FakeExecution.calls.clear()
    context = PluginContext(
        workspace=tmp_path, output_dir="proof_output", write_dirs=("proof_output",),
        un_write_dirs=("DUT",), cfg=Config({"output": "proof_output"}),
        plugin_root=Path(formal_tools.__file__).parent, dut_name="DUT",
    )
    (tool,) = create_tools(context)
    assert tool.name == "RunFormal"
    assert tool.invoke({"action": "run"}) == {"status": "RUNNING"}
    assert tool.invoke({"action": "status"}) == {"status": "RUNNING"}
    assert tool.invoke({"action": "cancel"}) == {"status": "CANCELLED"}
    assert tool.invoke({"action": "review", "property_names": ["top.A_CK_SLOW"],
                        "disposition": "defer", "reason": "1200s unresolved",
                        "next_action": "Retry after proving the required invariant"}) == {"status": "AWAITING_REVIEW"}
    assert FakeExecution.calls[0][1]["output_dir"] == "proof_output"
    assert FakeExecution.calls[0][1]["un_write_dirs"] == ["DUT"]
    assert FakeExecution.calls[-1][1]["action"] == "defer"
    with pytest.raises(ValidationError):
        formal_tools.RunFormalArgs.model_validate({"action": "status", "typo": True})
    converted = to_mcp_tool(tool)
    assert asyncio.run(converted.run({"action": "status"}, context=None)) == {"status": "RUNNING"}
    with pytest.raises(ToolError):
        asyncio.run(converted.run({"action": "status", "typo": True}, context=None))


def test_script_check_requires_explicit_run_and_never_starts_proof(tmp_path, monkeypatch):
    """Stage Check validates current proof evidence, not an implicit TCL run."""
    FakeExecution.calls.clear()
    output = tmp_path / "proof_output"
    (output / "tests").mkdir(parents=True)
    (output / "tests" / "DUT_formal.tcl").write_text("read_design -top DUT\nprove\n")
    monkeypatch.setattr(formal_tools, "render_environment", lambda *args, **kwargs: None)
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda path: SimpleNamespace())
    monkeypatch.setattr("formal.checkers.formal.get_primary_clock_reset", lambda _: ({}, {}))
    monkeypatch.setattr("formal.checkers.formal.validate_extra_config_against_design", lambda _: [])
    monkeypatch.setattr(BaseFormalChecker, "_execution", lambda _: FakeExecution())
    checker = ScriptGenerationChecker(dut_name="DUT")
    checker.cfg = Config({"output": "proof_output"})
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    ok, result = checker.do_check()
    assert not ok
    assert "RunFormal(action='run')" in result["next_action"]
    assert not any(call[0] == "run" for call in FakeExecution.calls)


def test_coverage_gate_rejects_stale_report_without_current_artifact(tmp_path, monkeypatch):
    """Old projected fanin files cannot satisfy a new run's coverage gate."""
    output = tmp_path / "proof_output" / "tests" / "avis"
    output.mkdir(parents=True)
    (output / "fanin.rep").write_text("Nets: 100/100 100%\n")
    monkeypatch.setattr(BaseFormalChecker, "_execution", lambda _: SimpleNamespace(
        check=lambda: (True, {"run_id": "current", "coverage_artifact": None})
    ))
    checker = CoverageAnalysisChecker(dut_name="DUT")
    checker.cfg = Config({"output": "proof_output"})
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    ok, result = checker.do_check()
    assert not ok
    assert result["error_code"] == "formal_coverage_missing"


def test_summary_rejects_unreported_deferred_gap(tmp_path, monkeypatch):
    """A hand-written success claim cannot conceal machine UNPROVEN evidence."""
    summary = {"core_function": "queue", "overall_result": "全部通过",
               "acceptance_conclusion": "建议验收", "completeness": {
                   "safety": "covered", "liveness": "covered", "cover": "covered"}}
    monkeypatch.setattr(BaseFormalChecker, "_execution", lambda _: SimpleNamespace(
        check=lambda: (True, {"proof_complete": False, "deferred_total": 1})
    ))
    monkeypatch.setattr("formal.checkers.formal.load_records", lambda path: SimpleNamespace(summary=summary))
    checker = FormalSummaryChecker(dut_name="DUT")
    checker.cfg = Config({"output": "proof_output"})
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    ok, result = checker.do_check()
    assert not ok
    assert "UNPROVEN" in result["details"]


def test_formal_check_resolves_output_even_with_disabled_skills(tmp_path):
    """A configured output directory does not depend on copied skills or env OUT."""
    checker = ScriptGenerationChecker(dut_name="DUT")
    checker.cfg = Config({"output": "proof_output", "skill": {"use_skill": False}})
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    assert checker.paths.base == str(tmp_path / "proof_output")


def test_checker_uses_final_cli_output_not_yaml_default(tmp_path, monkeypatch):
    """The final OUT template value is shared with the plugin tool context."""
    monkeypatch.setenv("OUT", "unrelated-process-output")
    checker = ScriptGenerationChecker(dut_name="DUT", cfg=Config({"output": "yaml_default"}))
    checker.cfg._temp_cfg = {"OUT": "cli_selected"}
    checker.set_workspace(str(tmp_path))
    checker.on_init()
    assert checker.paths.base == str(tmp_path / "cli_selected")


@pytest.mark.parametrize("use_skill", [True, False])
def test_workflow_budgets_and_skill_independent_actions(tmp_path, monkeypatch, use_skill):
    """Both skill modes load the same budgets and expose a non-skill execution path."""
    from ucagent.util.config import get_config
    from formal.execution import ExecutionPolicy

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    workflow = Path(formal_tools.__file__).parent / "workflows" / "formal.yaml"
    cfg = get_config(workflow_config_file=str(workflow), cfg_override=[{"skill.use_skill": use_skill}])
    policy = ExecutionPolicy.from_cfg(cfg)
    assert policy.first_pass_budget_s == 300
    assert policy.analysis_threshold_s == 1200
    text = workflow.read_text()
    assert "RunFormal(action=run)" in text
    assert "首要行动：加载" not in text
    assert "所有内容必须通过脚本" not in text
    assert not (tmp_path / ".ucagent" / "skills").exists()
    context = PluginContext(workspace=tmp_path, output_dir="proof_output", dut_name="DUT",
                            write_dirs=("proof_output",), un_write_dirs=("DUT",),
                            cfg=cfg, plugin_root=workflow.parent.parent)
    assert create_tools(context)[0].name == "RunFormal"


def test_plugin_factory_rejects_invalid_budget_at_startup(tmp_path):
    """Malformed runtime budgets fail at tool registration, not after launching work."""
    context = PluginContext(workspace=tmp_path, output_dir="output", dut_name="DUT",
                            write_dirs=("output",), un_write_dirs=("DUT",),
                            cfg=Config({"runtime_options": {"formal_execution": {"first_pass_budget_s": False}}}),
                            plugin_root=Path(formal_tools.__file__).parent)
    with pytest.raises(ValueError, match="positive integers"):
        create_tools(context)
