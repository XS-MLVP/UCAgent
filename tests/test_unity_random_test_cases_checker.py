#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for RandomTestCasesChecker argument guidance."""

import os
import sys
import json
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test_random import RandomTestCasesChecker
from ucagent.util.config import load_yaml_with_env_vars


class _FakeStageManager:
    def __init__(self):
        self.data = {}
        self.current_stage = SimpleNamespace(
            reset_continue_fail_count_with_batch_pass=lambda: None,
        )

    def get_data(self, key, default=None):
        return self.data.get(key, default)

    def set_data(self, key, value):
        self.data[key] = value

    def get_current_stage(self):
        return self.current_stage


class _FakeStage:
    name = "generate_random_test_cases"

    def title(self):
        return self.name

    def title_short(self):
        return self.name


def _write_doc(path, entries):
    lines = []
    last_fg = None
    last_fc = None
    for fg, fc, ck in entries:
        if fg != last_fg:
            lines.extend([f"<{fg}>", ""])
            last_fg = fg
            last_fc = None
        if fc != last_fc:
            lines.extend([f"<{fc}>", ""])
            last_fc = fc
        lines.extend([f"<{ck}>", f"{ck} description", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_checker(tmp_path, entries, batch_size=2):
    doc = tmp_path / "functions_and_checks.md"
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    _write_doc(doc, entries)
    manager = _FakeStageManager()
    checker = RandomTestCasesChecker(
        target_test_file="tests/test_random_*.py",
        doc_func_check="functions_and_checks.md",
        doc_bug_analysis="bug_analysis.md",
        test_dir="tests",
        batch_size=batch_size,
        data_key="RANDOM_TEST_DATA",
    ).set_workspace(str(tmp_path)).set_stage(_FakeStage()).set_stage_manager(manager)
    checker.on_init()
    return checker, manager


def test_random_test_checker_rejects_mark_function_in_comment(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    test_file = tmp_path / "tests" / "test_random_comment.py"
    test_file.write_text(
        "\n".join([
            "import ucagent",
            "",
            "def test_random_comment(env):",
            "    ucagent.repeat_count(1)",
            "    # env.cover.mark_function('FC-A', test_random_comment, ['CK-A'])",
            "    assert True",
        ]),
        encoding="utf-8",
    )

    passed, message = checker.test_check()

    assert passed is False
    assert ".mark_function" in message["error"]


def test_random_test_cases_requires_generated_argument_with_check_example(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A"), ("FG-A", "FC-A", "CK-B")],
    )

    passed, message = checker.do_check()

    assert passed is False
    assert "No valid CK labels were recorded" in message["error"][0]
    assert message["error"][1]["current_batch"][0]["CK"] == "FG-A/FC-A/CK-A"
    guidance = message["error"][2]
    assert "Call the Check tool with the stage_args JSON object" in guidance
    assert 'Check(stage_args={"generated": {"FG-A/FC-A/CK-A":' in guidance
    assert "JSON-string fallback" in guidance
    assert 'Check(stage_args="{\\"generated\\": {\\"FG-A/FC-A/CK-A\\":' in guidance


def test_random_test_cases_complete_error_uses_complete_example(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )

    passed, message = checker.do_check(is_complete=True)

    assert passed is False
    guidance = message["error"][2]
    assert "Call the Complete tool with the stage_args JSON object" in guidance
    assert 'Complete(stage_args={"generated": {"FG-A/FC-A/CK-A":' in guidance
    assert 'Complete(stage_args="{\\"generated\\": {\\"FG-A/FC-A/CK-A\\":' in guidance


def test_random_test_cases_invalid_generated_formats_show_check_example(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )

    passed, message = checker.do_check(generated=["FG-A/FC-A/CK-A"])

    assert passed is False
    assert "stage_args.generated must be a JSON object" in message["error"]
    assert 'Check(stage_args={"generated": {"FG-A/FC-A/CK-A":' in message["error"]
    assert 'Check(stage_args="{\\"generated\\": {\\"FG-A/FC-A/CK-A\\":' in message["error"]

    passed, message = checker.do_check(generated="FG-A/FC-A/CK-A generated")

    assert passed is False
    assert "stage_args.generated must be a JSON object" in message["error"]
    assert 'Check(stage_args={"generated": {"FG-A/FC-A/CK-A":' in message["error"]
    assert 'Check(stage_args="{\\"generated\\": {\\"FG-A/FC-A/CK-A\\":' in message["error"]


def test_random_test_cases_unknown_and_out_of_batch_labels_show_current_example(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [
            ("FG-A", "FC-A", "CK-A"),
            ("FG-A", "FC-A", "CK-B"),
            ("FG-A", "FC-A", "CK-C"),
        ],
        batch_size=1,
    )

    passed, message = checker.do_check(generated={
        "FG-A/FC-A/CK-B": "wrong batch",
        "FG-A/FC-A/CK-X": "unknown",
    })

    assert passed is False
    error_text = "\n".join(str(item) for item in message["error"])
    assert "not in the current function/check document" in error_text
    assert "not in the current batch" in error_text
    assert 'Check(stage_args={"generated": {"FG-A/FC-A/CK-A":' in error_text
    assert 'Check(stage_args="{\\"generated\\": {\\"FG-A/FC-A/CK-A\\":' in error_text


def test_random_test_cases_rejects_nested_json_dictionary_string(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    checker._run_random_tests = lambda timeout=0, **kwargs: (True, "pass")

    passed, message = checker.do_check(
        generated='{"FG-A/FC-A/CK-A": "generated deterministic random test"}',
    )

    assert passed is False
    assert "stage_args.generated must be a JSON object" in message["error"]
    assert checker.random_result == {}


def test_random_test_cases_complete_rejects_nested_json_string(tmp_path):
    checker, _manager = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    checker._run_random_tests = lambda timeout=0, **kwargs: (True, "pass")

    passed, message = checker.do_check(
        is_complete=True,
        generated='{"FG-A/FC-A/CK-A": "completed random-test analysis"}',
    )

    assert passed is False
    assert "stage_args.generated must be a JSON object" in message["error"]
    assert checker.random_result == {}


def test_random_test_stage_documents_unified_stage_args_fallback():
    repo_root = os.path.abspath(os.path.join(current_dir, ".."))
    config = load_yaml_with_env_vars(
        os.path.join(repo_root, "ucagent/lang/zh/config/default.yaml")
    )
    stage = next(
        stage for stage in config["stage"]
        if stage["name"] == "generate_random_test_cases"
    )
    task_text = json.dumps(stage["task"], ensure_ascii=False)

    assert "stage_args" in task_text
    assert "字符串fallback示例" in task_text
    assert "完整合法JSON对象" in task_text
    assert "文档结构/语言/代码风格等非DUT激励属性" in task_text
    assert "应跳过该CK并在stage_args.generated中说明确定的跳过原因" in task_text
    assert "不要为了制造随机用例而搜索或修改无关覆盖定义" in task_text
    assert "是跨阶段累计文档" in task_text
    assert "本阶段Check只运行{OUT}/tests/test_{DUT}_random*.py并产生局部报告" in task_text
    assert "历史TC未出现在本轮报告不表示它已Pass" in task_text
    assert "同名BG/TC跨不同CK时必须保留每条真实路径" in task_text
    assert "本轮没有确认新的DUT Bug时无需新增BG" in task_text
    assert "Check(generated=" not in task_text
