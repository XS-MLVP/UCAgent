"""Canonical CLI, make examples, catalog and configuration for persistent sessions."""
from pathlib import Path
import subprocess
import pytest
import yaml
from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.core.multi_agent.global_agent.session_contracts import GlobalSettings

ROOT = Path(__file__).resolve().parents[1]

def test_global_defaults_to_idle_tui(tmp_path):
    options = parse_launch_options(get_args([str(tmp_path), "--agent-mode", "multi"]))
    assert options["interface"] == "tui"
    assert not any(c.startswith(("chat ", "loop", "continue")) for c in options["commands"])

def test_global_initial_prompt_is_one_turn(tmp_path):
    options = parse_launch_options(get_args([str(tmp_path), "--agent-mode", "multi", "--loop", "--loop-msg", "do this", "--exit-on-completion"]))
    assert options["interface"] == "none"
    assert "chat 'do this'" in options["commands"]
    assert not any(c.startswith("loop") for c in options["commands"])

def test_global_root_override_does_not_create_project_ucagent(tmp_path):
    """Global session output honors global_agent.root without creating a project state directory."""
    from ucagent.application.plan import LaunchRequest
    from ucagent.application.preparation import prepare_launch

    config = tmp_path / "config.yaml"
    config.write_text("backend: {key_name: langchain}\n")
    args = get_args([
        str(tmp_path), "--agent-mode", "multi", "--config", str(config),
        "--override", "global_agent.root=output",
    ])
    request = LaunchRequest(**parse_launch_options(args))

    prepared, _, _ = prepare_launch(request)

    assert prepared.cfg.get_value("global_agent.root") == str(tmp_path / "output")
    assert Path(prepared.workspace).is_relative_to(tmp_path / "output" / "sessions")
    assert not (tmp_path / ".ucagent").exists()

@pytest.mark.parametrize("backend", ["langchain", "codex"])
@pytest.mark.parametrize("external", [True, False])
def test_documented_policy_loads_unittest_catalog(backend, external):
    """The documented policy resolves a bundled workflow for each supported tool mode."""
    from ucagent.core.multi_agent.global_agent.catalog import GlobalWorkflowCatalog
    from ucagent.util.config import Config
    document = (ROOT / "docs/content/02_usage/13_global_agent.md").read_text()
    policy = yaml.safe_load(document.split("```yaml\n", 1)[1].split("```", 1)[0])["global_agent"]
    policy["plugin_selectors"] = [str(ROOT / "ucagent/plugins/UnitTest")]
    policy["launch_profiles"]["standard"].update(backend=backend, no_embed_tools=external)
    settings = GlobalSettings.model_validate(policy)
    catalog = GlobalWorkflowCatalog(Config({"global_agent": settings.model_dump()}))
    assert {"unittest:unittest", "formal:formal"} <= set(catalog.entries)
    workflow = catalog.entries["unittest:unittest"].workflow
    assert workflow.config_file.is_file() and workflow.purpose
    assert settings.launch_profiles["standard"].backend == backend
    assert settings.launch_profiles["standard"].no_embed_tools is external


@pytest.mark.parametrize("target,prompt,interface", [
    ("multi", False, "--tui"), ("multi_tui", False, "--tui"),
    ("multi_interactive", False, "--human"), ("multi_unit", True, "--tui"),
])
def test_make_entry_contract(target, prompt, interface, tmp_path, monkeypatch):
    """Normal launch targets preserve idle startup and their selected interface."""
    monkeypatch.setenv("MAKELEVEL", "1")
    result = subprocess.run(["make", "--no-print-directory", "-n", target, "MULTI_WORKSPACE=" + str(tmp_path)],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    launch = result.stdout.strip().splitlines()[-1]
    assert "--agent-mode multi" in launch
    assert ("unittest:unittest" in launch) is prompt
    assert ("--loop-msg" in launch) is prompt
    assert interface in launch
    assert "--exit-on-completion" not in launch
    assert "--loop " not in launch
    assert "global_agent.allowed_workflows" not in launch


def test_make_accepts_codex_and_headless_request(tmp_path, monkeypatch):
    """The ordinary entry supports both backend scopes and one-shot requests."""
    monkeypatch.setenv("MAKELEVEL", "1")
    result = subprocess.run([
        "make", "--no-print-directory", "-n", "multi", "MULTI_WORKSPACE=" + str(tmp_path), "MULTI_UI=",
        "MULTI_PROMPT=Verify the DUT", "MULTI_BACKEND=codex",
        "MULTI_ARGS=--backend codex --exit-on-completion",
    ], cwd=ROOT, capture_output=True, text=True, check=True)
    launch = result.stdout.strip().splitlines()[-1]
    assert '--loop-msg "Verify the DUT"' in launch
    assert "--backend codex" in launch
    assert "--exit-on-completion" in launch
    assert "--tui" not in launch and "--human" not in launch


def test_global_mcp_prompt_uses_available_tools(tmp_path):
    """External Global backends must not be directed to removed business-stage tools."""
    from ucagent.util.config import get_config
    cfg = get_config(workspace=str(tmp_path), workflow_config_file=str(ROOT / "ucagent/core/multi_agent/global_agent/workflow.yaml"))
    prompt = cfg.get_value("mcp_server.init_prompt")
    assert "StartSuper" in prompt and "ListWorkflows" in prompt
    assert "RoleInfo" not in prompt and "ReadTextFile" not in prompt
