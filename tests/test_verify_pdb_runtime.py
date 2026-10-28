#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression coverage for PDB commands, console output, and runtime controls."""

import os
import readline
import signal
import shlex
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.verify_pdb import VerifyPDB
from ucagent.verify_agent import VerifyAgent
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.log import info
from ucagent.util.markdown import markdown_heading_spacing_errors


def _console_output_lines(rendered: str) -> list[str]:
    return [
        line
        for line in rendered.splitlines()
        if not line.startswith("> ")
        and not line.startswith("Executing shell command:")
        and not line.startswith("Working directory:")
        and not line.startswith("Idle timeout without output:")
        and "Command '" not in line
    ]


class _FakeAgent:
    def __init__(self, workspace: str | None = None) -> None:
        self._need_break = False
        self.break_threads: set[int] = set()
        if workspace is not None:
            self.workspace = workspace

    def set_break(self, value=True):
        self._need_break = value

    def is_break(self):
        return (
            self._need_break
            or threading.current_thread().ident in self.break_threads
        )

    def is_work_busy(self):
        """Expose an idle backend unless a test explicitly simulates model work."""
        return False

    def set_force_trace(self, _value):
        pass

    def message_echo(self, *_args, **_kwargs):
        pass

    def set_break_thread(self, thread_id: int) -> None:
        self.break_threads.add(thread_id)

    def clear_break_thread(self, thread_id: int) -> None:
        self.break_threads.discard(thread_id)


class _ProbePDB(VerifyPDB):
    def __init__(self, agent):
        super().__init__(agent)
        self.running_snapshots: list[list[str]] = []

    def do_probe(self, _arg):
        self.running_snapshots.append(self.get_running_commands())
        return False

    def do_tui(self, _arg):
        self.running_snapshots.append(self.get_running_commands())
        return False

    def do_probeout(self, _arg):
        print("probe output")
        return False


def test_generated_instruction_file_has_blank_lines_before_every_heading(tmp_path):
    dut_dir = tmp_path / "Adder"
    dut_dir.mkdir()
    (dut_dir / "README.md").write_text(
        "# DUT Overview\nDetails\n",
        encoding="utf-8",
    )
    agent = VerifyAgent.__new__(VerifyAgent)
    agent.workspace = str(tmp_path)
    agent.dut_name = "Adder"
    agent._default_system_prompt = "## Required Work\nRun verification."

    agent.generate_instruction_file("AGENT.md")

    content = (tmp_path / "AGENT.md").read_text(encoding="utf-8")
    assert markdown_heading_spacing_errors(content) == []
    assert content.startswith("\n# Goal Description\n")


@pytest.fixture
def probe_pdb():
    previous = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent())
    try:
        yield pdb
    finally:
        signal.signal(signal.SIGINT, previous)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


@pytest.fixture
def waveform_replay_pdb(probe_pdb, tmp_path, monkeypatch):
    """Wire real configured gate types to controllable test and replay results."""
    import ucagent.checkers.toffee_report as waveform_report
    from ucagent.checkers.toffee_report import UnityChipCheckerWaveformBugAnalysis
    from ucagent.checkers.unity_test import UnityChipCheckerTestCase

    (tmp_path / "tests").mkdir()
    classifier = UnityChipCheckerTestCase(
        doc_func_check="checks.md", test_dir="tests", doc_bug_analysis="bugs.md"
    ).set_workspace(str(tmp_path))
    gate = UnityChipCheckerWaveformBugAnalysis(
        bug_file="bugs.md", test_dir="tests", require_current_replay=True
    ).set_workspace(str(tmp_path))
    stage = SimpleNamespace(name="record_and_report_bugs", checker=[classifier, gate])
    state = SimpleNamespace(
        classifier=classifier, gate=gate, stage=stage,
        test_calls=[], replay_calls=[],
        test_result=(True, {"success": "Confirmed DUT reproducers remain Fail."}),
        replay_result=(True, "Automatically refreshed 2 semantically unchanged central records."),
        tools={"WaveInfo": object(), "ApplyWaveInfoEvidence": object()},
    )

    def run_tests(**kwargs):
        """Record one complete test-classification request."""
        state.test_calls.append(kwargs)
        return state.test_result

    def replay(*args, **kwargs):
        """Expose per-TC progress while retaining exact replay invocation details."""
        state.replay_calls.append((args, kwargs))
        kwargs["progress_callback"]("[1/2] Replaying 'tests/test_a.py::test_a'.")
        kwargs["progress_callback"]("[2/2] Replaying 'tests/test_b.py::test_b'.")
        return state.replay_result

    monkeypatch.setattr(classifier, "do_check", run_tests)
    monkeypatch.setattr(waveform_report, "check_all_documented_waveform_bug_analysis", replay)
    probe_pdb.agent.cfg = SimpleNamespace(call_time_out=240)
    probe_pdb.agent.stage_manager = SimpleNamespace(
        workspace=str(tmp_path), stages=[stage], stage_index=0
    )
    probe_pdb.agent.get_tool_by_name = state.tools.get
    probe_pdb.agent.backend = object()
    probe_pdb.agent.test_tools = []
    gate.set_stage_manager(SimpleNamespace(agent=probe_pdb.agent))
    state.pdb = probe_pdb
    return state


@pytest.mark.parametrize("argument, expected_timeout", [("", 240), ("120", 120)])
def test_waveform_replay_runs_full_classification_then_strict_gate(
    waveform_replay_pdb, argument, expected_timeout
):
    """Manual replay uses configured artifacts and reports progress without stage transitions."""
    state = waveform_replay_pdb
    state.pdb.execute_command(f"waveform_replay {argument}".strip())

    assert state.test_calls == [{"timeout": expected_timeout}]
    assert len(state.replay_calls) == 1
    args, kwargs = state.replay_calls[0]
    assert args == (state.pdb.agent.stage_manager.workspace, "bugs.md")
    assert kwargs["require_current_replay"] is True
    assert kwargs["waveform_test_dir"] == "tests"
    assert kwargs["waveform_tool"] is state.tools["WaveInfo"]
    assert kwargs["waveform_evidence_tool"] is state.tools["ApplyWaveInfoEvidence"]
    log = state.pdb.render_console_entries_since(0)
    assert "DUT test classification PASSED" in log
    assert "[1/2] Replaying 'tests/test_a.py::test_a'" in log
    assert "[2/2] Replaying 'tests/test_b.py::test_b'" in log
    assert "Automatically refreshed 2" in log
    assert "[waveform_replay] SUCCESS" in log
    assert state.pdb.agent.stage_manager.stage_index == 0
    assert state.classifier.is_in_check is False
    assert state.gate.is_in_check is False


