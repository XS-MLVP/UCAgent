# -*- coding: utf-8 -*-
"""Focused tests for the plugin-owned report/mark parsing helpers.

Covers ``unit_test.doc_marks``, ``unit_test.test_report``, and
``unit_test.report_utils`` markdown/report parsing helpers.
"""

import json
import os

from unit_test.doc_marks import parse_marks_from_file
from unit_test.test_report import (
    check_file_block,
    check_has_assert_in_tc,
    is_run_report_pass,
    workspace_relative_path,
)
from unit_test.report_utils import (
    get_un_mapped_lines,
    markdown_get_miss_headers,
    markdown_headers,
    parse_line_CK_map_file,
    parse_line_ignore_file,
    parse_un_coverage_json,
)
from unit_test.checkers.descriptions import description_mark_function_doc
from unit_test.checkers.toffee_report import get_toffee_json_test_case

current_dir = os.path.dirname(os.path.abspath(__file__))


def test_run_report_preserves_test_function_contract_diagnostic():
    diagnostic = {
        "error": "test function naming failed",
        "diagnostic": {
            "error_code": "TEST_FUNCTION_CONTRACT_VIOLATION",
            "observed": {"issues": ["tests/test_bad.py:1-1"]},
        },
    }

    passed, message = is_run_report_pass(
        {
            "run_test_success": False,
            "test_function_contract": diagnostic,
        },
        "ignored stdout",
        "ignored stderr",
    )

    assert passed is False
    assert message is diagnostic

def test_parse_marks_from_file():
    """Test the parse_marks_from_file function."""
    test_file = os.path.join(
        current_dir,
        "../src/unit_test/templates/unit_test/{{DUT}}_line_coverage_analysis.md",
    )
    marks = parse_marks_from_file(test_file, "LINE_IGNORE")

    assert marks["count"] == 2
    assert marks["marks"] == [
        "*/{{DUT}}/{{DUT}}_top.sv",
        "*/{{DUT}}/{{DUT}}_top.v",
    ]

def test_parse_line_ignore_file():
    """Test the parse_line_ignore_file function."""
    test_file = os.path.join(
        current_dir,
        "../src/unit_test/templates/unit_test/tests/{{DUT}}.ignore",
    )
    marks = parse_line_ignore_file(test_file)

    assert marks["count"] == 2
    assert marks["marks"] == [
        "*/{{DUT}}/{{DUT}}_top.sv",
        "*/{{DUT}}/{{DUT}}_top.v",
    ]

def test_parse_un_coverage_json(tmp_path):
    """Test the parse_un_coverage_json function."""
    test_file = tmp_path / "uc_test_report" / "line_dat" / "code_coverage.json"
    test_file.parent.mkdir(parents=True)
    source_file = tmp_path / "Demo_RTL" / "Demo.v"
    test_file.write_text(
        json.dumps({
            "overview": {
                "total": {"line": 10},
                "miss": {"line": 3},
            },
            "uncovered": {
                "data": {
                    str(source_file): {
                        "total": {"line": 10},
                        "modules": {
                            "Demo": {
                                "miss": {"line": 3},
                                "line": ["2", "4-5"],
                            }
                        },
                    }
                }
            },
        }),
        encoding="utf-8",
    )

    coverage = parse_un_coverage_json(
        "uc_test_report/line_dat/code_coverage.json",
        str(tmp_path),
    )

    assert coverage["lines_total"] == 10
    assert coverage["lines_covered"] == 7
    assert coverage["lines_uncovered"] == 3
    assert coverage["coverage_rate"] == 0.7
    assert coverage["uncoverage_detail"] == [{
        "module_name": "Demo",
        "lines_uncovered": "Demo_RTL/Demo.v:2,4-5",
    }]

def test_check_file_block():
    """Test the check_file_block function."""
    # Example usage
    print(check_file_block(
        {"test_report_and_marks_helpers.py": {
            "A": [129, 133], "B": [136, 142] # Example line ranges
        }}, current_dir, lambda x: "usage" in x))
    x = ".mark_function('FC-FUNCTION', 'test_report_and_marks_helpers.py:129-133::test_parse_marks_from_file', ['CK-CHECK1', 'CK-CHECK2'])"

def test_description_mark_function_doc():
    print(description_mark_function_doc(
        ["test_report_and_marks_helpers.py:129-133::test_parse_marks_from_file", "test_report_and_marks_helpers.py:136-143::test_parse_line_ignore_file"],
        current_dir,
    ))

def test_check_has_assert_in_tc():
    """Test the check_has_assert_in_tc function."""
    has_assert = check_has_assert_in_tc(current_dir,
        {"tests":{"test_cases": {
            "test_function.py:152-162::test_X":False,
            "test_function.py:162-172::test_sample_function":True
            }
            }
        })
    assert True
    print("Function 'test_sample_function' has assert:", has_assert)
    print("------------------------")

