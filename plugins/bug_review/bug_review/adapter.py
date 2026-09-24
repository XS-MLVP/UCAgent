"""UCAgent-specific tools and stage gates; core modules do not import this."""
from __future__ import annotations


from pydantic import BaseModel, Field
from ucagent.checkers.base import Checker
from ucagent.tools.uctool import UCTool
from ucagent.tools.waveform import ArgWaveInfo

from .workflow import Workflow


class BugReviewTool(UCTool):
    workspace: str = Field(exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    write_dirs: list[str] = Field(default_factory=list, exclude=True)
    un_write_dirs: list[str] = Field(default_factory=list, exclude=True)

    def workflow(self):
        return Workflow(self.workspace)


class EmptyArgs(BaseModel):
    """No arguments."""


def _result(callback):
    try:
        return callback()
    except (ValueError, OSError, KeyError) as exc:
        return {"error_code": "BENCHMARK_VALIDATION_FAILED", "error": str(exc),
                "next_action": "Correct the named input or judgment, then retry the same operation."}


class StageArgs(BaseModel):
    stage: str = Field(description="Exact current stage from CurrentTips or BugReviewStatus")


class ResponseArgs(BaseModel):
    task_id: str
    input_hash: str
    round_index: int = Field(ge=0, description="Use the round returned by BugReviewTasks")
    request_hash: str
    response: dict = Field(description="JSON response matching the current request schema, with real evidence citations")


class BugReviewRunStage(BugReviewTool):
    name: str = "BugReviewRunStage"
    description: str = "Execute the current deterministic benchmark stage or prepare its judgment queue. Never calls a model API."
    args_schema: type[BaseModel] = StageArgs
    call_time_out: int = 3600

    def _run(self, stage, run_manager=None):
        return _result(lambda: self.workflow().run(stage))


class BugReviewTasks(BugReviewTool):
    name: str = "BugReviewTasks"
    description: str = "Get current evidence, response schema, task identity and vote/appeal round. Read these before submitting a judgment."
    args_schema: type[BaseModel] = EmptyArgs

    def _run(self, run_manager=None):
        return _result(lambda: self.workflow().requests())


class BugReviewSubmitResponse(BugReviewTool):
    name: str = "BugReviewSubmitResponse"
    description: str = "Validate one evidence-based judgment round and save it. Returns another round when voting or an appeal is required."
    args_schema: type[BaseModel] = ResponseArgs

    def _run(self, task_id, input_hash, round_index, request_hash, response, run_manager=None):
        return _result(lambda: self.workflow().submit(task_id=task_id, input_hash=input_hash,
                                                 round_index=round_index, request_hash=request_hash, response=response))


class BugReviewStatus(BugReviewTool):
    name: str = "BugReviewStatus"
    description: str = "Read benchmark stage status and verify completed artifact fingerprints."
    args_schema: type[BaseModel] = EmptyArgs

    def _run(self, run_manager=None):
        return _result(lambda: self.workflow().status())


class WaveformArgs(BaseModel):
    task_id: str = Field(description="Current waveform review task from BugReviewTasks")
    query: ArgWaveInfo = Field(default_factory=ArgWaveInfo, description=(
        "WaveInfo arguments. Start with {} to discover this task's waveform and exact test_case_name. "
        "Final evidence requires pattern, signal_groups and start_step/end_step or logged_cycle/clock_signal."))


class BugReviewWaveInfo(BugReviewTool):
    name: str = "BugReviewWaveInfo"
    description: str = (
        "Inspect the current failed test's real waveform using WaveInfo. Returns evidence_id for "
        "BugReviewSubmitResponse. Verify test correctness first; preserve the returned evidence identity.")
    args_schema: type[BaseModel] = WaveformArgs
    call_time_out: int = 600

    def _run(self, task_id, query=None, run_manager=None):
        from .waveform import inspect_waveform
        from .tasks import task_lock
        workflow = self.workflow()
        with task_lock(workflow.root / "workflow.lock"):
            return _result(lambda: inspect_waveform(
                workflow, task_id, query.model_dump() if isinstance(query, ArgWaveInfo) else query or {}))


class BugReviewStageChecker(Checker):
    def __init__(self, stage, **kwargs):
        super().__init__()
        self.stage_id = stage

    def on_init(self):
        self.workflow = Workflow(self.workspace)
        return super().on_init()

    def get_template_data(self):
        return {"BUG_REVIEW_PROGRESS": "调用 BugReviewStatus 和 BugReviewTasks 获取当前阶段与待办"}

    def do_check(self, timeout=0, **kwargs):
        """Verify stage completion and the fingerprints of all accepted artifacts."""
        try:
            return self.workflow.check(self.stage_id)
        except (ValueError, OSError, KeyError) as exc:
            return False, {"error_code": "BENCHMARK_INTEGRITY_FAILED", "error": str(exc),
                           "next_action": "Restore the named artifact or prepare a new workspace for changed inputs."}
