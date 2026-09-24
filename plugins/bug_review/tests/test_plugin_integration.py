"""Verify isolated plugin identity, resources, entry points, and publication."""
import ast
from pathlib import Path
import subprocess

import pytest
import yaml

from bug_review.inputs import resolve_run_specs
from bug_review.benchmark_workflow.paths import default_configs, resources_root
from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash
from bug_review.workflow import ANALYSIS, SCORING, Workflow, main, prepare


ROOT = Path(__file__).resolve().parents[1]


def test_explicit_and_configured_inputs(tmp_path, monkeypatch):
    """Explicit paths use cwd; configured paths use the config directory."""
    source = tmp_path / "runs"
    source.mkdir()
    monkeypatch.chdir(tmp_path)
    assert resolve_run_specs(tmp_path / "config.toml", {}, ["model=runs"]) == [("model", str(source))]
    config = {"model_inputs": {"a": ["runs"], "b": ["missing"]}, "exclude_models": ["b"]}
    monkeypatch.chdir(ROOT)
    assert resolve_run_specs(tmp_path / "config.toml", config, []) == [("a", str(source))]
    for value in ["model", "=runs", "model="]:
        with pytest.raises(ValueError, match="LABEL=PATH"):
            resolve_run_specs(tmp_path / "config.toml", {}, [value])
    with pytest.raises(ValueError, match="do not exist"):
        resolve_run_specs(tmp_path / "config.toml", {}, ["a=/nonexistent-bug-review-input"])
    with pytest.raises(ValueError, match="no analysis inputs"):
        resolve_run_specs(tmp_path / "config.toml", {}, [])


def test_prepare_and_launch_use_new_plugin(tmp_path, monkeypatch):
    """Preparation and launch need no old CLI and select the new plugin identity."""
    source = tmp_path / "runs"
    source.mkdir()
    workspace = tmp_path / "analysis"
    main(["prepare-analysis", "--config", str(ROOT / "bug_review.toml"),
          "--run", f"model={source}", "--workspace", str(workspace)])
    assert Workflow(workspace).status()["current_stage"] == "inputs"
    assert (workspace / "BugReview/README.md").exists()
    commands = []
    monkeypatch.setattr("bug_review.workflow.subprocess.call", lambda command: commands.append(command) or 0)
    with pytest.raises(SystemExit) as exc:
        main(["launch", "--workspace", str(workspace), "--", "--tui"])
    assert exc.value.code == 0
    assert commands[0][-3:] == ["--plugin-workflow", "bug_review:analysis", "--tui"]
    assert commands[0][commands[0].index("--plugin") + 1] == str(ROOT)
    with pytest.raises(ValueError, match="requires replay"):
        prepare(tmp_path / "disabled", "analysis", replay={"enabled": False})


@pytest.mark.parametrize("skills_enabled", [True, False])
def test_plugin_registration_without_skill_directory(tmp_path, skills_enabled):
    """Both skill settings expose the same tools, stages, and passing stage gate."""
    from ucagent.plugins import PluginContext, create_plugin_tools, load_plugin
    from ucagent.util.config import Config
    loaded = load_plugin(str(ROOT))
    assert loaded.plugin.name == "bug_review"
    assert not loaded.plugin.skill_paths
    assert not (ROOT / "skills").exists()
    context = PluginContext(workspace=tmp_path, output_dir="results", write_dirs=("notes/",),
                            un_write_dirs=(), cfg=Config({"skill": {"use_skill": skills_enabled}}),
                            plugin_root=loaded.plugin.root)
    tools = create_plugin_tools([loaded], context)
    assert {tool.name for tool in tools} == {
        "BugReviewRunStage", "BugReviewTasks", "BugReviewSubmitResponse", "BugReviewStatus", "BugReviewWaveInfo"}
    for tool in tools:
        assert tool.args_schema.model_json_schema()["type"] == "object"
        from ucagent.tools.uctool import to_fastmcp
        assert to_fastmcp(tool).name == tool.name
    root = prepare(tmp_path, "analysis", replay={"enabled": True})
    status_tool = next(tool for tool in tools if tool.name == "BugReviewStatus")
    assert status_tool._run()["current_stage"] == "inputs"
    artifact = root / "input_inventory.json"
    atomic_write_json(artifact, {"runs": []})
    from bug_review.workflow import file_hash
    atomic_write_json(root / "workflow_state.json", {
        "config_hash": stable_hash(Workflow(root).config),
        "completed": {"inputs": {"input_inventory.json": file_hash(artifact)}}})
    checker = loaded.plugin.checkers[0](stage="inputs")
    checker.cfg = context.cfg
    checker.set_workspace(str(root)).on_init()
    assert checker.do_check(is_complete=True)[0]
    artifact.write_text("{}")
    assert checker.do_check(is_complete=True)[0] is False
    for workflow, stages in zip(loaded.plugin.workflows, (ANALYSIS, SCORING)):
        cfg = yaml.safe_load(workflow.config_file.read_text())
        assert tuple(stage["name"] for stage in cfg["stage"]) == stages
        assert cfg["skill"]["general_skill_list"] == []
        assert all(not stage.get("skill_list") for stage in cfg["stage"])
        assert all(stage["checker"][0]["clss"] == "BugReviewStageChecker" for stage in cfg["stage"])


