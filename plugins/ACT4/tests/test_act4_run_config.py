"""Exercise unified generation choices and the launcher without starting a model."""

import json
from pathlib import Path

import pytest
import yaml

from ucagent.plugins import PluginError
from ucagent_act4 import run_config
from ucagent_act4.workspace import validate_input_paths
from ucagent.util.config import Config


def request_data() -> dict:
    """Return the smallest useful public generation configuration."""
    return {"schema_version": 1, "suite": "Sstc", "workflow": "privileged-suite-generation", "workspace": "run"}


def test_defaults_and_mixed_sources(tmp_path):
    """Resolve every category and keep explicit local inputs separate from upstream fallbacks."""
    local = tmp_path / "previous"
    local.mkdir()
    data = request_data()
    data["assets"] = {"testplan": {"mode": "regenerate"}, "tests": {"source": "local", "path": "previous"}}
    result = run_config.resolve_run_config(data, tmp_path)
    assert set(result["assets"]) == set(run_config.ASSET_TYPES)
    assert result["accepted_partial_findings"] == []
    assert run_config.resolve_run_config({**data, "accepted_partial_findings": ["F8"]}, tmp_path)["accepted_partial_findings"] == ["F8"]
    assert result["assets"]["testplan"]["source"] is None
    assert result["assets"]["tests"]["path"] == str(local)
    assert result["assets"]["tests"]["on_missing"] == "error"
    assert result["assets"]["sail"] == {"mode": "repair_only", "source": "upstream", "path": None, "on_missing": "report"}


@pytest.mark.parametrize("category", sorted(run_config.SHARED_INPUTS))
def test_shared_inputs_do_not_inherit_regeneration(tmp_path, category):
    """Blanket suite policies cannot remove, synthesize or silently replace a shared dependency."""
    data = {**request_data(), "defaults": {"mode": "regenerate"}}
    assert run_config.resolve_run_config(data, tmp_path)["assets"][category]["mode"] == "repair_only"
    for policy in ({"mode": "regenerate"}, {"on_missing": "generate"}, {"mode": "improve"}):
        with pytest.raises(ValueError, match="repair_only"):
            run_config.resolve_run_config({**data, "assets": {category: policy}}, tmp_path)


@pytest.mark.parametrize("update", [
    {"schema_version": True}, {"suite": "unknown"}, {"workflow": "review"},
    {"unknown": 1}, {"output": "../escape"}, {"output": "capabilities/out"},
    {"assets": {"bad_category": {}}}, {"assets": {"tests": {"mode": "regenerate", "source": "upstream"}}},
    {"assets": {"tests": {"source": "local"}}}, {"assets": {"tests": {"mode": "skip"}}},
    {"defaults": {"source": "local"}}, {"limits": {"experiments": False}},
    {"runtime": {"use_skill": "false"}}, {"runtime": {"mcp_port": 0}},
    {"accepted_partial_findings": "all"}, {"accepted_partial_findings": ["F1", "F1"]}, {"accepted_partial_findings": ["*"]},
])
def test_invalid_run_choices_fail(tmp_path, update):
    """Reject misspelled fields, incoherent policies, unsafe paths and malformed limits."""
    with pytest.raises((ValueError, PluginError)):
        run_config.resolve_run_config({**request_data(), **update}, tmp_path)


def test_local_overlap_and_symlinks_fail(tmp_path):
    """Keep local originals outside the run even after resolving relative dot components."""
    (tmp_path / "run").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "run", target_is_directory=True)
    for source in ("run", "linked", "run/../run"):
        with pytest.raises(ValueError):
            run_config.resolve_run_config({**request_data(), "assets": {"tests": {"source": "local", "path": source}}}, tmp_path)


