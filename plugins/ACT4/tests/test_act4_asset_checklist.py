"""Exercise nine-category classification, isolated validation, patches and report evidence."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4.checkers import act4_asset_checklist_checker as checklist
from ucagent_act4.run_config import resolve_run_config


def git(root, *arguments):
    """Run fixture Git without depending on the developer's commit identity."""
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def repository(root):
    """Create a tiny, clean repository with a committed source and no generated files."""
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "ACT fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "asset.txt").write_text("verified")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Create fixture source")


@pytest.fixture
def scope(tmp_path, monkeypatch):
    """Prepare a clean ACT baseline and real validators with deterministic pass/fail behavior."""
    repository(tmp_path / "act4")
    for name in ("inputs", "environment", "fixtures"):
        (tmp_path / name).mkdir()
    for name in ("inputs", "environment"):
        (tmp_path / name / "receipt.json").write_text("{}")
    (tmp_path / "fixtures/oracle.txt").write_text("Source-derived expected value: verified")
    (tmp_path / "fixtures/reject.txt").write_text("deliberately incorrect")
    (tmp_path / "validate.py").write_text('''"""Validate actual fixture input and emit a fresh test report."""
from pathlib import Path
import json
import sys
source, output = map(Path, sys.argv[1:3])
expected = Path("fixtures/oracle.txt").read_text().partition(": ")[2]
if source.read_text() != expected:
    print("rejected deliberately incorrect input")
    sys.exit(4)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('<testsuite tests="1"><testcase name="source_matches_oracle"/></testsuite>')
if "norm_rules-extract" in output.name:
    output.write_text(json.dumps({"normative_rules": [{"name": "example_rule", "text": "verified"}]}))
if "udb_params-query" in output.name:
    output.write_text(json.dumps([{"name": "MXLEN"}]))
''')
    state = {}
    manager = SimpleNamespace(get_data=state.get, set_data=state.__setitem__)
    monkeypatch.setattr(checklist, "read_generation_inputs", lambda *args: {
        "suite": "Example", "act4": {"head": git(tmp_path / "act4", "rev-parse", "HEAD")}})
    monkeypatch.setattr(checklist, "prepared_environment", lambda *args: dict(os.environ))

    def checks(identity, roles, source="act4/asset.txt"):
        """Create source-dependent checks and a distinct deliberate rejection case."""
        result = []
        for role in sorted(roles):
            selected = "fixtures/reject.txt" if role == "negative" else source
            output = f"results/{identity}-{role}.xml"
            format_name = "norm_rules" if (identity, role) == ("norm_rules", "extract") else "udb_parameters" if (identity, role) == ("udb_params", "query") else "junit"
            result.append({"kind": role, "argv": [sys.executable, "validate.py", selected, output], "cwd": ".",
                           "inputs": ["validate.py", selected, "fixtures/oracle.txt"], "outputs": {} if role == "negative" else {output: format_name},
                           "exit_code": 4 if role == "negative" else 0,
                           "diagnostic": "rejected deliberately incorrect input" if role == "negative" else None})
        return result

    plan = {"schema_version": 1, "suite": "Example", "repositories": {"act4": "act4"}, "items": []}
    for category in checklist.CATEGORIES:
        plan["items"].append({"id": category, "category": category, "action": "reuse", "required": True,
                              "scope": "Current suite on the selected target", "reason": "Pinned existing implementation",
                              "repository": "act4", "artifacts": ["act4/asset.txt"],
                              "checks": checks(category, {"inspect"}), "report": None, "oracle": None})
    plan_path = tmp_path / "checklist.yaml"

    def save():
        """Write the current canonical checklist plan."""
        plan_path.write_text(yaml.safe_dump(plan, sort_keys=False))

    def checker(phase="plan", report=None):
        """Bind a fresh checker to persisted fixture stage state."""
        return checklist.ACT4AssetChecklistChecker(
            "Example", "checklist.yaml", "inputs", "environment", "out/validation", "out/dependency-patches",
            phase=phase, final_report=report).set_workspace(str(tmp_path)).set_stage_manager(manager)

    def changed(category, action="generate", repo="act4"):
        """Plan an actual modification with all category-specific validation roles."""
        item = next(item for item in plan["items"] if item["category"] == category)
        source = f"{repo}/new-{category}.txt" if action == "generate" else f"{repo}/asset.txt"
        item.update(action=action, repository=repo, artifacts=[source],
                    checks=checks(category, checklist.CATEGORIES[category][1] | {"negative", "regression"}, source),
                    oracle={"method": "manual_examples", "sources": ["fixtures/oracle.txt"],
                            "explanation": "Expected values derived separately from the edited implementation"})
        return item, tmp_path / source

    save()
    return SimpleNamespace(root=tmp_path, plan=plan, save=save, checker=checker, changed=changed, checks=checks, state=state)


