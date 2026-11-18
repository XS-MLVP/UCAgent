"""Verify final result publication, reusable tools, and shared-input integration."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest
import yaml

from act4_privileged_suite import environment, resources
from act4_privileged_suite.checkers.act4_final_report_checker import ACT4FinalReportChecker
from act4_privileged_suite.checkers.act4_resource_checker import ACT4ResourceChecker
from act4_privileged_suite.resource_tools import ACT4Resources
from ucagent.tools.uctool import to_mcp_tool

from test_act4_environment import plan_for
from test_act4_review_checker import ReviewHarness


@pytest.mark.parametrize("git_input", [True, False])
def test_generation_patch_contains_only_declared_sources_and_applies(tmp_path, git_input):
    """Publish a portable patch without including tools, reports, or unrelated user files."""
    source = tmp_path / "riscv-arch-test"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=test@example.org", "commit", "--allow-empty", "-qm", "baseline"], check=True)
    head = resources.git_text(source, "rev-parse", "HEAD") if git_input else None
    if not git_input:
        (source / ".git").rename(tmp_path / "unused-git")
    (source / "case.py").write_bytes(b'"""New source."""\r\nVALUE = 1\r\n')
    (source / "private.log").write_text("not part of the contribution")
    output = tmp_path / "out"
    intermediate = output / "intermediate/Suite/reports"
    intermediate.mkdir(parents=True)
    (output / "final.md").write_text("\n# Final result\n\nOnly the declared source is proposed.\n")
    record = {"path": "riscv-arch-test/case.py", "category": "contribution_source", "existed_before": False,
              "sha256_before": None, "sha256_after": hashlib.sha256((source / "case.py").read_bytes()).hexdigest()}
    manifest = {"baseline": {"git_head": head}, "contribution_set": [record["path"]], "files": [record]}
    (intermediate / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    checker = ACT4FinalReportChecker(report_file="out/final.md", contribution_manifest="out/intermediate/Suite/reports/manifest.yaml",
                                    patch_file="out/changes.patch", act4_root="riscv-arch-test").set_workspace(str(tmp_path))
    passed, result = checker.do_check()
    assert passed, result
    patch = output / "changes.patch"
    assert b"case.py" in patch.read_bytes() and b"private.log" not in patch.read_bytes()
    target = tmp_path / "received"
    target.mkdir()
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=target, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=target, check=True)
    assert (target / "case.py").read_bytes() == (source / "case.py").read_bytes()
    (source / "case.py").write_text("changed after manifest")
    assert not checker.do_check()[0]


@pytest.mark.parametrize("target", ["riscv-arch-test/case.py", "out/manifest.yaml", "out/final.md"])
def test_contribution_patch_cannot_overwrite_its_inputs(tmp_path, target):
    """Reject overlapping publication paths before changing any user-authored artifact."""
    (tmp_path / "riscv-arch-test").mkdir()
    output = tmp_path / "out"
    output.mkdir()
    (output / "final.md").write_text("\n# Review result\n\nKeep this report.\n")
    (output / "manifest.yaml").write_text("baseline: {git_head: null}\nfiles: []\ncontribution_set: []\n")
    (tmp_path / "riscv-arch-test/case.py").write_text("original source")
    previous = (tmp_path / target).read_bytes()
    checker = ACT4FinalReportChecker(report_file="out/final.md", contribution_manifest="out/manifest.yaml", patch_file=target,
                                    act4_root="riscv-arch-test").set_workspace(str(tmp_path))
    assert not checker.do_check()[0]
    assert (tmp_path / target).read_bytes() == previous


@pytest.mark.parametrize("preexisting", [False, True])
def test_modified_source_patch_requires_exact_preexisting_baseline(tmp_path, preexisting):
    """Refuse to absorb an unknown preexisting user edit into a generated contribution patch."""
    source = tmp_path / "riscv-arch-test"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "case.py").write_bytes(b"original\n")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=test@example.org", "commit", "-qm", "baseline"], check=True)
    head = resources.git_text(source, "rev-parse", "HEAD")
    (source / "case.py").write_bytes(b"proposed\n")
    output = tmp_path / "out"
    output.mkdir()
    (output / "final.md").write_text("\n# Result\n\nSource proposal.\n")
    record = {"path": "riscv-arch-test/case.py", "category": "contribution_source", "existed_before": True,
              "sha256_before": hashlib.sha256(b"user edit\n" if preexisting else b"original\n").hexdigest(),
              "sha256_after": hashlib.sha256(b"proposed\n").hexdigest()}
    (output / "manifest.yaml").write_text(yaml.safe_dump({"baseline": {"git_head": head}, "contribution_set": [record["path"]], "files": [record]}))
    checker = ACT4FinalReportChecker(report_file="out/final.md", contribution_manifest="out/manifest.yaml", patch_file="out/changes.patch",
                                    act4_root="riscv-arch-test").set_workspace(str(tmp_path))
    passed, result = checker.do_check()
    assert passed is not preexisting, result
    assert (output / "changes.patch").exists() is not preexisting


def test_environment_reuses_tool_from_old_run_and_ignores_changed_executable(tmp_path, monkeypatch):
    """Reuse a verified old installation despite changed plan prose, but re-probe its actual bytes."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    search = tmp_path / "output"
    previous = search / "old/out/intermediate/Old/environment"
    previous.mkdir(parents=True)
    old_plan = plan_for(previous)
    first = environment.prepare(previous, old_plan, 60)
    current = search / "new/out/intermediate/New/environment"
    current.mkdir(parents=True)
    resource_dir = current.parent / "resources"
    resource_dir.mkdir()
    (resource_dir / "receipt.json").write_text(json.dumps({"search_root": str(search)}))
    plan = plan_for(current)
    plan["tools"][-1]["basis"] = "Another explanation of the same supported tool version"
    (current / "plan.yaml").write_text(yaml.safe_dump(plan))
    reused = environment.prepare(current, plan, 60)
    assert reused["tools"]["fixture"]["origin"] == "existing_output"
    assert reused["tools"]["fixture"]["executable"] == first["tools"]["fixture"]["executable"]
    Path(first["tools"]["fixture"]["executable"]).write_text("#!/bin/sh\necho wrong-version\n")
    recovered = environment.prepare(current, plan, 60)
    assert recovered["tools"]["fixture"]["origin"] == "installed"
    assert environment.prepared_environment(current)


