import hashlib
from pathlib import Path

import yaml

from act4_privileged_suite.checkers.act4_ctp_reference_checker import (
    ACT4CTPReferenceChecker,
    _declared_source_items,
    _human_testplan_contract,
    _optimized_source_contract,
    _raw_matrix,
)
from act4_privileged_suite.checkers.act4_manual_reference_checker import ACT4ManualReferenceChecker


CTP_URL = "https://riscv.github.io/riscv-arch-test/ctp.html"
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/test-sheet-id/"
    "edit?gid=123456#gid=123456"
)
EXPORT_URL = (
    "https://docs.google.com/spreadsheets/d/test-sheet-id/"
    "export?format=csv&gid=123456"
)


def test_reference_checkers_provide_ucagent_descriptions() -> None:
    assert ACT4CTPReferenceChecker.do_check.__doc__
    assert ACT4ManualReferenceChecker.do_check.__doc__


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "ctp": tmp_path / "out/H/references/ctp.html",
        "raw": tmp_path / "out/H/references/H_ctp_raw.csv",
        "optimized": tmp_path / "out/H/H.csv",
        "human": tmp_path / "out/H/H_testplan.md",
        "normative": tmp_path / "out/H/H_normative_rules.csv",
        "metadata": tmp_path / "out/H/references/H_normative_rule_defs.yaml",
        "provenance": tmp_path / "out/H/reports/H_ctp_reference_provenance.yaml",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    paths["ctp"].write_text(
        f"""<!doctype html>
<html><body>
<table id="t-H-coverpoints">
<caption>Table 900. H Coverpoints</caption>
<tr><td><a href="{SHEET_URL}">Google Sheet Testplan</a></td></tr>
</table>
</body></html>
""",
        encoding="utf-8",
    )
    paths["raw"].write_text(
        "Coverpoint,Goal,Normative Rule\n"
        "cp_one,first,norm:sheet_hint:one\n"
        "cp_two,second,norm:sheet_hint:two\n",
        encoding="utf-8",
    )
    paths["optimized"].write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"src_one\"\"]\",cp_one,\"[\"\"real_one\"\"]\",coverpoint\n"
        "\"[\"\"src_two\"\"]\",cp_two,\"[\"\"real_two\"\"]\",coverpoint\n",
        encoding="utf-8",
    )
    paths["human"].write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition |\n"
        "| --- | --- | --- | --- |\n"
        "| `cp_one` | Verify the first CTP request. | `real_one` | coverpoint |\n"
        "| `cp_two` | Verify the second CTP request. | `real_two` | coverpoint |\n\n"
        "## `cp_one`\n\n"
        "- **Functional description:** Verify the first requested behavior.\n"
        "- **Interface / instruction:** Use the interface named by the specification.\n"
        "- **Privilege / preconditions:** Establish the required privilege state.\n"
        "- **Expected result:** Observe the specified architectural result.\n"
        "- **Timing / state restoration:** Record then restore modified state.\n"
        "- **Test notes:** Keep the result visible in the signature.\n\n"
        "## `cp_two`\n\n"
        "- **Functional description:** Verify the second requested behavior.\n"
        "- **Interface / instruction:** Use the interface named by the specification.\n"
        "- **Privilege / preconditions:** Establish the required privilege state.\n"
        "- **Expected result:** Observe the specified architectural result.\n"
        "- **Timing / state restoration:** Record then restore modified state.\n"
        "- **Test notes:** Keep the result visible in the signature.\n",
        encoding="utf-8",
    )
    paths["normative"].write_text(
        "Normative Rule,Rule Text,Coverpoints\n"
        "real_one,First rule,H_cg/cp_one\n"
        "real_two,Second rule,H_cg/cp_two\n",
        encoding="utf-8",
    )
    paths["metadata"].write_text(
        yaml.safe_dump(
            {
                "chapter_name": "H Extension",
                "normative_rule_definitions": [
                    {"name": "real_one", "tags": ["norm:real_one"]},
                    {"name": "real_two", "tags": ["norm:real_two"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_provenance(paths)
    return paths


def _write_provenance(paths: dict[str, Path]) -> None:
    paths["provenance"].write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "suite": "H",
                "ctp": {
                    "url": CTP_URL,
                    "fetched_at": "2026-09-01T00:00:00Z",
                    "snapshot_path": "out/H/references/ctp.html",
                    "sha256": _sha256(paths["ctp"]),
                    "coverpoints_table": {
                        "id": "t-H-coverpoints",
                        "title": "H Coverpoints",
                        "number": 900,
                        "sheet_url": SHEET_URL,
                        "spreadsheet_id": "test-sheet-id",
                        "gid": "123456",
                        "export_url": EXPORT_URL,
                    },
                },
                "testplan": {
                    "raw": {
                        "path": "out/H/references/H_ctp_raw.csv",
                        "sha256": _sha256(paths["raw"]),
                        "source_url": EXPORT_URL,
                    },
                    "optimized": {
                        "path": "out/H/H.csv",
                        "sha256": _sha256(paths["optimized"]),
                    },
                    "human_readable": {
                        "path": "out/H/H_testplan.md",
                        "sha256": _sha256(paths["human"]),
                    },
                    "boundary": {
                        "layout": "row-oriented Coverpoint column",
                        "request_regions": [
                            {
                                "id": "coverpoint_requests",
                                "rows": [2, 3],
                                "columns": [1, 1],
                                "exclusions": [],
                            }
                        ],
                        "non_request_regions": [
                            {
                                "id": "header",
                                "role": "header",
                                "rows": [1, 1],
                                "columns": [1, 3],
                                "reason": "CSV headings are context, not requests",
                            },
                            {
                                "id": "row_context",
                                "role": "context",
                                "rows": [2, 3],
                                "columns": [2, 3],
                                "reason": "goal and Sheet rule-hint cells qualify requests",
                            },
                        ],
                        "source_items": [
                            {
                                "id": "src_one",
                                "cells": [
                                    {"row": 2, "column": 1, "value": "cp_one"}
                                ],
                            },
                            {
                                "id": "src_two",
                                "cells": [
                                    {"row": 3, "column": 1, "value": "cp_two"}
                                ],
                            },
                        ],
                        "selection_basis": [
                            "both non-empty cells in the Coverpoint column"
                        ],
                        "changes": [],
                    },
                },
                "normative_rules_table": {
                    "path": "out/H/H_normative_rules.csv",
                    "sha256": _sha256(paths["normative"]),
                },
            }
        ),
        encoding="utf-8",
    )


def _checker(
    tmp_path: Path,
    paths: dict[str, Path],
    suite: str = "H",
) -> ACT4CTPReferenceChecker:
    return ACT4CTPReferenceChecker(
        suite=suite,
        ctp_snapshot=str(paths["ctp"]),
        provenance_file=str(paths["provenance"]),
        raw_testplan=str(paths["raw"]),
        optimized_testplan=str(paths["optimized"]),
        human_readable_testplan=str(paths["human"]),
        normative_table=str(paths["normative"]),
        normative_metadata=str(paths["metadata"]),
        require_request_regions=True,
        require_full_boundary_review=True,
    ).set_workspace(str(tmp_path))


def test_request_regions_detect_omitted_raw_request_cell(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("Header\ncp_one\ncp_two\n", encoding="utf-8")
    rows = _raw_matrix(raw, [])
    boundary = {
        "layout": "row",
        "request_regions": [
            {
                "id": "requests",
                "rows": [2, 3],
                "columns": [1, 1],
                "exclusions": [],
            }
        ],
        "source_items": [
            {
                "id": "one",
                "cells": [{"row": 2, "column": 1, "value": "cp_one"}],
            }
        ],
    }
    findings: list[dict] = []

    _declared_source_items(
        boundary,
        rows,
        findings,
        raw,
        require_request_regions=True,
    )

    assert any(
        finding["check"] == "ctp_request_region_coverage"
        for finding in findings
    )


def test_boundary_review_detects_unclassified_nonempty_region(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("Header,Notes\ncp_one,context\n", encoding="utf-8")
    boundary = {
        "layout": "row",
        "request_regions": [
            {
                "id": "requests",
                "rows": [2, 2],
                "columns": [1, 1],
                "exclusions": [],
            }
        ],
        "non_request_regions": [
            {
                "id": "header",
                "role": "header",
                "rows": [1, 1],
                "columns": [1, 2],
                "reason": "column headings",
            }
        ],
        "source_items": [
            {
                "id": "one",
                "cells": [{"row": 2, "column": 1, "value": "cp_one"}],
            }
        ],
    }
    findings: list[dict] = []

    _declared_source_items(
        boundary,
        _raw_matrix(raw, findings),
        findings,
        raw,
        require_request_regions=True,
        require_full_boundary_review=True,
    )

    assert any(
        finding["check"] == "ctp_boundary_review_coverage"
        for finding in findings
    )


def test_ctp_checker_accepts_dynamic_table_numbers_and_manual_rule_ids(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)

    passed, report = _checker(tmp_path, paths).do_check()

    assert passed
    assert report["summary"] == {"errors": 0, "warnings": 0}
    assert report["checks"]["ctp_table_number"] == 900
    assert report["checks"]["optimized_rules"] == 2


def test_ctp_checker_validates_declared_human_testplan(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    human = tmp_path / "out/H/H_testplan.md"
    detail = (
        "- **Functional description:** Verify the requested behavior.\n"
        "- **Interface / instruction:** Exercise the specified instruction.\n"
        "- **Privilege / preconditions:** Establish the requested mode.\n"
        "- **Expected result:** Record the architecturally defined result.\n"
        "- **Timing / state restoration:** Restore modified state after observation.\n"
        "- **Test notes:** Preserve signature evidence.\n"
    )
    human.write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition |\n"
        "| --- | --- | --- | --- |\n"
        "| `cp_one` | First request | `real_one` | coverpoint |\n"
        "| `cp_two` | Second request | `real_two` | coverpoint |\n\n"
        f"## `cp_one`\n\n{detail}\n## `cp_two`\n\n{detail}",
        encoding="utf-8",
    )
    provenance = yaml.safe_load(paths["provenance"].read_text(encoding="utf-8"))
    provenance["testplan"]["human_readable"] = {
        "path": "out/H/H_testplan.md",
        "sha256": _sha256(human),
    }
    paths["provenance"].write_text(
        yaml.safe_dump(provenance), encoding="utf-8"
    )
    checker = ACT4CTPReferenceChecker(
        suite="H",
        ctp_snapshot=str(paths["ctp"]),
        provenance_file=str(paths["provenance"]),
        raw_testplan=str(paths["raw"]),
        optimized_testplan=str(paths["optimized"]),
        normative_table=str(paths["normative"]),
        normative_metadata=str(paths["metadata"]),
        human_readable_testplan=str(human),
        require_request_regions=True,
        require_full_boundary_review=True,
    ).set_workspace(str(tmp_path))

    passed, report = checker.do_check()

    assert passed, report
    assert report["checks"]["human_testplan_coverpoints"] == 2


def test_ctp_checker_rejects_rule_ids_absent_from_manual_metadata(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    paths["optimized"].write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"src_one\"\"]\",cp_one,\"[\"\"norm:sheet_hint:one\"\"]\",coverpoint\n"
        "\"[\"\"src_two\"\"]\",cp_two,\"[\"\"real_two\"\"]\",coverpoint\n",
        encoding="utf-8",
    )
    paths["normative"].write_text(
        "Normative Rule,Rule Text,Coverpoints\n"
        "norm:sheet_hint:one,First rule,H_cg/cp_one\n"
        "real_two,Second rule,H_cg/cp_two\n",
        encoding="utf-8",
    )
    _write_provenance(paths)

    passed, report = _checker(tmp_path, paths).do_check()

    assert not passed
    checks = {finding["check"] for finding in report["findings"]}
    assert "ctp_testplan_rule_registry" in checks


def test_ctp_checker_requires_disclosure_for_boundary_changes(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    paths["optimized"].write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"src_one\"\"]\",cp_one,\"[\"\"real_one\"\"]\",coverpoint\n"
        "\"[\"\"src_two\"\"]\",,[],removed\n",
        encoding="utf-8",
    )
    paths["normative"].write_text(
        "Normative Rule,Rule Text,Coverpoints\n"
        "real_one,First rule,H_cg/cp_one\n",
        encoding="utf-8",
    )
    paths["human"].write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition |\n"
        "| --- | --- | --- | --- |\n"
        "| `cp_one` | Verify the first CTP request. | `real_one` | coverpoint |\n\n"
        "## `cp_one`\n\n"
        "- **Functional description:** Verify the first requested behavior.\n"
        "- **Interface / instruction:** Use the specified interface.\n"
        "- **Privilege / preconditions:** Establish the required privilege state.\n"
        "- **Expected result:** Observe the specified architectural result.\n"
        "- **Timing / state restoration:** Record then restore modified state.\n"
        "- **Test notes:** Keep the result visible in the signature.\n",
        encoding="utf-8",
    )
    _write_provenance(paths)
    provenance = yaml.safe_load(paths["provenance"].read_text(encoding="utf-8"))
    paths["provenance"].write_text(
        yaml.safe_dump(provenance),
        encoding="utf-8",
    )

    passed, report = _checker(tmp_path, paths).do_check()

    assert not passed
    assert any(
        finding["check"] == "ctp_boundary_change_disclosure"
        for finding in report["findings"]
    )


def test_ctp_checker_accepts_explicitly_removed_source_row(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["optimized"].write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"src_one\"\"]\",cp_one,\"[\"\"real_one\"\"]\",coverpoint\n"
        "\"[\"\"src_two\"\"]\",,[],removed\n",
        encoding="utf-8",
    )
    paths["normative"].write_text(
        "Normative Rule,Rule Text,Coverpoints\n"
        "real_one,First rule,H_cg/cp_one\n",
        encoding="utf-8",
    )
    paths["human"].write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition |\n"
        "| --- | --- | --- | --- |\n"
        "| `cp_one` | Verify the first CTP request. | `real_one` | coverpoint |\n\n"
        "## `cp_one`\n\n"
        "- **Functional description:** Verify the first requested behavior.\n"
        "- **Interface / instruction:** Use the specified interface.\n"
        "- **Privilege / preconditions:** Establish the required privilege state.\n"
        "- **Expected result:** Observe the specified architectural result.\n"
        "- **Timing / state restoration:** Record then restore modified state.\n"
        "- **Test notes:** Keep the result visible in the signature.\n",
        encoding="utf-8",
    )
    _write_provenance(paths)
    provenance = yaml.safe_load(paths["provenance"].read_text(encoding="utf-8"))
    provenance["testplan"]["boundary"].update(
        {
            "changes": [
                {
                    "action": "removed",
                    "source_item": "src_two",
                    "rationale": "outside the selected manual-defined sub-scope",
                    "evidence": ["selected specification section 1"],
                }
            ],
        }
    )
    paths["provenance"].write_text(
        yaml.safe_dump(provenance),
        encoding="utf-8",
    )

    passed, report = _checker(tmp_path, paths).do_check()

    assert passed, report


def test_ctp_checker_accepts_arbitrary_exact_sheet_backed_suite(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    suite = "SvaduPMP"
    paths["ctp"].write_text(
        paths["ctp"].read_text(encoding="utf-8")
        .replace("t-H-coverpoints", f"t-{suite}-coverpoints")
        .replace("H Coverpoints", f"{suite} Coverpoints"),
        encoding="utf-8",
    )
    paths["human"].write_text(
        paths["human"].read_text(encoding="utf-8").replace(
            "# H Human-Readable Test Plan",
            f"# {suite} Human-Readable Test Plan",
        ),
        encoding="utf-8",
    )
    _write_provenance(paths)
    provenance = yaml.safe_load(paths["provenance"].read_text(encoding="utf-8"))
    provenance["suite"] = suite
    provenance["ctp"]["coverpoints_table"].update(
        {
            "id": f"t-{suite}-coverpoints",
            "title": f"{suite} Coverpoints",
        }
    )
    paths["provenance"].write_text(
        yaml.safe_dump(provenance),
        encoding="utf-8",
    )

    passed, report = _checker(tmp_path, paths, suite=suite).do_check()

    assert passed, report


def test_ctp_checker_rejects_suite_without_google_sheet(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["ctp"].write_text(
        paths["ctp"].read_text(encoding="utf-8").replace(SHEET_URL, "#embedded"),
        encoding="utf-8",
    )
    _write_provenance(paths)

    passed, report = _checker(tmp_path, paths).do_check()

    assert not passed
    finding = next(
        item for item in report["findings"] if item["check"] == "ctp_sheet_link"
    )
    assert "not supported by this workflow" in finding["message"]


def test_ctp_checker_accepts_duplicate_links_to_same_sheet_tab(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    paths["ctp"].write_text(
        paths["ctp"].read_text(encoding="utf-8").replace(
            "</td>",
            f'<a href="{SHEET_URL}">duplicate</a></td>',
        ),
        encoding="utf-8",
    )
    _write_provenance(paths)

    passed, report = _checker(tmp_path, paths).do_check()

    assert passed, report


def test_ctp_checker_rejects_duplicate_suite_table_ids(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    duplicate = (
        f'<table id="t-H-coverpoints"><caption>Table 901. H Coverpoints</caption>'
        f'<a href="{SHEET_URL}">duplicate table</a></table>'
    )
    paths["ctp"].write_text(
        paths["ctp"].read_text(encoding="utf-8").replace(
            "</body>",
            f"{duplicate}</body>",
        ),
        encoding="utf-8",
    )
    _write_provenance(paths)

    passed, report = _checker(tmp_path, paths).do_check()

    assert not passed
    assert any(
        finding["check"] == "ctp_suite_table"
        and "2 tables" in finding["message"]
        for finding in report["findings"]
    )


def test_ctp_checker_rejects_provenance_table_number_drift(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    provenance = yaml.safe_load(paths["provenance"].read_text(encoding="utf-8"))
    provenance["ctp"]["coverpoints_table"]["number"] = 246
    paths["provenance"].write_text(
        yaml.safe_dump(provenance),
        encoding="utf-8",
    )

    passed, report = _checker(tmp_path, paths).do_check()

    assert not passed
    assert any(
        finding["check"] == "ctp_table_provenance"
        for finding in report["findings"]
    )


def test_source_items_support_row_column_and_matrix_layouts(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "mixed.csv"
    raw.write_text(
        ",Goal,cp_horizontal\n"
        "cp_vertical,detail,x\n",
        encoding="utf-8",
    )
    boundary = {
        "layout": "mixed matrix",
        "source_items": [
            {
                "id": "vertical",
                "cells": [{"row": 2, "column": 1, "value": "cp_vertical"}],
            },
            {
                "id": "horizontal",
                "cells": [{"row": 1, "column": 3, "value": "cp_horizontal"}],
            },
        ],
    }
    findings: list[dict] = []

    rows = _raw_matrix(raw, findings)
    items = _declared_source_items(boundary, rows, findings, raw)

    assert items == {"vertical", "horizontal"}
    assert findings == []


def test_source_items_may_share_context_cells(tmp_path: Path) -> None:
    raw = tmp_path / "matrix.csv"
    raw.write_text(",cp_a,cp_b\nmode,x,x\n", encoding="utf-8")
    boundary = {
        "layout": "matrix",
        "source_items": [
            {
                "id": "a",
                "cells": [
                    {"row": 2, "column": 1, "value": "mode"},
                    {"row": 1, "column": 2, "value": "cp_a"},
                ],
            },
            {
                "id": "b",
                "cells": [
                    {"row": 2, "column": 1, "value": "mode"},
                    {"row": 1, "column": 3, "value": "cp_b"},
                ],
            },
        ],
    }
    findings: list[dict] = []

    items = _declared_source_items(
        boundary, _raw_matrix(raw, findings), findings, raw
    )

    assert items == {"a", "b"}
    assert findings == []


def test_source_item_cells_must_match_raw_csv(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("cp_one,goal\n", encoding="utf-8")
    boundary = {
        "layout": "row",
        "source_items": [
            {
                "id": "one",
                "cells": [{"row": 1, "column": 1, "value": "stale"}],
            }
        ],
    }
    findings: list[dict] = []

    _declared_source_items(boundary, _raw_matrix(raw, findings), findings, raw)

    assert any(item["check"] == "ctp_source_cell" for item in findings)


def test_new_workflow_rejects_position_encoded_source_item_ids(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("cp_one\n", encoding="utf-8")
    boundary = {
        "layout": "row",
        "source_items": [
            {
                "id": "row1_cp_one",
                "cells": [{"row": 1, "column": 1, "value": "cp_one"}],
            }
        ],
    }
    findings: list[dict] = []

    _declared_source_items(
        boundary,
        _raw_matrix(raw, findings),
        findings,
        raw,
    )

    assert any(
        item["check"] == "ctp_source_item_semantic_id" for item in findings
    )


def test_human_testplan_matches_machine_coverpoints_and_rules(
    tmp_path: Path,
) -> None:
    testplan = tmp_path / "H_testplan.md"
    testplan.write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition | Test intent |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| `cp_one` | Read the H CSR in M mode | `real_one`, `real_two` | coverpoint | Exercise the CSR and record the value. |\n\n"
        "## `cp_one`\n\n"
        "- **Functional description:** Verify an H CSR read.\n"
        "- **Interface / instruction:** Execute CSRR on the target CSR.\n"
        "- **Privilege / preconditions:** Begin in M mode with H enabled.\n"
        "- **Expected result:** The observed value follows the CSR definition.\n"
        "- **Timing / state restoration:** Record the value and restore modified state.\n"
        "- **Test notes:** Keep the signature result observable.\n",
        encoding="utf-8",
    )
    findings: list[dict] = []

    rows = _human_testplan_contract(
        testplan,
        "H",
        {"cp_one": {"real_one", "real_two"}},
        findings,
    )

    assert rows == 1
    assert findings == []


def test_human_testplan_detects_rule_drift(tmp_path: Path) -> None:
    testplan = tmp_path / "H_testplan.md"
    testplan.write_text(
        "# H Human-Readable Test Plan\n\n"
        "| Coverpoint | Source request | Normative rules | Disposition |\n"
        "| --- | --- | --- | --- |\n"
        "| `cp_one` | Read H CSR | `wrong_rule` | coverpoint |\n",
        encoding="utf-8",
    )
    findings: list[dict] = []

    _human_testplan_contract(
        testplan, "H", {"cp_one": {"real_one"}}, findings
    )

    assert any(item["check"] == "ctp_human_testplan_rules" for item in findings)


def test_raw_matrix_rejects_html_download_and_malformed_csv(
    tmp_path: Path,
) -> None:
    html = tmp_path / "login.csv"
    malformed = tmp_path / "malformed.csv"
    html.write_text("<!doctype html><html>Sign in</html>", encoding="utf-8")
    malformed.write_text('"unterminated,value\n', encoding="utf-8")
    html_findings: list[dict] = []
    malformed_findings: list[dict] = []

    assert _raw_matrix(html, html_findings) == []
    assert _raw_matrix(malformed, malformed_findings) == []
    assert html_findings[0]["check"] == "ctp_csv_content"
    assert malformed_findings[0]["check"] == "ctp_csv_read"


def test_optimized_ctp_consumes_source_item_ids(
    tmp_path: Path,
) -> None:
    optimized = tmp_path / "split.csv"
    optimized.write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"first\"\"]\",cp_first,\"[\"\"rule_first\"\"]\",coverpoint\n"
        "\"[\"\"second\"\"]\",cp_second,\"[\"\"rule_second\"\"]\",coverpoint\n",
        encoding="utf-8",
    )
    findings: list[dict] = []

    consumed, added, removed = _optimized_source_contract(optimized, findings)

    assert consumed == {
        "first": "cp_first",
        "second": "cp_second",
    }
    assert added == set()
    assert removed == set()
    assert findings == []


def test_optimized_ctp_requires_one_canonical_row_per_coverpoint(
    tmp_path: Path,
) -> None:
    optimized = tmp_path / "H.csv"
    optimized.write_text(
        "source_items,coverpoint,normative_rules,disposition\n"
        "\"[\"\"first\"\"]\",cp_same,\"[\"\"real_one\"\"]\",coverpoint\n"
        "\"[\"\"second\"\"]\",cp_same,\"[\"\"real_two\"\"]\",coverpoint\n",
        encoding="utf-8",
    )
    findings: list[dict] = []

    consumed, added, removed = _optimized_source_contract(optimized, findings)

    assert consumed == {"first": "cp_same", "second": "cp_same"}
    assert added == set()
    assert removed == set()
    assert any(
        finding["check"] == "ctp_boundary_duplicate_coverpoint"
        for finding in findings
    )
