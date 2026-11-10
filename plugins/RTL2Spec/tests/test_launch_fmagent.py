"""Verify dynamic init paths remain inert in the upstream document launcher."""

from pathlib import Path

import pytest
import yaml

from rtl2spec import fmagent, fmagent_config
from rtl2spec.launch import build_command, main


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    """Keep generated task YAML and binding configuration within this test only."""
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    monkeypatch.setattr(fmagent_config, "plugin_source_root", lambda: plugin)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_ROOT", raising=False)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_PYTHON", raising=False)
    return plugin / "rtl2spec.local.toml"


@pytest.mark.parametrize("profile", ["generic", "xiangshan"])
def test_init_paths_preserve_template_and_do_not_prepare(tmp_path, local_config, monkeypatch, capsys, profile):
    """Missing environments still export exact template settings plus absolute selected paths."""
    root = tmp_path / "FM Agent"
    target = tmp_path / "run.yaml"
    monkeypatch.setattr(fmagent.subprocess, "run", lambda *args, **kwargs: pytest.fail("init must not provision or probe absent source"))
    assert main(["--init", profile, "--config", str(target), "--fmagent-root", str(root)]) == 0
    data = yaml.safe_load(target.read_text())
    assert data.pop("fmagent") == {"root": str(root), "python": str(root / ".venv/bin/python")}
    template = Path(__file__).resolve().parents[1] / f"src/rtl2spec/launch_configs/{profile}.yaml"
    assert data == yaml.safe_load(template.read_text())
    assert "Warning: source-missing" in capsys.readouterr().err
    assert not local_config.exists()


def test_init_uses_layered_paths_but_saved_yaml_stays_fixed(tmp_path, local_config, monkeypatch):
    """New tasks snapshot selected paths; subsequent binding/exports cannot change an old task."""
    local_config.write_text('[fmagent]\nroot="/saved/root"\npython="/saved/python"\n')
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", "/temporary/root")
    target = tmp_path / "run.yaml"
    main(["--init", "generic", "--config", str(target)])
    data = yaml.safe_load(target.read_text())
    assert data["fmagent"] == {"root": "/temporary/root", "python": "/temporary/root/.venv/bin/python"}
    original = target.read_bytes()
    local_config.write_text('[fmagent]\nroot="/new/root"\npython="/new/python"\n')
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", "/new/export")
    build_command(target)
    assert target.read_bytes() == original


def test_init_invalid_config_requires_full_explicit_bypass(tmp_path, local_config):
    """Malformed TOML must not create a task unless both paths explicitly bypass it."""
    local_config.write_text("[broken")
    target = tmp_path / "run.yaml"
    with pytest.raises(SystemExit) as error:
        main(["--init", "generic", "--config", str(target), "--fmagent-root", "/source"])
    assert error.value.code == 2 and not target.exists()
    assert main(["--init", "generic", "--config", str(target), "--fmagent-root", "/source", "--fmagent-python", "/python"]) == 0
    assert yaml.safe_load(target.read_text())["fmagent"] == {"root": "/source", "python": "/python"}


def test_original_config_launch_never_resolves_or_checks_fmagent(tmp_path, local_config, monkeypatch):
    """Corrupt plugin TOML and absent FM-Agent do not change the existing --config process."""
    local_config.write_text("[broken")
    target = tmp_path / "run.yaml"
    target.write_text("rtl2spec: {workspace: work, module: Top, workflow: generic-design-document}\nfmagent: {root: /absent, python: /missing}\n")
    monkeypatch.setattr(fmagent_config, "resolve_paths", lambda *args: pytest.fail("old startup must not consult integration paths"))
    monkeypatch.setattr(fmagent, "local_status", lambda *args: pytest.fail("old startup must not preflight FM-Agent"))
    commands = []
    monkeypatch.setattr("rtl2spec.launch.os.execv", lambda executable, command: commands.append(command))
    assert main(["--config", str(target)]) == 0
    assert commands == [build_command(target)]
    with pytest.raises(SystemExit) as error:
        main(["--config", str(target), "--fmagent-root", "/must-not-override"])
    assert error.value.code == 2 and len(commands) == 1
