"""Prove ISA-first ordering, immutable provenance and complete asset comparison."""

import copy
import hashlib
import json
from pathlib import Path
import re

import pytest
import yaml

from act4_privileged_suite.plugin import get_plugin
from act4_privileged_suite.review_tools import ACT4ReviewDocument
from ucagent.tools.uctool import to_mcp_tool
from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


@pytest.fixture
def isa_review(tmp_path: Path) -> tuple[ReviewHarness, dict]:
    """Use the complete maintained ISA plan example as a real gate input."""
    harness = ReviewHarness(tmp_path, accept_plan=False)
    guide = get_plugin().root / "Guide_Doc/ACT4_Extension_Review_Guide.md"
    plan = yaml.safe_load(re.findall(r"```yaml\n(.*?)```", guide.read_text(), re.DOTALL)[-1])
    (tmp_path / "isa-fixture.adoc").write_text(plan["requirements"][0]["basis"][0]["quote"] + "\n")
    harness.write("isa-plan.yaml", plan)
    harness.scope["reference_files"] = plan["reference_files"]
    harness.scope["reference_scope"] = plan["reference_scope"]
    harness.write("scope.yaml", harness.scope)
    return harness, plan


def test_isa_plan_does_not_inspect_assets_or_execute_jobs(isa_review, monkeypatch) -> None:
    """Accept the design from ISA sources while forbidding all reads of fixture assets."""
    harness, plan = isa_review
    original_text, original_bytes = Path.read_text, Path.read_bytes

    def read_text(path, *args, **kwargs):
        """Reject asset reads during the source-only planning stage."""
        assert not path.is_relative_to(harness.source), path
        return original_text(path, *args, **kwargs)

    def read_bytes(path, *args, **kwargs):
        """Reject binary asset reads as well as textual reads."""
        assert not path.is_relative_to(harness.source), path
        return original_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    passed, result = harness.checker("plan").do_check()
    assert passed and not result["accepted"], result
    assert not (harness.output / "isa-plan-accepted.json").exists()
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert passed and result["accepted"], result
    assert json.loads((harness.output / "isa-plan-accepted.json").read_text())["plan"] == plan
    assert not (harness.output / "validation-plan.json").exists()
    assert not (harness.output / "baseline").exists()


@pytest.mark.parametrize("phase", ["audit", "repair", "final"])
def test_isa_plan_cannot_be_skipped(tmp_path: Path, phase: str) -> None:
    """Reject asset review and command collection without an accepted independent plan."""
    harness = ReviewHarness(tmp_path, accept_plan=False)
    passed, result = harness.checker(phase).do_check(run_commands=True)
    assert not passed, result
    assert not (harness.output / "validation-plan.json").exists()
    assert not (harness.output / "evidence-before.json").exists()


@pytest.mark.parametrize("arguments", [{"run_commands": True}, {"experiment": {"action": "prepare", "id": "E1"}}])
def test_isa_plan_rejects_asset_execution(isa_review, arguments: dict) -> None:
    """Do not execute an asset job or repair experiment in the independent-design stage."""
    harness, _ = isa_review
    passed, result = harness.checker("plan").do_check(**arguments)
    assert not passed and "ISA sources only" in result["error"]


@pytest.mark.parametrize("mutation", ["duplicate", "missing_observation", "false_quote", "asset_citation", "missing_block", "orphan_requirement", "unrelated_block", "unknown_requirement"])
def test_isa_plan_rejects_incomplete_or_unverifiable_design(isa_review, mutation: str) -> None:
    """Require actual ISA quotations, unique requirements and complete source review links."""
    harness, plan = isa_review
    if mutation == "duplicate":
        plan["requirements"].append(copy.deepcopy(plan["requirements"][0]))
    elif mutation == "missing_observation":
        plan["requirements"][0]["observation"] = ""
    elif mutation == "false_quote":
        plan["requirements"][0]["basis"][0]["quote"] = "invented ISA rule"
    elif mutation == "asset_citation":
        plan["requirements"][0]["basis"][0]["path"] = "baseline/generators/H.py"
    elif mutation == "missing_block":
        plan["source_reviews"] = []
    elif mutation == "orphan_requirement":
        plan["source_reviews"][0]["requirements"] = []
    elif mutation == "unrelated_block":
        plan["source_reviews"][0]["source"] = "source:plan:existing:1-1"
    else:
        plan["source_reviews"][0]["requirements"] = ["I999"]
    harness.write("isa-plan.yaml", plan)
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert not passed, result
    assert not (harness.output / "isa-plan-accepted.json").exists()


