from pathlib import Path

import yaml

from act4_privileged_suite.checkers.act4_ai_review_checker import ACT4AIReviewChecker


def test_checker_has_ucagent_description() -> None:
    assert ACT4AIReviewChecker.do_check.__doc__


def _stage(checks: list[str], status: str = "approved") -> dict:
    section = {
        "review_status": status,
        "summary": "stage reviewed",
        "checks": [
            {
                "name": name,
                "status": "passed",
                "confidence": "confirmed",
                "evidence": [f"{name} checker output"],
                "conclusion": "passed",
                "workflow_blocking": False,
            }
            for name in checks
        ],
        "limitations": [],
        "blocking_issues": [],
        "artifacts": ["reviewed.asset"],
        "commands": [],
    }
    if status == "approved_with_limitations":
        section["limitations"] = ["optional coverage unavailable"]
    return section


def _report(stages: dict[str, dict]) -> dict:
    return {"schema_version": 1, "reviewer": "ai", "stages": stages}


def _write(path: Path, report: dict) -> None:
    path.write_text(yaml.safe_dump(report), encoding="utf-8")


def test_cumulative_prior_stage_and_limitation_pass(tmp_path: Path) -> None:
    _write(
        tmp_path / "review.yaml",
        _report(
            {
                "01_coverpoints": _stage(["suite_boundary"]),
                "02_norm_mapping": _stage(
                    ["mapping_schema"], "approved_with_limitations"
                ),
            }
        ),
    )
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "02_norm_mapping",
        required_prior_stages=["01_coverpoints"],
        required_check_names=["mapping_schema"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed
    assert result["summary"] == {"errors": 0, "warnings": 1}


def test_missing_prior_stage_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "review.yaml",
        _report({"02_norm_mapping": _stage(["mapping_schema"])}),
    )
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "02_norm_mapping",
        required_prior_stages=["01_coverpoints"],
        required_check_names=["mapping_schema"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "ai_review_prior_stage"
        for item in result["findings"]
    )


def test_missing_required_topic_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "review.yaml",
        _report({"01_coverpoints": _stage(["suite_boundary"])}),
    )
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "01_coverpoints",
        required_check_names=["coverage_semantics"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "ai_review_required_checks"
        for item in result["findings"]
    )


def test_blocking_issue_stops_stage(tmp_path: Path) -> None:
    section = _stage(["self_checking_build"], "blocked")
    section["blocking_issues"] = ["self-checking ELF unavailable"]
    _write(tmp_path / "review.yaml", _report({"05_build": section}))
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "05_build",
        required_check_names=["self_checking_build"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "ai_review_blocked"
        for item in result["findings"]
    )


def test_required_artifact_must_exist(tmp_path: Path) -> None:
    _write(
        tmp_path / "review.yaml",
        _report({"03_vm_resources": _stage(["profile_closure"])}),
    )
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "03_vm_resources",
        required_check_names=["profile_closure"],
        required_artifacts=["missing-contract.yaml"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "ai_review_required_artifact"
        for item in result["findings"]
    )


def test_not_run_requires_limitation_and_limited_status(
    tmp_path: Path,
) -> None:
    section = _stage(["reference_model_coverage"])
    section["checks"][0]["status"] = "not_run"
    _write(tmp_path / "review.yaml", _report({"05_build": section}))
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "05_build",
        required_check_names=["reference_model_coverage"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    checks = {item["check"] for item in result["findings"]}
    assert "ai_review_check_limitation" in checks
    assert "ai_review_status_consistency" in checks


def test_spike_fallback_is_a_nonblocking_limitation(tmp_path: Path) -> None:
    section = _stage(
        ["reference_model_coverage"], "approved_with_limitations"
    )
    section["checks"][0].update(
        {
            "status": "not_run",
            "confidence": "confirmed",
            "limitation": "Sail unavailable; Spike self-checking used",
        }
    )
    _write(tmp_path / "review.yaml", _report({"05_build": section}))
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "05_build",
        required_check_names=["reference_model_coverage"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed
    assert result["summary"] == {"errors": 0, "warnings": 1}


def test_workflow_blocking_must_be_boolean(tmp_path: Path) -> None:
    section = _stage(["mapping_schema"])
    section["checks"][0]["workflow_blocking"] = "false"
    _write(tmp_path / "review.yaml", _report({"02_norm_mapping": section}))
    checker = ACT4AIReviewChecker(
        "review.yaml",
        "02_norm_mapping",
        required_check_names=["mapping_schema"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(
        item["check"] == "ai_review_check_schema"
        for item in result["findings"]
    )
