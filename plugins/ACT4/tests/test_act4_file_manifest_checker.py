import hashlib
import stat
from pathlib import Path

import pytest
import yaml

from act4_privileged_suite.checkers.act4_file_manifest_checker import ACT4FileManifestChecker


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory_entry(path: Path, workspace: Path) -> dict:
    return {
        "path": path.relative_to(workspace).as_posix(),
        "type": "symlink" if path.is_symlink() else "file",
        "mode": format(stat.S_IMODE(path.lstat().st_mode), "o"),
        "sha256": ACT4FileManifestChecker._sha256(path),
    }


def _manifest(tmp_path: Path, baseline_entries: list[dict] | None = None) -> dict:
    (tmp_path / "riscv-arch-test").mkdir(exist_ok=True)
    artifact = tmp_path / "out" / "artifact.txt"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text("asset\n", encoding="utf-8")
    baseline_inventory = tmp_path / "out" / "baseline.yaml"
    baseline_inventory.write_text(
        yaml.safe_dump({"files": baseline_entries or []}), encoding="utf-8"
    )
    manifest_path = tmp_path / "out" / "manifest.yaml"
    base = {
        "schema_version": 2,
        "suite": "H",
        "workspace_root": str(tmp_path),
        "baseline": {
            "method": "sha256_snapshot",
            "git_head": None,
            "preexisting_changes": [],
            "status_command": "snapshot",
            "status_recorded": True,
            "baseline_inventory": "out/baseline.yaml",
        },
        "files": [
            {
                "path": "out/artifact.txt",
                "action": "created",
                "category": "internal_asset",
                "stage": "01_coverpoints",
                "content_summary": "test asset",
                "origin": "test",
                "reason": "exercise checker",
                "diff_summary": None,
                "diff_evidence": None,
                "existed_before": False,
                "sha256_before": None,
                "sha256_after": _sha(artifact),
                "hash_note": None,
            },
            {
                "path": "out/manifest.yaml",
                "action": "created",
                "category": "report",
                "stage": "01_coverpoints",
                "content_summary": "run inventory",
                "origin": "workflow",
                "reason": "audit outputs",
                "diff_summary": None,
                "diff_evidence": None,
                "existed_before": False,
                "sha256_before": None,
                "sha256_after": None,
                "hash_note": "self-referential manifest",
            },
            {
                "path": "out/baseline.yaml",
                "action": "created",
                "category": "report",
                "stage": "01_coverpoints",
                "content_summary": "frozen baseline inventory",
                "origin": "workflow",
                "reason": "verify protected framework integrity",
                "diff_summary": None,
                "diff_evidence": None,
                "existed_before": False,
                "sha256_before": None,
                "sha256_after": _sha(baseline_inventory),
                "hash_note": None,
            },
        ],
        "change_events": [],
        "framework_integrity": {
            "protected_files_modified": [],
            "protected_files_deleted": [],
            "protected_type_or_mode_changed": [],
            "policy_violations": [],
            "verification_command": "protected snapshot compare",
            "passed": True,
        },
    }
    manifest_path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return base


def _write_manifest(tmp_path: Path, manifest: dict) -> None:
    (tmp_path / "out" / "manifest.yaml").write_text(
        yaml.safe_dump(manifest), encoding="utf-8"
    )


def _checker(tmp_path: Path, **kwargs) -> ACT4FileManifestChecker:
    return ACT4FileManifestChecker(
        "out/manifest.yaml", expected_suite="H", **kwargs
    ).set_workspace(str(tmp_path))


def test_checker_provides_ucagent_description() -> None:
    assert ACT4FileManifestChecker.do_check.__doc__


def test_valid_v2_manifest_and_inventory_pass(tmp_path: Path) -> None:
    _manifest(tmp_path)

    passed, report = _checker(tmp_path, inventory_patterns=["out/**/*"]).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}
    assert report["checks"]["manifested_files"] == 3
    assert report["checks"]["inventory_files"] == 3
    assert report["checks"]["protected_changes"] == 0


def test_contribution_set_matches_source_category(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H_coverage.svh", "covergroup H_cg; endgroup")
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(
        tmp_path, require_contribution_set=True
    ).do_check()

    assert passed
    assert report["checks"]["contribution_sources"] == 1


def _add_contribution(tmp_path: Path, manifest: dict, path: str, content: str) -> Path:
    source = tmp_path / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(content)
    manifest["files"].append({
        **manifest["files"][0], "path": path, "category": "contribution_source",
        "sha256_after": _sha(source),
    })
    manifest.setdefault("contribution_set", []).append(path)
    return source


@pytest.mark.parametrize("root", ["riscv-arch-test", "upstream"])
@pytest.mark.parametrize("path", ["tests/H.S", "work_run/a.txt", "logs/H.sig.log", ".venv/local.py"])
def test_generated_contributions_respect_configured_act4_root(tmp_path, root, path):
    manifest = _manifest(tmp_path)
    _add_contribution(tmp_path, manifest, f"{root}/{path}", "# generated")
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, act4_root=root, require_contribution_set=True).do_check()
    assert not passed
    assert any(f["check"] == "manifest_generated_contribution" for f in report["findings"])