def test_reuse_has_real_compatibility_evidence_and_exact_final_checklist(scope):
    """A complete final checklist is generated from checks, not from model-authored status text."""
    assert scope.checker().do_check()[0]
    assert scope.checker().do_check(is_complete=True)[0]
    verifier = scope.checker("verify")
    assert not verifier.do_check(is_complete=True)[0]
    passed, result = verifier.do_check(action="validate")
    assert passed, result
    assert result["categories"] == 9 and result["scope_complete"]
    table = (scope.root / "out/validation/checklist.md").read_text()
    assert table.count("reused: 1") == 9
    (scope.root / "out/final.md").write_text("\n# Report\n" + table)
    assert scope.checker("verify", "out/final.md").do_check(is_complete=True)[0]
    (scope.root / "out/final.md").write_text(table.replace("reused: 1", "repaired: 1", 1))
    assert not scope.checker("verify", "out/final.md").do_check()[0]
    assert git(scope.root / "act4", "status", "--porcelain") == ""


@pytest.fixture
def shared_input(scope, monkeypatch):
    """Supply an authenticated original file separate from both the working tree and other suite assets."""
    source = scope.root / "act4/rules.txt"
    source.write_text("wrong rule")
    git(source.parent, "add", "rules.txt")
    git(source.parent, "commit", "-qm", "Freeze rules")
    shutil.copytree(source.parent, scope.root / "original")
    state = checklist.source_state(source.parent)
    settings = resolve_run_config({"schema_version": 1, "suite": "H", "workflow": "privileged-suite-generation", "workspace": "run"}, scope.root)
    imported = {"settings": settings, "owners": {"act4:rules.txt": ["norm_rules"]}, "selection": {"assets": {}},
                "repositories": {"act4": {"baseline": "original", "working": "act4", "working_initial": state, "baseline_state": state, "removed": []}}}
    monkeypatch.setattr(checklist, "run_settings", lambda cfg: settings)
    monkeypatch.setattr(checklist, "import_receipt", lambda *args: imported)
    item, _ = scope.changed("norm_rules", action="repair")
    item["artifacts"] = ["act4/rules.txt"]
    item["checks"] = scope.checks("norm_rules", checklist.CATEGORIES["norm_rules"][1] | {"negative", "regression"}, "act4/rules.txt")
    index = next(index for index, check in enumerate(item["checks"]) if check["kind"] == "semantic")
    item["oracle"]["baseline_failure"] = {"check_index": index, "exit_code": 4, "message": "rejected deliberately incorrect input"}
    return item, source


