# -*- coding: utf-8 -*-
"""Shared current-test-report store for UCAgent test-running workflows.

This module owns the workspace-level ``current_test_report.json`` protocol:
the runtime-snapshot sections that publish it, per-stage invalidation, and
the save/load helpers used by test runners, Checkers, and Skill scripts.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from ucagent.util.config import load_runtime_config
from ucagent.util.functions import load_json_file, save_json_file


CURRENT_TEST_REPORT_FILENAME = "current_test_report.json"
CURRENT_TEST_REPORT_SCHEMA_VERSION = 1
CURRENT_TEST_REPORT_RELATIVE_PATH = f".ucagent/{CURRENT_TEST_REPORT_FILENAME}"


def _current_test_report_path(workspace: str) -> Path:
    """Return the workspace-local report shared by test consumers and Skills."""
    runtime_config = load_runtime_config(workspace)
    relative = runtime_config.get("current_test_report")
    if not relative:
        raise ValueError(
            "Runtime config declares no 'current_test_report': workflows "
            "without a test dir publish no current test report."
        )
    return Path(workspace) / relative


def clear_current_test_report(workspace: str) -> None:
    """Invalidate a previous stage's report when a stage becomes active."""
    target = Path(workspace) / CURRENT_TEST_REPORT_RELATIVE_PATH
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def save_current_test_report(
    workspace: str,
    report: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Path:
    """Publish the latest structured test report for runtime consumers.

    The report is deliberately kept outside the DUT output directory so a Skill
    cannot accidentally bind itself to a stage-private or historical report.
    ``context`` is diagnostic metadata only; the actual test report remains under
    the stable ``report`` key.
    """
    if not isinstance(report, dict):
        raise TypeError("Current test report must be a mapping.")
    if context is not None and not isinstance(context, dict):
        raise TypeError("Current test report context must be a mapping.")
    target = _current_test_report_path(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CURRENT_TEST_REPORT_SCHEMA_VERSION,
        "report": report,
        "context": context or {},
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    save_json_file(str(temporary), payload)
    os.replace(temporary, target)
    return target


def load_current_test_report(workspace: str) -> Dict[str, Any]:
    """Load and validate the latest structured test report for a workspace."""
    target = _current_test_report_path(workspace)
    if not target.is_file():
        raise FileNotFoundError(
            f"Current test report not found: {target}. Run the current stage's "
            "real test cases with Check or RunTestCases before using a test-report Skill."
        )
    payload = load_json_file(str(target))
    if not isinstance(payload, dict):
        raise ValueError(f"Current test report {target} must be a JSON object.")
    if payload.get("schema_version") != CURRENT_TEST_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"Current test report {target} has an unsupported schema_version."
        )
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError(f"Current test report {target} has no report object.")
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise ValueError(f"Current test report {target} has invalid context metadata.")
    return payload


class TestProtocolRuntimeHook:
    """Runtime hook that publishes and invalidates the test-report snapshot."""

    def snapshot_sections(self, cfg: Any) -> Dict[str, Any]:
        """Return the runtime snapshot sections for the declared pytest dir.

        Workflows that run no tests declare no ``tools.RunTestCases.test_dir``;
        the snapshot then omits ``test_output_dir`` for its workspace
        consumers, and only test-running workflows publish the shared report
        pointer.
        """
        try:
            test_output_dir = cfg.get_value("tools.RunTestCases.test_dir", None)
        except AttributeError:
            test_output_dir = None
        if not isinstance(test_output_dir, str) or not test_output_dir.strip():
            return {}
        return {
            "test_output_dir": test_output_dir,
            "current_test_report": CURRENT_TEST_REPORT_RELATIVE_PATH,
        }

    def validate_runtime_snapshot(self, data: Dict[str, Any]) -> None:
        """Validate this hook's contributed snapshot sections."""
        if "test_output_dir" in data:
            test_output_dir = data["test_output_dir"]
            if not isinstance(test_output_dir, str) or not test_output_dir.strip():
                raise ValueError(
                    "Resolved runtime config value 'test_output_dir' must be a non-empty string."
                )
        if "current_test_report" in data:
            if data["current_test_report"] != CURRENT_TEST_REPORT_RELATIVE_PATH:
                raise ValueError(
                    "Resolved runtime config value 'current_test_report' must be "
                    f"'{CURRENT_TEST_REPORT_RELATIVE_PATH}'."
                )
            if "test_output_dir" not in data:
                raise ValueError(
                    "Resolved runtime config value 'current_test_report' requires "
                    "'test_output_dir': workflows without a test dir publish no "
                    "test report."
                )

    def on_stage_start(self, workspace: str) -> None:
        """Drop the previous stage's report when a stage becomes active.

        A test-report Skill must consume evidence produced in the active
        stage, not whichever test happened to run in the preceding stage.
        """
        clear_current_test_report(workspace)
