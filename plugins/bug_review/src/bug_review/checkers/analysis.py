"""Validate completed Bug Review stages against their source inventories."""

import os
from pathlib import Path
import stat

from ucagent.checkers.base import Checker

from ..core.layout import (review_waveinfo, ANALYSIS, module_label, prepare_workspace_layout,
                           resolve_out_dir, unity_test_root)
from ..core.validation import ReviewIssues


class BugReviewStageChecker(Checker):
    """Gate each stage on the workflow's sealed files and content contract."""

    def __init__(self, stage, **kwargs):
        """Store the exact stage selected by the workflow configuration."""
        super().__init__()
        self.stage_id = stage
        self._publish_registered = False

    def on_init(self):
        """Bind canonical artifact validation to the active workspace."""
        prepare_workspace_layout(self.workspace)
        self.workflow = Workflow(self.workspace)
        # Pytest creates session data; writable directories also allow archive
        # replacement. Files remain read-only and file tools deny source edits.
        root = unity_test_root(self.workflow.root)
        for directory, _, _ in os.walk(root):
            path = Path(directory)
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        manager = self.stage_manager
        if manager is not None:
            from ..core.replay import install_run_session_harvest

            install_run_session_harvest(manager, self.workflow.root)
        if self.stage_id == "publish" and not self._publish_registered:
            from ..publishing import publish_run

            def publish_completed(_stage):
                """Promote the report after the final stage is committed."""
                run = self.workflow.root
                name = self.workflow.label
                if run.name == name:
                    publish_run(run, run.parent)

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
                           "next_action": "Fix the named record field with UpdateReviewRecord, then run "
                                          "Check again; a completed test run never needs repeating for a "
                                          "record field"}


class Workflow:
    """Validate one module's current indexed stage artifacts."""

    def __init__(self, workspace):
        """Resolve the run layout and the workflow-managed output directory."""
        self.root = Path(workspace).resolve()
        self.label = module_label(self.root)
        self.out = resolve_out_dir(self.root)
        self.waveinfo = review_waveinfo(self.root)

    def status(self):
        """Return the first stage whose indexed artifacts do not pass Check."""
        completed = []
        for stage in ANALYSIS:
            try:
                valid, _ = self.check(stage)
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError):
                valid = False
            if not valid:
                break
            if stage == "publish":
                from ..core.records import load_record

                index = load_record(self.out, "review_index.json", "index")
                if index.stage_status.get("publish") != "complete":
                    break
            completed.append(stage)
        current = next((stage for stage in ANALYSIS if stage not in completed), "")
        return {"kind": "analysis", "current_stage": current,
                "completed": completed, "complete": not current}

    def check(self, stage):
        """Validate the requested stage and every preceding stage."""
        from ..core.records import load_record, source_root as prepared_source_root
        from ..core.validation import review_incomplete
        from .stages import CHECKS

        if stage not in ANALYSIS:
            raise ValueError(f"unknown Bug Review stage: {stage}")
        source = self.root.resolve()
        if not (self.out / "review_index.json").is_file():
            raise ValueError("analysis/review_index.json is missing; create full replay records")
        index = load_record(self.out, "review_index.json", "index")
        if (index.workspace.get("name") != self.label
                or index.workspace.get("source_path") != str(source)
                or index.workspace.get("execution_workspace") != str(self.root)):
            raise ValueError("review_index.json workspace identity differs from the run layout")
        required_stages = ANALYSIS[:ANALYSIS.index(stage) + (stage != "publish")]
        for required in required_stages:
            if index.stage_status.get(required) != "complete":
                raise ValueError(f"stage_status.{required} must be complete")
        ctx = {"source": source, "index": index,
               "source_root": prepared_source_root(self.out)}
        for check in CHECKS[:ANALYSIS.index(stage) + 1]:
            check(self, ctx)
        environment = load_record(self.out, index.environment_path, "environment")
        incomplete = review_incomplete(ctx["manifest"], ctx["cases"], environment)
        return True, {"stage": stage, "validated_workspaces": [self.label],
                      "review_status": "incomplete" if incomplete else "complete"}
