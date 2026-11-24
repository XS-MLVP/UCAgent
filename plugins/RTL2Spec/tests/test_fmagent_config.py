"""Test checkout-local path selection and TOML-preserving binding without installations."""

import json
from pathlib import Path
import sys

import pytest
import tomllib

from rtl2spec import fmagent_config
from rtl2spec.fmagent_config import bind_paths, plugin_source_root, resolve_paths


@pytest.fixture
def local_plugin(tmp_path, monkeypatch):
    """Isolate all local configuration writes from the actual plugin source checkout."""
    monkeypatch.setattr(fmagent_config, "plugin_source_root", lambda: tmp_path)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_ROOT", raising=False)
    monkeypatch.delenv("RTL2SPEC_FMAGENT_PYTHON", raising=False)
    return tmp_path


@pytest.mark.parametrize("root_layer", range(4))
@pytest.mark.parametrize("python_layer", range(4))
def test_root_python_layer_pairing(local_plugin, monkeypatch, root_layer, python_layer):
    """All 16 layer combinations forbid a lower-priority interpreter crossing roots."""
    roots = [str(local_plugin / f"root-{index}") for index in range(3)]
    pythons = [str(local_plugin / f"python-{index}") for index in range(3)]
    local = {}
    if root_layer == 2:
        local["root"] = roots[2]
    if python_layer == 2:
        local["python"] = pythons[2]
    (local_plugin / "rtl2spec.local.toml").write_text("[fmagent]\n" + "".join(f'{key} = "{value}"\n' for key, value in local.items()))
    if root_layer == 1:
        monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", roots[1])
    if python_layer == 1:
        monkeypatch.setenv("RTL2SPEC_FMAGENT_PYTHON", pythons[1])
    paths = resolve_paths(roots[0] if root_layer == 0 else None, pythons[0] if python_layer == 0 else None)
    expected_root = Path(roots[root_layer]) if root_layer < 3 else local_plugin / "third_party/FM-Agent"
    expected_python = Path(pythons[python_layer]) if python_layer < 3 and python_layer <= root_layer else expected_root / ".venv/bin/python"
    assert paths.root == expected_root
    assert paths.python == expected_python
    assert paths.root_source == ["argument", "environment", "local TOML", "default"][root_layer]
    assert paths.python_source == (["argument", "environment", "local TOML"][python_layer] if python_layer < 3 and python_layer <= root_layer else "root default")


def test_explicit_beats_all_lower_values(local_plugin, monkeypatch):
    """Populated lower layers never leak into complete explicit path choices."""
    (local_plugin / "rtl2spec.local.toml").write_text('[fmagent]\nroot="/toml"\npython="/toml/python"\n')
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", "/environment")
    monkeypatch.setenv("RTL2SPEC_FMAGENT_PYTHON", "/environment/python")
    paths = resolve_paths("/argument", "/argument/python")
    assert (str(paths.root), str(paths.python)) == ("/argument", "/argument/python")


def test_empty_home_relative_and_venv_symlink(local_plugin, monkeypatch):
    """Empty strings fall through; normalization retains a venv interpreter symlink."""
    monkeypatch.setenv("HOME", str(local_plugin))
    monkeypatch.setenv("RTL2SPEC_FMAGENT_ROOT", "~/source/../source")
    monkeypatch.setenv("RTL2SPEC_FMAGENT_PYTHON", "  ")
    monkeypatch.chdir(local_plugin)
    interpreter = local_plugin / "python"
    interpreter.symlink_to(sys.executable)
    paths = resolve_paths("", "nested/../python")
    assert paths.root == local_plugin / "source"
    assert paths.python == interpreter
    assert resolve_paths(" ").python == local_plugin / "source/.venv/bin/python"


