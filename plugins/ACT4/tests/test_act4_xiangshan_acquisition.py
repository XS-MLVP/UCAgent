"""Test upstream-first module selection and actual gap-generation orchestration boundaries."""

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4 import xiangshan_bundle as bundle
from ucagent_act4 import xiangshan_acquisition
from ucagent_act4.xiangshan_acquisition import XiangShanAcquisition
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
    assert "Internal timing scenario" in (harness.results / "delivery/TESTS.md").read_text()


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


@pytest.mark.parametrize("outcome", ["passed", "failed", "timeout", "skipped", "incomplete", "wrong_workflow", "missing_assets", "missing_report", "wrong_suite"])
@pytest.mark.parametrize("style", ["scenario", "table"])
def test_gap_generation_runs_existing_workflow_and_requires_completed_stages(harness, monkeypatch, outcome, style):
    """Invoke a private child workflow and reject failed, skipped, interrupted or substituted completion."""
    feature = harness.scope["features"][0]
    feature.update(resolution="generate", generation_job="G1", next_action="Generate the missing fixture suite")
    harness.scope["generation_jobs"] = [{"id": "G1", "suite": "H", "rationale": "Missing upstream implementation",
        "eligibility": "Synthetic native generation eligibility for orchestration tests", "generation_style": style}]
    harness.write("scope.yaml", harness.scope)
    manual = harness.root / "manual"
    manual.mkdir()
    roots = {"upstream": harness.framework, "local": harness.source, "xiangshan": harness.xs, "manual": manual}
    state = harness.state["act4_xiangshan:out/intermediate/Sstc/handoff:Sstc"]
    acquisition = XiangShanAcquisition(harness.output, roots, state, {}, None)
    scope = acquisition.validate("Sstc")
    workflow_name = xiangshan_acquisition.GENERATION_WORKFLOWS[style]
    workflow_id = f"act4:{workflow_name}"
    workflow_path = Path(__file__).resolve().parents[1] / f"src/ucagent_act4/workflows/{workflow_name}.yaml"
    workflow = yaml.safe_load(workflow_path.read_text())
    calls = []

    def child(argv, cwd, log, timeout, process_started, environment):
        """Emulate command boundaries while preserving actual filesystem receipt checks."""
        calls.append(argv)
        log.write_text("fixture child process")
        assert argv[1:3] == ["-m", "ucagent.cli"]
        assert workflow_id in argv
        assert "--exit-on-completion" in argv and "--loop" in argv
        assert "--mcp-server-no-file-tools" in argv and "--mcp-server-port" in argv
        from ucagent.util.config import Config
        from ucagent_act4.workspace import validate_input_paths

        settings = yaml.safe_load(Path(argv[argv.index("--config") + 1]).read_text())["act4_run"]
        assert settings["upstream"]["manual_root"] == str(manual)
        assert settings["upstream"]["act4_root"] == str(harness.framework)
        assert settings["workflow"] == workflow_name and settings["suite"] == "H"
        project = "act4_priv_suite_generate" if style == "scenario" else "act4_unprivileged_generate"
        validate_input_paths(Config({"act4_run": settings, "template_overwrite": {"PROJECT": project}}),
                             {"WORKSPACE": str(cwd), "OUT": "act4_assets", "DUT": "H"})
        assert not (cwd / "riscv-arch-test").exists()
        shutil.copytree(harness.framework, cwd / "riscv-arch-test")
        stages = {str(index): {"task": {"title": f"{index + 1}-{stage['name']}-fixture"}, "is_completed": outcome != "incomplete",
            "check_pass": True, "is_skipped": outcome == "skipped"} for index, stage in enumerate(workflow["stage"])}
        info = {"all_completed": outcome != "incomplete", "DUT": "H", "plugin_workflow": workflow_id,
                "stages_info": stages}
        if outcome == "wrong_workflow":
            info["plugin_workflow"] = "act4:unrelated-workflow"
        bundle.write_json(cwd / ".ucagent/ucagent_info.json", info)
        directory = "priv" if style == "scenario" else "rv64"
        assembly = cwd / f"riscv-arch-test/tests/{directory}/H/new.S"
        assembly.parent.mkdir(parents=True)
        assembly.write_text("generated fixture")
        category = "priv" if style == "scenario" else "unpriv"
        required = [f"coverpoints/{category}/H_coverage.svh", f"coverpoints/{category}/H_coverage_init.svh",
                    "coverpoints/norm/H.yaml"]
        required += ["testplans/priv/H.yaml", "generators/testgen/src/testgen/priv/extensions/H.py"] if style == "scenario" else ["testplans/H.csv"]
        for name in required:
            path = cwd / "riscv-arch-test" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated fixture")
        for name in ("H_validation_state.yaml", "H_file_manifest.yaml"):
            path = cwd / "act4_assets/intermediate/H/reports" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture report")
        (cwd / "act4_assets/final.md").write_text("fixture final")
        (cwd / "act4_assets/changes.patch").write_text("fixture patch")
        bundle.write_json(cwd / "act4_assets/intermediate/H/native-validation/receipt.json", {"status": "fixture"})
        if outcome == "missing_assets":
            (cwd / "riscv-arch-test" / required[0]).unlink()
        elif outcome == "missing_report":
            (cwd / "act4_assets/intermediate/H/native-validation/receipt.json").unlink()
        elif outcome == "wrong_suite":
            wrong = assembly.parent.with_name("HOther") / assembly.name
            wrong.parent.mkdir()
            assembly.rename(wrong)
        return {"status": outcome if outcome in {"failed", "timeout"} else "passed", "exit_code": 0}

    monkeypatch.setattr(bundle, "execute", child)
    if outcome != "passed":
        with pytest.raises(ValueError, match="did not finish|without completing|lacks|missing its"):
            acquisition.synthesize(scope, "G1", "codex", 30)
        assert not state.get("synthesis")
        return
    checker = harness.checker("inputs")
    checker.manual_root = "manual"
    checker.cfg = SimpleNamespace(get_value=lambda key, default=None: "codex")
    passed, result = checker.do_check(action="synthesize", generation_id="G1", timeout=30)
    assert passed, result
    assert len(calls) == 1
    imported = acquisition.import_roots(scope)["generated:G1"]
    relative = f"tests/{'priv' if style == 'scenario' else 'rv64'}/H/new.S"
    assert (imported / relative).read_text() == "generated fixture"
    assert not (harness.framework / relative).exists()
    assert state["synthesis"]["G1"]["workflow"] == workflow_id
    harness.plan["imports"] = [{"origin": "generated:G1", "source": relative,
                                "destination": relative, "features": ["timer"]}]
    harness.write("input.yaml", harness.plan)
    assert checker.do_check(action="prepare")[0]
    (imported / relative).write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        acquisition.import_roots(scope)


