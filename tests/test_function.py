#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for utility functions."""

import json
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.util.functions import find_files_by_glob, find_files_by_regex, find_files_by_pattern, render_template_dir
import ucagent.util.functions as fc


def test_run_report_preserves_test_function_contract_diagnostic():
    diagnostic = {
        "error": "test function naming failed",
        "diagnostic": {
            "error_code": "TEST_FUNCTION_CONTRACT_VIOLATION",
            "observed": {"issues": ["tests/test_bad.py:1-1"]},
        },
    }

    passed, message = fc.is_run_report_pass(
        {
            "run_test_success": False,
            "test_function_contract": diagnostic,
        },
        "ignored stdout",
        "ignored stderr",
    )

    assert passed is False
    assert message is diagnostic


def test_find_files_by_glob():
    """Test the find_files_by_glob function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_glob(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_regex():
    """Test the find_files_by_regex function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = r".*\.md$"
    
    # Call the function to find files
    found_files = find_files_by_regex(test_dir, pattern)

    # Print the found files
    print("Found files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_pattern():
    """Test the find_files_by_pattern function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_pattern(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = r".*\.md$"
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = ["*.md", r".*\.md$", "alu.md"]
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching patterns '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_render_template_dir(tmp_path):
    """Test the render_template_dir function."""
    workspace = str(tmp_path)
    template = os.path.abspath(
        os.path.join(current_dir, "../ucagent/lang/zh/template/unity_test")
    )
    context = {"DUT": "alu"}

    rendered_files = render_template_dir(workspace, template, context)

    assert "unity_test/alu_bug_analysis.md" in rendered_files
    assert "unity_test/alu_functions_and_checks.md" in rendered_files
    assert "unity_test/tests/alu_api.py" in rendered_files
    assert (tmp_path / "unity_test" / "alu_bug_analysis.md").is_file()


def test_render_template_target_preserves_non_template_files(tmp_path):
    """Target-mode rendering must merge only template-owned files."""

    template = tmp_path / "template"
    template.mkdir()
    (template / "{{DUT}}.txt").write_text("DUT={{DUT}} OUT={{OUT}}\n", encoding="utf-8")
    output = tmp_path / "generated"
    output.mkdir()
    preserved = output / "existing.txt"
    preserved.write_text("literal {{DUT}}\n", encoding="utf-8")

    rendered = render_template_dir(
        str(tmp_path),
        str(template),
        {"DUT": "alu", "OUT": "generated"},
        target_dir="{OUT}",
    )

    assert rendered == ["generated/alu.txt"]
    assert (output / "alu.txt").read_text(encoding="utf-8") == "DUT=alu OUT=generated\n"
    assert preserved.read_text(encoding="utf-8") == "literal {{DUT}}\n"
    assert not (tmp_path / "unity_test" / "{{DUT}}_bug_analysis.md").exists()


def test_render_template_dir_excludes_installer_bytecode(tmp_path):
    """Installed template bytecode must never be copied into a workspace."""

    template = tmp_path / "installed" / "templates" / "unit_design"
    cache = template / "tests" / "__pycache__"
    cache.mkdir(parents=True)
    (template / "tests" / "{{DUT}}_reference.py").write_text(
        'DUT = "{{DUT}}"\n', encoding="utf-8"
    )
    (cache / "{{DUT}}_reference.cpython-312.pyc").write_bytes(b"compiled")
    (template / "tests" / "stale.pyo").write_bytes(b"optimized")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    rendered = render_template_dir(
        str(workspace),
        str(template),
        {"DUT": "alu", "OUT": "output"},
        target_dir="{OUT}",
    )

    assert rendered == ["output/tests/alu_reference.py"]
    assert (workspace / "output" / "tests" / "alu_reference.py").read_text(
        encoding="utf-8"
    ) == 'DUT = "alu"\n'
    assert not (workspace / "output" / "tests" / "__pycache__").exists()
    assert not (workspace / "output" / "tests" / "stale.pyo").exists()

    default_workspace = tmp_path / "default-workspace"
    default_workspace.mkdir()
    default_rendered = render_template_dir(
        str(default_workspace),
        str(template),
        {"DUT": "alu"},
    )

    assert default_rendered == ["unit_design/tests/alu_reference.py"]
    assert not (
        default_workspace / "unit_design" / "tests" / "__pycache__"
    ).exists()
    assert not (
        default_workspace / "unit_design" / "tests" / "stale.pyo"
    ).exists()


def test_sync_dir_to_matches_relative_ignore_paths_without_broad_name_matches(
    tmp_path,
):
    """History sync must honor path rules while retaining similarly named artifacts."""

    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "performance" / "waves").mkdir(parents=True)
    (source / "performance" / "results").mkdir(parents=True)
    (source / "metadata").mkdir(parents=True)
    (source / "tests" / "database").mkdir(parents=True)
    (source / "performance" / "waves" / "tc.vcd").write_text(
        "wave\n", encoding="utf-8"
    )
    (source / "performance" / "results" / "tc.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (source / "metadata" / "ledger.json").write_text("{}\n", encoding="utf-8")
    (source / "tests" / "database" / "kept.json").write_text(
        "{}\n", encoding="utf-8"
    )

    fc.sync_dir_to(
        str(source),
        str(target),
        ["performance/waves", "tests/data"],
    )

    assert not (target / "performance" / "waves").exists()
    assert (target / "performance" / "results" / "tc.json").is_file()
    assert (target / "metadata" / "ledger.json").is_file()
    assert (target / "tests" / "database" / "kept.json").is_file()



def test_parse_marks_from_file():
    """Test the parse_marks_from_file function."""
    test_file = os.path.join(
        current_dir,
        "../ucagent/lang/zh/template/unity_test/{{DUT}}_line_coverage_analysis.md",
    )
    marks = fc.parse_marks_from_file(test_file, "LINE_IGNORE")

    assert marks["count"] == 2
    assert marks["marks"] == [
        "*/{{DUT}}/{{DUT}}_top.sv",
        "*/{{DUT}}/{{DUT}}_top.v",
    ]


def test_parse_line_ignore_file():
    """Test the parse_line_ignore_file function."""
    test_file = os.path.join(
        current_dir,
        "../ucagent/lang/zh/template/unity_test/tests/{{DUT}}.ignore",
    )
    marks = fc.parse_line_ignore_file(test_file)

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

    coverage = fc.parse_un_coverage_json(
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


def test_replace_bash_var():
    """Test the replace_bash_var function."""
    template_str = "Hello, $(name: Bob )! Welcome to $( place: Wonderland ). Your score is $(score: 100)."
    data = {
        "name": "Alice",
        "place": "Wonderland"
        # 'score' is intentionally left out to test default value
    }
    result = fc.replace_bash_var(template_str, data)
    print("Original string:", template_str)
    print("Data:", data)
    print("Replaced string:", result)
    print("------------------------")
    assert result == "Hello, Alice! Welcome to Wonderland. Your score is 100."
    assert fc.replace_bash_var("$(missing:)", {}) == ""
    assert fc.replace_bash_var("$(missing: fallback)", {}) == "fallback"
    assert fc.replace_bash_var("$(present: fallback)", {"present": ""}) == ""


def test_check_file_block():
    """Test the check_file_block function."""
    # Example usage
    print(fc.check_file_block(
        {"test_function.py": {
            "A": [129, 133], "B": [136, 142] # Example line ranges
        }}, current_dir, lambda x: "usage" in x))
    x = ".mark_function('FC-FUNCTION', 'test_function.py:129-133::test_find_files_by_glob', ['CK-CHECK1', 'CK-CHECK2'])"

def test_description_mark_function_doc():
    print(fc.description_mark_function_doc(
        ["test_function.py:129-133::test_find_files_by_glob", "test_function.py:136-143::test_find_files_by_regex"],
        current_dir,
    ))


def test_check_has_assert_in_tc():
    """Test the check_has_assert_in_tc function."""
    has_assert = fc.check_has_assert_in_tc(current_dir,
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
    test_file = workspace / "unity_test" / "tests" / "test_Adder_env_fixture.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_api_Adder_env_initialization():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    report_key = "/host/tmp/workspace/unity_test/tests/test_Adder_env_fixture.py:1-2::test_api_Adder_env_initialization"
    tests = fc.get_toffee_json_test_case(str(workspace), {report_key: "PASSED"})

    assert tests == [
        (
            "unity_test/tests/test_Adder_env_fixture.py:1-2::test_api_Adder_env_initialization",
            "PASSED",
        )
    ]

    ret, msg = fc.check_has_assert_in_tc(
        str(workspace),
        {"tests": {"test_cases": dict(tests)}},
    )

    assert ret is True
    assert msg == "All test cases have assert statements."


def test_workspace_relative_path_suffix_fallback_unique_filename(tmp_path):
    """Test suffix fallback can recover when only the file name is shared."""
    workspace = tmp_path / "workspace"
    test_file = workspace / "unity_test" / "tests" / "test_unique_name.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_unique_name():\n    assert True\n", encoding="utf-8")

    path = fc.workspace_relative_path(
        str(workspace),
        "/container/other_mount/test_unique_name.py",
    )

    assert path == "unity_test/tests/test_unique_name.py"


def test_workspace_relative_path_suffix_fallback_requires_unique_match(tmp_path):
    """Test suffix fallback does not guess when multiple files match."""
    workspace = tmp_path / "workspace"
    for rel_path in [
        "unity_test/tests/test_duplicate.py",
        "backup/tests/test_duplicate.py",
    ]:
        test_file = workspace / rel_path
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_duplicate():\n    assert True\n", encoding="utf-8")

    path = fc.workspace_relative_path(
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

    headers = fc.markdown_headers(str(tmp_path), "document.md", levels=2)

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

    miss_headers, message = fc.markdown_get_miss_headers(
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
    marks = fc.parse_line_CK_map_file(current_dir, test_file)
    print("Parsed CK marks from file '{}':".format(test_file))
    print("Marks:", marks)
    print("------------------------")

    a, b = fc.get_un_mapped_lines(current_dir, test_file, marks, 3)
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
    ret, msg = fc.check_has_assert_in_tc(str(workspace), report)
    assert ret is False
    assert "test_weak" in msg["error"]
    assert "test_strong" not in msg["error"]


def test_newest_file_mtime_reuses_recent_scan(tmp_path):
    """A fresh changed-files scan is reused instead of rescanning."""

    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")

    calls = {"count": 0}
    original = fc.list_files_by_mtime

    def counting_call(directory, *args, **kwargs):
        calls["count"] += 1
        return original(directory, *args, **kwargs)

    first = fc.newest_file_mtime(str(tmp_path), max_age=5.0)
    assert first == (tmp_path / "a.txt").stat().st_mtime

    import ucagent.util.functions as functions_module
    functions_module._FILE_ACTIVITY_CACHE.clear()
    functions_module.list_files_by_mtime = counting_call
    try:
        original(tmp_path)  # any existing caller (TUI/server) refreshes the cache
        reused = fc.newest_file_mtime(str(tmp_path), max_age=5.0)
        assert reused == first
        assert calls["count"] == 0, "fresh cache must be reused without a rescan"

        stale = fc.newest_file_mtime(str(tmp_path), max_age=0.0)
        assert stale == first
        assert calls["count"] == 1, "a stale cache triggers exactly one proactive rescan"
    finally:
        functions_module.list_files_by_mtime = original
