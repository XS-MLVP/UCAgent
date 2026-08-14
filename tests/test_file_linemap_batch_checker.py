import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ucagent.checkers.file_linemap import (
    UnityChipBatchCheckerFileLineMap,
    _line_block_base,
    _mapping_file_for_source,
    line_map_check_one_file,
)
from ucagent.util.config import load_yaml_with_env_vars


class _Stage:
    name = "functional_line_mapping_gap_analysis"

    def title(self):
        return self.name


def _write_spec(path):
    path.write_text(
        "# Spec\n\n<FG-API>\n\n<FC-API>\n\n<CK-API>\n",
        encoding="utf-8",
    )


def _strict_check(workspace, source_file, map_file, **kwargs):
    return line_map_check_one_file(
        str(workspace),
        source_file,
        map_file,
        ["FG-API/FC-API/CK-API"],
        "out/spec.md",
        "_line_func_map.txt",
        "out/line_map",
        20,
        True,
        max_block_lines=100,
        strict_line_bounds=True,
        required_ranges=kwargs.pop("required_ranges", None),
        ignore_blank_lines=True,
        require_ignore_reason=True,
        **kwargs,
    )


def test_strict_line_map_allows_blank_lines_and_rejects_oversized_ranges(tmp_path):
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    (tmp_path / "out" / "spec.md").parent.mkdir(exist_ok=True)
    _write_spec(tmp_path / "out" / "spec.md")
    source = tmp_path / "source.md"
    source.write_text("one\n\nthree\n", encoding="utf-8")
    map_file = tmp_path / "out" / "line_map" / "source_md_line_func_map.txt"
    map_file.write_text("FG-API/FC-API/CK-API: 1-1, 3-3\n", encoding="utf-8")

    passed, message = _strict_check(
        tmp_path,
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        required_ranges=[(1, 3)],
    )
    assert passed is True, message

    long_source = tmp_path / "long.md"
    long_source.write_text("x\n" * 101, encoding="utf-8")
    long_map = tmp_path / "out" / "line_map" / "long_md_line_func_map.txt"
    long_map.write_text("FG-API/FC-API/CK-API: 1-101\n", encoding="utf-8")
    passed, message = _strict_check(
        tmp_path,
        "long.md",
        "out/line_map/long_md_line_func_map.txt",
        required_ranges=[(1, 100)],
    )
    assert passed is False
    assert "100-line block limit" in str(message)


def test_batch_line_gap_detail_has_no_redundant_header(tmp_path):
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    source = tmp_path / "source.md"
    source.write_text("mapped\nunmapped\n", encoding="utf-8")
    map_file = tmp_path / "out" / "line_map" / "source_md_line_func_map.txt"
    map_file.write_text("FG-API/FC-API/CK-API: 1-1\n", encoding="utf-8")

    passed, message = line_map_check_one_file(
        str(tmp_path),
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        ["FG-API/FC-API/CK-API"],
        "out/spec.md",
        "_line_func_map.txt",
        "out/line_map",
        20,
        True,
        max_block_lines=100,
        strict_line_bounds=True,
        required_ranges=[(1, 2)],
        ignore_blank_lines=True,
        require_ignore_reason=True,
        include_line_detail_header=False,
    )
    assert passed is False
    assert "line: line_content" not in str(message)
    assert "2: unmapped" in str(message)


def test_strict_line_map_requires_valid_ck_and_ignore_reason(tmp_path):
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    source = tmp_path / "source.md"
    source.write_text("functional\ncomment\n", encoding="utf-8")
    map_path = tmp_path / "out" / "line_map" / "source_md_line_func_map.txt"

    map_path.write_text("FG-API/FC-UNKNOWN/CK-UNKNOWN: 1-1\n", encoding="utf-8")
    passed, message = _strict_check(
        tmp_path,
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        required_ranges=[(1, 2)],
    )
    assert passed is False
    assert "not found in documentation" in str(message)

    map_path.write_text("IGNORE/FC-API/CK-API: 1-2\n", encoding="utf-8")
    passed, message = _strict_check(
        tmp_path,
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        required_ranges=[(1, 2)],
    )
    assert passed is False
    assert "requires a reason comment" in str(message)

    map_path.write_text(
        "IGNORE/FC-API/CK-API: 1-2 # generated documentation, not DUT behavior\n",
        encoding="utf-8",
    )
    passed, message = _strict_check(
        tmp_path,
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        required_ranges=[(1, 2)],
    )
    assert passed is True, message


