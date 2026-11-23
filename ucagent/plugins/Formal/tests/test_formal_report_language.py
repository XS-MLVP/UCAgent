"""Keep accessible, evidence-scoped reporting guidance available with or without Skills."""

from pathlib import Path

import pytest

from ucagent.util.config import get_config


SOURCE = Path(__file__).resolve().parents[1] / "src/formal"


@pytest.mark.parametrize("enabled", [False, True])
def test_plain_language_report_contract_is_in_resolved_stage(tmp_path, monkeypatch, enabled):
    """The reporting requirement must not depend on reading an optional Skill."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = get_config(workflow_config_file=str(SOURCE / "workflows/formal.yaml"),
                     cfg_override=[{"skill.use_skill": enabled}])
    reports = next(item for item in cfg.get_value("stage") if item["name"] == "findings_and_summary")
    stage = next(item for item in reports["stage"] if item["name"] == "formal_execution")
    text = "\n".join(stage["task"])
    assert "触发条件" in text and "预期与实际差异" in text and "后果" in text
    assert "必要术语首次解释" in text and "不自造故障名称" in text
    assert "根因推测" in text and "原因未确认" in text
    assert "Guide_Doc/bug_report.md" in text


def test_report_guides_and_skill_reference_one_plain_language_contract():
    """Analysis, summary and optional Skill must point to the same report rule."""
    report = (SOURCE / "Guide_Doc/bug_report.md").read_text()
    assert "## 问题表述要求" in report
    assert "原因尚未确认" in report
    assert "请求已丢失" in report and "证据确认请求不再保留" in report
    assert "什么输入或配置下" in report and "哪个模块/信号本应怎样" in report
    for relative in ("Guide_Doc/env_analysis.md", "Guide_Doc/formal_summary.md", "skills/data/SKILL.md"):
        text = (SOURCE / relative).read_text()
        assert "Guide_Doc/bug_report.md" in text and "问题表述要求" in text
    # Normative Markdown headings retain the framework's required spacing.
    for relative in ("Guide_Doc/bug_report.md", "Guide_Doc/env_analysis.md", "Guide_Doc/formal_summary.md"):
        lines = (SOURCE / relative).read_text().splitlines()
        for index, line in enumerate(lines):
            if line.startswith("#"):
                assert index > 0 and not lines[index - 1].strip(), (relative, index + 1)
