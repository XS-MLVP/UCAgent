"""Expose the five-stage Bug Review workflow to UCAgent tools and Checkers."""
from __future__ import annotations


from pydantic import BaseModel, Field
from ucagent.tools.uctool import UCTool
from ucagent.tools.waveform import ArgWaveInfo

from .workflow import Workflow


class BugReviewTool(UCTool):
    """Bind plugin tools to the prepared analysis workspace."""

    workspace: str = Field(exclude=True)
    output_dir: str = Field(default="results", exclude=True)
    write_dirs: list[str] = Field(default_factory=list, exclude=True)
    un_write_dirs: list[str] = Field(default_factory=list, exclude=True)

    def workflow(self):
        """Open the prepared workflow for this tool call."""
        return Workflow(self.workspace)


class EmptyArgs(BaseModel):
    """No arguments."""


def _result(callback):
    """Return a bounded tool diagnostic for expected input errors."""
    try:
        return callback()
    except (ValueError, OSError, KeyError) as exc:
        return {"error_code": "BUG_REVIEW_VALIDATION_FAILED", "error": str(exc),
                "next_action": "Correct the named input or judgment, then retry the same operation."}


class StageArgs(BaseModel):
    """Select the exact current workflow stage."""

    stage: str = Field(description="Exact current stage from CurrentTips or BugReviewStatus")


class ResponseArgs(BaseModel):
    """Submit one judgment for a frozen review request."""

    task_id: str
    input_hash: str
    round_index: int = Field(ge=0, description="Use the round returned by BugReviewTasks")
    request_hash: str
    response: dict = Field(description="JSON response matching the current request schema, with real evidence citations")


class BugReviewRunStage(BugReviewTool):
    """Build outputs or expose pending evidence judgments."""

    name: str = "BugReviewRunStage"
    description: str = "Build the current Bug Review stage outputs or prepare its evidence judgments."
    args_schema: type[BaseModel] = StageArgs
    call_time_out: int = 3600

    def _run(self, stage, run_manager=None):
        """Run the selected stage through the workflow gate."""
        return _result(lambda: self.workflow().run(stage))


class BugReviewTasks(BugReviewTool):
    """List pending judgments for the active stage."""

    name: str = "BugReviewTasks"
    description: str = "Get current evidence, response schema and task identity before submitting a judgment."
    args_schema: type[BaseModel] = EmptyArgs

    def _run(self, run_manager=None):
        """Read bounded pending review requests."""
        return _result(lambda: self.workflow().requests())


class BugReviewSubmitResponse(BugReviewTool):
    """Accept one evidence-backed case or Bug decision."""

    name: str = "BugReviewSubmitResponse"
    description: str = "Validate and save one evidence-based replay, waveform or Bug judgment."
    args_schema: type[BaseModel] = ResponseArgs

    def _run(self, task_id, input_hash, round_index, request_hash, response, run_manager=None):
        """Validate and persist the requested judgment."""
        return _result(lambda: self.workflow().submit(task_id=task_id, input_hash=input_hash,
                                                 round_index=round_index, request_hash=request_hash, response=response))


class BugReviewStatus(BugReviewTool):
    """Expose workflow completion and artifact integrity status."""

    name: str = "BugReviewStatus"
    description: str = "Read Bug Review stage status and verify completed artifact fingerprints."
    args_schema: type[BaseModel] = EmptyArgs

    def _run(self, run_manager=None):
        """Read the current stage and completed stages."""
        return _result(lambda: self.workflow().status())


class WaveformArgs(BaseModel):
    """Select a failed case and one WaveInfo query."""

    task_id: str = Field(description="Current waveform review task from BugReviewTasks")
    query: ArgWaveInfo = Field(default_factory=ArgWaveInfo, description=(
        "WaveInfo arguments. Start with {} to discover this task's waveform and exact test_case_name. "
        "Final evidence requires pattern, signal_groups and start_step/end_step or logged_cycle/clock_signal."))


class BugReviewWaveInfo(BugReviewTool):
    """Inspect a failed case through UCAgent's signed WaveInfo tool."""

    name: str = "BugReviewWaveInfo"
    description: str = (
        "Inspect the current failed test's real waveform using WaveInfo. Returns evidence_id for "
        "BugReviewSubmitResponse. Verify test correctness first; preserve the returned evidence identity.")
    args_schema: type[BaseModel] = WaveformArgs
    call_time_out: int = 600

    def _run(self, task_id, query=None, run_manager=None):
        """Record a task-scoped waveform observation and evidence identity."""
        from .waveform import inspect_waveform
        from .tasks import task_lock
        workflow = self.workflow()
        with task_lock(workflow.root / "workflow.lock"):
            return _result(lambda: inspect_waveform(
                workflow, task_id, query.model_dump() if isinstance(query, ArgWaveInfo) else query or {}))
