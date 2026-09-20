"""Verify the published template contract without imposing prose or table-row counts."""

from pathlib import Path

import pytest

from rtl2spec.documents import (
    TEMPLATE,
    document_sections,
    template_version,
    validate_structure,
)

FIXTURE = Path(__file__).parent / "fixtures/design_document.md"


def test_complete_fixture_and_template_agree():
    """The independent completed fixture has all fixed headings and 14 correctly placed tables."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert validate_structure(text, "Sbuffer") == []
    sections = document_sections(text)
    assert sum(section["tables"] for section in sections) == 14
    assert [
        section["tables"] for section in sections if section["title"].startswith("附录")
    ] == [2, 1, 2, 1, 1, 2, 0]
    assert f"| 使用模板版本 | {template_version()} |" in TEMPLATE.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "original,replacement",
    [
        ("# Sbuffer 设计与功能检测点文档", "# Another 设计与功能检测点文档"),
        ("### 文档摘要", "### 自定义摘要"),
        ("### 文档摘要", "#### 文档摘要"),
        ("### 文档摘要", ""),
        ("### 文档摘要", "### 文档摘要\n\n### 额外小节"),
        ("#### `P-FORWARD`：组合转发", "#### `P-[NAME]`：[统一行为名称]"),
        ("### 附录 G：签核清单", "### 附录 G：其他清单"),
    ],
)
def test_heading_contract(original, replacement):
    """Renamed, missing, extra, unfilled or incorrectly nested headings cannot pass."""
    text = FIXTURE.read_text(encoding="utf-8").replace(original, replacement)
    result = validate_structure(text, "Sbuffer")
    assert result and result[0]["expected"]
    assert "Guide_Doc/chip_design_document_template_zh.md" in result[0]["next_action"]


def test_heading_order_is_checked():
    """The right titles in the wrong order are rejected."""
    text = (
        FIXTURE.read_text(encoding="utf-8")
        .replace("### 验证策略", "### SWAP")
        .replace("### 功能分组", "### 验证策略")
        .replace("### SWAP", "### 功能分组")
    )
    assert validate_structure(text, "Sbuffer")


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "moved", "fenced", "commented", "quoted"]
)
def test_tables_are_checked_per_section(mutation):
    """Count rendered tables in their own section; examples and quotations cannot replace them."""
    text = FIXTURE.read_text(encoding="utf-8")
    table = "| 参数 | 取值 |\n| --- | --- |\n| 数据宽度 | 8 位，无可配置参数 |"
    if mutation == "missing":
        text = text.replace(table, "")
    elif mutation == "extra":
        text = text.replace(table, table + "\n\n" + table)
    elif mutation == "moved":
        text = text.replace(table, "").replace(
            "### 附录 E：FACT、OPEN 与偏差", "### 附录 E：FACT、OPEN 与偏差\n\n" + table
        )
    elif mutation == "fenced":
        text = text.replace(table, "```text\n" + table + "\n```")
    elif mutation == "commented":
        text = text.replace(table, "<!--\n" + table + "\n-->")
    else:
        text = text.replace(
            table, "\n".join("> " + line for line in table.splitlines())
        )
    result = validate_structure(text, "Sbuffer")
    assert result and result[0]["error"].startswith("table count")


def test_repeatable_sections_are_explicit():
    """Behavior and extra-case blocks can expand without permitting arbitrary section changes."""
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace(
        "### 关键结构与状态",
        "#### P-ZERO：零输入\n\n输入为零时输出为零。\n\n### 关键结构与状态",
    )
    text = text.replace(
        "### 签核与开放项",
        "#### CASE-ZERO：全零数据\n\n验证 P-ZERO。\n\n#### CASE-ONE：全一数据\n\n验证 P-FORWARD。\n\n### 签核与开放项",
    )
    assert validate_structure(text, "Sbuffer") == []
    assert validate_structure(
        text.replace("#### CASE-ZERO：全零数据", "#### 自定义分节"), "Sbuffer"
    )


def test_no_behavior_definition_fails():
    """The repeatable behavior block still requires at least one real definition."""
    text = FIXTURE.read_text(encoding="utf-8").replace("#### `P-FORWARD`：组合转发", "")
    assert validate_structure(text, "Sbuffer")


def test_code_and_comments_do_not_create_headings():
    """Pseudo-code headings and tables remain examples, including four-backtick fences."""
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
        TEMPLATE.read_text(encoding="utf-8").replace("### 文档摘要", "### 新摘要"),
        encoding="utf-8",
    )
    monkeypatch.setattr(documents, "TEMPLATE", template)
    text = FIXTURE.read_text(encoding="utf-8")
    assert validate_structure(text, "Sbuffer")
    assert (
        validate_structure(text.replace("### 文档摘要", "### 新摘要"), "Sbuffer") == []
    )