@pytest.mark.parametrize("case", ["correct", "schema", "original_passes", "wrong_message", "wrong_exit", "candidate_fails", "reproducer_changed", "wrong_owner", "missing_proof", "generate"])
def test_shared_repair_must_reproduce_on_the_frozen_source(scope, shared_input, case):
    """Require authenticated ownership, a predeclared failing original and the same passing candidate test."""
    item, source = shared_input
    if case == "schema":
        item["oracle"]["baseline_failure"]["check_index"] = next(index for index, check in enumerate(item["checks"]) if check["kind"] == "schema")
    if case == "original_passes":
        (scope.root / "fixtures/oracle.txt").write_text("Source-derived expected value: wrong rule")
    if case == "wrong_message":
        item["oracle"]["baseline_failure"]["message"] = "different defect"
    if case == "wrong_exit":
        item["oracle"]["baseline_failure"]["exit_code"] = 2
    if case == "missing_proof":
        del item["oracle"]["baseline_failure"]
    if case == "wrong_owner":
        item["artifacts"] = ["act4/asset.txt"]
    if case == "generate":
        item["action"] = "generate"
    scope.save()
    passed, result = scope.checker().do_check()
    if case in {"wrong_owner", "missing_proof", "generate", "wrong_message", "wrong_exit", "original_passes"}:
        assert not passed, result
        assert source.read_text() == "wrong rule" and not scope.state
        return
    assert passed, result
    assert scope.checker().do_check(is_complete=True)[0]
    source.write_text("still incorrect" if case == "candidate_fails" else "verified")
    if case == "reproducer_changed":
        with (scope.root / "validate.py").open("a") as stream:
            stream.write("\n")
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed is (case in {"correct", "schema"}), result
    if passed:
        data = json.loads((scope.root / "out/validation/receipt.json").read_bytes())
        assert any(row["phase"] == "baseline" and row["exit_code"] == 4 for row in data["results"])
        assert "repaired: 1" in (scope.root / "out/validation/checklist.md").read_text()
    else:
        assert not (scope.root / "out/validation/receipt.json").exists()


def test_optional_reference_is_identity_only(scope, shared_input):
    """A pinned shared input needs no manufactured validator and cannot be counted as tested."""
    item, source = shared_input
    item.update(action="reference", required=False, checks=[], oracle=None)
    scope.save()
    assert scope.checker().do_check()[0]
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed, result
    row = next(line for line in (scope.root / "out/validation/checklist.md").read_text().splitlines() if line.startswith("| Norm Rules"))
    assert "referenced (identity only): 1" in row and "0 checked" in row
    source.write_text("silently edited")
    assert not scope.checker("verify").do_check()[0]


@pytest.mark.parametrize("case", ["required", "unselected", "unfrozen", "executable"])
def test_optional_reference_rejects_false_evidence(scope, shared_input, case):
    """Do not accept reference as a route around required, provenance or execution checks."""
    item, _ = shared_input
    item.update(action="reference", required=case == "required", checks=item["checks"] if case == "executable" else [], oracle=None)
    if case in {"unselected", "unfrozen"}:
        item["artifacts"] = ["act4/asset.txt" if case == "unselected" else "fixtures/oracle.txt"]
    scope.save()
    passed, report = scope.checker().do_check()
    assert not passed and "norm_rules" in report["error"]


def test_core_category_can_include_an_optional_inapplicable_subscope(scope):
    """Retain mandatory test coverage while documenting a genuinely inapplicable target variant."""
    core = next(item for item in scope.plan["items"] if item["category"] == "tests")
    scope.plan["items"].append(dict(core, id="rv32_extra", required=False, action="not_applicable", artifacts=[], checks=[], reason="Selected instruction only exists on RV64"))
    scope.save()
    assert scope.checker().do_check()[0]


