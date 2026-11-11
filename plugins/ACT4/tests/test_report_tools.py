"""Verify exact report quotes, unchanged semantic judgments, write policy and atomic failure."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite.checkers.act4_review_checker import TOPICS
from act4_privileged_suite.plugin import get_plugin
from act4_privileged_suite.report_tools import WriteACT4ReviewReport, create_review_report_tools
from act4_privileged_suite import report_tools
from test_act4_review_checker import ReviewHarness
from ucagent.plugins import LoadedPlugin, PluginContext, create_plugin_tools
from ucagent.tools.uctool import to_mcp_tool
from ucagent.util.config import Config


@pytest.fixture
def report_case(tmp_path: Path) -> SimpleNamespace:
    """Provide recorded source identities and a model-authored report without copied quotes."""
    root = tmp_path / "reports/H/review"
    (root / "baseline").mkdir(parents=True)
    source = root / "baseline/source.txt"
    source.write_bytes(('first: "quoted" # value\r\n  second: \'text\' \\ path  \r\n' +
                        '\n'.join(f'line {index}' for index in range(3, 151)) + '\n').encode())
    evidence = {"schema_version": 1, "review_digest": "current-digest", "jobs": [],
                "source_files": {"baseline/source.txt": hashlib.sha256(source.read_bytes()).hexdigest()}}
    (root / "evidence-before.json").write_text(json.dumps(evidence, indent=2) + "\n")
    document = {"schema_version": 1, "suite": "H", "summary": "Review evidence limitations",
                "checks": {topic: {"status": "unverified", "conclusion": "Needs real evidence", "evidence": ["evidence-before.json"]} for topic in TOPICS},
                "findings": [], "changes": [], "post_assets": {}, "traceability": [],
                "semantic_review": {"reviewer": "ai", "evidence_digest": "current-digest", "judgments": [
                    {"tasks": [f"topic:{topic}" for topic in sorted(TOPICS)], "status": "unverified",
                     "confidence": "unverified", "reasoning": "The fixture source cannot establish ISA semantics",
                     "conclusion": "Further review is required", "limitation": "Synthetic fixture only",
                     "next_action": "Read the actual specification", "findings": [],
                     "basis": [{"path": "baseline/source.txt", "lines": [1, 2],
                                "observation": "These are the selected fixture lines"}]}]}}
    config = Config({"stage": [{"checker": [{"clss": "ACT4ReviewChecker", "args": {
        "phase": phase, "suite": "H", "review_dir": "reports/H/review"}}]} for phase in ("audit", "final")]})
    context = PluginContext(tmp_path, "reports", ("reports",), ("Guide_Doc",), config, get_plugin().root)
    tool = create_review_report_tools(context)[0]
    return SimpleNamespace(root=root, source=source, evidence=evidence, document=document,
                           context=context, tool=tool, path="reports/H/review/review.yaml")


def test_write_report_extracts_exact_quotes_and_preserves_judgments(report_case) -> None:
    """Round-trip difficult source text through YAML without modifying input or judgments."""
    case = report_case
    original = deepcopy(case.document)
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert result["success"], result
    saved = yaml.safe_load((case.root / "review.yaml").read_text())
    quote = saved["semantic_review"]["judgments"][0]["basis"][0].pop("quote")
    assert quote == '\n'.join(case.source.read_text().splitlines()[:2])
    assert saved == original == case.document
    assert result["quotes"] == 1 and result["next_action"]
    assert result["sha256"] == hashlib.sha256((case.root / "review.yaml").read_bytes()).hexdigest()
    assert not (case.root / "candidate").exists()


@pytest.mark.parametrize("lines", [[0, 1], [2, 1], [1, 151], [1, 101], [True, 2], [1.0, 2], [1], "1:2"])
def test_report_rejects_invalid_line_ranges_without_writing(report_case, lines) -> None:
    """Enforce the same one-based bounded physical-line selection as the report gate."""
    case = report_case
    case.document["semantic_review"]["judgments"][0]["basis"][0]["lines"] = lines
    (case.root / "review.yaml").write_text("original report\n")
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and "lines" in result["error"]
    assert result["location"] == "semantic_review.judgments[0].basis[0]"
    assert (case.root / "review.yaml").read_text() == "original report\n"


def test_report_accepts_exactly_one_hundred_lines(report_case) -> None:
    """Accept the inclusive maximum citation span without extending its bounds."""
    case = report_case
    case.document["semantic_review"]["judgments"][0]["basis"][0]["lines"] = [1, 100]
    assert case.tool.invoke({"path": case.path, "document": case.document})["success"]
    report = yaml.safe_load((case.root / "review.yaml").read_text())
    assert len(report["semantic_review"]["judgments"][0]["basis"][0]["quote"].splitlines()) == 100


def test_late_invalid_citation_preserves_target(report_case) -> None:
    """Failure after preparing an earlier valid quote must leave the entire report untouched."""
    case = report_case
    (case.root / "review.yaml").write_text("original report\n")
    case.document["semantic_review"]["judgments"][0]["basis"].append({
        "path": "review.yaml", "lines": [1, 1], "observation": "Unacceptable self-citation"})
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and result["location"].endswith("basis[1]")
    assert (case.root / "review.yaml").read_text() == "original report\n"


def test_recorded_traversal_citation_is_still_rejected(report_case) -> None:
    """Even a path present in edited metadata cannot escape the report evidence directory."""
    case = report_case
    outside = case.context.workspace / "outside.txt"
    outside.write_text("external text\n")
    name = "../../../outside.txt"
    case.evidence["source_files"][name] = hashlib.sha256(outside.read_bytes()).hexdigest()
    (case.root / "evidence-before.json").write_text(json.dumps(case.evidence, indent=2) + "\n")
    case.document["semantic_review"]["judgments"][0]["basis"][0].update(path=name, lines=[1, 1])
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and "Unsafe relative path" in result["error"]
    assert not (case.root / "review.yaml").exists()


@pytest.mark.parametrize("path", ["review.yaml", "scope.yaml", "../outside", "/etc/passwd", "baseline/missing.txt"])
def test_report_rejects_unrecorded_citations(report_case, path: str) -> None:
    """Reject report self-citations and paths absent from the recorded evidence set."""
    case = report_case
    case.document["semantic_review"]["judgments"][0]["basis"][0]["path"] = path
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and "basis.path" in result["error"]
    assert not (case.root / "review.yaml").exists()


@pytest.mark.parametrize("defect", ["stale_digest", "changed_source", "binary", "blank", "missing_evidence", "invalid_json", "wrong_quote", "missing_observation", "empty_basis", "empty_judgments"])
def test_report_failure_preserves_existing_target(report_case, defect: str) -> None:
    """Reject invalid or stale evidence without rewriting the report or semantic status."""
    case = report_case
    (case.root / "review.yaml").write_text("original report\n")
    semantic = case.document["semantic_review"]
    citation = semantic["judgments"][0]["basis"][0]
    if defect == "stale_digest":
        semantic["evidence_digest"] = "old-digest"
    elif defect == "changed_source":
        case.source.write_text("changed\n")
    elif defect in {"binary", "blank"}:
        case.source.write_bytes(b"\xff\x00\n\n" if defect == "binary" else b"\n\n")
        case.evidence["source_files"]["baseline/source.txt"] = hashlib.sha256(case.source.read_bytes()).hexdigest()
        (case.root / "evidence-before.json").write_text(json.dumps(case.evidence, indent=2) + "\n")
    elif defect == "missing_evidence":
        (case.root / "evidence-before.json").unlink()
    elif defect == "invalid_json":
        (case.root / "evidence-before.json").write_text("{")
    elif defect == "wrong_quote":
        citation["quote"] = "Invented source text"
    elif defect == "missing_observation":
        citation.pop("observation")
    elif defect == "empty_basis":
        semantic["judgments"][0]["basis"] = []
    else:
        semantic["judgments"] = []
    original = deepcopy(case.document)
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and result["error_code"] == "act4_report_write"
    assert (case.root / "review.yaml").read_text() == "original report\n"
    assert case.document == original


@pytest.mark.parametrize("conflict", ["target", "evidence", "source"])
def test_report_preserves_concurrent_changes(report_case, monkeypatch, conflict: str) -> None:
    """A late evidence/source/target change must prevent publication and preserve external edits."""
    case = report_case
    target = case.root / "review.yaml"
    target.write_text("original report\n")
    dump = yaml.safe_dump

    def concurrent_dump(*args, **kwargs):
        """Inject a filesystem change after quote extraction but before report publication."""
        content = dump(*args, **kwargs)
        path = {"target": target, "evidence": case.root / "evidence-before.json", "source": case.source}[conflict]
        path.write_text("external change\n")
        return content

    monkeypatch.setattr(report_tools.yaml, "safe_dump", concurrent_dump)
    result = case.tool.invoke({"path": case.path, "document": case.document})
    assert not result["success"] and "changed" in result["error"]
    assert target.read_text() == ("external change\n" if conflict == "target" else "original report\n")


@pytest.mark.parametrize("policy", ["readonly", "denied", "symlink", "undeclared"])
def test_report_respects_workflow_paths_and_write_policy(report_case, policy: str) -> None:
    """Never modify arbitrary output files, read-only targets or symlink destinations."""
    case = report_case
    path = case.path
    if policy in {"readonly", "denied"}:
        context = case.context
        context = PluginContext(context.workspace, context.output_dir,
                                () if policy == "readonly" else context.write_dirs,
                                ("reports/H/review",) if policy == "denied" else context.un_write_dirs,
                                context.cfg, context.plugin_root)
        case.tool = create_review_report_tools(context)[0]
    elif policy == "symlink":
        other = case.context.workspace / "other.yaml"
        other.write_text("preserved\n")
        (case.root / "review.yaml").symlink_to(other)
    else:
        path = "reports/H/review/baseline.json"
    result = case.tool.invoke({"path": path, "document": case.document})
    assert not result["success"], result
    if policy == "symlink":
        assert other.read_text() == "preserved\n"
    else:
        assert not (case.root / "review.yaml").exists()


def test_final_report_cites_before_and_after_sources(report_case) -> None:
    """Use after evidence for the digest while retaining original source citations in final reports."""
    case = report_case
    candidate = case.root / "candidate/source.txt"
    candidate.parent.mkdir()
    candidate.write_text("current source\n")
    after = deepcopy(case.evidence)
    after.update(review_digest="after-digest", source_files={"candidate/source.txt": hashlib.sha256(candidate.read_bytes()).hexdigest()})
    (case.root / "evidence-after.json").write_text(json.dumps(after, indent=2) + "\n")
    semantic = case.document["semantic_review"]
    semantic["evidence_digest"] = "after-digest"
    semantic["judgments"][0]["basis"].append({"path": "candidate/source.txt", "lines": [1, 1], "observation": "Current source"})
    result = case.tool.invoke({"path": "reports/H/review/final.yaml", "document": case.document})
    assert result["success"] and result["quotes"] == 2


def test_factory_and_mcp_schema_use_only_declared_review_targets(report_case) -> None:
    """Register the local tool with MCP-compatible arguments and omit it from other workflows."""
    context = report_case.context
    loaded = LoadedPlugin(get_plugin(), "act4-privileged-suite", "test")
    tools = create_plugin_tools([loaded], context)
    assert [tool.name for tool in tools] == ["WriteACT4ReviewReport"]
    parameters = to_mcp_tool(tools[0]).parameters
    assert set(parameters["properties"]) == {"path", "document"}
    assert set(parameters["required"]) == {"path", "document"}
    other = PluginContext(context.workspace, context.output_dir, context.write_dirs, context.un_write_dirs,
                          Config({"stage": [{"checker": [{"clss": "ACT4AssetChecker"}]}]}), context.plugin_root)
    assert create_review_report_tools(other) == []


def test_generated_report_passes_existing_audit_gate(tmp_path: Path, monkeypatch) -> None:
    """Generate quotes for a full fixture review and validate it with cached native evidence."""
    harness = ReviewHarness(tmp_path)
    report = harness.audit()
    for judgment in report["semantic_review"]["judgments"]:
        for citation in judgment["basis"]:
            citation.pop("quote")
    context = PluginContext(tmp_path, "reports", ("reports",), ("Guide_Doc",), Config(), get_plugin().root)
    tool = WriteACT4ReviewReport(context, {"reports/H/review/review.yaml": "H"})
    result = tool.invoke({"path": "reports/H/review/review.yaml", "document": report})
    assert result["success"], result

    def unexpected_command(*args, **kwargs):
        """Fail if report preparation or ordinary validation starts a native command."""
        pytest.fail("Report-only validation must reuse native evidence")

    monkeypatch.setattr("act4_privileged_suite.checkers.act4_review_checker.execute_command", unexpected_command)
    passed, result = harness.checker("audit").do_check()
    assert passed, result
    report["semantic_review"]["judgments"][0]["confidence"] = "inferred"
    report["semantic_review"]["judgments"][0]["status"] = "passed"
    result = tool.invoke({"path": "reports/H/review/review.yaml", "document": report})
    assert result["success"], result
    passed, result = harness.checker("audit").do_check()
    assert not passed and "cannot be passed" in result["error"]
