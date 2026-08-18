import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, ".."))
repo_package_root = os.path.join(repo_root, "ucagent")
sys.path.insert(0, repo_root)

loaded_ucagent = sys.modules.get("ucagent")
loaded_ucagent_path = os.path.abspath(getattr(loaded_ucagent, "__file__", "") or "")
if loaded_ucagent is not None and not loaded_ucagent_path.startswith(repo_package_root + os.sep):
    for module_name in list(sys.modules):
        if module_name == "ucagent" or module_name.startswith("ucagent."):
            del sys.modules[module_name]

import ucagent.checkers as checkers
from ucagent.checkers.recorder import Recorder, RecordType
from ucagent.checkers.toffee_report import parse_bug_label
from ucagent.server.api_master import PdbMasterApiServer, PdbMasterClient
from ucagent.util.config import load_yaml_with_env_vars
from ucagent.util.functions import import_class_from_str


class _FakeStage:
    name = "bug_summary"

    def __init__(self):
        self.callbacks = []

    def append_on_complete_callback(self, callback):
        self.callbacks.append(callback)

    def complete(self):
        for callback in self.callbacks:
            callback(self)


class _FakeMasterClient:
    is_running = True

    def __init__(self):
        self.reports = []

    def report_records(self, report):
        self.reports.append(report)
        return True, "record report sent"


class _FailingMasterClient:
    is_running = True

    def report_records(self, report):
        raise RuntimeError("master unavailable")


class _StoppedMasterClient:
    is_running = False


class _UnsupportedMasterClient:
    is_running = True


class _FakeStageManager:
    def __init__(self, stage, master_clients=None):
        self.data = {}
        self.stages = [stage]
        pdb = SimpleNamespace(_master_clients=master_clients or {})
        self.agent = SimpleNamespace(dut_name="Adder", pdb=pdb)

    def get_data(self, key, default=None):
        return self.data.get(key, default)

    def set_data(self, key, value):
        self.data[key] = value


def _write_bug_doc(tmp_path, entries, relative_path="Adder_bug_analysis.md"):
    document_path = Path(tmp_path, relative_path)
    document_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Adder bug analysis"]
    if entries:
        lines.extend(["", "<FG-GROUP>", "", "<FC-FUNCTION>"])
    for index, (bug_name, confidence, ck_name) in enumerate(entries):
        lines.extend([
            "",
            f"- <{ck_name}> Checkpoint description",
            f"  - <BG-{bug_name}-{confidence}> Bug description",
            f"    - <TC-tests/test_adder.py::test_bug_{index}> Reproducer",
        ])
    document_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return document_path


def _write_static_bug_doc(
    tmp_path,
    entries,
    relative_path="Adder_static_bug_analysis.md",
):
    document_path = Path(tmp_path, relative_path)
    document_path.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        lines = ["<FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL>"]
    else:
        lines = ["# Adder static bug analysis", "", "<FG-GROUP>", "", "<FC-FUNCTION>"]
        current_ck = None
        for index, (alias, dynamic_tags, ck_name) in enumerate(entries):
            if ck_name != current_ck:
                lines.extend(["", f"- <{ck_name}> Static checkpoint"])
                current_ck = ck_name
            link_value = "".join(f"[{tag}]" for tag in dynamic_tags)
            lines.extend([
                f"  - <{alias}> Static Bug description",
                f"    - <LINK-BUG-{link_value}>",
                f"      - <FILE-rtl/adder.sv:{index + 1}>",
            ])
    document_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return document_path


def _make_recorder(
    tmp_path,
    recorder_type="bug",
    data_key="BUG_RECORDS",
    master_clients=None,
    type_args=None,
    initialize=True,
    **recorder_kwargs,
):
    if isinstance(recorder_type, str) and recorder_type.lower() == "bug":
        default_document = Path(tmp_path, "Adder_bug_analysis.md")
        if not default_document.exists():
            _write_bug_doc(tmp_path, [])
        default_static_document = Path(tmp_path, "Adder_static_bug_analysis.md")
        if not default_static_document.exists():
            _write_static_bug_doc(tmp_path, [])
    stage = _FakeStage()
    manager = _FakeStageManager(stage, master_clients=master_clients)
    recorder = (
        Recorder(
            type=recorder_type,
            data_key=data_key,
            type_args=type_args,
            **recorder_kwargs,
        )
        .set_workspace(str(tmp_path))
        .set_stage(stage)
        .set_stage_manager(manager)
    )
    if initialize:
        recorder.on_init()
    return recorder, manager, stage


def _with_expected_bug_metadata(recorder, records):
    _document, expected_bugs = recorder.type_handler._load_expected_bugs()
    enriched = []
    for record in records:
        item = dict(record)
        bug_name = item.get("bug_name")
        normalized_name = bug_name
        if isinstance(bug_name, str) and bug_name.strip("<>").startswith("BG-"):
            normalized_name, _confidence = parse_bug_label(bug_name)
        expected = expected_bugs.get(normalized_name)
        if expected is not None:
            item.setdefault("alias", list(expected["alias"]))
            item.setdefault("ref", list(expected["ref"]))
            item.setdefault("severity", "medium")
        enriched.append(item)
    return enriched


def test_bug_recorder_normalizes_and_caches_bug_list(tmp_path):
    _write_bug_doc(tmp_path, [
        ("overflow_bug", 76, "CK-OVERFLOW"),
        ("overflow_bug", 76, "CK-BOUNDARY"),
    ])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.check(bug_list=_with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["FG-GROUP/FC-FUNCTION/CK-OVERFLOW", "CK-BOUNDARY"],
        "desc": "The result width truncates the carry bit; the output declaration is too narrow.",
        "locations": ["rtl/adder.sv:128-229", "rtl/adder.sv:240,250-252"],
        "confidence": 76,
    }]))

    assert passed is True
    assert message["bug_count"] == 1
    assert manager.data["BUG_RECORDS"] == [{
        "bug_name": "overflow_bug",
        "alias": [],
        "CK": ["FG-GROUP/FC-FUNCTION/CK-OVERFLOW", "FG-GROUP/FC-FUNCTION/CK-BOUNDARY"],
        "desc": "The result width truncates the carry bit; the output declaration is too narrow.",
        "locations": ["rtl/adder.sv:128-229", "rtl/adder.sv:240,250-252"],
        "severity": "medium",
        "confidence": 0.76,
        "ref": ["Adder_bug_analysis.md:8-9,12-13"],
    }]