def test_regeneration_replacements_validate_old_deletions_as_well_as_new_sources(scope, monkeypatch):
    """Cover every removed original when a regeneration changes native file names."""
    import shutil

    source = scope.root / "act4"
    baseline = scope.root / "selected-inputs"
    shutil.copytree(source, baseline)
    original = checklist.source_state(baseline)
    (source / "asset.txt").unlink()
    imported = {"repositories": {"act4": {"baseline": "selected-inputs", "working": "act4",
                "baseline_state": original, "working_initial": checklist.source_state(source), "removed": ["asset.txt"]}},
                "owners": {"act4:asset.txt": list(checklist.CATEGORIES)},
                "settings": {"assets": {category: {"mode": "regenerate", "source": None, "on_missing": "generate"}
                                          for category in checklist.CATEGORIES}},
                "selection": {"assets": {category: {"files": []} for category in checklist.CATEGORIES}}}
    policies = {"assets": {category: {"mode": "regenerate"} for category in checklist.CATEGORIES}}
    monkeypatch.setattr(checklist, "run_settings", lambda cfg: policies)
    monkeypatch.setattr(checklist, "import_receipt", lambda *args: imported)
    generated = []
    for category in checklist.CATEGORIES:
        item, path = scope.changed(category)
        item["artifacts"].append("act4/asset.txt")
        generated.append(path)
    scope.save()
    passed, result = scope.checker().do_check()
    assert passed, result
    for path in generated:
        path.write_text("verified")
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed, result
    assert (baseline / "asset.txt").read_text() == "verified"


@pytest.mark.parametrize("category", checklist.CATEGORIES)
def test_every_category_requires_and_runs_its_specific_validation(scope, category):
    """Every new asset type has typed native checks, a negative case and independent regression."""
    _, source = scope.changed(category)
    scope.save()
    passed, result = scope.checker().do_check()
    assert passed, result
    source.write_text("verified")
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed, result
    assert "generated: 1" in (scope.root / "out/validation/checklist.md").read_text()
    assert source.read_text() == "verified"


@pytest.mark.parametrize("category", checklist.CATEGORIES)
def test_category_specific_roles_cannot_be_replaced_by_generic_success(scope, category):
    """A collection of passing generic checks cannot stand in for required category-specific checks."""
    item, _ = scope.changed(category)
    item["checks"] = scope.checks(category, {"inspect", "negative", "regression"})
    scope.save()
    passed, result = scope.checker().do_check()
    assert not passed and "Missing validation roles" in result["error"]


@pytest.mark.parametrize("mutation", ["source", "plan", "environment", "receipt", "log", "output", "mode"])
def test_evidence_is_bound_to_current_sources_and_results(scope, mutation):
    """Changes in either inputs or saved results invalidate Check and Complete."""
    assert scope.checker().do_check()[0]
    assert scope.checker("verify").do_check(action="validate")[0]
    receipt = scope.root / "out/validation/receipt.json"
    data = json.loads(receipt.read_text())
    outputs = [name for name in data["evidence"] if "/outputs/" in name]
    paths = {"source": "act4/asset.txt", "plan": "checklist.yaml", "environment": "environment/receipt.json",
             "receipt": "out/validation/receipt.json", "log": "out/validation/ctp-0.log", "output": outputs[0], "mode": "act4/asset.txt"}
    path = scope.root / paths[mutation]
    if mutation == "mode":
        path.chmod(0o755)
    else:
        path.write_text(path.read_text() + "\nchanged")
    assert not scope.checker("verify").do_check(is_complete=True)[0]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "core_skip", "no_checks", "escape", "empty_reason", "fake_command", "self_oracle"])
def test_invalid_plans_do_not_capture_a_baseline(scope, mutation):
    """Reject incomplete categories, placeholder validations and invalid path/provenance contracts."""
    item = scope.plan["items"][0]
    if mutation == "missing":
        scope.plan["items"].pop()
    elif mutation == "duplicate":
        scope.plan["items"].append(dict(item))
    elif mutation == "unknown":
        item["category"] = "another_type"
    elif mutation == "core_skip":
        item = next(item for item in scope.plan["items"] if item["category"] == "tests")
        item.update(action="not_applicable", required=False, artifacts=[], checks=[])
    elif mutation == "no_checks":
        item["checks"] = []
    elif mutation == "escape":
        item["artifacts"] = ["../outside"]
    elif mutation == "empty_reason":
        item["reason"] = ""
    elif mutation == "fake_command":
        item["checks"][0]["argv"] = ["true"]
    else:
        item, _ = scope.changed("norm_rules")
        item["oracle"]["sources"] = item["artifacts"]
    scope.save()
    assert not scope.checker().do_check()[0]
    assert not scope.state


