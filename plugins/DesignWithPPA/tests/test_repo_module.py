"""Repository workflow isolation, real unit execution, and complete delivery regressions."""

from __future__ import annotations

import helpers  # noqa: F401

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from ucagent.util.config import Config, get_config, load_yaml_with_env_vars
from design_with_ppa.contracts import atomic_json, atomic_text, atomic_yaml
from design_with_ppa.plugin import create_tools, get_plugin
from design_with_ppa.repo.apply_bundle import apply_bundle
from design_with_ppa.repo.common import RepoPaths, git_read, inside, tree_identity
from design_with_ppa.repo.delivery import deliver, restore_best
from design_with_ppa.repo.models import Interface, Recipe, validate_python
from design_with_ppa.repo.checkers import RepoModuleChecker
from design_with_ppa.repo.common import run_command
from design_with_ppa.repo.snapshot import snapshot_repository
from design_with_ppa.repo.tools import RunRepoValidation, RunRepoValidationArgs
from design_with_ppa.repo.validation import reference_check, validate_unit, validated_records
from ucagent.plugins import PluginContext


def git(root: Path, *args: str) -> str:
    """Operate only on disposable fixture repositories with local deterministic identity."""

    return subprocess.check_output(["git", "-C", str(root), "-c", "user.name=Unit Test",
                                    "-c", "user.email=unit@example.invalid", *args], text=True).strip()


@pytest.fixture
def repo_case(tmp_path):
    """Create a complete small combinational unit task and independent Git source."""

    source = tmp_path / "source with spaces"
    source.mkdir()
    git(source, "init", "-q")
    atomic_text(source / "rtl/unit.v", "// Increment one byte.\nmodule Unit(input [7:0] a, output [7:0] y); assign y = a + 8'd1; endmodule\n")
    atomic_text(source / "README.md", "\n# Source\n\nIndependent module fixture.\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "Initial unit")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    atomic_text(workspace / "task/README.md", "\n# Task\n\nIncrement bytes modulo 256.\n")
    cfg = Config({"design_with_ppa": {"repo": {"enabled": True, "source_path": str(source)},
                                    "min_optimization_iterations": 1, "max_optimization_iterations": 1,
                                    "no_improvement_patience": 1,
                                    "no_regression_metrics": "performance,timing", "ppa": {},
                                    "score_weights": {"timing": 1.0, "area": 1.0, "power": 1.0}}})
    cfg._temp_cfg = {"OUT": "design", "DUT": "task"}
    paths = RepoPaths(workspace, cfg)
    contract = {"objective": "Increment bytes modulo 256", "target_paths": ["rtl/unit.v"],
                "allowed_changes": ["rtl/*.v"], "dependencies": [], "caller_impact": "No callers in unit scope",
                "requirements": {"increment": "Increment modulo 256"}, "result_fields": {"result": {"width": 8}},
                "clock_period_ns": 10.0, "max_latency_cycles": 10,
                "min_throughput_per_cycle": 0.1, "max_cycles": 1000}
    atomic_yaml(paths.edit / "contract.yaml", contract)
    workload = {"seed": 1, "scenarios": [{"name": "bytes", "covers": ["increment"],
                 "transactions": [{"id": f"t{i}", "inputs": {"a": i}, "release_cycle": n} for n, i in enumerate([0, 1, 127, 255])],
                 "expected_examples": {"t0": {"result": 1}, "t255": {"result": 0}}}]}
    atomic_yaml(paths.edit / "verification/workload.yaml", workload)
    atomic_text(paths.edit / "verification/reference.py", '"""Independent byte arithmetic."""\n\ndef evaluate(transactions):\n    """Return one incremented byte per logical request."""\n    return {t["id"]: {"result": (t["inputs"]["a"] + 1) % 256} for t in transactions}\n')
    candidate = paths.edit / "candidate"
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "baseline", "hypothesis": "Measure original", "changes": []})
    atomic_yaml(candidate / "interface.yaml", {"version": "v1", "top": "Unit", "pins": {
        "a": {"direction": "input", "width": 8, "purpose": "operand"},
        "y": {"direction": "output", "width": 8, "purpose": "incremented byte"}},
        "clock": None, "reset": None, "reset_active": 0, "reset_cycles": 2,
        "request_when": {}, "response_when": {}, "protocol": "Combinational modulo increment"})
    atomic_yaml(candidate / "recipe.yaml", {"scope": "unit", "rtl_files": ["rtl/unit.v"], "timeout": 300})
    atomic_text(candidate / "adapter.py", '"""Drive and sample public pins."""\n\ndef run(env, transactions):\n    """Complete each byte request."""\n    for t in transactions:\n        while env.cycle < t["release_cycle"]:\n            env.tick()\n        env.drive(a=t["inputs"]["a"])\n        env.accept(t["id"])\n        env.sample(t["id"], {"result": "y"})\n        env.tick()\n')
    atomic_text(candidate / "protocol.py", '"""Independent output boundary check."""\n\ndef test_wrap(env):\n    """Assert unsigned wrap behavior through output pins."""\n    env.drive(a=255)\n    assert env.read("y") == 0\n    env.tick()\n')
    return paths


