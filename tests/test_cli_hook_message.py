"""Regression tests for UCAgent external hook message exit semantics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_hook(workspace: Path, config: Path, key: str) -> subprocess.CompletedProcess[str]:
    """Run the source-tree CLI hook command from a synthetic workspace."""

    return subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "ucagent.py"),
            "--hook-message",
            f"{config}::{key}",
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )


def test_terminal_hook_without_stop_message_is_success(tmp_path: Path) -> None:
    """A completed agent without a stop prompt must not produce Hook failed."""

    state_dir = tmp_path / ".ucagent"
    state_dir.mkdir()
    (state_dir / "ucagent_info.json").write_text(
        json.dumps({"all_completed": True, "is_agent_exit": True}),
        encoding="utf-8",
    )
    config = tmp_path / "hook.yaml"
    config.write_text("hooks:\n  continue: keep-going\n", encoding="utf-8")

    result = _run_hook(tmp_path, config, "continue|missing_stop")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_active_hook_without_continue_message_is_failure(tmp_path: Path) -> None:
    """An active run with a missing continue prompt must remain diagnosable."""

    state_dir = tmp_path / ".ucagent"
    state_dir.mkdir()
    (state_dir / "ucagent_info.json").write_text(
        json.dumps({"all_completed": False, "is_agent_exit": False}),
        encoding="utf-8",
    )
    config = tmp_path / "hook.yaml"
    config.write_text("hooks:\n  continue: keep-going\n", encoding="utf-8")

    result = _run_hook(tmp_path, config, "missing_continue")

    assert result.returncode != 0
    assert "Hook message is not configured" in result.stderr
