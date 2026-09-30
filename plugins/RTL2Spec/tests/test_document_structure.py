"""Verify the fixed formal document order and minimum table contract."""

from pathlib import Path
import re

import pytest

from rtl2spec.documents import TEMPLATE, document_sections, template_version, validate_structure

FIXTURE = Path(__file__).parent / "fixtures/design_document.md"


def test_complete_fixture_and_template_agree():
    """The complete fixture follows the formal v5.1 section order without comments."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert validate_structure(text, "Sbuffer") == []
    assert sum(section["tables"] for section in document_sections(text)) == 22
    assert "<!--" not in text
    assert f"> 模板结构版本：{template_version()}" in TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("# Sbuffer 设计与功能检测点文档", "# Another 设计与功能检测点文档"),
        ("## 文档摘要", "## 自定义摘要"),
        ("## 文档摘要", "### 文档摘要"),
        ("## 文档摘要", ""),
        ("## 文档摘要", "## 文档摘要\n\n## 额外小节"),
        ("### P-FORWARD：组合转发", "### P-[NAME]：[行为名称]"),
        ("## 附录 E：场景视角 Test Case", "## 附录 E：其他清单"),
    ],
)
def test_heading_contract(original, replacement):
    """Renamed, missing, extra or incorrectly nested headings cannot pass."""
    text = FIXTURE.read_text(encoding="utf-8").replace(original, replacement)
    result = validate_structure(text, "Sbuffer")
    assert result and result[0]["expected"]
    assert "Guide_Doc/chip_design_document_template_zh.md" in result[0]["next_action"]


def test_heading_order_is_checked():
    """The right titles in the wrong order are rejected."""
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace("## 形式化属性契约", "## SWAP").replace(
        "## 验证策略与 Testplan", "## 形式化属性契约"
    ).replace("## SWAP", "## 验证策略与 Testplan")
    assert validate_structure(text, "Sbuffer")


@pytest.mark.parametrize("mutation", ["missing", "extra", "moved", "fenced", "commented", "quoted"])
def test_tables_are_checked_per_section(mutation):
    """Required tables remain part of the structure contract; extra evidence tables are allowed."""
    text = FIXTURE.read_text(encoding="utf-8")
    table = "| 参数 ID | 参数 / 派生常量 | 配置值 | 约束或裁剪 | 证据 |\n| --- | --- | --- | --- | --- |\n| `PARAM-01` | `Sbuffer` | `8` | `无参数` | `E-RTL-01` |"
    if mutation == "missing":
        text = text.replace(table, "")
    elif mutation == "extra":
        text = text.replace(table, table + "\n\n" + table)
    elif mutation == "moved":
        text = text.replace(table, "").replace(
            "## 附录 C：范围、文档控制、证据与版本变更", "## 附录 C：范围、文档控制、证据与版本变更\n\n" + table
        )
    elif mutation == "fenced":
        text = text.replace(table, "```text\n" + table + "\n```")
    elif mutation == "commented":
        text = text.replace(table, "<!--\n" + table + "\n-->")
    else:
        text = text.replace(table, "\n".join("> " + line for line in table.splitlines()))
    result = validate_structure(text, "Sbuffer")
    if mutation == "extra":
        assert result == []
    else:
        assert result and result[0]["error"].startswith("table count")


def test_inapplicable_scenarios_can_be_omitted():
    """A DUT without a boundary or recovery path need not manufacture CASE sections."""
    text = FIXTURE.read_text(encoding="utf-8")
    for title in ("CASE-NORMAL", "CASE-BOUNDARY", "CASE-RECOVERY"):
        text = re.sub(
            rf"\n<!-- STRUCTURE: repeat min=0 -->\n\n### {title}：.*?(?=\n<!-- STRUCTURE: repeat min=0 -->|\n### CASE-EXTRA：)",
            "\n",
            text,
            flags=re.S,
        )
    assert validate_structure(text, "Sbuffer") == []


def test_repeatable_sections_are_explicit():
    """P-* and CASE-* blocks repeat without HTML structure comments in artifacts."""
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace(
        "## 验证策略与 Testplan", "### P-ZERO：零输入\n\n输入为零时输出为零。\n\n## 验证策略与 Testplan"
    )
    # The inserted P block belongs to the repeatable behavior section, so put
    # it immediately before the next top-level section.
    text = text.replace(
        "### P-ZERO：零输入\n\n输入为零时输出为零。\n\n## 验证策略与 Testplan",
        "### P-FORWARD：组合转发\n\n### P-ZERO：零输入\n\n输入为零时输出为零。\n\n## 验证策略与 Testplan",
    )
    text = text.replace(
        "### CASE-EXTRA：其他场景",
        "### CASE-ZERO：全零数据\n\n| 参与者 | 前置条件 | 输入 | 预期输出 | 关联 FC / CK |\n| --- | --- | --- | --- | --- |\n| 测试 | 输入为零 | 0x00 | 0x00 | FC-BEHAVIOR, CK-EVENT-RESULT |\n\n验证 P-ZERO。\n\n### CASE-EXTRA：其他场景",
    )
    assert validate_structure(text, "Sbuffer") == []


def test_no_behavior_definition_fails():
    """The behavior block requires at least one P-* definition."""
    text = FIXTURE.read_text(encoding="utf-8").replace("### P-FORWARD：组合转发", "")
    assert validate_structure(text, "Sbuffer")


def test_code_and_comments_do_not_create_headings():
    """Fenced headings and comments cannot satisfy the formal heading contract."""
    text = FIXTURE.read_text(encoding="utf-8")
    example = "\n\n````markdown\n# Example\n```text\n| A | B |\n| --- | --- |\n```\n````\n\n<!--\n# Hidden\n-->\n"
    assert validate_structure(text + example, "Sbuffer") == []
    assert validate_structure("", "Sbuffer")
    with pytest.raises(ValueError, match="unclosed"):
        validate_structure(text + "\n```markdown\n# Incomplete\n", "Sbuffer")


def test_contract_is_loaded_from_template(tmp_path, monkeypatch):
    """Changing the maintained template changes validation without a duplicated heading list."""
    from rtl2spec import documents

    template = tmp_path / "template.md"
    template.write_text(
        TEMPLATE.read_text(encoding="utf-8").replace("## 文档摘要", "## 新摘要"),
        encoding="utf-8",
    )
    monkeypatch.setattr(documents, "TEMPLATE", template)
    text = FIXTURE.read_text(encoding="utf-8")
    assert validate_structure(text, "Sbuffer")
    assert validate_structure(text.replace("## 文档摘要", "## 新摘要"), "Sbuffer") == []
