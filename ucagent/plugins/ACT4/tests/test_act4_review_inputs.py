"""Validate local asset inputs without weakening the existing review evidence contract."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from act4_privileged_suite.workspace import validate_review_paths
from act4_privileged_suite.plugin import get_plugin
from ucagent.plugins import PluginError
from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


@pytest.fixture
def local_review(tmp_path: Path) -> ReviewHarness:
    """Supply a user-selected module directory without Git metadata."""
    harness = ReviewHarness(tmp_path)
    (harness.source / ".git").rename(tmp_path / "saved-git")
    directory = tmp_path / "local-module"
    harness.source.rename(directory)
    harness.source = directory
    return harness


def test_local_directory_review_repair_and_patch(local_review: ReviewHarness) -> None:
    """Run the same audit, isolated validation, repair and delivery for a non-Git module."""
    harness = local_review
    harness.audit()
    baseline = json.loads((harness.output / "baseline.json").read_text())
    assert baseline["input"] == {"root": "local-module", "kind": "directory"}
    assert baseline["head"] is None
    assert harness.checker("repair").do_check()[0]
    (harness.output / "candidate/generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 2\n')
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Fixed the local fixture",
        "findings": [{"id": "F1", "status": "fixed", "reason": "Updated local generator", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Synthetic fixture does not certify ISA semantics"],
        "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    subprocess.run(["git", "apply", "--check", str(harness.output / "changes.patch")], cwd=harness.source, check=True)
    assert "VALUE = 1" in (harness.source / "generators/H.py").read_text()
    assert not (harness.source / "result.txt").exists()
    assert not (harness.source / ".git").exists()
    assert "Local source snapshot" in (harness.output / "final.md").read_text()


@pytest.mark.parametrize("mutation", ["source", "baseline", "mode", "new_dependency"])
def test_local_directory_input_drift_fails(local_review: ReviewHarness, mutation: str) -> None:
    """Bind local evidence to the complete source snapshot, including modes and new files."""
    harness = local_review
    assert harness.checker("audit").do_check()[0]
    path = (harness.output / "baseline" if mutation == "baseline" else harness.source) / "generators/H.py"
    if mutation == "mode":
        path.chmod(path.stat().st_mode ^ 0o100)
    elif mutation == "new_dependency":
        (harness.source / "helper.py").write_text('"""Added dependency."""\n')
    else:
        path.write_text('"""Changed source."""\n')
    passed, result = harness.checker("audit").do_check()
    assert not passed and "baseline changed" in result["error"]


def test_local_directory_symlink_escape_rejected(local_review: ReviewHarness) -> None:
    """Never import a local dependency outside its declared input root."""
    harness = local_review
    (harness.root / "secret.txt").write_text("outside input")
    (harness.source / "link.txt").symlink_to("../secret.txt")
    passed, result = harness.checker("audit").do_check()
    assert not passed and "escapes" in result["error"]


@pytest.mark.parametrize("source,output,manual", [
    ("local-module", "reports", "manual"),
    ("../outside", "reports", "manual"),
    ("/absolute", "reports", "manual"),
    (".", "reports", "manual"),
    ("local-module", "local-module/out", "manual"),
    ("reports/input", "reports", "manual"),
    ("local-module", "reports", "local-module/manual"),
    ("local-module", "reports", "reports/manual"),
    ("local-module", ".", "manual"),
])
def test_review_path_contract(tmp_path: Path, source: str, output: str, manual: str) -> None:
    """Validate configurable input boundaries before any workflow initialization writes."""
    values = {"template_overwrite.ACT4_REVIEW_ROOT": source, "template_overwrite.ACT4_MANUAL_ROOT": manual}
    config = SimpleNamespace(get_value=values.__getitem__)
    if (source, output, manual) == ("local-module", "reports", "manual"):
        assert validate_review_paths(config, {"WORKSPACE": str(tmp_path), "OUT": output}) == {}
    else:
        with pytest.raises(PluginError):
            validate_review_paths(config, {"WORKSPACE": str(tmp_path), "OUT": output})


def test_local_commands_do_not_depend_on_git(local_review: ReviewHarness, monkeypatch) -> None:
    """Preserve generation's tool prerequisites without imposing Git on directory review."""
    harness = local_review
    original = subprocess.run

    def run(argv, **kwargs):
        """Reject any Git invocation after switching to a directory input."""
        assert argv[0] != "git", argv
        return original(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    harness.audit()
    generation, review = get_plugin().workflows[:2]
    assert not generation.command_requirements
    assert not review.command_requirements


def test_local_assets_with_missing_validation_entrypoints(local_review: ReviewHarness) -> None:
    """Deliver honest partial review when local assets lack build and execution entrypoints."""
    harness = local_review
    (harness.source / "check.py").unlink()
    for job in harness.scope["jobs"]:
        if job["purpose"] != "environment":
            job.update(disposition="unavailable", reason="Local module has no runnable validation entrypoint; implementation can be reviewed but not validated")
    harness.write("scope.yaml", harness.scope)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Local asset defect retained; no executable validation entrypoint",
        "findings": [{"id": "F1", "status": "deferred", "reason": "No validated repair", "next_action": "Design the local fixture entrypoint", "evidence": ["evidence-after.json"]}],
        "ci_passed": False, "remaining_risks": ["Local validation is unavailable; no upstream CI claim"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    assert not (harness.output / "changes.patch").read_text()
    assert "incomplete or failed" in (harness.output / "final.md").read_text()
