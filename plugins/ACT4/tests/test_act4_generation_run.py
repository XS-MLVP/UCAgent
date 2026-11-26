"""Prove ISA-first mixed-source generation, baseline integrity and integrated repair evidence."""

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from ucagent_act4.checkers.act4_generation_run_checker import ACT4GenerationRunChecker
from ucagent_act4.checkers.act4_asset_checklist_checker import ACT4AssetChecklistChecker
from ucagent_act4.checkers.act4_review_checker import ACT4ReviewChecker
from ucagent_act4.checkers import act4_generation_run_checker as generation_run
from ucagent_act4.generation_run import import_receipt
from ucagent_act4.plugin import get_plugin
from ucagent_act4.resources import git_text
from ucagent_act4.run_config import ASSET_TYPES, resolve_run_config
from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


class GenerationHarness(ReviewHarness):
    """Extend the real review fixture with policy-driven import and a writable generation tree."""

    def __init__(self, root: Path, policies=None, has_spec=True, partial_ids=(), extra_reference=False):
        """Prepare clean external ACT sources and an independently accepted ISA design."""
        workspace = root / "workspace"
        workspace.mkdir()
        super().__init__(workspace, accept_plan=False)
        upstream = root / "upstream"
        self.source.rename(upstream)
        self.source = workspace / "act4-inputs"
        guide = get_plugin().root / "Guide_Doc/ACT4_Extension_Review_Guide.md"
        plan = yaml.safe_load(re.findall(r"```yaml\n(.*?)```", guide.read_text(), re.DOTALL)[-1])
        (workspace / "isa-fixture.adoc").write_text(plan["requirements"][0]["basis"][0]["quote"] + "\n" + ("Another supported configuration.\n" if extra_reference else ""))
        if extra_reference:
            plan["reference_scope"]["isa-fixture.adoc"]["excluded_reason"] = "Second configuration initially outside the selected scope"
            plan["source_reviews"].append({"source": "excluded:isa-fixture.adoc:2-2", "requirements": [],
                "reason": "Second configuration initially considered outside scope", "basis": [{"path": "isa-references/isa-fixture.adoc",
                "lines": [2, 2], "quote": "Another supported configuration.", "observation": "Additional configuration"}]})
        if not has_spec:
            plan.update(reference_files=[], reference_scope={}, requirements=[], source_reviews=[],
                        limitations=["No ISA source selected for this limited static-review fixture"])
        self.settings = resolve_run_config({"schema_version": 1, "suite": "H", "workflow": "privileged-suite-generation",
            "workspace": str(workspace), "output": "reports", "target_context": plan["target_context"],
            "upstream": {"act4_root": str(upstream)}, "assets": policies or {}, "accepted_partial_findings": list(partial_ids)}, root)
        self.scope["reference_files"] = plan["reference_files"]
        self.scope["reference_scope"] = plan["reference_scope"]
        self.write("scope.yaml", self.scope)
        self.write("isa-plan.yaml", plan)
        passed, result = self.checker("plan").do_check(is_complete=True)
        assert passed, result
        self.selection = {"schema_version": 1, "suite": "H", "repositories": {}, "assets": {
            name: {"files": [], "reason": "Determine applicability against the independent fixture requirement", "requirements": [item["id"] for item in plan["requirements"]]}
            for name in ASSET_TYPES}}
        self.selection["assets"]["tests"]["files"] = [{"repository": "act4", "path": "generators/H.py", "local_path": None}]
        self.inputs = self.output.parent / "asset-inputs"
        self.inputs.mkdir()

    def checker(self, phase):
        """Construct the actual generation-integrated review gate."""
        checker = ACT4ReviewChecker(phase, "H", "reports/intermediate/H/review", "reports/intermediate/H/review-results",
            act4_root="act4-inputs", generation_root="riscv-arch-test", cfg={"act4_run": self.settings})
        return checker.set_workspace(str(self.root)).set_stage_manager(self.manager)

    def run_checker(self, phase="inputs"):
        """Use the same frozen configuration for source selection and final delivery."""
        checker = ACT4GenerationRunChecker("H", "reports", phase, cfg={"act4_run": self.settings})
        return checker.set_workspace(str(self.root)).set_stage_manager(self.manager)

    def import_sources(self):
        """Execute source import rather than manufacturing an import receipt."""
        (self.inputs / "selection.yaml").write_text(yaml.safe_dump(self.selection))
        return self.run_checker().do_check(action="import")