def test_commit_snapshot_is_read_only_and_ignores_dirty_files(repo_case):
    """Default import preserves source bytes, index, modes, and committed content."""

    paths = repo_case
    atomic_text(paths.source / "rtl/unit.v", "local edit\n")
    atomic_text(paths.source / "untracked", "not selected\n")
    before = (git_read(paths.source, "status", "--porcelain=v1"), (paths.source / ".git/index").read_bytes())
    manifest = snapshot_repository(paths)
    assert manifest["local_changes_excluded"] is True
    assert "assign y" in (paths.snapshot / "rtl/unit.v").read_text()
    assert not (paths.snapshot / "untracked").exists()
    assert before == (git_read(paths.source, "status", "--porcelain=v1"), (paths.source / ".git/index").read_bytes())
    assert (paths.source / "rtl/unit.v").read_text() == "local edit\n"
    assert snapshot_repository(paths) == manifest
    atomic_text(paths.snapshot / "rtl/unit.v", "changed snapshot")
    with pytest.raises(ValueError, match="source_snapshot changed"):
        snapshot_repository(paths)


def test_worktree_snapshot_and_explicit_untracked(repo_case):
    """Working-tree import captures tracked changes/deletions and explicit untracked files."""

    paths = repo_case
    paths.cfg.set_value("design_with_ppa.repo.snapshot_mode", "working_tree")
    paths.cfg.set_value("design_with_ppa.repo.include_untracked", ["extra.v"])
    atomic_text(paths.source / "extra.v", "module Extra; endmodule\n")
    (paths.source / "README.md").unlink()
    atomic_text(paths.source / "rtl/unit.v", "modified\n")
    selected = RepoPaths(paths.workspace, paths.cfg)
    manifest = snapshot_repository(selected)
    assert not manifest["local_changes_excluded"]
    assert "README.md" not in manifest["files"]
    assert (selected.snapshot / "extra.v").is_file()
    assert (selected.snapshot / "rtl/unit.v").read_text() == "modified\n"


def test_archive_attributes_do_not_change_snapshot(repo_case):
    """Git export-ignore cannot silently omit a source dependency."""

    atomic_text(repo_case.source / ".gitattributes", "rtl/unit.v export-ignore\n")
    git(repo_case.source, "add", ".")
    git(repo_case.source, "commit", "-qm", "Archive attributes")
    assert "rtl/unit.v" in snapshot_repository(repo_case)["files"]


def test_selected_sources_exclude_unneeded_missing_submodules(repo_case):
    """An explicit dependency closure skips unrelated gitlinks but records their pins."""

    oid = git(repo_case.source, "rev-parse", "HEAD")
    git(repo_case.source, "update-index", "--add", "--cacheinfo", f"160000,{oid},missing")
    git(repo_case.source, "commit", "-qm", "Uninitialized unrelated dependency")
    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["rtl"])
    paths = RepoPaths(repo_case.workspace, repo_case.cfg)
    manifest = snapshot_repository(paths)
    assert set(manifest["files"]) == {"rtl/unit.v"}
    assert manifest["excluded_submodules"] == {"missing": oid}
    assert not manifest["submodules"]
    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["rtl", "missing"])
    with pytest.raises(ValueError, match="Submodule missing is unavailable"):
        snapshot_repository(RepoPaths(repo_case.workspace.parent / "selected-missing", repo_case.cfg))


def test_selected_sources_match_worktree_and_reject_empty_scope(repo_case):
    """Scoped worktrees preserve deletions and reject misspelled source selectors."""

    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["rtl"])
    repo_case.cfg.set_value("design_with_ppa.repo.snapshot_mode", "working_tree")
    repo_case.cfg.set_value("design_with_ppa.repo.include_untracked", ["rtl/new.v"])
    atomic_text(repo_case.source / "rtl/new.v", "module New; endmodule\n")
    (repo_case.source / "rtl/unit.v").unlink()
    manifest = snapshot_repository(RepoPaths(repo_case.workspace, repo_case.cfg))
    assert set(manifest["files"]) == {"rtl/new.v"}
    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["missing"])
    with pytest.raises(ValueError, match="outside source_paths"):
        RepoPaths(repo_case.workspace, repo_case.cfg)
    repo_case.cfg.set_value("design_with_ppa.repo.include_untracked", [])
    with pytest.raises(ValueError, match="matched no"):
        snapshot_repository(RepoPaths(repo_case.workspace.parent / "empty-scope", repo_case.cfg))


def test_submodule_is_copied_without_shared_git_or_files(repo_case, tmp_path):
    """Pinned submodule objects are read without changing the original worktree."""

    child = tmp_path / "dependency"
    child.mkdir()
    git(child, "init", "-q")
    atomic_text(child / "dep.v", "module Dep; endmodule\n")
    git(child, "add", ".")
    git(child, "commit", "-qm", "Dependency")
    git(repo_case.source, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "deps/dep")
    git(repo_case.source, "commit", "-qam", "Pin dependency")
    manifest = snapshot_repository(repo_case)
    assert manifest["submodules"]["deps/dep"] == git(child, "rev-parse", "HEAD")
    assert not (repo_case.snapshot / "deps/dep/.git").exists()
    assert (repo_case.snapshot / "deps/dep/dep.v").read_text() == "module Dep; endmodule\n"
    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["deps/dep/dep.v"])
    scoped = RepoPaths(tmp_path / "scoped-workspace", repo_case.cfg)
    selected = snapshot_repository(scoped)
    assert set(selected["files"]) == {"deps/dep/dep.v"}
    assert selected["submodules"] == manifest["submodules"]