@pytest.mark.parametrize("style", ["scenario", "table"])
def test_cannot_generate_over_existing_suite(harness, style):
    """The orchestration must preserve the generation workflow's new-suite-only contract."""
    relative = "generators/testgen/src/testgen/priv/extensions/Sstc.py" if style == "scenario" else "coverpoints/unpriv/Sstc_coverage.svh"
    generator = harness.framework / relative
    generator.parent.mkdir(parents=True)
    generator.write_text('"""Existing suite."""\n')
    assert harness.checker("scope").do_check(action="discover", queries=["Sstc"])[0]
    harness.scope["features"][0].update(resolution="generate", generation_job="G1", next_action="Investigate missing coverage")
    harness.scope["generation_jobs"] = [{"id": "G1", "suite": "Sstc", "rationale": "Gap", "eligibility": "Existing CTP", "generation_style": style}]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("scope").do_check()
    assert not passed and "do not overwrite" in result["error"].lower()


@pytest.mark.parametrize("style", [None, "", "unprivileged", []])
def test_generation_route_must_be_explicit(harness, style):
    """Do not silently choose a trap environment from an extension name or missing style."""
    harness.scope["features"][0].update(resolution="generate", generation_job="G1", next_action="Generate missing suite")
    job = {"id": "G1", "suite": "NewSuite", "rationale": "Missing asset", "eligibility": "Inspected native inputs"}
    if style is not None:
        job["generation_style"] = style
    harness.scope["generation_jobs"] = [job]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("scope").do_check()
    assert not passed and "generation_style: table or scenario" in result["error"], result


def test_generation_job_requires_catalog_suite_before_launch(harness):
    """Reject private native aliases before attempting to launch a generation child."""
    harness.scope["features"][0].update(resolution="generate", generation_job="G1", next_action="Generate missing suite")
    harness.scope["generation_jobs"] = [{"id": "G1", "suite": "UnknownSuite", "generation_style": "scenario",
        "rationale": "Missing asset", "eligibility": "Inspected native inputs"}]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("scope").do_check()
    assert not passed and "catalog Test Suite target" in result["error"]