def test_existing_changes_cannot_become_the_baseline(scope):
    """An already edited checkout cannot be relabeled as the original source."""
    (scope.root / "act4/asset.txt").write_text("changed")
    passed, result = scope.checker().do_check()
    assert not passed and "clean checkout" in result["error"]


@pytest.mark.parametrize("kind", ["reused_change", "unclassified", "symlink", "fake_repair", "same_oracle"])
def test_changed_sources_cannot_bypass_the_checklist(scope, kind):
    """Changes need explicit ownership and cannot masquerade as unchanged or independently justified."""
    if kind in {"fake_repair", "same_oracle"}:
        item, source = scope.changed("sail")
        if kind == "fake_repair":
            item["action"] = "repair"
        scope.save()
    assert scope.checker().do_check()[0]
    if kind == "reused_change":
        (scope.root / "act4/asset.txt").write_text("changed")
    elif kind == "unclassified":
        (scope.root / "act4/undeclared.txt").write_text("changed")
    elif kind == "symlink":
        (scope.root / "act4/asset.txt").unlink()
        (scope.root / "act4/asset.txt").symlink_to(scope.root / "fixtures/oracle.txt")
    else:
        source.write_text("verified")
        if kind == "same_oracle":
            item["oracle"]["sources"] = [source.relative_to(scope.root).as_posix()]
            scope.save()
    assert not scope.checker("verify").do_check(action="validate")[0]


@pytest.mark.parametrize("report", ["empty", "skipped", "failed", "invalid", "wrong_negative"])
def test_vacuous_tests_and_wrong_failure_causes_are_rejected(scope, report):
    """Command exit status alone cannot pass a semantic, regression or negative check."""
    item, source = scope.changed("sail")
    if report == "wrong_negative":
        next(check for check in item["checks"] if check["kind"] == "negative")["diagnostic"] = "different failure"
    else:
        texts = {"empty": "<testsuite/>", "skipped": '<testsuite><testcase><skipped/></testcase></testsuite>',
                 "failed": '<testsuite><testcase><failure/></testcase></testsuite>', "invalid": "not XML"}
        path = scope.root / "validate.py"
        path.write_text(path.read_text().replace('<testsuite tests="1"><testcase name="source_matches_oracle"/></testsuite>', texts[report]))
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified")
    assert not scope.checker("verify").do_check(action="validate")[0]


def test_report_is_visible_and_does_not_claim_required_work_complete(scope):
    """A real external blocker can be reported without pretending its capability was verified."""
    item = next(item for item in scope.plan["items"] if item["category"] == "rvvi")
    item.update(action="report", repository=None, artifacts=["fixtures/oracle.txt"], checks=[],
                report={"reason_code": "external_input", "impact": "Target trace cannot be observed", "next_action": "Provide target trace interface"})
    scope.save()
    assert scope.checker().do_check()[0]
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed and not result["scope_complete"] and result["unresolved_required"] == ["rvvi"]
    table = (scope.root / "out/validation/checklist.md").read_text()
    assert "reported: 1" in table and "Provide target trace interface" in table
    (scope.root / "out/final.md").write_text(table + "\n```yaml\nscope_completion:\n  scope_complete: true\n```\n")
    assert not scope.checker("verify", "out/final.md").do_check()[0]


