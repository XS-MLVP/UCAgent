"""Canonical CLI, make examples, catalog and configuration for persistent sessions."""
from pathlib import Path
import subprocess
import pytest
import yaml
from ucagent.interfaces.cli.arguments import get_args
from ucagent.interfaces.cli.options import parse_launch_options
from ucagent.core.global_agent.session_contracts import GlobalSettings

ROOT = Path(__file__).resolve().parents[1]

def test_global_defaults_to_idle_tui(tmp_path):
    options = parse_launch_options(get_args([str(tmp_path), "--agent-mode", "global"]))
    assert options["interface"] == "tui"
    assert not any(c.startswith(("chat ", "loop", "continue")) for c in options["commands"])

def test_global_initial_prompt_is_one_turn(tmp_path):
    options = parse_launch_options(get_args([str(tmp_path), "--agent-mode", "global", "--loop", "--loop-msg", "do this", "--exit-on-completion"]))
    assert options["interface"] == "none"
    assert "chat 'do this'" in options["commands"]
    assert not any(c.startswith("loop") for c in options["commands"])

@pytest.mark.parametrize("backend", ["langchain", "codex"])
@pytest.mark.parametrize("external", [True, False])
def test_documented_policy_loads_unittest_catalog(backend, external):
    """The documented policy resolves a bundled workflow for each supported tool mode."""
    from ucagent.core.workflow.contracts import WorkflowCatalog
    document = (ROOT / "docs/content/02_usage/13_global_agent.md").read_text()
    policy = yaml.safe_load(document.split("```yaml\n", 1)[1].split("```", 1)[0])["global_agent"]
    policy["plugin_selectors"] = [str(ROOT / "ucagent/plugins/UnitTest")]
    policy["launch_profiles"]["standard"].update(backend=backend, no_embed_tools=external)
    settings = GlobalSettings.model_validate(policy)
    catalog = WorkflowCatalog(settings)
    assert set(catalog.entries) == {"unittest:unittest"}
    workflow = catalog.entries["unittest:unittest"].workflow
    assert workflow.config_file.is_file() and workflow.purpose
    assert settings.launch_profiles["standard"].backend == backend
    assert settings.launch_profiles["standard"].no_embed_tools is external


@pytest.mark.parametrize("target,prompt,interface", [
    ("global", False, "--tui"), ("global_tui", False, "--tui"),
    ("global_interactive", False, "--human"), ("global_unit", True, "--tui"),
])
def test_make_entry_contract(target, prompt, interface, tmp_path):
    """Normal launch targets preserve idle startup and their selected interface."""
    result = subprocess.run(["make", "-n", target, "GLOBAL_WORKSPACE=" + str(tmp_path)],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    launch = result.stdout.strip().splitlines()[-1]
    assert "--agent-mode global" in launch
    assert "unittest:unittest" in launch
    assert ("--loop-msg" in launch) is prompt
    assert interface in launch
    assert "--exit-on-completion" not in launch
    assert "--loop " not in launch


def test_make_accepts_codex_and_headless_request(tmp_path):
    """The ordinary entry supports both backend scopes and one-shot requests."""
    result = subprocess.run([
        "make", "-n", "global", "GLOBAL_WORKSPACE=" + str(tmp_path), "GLOBAL_UI=",
        "GLOBAL_PROMPT=Verify the DUT", "GLOBAL_BACKEND=codex",
        "GLOBAL_ARGS=--backend codex --exit-on-completion",
    ], cwd=ROOT, capture_output=True, text=True, check=True)
    launch = result.stdout.strip().splitlines()[-1]
    assert '--loop-msg "Verify the DUT"' in launch
    assert "--backend codex" in launch and "global_agent.launch_profiles.standard.backend=codex" in launch
    assert "--exit-on-completion" in launch
    assert "--tui" not in launch and "--human" not in launch


def test_global_mcp_prompt_uses_available_tools(tmp_path):
    """External Global backends must not be directed to removed business-stage tools."""
    from ucagent.util.config import get_config
    cfg = get_config(workspace=str(tmp_path), workflow_config_file=str(ROOT / "ucagent/core/global_agent/workflow.yaml"))
    prompt = cfg.get_value("mcp_server.init_prompt")
    assert "StartSuper" in prompt and "ListWorkflows" in prompt
    assert "RoleInfo" not in prompt and "ReadTextFile" not in prompt
