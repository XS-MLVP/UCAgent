"""Exercise ROOT/phenomenon/case relationships against real measured VCD snapshots."""

import json
from html.parser import HTMLParser
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ucagent.util.waveform_viewer import build_waveform_viewer_url
from bug_review.core.evidence import decode_fields, root_page, snapshot_preview
from bug_review.core.records import (BugEntry, BugRecord, BusField, CaseEntry, CaseRecord,
    CoverageRecord, EnvironmentReview, EvidenceBinding, ReplayResult, ReplaySummary,
    ReviewEvent, ReviewIndex, RootCause, RootsRecord, ScenarioStep, TestManifest, WaveReview)
from bug_review.core.reporting import prepare_waveform_bundle, render_pages, verify_pages
from bug_review.core.validation import ReviewIssues, validate_correlation


def example(tmp_path):
    """Create two phenomena sharing a case, with two real executions and waveforms."""
    output = tmp_path / "verification_review/analysis"
    output.mkdir(parents=True)
    tests = tmp_path / "verification_review/run/unity_test/tests"
    tests.mkdir(parents=True)
    (tests / "test_demo.py").write_text("def test_message():\n    assert False, 'wrong message'\n")
    (tmp_path / "spec.md").write_text("Messages preserve the current request.\n")
    (tmp_path / "rtl.v").write_text("module demo; wire [95:0] cmsg; endmodule\n")
    case_id = "tests/test_demo.py::test_message"
    payload = {"v": 2, "test_dir": "verification_review/run/unity_test", "test_case": "test_message",
               "start": "0", "end": "40", "cursor": "0",
               "signals": ["TOP.demo.cmsg[95:0]", "TOP.demo.cvalid", "TOP.demo.cready"]}
    viewer = build_waveform_viewer_url(payload)
    raw = f"{0x100000000000000802000031:096b}"
    waves, receipts = [], []
    for receipt_id in ["a" * 32, "b" * 32]:
        target = tmp_path / f"verification_review/run/unity_test/{receipt_id}.vcd"
        target.write_text("$timescale 1ps $end\n$scope module TOP $end\n$scope module demo $end\n"
            "$var wire 96 ! cmsg [95:0] $end\n$var wire 1 \" cvalid $end\n"
            "$var wire 1 # cready $end\n$upscope $end\n$upscope $end\n$enddefinitions $end\n"
            "#0\nb0 !\n0\"\n0#\n#20\nb" + raw + " !\n1\"\n1#\n#40\n0\"\n")
        wave = WaveReview(receipt_id=receipt_id, conclusion="dut_bug", viewer_url=viewer,
                          analysis_window={"effective_start_step": 0, "effective_end_step": 40},
                          signal_groups={"outputs": payload["signals"]}, observed_behavior="wrong message",
                          alignment_evidence="valid and ready at 20", source_correlation="rtl.v:1")
        waves.append(wave)
        stat = target.stat()
        receipts.append({"receipt_id": receipt_id, "arguments": {"test_case_name": case_id},
            "result": {"waveform_viewer": {"url": viewer}, "analysis_window": wave.analysis_window,
                       "signal_groups": wave.signal_groups,
                       "waveform_selection": {"waveform_file": str(target.relative_to(tmp_path)),
                            "size_bytes": stat.st_size, "modified_time_ns": stat.st_mtime_ns}}})
    store = tmp_path / ".ucagent/waveinfo_receipts.json"
    store.parent.mkdir()
    store.write_text(json.dumps({"receipts": receipts}))
    waveinfo = SimpleNamespace(get_analysis_receipt=lambda receipt_id: next(
        (item for item in receipts if item["receipt_id"] == receipt_id), None),
        get_bug_document_evidence=lambda _: {"success": True})
    case = CaseRecord(case_id=case_id, bug_ids=["SYM-A", "SYM-B"],
                      replay=ReplayResult(status="failed", baseline_id="baseline-1", invocation_id="baseline-1", report_node_id=case_id,
                                          reruns=[{"invocation_id": "rerun-1"}]),
                      waveform=waves[0], additional_waveforms=[waves[1]],
                      scenario_steps=[ScenarioStep(step_id="read", execution_id=execution, action="RAID_CMD=2, R_TAG=0x33",
                          receiver_setting="cready=1", expected="R_TAG=0x33", status="failed",
                          source_refs=["unity_test/tests/test_demo.py:1-2"])
                          for execution in ["baseline-1", "rerun-1"]])
    case.test_review.correctness_confirmed = True
    case.failure_analysis.category = "confirmed_dut"
    for n, execution in enumerate(["baseline-1", "rerun-1"]):
        case.events.append(ReviewEvent(event_id=f"message-{n}", execution_id=execution, step_id="read",
            kind="first_deviation", source_kind="waveform", description=f"phenomenon {n}: stale R_TAG",
            expected="R_TAG=0x33", condition="cvalid && cready", receipt_id=waves[n].receipt_id,
            time=20, signal_path="TOP.demo.cmsg", raw_value=raw,
            fields=[BusField(name="R_TAG", parts=[(18, 18), (8, 0)], source_ref="spec.md:1")],
            rtl_refs=["rtl.v:1"]))
    bugs = {}
    for n, bug_id in enumerate(case.bug_ids):
        bugs[bug_id] = BugRecord(bug_id=bug_id, case_ids=[case_id], decision={
            "verdict": "confirmed", "review_confidence": 0.9, "rationale": "own direct waveform",
            "root_id": "ROOT-LATCH", "spec_ref": "spec.md:1", "rtl_ref": "rtl.v:1",
            "first_error": "message is not updated", "causal_chain": "latch -> stale output"},
            phenomenon={"scenario": {"summary": "read current result"},
                        "spec_expected": {"summary": "return current message"},
                        "actual": {"summary": "stale R_TAG=0x31"}, "bug_root_cause": "missing update",
                        "signal_explanations": [{"rtl_name": "cmsg", "meaning": "Return the current request message",
                            "signal_path": "TOP.demo.cmsg[95:0]", "source_refs": ["rtl.v:1"]}]},
            evidence_bindings=[EvidenceBinding(evidence_id=f"e-{n}", case_id=case_id,
                event_id=f"message-{n}", role="direct", reason=f"own phenomenon {n}")])
    roots = RootsRecord(roots=[RootCause(root_id="ROOT-LATCH", title="Current message is not latched",
        bug_ids=case.bug_ids, rtl_ref="rtl.v:1", first_error="message is not updated",
        causal_chain="latch -> stale output", primary_evidence_id="e-1",
        affected_behavior={"text": "The response message interface", "source_refs": ["spec.md:1"]},
        causal_steps=[{"summary": "The request does not update the message latch", "rtl_refs": ["rtl.v:1"]},
                      {"summary": "The output retains the prior message", "rtl_refs": ["rtl.v:1"], "evidence_ids": ["e-1"]}])])
    index = ReviewIndex(workspace={"name": "demo"}, source_files={},
        dut_context={"text": "Receive requests and return their messages", "source_refs": ["spec.md:1"]},
        stage_status={}, bug_order=list(bugs),
        bugs={bug_id: BugEntry(origin="reported", case_ids=[case_id]) for bug_id in bugs},
        cases={case_id: CaseEntry(replay_target=case_id, waveform_test_case_name=case_id,
                                  record_path="cases/case.json")})
    records = {"test_manifest.json": TestManifest(collection_command=["pytest"], pytest_target="tests",
                  collection_exit_code=0, collected=[case_id]),
               "replay_summary.json": ReplaySummary(baseline_id="baseline-1", outcomes={case_id: "failed"}),
               "environment_review.json": EnvironmentReview(),
               "report_reconciliation.json": {"schema": "bug_review.v9", "record_type": "reconciliation"},
               "coverage.json": CoverageRecord(metrics={})}
    for name, record in records.items():
        value = record.model_dump(mode="json", by_alias=True) if hasattr(record, "model_dump") else record
        (output / name).write_text(json.dumps(value))
    coverage = records["coverage.json"]
    return output, index, {case_id: case}, bugs, roots, coverage, waveinfo


