#!/usr/bin/env python3
"""Dynamic/static Bug namespace boundaries in workflow skill scripts."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ucagent.util.markdown import markdown_heading_spacing_errors
from ucagent.util.config import Config, save_current_test_report, save_runtime_config


REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPTS = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/dynamic-bug-recording/scripts/record_dynamic_bug.py",
)
LINK_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-validation/scripts/linkbug.py"
)
STATIC_RECORD_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/static-bug-analysis/scripts/record_static_bug.py"
)
FUNCTIONS_UPDATE_SCRIPT = (
    REPO_ROOT
    / "ucagent/lang/zh/skills/unitytest/functions-and-checks/scripts/update.py"
)


def test_bug_record_scripts_have_distinct_owners_and_names():
    assert RECORD_SCRIPTS[0].is_file()
    dynamic_script = RECORD_SCRIPTS[0].read_text(encoding="utf-8")
    assert not re.search(r"[\u4e00-\u9fff]", dynamic_script)
    assert "load_runtime_config(os.getcwd())" in dynamic_script
    assert 'runtime_config["test_output_dir"]' in dynamic_script
    assert "DYNAMIC_BUG_DOCUMENT_PATH.format" in dynamic_script
    assert 'os.environ.get("DUT")' not in dynamic_script
    assert 'os.environ.get("OUT")' not in dynamic_script
    assert STATIC_RECORD_SCRIPT.is_file()
    static_script = STATIC_RECORD_SCRIPT.read_text(encoding="utf-8")
    assert "load_runtime_config(os.getcwd())" in static_script
    assert "STATIC_BUG_DOCUMENT_PATH.format" in static_script
    assert 'os.environ.get("DUT")' not in static_script
    assert 'os.environ.get("OUT")' not in static_script
    for script_path in (FUNCTIONS_UPDATE_SCRIPT, LINK_SCRIPT):
        script = script_path.read_text(encoding="utf-8")
        assert "load_runtime_config(os.getcwd())" in script
        assert 'os.environ.get("DUT")' not in script
        assert 'os.environ.get("OUT")' not in script
    link_script = LINK_SCRIPT.read_text(encoding="utf-8")
    assert "DYNAMIC_BUG_DOCUMENT_PATH.format" in link_script
    assert "STATIC_BUG_DOCUMENT_PATH.format" in link_script
    assert not list(
        (REPO_ROOT / "ucagent/lang/zh/skills/unitytest").glob(
            "*/scripts/recordbug.py"
        )
    )


def _load_script(path: Path):
    spec = importlib.util.spec_from_file_location(
        f"test_{path.parent.parent.name}_{path.stem}", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_runtime_contract(
    workspace,
    report=None,
    *,
    dut="Adder",
    out="unity_test",
    test_output_dir="unity_test/tests",
):
    cfg = Config(
        {
            "runtime_options": {
                "need_ref_model": False,
                "mock_components_enabled": False,
            },
            "tools": {"RunTestCases": {"test_dir": test_output_dir}},
        }
    )
    cfg._temp_cfg = {"DUT": dut, "OUT": out}
    save_runtime_config(str(workspace), cfg)
    if report is not None:
        save_current_test_report(
            str(workspace), report, context={"stage_name": "test-stage"}
        )


def _insert_content(module, lines, fg, fc, ck, bg, tc, bd):
    return module.insert_content(
        lines,
        fg,
        fc,
        ck,
        bg,
        tc,
        bd,
        "算术功能",
        "结果计算",
        "精确输出",
        "结果不匹配",
    )


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_script_requires_current_stage_report(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    _write_runtime_contract(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="Run the current stage's real test"):
        module.resolve_fg_fc_ck_list_by_tc(
            "TC-unity_test/tests/test_demo.py::test_failure",
            "unity_test",
            "unity_test/tests",
        )


@pytest.mark.parametrize(
    ("bug_tag", "expected_root"),
    (
        ("BG-RESULT-WIDTH-90", "ROOT-RESULT-WIDTH"),
        ("BG-FIX-90", "ROOT-BUG-FIX"),
        ("BG-SOURCE-EVIDENCE-90", "ROOT-BUG-SOURCE-EVIDENCE"),
    ),
)
def test_dynamic_bug_root_tag_avoids_reserved_control_markers(
    bug_tag, expected_root
):
    module = _load_script(RECORD_SCRIPTS[0])

    assert module.root_cause_tag_for_bg(bug_tag) == expected_root


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_static_tag(script_path):
    module = _load_script(script_path)

    with pytest.raises(ValueError, match=r"cannot use the BG-STATIC-\* namespace"):
        module.validate_dynamic_bg_tag("BG-STATIC-DIV-INF-BY-NUM-95")
    with pytest.raises(ValueError, match="confidence must be greater than 0"):
        module.validate_dynamic_bg_tag("BG-DIV-INF-BY-NUM-0")

    module.validate_dynamic_bg_tag("BG-DIV-INF-BY-NUM-95")

    with pytest.raises(ValueError, match="must describe the actual item"):
        module.normalize_visible_title("功能组", "FG-ARITHMETIC")
    with pytest.raises(ValueError, match="cannot contain angle-bracket tags"):
        module.normalize_visible_title("算术功能 <FG-ARITHMETIC>", "FG-ARITHMETIC")
    with pytest.raises(ValueError, match="replace bracketed scaffold text"):
        module.normalize_visible_title("[功能组具体名称]", "FG-ARITHMETIC")


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_strips_only_report_line_range(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    report = {
        "failed_test_case_with_check_point_list": {
            "unity_test/tests/test_adder.py:12-18::test_overflow": [
                "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"
            ]
        }
    }
    _write_runtime_contract(tmp_path, report)
    monkeypatch.chdir(tmp_path)

    assert module.resolve_fg_fc_ck_list_by_tc(
        "TC-unity_test/tests/test_adder.py::test_overflow",
        "unity_test",
        "unity_test/tests",
    ) == [
        ("FG-ARITHMETIC", "FC-ADD", "CK-OVERFLOW")
    ]


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_short_path_with_report_candidate(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    _write_runtime_contract(
        tmp_path,
        {
            "failed_test_case_with_check_point_list": {
                "unity_test/tests/test_adder.py:12-18::test_overflow": [
                    "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"
                ]
            }
        },
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as error:
        module.resolve_fg_fc_ck_list_by_tc(
            "TC-tests/test_adder.py::test_overflow",
            "unity_test",
            "unity_test/tests",
        )

    message = str(error.value)
    assert "no exact FG/FC/CK report mapping" in message
    assert "unity_test/tests/test_adder.py::test_overflow" in message
    assert (
        "Configured TC output directory from .ucagent/runtime_config.json: "
        "'unity_test/tests'"
    ) in message
    assert "not equivalent identities" in message
    assert "configured directory unchanged" in message


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_node_outside_configured_output_dir(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    report_key = (
        f"{out_dir.as_posix()}/tests/test_adder.py:20-30"
        "::TestAdder::test_overflow"
    )
    report = {
        "failed_test_case_with_check_point_list": {
            report_key: ["FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"]
        }
    }
    _write_runtime_contract(tmp_path, report)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError) as error:
        module.resolve_fg_fc_ck_list_by_tc(
            f"TC-{out_dir.as_posix()}/tests/test_adder.py::TestAdder::test_overflow",
            out_dir.as_posix(),
            "unity_test/tests",
        )

    assert "TC file path must start with 'unity_test/tests/'" in str(error.value)


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_resolves_visible_source_titles(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    out_dir = tmp_path / "unity_test"
    tests_dir = out_dir / "tests"
    tests_dir.mkdir(parents=True)
    function_file = out_dir / "Adder_functions_and_checks.md"
    function_file.write_text(
        """## Functions