def test_import_waits_for_independent_plan_and_freezes_selection(tmp_path):
    """Deny premature discovery and detect edits to both immutable baselines and selection."""
    harness = GenerationHarness(tmp_path)
    key = "act4_review:reports/intermediate/H/review:H"
    state = harness.data.pop(key)
    assert not harness.run_checker().do_check(action="discover")[0]
    harness.data[key] = state
    assert harness.run_checker().do_check(action="discover")[0]
    passed, result = harness.import_sources()
    assert passed, result
    assert harness.run_checker().do_check(is_complete=True)[0]
    selection = harness.inputs / "selection.yaml"
    selection.write_text(selection.read_text() + "\n")
    assert not harness.run_checker().do_check()[0]


def test_import_rejects_selection_changed_while_sources_are_cloned(tmp_path, monkeypatch):
    """The frozen receipt must describe the exact selection used to build source snapshots."""
    harness = GenerationHarness(tmp_path)
    original_clone = generation_run.clone_local

    def mutate_selection(source, target, *args, **kwargs):
        """Change the public selection after its parsed snapshot has entered import."""
        original_clone(source, target, *args, **kwargs)
        if target.name == "baseline-act4":
            selection_path = harness.inputs / "selection.yaml"
            selection = yaml.safe_load(selection_path.read_text())
            selection["assets"]["tests"]["files"] = []
            selection_path.write_text(yaml.safe_dump(selection))

    monkeypatch.setattr(generation_run, "clone_local", mutate_selection)
    passed, result = harness.import_sources()
    assert not passed and "changed during import" in result["error"]
    assert not (harness.root / "riscv-arch-test").exists()
    assert not (harness.inputs / "receipt.json").exists()


def test_dependency_repository_id_is_rejected_before_import_when_noncanonical(tmp_path):
    """Use the same lowercase dependency-ID contract during import and checklist planning."""
    harness = GenerationHarness(tmp_path)
    harness.selection["repositories"] = {"Sail": "intermediate/H/dependency-sources/Sail"}
    passed, result = harness.import_sources()
    assert not passed and "Dependency repository IDs must match" in result["error"]


def test_missing_local_source_requires_generation_not_upstream_reuse(tmp_path):
    """An explicit local-missing policy cannot silently classify a bundled upstream file as reused."""
    empty = tmp_path / "empty-local"
    empty.mkdir()
    harness = GenerationHarness(tmp_path, {"tests": {"source": "local", "path": str(empty), "on_missing": "generate"}})
    harness.selection["assets"]["tests"]["files"] = []
    passed, result = harness.import_sources()
    assert passed, result
    plan_path = harness.output.parent / "asset_checklist.yaml"
    plan_path.write_text(yaml.safe_dump({"schema_version": 1, "suite": "H", "repositories": {"act4": "riscv-arch-test"},
                                         "items": [{"category": category, "action": "reuse"} for category in ASSET_TYPES]}))
    checker = ACT4AssetChecklistChecker("H", "reports/intermediate/H/asset_checklist.yaml",
        "reports/intermediate/H/inputs", "reports/intermediate/H/environment", "reports/intermediate/H/asset-validation",
        "reports/dependency-patches", phase="plan", cfg={"act4_run": harness.settings})
    checker.set_workspace(str(harness.root)).set_stage_manager(harness.manager)
    passed, result = checker.do_check()
    assert not passed and "missing; generate a new asset" in result["error"]


def test_absent_shared_input_needs_no_fabricated_isa_link(tmp_path):
    """Import a suite without fake obligations, source files or a working dependency fork."""
    harness = GenerationHarness(tmp_path)
    harness.selection["assets"]["norm_rules"].update(files=[], requirements=[], reason="No suite-specific rules selected; use frozen specification")
    passed, report = harness.import_sources()
    assert passed, report
    assert report["policies"]["norm_rules"]["on_missing"] == "report" and set(report["sources"]) == {"act4"}


def test_missing_local_shared_input_cannot_fall_back_to_upstream(tmp_path):
    """A missing local rules file can be reported, never silently borrowed from the ACT checkout."""
    local = tmp_path / "empty-local"
    local.mkdir()
    harness = GenerationHarness(tmp_path, {"norm_rules": {"source": "local", "path": str(local), "on_missing": "report"}})
    harness.selection["assets"]["norm_rules"].update(files=[], requirements=[])
    passed, result = harness.import_sources()
    assert passed, result
    (harness.output.parent / "asset_checklist.yaml").write_text(yaml.safe_dump({"schema_version": 1, "suite": "H", "repositories": {"act4": "riscv-arch-test"},
                                                                          "items": [{"category": "norm_rules", "action": "reference"}]}))
    checker = ACT4AssetChecklistChecker("H", "reports/intermediate/H/asset_checklist.yaml", "reports/intermediate/H/inputs", "reports/intermediate/H/environment",
                                        "reports/intermediate/H/asset-validation", "reports/dependency-patches", cfg={"act4_run": harness.settings})
    passed, result = checker.set_workspace(str(harness.root)).set_stage_manager(harness.manager).do_check()
    assert not passed and "local shared input is absent" in result["error"]