def test_root_has_one_detail_two_phenomena_and_two_wave_links(tmp_path):
    """Root owns one canonical page; the selected preview does not inherit list order."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    validate_correlation(index, cases, bugs, roots, tmp_path, waveinfo)
    assert prepare_waveform_bundle(output, cases) == {"available": 2, "unavailable": 0}
    pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
    assert manifest["root_count"] == 1 and manifest["phenomenon_count"] == 2
    root = pages["report/roots/" + root_page("ROOT-LATCH")]
    assert root.count("class='wave-preview'") == 1
    assert "b" * 32 + ".vcd" in root
    assert "a" * 32 + ".vcd" in root
    assert root.count("<h2>") == 6
    assert "SYM-A" in root and "SYM-B" in root
    assert root.count("<svg") == 1
    assert "R_TAG=0x31" in root
    assert all(item["page"].startswith("roots/") for item in manifest["bugs"])
    for filename, content in pages.items():
        target = output.parent / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (output.parent / "report/report_manifest.json").write_text(json.dumps(manifest))
    verify_pages(output, index, cases, bugs, roots)


@pytest.mark.parametrize("failure", ["normal", "other_case", "time", "signal", "execution", "not_reached", "primary", "other_execution_step"])
def test_invalid_relationship_or_normal_reference_cannot_confirm(tmp_path, failure):
    """Each phenomenon needs its own reached deviation with exact evidence identity."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    if failure == "normal":
        case.events[0].kind = "normal_reference"
    elif failure == "other_case":
        bugs["SYM-A"].evidence_bindings[0].case_id = "tests/other.py::test_bad"
    elif failure == "time":
        case.events[0].time = 41
    elif failure == "signal":
        case.events[0].signal_path = "TOP.other.cmsg"
    elif failure == "execution":
        case.events[0].execution_id = "unknown-invocation"
    elif failure == "not_reached":
        case.scenario_steps[0].status = "not_reached"
    elif failure == "other_execution_step":
        case.scenario_steps = [case.scenario_steps[1]]
    else:
        roots.roots[0].primary_evidence_id = "unknown-evidence"
    with pytest.raises(ReviewIssues):
        validate_correlation(index, cases, bugs, roots, tmp_path, waveinfo)


