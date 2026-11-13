"""Regress scoped review evidence, bounded batches, and safe document operations."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite.checkers.act4_asset_checker import ACT4AssetChecker
from act4_privileged_suite.checkers.act4_review_checker import ACT4ReviewChecker
from act4_privileged_suite.plugin import get_plugin
from act4_privileged_suite.review_tools import ACT4ReviewDocument, create_review_tools
from ucagent.plugins import PluginContext
from ucagent.tools.uctool import to_mcp_tool
from ucagent.util.config import Config

from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


@pytest.mark.parametrize("target, expected", [("Other_cg/cp/one", None), ("Other_cg/missing", "mapping_coverpoint_exists"), ("Other_cg/cp/missing", "mapping_bin_exists")])
def test_context_resolves_shared_symbols_without_expanding_review(tmp_path: Path, target: str, expected: str | None) -> None:
    """Context fixes cross-suite lookup but neither hides broken targets nor imports other points."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    (harness.source / "Other.svh").write_text("covergroup Other_cg;\ncp: coverpoint value { bins one = {1}; }\nendgroup\n")
    (harness.source / "coverpoints/norm").mkdir(parents=True)
    mapping = {"normative_rule_definitions": [{"name": "shared_rule", "coverpoint": [target]}]}
    (harness.source / "coverpoints/norm/H.yaml").write_text(yaml.safe_dump(mapping))
    (harness.source / "shared.yaml").write_text(yaml.safe_dump({"normative_rule_definitions": [{"name": "second_rule", "coverpoint": [target]}]}))
    harness.scope["assets"].update(coverage=["H.svh"], mappings=["coverpoints/norm/H.yaml", "shared.yaml"])
    harness.scope["context_files"] = ["Other.svh"]
    harness.scope["shared_assets"] = [{"path": "Other.svh", "consumers": ["H", "Other"], "boundary": "Resolve external targets only; Other semantics are outside this review"}]
    harness.write("scope.yaml", harness.scope)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["coverpoints"] == ["H_cg/cp"]
    findings = [finding for result in evidence["static"] for finding in result["report"]["findings"]]
    assert not any(item["check"] in {"source_mapping_mismatch", "mapping_group_exists"} for item in findings)
    assert any(item["check"] == expected for item in findings) is (expected is not None)
    generator_diagnostics = [item for key, item in evidence["review_tasks"].items() if key.startswith("diagnostic:") and item["check"] == "generator_registration"]
    assert len(generator_diagnostics) == 1 and len(generator_diagnostics[0]["occurrences"]) == 2
    _, ordinary = ACT4AssetChecker(suite="H", act4_root=str(harness.source), mapping="shared.yaml", coverage_files=["H.svh"], discover_coverage=False).set_workspace(str(tmp_path)).do_check()
    assert any(item["check"] == "mapping_group_exists" for item in ordinary["report"]["findings"])
    assert any(item["check"] == "source_mapping_mismatch" for item in ordinary["report"]["findings"])


@pytest.mark.parametrize("defect", ["missing", "overlap", "outside", "bool", "unordered", "unexplained", "unknown"])
def test_reference_ranges_reject_ambiguous_scope(tmp_path: Path, defect: str) -> None:
    """Reject silently omitted references, overlapping ranges, and unjustified exclusions."""
    harness = ReviewHarness(tmp_path)
    (tmp_path / "manual.adoc").write_text("Rule\n" * 100)
    harness.scope["reference_files"] = ["manual.adoc"]
    selection = {"reviewed_lines": [[1, 100]], "excluded_reason": ""}
    harness.scope["reference_scope"] = {"manual.adoc": selection}
    if defect == "missing":
        harness.scope.pop("reference_scope")
    elif defect == "unknown":
        harness.scope["reference_scope"]["unknown.adoc"] = selection
    elif defect == "unexplained":
        selection["reviewed_lines"] = [[20, 30]]
    else:
        selection["reviewed_lines"] = {"overlap": [[1, 20], [20, 30]], "outside": [[1, 101]], "bool": [[True, 20]], "unordered": [[20, 30], [1, 10]]}[defect]
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check()
    assert not passed and result["error_code"] == "act4_review_scope"


