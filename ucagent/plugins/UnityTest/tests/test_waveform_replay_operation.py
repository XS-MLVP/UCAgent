"""Migrated domain regression suite for standalone waveform replay and evidence repair."""

import io
import shlex
import threading
import time
import types
from contextlib import redirect_stdout
from types import SimpleNamespace
import pytest

from ucagent.util.config import Config
from unity_test.operations.waveform_replay import WaveformReplay


class ProbeReplay(WaveformReplay):
    """Capture domain diagnostics without constructing a debugger or changing global signals."""

    def __init__(self):
        """Provide the minimal controllable model boundary used by domain gate tests."""
        agent = SimpleNamespace(cfg=Config({}), backend=object(), test_tools=[], _break=False)
        agent.is_work_busy = lambda: False
        agent.is_break = lambda: agent._break
        agent.set_break = lambda value=True: setattr(agent, "_break", value)
        super().__init__(agent)
        self.output = io.StringIO()

    def execute_command(self, line):
        """Run the plugin operation directly while retaining its diagnostic output."""
        with redirect_stdout(self.output):
            return self.run(line.partition(" ")[2])

    def render_console_entries_since(self, index=0):
        """Return captured logs for the existing evidence and recovery assertions."""
        return self.output.getvalue()


@pytest.fixture
def probe_replay():
    """Create an isolated plugin operation for each domain regression."""
    return ProbeReplay()


@pytest.fixture
def waveform_runtime(probe_replay, tmp_path, monkeypatch):
    """Wire real configured gate types to controllable test and replay results."""
    import unity_test.checkers.waveform as waveform_checker_module
    from unity_test.checkers.waveform import UnityChipCheckerWaveformBugAnalysis
    from unity_test.checkers.unity_test import UnityChipCheckerTestCase
    from unity_test.checkers.recorder import Recorder
    from unity_test.checkers.static_bug import UnityChipCheckerStaticBugValidation

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
    monkeypatch.setattr(waveform_checker_module, "check_all_documented_waveform_bug_analysis", replay)
    probe_replay.agent.cfg = SimpleNamespace(call_time_out=240)
    probe_replay.agent.stage_manager = SimpleNamespace(
        workspace=str(tmp_path), stages=[stage], stage_index=0
    )
    probe_replay.agent.get_tool_by_name = state.tools.get
    probe_replay.agent.plugin_checker_registry = {
        UnityChipCheckerWaveformBugAnalysis.__name__: UnityChipCheckerWaveformBugAnalysis,
        UnityChipCheckerTestCase.__name__: UnityChipCheckerTestCase,
        Recorder.__name__: Recorder,
        UnityChipCheckerStaticBugValidation.__name__: UnityChipCheckerStaticBugValidation,
    }
    probe_replay.agent.backend = object()
    probe_replay.agent.test_tools = []
    gate.set_stage_manager(SimpleNamespace(agent=probe_replay.agent))
    state.operation = probe_replay
    return state


@pytest.mark.parametrize("argument, expected_timeout", [("", 240), ("120", 120)])
def test_waveform_replay_runs_full_classification_then_strict_gate(
    waveform_runtime, argument, expected_timeout
):
    """Manual replay uses configured artifacts and reports progress without stage transitions."""
    state = waveform_runtime
    state.operation.execute_command(f"waveform_replay {argument}".strip())

    assert state.test_calls == [{"timeout": expected_timeout}]
    assert len(state.replay_calls) == 1
    args, kwargs = state.replay_calls[0]
    assert args == (state.operation.agent.stage_manager.workspace, "bugs.md")
    assert kwargs["require_current_replay"] is True
    assert kwargs["waveform_test_dir"] == "tests"
    assert kwargs["waveform_tool"] is state.tools["WaveInfo"]
    assert kwargs["waveform_evidence_tool"] is state.tools["ApplyWaveInfoEvidence"]
    log = state.operation.render_console_entries_since(0)
    assert "DUT test classification PASSED" in log
    assert "[1/2] Replaying 'tests/test_a.py::test_a'" in log
    assert "[2/2] Replaying 'tests/test_b.py::test_b'" in log
    assert "Automatically refreshed 2" in log
    assert "[waveform_replay] SUCCESS" in log
    assert state.operation.agent.stage_manager.stage_index == 0
    assert state.classifier.is_in_check is False
    assert state.gate.is_in_check is False


