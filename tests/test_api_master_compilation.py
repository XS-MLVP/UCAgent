"""Exercise simulator detection and all Master compilation transports with real child processes."""

import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from ucagent.server.api_master import PdbMasterApiServer
from ucagent.util.config import Config, load_yaml_with_env_vars


@pytest.fixture
def master(tmp_path, monkeypatch):
    """Provide a deterministic PATH with fake compilers and a command-recording Picker."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("verilator", "gsim", "vcs", "uvs"):
        executable = bin_dir / name
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    picker = bin_dir / "picker"
    picker.write_text(
        f"#!{sys.executable}\n"
        '"""Record a Picker invocation without compiling hardware."""\n'
        "import json, os, pathlib, sys\n"
        "pathlib.Path('picker-command.json').write_text(json.dumps(sys.argv[1:]))\n"
        "print('picker compile log', flush=True)\n"
        "sys.exit(int(os.environ.get('TEST_PICKER_EXIT', '0')))\n"
    )
    picker.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    cfg = Config({"launch": {"file_browser_roots": [], "default_args": {
        "simulator": ["verilator", "vcs", "gsim", "uvs"], "picker_args": [],
    }}}).freeze()
    server = PdbMasterApiServer(workspace=str(tmp_path / "master"), cfg=cfg)
    return server, TestClient(server._app), bin_dir


def add_sources(server):
    """Create a workspace with the RTL and requirement consumed by compilation."""
    ws = server._create_workspace()
    server._store_file_bytes(ws["workspace_id"], "main_verilog", "Adder.v",
                             b"module Adder(); endmodule\n", "upload", "")
    server._store_file_bytes(ws["workspace_id"], "requirement", "needs.md",
                             b"Verify addition.\n", "upload", "")
    return ws


@pytest.mark.parametrize("transport", ["compile", "picker", "compile/stream", "compile/start"])
@pytest.mark.parametrize("simulator,suffix,access", [
    ("verilator", "fst", "1"), ("gsim", "fst", "0"),
    ("vcs", "fsdb", "0"), ("uvs", "usdb", "0"),
])
def test_compile_transports_dispatch_selected_simulator(master, simulator, suffix, access, transport):
    """Each API must execute and persist the same simulator, access mode, and waveform path."""
    server, client, _ = master
    ws = add_sources(server)
    base = f"/api/workspace/{ws['workspace_id']}"
    response = client.post(f"{base}/{transport}", json={
        "selected_module": "Adder", "simulator": simulator,
        "picker_args": ["--vflag", "-Wall"],
    })
    assert response.status_code == 200, response.text
    if transport == "compile/stream":
        events = [json.loads(line) for line in response.text.splitlines()]
        assert any(event.get("type") == "log" for event in events)
        result = events[-1]
        assert result["status"] == "ok", result
    elif transport == "compile/start":
        deadline = time.monotonic() + 5
        while True:
            result = client.get(f"{base}/compile/status").json()["runtime"]
            if result["status"] != "running" or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        assert result["status"] == "success", result
        assert "picker compile log" in result["chunk"]
    else:
        result = response.json()
        assert result["status"] == "ok", result
    compile_info = result["compile"]
    assert compile_info["simulator"] == simulator
    assert compile_info["waveform_suffix"] == suffix
    command = json.loads((Path(ws["workspace_dir"]) / "picker-command.json").read_text())
    assert command[command.index("--sim") + 1] == simulator
    assert command[command.index("--rw") + 1] == access
    assert command[command.index("-w") + 1] == str(Path(ws["picker_workspace"]) / "Adder" / f"Adder.{suffix}")
    assert command[-2:] == ["--vflag", "-Wall"]
    assert compile_info["picker_command"][1:] == command
    assert Path(compile_info["readme_path"]).read_text() == "Verify addition.\n"
    assert server._workspaces[ws["workspace_id"]]["compile"]["simulator"] == simulator
    # A successful compile only authorizes a launch with the same simulator.
    request = {"workspace_id": ws["workspace_id"], "selected_module": "Adder",
               "simulator": simulator, "picker_args": ["--vflag", "-Wall"]}
    assert server._validated_launch_context(request)[3] == "success"
    request["simulator"] = "vcs" if simulator != "vcs" else "verilator"
    with pytest.raises(ValueError, match="Please compile first"):
        server._validated_launch_context(request)


@pytest.mark.parametrize("missing", ["verilator", "picker"])
def test_simulator_options_refresh_missing_executables(master, missing):
    """Both discovery endpoints must report current PATH availability with a reason."""
    _, client, bin_dir = master
    (bin_dir / missing).unlink()
    for endpoint in ("/api/launch/config", "/api/launch/simulators"):
        response = client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        assert data["default_simulator"] == ("vcs" if missing == "verilator" else "")
        options = {item["value"]: item for item in data["simulators"]}
        assert set(options) == {"verilator", "gsim", "vcs", "uvs"}
        assert not options["verilator"]["enabled"]
        assert missing in options["verilator"]["reason"]
        assert options["vcs"]["enabled"] == (missing != "picker")
    # Detection is live and also rejects a non-executable file.
    (bin_dir / missing).write_text("unexecutable")
    assert not client.get("/api/launch/simulators").json()["simulators"][0]["enabled"]
    (bin_dir / missing).chmod(0o755)
    assert all(item["enabled"] for item in client.get("/api/launch/simulators").json()["simulators"])


@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
@pytest.mark.parametrize("selection", ["unknown", "", False, [], "vcs"])
def test_invalid_or_unavailable_selection_preserves_compiled_workspace(master, selection, transport):
    """Invalid options must fail before resetting an existing compiled package or starting work."""
    server, client, bin_dir = master
    ws = add_sources(server)
    (bin_dir / "vcs").unlink()
    dut_dir = Path(ws["picker_workspace"]) / "Adder"
    dut_dir.mkdir()
    marker = dut_dir / "keep.txt"
    marker.write_text("compiled package")
    response = client.post(f"/api/workspace/{ws['workspace_id']}/{transport}", json={
        "selected_module": "Adder", "simulator": selection,
    })
    assert response.status_code == 400
    assert "simulator" in response.text.lower()
    assert marker.read_text() == "compiled package"
    assert ws["workspace_id"] not in server._compile_runtime
    assert not (Path(ws["workspace_dir"]) / "picker-command.json").exists()


@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
@pytest.mark.parametrize("args", [
    ["--sim", "vcs"], ["--sim=vcs"], ["-w", "other.vcd"],
    ["--wave_file_name=other.vcd"], ["-wother.vcd"], ["--rw", "1"],
    ["--access-mode=dpi"],
])
def test_extra_arguments_cannot_override_simulator_contract(master, transport, args):
    """All compile APIs must reject arguments that invalidate the persisted simulator identity."""
    server, client, _ = master
    ws = server._create_workspace()
    response = client.post(f"/api/workspace/{ws['workspace_id']}/{transport}", json={
        "selected_module": "Adder", "simulator": "vcs", "picker_args": args,
    })
    assert response.status_code == 400
    assert "picker_args must not" in response.text
    assert not Path(ws["workspace_dir"]).exists()


def test_simulator_defaults_from_resolved_launch_config(master):
    """Omitting a selection must use the resolved launch default and an explicit request must override it."""
    server, client, _ = master
    server.cfg = Config({"launch": {"default_args": {"simulator": ["vcs", "verilator"]}}}).freeze()
    ws = add_sources(server)
    response = client.post(f"/api/workspace/{ws['workspace_id']}/compile", json={"selected_module": "Adder"})
    assert response.json()["compile"]["simulator"] == "vcs"
    assert client.get("/api/launch/config").json()["default_simulator"] == "vcs"
    response = client.post(f"/api/workspace/{ws['workspace_id']}/compile", json={
        "selected_module": "Adder", "simulator": "verilator",
    })
    assert response.json()["compile"]["simulator"] == "verilator"


def test_failed_compile_retains_simulator_and_logs(master, monkeypatch):
    """A compiler failure must retain the selected simulator and command for diagnosis."""
    server, client, _ = master
    monkeypatch.setenv("TEST_PICKER_EXIT", "2")
    ws = add_sources(server)
    response = client.post(f"/api/workspace/{ws['workspace_id']}/compile", json={
        "selected_module": "Adder", "simulator": "uvs",
    })
    data = response.json()
    assert data["status"] == "failed"
    assert data["compile"]["simulator"] == "uvs"
    assert data["compile"]["picker_exit_code"] == 2
    assert "picker compile log" in data["compile"]["picker_stdout"]


def test_package_resources_and_launch_yaml_simulator(master, tmp_path):
    """The package split must keep UI, static resources, CLI paths, and YAML imports usable."""
    server, client, _ = master
    assert 'id="picker-simulators"' in client.get("/launch/").text
    assert client.get("/static/share/ucagent-shell.js").status_code == 200
    ws = add_sources(server)
    prepared = {"workspace_dir": ws["workspace_dir"], "dut_name": "Adder"}
    command, _ = server._build_ucagent_command({"use_zip_workspace": False}, prepared, {"host": "127.0.0.1", "port": 8818, "password": ""})
    assert Path(command[1]).is_file()
    assert Path(command[1]).name == "cli.py"
    spec = server._normalize_launch_yaml_spec(str(tmp_path / "launch.yaml"), {
        "module": "Adder", "simulator": "uvs",
    })
    assert spec["fields"]["simulator"] == "uvs"
    assert spec["imports"] == []


def test_setting_yaml_simulator_default():
    """Parse the edited YAML using the application's environment-aware loader."""
    config = load_yaml_with_env_vars(str(Path(__file__).parents[1] / "ucagent" / "setting.yaml"))
    assert config["launch"]["default_args"]["simulator"] == ["verilator", "vcs", "gsim", "uvs"]