@pytest.mark.parametrize("argument", ["0", "-1", "bad", "1.5", "10 20"])
def test_waveform_replay_rejects_invalid_timeout(waveform_replay_pdb, argument):
    """Invalid command arguments fail before tests or evidence writes begin."""
    state = waveform_replay_pdb
    state.pdb.execute_command(f"waveform_replay {argument}")
    log = state.pdb.render_console_entries_since(0)
    assert "FAILED during configuration" in log
    assert "waveform_replay [timeout_seconds]" in log
    assert not state.test_calls
    assert not state.replay_calls


@pytest.mark.parametrize("gate_count", [0, 2])
def test_waveform_replay_rejects_missing_or_ambiguous_gates(waveform_replay_pdb, gate_count):
    """Configuration ambiguity never selects an arbitrary waveform document."""
    state = waveform_replay_pdb
    state.stage.checker = [state.classifier] + [state.gate] * gate_count
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    assert f"found {gate_count}" in log
    assert "require_current_replay=true" in log
    assert not state.test_calls
    assert not state.replay_calls


def test_waveform_replay_requires_matching_preceding_classification(waveform_replay_pdb):
    """A test runner for another document cannot authorize the selected replay."""
    state = waveform_replay_pdb
    state.classifier.doc_bug_analysis = "other_bugs.md"
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    assert "preceding DUT test classification checker" in log
    assert "bugs.md" in log
    assert not state.test_calls
    assert not state.replay_calls


@pytest.mark.parametrize("tool_name", ["WaveInfo", "ApplyWaveInfoEvidence"])
def test_waveform_replay_requires_evidence_tools(waveform_replay_pdb, tool_name):
    """Missing evidence tools are diagnosed before rerunning tests."""
    state = waveform_replay_pdb
    del state.tools[tool_name]
    state.pdb.execute_command("waveform_replay")
    assert "Enable WaveInfo and ApplyWaveInfoEvidence" in state.pdb.render_console_entries_since(0)
    assert not state.test_calls
    assert not state.replay_calls


def test_waveform_replay_preserves_test_failure_diagnostic(waveform_replay_pdb):
    """A classification failure reports its exact artifact and blocks replay."""
    state = waveform_replay_pdb
    state.test_result = (False, {
        "error": "tests/test_a.py:42 fixture failure",
        "next_action": "Repair the env fixture, then rerun.",
    })
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    assert "DUT test classification failed" in log
    assert "tests/test_a.py:42 fixture failure" in log
    assert "Repair the env fixture" in log
    assert not state.replay_calls
    assert "[waveform_replay] SUCCESS" not in log


def test_waveform_replay_preserves_complete_batch_review_diagnostic(waveform_replay_pdb):
    """Semantic changes remain failures with their actionable batch call intact."""
    state = waveform_replay_pdb
    state.replay_result = (False, {
        "error_code": "WAVEFORM_SEMANTIC_BATCH_REVIEW_REQUIRED",
        "error": "Two TCs changed semantic inputs.",
        "next_action": "Review all returned items together.",
        "review_batch_call": {
            "tool": "ReviewWaveInfoEvidenceBatch",
            "arguments": {"target_file": "bugs.md", "items": [
                {"test_case_tag": "TC-tests/test_a.py::test_a", "receipt_id": "a" * 32},
                {"test_case_tag": "TC-tests/test_b.py::test_b", "receipt_id": "b" * 32},
            ]},
        },
    })
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    assert "[waveform_replay] FAILED after" in log
    assert "WAVEFORM_SEMANTIC_BATCH_REVIEW_REQUIRED" in log
    assert "ReviewWaveInfoEvidenceBatch" in log
    assert "TC-tests/test_a.py::test_a" in log
    assert "TC-tests/test_b.py::test_b" in log
    assert "Review all returned items together" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("failure", [OSError("disk is read-only"), KeyboardInterrupt()])
def test_waveform_replay_reports_exception_and_cancellation_context(
    waveform_replay_pdb, monkeypatch, failure
):
    """Unexpected replay failures and cancellation preserve the current TC in logs."""
    import ucagent.checkers.toffee_report as waveform_report

    def fail_replay(*args, **kwargs):
        """Simulate a failure while replaying a known test."""
        kwargs["progress_callback"]("[1/2] Replaying 'tests/test_a.py::test_a'.")
        raise failure

    state = waveform_replay_pdb
    monkeypatch.setattr(waveform_report, "check_all_documented_waveform_bug_analysis", fail_replay)
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    status = "CANCELLED" if isinstance(failure, KeyboardInterrupt) else "FAILED"
    assert f"[waveform_replay] {status}" in log
    assert "tests/test_a.py::test_a" in log
    if isinstance(failure, OSError):
        assert "disk is read-only" in log
    assert "[waveform_replay] SUCCESS" not in log
    assert state.gate.is_in_check is False


@pytest.mark.parametrize("checker_name", ["classifier", "gate"])
def test_waveform_replay_rejects_an_active_check(waveform_replay_pdb, checker_name):
    """Active test or waveform checks prevent overlapping manual replay operations."""
    state = waveform_replay_pdb
    checker = getattr(state, checker_name)
    checker.is_in_check = True
    state.pdb.execute_command("waveform_replay")
    log = state.pdb.render_console_entries_since(0)
    assert "already running" in log
    assert not state.test_calls
    assert not state.replay_calls
    assert checker.is_in_check is True