def test_bug_recorder_preserves_severity(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, _message = recorder.do_check(bug_list=_with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "The result width truncates the carry bit.",
        "locations": ["rtl/adder.sv:128-229"],
        "confidence": 0.76,
        "severity": " HIGH ",
    }]))

    assert passed is True
    assert manager.data["BUG_RECORDS"][0]["severity"] == "HIGH"


@pytest.mark.parametrize(
    ("severity", "error_text"),
    [
        ("", "must be a non-empty string"),
        ("urgent", "must be one of"),
        (123, "must be a non-empty string"),
        (None, "must be a non-empty string"),
    ],
)
def test_bug_recorder_reports_invalid_severity_values(tmp_path, severity, error_text):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(
        bug_list=_with_expected_bug_metadata(
            recorder,
            [
                {
                    "bug_name": "overflow_bug",
                    "CK": ["CK-OVERFLOW"],
                    "desc": "The result width truncates the carry bit.",
                    "locations": ["rtl/adder.sv:128-229"],
                    "confidence": 0.76,
                    "severity": severity,
                }
            ],
        )
    )

    assert passed is False
    assert error_text in message["error"]
    assert "lowest, low, medium, high, highest" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_requires_severity(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    record = _with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "The result width truncates the carry bit.",
        "locations": ["rtl/adder.sv:128-229"],
        "confidence": 0.76,
    }])[0]
    record.pop("severity")

    passed, message = recorder.do_check(bug_list=[record])

    assert passed is False
    assert ".severity is required" in message["error"]
    assert "lowest, low, medium, high, highest" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_reuses_existing_records_on_complete(tmp_path):
    recorder, manager, _stage = _make_recorder(tmp_path)
    manager.data["BUG_RECORDS"] = []

    passed, message = recorder.do_check(is_complete=True)

    assert passed is True
    assert message["bug_count"] == 0


def test_bug_recorder_reads_legacy_string_checkpoint(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    records = _with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "The output is truncated because the result signal is too narrow.",
        "locations": ["rtl/adder.sv:128-229"],
        "confidence": 0.76,
    }])
    manager.data["BUG_RECORDS"] = json.dumps(records)

    assert recorder.get_template_data()["COMPLETED_BUGS"] == 1
    passed, message = recorder.do_check(is_complete=True)

    assert passed is True
    assert message["bug_count"] == 1


def test_bug_recorder_rejects_nested_json_string_bug_list(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    bug_list = json.dumps(_with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "The output is truncated because the result signal is too narrow.",
        "locations": ["rtl/adder.sv:128-229"],
        "confidence": 0.76,
    }]))

    passed, message = recorder.do_check(bug_list=bug_list)

    assert passed is False
    assert "must be a JSON array, got str" in message["error"]
    assert "complete stage_args object as a JSON string" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_missing_bug_list_shows_check_object_and_string_examples(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, _manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check()

    assert passed is False
    assert message["current_batch"][0]["bug_name"] == "overflow_bug"
    error_text = message["error"]
    assert "Call the Check tool with the stage_args JSON object" in error_text
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "overflow_bug"' in error_text
    assert 'JSON-string fallback: Check(stage_args="{\\"bug_list\\": [{\\"bug_name\\": \\"overflow_bug\\"' in error_text
    assert '"CK": ["FG-GROUP/FC-FUNCTION/CK-OVERFLOW"]' in error_text
    assert '"confidence": 0.76' in error_text
    assert '"ref": ["Adder_bug_analysis.md:8-9"]' in error_text
    assert '"severity": "REPLACE_WITH_LOWEST_LOW_MEDIUM_HIGH_HIGHEST"' in error_text
    assert "Required `severity` accepts lowest, low, medium, high, highest" in error_text


def test_bug_recorder_missing_bug_list_shows_complete_examples(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, _manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(is_complete=True)

    assert passed is False
    error_text = message["error"]
    assert "Call the Complete tool with the stage_args JSON object" in error_text
    assert 'Object template: Complete(stage_args={"bug_list": [{"bug_name": "overflow_bug"' in error_text
    assert 'JSON-string fallback: Complete(stage_args="{\\"bug_list\\": [{\\"bug_name\\": \\"overflow_bug\\"' in error_text


def test_bug_recorder_rejects_invalid_json_string_bug_list(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(bug_list="[{'bug_name': 'not-json'}]")

    assert passed is False
    assert "must be a JSON array, got str" in message["error"]
    assert message["current_batch"][0]["bug_name"] == "overflow_bug"
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "overflow_bug"' in message["error"]
    assert "JSON-string fallback: Check(stage_args=" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_rejects_non_array_bug_list_with_call_examples(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(bug_list={
        "bug_name": "overflow_bug",
    })

    assert passed is False
    assert "must be a JSON array" in message["error"]
    assert message["current_batch"][0]["bug_name"] == "overflow_bug"
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "overflow_bug"' in message["error"]
    assert "JSON-string fallback: Check(stage_args=" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_complete_rejects_nested_json_string_bug_list(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    bug_list = json.dumps(_with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "The output is truncated because the result signal is too narrow.",
        "locations": ["rtl/adder.sv:128-229"],
        "confidence": 0.76,
    }]))

    passed, message = recorder.do_check(
        is_complete=True,
        bug_list=bug_list,
    )

    assert passed is False
    assert "must be a JSON array, got str" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_reuses_existing_bug_label_parser(tmp_path):
    _write_bug_doc(tmp_path, [("CIN-OVERFLOW", 98, "CK-CIN-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, _message = recorder.do_check(bug_list=_with_expected_bug_metadata(recorder, [{
        "bug_name": "<BG-CIN-OVERFLOW-98>",
        "CK": ["CK-CIN-OVERFLOW"],
        "desc": "Carry input is omitted from overflow detection.",
        "locations": ["Adder.v:28-30"],
        "confidence": 0.98,
    }]))

    assert passed is True
    assert manager.data["BUG_RECORDS"][0]["bug_name"] == "CIN-OVERFLOW"
    assert manager.data["BUG_RECORDS"][0]["confidence"] == 0.98


def test_bug_recorder_rejects_invalid_source_location(tmp_path):
    _write_bug_doc(tmp_path, [("overflow_bug", 76, "CK-OVERFLOW")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(bug_list=_with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow_bug",
        "CK": ["CK-OVERFLOW"],
        "desc": "Root cause",
        "locations": ["rtl/adder.sv:229-128"],
        "confidence": 0.76,
    }]))

    assert passed is False
    assert "invalid line range" in message["error"]
    assert message["current_batch"][0]["bug_name"] == "overflow_bug"
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "overflow_bug"' in message["error"]
    assert "JSON-string fallback: Check(stage_args=" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_records_document_bugs_in_batches(tmp_path):
    _write_bug_doc(tmp_path, [
        ("bug-a", 90, "CK-A"),
        ("bug-b", 80, "CK-B"),
        ("bug-c", 70, "CK-C"),
    ])
    recorder, manager, _stage = _make_recorder(
        tmp_path,
        type_args={"bug_file": "{{DUT}}_bug_analysis.md", "batch_size": 2},
    )
    records = {
        name: {
            "bug_name": name,
            "CK": [ck],
            "desc": f"Description and root cause for {name}.",
            "locations": [f"rtl/adder.sv:{line}-{line + 1}"],
            "confidence": confidence,
        }
        for name, confidence, ck, line in [
            ("bug-a", 0.90, "CK-A", 10),
            ("bug-b", 0.80, "CK-B", 20),
            ("bug-c", 0.70, "CK-C", 30),
        ]
    }
    records = {
        name: _with_expected_bug_metadata(recorder, [record])[0]
        for name, record in records.items()
    }

    passed, message = recorder.do_check(bug_list=[records["bug-c"]])
    assert passed is False
    assert "not in the current batch" in message["error"]
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "bug-a"' in message["error"]
    assert "JSON-string fallback: Check(stage_args=" in message["error"]
    assert "BUG_RECORDS" not in manager.data

    passed, message = recorder.do_check(
        bug_list=[records["bug-a"], records["bug-b"]]
    )
    assert passed is False
    assert message["progress"] == "2/3"
    assert [item["bug_name"] for item in message["current_batch"]] == ["bug-c"]
    assert [item["bug_name"] for item in manager.data["BUG_RECORDS"]] == [
        "bug-a",
        "bug-b",
    ]

    passed, message = recorder.do_check(bug_list=[records["bug-a"]])
    assert passed is False
    assert "already recorded" in message["error"]
    assert 'Object template: Check(stage_args={"bug_list": [{"bug_name": "bug-c"' in message["error"]

    passed, message = recorder.do_check(is_complete=True)
    assert passed is False
    assert message["progress"] == "2/3"
    assert 'Object template: Complete(stage_args={"bug_list": [{"bug_name": "bug-c"' in message["error"]
    assert "JSON-string fallback: Complete(stage_args=" in message["error"]

    passed, message = recorder.do_check(bug_list=[records["bug-c"]])
    assert passed is True
    assert message["progress"] == "3/3"

    passed, message = recorder.do_check(is_complete=True)
    assert passed is True
    assert message["bug_count"] == 3
    assert [item["bug_name"] for item in manager.data["BUG_RECORDS"]] == [
        "bug-a",
        "bug-b",
        "bug-c",
    ]