def test_missing_snapshot_preserves_claim_but_marks_delivery_incomplete(tmp_path):
    """One member's available waveform cannot cover the other member's lost snapshot."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    prepare_waveform_bundle(output, cases)
    (output.parent / ("report/waveforms/" + "a" * 32 + ".vcd")).unlink()
    pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
    assert manifest["review_status"] == "incomplete"
    assert manifest["roots"][0]["preview_status"] == "available"
    assert bugs["SYM-A"].decision.verdict == "confirmed"


def test_bus_decode_preserves_precision_noncontiguous_bits_and_unknowns():
    """256-bit values and DEC R_TAG are decoded without Number coercion or X/Z loss."""
    field = BusField(name="R_TAG", parts=[(18, 18), (8, 0)], source_ref="spec.md:1")
    bits = f"{(1 << 255) | (1 << 18) | 0x33:0256b}"
    assert decode_fields(bits, [field])[0]["value"] == "0x233"
    unknown = bits[:-1] + "z"
    assert decode_fields(unknown, [field])[0]["bits"].endswith("z")
    with pytest.raises(ValueError):
        decode_fields("0", [field])
    with pytest.raises(ValidationError):
        BusField(name="overlap", parts=[(8, 0), (2, 0)], source_ref="spec.md:1")
    enum = BusField(name="RAID_CMD", parts=[(1, 0)], source_ref="spec.md:1", enum_values={"0": "DATA"})
    assert decode_fields("10", [enum])[0]["enum_status"] == "unknown"
    assert decode_fields("xz", [enum])[0]["value"] == "0bxz"


def test_snapshot_rejects_wrong_observed_value(tmp_path):
    """Preview reads the actual snapshot and rejects an invented raw event value."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    event = case.events[0].model_copy(deep=True)
    event.raw_value = "0" * 96
    with pytest.raises(ValueError, match="raw_value"):
        snapshot_preview(tmp_path / ("verification_review/run/unity_test/" + "a" * 32 + ".vcd"), case.waveform, event)


