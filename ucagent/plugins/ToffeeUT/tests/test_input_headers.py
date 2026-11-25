"""Inventory freshness for HDL headers, using text fixtures and no DUT execution."""

import pytest

from toffee_ut.paths import digest, source_identity, write_json
from toffee_ut.project import inspect_inputs


@pytest.mark.parametrize("suffix", [".vh", ".svh"])
@pytest.mark.parametrize("explicit_file", [False, True])
def test_hdl_header_is_part_of_the_declared_input_identity(tmp_path, suffix, explicit_file):
    """Both directory discovery and an explicit header must fingerprint actual bytes."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    header = inputs / ("definitions" + suffix)
    header.write_text("// Inventory-only header fixture; never compiled.\n")
    relative = header.relative_to(tmp_path).as_posix()
    inventory = inspect_inputs(tmp_path, "Block", documents=[],
                               rtl_dirs=[relative if explicit_file else "inputs"], mode="derive")
    assert inventory["rtl"] == {relative: digest(header)}


@pytest.mark.parametrize("suffix", [".vh", ".svh"])
def test_changed_header_invalidates_the_project_source_identity(tmp_path, suffix):
    """A receipt cannot remain current after a declared included header changes."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    header = inputs / ("definitions" + suffix)
    header.write_text("// Header revision one; no simulator is involved.\n")
    root = tmp_path / "ut_project"
    write_json(root / "results/input_inventory.json", inspect_inputs(
        tmp_path, "Block", documents=[], rtl_dirs=["inputs"], mode="derive"))
    before = source_identity(root, tmp_path)
    header.write_text("// Header revision two; must invalidate input identity.\n")
    after = source_identity(root, tmp_path)
    key = "workspace:" + header.relative_to(tmp_path).as_posix()
    assert key in before and key in after
    assert before[key] != after[key]


def test_header_symlink_cannot_escape_the_workspace(tmp_path):
    """Recognizing an HDL header does not weaken the workspace input boundary."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.svh"
    outside.write_text("// External inventory fixture; never compiled.\n")
    (workspace / "inside.svh").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        inspect_inputs(workspace, "Block", documents=[], rtl_dirs=["inside.svh"], mode="derive")
