import ast
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from ucagent.util.bug_analysis_contract import (
    BUG_ANALYSIS_SECTION_TITLES,
    BUG_ANALYSIS_SECTION_MARKERS,
    DYNAMIC_BUG_DOCUMENT_PATH,
    NO_BUG_DOCUMENT_SECTIONS,
    NO_BUG_DOCUMENT_TITLE,
    RELATED_BUGS_MARKER,
    ROOT_ANALYSIS_SECTION_MARKERS,
    STATIC_BUG_DOCUMENT_PATH,
    TEST_CASE_SERIALIZATION,
)
from ucagent.util.markdown import (
    ensure_markdown_file_heading_spacing,
    ensure_markdown_heading_spacing,
    markdown_heading_spacing_errors,
)
from ucagent.lang.zh.skills.formal.lib import formal_tools


IMPLEMENTATION_ROOT = REPOSITORY_ROOT / "ucagent"
LANGUAGE_ROOT = IMPLEMENTATION_ROOT / "lang"
CHINESE_LANGUAGE_ROOT = LANGUAGE_ROOT / "zh"
LOCALE_CONTRACT = (
    CHINESE_LANGUAGE_ROOT / "config" / "bug_analysis_contract.json"
)
BUG_HEADING_COMPANIONS = frozenset(
    [marker for _field, marker in BUG_ANALYSIS_SECTION_MARKERS]
    + [marker for _field, marker in ROOT_ANALYSIS_SECTION_MARKERS]
    + [RELATED_BUGS_MARKER]
)


def _markdown_heading_spacing_errors(text: str):
    return markdown_heading_spacing_errors(text, BUG_HEADING_COMPANIONS)


def _contains_han(value: str) -> bool:
    ranges = (
        (0x2E80, 0x303F),
        (0x3400, 0x4DBF),
        (0x4E00, 0x9FFF),
        (0xF900, 0xFAFF),
        (0xFF00, 0xFFEF),
        (0x20000, 0x2EBEF),
        (0x30000, 0x323AF),
    )
    return any(
        lower <= ord(character) <= upper
        for character in value
        for lower, upper in ranges
    )


def test_generic_implementation_python_has_no_chinese_literals():
    failures = []
    for path in sorted(IMPLEMENTATION_ROOT.rglob("*.py")):
        if path.is_relative_to(CHINESE_LANGUAGE_ROOT):
            continue
        source = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), start=1):
            if _contains_han(line):
                failures.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _contains_han(node.value):
                    failures.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno} (decoded string)"
                    )
    assert not failures, "Chinese literals found outside ucagent/lang/zh: " + ", ".join(
        sorted(set(failures))
    )


def test_bug_analysis_titles_come_from_zh_locale_contract():
    payload = json.loads(LOCALE_CONTRACT.read_text(encoding="utf-8"))

    assert dict(BUG_ANALYSIS_SECTION_TITLES) == payload["analysis_section_titles"]

    asset = (
        CHINESE_LANGUAGE_ROOT
        / "skills"
        / "unitytest"
        / "dynamic-bug-recording"
        / "assets"
        / "dynamic_bug_entry.md"
    ).read_text(encoding="utf-8")
    guide = (
        CHINESE_LANGUAGE_ROOT / "doc" / "Guide_Doc" / "dut_bug_analysis.md"
    ).read_text(encoding="utf-8")
    for title in payload["analysis_section_titles"].values():
        assert asset.count(title) == 1
        assert title in guide


def test_bug_analysis_paths_tc_forms_and_no_bug_shape_come_from_locale_contract():
    payload = json.loads(LOCALE_CONTRACT.read_text(encoding="utf-8"))

    assert DYNAMIC_BUG_DOCUMENT_PATH == "{OUT}/{DUT}_bug_analysis.md"
    assert STATIC_BUG_DOCUMENT_PATH == "{OUT}/{DUT}_static_bug_analysis.md"
    assert payload["document_paths"] == {
        "dynamic": DYNAMIC_BUG_DOCUMENT_PATH,
        "static": STATIC_BUG_DOCUMENT_PATH,
    }
    assert TEST_CASE_SERIALIZATION == {
        "markdown_tag": "- {visible_title} <TC-{exact_report_node_id}>",
        "tool_or_yaml": "TC-{exact_report_node_id}",
        "waveinfo": "{exact_report_node_id}",
    }
    assert payload["test_case_serialization"] == TEST_CASE_SERIALIZATION
    assert NO_BUG_DOCUMENT_TITLE == "# {DUT} 动态 Bug 分析"
    assert list(NO_BUG_DOCUMENT_SECTIONS) == payload["no_bug_document"]["sections"]
    assert payload["no_bug_document"]["container_body_must_be_empty"] is True

    expected_markers = [
        ("<DYNAMIC-BUGS>", "</DYNAMIC-BUGS>"),
        ("<ROOT-CAUSES>", "</ROOT-CAUSES>"),
        ("<WAVEFORM-EVIDENCE>", "</WAVEFORM-EVIDENCE>"),
    ]
    for relative_path in (
        "template/unity_test/{{DUT}}_bug_analysis.md",
        "skills/unitytest/dynamic-bug-recording/assets/bug_analysis_document.md",
    ):
        document = (CHINESE_LANGUAGE_ROOT / relative_path).read_text(encoding="utf-8")
        for start_marker, end_marker in expected_markers:
            assert f"{start_marker}\n{end_marker}" in document