def test_bug_recorder_rejects_records_not_declared_in_document(tmp_path):
    _write_bug_doc(tmp_path, [("documented", 90, "CK-DOCUMENTED")])
    recorder, manager, _stage = _make_recorder(tmp_path)

    passed, message = recorder.do_check(bug_list=[{
        "bug_name": "extra",
        "CK": ["CK-DOCUMENTED"],
        "desc": "Extra bug",
        "locations": ["rtl/adder.sv:10-11"],
        "confidence": 0.90,
    }])

    assert passed is False
    assert "is not declared" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_treats_missing_bug_document_as_no_bugs(tmp_path):
    recorder, manager, stage = _make_recorder(
        tmp_path,
        initialize=False,
        output="reports/{{DUT}}_bug_summary.md",
    )
    Path(tmp_path, "Adder_bug_analysis.md").unlink()
    recorder.on_init()

    passed, message = recorder.do_check(is_complete=True)

    assert passed is True
    assert message["bug_count"] == 0
    assert message["progress"] == "0/0"
    assert manager.data["BUG_RECORDS"] == []

    stage.complete()

    summary = Path(tmp_path, "reports/Adder_bug_summary.md").read_text(
        encoding="utf-8"
    )
    assert "Total Bugs: 0" in summary


def test_bug_recorder_requires_dynamic_document_for_confirmed_static_links(tmp_path):
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-CONFIRMED", ["BG-dynamic-90"], "CK-STATIC"),
    ])
    recorder, manager, _stage = _make_recorder(tmp_path, initialize=False)
    Path(tmp_path, "Adder_bug_analysis.md").unlink()
    recorder.on_init()

    passed, message = recorder.do_check(bug_list=[])

    assert passed is False
    assert "does not exist" in message["error"]
    assert "confirmed dynamic links" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_requires_static_bug_analysis_document(tmp_path):
    recorder, manager, _stage = _make_recorder(tmp_path, initialize=False)
    Path(tmp_path, "Adder_static_bug_analysis.md").unlink()
    recorder.on_init()

    passed, message = recorder.do_check(bug_list=[])

    assert passed is False
    assert "Static bug analysis document" in message["error"]
    assert "does not exist" in message["error"]
    assert "BUG_RECORDS" not in manager.data