def test_dependency_patch_is_separate_reproducible_and_tamper_evident(scope, tmp_path):
    """Cross-project repairs are validated and published separately from the ACT suite patch."""
    repository(scope.root / "sail")
    scope.plan["repositories"]["sail"] = "sail"
    item, source = scope.changed("sail", "repair", "sail")
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified\n")
    validator = scope.root / "validate.py"
    validator.write_text(validator.read_text().replace('source.read_text() != expected', 'source.read_text().strip() != expected'))
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed, result
    patch = scope.root / "out/dependency-patches/sail.patch"
    assert patch.is_file() and not (scope.root / "out/dependency-patches/act4.patch").exists()
    destination = tmp_path / "consumer"
    subprocess.run(["git", "clone", "-q", str(scope.root / "sail"), str(destination)], check=True)
    git(destination, "apply", "--check", str(patch))
    git(destination, "apply", str(patch))
    assert (destination / "asset.txt").read_bytes() == source.read_bytes()
    patch.write_text(patch.read_text() + "tampered")
    assert not scope.checker("verify").do_check()[0]


def test_dependency_patch_preserves_trailing_whitespace(scope, tmp_path):
    """Publish the exact Git patch bytes when a changed source line ends in spaces."""
    repository(scope.root / "sail")
    scope.plan["repositories"]["sail"] = "sail"
    _, source = scope.changed("sail", "repair", "sail")
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_bytes(b"verified \n")
    validator = scope.root / "validate.py"
    validator.write_text(validator.read_text().replace("source.read_text() != expected", "source.read_text().strip() != expected"))
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed, result
    patch = scope.root / "out/dependency-patches/sail.patch"
    assert b"+verified \n" in patch.read_bytes()
    consumer = tmp_path / "consumer"
    subprocess.run(["git", "clone", "-q", str(scope.root / "sail"), str(consumer)], check=True)
    subprocess.run(["git", "-C", str(consumer), "apply", "--check", str(patch)], check=True)


def test_fixed_oracle_cannot_be_rewritten_to_match_the_generated_result(scope):
    """Oracle evidence is frozen before implementing the change, including files outside repositories."""
    _, source = scope.changed("tests")
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified")
    (scope.root / "fixtures/oracle.txt").write_text("Changed expectation to match implementation")
    passed, result = scope.checker("verify").do_check(action="validate")
    assert not passed and "oracle sources changed" in result["error"]


def test_missing_private_dependency_is_not_available_in_isolated_validation(scope):
    """Validation cannot accidentally succeed only because a private workspace file exists."""
    (scope.root / "private.txt").write_text("hidden dependency")
    script = scope.root / "validate.py"
    script.write_text(script.read_text() + '\nassert Path("private.txt").exists()\n')
    assert scope.checker().do_check()[0]
    assert not scope.checker("verify").do_check(action="validate")[0]


def test_stale_output_is_not_accepted_as_a_fresh_result(scope):
    """The isolated run does not import prewritten pass reports from the original workspace."""
    output = scope.root / "results/norm_rules-inspect.xml"
    output.parent.mkdir()
    output.write_text('<testsuite><testcase name="stale"/></testsuite>')
    (scope.root / "validate.py").write_text('"""Intentionally do not produce evidence."""\n')
    assert scope.checker().do_check()[0]
    passed, result = scope.checker("verify").do_check(action="validate")
    assert not passed and "Missing or empty" in result["error"]


def test_negative_missing_command_does_not_count_as_expected_failure(scope):
    """Unavailable tools must not masquerade as deliberately rejected bad inputs."""
    item, source = scope.changed("rvvi")
    for check in item["checks"]:
        check["argv"][0] = "missing-act4-validator-command"
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified")
    assert not scope.checker("verify").do_check(action="validate")[0]


def test_concurrent_source_change_invalidates_validation(scope, monkeypatch):
    """A successful isolated run cannot authenticate a concurrently changed original source."""
    assert scope.checker().do_check()[0]
    execute = checklist.execute

    def change_source(*args, **kwargs):
        """Modify the original only after the actual validator has run in the isolated copy."""
        result = execute(*args, **kwargs)
        if "validate.py" in args[0]:
            (scope.root / "act4/asset.txt").write_text("concurrent edit")
        return result

    monkeypatch.setattr(checklist, "execute", change_source)
    passed, result = scope.checker("verify").do_check(action="validate")
    assert not passed and "Sources changed during validation" in result["error"]