@pytest.mark.parametrize("patch", [False, True])
def test_local_sources_and_patch_only_outputs(tmp_path, patch):
    """Reconstruct selected native sources without modifying originals or silently importing other categories."""
    local = tmp_path / "previous"
    local.mkdir()
    harness = GenerationHarness(tmp_path, {"tests": {"source": "local", "path": str(local)}})
    source = Path(harness.settings["upstream"]["act4_root"])
    item = harness.selection["assets"]["tests"]["files"][0]
    if patch:
        (source / "generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 4\n')
        (source / "README.md").write_text("Unselected documentation change\n")
        (local / "changes.patch").write_text(git_text(source, "diff", "HEAD") + "\n")
        subprocess.run(["git", "-C", str(source), "restore", "."], check=True)
        item.update(local_path="changes.patch", patch_base=git_text(source, "rev-parse", "HEAD"))
    else:
        (local / "H.py").write_text('"""Native H generator fixture."""\nVALUE = 4\n')
        item["local_path"] = "H.py"
    passed, result = harness.import_sources()
    assert passed, result
    assert "VALUE = 4" in (harness.source / "generators/H.py").read_text()
    assert "VALUE = 4" in (harness.root / "riscv-arch-test/generators/H.py").read_text()
    assert "Unselected" not in (harness.source / "README.md").read_text()
    original = local / item["local_path"]
    original.write_text(original.read_text() + "\n")
    passed, result = harness.run_checker().do_check()
    assert not passed and "local asset changed" in result["error"]


@pytest.mark.parametrize("failure", ["missing", "wrong_base", "unappliable", "duplicate", "binary"])
def test_input_failures_do_not_publish_sources(tmp_path, failure):
    """Report unresolvable local choices and patch conflicts before exposing a generation checkout."""
    local = tmp_path / "previous"
    local.mkdir()
    harness = GenerationHarness(tmp_path, {"tests": {"source": "local", "path": str(local)}})
    item = harness.selection["assets"]["tests"]["files"][0]
    if failure == "missing":
        harness.selection["assets"]["tests"]["files"] = []
    elif failure == "duplicate":
        (local / "H.py").write_text("valid source\n")
        item["local_path"] = "H.py"
        harness.selection["assets"]["testplan"]["files"] = [{**item, "local_path": None}]
    elif failure == "binary":
        (local / "H.elf").write_bytes(b"\x7fELFdata")
        item["local_path"] = "H.elf"
    else:
        (local / "changes.patch").write_text("not an applicable patch\n")
        item.update(local_path="changes.patch", patch_base="f" * 40 if failure == "wrong_base" else git_text(Path(harness.settings["upstream"]["act4_root"]), "rev-parse", "HEAD"))
    passed, result = harness.import_sources()
    assert not passed, result
    assert not (harness.root / "riscv-arch-test").exists()
    assert not (harness.inputs / "receipt.json").exists()


def test_regeneration_excludes_old_design_and_accepts_planned_changes(tmp_path):
    """Retain old bytes only for machine comparison, never as before-review source assets."""
    harness = GenerationHarness(tmp_path, {"tests": {"mode": "regenerate"}})
    passed, result = harness.import_sources()
    assert passed, result
    assert (harness.source / "generators/H.py").is_file()
    assert not (harness.root / "riscv-arch-test/generators/H.py").exists()
    passed, result = harness.checker("audit").do_check()
    assert not passed and "regenerat" in str(result).lower(), result
    harness.scope["assets"]["generators"] = []
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check()
    assert passed, result
    assert not (harness.output / "baseline/generators/H.py").exists()
    receipt = import_receipt(harness.root, harness.settings, harness.data.get)
    assert receipt["repositories"]["act4"]["removed"] == ["generators/H.py"]


def test_repair_excluded_reference_without_changing_baseline_or_fabricating_patch(tmp_path):
    """Add an omitted reference range only to after evidence and require its actual quotation."""
    harness = GenerationHarness(tmp_path, extra_reference=True)
    assert harness.import_sources()[0]
    review = harness.audit()
    review["changes"] = []
    review["findings"][0]["classification"] = "validation_gap"
    review["findings"][0]["evidence"] = ["references/isa-fixture.adoc"]
    review["semantic_review"] = harness.assess(review)
    harness.write("review.yaml", review)
    assert harness.checker("audit").do_check(is_complete=True)[0]
    before = (harness.output / "evidence-before.json").read_bytes()
    review["scope_repairs"] = {"F1": {"isa-fixture.adoc": [[1, 2]]}}
    harness.write("review.yaml", review)
    passed, result = harness.checker("repair").do_check(run_commands=True)
    assert not passed and "nonoverlapping" in result["error"]
    review["scope_repairs"]["F1"]["isa-fixture.adoc"] = [[2, 2]]
    harness.write("review.yaml", review)
    passed, result = harness.checker("repair").do_check(run_commands=True)
    assert passed, result
    final = {"suite": "H", "schema_version": 1, "summary": "Additional reference reviewed", "ci_passed": True,
        "remaining_risks": ["Synthetic fixture does not establish ISA completeness"], "coverage_changes": [], "traceability": [], "findings": [{"id": "F1", "status": "fixed",
        "classification": "validation_gap", "reason": "The after scope now includes the omitted section", "evidence": ["evidence-after.json"]}]}
    harness.write_final(final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert not passed and "newly reviewed" in result["error"]
    for item in final["semantic_review"]["judgments"]:
        if item["tasks"] in (["finding:F1"], ["source:specification:isa-fixture.adoc:2-2"]):
            item.update(status="passed", confidence="confirmed", basis=[{"path": "references/isa-fixture.adoc", "lines": [2, 2],
                "quote": "Another supported configuration.", "observation": "After scope includes second configuration"}])
    harness.write("final.yaml", final)
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    assert (harness.output / "evidence-before.json").read_bytes() == before
    assert (harness.output.parent / "review-results/changes.patch").read_bytes() == b""


@pytest.mark.parametrize("modify,partial", [(False, False), (False, True), (True, False)])
def test_integrated_review_uses_generated_sources_and_empty_patch(tmp_path, modify, partial):
    """Drive real before/after review over an imported baseline, including a no-change result."""
    harness = GenerationHarness(tmp_path, partial_ids=["F1"] if partial else [])
    assert harness.import_sources()[0]
    review = harness.audit()
    if not modify:
        review["changes"] = []
        harness.write("review.yaml", review)
    else:
        (harness.root / "riscv-arch-test/generators/H.py").write_text('"""Native H generator fixture."""\nVALUE = 2\n')
    assert harness.checker("audit").do_check(is_complete=True)[0]
    passed, result = harness.checker("repair").do_check(run_commands=True)
    assert passed, result
    harness.write_final({"schema_version": 1, "suite": "H", "summary": "Validated fixture source disposition",
        "findings": [{"id": "F1", "status": "fixed" if modify else "deferred", "reason": "Fixture disposition", "next_action": "Inspect the remaining fixture semantic gap", "evidence": ["evidence-after.json"]}],
        "ci_passed": True, "remaining_risks": ["Synthetic fixture does not prove ISA semantics"], "coverage_changes": [], "traceability": []})
    if modify:
        candidate = harness.output / "candidate/generators/H.py"
        candidate.write_text('"""Native H generator fixture."""\nVALUE = 3\n')
        passed, result = harness.checker("final").do_check(is_complete=True)
        assert not passed and "candidate" in result["error"].lower()
        candidate.write_bytes((harness.root / "riscv-arch-test/generators/H.py").read_bytes())
    elif not partial:
        passed, result = harness.checker("final").do_check(is_complete=True)
        assert not passed and result["error_code"] == "act4_local_repair_required"
        assert result["observed"]["items"][0]["id"] == "F1" and result["observed"]["items"][0]["paths"]
        final = yaml.safe_load((harness.output / "final.yaml").read_bytes())
        finding = final["findings"][0]
        blocker, basis = finding["blocker"], finding["investigation"][0]["basis"]
        blocker["stop_reason"] = "budget_exhausted"
        for resource in ("tokens", "seconds", "experiments"):
            blocker["budget"] = {"resource": resource, "limit": 1, "consumed": 1, "basis": basis}
            harness.write("final.yaml", final)
            passed, result = harness.checker("final").do_check(is_complete=True)
            assert not passed and resource.rstrip("s") in result["error"].lower(), result
        blocker.pop("budget")
        blocker.update(stop_reason="external_dependency", owner="upstream", alternatives=[
            {"route": route, "status": "ruled_out", "result": "Fixture input is absent on this route", "basis": basis}
            for route in ("suite_local", "positive_subset", "native_entrypoint", "validation_only")])
        harness.write("final.yaml", final)
        passed, result = harness.checker("final").do_check(is_complete=True)
        assert passed, result
        return
    passed, result = harness.checker("final").do_check(is_complete=True)
    assert passed, result
    patch = harness.output.parent / "review-results/changes.patch"
    if modify:
        reuse = json.loads((harness.output / "reuse-final.json").read_bytes())["judgments"]
        assert set(reuse) == {"source:specification:isa-fixture.adoc:1-1"}
    assert bool(patch.read_text()) is modify
    accepted = json.loads((harness.output / "final-accepted.json").read_text())
    assert accepted["summary"] == "Validated fixture source disposition"
    items = [{"id": category, "category": category, "action": "reuse", "required": True,
              "scope": "Fixture native source", "reason": "Preserve selected baseline", "repository": "act4",
              "artifacts": ["riscv-arch-test/generators/H.py"], "report": None, "oracle": None,
              "checks": [{"kind": "inspect", "argv": [sys.executable, "check.py"], "cwd": "riscv-arch-test",
                          "inputs": ["riscv-arch-test/generators/H.py"], "outputs": {"result.txt": "text"}, "exit_code": 0, "diagnostic": None}]}
             for category in ASSET_TYPES]
    (harness.output.parent / "asset_checklist.yaml").write_text(yaml.safe_dump({"schema_version": 1, "suite": "H",
        "repositories": {"act4": "riscv-arch-test"}, "items": items}))
    report = harness.root / "reports/final.md"
    report.write_text("\n# Result\n\n" + accepted["summary"] + "\n\n[Review](intermediate/H/review-results/final.md)\n")
    assert not harness.run_checker("final").do_check()[0]
    table = (harness.inputs / "policies.md").read_text()
    outcome = "complete; fixed: 1; local pending: 0" if modify else "partial; fixed: 0; local pending: 1"
    assert f"Finding scope: {outcome}; external pending: 0." in table.splitlines()
    report.write_text(report.read_text() + table)
    passed, result = harness.run_checker("final").do_check(is_complete=True)
    assert passed, result
    assert (harness.root / "reports/changes.patch").read_bytes() == patch.read_bytes()
    review_report = harness.output.parent / "review-results/final.md"
    review_report.write_text("")
    passed, result = harness.run_checker("final").do_check(is_complete=True)
    assert not passed and "review report changed" in result["error"]
    report.write_text(report.read_text().replace(table, "\n```markdown\n" + table + "```\n"))
    assert not harness.run_checker("final").do_check()[0]
    (harness.root / "riscv-arch-test/generators/H.py").write_text("changed after verification\n")
    assert not harness.checker("final").do_check(is_complete=True)[0]


def test_planned_generation_does_not_require_an_invented_defect(tmp_path):
    """Authorize planned changes by accepted ISA IDs and reject invented requirement references."""
    harness = GenerationHarness(tmp_path)
    assert harness.import_sources()[0]
    review = harness.audit()
    review["changes"][0]["findings"] = []
    review["changes"][0]["requirements"] = harness.selection["assets"]["tests"]["requirements"]
    harness.write("review.yaml", review)
    passed, result = harness.checker("repair").do_check()
    assert passed, result
    review["changes"][0]["requirements"] = ["I999"]
    harness.write("review.yaml", review)
    passed, result = harness.checker("repair").do_check()
    assert not passed and "accepted ISA requirements" in result["error"]


def test_shared_source_requires_compatible_category_policies(tmp_path):
    """Allow genuinely shared input files without allowing one category to override another."""
    harness = GenerationHarness(tmp_path)
    harness.selection["assets"]["testplan"]["files"] = [dict(harness.selection["assets"]["tests"]["files"][0])]
    passed, result = harness.import_sources()
    assert passed, result
    receipt = import_receipt(harness.root, harness.settings, harness.data.get)
    assert set(receipt["owners"]["act4:generators/H.py"]) == {"tests", "testplan"}


def test_missing_isa_retains_limited_existing_asset_review(tmp_path):
    """Do not demand invented ISA IDs merely to import and statically inspect existing sources."""
    harness = GenerationHarness(tmp_path, has_spec=False)
    passed, result = harness.import_sources()
    assert passed, result
    passed, result = harness.checker("audit").do_check()
    assert passed, result
