"""Exercise relocated command entry points without relying on an installed plugin."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ucagent_act4.checkers import act4_review_checker
from ucagent_act4.scripts import check_assets


PROJECT = Path(__file__).resolve().parents[1]


def invoke_assets(workspace, *arguments):
    """Run the asset CLI without site packages or UCAgent on its import path."""
    return subprocess.run(
        [sys.executable, "-S", "-m", "ucagent_act4.scripts.check_assets", *arguments],
        cwd=workspace,
        env={**os.environ, "PYTHONPATH": str(PROJECT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_asset_script_help(tmp_path):
    """Expose the relocated CLI and its canonical arguments from an unrelated cwd."""
    result = invoke_assets(tmp_path, "--help")
    assert result.returncode == 0, result.stderr
    assert "--require-standalone-generator" in result.stdout
    assert "--norm-rules" in result.stdout


@pytest.mark.parametrize("missing", [False, True])
def test_asset_script_reports_and_exit_status(tmp_path, missing):
    """Write both reports and preserve error status independently of plugin loading."""
    asset = tmp_path / "asset.txt"
    if not missing:
        asset.write_text("Fixture asset\n", encoding="utf-8")
    reports = tmp_path / "reports"
    result = invoke_assets(
        tmp_path, "--act4-root", str(tmp_path), "--asset", str(asset),
        "--output-dir", str(reports), "--stdout",
    )
    assert result.returncode == (2 if missing else 0), result.stderr
    report = json.loads(result.stdout)
    assert bool(report["summary"]["errors"]) == missing
    assert json.loads((reports / "manifest.asset-consistency.json").read_text()) == report
    assert (reports / "manifest.asset-consistency.md").is_file()


def test_asset_script_invalid_input(tmp_path):
    """Report an unreadable ACT root as an input error without manufacturing a report."""
    result = invoke_assets(tmp_path, "--act4-root", str(tmp_path / "missing"))
    assert result.returncode == 1
    assert "ACT4 root is not a directory" in result.stderr
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("fail_on_warning", [False, True])
def test_asset_script_warning_policy(tmp_path, monkeypatch, fail_on_warning):
    """Keep warning exit policy in the command layer without changing the shared engine."""
    report = {"status": "warning", "summary": {"errors": 0, "warnings": 1}}
    monkeypatch.setattr(check_assets.core, "run_asset_checks", lambda **kwargs: report)
    arguments = ["--output-dir", str(tmp_path)]
    if fail_on_warning:
        arguments.append("--fail-on-warning")
    assert check_assets.main(arguments) == (2 if fail_on_warning else 0)


def test_benchmark_script_help(tmp_path):
    """Run the development script with the documented test-fixture import path."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        str(path) for path in (PROJECT / "src", PROJECT / "tests", PROJECT.parents[1])
    )
    result = subprocess.run(
        [sys.executable, str(PROJECT / "scripts/benchmark_scope_validation.py"), "--help"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--base-path" in result.stdout


def test_benchmark_explicit_baseline_path(tmp_path, monkeypatch):
    """Use the requested historical source path rather than guessing an earlier layout."""
    spec = importlib.util.spec_from_file_location(
        "act4_scope_benchmark", PROJECT / "scripts/benchmark_scope_validation.py",
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    baseline_path = "snapshot/checkers/review.py"
    calls = []

    def baseline_source(command, **kwargs):
        """Supply the current scope validator as a deterministic comparison baseline."""
        calls.append(command)
        return Path(act4_review_checker.__file__).read_text(encoding="utf-8")

    monkeypatch.setattr(benchmark.subprocess, "check_output", baseline_source)
    output = tmp_path / "benchmark.json"
    monkeypatch.setattr(sys, "argv", [
        "benchmark_scope_validation.py", "--base-ref", "baseline", "--base-path", baseline_path,
        "--repeats", "1", "--output", str(output),
    ])
    benchmark.main()
    report = json.loads(output.read_text())
    assert calls == [["git", "show", f"baseline:{baseline_path}"]]
    assert report["baseline_path"] == baseline_path
    assert report["summary"]["before"]["failed_checks"]["median"] > 0
    assert report["summary"]["after"]["failed_checks"]["median"] > 0
