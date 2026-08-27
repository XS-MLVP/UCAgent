#!/usr/bin/env python3
"""Safety and Make integration tests for copied workspace asset refresh."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "ucagent/scripts/refresh_workspace_assets.py"


def _populate_workspace(workspace: Path) -> list[Path]:
    (workspace / ".ucagent/skills/public").mkdir(parents=True)
    (workspace / ".ucagent/skills/public/SKILL.md").write_text(
        "stale skill\n", encoding="utf-8"
    )
    (workspace / "Guide_Doc").mkdir()
    (workspace / "Guide_Doc/guide.md").write_text("stale guide\n", encoding="utf-8")
    preserved = [
        workspace / ".ucagent/runtime_config.json",
        workspace / ".ucagent/ucagent_info.json",
        workspace / ".ucagent/waveinfo_receipts.json",
        workspace / ".ucagent/.waveinfo_receipt_key",
        workspace / ".ucagent/current_test_report.json",
        workspace / ".ucagent/history/stage.json",
        workspace / ".ucagent/batch_checkpoints/test_cases.json",
        workspace / "unity_test/Demo_bug_analysis.md",
        workspace / "tests/data/session/test_demo.vcd",
        workspace / "uc_test_report/report.json",
        workspace / "Demo/build/output.bin",
        workspace / "AGENTS.md",
    ]
    for path in preserved:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserve\n", encoding="utf-8")
    return preserved


def _run_script(workspace: Path, guide_doc_cache: str = "Guide_Doc"):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace",
            str(workspace),
            "--guide-doc-cache",
            guide_doc_cache,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_refresh_removes_only_copied_workspace_assets(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preserved = _populate_workspace(workspace)

    result = _run_script(workspace)

    assert result.returncode == 0, result.stderr or result.stdout
    assert not (workspace / ".ucagent/skills").exists()
    assert not (workspace / "Guide_Doc").exists()
    assert all(path.is_file() for path in preserved)
    assert "removed cache directory: .ucagent/skills" in result.stdout
    assert "removed cache directory: Guide_Doc" in result.stdout
    assert "Restart UCAgent" in result.stdout


def test_refresh_unlinks_cache_symlink_without_following_it(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.md"
    outside_file.write_text("keep\n", encoding="utf-8")
    (workspace / ".ucagent").mkdir()
    (workspace / ".ucagent/skills").symlink_to(outside, target_is_directory=True)
    (workspace / "Guide_Doc").symlink_to(outside, target_is_directory=True)

    result = _run_script(workspace)

    assert result.returncode == 0, result.stdout
    assert not (workspace / ".ucagent/skills").exists()
    assert not (workspace / "Guide_Doc").exists()
    assert outside_file.read_text(encoding="utf-8") == "keep\n"


def test_refresh_rejects_unsafe_workspace_and_guide_paths(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    for unsafe_guide in (
        "",
        "../Guide_Doc",
        "/tmp/Guide_Doc",
        "docs/../Guide_Doc",
        ".ucagent/Guide_Doc",
        "unity_test",
    ):
        result = _run_script(workspace, unsafe_guide)
        assert result.returncode == 2

    result = _run_script(Path("/"))
    assert result.returncode == 2


def test_refresh_rejects_symlinked_cache_parent(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "skills").mkdir()
    (outside / "skills/keep.md").write_text("keep\n", encoding="utf-8")
    (workspace / ".ucagent").symlink_to(outside, target_is_directory=True)
    (workspace / "Guide_Doc").mkdir()

    result = _run_script(workspace)

    assert result.returncode == 2
    assert (outside / "skills/keep.md").is_file()
    assert (workspace / "Guide_Doc").is_dir()


def test_refresh_validates_all_targets_before_removing_any_cache(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".ucagent/skills").mkdir(parents=True)
    skill_file = workspace / ".ucagent/skills/keep.md"
    skill_file.write_text("stale but recoverable\n", encoding="utf-8")
    (workspace / "Guide_Doc").write_text("not a directory\n", encoding="utf-8")

    result = _run_script(workspace)

    assert result.returncode == 2
    assert skill_file.is_file()
    assert (workspace / "Guide_Doc").is_file()


def test_make_refresh_target_uses_explicit_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    preserved = _populate_workspace(workspace)
    make_args = ["make", "refresh_Demo", f"CWD={workspace}"]

    dry_run = subprocess.run(
        ["make", "-n", "refresh_Demo", f"CWD={workspace}"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert "refresh_workspace_assets.py" in dry_run.stdout
    assert str(workspace) in dry_run.stdout

    result = subprocess.run(
        make_args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not (workspace / ".ucagent/skills").exists()
    assert not (workspace / "Guide_Doc").exists()
    assert all(path.is_file() for path in preserved)