@pytest.mark.parametrize("argument", ["0", "-1", "bad", "1.5", "10 20"])
def test_waveform_replay_rejects_invalid_timeout(waveform_runtime, argument):
    """Invalid command arguments fail before tests or evidence writes begin."""
    state = waveform_runtime
    state.operation.execute_command(f"waveform_replay {argument}")
    log = state.operation.render_console_entries_since(0)
    assert "FAILED during configuration" in log
    assert "waveform_replay [timeout_seconds]" in log
    assert not state.test_calls
    assert not state.replay_calls


@pytest.mark.parametrize("gate_count", [0, 2])
def test_waveform_replay_rejects_missing_or_ambiguous_gates(waveform_runtime, gate_count):
    """Configuration ambiguity never selects an arbitrary waveform document."""
    state = waveform_runtime
    state.stage.checker = [state.classifier] + [state.gate] * gate_count
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    assert f"found {gate_count}" in log
    assert "require_current_replay=true" in log
    assert not state.test_calls
    assert not state.replay_calls


def test_waveform_replay_requires_matching_preceding_classification(waveform_runtime):
    """A test runner for another document cannot authorize the selected replay."""
    state = waveform_runtime
    state.classifier.doc_bug_analysis = "other_bugs.md"
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    assert "preceding DUT test classification checker" in log
    assert "bugs.md" in log
    assert not state.test_calls
    assert not state.replay_calls


@pytest.mark.parametrize("tool_name", ["WaveInfo", "ApplyWaveInfoEvidence"])
def test_waveform_replay_requires_evidence_tools(waveform_runtime, tool_name):
    """Missing evidence tools are diagnosed before rerunning tests."""
    state = waveform_runtime
    del state.tools[tool_name]
    state.operation.execute_command("waveform_replay")
    assert "Enable WaveInfo and ApplyWaveInfoEvidence" in state.operation.render_console_entries_since(0)
    assert not state.test_calls
    assert not state.replay_calls


def test_waveform_replay_preserves_test_failure_diagnostic(waveform_runtime):
    """A classification failure reports its exact artifact and blocks replay."""
    state = waveform_runtime
    state.test_result = (False, {
        "error": "tests/test_a.py:42 fixture failure",
        "next_action": "Repair the env fixture, then rerun.",
    })
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    assert "DUT test classification failed" in log
    assert "tests/test_a.py:42 fixture failure" in log
    assert "Repair the env fixture" in log
    assert not state.replay_calls
    assert "[waveform_replay] SUCCESS" not in log


def test_waveform_replay_preserves_complete_batch_review_diagnostic(waveform_runtime):
    """Semantic changes remain failures with their actionable batch call intact."""
    state = waveform_runtime
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
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    assert "[waveform_replay] FAILED after" in log
    assert "WAVEFORM_SEMANTIC_BATCH_REVIEW_REQUIRED" in log
    assert "ReviewWaveInfoEvidenceBatch" in log
    assert "TC-tests/test_a.py::test_a" in log
    assert "TC-tests/test_b.py::test_b" in log
    assert "Review all returned items together" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("failure", [OSError("disk is read-only"), KeyboardInterrupt()])
