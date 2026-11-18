"""Exercise bounded FormalMC scheduling using isolated processes and real report shapes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import pytest

from formal.execution import (
    ACTIVE_RUNS,
    ExecutionPolicy,
    FormalExecution,
    choose_next,
    parse_properties,
    process_identity,
    group_members,
    stop_process,
)


class Config:
    """Supply the resolved runtime policy without constructing an agent."""

    def __init__(self, values=None):
        """Store a caller-owned policy mapping."""
        self.values = {} if values is None else values

    def get_value(self, name, default=None):
        """Return only the canonical Formal execution configuration."""
        return self.values if name == "runtime_options.formal_execution" else default


def wait_for(execution, predicate, timeout=15, **batch):
    """Wait within a bounded test deadline while the independent controller runs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = execution.status(**batch)
        if predicate(status):
            return status
        time.sleep(0.05)
    pytest.fail(f"Formal controller did not reach expected state: {status}")


def state_for(workspace, status):
    """Read the exact machine artifact returned by the public execution facade."""
    return json.loads((workspace / status["state_artifact"]).read_text())


@pytest.fixture
def execution_factory(tmp_path, monkeypatch):
    """Build genuine subprocess fixtures and always cancel their owned workers."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "FormalMC"
    fake.write_text(
        f"#!{sys.executable}\n"
        + r'''"""Emit deterministic FormalMC-like output for scheduler integration tests."""
import json
import os
from pathlib import Path
import re
import sys
import time

script = Path(sys.argv[sys.argv.index('-f') + 1]).read_text()
properties = json.loads(os.environ['FAKE_FORMAL_PROPERTIES'])

def rows(kind=None, target=None, status='NotRun(-1)'):
    """Render actual 2025.12 tab-separated property table rows."""
    for index, prop in enumerate(properties, 1):
        if kind is not None and prop['kind'] != kind:
            continue
        value = status if prop['name'] == target else 'NotRun(-1)'
        print(f" {index} {prop['name']} : {value}\tpdrx\t0.01\t(-)", flush=True)

match = re.search(r'^prove\s+"([^"\n]+)"', script, re.M)
if "UCAGENT_DIAG_BEGIN_" in script:
    for line in script.splitlines():
        if line.startswith("puts UCAGENT_DIAG_"):
            print(line.removeprefix("puts "), flush=True)
        elif line.startswith(("clk_ana", "rst_ana", "show_cons", "check_overcons", "prop_sanity", "fanin")):
            print(f"Native observation for {line}", flush=True)
    sys.exit(0)
if not match and 'file rename -force request.tcl active.tcl' not in script:
    if os.environ.get('FAKE_FORMAL_PREPARATION_ERROR'):
        print('Error: license server unavailable', flush=True)
        sys.exit(2)
    if os.environ.get('FAKE_FORMAL_COMPILE_ERROR'):
        original = Path(re.search(r'source "([^"]+)"', script).group(1))
        checker = original.with_name('DUT_checker.sv')
        lines = checker.read_text().splitlines()
        index = next(i for i, line in enumerate(lines, 1) if 'C_UCAGENT_TOOLCHAIN_SMOKE' in line or re.search(r'property\s+.*CK_READY\b', line))
        print(f'Error: {checker}({index + 1}): invalid property expression', flush=True)
        sys.exit(2)
    print('UCAGENT_ASSERT_BEGIN', flush=True)
    rows('assert')
    print('UCAGENT_ASSERT_END', flush=True)
    print('UCAGENT_COVER_BEGIN', flush=True)
    rows('cover')
    print('UCAGENT_COVER_END', flush=True)
    sys.exit(0)

def prove_script(script):
    """Simulate one exact tool job and publish its test outputs."""
    match = re.search(r'^prove\s+"([^"\n]+)"', script, re.M)
    name = match.group(1)
    budget = int(re.search(r'set_opt -timeout\s+(\d+)s', script).group(1))
    print('UCAGENT_PROOF_STARTED', flush=True)
    if os.environ.get("FAKE_FORMAL_LICENSE_WAIT"):
        print("Info: waiting for license(-4)...", flush=True)
        time.sleep(0.6)
    if 'CRASH' in name:
        time.sleep(0.15)
        print('Error: proof worker failed', flush=True)
        sys.exit(2)
    if 'SLOW' in name:
        time.sleep(budget)
        result = 'Undet (42)'
    else:
        time.sleep(0.15)
        result = 'TrivF (0)' if 'STATIC_FALSE' in name else 'Unsupported' if 'UNSUPPORTED' in name else 'Fail (2)' if 'WITNESS' in name else 'Pass'
    if 'WITNESS' in name:
        work = Path(sys.argv[sys.argv.index('-work_dir') + 1])
        witness = work / 'avis' / name / (name + '.tb.v')
        witness.parent.mkdir(parents=True, exist_ok=True)
        witness.write_text("// initialization\ninitial begin\ninput_data <= 8'b10100101;\nvalid <= 1'b1;\nend\n")
        if os.environ.get("FAKE_FORMAL_REPLAY"):
            trace = witness.with_name(name + ".vcd")
            trace.write_text(
                "$timescale 1 ns $end\n$scope module DUT_wrapper $end\n"
                "$var wire 1 ! clk $end\n$var wire 1 # req $end\n"
                "$var wire 1 $ ack $end\n$var wire 1 % rst_n $end\n"
                "$upscope $end\n$enddefinitions $end\n"
                "#0\n0!\n1#\n0$\n1%\n#5\n1!\n#10\n0!\n#15\n1!\n"
            )
    print('UCAGENT_PROOF_FINISHED', flush=True)
    print('UCAGENT_RESULT_BEGIN', flush=True)
    rows(target=name, status=result)
    print('UCAGENT_RESULT_END', flush=True)

if 'file rename -force request.tcl active.tcl' in script:
    work = Path(sys.argv[sys.argv.index('-work_dir') + 1])
    request = work / 'request.tcl'
    active = work / 'active.tcl'
    while True:
        if not request.is_file():
            time.sleep(0.015)
            continue
        request.replace(active)
        job = active.read_text()
        if job.strip() == 'exit':
            sys.exit(0)
        prove_script(job)
        marker = re.search(r'puts \[list UCAGENT_SESSION_DONE (\d+)\]', job)
        print(f'UCAGENT_SESSION_DONE {marker[1]}', flush=True)
else:
    prove_script(script)
''',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    made = []

    def make(names=("A_FAST",), **overrides):
        """Create one independent DUT workspace and configured execution facade."""
        workspace = tmp_path / f"ws-{len(made)}"
        dut = workspace / "DUT"
        dut.mkdir(parents=True)
        (dut / "dut.sv").write_text("module DUT; endmodule\n")
        tests = workspace / "output" / "tests"
        tests.mkdir(parents=True)
        (tests / "DUT_checker.sv").write_text("// checker\n")
        (tests / "DUT_wrapper.sv").write_text("// wrapper\n")
        (tests / "DUT_formal.tcl").write_text(
            "# setup\n# UCAGENT_PROOF_BEGIN\nprove\nshow_prop -summary\nexit\n"
        )
        props = [{"name": name, "kind": "cover" if name.startswith(("reach", "u_checker.C_CK_")) else "assert"} for name in names]
        monkeypatch.setenv("FAKE_FORMAL_PROPERTIES", json.dumps(props))
        policy = dict(first_pass_budget_s=1, analysis_threshold_s=2,
                      max_active_workers=1, slow_queue_max_workers=1,
                      setup_timeout_s=3, stop_grace_s=1,
                      max_review_rounds=2, property_cumulative_budget_s=8)
        policy.update(overrides)
        execution = FormalExecution(str(workspace), "output", "DUT", Config(policy))
        made.append((execution, workspace))
        return execution, workspace

    yield make
    for execution, workspace in made:
        if not (workspace / "output" / "formal_runs" / "current.json").is_file():
            continue
        execution.cancel()
        current = execution.status()
        if current.get("status") in ACTIVE_RUNS:
            current = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
        if current.get("state_artifact"):
            state = state_for(workspace, current)
            assert not any(attempt.get("running") for item in state["properties"].values() for attempt in item["attempts"])


def test_policy_defaults_and_invalid_limits():
    """Reject booleans, unknown keys, incompatible budgets, and excess slow slots."""
    assert ExecutionPolicy.from_cfg(Config()).first_pass_budget_s == 300
    assert ExecutionPolicy.from_cfg(Config()).analysis_threshold_s == 1200
    invalid = [None, [], {"first_pass_budget_s": True}, {"first_pass_budget_s": 0},
               {"first_pass_budget_s": 1.5}, {"unknown": 1},
               {"analysis_threshold_s": 300}, {"slow_queue_max_workers": 3},
               {"property_cumulative_budget_s": 1199}]
    for values in invalid:
        with pytest.raises(ValueError):
            ExecutionPolicy.from_cfg(Config(values if values is not None else "invalid"))


def test_scheduler_prefers_untouched_targets_and_bounds_slow_lane():
    """A pending first turn outranks slow retries and reserved occupancy is bounded."""
    policy = ExecutionPolicy(max_active_workers=3, slow_queue_max_workers=1)
    properties = {"slow": {"state": "QUEUED_SLOW"}, "fast": {"state": "QUEUED_FAST"}}
    assert choose_next(properties, [], policy) == "fast"
    properties["fast"]["state"] = "RUNNING_FAST"
    assert choose_next(properties, [{"lane": "fast"}, {"lane": "slow"}], policy) is None
    assert choose_next(properties, [{"lane": "fast"}], policy) == "slow"
    assert choose_next(properties, [{"lane": "slow"}], policy) == "slow"


def test_real_table_parser_keeps_hierarchy_and_unproved_states():
    """Read genuine FormalMC spellings and keep unknown status distinct from success."""
    text = """UCAGENT_ASSERT_BEGIN
  1 u1.A_CHECK : Fail (2)\tpdrx\t0.00\t(-)
  2 u2.A_CHECK : NotRun(-1)\tunknown\t0.00\t(-)
  3 A_SLOW : Undet (708)\tbmc\t1.01\t(-)