@pytest.mark.parametrize("format_name,content", [
    ("norm_rules", '{"normative_rules": []}'),
    ("norm_rules", '{"normative_rules": [{"name":"same","text":"a"},{"name":"same","text":"b"}]}'),
    ("udb_parameters", '[]'),
    ("udb_parameters", '[{"name":"MXLEN"},{"name":"MXLEN"}]'),
    ("elf", 'not an ELF'),
    ("json", '{}'),
    ("yaml", '[]'),
])
def test_native_evidence_formats_reject_empty_or_invalid_data(tmp_path, format_name, content):
    """Native rule/parameter outputs and binary artifacts have independent structural validation."""
    path = tmp_path / "result"
    path.write_text(content)
    with pytest.raises(ValueError):
        checklist.verify_output(path, format_name)


def test_duplicate_or_fenced_final_checklist_is_not_a_visible_single_summary(scope):
    """The report needs one visible canonical checklist, not a hidden or contradictory copy."""
    assert scope.checker().do_check()[0]
    assert scope.checker("verify").do_check(action="validate")[0]
    table = (scope.root / "out/validation/checklist.md").read_text()
    path = scope.root / "out/final.md"
    for text in ("```markdown\n" + table + "```\n", table + "\n## Asset checklist\n\nContradictory summary\n"):
        path.write_text(text)
        assert not scope.checker("verify", "out/final.md").do_check()[0]


def test_checklist_is_wired_only_into_generation_and_keeps_all_existing_stages():
    """Review/handoff remain independent and generation gets plan, verify and final gates."""
    from ucagent_act4.plugin import get_plugin

    for workflow in get_plugin().workflows:
        stages = yaml.safe_load(workflow.config_file.read_text())["stage"]
        gates = [(stage["name"], gate) for stage in stages for gate in stage["checker"]
                 if gate["clss"] == "ACT4AssetChecklistChecker"]
        if workflow.name.endswith("suite-generation"):
            assert [name for name, _ in gates] == ["plan_missing_capabilities", "verify_completed_capabilities", "generate_final_human_report"]
            assert [gate["args"]["phase"] for _, gate in gates] == ["plan", "verify", "verify"]
            assert gates[-1][1]["args"]["final_report"] == "{OUT}/final.md"
        else:
            assert not gates
        for stage in stages:
            assert len({gate["name"] for gate in stage["checker"]}) == len(stage["checker"])


def test_guide_contains_a_complete_canonical_nine_category_example():
    """The mandatory non-Skill guide provides an executable current-format example for every category."""
    import re

    document = Path(checklist.__file__).parents[1] / "Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md"
    text = document.read_text()
    plan = yaml.safe_load(re.search(r"```yaml\n(.*?)\n```", text, re.S).group(1))
    assert set(plan) == {"schema_version", "suite", "repositories", "items"}
    assert {item["category"] for item in plan["items"]} == set(checklist.CATEGORIES)
    assert {item["category"] for item in plan["items"] if not item["checks"]} == {"norm_rules", "rvvi"}
    assert all((not item["required"] and item["action"] in {"reference", "not_applicable"}) or item["checks"] for item in plan["items"])
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6} ", line):
            assert index and not lines[index - 1].strip()


def test_optional_category_can_be_genuinely_inapplicable(scope):
    """A scoped optional requirement can be inapplicable without inventing source assets or checks."""
    item = next(item for item in scope.plan["items"] if item["category"] == "rvvi")
    item.update(action="not_applicable", required=False, repository=None, artifacts=[], checks=[],
                reason="No DUT trace integration is requested for this standalone model target")
    scope.save()
    assert scope.checker().do_check()[0]
    passed, result = scope.checker("verify").do_check(action="validate")
    assert passed and result["scope_complete"]
    assert "not applicable: 1" in (scope.root / "out/validation/checklist.md").read_text()