def test_markdown_heading_spacing_scan_ignores_non_markdown_fences():
    sample = """
# Document

```python
# Python comment
```

<a id="example-anchor"></a>

## Anchored heading

````markdown

# Embedded document

```systemverilog
# preprocessor-like example
```
````
"""

    assert _markdown_heading_spacing_errors(sample) == []


def test_markdown_heading_spacing_formatter_preserves_code_and_line_endings():
    sample = (
        "# Document\r\n"
        "text\r\n"
        "```python\r\n"
        "# Python comment\r\n"
        "```\r\n"
        "## Section"
    )

    formatted = ensure_markdown_heading_spacing(sample)

    assert formatted == (
        "\r\n"
        "# Document\r\n"
        "\r\n"
        "text\r\n"
        "```python\r\n"
        "# Python comment\r\n"
        "```\r\n"
        "\r\n"
        "## Section\r\n"
        "\r\n"
    )
    assert _markdown_heading_spacing_errors(formatted) == []
    assert ensure_markdown_heading_spacing(formatted) == formatted


def test_markdown_heading_companions_must_be_explicit():
    sample = "## Root field\n<ROOT-FIX>\ncontent\n"

    assert markdown_heading_spacing_errors(sample) == [
        (1, "before"),
        (1, "after"),
    ]
    assert markdown_heading_spacing_errors(sample, ("<ROOT-FIX>",)) == [
        (1, "before")
    ]
    assert ensure_markdown_heading_spacing(sample) == (
        "\n## Root field\n\n<ROOT-FIX>\ncontent\n"
    )
    assert ensure_markdown_heading_spacing(sample, ("<ROOT-FIX>",)) == (
        "\n## Root field\n<ROOT-FIX>\ncontent\n"
    )


def test_markdown_heading_spacing_has_no_preceding_blank_exceptions():
    sample = (
        "# File heading\n\n"
        '<a id="section"></a>\n'
        "## Anchored heading\n\n"
        "```markdown\n"
        "### Embedded heading\n\n"
        "```\n"
    )

    assert markdown_heading_spacing_errors(sample) == [
        (1, "before"),
        (4, "before"),
        (7, "before"),
    ]
    formatted = ensure_markdown_heading_spacing(sample)
    assert formatted.startswith("\n# File heading")
    assert '<a id="section"></a>\n\n## Anchored heading' in formatted
    assert "```markdown\n\n### Embedded heading" in formatted
    assert markdown_heading_spacing_errors(formatted) == []


def test_markdown_file_formatter_preserves_canonical_field_companions():
    sample = "# Bug\n###### Overview\n<BUG-OVERVIEW>\ncontent\n"

    formatted = ensure_markdown_file_heading_spacing("bug.md", sample)

    assert formatted == (
        "\n# Bug\n\n###### Overview\n<BUG-OVERVIEW>\ncontent\n"
    )
    assert ensure_markdown_file_heading_spacing("bug.txt", sample) == sample


def test_markdown_formatter_reuses_blank_line_between_adjacent_headings():
    sample = "# Parent\n## Child\nbody\n"

    formatted = ensure_markdown_heading_spacing(sample)

    assert formatted == "\n# Parent\n\n## Child\n\nbody\n"
    assert ensure_markdown_heading_spacing(formatted) == formatted


def test_runtime_markdown_headings_are_surrounded_by_blank_lines():
    runtime_roots = (
        CHINESE_LANGUAGE_ROOT / "doc",
        CHINESE_LANGUAGE_ROOT / "template",
        CHINESE_LANGUAGE_ROOT / "skills",
    )
    paths = {
        path
        for root in runtime_roots
        for path in root.rglob("*")
        if path.is_file() and (path.name.endswith(".md") or path.name.endswith(".md.j2"))
    }
    paths.update(IMPLEMENTATION_ROOT.rglob("SKILL.md"))

    failures = []
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8")
        companions = (
            BUG_HEADING_COMPANIONS
            if (
                path == CHINESE_LANGUAGE_ROOT / "doc" / "Guide_Doc" / "dut_bug_analysis.md"
                or path.is_relative_to(
                    CHINESE_LANGUAGE_ROOT
                    / "skills"
                    / "unitytest"
                    / "dynamic-bug-recording"
                    / "assets"
                )
            )
            else ()
        )
        for line_number, side in markdown_heading_spacing_errors(text, companions):
            failures.append(
                f"{path.relative_to(REPOSITORY_ROOT)}:{line_number} missing blank line {side} heading"
            )

    assert not failures, "Runtime Markdown heading spacing errors:\n" + "\n".join(
        failures
    )


def test_formal_markdown_renderers_preserve_heading_spacing(tmp_path):
    class EmptyTemplateValue(dict):
        def __getattr__(self, _name):
            return self

        def __bool__(self):
            return False

        def __str__(self):
            return ""

    empty = EmptyTemplateValue()
    contexts = {
        "functions_and_checks.md": {"DUT": "Demo", "function_groups": []},
        "verification_needs_and_plan.md": {"DUT": "Demo", "planning": empty},
        "basic_info.md": {"DUT": "Demo", "basic_info": empty},
        "env_analysis.md": {
            "DUT": "Demo",
            "summary_items": [],
            "tt_entries": [],
            "fa_entries": [],
        },
        "bug_report.md": {"DUT": "Demo", "bugs": []},
        "formal_summary.md": {"DUT": "Demo", "summary": empty, "coverage": empty},
    }

    for template_name, context in contexts.items():
        output = tmp_path / template_name
        formal_tools._render_to_file(template_name, context, str(output))
        assert output.is_file(), template_name
        assert markdown_heading_spacing_errors(output.read_text(encoding="utf-8")) == []