@pytest.mark.parametrize("workflow", run_config.WORKFLOWS)
def test_launcher_dry_run_and_immutable_configuration(tmp_path, monkeypatch, capsys, workflow):
    """Pass the validated snapshot to the real CLI syntax and refuse changed restart policies."""
    from ucagent.cli import get_args

    source = tmp_path / "run.yaml"
    source.write_text(yaml.safe_dump({**request_data(), "workflow": workflow}))
    monkeypatch.setenv("TEST_API_SECRET", "must-not-appear-in-banner")
    assert run_config.main([str(source), "--print-command"]) == 0
    output = capsys.readouterr().out
    banner = json.loads(output)
    command = banner["command"]
    assert banner["input_file"] == str(source) and len(banner["configuration"]["assets"]) == 9
    assert not (tmp_path / "run").exists()
    monkeypatch.setattr("sys.argv", command)
    parsed = get_args()
    assert parsed.backend == "codex" and parsed.loop and parsed.exit_on_completion
    assert parsed.mcp_server_no_file_tools
    calls = []
    def child(argv, **kwargs):
        """The full public configuration is visible before starting or resuming the child."""
        output = capsys.readouterr().out
        assert json.loads(output) == banner and "must-not-appear-in-banner" not in output
        calls.append(argv)
        return 0

    monkeypatch.setattr(run_config.subprocess, "call", child)
    assert run_config.main([str(source)]) == 0
    snapshot = yaml.safe_load((tmp_path / "run/.ucagent/act4-run.yaml").read_text())
    assert snapshot["act4_run"]["assets"]["tests"]["mode"] == "improve"
    assert snapshot["skill"]["use_skill"] is False
    assert run_config.main([str(source)]) == 0
    source.write_text(yaml.safe_dump({**request_data(), "assets": {"tests": {"mode": "regenerate"}}}))
    with pytest.raises(SystemExit):
        run_config.main([str(source)])
    assert len(calls) == 2


def test_workflow_mismatch_and_missing_config_fail(tmp_path):
    """Prevent CLI workflow choices from silently changing the reusable run contract."""
    settings = run_config.resolve_run_config(request_data(), tmp_path)
    context = {"DUT": "Sstc", "WORKSPACE": settings["workspace"], "OUT": settings["output"]}
    with pytest.raises(PluginError, match="run YAML"):
        validate_input_paths(Config({}), context)
    with pytest.raises(PluginError, match="workflow conflicts"):
        validate_input_paths(Config({"act4_run": settings, "template_overwrite": {"PROJECT": "act4_unprivileged_generate"}}), context)


@pytest.mark.parametrize("workflow,project", [("privileged-suite-generation", "act4_priv_suite_generate"), ("unprivileged-suite-generation", "act4_unprivileged_generate")])
def test_direct_start_shows_public_arguments_only(tmp_path, monkeypatch, capsys, workflow, project):
    """Direct initialization reports public switches, never private overrides or duplicate launcher banners."""
    settings = run_config.resolve_run_config({**request_data(), "workflow": workflow}, tmp_path)
    context = {"DUT": settings["suite"], "WORKSPACE": settings["workspace"], "OUT": settings["output"]}
    cfg = Config({"act4_run": settings, "template_overwrite": {"PROJECT": project}, "api_key": "not-public"})
    monkeypatch.setattr("sys.argv", ["ucagent", "--backend", "codex", "--loop", "--mcp-server-port=-1", "--config-override", "token=not-public"])
    validate_input_paths(cfg, context)
    output = capsys.readouterr().out
    assert '"--backend": "codex"' in output and '"--mcp-server-port": "-1"' in output and "not-public" not in output
    monkeypatch.setenv("ACT4_ANNOUNCED_CONFIG", str(tmp_path / "run/.ucagent/act4-run.yaml"))
    validate_input_paths(cfg, context)
    assert '"configuration":' not in capsys.readouterr().out


def test_bundled_configuration_is_complete():
    """Keep the reusable sample executable through the strict public parser."""
    path = Path(__file__).resolve().parents[1] / "examples/generation.yaml"
    result = run_config.resolve_run_config(yaml.safe_load(path.read_text()), path.parent)
    assert result["suite"] == "Sstc" and len(result["assets"]) == 9


def test_duplicate_configuration_fields_fail(tmp_path):
    """Never let a later duplicate silently override the requested source policy."""
    source = tmp_path / "duplicate.yaml"
    source.write_text(yaml.safe_dump(request_data()) + "suite: H\n")
    with pytest.raises(SystemExit):
        run_config.main([str(source), "--print-command"])


def test_launcher_rejects_unrelated_existing_checkpoints(tmp_path):
    """Require a fresh run rather than attaching a new contract to an unrelated stage history."""
    source = tmp_path / "run.yaml"
    source.write_text(yaml.safe_dump(request_data()))
    checkpoint = tmp_path / "run/.ucagent/ucagent_info.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{}")
    with pytest.raises(SystemExit):
        run_config.main([str(source)])
    assert not (checkpoint.parent / "act4-run.yaml").exists()
