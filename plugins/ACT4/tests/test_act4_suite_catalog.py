"""Regressions for the shared Test Suite target list and pre-resource startup gate."""

import csv
import hashlib
import json
from pathlib import Path
import re
import runpy
import tomllib

import pytest

from ucagent.plugins import PluginError, load_plugin
from ucagent.util.config import Config
from ucagent.verify_agent import VerifyAgent
from ucagent_act4.run_config import resolve_run_config
from ucagent_act4.plugin import get_plugin
from ucagent_act4.suite_catalog import CATALOG_ROOT, load_suite_catalog, validate_suite_target


PROJECT = Path(__file__).resolve().parents[1]
WORKFLOWS = ["privileged-suite-generation", "unprivileged-suite-generation"]


def write_catalog(root: Path, rows: list, metadata: dict) -> None:
    """Write a temporary catalog with an updated digest for parser boundary tests."""
    with (root / "test_suites.csv").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)
    metadata["sha256"] = hashlib.sha256((root / "test_suites.csv").read_bytes()).hexdigest()
    (root / "test_suites.json").write_text(json.dumps(metadata), encoding="utf-8")


@pytest.fixture
def snapshot() -> tuple[list, dict]:
    """Read an independent mutable copy of the bundled source records."""
    with (CATALOG_ROOT / "test_suites.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    return rows, json.loads((CATALOG_ROOT / "test_suites.json").read_text(encoding="utf-8"))


def test_snapshot_preserves_all_sheet_rows_and_distinct_names(snapshot) -> None:
    """Deduplicate only exact names, never case variants or source provenance."""
    catalog = load_suite_catalog()
    rows, _ = snapshot
    expected = {number: row[1].strip() for number, row in enumerate(rows[3:], 4) if row[1].strip()}
    observed = {row["row"]: entry["test_suite"] for entry in catalog["targets"].values() for row in entry["rows"]}
    observed.update({number: name for name, entry in catalog["excluded"].items() for number in entry["rows"]})
    assert observed == expected
    assert catalog["record_count"] == 291
    assert len(catalog["targets"]) == 267
    assert catalog["targets"]["Sstc"]["rows"][0]["row"] == 42
    assert catalog["targets"]["sstc"]["rows"][0]["row"] == 283
    assert [row["row"] for row in catalog["targets"]["H"]["rows"]] == [127, 156]
    assert all(re.fullmatch(r"[A-Za-z0-9_]+", target) for target in catalog["targets"])


def test_every_catalog_target_resolves_without_asset_checks(monkeypatch, capsys) -> None:
    """Admit every named scope even when its plan, model, or generated assets are missing."""
    def reject_network(*args, **kwargs):
        """Fail if startup tries to fetch external resources."""
        raise AssertionError("Catalog lookup must work offline")

    monkeypatch.setattr("socket.create_connection", reject_network)
    catalog = load_suite_catalog()
    for target, entry in catalog["targets"].items():
        scope = json.loads(validate_suite_target(target)["ACT4_SUITE_SCOPE"])
        assert scope["test_suite"] == entry["test_suite"]
        assert scope["target"] == target
        assert all(set(row) == {"row", "group", "description"} for row in scope["rows"])
    capsys.readouterr()


@pytest.mark.parametrize("target", [None, "", " Sstc", "Sstc ", "SSTC", "ExampleSuite", "Smnpm", "../Sstc", "I;echo", [], 3])
def test_unknown_target_fails_without_normalization(target) -> None:
    """Reject misspellings, unlisted native aliases, unsafe paths, and malformed input."""
    with pytest.raises(PluginError, match="exact, case-sensitive CLI target"):
        validate_suite_target(target)


def test_complex_name_requires_documented_cli_target(capsys) -> None:
    """Keep the original composite request rather than silently selecting one extension."""
    with pytest.raises(PluginError, match="Candidate CLI targets: Sspm_Smnpm"):
        validate_suite_target("Sspm (Smnpm*)")
    scope = json.loads(validate_suite_target("Sspm_Smnpm")["ACT4_SUITE_SCOPE"])
    assert scope["test_suite"] == "Sspm (Smnpm*)"
    assert "Supervisor Pointer Masking" in capsys.readouterr().out


def test_headings_are_rejected_with_specific_reason() -> None:
    """Do not turn supplier labels or unspecified reminders into executable suites."""
    for target in load_suite_catalog()["excluded"]:
        with pytest.raises(PluginError, match="not an executable suite"):
            validate_suite_target(target)
    with pytest.raises(PluginError, match="Section heading"):
        validate_suite_target("Alibaba_Hypervisor_Suites")


def test_terminal_summary_is_provenanced_not_validation(capsys) -> None:
    """Show basic metadata and historical status without leaking progress into ISA planning."""
    context = validate_suite_target("Sstc")
    output = capsys.readouterr().out
    for text in ("ACT4 Test Suite: Sstc", "Supervisor Timer Interrupts", "Sheet row 42", "owner:",
                 "Norm Rules/YAML=", "CTP/Written=", "Tests/Written=", "2026-11-19", "not evidence"):
        assert text in output
    assert "status" not in context["ACT4_SUITE_SCOPE"]
    assert "owner" not in context["ACT4_SUITE_SCOPE"]
    validate_suite_target("H")
    output = capsys.readouterr().out
    assert "Sheet row 127" in output and "Sheet row 156" in output


@pytest.mark.parametrize("workflow_name", WORKFLOWS)
def test_all_three_workflow_hooks_validate_before_path_processing(tmp_path, workflow_name) -> None:
    """Reject bad targets before any filesystem or resource setup, including local review."""
    workflow = next(item for item in get_plugin().workflows if item.name == workflow_name)
    with pytest.raises(PluginError, match="Invalid ACT4 Test Suite"):
        workflow.template_context_factory(None, {"DUT": "UnknownSuite"})
    settings = resolve_run_config({"schema_version": 1, "suite": "IOMMU", "workflow": workflow_name,
        "workspace": str(tmp_path), "output": "results"}, tmp_path.parent)
    project = "act4_priv_suite_generate" if workflow_name == "privileged-suite-generation" else "act4_unprivileged_generate"
    config = Config({"act4_run": settings, "template_overwrite": {"PROJECT": project}})
    context = workflow.template_context_factory(config, {"WORKSPACE": str(tmp_path), "OUT": "results", "DUT": "IOMMU"})
    assert json.loads(context["ACT4_SUITE_SCOPE"])["test_suite"] == "IOMMU"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("workflow_name", WORKFLOWS)
@pytest.mark.parametrize("skill_enabled", [False, True])
def test_invalid_target_stops_real_initialization(tmp_path, monkeypatch, workflow_name, skill_enabled) -> None:
    """Stop before runtime snapshots, guides, models, or stage initialization in either skill mode."""
    monkeypatch.setenv("HOME", str(tmp_path))
    loaded = load_plugin(str(PROJECT))
    workflow = next(item for item in loaded.plugin.workflows if item.name == workflow_name)

    def reject_runtime_setup(*args, **kwargs):
        """Make later initialization an explicit test failure."""
        raise AssertionError("Invalid targets must fail before runtime setup")

    monkeypatch.setattr("ucagent.verify_agent.save_runtime_config", reject_runtime_setup)
    with pytest.raises(PluginError, match="Invalid ACT4 Test Suite"):
        VerifyAgent(
            workspace=str(tmp_path), dut_name="UnknownSuite", output="results",
            workflow_config_file=str(workflow.config_file), plugins=[loaded],
            plugin_workflow=f"act4:{workflow_name}", template_context_factory=workflow.template_context_factory,
            cfg_override=[{"backend.key_name": "blank"}, {"skill.use_skill": skill_enabled}, {"langfuse.enable": False}],
            no_embed_tools=True, no_history=True,
        )
    assert not (tmp_path / "results").exists()
    assert not (tmp_path / "Guide_Doc").exists()


def test_xiangshan_target_does_not_use_catalog(tmp_path, monkeypatch) -> None:
    """Leave hardware-module names and the XiangShan startup path unrestricted."""
    def reject_catalog(*args, **kwargs):
        """Fail if the unrelated handoff workflow enters the suite gate."""
        raise AssertionError("XiangShan must not consult the catalog")

    monkeypatch.setattr("ucagent_act4.workspace.validate_suite_target", reject_catalog)
    workflow = next(item for item in get_plugin().workflows if item.name == "xiangshan-v3-handoff")
    config = Config({"template_overwrite": {field: name for field, name in (
        ("ACT4_INPUT_ROOT", "assets"), ("ACT4_FRAMEWORK_ROOT", "act"),
        ("ACT4_XIANGSHAN_ROOT", "xs"), ("ACT4_MANUAL_ROOT", "manual"),
    )}})
    assert workflow.template_context_factory(config, {"WORKSPACE": str(tmp_path), "OUT": "results", "DUT": "Vector"}) == {}


@pytest.mark.parametrize("fault", ["missing", "digest", "headers", "short_row", "empty", "collision", "stale_exclusion", "date", "schema", "json"])
def test_corrupt_catalog_fails_closed(tmp_path, snapshot, fault) -> None:
    """Do not accept arbitrary targets when packaged metadata or source structure is invalid."""
    rows, metadata = snapshot
    if fault == "headers":
        rows[0][1] = "Wrong header"
    elif fault == "short_row":
        rows[5].pop()
    elif fault == "empty":
        rows = rows[:3]
    elif fault == "collision":
        rows[4][1] = "I!"
    elif fault == "stale_exclusion":
        metadata["non_targets"]["Not in source"] = "heading"
    elif fault == "date":
        metadata["retrieved_on"] = "invalid"
    elif fault == "schema":
        metadata["schema_version"] = 99
    write_catalog(tmp_path, rows, metadata)
    if fault == "missing":
        (tmp_path / "test_suites.csv").unlink()
    elif fault == "digest":
        with (tmp_path / "test_suites.csv").open("a") as stream:
            stream.write("\n")
    elif fault == "json":
        (tmp_path / "test_suites.json").write_text("{invalid", encoding="utf-8")
    with pytest.raises(PluginError, match="Cannot load ACT4 Test Suite catalog"):
        load_suite_catalog(tmp_path)


def test_rendered_catalog_merges_names_and_omits_source_rows() -> None:
    """Keep two readable columns, showing original names only when they differ."""
    script = runpy.run_path(str(PROJECT / "scripts/sync_suite_targets.py"))
    rendered = script["render_catalog"]()
    assert "| Test Suite | Description |" in rendered
    assert "| `I` | Integer |" in rendered
    assert "| `Sspm_Smnpm`<br>Sspm (Smnpm*) | Supervisor Pointer Masking |" in rendered
    assert "| Test Suite cell | Reason |" in rendered
    assert "Sheet rows" not in rendered
    assert all(line.count("|") == 3 for line in rendered.splitlines() if line.startswith("|"))


def test_target_document_and_packaging_use_the_runtime_catalog() -> None:
    """Prevent documentation drift and omission of catalog files from installed plugins."""
    script = runpy.run_path(str(PROJECT / "scripts/sync_suite_targets.py"))
    document = (PROJECT / "docs/test-suites.md").read_text(encoding="utf-8")
    rendered = document.split(script["START"])[1].split(script["END"])[0].strip()
    assert rendered == script["render_catalog"]()
    config = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"]["package-data"]["ucagent_act4"]
    assert "data/*.csv" in package_data and "data/*.json" in package_data
    assert "recursive-include src/ucagent_act4/data *.csv *.json" in (PROJECT / "MANIFEST.in").read_text()
