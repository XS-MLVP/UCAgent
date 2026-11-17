"""Bundled technology selection, asset integrity, and mapped register counts."""

from __future__ import annotations

import helpers  # noqa: F401

from pathlib import Path
import hashlib
import json
import re
import tomllib

import pytest

from helpers import PLUGIN_SOURCE
from design_with_ppa.plugin import get_plugin
from design_with_ppa.ppa import AnalyzePPA, PPAConfig, resolve_ppa_config
from design_with_ppa.ppa.backends.yosys_opensta import YosysOpenSTABackend
from design_with_ppa.ppa.config import PDKConfig, resolve_pdk
from ucagent.util.config import Config, load_yaml_with_env_vars


ASAP7_FILE = "asap7sc7p5t_28_RVT_TT_nldm_merged.lib"
ASAP7_HASH = "5d5d792741a15885a918cb1634de8124f0256e3f6d5b1f5a4d3c8a358e8597a0"
ASSETS = PLUGIN_SOURCE / "design_with_ppa" / "assets"


@pytest.mark.parametrize("workflow", ["unit-design-tdd", "repo-module-tdd"])
def test_workflow_and_direct_defaults_resolve_same_asap7(tmp_path, workflow):
    """Every entry point resolves the installed default without workspace files."""

    raw = load_yaml_with_env_vars(
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / f"{workflow}.yaml"
    )
    selected = resolve_ppa_config(Config(raw))
    assert selected == PPAConfig()
    tool = AnalyzePPA(workspace=str(tmp_path), analysis_config=selected)
    pdk = resolve_pdk(selected.pdk, tool._resolve_input)
    identity = AnalyzePPA(workspace=str(tmp_path)).analysis_identity()["pdk"]
    assert pdk.provenance == identity
    assert pdk.files["liberty"] == (ASSETS / ASAP7_FILE,)
    assert identity["files"]["liberty"] == [{"path": f"bundled:{ASAP7_FILE}", "sha256": ASAP7_HASH}]
    assert identity["name"] == "asap7sc7p5t_28"
    assert identity["corner"] == "RVT_TT_0p7V_25C"
    assert identity["tie_high"] == {"cell": "TIEHIx1_ASAP7_75t_R", "port": "H"}
    assert identity["tie_low"] == {"cell": "TIELOx1_ASAP7_75t_R", "port": "L"}
    assert not list(tmp_path.glob("*.lib"))


def test_asap7_asset_and_provenance_are_complete():
    """The exact merged input, all 202 unique cells, and licensing are shipped."""

    data = (ASSETS / ASAP7_FILE).read_bytes()
    manifest = json.loads((ASSETS / ASAP7_FILE.replace(".lib", ".manifest.json")).read_text())
    assert hashlib.sha256(data).hexdigest() == manifest["sha256"] == ASAP7_HASH
    assert len(data) == manifest["bytes"] == 46154226
    cells = re.findall(rb"\bcell\s*\(\s*([^\s)]+)\s*\)\s*\{", data)
    assert len(cells) == len(set(cells)) == manifest["cells"] == 202
    assert sum(row["cells"] for row in manifest["sources"]) == 202
    assert sum(row["explicit_pin_max_transition_added"] for row in manifest["sources"]) == 58
    assert len(manifest["sources"]) == 5
    assert b"Copyright" in data[:4000] and b"Redistribution and use" in data[:4000]
    assert "BSD 3-Clause License" in (ASSETS / "LICENSE-ASAP7.txt").read_text()
    declared = {path.name for path in get_plugin().assets}
    assert {ASAP7_FILE, ASAP7_FILE.replace(".lib", ".manifest.json"), "LICENSE-ASAP7.txt", "SOURCE.md"} <= declared
    project = tomllib.loads((PLUGIN_SOURCE.parent / "pyproject.toml").read_text())
    patterns = project["tool"]["setuptools"]["package-data"]["design_with_ppa"]
    assert {"assets/*.lib", "assets/*.json", "assets/*.txt", "assets/*.md"} <= set(patterns)


def test_nangate45_remains_an_explicit_preset(tmp_path):
    """Choosing Nangate45 supplies its own file and constant cells."""

    tool = AnalyzePPA(workspace=str(tmp_path))
    pdk = resolve_pdk(PDKConfig(name="nangate45", corner="typical"), tool._resolve_input)
    assert pdk.files["liberty"] == (ASSETS / "NangateOpenCellLibrary_typical.lib",)
    assert pdk.config.tie_high.model_dump() == {"cell": "LOGIC1_X1", "port": "Z"}
    assert pdk.config.tie_low.model_dump() == {"cell": "LOGIC0_X1", "port": "Z"}


@pytest.mark.parametrize("name", ["asap7sc7p5t_28", "nangate45"])
def test_bundled_corner_requires_matching_asset(tmp_path, name):
    """A corner label cannot silently relabel a bundled characterization."""

    tool = AnalyzePPA(workspace=str(tmp_path))
    with pytest.raises(ValueError, match="supports only corner="):
        resolve_pdk(PDKConfig(name=name, corner="other"), tool._resolve_input)


def test_missing_default_asset_fails_without_switching_technology(tmp_path, monkeypatch):
    """An incomplete installation diagnoses the missing ASAP7 file explicitly."""

    original = Path.is_file

    def is_file(path):
        """Simulate a missing bundled file without modifying package resources."""

        return False if path == ASSETS / ASAP7_FILE else original(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    with pytest.raises(FileNotFoundError, match="bundled asap7sc7p5t_28 Liberty asset is missing"):
        resolve_pdk(PDKConfig(), AnalyzePPA(workspace=str(tmp_path))._resolve_input)


@pytest.mark.parametrize("tool_override", [False, True])
def test_explicit_liberty_replaces_bundled_corner(tmp_path, tool_override):
    """Both configured files and a tool argument select the supplied library."""

    library = tmp_path / "cells.lib"
    library.write_text("library(custom) {}\n")
    tool = AnalyzePPA(workspace=str(tmp_path))
    config = PDKConfig(corner="other", files={} if tool_override else {"liberty": ["cells.lib"]},
                       tie_high={"cell": "ONE", "port": "Y"})
    pdk = resolve_pdk(config, tool._resolve_input, "cells.lib" if tool_override else None)
    assert pdk.files["liberty"] == (library,)
    assert pdk.provenance["files"]["liberty"][0]["path"] == "cells.lib"
    assert pdk.config.tie_high.cell == "ONE"
    assert pdk.config.corner == "other"


@pytest.mark.parametrize("count", [None, 0, 2, 3])
def test_mapped_count_uses_register_evidence(count):
    """Technology naming cannot override OpenSTA's register instance count."""

    stats = {"modules": {"dut": {"num_cells": 3, "num_cells_by_type": {"STATE_X1": 2, "DFF_LABEL_ONLY": 1},
                                 "area": 5.0, "sequential_area": 3.0}}}
    summary = YosysOpenSTABackend._area_summary(stats, "dut", count)
    assert summary["sequential_cell_count"] == count
    assert summary["combinational_cell_count"] == (3 - count if count is not None else None)
    assert summary["total"] == 5.0


@pytest.mark.parametrize("count", [-1, 4])
def test_inconsistent_register_count_is_rejected(count):
    """Conflicting tool evidence cannot yield a negative combinational count."""

    with pytest.raises(ValueError, match="outside the mapped cell-count range"):
        YosysOpenSTABackend._area_summary({"modules": {"dut": {"num_cells": 3}}}, "dut", count)
