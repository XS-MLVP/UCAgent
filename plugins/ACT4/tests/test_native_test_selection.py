"""Exercise isolated checker changes with native ACT selection and bounded fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from ucagent_act4.checkers.act4_test_asset_checker import ACT4TestAssetChecker


@pytest.fixture
def native_workspace(tmp_path: Path) -> Path:
    """Use real frozen native Python/APIs and a minimal pair of target configurations."""
    configured = os.environ.get("ACT4_NATIVE_TEST_ROOT")
    if not configured:
        pytest.skip("set ACT4_NATIVE_TEST_ROOT to a prepared frozen ACT checkout")
    native = Path(configured).resolve()
    assert (native / ".venv/bin/python").is_file(), native
    (tmp_path / ".venv").symlink_to(native / ".venv", target_is_directory=True)
    (tmp_path / "framework").symlink_to(native / "framework", target_is_directory=True)
    for name, params, extensions in (
        ("shared", {}, ["I"]), ("rv32", {"MXLEN": 32}, ["I"]),
        ("rv64", {"MXLEN": 64}, ["I"]), ("optional", {}, ["I", "Zextra"]),
    ):
        source = tmp_path / f"tests/priv/Example/{name}.S"
        source.parent.mkdir(parents=True, exist_ok=True)
        header = yaml.safe_dump({"MARCH": "rv${XLEN}i", "REQUIRED_EXTENSIONS": extensions, "params": params})
        source.write_text(
            "##### START_TEST_CONFIG #####\n" + "".join(f"# {line}\n" for line in header.splitlines())
            + "##### END_TEST_CONFIG #####\nRVTEST_CODE_BEGIN\nRVTEST_CODE_END\n"
        )
    for xlen in (32, 64):
        folder = tmp_path / f"config/rv{xlen}"
        folder.mkdir(parents=True)
        (folder / "link.ld").write_text("SECTIONS {}\n")
        (folder / "udb.yaml").write_text(yaml.safe_dump({"params": {"MXLEN": xlen}}))
        (folder / "test_config.yaml").write_text(yaml.safe_dump({
            "name": f"rv{xlen}", "udb_config": "udb.yaml", "linker_script": "link.ld",
            "dut_include_dir": ".", "compiler_exe": "riscv64-unknown-elf-gcc",
            "ref_model_exe": "sail_riscv_sim",
        }))
        build = tmp_path / f"work_itgen_Example/rv{xlen}"
        (build / "env").mkdir(parents=True)
        (build / "env/extensions.txt").write_text("I\n")
        (build / "elfs").mkdir()
        (build / "build").mkdir()
        for name in ("shared", f"rv{xlen}"):
            (build / f"elfs/{name}.elf").write_bytes(b"\x7fELF" + bytes([xlen // 32]) + bytes(59))
            (build / f"build/{name}.sig").write_text("0001\n")
            (build / f"build/{name}.results").write_text(".word 1\n")
            (build / f"build/{name}.sig.log").write_text(
                f'RVCP-SUMMARY: TEST SIGRUN - Test File "{name}.S"\n'
                f"setting signature-granularity to {xlen // 8} bytes\n"
                f"begin_signature: 0x1000\nend_signature: {hex(0x1000 + xlen // 8)}\nSUCCESS\n"
            )
    (tmp_path / "contract.yaml").write_text(yaml.safe_dump({
        "decision": "no_vm", "selected_target": {"XLEN": 64}, "supported_xlens": [32, 64],
    }))
    return tmp_path


def check(root: Path, xlen: int) -> tuple[bool, dict]:
    """Check one explicitly selected build without borrowing other configurations."""
    config = f"config/rv{xlen}/test_config.yaml"
    state = {
        "source_generated": True, "supported_xlens": [32, 64], "contribution_ready": False,
        "generation_scope": {"status": "complete", "generated_targets": [],
                             "partial_targets": [], "blocked_targets": []},
        "self_checking": {"model": "sail", "passed": True, "executable": "sail_riscv_sim",
                          "config_file": config,
                          "command": f"WORKDIR=work_itgen_Example CONFIG_FILES={config} EXTENSIONS=Example make"},
        "sail_coverage": {"passed": False, "command": "", "blocked_reason": "not requested"},
    }
    (root / "state.yaml").write_text(yaml.safe_dump(state))
    checker = ACT4TestAssetChecker(
        act4_root=str(root), source_patterns=["tests/priv/Example/*.S"],
        elf_patterns=["work_itgen_Example/**/elfs/*.elf"],
        signature_patterns=["work_itgen_Example/**/build/*.sig"],
        result_patterns=["work_itgen_Example/**/build/*.results"],
        reference_model_log_patterns=["work_itgen_Example/**/build/*.sig.log"],
        validation_state="state.yaml", vm_resource_contract="contract.yaml", validate_vm_contract=True,
        require_matching_xlen=True, require_signature=True, require_results=True,
        require_reference_model_logs=True, require_signature_completeness=True,
        allow_sail_coverage_blocked=True, source_markers=["RVTEST_CODE_END"],
    ).set_workspace(str(root))
    return checker.do_check()


@pytest.mark.parametrize("xlen", [32, 64])
def test_native_applicability_preserves_full_source_scope(native_workspace: Path, xlen: int) -> None:
    """Keep shared, opposite-XLEN and optional sources visible in each config review."""
    passed, result = check(native_workspace, xlen)
    assert passed, result
    checks = result["report"]["checks"]
    assert checks["source_files"] == 4
    assert checks["applicable_source_files"] == 2
    assert checks["complete_reference_runs"] == 2
    selection = checks["source_selection"]
    assert selection["xlen"] == xlen
    assert {Path(item["source"]).stem for item in selection["excluded_sources"]} == {
        "optional", f"rv{96 - xlen}",
    }


@pytest.mark.parametrize("suffix", ["sig", "results", "sig.log", "elf"])
def test_missing_evidence_cannot_use_other_config(native_workspace: Path, suffix: str) -> None:
    """A genuine same-stem artifact under RV32 cannot repair an absent RV64 artifact."""
    folder = "elfs" if suffix == "elf" else "build"
    (native_workspace / f"work_itgen_Example/rv64/{folder}/shared.{suffix}").unlink()
    passed, result = check(native_workspace, 64)
    assert not passed
    assert any(item["severity"] == "error" for item in result["report"]["findings"])


@pytest.mark.parametrize("suffix", ["sig", "results", "sig.log"])
def test_truncated_evidence_is_still_rejected(native_workspace: Path, suffix: str) -> None:
    """Selection must not weaken signature interval or terminal-log checks."""
    (native_workspace / f"work_itgen_Example/rv64/build/shared.{suffix}").write_text("")
    passed, _ = check(native_workspace, 64)
    assert not passed


def test_wrong_elf_class_conflicts_with_native_config(native_workspace: Path) -> None:
    """Check selected UDB XLEN against final ELF even for a templated MARCH."""
    path = native_workspace / "work_itgen_Example/rv64/elfs/shared.elf"
    path.write_bytes(b"\x7fELF\x01" + bytes(59))
    passed, result = check(native_workspace, 64)
    assert not passed
    assert any(item["check"] == "source_xlen_conflict" for item in result["report"]["findings"])


def test_excluded_sources_still_receive_structure_checks(native_workspace: Path) -> None:
    """A source excluded from this target remains subject to full source validation."""
    path = native_workspace / "tests/priv/Example/optional.S"
    path.write_text(path.read_text().replace("RVTEST_CODE_END", "INVALID_END"))
    passed, result = check(native_workspace, 64)
    assert not passed
    assert any(item["check"] == "test_source_marker" for item in result["report"]["findings"])


def test_missing_native_selection_resources_fail_closed(native_workspace: Path) -> None:
    """Absent derived capabilities are an error, never evidence of inapplicability."""
    (native_workspace / "work_itgen_Example/rv64/env/extensions.txt").unlink()
    passed, result = check(native_workspace, 64)
    assert not passed
    assert any(item["check"] == "native_source_selection" for item in result["report"]["findings"])


def test_matching_contract_target_xlen_conflict_is_rejected(native_workspace: Path) -> None:
    """A dual-XLEN support set does not hide a conflict for the explicitly matching target."""
    path = native_workspace / "contract.yaml"
    contract = yaml.safe_load(path.read_text())
    contract["selected_target"] = {"test_config": "config/rv64/test_config.yaml", "XLEN": 32}
    path.write_text(yaml.safe_dump(contract))
    passed, result = check(native_workspace, 64)
    assert not passed
    assert any(item["check"] == "selected_config_xlen_contract" for item in result["report"]["findings"])