@pytest.mark.parametrize(
    ("field", "value", "error_text"),
    [
        ("CK", ["CK-OTHER"], "is not associated"),
        ("confidence", 0.80, "does not match"),
    ],
)
def test_bug_recorder_requires_document_ck_and_confidence(
    tmp_path, field, value, error_text
):
    _write_bug_doc(tmp_path, [("documented", 90, "CK-DOCUMENTED")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    record = {
        "bug_name": "documented",
        "CK": ["CK-DOCUMENTED"],
        "desc": "Description and root cause",
        "locations": ["rtl/adder.sv:10-11"],
        "confidence": 0.90,
    }
    record[field] = value

    passed, message = recorder.do_check(
        bug_list=_with_expected_bug_metadata(recorder, [record])
    )

    assert passed is False
    assert error_text in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_accepts_document_path_as_direct_recorder_argument(tmp_path):
    _write_bug_doc(
        tmp_path,
        [("custom-path", 85, "CK-CUSTOM")],
        relative_path="reports/Adder_bug_analysis.md",
    )
    recorder, manager, _stage = _make_recorder(
        tmp_path,
        bug_file="reports/{{DUT}}_bug_analysis.md",
    )

    passed, _message = recorder.do_check(bug_list=_with_expected_bug_metadata(recorder, [{
        "bug_name": "custom-path",
        "CK": ["CK-CUSTOM"],
        "desc": "Description and root cause",
        "locations": ["rtl/adder.sv:40-42"],
        "confidence": 0.85,
    }]))

    assert passed is True
    assert manager.data["BUG_RECORDS"][0]["bug_name"] == "custom-path"


def test_bug_recorder_accepts_dut_placeholder_after_config_rendering(tmp_path):
    _write_bug_doc(
        tmp_path,
        [],
        relative_path="reports/Adder_bug_analysis.md",
    )
    recorder, _manager, _stage = _make_recorder(
        tmp_path,
        type_args={"bug_file": "reports/{Adder}_bug_analysis.md"},
    )

    passed, message = recorder.do_check(bug_list=[])

    assert passed is True
    assert message["bug_count"] == 0


def test_bug_recorder_maps_confirmed_static_aliases_and_exact_document_refs(tmp_path):
    _write_bug_doc(tmp_path, [
        ("bug-a", 90, "CK-A"),
        ("bug-b", 80, "CK-B"),
    ])
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-A", ["BG-bug-a-90"], "CK-STATIC"),
        ("BG-STATIC-002-SHARED", ["BG-bug-a-90", "BG-bug-b-80"], "CK-STATIC"),
        ("BG-STATIC-003-NA", ["BG-NA"], "CK-STATIC"),
        ("BG-STATIC-004-TBD", ["BG-TBD"], "CK-STATIC"),
    ])
    recorder, manager, _stage = _make_recorder(tmp_path)

    template_data = recorder.get_template_data()

    assert template_data["LIST_CURRENT_BUGS"][:2] == [
        {
            "bug_name": "bug-a",
            "alias": ["BG-STATIC-001-A", "BG-STATIC-002-SHARED"],
            "CK": ["FG-GROUP/FC-FUNCTION/CK-A"],
            "confidence": 0.90,
            "ref": [
                "Adder_static_bug_analysis.md:8-10,11-13",
                "Adder_bug_analysis.md:8-9",
            ],
            "document_marks": ["FG-GROUP/FC-FUNCTION/CK-A/BG-bug-a-90"],
            "document_blocks": [[
                "7: ...",
                "8:   - <BG-bug-a-90> Bug description",
                "9: ...",
            ]],
        },
        {
            "bug_name": "bug-b",
            "alias": ["BG-STATIC-002-SHARED"],
            "CK": ["FG-GROUP/FC-FUNCTION/CK-B"],
            "confidence": 0.80,
            "ref": [
                "Adder_static_bug_analysis.md:11-13",
                "Adder_bug_analysis.md:12-13",
            ],
            "document_marks": ["FG-GROUP/FC-FUNCTION/CK-B/BG-bug-b-80"],
            "document_blocks": [[
                "11: ...",
                "12:   - <BG-bug-b-80> Bug description",
                "13: ...",
            ]],
        },
    ]

    records = _with_expected_bug_metadata(recorder, [
        {
            "bug_name": "bug-a",
            "CK": ["CK-A"],
            "desc": "Bug A description and root cause.",
            "locations": ["rtl/adder.sv:10-12"],
            "confidence": 0.90,
        },
        {
            "bug_name": "bug-b",
            "CK": ["CK-B"],
            "desc": "Bug B description and root cause.",
            "locations": ["rtl/adder.sv:20-22"],
            "confidence": 0.80,
        },
    ])
    passed, message = recorder.do_check(bug_list=records)

    assert passed is True
    assert message["bug_count"] == 2
    assert manager.data["BUG_RECORDS"][0]["alias"] == [
        "BG-STATIC-001-A",
        "BG-STATIC-002-SHARED",
    ]
    assert manager.data["BUG_RECORDS"][1]["alias"] == [
        "BG-STATIC-002-SHARED"
    ]


def test_bug_recorder_ignores_zero_confidence_bugs_everywhere(tmp_path):
    _write_bug_doc(tmp_path, [
        ("dismissed", 0, "CK-DISMISSED"),
        ("confirmed", 80, "CK-CONFIRMED"),
    ])
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-DISMISSED", ["BG-dismissed-0"], "CK-STATIC"),
        ("BG-STATIC-002-CONFIRMED", ["BG-confirmed-80"], "CK-STATIC"),
    ])
    recorder, manager, stage = _make_recorder(
        tmp_path,
        output="reports/{{DUT}}_bug_summary.md",
    )

    template_data = recorder.get_template_data()

    assert template_data["TOTAL_BUGS"] == 1
    assert template_data["COMPLETED_BUGS"] == 0
    assert [
        item["bug_name"] for item in template_data["LIST_CURRENT_BUGS"]
    ] == ["confirmed"]
    assert template_data["LIST_CURRENT_BUGS"][0]["alias"] == [
        "BG-STATIC-002-CONFIRMED"
    ]

    record = _with_expected_bug_metadata(recorder, [{
        "bug_name": "confirmed",
        "CK": ["CK-CONFIRMED"],
        "desc": "The confirmed Bug is caused by an incorrect output assignment.",
        "locations": ["rtl/adder.sv:20-22"],
        "confidence": 0.80,
    }])
    passed, message = recorder.do_check(bug_list=record)

    assert passed is True
    assert message["bug_count"] == 1
    assert [item["bug_name"] for item in manager.data["BUG_RECORDS"]] == [
        "confirmed"
    ]

    stage.complete()

    markdown = Path(tmp_path, "reports/Adder_bug_summary.md").read_text(
        encoding="utf-8"
    )
    assert "Total Bugs: 1" in markdown
    assert "confirmed" in markdown
    assert "BG-STATIC-002-CONFIRMED" in markdown
    assert "dismissed" not in markdown
    assert "BG-STATIC-001-DISMISSED" not in markdown


def test_bug_recorder_completes_when_document_only_has_zero_confidence_bugs(tmp_path):
    _write_bug_doc(tmp_path, [("dismissed", 0, "CK-DISMISSED")])
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-DISMISSED", ["BG-dismissed-0"], "CK-STATIC"),
    ])
    recorder, manager, _stage = _make_recorder(tmp_path)

    assert recorder.get_template_data() == {
        "TOTAL_BUGS": 0,
        "COMPLETED_BUGS": 0,
        "LIST_CURRENT_BUGS": [],
    }

    passed, message = recorder.do_check(is_complete=True)

    assert passed is True
    assert message["bug_count"] == 0
    assert message["progress"] == "0/0"
    assert manager.data["BUG_RECORDS"] == []