def test_reference_selection_keeps_exclusions_and_deduplicates_plans(tmp_path: Path) -> None:
    """Full references stay frozen while selected obligations and explicit exclusions stay auditable."""
    harness = ReviewHarness(tmp_path)
    (tmp_path / "manual.adoc").write_text("Unrelated rule\n" * 200 + "Selected obligation\n" * 20 + "Other extension\n" * 300)
    (harness.source / "plan.md").write_text("Planned obligation\n")
    harness.scope["assets"]["test_plans"] = ["plan.md"]
    harness.scope["reference_files"] = ["manual.adoc", "riscv-arch-test/plan.md"]
    harness.scope["reference_scope"] = {"manual.adoc": {"reviewed_lines": [[201, 220]], "excluded_reason": "Other extension chapters do not apply"},
        "riscv-arch-test/plan.md": {"reviewed_lines": [[1, 1]], "excluded_reason": ""}}
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert set(evidence["obligation_sources"]) == {"source:plan:plan.md:1-1", "source:specification:manual.adoc:201-220"}
    boundary = evidence["review_tasks"]["boundary:manual.adoc"]
    assert boundary["excluded_lines"] == [[1, 200], [221, 520]]
    assert (harness.output / "references/manual.adoc").read_bytes() == (tmp_path / "manual.adoc").read_bytes()
    judgment = next(item for item in review["semantic_review"]["judgments"] if item["tasks"] == ["boundary:manual.adoc"])
    judgment.update(status="passed", confidence="confirmed")
    harness.write("review.yaml", review)
    assert not harness.checker("audit").do_check()[0]


def test_batches_require_current_records_and_reconcile_restart(tmp_path: Path) -> None:
    """Complete only validated batches; removing records invalidates persisted completion claims."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    judgments = copy.deepcopy(review["semantic_review"]["judgments"])
    review["semantic_review"]["judgments"] = []
    harness.write("review.yaml", review)
    checker = ACT4ReviewChecker("audit", "H", "reports/H/review", batch_size=2).set_workspace(str(tmp_path)).set_stage_manager(harness.manager)
    checker.set_stage(SimpleNamespace(name="review_audit", title=lambda: "review_audit"))
    passed, result = checker.do_check(is_complete=True)
    assert not passed and result["error_code"] == "act4_review_batch_pending"
    assert len(result["current_batch"]) == 2
    initial_template = checker.get_template_data()
    assert checker.get_template_data() == initial_template
    while not passed:
        current = set(result["current_batch"])
        review["semantic_review"]["judgments"].extend(item for item in judgments if set(item["tasks"]) <= current)
        harness.write("review.yaml", review)
        passed, result = checker.do_check(is_complete=True)
    review["semantic_review"]["judgments"].pop()
    harness.write("review.yaml", review)
    resumed = ACT4ReviewChecker("audit", "H", "reports/H/review", batch_size=2).set_workspace(str(tmp_path)).set_stage_manager(harness.manager)
    resumed.set_stage(SimpleNamespace(name="review_audit", title=lambda: "review_audit"))
    passed, result = resumed.do_check(is_complete=True)
    assert not passed and result["observed"]["completed"] < result["observed"]["total"]
    progress = json.loads((harness.output / "progress-audit.json").read_text())
    assert len(progress["missing_tasks"]) == 1


def test_missing_obligation_and_traceability_are_batched_together(tmp_path: Path) -> None:
    """Expose all incomplete dimensions instead of serially hiding later missing work."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "plan.md").write_text("Required behavior\n")
    (harness.source / "H.svh").write_text("covergroup H_cg;\ncp: coverpoint flag;\nendgroup\n")
    harness.scope["assets"].update(test_plans=["plan.md"], coverage=["H.svh"])
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    review["obligations"] = []
    review["traceability"] = []
    review["semantic_review"]["judgments"] = [item for item in review["semantic_review"]["judgments"] if not item["tasks"][0].startswith("obligation:")]
    harness.write("review.yaml", review)
    passed, result = harness.checker("audit").do_check(is_complete=True)
    assert not passed and result["error_code"] == "act4_review_batch_pending"
    progress = json.loads((harness.output / "progress-audit.json").read_text())
    assert set(progress["missing_tasks"]) == {"source:plan:plan.md:1-1", "point:H_cg/cp"}


@pytest.fixture
def document_tool(tmp_path: Path) -> tuple[ReviewHarness, ACT4ReviewDocument]:
    """Collect a small real evidence set and bind a review-only tool with write restrictions."""
    harness = ReviewHarness(tmp_path)
    assert harness.checker("audit").do_check()[0]
    harness.checker("audit").do_check(run_commands=True)
    tool = ACT4ReviewDocument(workspace=str(tmp_path), review_dir="reports/H/review", suite="H", write_dirs=["reports"], un_write_dirs=["riscv-arch-test"])
    return harness, tool