def test_waveform_replay_cancels_running_test_process(waveform_replay_pdb, monkeypatch):
    """Cancelling during test execution kills the tracked process and resets its state."""
    state = waveform_replay_pdb
    killed = []

    def cancel_tests(**kwargs):
        """Attach a running process before simulating a user interrupt."""
        state.classifier.set_check_process(
            SimpleNamespace(pid=123, kill=lambda: killed.append(True)), kwargs["timeout"]
        )
        raise KeyboardInterrupt()

    monkeypatch.setattr(state.classifier, "do_check", cancel_tests)
    state.pdb.execute_command("waveform_replay")
    assert killed == [True]
    assert state.classifier.is_in_check is False
    assert state.classifier._process is None
    assert not state.replay_calls
    assert "CANCELLED during: Running the full DUT test classification check" in state.pdb.render_console_entries_since(0)


@pytest.mark.parametrize("skills_enabled", [False, True])
@pytest.mark.parametrize("failure_scope", ["classification", "waveform"])
def test_waveform_replay_reanalyzes_failures_and_revalidates(
    waveform_replay_pdb, skills_enabled, failure_scope
):
    """Both failure sources reach the configured LLM with canonical repair/removal rules."""
    state = waveform_replay_pdb
    state.pdb.agent.cfg.skill = SimpleNamespace(use_skill=skills_enabled)
    diagnostic = {"error": "TC-tests/test_a.py::test_a changed", "requires_bug_reanalysis": True}
    if failure_scope == "classification":
        state.test_result = (False, diagnostic)
    else:
        state.replay_result = (False, diagnostic)
    prompts = []
    state.pdb.agent.set_break(True)

    def reanalyze(prompt):
        """Represent one backend turn that repairs actual inputs before revalidation."""
        assert state.pdb.agent.is_break() is False
        prompts.append(prompt)
        state.test_result = (True, {"success": "Current tests classified."})
        state.replay_result = (True, {"success": "Current Bug evidence validated."})

    state.pdb.agent.custom_chat = reanalyze
    state.pdb.execute_command("waveform_replay 120 --reanalyze --max-rounds 2")

    assert len(prompts) == 1
    prompt = prompts[0]
    assert "Guide_Doc/dut_bug_analysis.md section 5.1" in prompt
    assert "tests/test_a.py::test_a changed" in prompt
    assert "If a valid TC still reproduces a DUT Bug, keep it Fail" in prompt
    assert "If a corrected TC passes" in prompt
    assert "Delete unsupported BG entries" in prompt
    assert "delete only unreferenced ROOTs" in prompt
    assert "only when no remaining BG uses that TC" in prompt
    assert "LINK-BUG" in prompt
    assert "ReviewWaveInfoEvidenceBatch atomically" in prompt
    assert "Do not modify DUT implementation" in prompt
    assert "ListSkill" in prompt if skills_enabled else "ListSkill" not in prompt
    assert len(state.test_calls) == 2
    assert all(call == {"timeout": 120} for call in state.test_calls)
    assert len(state.replay_calls) == (1 if failure_scope == "classification" else 2)
    log = state.pdb.render_console_entries_since(0)
    assert "LLM REANALYSIS round 1/2" in log
    assert "revalidating actual artifacts" in log
    assert "[waveform_replay] SUCCESS" in log
    assert "LLM reanalysis rounds=1" in log
    assert state.pdb.agent.is_break() is True
    assert state.pdb.agent.stage_manager.stage_index == 0


def test_waveform_replay_reanalysis_requires_opt_in_and_an_actual_failure(waveform_replay_pdb):
    """A successful replay never consumes a model turn even with reanalysis enabled."""
    state = waveform_replay_pdb
    prompts = []
    state.pdb.agent.custom_chat = prompts.append
    state.pdb.execute_command("waveform_replay --reanalyze")
    assert not prompts
    assert "LLM reanalysis rounds=0" in state.pdb.render_console_entries_since(0)


@pytest.mark.parametrize("arguments", [
    "--max-rounds 2", "--reanalyze --max-rounds", "--reanalyze --max-rounds 0",
    "--reanalyze --max-rounds -2", "--reanalyze --max-rounds bad", "--unknown",
])
def test_waveform_replay_rejects_invalid_reanalysis_arguments(waveform_replay_pdb, arguments):
    """Invalid recovery options stop before any tests or model work."""
    state = waveform_replay_pdb
    state.pdb.execute_command(f"waveform_replay {arguments}")
    assert "FAILED during configuration" in state.pdb.render_console_entries_since(0)
    assert not state.test_calls


def test_waveform_replay_reanalysis_limit_cannot_be_bypassed_by_llm_claims(waveform_replay_pdb):
    """Model assertions of success cannot replace passing artifact checks."""
    state = waveform_replay_pdb
    state.test_result = (False, {"error": "Still-failing unrecorded DUT Bug."})
    prompts = []
    state.pdb.agent.custom_chat = lambda prompt: prompts.append(prompt) or "Everything is fixed."
    state.pdb.execute_command("waveform_replay --reanalyze --max-rounds 2")
    assert len(prompts) == 2
    assert len(state.test_calls) == 3
    log = state.pdb.render_console_entries_since(0)
    assert "LLM reanalysis limit (2) reached" in log
    assert "Still-failing unrecorded DUT Bug" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("unavailable", ["blank", "busy"])
def test_waveform_replay_reanalysis_rejects_unavailable_backend(
    waveform_replay_pdb, unavailable
):
    """Disabled or busy model work leaves the original diagnostic visible."""
    from ucagent.abackend.blank import BlankBackend

    state = waveform_replay_pdb
    state.test_result = (False, {"error": "Current TC needs reanalysis."})
    if unavailable == "blank":
        state.pdb.agent.backend = BlankBackend(state.pdb.agent, object())
    else:
        state.pdb.agent.is_work_busy = lambda: True
    state.pdb.execute_command("waveform_replay --reanalyze")
    log = state.pdb.render_console_entries_since(0)
    if unavailable == "blank":
        assert "Current TC needs reanalysis" in log
        assert "disables model work" in log
    else:
        assert "LLM is already working" in log
        assert not state.test_calls
        assert not state.replay_calls
    assert "[waveform_replay] SUCCESS" not in log