def test_scoped_validation_rejects_unimported_changes_and_dependencies(repo_case):
    """Direct tool invocation enforces import scope as well as the stage contract."""

    repo_case.cfg.set_value("design_with_ppa.repo.source_paths", ["rtl"])
    paths = RepoPaths(repo_case.workspace, repo_case.cfg)
    path = paths.edit / "contract.yaml"
    contract = yaml.safe_load(path.read_text())
    contract["dependencies"] = ["README.md"]
    atomic_yaml(path, contract)
    with pytest.raises(ValueError, match="absent from source_snapshot"):
        validate_unit(paths, baseline=True)
    contract["dependencies"] = []
    contract["allowed_changes"].append("README.md")
    atomic_yaml(path, contract)
    atomic_yaml(paths.edit / "candidate/candidate.yaml", {"variant_id": "bad", "hypothesis": "Out of scope",
                "changes": [{"path": "README.md", "action": "add"}]})
    with pytest.raises(ValueError, match="outside imported source_paths"):
        validate_unit(paths, baseline=True)


@pytest.mark.parametrize("value", ["../escape", "/absolute", "a/../../escape", ".git/config", "a\\b"])
def test_path_escape_rejected(tmp_path, value):
    """No authored path can select the original repository or Git metadata."""

    with pytest.raises(ValueError):
        inside(tmp_path, value)


def test_source_workspace_overlap_rejected(repo_case):
    """A repository inside the writable workspace is not a valid read-only source."""

    with pytest.raises(ValueError, match="non-overlapping"):
        RepoPaths(repo_case.source / "workspace", repo_case.cfg)


def test_external_symlink_rejected(repo_case, tmp_path):
    """A tracked absolute link cannot escape the independent snapshot."""

    (repo_case.source / "outside").symlink_to(tmp_path)
    git(repo_case.source, "add", "outside")
    git(repo_case.source, "commit", "-qm", "External symlink")
    with pytest.raises(ValueError, match="escapes"):
        snapshot_repository(repo_case)


def test_reference_and_coverage_are_real(repo_case):
    """Reference examples execute, and missing requirement coverage is rejected."""

    assert reference_check(repo_case)["expected"]["bytes"]["t255"] == {"result": 0}
    path = repo_case.edit / "verification/reference.py"
    atomic_text(path, path.read_text().replace("+ 1", "+ 2"))
    with pytest.raises(ValueError, match="self-test failed"):
        reference_check(repo_case)


def test_reference_rejects_unachievable_throughput_schedule(repo_case):
    """A release schedule that caps throughput below the contract minimum is rejected early."""

    path = repo_case.edit / "verification/workload.yaml"
    original = path.read_text()
    workload = yaml.safe_load(original)
    for scenario in workload["scenarios"]:
        for index, transaction in enumerate(scenario["transactions"]):
            transaction["release_cycle"] = index * 15
    atomic_yaml(path, workload)
    with pytest.raises(ValueError, match="cannot reach min_throughput_per_cycle"):
        reference_check(repo_case)
    atomic_text(path, original)
    assert reference_check(repo_case)["expected"]["bytes"]["t255"] == {"result": 0}


def test_python_contract_rejects_internal_state(repo_case):
    """Test adapters cannot bypass public pins to read private DUT state."""

    path = repo_case.edit / "candidate/adapter.py"
    atomic_text(path, 'def run(env, transactions):\n    print(env._dut)\n')
    with pytest.raises(ValueError, match="private state"):
        validate_python(path)
    atomic_text(path, 'def run(env, transactions):\n    env.read = lambda name: 0\n')
    with pytest.raises(ValueError, match="must not replace"):
        validate_python(path)


def test_recipe_rejects_system_build_contract():
    """Only module unit scope is accepted by the new workflow."""

    with pytest.raises(ValueError):
        Recipe.model_validate({"scope": "system", "rtl_files": ["rtl/top.v"]})


def test_plugin_workflow_selection_preserves_old_tools(repo_case):
    """New workflow tools are opt-in; old workflow tool schemas remain untouched."""

    paths = repo_case
    context = PluginContext(paths.workspace, "design", ("design",), (), paths.cfg, Path.cwd())
    assert [t.name for t in create_tools(context)] == ["RunRepoValidation"]
    paths.cfg.set_value("design_with_ppa.repo.enabled", False)
    assert [t.name for t in create_tools(context)] == ["AnalyzePPA", "RunDesignConsistency"]
    assert [w.name for w in get_plugin().workflows] == ["unit-design-tdd", "repo-module-tdd"]
    assert RunRepoValidationArgs.model_json_schema()["properties"]["baseline"]["default"] is False


