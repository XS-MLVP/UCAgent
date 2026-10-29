#coding: utf-8
"""UnityTest waveform Bug-analysis Checker."""

import copy

from ucagent.checkers.base import Checker
from .toffee_report import check_all_documented_waveform_bug_analysis


class UnityChipCheckerWaveformBugAnalysis(Checker):
    """Independent analysis-and-waveform gate for the dynamic Bug document."""

    def __init__(
        self,
        bug_file: str,
        test_dir: str,
        require_current_replay: bool = False,
        **kwargs,
    ):
        super().__init__()
        del kwargs
        if type(require_current_replay) is not bool:
            raise ValueError("require_current_replay must be a boolean")
        self.bug_file = bug_file
        self.test_dir = test_dir
        self.require_current_replay = require_current_replay

    def do_check(self, **kwargs) -> tuple[bool, object]:
        """Validate dynamic Bug analysis and safely refresh current WaveInfo evidence."""
        del kwargs
        waveform_tool = None
        waveform_evidence_tool = None
        if self.stage_manager is not None:
            waveform_tool = self.get_tool_by_name("WaveInfo")
            waveform_evidence_tool = self.get_tool_by_name("ApplyWaveInfoEvidence")
        passed, message = check_all_documented_waveform_bug_analysis(
            self.workspace,
            self.bug_file,
            waveform_tool=waveform_tool,
            waveform_evidence_tool=waveform_evidence_tool,
            waveform_test_dir=self.test_dir,
            require_current_replay=self.require_current_replay,
        )
        if passed:
            return True, {"success": message}
        if (
            isinstance(message, dict)
            and {"error_code", "error", "next_action"}.issubset(message)
        ):
            return False, {
                "error": message["error"],
                "diagnostic": copy.deepcopy(message),
            }
        return False, message


