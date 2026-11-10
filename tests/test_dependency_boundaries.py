"""Enforce dependency direction across Agent, application and shared filesystem layers."""

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def internal_imports(path):
    """Resolve explicit absolute and relative imports, including imports inside functions."""
    module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    package = module.removesuffix(".__init__") if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            target = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            yield target, node.lineno
            for alias in node.names:
                imported = target + "." + alias.name
                if imported == "ucagent.VerifyAgent":
                    imported = "ucagent.core.agent.execution"
                yield imported, node.lineno


@pytest.mark.parametrize("folder, forbidden", [
    ("core", ("application", "runtime", "interfaces")),
    ("runtime", ("application", "interfaces")),
    ("interfaces", ("application",)),
    ("util", ("application", "runtime", "interfaces", "core", "plugins")),
])
def test_lower_layers_do_not_import_upper_layers(folder, forbidden):
    """Late imports are subject to the same architectural boundary as module imports."""
    prefixes = tuple("ucagent." + name for name in forbidden)
    failures = []
    for path in (ROOT / "ucagent" / folder).rglob("*.py"):
        for target, line in internal_imports(path):
            if any(target == prefix or target.startswith(prefix + ".") for prefix in prefixes):
                failures.append(f"{path.relative_to(ROOT)}:{line}: {target}")
    assert not failures, "\n".join(failures)


def test_direct_agent_construction_does_not_load_application(tmp_path):
    """The public constructor works with application modules unavailable to imports."""
    source = r'''import importlib.abc
from pathlib import Path
import sys

class ApplicationBlocked(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ucagent.application" or fullname.startswith("ucagent.application."):
            raise AssertionError("Agent construction imported application: " + fullname)

sys.meta_path.insert(0, ApplicationBlocked())
from ucagent import VerifyAgent
workspace = Path(sys.argv[1])
agent = VerifyAgent(str(workspace), "DUT", None, config_file="master.yaml",
    cfg_override=[{"backend.key_name": "blank"}, {"langfuse.enable": False}, {"skill.use_skill": False}],
    no_embed_tools=True, no_history=True)
assert not any(name.startswith("ucagent.application") for name in sys.modules)
agent._startup_cleanup.close()
'''
    result = subprocess.run([sys.executable, "-c", source, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]


def test_shared_file_policy_imports_only_standard_library():
    """File-policy decisions remain usable without tools, configuration or runtime imports."""
    path = ROOT / "ucagent/util/file_policy.py"
    for target, line in internal_imports(path):
        assert target.split(".", 1)[0] in sys.stdlib_module_names, (line, target)


def test_filesystem_utilities_work_with_tool_and_server_imports_blocked(tmp_path):
    """Permission decisions and chmod do not trigger tool schemas or server transports."""
    source = r'''import importlib.abc
from pathlib import Path
import sys

class UpperLayersBlocked(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".")
               for prefix in ("ucagent.core.tools", "ucagent.interfaces.server", "ucagent.application", "ucagent.core.agent")):
            raise AssertionError("Utility imported upper layer: " + fullname)

sys.meta_path.insert(0, UpperLayersBlocked())
from ucagent.util.functions import chmode_ro_by_pattern
from ucagent.util.file_policy import is_file_writeable
import ucagent.util.waveform_viewer
workspace = Path(sys.argv[1])
protected = workspace / "dut"
protected.mkdir()
(protected / "top.v").write_text("module top; endmodule")
(protected / "notes.md").write_text("notes")
chmode_ro_by_pattern(str(workspace), ["dut"], write_dirs=["dut/*.md"])
assert not (protected / "top.v").stat().st_mode & 0o200
assert (protected / "notes.md").stat().st_mode & 0o200
assert not is_file_writeable("dut/top.v", ["dut"], ["dut/*.md"])[0]
wave = protected / "signal.vcd"
wave.write_text("waveform fixture")
payload = {"schema_version": 1, "waveform_file": wave.name, "signals": [],
           "source_files": [], "dut_python_path": None}
try:
    ucagent.util.waveform_viewer.write_waveform_metadata(
        workspace, "dut/signal.vcd.json", payload, un_write_dirs=["dut"])
except PermissionError:
    pass
else:
    raise AssertionError("Waveform metadata bypassed file policy")
assert not (protected / "signal.vcd.json").exists()
'''
    result = subprocess.run([sys.executable, "-c", source, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]


def test_internal_modules_do_not_import_launch_entrypoints():
    """Path discovery and reusable modules cannot load application through an entrypoint."""
    failures = []
    for folder in ("core", "runtime", "interfaces", "util", "application"):
        for path in (ROOT / "ucagent" / folder).rglob("*.py"):
            for target, line in internal_imports(path):
                if target in {"ucagent.__main__", "ucagent.application.entry"} or target.startswith(("ucagent.__main__.", "ucagent.application.entry.")):
                    failures.append(f"{path.relative_to(ROOT)}:{line}: {target}")
    assert not failures, "\n".join(failures)


def test_workspace_services_do_not_import_http():
    """File/history policy and saved queries remain independent of the HTTP framework."""
    paths = [ROOT / "ucagent/core/workspace/files.py", ROOT / "ucagent/core/stage/history.py",
             *(ROOT / "ucagent/runtime/workspace").glob("*.py")]
    for path in paths:
        for target, line in internal_imports(path):
            assert not target.startswith(("fastapi", "starlette", "ucagent.interfaces")), (path, line, target)


def test_master_default_root_does_not_load_launch_entrypoints():
    """Resolve source and installed package locations with startup imports blocked."""
    source = r'''import importlib.abc
import os
import sys
import ucagent

class EntryBlocked(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ucagent.__main__" or fullname.startswith("ucagent.application"):
            raise AssertionError("Path discovery loaded startup: " + fullname)

sys.meta_path.insert(0, EntryBlocked())
from ucagent.interfaces.server.api_master.common import _default_launch_root
original = ucagent.__file__
assert _default_launch_root() == os.path.abspath(os.path.join(os.path.dirname(original), "..", "examples"))
ucagent.__file__ = "/installed/site-packages/ucagent/__init__.py"
assert _default_launch_root() == "/installed/site-packages/examples"
assert "ucagent.__main__" not in sys.modules
assert not any(name.startswith("ucagent.application") for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", source], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr)[-6000:]
