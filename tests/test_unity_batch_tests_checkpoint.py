#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restart persistence for batched Unity test implementation."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.checkers.unity_test import (
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerBatchTestsImplementation,
)
import ucagent.checkers.unity_test as unity_test_module


class _Stage:
    name = "test_case_implementation_in_batch"

    def __init__(self):
        self.batch_resets = 0

    def title(self):
        return "test_case_implementation_in_batch"

    def reset_continue_fail_count_with_batch_pass(self):
        self.batch_resets += 1


class _Manager:
    def __init__(self, report, stage):
        self.data = {"TEST_TEMPLATE_IMP_REPORT": copy.deepcopy(report)}
        self.stage = stage
        self.stage_index = 0
        self.agent = SimpleNamespace(get_tool_by_name=lambda _name: None)

    def get_data(self, key, default=None):
        return self.data.get(key, default)

    def set_data(self, key, value):
        self.data[key] = value

    def get_current_stage(self):
        return self.stage


def _initial_report(test_names):
    return {
        "tests": {
            "total": len(test_names),
            "fails": len(test_names),
            "test_cases": {
                f"tests/test_demo.py:{index * 3 + 1}-{index * 3 + 2}::{name}": "FAILED"
                for index, name in enumerate(test_names)
            },
        }
    }


def _checker(tmp_path, report, *, batch_size=2):
    test_dir = tmp_path / "tests"
    test_dir.mkdir(exist_ok=True)
    (test_dir / "test_demo.py").write_text("# test source\n", encoding="utf-8")
    stage = _Stage()
    manager = _Manager(report, stage)
    checker = UnityChipCheckerBatchTestsImplementation(
        doc_func_check="functions.md",
        doc_bug_analysis="bugs.md",
        test_dir="tests",
        batch_size=batch_size,
        data_key="TEST_TEMPLATE_IMP_REPORT",
        pre_report_file=".TEST_TEMPLATE_IMP_REPORT.json",
        ret_std_out=False,
        ret_std_error=False,
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage)
    checker.set_stage_manager(manager)
    checker.on_init()
    return checker, stage


def _patch_successful_batch(monkeypatch):
    def run_current_batch(checker, **_kwargs):
        test_cases = {
            test_case: "PASSED"
            for test_case in checker.current_test_cases
        }
        return {
            "run_test_success": True,
            "tests": {
                "total": len(test_cases),
                "fails": 0,
                "test_cases": test_cases,
            },
            "failed_check_point_list": [],
            "failed_test_case_with_check_point_list": {},
            "unmarked_check_point_list": [],
        }, "", ""

    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        run_current_batch,
    )
    monkeypatch.setattr(
        unity_test_module.fc,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        unity_test_module.fc,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, {"success": "ok"}),
    )
    monkeypatch.setattr(
        unity_test_module,
        "check_report",
        lambda *_args, **_kwargs: (True, "ok", {}),
    )


def _cached_batch_payload(checker):
    target_tests, _missing = checker.get_run_args(checker.test_dir)
    report = {
        "run_test_success": True,
        "execution": {"invocation_success": True},
        "tests": {
            "total": len(checker.current_test_cases),
            "fails": len(checker.current_test_cases),
            "test_cases": {
                test_case: "FAILED"
                for test_case in checker.current_test_cases
            },
        },
    }
    return {
        "report": report,
        "context": {
            **checker._build_test_report_context(),
            "test_dir_or_file": checker.test_dir,
            "pytest_ex_args": target_tests,
        },
    }


