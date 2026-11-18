"""Regress shared citation validation and conflict-safe incremental report publication."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from act4_privileged_suite.review_tools import ACT4ReviewDocument
from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators
from test_act4_review_isa_plan import isa_review


@pytest.fixture
def citation_case(tmp_path: Path) -> SimpleNamespace:
    """Provide recorded text, tool discovery, and a revision-bound unfinished review."""
    root = tmp_path / "reports/intermediate/H/review"
    (root / "baseline").mkdir(parents=True)
    source = root / "baseline/source.txt"
    source.write_bytes(('first: "quoted" # value\r\n  second: \'text\' \\ path  \r\n' +
                        '\n'.join(f'line {index}' for index in range(3, 151)) + '\n').encode())
    (root / "probe.log").write_text("Optional simulator not available\n")
    (root / "before.log").write_text("Baseline validation result\n")
    environment = {"tools": {"questa": {"attempts": [
        {"log": "probe.log", "sha256": hashlib.sha256((root / "probe.log").read_bytes()).hexdigest()},
    ]}}}
    evidence = {"schema_version": 1, "review_digest": "current-digest", "environment": environment,
                "source_files": {"baseline/source.txt": hashlib.sha256(source.read_bytes()).hexdigest()},
                "jobs": [{"log": "before.log", "log_sha256": hashlib.sha256((root / "before.log").read_bytes()).hexdigest()}]}
    for name, data in (("evidence-before.json", evidence), ("environment.json", environment)):
        (root / name).write_text(json.dumps(data, indent=2) + "\n")
    report = {"schema_version": 1, "suite": "H", "summary": "Review in progress", "findings": [],
              "semantic_review": {"reviewer": "ai", "evidence_digest": "current-digest", "judgments": []}}
    path = root / "review.yaml"
    path.write_text(yaml.safe_dump(report))
    tool = ACT4ReviewDocument(workspace=str(tmp_path), review_dir="reports/intermediate/H/review", suite="H", write_dirs=["reports"])
    citation = {"path": "baseline/source.txt", "lines": [1, 2], "observation": "The source includes quoted and indented text"}
    changes = {"findings": [{"id": "F1", "investigation": [{"basis": [citation]}]}]}
    return SimpleNamespace(root=root, source=source, evidence=evidence, report=report, path=path, tool=tool,
                           citation=citation, changes=changes, revision=hashlib.sha256(path.read_bytes()).hexdigest())


def test_document_preserves_semantics_quotes_and_permissions(citation_case) -> None:
    """Round-trip exact quotes without rewriting conclusions, unrelated records or file permissions."""
    case = citation_case
    case.path.chmod(0o640)
    judgment = {"tasks": ["topic:ci"], "status": "unverified", "confidence": "inferred",
                "reasoning": "The quoted source does not prove execution", "conclusion": "Needs validation",
                "limitation": "No execution evidence", "next_action": "Run validation", "findings": [],
                "basis": [deepcopy(case.citation)]}
    changes = {"semantic_review": {"judgments": [judgment]}}
    original = deepcopy(changes)
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": changes})
    assert result["ok"], result
    saved = yaml.safe_load(case.path.read_text())
    actual = saved["semantic_review"]["judgments"][0]
    assert actual["basis"][0].pop("quote") == '\n'.join(case.source.read_text().splitlines()[:2])
    assert actual == original["semantic_review"]["judgments"][0]
    assert changes == original and saved["summary"] == case.report["summary"]
    assert case.path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("lines", [[1, 100], [0, 1], [2, 1], [1, 151], [1, 101], [True, 2], [1.0, 2], [1], "1:2"])
def test_document_enforces_exact_physical_line_bounds(citation_case, lines) -> None:
    """Only existing inclusive integer ranges of at most one hundred lines may be quoted."""
    case = citation_case
    case.citation["lines"] = lines
    original = case.path.read_bytes()
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert result["ok"] == (lines == [1, 100]), result
    if not result["ok"]:
        assert case.path.read_bytes() == original
        assert result["location"] == "changes.findings[0].investigation[0].basis[0]"


@pytest.mark.parametrize("defect", ["stale_digest", "missing_evidence", "invalid_json", "wrong_schema",
                                   "changed_source", "binary", "blank", "wrong_quote", "missing_path",
                                   "missing_lines", "missing_observation", "unrecorded"])
def test_document_rejects_invalid_inputs_without_publishing(citation_case, defect: str) -> None:
    """Invalid evidence and partial citations must leave the current report untouched."""
    case = citation_case
    if defect == "stale_digest":
        case.changes["semantic_review"] = {"evidence_digest": "old-digest"}
    elif defect == "missing_evidence":
        (case.root / "evidence-before.json").unlink()
    elif defect == "invalid_json":
        (case.root / "evidence-before.json").write_text("{")
    elif defect == "wrong_schema":
        case.evidence["schema_version"] = True
        (case.root / "evidence-before.json").write_text(json.dumps(case.evidence, indent=2) + "\n")
    elif defect == "changed_source":
        case.source.write_text("New source\n")
    elif defect in {"binary", "blank"}:
        case.source.write_bytes(b"\xff\x00\n\n" if defect == "binary" else b"\n\n")
        case.evidence["source_files"]["baseline/source.txt"] = hashlib.sha256(case.source.read_bytes()).hexdigest()
        (case.root / "evidence-before.json").write_text(json.dumps(case.evidence, indent=2) + "\n")
    elif defect == "wrong_quote":
        case.citation["quote"] = "Invented text"
    elif defect.startswith("missing_"):
        case.citation.pop(defect.removeprefix("missing_"))
    else:
        case.citation["path"] = "review.yaml"
    original = case.path.read_bytes()
    changes = deepcopy(case.changes)
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": changes})
    assert not result["ok"], result
    assert case.path.read_bytes() == original and changes == case.changes


@pytest.mark.parametrize("basis", [None, {}, [], [None], [{}], [{"path": "baseline/source.txt"}]])
def test_incomplete_basis_is_diagnosed_before_writing(citation_case, basis) -> None:
    """A malformed basis must not silently bypass exact extraction and appear in a saved report."""
    case = citation_case
    case.changes["findings"][0]["investigation"][0]["basis"] = basis
    original = case.path.read_bytes()
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert not result["ok"] and result["location"].startswith("changes.findings[0].investigation[0].basis")
    assert case.path.read_bytes() == original


@pytest.mark.parametrize("name", ["environment.json", "evidence-before.json", "before.log", "probe.log", "experiment.log"])
def test_final_document_retains_baseline_environment_and_experiment_sources(citation_case, name: str) -> None:
    """Final review may quote all retained before/after, environment and experiment evidence."""
    case = citation_case
    after = deepcopy(case.evidence)
    after.update(review_digest="after-digest", jobs=[], source_files={})
    (case.root / "evidence-after.json").write_text(json.dumps(after, indent=2) + "\n")
    if name == "experiment.log":
        (case.root / name).write_text("Minimal experiment result\n")
        receipt = {"source_files": {name: hashlib.sha256((case.root / name).read_bytes()).hexdigest()}, "jobs": []}
        (case.root / "receipt.json").write_text(json.dumps(receipt))
        index = {"receipts": {"receipt.json": hashlib.sha256((case.root / "receipt.json").read_bytes()).hexdigest()}, "attempts": {}}
        (case.root / "experiments.json").write_text(json.dumps(index))
    citation = {"path": name, "lines": [1, 1], "observation": "Retained evidence for comparison"}
    changes = {"semantic_review": {"reviewer": "ai", "evidence_digest": "after-digest", "judgments": [
        {"tasks": ["topic:ci"], "basis": [citation], "status": "unverified"},
    ]}}
    result = case.tool.invoke({"action": "update", "document": "final", "changes": changes})
    assert result["ok"], result
    saved = yaml.safe_load((case.root / "final.yaml").read_text())
    assert saved["semantic_review"]["judgments"][0]["basis"][0]["quote"] == (case.root / name).read_text().splitlines()[0]


@pytest.mark.parametrize("conflict", ["report", "evidence", "source", "index_created", "permissions", "policy", "symlink"])
def test_document_detects_changes_during_serialization(citation_case, monkeypatch, conflict: str) -> None:
    """Late changes must reject publication and preserve reports, permissions and external edits."""
    case = citation_case
    original = case.path.read_bytes()
    dump = yaml.safe_dump

    def concurrent_dump(*args, **kwargs):
        """Change a dependency after quote extraction and before publication."""
        content = dump(*args, **kwargs)
        if conflict == "report":
            case.path.write_text("External report edit\n")
        elif conflict == "evidence":
            (case.root / "evidence-before.json").write_text("New evidence\n")
        elif conflict == "source":
            case.source.write_text("New source\n")
        elif conflict == "index_created":
            (case.root / "experiments.json").write_text('{"receipts": {}, "attempts": {}}')
        elif conflict == "permissions":
            case.path.chmod(0o400)
        elif conflict == "policy":
            case.tool.un_write_dirs = ["reports"]
        else:
            other = case.root / "other.yaml"
            other.write_bytes(original)
            case.path.unlink()
            case.path.symlink_to(other)
        return content

    monkeypatch.setattr("act4_privileged_suite.review_tools.yaml.safe_dump", concurrent_dump)
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert not result["ok"], result
    assert case.path.read_bytes() == (b"External report edit\n" if conflict == "report" else original)
    assert not list(case.root.glob(".review-document-*"))
    if conflict == "permissions":
        assert case.path.stat().st_mode & 0o777 == 0o400


def test_stale_report_revision_cannot_replace_a_newer_edit(citation_case) -> None:
    """Changes prepared against an earlier revision must preserve edits made before invocation."""
    case = citation_case
    case.path.write_text("Newer report edit\n")
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert not result["ok"] and "revision changed" in result["error"]
    assert case.path.read_text() == "Newer report edit\n"


@pytest.mark.parametrize("field,value", [("source_files", []), ("jobs", {}), ("jobs", ["invalid"]),
                                        ("environment", None), ("environment", {"tools": []})])
def test_malformed_evidence_returns_an_actionable_failure(citation_case, field: str, value) -> None:
    """Malformed metadata must not escape as internal exceptions or publish a report."""
    case = citation_case
    case.evidence[field] = value
    (case.root / "evidence-before.json").write_text(json.dumps(case.evidence))
    original = case.path.read_bytes()
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert not result["ok"] and "evidence-before.json" in result["error"]
    assert result["next_action"] and case.path.read_bytes() == original


@pytest.mark.parametrize("escape", ["recorded_traversal", "source_symlink", "directory_symlink"])
def test_document_rejects_path_escapes_and_symlink_writes(citation_case, escape: str) -> None:
    """Recorded hashes do not authorize source traversal or writes through linked directories."""
    case = citation_case
    original = case.path.read_bytes()
    if escape == "directory_symlink":
        protected = Path(case.tool.workspace) / "protected"
        case.root.rename(protected)
        case.root.symlink_to(protected, target_is_directory=True)
    else:
        external = Path(case.tool.workspace) / "outside.txt"
        external.write_bytes(case.source.read_bytes())
        if escape == "source_symlink":
            case.source.unlink()
            case.source.symlink_to(external)
        else:
            name = "../../../outside.txt"
            case.evidence["source_files"][name] = hashlib.sha256(external.read_bytes()).hexdigest()
            (case.root / "evidence-before.json").write_text(json.dumps(case.evidence, indent=2) + "\n")
            case.citation["path"] = name
    result = case.tool.invoke({"action": "update", "expected_sha256": case.revision, "changes": case.changes})
    assert not result["ok"] and case.path.read_bytes() == original


def test_initialize_rechecks_scope_before_creating_report(citation_case, monkeypatch) -> None:
    """A scope change during draft rendering must prevent publication based on old assets."""
    case = citation_case
    case.path.unlink()
    scope = case.root / "scope.yaml"
    scope.write_text(yaml.safe_dump({"assets": {"generators": ["source.txt"]}}))
    dump = yaml.safe_dump

    def concurrent_dump(*args, **kwargs):
        """Simulate an operator updating scope while the initial draft is serialized."""
        content = dump(*args, **kwargs)
        scope.write_text("New scope\n")
        return content

    monkeypatch.setattr("act4_privileged_suite.review_tools.yaml.safe_dump", concurrent_dump)
    result = case.tool.invoke({"action": "initialize"})
    assert not result["ok"] and "scope.yaml changed" in result["error"]
    assert not case.path.exists()


@pytest.mark.parametrize("changed", ["isa-plan-context.json", "isa-plan-accepted.json"])
def test_plan_update_cannot_race_source_selection_or_acceptance(isa_review, monkeypatch, changed: str) -> None:
    """ISA-only editing cannot publish against changed selections or a newly frozen plan."""
    harness, _ = isa_review
    assert harness.checker("plan").do_check()[0]
    tool = ACT4ReviewDocument(workspace=str(harness.root), review_dir="reports/intermediate/H/review", suite="H", write_dirs=["reports"])
    original = (harness.output / "isa-plan.yaml").read_bytes()
    status = tool.invoke({"action": "status", "document": "isa-plan"})
    dump = yaml.safe_dump

    def concurrent_dump(*args, **kwargs):
        """Simulate refreshed context or acceptance before atomic publication."""
        content = dump(*args, **kwargs)
        (harness.output / changed).write_text("Updated plan evidence\n")
        return content

    monkeypatch.setattr("act4_privileged_suite.review_tools.yaml.safe_dump", concurrent_dump)
    result = tool.invoke({"action": "update", "document": "isa-plan", "expected_sha256": status["sha256"],
                          "changes": {"limitations": ["Additional design limitation"]}})
    assert not result["ok"] and changed in result["error"]
    assert (harness.output / "isa-plan.yaml").read_bytes() == original


def test_repeated_citations_share_one_source_read(citation_case, monkeypatch) -> None:
    """Extract multiple selections from one stable source snapshot without repeated reads."""
    case = citation_case
    reads = []
    read_bytes = Path.read_bytes

    def tracked_read(path):
        """Track reads of the selected source while retaining normal filesystem behavior."""
        if path == case.source:
            reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read)
    result = case.tool.invoke({"action": "quote", "citations": [deepcopy(case.citation) for _ in range(12)]})
    assert result["ok"] and len(reads) == 1
    assert len({item["quote"] for item in result["citations"]}) == 1


def test_written_report_still_requires_ordinary_checker_acceptance(tmp_path: Path, monkeypatch) -> None:
    """Native evidence is reused, but publishing inferred judgments cannot make Check pass."""
    harness = ReviewHarness(tmp_path)
    report = harness.audit()
    tool = ACT4ReviewDocument(workspace=str(tmp_path), review_dir="reports/intermediate/H/review", suite="H", write_dirs=["reports"])
    for judgment in report["semantic_review"]["judgments"]:
        for citation in judgment["basis"]:
            citation.pop("quote", None)
    for finding in report["findings"]:
        for citation in finding["repair_plan"]["basis"]:
            citation.pop("quote", None)
        for attempt in finding["investigation"]:
            for citation in attempt["basis"]:
                citation.pop("quote", None)
    changes = {"findings": report["findings"], "semantic_review": report["semantic_review"]}

    def unexpected_command(*args, **kwargs):
        """Report editing and ordinary Check must not rerun cached native validation."""
        pytest.fail("Report editing started a native command")

    monkeypatch.setattr("act4_privileged_suite.checkers.act4_review_checker.execute_command", unexpected_command)
    result = tool.invoke({"action": "update", "expected_sha256": tool.invoke({"action": "status"})["sha256"], "changes": changes})
    assert result["ok"], result
    assert harness.checker("audit").do_check()[0]
    changes["semantic_review"]["judgments"][0].update(status="passed", confidence="inferred")
    result = tool.invoke({"action": "update", "expected_sha256": result["sha256"], "changes": changes})
    assert result["ok"], result
    passed, diagnostic = harness.checker("audit").do_check()
    assert not passed and "cannot be passed" in diagnostic["error"]
