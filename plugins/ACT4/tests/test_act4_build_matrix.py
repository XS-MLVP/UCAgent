"""Exercise required configuration aggregation independently of an installed ACT checkout."""

from hashlib import sha256
import json
from types import SimpleNamespace

import pytest
import yaml

from ucagent_act4.checkers.act4_review_checker import digest
from ucagent_act4.checkers.act4_test_asset_checker import ACT4TestAssetChecker


@pytest.fixture
def matrix(tmp_path, monkeypatch):
    """Freeze two independent builds and supply native selections with one shared source."""
    sources = tmp_path / "tests/priv/Example"
    sources.mkdir(parents=True)
    for stem in ("shared", "only32", "only64"):
        (sources / f"{stem}.S").write_text("RVTEST_CODE_END\n")
    targets, jobs, attempts = {}, [], []
    for width in (32, 64):
        target = f"rv{width}"
        config = f"config/{target}/test_config.yaml"
        path = tmp_path / config
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump({"name": target, "ref_model_exe": "sail_riscv_sim"}))
        targets[target] = {"config": config, "sources": {config: sha256(path.read_bytes()).hexdigest()}}
        argv = ["make", f"CONFIG_FILES={config}", "EXTENSIONS=Example", "WORKDIR=work_itgen_Example"]
        jobs.append({"target": target, "purpose": "build", "optional": False, "argv": argv})
        attempts.append({"config_file": config, "command": " ".join(argv), "status": "passed", "model": "sail", "executable": "sail_riscv_sim"})
        build = tmp_path / "work_itgen_Example" / target / "elfs"
        build.mkdir(parents=True)
        for stem in ("shared", f"only{width}"):
            (build / f"{stem}.elf").write_bytes(b"\x7fELF" + bytes([width // 32]) + bytes(59))
    evidence = {"jobs": jobs, "validation_plan": {"targets": targets}}
    (tmp_path / "review").mkdir()
    (tmp_path / "review/evidence-before.json").write_text(json.dumps(evidence))
    state = {"source_generated": True, "supported_xlens": [32, 64], "self_checking": dict(attempts[1], passed=True, model="sail", executable="sail_riscv_sim"),
             "sail_coverage": {"passed": False, "command": "", "blocked_reason": "not measured"},
             "generation_scope": {"status": "complete", "generated_targets": [], "partial_targets": [], "blocked_targets": []},
             "contribution_ready": False, "reference_model_evaluation": {"attempts": attempts}}
    (tmp_path / "state.yaml").write_text(yaml.safe_dump(state))
    checker = ACT4TestAssetChecker(suite="Example", matrix_review_dir="review", act4_root=str(tmp_path),
                                  source_patterns=["tests/priv/Example/*.S"], elf_patterns=["work_itgen_Example/*/elfs/*.elf"],
                                  validate_test_config=False, validation_state="state.yaml", output_dir="reports")
    checker.set_workspace(str(tmp_path))
    checker.stage_manager = SimpleNamespace(get_data=lambda key, default: {"evidence-before": digest(evidence)})

    def select(controls, candidates, build, findings):
        """Stand in only for the ACT subprocess; use the real checker for all evidence."""
        width = int(build.name[2:])
        return {"selected_sources": [str(item) for item in candidates if item.stem in {"shared", f"only{width}"}],
                "config_file": str(tmp_path / controls["CONFIG_FILES"]), "build_root": str(build), "xlen": width}

    monkeypatch.setattr(checker, "_native_source_selection", select)
    return checker


def test_required_matrix_and_independent_selection_preflight(matrix, tmp_path):
    """Each target checks two ELFs; their union is three, not four independent sources."""
    passed, result = matrix.do_check()
    assert passed, result
    assert result["report"]["checks"] == {"source_files": 3, "selected_union": 3, "xlens": [32, 64]}
    assert all(item["selected"] == 2 for item in result["report"]["configs"].values())
    report = json.loads((tmp_path / "reports/test-assets.json").read_text())
    assert all(item["checks"]["elf_files"] == 2 for item in report["configs"].values())
    (tmp_path / "state.yaml").unlink()
    (tmp_path / "work_itgen_Example/rv32/elfs/shared.elf").unlink()
    matrix.selection_only = True
    assert matrix.do_check()[0]


def test_extra_primary_does_not_cover_a_gap_in_required_builds(matrix, tmp_path):
    """Validate the optional primary, but never borrow its source coverage for a required target."""
    baseline = tmp_path / "review/evidence-before.json"
    evidence = json.loads(baseline.read_bytes())
    evidence["jobs"][1]["optional"] = True
    baseline.write_text(json.dumps(evidence))
    matrix.stage_manager = SimpleNamespace(get_data=lambda key, default: {"evidence-before": digest(evidence)})
    passed, response = matrix.do_check()
    assert not passed and response["diagnostic"]["error_code"] == "matrix_source_union"
    assert response["report"]["checks"] == {"source_files": 3, "selected_union": 2, "xlens": [32]}
    assert len(response["report"]["configs"]) == 2


@pytest.mark.parametrize(("change", "code"), [("omit_attempt", "matrix_build_attempt"), ("borrow", "test_elf_match"),
    ("omit_source", "matrix_source_union"), ("scope", "matrix_review"), ("config", "matrix_review"), ("controls", "matrix_build_attempt"),
    ("failed_attempt", "matrix_build_attempt"), ("model", "validation_self_check_model_mismatch"), ("truncate", "test_elf_header")])
def test_required_matrix_fails_closed(matrix, tmp_path, change, code):
    """Edited scope, changed controls, missing builds and unselected sources never pass."""
    if change in {"omit_attempt", "controls", "failed_attempt", "model"}:
        state = yaml.safe_load((tmp_path / "state.yaml").read_text())
        attempts = state["reference_model_evaluation"]["attempts"]
        if change == "omit_attempt":
            attempts.pop(0)
        elif change == "failed_attempt":
            attempts[0].update(status="failed", passed=True)
        elif change == "model":
            attempts[0]["model"] = "spike"
        else:
            attempts[0]["command"] += " EXCLUDE_EXTENSIONS=Example"
        (tmp_path / "state.yaml").write_text(yaml.safe_dump(state))
    elif change == "borrow":
        (tmp_path / "work_itgen_Example/rv32/elfs/shared.elf").unlink()
    elif change == "truncate":
        (tmp_path / "work_itgen_Example/rv32/elfs/shared.elf").write_bytes(b"\x7fELF\x01")
    elif change == "omit_source":
        (tmp_path / "tests/priv/Example/uncovered.S").write_text("RVTEST_CODE_END\n")
    elif change == "scope":
        (tmp_path / "review/evidence-before.json").write_text("{}")
    else:
        (tmp_path / "config/rv32/test_config.yaml").write_text("name: renamed")
    passed, result = matrix.do_check()
    assert not passed and result["diagnostic"]["error_code"] == code
    if change in {"borrow", "model", "failed_attempt", "truncate"}:
        assert result["diagnostic"]["location"] == "config/rv32/test_config.yaml"
    if change == "omit_source":
        assert result["diagnostic"]["observed"]["examples"] == [str(tmp_path / "tests/priv/Example/uncovered.S")]
    assert result["diagnostic"]["failure_key"] == matrix.do_check()[1]["diagnostic"]["failure_key"]
    assert result["diagnostic"]["next_action"] and (tmp_path / "reports/test-assets.json").is_file()