def test_waveform_replay_rejects_model_work_before_running_tests(waveform_replay_pdb):
    """Manual replay cannot rotate test artifacts underneath an active model turn."""
    state = waveform_replay_pdb
    state.pdb.agent.is_work_busy = lambda: True
    state.pdb.execute_command("waveform_replay")
    assert not state.test_calls
    assert not state.replay_calls
    assert not state.pdb._waveform_replay_lock.locked()
    log = state.pdb.render_console_entries_since(0)
    assert "LLM is already working" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("failure", [None, OSError("model unavailable"), KeyboardInterrupt()])
def test_waveform_replay_guards_stage_tools_and_restores_state(
    waveform_replay_pdb, failure
):
    """Stage callbacks stay blocked through direct/local calls and restore on every exit."""
    from ucagent.stage.vmanager import ToolDoCheck, ToolDoComplete, ToolGoToStage, ToolDoExit, ToolCurrentTips

    state = waveform_replay_pdb
    state.test_result = (False, {"error": "Reanalyze the changed TC."})
    calls = []

    def original(*args, **kwargs):
        """Record any stage mutation that must remain blocked during recovery."""
        calls.append((args, kwargs))
        return "Original stage behavior."

    tools = [tool().set_function(original) for tool in (
        ToolDoCheck, ToolDoComplete, ToolGoToStage, ToolDoExit, ToolCurrentTips
    )]
    state.pdb.agent.test_tools = tools
    state.pdb.agent.set_break(True)

    def reanalyze(prompt):
        """Exercise callbacks used by MCP, local tools and direct backend retries."""
        assert tools[0].invoke({})["error"].startswith("Stage actions")
        assert tools[1]._run()["error"].startswith("Stage actions")
        assert tools[2]._run(0)["error"].startswith("Stage actions")
        assert tools[3]._run()["error"].startswith("Stage actions")
        assert tools[4]._run() == prompt
        if failure is not None:
            raise failure
        state.test_result = (True, {})

    state.pdb.agent.custom_chat = reanalyze
    state.pdb.execute_command("waveform_replay --reanalyze")
    assert not calls
    assert all(tool.function is original for tool in tools)
    assert state.pdb.agent.is_break() is True
    assert state.pdb._waveform_replay_lock.locked() is False
    log = state.pdb.render_console_entries_since(0)
    if failure is None:
        assert "[waveform_replay] SUCCESS" in log
    else:
        assert "[waveform_replay] SUCCESS" not in log
        assert "CANCELLED" in log if isinstance(failure, KeyboardInterrupt) else "model unavailable" in log


def test_waveform_replay_rejects_overlapping_command(waveform_replay_pdb):
    """One replay command owns classification, model turns and evidence refresh together."""
    state = waveform_replay_pdb
    with state.pdb._waveform_replay_lock:
        state.pdb.execute_command("waveform_replay --reanalyze")
    assert not state.test_calls
    assert "Another waveform_replay command is already running" in state.pdb.render_console_entries_since(0)


@pytest.mark.parametrize("model_fails_after_edit", [False, True])
def test_waveform_replay_invalidates_recorded_bugs_after_reanalysis_edits(
    waveform_replay_pdb, tmp_path, model_fails_after_edit
):
    """Old stored findings cannot repopulate summaries after removal, even on model failure."""
    from ucagent.checkers.recorder import Recorder

    state = waveform_replay_pdb
    bug_document = tmp_path / "bugs.md"
    bug_document.write_text(
        "\n# Bug analysis\n\n### Arithmetic <FG-A>\n\n#### Add <FC-A>\n\n"
        "##### Output <CK-A>\n\n###### Old finding <BG-OLD-80>\n\nOld analysis.\n",
        encoding="utf-8",
    )
    (tmp_path / "static.md").write_text("\n# Static analysis\n", encoding="utf-8")
    recorder = Recorder(
        type="bug", data_key="BUG_RECORDS", bug_file="bugs.md",
        static_bug_file="static.md", output="summary.md",
    ).set_workspace(str(tmp_path))
    manager = state.pdb.agent.stage_manager
    data = {"BUG_RECORDS": [{"bug_name": "OLD", "desc": "Old conclusion."}]}
    saves = []
    manager.set_data = data.__setitem__
    manager.save_stage_info = lambda: saves.append(True)
    recorder.set_stage_manager(manager)
    recorder.type_handler.on_init()
    assert set(recorder.type_handler._expected_bugs) == {"OLD"}
    state.stage.checker.append(recorder)
    state.test_result = (False, {"error": "The corrected TC now passes; old finding is stale."})

    def reanalyze(prompt):
        """Remove the disproved finding, optionally simulating a later backend failure."""
        assert "static.md" in prompt
        assert "summary.md" in prompt
        bug_document.write_text("\n# Bug analysis\n", encoding="utf-8")
        state.test_result = (True, {})
        if model_fails_after_edit:
            raise OSError("Backend failed after writing the current analysis.")

    state.pdb.agent.custom_chat = reanalyze
    state.pdb.execute_command("waveform_replay --reanalyze")
    assert data["BUG_RECORDS"] is None
    assert recorder.type_handler._expected_bugs == {}
    assert saves == [True]
    log = state.pdb.render_console_entries_since(0)
    assert "Invalidated previously recorded Bug data" in log
    assert ("[waveform_replay] SUCCESS" in log) is not model_fails_after_edit


