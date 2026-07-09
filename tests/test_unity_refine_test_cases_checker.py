#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UnityChipCheckerRefineTestCases."""

import os
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test import UnityChipCheckerRefineTestCases
from ucagent.tools.testops import RunUnityChipTest


class _FakeStageManager:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.current_stage = SimpleNamespace(reset_continue_fail_count_with_batch_pass=lambda: None)

    def get_data(self, key, default=None):
        return self.data.get(key, default)

    def set_data(self, key, value):
        self.data[key] = value

    def get_current_stage(self):
        return self.current_stage


class _FakeStage:
    name = "refine_test_cases_based_on_functional_points"

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


def _make_checker(tmp_path, entries, batch_size=2, data_key="REFINE_DATA", manager_data=None):
    doc = tmp_path / "functions_and_checks.md"
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    _write_doc(doc, entries)
    manager = _FakeStageManager(manager_data)
    checker = UnityChipCheckerRefineTestCases(
        "functions_and_checks.md",
        test_dir="tests",
        ignore_tc_prefix="test_ignore_",
        batch_size=batch_size,
        data_key=data_key,
    ).set_workspace(str(tmp_path)).set_stage(_FakeStage()).set_stage_manager(manager)
    checker.on_init()
    return checker, manager, tests_dir, doc


def test_get_ck_test_cases_info_uses_mark_function_not_fc_cover_receiver(tmp_path):
    checker, _manager, tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    test_file = tests_dir / "test_sample.py"
    test_file.write_text(
        "\n".join([
            "def test_a(env):",
            "    tracker.mark_function(\"FC-A\", test_a, [\"CK-A\"])",
            "    assert True",
        ]),
        encoding="utf-8",
    )

    ck_map = checker.get_ck_test_cases_info(["FG-A/FC-A/CK-A"])

    assert ck_map["FG-A/FC-A/CK-A"] == ["tests/test_sample.py:1-3::test_a"]
    assert checker.unresolved_mark_function == []


def test_get_ck_test_cases_info_handles_multiline_call_and_ambiguous_fg(tmp_path):
    checker, _manager, tests_dir, _doc = _make_checker(
        tmp_path,
        [
            ("FG-A", "FC-SAME", "CK-SAME"),
            ("FG-B", "FC-SAME", "CK-SAME"),
        ],
    )
    test_file = tests_dir / "test_multiline.py"
    test_file.write_text(
        "\n".join([
            "def test_multiline(env):",
            "    env.some_cover[\"FG-B\"].mark_function(",
            "        \"FC-SAME\",",
            "        test_multiline,",
            "        [\"CK-SAME\"],",
            "    )",
            "    assert True",
        ]),
        encoding="utf-8",
    )

    ck_map = checker.get_ck_test_cases_info([
        "FG-A/FC-SAME/CK-SAME",
        "FG-B/FC-SAME/CK-SAME",
    ])

    assert ck_map["FG-A/FC-SAME/CK-SAME"] == []
    assert ck_map["FG-B/FC-SAME/CK-SAME"] == ["tests/test_multiline.py:1-7::test_multiline"]
    assert checker.unresolved_mark_function == []


def test_get_ck_test_cases_info_records_unresolved_dynamic_marks_and_ignores_prefix(tmp_path):
    checker, _manager, tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    test_file = tests_dir / "test_dynamic.py"
    test_file.write_text(
        "\n".join([
            "def test_dynamic(env):",
            "    fc = \"FC-A\"",
            "    env.anything.mark_function(fc, test_dynamic, [\"CK-A\"])",
            "",
            "def test_ignore_case(env):",
            "    env.anything.mark_function(\"FC-A\", test_ignore_case, [\"CK-A\"])",
        ]),
        encoding="utf-8",
    )

    ck_map = checker.get_ck_test_cases_info(["FG-A/FC-A/CK-A"])

    assert ck_map["FG-A/FC-A/CK-A"] == []
    assert len(checker.unresolved_mark_function) == 1
    assert checker.unresolved_mark_function[0]["test_case"] == "tests/test_dynamic.py:1-3::test_dynamic"


def test_get_template_data_only_reports_cached_total_test_cases(tmp_path):
    checker, _manager, tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )
    test_file = tests_dir / "test_count.py"
    test_file.write_text(
        "\n".join([
            "def test_one(env):",
            "    env.anything.mark_function(\"FC-A\", test_one, [\"CK-A\"])",
            "",
            "def test_two(env):",
            "    env.anything.mark_function(\"FC-A\", test_two, [\"CK-A\"])",
            "",
            "def test_ignore_count(env):",
            "    env.anything.mark_function(\"FC-A\", test_ignore_count, [\"CK-A\"])",
        ]),
        encoding="utf-8",
    )

    assert checker.get_template_data()["TOTAL_TCS"] == 0
    checker.get_ck_test_cases_info(["FG-A/FC-A/CK-A"])
    data = checker.get_template_data()

    assert data["TOTAL_TCS"] == 2


