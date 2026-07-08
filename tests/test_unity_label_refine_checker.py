#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for UnityChipCheckerLabelStructureRefine."""

import os
import sys
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.unity_test import UnityChipCheckerLabelStructureRefine


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
    name = "functional_specification_refine"

    def title(self):
        return self.name

    def title_short(self):
        return self.name


def _write_doc(path, ck_names):
    lines = ["<FG-API>", "", "<FC-BASIC>", ""]
    for ck in ck_names:
        lines.extend([f"<CK-{ck}>", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_checker(tmp_path, ck_names, cached_ck_names=None, batch_size=2):
    doc = tmp_path / "functions_and_checks.md"
    _write_doc(doc, ck_names)
    manager_data = {}
    if cached_ck_names is not None:
        manager_data["CK_LIST"] = [
            f"FG-API/FC-BASIC/CK-{ck}"
            for ck in cached_ck_names
        ]
    elif ck_names is not None:
        manager_data["CK_LIST"] = [
            f"FG-API/FC-BASIC/CK-{ck}"
            for ck in ck_names
        ]
    manager = _FakeStageManager(manager_data)
    checker = UnityChipCheckerLabelStructureRefine(
        "functions_and_checks.md",
        "CK",
        "CK_LIST",
        batch_size=batch_size,
    ).set_workspace(str(tmp_path)).set_stage(_FakeStage()).set_stage_manager(manager)
    checker.on_init()
    return checker, manager


def test_label_structure_refine_requires_refined_argument_for_current_batch(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B"])

    passed, msg = checker.do_check()

    assert passed is False
    assert "No valid CK labels were refined in the current batch" in "\n".join(msg["error"])


def test_label_structure_refine_rejects_unknown_and_out_of_batch_labels(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B", "C"], batch_size=1)

    passed, msg = checker.do_check(refined={
        "FG-API/FC-BASIC/CK-B": "wrong batch",
        "FG-API/FC-BASIC/CK-X": "unknown",
    })

    assert passed is False
    error_text = "\n".join(msg["error"])
    assert "not in the original list" in error_text
    assert "not in the current batch" in error_text
    assert "FG-API/FC-BASIC/CK-A" in error_text


def test_label_structure_refine_accepts_stringified_refined_dict(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B"], batch_size=2)

    passed, msg = checker.do_check(
        refined='{"FG-API/FC-BASIC/CK-A": "reviewed A"}',
    )

    assert passed is False
    assert "CK-B" in msg["error"]
    assert checker.batch_task.gen_task_list == ["FG-API/FC-BASIC/CK-A"]


def test_label_structure_refine_rejects_unparseable_refined_string(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B"], batch_size=2)

    passed, msg = checker.do_check(refined="FG-API/FC-BASIC/CK-A reviewed")

    assert passed is False
    assert "could not be parsed as a dictionary" in msg["error"]


def test_label_structure_refine_accumulates_completed_tasks_across_checks(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B", "C"], batch_size=2)

    passed, msg = checker.do_check(refined={"FG-API/FC-BASIC/CK-A": "reviewed A"})
    assert passed is False
    assert "CK-B" in msg["error"]
    assert checker.batch_task.gen_task_list == ["FG-API/FC-BASIC/CK-A"]

    passed, msg = checker.do_check(refined={"FG-API/FC-BASIC/CK-B": "reviewed B"})
    assert passed is False
    assert "next 1 CK" in msg["success"]
    assert checker.batch_task.gen_task_list == [
        "FG-API/FC-BASIC/CK-A",
        "FG-API/FC-BASIC/CK-B",
    ]
    assert checker.batch_task.tbd_task_list == ["FG-API/FC-BASIC/CK-C"]

    passed, msg = checker.do_check(refined={"FG-API/FC-BASIC/CK-C": "reviewed C"})
    assert passed is True
    assert "All CK are done" in msg["success"]


def test_label_structure_refine_complete_saves_updated_doc_labels_and_results(tmp_path):
    checker, manager = _make_checker(tmp_path, ["A", "B"], batch_size=2)

    passed, msg = checker.do_check(
        is_complete=True,
        refined={
            "FG-API/FC-BASIC/CK-A": "reviewed A",
            "FG-API/FC-BASIC/CK-B": "reviewed B",
        },
    )

    assert passed is True
    assert "complete success" in msg["success"]
    assert manager.data["CK_LIST"] == [
        "FG-API/FC-BASIC/CK-A",
        "FG-API/FC-BASIC/CK-B",
    ]
    assert manager.data["_CK_REFINE_RESULT"] == {
        "FG-API/FC-BASIC/CK-A": "reviewed A",
        "FG-API/FC-BASIC/CK-B": "reviewed B",
    }


def test_label_structure_refine_uses_original_data_key_as_source_not_latest_doc(tmp_path):
    checker, _manager = _make_checker(tmp_path, ["A", "B"], cached_ck_names=["A"], batch_size=2)

    passed, msg = checker.do_check(refined={
        "FG-API/FC-BASIC/CK-B": "new ck from refined doc",
    })

    assert passed is False
    error_text = "\n".join(msg["error"])
    assert "not in the original list" in error_text
    assert checker.batch_task.source_task_list == ["FG-API/FC-BASIC/CK-A"]


def test_label_structure_refine_on_init_does_not_overwrite_checkpoint_lists(tmp_path):
    checker, manager = _make_checker(tmp_path, ["A", "B"], cached_ck_names=["A", "B"], batch_size=2)
    checker.batch_task.source_task_list = ["FG-API/FC-BASIC/CK-A"]
    checker.batch_task.gen_task_list = ["FG-API/FC-BASIC/CK-A"]
    checker.batch_task.tbd_task_list = []
    checker.batch_task.cmp_task_list = []
    manager.data["CK_LIST"] = ["FG-API/FC-BASIC/CK-A", "FG-API/FC-BASIC/CK-B"]

    checker.on_init()

    assert checker.batch_task.source_task_list == ["FG-API/FC-BASIC/CK-A"]
    assert checker.batch_task.gen_task_list == ["FG-API/FC-BASIC/CK-A"]
    assert checker.batch_task.tbd_task_list == []


def test_label_structure_refine_on_init_falls_back_to_current_doc_when_data_key_empty(tmp_path):
    checker, manager = _make_checker(tmp_path, ["A", "B"], cached_ck_names=[], batch_size=2)

    assert checker.batch_task.source_task_list == [
        "FG-API/FC-BASIC/CK-A",
        "FG-API/FC-BASIC/CK-B",
    ]
    assert manager.data["CK_LIST"] == [
        "FG-API/FC-BASIC/CK-A",
        "FG-API/FC-BASIC/CK-B",
    ]