@pytest.mark.parametrize("failure", [None, OSError("refresh failed after write"), KeyboardInterrupt()])
@pytest.mark.parametrize("separate_stage", [False, True])
def test_waveform_replay_invalidates_recorded_bugs_after_automatic_refresh(
    waveform_replay_pdb, tmp_path, monkeypatch, failure, separate_stage
):
    """Automatic writes invalidate all matching Recorder views even on failed replay."""
    import ucagent.checkers.toffee_report as waveform_report
    from ucagent.checkers.recorder import Recorder

    state = waveform_replay_pdb
    bug_document = tmp_path / "bugs.md"
    bug_document.write_text(
        "\n# Bug analysis\n\n### Arithmetic <FG-A>\n\n#### Add <FC-A>\n\n"
        "##### Output <CK-A>\n\n###### Finding <BG-RESULT-80>\n\nAnalysis.\n",
        encoding="utf-8",
    )
    (tmp_path / "static.md").write_text("\n# Static analysis\n", encoding="utf-8")
    recorder = Recorder(
        type="bug", data_key="BUG_RECORDS", bug_file="bugs.md",
        static_bug_file="static.md",
    ).set_workspace(str(tmp_path))
    manager = state.pdb.agent.stage_manager
    data = {"BUG_RECORDS": [{"bug_name": "RESULT", "desc": "Accepted conclusion."}]}
    saves = []
    manager.set_data = data.__setitem__
    manager.save_stage_info = lambda: saves.append(True)
    recorder.set_stage_manager(manager)
    recorder.type_handler.on_init()
    old_references = recorder.type_handler._expected_bugs["RESULT"]["ref"]
    if separate_stage:
        manager.stages.append(SimpleNamespace(name="record", checker=[recorder]))
    else:
        state.stage.checker.append(recorder)

    def refresh(*args, **kwargs):
        """Model an evidence refresh that changes accepted document line references."""
        bug_document.write_bytes(b"\n" + bug_document.read_bytes())
        if failure is not None:
            raise failure
        return True, "Current waveform evidence refreshed."

    monkeypatch.setattr(waveform_report, "check_all_documented_waveform_bug_analysis", refresh)
    state.pdb.execute_command("waveform_replay")
    assert data["BUG_RECORDS"] is None
    assert saves == [True]
    assert recorder.type_handler._expected_bugs["RESULT"]["ref"] != old_references
    assert not state.pdb._waveform_replay_lock.locked()
    log = state.pdb.render_console_entries_since(0)
    assert "Invalidated previously recorded Bug data" in log
    assert ("[waveform_replay] SUCCESS" in log) is (failure is None)


def test_waveform_replay_reanalysis_requires_current_static_links(
    waveform_replay_pdb, tmp_path
):
    """Deleting a dynamic finding cannot leave a dangling static confirmation and still pass."""
    from ucagent.checkers.static_bug import UnityChipCheckerStaticBugValidation

    state = waveform_replay_pdb
    (tmp_path / "checks.md").write_text("<FG-A>\n<FC-A>\n<CK-A>\n", encoding="utf-8")
    (tmp_path / "dut.v").write_text("module dut; endmodule\n", encoding="utf-8")
    static_document = tmp_path / "static.md"
    static_document.write_text(
        "<STATIC-BUG-SUMMARY>\n<STATIC-BUG-DETAILS>\n<FG-A>\n<FC-A>\n<CK-A>\n"
        "<BG-STATIC-ONE>\n<LINK-BUG-[BG-OLD-80]>\n<FILE-dut.v:1-1>\n<STATIC-BUG-PROGRESS>\n",
        encoding="utf-8",
    )
    static_checker = UnityChipCheckerStaticBugValidation(
        static_doc="static.md", bug_analysis_doc="bugs.md", functions_and_checks_doc="checks.md"
    ).set_workspace(str(tmp_path))
    state.pdb.agent.stage_manager.stages.insert(0, SimpleNamespace(
        name="static_bug_validation", checker=[static_checker]
    ))
    state.test_result = (False, {"error": "The current corrected TC no longer proves BG-OLD-80."})
    prompts = []

    def reanalyze(prompt):
        """First remove the disproved Bug, then resolve its remaining static confirmation."""
        prompts.append(prompt)
        if len(prompts) == 1:
            (tmp_path / "bugs.md").write_text("\n# Current analysis\n", encoding="utf-8")
            state.test_result = (True, {})
        else:
            assert "BG-OLD-80" in prompt
            assert "not found" in prompt
            static_document.write_text(
                static_document.read_text(encoding="utf-8").replace("[BG-OLD-80]", "[BG-NA]"),
                encoding="utf-8",
            )

    state.pdb.agent.custom_chat = reanalyze
    state.pdb.execute_command("waveform_replay --reanalyze --max-rounds 2")
    log = state.pdb.render_console_entries_since(0)
    assert "[waveform_replay] SUCCESS" in log, log
    assert "Validating static Bug links in 'static.md'" in log
    assert len(prompts) == 2
    assert len(state.test_calls) == 3
    assert "[BG-OLD-80]" not in static_document.read_text(encoding="utf-8")
    assert "<BG-STATIC-ONE>" in static_document.read_text(encoding="utf-8")


def test_execute_command_tracks_foreground_command(probe_pdb):
    probe_pdb.execute_command("probe demo")

    assert probe_pdb.running_snapshots == [["probe demo"]]
    assert probe_pdb.get_running_commands() == []


def test_execute_command_does_not_track_tui_itself(probe_pdb):
    probe_pdb.execute_command("tui")

    assert probe_pdb.running_snapshots == [[]]
    assert probe_pdb.get_running_commands() == []


def test_cancel_running_sleep_returns_quickly(probe_pdb):
    errors: list[BaseException] = []

    def run_sleep():
        try:
            probe_pdb.execute_command("sleep 5")
        except KeyboardInterrupt:
            pass
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_sleep)
    started = time.monotonic()
    worker.start()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if probe_pdb.get_running_commands() == ["sleep 5"]:
            break
        time.sleep(0.01)

    assert probe_pdb.get_running_commands() == ["sleep 5"]
    assert probe_pdb.cancel_last_running_command() is True

    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    assert probe_pdb.get_running_commands() == []
    assert time.monotonic() - started < 1.5


def test_execute_command_records_shared_console_transcript(probe_pdb):
    probe_pdb.execute_command("probeout demo")

    assert probe_pdb.get_console_entry_count() == 2
    assert probe_pdb.render_console_entries_since(0) == "> probeout demo\nprobe output\n"


def test_info_output_outside_command_is_recorded(probe_pdb):
    info("shared info output")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "INFO" in rendered
    assert "shared info output" in rendered