def test_report_rerender_reuses_verified_readonly_snapshots(tmp_path):
    """An immutable archived waveform must remain usable on repeated rendering."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    prepare_waveform_bundle(output, cases)
    snapshots = list((output.parent / "report/waveforms").glob("*.vcd"))
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in snapshots}
    for path in snapshots:
        path.chmod(0o444)
    result = prepare_waveform_bundle(output, cases)
    assert result["available"] == 2
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in snapshots} == before


def test_dense_preview_focuses_event_without_changing_signed_viewer_window(tmp_path):
    """A long real trace stays usable without dropping edges or editing its link."""
    path = tmp_path / "dense.vcd"
    path.write_text("$timescale 1ps $end\n$scope module TOP $end\n"
                    "$var wire 1 ! clk $end\n$upscope $end\n$enddefinitions $end\n"
                    + "".join(f"#{tick}\n{tick % 2}!\n" for tick in range(1025)))
    payload = {"v": 2, "test_dir": "verification_review/run/unity_test", "test_case": "dense",
               "start": "0", "end": "1024", "cursor": "0", "signals": ["TOP.clk"]}
    wave = SimpleNamespace(viewer_url=build_waveform_viewer_url(payload))
    original_url = wave.viewer_url
    event = SimpleNamespace(time=512, raw_value="0", signal_path="TOP.clk",
                            description="checked clock event", fields=[])
    preview = snapshot_preview(path, wave, event)
    assert (preview["start"], preview["end"]) == (448, 576)
    assert preview["signal_paths"] == ["TOP.clk"]
    assert "stroke-dasharray" in preview["svg"]
    assert wave.viewer_url == original_url
    event.time = 1025
    with pytest.raises(ValueError, match="outside the signed window"):
        snapshot_preview(path, wave, event)


def test_fst_export_preserves_the_measured_event_and_download_identity(tmp_path):
    """Real GTKWave conversion preserves scope, width, timescale and event values."""
    converter = shutil.which("vcd2fst")
    if not converter or not shutil.which("fst2vcd"):
        pytest.skip("GTKWave converters are required for this real-format check")
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    receipt = waveinfo.get_analysis_receipt(case.waveform.receipt_id)
    original = tmp_path / receipt["result"]["waveform_selection"]["waveform_file"]
    fst = original.with_suffix(".fst")
    result = subprocess.run([converter, "-v", str(original), "-f", str(fst)], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    selection = receipt["result"]["waveform_selection"]
    selection.update(waveform_file=str(fst.relative_to(tmp_path)), size_bytes=fst.stat().st_size,
                     modified_time_ns=fst.stat().st_mtime_ns)
    store = tmp_path / ".ucagent/waveinfo_receipts.json"
    receipts = [waveinfo.get_analysis_receipt(wave.receipt_id) for wave in [case.waveform, *case.additional_waveforms]]
    store.write_text(json.dumps({"receipts": receipts}))
    prepare_waveform_bundle(output, cases)
    exported = json.loads((output.parent / "report/waveform_exports.json").read_text())["exports"][case.waveform.receipt_id]
    assert exported["status"] == "available", exported
    assert exported["timescale"] == "10^-12 s"
    assert (output.parent / "report" / exported["file"]).is_file()
    pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
    assert manifest["waveform_exports"][case.waveform.receipt_id]["source_sha256"] == exported["source_sha256"]
    assert "downloads/" + case.waveform.receipt_id + ".vcd" in pages["report/roots/" + root_page("ROOT-LATCH")]


def test_receipt_selection_preserves_other_executions_and_reviewed_notes(tmp_path):
    """Switching the case's primary receipt retains both observations without duplicates."""
    import ucagent
    from ucagent.util.config import REQUIRED_RUNTIME_BOOL_OPTIONS
    from bug_review.tools import ApplyReceiptToCase

    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    runtime = tmp_path / ".ucagent/runtime_config.json"
    runtime.write_text(json.dumps({"schema_version": 1, "DUT": "demo", "OUT": "verification_review/analysis",
        "test_output_dir": "verification_review/run/unity_test", "current_test_report": ".ucagent/current_test_report.json",
        "ucagent_python_path": str(Path(ucagent.__file__).resolve().parent.parent),
        "runtime_options": {key: False for key in REQUIRED_RUNTIME_BOOL_OPTIONS}}))
    (output / "cases").mkdir()
    (output / "review_index.json").write_text(json.dumps(index.model_dump(mode="json", by_alias=True)))
    path = output / "cases/case.json"
    path.write_text(json.dumps(case.model_dump(mode="json", by_alias=True)))
    tool = ApplyReceiptToCase(workspace=str(tmp_path), output_dir="verification_review/analysis")
    tool.waveinfo = waveinfo
    result = tool._run(case.case_id, "b" * 32)
    assert result["success"], result
    selected = CaseRecord.model_validate(json.loads(path.read_text()))
    assert selected.waveform.receipt_id == "b" * 32
    assert selected.waveform.observed_behavior == "wrong message"
    assert selected.waveform.conclusion == "dut_bug"
    assert [wave.receipt_id for wave in selected.additional_waveforms] == ["a" * 32]
    assert len(selected.events) == 2
    assert tool._run(case.case_id, "b" * 32)["success"]
    assert len(CaseRecord.model_validate(json.loads(path.read_text())).additional_waveforms) == 1


