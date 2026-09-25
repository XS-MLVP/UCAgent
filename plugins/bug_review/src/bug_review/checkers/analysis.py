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
        """Bind canonical artifact validation to the active workspace."""
        self.workflow = Workflow(self.workspace)
        return super().on_init()

    def get_template_data(self):
        """Expose the direct artifact completion criterion without changing state."""
        return {"BUG_REVIEW_PROGRESS": "Use the current stage Skill to create every declared output, then run Check."}

    def do_check(self, timeout=0, **kwargs):
        """Verify direct stage artifacts, real WaveInfo receipts and report links."""
        try:
            return self.workflow.check(self.stage_id)
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            return False, {"error_code": "BUG_REVIEW_INTEGRITY_FAILED", "error": str(exc),
                           "next_action": "Restore the named artifact or call the default WaveInfo tool for the exact test case, then run Check again."}