def test_tool_recipe_does_not_depend_on_descriptive_prose(tmp_path, monkeypatch):
    """Changing installation justification cannot create a duplicate versioned tool directory."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    plan = plan_for(tmp_path)
    first = environment.prepare(tmp_path, plan, 60)
    plan["tools"][-1]["basis"] = "Same dependency, another run's description"
    (tmp_path / "plan.yaml").write_text(yaml.safe_dump(plan))
    second = environment.prepare(tmp_path, plan, 60)
    assert second["tools"]["fixture"]["prefix"] == first["tools"]["fixture"]["prefix"]
    assert second["tools"]["fixture"]["origin"] == "cache"


def test_resource_reader_converts_to_mcp(tmp_path):
    """The read-only resource interface has the same bounded schema locally and through MCP."""
    tool = ACT4Resources(workspace=str(tmp_path), resource_dir="out/intermediate/H/resources",
                         inputs={"act4": "riscv-arch-test", "manual": "riscv-isa-manual"}, write_dirs=["out"])
    converted = to_mcp_tool(tool)
    assert converted.name == "ACT4Resources"
    assert converted.parameters["additionalProperties"] is False
    assert converted.parameters["properties"]["limit"]["maximum"] == 200
    assert not tool.invoke({"action": "status"})["ok"]


def test_review_consumes_shared_sources_and_keeps_report_links_valid(tmp_path):
    """A review using an external shared pin still creates isolated evidence and navigable root results."""
    workspace = tmp_path / "output/run"
    workspace.mkdir(parents=True)
    harness = ReviewHarness(workspace)
    resources.git_text(harness.source, "branch", "-M", "act4")
    resources.git_text(harness.source, "remote", "add", "origin", resources.REPOSITORIES["act4"][1])
    previous = tmp_path / "output/old"
    previous.mkdir()
    harness.source.rename(previous / "riscv-arch-test")
    manual = workspace / "riscv-isa-manual"
    manual.mkdir()
    preparation = ACT4ResourceChecker("reports/intermediate/H/resources", "review",
                                     {"act4": "riscv-arch-test", "manual": "riscv-isa-manual"})
    preparation.set_workspace(str(workspace)).set_stage_manager(harness.manager)
    passed, result = preparation.do_check(action="prepare")
    assert passed, result
    shared = Path(result["resources"]["act4"]["path"])
    before = resources.repository_identity(shared, clean=True)
    review = harness.audit()
    review["changes"] = []
    harness.write("review.yaml", review)
    assert harness.checker("repair").do_check(run_commands=True)[0]
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "No source changes; evidence retained",
        "findings": [{"id": "F1", "status": "deferred", "reason": "Need the actual ISA scope",
                      "next_action": "Provide the selected ISA input", "evidence": ["review.yaml"]}],
        "ci_passed": True, "remaining_risks": ["Deferred finding"], "coverage_changes": [], "traceability": []})
    passed, result = harness.checker("final").do_check()
    assert passed, result
    assert not harness.source.exists()
    assert resources.repository_identity(shared, clean=True) == before
    assert not (harness.output / "final.md").exists()
    assert not (harness.output / "changes.patch").exists()
    text = (harness.results / "final.md").read_text()
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if "://" not in target and not target.startswith("#"):
            assert (harness.results / target.split("#", 1)[0]).exists(), target
