"""Test upstream-first module selection and actual gap-generation orchestration boundaries."""

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite import xiangshan_bundle as bundle
from act4_privileged_suite.xiangshan_acquisition import XiangShanAcquisition
from test_act4_xiangshan_handoff import HandoffHarness


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Provide canonical module-selection documents and independent local/upstream trees."""
    return HandoffHarness(tmp_path, monkeypatch)


@pytest.mark.parametrize("mutation", ["no_search", "new_upstream_file", "unread_candidates", "fake_quote", "complete_local", "complete_generate", "unknown_job", "unknown_query"])
def test_scope_requires_real_upstream_first_assessment(harness, mutation):
    """Fail fabricated absence claims, stale catalogs and regeneration of sufficient upstream assets."""
    feature = harness.scope["features"][0]
    if mutation == "no_search":
        (harness.output / "discovery.json").unlink()
    elif mutation == "new_upstream_file":
        (harness.framework / "testplans/new.csv").write_text("new assets\n")
    elif mutation == "unread_candidates":
        feature["inspected"] = []
    elif mutation == "fake_quote":
        feature["inspected"][0]["quote"] = "invented"
    elif mutation in {"complete_local", "complete_generate"}:
        feature.update(upstream_status="complete", resolution=mutation.split("_")[1])
    elif mutation == "unknown_job":
        feature.update(resolution="generate", generation_job="unknown", next_action="Generate missing suite")
    else:
        feature["queries"] = ["never-searched"]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("scope").do_check()
    assert not passed, result


def test_module_can_resolve_multiple_act_suites_and_preserve_unavailable_parts(harness):
    """Keep one user module independent of ACT suite names and disclose unsupported functions."""
    feature = harness.scope["features"][0]
    feature["act4_suites"] = ["Sstc", "InterruptsS"]
    harness.scope["features"].append({**feature, "id": "timing", "description": "Internal timing scenario",
        "act4_suites": [], "resolution": "unavailable", "gap": "No ISA-visible observation for this microarchitecture property",
        "assessment": "Needs a unit-level testbench", "next_action": "Use an independent RTL interface testbench"})
    harness.write("scope.yaml", harness.scope)
    harness.built()
    passed, report = harness.checker("delivery").do_check(action="package")
    assert passed, report
    assert report["functions"][1]["resolution"] == "unavailable"
    assert "Internal timing scenario" in (harness.output / "delivery/TESTS.md").read_text()


def test_mixed_imports_cannot_bypass_upstream_reuse(harness):
    """A complete upstream function cannot silently be replaced with local or unrelated generated input."""
    harness.scope["features"][0].update(upstream_status="complete", resolution="reuse")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inputs").do_check(action="prepare")
    assert not passed and "Local supplementation" in result["error"]


def test_discovery_is_a_real_catalog_and_normal_check_does_not_refetch(harness, monkeypatch):
    """Persist independent query results and do not launch commands during ordinary scope checks."""
    passed, result = harness.checker("scope").do_check(action="discover", queries=["Sstc", "vector-missing-fixture"])
    assert passed and result["counts"]["Sstc"] > 0 and result["counts"]["vector-missing-fixture"] == 0

    def forbidden(*args, **kwargs):
        """Reject any attempt to execute an acquisition command during a read-only check."""
        raise AssertionError("Unexpected command")

    monkeypatch.setattr(bundle, "execute", forbidden)
    assert harness.checker("scope").do_check(is_complete=True)[0]


def test_fetch_owns_new_paths_and_never_changes_provided_checkout(tmp_path, monkeypatch):
    """Download fixed public inputs only into fresh owned directories and reuse completed fetches."""
    output = tmp_path / "out"
    output.mkdir()
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "unchanged"
    marker.write_text("user checkout")
    roots = {"upstream": output / "repositories/riscv-arch-test", "xiangshan": existing,
             "manual": output / "repositories/riscv-isa-manual"}
    calls = []

    def clone(argv, cwd, log, timeout, *args):
        """Materialize a fixed-public-source clone fixture without accessing the network."""
        calls.append(argv)
        assert argv[:2] == ["git", "clone"]
        assert argv[-2].startswith("https://github.com/riscv/")
        Path(argv[-1]).mkdir()
        log.write_text("clone fixture")
        return {"status": "passed"}

    monkeypatch.setattr(bundle, "execute", clone)
    acquisition = XiangShanAcquisition(output, roots, {}, {}, None)
    acquisition.fetch(30)
    acquisition.fetch(30)
    assert len(calls) == 2 and marker.read_text() == "user checkout"
    roots["upstream"] = tmp_path / "missing-user-path"
    with pytest.raises(ValueError, match="user-specified"):
        acquisition.fetch(30)


@pytest.mark.parametrize("outcome", ["passed", "failed", "timeout", "skipped", "incomplete", "wrong_workflow"])
def test_gap_generation_runs_existing_workflow_and_requires_completed_stages(harness, monkeypatch, outcome):
    """Invoke a private child workflow and reject failed, skipped, interrupted or substituted completion."""
    feature = harness.scope["features"][0]
    feature.update(resolution="generate", generation_job="G1", next_action="Generate the missing fixture suite")
    harness.scope["generation_jobs"] = [{"id": "G1", "suite": "NewTimer", "rationale": "Missing upstream implementation",
        "eligibility": "Synthetic CTP eligibility for orchestration tests"}]
    harness.write("scope.yaml", harness.scope)
    manual = harness.root / "manual"
    manual.mkdir()
    roots = {"upstream": harness.framework, "local": harness.source, "xiangshan": harness.xs, "manual": manual}
    state = harness.state["act4_xiangshan:out/Sstc/handoff:Sstc"]
    acquisition = XiangShanAcquisition(harness.output, roots, state, {}, None)
    scope = acquisition.validate("Sstc")
    workflow_path = Path(__file__).resolve().parents[1] / "src/act4_privileged_suite/workflows/privileged-suite-generation.yaml"
    workflow = yaml.safe_load(workflow_path.read_text())
    calls = []

    def child(argv, cwd, log, timeout, process_started, environment):
        """Emulate command boundaries while preserving actual filesystem receipt checks."""
        calls.append(argv)
        log.write_text("fixture child process")
        if argv[:2] == ["git", "clone"]:
            shutil.copytree(harness.framework, argv[-1])
            return {"status": "passed", "exit_code": 0}
        assert argv[1:3] == ["-m", "ucagent.cli"]
        assert "act4-privileged-suite:privileged-suite-generation" in argv
        assert "--exit-on-completion" in argv and "--loop" in argv
        assert environment["ACT4_MANUAL_ROOT"] == str(manual)
        stages = {str(index): {"task": {"title": f"{index + 1}-{stage['name']}-fixture"}, "is_completed": outcome != "incomplete",
            "check_pass": True, "is_skipped": outcome == "skipped"} for index, stage in enumerate(workflow["stage"])}
        info = {"all_completed": outcome != "incomplete", "DUT": "NewTimer", "plugin_workflow": "act4-privileged-suite:privileged-suite-generation",
                "stages_info": stages}
        if outcome == "wrong_workflow":
            info["plugin_workflow"] = "act4-privileged-suite:extension-review"
        bundle.write_json(cwd / ".ucagent/ucagent_info.json", info)
        assembly = cwd / "riscv-arch-test/tests/priv/NewTimer/new.S"
        assembly.parent.mkdir(parents=True)
        assembly.write_text("generated fixture")
        for name in ("generators/testgen/src/testgen/priv/extensions/NewTimer.py", "coverpoints/priv/NewTimer_coverage.svh", "coverpoints/norm/NewTimer.yaml"):
            path = cwd / "riscv-arch-test" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated fixture")
        for name in ("NewTimer_final_summary_report.md", "NewTimer_validation_state.yaml", "NewTimer_file_manifest.yaml"):
            path = cwd / "act4_assets/NewTimer/reports" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture report")
        return {"status": outcome if outcome in {"failed", "timeout"} else "passed", "exit_code": 0}

    monkeypatch.setattr(bundle, "execute", child)
    if outcome != "passed":
        with pytest.raises(ValueError, match="did not finish|without completing"):
            acquisition.synthesize(scope, "G1", "langchain", 30)
        assert not state.get("synthesis")
        return
    checker = harness.checker("inputs")
    checker.manual_root = "manual"
    checker.cfg = SimpleNamespace(get_value=lambda key, default=None: "langchain")
    passed, result = checker.do_check(action="synthesize", generation_id="G1", timeout=30)
    assert passed, result
    assert len(calls) == 2
    imported = acquisition.import_roots(scope)["generated:G1"]
    assert (imported / "tests/priv/NewTimer/new.S").read_text() == "generated fixture"
    assert not (harness.framework / "tests/priv/NewTimer/new.S").exists()
    harness.plan["imports"] = [{"origin": "generated:G1", "source": "tests/priv/NewTimer/new.S",
                                "destination": "tests/priv/NewTimer/new.S", "features": ["timer"]}]
    harness.write("input.yaml", harness.plan)
    assert checker.do_check(action="prepare")[0]
    (imported / "tests/priv/NewTimer/new.S").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        acquisition.import_roots(scope)


def test_cannot_generate_over_existing_privileged_suite(harness):
    """The orchestration must preserve the generation workflow's new-suite-only contract."""
    generator = harness.framework / "generators/testgen/src/testgen/priv/extensions/Sstc.py"
    generator.parent.mkdir(parents=True)
    generator.write_text('"""Existing suite."""\n')
    assert harness.checker("scope").do_check(action="discover", queries=["Sstc"])[0]
    harness.scope["features"][0].update(resolution="generate", generation_job="G1", next_action="Investigate missing coverage")
    harness.scope["generation_jobs"] = [{"id": "G1", "suite": "Sstc", "rationale": "Gap", "eligibility": "Existing CTP"}]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("scope").do_check()
    assert not passed and "do not overwrite" in result["error"]