def test_real_unit_baseline_candidate_delivery(repo_case):
    """Run actual Yosys/Picker/STA, interface evolution, best restore, patch and rebuild."""

    if any(not shutil.which(name) for name in ("yosys", "picker", "sta", "verilator")):
        pytest.skip("Real unit toolchain is unavailable")
    paths = repo_case
    source_before = (git_read(paths.source, "status", "--porcelain=v1"), (paths.source / ".git/index").read_bytes())
    baseline = validate_unit(paths, baseline=True)
    assert baseline["accepted"] and baseline["system_integration"] == "not_run"
    candidate = paths.edit / "candidate"
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "renamed", "hypothesis": "Explore renamed public output", "changes": [{"path": "rtl/unit.v", "action": "replace"}]})
    atomic_text(candidate / "files/rtl/unit.v", (paths.source / "rtl/unit.v").read_text().replace(" y", " result"))
    interface = yaml.safe_load((candidate / "interface.yaml").read_text())
    interface["version"] = "v2"
    interface["pins"]["result"] = interface["pins"].pop("y")
    atomic_yaml(candidate / "interface.yaml", interface)
    for name in ("adapter.py", "protocol.py"):
        path = candidate / name
        atomic_text(path, path.read_text().replace('"y"', '"result"'))
    measured = validate_unit(paths)
    assert measured["accepted"]
    assert len(validated_records(paths)) == 2
    paths.cfg.set_value("design_with_ppa.repo.interface_policy", "preserve")
    # Source-selection settings are frozen too: a resumed run cannot silently
    # reinterpret the authorization under which its baseline was measured.
    with pytest.raises(ValueError, match="Source settings changed"):
        snapshot_repository(RepoPaths(paths.workspace, paths.cfg))
    paths.cfg.set_value("design_with_ppa.repo.interface_policy", "evolve")
    saved = paths.edit / "verification/workload.yaml"
    old = saved.read_text()
    atomic_text(saved, old.replace("seed: 1", "seed: 2"))
    with pytest.raises(ValueError, match="contract changed"):
        validate_unit(paths)
    atomic_text(saved, old)
    variant_path = candidate / "candidate.yaml"
    variant_yaml = yaml.safe_load(variant_path.read_text())
    variant_yaml["variant_id"] = "duplicate"
    atomic_yaml(variant_path, variant_yaml)
    with pytest.raises(ValueError, match="distinct unit experiment"):
        validate_unit(paths)
    restore_best(paths)
    result = deliver(paths, migration_script=True)
    bundle = paths.edit / "delivery"
    assert result["patch_rebuild_pass"]
    assert (bundle / "apply.py").is_file()
    assert (bundle / "changes.patch").stat().st_size > 0
    target = paths.workspace.parent / "manual target"
    shutil.copytree(paths.source, target)
    assert apply_bundle(bundle, target)["status"] == "preview"
    assert (target / "rtl/unit.v").read_bytes() == (paths.source / "rtl/unit.v").read_bytes()
    assert apply_bundle(bundle, target, apply=True)["status"] == "applied"
    with pytest.raises(ValueError, match="conflicts"):
        apply_bundle(bundle, target, apply=True)
    assert source_before == (git_read(paths.source, "status", "--porcelain=v1"), (paths.source / ".git/index").read_bytes())


def test_real_candidates_and_delivery_stage_gates(repo_case):
    """Stage gates drive measured rounds through the batch lifecycle and deliver."""

    if any(not shutil.which(name) for name in ("yosys", "picker", "sta", "verilator")):
        pytest.skip("Real unit toolchain is unavailable")
    paths = repo_case
    validate_unit(paths, baseline=True)

    class Stage:
        """Provide the batch lifecycle surface used by the stage gates."""

        name = "module_candidates"

        def title(self) -> str:
            """Return the deterministic stage title."""

            return self.name

    checker = RepoModuleChecker(phase="candidates", cfg=paths.cfg)
    checker.set_workspace(str(paths.workspace)).set_stage(Stage())
    checker.on_init()
    passed, result = checker.do_check()
    assert not passed
    assert "candidate-1" in str(result)
    candidate = paths.edit / "candidate"
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "carry_chain", "hypothesis": "Explore explicit carry logic",
                "changes": [{"path": "rtl/unit.v", "action": "replace"}]})
    atomic_text(candidate / "files/rtl/unit.v",
                "module Unit(input [7:0] a, output [7:0] y); "
                "wire [8:0] sum = {1'b0, a} + 9'd1; assign y = sum[7:0]; endmodule\n")
    # The gate itself must measure the changed candidate, not only trust new files.
    passed, result = checker.do_check()
    assert passed, result
    assert checker.batch.gen_task_list == ["candidate-1"]
    passed, result = checker.do_check(is_complete=True)
    assert passed, result
    delivery = RepoModuleChecker(phase="delivery", cfg=paths.cfg)
    delivery.set_workspace(str(paths.workspace)).set_stage(Stage())
    passed, result = delivery.do_check()
    assert passed, result
    assert result["verification_scope"] == "unit_only"
    summary = paths.edit / "delivery/summary.md"
    assert summary.is_file()
    from ucagent.util.markdown import markdown_heading_spacing_errors
    text = summary.read_text(encoding="utf-8")
    assert not markdown_heading_spacing_errors(text)
    assert "`baseline`" in text and "`carry_chain`" in text
    assert "ppa.area.total" in text and "unit_only" in text
    assert ("No primary metric improved" in text) == (not result["improvement_found"])
    passed, cached = delivery.do_check()
    assert passed and cached == {"delivery": "repo/delivery", "verification_scope": "unit_only"}


def test_cfg_ppa_analysis_depth_reaches_every_measurement(repo_case, monkeypatch):
    """Configured OpenSTA detail limits must reach each measured PPA analysis."""

    if any(not shutil.which(name) for name in ("yosys", "picker", "sta", "verilator")):
        pytest.skip("Real unit toolchain is unavailable")
    from design_with_ppa.repo import validation as validation_module

    recorded = {}
    analyze = validation_module.AnalyzePPA.analyze

    def spy(owner, arguments):
        """Record the exact analysis arguments before running the real flow."""

        recorded[vars(arguments)["report_path"]] = arguments
        return analyze(owner, arguments)

    monkeypatch.setattr(validation_module.AnalyzePPA, "analyze", spy)
    paths = repo_case
    paths.cfg.set_value("design_with_ppa.ppa.max_timing_paths", 3)
    paths.cfg.set_value("design_with_ppa.ppa.max_power_instances", 4)
    validate_unit(paths, baseline=True)
    assert recorded
    for arguments in recorded.values():
        assert arguments.max_timing_paths == 3
        assert arguments.max_power_instances == 4