@pytest.mark.parametrize(
    ("field", "mutate", "error_text"),
    [
        ("alias", lambda value: value[1:], ".alias does not exactly match"),
        ("alias", lambda value: value + ["BG-STATIC-EXTRA"], ".alias does not exactly match"),
        ("ref", lambda value: value[1:], ".ref does not exactly match"),
        ("ref", lambda value: value + ["other.md:1-2"], ".ref does not exactly match"),
    ],
)
def test_bug_recorder_rejects_missing_or_extra_aliases_and_refs(
    tmp_path,
    field,
    mutate,
    error_text,
):
    _write_bug_doc(tmp_path, [("bug-a", 90, "CK-A")])
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-A", ["BG-bug-a-90"], "CK-STATIC"),
    ])
    recorder, manager, _stage = _make_recorder(tmp_path)
    record = _with_expected_bug_metadata(recorder, [{
        "bug_name": "bug-a",
        "CK": ["CK-A"],
        "desc": "Bug A description and root cause.",
        "locations": ["rtl/adder.sv:10-12"],
        "confidence": 0.90,
    }])[0]
    record[field] = mutate(record[field])

    passed, message = recorder.do_check(bug_list=[record])

    assert passed is False
    assert error_text in message["error"]
    assert "BUG_RECORDS" not in manager.data


@pytest.mark.parametrize("field", ["alias", "ref"])
def test_bug_recorder_requires_alias_and_ref_keys(tmp_path, field):
    _write_bug_doc(tmp_path, [("bug-a", 90, "CK-A")])
    recorder, manager, _stage = _make_recorder(tmp_path)
    record = _with_expected_bug_metadata(recorder, [{
        "bug_name": "bug-a",
        "CK": ["CK-A"],
        "desc": "Bug A description and root cause.",
        "locations": ["rtl/adder.sv:10-12"],
        "confidence": 0.90,
    }])[0]
    record.pop(field)

    passed, message = recorder.do_check(bug_list=[record])

    assert passed is False
    assert f".{field}" in message["error"]
    assert "BUG_RECORDS" not in manager.data


def test_bug_recorder_generates_linked_markdown_summary_on_stage_complete(tmp_path):
    _write_bug_doc(tmp_path, [("overflow", 90, "CK-OVERFLOW")])
    _write_static_bug_doc(tmp_path, [
        ("BG-STATIC-001-OVERFLOW", ["BG-overflow-90"], "CK-STATIC"),
        ("BG-STATIC-002-OVERFLOW", ["BG-overflow-90"], "CK-STATIC"),
    ])
    recorder, manager, stage = _make_recorder(
        tmp_path,
        output="reports/{{DUT}}_bug_summary.md",
    )
    summary_path = Path(tmp_path, "reports/Adder_bug_summary.md")
    record = _with_expected_bug_metadata(recorder, [{
        "bug_name": "overflow",
        "CK": ["CK-OVERFLOW"],
        "desc": "The result is truncated | the root cause is an undersized signal.\nCarry is lost.",
        "locations": ["rtl/adder.sv:10-12,20"],
        "confidence": 0.90,
        "severity": "high",
    }])

    passed, message = recorder.do_check(bug_list=record)

    assert passed is True
    assert message["bug_count"] == 1
    assert summary_path.exists() is False
    cached_payload = json.loads(json.dumps(manager.data["BUG_RECORDS"]))

    stage.complete()

    assert summary_path.exists() is True
    markdown = summary_path.read_text(encoding="utf-8")
    assert "# Adder Bug Summary" in markdown
    assert "Total Bugs: 1" in markdown
    assert "| Name | Severity | Alias | CK | Analysis | Locations | Confidence | Ref |" in markdown
    assert "| overflow | high |" in markdown
    assert "BG-STATIC-001-OVERFLOW" in markdown
    assert "BG-STATIC-002-OVERFLOW" in markdown
    assert "FG-GROUP/FC-FUNCTION/CK-OVERFLOW" in markdown
    assert "truncated \\| the root cause" in markdown
    assert "signal.<br>Carry is lost." in markdown
    assert "[rtl/adder.sv:10-12](../rtl/adder.sv#L10-L12)" in markdown
    assert "[rtl/adder.sv:20](../rtl/adder.sv#L20)" in markdown
    assert (
        "[Adder_static_bug_analysis.md:8-10]"
        "(../Adder_static_bug_analysis.md#L8-L10)"
    ) in markdown
    assert (
        "[Adder_static_bug_analysis.md:11-13]"
        "(../Adder_static_bug_analysis.md#L11-L13)"
    ) in markdown
    assert (
        "[Adder_bug_analysis.md:8-9](../Adder_bug_analysis.md#L8-L9)"
    ) in markdown
    assert manager.data["BUG_RECORDS"] == cached_payload


@pytest.mark.parametrize("output", [None, "", "   "])
def test_bug_recorder_skips_markdown_summary_for_empty_output(tmp_path, output):
    recorder, manager, stage = _make_recorder(tmp_path, output=output)

    passed, _message = recorder.do_check(bug_list=[])
    stage.complete()

    assert passed is True
    assert recorder.type_handler.persist_on_stage_complete is False
    assert manager.data["BUG_RECORDS"] == []
    assert list(Path(tmp_path).glob("*bug_summary.md")) == []


class _CustomRecordType(RecordType):
    record_type = "metric"

    def record(self, current_payload, is_complete=False, value=None, **kwargs):
        if value is None and current_payload is None:
            return False, current_payload, {"error": "value is required"}
        payload = current_payload if value is None else {"value": value, "final": is_complete}
        return True, payload, {"message": "metric recorded"}


class _InvalidContractRecordType(RecordType):
    record_type = "invalid"

    def record(self, current_payload, is_complete=False, **kwargs):
        return True, current_payload


def test_recorder_supports_custom_record_type_classes(tmp_path):
    recorder, manager, _stage = _make_recorder(
        tmp_path,
        recorder_type=_CustomRecordType,
        data_key="METRICS",
    )

    passed, _message = recorder.do_check(value=42)

    assert passed is True
    assert recorder.record_type == "metric"
    assert manager.data["METRICS"] == {"value": 42, "final": False}