@pytest.mark.parametrize("artifact", ["isa-plan.yaml", "isa-plan-accepted.json", "isa-plan-context.json", "isa-references/isa-fixture.adoc", "original"])
def test_accepted_isa_design_and_sources_are_immutable(isa_review, artifact: str) -> None:
    """Detect changes to any accepted plan component after reconstructing the checker."""
    harness, plan = isa_review
    assert harness.checker("plan").do_check(is_complete=True)[0]
    if artifact == "original":
        (harness.root / "isa-fixture.adoc").write_text("changed rule\n")
    elif artifact == "isa-plan.yaml":
        plan["requirements"][0]["stimulus"] = "Reduce the plan to fit existing tests"
        harness.write(artifact, plan)
    else:
        path = harness.output / artifact
        if path.suffix == ".json":
            data = json.loads(path.read_text())
            data["forged"] = True
            path.write_text(json.dumps(data))
        else:
            path.write_text("changed rule\n")
    passed, result = harness.checker("audit").do_check()
    assert not passed, result
    assert not (harness.output / "validation-plan.json").exists()


def test_plan_document_tool_uses_only_isa_and_preserves_acceptance(isa_review) -> None:
    """Author the plan through MCP-compatible document operations, without native evidence."""
    harness, plan = isa_review
    harness.write("isa-plan.yaml", {**plan, "requirements": [], "source_reviews": []})
    assert not harness.checker("plan").do_check()[0]
    assert (harness.output / "isa-plan-context.json").exists()
    tool = ACT4ReviewDocument(workspace=str(harness.root), review_dir="reports/H/review", suite="H", write_dirs=["reports"])
    assert "isa-plan" in to_mcp_tool(tool).parameters["properties"]["document"]["enum"]
    status = tool._run(action="status", document="isa-plan")
    assert status["ok"] and status["progress"]["source_count"] == 1
    changes = copy.deepcopy({key: plan[key] for key in ("requirements", "source_reviews")})
    for item in changes["requirements"] + changes["source_reviews"]:
        for citation in item["basis"]:
            citation.pop("quote")
    result = tool._run(action="update", document="isa-plan", expected_sha256=status["sha256"], changes=changes)
    assert result["ok"], result
    assert tool._run(action="quote", document="isa-plan", citations=[plan["requirements"][0]["basis"][0]])["ok"]
    assert not tool._run(action="quote", document="isa-plan", citations=[{"path": "baseline/generators/H.py", "lines": [1, 1], "observation": "Existing test"}])["ok"]
    assert not tool._run(action="update", document="isa-plan", expected_sha256=status["sha256"], changes={"limitations": ["stale update"]})["ok"]
    assert harness.checker("plan").do_check(is_complete=True)[0]
    revision = hashlib.sha256((harness.output / "isa-plan.yaml").read_bytes()).hexdigest()
    result = tool._run(action="update", document="isa-plan", expected_sha256=revision, changes={"limitations": []})
    assert not result["ok"] and "frozen" in result["error"]


def test_isa_exclusions_require_their_own_source_review(isa_review) -> None:
    """Check excluded sections rather than silently shrinking the independent source scope."""
    harness, plan = isa_review
    (harness.root / "isa-fixture.adoc").write_text(plan["requirements"][0]["basis"][0]["quote"] + "\nEditorial publication note.\n")
    plan["reference_scope"]["isa-fixture.adoc"]["excluded_reason"] = "Publication note has no architectural requirements"
    harness.write("isa-plan.yaml", plan)
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert not passed and "excluded:isa-fixture.adoc:2-2" in result["error"]
    plan["source_reviews"].append({"source": "excluded:isa-fixture.adoc:2-2", "requirements": [],
        "reason": "The publication note does not define architectural behavior", "basis": [{"path": "isa-references/isa-fixture.adoc",
            "lines": [2, 2], "quote": "Editorial publication note.", "observation": "Editorial only"}]})
    harness.write("isa-plan.yaml", plan)
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert passed, result