def test_batch_checker_uses_only_files_configured_in_file_list(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "dut.md").write_text("line\n" * 101, encoding="utf-8")

    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
        batch_size=1,
        max_block_lines=100,
    ).set_workspace(str(tmp_path)).set_stage(_Stage())
    checker.on_init()

    assert [_line_block_base(task) for task in checker.batch_task.source_task_list] == [
        "src/dut.md:1-100",
        "src/dut.md:101-101",
    ]
    assert [_line_block_base(task) for task in checker.batch_task.tbd_task_list] == [
        "src/dut.md:1-100"
    ]

    passed, result = checker.do_check(is_complete=False)
    assert passed is False
    assert result["missing_mapping_files"] == [
        "out/line_map/src_dut_md_line_func_map.txt"
    ]
    initial_content = result["current_line_block_contents"][0]["content"]
    assert list(initial_content.items()) == [(line_number, "line") for line_number in range(1, 101)]

    map_file = _mapping_file_for_source(
        "src/dut.md", "out/line_map", "_line_func_map.txt"
    )
    (tmp_path / map_file).write_text(
        "FG-API/FC-API/CK-API: 1-100\nFG-API/FC-API/CK-API: 101-101\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "progress.md").write_text(
        "| <file>src/dut.md:1-100</file> | 100 | 完成 |\n",
        encoding="utf-8",
    )

    passed, result = checker.do_check(is_complete=False)
    assert passed is False
    assert result["progress"] == "1/2"
    assert result["current_line_block_contents"][0]["line_block"] == "src/dut.md:1-100"
    assert len(result["current_line_block_contents"][0]["content"]) == 100
    assert result["next_line_blocks"] == ["src/dut.md:101-101"]
    assert list(result["next_line_block_contents"][0]["content"].items()) == [(101, "line")]
    assert [_line_block_base(task) for task in checker.batch_task.tbd_task_list] == [
        "src/dut.md:101-101"
    ]

    with (tmp_path / "out" / "progress.md").open("a", encoding="utf-8") as progress:
        progress.write("| <file>src/dut.md:101-101</file> | 1 | 完成 |\n")
    passed, result = checker.do_check(is_complete=False)
    assert passed is True
    assert result["progress"] == "2/2"

    passed, result = checker.do_check(is_complete=True)
    assert passed is True
    assert result == "Complete success."

    # A content-only change invalidates the old checkpoint-backed task token,
    # even though the file still has the same number of physical lines.
    (tmp_path / "src" / "dut.md").write_text("changed\n" * 101, encoding="utf-8")
    passed, result = checker.do_check(is_complete=False)
    assert passed is False
    assert "source file content changed" in str(result)


def test_batch_checker_does_not_scan_or_check_before_on_init(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "out").mkdir()
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "dut.md").write_text("line\n", encoding="utf-8")

    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
    ).set_workspace(str(tmp_path)).set_stage(_Stage())

    def fail_if_scanned(*args, **kwargs):
        raise AssertionError("file_list must not be scanned before checker.on_init()")

    monkeypatch.setattr(
        "ucagent.checkers.file_linemap.fc.find_files_by_pattern", fail_if_scanned
    )
    assert checker.get_template_data() == {
        "TOTAL_LINE_BLOCKS": "-",
        "COMPLETED_LINE_BLOCKS": "-",
        "LINE_MAP_PROGRESS": "-/-",
        "CURRENT_LINE_BLOCKS": "",
        "MAX_LINE_BLOCK_LINES": 100,
    }
    passed, result = checker.do_check(is_complete=False)
    assert passed is False
    assert "has not been initialized" in str(result)

    monkeypatch.undo()
    checker.on_init()
    assert [_line_block_base(task) for task in checker.batch_task.source_task_list] == [
        "src/dut.md:1-1"
    ]

    monkeypatch.setattr(
        "ucagent.checkers.file_linemap.fc.find_files_by_pattern", fail_if_scanned
    )
    assert checker.get_template_data()["LINE_MAP_PROGRESS"] == "0/1"


def test_batch_checker_rejects_future_progress_marker(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "dut.md").write_text("line\n" * 101, encoding="utf-8")

    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
        batch_size=1,
        max_block_lines=100,
    ).set_workspace(str(tmp_path)).set_stage(_Stage())
    checker.on_init()

    map_file = _mapping_file_for_source(
        "src/dut.md", "out/line_map", "_line_func_map.txt"
    )
    (tmp_path / map_file).write_text(
        "FG-API/FC-API/CK-API: 1-100\nFG-API/FC-API/CK-API: 101-101\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "progress.md").write_text(
        "| <file>src/dut.md:101-101</file> | 1 | 完成 |\n",
        encoding="utf-8",
    )

    passed, result = checker.do_check(is_complete=False)
    assert passed is False
    assert "future line block" in str(result)
    assert result["current_batch"] == ["src/dut.md:1-100"]
    assert len(result["current_line_block_contents"][0]["content"]) == 100


def test_batch_checker_treats_all_blank_files_as_complete(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "out").mkdir()
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "blank.md").write_text("\n   \n\t\n", encoding="utf-8")

    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
    ).set_workspace(str(tmp_path)).set_stage(_Stage())
    checker.on_init()

    template_data = checker.get_template_data()
    assert template_data["TOTAL_LINE_BLOCKS"] == 0
    assert template_data["COMPLETED_LINE_BLOCKS"] == 0
    assert template_data["LINE_MAP_PROGRESS"] == "0/0"

    passed, result = checker.do_check(is_complete=False)
    assert passed is True
    assert result["progress"] == "0/0"
    assert result["current_line_block_contents"] == []

    passed, result = checker.do_check(is_complete=True)
    assert passed is True
    assert result == "Complete success."


def test_default_config_defines_line_map_targets_only_in_checker_file_list():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config = load_yaml_with_env_vars(
        os.path.join(project_root, "ucagent/lang/zh/config/default.yaml")
    )
    parent = next(
        stage
        for stage in config["stage"]
        if stage["name"] == "functional_specification_analysis"
    )
    stage_names = [stage["name"] for stage in parent["stage"]]
    child_index = stage_names.index("functional_line_mapping_gap_analysis")
    assert stage_names[child_index - 1] == "check_point_design"

    child = parent["stage"][child_index]
    checker_args = child["checker"][0]["args"]
    assert child["reference_files"] == [
        "Guide_Doc/dut_functions_and_checks.md",
        "Guide_Doc/dut_line_func_map.md",
        "{OUT}/{DUT}_functions_and_checks.md",
    ]
    assert checker_args["file_list"] == [
        "{DUT}/*.md",
        "{DUT}_Doc/*.md",
        "{OUT}/{DUT}_basic_info.md",
        "{OUT}/{DUT}_verification_needs_and_plan.md",
    ]
    assert "ignore_file_patterns" not in checker_args
    assert all("Guide_Doc" not in pattern for pattern in checker_args["file_list"])
