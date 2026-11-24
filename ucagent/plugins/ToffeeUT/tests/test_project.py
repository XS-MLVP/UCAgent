"""Input discovery, safe paths and non-destructive project adoption contracts."""

import ast
import json
from pathlib import Path

import pytest

from toffee_ut.audit import audit_project
from toffee_ut.cli import main
from toffee_ut.layout import project_layout
from toffee_ut.paths import local_path, source_identity, write_json
from toffee_ut.project import inspect_inputs, package_root, scaffold
from toffee_ut.tools import UTProject
from ucagent.util.config import Config


@pytest.mark.parametrize("path", ["../outside", "/abs", "nested/../../outside", "", "a\\b", "\x00"])
def test_paths_reject_escape_and_invalid_input(tmp_path, path):
    """Never permit lexical paths that escape or have ambiguous separator semantics."""
    with pytest.raises(ValueError):
        local_path(tmp_path, path)


def test_symlink_paths_cannot_escape_workspace(tmp_path):
    """An otherwise relative path cannot bypass the workspace through a link."""
    (tmp_path / "link").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        scaffold(tmp_path, "Block", project="link/ut_project")
    with pytest.raises(ValueError):
        inspect_inputs(tmp_path, "Block", documents=["link/source.md"])


def test_inspection_routes_real_inputs_not_empty_skeleton(tmp_path):
    """Empty/generated specification files are not independent provided documentation."""
    assert inspect_inputs(tmp_path, "Block")["document_mode"] == "derive"
    scaffold(tmp_path, "Block")
    assert inspect_inputs(tmp_path, "Block")["document_mode"] == "derive"
    (tmp_path / "Block_Doc").mkdir()
    (tmp_path / "Block_Doc/interface.md").write_text("Independent contract\n")
    found = inspect_inputs(tmp_path, "Block")
    assert found["document_mode"] == "provided"
    assert "Block_Doc/interface.md" in found["documents"]
    assert inspect_inputs(tmp_path, "Block", mode="derive")["document_mode"] == "derive"


@pytest.mark.parametrize("kwargs", [{"documents": ["missing.md"]}, {"rtl_dirs": ["missing"]}, {"mode": "provided"}])
def test_explicit_missing_inputs_are_not_silently_ignored(tmp_path, kwargs):
    """Explicitly requested inputs must be usable before routing or writing files."""
    with pytest.raises((ValueError, FileNotFoundError)):
        inspect_inputs(tmp_path, "Block", **kwargs)


def test_scaffold_is_minimal_and_idempotent(tmp_path):
    """A new project has editable entrypoints and no unnecessary shared/responsibility shells."""
    result = scaffold(tmp_path, "Block")
    root = tmp_path / "ut_project"
    assert result["created"]
    assert not (root / "testbenches/shared").exists()
    assert not (root / "testbenches/block/model.py").exists()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert scaffold(tmp_path, "Block")["created"] == []
    assert all(path.read_bytes() == contents for path, contents in before.items())
    for path in root.rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    assert 'assert False, "Not implemented"' in (root / "testbenches/block/tests/test_contract.py").read_text()


def test_adoption_preserves_mapping_namespace_fixtures_and_tests(tmp_path):
    """A ucv4xs-style mapped DUT gets no guessed env.py or failing new placeholder."""
    root = tmp_path / "suites/group/suite"
    for part in (tmp_path / "suites", tmp_path / "suites/group", root):
        part.mkdir(parents=True, exist_ok=True)
        (part / "__init__.py").write_text('"""Existing project namespace."""\n')
    write_json(root / "workspace.json", {"schema": 2, "fixtures": "conftest.py", "duts": {"variant": {
        "testbench": "common", "environment": "testbenches/common/env/agent.py",
        "tests": ["testbenches/common/tests"], "design_spec": ["docs/spec/design/common.md"],
        "verification_spec": ["docs/spec/verification/common.md"]}}})
    write_json(root / "ucv.json", {"duts": {"variant": {"top": "ActualTop", "export_name": "VariantDut"}}})
    for name in ("conftest.py", "pytest.ini", "testbenches/common/env/agent.py", "testbenches/common/tests/test_real.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# existing content\n")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = scaffold(tmp_path, "variant", project="suites/group/suite")
    assert result["adopted"] and not result["created"]
    assert result["package"] == "suites.group.suite"
    assert package_root(root) == tmp_path
    assert all(path.read_bytes() == contents for path, contents in before.items())
    layout = project_layout(tmp_path, "variant", "suites/group/suite")
    assert layout["testbench"] == "common" and layout["export_name"] == "VariantDut"
    assert not (root / "testbenches/variant").exists()


def test_invalid_native_input_fails_before_any_scaffolding(tmp_path):
    """Invalid native-package options cannot leave a partially generated project."""
    with pytest.raises(ValueError, match="Picker"):
        scaffold(tmp_path, "Block", native_package="missing")
    assert not (tmp_path / "ut_project").exists()


def test_native_package_link_stays_in_workspace_and_is_hashed(tmp_path):
    """Local exported packages can be linked without losing their source fingerprints."""
    native = tmp_path / "Block"
    native.mkdir()
    (native / "__init__.py").write_text("# exported package input, not executed\n")
    scaffold(tmp_path, "Block")
    link = tmp_path / "ut_project/dut/Block"
    assert link.resolve() == native
    first = source_identity(tmp_path / "ut_project", tmp_path)
    (native / "__init__.py").write_text("# modified export input\n")
    assert source_identity(tmp_path / "ut_project", tmp_path) != first


@pytest.mark.parametrize("protected", ["ut_project/conftest.py", "ut_project/testbenches/*/env.py"])
def test_scaffold_checks_entire_write_footprint_before_writing(tmp_path, protected):
    """Protected leaf files block the complete creation operation, including wildcard rules."""
    cfg = Config({"write_dirs": ["ut_project"], "un_write_dirs": [protected], "runtime_options": {}})
    tool = UTProject(workspace=str(tmp_path), project="ut_project", dut="Block", cfg=cfg)
    result = tool._run("scaffold")
    assert not result["ok"], result
    assert not (tmp_path / "ut_project").exists()


def test_cli_inspection_writes_auditable_inventory(project, capsys):
    """The non-Skill CLI and UCAgent inspect action produce the same reusable input record."""
    assert main(["inspect", str(project), "Block", "--rtl-dir", "inputs/Block.sv"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rtl"]
    assert audit_project(project, "Block", phase="inputs")["ok"]
    (project / "inputs/Block.sv").write_text("// input changed\n")
    assert not audit_project(project, "Block", phase="inputs")["ok"]
