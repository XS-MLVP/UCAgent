"""Gate review stages from actual artifacts, leaving stage state to UCAgent."""

from ucagent.checkers.base import Checker
from ..core.layout import runtime_layout
from ..core.validation import validate, ReviewIssues
from ..core.reporting import render_report


class BugReviewStageChecker(Checker):
    """Validate the current stage without manual completion flags or input hashing."""

    def __init__(self, stage, **kwargs):
        """Store the stage name; initialize workspace-dependent state on activation."""
        super().__init__()
        self.stage_id = stage
        self._registered = False

    def on_init(self):
        """Bind paths and register run harvesting once per manager callback key."""
        self.layout = runtime_layout(self.workspace)
        if self.stage_manager is not None:
            from ..core.replay import harvest_waveforms
            self.stage_manager.add_post_test_case_run_callback('bug_review_sessions', lambda: harvest_waveforms(self.layout))
        if self.stage_id == 'publish' and not self._registered:
            from ..publishing import publish_run
            self.stage.append_on_complete_callback(lambda _: publish_run(self.workspace, self.layout.workspace.parent))
            self._registered = True
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs):
        """Return bounded source/evidence gaps; never execute tests or refresh evidence."""
        try:
            result = validate(self.layout, self.stage_id)
            if self.stage_id == 'publish':
                render_report(self.layout, verify_only=True)
            return True, result
        except ReviewIssues as error:
            return False, error.result()
        except (ValueError, OSError, KeyError, TypeError) as error:
            return False, {'error_code': 'REVIEW_INVALID', 'error': str(error)[:1600],
                           'next_action': 'Use ReviewContext and the named record tool, then Check again'}