def test_local_asset_cannot_be_relabelled_as_act4_contribution(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["files"][0]["category"] = "contribution_source"
    manifest["contribution_set"] = ["out/artifact.txt"]
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert not passed
    assert any(f["check"] == "manifest_contribution_path" for f in report["findings"])


@pytest.mark.parametrize(("suffix", "content"), [
    (".py", "from act4_privileged_suite.checkers import load_contract"),
    (".py", 'from pathlib import Path\np = Path("out/artifact.txt")\np.read_text()'),
    (".py", 'import os\nos.getenv("ITGEN_WORKSPACE")'),
    (".svh", '`include "../../../unity_test/H/local.svh"'),
    (".svh", '`include "out/artifact.txt"'),
    (".svh", 'initial $readmemh("out/artifact.txt", data);'),
    (".adoc", 'include::out/artifact.txt[]'),
    (".adoc", 'image::unity_test/H/chart.png[]'),
])
def test_final_gate_rejects_explicit_local_dependencies(tmp_path, suffix, content):
    manifest = _manifest(tmp_path)
    _add_contribution(tmp_path, manifest, f"riscv-arch-test/coverpoints/priv/H{suffix}", content)
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert not passed
    errors = [f for f in report["findings"] if f["check"] == "manifest_contribution_dependency"]
    assert len(errors) == 1


@pytest.mark.parametrize("import_statement", ["import helper", "from . import helper", "from .helper import data"])
@pytest.mark.parametrize("contributed_helper", [False, True])
def test_final_gate_distinguishes_local_and_contributed_helper(tmp_path, import_statement, contributed_helper):
    manifest = _manifest(tmp_path)
    helper = tmp_path / "riscv-arch-test/coverpoints/priv/helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text('data = "local"')
    manifest["files"].append({**manifest["files"][0], "path": str(helper.relative_to(tmp_path)), "sha256_after": _sha(helper)})
    if contributed_helper:
        manifest["files"][-1]["category"] = "contribution_source"
        manifest["contribution_set"] = [str(helper.relative_to(tmp_path))]
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H.py", import_statement)
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert passed == contributed_helper, report
    assert any(f["check"] == "manifest_contribution_dependency" for f in report["findings"]) != contributed_helper


def test_local_helpers_comments_native_inputs_and_source_dependencies_are_allowed(tmp_path):
    manifest = _manifest(tmp_path)
    # Internal scripts may read contracts. Only the declared PR set is checked.
    helper = tmp_path / "out/artifact.txt"
    helper.write_text('import itgen\nopen("unity_test/H/H_vm_resource_contract.yaml")')
    manifest["files"][0]["sha256_after"] = _sha(helper)
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/data.svh", "// native source")
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H.svh", '''
// `include "out/artifact.txt"
/* `include "unity_test/H/local.svh" */
`include "data.svh"
`include "coverage/RISCV_coverage.svh"
''')
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H.py", '''
"""See unity_test/H/H_vm_resource_contract.yaml for local review history."""
from pathlib import Path
from testgen.priv.registry import add_priv_test_generator
Path("testplans/H.csv").read_text()
''')
    _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/norm/H.yaml", 'normative_rule_definitions:\n- name: contract\n  coverpoint: [H_cg/cp_contract]\n')
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert passed, report


@pytest.mark.parametrize("missing_target", [False, True])
def test_symlink_cannot_hide_local_contribution_dependency(tmp_path, missing_target):
    manifest = _manifest(tmp_path)
    source = _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H.svh", "// temporary")
    source.unlink()
    source.symlink_to(tmp_path / ("out/absent.txt" if missing_target else "out/artifact.txt"))
    manifest["files"][-1]["sha256_after"] = ACT4FileManifestChecker._sha256(source)
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert not passed
    assert any(f["check"] == "manifest_contribution_dependency" for f in report["findings"])


def test_native_source_symlink_and_binary_ctp_asset_are_allowed(tmp_path):
    manifest = _manifest(tmp_path)
    target = _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/data.svh", "// shared suite source")
    link = _add_contribution(tmp_path, manifest, "riscv-arch-test/coverpoints/priv/H.svh", "// replaced by link")
    link.unlink()
    link.symlink_to(target.name)
    manifest["files"][-1]["sha256_after"] = ACT4FileManifestChecker._sha256(link)
    picture = _add_contribution(tmp_path, manifest, "riscv-arch-test/ctp/figure.png", "")
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest["files"][-1]["sha256_after"] = _sha(picture)
    _write_manifest(tmp_path, manifest)
    passed, report = _checker(tmp_path, require_contribution_set=True).do_check()
    assert passed, report


def test_generated_assembly_cannot_be_a_contribution_source(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    source = tmp_path / "riscv-arch-test" / "tests" / "priv" / "H" / "H-00.S"
    source.parent.mkdir(parents=True)
    source.write_text("generated\n", encoding="utf-8")
    manifest["files"].append(
        {
            "path": "riscv-arch-test/tests/priv/H/H-00.S",
            "action": "generated",
            "category": "contribution_source",
            "stage": "05_build",
            "content_summary": "generated validation source",
            "origin": "testgen",
            "reason": "validate generator",
            "diff_summary": None,
            "diff_evidence": None,
            "existed_before": False,
            "sha256_before": None,
            "sha256_after": _sha(source),
            "hash_note": None,
        }
    )
    manifest["contribution_set"] = [
        "riscv-arch-test/tests/priv/H/H-00.S"
    ]
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(
        tmp_path, require_contribution_set=True
    ).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_generated_contribution"
        for item in report["findings"]
    )


def test_v1_manifest_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["schema_version"] = 1
    manifest["baseline"]["clean_status_command"] = manifest["baseline"].pop(
        "status_command"
    )
    manifest["baseline"]["clean_status_verified"] = manifest["baseline"].pop(
        "status_recorded"
    )
    manifest["framework_integrity"] = {
        "preexisting_files_modified": [],
        "preexisting_files_deleted": [],
        "policy_violations": [],
        "verification_command": "snapshot compare",
        "passed": True,
    }
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_version" for item in report["findings"]
    )


def test_unlisted_delivery_file_still_fails(tmp_path: Path) -> None:
    _manifest(tmp_path)
    (tmp_path / "out" / "forgotten.log").write_text("forgotten\n", encoding="utf-8")

    passed, report = _checker(
        tmp_path, inventory_patterns=["out/**/*"]
    ).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_inventory_missing"
        for item in report["findings"]
    )


@pytest.mark.parametrize(("filename", "is_evidence"), [
    ("H.sig.elf", False), ("rvtest_config.h", False), ("build.stamp", False),
    ("H.elf", True), ("H.sig", True), ("H.results", True),
    ("H.sig.log", True), ("H.S", True),
])
def test_nested_local_work_inventory_keeps_final_evidence(tmp_path, filename, is_evidence):
    _manifest(tmp_path)
    path = tmp_path / "out/reports/reassessment/work/target/build" / filename
    path.parent.mkdir(parents=True)
    path.write_text("native build output")
    passed, report = _checker(tmp_path, inventory_patterns=["out/**/*"]).do_check()
    assert passed != is_evidence, report
    assert any(f["check"] == "manifest_inventory_missing" for f in report["findings"]) == is_evidence


def test_hash_mismatch_and_declared_policy_violation_fail(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["files"][0]["sha256_after"] = "0" * 64
    manifest["framework_integrity"]["policy_violations"] = ["tests/env/base.h"]
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    checks = {item["check"] for item in report["findings"]}
    assert "manifest_hash_mismatch" in checks
    assert "manifest_framework_integrity" in checks


def test_policy_violation_event_fails_even_if_file_was_restored(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["change_events"] = [
        {
            "path": "riscv-arch-test/tests/env/base.h",
            "event": "policy_violation",
            "stage": "05_build",
            "timestamp": None,
            "sha256_before": "a",
            "sha256_after": "a",
            "content_summary": "protected file was written and restored",
            "reason": "debug attempt",
            "evidence": "recorded command",
        }
    ]
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_policy_violation"
        for item in report["findings"]
    )


def test_project_local_venv_is_allowed_without_per_file_manifest(tmp_path: Path) -> None:
    _manifest(tmp_path)
    package = tmp_path / "riscv-arch-test" / ".venv" / "lib" / "package.py"
    package.parent.mkdir(parents=True)
    package.write_text("value = 1\n", encoding="utf-8")

    checker = _checker(tmp_path)
    assert ".venv/lib/package.py" not in checker._scan_act4_objects()
    passed, report = checker.do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_cache_inside_protected_source_tree_is_a_tool_artifact(tmp_path: Path) -> None:
    _manifest(tmp_path)
    cached = (
        tmp_path
        / "riscv-arch-test"
        / "generators/testgen/src/testgen/__pycache__/module.pyc"
    )
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cache")

    checker = _checker(tmp_path)
    assert (
        "generators/testgen/src/testgen/__pycache__/module.pyc"
        not in checker._scan_act4_objects()
    )
    passed, report = checker.do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_inventory_ignores_python_cache_files(tmp_path: Path) -> None:
    _manifest(tmp_path)
    cached = tmp_path / "out/reports/__pycache__/helper.cpython-313.pyc"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cache")

    passed, report = _checker(
        tmp_path, inventory_patterns=["out/reports/**/*"]
    ).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_unknown_new_act4_file_is_ignored(tmp_path: Path) -> None:
    _manifest(tmp_path)
    (tmp_path / "riscv-arch-test" / "scratch.tmp").write_text(
        "temporary\n", encoding="utf-8"
    )

    passed, report = _checker(tmp_path).do_check()

    assert passed
    assert report["status"] == "complete"
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_new_object_under_protected_path_blocks(tmp_path: Path) -> None:
    _manifest(tmp_path)
    injected = tmp_path / "riscv-arch-test" / "framework" / "injected.py"
    injected.parent.mkdir()
    injected.write_text("pass\n", encoding="utf-8")

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_protected_framework_addition"
        for item in report["findings"]
    )


def test_modifying_protected_baseline_object_blocks(tmp_path: Path) -> None:
    core = tmp_path / "riscv-arch-test" / "framework" / "core.py"
    core.parent.mkdir(parents=True)
    core.write_text("original\n", encoding="utf-8")
    manifest = _manifest(tmp_path, [_inventory_entry(core, tmp_path)])
    core.write_text("changed\n", encoding="utf-8")
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    assert report["checks"]["protected_changes"] == 1
    assert any(
        item["check"] == "manifest_protected_framework_change"
        for item in report["findings"]
    )


def test_replacing_protected_symlink_with_file_blocks(tmp_path: Path) -> None:
    framework = tmp_path / "riscv-arch-test" / "framework"
    framework.mkdir(parents=True)
    target = framework / "target.py"
    target.write_text("target\n", encoding="utf-8")
    link = framework / "current.py"
    link.symlink_to("target.py")
    manifest = _manifest(
        tmp_path,
        [_inventory_entry(target, tmp_path), _inventory_entry(link, tmp_path)],
    )
    link.unlink()
    link.write_text("replacement\n", encoding="utf-8")
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    finding = next(
        item
        for item in report["findings"]
        if item["check"] == "manifest_protected_framework_change"
        and item["message"].endswith("framework/current.py")
    )
    assert "type" in finding["changed_fields"]


def test_modifying_noncritical_baseline_object_is_ignored(tmp_path: Path) -> None:
    note = tmp_path / "riscv-arch-test" / "docs" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("original\n", encoding="utf-8")
    manifest = _manifest(tmp_path, [_inventory_entry(note, tmp_path)])
    note.write_text("changed\n", encoding="utf-8")
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_current_suite_generator_is_excluded_from_protected_tree(tmp_path: Path) -> None:
    _manifest(tmp_path)
    generator = (
        tmp_path
        / "riscv-arch-test"
        / "generators/testgen/src/testgen/priv/extensions/H.py"
    )
    generator.parent.mkdir(parents=True)
    generator.write_text("def generate():\n    return []\n", encoding="utf-8")

    passed, report = _checker(tmp_path).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_obsolete_ephemeral_event_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["change_events"] = [
        {
            "path": "riscv-arch-test/.venv/pyvenv.cfg",
            "event": "ephemeral_created",
            "stage": "04_generator",
            "timestamp": None,
            "sha256_before": None,
            "sha256_after": "a" * 64,
            "content_summary": "tool created a local environment file",
            "reason": "test generation dependency resolution",
            "evidence": "tool output",
        }
    ]
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert not passed
    assert any(
        item["check"] == "manifest_event_type" for item in report["findings"]
    )


def test_recorded_dirty_start_is_allowed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["baseline"]["preexisting_changes"] = ["docs/local-note.md"]
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}


def test_integrity_only_skips_output_manifest_validation(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.pop("files")
    manifest.pop("change_events")
    _write_manifest(tmp_path, manifest)

    passed, report = _checker(tmp_path, integrity_only=True).do_check()

    assert passed
    assert report["checks"]["manifested_files"] == 0