@pytest.mark.parametrize("simulator", [
    "vcs", "", False, [], None, ["unknown"], ["vcs", "vcs"], ["vcs", False], {"vcs": 1},
])
def test_invalid_configured_simulator_fails_at_startup(tmp_path, simulator):
    """An invalid launch default must fail before the Master creates runtime state."""
    cfg = Config({"launch": {"default_args": {"simulator": simulator}}}).freeze()
    workspace = tmp_path / "invalid-master"
    with pytest.raises(ValueError, match="launch.default_args.simulator.*nonempty ordered list"):
        PdbMasterApiServer(workspace=str(workspace), cfg=cfg)
    assert not workspace.exists()


@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
def test_compile_defaults_to_first_available_priority(master, transport):
    """API defaults must skip missing higher priorities and persist one resolved simulator."""
    server, client, bin_dir = master
    server.cfg = Config({"launch": {"default_args": {
        "simulator": ["uvs", "vcs", "verilator"],
    }}}).freeze()
    (bin_dir / "uvs").unlink()
    for endpoint in ("/api/launch/config", "/api/launch/simulators"):
        data = client.get(endpoint).json()
        assert [item["value"] for item in data["simulators"]] == ["uvs", "vcs", "verilator"]
        assert data["default_simulator"] == "vcs"
    ws = add_sources(server)
    base = f"/api/workspace/{ws['workspace_id']}"
    response = client.post(f"{base}/{transport}", json={"selected_module": "Adder"})
    assert response.status_code == 200
    if transport == "compile/stream":
        result = json.loads(response.text.splitlines()[-1])
    elif transport == "compile/start":
        deadline = time.monotonic() + 5
        while True:
            result = client.get(f"{base}/compile/status").json()["runtime"]
            if result["status"] != "running" or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        assert result["status"] == "success", result
    else:
        result = response.json()
    assert result["compile"]["simulator"] == "vcs"
    # Merge launch defaults into a single selection before queuing a task.
    request = server._normalized_launch_request({"workspace_id": ws["workspace_id"], "selected_module": "Adder"})
    assert request["simulator"] == "vcs"
    assert server._validated_launch_context(request)[3] == "success"
    (bin_dir / "vcs").unlink()
    assert client.get("/api/launch/simulators").json()["default_simulator"] == "verilator"
    assert request["simulator"] == "vcs"
    assert server._validated_launch_context(request)[3] == "success"


