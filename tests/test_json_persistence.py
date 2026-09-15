#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atomic JSON persistence regression tests."""

import json
import os
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

import ucagent.util.functions as fc


def test_save_json_file_replace_failure_preserves_previous_state(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "state.json"
    fc.save_json_file(str(target), {"progress": 1})

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(fc.os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        fc.save_json_file(str(target), {"progress": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"progress": 1}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_save_json_file_serialization_failure_preserves_previous_state(tmp_path):
    target = tmp_path / "state.json"
    fc.save_json_file(str(target), {"progress": 1})

    with pytest.raises(ValueError, match="not JSON serializable"):
        fc.save_json_file(str(target), {"invalid": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"progress": 1}
    assert list(tmp_path.glob(".state.json.*.tmp")) == []