@pytest.mark.parametrize("mutation", ["omitted", "unknown", "scope_narrowed", "citation_removed"])
def test_audit_must_compare_the_independent_plan(isa_review, mutation: str) -> None:
    """Prevent discarding or relabeling the independent requirements to match existing assets."""
    harness, _ = isa_review
    assert harness.checker("plan").do_check(is_complete=True)[0]
    review = harness.audit()
    assert review["obligations"][0]["plan_items"] == ["I1"]
    if mutation == "omitted":
        review["obligations"][0]["plan_items"] = []
    elif mutation == "unknown":
        review["obligations"][0]["plan_items"] = ["I999"]
    elif mutation == "scope_narrowed":
        harness.scope.update(reference_files=[], reference_scope={})
        harness.write("scope.yaml", harness.scope)
    else:
        judgment = next(item for item in review["semantic_review"]["judgments"] if "obligation:O1" in item["tasks"])
        judgment["basis"] = [item for item in judgment["basis"] if item["path"] != "isa-plan.yaml"]
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check(is_complete=True)
    assert not passed, result


@pytest.mark.parametrize("local_input", [False, True])
def test_final_retains_isa_comparison_and_reports_limitations(isa_review, local_input: bool) -> None:
    """Preserve original requirement IDs through formal repair and final report delivery."""
    harness, _ = isa_review
    if local_input:
        (harness.source / ".git").rename(harness.root / "saved-git")
        local = harness.root / "local-module"
        harness.source.rename(local)
        harness.source = local
    assert harness.checker("plan").do_check(is_complete=True)[0]
    harness.audit()
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 2\n')
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "Fixture repair; ISA semantics remain unverified",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Changed fixture", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Synthetic ISA; no real architectural validation"], "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    text = (harness.output / "final.md").read_text()
    assert "Independent ISA plan comparison" in text and "| I1 | O1 |" in text
    assert "Synthetic rule" in text
    final["obligations"][0]["plan_items"] = []
    harness.write("final.yaml", final)
    assert not harness.checker("final").do_check(is_complete=True)[0]


def test_missing_isa_requires_explicit_limitation(tmp_path: Path) -> None:
    """Allow honest asset-only review but never present a missing design as complete ISA coverage."""
    harness = ReviewHarness(tmp_path, accept_plan=False)
    plan = {"schema_version": 1, "suite": "H", "target_context": "User requests local module H",
            "reference_files": [], "reference_scope": {}, "requirements": [], "source_reviews": [], "limitations": []}
    harness.write("isa-plan.yaml", plan)
    assert not harness.checker("plan").do_check(is_complete=True)[0]
    plan["limitations"] = ["ISA original text is unavailable; semantic completeness is not established"]
    harness.write("isa-plan.yaml", plan)
    assert harness.checker("plan").do_check(is_complete=True)[0]


def test_no_applicable_rules_need_not_invent_a_requirement(isa_review) -> None:
    """Allow a justified empty design while retaining source review and its limitation."""
    harness, plan = isa_review
    plan["requirements"] = []
    plan["source_reviews"][0].update(requirements=[], reason="User scope excludes feature X absent configurations")
    plan["limitations"] = ["The selected rule is outside the user scope; no applicable test was designed"]
    harness.write("isa-plan.yaml", plan)
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert passed, result


def test_planning_cannot_be_backdated_after_validation(isa_review) -> None:
    """Reject an attempt to accept a supposedly independent plan after collecting asset evidence."""
    harness, _ = isa_review
    (harness.output / "validation-plan.json").write_text('{}')
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert not passed and "before asset validation" in result["error"]


def test_asset_inputs_cannot_be_used_as_independent_isa_sources(isa_review) -> None:
    """Reject a declared asset file before creating an allegedly ISA-only source snapshot."""
    harness, plan = isa_review
    plan["reference_files"] = ["riscv-arch-test/README.md"]
    plan["reference_scope"] = {"riscv-arch-test/README.md": {"reviewed_lines": [[1, 1]], "excluded_reason": ""}}
    harness.write("isa-plan.yaml", plan)
    passed, result = harness.checker("plan").do_check(is_complete=True)
    assert not passed and "asset input directory" in result["error"]
    assert not (harness.output / "isa-references").exists()
