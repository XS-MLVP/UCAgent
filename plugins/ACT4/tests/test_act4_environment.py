"""Exercise reusable ACT4 environment probing, installation, and receipt validation."""

from pathlib import Path
import subprocess
import sys
import tempfile

import pytest
import yaml

from act4_privileged_suite import environment
from act4_privileged_suite.plugin import get_plugin


def plan_for(tmp_path: Path, optional_failure: bool = False) -> dict:
    """Create a complete tool plan with one isolated fixture installation."""
    plan = {"schema_version": 1, "tools": []}
    for identifier in sorted(environment.TOOL_IDS):
        tool = {
            "id": identifier,
            "version": "Python 3.",
            "basis": "test fixture",
            "probe": ["{PYTHON}", "--version"],
            "expected_output": r"Python 3\.",
            "install": [],
            "bin_dirs": ["bin"],
            "storage": "persistent",
            "unavailable_reason": "Not required by the test fixture",
        }
        if optional_failure and identifier == "reference":
            tool.update(probe=["missing-reference-fixture", "--version"], expected_output="fixture", unavailable_reason="Reference model intentionally unavailable")
        plan["tools"].append(tool)
    wrapper = "#!" + sys.executable + "\nprint('act4-fixture 1.0')\n"
    source = tmp_path / "fixture-source"
    source.write_text(wrapper, encoding="utf-8")
    source.chmod(0o755)
    plan["tools"].append({
        "id": "fixture", "version": "act4-fixture 1.0", "basis": "test fixture",
        "probe": ["act4-fixture", "--version"], "expected_output": r"act4-fixture 1\.0",
        "install": [["mkdir", "-p", "{PREFIX}/bin"], ["cp", str(source), "{PREFIX}/bin/act4-fixture"]],
        "bin_dirs": ["bin"], "storage": "persistent",
    })
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    return environment.read_plan(tmp_path)


def test_preparation_installs_once_then_reuses_persistent_tool(tmp_path, monkeypatch) -> None:
    """Install into a versioned user prefix and validate reuse through PATH and hashes."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    plan = plan_for(tmp_path)

    receipt = environment.prepare(tmp_path, plan, timeout=60)

    tool = receipt["tools"]["fixture"]
    assert tool["status"] == "ready"
    assert tool["origin"] == "installed"
    assert Path(tool["executable"]).is_relative_to(tmp_path / "home")
    assert environment.prepared_environment(tmp_path)["PATH"].startswith(str(Path(tool["executable"]).parent))
    shell = subprocess.run(
        ["bash", "-c", f"source {tmp_path / 'activate.sh'} && act4-fixture --version"],
        capture_output=True, text=True, check=True,
    )
    assert "act4-fixture 1.0" in shell.stdout

    reused = environment.prepare(tmp_path, plan, timeout=60)

    assert reused["tools"]["fixture"]["status"] == "ready"
    assert reused["tools"]["fixture"]["origin"] == "cache"
    assert not any(item.get("log", "").startswith("fixture-install-") for item in reused["tools"]["fixture"]["attempts"])


def test_receipt_detects_plan_changes(tmp_path, monkeypatch) -> None:
    """Reject stale receipts rather than silently using altered installation inputs."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    environment.prepare(tmp_path, plan_for(tmp_path), timeout=60)
    (tmp_path / "plan.yaml").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Environment evidence changed: plan.yaml"):
        environment.prepared_environment(tmp_path)


def test_missing_optional_tool_is_a_recorded_limitation(tmp_path) -> None:
    """Preserve an unavailable reference model without misreporting it as installed."""
    receipt = environment.prepare(tmp_path, plan_for(tmp_path, optional_failure=True), timeout=60)

    assert receipt["tools"]["reference"]["status"] == "unavailable"
    assert "intentionally unavailable" in receipt["tools"]["reference"]["reason"]
    assert environment.prepared_environment(tmp_path)
    assert "9/10 tools" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_temporary_installation_stays_under_system_temp(tmp_path, monkeypatch) -> None:
    """Place a conflicting tool under an isolated temporary prefix, not the persistent store."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    plan = plan_for(tmp_path)
    plan["tools"][-1]["storage"] = "temporary"
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")

    receipt = environment.prepare(tmp_path, environment.read_plan(tmp_path), timeout=60)

    prefix = Path(receipt["tools"]["fixture"]["prefix"])
    assert prefix.is_relative_to(Path(tempfile.gettempdir()))
    assert not prefix.is_relative_to(tmp_path / "home")


@pytest.mark.parametrize("install", [["sudo", "apt", "install", "tool", "{PREFIX}"], ["curl", "-L", "https://example.invalid/tool"]])
def test_plan_rejects_global_or_unscoped_install_commands(tmp_path, install) -> None:
    """Require direct prefix-scoped installers and reject global package commands."""
    plan = plan_for(tmp_path)
    plan["tools"][-1]["install"] = [install]
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="prefix-scoped|explicitly use|not allowed|write directly under"):
        environment.read_plan(tmp_path)


@pytest.mark.parametrize("install", [
    [["/tmp/untrusted/cp", "source", "{PREFIX}/bin/tool"]],
    [["cp", "source", "{PREFIX}/../escaped"]],
])
def test_plan_rejects_executable_and_destination_path_escapes(tmp_path, install) -> None:
    """Reject path-based command allowlist bypasses and prefix traversal."""
    plan = plan_for(tmp_path)
    plan["tools"][-1]["install"] = install
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="not allowed|remain below"):
        environment.read_plan(tmp_path)


def test_python_placeholder_installer_is_accepted(tmp_path) -> None:
    """Allow bounded pip installation through the current UCAgent interpreter."""
    plan = plan_for(tmp_path)
    python = next(tool for tool in plan["tools"] if tool["id"] == "python")
    python.update(install=[["{PYTHON}", "-m", "pip", "install", "--prefix", "{PREFIX}", "ruff==0.15.22"]])
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")

    validated = environment.read_plan(tmp_path)

    assert next(tool for tool in validated["tools"] if tool["id"] == "python")["install"]


def test_environment_guide_plan_example_matches_checker_contract(tmp_path) -> None:
    """Keep the documented complete plan schema executable by the validator."""
    guide = Path(__file__).resolve().parents[1] / "src/act4_privileged_suite/Guide_Doc/ACT4_Environment_Guide.md"
    text = guide.read_text(encoding="utf-8")
    example = text.split("```yaml\n", 1)[1].split("```", 1)[0]
    (tmp_path / "plan.yaml").write_text(example, encoding="utf-8")

    parsed = environment.read_plan(tmp_path)

    assert environment.TOOL_IDS <= {tool["id"] for tool in parsed["tools"]}


def test_every_workflow_prepares_environment_before_asset_execution() -> None:
    """Allow read-only XiangShan scope discovery before tool setup; keep generation/review unchanged."""
    for workflow in get_plugin().workflows:
        config = yaml.safe_load(workflow.config_file.read_text(encoding="utf-8"))
        first = config["stage"][1 if workflow.name == "xiangshan-v3-handoff" else 0]
        assert first["name"] == "prepare_environment"
        gate = first["checker"][0]
        assert gate["clss"] == "ACT4EnvironmentChecker"
        assert gate["args"]["environment_dir"].endswith("/{DUT}/environment")