def test_toffee_test_case_path_suffix_fallback(tmp_path):
    """Test Toffee report paths with different host/container prefixes."""
    workspace = tmp_path / "workspace"
    test_file = workspace / "unit_test" / "tests" / "test_Adder_env_fixture.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_api_Adder_env_initialization():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    report_key = "/host/tmp/workspace/unit_test/tests/test_Adder_env_fixture.py:1-2::test_api_Adder_env_initialization"
    tests = get_toffee_json_test_case(str(workspace), {report_key: "PASSED"})

    assert tests == [
        (
            "unit_test/tests/test_Adder_env_fixture.py:1-2::test_api_Adder_env_initialization",
            "PASSED",
        )
    ]

    ret, msg = check_has_assert_in_tc(
        str(workspace),
        {"tests": {"test_cases": dict(tests)}},
    )

    assert ret is True
    assert msg == "All test cases have assert statements."

def test_workspace_relative_path_suffix_fallback_unique_filename(tmp_path):
    """Test suffix fallback can recover when only the file name is shared."""
    workspace = tmp_path / "workspace"
    test_file = workspace / "unit_test" / "tests" / "test_unique_name.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_unique_name():\n    assert True\n", encoding="utf-8")

    path = workspace_relative_path(
        str(workspace),
        "/container/other_mount/test_unique_name.py",
    )

    assert path == "unit_test/tests/test_unique_name.py"

def test_workspace_relative_path_suffix_fallback_requires_unique_match(tmp_path):
    """Test suffix fallback does not guess when multiple files match."""
    workspace = tmp_path / "workspace"
    for rel_path in [
        "unit_test/tests/test_duplicate.py",
        "backup/tests/test_duplicate.py",
    ]:
        test_file = workspace / rel_path
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_duplicate():\n    assert True\n", encoding="utf-8")

    path = workspace_relative_path(
        str(workspace),
        "/container/workdir/tests/test_duplicate.py",
    )

    assert path == "container/workdir/tests/test_duplicate.py"

def test_markdown_headers(tmp_path):
    """Test function markdown_headers"""
    test_file = tmp_path / "document.md"
    test_file.write_text(
        "\n# Document\n\n## Overview\n\n### Detail\n\n## Results\n",
        encoding="utf-8",
    )

    headers = markdown_headers(str(tmp_path), "document.md", levels=2)

    assert headers == [(2, "Overview"), (2, "Results")]

def test_markdown_get_miss_headers(tmp_path):
    """Test function markdown_get_miss_headers"""
    (tmp_path / "target.md").write_text(
        "\n# Target\n\n## Overview\n",
        encoding="utf-8",
    )
    (tmp_path / "reference.md").write_text(
        "\n# Reference\n\n## Overview\n\n## Required Results\n",
        encoding="utf-8",
    )

    miss_headers, message = markdown_get_miss_headers(
        str(tmp_path),
        "target.md",
        "reference.md",
        levels=2,
    )

    assert miss_headers == [(2, "Required Results")]
    assert "Level 2, Overview: Present" in message
    assert "Level 2, Required Results: Missed" in message

def test_parse_line_CK_map_file():
    """Test the parse_line_CK_map_file function."""
    test_file = os.path.join("test_data/line_ck_maps.md")
    marks = parse_line_CK_map_file(current_dir, test_file)
    print("Parsed CK marks from file '{}':".format(test_file))
    print("Marks:", marks)
    print("------------------------")

    a, b = get_un_mapped_lines(current_dir, test_file, marks, 3)
    print("Unmapped lines:", a)
    print(b)
    print("------------------------")

if __name__ == "__main__":
    #test_find_files_by_glob()
    #test_find_files_by_regex()
    #test_find_files_by_pattern()
    #test_render_template_dir()
    #test_parse_marks_from_file()
    #test_parse_line_ignore_file()
    #test_parse_un_coverage_json()
    #test_replace_bash_var()
    #test_check_file_block()
    #test_description_mark_function_doc()
    #test_check_has_assert_in_tc()
    #test_markdown_headers()
    #test_markdown_get_miss_headers()
    test_parse_line_CK_map_file()

def test_check_has_assert_ignores_comments_and_fragments(tmp_path):
    """Comments, identifier fragments, and unittest methods are not assertions."""

    workspace = tmp_path / "workspace"
    test_dir = workspace / "tests"
    test_dir.mkdir(parents=True)
    (test_dir / "test_weak.py").write_text(
        "def test_weak():\n"
        "    # no assert needed here\n"
        "    asserted_count = 0\n"
        "    self.assertEqual(1, 1)\n"
        "    return asserted_count\n",
        encoding="utf-8",
    )
    (test_dir / "test_strong.py").write_text(
        "import pytest\n"
        "def test_strong():\n"
        "    with pytest.raises(ValueError):\n"
        "        raise ValueError('x')\n",
        encoding="utf-8",
    )
    report = {
        "tests": {
            "test_cases": {
                "tests/test_weak.py:1-4::test_weak": "PASSED",
                "tests/test_strong.py:1-4::test_strong": "PASSED",
            }
        }
    }
    ret, msg = check_has_assert_in_tc(str(workspace), report)
    assert ret is False
    assert "test_weak" in msg["error"]
    assert "test_strong" not in msg["error"]