def test_document_tool_initializes_and_upserts_exact_citations(document_tool) -> None:
    """Generate no semantic verdicts, serialize quotations exactly, and preserve unrelated work."""
    harness, tool = document_tool
    assert tool.invoke({"action": "initialize"})["ok"]
    draft = yaml.safe_load((harness.output / "review.yaml").read_text())
    assert draft["semantic_review"]["judgments"] == [] and draft["findings"] == []
    assert not harness.checker("audit").do_check(is_complete=True)[0]
    status = tool.invoke({"action": "status"})
    assert status["progress"]["current_batch"] and "missing_tasks" not in status["progress"]
    citation = {"path": "baseline/generators/H.py", "lines": [1, 2], "observation": "The fixture generator contains VALUE = 1"}
    quoted = tool.invoke({"action": "quote", "citations": [citation]})
    assert quoted["ok"] and quoted["citations"][0]["quote"] == '"""Native H generator fixture."""\nVALUE = 1'
    result = tool.invoke({"action": "update", "expected_sha256": status["sha256"], "changes": {"summary": "Review: still incomplete", "findings": [{"id": "F1", "investigation": [{"basis": [citation]}]}]}})
    assert result["ok"], result
    updated = yaml.safe_load((harness.output / "review.yaml").read_text())
    assert updated["findings"][0]["investigation"][0]["basis"][0] == quoted["citations"][0]
    assert len(updated["checks"]) == 8
    assert not harness.checker("audit").do_check(is_complete=True)[0]
    assert not tool.invoke({"action": "update", "expected_sha256": status["sha256"], "changes": {"summary": "stale overwrite"}})["ok"]
    schema = to_mcp_tool(tool).parameters
    assert schema["properties"]["action"]["enum"] == ["status", "initialize", "quote", "update", "context", "reuse"]


@pytest.mark.parametrize("defect", ["escape", "stale_source", "bad_quote", "too_many_lines", "boolean_lines", "self_reference", "protected", "symlink", "duplicate_ids"])
def test_document_tool_rejects_unsafe_or_unverifiable_updates(document_tool, defect: str, tmp_path: Path) -> None:
    """Failed extraction or policy checks leave the original document byte-for-byte unchanged."""
    harness, tool = document_tool
    assert tool._run("initialize")["ok"]
    original = (harness.output / "review.yaml").read_bytes()
    citation = {"path": "baseline/generators/H.py", "lines": [1, 1], "observation": "Actual source"}
    if defect == "escape":
        citation["path"] = "../../../../secret"
    elif defect == "self_reference":
        citation["path"] = "review.yaml"
    elif defect == "stale_source":
        (harness.output / "baseline/generators/H.py").write_text("Changed\n")
    elif defect == "bad_quote":
        citation["quote"] = "Invented text"
    elif defect in {"too_many_lines", "boolean_lines"}:
        citation["lines"] = [1, 101] if defect == "too_many_lines" else [True, 1]
    elif defect == "protected":
        tool.un_write_dirs = ["reports/H/review"]
    elif defect == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_text("{}")
        (harness.output / "evidence-before.json").unlink()
        (harness.output / "evidence-before.json").symlink_to(outside)
    changes = {"findings": [{"id": "F1", "investigation": [{"basis": [citation]}]}]}
    if defect == "duplicate_ids":
        changes["findings"] *= 2
    result = tool._run("update", expected_sha256=hashlib.sha256(original).hexdigest(), changes=changes)
    assert not result["ok"] and (harness.output / "review.yaml").read_bytes() == original


def test_grouped_judgment_update_cannot_drop_other_tasks(document_tool) -> None:
    """Replacing one grouped verdict must explicitly preserve every task in that group."""
    harness, tool = document_tool
    assert tool._run("initialize")["ok"]
    revision = tool._run("status")["sha256"]
    result = tool._run("update", expected_sha256=revision, changes={"semantic_review": {"judgments": [{"tasks": ["topic:ci", "topic:omissions"]}]}})
    assert result["ok"]
    original = (harness.output / "review.yaml").read_bytes()
    result = tool._run("update", expected_sha256=result["sha256"], changes={"semantic_review": {"judgments": [{"tasks": ["topic:ci"]}]}})
    assert not result["ok"] and (harness.output / "review.yaml").read_bytes() == original


@pytest.mark.parametrize("action", ["status", "initialize", "quote"])
def test_document_operations_do_not_silently_ignore_updates(document_tool, action: str) -> None:
    """An update supplied to the wrong action must not be reported as successful."""
    harness, tool = document_tool
    result = tool._run(action, changes={"summary": "This was meant to be saved"})
    assert not result["ok"] and not (harness.output / "review.yaml").exists()


@pytest.mark.parametrize("settings", [{}, {"template_overwrite": {"PROJECT": "act4_generation"}}])
def test_document_factory_is_review_only(tmp_path: Path, settings: dict) -> None:
    """Loading the ACT4 plugin must not add the review tool to generation workflows."""
    cfg = Config(settings)
    context = PluginContext(tmp_path, "reports", ("reports",), (), cfg, get_plugin().root)
    assert create_review_tools(context) == []


