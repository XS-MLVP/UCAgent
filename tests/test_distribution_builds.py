"""Build isolated source copies to validate wheel contents and standalone plugin sdists."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    any(importlib.util.find_spec(name) is None for name in ("build", "setuptools", "setuptools_scm", "wheel")),
    reason="Distribution checks require build, setuptools, setuptools-scm and wheel",
)


def build_artifact(project, kind):
    """Build without dependency downloads or touching the live checkout."""
    result = subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--" + kind],
                            cwd=project, env={**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": "26.11.25"},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-12000:]
    return next((project / "dist").glob("*.whl" if kind == "wheel" else "*.tar.gz"))


def test_framework_wheel_and_sdist_load_default_workflow_without_source_checkout(tmp_path):
    """Both build routes contain ToffeeUT code and assets, not independent plugins or tests."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "MANIFEST.in", "LICENSE", "NOTICE.md", "README.en.md"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / "ucagent", source / "ucagent",
                    ignore=shutil.ignore_patterns("__pycache__", ".venv", "build", "*.egg-info"))
    direct = build_artifact(source, "wheel")
    sdist = build_artifact(source, "sdist")
    unpacked = tmp_path / "sdist"
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    rebuilt = build_artifact(next(unpacked.iterdir()), "wheel")
    for index, wheel in enumerate((direct, rebuilt)):
        installed = tmp_path / f"installed-{index}"
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            assert "ucagent/plugins/ToffeeUT/src/toffee_ut/plugin.py" in names
            assert "ucagent/plugins/UnitTest/src/unit_test/plugin.py" in names
            assert not any(name.startswith("ucagent/plugins/" + plugin + "/") for name in names
                           for plugin in ("Formal", "DesignWithPPA", "RTL2Spec", "ACT4"))
            assert not any(name.startswith(f"ucagent/plugins/{plugin}/tests/") for name in names
                           for plugin in ("ToffeeUT", "UnitTest"))
            assert not any("/__pycache__/" in name for name in names)
            archive.extractall(installed)
        script = """
from pathlib import Path
import ucagent
from ucagent.core.plugins import load_plugin
from ucagent.util.config import load_yaml_with_env_vars, resolve_workflow_pointer_path
root = Path(ucagent.__file__).resolve().parent
assert root == Path.cwd() / 'ucagent'
selector = load_yaml_with_env_vars(str(root / 'core/locales/zh.yaml'))['workflow']
workflow = Path(resolve_workflow_pointer_path(selector, 'zh'))
assert workflow.is_file() and workflow.is_relative_to(root)
plugin = load_plugin(str(root / 'plugins/ToffeeUT'), check_dependencies=False)
assert plugin.plugin.name == 'toffee-ut'
assert load_plugin('toffee-ut', check_dependencies=False).plugin.root == plugin.plugin.root
assert any(entry.config_file.resolve() == workflow for entry in plugin.plugin.workflows)
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=installed,
                                env={**os.environ, "PYTHONPATH": str(installed)}, capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["RTL2Spec", "DesignWithPPA", "ACT4"])
def test_standalone_plugin_builds_from_checkout_and_complete_sdist(tmp_path, name):
    """License roots survive both source-checkout and published-sdist build layouts."""
    repository = tmp_path / "repository"
    project = repository / "ucagent/plugins" / name
    shutil.copytree(ROOT / "ucagent/plugins" / name, project,
                    ignore=shutil.ignore_patterns("__pycache__", ".venv", "build", "*.egg-info"))
    (repository / "ucagent/__init__.py").touch()
    for policy in ("LICENSE", "NOTICE.md"):
        shutil.copy2(ROOT / policy, repository / policy)
    build_artifact(project, "wheel")
    sdist = build_artifact(project, "sdist")
    assert not (project / "LICENSE").exists() and not (project / "NOTICE.md").exists()
    unpacked = tmp_path / "standalone"
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    standalone = next(unpacked.iterdir())
    build_artifact(standalone, "wheel")
    for policy in ("LICENSE", "NOTICE.md"):
        assert (standalone / policy).read_bytes() == (ROOT / policy).read_bytes()