def test_waveform_replay_reports_exception_and_cancellation_context(
    waveform_runtime, monkeypatch, failure
):
    """Unexpected replay failures and cancellation preserve the current TC in logs."""
    import unity_test.checkers.waveform as waveform_checker_module

    def fail_replay(*args, **kwargs):
        """Simulate a failure while replaying a known test."""
        kwargs["progress_callback"]("[1/2] Replaying 'tests/test_a.py::test_a'.")
        raise failure

    state = waveform_runtime
    monkeypatch.setattr(waveform_checker_module, "check_all_documented_waveform_bug_analysis", fail_replay)
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    status = "CANCELLED" if isinstance(failure, KeyboardInterrupt) else "FAILED"
    assert f"[waveform_replay] {status}" in log
    assert "tests/test_a.py::test_a" in log
    if isinstance(failure, OSError):
        assert "disk is read-only" in log
    assert "[waveform_replay] SUCCESS" not in log
    assert state.gate.is_in_check is False


@pytest.mark.parametrize("checker_name", ["classifier", "gate"])
def test_waveform_replay_rejects_an_active_check(waveform_runtime, checker_name):
    """Active test or waveform checks prevent overlapping manual replay operations."""
    state = waveform_runtime
    checker = getattr(state, checker_name)
    checker.is_in_check = True
    state.operation.execute_command("waveform_replay")
    log = state.operation.render_console_entries_since(0)
    assert "already running" in log
    assert not state.test_calls
    assert not state.replay_calls
    assert checker.is_in_check is True


def test_waveform_replay_cancels_running_test_process(waveform_runtime, monkeypatch):
    """Cancelling during test execution kills the tracked process and resets its state."""
    state = waveform_runtime
    killed = []

    def cancel_tests(**kwargs):
        """Attach a running process before simulating a user interrupt."""
        state.classifier.set_check_process(
            SimpleNamespace(pid=123, kill=lambda: killed.append(True)), kwargs["timeout"]
        )
        raise KeyboardInterrupt()

    monkeypatch.setattr(state.classifier, "do_check", cancel_tests)
    state.operation.execute_command("waveform_replay")
    assert killed == [True]
    assert state.classifier.is_in_check is False
    assert state.classifier._process is None
    assert not state.replay_calls
    assert "CANCELLED during: Running the full DUT test classification check" in state.operation.render_console_entries_since(0)


@pytest.mark.parametrize("skills_enabled", [False, True])
@pytest.mark.parametrize("failure_scope", ["classification", "waveform"])
def test_waveform_replay_reanalyzes_failures_and_revalidates(
    waveform_runtime, skills_enabled, failure_scope
):
    """Both failure sources reach the configured LLM with canonical repair/removal rules."""
    state = waveform_runtime
    state.operation.agent.cfg.skill = SimpleNamespace(use_skill=skills_enabled)
    diagnostic = {"error": "TC-tests/test_a.py::test_a changed", "requires_bug_reanalysis": True}
    if failure_scope == "classification":
        state.test_result = (False, diagnostic)
    else:
        state.replay_result = (False, diagnostic)
    prompts = []
    state.operation.agent.set_break(True)

    def reanalyze(prompt):
        """Represent one backend turn that repairs actual inputs before revalidation."""
        assert state.operation.agent.is_break() is False
        prompts.append(prompt)
        state.test_result = (True, {"success": "Current tests classified."})
        state.replay_result = (True, {"success": "Current Bug evidence validated."})

    state.operation.agent.custom_chat = reanalyze
    state.operation.execute_command("waveform_replay 120 --reanalyze --max-rounds 2")

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
    log = state.operation.render_console_entries_since(0)
    assert "LLM REANALYSIS round 1/2" in log
    assert "revalidating actual artifacts" in log
    assert "[waveform_replay] SUCCESS" in log
    assert "LLM reanalysis rounds=1" in log
    assert state.operation.agent.is_break() is True
    assert state.operation.agent.stage_manager.stage_index == 0


def test_waveform_replay_reanalysis_requires_opt_in_and_an_actual_failure(waveform_runtime):
    """A successful replay never consumes a model turn even with reanalysis enabled."""
    state = waveform_runtime
    prompts = []
    state.operation.agent.custom_chat = prompts.append
    state.operation.execute_command("waveform_replay --reanalyze")
    assert not prompts
    assert "LLM reanalysis rounds=0" in state.operation.render_console_entries_since(0)