def test_final_review_batches_cannot_publish_partial_delivery(tmp_path: Path) -> None:
    """After-evidence judgments remain mandatory even with an empty, honestly scoped patch."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    review.update(findings=[], changes=[])
    review["semantic_review"] = harness.assess(review)
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    final = {"schema_version": 1, "suite": "H", "summary": "No source changes; synthetic semantics unverified",
        "findings": [], "ci_passed": True, "remaining_risks": ["Synthetic ISA semantics remain unverified"],
        "coverage_changes": [], "traceability": []}
    harness.write_final(final)
    judgments = copy.deepcopy(final["semantic_review"]["judgments"])
    final["semantic_review"]["judgments"] = []
    harness.write("final.yaml", final)
    checker = ACT4ReviewChecker("final", "H", "reports/H/review", batch_size=3).set_workspace(str(tmp_path)).set_stage_manager(harness.manager)
    passed, result = checker.do_check(is_complete=True)
    assert not passed and not (harness.output / "final.md").exists()
    assert not (harness.output / "changes.patch").exists()
    assert len(result["current_batch"]) == 3
    final["semantic_review"]["judgments"] = judgments
    harness.write("final.yaml", final)
    passed, result = checker.do_check(is_complete=True)
    assert passed, result
    assert (harness.output / "final.md").is_file()
    assert (harness.output / "changes.patch").read_bytes() == b""


@pytest.mark.parametrize("defect", ["overlap", "no_boundary", "missing_file"])
def test_context_scope_is_explicit_and_disjoint(tmp_path: Path, defect: str) -> None:
    """Reference-only scope cannot silently hide reviewed files or unresolved dependencies."""
    harness = ReviewHarness(tmp_path)
    (harness.source / "Other.svh").write_text("covergroup Other_cg;\ncp: coverpoint flag;\nendgroup\n")
    name = "generators/H.py" if defect == "overlap" else "missing.svh" if defect == "missing_file" else "Other.svh"
    harness.scope["context_files"] = [name]
    if defect != "no_boundary":
        harness.scope["shared_assets"] = [{"path": name, "consumers": ["H", "Other"], "boundary": "Reference only"}]
    harness.write("scope.yaml", harness.scope)
    assert not harness.checker("audit").do_check()[0]


@pytest.mark.parametrize("failure", ["schema", "batch"])
def test_review_pauses_repeated_checks_inside_one_model_turn(tmp_path: Path, failure: str) -> None:
    """Repeated tool calls pause review without requiring an outer backend turn to finish."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    original = copy.deepcopy(review)
    if failure == "schema":
        review["summary"] = ""
    else:
        review["semantic_review"]["judgments"] = []
    harness.write("review.yaml", review)
    pauses = []
    harness.manager.agent = SimpleNamespace(set_break=pauses.append)
    checker = ACT4ReviewChecker("audit", "H", "reports/H/review", max_stalled_checks=2).set_workspace(str(tmp_path)).set_stage_manager(harness.manager)
    assert not checker.do_check()[0]
    passed, result = checker.do_check()
    assert not passed and result["execution_paused"] is True and pauses == [True]
    harness.write("review.yaml", original)
    assert checker.do_check()[0]
    harness.write("review.yaml", review)
    passed, result = checker.do_check()
    assert not passed and result["stalled_checks"] == 1 and not result.get("execution_paused")


def test_batch_progress_resets_per_check_stall_detection(tmp_path: Path) -> None:
    """Newly validated work resets the budget even before the entire current batch is done."""
    harness = ReviewHarness(tmp_path)
    review = harness.audit()
    judgments = review["semantic_review"]["judgments"]
    review["semantic_review"]["judgments"] = []
    harness.write("review.yaml", review)
    pauses = []
    harness.manager.agent = SimpleNamespace(set_break=pauses.append)
    checker = ACT4ReviewChecker("audit", "H", "reports/H/review", max_stalled_checks=2).set_workspace(str(tmp_path)).set_stage_manager(harness.manager)
    assert not checker.do_check()[0]
    review["semantic_review"]["judgments"] = [judgments[0]]
    harness.write("review.yaml", review)
    passed, result = checker.do_check()
    assert not passed and result["stalled_checks"] == 1 and pauses == []


@pytest.mark.parametrize("limit", [0, -1, True, "8"])
def test_review_stall_limit_requires_a_positive_integer(limit) -> None:
    """Reject ambiguous or disabled per-Check review protection."""
    with pytest.raises(ValueError, match="max_stalled_checks"):
        ACT4ReviewChecker("audit", "H", "reports/H/review", max_stalled_checks=limit)


@pytest.mark.parametrize("batch_size", [0, 51, True, "12"])
def test_review_batch_size_is_bounded(batch_size) -> None:
    """Reject invalid or unbounded review batch configuration before workspace access."""
    with pytest.raises(ValueError, match="batch_size"):
        ACT4ReviewChecker("audit", "H", "reports/H/review", batch_size=batch_size)
