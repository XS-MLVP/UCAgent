"""Validate completed Bug Review stages against their source inventories."""

from ucagent.checkers.base import Checker

from ..review_validation import ReviewIssues
from ..workflow import Workflow


class BugReviewStageChecker(Checker):
    """Gate each stage on the workflow's sealed files and content contract."""

    def __init__(self, stage, **kwargs):
        """Store the exact stage selected by the workflow configuration."""
        super().__init__()
        self.stage_id = stage
        self._publish_registered = False

    def on_init(self):
        """Bind canonical artifact validation to the active workspace."""
        self.workflow = Workflow(self.workspace)
        if self.stage_id == "publish" and not self._publish_registered:
            from ..workflow import publish_run

            def publish_completed(_stage):
                """Promote the report after the final stage is committed."""
                run = self.workflow.root
                publish_run(run, run.parents[2])

            self.stage.append_on_complete_callback(publish_completed)
            self._publish_registered = True
        return super().on_init()

    def get_template_data(self):
        """Expose the direct artifact completion criterion without changing state."""
        return {"BUG_REVIEW_PROGRESS": "Create every declared output using available tools, then run Check."}

    def do_check(self, timeout=0, **kwargs):
        """Verify direct stage artifacts, real WaveInfo receipts and report links."""
        try:
            return self.workflow.check(self.stage_id)
        except ReviewIssues as exc:
            return False, exc.result()
        except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
            return False, {"error_code": "BUG_REVIEW_INTEGRITY_FAILED", "error": str(exc),
                           "next_action": "Correct the named artifact or evidence field, then run Check again."}
