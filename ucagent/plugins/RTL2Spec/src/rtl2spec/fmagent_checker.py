"""Automatic, task-local FM-Agent preparation and one-shot raw spec export gates."""

from pathlib import Path

from ucagent.checkers.base import Checker

from .fmagent_workflow import export_specs, prepare, settings_from_cfg


CONSUMER_STAGES = ("inspect_and_capture_evidence", "draft_design_document", "review_source_semantics", "validate_and_finalize")


class RTL2SpecFMAgentPrepareChecker(Checker):
    """Prepare native artifacts once and register references in all four consumers."""

    def __init__(self, module: str, kind: str, output_dir: str = "outputs", cfg=None):
        """Store static context without accessing runtime directories."""
        super().__init__()
        if kind not in {"generic", "xiangshan"}:
            raise ValueError("kind must be generic or xiangshan")
        self.cfg = cfg
        self.module, self.kind, self.output_dir = module, kind, output_dir
        self._state, self._prepared, self._failure = "not_started", None, None
        self._diagnostic = None

    def set_stage_manager(self, manager):
        """Reject skipped or restored downstream entry before automatic preparation writes."""
        super().set_stage_manager(manager)
        if (manager.stages[0] is not self.stage or self.stage.is_skipped()
                or manager.stage_index != 0 or manager.force_stage_index != 0
                or 0 in (manager.stage_skip_list or [])
                or manager.ucagent_info.get("stage_index", 0) != 0):
            raise ValueError("prepare_fmagent cannot be bypassed; start a new task with --no-history and no stage skip/force")
        names = tuple(stage.name for stage in manager.stages[1:])
        expected = (("inspect_and_capture_evidence" if self.kind == "generic" else "inspect_and_generate_evidence"), *CONSUMER_STAGES[1:])
        if names != expected:
            raise ValueError(f"FM-Agent requires the four original downstream stages: {CONSUMER_STAGES}")
        return self

    def on_init(self):
        """Run preparation only on first entry; repeated initialization preserves read evidence."""
        if self._state == "not_started":
            self._state = "running"
            try:
                settings = settings_from_cfg(self.cfg)
                if not settings.enabled:
                    raise ValueError("FM-Agent workflow requires fmagent.enabled=true")
                self._prepared = prepare(Path(self.workspace).resolve(), self.module, self.output_dir, self.kind, settings)
                for stage in self.stage_manager.stages[1:]:
                    stage.add_reference_files(self._prepared["references"])
                self._state = "ready"
            except BaseException as exc:
                self._state = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
                self._failure = exc
                self._diagnostic = {"error_code": "FMAGENT_PREPARATION_FAILED", "error": str(exc),
                                    "details": getattr(exc, "__notes__", []),
                                    "next_action": "Preserve input and native output at their reported locations; ask the operator to resolve the failure and approve a new task with empty outputs."}
                raise
        if self._state != "ready":
            raise RuntimeError(f"FM-Agent preparation {self._state}; no automatic retry") from self._failure
        return super().on_init()

    def get_template_data(self):
        """Project only cached preparation status."""
        return {"fmagent_state": self._state, "fmagent_spec_count": len(self._prepared["specs"]) if self._prepared else 0}

    def do_check(self, is_complete=False, **kwargs):
        """Confirm the preparation operation, without validating spec contents or restarting it."""
        if self._state == "ready":
            return True, self.get_template_data()
        return False, self._diagnostic or {"error_code": "FMAGENT_PREPARATION_INCOMPLETE", "error": f"Preparation is {self._state}",
                       "next_action": "Inspect preserved native output and operator diagnostics; start a newly approved task with empty outputs."}


class RTL2SpecFMAgentExportChecker(Checker):
    """Export the prepared spec set once, when the draft stage becomes active."""

    def __init__(self, cfg=None):
        """Initialize task-local export state without workspace access."""
        super().__init__()
        self.cfg = cfg
        self._state, self._result, self._failure = "not_started", {}, None

    def on_init(self):
        """Automatically export after evidence capture, never retrying partial copies."""
        if self._state == "not_started":
            self._state = "exporting"
            try:
                preparation = next(checker for checker in self.stage_manager.stages[0].checker
                                   if isinstance(checker, RTL2SpecFMAgentPrepareChecker))
                if preparation._state != "ready":
                    raise ValueError("FM-Agent preparation must finish before spec export")
                self._result = export_specs(preparation._prepared)
                self._state = "ready"
            except Exception as exc:
                self._state, self._failure = "failed", exc
                self._result = {"error_code": "FMAGENT_EXPORT_FAILED", "error": str(exc),
                                "next_action": "Preserve original and partial exported files; ask the operator to select fresh outputs for a new task."}
            except BaseException as exc:
                self._state, self._failure = "failed", exc
                raise
        return super().on_init()

    def do_check(self, is_complete=False, **kwargs):
        """Report the cached copy operation outcome, allowing zero and empty specs."""
        if self._state == "ready":
            return True, self._result
        return False, self._result or {"error_code": "FMAGENT_EXPORT_INCOMPLETE", "error": f"Export is {self._state}",
                                      "next_action": "Enter the draft stage after successful preparation and evidence capture."}
