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


def test_batch_line_gap_detail_includes_numbered_uncovered_source(tmp_path):
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
        compact_unmapped_blocks=True,
    )
    assert passed is False
    assert "line: line_content" not in str(message)
    assert "Uncovered blocks: [2-2]" in message["error"]
    assert "2: unmapped" in message["error"]
    assert message["uncovered_line_count"] == 1
    assert message["uncovered_line_blocks"] == ["2-2"]
    assert list(message["uncovered_content"].items()) == [(2, "unmapped")]


def test_compact_line_gap_detail_without_required_ranges_includes_source(tmp_path):
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "source.md").write_text("mapped\nunmapped\n", encoding="utf-8")
    (tmp_path / "out" / "line_map" / "source_md_line_func_map.txt").write_text(
        "FG-API/FC-API/CK-API: 1-1\n",
        encoding="utf-8",
    )

    passed, message = _strict_check(
        tmp_path,
        "source.md",
        "out/line_map/source_md_line_func_map.txt",
        compact_unmapped_blocks=True,
    )

    assert passed is False
    assert "2: unmapped" in message["error"]
    assert list(message["uncovered_content"].items()) == [(2, "unmapped")]


def test_batch_checker_reports_uncovered_ranges_and_numbered_content(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "dut.md").write_text(
        "\n".join(f"source content {line_number}" for line_number in range(1, 11))
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "line_map" / "src_dut_md_line_func_map.txt").write_text(
        "FG-API/FC-API/CK-API: 1-2, 6-7, 10-10\n",
        encoding="utf-8",
    )
    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
    ).set_workspace(str(tmp_path)).set_stage(_Stage())
    checker.on_init()

    passed, result = checker.do_check(is_complete=False)

    assert passed is False
    details = result["invalid_mappings"][0]["details"]
    assert details["uncovered_line_count"] == 5
    assert details["uncovered_line_blocks"] == ["3-5", "8-9"]
    assert "Uncovered blocks: [3-5, 8-9]" in details["error"]
    assert "3: source content 3" in details["error"]
    assert "9: source content 9" in details["error"]
    assert list(details["uncovered_content"].items()) == [
        (3, "source content 3"),
        (4, "source content 4"),
        (5, "source content 5"),
        (8, "source content 8"),
        (9, "source content 9"),
    ]
    assert result["uncovered_lines"] == [
        {
            "line_block": "src/dut.md:1-10",
            "uncovered_line_count": 5,
            "uncovered_blocks": ["3-5", "8-9"],
            "uncovered_content": {
                3: "source content 3",
                4: "source content 4",
                5: "source content 5",
                8: "source content 8",
                9: "source content 9",
            },
        }
    ]
    assert len(result["current_line_block_contents"][0]["content"]) == 10


