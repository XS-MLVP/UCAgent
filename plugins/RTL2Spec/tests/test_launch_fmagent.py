"""Verify inert init templates and exec-based optional workflow routing."""

from pathlib import Path

import pytest
import yaml

from rtl2spec import fmagent, fmagent_config
from rtl2spec.launch import build_command, main


@pytest.mark.parametrize("profile", ["generic", "xiangshan"])
def test_init_exports_only_task_settings(tmp_path, monkeypatch, profile):
    """Neither corrupt bindings nor missing dependencies affect task template export."""
    monkeypatch.setattr(fmagent_config, "resolve_paths", lambda *args: pytest.fail("init cannot resolve paths"))
    monkeypatch.setattr(fmagent, "local_status", lambda *args: pytest.fail("init cannot probe environment"))
    target = tmp_path / "run.yaml"
    assert main(["--init", profile, "--config", str(target)]) == 0
    template = Path(__file__).resolve().parents[1] / f"src/rtl2spec/launch_configs/{profile}.yaml"
    assert target.read_bytes() == template.read_bytes()
    assert yaml.safe_load(target.read_text())["fmagent"] == {
        "enabled": False, "mode": "run", "resume": False, "isolate": False,
        "submodule": "." if profile == "generic" else "src/main/scala/xiangshan/mem/sbuffer"}


@pytest.mark.parametrize("option", ["--fmagent-root", "--fmagent-python"])
def test_removed_init_path_options_rejected(tmp_path, option):
    """Path options belong only to the independent management interface."""
    with pytest.raises(SystemExit) as error:
        main(["--init", "generic", "--config", str(tmp_path / "run.yaml"), option, "/path"])
    assert error.value.code == 2
    assert not (tmp_path / "run.yaml").exists()


@pytest.mark.parametrize("profile", ["generic", "xiangshan"])
@pytest.mark.parametrize("enabled,mode", [(False, "run"), (True, "run"), (True, "reuse")])
def test_exec_routing_never_probes_environment(tmp_path, monkeypatch, profile, enabled, mode):
    """Both entry modes select composed stages while leaving preparation inside UCAgent."""
    target = tmp_path / "run.yaml"
    assert main(["--init", profile, "--config", str(target)]) == 0
    data = yaml.safe_load(target.read_text())
    data["fmagent"].update(enabled=enabled, mode=mode)
    target.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(fmagent_config, "resolve_paths", lambda *args: pytest.fail("launcher cannot resolve environment"))
    monkeypatch.setattr(fmagent, "local_status", lambda *args: pytest.fail("launcher cannot probe environment"))
    commands = []
    monkeypatch.setattr("rtl2spec.launch.os.execv", lambda executable, command: commands.append(command))
    assert main(["--config", str(target)]) == 0
    assert commands == [build_command(target)]
    command = commands[0]
    assert command[command.index("--plugin-workflow") + 1] == f"rtl2spec:{profile}-design-document" + ("-fmagent" if enabled else "")
    assert "--no-history" in command


@pytest.mark.parametrize("settings", [{"enabled": "true"}, {"root": "/old"}, {"mode": "reuse", "resume": True}])
def test_invalid_options_stop_before_exec(tmp_path, monkeypatch, settings):
    """Strict task options apply to the CLI before process replacement."""
    target = tmp_path / "run.yaml"
    target.write_text(yaml.safe_dump({"rtl2spec": {"workspace": "work", "module": "Top", "workflow": "generic-design-document"}, "fmagent": settings}))
    monkeypatch.setattr("rtl2spec.launch.os.execv", lambda *args: pytest.fail("invalid config cannot exec"))
    with pytest.raises(SystemExit) as error:
        main(["--config", str(target)])
    assert error.value.code == 2