@pytest.mark.parametrize("missing", ["picker", "all-configured"])
@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
def test_no_available_priority_allows_master_but_blocks_compile(master, tmp_path, missing, transport):
    """A Master without available compilation tools must still serve detection and preserve files."""
    server, _, bin_dir = master
    if missing == "picker":
        (bin_dir / "picker").unlink()
    else:
        for simulator in ("verilator", "vcs"):
            (bin_dir / simulator).unlink()
    cfg = Config({"launch": {"file_browser_roots": [], "default_args": {
        "simulator": ["vcs", "verilator"],
    }}}).freeze()
    server = PdbMasterApiServer(workspace=str(tmp_path / "unavailable-master"), cfg=cfg)
    client = TestClient(server._app)
    for endpoint in ("/api/launch/config", "/api/launch/simulators"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.json()["default_simulator"] == ""
        assert all(not item["enabled"] for item in response.json()["simulators"])
    ws = server._create_workspace()
    response = client.post(f"/api/workspace/{ws['workspace_id']}/{transport}", json={"selected_module": "Adder"})
    assert response.status_code == 400
    assert "No configured Picker simulator is available" in response.text
    assert not Path(ws["workspace_dir"]).exists()
    assert ws["workspace_id"] not in server._compile_runtime


@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
def test_unconfigured_simulator_is_not_a_fallback(master, transport):
    """Tools outside the configured candidate list must not bypass its selection policy."""
    server, client, _ = master
    server.cfg = Config({"launch": {"default_args": {"simulator": ["vcs"]}}}).freeze()
    ws = server._create_workspace()
    response = client.post(f"/api/workspace/{ws['workspace_id']}/{transport}", json={
        "selected_module": "Adder", "simulator": "verilator",
    })
    assert response.status_code == 400
    assert "not in launch.default_args.simulator" in response.text
    assert not Path(ws["workspace_dir"]).exists()


@pytest.mark.parametrize("has_compile_record", [True, False])
def test_relaunch_needs_no_compiler_availability(master, has_compile_record):
    """An existing DUT package must relaunch even when no compiler is available on the Master."""
    server, client, bin_dir = master
    ws = add_sources(server)
    if has_compile_record:
        response = client.post(f"/api/workspace/{ws['workspace_id']}/compile", json={
            "selected_module": "Adder", "simulator": "uvs",
        })
        assert response.json()["status"] == "ok"
    info_dir = Path(ws["picker_workspace"]) / ".ucagent"
    info_dir.mkdir()
    (info_dir / "ucagent_info.json").write_text(json.dumps({"dut_name": "Adder", "selected_module": "Adder"}))
    (bin_dir / "picker").unlink()
    server.cfg = Config({
        "launch": {"file_browser_roots": [], "default_args": {
            "simulator": ["vcs", "verilator"],
        }},
        "master_api": {"max_task_count": 100},
    }).freeze()

    def launch(req, workspace, prepared, compile_info, picker_status):
        """Inspect the resolved relaunch after its real validation and skip only process startup."""
        assert picker_status == "success"
        if has_compile_record:
            assert req["simulator"] == "uvs"
        return {"task_id": workspace["task_id"], "process_status": "starting"}

    with patch.object(server, "_launch_validated_task", side_effect=launch):
        response = client.post("/api/relaunch", json={"workspace_id": ws["workspace_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("changed", [
    {"simulator": "vcs"}, {"dut_name": "Other"}, {"selected_module": "Other"},
    {"main_verilog_path": "/other.v"}, {"picker_args": ["--vflag", "-Wall"]},
])
def test_running_compile_only_reuses_identical_requests(master, changed):
    """A retry may reuse its running compile, but different settings must not attach to it."""
    server, client, _ = master
    ws = add_sources(server)
    endpoint = f"/api/workspace/{ws['workspace_id']}/compile/start"
    request = {"selected_module": "Adder", "simulator": "verilator"}
    started = threading.Event()
    release = threading.Event()

    def hold_compile(*args):
        """Keep the first job running while concurrent HTTP requests are validated."""
        started.set()
        release.wait(5)

    try:
        with patch.object(server, "_run_compile_job", side_effect=hold_compile) as worker:
            assert client.post(endpoint, json=request).status_code == 200
            assert started.wait(5)
            assert client.post(endpoint, json=request).status_code == 200
            response = client.post(endpoint, json={**request, **changed})
            assert response.status_code == 400
            assert "different settings" in response.text
            assert worker.call_count == 1
    finally:
        release.set()


@pytest.mark.parametrize("selection", ["", None, False, ["vcs"], {"name": "vcs"}, "unknown"])
def test_launch_yaml_rejects_invalid_simulator_field(master, tmp_path, selection):
    """An explicit malformed simulator must fail instead of silently choosing another tool."""
    server, _, _ = master
    with pytest.raises(ValueError, match="simulator"):
        server._normalize_launch_yaml_spec(str(tmp_path / "launch.yaml"), {
            "module": "Adder", "simulator": selection,
        })


@pytest.mark.parametrize("transport", ["compile", "compile/stream", "compile/start"])
def test_failed_recompile_cannot_reuse_deleted_package_metadata(master, transport):
    """Resetting a package must invalidate the previous successful compile even if preparation fails."""
    server, client, _ = master
    ws = add_sources(server)
    base = f"/api/workspace/{ws['workspace_id']}"
    request = {"selected_module": "Adder", "simulator": "verilator"}
    assert client.post(f"{base}/compile", json=request).json()["status"] == "ok"
    assert server._validated_launch_context({**request, "workspace_id": ws["workspace_id"]})[3] == "success"
    with patch.object(server, "_build_picker_command", side_effect=ValueError("Failed to prepare Picker command")):
        response = client.post(f"{base}/{transport}", json={**request, "simulator": "vcs"})
        if transport == "compile/stream":
            assert json.loads(response.text.splitlines()[-1])["status"] == "failed"
        elif transport == "compile/start":
            deadline = time.monotonic() + 5
            while True:
                runtime = client.get(f"{base}/compile/status").json()["runtime"]
                if runtime["status"] != "running" or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            assert runtime["status"] == "failed", runtime
        else:
            assert response.status_code == 400
    with pytest.raises(ValueError, match="Please compile first"):
        server._validated_launch_context({**request, "workspace_id": ws["workspace_id"]})