def test_batch_checker_bounds_error_excerpt_but_keeps_all_uncovered_content(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "out" / "line_map").mkdir(parents=True)
    _write_spec(tmp_path / "out" / "spec.md")
    (tmp_path / "src" / "dut.md").write_text(
        "\n".join(f"source line {line_number}" for line_number in range(1, 9)) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "out" / "line_map" / "src_dut_md_line_func_map.txt").write_text(
        "",
        encoding="utf-8",
    )
    checker = UnityChipBatchCheckerFileLineMap(
        name="functional_line_mapping",
        file_list=["src/*.md"],
        func_check_file="out/spec.md",
        progress_file="out/progress.md",
        map_location="out/line_map",
        max_example_lines=3,
    ).set_workspace(str(tmp_path)).set_stage(_Stage())
    checker.on_init()

    passed, result = checker.do_check(is_complete=False)

    assert passed is False
    details = result["invalid_mappings"][0]["details"]
    assert "1: source line 1" in details["error"]
    assert "3: source line 3" in details["error"]
    assert "4: source line 4" not in details["error"]
    assert "... (and 5 more uncovered lines; see uncovered_content)" in details["error"]
    assert list(details["uncovered_content"].items()) == [
        (line_number, f"source line {line_number}")
        for line_number in range(1, 9)
    ]
    assert list(result["uncovered_lines"][0]["uncovered_content"].items()) == [
        (line_number, f"source line {line_number}")
        for line_number in range(1, 9)
    ]


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
    assert "target document changed outside this stage" in str(result)
    assert "do not modify the target document to preserve old progress" in str(result)


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
        "COUNT_CK": "-",
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
    assert checker.get_template_data()["COUNT_CK"] == 1
    assert checker.filter_vstage_description(
        "功能规格逐行查漏补缺[{LINE_MAP_PROGRESS}|{COUNT_CK}]"
    ) == "功能规格逐行查漏补缺[0/1|1]"


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
    assert child["desc"] == "功能规格逐行查漏补缺[{LINE_MAP_PROGRESS}|{COUNT_CK}]"
    task_text = "\n".join(child["task"])
    assert "按批次审查运行时提供的目标文档行块" in task_text
    assert "目标文档集合由当前阶段配置动态确定" in task_text
    assert "所有有功能意义的非空白内容" in task_text
    assert "不要自行猜测、补充或创建未返回的目标文件" in task_text
    assert "参考文档是本阶段的输入，不得修改、重排、格式化、插入空行" in task_text
    assert "正常情况下参考文档的路径和物理行范围保持不变" in task_text
    assert "不得因为 functions_and_checks.md 变化而重算、平移或改写参考文档行号" in task_text
    assert "视为阶段外部变更/输入变更" in task_text
    assert "不得自行修改参考文档来消除错误" in task_text
    assert "不是对应源文件的完整内容" in task_text
    assert "再使用ReadTextFile查看file字段指向的原文件" in task_text
    assert "例如[99-120, 456-888]" in task_text
    assert "uncovered_content" in task_text
    assert "动态工作文档，不是静态只读输入" in task_text
    assert "按可独立激励、观测和判定的维度拆分为多个 CK" in task_text
    assert "不能通过删除标签掩盖功能遗漏" in task_text
    assert "不能留下旧 CK、MISSMT 或不存在的标签" in task_text
    assert "覆盖率定义、测试用例、静态/动态 Bug 证据" in task_text
    assert "同一文档行如果确实同时描述多个独立且可验证的行为" in task_text
    assert "file_list" not in task_text
    assert "MAX_LINE_BLOCK_LINES" not in task_text
    assert "max_example_lines" not in task_text
    assert "100 行" not in task_text
    assert "1-100" not in task_text
    assert child["reference_files"] == [
        "Guide_Doc/dut_functions_and_checks.md",
        "Guide_Doc/dut_line_func_map.md",
        "{OUT}/{DUT}_functions_and_checks.md",
    ]
    assert child["output_files"] == [
        "{OUT}/{DUT}_functions_and_checks.md",
        "{OUT}/{DUT}_line_map_progress.md",
        "{OUT}/line_map/*_line_func_map.txt",
    ]
    assert checker_args["file_list"] == [
        "{DUT}/*.md",
        "{DOC_PATH}/*.md",
        "{OUT}/{DUT}_basic_info.md",
        "{OUT}/{DUT}_verification_needs_and_plan.md",
    ]
    assert "ignore_file_patterns" not in checker_args
    assert all("Guide_Doc" not in pattern for pattern in checker_args["file_list"])


def test_runtime_line_map_guide_uses_configured_limits_and_user_facing_terms():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    guide_path = os.path.join(
        project_root, "ucagent/lang/zh/doc/Guide_Doc/dut_line_func_map.md"
    )
    with open(guide_path, encoding="utf-8") as guide_file:
        guide_text = guide_file.read()

    assert "当前阶段配置的行范围上限" in guide_text
    assert "以任务描述及 `Check`/`Complete` 返回的当前批次为准" in guide_text
    assert "每个映射区间最多覆盖 100 行" not in guide_text
    assert "`max_example_lines`" not in guide_text
    assert "`file_list`" not in guide_text
    assert "正常执行时，目标文档是只读输入" in guide_text
    assert "阶段外部更新、重新生成或其他进程修改" in guide_text