### 算术功能
<FG-ARITHMETIC>

#### 加法结果
<FC-ADD>

- <CK-OVERFLOW> 进位输出：验证进位位
""",
        encoding="utf-8",
    )
    (tests_dir / "test_adder.py").write_text(
        'def test_overflow(env):\n    """进位输入产生进位"""\n    pass\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert module.resolve_checkpoint_titles(
        function_file, "FG-ARITHMETIC", "FC-ADD", "CK-OVERFLOW"
    ) == ("算术功能", "加法结果", "进位输出")
    assert module.resolve_test_title(
        "TC-unity_test/tests/test_adder.py::test_overflow"
    ) == "进位输入产生进位"

    lines = module.make_bug_analysis_document("Adder").splitlines(keepends=True)
    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "完整和进位丢失",
        "算术功能",
        "加法结果",
        "进位输出",
        "进位输入产生进位",
    )
    document = "".join(lines)
    assert "### 算术功能 <FG-ARITHMETIC>" in document
    assert "#### 加法结果 <FC-ADD>" in document
    assert "##### 进位输出 <CK-OVERFLOW>" in document
    assert "###### 完整和进位丢失（98%） <BG-CIN-OVERFLOW-98>" in document
    assert "- 进位输入产生进位 <TC-tests/test_adder.py::test_overflow>" in document


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_main_writes_chinese_titles_from_runtime_sources(
    script_path, tmp_path, monkeypatch
):
    module = _load_script(script_path)
    runtime_dir = tmp_path / ".ucagent"
    runtime_dir.mkdir()
    (runtime_dir / "runtime_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Adder",
                "OUT": "unity_test",
                "test_output_dir": "custom_tc",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "unity_test"
    tests_dir = tmp_path / "custom_tc"
    out_dir.mkdir()
    tests_dir.mkdir(parents=True)
    save_current_test_report(
        str(tmp_path),
        {
            "failed_test_case_with_check_point_list": {
                "custom_tc/test_adder.py:1-4::test_overflow": [
                    "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"
                ]
            }
        },
        context={"stage_name": "basic_api_functional_test"},
    )
    (out_dir / "Adder_functions_and_checks.md").write_text(
        "### 算术功能\n<FG-ARITHMETIC>\n\n"
        "#### 加法结果\n<FC-ADD>\n\n"
        "- <CK-OVERFLOW> 进位输出：验证进位位\n",
        encoding="utf-8",
    )
    (tests_dir / "test_adder.py").write_text(
        'def test_overflow(env):\n    """进位输入产生进位"""\n    pass\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong_output")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "-MODE",
            "bug",
            "-BG",
            "BG-CARRY-DROPPED-95",
            "-TC",
            "TC-custom_tc/test_adder.py::test_overflow",
            "-BD",
            "完整和进位丢失",
            "-CHECKPOINT",
            "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW",
            "-ROOT-TAG",
            "ROOT-CARRY-DROPPED",
            "-ROOT-TITLE",
            "进位位宽不足",
            "-OVERVIEW",
            "加法结果未保留完整进位。",
            "-SYMPTOMS",
            "最大输入产生错误的低位结果。",
            "-TRIGGER",
            "两个最大操作数相加时稳定触发。",
        ],
    )

    module.main()

    document = (out_dir / "Adder_bug_analysis.md").read_text(encoding="utf-8")
    assert "### 算术功能 <FG-ARITHMETIC>" in document
    assert "#### 加法结果 <FC-ADD>" in document
    assert "##### 进位输出 <CK-OVERFLOW>" in document
    assert "###### 完整和进位丢失（95%） <BG-CARRY-DROPPED-95>" in document
    assert (
        "- 进位输入产生进位 "
        "<TC-custom_tc/test_adder.py::test_overflow>"
    ) in document
    assert not (tmp_path / "wrong_output").exists()


def test_dynamic_bug_skill_script_completes_bg_and_root_without_manual_editing(
    tmp_path, monkeypatch
):
    module = _load_script(RECORD_SCRIPTS[0])
    _write_runtime_contract(
        tmp_path,
        {
            "failed_test_case_with_check_point_list": {
                "custom_tc/test_adder.py:1-4::test_overflow": [
                    "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"
                ]
            }
        },
        out="unity_test",
        test_output_dir="custom_tc",
    )
    (tmp_path / "unity_test").mkdir()
    (tmp_path / "unity_test/Adder_functions_and_checks.md").write_text(
        "### 算术功能\n<FG-ARITHMETIC>\n\n"
        "#### 加法结果\n<FC-ADD>\n\n"
        "- <CK-OVERFLOW> 进位输出：验证进位位\n",
        encoding="utf-8",
    )
    (tmp_path / "custom_tc").mkdir()
    (tmp_path / "custom_tc/test_adder.py").write_text(
        'def test_overflow(env):\n    """进位输入产生进位"""\n    pass\n',
        encoding="utf-8",
    )
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl/adder.v").write_text(
        "module adder;\nassign result = a + b;\nendmodule\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(RECORD_SCRIPTS[0]),
            "-MODE",
            "bug",
            "-BG",
            "BG-CARRY-DROPPED-95",
            "-TC",
            "TC-custom_tc/test_adder.py::test_overflow",
            "-BD",
            "进位结果丢失",
            "-CHECKPOINT",
            "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW",
            "-ROOT-TAG",
            "ROOT-ADDER-CARRY",
            "-ROOT-TITLE",
            "加法进位宽度不足",
            "-OVERVIEW",
            "规格要求完整保留进位结果。",
            "-SYMPTOMS",
            "边界输入返回的结果缺少进位位。",
            "-TRIGGER",
            "当两个最大操作数同时输入时，错误稳定出现。",
        ],
    )
    module.main()

    target = tmp_path / "unity_test/Adder_bug_analysis.md"
    document = target.read_text(encoding="utf-8")
    assert document.count("<BG-CARRY-DROPPED-95>") == 1
    assert document.count("<TC-custom_tc/test_adder.py::test_overflow>") == 1
    assert "<BUG-TODO>" in document
    assert "规格要求完整保留进位结果。" in document
    assert "边界输入返回的结果缺少进位位。" in document
    assert "当两个最大操作数同时输入时，错误稳定出现。" in document
    assert "<CAUSE-REF-ROOT-ADDER-CARRY>" in document

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(RECORD_SCRIPTS[0]),
            "-MODE",
            "root",
            "-ROOT-TAG",
            "ROOT-ADDER-CARRY",
            "-ROOT-TITLE",
            "加法进位宽度不足",
            "-ANALYSIS",
            "中间结果在输出前丢失最高有效进位位。",
            "-CAUSAL-CHAIN",
            "输入被接受后，截断的中间值沿结果路径传播到失败断言。",
            "-FIX",
            "保留完整结果宽度并重新验证边界输入。",
            "-RETEST",
            "重跑所有关联 CK 和边界用例，并确认波形证据仍匹配。",
            "-SOURCE-LOCATION",
            "rtl/adder.v:1-3",
            "-FIRST-ERROR-LINE",
            "2",
            "-FIRST-ERROR-NOTE",
            "结果表达式宽度不足。",
            "-PROPAGATION-LINE",
            "2",
            "-PROPAGATION-NOTE",
            "截断值进入结果输出。",
            "-OBSERVABLE-LINE",
            "2",
            "-OBSERVABLE-NOTE",
            "失败断言观察到错误结果。",
        ],
    )
    module.main()
    completed = target.read_text(encoding="utf-8")
    assert completed.count("<ROOT-ADDER-CARRY>") == 1
    assert completed.count("<ROOT-CAUSE-ANALYSIS>") == 1
    assert completed.count("<BUG-TODO>") == 0
    assert "rtl/adder.v:1-3" in completed
    assert completed.count("<ROOT-SOURCE-FIRST-ERROR>") == 1
    assert completed.count("<ROOT-SOURCE-PROPAGATION>") == 1
    assert completed.count("<ROOT-SOURCE-OBSERVABLE>") == 1
    assert "中间结果在输出前丢失最高有效进位位。" in completed

    module.main()
    repeated = target.read_text(encoding="utf-8")
    assert repeated == completed


def test_dynamic_bug_skill_script_supports_blackbox_root_and_rejects_mixed_source_args():
    module = _load_script(RECORD_SCRIPTS[0])
    blackbox = SimpleNamespace(
        source_unavailable_reason="没有可访问的RTL源码。",
        source_location=None,
        first_error_line=None,
        first_error_note=None,
        propagation_line=None,
        propagation_note=None,
        observable_line=None,
        observable_note=None,
    )
    assert module._source_evidence_body(blackbox) == (
        "<ROOT-SOURCE-UNAVAILABLE>\n没有可访问的RTL源码。"
    )

    mixed = SimpleNamespace(
        source_unavailable_reason="没有可访问的RTL源码。",
        source_location=None,
        first_error_line=1,
        first_error_note="错误位置。",
        propagation_line=None,
        propagation_note=None,
        observable_line=None,
        observable_note=None,
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        module._source_evidence_body(mixed)

    invalid_range = SimpleNamespace(
        source_unavailable_reason=None,
        source_location="rtl/adder.v:3-1",
        first_error_line=1,
        first_error_note="错误位置。",
        propagation_line=1,
        propagation_note="传播位置。",
        observable_line=1,
        observable_note="观察位置。",
    )
    with pytest.raises(ValueError, match="start <= end"):
        module._source_evidence_body(invalid_range)

    with pytest.raises(ValueError, match="reserved Bug document marker"):
        module.normalize_field_text(
            "伪造 <ROOT-SOURCE-FIRST-ERROR> 标记。",
            "first-error note",
        )


def test_dynamic_bug_skill_script_rejects_arguments_from_the_other_mode(monkeypatch):
    module = _load_script(RECORD_SCRIPTS[0])
    monkeypatch.setattr(
        sys,
        "argv",
        [str(RECORD_SCRIPTS[0]), "-MODE", "bug", "-ANALYSIS", "root text"],
    )
    bug_args = module.parse_args()
    with pytest.raises(ValueError, match="bug mode does not accept root-only"):
        module._run_bug_operation({}, bug_args, "unused")

    monkeypatch.setattr(
        sys,
        "argv",
        [str(RECORD_SCRIPTS[0]), "-MODE", "root", "-BG", "BG-A-90"],
    )
    root_args = module.parse_args()
    with pytest.raises(ValueError, match="root mode does not accept bug-only"):
        module._run_root_operation({}, root_args, "unused")


def test_dynamic_bug_skill_script_moves_bg_root_relation_without_orphaning_old_root():
    module = _load_script(RECORD_SCRIPTS[0])
    lines = module.make_bug_analysis_document("Adder").splitlines(keepends=True)
    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-SECOND-90",
        "TC-tests/test_adder.py::test_second",
        "Second Bug.",
        "算术功能",
        "结果计算",
        "精确输出",
        "第二个结果不匹配",
        root_tag="ROOT-SECOND",
        root_title="第二个根因",
    )
    _insert_content(
        module,
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
    )
    module._remove_stale_root_relation(
        lines,
        "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "ROOT-NEW-CAUSE",
    )
    module.insert_content(
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
        "算术功能",
        "结果计算",
        "精确输出",
        "结果不匹配",
        root_tag="ROOT-NEW-CAUSE",
        root_title="新的根因",
    )
    module._update_bug_fields(
        lines,
        "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "更新后的溢出标题",
        {
            "overview": "完整结果被截断。",
            "symptoms": "边界结果错误。",
            "trigger": "溢出输入触发。",
        },
        "ROOT-NEW-CAUSE",
        "新的根因",
    )
    document = "".join(lines)
    assert "<ROOT-CIN-OVERFLOW>" not in document
    assert "<CAUSE-REF-ROOT-CIN-OVERFLOW>" not in document
    assert "<CAUSE-REF-ROOT-NEW-CAUSE>" in document
    assert "###### 更新后的溢出标题（98%） <BG-CIN-OVERFLOW-98>" in document
    assert "<RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-OVERFLOW/BG-CIN-OVERFLOW-98>" in document
    assert document.count("<ROOT-NEW-CAUSE>") == 1
    assert '<a id="root-cause-second"></a>' in document
    assert document.count("<ROOT-SECOND>") == 1
    assert "<RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-OVERFLOW/BG-SECOND-90>" in document


def test_dynamic_bug_skill_script_serializes_concurrent_process_updates(tmp_path):
    _write_runtime_contract(
        tmp_path,
        {
            "failed_test_case_with_check_point_list": {
                "unity_test/tests/test_adder.py:1-3::test_overflow": [
                    "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW"
                ]
            }
        },
        out="unity_test",
        test_output_dir="unity_test/tests",
    )
    out_dir = tmp_path / "unity_test"
    tests_dir = out_dir / "tests"
    out_dir.mkdir(exist_ok=True)
    tests_dir.mkdir(exist_ok=True)
    (out_dir / "Adder_functions_and_checks.md").write_text(
        "### 算术功能\n<FG-ARITHMETIC>\n\n"
        "#### 加法结果\n<FC-ADD>\n\n"
        "- <CK-OVERFLOW> 进位输出：验证进位位\n",
        encoding="utf-8",
    )
    (tests_dir / "test_adder.py").write_text(
        'def test_overflow(env):\n    """进位输入产生进位"""\n    pass\n',
        encoding="utf-8",
    )
    common_args = [
        "-TC",
        "TC-unity_test/tests/test_adder.py::test_overflow",
        "-BD",
        "进位结果丢失",
        "-CHECKPOINT",
        "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW",
        "-ROOT-TITLE",
        "进位根因",
        "-OVERVIEW",
        "结果被截断。",
        "-SYMPTOMS",
        "边界结果错误。",
        "-TRIGGER",
        "边界输入触发。",
    ]
    commands = [
        [
            sys.executable,
            str(RECORD_SCRIPTS[0]),
            "-MODE",
            "bug",
        ]
        + [
            "-BG",
            bg,
            "-ROOT-TAG",
            root,
        ]
        + common_args
        for bg, root in (
            ("BG-CONCURRENT-A-90", "ROOT-CONCURRENT-A"),
            ("BG-CONCURRENT-B-90", "ROOT-CONCURRENT-B"),
        )
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT)
    with subprocess.Popen(
        commands[0], cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as first, subprocess.Popen(
        commands[1], cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as second:
        first_output = first.communicate(timeout=30)[0]
        second_output = second.communicate(timeout=30)[0]
        assert first.returncode == 0, first_output
        assert second.returncode == 0, second_output
    document = (out_dir / "Adder_bug_analysis.md").read_text(encoding="utf-8")
    assert document.count("<BG-CONCURRENT-A-90>") == 1
    assert document.count("<BG-CONCURRENT-B-90>") == 1
    assert document.count("<ROOT-CONCURRENT-A>") == 1
    assert document.count("<ROOT-CONCURRENT-B>") == 1


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_generates_incomplete_analysis_scaffold(script_path):
    module = _load_script(script_path)
    initial_document = module.make_bug_analysis_document("Adder")
    rendered_template = (
        REPO_ROOT
        / "ucagent/lang/zh/template/unity_test/{{DUT}}_bug_analysis.md"
    ).read_text(encoding="utf-8").replace("{{DUT}}", "Adder")
    assert initial_document == rendered_template
    lines = initial_document.splitlines(keepends=True)

    _insert_content(
        module,
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow",
        "Overflow is not raised.",
    )

    document = "".join(lines)
    assert markdown_heading_spacing_errors(
        document, module.HEADING_COMPANION_MARKERS
    ) == []
    markers = (
        module.OVERVIEW_MARKER,
        "<BUG-SYMPTOMS>",
        "<BUG-TRIGGER>",
    )
    assert document.index("<BG-CIN-OVERFLOW-98>") < document.index(markers[0])
    assert [document.count(marker) for marker in markers] == [1] * len(markers)
    for marker in (
        "<ROOT-CAUSE-ANALYSIS>",
        "<ROOT-SOURCE-EVIDENCE>",
        "<ROOT-CAUSAL-CHAIN>",
        "<ROOT-FIX>",
        "<ROOT-RETEST>",
    ):
        assert document.count(marker) == 1
    assert "<CAUSE-REF-ROOT-CIN-OVERFLOW>" in document
    assert "<RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-OVERFLOW/BG-CIN-OVERFLOW-98>" in document
    assert "<BUG-ROOT-CAUSE>" not in document
    assert [document.index(marker) for marker in markers] == sorted(
        document.index(marker) for marker in markers
    )
    assert document.index("###### Bug 概述") < document.index(
        module.OVERVIEW_MARKER
    )
    assert document.count(module.TODO_MARKER) == 7
    assert "waveform_analysis:" not in document
    assert document.count("<WAVEFORM-REF>") == 1
    for heading in (
        "### 算术功能 <FG-ARITHMETIC>",
        "#### 结果计算 <FC-ADD>",
        "##### 精确输出 <CK-OVERFLOW>",
        "###### Overflow is not raised.（98%） <BG-CIN-OVERFLOW-98>",
        "- 结果不匹配 <TC-tests/test_adder.py::test_overflow>",
        "###### Bug 概述",
        "###### 现象与严重度",
        "###### 触发条件与影响",
            "#### 根因分析",
            "#### 源码证据",
            "#### 因果链",
            "#### 修复建议",
            "#### 风险与复验",
    ):
        assert heading in document
    assert document.index("<BG-CIN-OVERFLOW-98>") < document.index("</DYNAMIC-BUGS>")
    assert document.index("</DYNAMIC-BUGS>") < document.index("<WAVEFORM-EVIDENCE>")
    assert "replace with WaveInfo" not in document
    assert "填写严重度" not in document
    assert "插入带真实路径" not in document

    _insert_content(
        module,
        lines,
        "FG-ARITHMETIC",
        "FC-ADD",
        "CK-OVERFLOW",
        "BG-CIN-OVERFLOW-98",
        "TC-tests/test_adder.py::test_overflow_random",
        "Random overflow reproducer.",
    )
    document = "".join(lines)
    assert document.index(
        "<TC-tests/test_adder.py::test_overflow_random>"
    ) < document.index(module.OVERVIEW_MARKER)
    assert document.count("<WAVEFORM-REF>") == 2
    assert document.count("<WAVEFORM-VIEWER>") == 0


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_preserves_canonical_nested_order(script_path):
    module = _load_script(script_path)
    lines = module.make_bug_analysis_document("Adder").splitlines(keepends=True)
    entries = (
        ("FG-A", "FC-A", "CK-A", "BG-A-90", "TC-tests/test_a.py::test_a"),
        ("FG-A", "FC-A", "CK-A", "BG-A-90", "TC-tests/test_a.py::test_a_edge"),
        ("FG-B", "FC-B", "CK-B", "BG-B-90", "TC-tests/test_b.py::test_b"),
        ("FG-A", "FC-C", "CK-C", "BG-C-90", "TC-tests/test_c.py::test_c"),
        ("FG-A", "FC-A", "CK-D", "BG-D-90", "TC-tests/test_d.py::test_d"),
        ("FG-A", "FC-A", "CK-A", "BG-E-90", "TC-tests/test_e.py::test_e"),
    )
    for fg, fc, ck, bg, tc in entries:
        _insert_content(module, lines, fg, fc, ck, bg, tc, bg)

    document = "".join(lines)
    assert document.index("<FG-A>") < document.index("<FG-B>")
    assert document.index("<FC-A>") < document.index("<FC-C>") < document.index("<FG-B>")
    assert document.index("<CK-A>") < document.index("<CK-D>") < document.index("<FC-C>")
    assert document.index("<BG-A-90>") < document.index("<BG-E-90>") < document.index("<CK-D>")
    first_bg_end = document.index("<BG-E-90>")
    first_bg = document[document.index("<BG-A-90>") : first_bg_end]
    assert first_bg.count("<TC-") == 2
    assert first_bg.rindex("<TC-") < first_bg.index(module.OVERVIEW_MARKER)
    assert document.count("###### Bug 概述") == len({entry[3] for entry in entries})


@pytest.mark.parametrize("script_path", RECORD_SCRIPTS)
def test_dynamic_bug_record_script_rejects_unsupported_analysis_arguments(
    script_path, monkeypatch
):
    module = _load_script(script_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "-BG",
            "BG-CIN-OVERFLOW-98",
            "-TC",
            "TC-tests/test_adder.py::test_overflow",
            "-BD",
            "Overflow is not raised.",
            "-ROOT",
            "unsupported root cause argument",
        ],
    )

    with pytest.raises(SystemExit):
        module.parse_args()


def test_static_bug_link_script_requires_distinct_dynamic_target():
    module = _load_script(LINK_SCRIPT)

    with pytest.raises(ValueError, match="is a static Bug tag"):
        module.parse_link_targets("BG-STATIC-DIV-INF-BY-NUM-95")

    assert module.parse_link_targets("BG-DIV-INF-BY-NUM-95") == [
        "BG-DIV-INF-BY-NUM-95"
    ]


def test_static_bug_record_template_uses_markers_before_localizable_titles():
    module = _load_script(STATIC_RECORD_SCRIPT)
    document = module.static_bug_analysis_md_template.format(DUT="Adder")

    ordered_tokens = (
        module.STATIC_BUG_SUMMARY_MARKER,
        "## 一、潜在Bug汇总",
        module.STATIC_BUG_DETAILS_MARKER,
        "## 二、详细分析",
        module.STATIC_BUG_PROGRESS_MARKER,
        "## 三、批次分析进度",
    )
    assert [document.index(token) for token in ordered_tokens] == sorted(
        document.index(token) for token in ordered_tokens
    )
    assert markdown_heading_spacing_errors(document) == []


@pytest.mark.parametrize(
    "invalid_location",
    (
        "rtl/dut.v:10",
        "rtl/dut.v:L10-L10",
        "rtl/dut.v:14-10",
    ),
)
def test_static_bug_record_script_rejects_noncanonical_source_ranges(
    invalid_location,
):
    module = _load_script(STATIC_RECORD_SCRIPT)
    functions = {"FG-A": {"FC-A": {"CK-A": {}}}}

    passed, message = module.validate_hierarchy(
        "Demo",
        functions,
        "FG-A",
        "FC-A",
        "CK-A",
        "BG-STATIC-001-RESULT",
        invalid_location,
    )

    assert passed == 0
    assert "RunSkillScript" in message


@pytest.mark.parametrize("location", ("rtl/dut.v:10-10", "rtl/dut.v:10-14"))
def test_static_bug_record_script_accepts_explicit_source_ranges(location):
    module = _load_script(STATIC_RECORD_SCRIPT)
    functions = {"FG-A": {"FC-A": {"CK-A": {}}}}

    passed, message = module.validate_hierarchy(
        "Demo",
        functions,
        "FG-A",
        "FC-A",
        "CK-A",
        "BG-STATIC-001-RESULT",
        location,
    )

    assert passed == 1
    assert message is None


def test_static_bug_record_script_uses_resolved_runtime_config(
    tmp_path,
    monkeypatch,
):
    module = _load_script(STATIC_RECORD_SCRIPT)
    runtime_dir = tmp_path / ".ucagent"
    runtime_dir.mkdir()
    (runtime_dir / "runtime_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Demo",
                "OUT": "unity_test",
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "unity_test"
    out_dir.mkdir()
    (out_dir / "Demo_functions_and_checks.md").write_text(
        "<FG-A>\n<FC-A>\n<CK-A>\n",
        encoding="utf-8",
    )
    source = tmp_path / "rtl" / "dut.v"
    source.parent.mkdir()
    source.write_text("module dut;\nendmodule\n", encoding="utf-8")
    unreviewed = tmp_path / "Demo_RTL" / "unreviewed.v"
    unreviewed.parent.mkdir()
    unreviewed.write_text("module unreviewed;\nendmodule\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "project_root", str(tmp_path))
    monkeypatch.setattr(
        module,
        "get_function_dict_json_path",
        lambda dut: str(tmp_path / f"{dut}_functions_and_checks.json"),
    )
    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong_output")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(STATIC_RECORD_SCRIPT),
            "-FG",
            "FG-A",
            "-FGD",
            "Function A",
            "-FC",
            "FC-A",
            "-FCD",
            "Function C",
            "-CK",
            "CK-A",
            "-CKD",
            "Check A",
            "-BG",
            "BG-STATIC-001-RESULT",
            "-FILE",
            "rtl/dut.v:1-1",
            "-BD",
            "Result source candidate",
            "-CL",
            "High",
        ],
    )

    module.main()

    target = out_dir / "Demo_static_bug_analysis.md"
    assert target.is_file()
    document = target.read_text(encoding="utf-8")
    assert "# Demo RTL" in document
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        f'<file sha256="{source_digest}">rtl/dut.v</file>' in document
    )
    assert "unreviewed.v</file>" not in document
    assert markdown_heading_spacing_errors(document) == []
    assert not (tmp_path / "wrong_output").exists()


@pytest.mark.parametrize(
    ("script_path", "path_loader", "expected_name"),
    (
        (FUNCTIONS_UPDATE_SCRIPT, "load_doc_path", "Demo_functions_and_checks.md"),
        (LINK_SCRIPT, "get_target_md_path", "Demo_static_bug_analysis.md"),
        (LINK_SCRIPT, "get_bug_analysis_md_path", "Demo_bug_analysis.md"),
    ),
)
def test_skill_path_loaders_use_resolved_runtime_config(
    script_path,
    path_loader,
    expected_name,
    tmp_path,
    monkeypatch,
):
    module = _load_script(script_path)
    runtime_dir = tmp_path / ".ucagent"
    runtime_dir.mkdir()
    (runtime_dir / "runtime_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "DUT": "Demo",
                "OUT": "unity_test",
                "test_output_dir": "unity_test/tests",
                "ucagent_python_path": str(REPO_ROOT),
                "current_test_report": ".ucagent/current_test_report.json",
                "runtime_options": {
                    "need_ref_model": False,
                    "mock_components_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    expected = tmp_path / "unity_test" / expected_name
    expected.parent.mkdir()
    expected.write_text("canonical runtime target\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("DUT", "WrongDut")
    monkeypatch.setenv("OUT", "wrong_output")

    resolved = getattr(module, path_loader)()

    assert Path(resolved) == expected


def test_static_bug_link_script_does_not_accept_noncanonical_title_label():
    module = _load_script(LINK_SCRIPT)

    assert module.collect_bg_tags_from_bug_analysis(
        ["**Bug标签**: BG-DIV-INF-BY-NUM-95\n"]
    ) == set()


def test_static_bug_link_script_rejects_incomplete_dynamic_scaffold(tmp_path):
    module = _load_script(LINK_SCRIPT)
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        "<TC-tests/test_a.py::test_a>\n"
        "<WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-placeholder)\n"
        "<BUG-TODO>\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only an incomplete scaffold"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_accepts_filled_dynamic_analysis(tmp_path):
    module = _load_script(LINK_SCRIPT)
    test_tag = "TC-tests/test_a.py::test_a"
    reference = module.waveform_reference(test_tag)
    anchor = reference.rsplit("#", 1)[1].rstrip(")")
    sections = "\n".join(
        f"{marker}\n**Localized {key} title**\ncompleted evidence-backed content"
        for key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    sections += "\n<CAUSE-REF-ROOT-DIV> [Division cause](#root-cause-div)"
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        f"<{test_tag}>\n"
        f"{reference}\n"
        f"{sections}\n</DYNAMIC-BUGS>\n"
        "<ROOT-CAUSES>\n"
        "<a id=\"root-cause-div\"></a>\n"
        "### Division cause <ROOT-DIV>\n"
        "<ROOT-CAUSE-ANALYSIS>\ncompleted analysis\n"
        "<ROOT-SOURCE-EVIDENCE>\ncompleted source evidence\n"
        "<ROOT-CAUSAL-CHAIN>\ncompleted causal chain\n"
        "<ROOT-FIX>\ncompleted fix\n"
        "<ROOT-RETEST>\ncompleted retest\n"
        "<RELATED-BUGS>\n"
        "- <RELATED-BUG-FG-A/FC-A/CK-A/BG-DIV-INF-BY-NUM-95> [FG-A/FC-A/CK-A/BG-DIV-INF-BY-NUM-95](#bug-anchor)\n"
        "</ROOT-CAUSES>\n"
        "<WAVEFORM-EVIDENCE>\n"
        f"<a id=\"{anchor}\"></a>\n"
        f"### <WAVEFORM-{test_tag}>\n"
        "```yaml\nwaveform_analysis:\n"
        f"  test_case: {test_tag}\n"
        "  bug_tags: [BG-DIV-INF-BY-NUM-95]\n"
        "  status: confirmed\n"
        "  alignment_evidence: completed\n"
        "  bug_evidence:\n"
        "    BG-DIV-INF-BY-NUM-95:\n"
        "      required_signals: [TOP.dut.valid]\n"
        "      observed_behavior: completed\n"
        "      source_correlation: completed\n"
        "```\n"
        "<WAVEFORM-VIEWER> [viewer](/surfer/?wave=eyJ2IjoxfQ)\n"
        "</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    module.ensure_link_targets_exist_in_bug_analysis(
        ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
    )
    blocks = module.collect_dynamic_bg_blocks(
        bug_file.read_text(encoding="utf-8").splitlines(keepends=True),
        "BG-DIV-INF-BY-NUM-95",
    )
    assert len(blocks) == 1
    assert "<TC-tests/test_a.py::test_a>" in blocks[0]
    assert "<BUG-TRIGGER>" in blocks[0]
    assert "<BUG-RETEST>" not in blocks[0]


def test_static_bug_link_script_rejects_missing_dynamic_container(tmp_path):
    module = _load_script(LINK_SCRIPT)
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text("<BG-DIV-INF-BY-NUM-95>\n", encoding="utf-8")

    with pytest.raises(ValueError, match="<DYNAMIC-BUGS>.*exactly once"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_requires_structured_confirmed_waveform(tmp_path):
    module = _load_script(LINK_SCRIPT)
    test_tag = "TC-tests/test_a.py::test_a"
    reference = module.waveform_reference(test_tag)
    sections = "\n".join(
        f"{marker}\ncompleted evidence-backed content"
        for _key, marker in module.DYNAMIC_BUG_SECTION_MARKERS
    )
    bug_file = tmp_path / "bugs.md"
    bug_file.write_text(
        "<DYNAMIC-BUGS>\n<FG-A>\n<FC-A>\n<CK-A>\n<BG-DIV-INF-BY-NUM-95>\n"
        f"<{test_tag}>\n"
        f"{reference}\n"
        "waveform_analysis: status: confirmed\n"
        f"{sections}\n</DYNAMIC-BUGS>\n"
        "<WAVEFORM-EVIDENCE>\n</WAVEFORM-EVIDENCE>\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="central evidence"):
        module.ensure_link_targets_exist_in_bug_analysis(
            ["BG-DIV-INF-BY-NUM-95"], str(bug_file)
        )


def test_static_bug_link_script_updates_tagged_localized_report(tmp_path):
    module = _load_script(LINK_SCRIPT)
    static_file = tmp_path / "static.md"
    static_file.write_text(
        "## Localized summary\n<STATIC-BUG-SUMMARY>\n"
        "| 序号 | Bug标签 | 功能路径 | 描述 | 置信度 | 文件 | 动态Bug关联 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 001 | BG-STATIC-001-DIV | FG-A/FC-A/CK-A | desc | high | rtl/a.v | LINK-BUG-[BG-TBD] |\n"
        "## Localized details\n<STATIC-BUG-DETAILS>\n"
        "<FG-A>\n<FC-A>\n<CK-A>\n<BG-STATIC-001-DIV>\n"
        "<LINK-BUG-[BG-TBD]>\n<FILE-rtl/a.v:1-1>\n"
        "## Localized progress\n<STATIC-BUG-PROGRESS>\n",
        encoding="utf-8",
    )

    module.update_static_bug_link(
        str(static_file), "BG-STATIC-001-DIV", ["BG-DIV-INF-BY-NUM-95"]
    )

    updated = static_file.read_text(encoding="utf-8")
    assert "LINK-BUG-[BG-DIV-INF-BY-NUM-95]" in updated
    assert "<LINK-BUG-[BG-DIV-INF-BY-NUM-95]>" in updated
    assert "BG-TBD" not in updated
