"""Plugin commands are explicit, optional and share the application's operation slot."""

from types import SimpleNamespace
import threading
import pytest

from test_runtime_host import make_host
from ucagent.control.commands import CommandSession, create_registry
from ucagent.control.controller import ControlError
from ucagent.plugins import Plugin, LoadedPlugin, PluginError, register_plugin_commands, validate_plugin, plugin_summary
from unity_test.operations.waveform_replay import WaveformReplay, waveform_commands


def test_plugin_absence_registration_and_collision(tmp_path):
    """An unloaded workflow exposes no domain command; aliases cannot overwrite core names."""
    host, runtime = make_host(tmp_path)
    assert "waveform_replay" not in host.registry.complete("")
    plugin = validate_plugin(Plugin("wave", "1.0.0", "Test commands", tmp_path,
                                    command_factories=(waveform_commands,)), check_dependencies=False)
    loaded = LoadedPlugin(plugin, "test", "test")
    register_plugin_commands(host.registry, [loaded])
    assert host.registry.resolve("waveform_replay").handler is not None
    assert plugin_summary(loaded)["command_factories"] == ["waveform_commands"]
    with pytest.raises(PluginError, match="conflict"):
        register_plugin_commands(host.registry, [loaded])


def test_waveform_uses_shared_slot_and_records_validation_failure(tmp_path, monkeypatch):
    """Domain failures remain failed operations and block competing model actions."""
    host, runtime = make_host(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def replay(self, arg, context=None):
        """Hold validation until a competing request has observed its model reservation."""
        entered.set()
        assert release.wait(3)
        return {"ok": False, "result": {"error": "Evidence stale"}}

    monkeypatch.setattr(WaveformReplay, "run", replay)
    host.registry.register(waveform_commands(host.controller)[0])
    operation = host.registry.execute("waveform_replay", runtime.session).data
    try:
        assert entered.wait(2)
        with pytest.raises(ControlError, match="still active"):
            host.registry.execute("nr", runtime.session)
    finally:
        release.set()
    result = host.operations.wait(operation["id"], 2)
    assert result["state"] == "failed"
    assert result["result"]["result"]["error"] == "Evidence stale"
    assert host.operations.close(2)["closed"]
