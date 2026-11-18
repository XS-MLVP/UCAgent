"""Exercise both native plan styles, contribution boundaries and execution receipts offline."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4.generation_assets import contribution_path_allowed, plan_records, validate_native_assets
from ucagent_act4.checkers import act4_native_validation_checker as validation
from ucagent_act4.checkers.act4_native_assets_checker import ACT4NativeAssetsChecker
from ucagent_act4.checkers.act4_asset_consistency import parse_canonical_sheet


def write(root, name, content):
    """Create an explicit text fixture under its configured root."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def commit(root):
    """Commit a fixture using a local-only identity without developer configuration."""
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.org",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)


@pytest.fixture(params=["privileged", "unprivileged"])
def assets(tmp_path, request):
    """Provide complete native assets with a real Git tracking policy and unchanged native config."""
    kind = request.param
    root = tmp_path / "riscv-arch-test"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    write(root, ".gitignore", "work*/\ntests/priv/**/*.S\n!tests/priv/PMP*/**/*.S\n")
    write(root, "Makefile", "tests:\n\t@true\nelfs:\n\t@true\n")
    write(root, "config/spike/rv64/test_config.yaml", "name: rv64\n")
    write(root, "config/spike/rv64/run_cmd.txt", "spike --isa=RV64IM {elf}\n")
    write(root, "generators/ctp/generate_norm_table.py", '"""Include _parameters.adoc."""\n')
    write(root, "docs/ctp/src/ctp.adoc", "include::example.adoc[]\n")
    write(root, "generators/coverage/src/covergroupgen/templates/cp_rd.sv", "cp_rd: coverpoint ins.rd;\n")
    write(root, "generators/coverage/src/covergroupgen/templates/sample_R.sv", "ins.add_rd(0);\n")
    for filename in ("RISCV_coverage_base_init.svh", "RISCV_coverage_base_sample.svh", "RISCV_instruction_sample.svh"):
        write(root, "coverpoints/coverage/" + filename, "native aggregate fixture\n")
    commit(root)
    inputs = tmp_path / "out/inputs"
    write(inputs, "norm-rules.json", json.dumps({"normative_rules": [{"name": "test_rule", "text": "A normative requirement."}]}))
    write(inputs, "published-norm-rules.json", (inputs / "norm-rules.json").read_text())
    write(inputs, "testplan.schema.json", json.dumps({"type": "object"}))
    if kind == "privileged":
        plan = {"suite": "Example", "coverpoints": [{"name": "cp_rd", "goal": "Access", "description": "Exercise register",
                                                    "expectation": "The expected value", "check": "Compare signature", "rules": ["test_rule"]}]}
        write(root, "testplans/priv/Example.yaml", yaml.safe_dump(plan))
        write(root, "generators/testgen/src/testgen/priv/extensions/Example.py", '"""Suite generator fixture."""\n')
        coverage = "priv"
    else:
        write(root, "testplans/Example.csv", "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
        for xlen in (32, 64):
            write(root, f"tests/rv{xlen}/Example/Example-add-00.S",
                  f"##### START_TEST_CONFIG #####\n# REQUIRED_EXTENSIONS: [I]\n# MARCH: rv{xlen}i\n"
                  f"# params:\n#   MXLEN: {xlen}\n##### END_TEST_CONFIG #####\n.text\nadd x3,x1,x2\n")
        coverage = "unpriv"
    write(root, f"coverpoints/{coverage}/Example_coverage.svh", "covergroup Example_cg;\ncp_rd: coverpoint ins.rd;\nendgroup\n")
    write(root, f"coverpoints/{coverage}/Example_coverage_init.svh", "Example_cg = new;\n")
    write(root, "coverpoints/norm/Example.yaml", "normative_rule_definitions:\n- name: test_rule\n  coverpoint: [cp_rd]\n")
    write(root, "docs/ctp/src/example.adoc", "include::{testplansdir}/Example.adoc[]\ninclude::norm/Example_norm_rules.adoc[]\n")
    contract = {"schema_version": 1, "suite": "Example", "kind": kind,
                "parameters": {"status": "not_applicable", "names": [], "rationale": "No variable parameter in selected rules"},
                "ctp_sources": ["docs/ctp/src/example.adoc"], "extension_sources": [],
                "validation_configs": ["config/spike/rv64/test_config.yaml"]}
    contract_path = write(tmp_path, "out/asset_contract.yaml", yaml.safe_dump(contract))
    return SimpleNamespace(workspace=tmp_path, root=root, inputs=inputs, kind=kind, contract=contract, path=contract_path)


def check_assets(assets, phase="assets"):
    """Check the live native fixture using the public shared validator."""
    return validate_native_assets(assets.root, assets.inputs, "Example", assets.kind, assets.path, phase)


def test_table_assets_require_valid_native_selection_header(assets):
    """Reject nonempty assembly that cannot satisfy the native test metadata contract."""
    if assets.kind != "unprivileged":
        return
    path = assets.root / "tests/rv64/Example/Example-add-00.S"
    path.write_text(path.read_text().replace("# MARCH: rv64i\n", ""))
    with pytest.raises(ValueError, match="test_config_march"):
        check_assets(assets)


def test_native_asset_completeness_and_derived_views(assets):
    """Both formats produce required source sets; only privileged rows derive the internal CSV."""
    result = validate_native_assets(assets.root, assets.inputs, "Example", assets.kind, assets.path, "assets",
                                    assets.workspace / "out/plan.csv", assets.workspace / "out/plan.md")
    assert result["requests"] == 1
    assert "docs/ctp/src/example.adoc" in result["required_sources"]
    assert (assets.workspace / "out/plan.md").read_text().startswith("\n# Example Native Test Plan\n")
    assert (assets.workspace / "out/plan.csv").exists() == (assets.kind == "privileged")
    if assets.kind == "privileged":
        findings = []
        derived = parse_canonical_sheet(assets.workspace / "out/plan.csv", findings)
        assert not findings
        assert derived["rules"] == {"test_rule"}


@pytest.mark.parametrize("mutation", ["missing_norm", "unknown_rule", "missing_ctp", "missing_coverage", "bad_kind", "dropped_source"])
def test_native_incomplete_assets_are_rejected(assets, mutation):
    """Missing or inconsistent asset classes must not be accepted as contribution-complete."""
    result = check_assets(assets)
    if mutation == "missing_norm":
        (assets.root / "coverpoints/norm/Example.yaml").unlink()
    elif mutation == "unknown_rule":
        write(assets.root, "coverpoints/norm/Example.yaml", "normative_rule_definitions: [{name: invented, coverpoint: [cp_rd]}]\n")
    elif mutation == "missing_ctp":
        write(assets.root, "docs/ctp/src/example.adoc", "include::{testplansdir}/Example.adoc[]\n")
    elif mutation == "missing_coverage":
        suffix = "priv" if assets.kind == "privileged" else "unpriv"
        (assets.root / f"coverpoints/{suffix}/Example_coverage.svh").unlink()
    elif mutation == "bad_kind":
        assets.contract["kind"] = "invalid"
        assets.path.write_text(yaml.safe_dump(assets.contract))
    else:
        original = (assets.root / result["native_plan"]).read_text()
        if assets.kind == "privileged":
            write(assets.inputs, "source-plan.yaml", original.replace("cp_rd", "cp_deleted"))
        else:
            write(assets.inputs, "source-plan.csv", original.replace("add,", "sub,"))
    with pytest.raises((ValueError, OSError)):
        check_assets(assets)


@pytest.mark.parametrize("malformed", [False, True])
def test_parameter_mapping_is_conditional_and_native(assets, malformed):
    """No-parameter suites pass without a file; required parameters need native names and effects."""
    assets.contract["parameters"] = {"status": "required", "names": ["MXLEN"], "rationale": "Select supported XLEN"}
    assets.path.write_text(yaml.safe_dump(assets.contract))
    entries = {"parameter_definitions": [{"name": "MXLEN", "coverpoint": ["all tests"], "effect": ["Select matching XLEN tests"]}]}
    if malformed:
        entries["parameter_definitions"][0]["name"] = ["invalid"]
    write(assets.root, "coverpoints/param/Example.yaml", yaml.safe_dump(entries))
    if malformed:
        with pytest.raises(ValueError):
            check_assets(assets)
    else:
        assert "coverpoints/param/Example.yaml" in check_assets(assets)["required_sources"]


@pytest.mark.parametrize("content", ["Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,,x\n",
                                    "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,variant\n"])
def test_instruction_plan_cannot_drop_original_dimensions(tmp_path, content):
    """Preserve each source instruction's XLEN and selected coverpoint variant, not just its name."""
    inputs = tmp_path / "inputs"
    write(inputs, "source-plan.csv", "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
    write(tmp_path, "testplans/Example.csv", content)
    with pytest.raises(ValueError, match="preserve"):
        validate_native_assets(tmp_path, inputs, "Example", "unprivileged", tmp_path / "contract.yaml", "plan")


@pytest.mark.parametrize("content", ["Instruction,Type,RV32,RV64,cp_rd\nadd,R,,,x\n",
                                    "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,\n",
                                    "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x,extra\n"])
def test_malformed_instruction_matrices_fail(tmp_path, content):
    """Native CSV parsing rejects zero-XLEN, zero-coverpoint, and over-wide rows."""
    path = write(tmp_path, "Example.csv", content)
    with pytest.raises(ValueError):
        plan_records(path, "unprivileged", "Example")


def test_contribution_policy_obeys_upstream_git_rules(assets):
    """Tracked and unignored assembly is allowed, ignored privileged intermediates are not."""
    for name in ("tests/rv64/Example/test.S", "tests/priv/Example/test.S", "tests/priv/PMP/test.S"):
        write(assets.root, name, ".text\n")
    assert contribution_path_allowed(assets.root, "tests/rv64/Example/test.S")
    assert contribution_path_allowed(assets.root, "tests/priv/PMP/test.S")
    assert not contribution_path_allowed(assets.root, "tests/priv/Example/test.S")
    write(assets.root, "work/test.elf", "not a contribution")
    assert not contribution_path_allowed(assets.root, "work/test.elf")


@pytest.fixture
def runner(assets, monkeypatch):
    """Run real local clone/apply isolation with controlled native command outcomes."""
    result = check_assets(assets)
    head = subprocess.check_output(["git", "-C", str(assets.root), "rev-parse", "HEAD"], text=True).strip()
    manifest = {"baseline": {"git_head": head}, "contribution_set": ["riscv-arch-test/" + name for name in result["required_sources"]]}
    manifest_path = write(assets.workspace, "out/manifest.yaml", yaml.safe_dump(manifest))
    write(assets.inputs, "receipt.json", "{}\n")
    write(assets.workspace, "out/environment/receipt.json", "{}\n")
    captured = {"suite": "Example", "kind": assets.kind, "act4": {"path": str(assets.root), "head": head},
                "limitations": ["Published rule text and pinned manual are separate snapshots; compare semantics before implementation."]}
    monkeypatch.setattr(validation, "read_generation_inputs", lambda directory, get_value: captured)
    monkeypatch.setattr(validation, "prepared_environment", lambda directory, get_value: dict(os.environ))
    state = {}
    manager = SimpleNamespace(get_data=state.get, set_data=state.__setitem__)
    checker = validation.ACT4NativeValidationChecker("Example", assets.kind, "out/inputs", "out/asset_contract.yaml",
                                                     "out/manifest.yaml", "out/native", "out/environment")
    checker.set_workspace(str(assets.workspace)).set_stage_manager(manager)
    controls = {"failure": "", "unavailable": "", "zero_elf": False, "mutate": "", "calls": []}

    def execute(argv, cwd, log, timeout, track, env):
        """Record actual orchestration while simulating external compiler/model results."""
        controls["calls"].append((argv, cwd))
        assert cwd != assets.root
        assert cwd.is_relative_to(env["MISE_TRUSTED_CONFIG_PATHS"])
        assert env["MISE_TRUSTED_CONFIG_PATHS"] != str(assets.root)
        name = log.stem
        log.write_text("[]\n" if name == "udb_parameters" else "native consumer output\n")
        if name == "build_0" and not controls["zero_elf"]:
            write(cwd, "work_native/rv64/elfs/test.elf", "ELF fixture")
        if controls["mutate"] and name == "source_hooks":
            write(cwd, controls["mutate"], "hook-modified fixture\n")
        status = "failed" if name == controls["failure"] else "unavailable" if name == controls["unavailable"] else "passed"
        return {"status": status, "argv": argv}

    monkeypatch.setattr(validation, "execute", execute)
    return SimpleNamespace(assets=assets, checker=checker, controls=controls, state=state, manifest=manifest,
                           manifest_path=manifest_path, receipt=assets.workspace / "out/native/receipt.json")


def test_native_execution_receipt_and_final_report(runner):
    """Completion requires tool-created current evidence and the final summary must agree with it."""
    assert not runner.checker.do_check()[0]
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report
    assert report["validation_complete"]
    assert runner.checker.do_check(is_complete=True)[0]
    receipt = json.loads(runner.receipt.read_text())
    summary = {"asset_completeness": "complete", "validation_complete": True, "limitations": [],
               "source_limitations": receipt["source_limitations"],
               "submission_requirements": receipt["submission_requirements"]}
    final = write(runner.assets.workspace, "out/final.md", "\n# Result\n\n```yaml\n" + yaml.safe_dump({"generation_result": summary}) + "```\n")
    runner.checker.final_report = "out/final.md"
    assert runner.checker.do_check()[0]
    final.write_text(final.read_text().replace("validation_complete: true", "validation_complete: false"))
    assert not runner.checker.do_check()[0]


@pytest.mark.parametrize("change", ["source", "receipt", "log", "contract", "environment", "mode"])
def test_native_execution_rejects_stale_or_forged_evidence(runner, change):
    """Changed assets, logs or prepared inputs cannot reuse a successful native run."""
    assert runner.checker.do_check(action="validate")[0]
    path = {"source": runner.assets.root / "coverpoints/norm/Example.yaml", "receipt": runner.receipt,
            "log": runner.receipt.parent / "ctp.log", "contract": runner.assets.path,
            "environment": runner.assets.workspace / "out/environment/receipt.json",
            "mode": runner.assets.root / "coverpoints/norm/Example.yaml"}[change]
    if change == "mode":
        path.chmod(0o755)
    else:
        path.write_text(path.read_text() + "\n")
    assert not runner.checker.do_check(is_complete=True)[0]


@pytest.mark.parametrize("control,value", [("failure", "regeneration"), ("failure", "ctp"), ("failure", "build_0"),
                                         ("zero_elf", True), ("mutate", "Makefile")])
def test_native_execution_does_not_accept_false_success(runner, control, value):
    """Failing consumers, empty runs and hook changes outside the contribution never pass."""
    runner.controls[control] = value
    passed, report = runner.checker.do_check(action="validate")
    assert not passed and report["error_code"] == "act4_native_validation"


def test_unavailable_native_executable_is_a_visible_limit(runner):
    """A missing optional executable is recorded, never counted as validated."""
    runner.controls["unavailable"] = "source_hooks"
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report
    assert not report["validation_complete"]
    assert report["limitations"][0]["name"] == "source_hooks"


def test_missing_contribution_cannot_use_local_only_assets(runner):
    """The isolated validation must be reproducible from the declared contribution alone."""
    runner.manifest["contribution_set"].pop()
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    passed, report = runner.checker.do_check(action="validate")
    assert not passed and "omits" in report["error"]


def test_existing_unchanged_native_dependency_need_not_be_contributed(runner):
    """An unchanged CTP chapter already in the baseline is a dependency, not a required diff."""
    chapter = "docs/ctp/src/example.adoc"
    subprocess.run(["git", "-C", str(runner.assets.root), "add", "--", chapter], check=True)
    subprocess.run(["git", "-C", str(runner.assets.root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.org",
                    "-c", "commit.gpgsign=false", "commit", "-qm", "chapter"], check=True)
    head = subprocess.check_output(["git", "-C", str(runner.assets.root), "rev-parse", "HEAD"], text=True).strip()
    runner.manifest["baseline"]["git_head"] = head
    runner.manifest["contribution_set"].remove("riscv-arch-test/" + chapter)
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    captured = validation.read_generation_inputs(None, None)
    captured["act4"]["head"] = head
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report


def test_native_asset_checker_returns_actionable_error(assets, monkeypatch):
    """Invalid native schema/content produces a bounded artifact-specific diagnostic."""
    checker = ACT4NativeAssetsChecker("Example", assets.kind, "out/inputs", "out/asset_contract.yaml")
    checker.set_workspace(str(assets.workspace))
    monkeypatch.setattr("ucagent_act4.checkers.act4_native_assets_checker.read_generation_inputs",
                        lambda directory, get_value: {"suite": "Example", "kind": assets.kind, "act4": {"path": str(assets.root)}})
    assets.path.write_text("schema_version: 99\n")
    passed, report = checker.do_check()
    assert not passed and report["artifact"] == "out/asset_contract.yaml" and report["next_action"]


@pytest.mark.parametrize("mutation", ["parameter_target", "detached_ctp", "invalid_schema", "incomplete_row"])
def test_native_contract_failure_boundaries(assets, mutation):
    """Reject parameter typos, unreachable chapters and schema-invalid or incomplete plans."""
    if mutation == "parameter_target":
        assets.contract["parameters"] = {"status": "required", "names": ["MXLEN"], "rationale": "Register width"}
        assets.path.write_text(yaml.safe_dump(assets.contract))
        write(assets.root, "coverpoints/param/Example.yaml", "parameter_definitions: [{name: MXLEN, coverpoint: ['cp_rd, cp_typo'], effect: ['Select XLEN']}]\n")
    elif mutation == "detached_ctp":
        write(assets.root, "docs/ctp/src/ctp.adoc", "Unrelated chapter\n")
    elif assets.kind == "privileged":
        if mutation == "invalid_schema":
            write(assets.inputs, "testplan.schema.json", json.dumps({"type": "string"}))
        else:
            path = assets.root / "testplans/priv/Example.yaml"
            plan = yaml.safe_load(path.read_text())
            plan["coverpoints"][0]["check"] = ""
            path.write_text(yaml.safe_dump(plan))
    else:
        if mutation == "invalid_schema":
            write(assets.root, "testplans/Example.csv", "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\nadd,R,x,x,x\n")
        else:
            (assets.root / "tests/rv32/Example/Example-add-00.S").unlink()
    from jsonschema import ValidationError

    with pytest.raises((ValueError, ValidationError)):
        check_assets(assets)


@pytest.mark.parametrize("assets", ["unprivileged"], indirect=True)
def test_unprivileged_extension_sources_are_bounded(assets):
    """An extension list cannot authorize changes to framework, configuration or build internals."""
    assets.contract["extension_sources"] = ["Makefile"]
    assets.path.write_text(yaml.safe_dump(assets.contract))
    with pytest.raises(ValueError, match="Invalid instruction"):
        check_assets(assets)


@pytest.mark.parametrize("assets", ["unprivileged"], indirect=True)
def test_coverage_target_and_variant_must_exist(assets):
    """A real rule name alone cannot legitimize a nonexistent coverage target or template."""
    path = assets.root / "coverpoints/norm/Example.yaml"
    original = path.read_text()
    path.write_text(original.replace("cp_rd", "cp_missing"))
    with pytest.raises(ValueError, match="does not exist"):
        check_assets(assets)
    path.write_text(original)
    (assets.root / "generators/coverage/src/covergroupgen/templates/cp_rd.sv").unlink()
    with pytest.raises(ValueError, match="missing native coverage template"):
        check_assets(assets)


def test_modified_unsubmitted_framework_blocks_validation(runner):
    """Fresh or final validation cannot silently ignore a tracked framework mutation."""
    assert runner.checker.do_check(action="validate")[0]
    write(runner.assets.root, "Makefile", "tests:\n\t@echo changed\n")
    passed, report = runner.checker.do_check(is_complete=True)
    assert not passed and "outside the contribution" in report["error"]


def test_fresh_regeneration_diff_blocks_delivery(runner):
    """The native generator must reproduce the committed coverage/test source bytes."""
    execute = validation.execute

    def regenerate(argv, cwd, log, timeout, track, env):
        """Simulate an upstream consumer revealing a stale delivered coverage artifact."""
        result = execute(argv, cwd, log, timeout, track, env)
        if log.stem == "regeneration":
            coverage = "priv" if runner.assets.kind == "privileged" else "unpriv"
            write(cwd, f"coverpoints/{coverage}/Example_coverage.svh", "regenerated new content\n")
        return result

    from unittest.mock import patch

    with patch.object(validation, "execute", regenerate):
        passed, report = runner.checker.do_check(action="validate")
    assert not passed and "regeneration" in report["error"]
