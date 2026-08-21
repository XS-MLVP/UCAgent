import ast
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from ucagent.util.bug_analysis_contract import BUG_ANALYSIS_SECTION_TITLES


IMPLEMENTATION_ROOT = REPOSITORY_ROOT / "ucagent"
LANGUAGE_ROOT = IMPLEMENTATION_ROOT / "lang"
CHINESE_LANGUAGE_ROOT = LANGUAGE_ROOT / "zh"
LOCALE_CONTRACT = (
    CHINESE_LANGUAGE_ROOT / "config" / "bug_analysis_contract.json"
)


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
