"""Standalone waveform classification, evidence revalidation and bounded model reanalysis."""

from pathlib import Path
import shlex
import threading
import time

from ucagent.runtime.control.commands import Argument, CommandSpec
from ucagent.runtime.operations import OperationCancelled, OperationFailure
from ucagent.util.log import info, echo, echo_r, echo_g, echo_y
from ucagent.util.functions import dump_as_json
from unit_test.checkers.waveform import UnityChipCheckerWaveformBugAnalysis
from unit_test.checkers.unit_test import UnityChipCheckerTestCase
from unit_test.checkers.recorder import Recorder
from unit_test.checkers.static_bug import UnityChipCheckerStaticBugValidation


class WaveformReplay:
    """Use configured domain gates without advancing stages or recording accepted Bugs."""

    def __init__(self, agent):
        """Bind one operation to the assembled agent and its existing verification objects."""
        self.agent = agent
        self._waveform_replay_lock = threading.Lock()

    def run(self, arg, context=None):
        """Rerun DUT tests and refresh all documented Bug waveform evidence.

        Usage: waveform_replay [timeout_seconds] [--reanalyze] [--max-rounds N]
        Uses the unique configured current-replay gate and its preceding test
        classification checker. Defaults to cfg.call_time_out for the test run.
        Changed TCs fail replay even if waveforms match. With --reanalyze, send
        failures to the configured LLM to re-analyze Bugs, repair invalid tests,
        update confirmed Bugs, and remove disproved associations. Revalidate after
        each round (default maximum: 3). No stage completion or Bug recording.
        """
        from ucagent.core.backends.blank import BlankBackend
        from ucagent.core.stage.vmanager import ManagerTool

        BugRecordType_name = "BugRecordType"

        started = time.monotonic()
        step = "configuration"
        acquired = False

        def log_progress(text):
            """Log the current operation so failures retain their exact TC context."""
            nonlocal step
            if context is not None:
                context.checkpoint()
            step = text
            info(f"[waveform_replay] {text}")

        try:
            arguments = shlex.split(arg)
            reanalyze = False
            max_rounds = 3
            timeout_arg = None
            rounds_arg = None
            while arguments:
                token = arguments.pop(0)
                if token == "--reanalyze" and not reanalyze:
                    reanalyze = True
                elif token == "--max-rounds" and rounds_arg is None and arguments:
                    rounds_arg = arguments.pop(0)
                elif token.startswith("--") or timeout_arg is not None:
                    raise ValueError(f"Unexpected or incomplete argument: {token}")
                else:
                    timeout_arg = token
            try:
                timeout = int(timeout_arg) if timeout_arg is not None else self.agent.cfg.call_time_out
            except ValueError:
                raise ValueError("timeout_seconds must be a positive integer") from None
            if type(timeout) is not int or timeout <= 0:
                raise ValueError("timeout_seconds must be a positive integer")
            if rounds_arg is not None:
                if not reanalyze:
                    raise ValueError("--max-rounds requires --reanalyze")
                try:
                    max_rounds = int(rounds_arg)
                except ValueError:
                    raise ValueError("--max-rounds must be a positive integer") from None
                if max_rounds <= 0:
                    raise ValueError("--max-rounds must be a positive integer")
            acquired = self._waveform_replay_lock.acquire(blocking=False)
            if not acquired:
                raise RuntimeError("Another waveform_replay command is already running.")
            if self.agent.is_work_busy():
                raise RuntimeError(
                    "The LLM is already working. Wait for it to finish before retrying waveform_replay."
                )
            manager = self.agent.stage_manager
            gates = [
                (stage, index, checker)
                for stage in manager.stages
                for index, checker in enumerate(stage.checker)
                if isinstance(checker, UnityChipCheckerWaveformBugAnalysis)
                and checker.require_current_replay
            ]
            if len(gates) != 1:
                raise ValueError(
                    f"Expected exactly one configured current-replay waveform gate; "
                    f"found {len(gates)}. Configure one "
                    "UnityChipCheckerWaveformBugAnalysis with require_current_replay=true."
                )
            stage, gate_index, gate = gates[0]
            classifiers = [
                checker for checker in stage.checker[:gate_index]
                if isinstance(checker, UnityChipCheckerTestCase)
                and checker.test_dir == gate.test_dir
                and checker.doc_bug_analysis == gate.bug_file
            ]
            if len(classifiers) != 1:
                raise ValueError(
                    f"Stage '{stage.name}' must have exactly one preceding DUT test "
                    f"classification checker for '{gate.test_dir}' and '{gate.bug_file}'."
                )
            waveinfo = self.agent.get_tool_by_name("WaveInfo")
            writer = self.agent.get_tool_by_name("ApplyWaveInfoEvidence")
            if waveinfo is None or writer is None:
                raise ValueError(
                    "Enable WaveInfo and ApplyWaveInfoEvidence before waveform_replay."
                )
            classifier = classifiers[0]
            bug_recorders = [
                checker for configured_stage in manager.stages for checker in configured_stage.checker
                if isinstance(checker, Recorder)
                and type(checker.type_handler).__name__ == BugRecordType_name
                and checker.type_handler.bug_file == gate.bug_file
            ]
            related_documents = list(getattr(stage, "reference_files", []))
            static_checkers = [
                checker for configured_stage in manager.stages for checker in configured_stage.checker
                if isinstance(checker, UnityChipCheckerStaticBugValidation)
                and checker.bug_analysis_doc == gate.bug_file
                and checker.functions_and_checks_doc == classifier.doc_func_check
            ]
            related_documents.extend(
                checker.static_doc for checker in static_checkers
                if checker.static_doc not in related_documents
            )
            for recorder in bug_recorders:
                related_documents.extend(path for path in (
                    recorder.type_handler.static_bug_file, recorder.type_handler.output
                ) if path and path not in related_documents)
            if classifier.is_in_check or gate.is_in_check:
                raise RuntimeError(
                    "The configured test or waveform check is already running. "
                    "Wait for it to finish before retrying waveform_replay."
                )
            watched_paths = {Path(gate.get_path(gate.bug_file))}
            watched_paths.update(
                Path(recorder.get_path(recorder.type_handler.static_bug_file))
                for recorder in bug_recorders
            )
            watched_paths.update(
                Path(checker.get_path(checker.static_doc)) for checker in static_checkers
            )
            document_contents = {
                path: path.read_bytes() if path.is_file() else None
                for path in watched_paths
            }

            def invalidate_recorded_bugs():
                """Reload Recorder views after either automatic refresh or model edits."""
                nonlocal document_contents
                if not bug_recorders:
                    return
                current_contents = {
                    path: path.read_bytes() if path.is_file() else None
                    for path in watched_paths
                }
                if current_contents == document_contents:
                    return
                # Receipts and conclusions can change document line references;
                # accepted records must not survive either kind of document edit.
                for recorder in bug_recorders:
                    recorder.smanager_set_value(recorder.data_key, None, persist=True)
                    recorder.type_handler.on_init()
                document_contents = current_contents
                info(
                    "[waveform_replay] Invalidated previously recorded Bug data after "
                    "analysis changes; record the current Bugs again before publishing."
                )

            log_progress(
                f"START stage='{stage.name}', document='{gate.bug_file}', "
                f"test_dir='{gate.test_dir}', timeout={timeout}s."
            )
            for round_index in range(max_rounds + 1 if reanalyze else 1):
                log_progress("Running the full DUT test classification check.")
                try:
                    try:
                        passed, result = classifier.check(timeout=timeout)
                    except KeyboardInterrupt:
                        classifier.kill()
                        classifier.set_check_process(None, None)
                        raise
                    failure_scope = "DUT test classification"
                    if passed:
                        log_progress("DUT test classification PASSED; replaying all documented Bug TCs.")
                        failure_scope = f"waveform validation for '{gate.bug_file}'"
                        try:
                            passed, result = gate.check(progress_callback=log_progress)
                        except KeyboardInterrupt:
                            gate.is_in_check = False
                            raise
                    if passed and round_index:
                        for static_checker in static_checkers:
                            failure_scope = f"static Bug links in '{static_checker.static_doc}'"
                            log_progress(f"Validating {failure_scope} after reanalysis.")
                            try:
                                passed, result = static_checker.check(timeout=timeout)
                            except KeyboardInterrupt:
                                static_checker.is_in_check = False
                                raise
                            if not passed:
                                break
                finally:
                    invalidate_recorded_bugs()
                elapsed = time.monotonic() - started
                if passed:
                    info(f"[waveform_replay] {result}")
                    echo_g(
                        f"[waveform_replay] SUCCESS after {elapsed:.2f}s: "
                        f"all documented Bug waveform evidence in '{gate.bug_file}' is current; "
                        f"LLM reanalysis rounds={round_index}."
                    )
                    return {"ok": True, "rounds": round_index, "result": result}
                echo_r(f"[waveform_replay] FAILED after {elapsed:.2f}s: {failure_scope} failed.")
                echo(dump_as_json(result))
                if not reanalyze:
                    echo_y("Follow the diagnostic, or use waveform_replay --reanalyze [timeout_seconds].")
                    return {"ok": False, "result": result, "step": failure_scope}
                if round_index == max_rounds:
                    echo_r(f"[waveform_replay] FAILED: LLM reanalysis limit ({max_rounds}) reached; blockers remain.")
                    return {"ok": False, "result": result, "step": "reanalysis_limit"}
                if isinstance(self.agent.backend, BlankBackend):
                    raise RuntimeError("LLM reanalysis requires a model backend; the configured backend disables model work.")
                if self.agent.is_work_busy():
                    raise RuntimeError("The LLM is already working. Wait for it to finish before retrying --reanalyze.")

                prompt = (
                    "Perform standalone Bug reanalysis for the operator's waveform_replay request. "
                    "Resolve the validation failure below using real tests, specification, source, "
                    "and waveform evidence. Do not resume other stage tasks.\n"
                    f"Dynamic Bug document: {gate.bug_file}\n"
                    f"Functions/checks document: {classifier.doc_func_check}\n"
                    f"DUT test directory: {gate.test_dir}\n"
                    f"Related documents and existing summaries: {related_documents}\n"
                    "Read Guide_Doc/dut_bug_analysis.md and Guide_Doc/dut_test_case.md, "
                    "the current documents, exact affected TCs, specification, and relevant source. "
                    "Follow the complete canonical artifact in Guide_Doc/dut_bug_analysis.md section 5.1.\n"
                    "A changed TC requires new analysis even if its waveform is identical. "
                    "First determine whether the failure is a DUT defect or an invalid test, "
                    "fixture, API, reference model, Mock, reset, or timing assumption. "
                    "For each affected TC derive specification_expected independently and compare "
                    "input | specification_expected | test_expected | actual | classification. "
                    "Repair verification infrastructure to Pass; keep meaningful assertions and coverage. "
                    "Do not modify DUT implementation, weaken assertions, skip/xfail tests, "
                    "hide failures, or change confidence to zero to bypass validation. Never "
                    "edit generated test reports, waveforms, or receipt stores.\n"
                    "If a valid TC still reproduces a DUT Bug, keep it Fail and update every "
                    "affected BG's OVERVIEW/SYMPTOMS/TRIGGER, its ROOT's five analysis fields, "
                    "source locations, causal chain, and bidirectional references. Preserve "
                    "unrelated findings. For semantic review, execute the complete review_batch_call "
                    "with review omitted, read changed_source_files, then submit all completed "
                    "reviews with ReviewWaveInfoEvidenceBatch atomically. Do not just copy old "
                    "conclusions. Keep the target unchanged between preparing and submitting "
                    "the batch; update BG/ROOT fields before preparation or after submission. "
                    "Do not just replace a receipt. Do not rerun tests/WaveInfo between batch "
                    "items. If you change TC/source again, rerun the affected tests and obtain "
                    "fresh WaveInfo evidence with exact test_case_name, signals and time window.\n"
                    "If a corrected TC passes and no longer proves a DUT Bug, remove its TC "
                    "and WAVEFORM-REF from each disproved BG association. If only one BG association is disproved while "
                    "the TC still reproduces another confirmed Bug, remove only the disproved "
                    "association and keep the failing TC with its supported BGs. Keep each BG supported "
                    "by other valid failing TCs. Delete unsupported BG entries and empty dynamic "
                    "FG/FC/CK branches; update ROOT RELATED-BUGS and delete only unreferenced ROOTs. "
                    "Use ordinary file-editing tools for this scoped removal of disproved "
                    "associations; record only facts established by current full test results. "
                    "Delete a central waveform record only when no remaining BG uses that TC. "
                    "If the TC still supports other BGs, update that unique record's bug_evidence "
                    "and signed signal coverage for exactly the remaining associations. Remove "
                    "stale LINK-BUG confirmations in the static Bug document and update existing "
                    "Bug summaries and narrative verification reports that reference disproved findings. Preserve static "
                    "candidates unless current source/specification also disproves them. Never "
                    "remove a still-failing valid reproducer to make the document pass.\n"
                    "When no dynamic Bug remains, retain the canonical title and three ordered "
                    "sections with empty closed DYNAMIC-BUGS, ROOT-CAUSES and WAVEFORM-EVIDENCE "
                    "bodies. Keep the functions/checks specification and test coverage. Preserve "
                    "exact report node IDs, stable anchors, and blank lines around headings.\n"
                    "Return a concise account of each updated or removed TC/BG/ROOT, the reason, "
                    "test results, and any unresolved issue. The command will rerun full test "
                    "classification and waveform validation after this turn. Do not call Check, "
                    "Complete, GoToStage, Exit, or record/commit stage work.\n"
                )
                if getattr(getattr(self.agent.cfg, "skill", None), "use_skill", False):
                    prompt += (
                        "Available Skills may accelerate recording and repair; use ListSkill "
                        "and read the applicable SKILL.md before using one. When unavailable, "
                        "use ordinary file tools and Guide_Doc/dut_bug_analysis.md to produce "
                        "the same canonical artifacts.\n"
                    )
                prompt += f"Validation failure ({failure_scope}):\n{dump_as_json(result)}"

                def blocked_stage_action(*args, **kwargs):
                    """Keep standalone reanalysis from running or completing stage work."""
                    return {"error": "Stage actions are unavailable during standalone Bug reanalysis.",
                            "next_action": "Finish the requested artifact repair and return; waveform_replay will validate it."}

                def reanalysis_tips(*args, **kwargs):
                    """Keep CurrentTips focused on the operator's reanalysis request."""
                    return prompt

                # Replace callbacks as well as invocation paths, including MCP and
                # the backend's direct retry of malformed tool calls.
                protected_tools = []
                previous_break = self.agent.is_break()
                stage_index = manager.stage_index
                try:
                    for tool in self.agent.test_tools:
                        if not isinstance(tool, ManagerTool):
                            continue
                        if tool.name in {"Check", "Complete", "GoToStage", "Exit", "ApproveStagePass",
                                         "SetCurrentStageJournal", "SetSkillUsage", "StageCommit", "CurrentTips"}:
                            protected_tools.append((tool, tool.function))
                            tool.function = reanalysis_tips if tool.name == "CurrentTips" else blocked_stage_action
                    log_progress(f"LLM REANALYSIS round {round_index + 1}/{max_rounds}: {failure_scope}.")
                    self.agent.set_break(False)
                    self.agent.custom_chat(prompt)
                    if self.agent.is_break():
                        raise KeyboardInterrupt
                    if manager.stage_index != stage_index:
                        raise RuntimeError("The stage changed during standalone Bug reanalysis; inspect the stage before retrying.")
                finally:
                    for tool, function in reversed(protected_tools):
                        tool.function = function
                    self.agent.set_break(previous_break or self.agent.is_break())
                    invalidate_recorded_bugs()
                log_progress(f"LLM REANALYSIS round {round_index + 1} returned; revalidating actual artifacts.")
        except (KeyboardInterrupt, OperationCancelled):
            echo_r(f"[waveform_replay] CANCELLED during: {step}")
            return {"ok": False, "cancelled": True, "step": step}
        except Exception as error:
            echo_r(
                f"[waveform_replay] FAILED during {step}: "
                f"{type(error).__name__}: {error}"
            )
            echo_y("Correct the reported problem, then retry waveform_replay [timeout_seconds] [--reanalyze] [--max-rounds N].")
            return {"ok": False, "step": step, "error": str(error)}
        finally:
            if acquired:
                self._waveform_replay_lock.release()



def waveform_commands(controller):
    """Contribute waveform replay only when the UnitTest plugin is loaded."""
    operation = WaveformReplay(controller.agent)

    def submit(argv=()):
        """Reserve the shared model slot for classification and optional reanalysis."""
        def run(context):
            """Translate domain validation and cancellation into real operation terminal states."""
            result = operation.run(shlex.join(argv), context)
            if result.get("cancelled"):
                context.cancel_event.set()
                context.checkpoint()
            if not result["ok"]:
                raise OperationFailure("validation_failed", result.get("error", "Waveform validation failed."), result)
            return result

        return controller._operation_owner().submit("waveform_replay", run, model=True)

    return (CommandSpec("waveform_replay", "Replay waveform evidence: [timeout] [--reanalyze] [--max-rounds n].",
                        owner="unittest", arguments=(Argument("argv", "words", (), rest=True),), handler=submit, model=True),)