def test_successful_batch_is_restored_after_checker_recreation(tmp_path, monkeypatch):
    report = _initial_report(["test_a", "test_b", "test_c"])
    checker, stage = _checker(tmp_path, report)
    _patch_successful_batch(monkeypatch)

    passed, message = checker.do_check()

    assert passed is False
    assert "2/3" in message["success"]
    assert stage.batch_resets == 1
    checkpoint = Path(checker.batch_task.checkpoint_file)
    persisted = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert persisted["gen_task_list"] == [
        "tests/test_demo.py::test_a",
        "tests/test_demo.py::test_b",
    ]

    restored, _ = _checker(tmp_path, report)

    assert restored.get_template_data()["COMPLETED_CASES"] == 2
    assert restored.get_template_data()["TOTAL_CASES"] == 3
    assert restored.current_test_cases == ["tests/test_demo.py::test_c"]
    assert "committed 2/3" in restored.get_template_data()["BATCH_PROGRESS"]


def test_failed_batch_validation_does_not_persist_completion(tmp_path, monkeypatch):
    report = _initial_report(["test_a", "test_b", "test_c"])
    checker, _ = _checker(tmp_path, report)

    def run_current_batch(current_checker, **_kwargs):
        test_cases = {
            test_case: "FAILED"
            for test_case in current_checker.current_test_cases
        }
        return {
            "run_test_success": True,
            "tests": {
                "total": len(test_cases),
                "fails": len(test_cases),
                "test_cases": test_cases,
            },
        }, "", ""

    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        run_current_batch,
    )
    monkeypatch.setattr(
        unity_test_module.fc,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        unity_test_module,
        "check_report",
        lambda *_args, **_kwargs: (False, "evidence incomplete", {}),
    )

    passed, _ = checker.do_check()

    assert passed is False
    restored, _ = _checker(tmp_path, report)
    assert restored.get_template_data()["COMPLETED_CASES"] == 0
    assert restored.current_test_cases == [
        "tests/test_demo.py::test_a",
        "tests/test_demo.py::test_b",
    ]


def test_cached_document_preflight_rejects_without_rerunning_tests(
    tmp_path,
    monkeypatch,
):
    checker, _stage = _checker(tmp_path, _initial_report(["test_a", "test_b"]))
    payload = _cached_batch_payload(checker)
    monkeypatch.setattr(
        unity_test_module,
        "load_current_test_report",
        lambda _workspace: copy.deepcopy(payload),
    )

    def unexpected_test_run(*_args, **_kwargs):
        raise AssertionError("cached document preflight must not execute pytest")

    monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", unexpected_test_run)
    monkeypatch.setattr(
        unity_test_module,
        "check_report",
        lambda *_args, **_kwargs: (
            False,
            {
                "error_code": "WAVEFORM_RECORD_ANCHOR_INVALID",
                "error": "stable waveform anchor is invalid",
                "next_action": "run repair",
            },
            -1,
        ),
    )

    passed, message = checker.do_check()

    assert passed is False
    assert message["diagnostic"]["error_code"] == "WAVEFORM_RECORD_ANCHOR_INVALID"
    assert (
        message["diagnostic"]["validation_mode"]
        == "cached_report_document_preflight"
    )
    assert message["diagnostic"]["batch_progress"]["test_run"] == "not_run"
    assert message["diagnostic"]["rerun_test"] is False
    assert message["diagnostic"]["rerun_waveinfo"] is False
    assert message["diagnostic"]["batch_advanced"] is False
    assert message["REPORT"] == payload["report"]
    assert checker.batch_task.gen_task_list == []


def test_passing_cached_document_preflight_still_runs_fresh_batch(
    tmp_path,
    monkeypatch,
):
    checker, _stage = _checker(tmp_path, _initial_report(["test_a", "test_b"]))
    payload = _cached_batch_payload(checker)
    monkeypatch.setattr(
        unity_test_module,
        "load_current_test_report",
        lambda _workspace: copy.deepcopy(payload),
    )
    test_run_count = 0

    def run_current_batch(current_checker, **_kwargs):
        nonlocal test_run_count
        test_run_count += 1
        report = copy.deepcopy(payload["report"])
        report["tests"]["test_cases"] = {
            test_case: "PASSED"
            for test_case in current_checker.current_test_cases
        }
        report["tests"]["fails"] = 0
        return report, "", ""

    monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", run_current_batch)
    monkeypatch.setattr(
        unity_test_module.fc,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        unity_test_module.fc,
        "check_has_assert_in_tc",
        lambda *_args, **_kwargs: (True, {"success": "ok"}),
    )
    monkeypatch.setattr(
        unity_test_module,
        "check_report",
        lambda *_args, **_kwargs: (True, "ok", {}),
    )

    checker.do_check()

    assert test_run_count == 1
    assert checker.batch_task.gen_task_list == checker.batch_task.source_task_list


