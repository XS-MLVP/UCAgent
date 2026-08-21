# -*- coding: utf-8 -*-
"""Canonical machine-readable contract for dynamic Bug analysis documents."""

import hashlib
import json
from pathlib import Path
import posixpath
import re


DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
DYNAMIC_BUGS_END_MARKER = "</DYNAMIC-BUGS>"
WAVEFORM_EVIDENCE_MARKER = "<WAVEFORM-EVIDENCE>"
WAVEFORM_EVIDENCE_END_MARKER = "</WAVEFORM-EVIDENCE>"
WAVEFORM_REFERENCE_MARKER = "<WAVEFORM-REF>"
WAVEFORM_RECORD_TAG_PREFIX = "WAVEFORM-"
STATIC_BUG_SECTION_MARKERS = (
    "<STATIC-BUG-SUMMARY>",
    "<STATIC-BUG-DETAILS>",
    "<STATIC-BUG-PROGRESS>",
)
DOCUMENT_TAG_PATTERN = re.compile(r"<(FG|FC|CK|BG|TC)-([^<>]+)>")
WAVEFORM_BLOCK_KEY = "waveform_analysis"
WAVEFORM_FENCE_OPEN = "```yaml"
WAVEFORM_FENCE_CLOSE = "```"
WAVEFORM_LLM_ANALYSIS_FIELDS = (
    "alignment_evidence",
)
WAVEFORM_BUG_ANALYSIS_FIELDS = (
    "required_signals",
    "observed_behavior",
    "source_correlation",
)
WAVEFORM_SIGNAL_GROUP_FIELDS = (
    "clocks",
    "inputs",
    "outputs",
    "protocol",
    "key_signals",
)
BUG_TODO_MARKER = "<BUG-TODO>"
BUG_SOURCE_UNAVAILABLE_MARKER = "<BUG-SOURCE-UNAVAILABLE>"
BUG_SOURCE_EVIDENCE_MARKERS = (
    "<BUG-SOURCE-FIRST-ERROR>",
    "<BUG-SOURCE-PROPAGATION>",
    "<BUG-SOURCE-OBSERVABLE>",
)
BUG_ANALYSIS_SECTION_MARKERS = (
    ("overview", "<BUG-OVERVIEW>"),
    ("symptoms", "<BUG-SYMPTOMS>"),
    ("trigger", "<BUG-TRIGGER>"),
    ("root_cause", "<BUG-ROOT-CAUSE>"),
    ("source_evidence", "<BUG-SOURCE-EVIDENCE>"),
    ("causal_chain", "<BUG-CAUSAL-CHAIN>"),
    ("fix", "<BUG-FIX>"),
    ("retest", "<BUG-RETEST>"),
)


def _load_locale_contract() -> dict:
    """Load and validate the localized display contract."""

    contract_path = (
        Path(__file__).resolve().parents[1]
        / "lang"
        / "zh"
        / "config"
        / "bug_analysis_contract.json"
    )
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"cannot load Bug analysis locale contract '{contract_path}': {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("Bug analysis locale contract must be a JSON object")

    generic_titles = payload.get("generic_visible_titles")
    confidence = payload.get("bg_confidence")
    waveform_suffix = payload.get("waveform_title_suffix")
    section_titles = payload.get("analysis_section_titles")
    expected_keys = [key for key, _marker in BUG_ANALYSIS_SECTION_MARKERS]
    if not isinstance(generic_titles, list) or not all(
        isinstance(value, str) and value for value in generic_titles
    ):
        raise RuntimeError("generic_visible_titles must be a non-empty string list")
    if not isinstance(confidence, dict) or not all(
        isinstance(confidence.get(key), str) and confidence[key]
        for key in ("prefix", "suffix")
    ):
        raise RuntimeError("bg_confidence must define non-empty prefix and suffix")
    if not isinstance(waveform_suffix, str) or not waveform_suffix:
        raise RuntimeError("waveform_title_suffix must be a non-empty string")
    if not isinstance(section_titles, dict) or list(section_titles) != expected_keys:
        raise RuntimeError(
            "analysis_section_titles keys must match the canonical marker order"
        )
    if not all(
        isinstance(section_titles[key], str)
        and section_titles[key].startswith("###### ")
        and "\n" not in section_titles[key]
        for key in expected_keys
    ):
        raise RuntimeError(
            "analysis_section_titles values must be single level-6 Markdown headings"
        )
    return payload


_LOCALE_CONTRACT = _load_locale_contract()
GENERIC_DYNAMIC_TITLES = frozenset(_LOCALE_CONTRACT["generic_visible_titles"])
_BG_CONFIDENCE_PREFIX = _LOCALE_CONTRACT["bg_confidence"]["prefix"]
_BG_CONFIDENCE_SUFFIX = _LOCALE_CONTRACT["bg_confidence"]["suffix"]
_WAVEFORM_TITLE_SUFFIX = _LOCALE_CONTRACT["waveform_title_suffix"]
BUG_ANALYSIS_SECTION_TITLES = tuple(
    (key, _LOCALE_CONTRACT["analysis_section_titles"][key])
    for key, _marker in BUG_ANALYSIS_SECTION_MARKERS
)