def test_refine_test_cases_requires_refined_argument_for_current_batch(tmp_path):
    checker, _manager, _tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A"), ("FG-A", "FC-A", "CK-B")],
    )

    passed, msg = checker.do_check()

    assert passed is False
    assert "No valid CK labels were refined in the current batch" in msg["error"][0]
    assert msg["error"][1]["current_batch"][0]["CK"] == "FG-A/FC-A/CK-A"


def test_refine_test_cases_rejects_unknown_and_out_of_batch_labels(tmp_path):
    checker, _manager, _tests_dir, _doc = _make_checker(
        tmp_path,
        [
            ("FG-A", "FC-A", "CK-A"),
            ("FG-A", "FC-A", "CK-B"),
            ("FG-A", "FC-A", "CK-C"),
        ],
        batch_size=1,
    )

    passed, msg = checker.do_check(refined={
        "FG-A/FC-A/CK-B": "wrong batch",
        "FG-A/FC-A/CK-X": "unknown",
    })

    assert passed is False
    error_text = "\n".join(str(x) for x in msg["error"])
    assert "not in the current function/check document" in error_text
    assert "not in the current batch" in error_text
    assert "FG-A/FC-A/CK-A" in error_text


def test_refine_test_cases_accepts_stringified_refined_dict_and_accumulates(tmp_path):
    checker, _manager, _tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A"), ("FG-A", "FC-A", "CK-B")],
        batch_size=2,
    )

    passed, msg = checker.do_check(refined='{"FG-A/FC-A/CK-A": "reviewed A"}')

    assert passed is False
    assert "CK-B" in msg["error"]
    assert checker.batch_task.gen_task_list == ["FG-A/FC-A/CK-A"]
    assert checker.refine_result == {"FG-A/FC-A/CK-A": "reviewed A"}


def test_refine_test_cases_reloads_doc_each_check(tmp_path):
    checker, _manager, _tests_dir, doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
        batch_size=10,
    )

    passed, msg = checker.do_check(refined={"FG-A/FC-A/CK-A": "reviewed A"})
    assert passed is True
    assert "All CK are done" in msg["success"]

    _write_doc(doc, [("FG-A", "FC-A", "CK-A"), ("FG-A", "FC-A", "CK-B")])

    passed, msg = checker.do_check()

    assert passed is False
    assert "FG-A/FC-A/CK-B" in msg["error"][0]
    assert checker.batch_task.source_task_list == ["FG-A/FC-A/CK-A", "FG-A/FC-A/CK-B"]
    assert checker.batch_task.tbd_task_list == ["FG-A/FC-A/CK-B"]


def test_refine_test_cases_data_key_saves_data_but_is_not_ck_source(tmp_path):
    cached_source = ["FG-A/FC-A/CK-CACHED"]
    checker, manager, _tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
        manager_data={
            "REFINE_DATA": {
                "source_ck_list": cached_source,
            },
        },
    )

    passed, msg = checker.do_check(is_complete=True, refined={"FG-A/FC-A/CK-A": "reviewed A"})

    assert passed is True
    assert checker.batch_task.source_task_list == ["FG-A/FC-A/CK-A"]
    assert manager.data["REFINE_DATA"]["source_ck_list"] == ["FG-A/FC-A/CK-A"]
    assert manager.data["REFINE_DATA"]["source_ck_list"] != cached_source
    assert manager.data["REFINE_DATA"]["refine_result"] == {"FG-A/FC-A/CK-A": "reviewed A"}
    assert manager.data["REFINE_DATA"]["total_test_cases_count"] == 0


def test_refine_test_cases_does_not_run_pytest(tmp_path, monkeypatch):
    checker, _manager, _tests_dir, _doc = _make_checker(
        tmp_path,
        [("FG-A", "FC-A", "CK-A")],
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("RunUnityChipTest.do must not be called")

    monkeypatch.setattr(RunUnityChipTest, "do", fail_if_called)

    passed, msg = checker.do_check(refined={"FG-A/FC-A/CK-A": "reviewed A"})

    assert passed is True
    assert "All CK are done" in msg["success"]