def test_cached_document_preflight_is_invalidated_by_test_source_change(
    tmp_path,
    monkeypatch,
):
    checker, _stage = _checker(tmp_path, _initial_report(["test_a", "test_b"]))
    payload = _cached_batch_payload(checker)
    (tmp_path / "tests/test_demo.py").write_text(
        "# changed test source\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        unity_test_module,
        "load_current_test_report",
        lambda _workspace: copy.deepcopy(payload),
    )
    test_run_count = 0

    def run_current_batch(current_checker, **_kwargs):
        nonlocal test_run_count
        test_run_count += 1
        return copy.deepcopy(payload["report"]), "", ""

    monkeypatch.setattr(BaseUnityChipCheckerTestCase, "do_check", run_current_batch)
    monkeypatch.setattr(
        unity_test_module.fc,
        "is_run_report_pass",
        lambda *_args, **_kwargs: (False, {"error": "stop after fresh run"}),
    )

    passed, message = checker.do_check()

    assert passed is False
    assert message["error"] == "stop after fresh run"
    assert test_run_count == 1


def test_restart_reconciles_completed_tasks_with_changed_source_list(
    tmp_path,
    monkeypatch,
):
    report = _initial_report(["test_a", "test_b", "test_c"])
    checker, _ = _checker(tmp_path, report)
    _patch_successful_batch(monkeypatch)
    checker.do_check()

    changed_report = _initial_report(["test_b", "test_c", "test_d"])
    restored, _ = _checker(tmp_path, changed_report)

    assert restored.batch_task.source_task_list == [
        "tests/test_demo.py::test_b",
        "tests/test_demo.py::test_c",
        "tests/test_demo.py::test_d",
    ]
    assert restored.batch_task.gen_task_list == ["tests/test_demo.py::test_b"]
    assert restored.current_test_cases == [
        "tests/test_demo.py::test_c",
        "tests/test_demo.py::test_d",
    ]
    assert restored.get_template_data()["COMPLETED_CASES"] == 1


def test_restart_rejects_unknown_checkpoint_progress(tmp_path):
    report = _initial_report(["test_a", "test_b"])
    checker, _ = _checker(tmp_path, report)
    checkpoint = Path(checker.batch_task.checkpoint_file)
    persisted = json.loads(checkpoint.read_text(encoding="utf-8"))
    persisted["gen_task_list"] = ["tests/test_demo.py::test_forged"]
    checkpoint.write_text(json.dumps(persisted), encoding="utf-8")

    restored, _ = _checker(tmp_path, report)
    passed, message = restored.do_check()

    assert passed is False
    assert message["error_code"] == "BATCH_CHECKPOINT_INVALID"
    assert message["observed"]["unknown_tasks"] == [
        "tests/test_demo.py::test_forged"
    ]


def test_checkpoint_replace_failure_preserves_previous_state(
    tmp_path,
    monkeypatch,
):
    report = _initial_report(["test_a", "test_b"])
    checker, _ = _checker(tmp_path, report)
    checkpoint = Path(checker.batch_task.checkpoint_file)
    previous = checkpoint.read_bytes()
    checker.batch_task.gen_task_list = ["tests/test_demo.py::test_a"]

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr("ucagent.checkers.base.os.replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        checker.batch_task.savepoint_file()

    assert checkpoint.read_bytes() == previous
    assert list(checkpoint.parent.glob(f".{checkpoint.name}.*.tmp")) == []
