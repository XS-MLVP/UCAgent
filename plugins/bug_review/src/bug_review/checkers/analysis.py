"""Validate completed Bug Review stages against their source inventories."""

from ucagent.checkers.base import Checker

from ..workflow import Workflow


class BugReviewStageChecker(Checker):
    """Gate each stage on the workflow's sealed files and content contract."""

    def __init__(self, stage, **kwargs):
        """Store the exact stage selected by the workflow configuration."""
        super().__init__()
        self.stage_id = stage

    def on_init(self):
        """Bind the checker to the prepared analysis workspace."""
        self.workflow = Workflow(self.workspace)
        return super().on_init()

    def get_template_data(self):
        """Expose stage progress guidance without changing workflow state."""
        return {"BUG_REVIEW_PROGRESS": "调用 BugReviewStatus 和 BugReviewTasks 获取当前阶段与待办"}

    def do_check(self, timeout=0, **kwargs):
        """Verify sealed outputs, Bug identities, evidence and report links."""
        try:
            return self.workflow.check(self.stage_id)
        except (ValueError, OSError, KeyError) as exc:
            return False, {"error_code": "BUG_REVIEW_INTEGRITY_FAILED", "error": str(exc),
                           "next_action": "Restore the named artifact or prepare a new workspace for changed inputs."}