@pytest.mark.parametrize("failure", ["dut_missing", "dut_source", "mixed_context", "root_source", "empty_chain", "non_rtl", "foreign_event", "missing_signals", "invented_name", "unsigned_path"])
def test_sourced_narrative_rejects_invalid_provenance(tmp_path, failure):
    """LLM explanations cannot replace source lines, exact RTL names or root-local events."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    root = roots.roots[0]
    signal = bugs["SYM-A"].phenomenon.signal_explanations[0]
    if failure == "dut_missing":
        index.dut_context.text = ""
        index.dut_context.source_refs = []
    elif failure == "dut_source":
        index.dut_context.source_refs = ["missing.md:1"]
    elif failure == "mixed_context":
        index.dut_context.unavailable_reason = "No documentation"
    elif failure == "root_source":
        root.affected_behavior.source_refs = []
    elif failure == "empty_chain":
        root.causal_steps = []
    elif failure == "non_rtl":
        root.causal_steps[0].rtl_refs = ["spec.md:1"]
    elif failure == "foreign_event":
        root.bug_ids = ["SYM-A"]
        root.causal_steps[0].evidence_ids = ["e-1"]
    elif failure == "missing_signals":
        bugs["SYM-A"].phenomenon.signal_explanations = []
    elif failure == "invented_name":
        signal.rtl_name = "decoded_message_tag"
    else:
        signal.signal_path = "TOP.other.cmsg[95:0]"
    with pytest.raises(ReviewIssues):
        validate_correlation(index, cases, bugs, roots, tmp_path, waveinfo)


def test_unavailable_dut_context_is_an_explicit_delivery_gap(tmp_path):
    """Unknown documentation keeps signed DUT findings intact while marking incomplete delivery."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    index.dut_context.text = ""
    index.dut_context.source_refs = []
    index.dut_context.unavailable_reason = "The uploaded baseline omits module and interface documentation."
    validate_correlation(index, cases, bugs, roots, tmp_path, waveinfo)
    prepare_waveform_bundle(output, cases)
    pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
    assert manifest["review_status"] == "incomplete"
    assert manifest["roots"][0]["context_status"] == "incomplete"
    assert manifest["roots"][0]["evidence_status"] == "complete"
    assert {bug.decision.verdict for bug in bugs.values()} == {"confirmed"}
    assert index.dut_context.unavailable_reason in pages["report/roots/" + root_page("ROOT-LATCH")]