def normalize_display_title(value: str) -> str:
    """Return one safe, visible Markdown title without embedded machine tags."""

    title = re.sub(r"\s+", " ", str(value or "")).strip()
    if not title:
        raise ValueError("visible description must be non-empty")
    if "\n" in str(value) or "\r" in str(value) or "<" in title or ">" in title:
        raise ValueError("visible description must be one line without angle-bracket tags")
    if title.startswith("[") and title.endswith("]"):
        raise ValueError("visible description must replace bracketed scaffold text")
    if title in GENERIC_DYNAMIC_TITLES:
        raise ValueError("visible description must identify the tagged item")
    return title


def parse_dynamic_tag_heading(line: str, kind: str, label: str) -> str:
    """Validate one semantic FG/FC/CK/BG/TC heading and return its visible title."""

    prefixes = {
        "FG": "### ",
        "FC": "#### ",
        "CK": "##### ",
        "BG": "###### ",
        "TC": "- ",
    }
    if kind not in prefixes:
        raise ValueError(f"unsupported dynamic tag kind: {kind}")
    text = str(line).strip()
    prefix = prefixes[kind]
    suffix = f" <{label}>"
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise ValueError(
            f"use '{prefix}<visible description>{suffix}' with the tag at line end"
        )
    title = text[len(prefix) : -len(suffix)].strip()
    if kind == "BG":
        confidence_match = re.fullmatch(
            rf"(.+){re.escape(_BG_CONFIDENCE_PREFIX)}"
            rf"(\d{{1,3}}){re.escape(_BG_CONFIDENCE_SUFFIX)}",
            title,
        )
        if confidence_match is None:
            raise ValueError(
                "BG visible description must end with the confidence notation shown in "
                "Guide_Doc/dut_bug_analysis.md section 5.1"
            )
        title = confidence_match.group(1).strip()
        label_match = re.fullmatch(r"BG-.+-(\d{1,3})", label)
        if label_match is None or confidence_match.group(2) != label_match.group(1):
            raise ValueError("BG visible confidence must match the BG tag suffix")
    return normalize_display_title(title)


def waveform_record_heading(test_case_tag: str, test_title: str) -> str:
    """Return the visible heading for one central waveform record."""

    title = normalize_display_title(test_title)
    return (
        f"### {title}{_WAVEFORM_TITLE_SUFFIX} "
        f"<{waveform_record_tag(test_case_tag)}>"
    )


def parse_waveform_record_heading(line: str) -> tuple[str, str]:
    """Return the canonical TC tag and visible title from a waveform record heading."""

    match = re.fullmatch(r"###\s+(.+?)\s+<(WAVEFORM-TC-[^<>]+)>", str(line).strip())
    if match is None:
        raise ValueError(
            "use a level-3 heading with a visible test description, the required "
            "waveform suffix shown in Guide_Doc/dut_bug_analysis.md section 5.1, "
            "and <WAVEFORM-TC-...> at line end"
        )
    visible = match.group(1)
    suffix = _WAVEFORM_TITLE_SUFFIX
    if not visible.endswith(suffix):
        raise ValueError(
            "waveform record visible description must end with the suffix shown in "
            "Guide_Doc/dut_bug_analysis.md section 5.1"
        )
    title = normalize_display_title(visible[: -len(suffix)])
    test_case_tag = normalize_test_case_tag(match.group(2)[len("WAVEFORM-") :])
    return test_case_tag, title


def normalize_test_case_tag(value: str) -> str:
    """Return the canonical ``TC-path::node`` tag used by Bug documents."""

    normalized = str(value or "").strip()
    if normalized.startswith("<") and normalized.endswith(">"):
        normalized = normalized[1:-1].strip()
    if not normalized.startswith("TC-"):
        raise ValueError("test case tag must use the exact TC-... form")
    payload = normalized[len("TC-") :]
    parts = payload.split("::")
    if len(parts) not in (2, 3) or not all(part.strip() for part in parts):
        raise ValueError(
            "test case tag must contain a pytest file/function node ID, optionally with a class"
        )
    file_path = posixpath.normpath(parts[0].replace("\\", "/"))
    if file_path in ("", ".") or file_path.startswith("../") or file_path == "..":
        raise ValueError("test case path must be a workspace-relative Python file")
    if file_path.startswith("/") or not file_path.endswith(".py"):
        raise ValueError("test case path must be a workspace-relative Python file")
    return "TC-" + "::".join([file_path, *(part.strip() for part in parts[1:])])


def waveform_anchor_id(test_case_tag: str) -> str:
    """Return the stable Markdown anchor for one canonical test case tag."""

    canonical = normalize_test_case_tag(test_case_tag)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"waveform-{digest}"


def waveform_record_tag(test_case_tag: str) -> str:
    """Return the machine tag that owns one test case's waveform evidence."""

    return WAVEFORM_RECORD_TAG_PREFIX + normalize_test_case_tag(test_case_tag)


def waveform_reference(test_case_tag: str, label: str = "WAVEFORM-EVIDENCE") -> str:
    """Return the canonical in-document link from a Bug/TC to its evidence."""

    return f"{WAVEFORM_REFERENCE_MARKER} [{label}](#{waveform_anchor_id(test_case_tag)})"