@pytest.mark.parametrize("text", ['[fmagent', '[fmagent]\nroot=123', 'fmagent="wrong"', '[fmagent]\npython=false'])
def test_invalid_local_config_needs_complete_explicit_override(local_plugin, text):
    """Partial choices do not suppress malformed configuration; full paths can bypass it."""
    config = local_plugin / "rtl2spec.local.toml"
    config.write_text(text)
    with pytest.raises(ValueError, match="Invalid local configuration"):
        resolve_paths("/source")
    assert resolve_paths("/source", "/source/python").python == Path("/source/python")
    if text in ('[fmagent', 'fmagent="wrong"'):
        with pytest.raises(ValueError, match="repair"):
            bind_paths(resolve_paths("/source", "/source/python"))
        assert config.read_text() == text
    else:
        bind_paths(resolve_paths("/source", "/source/python"))
        assert tomllib.loads(config.read_text())["fmagent"] == {"root": "/source", "python": "/source/python"}


@pytest.mark.parametrize("text", ["", '# retain comment\n[other]\nvalue=7 # retain value\n', '# start\n[fmagent] # table\nroot = "/old" # root note\npython = "/old/python" # python note\nextra = "stay"\n[other]\nvalues=[1, 2]\n'])
def test_bind_preserves_unknown_content_and_comments(local_plugin, text):
    """Only path values change, including for empty and unrelated-only documents."""
    config = local_plugin / "rtl2spec.local.toml"
    config.write_text(text)
    paths = resolve_paths(str(local_plugin / 'source "quoted"'), str(local_plugin / "venv/bin/python"))
    bind_paths(paths)
    result = config.read_text()
    data = tomllib.loads(result)
    assert data["fmagent"]["root"] == str(paths.root)
    assert data["fmagent"]["python"] == str(paths.python)
    for fragment in ("# retain comment", "value=7 # retain value", "# start", "# table", "# root note", "# python note", 'extra = "stay"', 'values=[1, 2]'):
        if fragment in text:
            assert fragment in result


def test_bind_missing_dependency_is_actionable(local_plugin, monkeypatch):
    """A partial plugin install fails before changing the local TOML."""
    monkeypatch.setitem(sys.modules, "tomlkit", None)
    with pytest.raises(ValueError, match="declared tomlkit dependency"):
        bind_paths(resolve_paths())
    assert not (local_plugin / "rtl2spec.local.toml").exists()


@pytest.mark.parametrize("editable", [True, False])
def test_installed_package_uses_retained_direct_url_not_cwd(tmp_path, monkeypatch, editable):
    """Local ordinary/editable metadata resolves the retained source, even with spaces."""
    source = tmp_path / "retained source"
    module = source / "src/rtl2spec/fmagent_config.py"
    module.parent.mkdir(parents=True)
    module.write_text("fixture")
    monkeypatch.setattr(fmagent_config, "__file__", str(tmp_path / "site-packages/rtl2spec/fmagent_config.py"))

    class Distribution:
        """Expose only the standard installer provenance used by management."""

        def read_text(self, name):
            """Return local directory provenance independently of the working directory."""
            assert name == "direct_url.json"
            return json.dumps({"url": source.as_uri(), "dir_info": {"editable": editable}})

    monkeypatch.setattr(fmagent_config.metadata, "distribution", lambda name: Distribution())
    monkeypatch.chdir(tmp_path)
    assert plugin_source_root() == source


@pytest.mark.parametrize("provenance", [None, "{}", "not json", '{"url":"https://example.invalid/plugin","dir_info":{}}', '{"url":"file:///missing","dir_info":{}}'])
def test_missing_retained_source_reports_wheel_limit(tmp_path, monkeypatch, provenance):
    """Do not search cwd, HOME, or another checkout when installer provenance is absent."""
    monkeypatch.setattr(fmagent_config, "__file__", str(tmp_path / "site-packages/rtl2spec/fmagent_config.py"))

    class Distribution:
        """Supply invalid or absent source metadata."""

        def read_text(self, name):
            """Return the current invalid metadata fixture."""
            return provenance

    monkeypatch.setattr(fmagent_config.metadata, "distribution", lambda name: Distribution())
    with pytest.raises(ValueError, match="retained RTL2Spec local source"):
        plugin_source_root()


def test_source_root_and_ignore_are_checkout_specific():
    """Management belongs to the current source tree and local TOML has an exact ignore."""
    source = Path(__file__).resolve().parents[1]
    assert plugin_source_root() == source
    assert "/rtl2spec.local.toml" in (source / ".gitignore").read_text().splitlines()