def test_chcwd_controls_pdb_and_shell_command_cwd(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    subdir = workspace / "subdir"
    nested = subdir / "nested"
    subdir.mkdir(parents=True)
    nested.mkdir()
    (subdir / "marker.txt").write_text("demo", encoding="utf-8")
    (nested / "deep.txt").write_text("nested", encoding="utf-8")

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    process_cwd = os.getcwd()
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        pdb.execute_command("chcwd subdir")
        assert pdb._command_cwd == str(subdir)
        assert os.getcwd() == process_cwd

        pdb.execute_command("pwd")
        output = capsys.readouterr().out
        assert f"Current working directory: {subdir}" in output

        pdb.execute_command("ls")
        output = capsys.readouterr().out
        assert "marker.txt" in output

        pdb.execute_command("shell pwd")
        output = capsys.readouterr().out
        assert f"Working directory: {subdir}" in output
        assert str(subdir) in output
        assert os.getcwd() == process_cwd

        pdb.execute_command("chcwd .")
        assert pdb._command_cwd == str(workspace)

        completions = pdb.complete_cd("subdir/", "cd subdir/", 3, len("cd subdir/"))
        assert "subdir/nested/" in completions
        assert "subdir/marker.txt" not in completions

        pdb.execute_command("cd subdir")
        assert pdb._command_cwd == str(subdir)

        pdb.execute_command("cd .")
        assert pdb._command_cwd == str(subdir)

        pdb.execute_command("cd")
        assert pdb._command_cwd == str(workspace)

        pdb.execute_command("shell pwd")
        output = capsys.readouterr().out
        assert f"Working directory: {workspace}" in output
        assert str(workspace) in output
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_cmd_timeout_command_shows_and_sets_idle_timeout(probe_pdb, capsys):
    probe_pdb.execute_command("cmd_timeout")
    output = capsys.readouterr().out
    assert "Shell command idle timeout: 1200 seconds" in output

    probe_pdb.execute_command("cmd_timeout 1.5")
    output = capsys.readouterr().out
    assert "Shell command idle timeout set to 1.5 seconds." in output
    assert probe_pdb._cmd_idle_timeout == 1.5

    probe_pdb.execute_command("cmd_timeout off")
    output = capsys.readouterr().out
    assert "Shell command idle timeout set to disabled." in output
    assert probe_pdb._cmd_idle_timeout == 0


def test_readline_completion_binding_uses_libedit_syntax(probe_pdb, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(readline, "__doc__", "Importing this module enables command line editing using libedit readline.")
    monkeypatch.setattr(readline, "parse_and_bind", calls.append)

    probe_pdb._bind_readline_completion()

    assert calls == ["bind ^I rl_complete"]
    assert probe_pdb._readline_completion_bind_command() == "bind ^I rl_complete"


def test_readline_completion_binding_uses_gnu_syntax(probe_pdb, monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(readline, "__doc__", "GNU readline")
    monkeypatch.setattr(readline, "parse_and_bind", calls.append)

    probe_pdb._bind_readline_completion()

    assert calls == ["tab: complete"]
    assert probe_pdb._readline_completion_bind_command() == "tab: complete"


def test_shell_command_runs_while_agent_break_is_set(probe_pdb):
    probe_pdb.agent.set_break(True)

    probe_pdb.execute_command("sh -c 'echo break-ok'")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "break-ok" in _console_output_lines(rendered)
    assert "interrupted" not in rendered


def test_unknown_non_dangerous_command_executes_as_shell(probe_pdb):
    probe_pdb.execute_command("command -v sh")

    rendered = probe_pdb.render_console_entries_since(0)
    assert "/sh" in rendered or rendered.splitlines().count("sh") > 0
    assert "Executing as bash command: command -v sh" in rendered


def test_shell_command_completion_whitelist_and_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "demo.txt").write_text("demo", encoding="utf-8")

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        assert "pytest" in pdb.api_all_cmds("py")
        assert "pytest" in pdb.completenames("py")
        assert "rm" not in pdb.api_all_cmds("r")

        completions = pdb.completedefault("de", "pytest de", len("pytest "), len("pytest de"))
        assert "demo.txt" in completions

        shell_completions = pdb.complete_shell("de", "shell pytest de", len("shell pytest "), len("shell pytest de"))
        assert "demo.txt" in shell_completions
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_shell_command_streams_output_before_completion(probe_pdb):
    code = (
        "import time; "
        "print('stream-first', flush=True); "
        "time.sleep(1.5); "
        "print('stream-second', flush=True)"
    )
    command = f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    errors: list[BaseException] = []

    def run_command():
        try:
            probe_pdb.execute_command(command)
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_command)
    worker.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            rendered = probe_pdb.render_console_entries_since(0)
            if "stream-first" in rendered:
                break
            time.sleep(0.02)

        rendered = probe_pdb.render_console_entries_since(0)
        assert "stream-first" in rendered
        assert worker.is_alive()
        assert "stream-second" not in _console_output_lines(rendered)
    finally:
        worker.join(timeout=3.0)
        if worker.is_alive():
            probe_pdb.cancel_last_running_command()
            worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    rendered = probe_pdb.render_console_entries_since(0)
    assert "stream-second" in _console_output_lines(rendered)
    assert "Command completed successfully" in rendered


def test_shell_command_pty_streams_line_buffered_output(probe_pdb):
    code = (
        "import time; "
        "print('line-buffered-first'); "
        "time.sleep(1.5); "
        "print('line-buffered-second')"
    )
    command = f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    errors: list[BaseException] = []

    def run_command():
        try:
            probe_pdb.execute_command(command)
        except BaseException as exc:  # pragma: no cover - debugging aid
            errors.append(exc)

    worker = threading.Thread(target=run_command)
    worker.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
            if "line-buffered-first" in output_lines:
                break
            time.sleep(0.02)

        output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
        assert "line-buffered-first" in output_lines
        assert worker.is_alive()
        assert "line-buffered-second" not in output_lines
    finally:
        worker.join(timeout=3.0)
        if worker.is_alive():
            probe_pdb.cancel_last_running_command()
            worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert not errors
    output_lines = _console_output_lines(probe_pdb.render_console_entries_since(0))
    assert "line-buffered-second" in output_lines


def test_shell_idle_timeout_resets_after_output(probe_pdb):
    probe_pdb._cmd_idle_timeout = 1.0
    code = (
        "import time\n"
        "for idx in range(4):\n"
        "    print(f'tick-{idx}', flush=True)\n"
        "    time.sleep(0.35)\n"
        "print('still-alive', flush=True)\n"
    )

    probe_pdb.execute_command(
        f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    )

    rendered = probe_pdb.render_console_entries_since(0)
    output_lines = _console_output_lines(rendered)
    assert "tick-0" in output_lines
    assert "tick-3" in output_lines
    assert "still-alive" in output_lines
    assert "timed out" not in rendered


def test_shell_idle_timeout_kills_quiet_command(probe_pdb):
    probe_pdb._cmd_idle_timeout = 0.4
    code = (
        "import time; "
        "print('quiet-start', flush=True); "
        "time.sleep(5); "
        "print('quiet-late', flush=True)"
    )

    started = time.monotonic()
    probe_pdb.execute_command(
        f"shell {shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    )

    rendered = probe_pdb.render_console_entries_since(0)
    output_lines = _console_output_lines(rendered)
    assert time.monotonic() - started < 2.0
    assert "quiet-start" in output_lines
    assert "quiet-late" not in output_lines
    assert "timed out after 0.4 seconds without output" in rendered


def test_chcwd_rejects_paths_outside_workspace(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(_FakeAgent(workspace=str(workspace)))
    try:
        pdb.execute_command(f"chcwd {outside}")
        output = capsys.readouterr().out

        assert "outside the workspace" in output
        assert pdb._command_cwd == str(workspace)
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_add_un_write_path_accepts_wildcard_pattern(tmp_path, capsys):
    """Wildcard no-write patterns register at runtime without existing on disk."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = _FakeAgent(workspace=str(workspace))
    agent.cfg = types.SimpleNamespace(un_write_dirs=[], write_dirs=[])

    previous_signal = signal.getsignal(signal.SIGINT)
    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    pdb = _ProbePDB(agent)
    try:
        ok, normalized = pdb.api_is_valid_workspace_path("DUT/*.v")
        assert ok is True
        assert normalized == "DUT/*.v"

        pdb.do_add_un_write_path("DUT/*.v")
        assert "DUT/*.v" in agent.cfg.un_write_dirs
        output = capsys.readouterr().out
        assert "already in the non-writable" not in output

        ok, reason = pdb.api_is_valid_workspace_path("missing_dir")
        assert ok is False
        assert "does not exist" in reason
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        sys.stdout = previous_stdout
        sys.stderr = previous_stderr


def test_add_cmds_falls_back_when_tui_app_stopped(probe_pdb):
    class _DeadKeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("stopped app should not process commands")

    class _DeadApp:
        key_handler = _DeadKeyHandler()

        def call_from_thread(self, *_args, **_kwargs):
            raise RuntimeError("App is not running")

    probe_pdb._in_tui = True
    probe_pdb._tui_app = _DeadApp()

    probe_pdb.add_cmds(["sleep 5", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit"]


def test_add_cmds_with_exit_in_tui_defers_to_pdb_queue(probe_pdb):
    class _KeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("exit batches should not be executed inside the TUI")

    class _App:
        def __init__(self):
            self.key_handler = _KeyHandler()
            self.quit_requested = 0

        def call_from_thread(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        def action_quit(self):
            self.quit_requested += 1

    app = _App()
    probe_pdb._in_tui = True
    probe_pdb._tui_app = app

    probe_pdb.add_cmds(["sleep 5", "quit", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit", "quit"]
    assert app.quit_requested == 1


def test_add_cmds_with_exit_handles_stopped_tui_app(probe_pdb):
    class _KeyHandler:
        def process_command(self, _cmd):
            raise AssertionError("stopped app should not process commands")

    class _DeadApp:
        def __init__(self):
            self.key_handler = _KeyHandler()

        def call_from_thread(self, *_args, **_kwargs):
            raise RuntimeError("App is not running")

        def action_quit(self):
            raise AssertionError("stopped app should not quit synchronously")

    probe_pdb._in_tui = True
    probe_pdb._tui_app = _DeadApp()

    probe_pdb.add_cmds(["sleep 5", "quit"])

    assert probe_pdb.init_cmd == ["sleep 5", "quit"]


def test_exit_cleans_owned_xpra_sessions_when_workspace_sync_fails(monkeypatch):
    """Exit must reap GUI applications and restore modes even after sync errors."""
    events = []
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._is_exit = False
    agent.cwd_read_only_files = ["tracked-file"]
    agent.pdb = SimpleNamespace(_cmd_api_server=SimpleNamespace(
        close_sessions=lambda: events.append("closed")))

    def fail_sync():
        """Represent an unavailable destination during the normal exit path."""
        raise OSError("workspace sync failed")

    agent._sync_workspace_back_on_exit = fail_sync
    monkeypatch.setattr("ucagent.verify_agent.fc.chmode_rw", lambda files: events.append(files))
    with pytest.raises(OSError, match="workspace sync failed"):
        agent.exit()
    assert events == ["closed", ["tracked-file"]]
    agent.exit()
    assert len(events) == 2


def test_exit_on_completion_defers_until_work_finishes():
    class _PdbRecorder:
        def __init__(self):
            self.cmds = []

        def add_cmds(self, cmds):
            self.cmds.append(cmds)

    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion = True
    agent._exit_on_completion_pending = False
    agent._exit_on_completion_queued = False
    agent._is_work_busy = False
    agent._need_break = True
    agent.stream_output = False
    agent.pdb = _PdbRecorder()

    def do_work_values(_instructions, _config):
        assert agent.is_work_busy()
        agent.try_exit_on_completion()
        assert agent.pdb.cmds == []

    agent.do_work_values = do_work_values

    agent.do_work({}, {})

    assert agent._need_break is False
    assert agent.pdb.cmds == [["sleep 5", "quit", "quit", "quit"]]


def test_do_work_recovers_pending_tool_calls_before_reraising():
    class _Backend:
        def __init__(self):
            self.errors = []

        def recover_pending_tool_calls(self, error):
            self.errors.append(error)
            return 1

    agent = VerifyAgent.__new__(VerifyAgent)
    agent._exit_on_completion_pending = False
    agent._is_work_busy = False
    agent.stream_output = False
    agent.backend = _Backend()

    def fail_work(_instructions, _config):
        raise RuntimeError("tool execution failed")

    agent.do_work_values = fail_work

    with pytest.raises(RuntimeError, match="tool execution failed"):
        agent.do_work({}, {})

    assert len(agent.backend.errors) == 1
    assert agent.is_work_busy() is False


def test_loop_retry_budget_is_not_refreshed_without_agent_progress(probe_pdb):
    calls = 0
    probe_pdb.max_loop_retry = 2
    probe_pdb.retry_delay_start = 0
    probe_pdb.retry_delay_end = 0
    probe_pdb.loop_alive_time = -1
    probe_pdb.agent.invoke_round = 0

    def fail_without_progress(_message):
        nonlocal calls
        calls += 1
        if calls >= 3:
            probe_pdb.agent.set_break(True)
        raise RuntimeError("deterministic failure")

    probe_pdb.agent.run_loop = fail_without_progress

    probe_pdb.do_loop("")

    assert calls == 2


def test_loop_retry_budget_can_refresh_after_agent_progress(probe_pdb):
    calls = 0
    probe_pdb.max_loop_retry = 2
    probe_pdb.retry_delay_start = 0
    probe_pdb.retry_delay_end = 0
    probe_pdb.loop_alive_time = -1
    probe_pdb.agent.invoke_round = 0

    def fail_after_progress(_message):
        nonlocal calls
        calls += 1
        probe_pdb.agent.invoke_round += 1
        if calls >= 3:
            probe_pdb.agent.set_break(True)
        raise RuntimeError("failure after progress")

    probe_pdb.agent.run_loop = fail_after_progress

    probe_pdb.do_loop("")

    assert calls == 3


def _failure_result(error="same actionable failure"):
    return {
        "check_pass": False,
        "failure_summary": {
            "stage_index": 19,
            "stage_name": "generate_random_test_cases",
            "failed_validation_gate_index": 0,
            "error_code": "TEST_REPORT_MISMATCH",
            "error": error,
            "next_action": "Repair the reported artifact and call Check again.",
        },
    }


def _stall_probe(max_stalled_rounds=3):
    agent = VerifyAgent.__new__(VerifyAgent)
    agent._max_stalled_rounds = max_stalled_rounds
    agent._stalled_rounds = 0
    agent._last_stall_signature = None
    agent._need_human = False
    agent.stage_manager = SimpleNamespace(
        validation_revision=0,
        stage_index=19,
        last_check_info={},
    )
    return agent


def _record_validation_round(agent, result, stage_index=19):
    previous_revision = agent.stage_manager.validation_revision
    previous_stage_index = agent.stage_manager.stage_index
    agent.stage_manager.validation_revision += 1
    agent.stage_manager.stage_index = stage_index
    agent.stage_manager.last_check_info = result
    agent._update_stalled_rounds(previous_revision, previous_stage_index)


def test_unchanged_checker_diagnostic_pauses_agent_loop():
    agent = _stall_probe(max_stalled_rounds=3)

    for _ in range(3):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 3
    assert agent._need_human is True


def test_changed_checker_diagnostic_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)

    _record_validation_round(agent, _failure_result())
    _record_validation_round(agent, _failure_result("different actionable failure"))

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_dynamic_summary_metadata_does_not_hide_unchanged_failure():
    agent = _stall_probe(max_stalled_rounds=2)
    first = _failure_result()
    second = _failure_result()
    first["failure_summary"]["details"] = {"attempt": 1}
    second["failure_summary"]["details"] = {"attempt": 2}

    _record_validation_round(agent, first)
    _record_validation_round(agent, second)

    assert agent._stalled_rounds == 2
    assert agent._need_human is True


def test_validation_progress_resets_stalled_round_count():
    agent = _stall_probe(max_stalled_rounds=3)
    _record_validation_round(agent, _failure_result())

    _record_validation_round(
        agent,
        {"check_pass": False, "progress_summary": {"status": "batch_advanced"}},
    )

    assert agent._stalled_rounds == 0
    assert agent._last_stall_signature is None


def test_round_without_new_validation_does_not_count_as_stalled():
    agent = _stall_probe(max_stalled_rounds=2)
    _record_validation_round(agent, _failure_result())

    revision = agent.stage_manager.validation_revision
    agent._update_stalled_rounds(revision, agent.stage_manager.stage_index)

    assert agent._stalled_rounds == 1
    assert agent._need_human is False


def test_disabled_stall_protection_does_not_pause_agent():
    agent = _stall_probe(max_stalled_rounds=0)

    for _ in range(4):
        _record_validation_round(agent, _failure_result())

    assert agent._stalled_rounds == 0
    assert agent._need_human is False


def test_default_config_disables_stalled_checker_pause():
    """Keep automatic Checker-stall escalation opt-in at repository defaults."""
    config_path = os.path.join(current_dir, "..", "ucagent", "setting.yaml")

    config = load_yaml_with_env_vars(config_path)

    assert config["loop_settings"]["max_stalled_rounds"] == 0


def test_swarm_launch_does_not_force_human_check():
    """Keep the example human-check injection documented but inactive."""

    makefile_path = os.path.join(current_dir, "..", "Makefile")
    with open(makefile_path, encoding="utf-8") as makefile_handle:
        makefile = makefile_handle.read()
    override = (
        "--override launch.default_args.extra_args[0:0]=@base64:"
        "LS1vdmVycmlkZQpzdGFnZVstMV0ubmVlZF9odW1hbl9jaGVjaz1UcnVl"
    )
    active_lines = [
        line for line in makefile.splitlines() if not line.lstrip().startswith("#")
    ]

    assert override not in "\n".join(active_lines)
    assert any(
        override in line and line.lstrip().startswith("#")
        for line in makefile.splitlines()
    )


@pytest.mark.parametrize("value", [True, -1, 1.5, "3", None])
def test_max_stalled_rounds_rejects_ambiguous_values(value):
    with pytest.raises(ValueError, match="max_stalled_rounds"):
        VerifyAgent._validated_max_stalled_rounds(value)


@pytest.mark.parametrize("value", [0, 1, 3])
def test_max_stalled_rounds_accepts_non_negative_integers(value):
    assert VerifyAgent._validated_max_stalled_rounds(value) == value