UCAGENT_ASSERT_END
UCAGENT_COVER_BEGIN
  4 reach_without_prefix : Pass (3)\tpdrx\t0.01\t(-)
UCAGENT_COVER_END
"""
    parsed = parse_properties(text)
    assert parsed["u1.A_CHECK"]["result"] == "FALSIFIED"
    assert parsed["u2.A_CHECK"]["result"] == "UNPROVEN"
    assert parsed["A_SLOW"]["result"] == "UNPROVEN"
    assert parsed["A_SLOW"]["solver_reported_time_s"] == 1.01
    assert parsed["reach_without_prefix"]["result"] == "COVER_REACHED"


def test_static_false_results_keep_remaining_properties_running(execution_factory):
    """Static constant failures are real final results, not controller exceptions."""
    execution, workspace = execution_factory(("lane.STATIC_FALSE", "other.A_FAST", "reach_STATIC_FALSE"))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert done["status"] == "COMPLETED"
    assert done["counts"] == {"TRIVIALLY_FALSE": 1, "PROVEN": 1, "COVER_UNREACHABLE": 1}
    assert execution.check()[0] is True
    reference = execution.evidence(["lane.STATIC_FALSE"])["items"][0]
    assert reference["raw_status"] == "TrivF (0)"
    assert reference["witness_artifact"] is None


def test_unknown_status_isolated_without_changing_goals(execution_factory):
    """Unsupported engine output stops only its target and asks for operator repair."""
    execution, workspace = execution_factory(("first.UNSUPPORTED", "second.A_FAST"))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert done["status"] == "NEEDS_OPERATOR"
    state = state_for(workspace, done)
    assert state["properties"]["first.UNSUPPORTED"]["error_code"] == "formal_tool_result_unsupported"
    assert state["properties"]["second.A_FAST"]["result"] == "PROVEN"
    assert state["properties"]["first.UNSUPPORTED"]["attempts"][0]["ended_at"]
    assert execution.check()[0] is False
    assert "Preserve the original properties" in done["next_action"]
    with pytest.raises(ValueError, match="in REVIEW"):
        execution.review(["first.UNSUPPORTED"], "defer", "Parser does not support output", "Fix tool adapter")


def test_witness_export_is_exact_current_and_tamper_checked(execution_factory):
    """Evidence returns original numeric inputs and binds exact hierarchical identity."""
    execution, workspace = execution_factory(("nested.WITNESS",))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    evidence = execution.evidence(["nested.WITNESS"])["items"][0]
    assert evidence["evidence_ref"]["property"] == "nested.WITNESS"
    assert evidence["initial_values"] == [{"signal": "input_data", "width": 8, "value": "0xa5", "has_unknown": False},
                                           {"signal": "valid", "width": 1, "value": "0x1", "has_unknown": False}]
    with pytest.raises(ValueError, match="Exact property"):
        execution.evidence(["WITNESS"])
    with pytest.raises(ValueError, match="unique"):
        execution.evidence([])
    (workspace / evidence["witness_artifact"]).write_text("modified trace")
    with pytest.raises(ValueError, match="witness changed"):
        execution.evidence(["nested.WITNESS"])


def test_run_is_idempotent_and_preserves_cover_type(execution_factory):
    """Repeated submission does not duplicate a run and typed cover success survives."""
    execution, workspace = execution_factory(("u1.A_FAST", "reach_without_prefix"))
    first = execution.run()
    assert execution.run()["run_id"] == first["run_id"]
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert done["status"] == "COMPLETED"
    assert done["proof_complete"] is True
    assert done["counts"] == {"PROVEN": 1, "COVER_REACHED": 1}
    assert execution.run()["run_id"] == first["run_id"]
    state = state_for(workspace, done)
    assert all(len(item["attempts"]) == 1 for item in state["properties"].values())


def test_native_diagnostics_use_frozen_inputs_and_preserve_proof(execution_factory):
    """Bound native commands to a stored run and reject a modified snapshot."""
    from formal.tools import AnalyzeFormal

    execution, workspace = execution_factory(("A_FAST",))
    submitted = execution.run()
    done = wait_for(execution, lambda item: item["status"] == "COMPLETED")
    tool = AnalyzeFormal(workspace=str(workspace), output_dir="output", dut="DUT",
                         cfg=Config(vars(execution.policy)))
    before = (workspace / done["state_artifact"]).read_bytes()
    request = {"run_id": submitted["run_id"]}
    env = tool.invoke({**request, "mode": "environment"})
    assert env["status"] == "completed", env
    assert env["observations"]["reset"]["lines"] == ["Native observation for rst_ana"]
    assert (workspace / env["log"]).is_file()
    depth = tool.invoke({**request, "mode": "overconstraint", "depth": 7})
    assert depth["search_depth"] == 7
    assert depth["observations"]["overconstraint"]["lines"] == ["Native observation for check_overcons -depth 7"]
    for mode, command in (("sanity", 'prop_sanity -vac2 "A_FAST"'), ("fanin", 'fanin -assertion "A_FAST" -list -disp')):
        result = tool.invoke({**request, "mode": mode, "property_name": "A_FAST"})
        assert result["observations"][mode]["command"] == command
    with pytest.raises(ValueError, match="exact Assert/Cover name"):
        tool.invoke({**request, "mode": "fanin", "property_name": "A_*"})
    assert (workspace / done["state_artifact"]).read_bytes() == before
    setup = (workspace / done["state_artifact"]).parent / "inputs" / "output" / "tests" / "setup.tcl"
    setup.write_text("exit\n")
    with pytest.raises(ValueError, match="does not match the input snapshot"):
        tool.invoke({**request, "mode": "environment"})


def test_fast_assertions_share_only_a_bounded_session_and_keep_separate_receipts(execution_factory):
    """A timeout leaves a fresh slow turn and a combined session preserves distinct evidence."""
    execution, workspace = execution_factory(("A_FAST", "A_WITNESS", "A_SLOW"), session_max_properties=2)
    run = execution.run(["A_FAST", "A_WITNESS", "A_SLOW"])
    batch = {"scope": "selected", "run_id": run["run_id"]}
    finished = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS, **batch)
    assert finished["status"] == "AWAITING_REVIEW", finished
    props = state_for(workspace, finished)["properties"]
    fast, witness = (props[name]["attempts"][0] for name in ("A_FAST", "A_WITNESS"))
    assert fast["pid"] == witness["pid"]
    assert fast["console"] != witness["console"]
    assert not any("session" in attempt for attempt in props["A_SLOW"]["attempts"])
    assert [attempt["lane"] for attempt in props["A_SLOW"]["attempts"]] == ["fast", "slow"]
    evidence = execution.evidence(["A_FAST", "A_WITNESS"], **batch)["items"]
    assert [(item["result"], bool(item["witness_sha256"])) for item in evidence] == [("PROVEN", False), ("FALSIFIED", True)]


def test_cancel_cleans_a_running_shared_session(execution_factory):
    """Cancelling the selected scope reclaims the shared process before any later CK runs."""
    execution, workspace = execution_factory(("A_SLOW", "A_FAST"), session_max_properties=2, first_pass_budget_s=4,
                                             analysis_threshold_s=6)
    run = execution.run(["A_SLOW", "A_FAST"])
    batch = {"scope": "selected", "run_id": run["run_id"]}
    wait_for(execution, lambda item: item["states"].get("RUNNING_FAST"), **batch)
    execution.cancel(**batch)
    stopped = wait_for(execution, lambda item: item["status"] == "CANCELLED", **batch)
    props = state_for(workspace, stopped)["properties"]
    assert props["A_SLOW"]["attempts"][0]["session"]
    assert not props["A_SLOW"]["attempts"][0]["running"]
    assert not props["A_FAST"]["attempts"]


def test_replay_reproduces_old_failure_before_checking_current_body(execution_factory, monkeypatch):
    """Use the sealed witness across body edits, and reject a baseline or source change."""
    import yaml
    from formal.tools import AnalyzeFormal

    pytest.importorskip("wavekit")
    pytest.importorskip("pyslang")
    name = "u_checker.A_CK_WITNESS"
    execution, workspace = execution_factory((name,))
    monkeypatch.setenv("FAKE_FORMAL_REPLAY", "1")
    output = workspace / "output"
    (output / "tests" / "DUT_wrapper.sv").write_text("  u_checker (.clk(clk), .rst_n(rst_n), .req(req), .ack(ack));")
    ck = {"id": "CK-WITNESS", "style": "Seq", "description": "Request acknowledged",
          "sva_body": "@(posedge clk) disable iff (!rst_n) req |-> ack;"}
    records = {"dut": "DUT", "spec": {"function_groups": [{"id": "FG-REQUEST", "functions": [
        {"id": "FC-ACK", "check_points": [ck]},
    ]}]}}
    records_file = output / ".formal_records.yaml"
    records_file.write_text(yaml.safe_dump(records))
    submitted = execution.run()
    finished = wait_for(execution, lambda item: item["status"] == "COMPLETED")
    tool = AnalyzeFormal(workspace=str(workspace), output_dir="output", dut="DUT", cfg=Config(vars(execution.policy)))
    request = {"mode": "replay", "run_id": submitted["run_id"], "property_name": name}
    replayed = tool.invoke(request)
    assert replayed["status"] == "still_fails", replayed
    assert replayed["check_tick"] == "5"
    ck["sva_body"] = "@(posedge clk) disable iff (!rst_n) req |-> !ack;"
    records_file.write_text(yaml.safe_dump(records))
    changed = tool.invoke(request)
    assert changed["status"] == "triggered_no_failure_in_trace", changed
    assert changed["checked"] == 2
    assert state_for(workspace, finished)["properties"][name]["result"] == "FALSIFIED"
    ck["sva_body"] = "@(posedge clk) req |-> s_eventually ack;"
    records_file.write_text(yaml.safe_dump(records))
    assert tool.invoke(request)["status"] == "insufficient_evidence"
    (workspace / "DUT" / "dut.sv").write_text("module DUT; logic changed; endmodule\n")
    rejected = tool.invoke(request)
    assert rejected["status"] == "insufficient_evidence" and "RTL" in rejected["reason"]


def test_long_target_yields_to_fast_targets_then_needs_review(execution_factory):
    """Single-slot first-turn scheduling runs fast targets before a slow second turn."""
    execution, workspace = execution_factory(("A_SLOW", "u1.A_FAST", "u2.A_FAST"))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    state = state_for(workspace, done)
    assert done["status"] == "AWAITING_REVIEW"
    slow = state["properties"]["A_SLOW"]
    assert slow["state"] == "REVIEW"
    assert slow["result"] == "UNPROVEN"
    assert [attempt["lane"] for attempt in slow["attempts"]] == ["fast", "slow"]
    assert slow["attempts"][1]["started_at"] > max(
        state["properties"][name]["attempts"][0]["ended_at"] for name in ("u1.A_FAST", "u2.A_FAST")
    )
    assert done["counts"]["PROVEN"] == 2
    assert done["counts"]["UNPROVEN"] == 1
    assert state["checkpoints"]


def test_defer_records_gap_without_changing_proof_result(execution_factory):
    """Explicitly reviewed deferral closes disposition, never proves the assertion."""
    execution, workspace = execution_factory(("A_SLOW",))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert execution.check()[0] is False
    reviewed = execution.review(["A_SLOW"], "defer", "Needs a memory invariant", "Resume after invariant review")
    assert reviewed["proof_complete"] is False
    assert reviewed["counts"] == {"UNPROVEN": 1}
    assert reviewed["review_queue"][0]["disposition"] == "DEFERRED"
    state = state_for(workspace, reviewed)
    assert state["decisions"][0]["reason"] == "Needs a memory invariant"
    allowed, summary = execution.check()
    assert allowed is True
    assert summary["proof_complete"] is False
    assert "Proof complete: `false`" in (workspace / reviewed["report"]).read_text()


def test_review_validation_and_retry_limit(execution_factory):
    """Reject forged decisions and cap repeated execution of unchanged inputs."""
    execution, workspace = execution_factory(("A_SLOW",), max_review_rounds=1)
    execution.run()
    wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    for names, action, reason, following in [([], "defer", "why", "next"),
                                           (["A_SLOW", "A_SLOW"], "defer", "why", "next"),
                                           (["A_SLOW"], "pass", "why", "next"),
                                           (["A_SLOW"], "defer", "", "next"),
                                           (["missing"], "defer", "why", "next")]:
        with pytest.raises(ValueError):
            execution.review(names, action, reason, following)
    with pytest.raises(ValueError, match="Retry budget exhausted"):
        execution.review(["A_SLOW"], "retry", "Try again", "Inspect updated progress")


def test_crash_preserves_partial_results_and_cannot_be_deferred(execution_factory):
    """Infrastructure failure is actionable ERROR, not budget-exhausted proof debt."""
    execution, workspace = execution_factory(("A_FAST", "A_CRASH"))
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    state = state_for(workspace, done)
    assert state["properties"]["A_FAST"]["result"] == "PROVEN"
    assert state["properties"]["A_CRASH"]["state"] == "ERROR"
    assert execution.check()[0] is False
    with pytest.raises(ValueError, match="in REVIEW"):
        execution.review(["A_CRASH"], "defer", "Tool crashed", "Ask operator to repair runtime")


def test_cancel_cleans_owned_attempt_and_rejects_stale_evidence(execution_factory):
    """Cancellation cleans live attempts and changed files cannot reuse old evidence."""
    execution, workspace = execution_factory(("A_SLOW",), first_pass_budget_s=3, analysis_threshold_s=4)
    started = execution.run()
    wait_for(execution, lambda item: bool(item.get("states", {}).get("RUNNING_FAST")))
    execution.cancel()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert done["status"] == "CANCELLED"
    assert execution.check()[0] is False
    state = state_for(workspace, done)
    assert all(not attempt["running"] for item in state["properties"].values() for attempt in item["attempts"])
    (workspace / "DUT" / "dut.sv").write_text("module DUT; wire changed; endmodule\n")
    assert execution.status()["current_inputs"] is False
    with pytest.raises(ValueError, match="current inputs"):
        execution.review(["A_SLOW"], "retry", "Inputs changed", "Run current inputs")
    assert execution.run()["run_id"] != started["run_id"]


def test_active_input_revision_requires_cancel(execution_factory):
    """Changing current source does not implicitly terminate immutable active work."""
    execution, workspace = execution_factory(("A_SLOW",), first_pass_budget_s=3, analysis_threshold_s=4)
    execution.run()
    wait_for(execution, lambda item: bool(item.get("states", {}).get("RUNNING_FAST")))
    (workspace / "DUT" / "dut.sv").write_text("module DUT; wire changed; endmodule\n")
    with pytest.raises(ValueError, match="still running"):
        execution.run()


def test_paths_reject_escape_and_input_symlinks(execution_factory, tmp_path):
    """Reject workspace traversal and linked source files before launching a child."""
    execution, workspace = execution_factory()
    outside = tmp_path / "external.sv"
    outside.write_text("module external; endmodule\n")
    (workspace / "DUT" / "linked.sv").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink|outside"):
        execution.run()
    escaped = FormalExecution(str(workspace), "../outside", "DUT", Config())
    with pytest.raises(ValueError):
        escaped.run()
    protected = FormalExecution(str(workspace), "output", "DUT", Config(), un_write_dirs=["output/"])
    with pytest.raises(ValueError):
        protected.run()


def test_managed_root_symlink_is_rejected(execution_factory, tmp_path):
    """Do not allow managed artifact roots to redirect writes outside their location."""
    execution, workspace = execution_factory()
    external = tmp_path / "external-runs"
    external.mkdir()
    (workspace / "output" / "formal_runs").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        execution.run()


def test_status_can_wait_for_meaningful_progress(execution_factory):
    """The tool can wait on the controller instead of requiring rapid agent polling."""
    execution, workspace = execution_factory(("A_SLOW",))
    execution.run()
    wait_for(execution, lambda item: item["status"] == "RUNNING")
    waited = execution.status(wait_s=3)
    assert waited["checkpoint_total"] > 0 or waited["status"] not in ACTIVE_RUNS
    with pytest.raises(ValueError, match="wait_s"):
        execution.status(wait_s=True)


def test_recorded_descendant_is_cleaned_after_group_leader_exits():
    """Recovery recognizes a recorded child without trusting a recycled group number."""
    launcher = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(p.pid,flush=True); time.sleep(0.5)"],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    identity = process_identity(launcher.pid)
    child_pid = int(launcher.stdout.readline())
    child_identity = process_identity(child_pid)
    members = group_members(launcher.pid)
    try:
        launcher.wait(timeout=3)
        stop_process(launcher.pid, identity, 0.1, members)
        deadline = time.monotonic() + 2
        while process_identity(child_pid) == child_identity and time.monotonic() < deadline:
            time.sleep(0.02)
        assert process_identity(child_pid) != child_identity
    finally:
        if process_identity(child_pid) == child_identity:
            os.kill(child_pid, signal.SIGKILL)
        if launcher.poll() is None:
            launcher.kill()
        launcher.wait()
        launcher.stdout.close()


def test_completed_state_cannot_replace_property_evidence(execution_factory):
    """Check revalidates the exact property report rather than trusting state markers."""
    execution, workspace = execution_factory()
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    assert execution.check()[0] is True
    state = state_for(workspace, done)
    attempt = state["properties"]["A_FAST"]["attempts"][-1]
    run_dir = (workspace / done["state_artifact"]).parent
    (run_dir / attempt["console"]).write_text("A hand-authored claim is not tool evidence\n")
    assert execution.check()[0] is False


def test_unrecognized_property_status_fails_closed():
    """A future report spelling cannot silently shrink the expected property set."""
    with pytest.raises(ValueError, match="Unrecognized"):
        parse_properties(" 1 u.A_CHECK : Unsupported\tunknown\t0.00\t(-)\n")


def test_protected_uncreated_artifact_subtree_is_rejected(execution_factory):
    """A no-write descendant applies before the managed directory is first created."""
    execution, workspace = execution_factory()
    execution.un_write_dirs = ["output/formal_runs"]
    with pytest.raises(ValueError, match="not allowed"):
        execution.run()
    assert not (workspace / "output" / "formal_runs").exists()


def test_parallel_fast_property_finishes_before_slow_turn(execution_factory):
    """A long property occupies one slot, not a barrier across the whole batch."""
    execution, workspace = execution_factory(("A_SLOW", "A_FAST"), max_active_workers=2)
    execution.run()
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    state = state_for(workspace, done)
    assert state["properties"]["A_FAST"]["attempts"][0]["ended_at"] < state["properties"]["A_SLOW"]["attempts"][0]["ended_at"]


def test_retry_keeps_attempts_and_cumulative_budget(execution_factory):
    """Retry adds a recorded round rather than deleting earlier time and decisions."""
    execution, workspace = execution_factory(("A_SLOW",))
    execution.run()
    previous = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    before = state_for(workspace, previous)["properties"]["A_SLOW"]["execution_elapsed_s"]
    with pytest.raises(ValueError, match="exceeds the remaining"):
        execution.review(["A_SLOW"], "retry", "Try longer", "Review remaining depth", retry_budget_s=9)
    execution.review(["A_SLOW"], "retry", "Check a longer bounded attempt", "Review remaining depth", retry_budget_s=3)
    done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    item = state_for(workspace, done)["properties"]["A_SLOW"]
    assert len(item["attempts"]) == 3
    assert item["review_round"] == 2
    assert item["attempts"][-1]["budget_s"] == 3
    assert item["execution_elapsed_s"] > before
    with pytest.raises(ValueError, match="Retry budget exhausted"):
        execution.review(["A_SLOW"], "retry", "Again", "Inspect")


def test_controller_crash_cleans_owned_workers(execution_factory):
    """A dead controller is detected and its persisted owned process is terminated."""
    execution, workspace = execution_factory(("A_SLOW",), first_pass_budget_s=4, analysis_threshold_s=5)
    execution.run()
    running = wait_for(execution, lambda item: bool(item.get("states", {}).get("RUNNING_FAST")))
    state = state_for(workspace, running)
    attempt = state["properties"]["A_SLOW"]["attempts"][0]
    assert process_identity(state["controller_pid"]) == state["controller_identity"]
    os.kill(state["controller_pid"], signal.SIGKILL)
    done = wait_for(execution, lambda item: item["status"] == "INTERRUPTED")
    assert process_identity(attempt["pid"]) != attempt["identity"]
    assert execution.check()[0] is False


def test_semantic_yaml_changes_invalidate_but_analysis_does_not(execution_factory):
    """Evidence tracks spec/config inputs without being invalidated by its own projection."""
    execution, workspace = execution_factory()
    records = workspace / "output" / ".formal_records.yaml"
    records.write_text("dut: DUT\nspec: {}\nanalysis: {}\n")
    execution.run()
    wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)
    records.write_text("dut: DUT\nspec: {}\nanalysis: {note: reviewed}\n")
    assert execution.status()["current_inputs"] is True
    records.write_text("dut: DUT\nspec: {parameters: {WIDTH: 16}}\nanalysis: {}\n")
    assert execution.status()["current_inputs"] is False
    assert execution.check()[0] is False


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Set FORMALMC_INTEGRATION=1 for licensed short real-tool test")
def test_actual_formalmc_short_design(tmp_path):
    """Run a real two-assertion design through inventory, isolated attempts, and gate."""
    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC is unavailable")
    workspace = tmp_path / "real"
    dut = workspace / "DUT"
    dut.mkdir(parents=True)
    (dut / "dut.sv").write_text(
        "module DUT(input logic clk,rst_n,en,input logic [3:0] d);\n"
        "logic [3:0] q; always @(posedge clk) if(!rst_n) q<=0; else if(en) q<=d;\n"
        "A_HOLD: assert property (@(posedge clk) disable iff(!rst_n) !en |=> $stable(q));\n"
        "A_BAD: assert property (@(posedge clk) disable iff(!rst_n) q==0);\n"
        "C_NEVER: cover property (@(posedge clk) disable iff(!rst_n) en && !en);\nendmodule\n"
    )
    tests = workspace / "output" / "tests"
    tests.mkdir(parents=True)
    (tests / "DUT_checker.sv").write_text("// no auxiliary checker\n")
    (tests / "DUT_wrapper.sv").write_text("// DUT is verification top\n")
    (tests / "DUT_formal.tcl").write_text(
        'set SCRIPT_DIR [file dirname [info script]]\n'
        'read_design -top DUT -sysv [file join $SCRIPT_DIR ../../DUT/dut.sv]\n'
        'def_clk clk\ndef_rst rst_n -value 0\n'
        '# UCAGENT_PROOF_BEGIN\nprove\nshow_prop -summary\nexit\n'
    )
    policy = dict(first_pass_budget_s=1, analysis_threshold_s=2,
                  max_active_workers=1, slow_queue_max_workers=1,
                  setup_timeout_s=10, stop_grace_s=1,
                  max_review_rounds=1, property_cumulative_budget_s=3, session_max_properties=2)
    execution = FormalExecution(str(workspace), "output", "DUT", Config(policy))
    try:
        execution.run()
        done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS, timeout=25)
        state = state_for(workspace, done)
        assert done["status"] == "COMPLETED", state
        assert state["properties"]["A_HOLD"]["result"] == "PROVEN"
        assert state["properties"]["A_BAD"]["result"] == "FALSIFIED"
        assert state["properties"]["C_NEVER"]["result"] == "COVER_UNREACHABLE"
        assert execution.check()[0] is True
        from formal.tools import AnalyzeFormal
        tool = AnalyzeFormal(workspace=str(workspace), output_dir="output", dut="DUT", cfg=Config(policy))
        request = {"run_id": done["run_id"]}
        env = tool.invoke({**request, "mode": "environment"})
        assert env["status"] == "completed", env
        assert "posedge, clk" in env["observations"]["clock"]["lines"]
        bounded = tool.invoke({**request, "mode": "overconstraint", "depth": 7})
        assert bounded["status"] == "completed", bounded
        cone = tool.invoke({**request, "mode": "fanin", "property_name": "A_HOLD"})
        assert cone["status"] == "completed", cone
        assert {"kind": "input", "signal": "en"} in cone["signals"]
        sanity = tool.invoke({**request, "mode": "sanity", "property_name": "A_HOLD"})
        if sanity["status"] == "unavailable":
            assert sanity["required_feature"] == "FormalVac"
        else:
            assert sanity["status"] == "completed", sanity
        unreachable = tool.invoke({**request, "mode": "unreachable", "property_name": "C_NEVER"})
        assert unreachable["observed_cover_result"] == "COVER_UNREACHABLE", unreachable
        bounded_search = tool.invoke({**request, "mode": "bounded_search", "property_name": "A_BAD", "depth": 7})
        assert bounded_search["search_outcome"] == "counterexample", bounded_search
        assert bounded_search["requested_depth"] == 7
        assert execution.check()[0] is True
        selected = execution.run(["A_HOLD", "A_BAD"])
        batch = {"run_id": selected["run_id"], "scope": "selected"}
        finished = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS, timeout=25, **batch)
        assert finished["status"] == "COMPLETED", state_for(workspace, finished)
        isolated_results = execution.evidence(["A_HOLD", "A_BAD"], **batch)
        assert {row["result"] for row in isolated_results["items"]} == {"PROVEN", "FALSIFIED"}
        attempts = state_for(workspace, finished)["properties"]
        assert attempts["A_HOLD"]["attempts"][0]["pid"] == attempts["A_BAD"]["attempts"][0]["pid"]
        assert execution.status()["run_id"] == done["run_id"]
    finally:
        execution.cancel()
        wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS)


@pytest.mark.skipif(os.environ.get("FORMALMC_INTEGRATION") != "1", reason="Requires licensed FormalMC")
def test_actual_formalmc_counterexample_replay(tmp_path):
    """Replay a real native VCD against a revised assertion in the generated checker."""
    import yaml
    from formal.tools import AnalyzeFormal, RunFormal
    from ucagent.util.config import Config as RuntimeConfig

    if not shutil.which("FormalMC"):
        pytest.skip("FormalMC is unavailable")
    workspace = tmp_path
    (workspace / "DUT").mkdir()
    (workspace / "DUT" / "DUT.sv").write_text(
        "module DUT(input logic clk, rst_n, req, output logic armed, ack);\n"
        "logic startup;\n"
        "always @(posedge clk) if (!rst_n) begin startup <= 0; armed <= 0; end\n"
        "else begin startup <= 1; armed <= startup; end\n"
        "assign ack = !req;\nendmodule\n"
    )
    (workspace / "output").mkdir()
    path = workspace / "output" / ".formal_records.yaml"
    ck = {"id": "CK-ACK", "style": "Seq", "description": "Active request is acknowledged",
          "sva_body": "@(posedge clk) disable iff (!rst_n) (armed && req) |-> ack;"}
    records = {"dut": "DUT", "basic_info": {"clock_reset": {
        "clock_signal": "clk", "clock_count": "1", "reset_signal": "rst_n", "reset_type": "低有效同步",
    }}, "spec": {"function_groups": [{"id": "FG-IO", "functions": [{"id": "FC-ACK", "check_points": [ck]}]}]}}
    path.write_text(yaml.safe_dump(records))
    cfg = RuntimeConfig({"runtime_options": {"formal_execution": {"max_active_workers": 1}}})
    arguments = {"workspace": str(workspace), "output_dir": "output", "dut": "DUT", "cfg": cfg}
    tool = RunFormal(**arguments)
    run = tool.invoke({"action": "run", "scope": "selected", "ck_ids": ["CK-ACK"]})
    batch = {"run_id": run["run_id"], "scope": "selected"}
    execution = FormalExecution(**arguments)
    try:
        finished = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS, **batch)
        assert finished["counts"] == {"FALSIFIED": 1}, state_for(workspace, finished)
        request = {"mode": "replay", "run_id": run["run_id"], "property_name": finished["selected_properties"][0]}
        analyzer = AnalyzeFormal(**arguments)
        before = analyzer.invoke(request)
        assert before["status"] == "still_fails", before
        ck["sva_body"] = "@(posedge clk) disable iff (!rst_n) (armed && req) |-> !ack;"
        path.write_text(yaml.safe_dump(records))
        after = analyzer.invoke(request)
        assert after["status"] == "triggered_no_failure_in_trace", after
        assert after["original_failure"]["check_tick"] == before["check_tick"]
    finally:
        execution.cancel(**batch)


def test_selected_scope_cannot_change_full_pointer_or_cancel_full(execution_factory):
    """Both controllers coexist and a selected verdict never authorizes full acceptance."""
    execution, workspace = execution_factory(("A_SLOW", "A_FAST"), max_active_workers=2)
    full = execution.run()
    selected = execution.run(["A_FAST"])
    assert full["scope"] == "full" and selected["scope"] == "selected"
    assert full["run_id"] != selected["run_id"]
    root = workspace / "output" / "formal_runs"
    assert json.loads((root / "current.json").read_text())["run_id"] == full["run_id"]
    assert json.loads((root / "selected.json").read_text())["run_id"] == selected["run_id"]

    def selected_status():
        """Read only the selected controller regardless of the full pointer."""
        return execution.status(run_id=selected["run_id"], scope="selected")

    deadline = time.monotonic() + 10
    while selected_status()["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
        time.sleep(0.05)
    result = selected_status()
    assert result["selected_complete"] and not result["full_complete"]
    assert result["counts"] == {"PROVEN": 1, "NOT_EXECUTED": 1}
    from dataclasses import asdict
    from formal.tools import RunFormal
    tool = RunFormal(str(workspace), "output", "DUT", Config(asdict(execution.policy)))
    resolved = tool.invoke({"action": "status", "run_id": selected["run_id"], "wait_s": 0})
    assert resolved["scope"] == "selected" and resolved["counts"] == result["counts"]
    assert resolved["current_inputs"]
    assert execution.check()[0] is False
    with pytest.raises(ValueError, match="scope"):
        execution.cancel(run_id=full["run_id"], scope="selected")
    assert execution.status()["run_id"] == full["run_id"]


def test_concurrent_scopes_share_slot_and_cancel_exact_run(execution_factory):
    """Cancelling the selected controller leaves the full controller and pointer live."""
    execution, workspace = execution_factory(("A_SLOW", "A_FAST"))
    full = execution.run()
    wait_for(execution, lambda row: row["states"].get("RUNNING_FAST", 0) > 0)
    selected = execution.run(["A_SLOW"])
    selected_id = selected["run_id"]
    assert execution.cancel(run_id=selected_id, scope="selected")["run_id"] == selected_id
    deadline = time.monotonic() + 10
    while execution.status(run_id=selected_id, scope="selected")["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
        time.sleep(0.05)
    assert execution.status(run_id=selected_id, scope="selected")["status"] == "CANCELLED"
    assert execution.status()["run_id"] == full["run_id"]
    assert execution.status()["status"] != "CANCELLED"
    assert not (workspace / full["state_artifact"]).with_name("cancel").exists()


def test_active_review_is_applied_while_other_targets_continue(execution_factory):
    """A ready target accepts a disposition while another proof remains scheduled."""
    execution, workspace = execution_factory(("A_SLOW1", "A_SLOW2", "A_SLOW3"), max_active_workers=2)
    execution.run()
    pending = wait_for(execution, lambda row: row["status"] == "RUNNING" and row["needs_review"] > 0)
    ready = next(row for row in pending["review_queue"] if "defer" in row["actions"])
    response = execution.review([ready["property"]], "defer", "Needs a stronger invariant", "Review the original assumptions",
                                run_id=pending["run_id"])
    assert response["review_pending"]
    applied = wait_for(execution, lambda row: row["deferred_total"] == 1)
    state = state_for(workspace, applied)
    assert state["properties"][ready["property"]]["result"] == "UNPROVEN"
    assert state["decisions"][-1]["property"] == ready["property"]
    assert not (workspace / applied["state_artifact"]).with_name("cancel").exists()


def test_repair_then_selected_proof_and_full_regression(execution_factory):
    """Exercise generated SVA, selection, isolation and full Check on one fixture."""
    pytest.importorskip("pyslang")
    import yaml

    from formal.preflight import PreflightError
    from formal.tools import render_environment

    execution, workspace = execution_factory(("top.A_CK_FAST", "reach.C_CK_ACTIVE"), max_active_workers=2)
    (workspace / "DUT" / "dut.sv").write_text("module DUT(input logic a, output logic z); assign z=a; endmodule\n")
    records = workspace / "output" / ".formal_records.yaml"

    def author(body):
        """Write the same requirement with either a bad name or its correction."""
        records.write_text(json.dumps({"dut": "DUT", "spec": {"function_groups": [
            {"id": "FG-DUT", "functions": [{"id": "FC-DUT", "check_points": [
                {"id": "CK-FAST", "style": "Comb", "description": "Identity", "sva_body": body},
                {"id": "CK-ACTIVE", "style": "Cover", "description": "Active", "sva_body": "z;"},
                {"id": "CK-LEGAL", "style": "Assume", "description": "Input domain", "sva_body": "!$isunknown(a);"},
            ]}]}]}}))

    author("z == missing_signal;")
    with pytest.raises(PreflightError):
        render_environment(str(workspace), "output", "DUT")
    author("z == a;")
    render_environment(str(workspace), "output", "DUT")
    selected = execution.run(["top.A_CK_FAST"])
    deadline = time.monotonic() + 10
    while execution.status(run_id=selected["run_id"], scope="selected")["status"] in ACTIVE_RUNS and time.monotonic() < deadline:
        time.sleep(0.05)
    selected_state = execution.status(run_id=selected["run_id"], scope="selected")
    assert selected_state["selected_complete"]
    frozen = (workspace / selected_state["state_artifact"]).parent / "inputs" / "output" / "tests" / "DUT_checker.sv"
    assert "M_CK_LEGAL: assume property" in frozen.read_text()
    assert execution.check()[0] is False
    execution.run()
    wait_for(execution, lambda result: result["status"] not in ACTIVE_RUNS)
    assert execution.check()[0] is True
    saved = yaml.safe_load(records.read_text())
    assert saved["run_results"]["run_id"] != selected["run_id"]


def test_disposable_preflight_and_function_batches_are_separate_from_full_acceptance(execution_factory, monkeypatch):
    """Exercise phase 5–7 receipts across two incremental FC revisions."""
    import yaml
    from formal.baseline import function_batch_progress
    from formal.data import FormalDataStore
    from formal.skills.lib.models import FormalRecords
    from formal.tools import RunFormal, render_environment
    from ucagent.util.config import Config as RuntimeConfig

    cover = "u_checker.C_CK_READY"
    first = "top.u_checker.A_CK_FIRST"
    second = "u_checker.A_CK_SECOND"
    execution, workspace = execution_factory((cover,))
    runtime_cfg = RuntimeConfig({"runtime_options": {"formal_batched_sva": True,
                                                        "formal_execution": vars(execution.policy)}})
    execution.batched_sva = True
    (workspace / "DUT" / "dut.sv").write_text(
        "module DUT(input logic clk, input logic a, input logic b, output logic y); assign y = a & b; endmodule\n")
    out = workspace / "output"
    path = out / ".formal_records.yaml"
    shared = {"id": "CK-READY", "style": "Cover", "description": "Check one attainable transaction",
              "sva_body": "@(posedge clk) a;"}
    ck_first = {"id": "CK-FIRST", "style": "Comb", "description": "No output when input is clear"}
    ck_second = {"id": "CK-SECOND", "style": "Comb", "description": "Both inputs assert output"}
    records = {"dut": "DUT", "basic_info": {"clock_reset": {"clock_signal": "clk"}}, "spec": {"function_groups": [
        {"id": "FG-FUNCTION", "functions": [
            {"id": "FC-SECOND", "review_order": 2, "check_points": [ck_second]},
            {"id": "FC-BASE", "review_order": 3, "check_points": [shared]},
            {"id": "FC-FIRST", "review_order": 1, "check_points": [ck_first]},
        ]}
    ]}}
    path.write_text(yaml.safe_dump(records))
    tool = RunFormal(str(workspace), "output", "DUT", runtime_cfg)
    store = FormalDataStore(str(workspace), "output", "DUT", cfg=runtime_cfg)
    monkeypatch.setenv("FAKE_FORMAL_PROPERTIES", json.dumps([{"name": "C_UCAGENT_TOOLCHAIN_SMOKE", "kind": "cover"}]))
    monkeypatch.setenv("FAKE_FORMAL_COMPILE_ERROR", "1")
    bad = tool.invoke({"action": "preflight"})
    failed = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS,
                      scope="preflight", run_id=bad["run_id"])
    assert failed["error_code"] == "formal_tool_compile_error", failed
    assert failed["diagnostics"][0]["path"] == "output/tests/DUT_checker.sv"
    cached = tool.invoke({"action": "preflight"})
    assert cached["run_id"] == bad["run_id"]
    assert cached["status"] == "ERROR"
    monkeypatch.delenv("FAKE_FORMAL_COMPILE_ERROR")
    monkeypatch.setenv("FAKE_FORMAL_PREPARATION_ERROR", "1")
    transient = tool.invoke({"action": "preflight", "retry_prepare": True})
    assert transient["run_id"] != bad["run_id"]
    status = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS,
                      scope="preflight", run_id=transient["run_id"])
    assert status["error_code"] == "formal_tool_preparation_error"
    monkeypatch.delenv("FAKE_FORMAL_PREPARATION_ERROR")
    preflight = tool.invoke({"action": "preflight", "retry_prepare": True})
    assert preflight["run_id"] != transient["run_id"]
    smoke = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS,
                     scope="preflight", run_id=preflight["run_id"])
    assert smoke["status"] == "COMPLETED", smoke
    assert smoke["counts"] == {"COVER_REACHED": 1}
    smoke_report = (workspace / smoke["report"]).read_text()
    assert "Toolchain smoke complete: `true`" in smoke_report
    assert "Proof complete: `false`" in smoke_report
    assert "CK_FIRST" not in (out / "formal_runs" / preflight["run_id"] / "inputs/output/tests/DUT_checker.sv").read_text()
    assert execution.status()["status"] == "NOT_STARTED"
    assert execution.check_smoke()["preflight_complete"]
    assert not (out / "formal_runs" / "baseline.json").exists()
    assert execution.check_smoke()["preflight_complete"]
    first_batch = store.prepare("sva")
    assert first_batch["fc_id"] == "FC-FIRST"
    assert first_batch["run_call"] == {"action": "run", "scope": "selected", "fc_id": "FC-FIRST"}
    assert store.prepare("sva", function="FC-SECOND")["check_points"]["items"][0]["property_name"] == second
    with pytest.raises(ValueError, match="Implement the selected Assert/Cover"):
        tool.invoke({"action": "run", "scope": "selected", "ck_ids": ["CK-SECOND"]})
    # Smoke never freezes official properties or consumes their results.

    def run_selected(name, known, **selector):
        """Generate a real checker and record exactly the diagnostic target."""
        monkeypatch.setenv("FAKE_FORMAL_PROPERTIES", json.dumps(
            [{"name": cover, "kind": "cover"}, *({"name": n, "kind": "assert"} for n in known)]))
        request = {"action": "run", "scope": "selected", **selector}
        result = tool.invoke(request)
        done = wait_for(execution, lambda item: item["status"] not in ACTIVE_RUNS,
                        scope="selected", run_id=result["run_id"])
        assert done["status"] == "COMPLETED", done
        assert done["counts"]["PROVEN"] == 1
        assert done["selected_properties"] == [name]
        assert not done["proof_complete"]
        assert tool.invoke(request)["run_id"] == result["run_id"]

    ck_first["sva_body"] = "!a |-> !y;"
    path.write_text(yaml.safe_dump(records))
    run_selected(first, [first], ck_ids=["CK-FIRST"])
    assert function_batch_progress(execution, FormalRecords.model_validate(records))["pending"] == ["CK-READY", "CK-SECOND"]
    plan = tool.invoke({"action": "pending"})
    assert plan["batches"][0]["fc_id"] == "FC-SECOND"
    assert plan["batches"][0]["phase"] == "implement"
    assert plan["batches"][0]["unimplemented_ck_ids"] == ["CK-SECOND"]
    assert plan["batches"][0]["run_call"] is None
    with pytest.raises(ValueError, match="Complete all SVA"):
        tool.invoke({"action": "run"})
    ck_second["sva_body"] = "(a && b) |-> y;"
    path.write_text(yaml.safe_dump(records))
    run_selected(second, [first, second], fc_id="FC-SECOND")
    current = FormalRecords.model_validate(records)
    assert function_batch_progress(execution, current)["pending"] == ["CK-READY"]
    assert execution.status()["status"] == "NOT_STARTED"
    ck_first["sva_body"] = "!b |-> !y;"
    path.write_text(yaml.safe_dump(records))
    render_environment(str(workspace), "output", "DUT")
    assert function_batch_progress(execution, FormalRecords.model_validate(records))["pending"] == ["CK-FIRST", "CK-READY"]
    plan = tool.invoke({"action": "pending"})
    assert plan["batches"][0]["run_call"] == {"action": "run", "scope": "selected", "fc_id": "FC-FIRST"}

    shared["sva_body"] = "@(posedge clk) b;"
    path.write_text(yaml.safe_dump(records))
    assert tool.invoke({"action": "run", "scope": "selected", "property_names": [first]})["scope"] == "selected"



def test_native_license_wait_is_reported_separately_from_solver_result(execution_factory, monkeypatch):
    """A wait is observable during execution and does not downgrade the eventual proof."""
    monkeypatch.setenv("FAKE_FORMAL_LICENSE_WAIT", "1")
    execution, workspace = execution_factory()
    execution.run()
    waiting = wait_for(execution, lambda status: bool(status["license_wait"]["active_properties"]))
    assert waiting["license_wait"] == {"reported_attempts": 1, "active_properties": ["A_FAST"]}
    assert "license waiting" in waiting["next_action"]
    finished = wait_for(execution, lambda status: status["status"] == "COMPLETED")
    assert finished["counts"] == {"PROVEN": 1}
    assert finished["license_wait"] == {"reported_attempts": 1, "active_properties": []}
    report = (workspace / finished["report"]).read_text()
    assert "Attempt wall seconds | Solver-reported seconds | License wait reported" in report
    assert " | Yes | " in report