@pytest.mark.parametrize("arguments", [
    "--max-rounds 2", "--reanalyze --max-rounds", "--reanalyze --max-rounds 0",
    "--reanalyze --max-rounds -2", "--reanalyze --max-rounds bad", "--unknown",
])
def test_waveform_replay_rejects_invalid_reanalysis_arguments(waveform_runtime, arguments):
    """Invalid recovery options stop before any tests or model work."""
    state = waveform_runtime
    state.operation.execute_command(f"waveform_replay {arguments}")
    assert "FAILED during configuration" in state.operation.render_console_entries_since(0)
    assert not state.test_calls


def test_waveform_replay_reanalysis_limit_cannot_be_bypassed_by_llm_claims(waveform_runtime):
    """Model assertions of success cannot replace passing artifact checks."""
    state = waveform_runtime
    state.test_result = (False, {"error": "Still-failing unrecorded DUT Bug."})
    prompts = []
    state.operation.agent.custom_chat = lambda prompt: prompts.append(prompt) or "Everything is fixed."
    state.operation.execute_command("waveform_replay --reanalyze --max-rounds 2")
    assert len(prompts) == 2
    assert len(state.test_calls) == 3
    log = state.operation.render_console_entries_since(0)
    assert "LLM reanalysis limit (2) reached" in log
    assert "Still-failing unrecorded DUT Bug" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("unavailable", ["blank", "busy"])
def test_waveform_replay_reanalysis_rejects_unavailable_backend(
    waveform_runtime, unavailable
):
    """Disabled or busy model work leaves the original diagnostic visible."""
    from ucagent.abackend.blank import BlankBackend

    state = waveform_runtime
    state.test_result = (False, {"error": "Current TC needs reanalysis."})
    if unavailable == "blank":
        state.operation.agent.backend = BlankBackend(state.operation.agent, object())
    else:
        state.operation.agent.is_work_busy = lambda: True
    state.operation.execute_command("waveform_replay --reanalyze")
    log = state.operation.render_console_entries_since(0)
    if unavailable == "blank":
        assert "Current TC needs reanalysis" in log
        assert "disables model work" in log
    else:
        assert "LLM is already working" in log
        assert not state.test_calls
        assert not state.replay_calls
    assert "[waveform_replay] SUCCESS" not in log


def test_waveform_replay_rejects_model_work_before_running_tests(waveform_runtime):
    """Manual replay cannot rotate test artifacts underneath an active model turn."""
    state = waveform_runtime
    state.operation.agent.is_work_busy = lambda: True
    state.operation.execute_command("waveform_replay")
    assert not state.test_calls
    assert not state.replay_calls
    assert not state.operation._waveform_replay_lock.locked()
    log = state.operation.render_console_entries_since(0)
    assert "LLM is already working" in log
    assert "[waveform_replay] SUCCESS" not in log


@pytest.mark.parametrize("failure", [None, OSError("model unavailable"), KeyboardInterrupt()])
def test_waveform_replay_guards_stage_tools_and_restores_state(
    waveform_runtime, failure
):
    """Stage callbacks stay blocked through direct/local calls and restore on every exit."""
    from ucagent.stage.vmanager import ToolDoCheck, ToolDoComplete, ToolGoToStage, ToolDoExit, ToolCurrentTips

    state = waveform_runtime
    state.test_result = (False, {"error": "Reanalyze the changed TC."})
    calls = []

    def original(*args, **kwargs):
        """Record any stage mutation that must remain blocked during recovery."""
        calls.append((args, kwargs))
        return "Original stage behavior."

    tools = [tool().set_function(original) for tool in (
        ToolDoCheck, ToolDoComplete, ToolGoToStage, ToolDoExit, ToolCurrentTips
    )]
    state.operation.agent.test_tools = tools
    state.operation.agent.set_break(True)

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

    state.operation.agent.custom_chat = reanalyze
    state.operation.execute_command("waveform_replay --reanalyze")
    assert not calls
    assert all(tool.function is original for tool in tools)
    assert state.operation.agent.is_break() is True
    assert state.operation._waveform_replay_lock.locked() is False
    log = state.operation.render_console_entries_since(0)
    if failure is None:
        assert "[waveform_replay] SUCCESS" in log
    else:
        assert "[waveform_replay] SUCCESS" not in log
        assert "CANCELLED" in log if isinstance(failure, KeyboardInterrupt) else "model unavailable" in log


