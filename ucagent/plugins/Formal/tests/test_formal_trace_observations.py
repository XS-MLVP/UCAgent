"""Original trace observation contracts independent of DUT names and arithmetic."""

import hashlib
import json
from pathlib import Path

import pytest

from formal.evidence import original_inputs, trace_observations, observation_text
from formal.execution import property_evidence
from formal.skills.lib.formal_tools import auto_scaffold_bug_entries, validate_original_observations, generate_bug_report_doc
from formal.skills.lib.models import AnalysisData, AnalysisEntry, BugEntry, FormalRecords, RunResults


def write_trace(path):
    """Produce wide, nested and unknown signals in a standard multi-sample trace."""
    path.write_text("""$timescale 10 ps $end
$scope module PacketShell $end
$var wire 80 ! payload [79:0] $end
$var wire 4 \" observed [3:0] $end
$var wire 1 # ready $end
$scope module inner $end
$var wire 1 $ internal $end
$upscope $end
$upscope $end
$scope module AuxShell $end
$var wire 1 % error $end
$upscope $end
$enddefinitions $end
#0
b1 !
b0000 \"
0#
1$
0%
#25
b10000000000000000000000000000000000000000000000000000000000000000000000000000001 !
b1xz0 \"
1#
1%
#30
""", encoding="utf-8")


def test_generic_top_scope_last_sample_preserves_wide_values_and_xz(tmp_path):
    """No clock, signal-name convention, or 64-bit conversion limit is assumed."""
    pytest.importorskip("wavekit")
    path = tmp_path / "original.vcd"
    write_trace(path)
    result = trace_observations(path)
    assert result["status"] == "available"
    assert result["sampled_time"] == 30
    assert result["time_unit"] == "ps" and result["time_magnitude"] == "10"
    assert result["sample_kind"] == "last_recorded_sample_not_failure_cycle"
    rows = {row["name"]: row for row in result["signals"]}
    assert "PacketShell.inner.internal" not in rows
    wide = rows["PacketShell.payload[79:0]"]
    assert wide["width"] == 80 and int(wide["value"], 16) > 2**64
    unknown = rows['PacketShell.observed[3:0]']
    assert unknown["value"] is None
    assert unknown["bits"] == "1xz0"
    assert unknown["unknown_mask"] == "0x4" and unknown["z_mask"] == "0x2"
    assert rows["AuxShell.error"]["value"] == "0x1"
    limited = trace_observations(path, max_signals=1)
    assert limited["truncated"] and limited["omitted_signals"] == 3


def test_no_trace_or_parser_failure_does_not_invent_values(tmp_path, monkeypatch):
    """Unavailability has an explicit task recovery action, not made-up signal zeros."""
    assert trace_observations(tmp_path / "absent.vcd")["signals"] == []
    import wavekit
    path = tmp_path / "broken.vcd"
    path.write_text("broken trace")
    def fail(*args):
        """Simulate provider failure without leaking implementation errors into task data."""
        raise RuntimeError("native dependency private implementation error")
    monkeypatch.setattr(wavekit, "VcdReader", fail)
    result = trace_observations(path)
    assert result["status"] == "unavailable" and result["signals"] == []
    assert "private implementation" not in json.dumps(result)
    assert "operator" in result["next_action"]


def test_initialization_is_bounded_and_never_claims_full_waveform(tmp_path):
    """More than 64 original inputs explicitly marks the projection as partial."""
    path = tmp_path / "original.tb.v"
    path.write_text("// initialization\ninitial begin\n" + "\n".join(f"input_{index} <= 1'b1;" for index in range(70)) + "\nend\n")
    result = original_inputs(path)
    assert len(result["initial_values"]) == 64
    assert result["initial_values_observed_count"] == 70
    assert result["initial_values_truncated"] is True
    assert result["initial_values_only"] is True


def test_trace_hash_is_current_machine_provenance(tmp_path):
    """A changed stored observation cannot retain an earlier evidence reference."""
    name = "u_checker.A_REQUIRED"
    run = tmp_path / "run"
    console = run / "attempts" / "000001" / "console.log"
    console.parent.mkdir(parents=True)
    console.write_text(f"UCAGENT_RESULT_BEGIN\n 1 {name} : Fail (1)\tpdrx\t0.01\t(-)\nUCAGENT_RESULT_END\n")
    directory = console.parent / "avis" / name
    directory.mkdir(parents=True)
    witness = directory / (name + ".tb.v")
    witness.write_text("// initialization\ninitial begin\nenable <= 1'b1;\nend\n")
    trace = directory / (name + ".vcd")
    write_trace(trace)
    attempt = {"console": str(console.relative_to(run)), "console_hash": hashlib.sha256(console.read_bytes()).hexdigest(),
               "witness_hash": hashlib.sha256(witness.read_bytes()).hexdigest(), "trace_hash": hashlib.sha256(trace.read_bytes()).hexdigest(), "returncode": 0}
    state = {"workspace": str(tmp_path), "run_id": "run-1", "fingerprint": "original-inputs"}
    item = {"kind": "assert", "result": "FALSIFIED", "raw_status": "Fail (1)", "attempts": [attempt]}
    evidence = property_evidence(run, state, name, item)
    assert evidence["evidence_ref"]["trace_sha256"] == attempt["trace_hash"]
    assert evidence["trace_observations"]["status"] == "available"
    trace.write_text(trace.read_text() + "#31\n")
    with pytest.raises(ValueError, match="trace changed"):
        property_evidence(run, state, name, item)


def test_bug_scaffold_overwrites_authored_observations_with_original_machine_values(tmp_path):
    """Expected semantics remain authored, while trigger/actual are deterministic facts."""
    name = "branch.A_REQUIRED"
    evidence = {"result": "FALSIFIED", "raw_status": "Fail (2)", "evidence_ref": {"property": name},
                "initial_values": [{"signal": "request", "width": 1, "value": "0x1"}],
                "trace_observations": {"status": "available", "sampled_time": 20, "time_unit": "ns", "time_magnitude": "1",
                                       "signals": [{"name": "Shell.observed", "width": 1, "value": "0x0"}]}}
    records = FormalRecords(dut="ControlBlock", run_results=RunResults(timestamp="now", log_hash="digest", stats={},
        failing_properties=[name], tt_properties=[], property_evidence={name: evidence}),
        analysis=AnalysisData(fa_entries=[AnalysisEntry(id="FA-001", prop_name=name, resolution="RTL_BUG")]),
        bugs=[BugEntry(id="BG-001", property=name, trigger="invented inputs", actual="invented output", expected="Specification requires acknowledgement")])
    assert auto_scaffold_bug_entries(records)
    bug = records.bugs[0]
    assert "request=0x1" in bug.trigger and "invented" not in bug.trigger
    assert "Shell.observed=0x0" in bug.actual and "not asserted to be the failure cycle" in bug.actual
    assert bug.expected == "Specification requires acknowledgement"
    assert not auto_scaffold_bug_entries(records)
    validate_original_observations(records)
    target = tmp_path / "bug-report.md"
    target.write_text("previous accepted report")
    bug.actual = "A new authored signal value"
    with pytest.raises(ValueError, match="Machine observations changed"):
        generate_bug_report_doc(records, str(target))
    assert target.read_text() == "previous accepted report"
    auto_scaffold_bug_entries(records)
    evidence["trace_observations"] = {"status": "unavailable"}
    records.run_results.property_evidence[name] = evidence
    auto_scaffold_bug_entries(records)
    assert "no values are inferred" in bug.actual
