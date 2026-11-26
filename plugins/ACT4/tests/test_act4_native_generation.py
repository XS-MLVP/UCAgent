"""Exercise both native plan styles, contribution boundaries and execution receipts offline."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4.generation_assets import contribution_path_allowed, plan_records, validate_native_assets
from ucagent_act4.checkers import act4_native_validation_checker as validation
from ucagent_act4.checkers.act4_native_assets_checker import ACT4NativeAssetsChecker
from ucagent_act4.checkers.act4_asset_consistency import parse_canonical_sheet
from ucagent_act4.xiangshan_bundle import execute as execute_command


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
    write(root, "framework/src/act/data/Gemfile", "")
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
    native_path = "testplans/priv/Example.yaml" if kind == "privileged" else "testplans/Example.csv"
    write(inputs, "receipt.json", json.dumps({"schema_version": 2, "native_plans": [native_path],
                                             "source_plans": {}, "companion_plans": {}}))
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
            write(root, f"tests/rv{xlen}i/Example/Example-add-00.S",
                  f"##### START_TEST_CONFIG #####\n# REQUIRED_EXTENSIONS: [I]\n# MARCH: rv{xlen}i\n"
                  f"# params:\n#   MXLEN: {xlen}\n##### END_TEST_CONFIG #####\n.text\nadd x3,x1,x2\n")
        coverage = "unpriv"
    write(root, f"coverpoints/{coverage}/Example_coverage.svh", "covergroup Example_cg;\ncp_rd: coverpoint ins.rd;\nendgroup\n")
    write(root, f"coverpoints/{coverage}/Example_coverage_init.svh", "Example_cg = new;\n")
    write(root, "coverpoints/norm/Example.yaml", "normative_rule_definitions:\n- name: test_rule\n  coverpoint: [cp_rd]\n")
    write(root, "docs/ctp/src/example.adoc", "include::{testplansdir}/Example.adoc[]\ninclude::norm/Example_norm_rules.adoc[]\n")
    contract = {"schema_version": 1, "suite": "Example", "kind": kind,
                "parameters": {"status": "not_applicable", "names": [], "rationale": "No variable parameter in selected rules"},
                "ctp_sources": ["docs/ctp/src/example.adoc"], "extension_sources":
                ["generators/testgen/src/testgen/priv/extensions/Example.py"] if kind == "privileged" else [],
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
    path = assets.root / "tests/rv64i/Example/Example-add-00.S"
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
        native_path = result["native_plans"][0]
        original = (assets.root / native_path).read_text()
        receipt = json.loads((assets.inputs / "receipt.json").read_text())
        snapshot = "plans/" + native_path
        receipt["source_plans"][native_path] = snapshot
        write(assets.inputs, "receipt.json", json.dumps(receipt))
        if assets.kind == "privileged":
            write(assets.inputs, snapshot, original.replace("cp_rd", "cp_deleted"))
        else:
            write(assets.inputs, snapshot, original.replace("add,", "sub,"))
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
    write(inputs, "receipt.json", json.dumps({"native_plans": ["testplans/Example.csv"],
                                             "source_plans": {"testplans/Example.csv": "plans/testplans/Example.csv"}}))
    write(inputs, "plans/testplans/Example.csv", "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\n")
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


def test_frozen_tracked_source_can_be_validated_as_a_deletion(assets):
    """A deleted path remains eligible only when its frozen baseline exists."""
    name = "tests/rv64/Example/deleted.S"
    path = write(assets.root, name, ".text\n")
    subprocess.run(["git", "-C", str(assets.root), "add", name], check=True)
    path.unlink()
    assert not contribution_path_allowed(assets.root, name)
    assert contribution_path_allowed(assets.root, name, allow_missing=True)


@pytest.fixture
def runner(assets, monkeypatch):
    """Run real local clone/apply isolation with controlled native command outcomes."""
    result = check_assets(assets)
    head = subprocess.check_output(["git", "-C", str(assets.root), "rev-parse", "HEAD"], text=True).strip()
    manifest = {"baseline": {"git_head": head}, "contribution_set": ["riscv-arch-test/" + name for name in result["required_sources"]]}
    manifest_path = write(assets.workspace, "out/manifest.yaml", yaml.safe_dump(manifest))
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


@pytest.mark.parametrize("stdout,code,success", [('[{"name":"MXLEN"}]', 0, True), ('not JSON', 0, False),
                                                ('[{"name":"OTHER"}]', 0, False), ('{}', 0, False),
                                                ('[{"name":"MXLEN"}]', 1, False)])
def test_native_udb_stdout_and_failure_receipts(runner, monkeypatch, stdout, code, success):
    """Keep diagnostics out of JSON and publish an attributable current receipt even on malformed output."""
    assets = runner.assets
    assets.contract['parameters'] = {'status': 'required', 'names': ['MXLEN'], 'rationale': 'Select supported XLEN'}
    assets.path.write_text(yaml.safe_dump(assets.contract))
    mapping = 'coverpoints/param/Example.yaml'
    write(assets.root, mapping, "parameter_definitions: [{name: MXLEN, coverpoint: ['all tests'], effect: ['Width']}]\n")
    runner.manifest['contribution_set'].append('riscv-arch-test/' + mapping)
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    simulated = validation.execute

    def execute(argv, cwd, log, timeout, track, env, **kwargs):
        """Exercise real subprocess redirection while keeping unrelated consumers offline."""
        if log.stem == 'udb_parameters':
            script = f'import sys; print("info", file=sys.stderr); print({stdout!r}); sys.exit({code})'
            return execute_command([sys.executable, '-c', script], cwd, log, timeout, env=env, **kwargs)
        return simulated(argv, cwd, log, timeout, track, env)

    monkeypatch.setattr(validation, 'execute', execute)
    passed, report = runner.checker.do_check(action='validate')
    assert passed is success, report
    receipt = json.loads(runner.receipt.read_bytes())
    record = next(item for item in receipt['results'] if item['name'] == 'udb_parameters')
    assert receipt['validation_complete'] is success
    assert (runner.receipt.parent / record['log']).read_text().strip() == stdout
    stderr = runner.receipt.parent / record['stderr_log']
    assert stderr.read_text().strip() == 'info'
    if not success:
        assert report['observed'][0]['log'] == record['log']
        assert report['artifact'].endswith(record['stderr_log'] if code else record['log'])
    stderr.write_text('tampered')
    passed, diagnosis = runner.checker.do_check(is_complete=True)
    assert not passed and 'stderr' in diagnosis['error']


def test_aborted_native_attempt_withdraws_previous_receipt(runner, monkeypatch):
    """A new run cannot leave an old passing receipt next to overwritten or incomplete logs."""
    assert runner.checker.do_check(action="validate")[0]

    def unavailable(*args, **kwargs):
        """Interrupt the isolated checkout before any consumer can publish a new result."""
        raise OSError("test checkout interrupted")

    monkeypatch.setattr(validation, "clone_local", unavailable)
    passed, diagnostic = runner.checker.do_check(action="validate")
    assert not passed and "checkout interrupted" in diagnostic["error"]
    partial = json.loads(runner.receipt.read_bytes())
    assert not partial["validation_complete"] and partial["results"][0]["status"] == "incomplete"
    assert not runner.checker.do_check(is_complete=True)[0]


def test_cached_native_evidence_requires_current_schema(runner):
    """A registered digest cannot substitute for a receipt with the current evidence contract."""
    assert runner.checker.do_check(action="validate")[0]
    data = json.loads(runner.receipt.read_bytes())
    data.pop("schema_version")
    runner.receipt.write_text(json.dumps(data))
    runner.state[f"act4_native_validation:{runner.receipt.parent}"] = validation.sha256(runner.receipt)
    passed, report = runner.checker.do_check(is_complete=True)
    assert not passed and 'action' in report['error'] and 'validate' in report['error']


@pytest.mark.parametrize("case", ["limited", "suite_error", "different_baseline", "other_error", "changed_chapter",
                                  "tables_failed", "render_failed", "no_pdf", "missing_plan"])
def test_native_ctp_baseline_requires_proof_and_actual_suite_render(runner, monkeypatch, case):
    """Only an unchanged unrelated baseline defect plus successful native consumers can limit the full-book claim."""
    assets = runner.assets
    chapter = "docs/ctp/src/example.adoc"
    family = "priv/" if assets.kind == "privileged" else ""
    write(assets.root, chapter, f"include::{{testplansdir}}/{family}Example.adoc[]\ninclude::norm/Example_norm_rules.adoc[]\n")
    write(assets.root, 'coverpoints/norm/Other.yaml', 'normative_rule_definitions: []\n')
    subprocess.run(['git', '-C', str(assets.root), 'add', '--', chapter, 'coverpoints/norm/Other.yaml'], check=True)
    subprocess.run(['git', '-C', str(assets.root), '-c', 'user.name=Fixture', '-c', 'user.email=test@example.org',
                    '-c', 'commit.gpgsign=false', 'commit', '-qm', 'CTP baseline'], check=True)
    head = validation.git_text(assets.root, 'rev-parse', 'HEAD')
    validation.read_generation_inputs(None, None)['act4']['head'] = head
    runner.manifest['baseline']['git_head'] = head
    if case != 'changed_chapter':
        runner.manifest['contribution_set'].remove('riscv-arch-test/' + chapter)
    else:
        with (assets.root / chapter).open('a') as stream:
            stream.write('\nChanged CTP content\n')
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    simulated = validation.execute

    def execute(argv, cwd, log, timeout, track, env):
        """Simulate native tool outcomes but use the real fresh candidate and pinned baseline checkouts."""
        result = simulated(argv, cwd, log, timeout, track, env)
        name = log.stem
        if name in {'ctp', 'ctp_baseline'}:
            mapping = 'Example' if case == 'suite_error' else 'Other'
            rule = 'other_rule' if name == 'ctp_baseline' and case == 'different_baseline' else 'missing_rule'
            log.write_text(f"Error: {cwd}/coverpoints/norm/{mapping}.yaml: 1 rules not in norm-rules.json: {rule}\n"
                           "make: *** [Makefile:187: normrules] Error 1\n" + ('Error: other failure\n' if case == 'other_error' else ''))
            result.update(status='failed', exit_code=2)
        if name == 'ctp_testplans' and case != 'missing_plan':
            write(cwd, f'docs/ctp/build/generated/testplans/{family}Example.adoc', 'Plan table')
        if name == 'ctp_suite_tables':
            view = Path(next(arg.split('=', 1)[1] for arg in argv if arg.startswith('REPO_ROOT=')))
            assert sorted(path.name for path in (view / 'coverpoints/norm').glob('*.yaml')) == ['Example.yaml']
            write(cwd, 'docs/ctp/build/generated/norm/Example_norm_rules.adoc', 'Rule table')
            if case == 'tables_failed':
                result['status'] = 'failed'
        if name == 'ctp_suite_render':
            if case != 'no_pdf':
                write(cwd, 'docs/ctp/build/act4-suite-tables.pdf', '%PDF-1.7 rendered')
            write(cwd, 'docs/ctp/build/act4-suite-tables.html', '<!DOCTYPE html>rendered')
            if case == 'render_failed':
                result['status'] = 'failed'
        return result

    monkeypatch.setattr(validation, 'execute', execute)
    passed, report = runner.checker.do_check(action='validate')
    assert passed == (case == 'limited'), report
    receipt = json.loads(runner.receipt.read_bytes())
    assert receipt['validation_complete'] == passed
    records = {item['name']: item for item in receipt['results']}
    assert records['ctp']['exit_code'] == 2
    if passed:
        assert records['ctp']['status'] == 'baseline_limited' and records['ctp_baseline']['command_status'] == 'failed'
        assert records['ctp']['missing_rules'] == {'Other.yaml': ['missing_rule']}
        assert records['ctp']['reason'] in report['source_limitations']
        assert set(records['ctp_suite_render']['outputs']) == {'act4-suite-tables.pdf', 'act4-suite-tables.html'}
        assert runner.checker.do_check(is_complete=True)[0]
        summary = {key: receipt[key] for key in ('asset_completeness', 'validation_complete', 'source_limitations', 'submission_requirements')}
        summary['limitations'] = []
        final = write(assets.workspace, 'out/final.md', '```yaml\n' + yaml.safe_dump({'generation_result': summary}) + '```\n')
        runner.checker.final_report = 'out/final.md'
        assert not runner.checker.do_check()[0]
        summary['limitations'] = ['ctp']
        final.write_text('```yaml\n' + yaml.safe_dump({'generation_result': summary}) + '```\n')
        assert runner.checker.do_check()[0]
        changed = records['ctp_baseline']['log'] if assets.kind == 'privileged' else 'act4-suite-tables.pdf'
        (runner.receipt.parent / changed).write_text('modified')
        assert not runner.checker.do_check(is_complete=True)[0]
    else:
        assert records['ctp']['status'] == 'failed'
        if case == 'render_failed':
            assert report['artifact'].endswith('ctp_suite_render.log') and report['failure_key'] == 'ctp_suite_render:failed'
        assert not runner.checker.do_check(is_complete=True)[0]


def test_incremental_native_validation_allows_unchanged_imported_sources(runner, monkeypatch):
    """Validate a zero-diff imported overlay without demanding fictitious contributions or Git commits."""
    import shutil

    baseline = runner.assets.workspace / "selected-inputs"
    shutil.copytree(runner.assets.root, baseline)
    state = validation.source_state(baseline)
    imported = {"repositories": {"act4": {"baseline": "selected-inputs", "working": "riscv-arch-test",
                "baseline_state": state, "working_initial": state, "removed": []}}}
    monkeypatch.setattr(validation, "run_settings", lambda cfg: {"suite": "Example"})
    monkeypatch.setattr(validation, "import_receipt", lambda *args: imported)
    runner.manifest["contribution_set"] = []
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report
    assert report["validation_complete"]
    assert runner.checker.do_check(is_complete=True)[0]
    assert validation.source_state(baseline) == state


def test_native_validation_accepts_deleted_source_from_pinned_git_baseline(runner):
    """Allow a valid source deletion when the pinned commit proves its original bytes existed."""
    if runner.assets.kind != "privileged":
        pytest.skip("Unprivileged assets restrict contributions to declared assembly sources")
    name = "riscv-arch-test/Makefile"
    runner.manifest["contribution_set"].append(name)
    runner.manifest_path.write_text(yaml.safe_dump(runner.manifest))
    (runner.assets.root / "Makefile").unlink()
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report
    assert report["validation_complete"]


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


def test_unavailable_free_native_executable_requires_completion(runner):
    """Free native consumers must be installed or implemented, not excused as commercial tools."""
    runner.controls["unavailable"] = "source_hooks"
    passed, report = runner.checker.do_check(action="validate")
    assert not passed and "source_hooks" in report["error"]
    receipt = json.loads(runner.receipt.read_text())
    assert not receipt["validation_complete"]
    assert next(result for result in receipt["results"] if result["name"] == "source_hooks")["status"] == "unavailable"


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
                        lambda directory, get_value: {"suite": "Example", "kind": assets.kind, "act4": {"path": str(assets.root)},
                                                      "native_plans": json.loads((assets.inputs / "receipt.json").read_text())["native_plans"]})
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
            (assets.root / "tests/rv32i/Example/Example-add-00.S").unlink()
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


def test_native_variants_and_vector_metadata_are_not_duplicate_requests(tmp_path):
    """Instruction identity includes formatter and extra extensions; EFFEW is not a coverpoint."""
    path = write(tmp_path, "Vector.csv", "Instruction,Type,RV32,RV64,ExtraExtensions,EFFEW8,EFFEW16,cp_rd\n"
                 "vadd.vv,VVV,x,x,,x,x,x\nvadd.vv,VVV,x,x,Zvbb,x,x,x\nvadd.vv,VVV_MASK,x,x,,x,x,x\n")
    records = plan_records(path, "unprivileged", "Vector")
    assert set(records) == {"vadd.vv|VVV|", "vadd.vv|VVV|Zvbb", "vadd.vv|VVV_MASK|"}
    path.write_text(path.read_text() + "vadd.vv,VVV,x,x,,x,x,x\n")
    with pytest.raises(ValueError, match="duplicate"):
        plan_records(path, "unprivileged", "Vector")


@pytest.mark.parametrize("assets", ["privileged"], indirect=True)
def test_incomplete_source_plan_is_input_not_a_generation_prerequisite(assets):
    """Empty or descriptive source plans may be completed while preserving their requests."""
    receipt = json.loads((assets.inputs / "receipt.json").read_text())
    snapshot = "plans/testplans/priv/Example.yaml"
    receipt["source_plans"]["testplans/priv/Example.yaml"] = snapshot
    write(assets.inputs, "receipt.json", json.dumps(receipt))
    write(assets.inputs, snapshot, "suite: Example\ncoverpoints: []\n")
    assert check_assets(assets)["requests"] == 1
    write(assets.inputs, snapshot, "suite: Example\ncoverpoints: [{name: Register access behavior}]\n")
    with pytest.raises(ValueError, match="drops source requests"):
        check_assets(assets)
    request = "testplans/priv/Example.yaml#Register access behavior"
    assets.contract["source_request_map"] = {request: ["testplans/priv/Example.yaml#cp_rd"]}
    assets.path.write_text(yaml.safe_dump(assets.contract))
    assert check_assets(assets)["requests"] == 1
    assets.contract["source_request_map"][request] = []
    assets.path.write_text(yaml.safe_dump(assets.contract))
    with pytest.raises(ValueError, match="existing final"):
        check_assets(assets)


@pytest.mark.parametrize("assets", ["privileged"], indirect=True)
def test_composite_plans_preserve_namespaced_requests_and_all_ctp_tables(assets):
    """Identical point names in different privilege-mode plans remain separate source requests."""
    prototype = yaml.safe_load((assets.root / "testplans/priv/Example.yaml").read_text())
    plans = [f"testplans/priv/Example_{member}.yaml" for member in ("common", "S", "H")]
    receipt = json.loads((assets.inputs / "receipt.json").read_text())
    receipt.update(native_plans=plans, source_plans={name: "plans/" + name for name in plans})
    write(assets.inputs, "receipt.json", json.dumps(receipt))
    for name in plans:
        plan = dict(prototype, suite=Path(name).stem)
        if name.endswith("_common.yaml"):
            plan["coverpoints"] = [{"heading": "Shared setup for both execution modes"}]
        text = yaml.safe_dump(plan)
        write(assets.root, name, text)
        write(assets.inputs, "plans/" + name, text)
    chapter = "\n".join(f"include::{{testplansdir}}/priv/{Path(name).stem}.adoc[]" for name in plans)
    chapter += "\ninclude::norm/Example_norm_rules.adoc[]\n"
    write(assets.root, "docs/ctp/src/example.adoc", chapter)
    result = check_assets(assets)
    assert result["requests"] == 2 and set(plans) <= set(result["required_sources"])
    write(assets.root, "docs/ctp/src/example.adoc", chapter.replace("Example_H.adoc", "Unrelated.adoc"))
    with pytest.raises(ValueError, match="Example_H.adoc"):
        check_assets(assets)
    write(assets.root, "docs/ctp/src/example.adoc", chapter)
    path = assets.root / plans[-1]
    path.write_text(path.read_text().replace("cp_rd", "cp_new"))
    with pytest.raises(ValueError, match="drops source requests"):
        check_assets(assets, "plan")
    assets.contract["source_request_map"] = {plans[-1] + "#cp_rd": [plans[-1] + "#cp_new"]}
    assets.path.write_text(yaml.safe_dump(assets.contract))
    assert check_assets(assets, "plan")["requests"] == 2
    derived = assets.workspace / "out/plan.csv"
    validate_native_assets(assets.root, assets.inputs, "Example", assets.kind, assets.path, "plan", derived)
    findings = []
    sheet = parse_canonical_sheet(derived, findings)
    assert not findings and sheet["rules"] == {"test_rule"}
    assert plans[-1] + "#cp_rd" in derived.read_text()
    path.write_text(path.read_text().replace("cp_new", "cp_rd"))
    assets.contract["source_request_map"] = {}
    assets.path.write_text(yaml.safe_dump(assets.contract))
    validate_native_assets(assets.root, assets.inputs, "Example", assets.kind, assets.path, "plan", derived)
    findings = []
    assert parse_canonical_sheet(derived, findings)["row_count"] == 1
    assert not findings


def test_repeated_privileged_point_preserves_all_scenarios(tmp_path):
    """Repeated logical points aggregate rules and descriptions without dropping a scenario."""
    rows = [{"name": "cp_access / cp_result", "goal": "Check access", "description": "Machine access",
             "expectation": "Allowed", "check": "Compare result", "rules": ["machine"]},
            {"name": "cp_access", "goal": "Check access", "description": "User access", "expectation": "Trap",
             "check": "Compare cause", "rules": ["user"]}]
    path = write(tmp_path, "Example.yaml", yaml.safe_dump({"suite": "Example", "coverpoints": rows}))
    records = plan_records(path, "privileged", "Example")
    assert set(records) == {"cp_access", "cp_result"}
    assert records["cp_access"]["rules"] == ["machine", "user"]
    assert records["cp_access"]["description"] == "Machine access\nUser access"


@pytest.mark.parametrize("assets", ["privileged"], indirect=True)
def test_shared_generator_and_priv_csv_are_real_contribution_sources(assets):
    """A nested/shared generator and a privileged instruction matrix need not have a top-level twin."""
    original = assets.root / "generators/testgen/src/testgen/priv/extensions/Example.py"
    nested = "generators/testgen/src/testgen/priv/extensions/memory/shared.py"
    write(assets.root, nested, original.read_text())
    original.unlink()
    assets.contract["extension_sources"] = [nested]
    assets.path.write_text(yaml.safe_dump(assets.contract))
    matrix = "Instruction,Type,RV32,RV64,cp_rd\nadd,R,x,x,x\nsub,R,x,x,\n"
    write(assets.inputs, "plans/testplans/priv/Example.csv", matrix)
    receipt = json.loads((assets.inputs / "receipt.json").read_text())
    receipt["companion_plans"] = {"testplans/priv/Example.csv": "plans/testplans/priv/Example.csv"}
    write(assets.inputs, "receipt.json", json.dumps(receipt))
    write(assets.root, "testplans/priv/Example.csv", matrix)
    result = check_assets(assets)
    assert nested in result["required_sources"]
    assert "testplans/priv/Example.csv" in result["required_sources"]
    write(assets.root, "testplans/priv/Example.csv", matrix.replace("sub,R,x,x,\n", ""))
    with pytest.raises(ValueError, match="preserve source"):
        check_assets(assets)


def test_pending_rules_require_explicit_native_tracking(assets):
    """Source-bound IDs are usable, but cannot be silently represented as published normative tags."""
    rules = json.loads((assets.inputs / "norm-rules.json").read_text())
    rules["normative_rules"][0]["status"] = "pending_source_binding"
    write(assets.inputs, "norm-rules.json", json.dumps(rules))
    with pytest.raises(ValueError, match="untagged_upstream"):
        check_assets(assets)
    mapping = assets.root / "coverpoints/norm/Example.yaml"
    mapping.write_text("untagged_upstream: Pending Example rule-tag proposal\n" + mapping.read_text())
    assert check_assets(assets)["pending_rules"] == ["test_rule"]


@pytest.mark.parametrize("assets", ["unprivileged"], indirect=True)
def test_vector_sew_outputs_use_native_paths_and_recursive_templates(assets):
    """Vector metadata selects per-SEW files and uses native regeneration to validate SEW templates."""
    write(assets.root, "testplans/Example.csv", "Instruction,Type,RV32,RV64,EFFEW8,EFFEW16,cp_rd\nadd,R,x,x,x,x,x\n")
    assets.contract["native_suites"] = ["Example8", "Example16"]
    assets.path.write_text(yaml.safe_dump(assets.contract))
    (assets.root / "generators/coverage/src/covergroupgen/templates/cp_rd.sv").unlink()
    for width in (8, 16):
        for suffix in ("coverage", "coverage_init"):
            write(assets.root, f"coverpoints/unpriv/Example{width}_{suffix}.svh",
                  (assets.root / f"coverpoints/unpriv/Example_{suffix}.svh").read_text().replace("Example_cg", f"Example{width}_cg"))
        for xlen in (32, 64):
            source = assets.root / f"tests/rv{xlen}i/Example/Example-add-00.S"
            write(assets.root, f"tests/rv{xlen}i/Example{width}/Example{width}-add-00.S", source.read_text())
    result = check_assets(assets)
    assert result["native_suites"] == ["Example8", "Example16"]
    assert len(result["generated_tests"]) == 4
    (assets.root / "tests/rv64i/Example16/Example16-add-00.S").unlink()
    with pytest.raises(ValueError, match="Example16"):
        check_assets(assets)


def test_new_native_configs_are_generated_and_validated_in_isolation(runner):
    """Generated target configuration sources can be contributed without altering existing configs."""
    assets = runner.assets
    config, command = "config/new-model/rv64/test_config.yaml", "config/new-model/rv64/run_cmd.txt"
    write(assets.root, config, "name: rv64\n")
    write(assets.root, command, "model {elf}\n")
    assets.contract["extension_sources"].extend([config, command])
    assets.contract["validation_configs"] = [config]
    assets.path.write_text(yaml.safe_dump(assets.contract))
    manifest = yaml.safe_load(runner.manifest_path.read_text())
    manifest["contribution_set"].extend(["riscv-arch-test/" + config, "riscv-arch-test/" + command])
    runner.manifest_path.write_text(yaml.safe_dump(manifest))
    passed, report = runner.checker.do_check(action="validate")
    assert passed, report