def test_local_import_closure_and_resources():
    """No module imports the old plugin or unshipped maintenance scripts."""
    import importlib
    for path in (ROOT / "bug_review").rglob("*.py"):
        if "resources" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
            assert not any(n.split(".")[0] in {"benchmark_workflow", "ucagent_benchmark", "scripts"} for n in names)
        if path.name not in {"__main__.py", "__init__.py"}:
            importlib.import_module(".".join(path.relative_to(ROOT).with_suffix("").parts))
    assert (resources_root() / "qemu_python_launcher.sh").is_file()
    assert (resources_root() / "run_waveform_conversion.py").is_file()
    assert (default_configs() / "ground_truth_registry/manifest.json").is_file()
    assert (default_configs() / "scoring/scoring_policy_root_centric_v2.json").is_file()
    assert not (ROOT / "scripts").exists()


def test_analysis_publication_and_scoring(tmp_path, monkeypatch):
    """Publish a valid empty-Bug analysis, score it, and reject altered evidence."""
    from bug_review.benchmark_workflow import ground_truth_registry
    def reject_registry_write(*args, **kwargs):
        """Reference data must remain read-only during publication."""
        raise AssertionError("publication attempted to alter the GT registry")
    monkeypatch.setattr(ground_truth_registry, "register_or_update_dut_gt", reject_registry_write)
    payload = {"dut": "review_fixture", "model_names": ["model"], "analysis_state": "finalized",
               "analysis_schema": "benchmark_analysis.v1", "matrix": [], "benchmark_records": [],
               "rtl_root_bugs": [], "rtl_gt_selected_root_ids": [], "runs": []}
    root = prepare(tmp_path / "analysis", "analysis", replay={"enabled": True})
    atomic_write_json(root / "parsed_inputs.json", {"dut_inputs": [{"dut": "review_fixture"}]})
    atomic_write_json(root / "tasks/review_fixture/analysis.json", payload)
    workflow = Workflow(root)
    paths = workflow._publish_analysis()
    assert root / "analysis/analysis_manifest.json" in paths
    assert (root / "analysis/dut_review_fixture/reports/zh/index.html").is_file()
    main(["prepare-scoring", "--analysis-manifest", str(root / "analysis/analysis_manifest.json"),
          "--workspace", str(tmp_path / "scores")])
    scores = Workflow(tmp_path / "scores")
    for stage in SCORING:
        scores.run(stage)
        assert scores.check(stage)[0]
    assert scores.status()["complete"]
    assert (tmp_path / "scores/scores/index.html").is_file()
    assert workflow._publish_analysis() == paths
    (tmp_path / "scores/overall_model_score.json").write_text("{}")
    with pytest.raises(ValueError, match="output changed"):
        scores.status()


def test_make_routing_and_arguments(tmp_path):
    """The root Makefile forwards analysis and scoring to the isolated plugin."""
    repo = ROOT.parents[1]
    result = subprocess.run(["make", "-n", "bug_review_example", "ARGS=--mcp-server-port 5012"],
                            cwd=repo, capture_output=True, text=True, check=True)
    assert "-C plugins/bug_review" in result.stdout
    assert "-m bug_review.input_preparation" in result.stdout
    assert "--plugin-workflow bug_review:analysis" in result.stdout
    assert "--mcp-server-port 5012" in result.stdout
    assert "/output/bug_review/workspace_example" in result.stdout
    result = subprocess.run(["make", "-n", "bug-review-scoring", "ANALYSIS_NAME=example"],
                            cwd=repo, capture_output=True, text=True, check=True)
    assert "--plugin-workflow bug_review:scoring" in result.stdout
    result = subprocess.run(["make", "-n", "benchmark_example"], cwd=repo,
                            capture_output=True, text=True, check=True)
    assert "-C plugins/Benchmark" in result.stdout
