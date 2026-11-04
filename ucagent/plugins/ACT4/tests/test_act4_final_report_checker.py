from pathlib import Path

import pytest
import yaml

from act4_privileged_suite.checkers.act4_final_report_checker import ACT4FinalReportChecker


def _write_inputs(tmp_path: Path) -> None:
    reports = tmp_path / "unity_test/H/reports"
    reports.mkdir(parents=True)
    (reports / "detail.md").write_text("# Detail\n", encoding="utf-8")
    (reports / "state.yaml").write_text(
        yaml.safe_dump(
            {
                "contribution_ready": True,
                "generation_scope": {"status": "partial"},
            }
        ),
        encoding="utf-8",
    )


def _checker(tmp_path: Path) -> ACT4FinalReportChecker:
    return ACT4FinalReportChecker(
        report_file="unity_test/H/reports/final.md",
        required_reports=[
            "unity_test/H/reports/detail.md",
            "unity_test/H/reports/state.yaml",
        ],
        required_sections=["Executive conclusion", "Report index", "Limitations"],
        required_phrases=["human inspector", "superseded"],
        validation_state="unity_test/H/reports/state.yaml",
    ).set_workspace(str(tmp_path))


def test_checker_provides_ucagent_description() -> None:
    assert ACT4FinalReportChecker.do_check.__doc__


def test_complete_navigable_report_passes(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    report = tmp_path / "unity_test/H/reports/final.md"
    report.write_text(
        """# Final report

## Executive conclusion

Contribution ready is true for partial scope.

## Final validation state

```yaml
source_contribution_ready: true
generation_scope_status: partial
```

## Report index

- [Detail](detail.md)
- [State](state.yaml)

The old result is superseded by the final state.

## Limitations

Human inspector review is still required.
""",
        encoding="utf-8",
    )

    passed, result = _checker(tmp_path).do_check()

    assert passed
    assert result["summary"] == {"errors": 0, "warnings": 0}


def test_narrative_keywords_cannot_mask_wrong_structured_state(
    tmp_path: Path,
) -> None:
    _write_inputs(tmp_path)
    report = tmp_path / "unity_test/H/reports/final.md"
    report.write_text(
        """# Final report

## Executive conclusion

Contribution ready is true and scope is partial.

## Final validation state

```yaml
source_contribution_ready: false
generation_scope_status: complete
```

## Report index

- [Detail](detail.md)
- [State](state.yaml)

The old result is superseded by the final state.

## Limitations

Human inspector review is still required.
""",
        encoding="utf-8",
    )

    passed, result = _checker(tmp_path).do_check()

    assert not passed
    mismatches = [
        finding
        for finding in result["findings"]
        if finding["check"] == "final_report_state_summary"
    ]
    assert len(mismatches) == 2


def test_unlinked_report_and_missing_explanation_fail(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    report = tmp_path / "unity_test/H/reports/final.md"
    report.write_text(
        "# Final report\n\n## Executive conclusion\n\nPartial contribution.\n",
        encoding="utf-8",
    )

    passed, result = _checker(tmp_path).do_check()

    assert not passed
    checks = {item["check"] for item in result["findings"]}
    assert "final_report_index" in checks
    assert "final_report_section" in checks
    assert "final_report_explanation" in checks


@pytest.mark.parametrize("value", [0, 1, "true", None])
@pytest.mark.parametrize("readiness", [False, True])
def test_final_readiness_requires_boolean(tmp_path: Path, value, readiness: bool) -> None:
    """Reject non-boolean summaries even when Python equality matches a bool."""
    _write_inputs(tmp_path)
    state_path = tmp_path / "unity_test/H/reports/state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["contribution_ready"] = readiness
    state_path.write_text(yaml.safe_dump(state), encoding="utf-8")
    report = tmp_path / "unity_test/H/reports/final.md"
    report.write_text(
        "\n# Final report\n\n## Final validation state\n\n```yaml\n"
        + yaml.safe_dump(
            {"source_contribution_ready": value, "generation_scope_status": "partial"}
        )
        + "```\n",
        encoding="utf-8",
    )
    checker = ACT4FinalReportChecker(
        report_file="unity_test/H/reports/final.md",
        validation_state="unity_test/H/reports/state.yaml",
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert not passed
    assert any(item["check"] == "final_report_state_summary" for item in result["findings"])