def test_real_function_docs_coverage_and_annotated_test_cases(repo_case):
    """FG/FC/CK docs bind the contract, coverage statistics are real, TC gates pass."""

    if any(not shutil.which(name) for name in ("yosys", "picker", "sta", "verilator")):
        pytest.skip("Real unit toolchain is unavailable")
    paths = repo_case
    plugin_root = Path(__file__).resolve().parents[1]
    atomic_text(paths.edit / "functions_and_checks.md",
                "\n# 功能合同\n\n## 字节运算\n\n<FG-BYTE>\n\n### 自增\n\n<FC-INC>\n\n"
                "#### 结果\n\n<CK-RESULT>\n\n按公开引脚观测：result 为 (a + 1) mod 256，255 回绕到 0。\n")
    contract_path = paths.edit / "contract.yaml"
    contract = yaml.safe_load(contract_path.read_text())
    contract["requirements"] = {"FG-BYTE/FC-INC/CK-RESULT": "Increment modulo 256"}
    atomic_yaml(contract_path, contract)
    workload_path = paths.edit / "verification/workload.yaml"
    workload = yaml.safe_load(workload_path.read_text())
    workload["scenarios"][0]["covers"] = ["FG-BYTE/FC-INC/CK-RESULT"]
    atomic_yaml(workload_path, workload)
    checker = RepoModuleChecker(phase="contract", cfg=paths.cfg)
    passed, result = checker.set_workspace(str(paths.workspace)).do_check()
    assert passed and result["checkpoints"] == 1
    coverage = reference_check(paths)["coverage"]
    assert coverage["total"] == 1 and coverage["coverage"] == 1.0
    stored = json.loads((paths.edit / "coverage.json").read_text(encoding="utf-8"))
    assert stored["checkpoints"]["FG-BYTE/FC-INC/CK-RESULT"]["transactions"] == 4
    validate_unit(paths, baseline=True)
    tests = paths.edit / "tests"
    tests.mkdir()
    conftest = (plugin_root / "src/design_with_ppa/templates/repo_module/repo/tests/conftest.py").read_text(encoding="utf-8")
    atomic_text(tests / "conftest.py", conftest)
    atomic_text(tests / "test_increment.py",
                '"""Annotated public-pin test cases for the increment checkpoint."""\n\n'
                'COVERS = ["FG-BYTE/FC-INC/CK-RESULT"]\n\n\n'
                'def test_wrap(env, reference):\n    """Verify wrap behavior against the frozen reference."""\n\n'
                '    expected = reference([{"id": "t255", "inputs": {"a": 255}}])["t255"]["result"]\n'
                '    env.drive(a=255)\n    assert env.read("y") == expected\n    env.tick()\n')
    gate = RepoModuleChecker(phase="test_cases", cfg=paths.cfg)
    passed, result = gate.set_workspace(str(paths.workspace)).do_check()
    assert passed, result
    assert result["tc_coverage"] == "1/1" and result["test_cases"] == 1
    assert (paths.state / "test_gate.json").is_file()
    atomic_text(tests / "test_increment.py", (tests / "test_increment.py").read_text() + "\n# drift\n")
    frozen = RepoModuleChecker(phase="candidates", cfg=paths.cfg)
    passed, result = frozen.set_workspace(str(paths.workspace)).do_check()
    assert not passed and "Frozen test-stage artifacts changed" in str(result)
    atomic_text(tests / "test_increment.py", (tests / "test_increment.py").read_text().replace("\n# drift\n", ""))
    passed, result = gate.do_check()
    assert passed
    candidate = paths.edit / "candidate"
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "carry_chain", "hypothesis": "Explore explicit carry logic",
                "changes": [{"path": "rtl/unit.v", "action": "replace"}]})
    atomic_text(candidate / "files/rtl/unit.v",
                "module Unit(input [7:0] a, output [7:0] y); "
                "wire [8:0] sum = {1'b0, a} + 9'd1; assign y = sum[7:0]; endmodule\n")
    measured = RepoModuleChecker(phase="candidates", cfg=paths.cfg)
    passed, result = measured.set_workspace(str(paths.workspace)).do_check()
    assert passed, result
    broken = tests / "test_increment.py"
    atomic_text(broken, broken.read_text().replace('COVERS = ["FG-BYTE/FC-INC/CK-RESULT"]', "COVERS = []"))
    passed, result = gate.do_check()
    assert not passed and "back-annotation" in str(result)