def test_waveform_replay_rejects_overlapping_command(waveform_runtime):
    """One replay command owns classification, model turns and evidence refresh together."""
    state = waveform_runtime
    with state.operation._waveform_replay_lock:
        state.operation.execute_command("waveform_replay --reanalyze")
    assert not state.test_calls
    assert "Another waveform_replay command is already running" in state.operation.render_console_entries_since(0)


@pytest.mark.parametrize("model_fails_after_edit", [False, True])
def test_waveform_replay_invalidates_recorded_bugs_after_reanalysis_edits(
    waveform_runtime, tmp_path, model_fails_after_edit
):
    """Old stored findings cannot repopulate summaries after removal, even on model failure."""
    from unity_test.checkers.recorder import Recorder

    state = waveform_runtime
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
    manager = state.operation.agent.stage_manager
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

    state.operation.agent.custom_chat = reanalyze
    state.operation.execute_command("waveform_replay --reanalyze")
    assert data["BUG_RECORDS"] is None
    assert recorder.type_handler._expected_bugs == {}
    assert saves == [True]
    log = state.operation.render_console_entries_since(0)
    assert "Invalidated previously recorded Bug data" in log
    assert ("[waveform_replay] SUCCESS" in log) is not model_fails_after_edit


@pytest.mark.parametrize("failure", [None, OSError("refresh failed after write"), KeyboardInterrupt()])
@pytest.mark.parametrize("separate_stage", [False, True])
def test_waveform_replay_invalidates_recorded_bugs_after_automatic_refresh(
    waveform_runtime, tmp_path, monkeypatch, failure, separate_stage
):
    """Automatic writes invalidate all matching Recorder views even on failed replay."""
    import unity_test.checkers.waveform as waveform_checker_module
    from unity_test.checkers.recorder import Recorder

    state = waveform_runtime
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
    manager = state.operation.agent.stage_manager
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

    monkeypatch.setattr(waveform_checker_module, "check_all_documented_waveform_bug_analysis", refresh)
    state.operation.execute_command("waveform_replay")
    assert data["BUG_RECORDS"] is None
    assert saves == [True]
    assert recorder.type_handler._expected_bugs["RESULT"]["ref"] != old_references
    assert not state.operation._waveform_replay_lock.locked()
    log = state.operation.render_console_entries_since(0)
    assert "Invalidated previously recorded Bug data" in log
    assert ("[waveform_replay] SUCCESS" in log) is (failure is None)


def test_waveform_replay_reanalysis_requires_current_static_links(
    waveform_runtime, tmp_path
):
    """Deleting a dynamic finding cannot leave a dangling static confirmation and still pass."""
    from unity_test.checkers.static_bug import UnityChipCheckerStaticBugValidation

    state = waveform_runtime
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
    state.operation.agent.stage_manager.stages.insert(0, SimpleNamespace(
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

    state.operation.agent.custom_chat = reanalyze
    state.operation.execute_command("waveform_replay --reanalyze --max-rounds 2")
    log = state.operation.render_console_entries_since(0)
    assert "[waveform_replay] SUCCESS" in log, log
    assert "Validating static Bug links in 'static.md'" in log
    assert len(prompts) == 2
    assert len(state.test_calls) == 3
    assert "[BG-OLD-80]" not in static_document.read_text(encoding="utf-8")
    assert "<BG-STATIC-ONE>" in static_document.read_text(encoding="utf-8")