class DefaultText(HTMLParser):
    """Collect rendered text while excluding collapsed details and nonvisual scripts."""

    def __init__(self):
        """Initialize HTML parser state for the default visible document."""
        super().__init__()
        self.hidden = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        """Track collapsed groups and script/style payloads."""
        if tag in {"details", "script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        """Restore visible text collection after a hidden group."""
        if tag in {"details", "script", "style"}:
            self.hidden -= 1

    def handle_data(self, data):
        """Keep only text that belongs to the initially visible page."""
        if not self.hidden:
            self.text.append(data)


def test_root_default_focuses_scenario_and_rtl_with_deduplicated_downloads(tmp_path):
    """Routine case operations and receipts stay collapsed, while RTL and concise wave links remain visible."""
    output, index, cases, bugs, roots, coverage, waveinfo = example(tmp_path)
    case = next(iter(cases.values()))
    case.scenario_steps[0].action = "RESET_AND_CONFIGURE_EXAMPLE"
    bugs["SYM-A"].evidence_bindings.append(EvidenceBinding(evidence_id="support-same-snapshot",
        case_id=case.case_id, event_id="message-0", role="corroborating", reason="Same signed observation"))
    prepare_waveform_bundle(output, cases)
    pages, manifest = render_pages(output, index, cases, bugs, roots, coverage)
    document = pages["report/roots/" + root_page("ROOT-LATCH")]
    visible = DefaultText()
    visible.feed(document)
    text = " ".join(visible.text)
    assert "RESET_AND_CONFIGURE_EXAMPLE" not in text
    assert "a" * 32 not in text
    assert "The request does not update the message latch" in text
    assert "Receive requests and return their messages" in text
    assert "phenomenon 0: stale R_TAG" not in text
    assert document.count("class='original-report'") == 1
    assert document.count("download>") == 4  # Original and VCD once per receipt.
    assert all(f"data-section='{section}'" in document for section in ["dut", "goal", "scenario", "rtl"])
    assert manifest["detail_layout"] == "scenario_rtl.v1"
    assert "RTL ·" in document


def test_preview_prioritizes_signed_key_signals_over_clock(tmp_path):
    """Thumbnail uses checked and relevant signed signals without altering the full signed viewer payload."""
    path = tmp_path / "focused.vcd"
    names = ["clock", "unrelated1", "unrelated2", "unrelated3", "unrelated4", "enable", "state", "valid"]
    declarations = "".join(f"$var wire 1 {chr(33+i)} {name} $end\n" for i, name in enumerate(names))
    values = "".join(f"0{chr(33+i)}\n" for i in range(len(names)))
    path.write_text("$timescale 1ps $end\n$scope module TOP $end\n" + declarations
                    + "$upscope $end\n$enddefinitions $end\n#0\n" + values + "#10\n1(\n")
    payload = {"v": 2, "test_dir": "verification_review/run/unity_test", "test_case": "focused",
               "start": "0", "end": "10", "cursor": "0", "signals": ["TOP." + name for name in names]}
    wave = SimpleNamespace(viewer_url=build_waveform_viewer_url(payload),
        signal_groups={"key_signals": ["TOP.enable", "TOP.state", "TOP.unsigned"], "protocol": ["TOP.valid"]})
    original_url = wave.viewer_url
    event = SimpleNamespace(time=10, raw_value="1", signal_path="TOP.valid", description="valid rises", fields=[])
    preview = snapshot_preview(path, wave, event)
    assert preview["signal_paths"][:3] == ["TOP.valid", "TOP.enable", "TOP.state"]
    assert "TOP.unsigned" not in preview["signal_paths"]
    assert len(preview["signal_paths"]) == 6
    assert wave.viewer_url == original_url