def test_real_added_sequential_unit_with_generated_rtl(repo_case):
    """Add a handshake unit with native module generation and an existing RTL dependency."""

    if any(not shutil.which(name) for name in ("yosys", "picker", "sta", "verilator")):
        pytest.skip("Real unit toolchain is unavailable")
    paths = repo_case
    paths.cfg.set_value("design_with_ppa.repo.mode", "add")
    paths.cfg.set_value("design_with_ppa.ppa.sdc_file", "unit.sdc")
    atomic_text(paths.workspace / "unit.sdc", "create_clock -name clk -period 10 [get_ports clk]\n")
    paths = RepoPaths(paths.workspace, paths.cfg)
    atomic_text(paths.source / "deps headers/unit_flags.vh", "`define UNIT_READY 1'b1\n")
    git(paths.source, "add", ".")
    git(paths.source, "commit", "-qm", "Add unit include dependency")
    contract_path = paths.edit / "contract.yaml"
    contract = yaml.safe_load(contract_path.read_text())
    contract.update(target_paths=["rtl/wrapper.sv"], allowed_changes=["rtl/*.sv"], dependencies=["rtl/unit.v", "deps headers/unit_flags.vh"])
    atomic_yaml(contract_path, contract)
    candidate = paths.edit / "candidate"
    atomic_yaml(candidate / "candidate.yaml", {"variant_id": "first", "hypothesis": "Implement a registered handshake increment unit", "changes": [{"path": "rtl/wrapper.sv", "action": "add"}]})
    atomic_text(candidate / "files/rtl/wrapper.sv", '''// Registered byte increment using the source unit dependency.
`include "unit_flags.vh"
module Wrap(input clk, input rst, input valid, output ready,
            input [8:0] a, output reg [7:0] result, output reg done);
  wire [7:0] incremented;
  Unit increment(.a(a[7:0]), .y(incremented));
  assign ready = `UNIT_READY;
  always @(posedge clk) begin
    if (rst) begin result <= 0; done <= 0; end
    else begin done <= valid; if (valid) result <= incremented; end
  end
endmodule
''')
    pins = {name: {"direction": direction, "width": width, "purpose": name}
            for name, direction, width in [("clk", "input", 1), ("rst", "input", 1), ("valid", "input", 1),
                                          ("ready", "output", 1), ("a", "input", 9), ("result", "output", 8), ("done", "output", 1)]}
    atomic_yaml(candidate / "interface.yaml", {"version": "registered", "top": "Wrap", "pins": pins,
                "clock": "clk", "reset": "rst", "reset_active": 1, "reset_cycles": 2,
                "request_when": {"valid": 1, "ready": 1}, "response_when": {"done": 1},
                "protocol": "Accept valid requests each rising edge; registered response valid next cycle."})
    atomic_yaml(candidate / "recipe.yaml", {"scope": "unit", "systemverilog": True,
                "build": [{"argv": [sys.executable, "-c", "from pathlib import Path; Path('unit_export.sv').write_bytes(Path('rtl/wrapper.sv').read_bytes())"]}],
                "tool_versions": [{"argv": [sys.executable, "--version"]}],
                "rtl_files": ["rtl/unit.v", "unit_export.sv"], "include_dirs": ["deps headers"],
                "defines": {"UNIT_BUILD": "1"}, "timeout": 300})
    atomic_text(candidate / "adapter.py", '''"""Adapt byte transactions to a registered valid/ready interface."""


def run(env, transactions):
    """Measure the actual registered output after each accepted request."""
    for transaction in transactions:
        while env.cycle < transaction["release_cycle"]:
            env.tick()
        env.drive(a=transaction["inputs"]["a"], valid=1)
        env.accept(transaction["id"])
        env.tick()
        env.sample(transaction["id"], {"result": "result"})
        env.drive(valid=0)
        env.tick()
''')
    atomic_text(candidate / "protocol.py", '''"""Public reset and handshake unit checks."""


def test_reset(env):
    """No response is pending after reset; ready permits a new request."""
    assert env.read("done") == 0
    assert env.read("ready") == 1
    env.drive(valid=1, a=255)
    env.tick()
    assert env.read("done") == 1
    assert env.read("result") == 0
    env.drive(rst=1)
    env.tick()
    assert env.read("done") == 0
''')
    result = validate_unit(paths, baseline=True)
    assert result["accepted"] and result["verification_scope"] == "unit_only"
    assert result["build"]["pins"]["a"]["width"] == 9
    assert result["performance_metrics"]["unit.latency_cycles"]["value"] >= 1
    alignment = result["unit_results"]["scenarios"]["bytes"]["waveform_alignment"]
    # FST dumps are event-driven: the window is bounded by real public-pin
    # transitions, so only ordering and positivity are format-independent.
    assert alignment["native_start_tick"] > 0
    assert alignment["native_end_tick"] > alignment["native_start_tick"]
    assert 0.5 <= alignment["native_ticks_per_cycle"] <= 4.0
    assert alignment["activity_last_cycle"] > alignment["activity_first_cycle"]
    delivered = deliver(paths)
    assert delivered["patch_rebuild_pass"]
    assert not (paths.source / "rtl/wrapper.sv").exists()
    assert not (paths.source / "unit_export.sv").exists()


def test_unit_command_failure_and_timeout_are_actionable(tmp_path):
    """Module command failures identify the command; timeouts terminate the process group."""

    with pytest.raises(ValueError, match="Command failed"):
        run_command([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, 2)
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 1)


def test_native_commands_do_not_inherit_source_routing(tmp_path, monkeypatch):
    """Independent module commands cannot inherit SOURCE_PATH or Git worktree routing."""

    monkeypatch.setenv("SOURCE_PATH", "/original/repository")
    monkeypatch.setenv("GIT_WORK_TREE", "/original/repository")
    result = run_command([sys.executable, "-c", "import os; print('SOURCE_PATH' in os.environ or 'GIT_WORK_TREE' in os.environ)"], tmp_path, 5)
    assert result["stdout"].strip() == "False"


def test_native_wrapper_failure_preserves_compiler_diagnostic(tmp_path):
    """A Python build wrapper must not obscure the native compiler's actual error."""

    with pytest.raises(ValueError, match="Unit.scala:4: error: unresolved import") as error:
        run_command([sys.executable, "-c", "import sys; print('Unit.scala:4: error: unresolved import', file=sys.stderr); raise RuntimeError('export failed')"], tmp_path, 5)
    assert "RuntimeError: export failed" in str(error.value)
    assert "Traceback (most recent call last):" not in str(error.value)


def test_source_receipt_forgery_is_rejected(repo_case):
    """An edited snapshot manifest cannot authorize a different imported source."""

    snapshot_repository(repo_case)
    artifact = repo_case.state / "source.json"
    record = json.loads(artifact.read_text())
    record["payload"]["commit"] = "forged"
    atomic_json(artifact, record)
    with pytest.raises(ValueError, match="Evidence changed"):
        snapshot_repository(repo_case)