def test_recorder_validates_custom_record_type_contract(tmp_path):
    recorder, manager, _stage = _make_recorder(
        tmp_path,
        recorder_type=_InvalidContractRecordType,
        data_key="INVALID",
    )

    passed, message = recorder.do_check()

    assert passed is False
    assert "must return (passed, payload, message)" in message["error"]
    assert "INVALID" not in manager.data


def test_recorder_supports_exported_and_fully_qualified_custom_type_names(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(checkers, "CustomMetricRecordType", _CustomRecordType, raising=False)

    short_name_recorder, _manager, _stage = _make_recorder(
        tmp_path,
        recorder_type="CustomMetricRecordType",
    )
    qualified_recorder, _manager, _stage = _make_recorder(
        tmp_path,
        recorder_type=f"{__name__}._CustomRecordType",
    )

    assert short_name_recorder.record_type == "metric"
    assert qualified_recorder.record_type == "metric"


def test_recorder_is_exported_for_stage_configuration():
    assert import_class_from_str("Recorder", checkers) is Recorder


def test_recorder_registers_completion_callback_regardless_of_setter_order(tmp_path):
    stage = _FakeStage()
    manager = _FakeStageManager(stage)
    recorder = Recorder(type="bug").set_workspace(str(tmp_path))

    recorder.set_stage_manager(manager)
    assert stage.callbacks == []

    recorder.set_stage(stage)
    assert stage.callbacks == [recorder._sync_to_masters]


def test_recorder_reports_versioned_envelope_only_after_stage_complete(tmp_path):
    master_client = _FakeMasterClient()
    recorder, manager, stage = _make_recorder(
        tmp_path,
        master_clients={"http://master:8800": master_client},
    )
    passed, _message = recorder.do_check(bug_list=[])

    assert passed is True
    assert master_client.reports == []

    stage.complete()

    assert len(master_client.reports) == 1
    report = master_client.reports[0]
    assert report["schema_version"] == 1
    assert report["record_type"] == "bug"
    assert report["data_key"] == "BUG_RECORDS"
    assert report["payload"] == manager.data["BUG_RECORDS"]
    assert report["source"] == {
        "dut_name": "Adder",
        "workspace": str(tmp_path),
        "stage_name": "bug_summary",
        "stage_index": 0,
    }


def test_recorder_continues_reporting_after_one_master_client_fails(tmp_path):
    working_client = _FakeMasterClient()
    recorder, _manager, stage = _make_recorder(
        tmp_path,
        master_clients={
            "http://failed-master:8800": _FailingMasterClient(),
            "http://working-master:8800": working_client,
        },
    )
    passed, _message = recorder.do_check(bug_list=[])

    assert passed is True
    with patch("ucagent.checkers.recorder.info") as info_log, patch(
        "ucagent.checkers.recorder.warning"
    ) as warning_log:
        stage.complete()
    assert len(working_client.reports) == 1
    info_messages = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
    warning_messages = "\n".join(str(call.args[0]) for call in warning_log.call_args_list)
    assert "starting Master synchronization" in info_messages
    assert "sending type 'bug' records" in info_messages
    assert "synchronized type 'bug' records to Master 'http://working-master:8800' successfully" in info_messages
    assert "failed to synchronize type 'bug' records to Master 'http://failed-master:8800'" in warning_messages
    assert "configured=2, attempted=2, succeeded=1, failed=1, skipped=0" in warning_messages


def test_recorder_logs_skipped_master_clients(tmp_path):
    recorder, _manager, stage = _make_recorder(
        tmp_path,
        master_clients={
            "http://stopped-master:8800": _StoppedMasterClient(),
            "http://unsupported-master:8800": _UnsupportedMasterClient(),
        },
    )
    passed, _message = recorder.do_check(bug_list=[])

    assert passed is True
    with patch("ucagent.checkers.recorder.info") as info_log, patch(
        "ucagent.checkers.recorder.warning"
    ) as warning_log:
        stage.complete()

    info_messages = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
    warning_messages = "\n".join(str(call.args[0]) for call in warning_log.call_args_list)
    assert "starting Master synchronization" in info_messages
    assert "client is not running" in warning_messages
    assert "does not support record reports" in warning_messages
    assert "configured=2, attempted=0, succeeded=0, failed=0, skipped=2" in warning_messages


def test_recorder_logs_when_no_master_is_configured(tmp_path):
    recorder, _manager, stage = _make_recorder(tmp_path)
    passed, _message = recorder.do_check(bug_list=[])

    assert passed is True
    with patch("ucagent.checkers.recorder.info") as info_log:
        stage.complete()

    info_messages = "\n".join(str(call.args[0]) for call in info_log.call_args_list)
    assert "skipped Master synchronization" in info_messages
    assert "no Master clients are configured" in info_messages


def test_recorder_logs_when_stage_completion_aborts_master_sync(tmp_path):
    master_client = _FakeMasterClient()
    recorder, _manager, stage = _make_recorder(
        tmp_path,
        recorder_type="launch",
        data_key="NEXT_TASKS",
        master_clients={"http://master:8800": master_client},
        task_list=[{"task_name": "next"}],
    )
    passed, _message = recorder.do_check()

    assert passed is True
    with patch.object(
        recorder.type_handler,
        "on_stage_complete",
        side_effect=RuntimeError("cannot build payload"),
    ), patch("ucagent.checkers.recorder.warning") as warning_log:
        stage.complete()

    warning_messages = "\n".join(str(call.args[0]) for call in warning_log.call_args_list)
    assert "Master synchronization was aborted" in warning_messages
    assert "cannot build payload" in warning_messages
    assert master_client.reports == []


def test_launch_recorder_only_persists_configured_payload_on_stage_complete(tmp_path):
    master_client = _FakeMasterClient()
    task_list = [
        {
            "task_name": "lint-first",
            "selected_module": "Adder",
            "launch_mode": "process",
            "custom": {"command": ["lint", "--strict"]},
        },
        {
            "task_name": "verify-second",
            "selected_module": "Adder",
            "launch_mode": "docker",
            "custom": ["unvalidated", 42],
        },
    ]
    recorder, manager, stage = _make_recorder(
        tmp_path,
        recorder_type="launch",
        data_key="NEXT_TASKS",
        master_clients={"http://master:8800": master_client},
        task_list=task_list,
        stop_on_failure=False,
    )

    passed, message = recorder.do_check(
        task_list=[{"task_name": "ignored-runtime-task"}],
        bug_list=[{"bug_name": "ignored-runtime-bug"}],
    )

    assert passed is True
    assert message["task_count"] == 2
    assert "NEXT_TASKS" not in manager.data
    assert master_client.reports == []

    passed, _message = recorder.do_check(
        is_complete=True,
        task_list=[{"task_name": "also-ignored"}],
    )
    assert passed is True
    assert "NEXT_TASKS" not in manager.data

    stage.complete()
    assert manager.data["NEXT_TASKS"] == {
        "task_list": task_list,
        "stop_on_failure": False,
    }
    assert master_client.reports[0]["record_type"] == "launch"
    assert master_client.reports[0]["payload"] == manager.data["NEXT_TASKS"]


def test_launch_recorder_does_not_validate_configured_task_items(tmp_path):
    task_list = [
        {"custom_task": {"priority": 1}},
        "opaque-task-reference",
        42,
        None,
    ]
    recorder, manager, stage = _make_recorder(
        tmp_path,
        recorder_type="launch",
        data_key="NEXT_TASKS",
        task_list=task_list,
    )

    passed, message = recorder.do_check()

    assert passed is True
    assert message["task_count"] == 4
    assert "NEXT_TASKS" not in manager.data

    stage.complete()
    assert manager.data["NEXT_TASKS"] == {"task_list": task_list}


def test_configured_launch_payload_ignores_shared_checker_arguments(tmp_path):
    task_list = [{
        "task_name": "Adder-vibe",
        "dut_name": "Adder",
        "selected_module": "Adder",
        "config": "vibe.yaml",
    }]
    recorder, manager, stage = _make_recorder(
        tmp_path,
        recorder_type="launch",
        data_key="NEXT_TASKS",
        task_list=task_list,
        stop_on_failure=False,
    )

    passed, message = recorder.do_check(
        bug_list=[{"bug_name": "shared-stage-argument"}],
    )

    assert passed is True
    assert message["task_count"] == 1
    assert "NEXT_TASKS" not in manager.data

    stage.complete()
    assert manager.data["NEXT_TASKS"] == {
        "task_list": task_list,
        "stop_on_failure": False,
    }
    assert "bug_list" not in manager.data["NEXT_TASKS"]


def test_bug_recorder_exposes_batch_template_data_before_first_check(tmp_path):
    _write_bug_doc(tmp_path, [
        ("bug-a", 90, "CK-A"),
        ("bug-b", 80, "CK-B"),
        ("bug-c", 70, "CK-C"),
    ])
    recorder, manager, _stage = _make_recorder(
        tmp_path,
        type_args={"batch_size": 2},
    )

    template_data = recorder.get_template_data()

    assert template_data["TOTAL_BUGS"] == 3
    assert template_data["COMPLETED_BUGS"] == 0
    assert [
        item["bug_name"] for item in template_data["LIST_CURRENT_BUGS"]
    ] == ["bug-a", "bug-b"]

    assert template_data["LIST_CURRENT_BUGS"][0]["document_blocks"]
    assert "BUG_RECORDS" not in manager.data
    assert recorder.filter_vstage_description(
        "Bug records [{COMPLETED_BUGS}/{TOTAL_BUGS}]"
    ) == "Bug records [0/3]"
    rendered_task = recorder.filter_vstage_task([
        {"Current bugs": "{LIST_CURRENT_BUGS}"},
    ])
    assert [
        item["bug_name"] for item in rendered_task[0]["Current bugs"]
    ] == ["bug-a", "bug-b"]

    passed, message = recorder.do_check(bug_list=_with_expected_bug_metadata(recorder, [
        {
            "bug_name": "bug-a",
            "CK": ["CK-A"],
            "desc": "Bug A is caused by an incorrect result-width declaration.",
            "locations": ["rtl/adder.sv:10-11"],
            "confidence": 0.90,
        },
        {
            "bug_name": "bug-b",
            "CK": ["CK-B"],
            "desc": "Bug B is caused by missing carry propagation.",
            "locations": ["rtl/adder.sv:20-21"],
            "confidence": 0.80,
        },
    ]))

    assert passed is False
    assert message["progress"] == "2/3"
    template_data = recorder.get_template_data()
    assert template_data["COMPLETED_BUGS"] == 2
    assert [
        item["bug_name"] for item in template_data["LIST_CURRENT_BUGS"]
    ] == ["bug-c"]
    assert recorder.filter_vstage_description(
        "Bug records [{COMPLETED_BUGS}/{TOTAL_BUGS}]"
    ) == "Bug records [2/3]"


def test_bug_recorder_template_data_is_unknown_until_stage_on_init(tmp_path):
    _write_bug_doc(tmp_path, [
        ("bug-a", 90, "CK-A"),
        ("bug-b", 80, "CK-B"),
    ])
    recorder, _manager, _stage = _make_recorder(tmp_path, initialize=False)
    load_expected_bugs = Mock(wraps=recorder.type_handler._load_expected_bugs)
    recorder.type_handler._load_expected_bugs = load_expected_bugs

    template_data = recorder.get_template_data()

    assert template_data == {
        "TOTAL_BUGS": "-",
        "COMPLETED_BUGS": "-",
        "LIST_CURRENT_BUGS": [],
    }
    assert recorder.filter_vstage_description(
        "Bug records [{COMPLETED_BUGS}/{TOTAL_BUGS}]"
    ) == "Bug records [-/-]"
    load_expected_bugs.assert_not_called()

    recorder.on_init()
    template_data = recorder.get_template_data()

    load_expected_bugs.assert_called_once_with()
    assert template_data["TOTAL_BUGS"] == 2
    assert template_data["COMPLETED_BUGS"] == 0
    assert [
        item["bug_name"] for item in template_data["LIST_CURRENT_BUGS"]
    ] == ["bug-a", "bug-b"]

    passed, message = recorder.do_check()

    assert passed is False
    assert message["progress"] == "0/2"
    recorder.get_template_data()
    load_expected_bugs.assert_called_once_with()


def test_default_workflow_ends_with_record_and_report_bugs_stage():
    config = load_yaml_with_env_vars(
        os.path.join(repo_root, "ucagent/lang/zh/config/default.yaml")
    )

    stage = config["stage"][-1]
    assert stage["name"] == "record_and_report_bugs"
    assert stage["desc"] == "记录并同步所有已确定的Bug[{COMPLETED_BUGS}/{TOTAL_BUGS}]"
    task_text = json.dumps(stage["task"], ensure_ascii=False)
    assert "vibe" not in task_text.lower()
    assert "launch" not in task_text.lower()
    assert "master" not in task_text.lower()
    for field in (
        "bug_name",
        "alias",
        "CK",
        "desc",
        "locations",
        "severity",
        "confidence",
        "ref",
    ):
        assert field in task_text
    assert "lowest、low、medium、high、highest" in task_text
    assert "severity：必填" in task_text
    assert "Check(stage_args=" in task_text
    assert "bug_list" in task_text
    assert "完整stage_args JSON对象作为字符串" in task_text
    assert "字符串fallback示例" in task_text
    assert "Complete(stage_args=" in task_text
    assert "Check(bug_list=" not in task_text
    assert "FG-ARITHMETIC/FC-ADD/CK-CIN-OVERFLOW" in task_text
    assert "{LIST_CURRENT_BUGS}" in task_text
    assert "{COMPLETED_BUGS}/{TOTAL_BUGS}" in task_text
    assert "置信度为0的Bug" in task_text
    assert "调用Check()获取当前批次" not in task_text
    assert "不得删除仍由正确测试稳定复现的动态Bug" in task_text
    assert [checker["clss"] for checker in stage["checker"]] == [
        "UnityChipCheckerTestCase",
        "UnityChipCheckerWaveformBugAnalysis",
        "Recorder",
    ]
    recorder_checkers = [
        checker for checker in stage["checker"] if checker["clss"] == "Recorder"
    ]
    assert [checker["args"]["type"] for checker in recorder_checkers] == ["bug"]
    waveform_checker = next(
        checker
        for checker in stage["checker"]
        if checker["clss"] == "UnityChipCheckerWaveformBugAnalysis"
    )
    recorder_checker = recorder_checkers[0]
    assert waveform_checker["args"]["bug_file"] == (
        "{OUT}/{DUT}_bug_analysis.md"
    )
    assert waveform_checker["args"]["test_dir"] == "{OUT}/tests"
    assert recorder_checker["args"]["bug_file"] == "{OUT}/{DUT}_bug_analysis.md"
    assert recorder_checker["args"]["static_bug_file"] == (
        "{OUT}/{DUT}_static_bug_analysis.md"
    )
    assert recorder_checker["args"]["output"] == (
        "{OUT}/{DUT}_bug_summary.md"
    )
    assert "output_files" not in stage
    assert "bug_files" not in recorder_checker["args"]
    assert all("Complete(task_list" not in instruction for instruction in stage["task"])


def test_master_record_api_accepts_generic_payload_and_logs_summary(tmp_path):
    server = PdbMasterApiServer(workspace=str(tmp_path))
    client = TestClient(server._app)
    report = {
        "schema_version": 1,
        "agent_id": "agent-1",
        "record_type": "custom.metrics",
        "data_key": "METRICS",
        "payload": {"latency": 12, "throughput": 4},
        "source": {"stage_name": "summary"},
    }

    with patch("ucagent.server.api_master._master_log") as master_log:
        response = client.post("/api/records", json=report)

    assert response.status_code == 200
    assert response.json()["accepted"] == {
        "agent_id": "agent-1",
        "record_type": "custom.metrics",
        "data_key": "METRICS",
        "item_count": 2,
        "schema_version": 1,
    }
    log_message = master_log.call_args.args[0]
    assert "agent='agent-1'" in log_message
    assert "type='custom.metrics'" in log_message
    assert "stage='summary'" in log_message


def test_master_record_api_logs_launch_task_order(tmp_path):
    server = PdbMasterApiServer(workspace=str(tmp_path))
    client = TestClient(server._app)
    report = {
        "schema_version": 1,
        "agent_id": "agent-1",
        "record_type": "launch",
        "data_key": "NEXT_TASKS",
        "payload": {
            "task_list": [
                {"task_name": "first"},
                {"selected_module": "second"},
            ],
            "stop_on_failure": True,
        },
        "source": {"stage_name": "plan-next"},
    }

    with patch("ucagent.server.api_master._master_log") as master_log:
        response = client.post("/api/records", json=report)

    assert response.status_code == 200
    assert response.json()["accepted"]["item_count"] == 2
    log_message = master_log.call_args.args[0]
    assert 'launch_order=["first", "second"]' in log_message


def test_master_record_api_validates_generic_envelope(tmp_path):
    server = PdbMasterApiServer(workspace=str(tmp_path))
    client = TestClient(server._app)

    response = client.post("/api/records", json={
        "agent_id": "agent-1",
        "record_type": "bug",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "'payload' is required"


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("source", [], "'source' must be an object"),
        ("schema_version", True, "'schema_version' must be an integer"),
        ("data_key", [], "'data_key' must be a string"),
    ],
)
def test_master_record_api_rejects_invalid_envelope_field_types(
    tmp_path, field, value, detail
):
    server = PdbMasterApiServer(workspace=str(tmp_path))
    client = TestClient(server._app)
    report = {
        "schema_version": 1,
        "agent_id": "agent-1",
        "record_type": "bug",
        "data_key": "BUG_RECORDS",
        "payload": [],
        "source": {},
    }
    report[field] = value

    response = client.post("/api/records", json=report)

    assert response.status_code == 400
    assert response.json()["detail"] == detail


def test_master_client_reports_records_with_agent_identity():
    pdb = SimpleNamespace()
    client = PdbMasterClient(
        pdb,
        master_url="http://master:8800",
        agent_id="agent-7",
        access_key="secret",
    )
    client._running = True
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"status": "ok"}

    with patch("requests.post", return_value=response) as post:
        passed, message = client.report_records({
            "schema_version": 1,
            "record_type": "bug",
            "data_key": "BUG_RECORDS",
            "payload": [],
            "source": {},
        })

    assert passed is True
    assert "Reported type 'bug' records" in message
    assert post.call_args.args[0] == "http://master:8800/api/records"
    assert post.call_args.kwargs["json"]["agent_id"] == "agent-7"
    assert post.call_args.kwargs["headers"] == {"X-Access-Key": "secret"}


def test_master_client_rejects_non_json_record_report():
    client = PdbMasterClient(
        SimpleNamespace(),
        master_url="http://master:8800",
        agent_id="agent-7",
    )
    client._running = True

    passed, message = client.report_records({"payload": {"not-json"}})

    assert passed is False
    assert "JSON serializable" in message