def test_independent_oracle_is_a_validation_input_not_only_plan_prose(scope):
    """Semantic validation must declare its immutable expected-result dependencies explicitly."""
    item, _ = scope.changed("rvvi")
    for check in item["checks"]:
        check["inputs"].remove("fixtures/oracle.txt")
    scope.save()
    passed, result = scope.checker().do_check()
    assert not passed and "oracle sources as inputs" in result["error"]


def test_validation_cannot_directly_reference_the_original_workspace(scope):
    """A declared absolute source/script path cannot silently bypass the isolated checkout."""
    scope.plan["items"][0]["checks"][0]["argv"][1] = str(scope.root / "validate.py")
    scope.save()
    passed, result = scope.checker().do_check()
    assert not passed and "original workspace" in result["error"]


def test_invalid_negative_pattern_is_an_actionable_diagnostic(scope):
    """A malformed rejection expression must fail Check without crashing the stage."""
    item, _ = scope.changed("tests")
    next(check for check in item["checks"] if check["kind"] == "negative")["diagnostic"] = "[invalid pattern"
    scope.save()
    passed, result = scope.checker().do_check()
    assert not passed and result["error_code"] == "act4_asset_checklist"
    assert result["artifact"] == "checklist.yaml#tests"


def test_source_state_preserves_leading_spaces_in_git_paths(scope):
    """Git's NUL-delimited paths cannot be stripped before resolving source files."""
    path = scope.root / "act4/ leading-space.txt"
    path.write_text("verified")
    state = checklist.source_state(scope.root / "act4")
    assert state["files"][path.name]["sha256"] == checklist.sha256(path)


def test_validators_cannot_repair_the_isolated_source_during_checks(scope):
    """Validation proves the provided change, not an undisclosed corrected version in its clone."""
    validator = scope.root / "validate.py"
    validator.write_text(validator.read_text() + '\nif "tests-inspect" in output.name:\n    source.write_text("modified during validation")\n')
    assert scope.checker().do_check()[0]
    passed, result = scope.checker("verify").do_check(action="validate")
    assert not passed and "Validators changed source files" in result["error"]
    assert (scope.root / "act4/asset.txt").read_text() == "verified"


@pytest.mark.parametrize("preserve_edit", [False, True])
def test_revalidation_withdraws_old_patches_but_preserves_user_edits(scope, preserve_edit):
    """Failed revalidation must not leave an obsolete generated patch as a current deliverable."""
    repository(scope.root / "sail")
    scope.plan["repositories"]["sail"] = "sail"
    _, source = scope.changed("sail", repo="sail")
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified")
    verifier = scope.checker("verify")
    passed, result = verifier.do_check(action="validate")
    assert passed, result
    patch = scope.root / "out/dependency-patches/sail.patch"
    if preserve_edit:
        patch.write_text("user edit to retain")
    (scope.root / "validate.py").write_text('raise RuntimeError("validation now fails")\n')
    passed, result = verifier.do_check(action="validate")
    assert not passed and not verifier.do_check(is_complete=True)[0]
    if preserve_edit:
        assert patch.read_text() == "user edit to retain"
        assert "preserve it elsewhere" in result["error"]
    else:
        assert not patch.exists()


def test_dependency_patch_publication_does_not_overwrite_unowned_file(scope):
    """Preexisting user patch files remain untouched even after all checks pass."""
    repository(scope.root / "sail")
    scope.plan["repositories"]["sail"] = "sail"
    _, source = scope.changed("sail", repo="sail")
    scope.save()
    assert scope.checker().do_check()[0]
    source.write_text("verified")
    patch = scope.root / "out/dependency-patches/sail.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("existing user patch")
    passed, result = scope.checker("verify").do_check(action="validate")
    assert not passed and "unowned dependency patch" in result["error"]
    assert patch.read_text() == "existing user patch"