@pytest.mark.parametrize("skills_enabled", [False, True])
def test_repo_workflow_configuration_and_stage_lifecycle(repo_case, monkeypatch, skills_enabled):
    """Resolve new YAML, instantiate every stage gate, and require no optional skill files."""

    from ucagent.stage.vstage import VerifyStage
    from ucagent.util.config import build_runtime_config
    from design_with_ppa.checkers import (DesignFunctionalContractChecker,
                                          DesignLabelStructureChecker,
                                          DesignMarkdownFileFormatChecker)

    workflow = next(w for w in get_plugin().workflows if w.name == "repo-module-tdd")
    monkeypatch.setenv("SOURCE_PATH", str(repo_case.source))
    cfg = get_config(None, [{"skill.use_skill": skills_enabled}], str(repo_case.workspace), workflow_config_file=str(workflow.config_file))
    cfg.un_freeze()
    cfg._temp_cfg = {"OUT": "design", "DUT": "task"}
    cfg.update_template({"OUT": "design", "DUT": "task", "WORKSPACE": str(repo_case.workspace)})
    cfg.freeze()
    assert cfg.skill.use_skill is skills_enabled
    exported = build_runtime_config(cfg, runtime_config_keys=list(workflow.runtime_config_keys))
    assert exported["plugin_options"]["design_with_ppa.repo.source_path"] == str(repo_case.source)
    raw = load_yaml_with_env_vars(workflow.config_file)
    assert len(raw["stage"]) == 8
    assert "scope: unit" in (workflow.template_dir / "repo/candidate/recipe.yaml").read_text()
    assert not (repo_case.workspace / ".ucagent/skills").exists()
    for item in raw["stage"]:
        checker_config = copy.deepcopy(item["checker"])
        for gate in checker_config:
            gate["extra_args"] = {}
        stage = VerifyStage(cfg=cfg, workspace=str(repo_case.workspace), name=item["name"],
                            description=item["desc"], task=item["task"], checker=[Config(gate) for gate in checker_config],
                            reference_files=[], skill_list=[], output_files=item["output_files"],
                            checker_registry={"RepoModuleChecker": RepoModuleChecker,
                                              "DesignFunctionalContractChecker": DesignFunctionalContractChecker,
                                              "DesignLabelStructureChecker": DesignLabelStructureChecker,
                                              "DesignMarkdownFileFormatChecker": DesignMarkdownFileFormatChecker})
        checker = stage.checker[0]
        if isinstance(checker, RepoModuleChecker):
            assert checker.cfg is cfg
            assert not stage.skill_list
            checker.on_init()
            assert checker.get_template_data() is None
        assert str(checker)
    check = RepoModuleChecker(phase="reference")
    check.cfg = cfg
    assert check.set_workspace(str(repo_case.workspace)).do_check()[0]


def test_repo_tool_mcp_and_local_failures(repo_case):
    """The workflow-local tool converts to MCP and diagnoses real local invocation failures."""

    from ucagent.tools.uctool import to_fastmcp

    tool = RunRepoValidation(workspace=str(repo_case.workspace), cfg=repo_case.cfg)
    schema = to_fastmcp(tool).parameters
    assert schema["properties"]["action"]["default"] == "validate"
    result = tool._run()
    assert result["error_code"] == "repo_validation_failed"
    assert "baseline=true" in result["error"]


def test_missing_rtl_output_and_pin_mismatch(repo_case):
    """Unit export cannot pass with missing generated output or undeclared public pins."""

    from design_with_ppa.repo.build import prepare_unit
    from design_with_ppa.repo.models import read_model
    from design_with_ppa.repo.snapshot import materialize

    paths = repo_case
    snapshot_repository(paths)
    repository = paths.workspace / "isolated"
    materialize(paths.snapshot, paths.edit / "candidate", [], repository)
    interface = read_model(paths.edit / "candidate", "interface.yaml", Interface)
    missing = Recipe.model_validate({"scope": "unit", "rtl_files": ["absent.v"]})
    with pytest.raises(ValueError, match="Required artifact is missing"):
        prepare_unit(repository, paths.edit / "candidate", paths.workspace / "missing-build", missing, interface)
    if not shutil.which("yosys"):
        pytest.skip("Yosys is unavailable")
    interface.pins["a"].width = 7
    recipe = read_model(paths.edit / "candidate", "recipe.yaml", Recipe)
    with pytest.raises(ValueError, match="pins differ"):
        prepare_unit(repository, paths.edit / "candidate", paths.workspace / "mismatch-build", recipe, interface)



def test_prepare_unit_honors_workflow_python_dut_options(repo_case, monkeypatch):
    """The resolved workflow's conversion options reach the managed unit builder."""

    from design_with_ppa.repo import build as repo_build
    from design_with_ppa.repo.models import read_model
    from design_with_ppa.repo.snapshot import materialize
    from design_with_ppa.rtl import resolve_rtl_config

    paths = repo_case
    if not shutil.which("yosys"):
        pytest.skip("Yosys is unavailable")
    snapshot_repository(paths)
    repository = paths.workspace / "isolated"
    materialize(paths.snapshot, paths.edit / "candidate", [], repository)
    interface = read_model(paths.edit / "candidate", "interface.yaml", Interface)
    recipe = read_model(paths.edit / "candidate", "recipe.yaml", Recipe)
    paths.cfg.un_freeze()
    paths.cfg.set_value(
        "design_with_ppa.rtl",
        {"python_dut": {"interface": "automatic",
                        "options": {"verilator_args": ["-O3", "--output-split", "3000"],
                                    "ccache_enabled": False}}},
    )
    captured: dict = {}

    class StubChecker:
        """Record the resolved conversion options and stand in for the build."""

        def __init__(self, *, cfg, **kwargs):
            del kwargs
            captured["options"] = resolve_rtl_config(cfg)[0].python_dut_options

        def set_workspace(self, workspace):
            self.workspace = workspace
            return self

        def do_check(self, **kwargs):
            del kwargs
            atomic_json(
                Path(self.workspace) / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json",
                {"stub": True},
            )
            return True, {"stubbed": True}

    monkeypatch.setattr(repo_build, "RTLBackendBuildChecker", StubChecker)
    evidence = repo_build.prepare_unit(
        repository, paths.edit / "candidate", paths.workspace / "options-build",
        recipe, interface, cfg=paths.cfg,
    )

    assert captured["options"] == {
        "verilator_args": ["-O3", "--output-split", "3000"],
        "ccache_enabled": False,
    }
    assert evidence["builder"] == {"stub": True}
    assert (paths.workspace / "options-build" / "design/rtl/unit.v").is_file()


def test_delete_binary_and_mode_delivery_preflight(tmp_path):
    """Standalone delivery supports add/delete/replace and refuses conflicts before any write."""

    from design_with_ppa.repo.apply_bundle import file_state

    target, bundle = tmp_path / "target", tmp_path / "bundle"
    target.mkdir()
    atomic_text(target / "remove.txt", "old\n")
    atomic_text(target / "replace.txt", "before\n")
    atomic_text(bundle / "files/replace.txt", "after\n")
    (bundle / "files/replace.txt").chmod(0o755)
    (bundle / "files/add.bin").write_bytes(bytes(range(256)))
    changes = [{"path": "remove.txt", "action": "delete", "before": file_state(target / "remove.txt"), "after": None},
               {"path": "replace.txt", "action": "replace", "before": file_state(target / "replace.txt"), "after": file_state(bundle / "files/replace.txt")},
               {"path": "add.bin", "action": "add", "before": None, "after": file_state(bundle / "files/add.bin")}]
    atomic_json(bundle / "manifest.json", {"base_commit": "unused", "changes": changes})
    atomic_text(target / "replace.txt", "conflicting\n")
    with pytest.raises(ValueError, match="conflicts"):
        apply_bundle(bundle, target, apply=True)
    assert (target / "remove.txt").exists()
    assert not (target / "add.bin").exists()
    atomic_text(target / "replace.txt", "before\n")
    apply_bundle(bundle, target, apply=True)
    assert not (target / "remove.txt").exists()
    assert (target / "replace.txt").stat().st_mode & 0o111
    assert (target / "add.bin").read_bytes() == bytes(range(256))


def test_guide_examples_and_packaged_templates_are_canonical():
    """The skill-free runtime guide exposes valid complete examples for each task artifact."""

    import ast
    import re
    from ucagent.util.markdown import markdown_heading_spacing_errors
    from design_with_ppa.repo.models import Candidate, TaskContract, Workload

    root = Path(__file__).resolve().parents[1]
    guide = root / "src/design_with_ppa/Guide_Doc/repo_module.md"
    content = guide.read_text()
    assert not markdown_heading_spacing_errors(content)
    mappings = [yaml.safe_load(body) for body in re.findall(r"```yaml\n(.*?)\n```", content, re.S)]
    for model, value in zip((TaskContract, Workload, Candidate, Interface, Recipe, Candidate), mappings):
        model.model_validate(value)
    for code in re.findall(r"```python\n(.*?)\n```", content, re.S):
        ast.parse(code)


def test_byte_increment_case_bootstraps_a_real_source_repository(tmp_path):
    """The maintained case and its Makefile demo source satisfy the import contract."""

    if shutil.which("make") is None:
        pytest.skip("make is unavailable")
    plugin_root = Path(__file__).resolve().parents[1]
    readme = (plugin_root / "cases/repo_byte_increment/README.md").read_text(encoding="utf-8")
    from ucagent.util.markdown import markdown_heading_spacing_errors

    assert not markdown_heading_spacing_errors(readme)
    assert "`rtl/unit.v`" in readme and "(a + 1) mod 256" in readme
    demo = tmp_path / "demo-source"
    created = subprocess.run(
        ["make", "prepare-repo-demo-source",
         f"WORKSPACE_ROOT={tmp_path}", f"DEMO_REPO_SOURCE={demo}"],
        cwd=plugin_root, check=True, capture_output=True, text=True)
    assert "Created demo source repository" in created.stdout
    reused = subprocess.run(
        ["make", "prepare-repo-demo-source",
         f"WORKSPACE_ROOT={tmp_path}", f"DEMO_REPO_SOURCE={demo}"],
        cwd=plugin_root, check=True, capture_output=True, text=True)
    assert "Reusing demo source repository" in reused.stdout
    unit = (demo / "rtl/unit.v").read_text(encoding="utf-8")
    assert "module Unit(input [7:0] a, output [7:0] y)" in unit and "8'd1" in unit
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    atomic_text(workspace / "task/README.md", readme)
    cfg = Config({"design_with_ppa": {"repo": {"enabled": True, "source_path": str(demo)}}})
    cfg._temp_cfg = {"OUT": "design", "DUT": "task"}
    manifest = snapshot_repository(RepoPaths(workspace, cfg))
    assert set(manifest["files"]) == {"rtl/unit.v", "README.md"}
    assert (RepoPaths(workspace, cfg).snapshot / "rtl/unit.v").read_text(encoding="utf-8") == unit
