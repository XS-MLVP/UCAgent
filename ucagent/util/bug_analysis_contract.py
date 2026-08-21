# -*- coding: utf-8 -*-
"""Canonical machine-readable contract for dynamic Bug analysis documents."""

import hashlib
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
GENERIC_DYNAMIC_TITLES = frozenset(
    {
        "\u529f\u80fd\u7ec4",
        "\u529f\u80fd\u7ec4\uff1a",
        "\u529f\u80fd",
        "\u529f\u80fd\uff1a",
        "\u68c0\u6d4b\u70b9",
        "\u68c0\u6d4b\u70b9\uff1a",
        "\u52a8\u6001 Bug",
        "\u5931\u8d25\u7528\u4f8b",
        "\u5931\u8d25\u7528\u4f8b\uff1a",
    }
)
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
BUG_ANALYSIS_SECTION_TITLES = (
    ("overview", "###### Bug \u6982\u8ff0"),
    ("symptoms", "###### \u73b0\u8c61\u4e0e\u4e25\u91cd\u5ea6"),
    ("trigger", "###### \u89e6\u53d1\u6761\u4ef6\u4e0e\u5f71\u54cd"),
    ("root_cause", "###### \u6839\u56e0\u5206\u6790"),
    ("source_evidence", "###### \u6e90\u7801\u8bc1\u636e"),
    ("causal_chain", "###### \u52a8\u6001\u56e0\u679c\u94fe"),
    ("fix", "###### \u4fee\u590d\u5efa\u8bae"),
    ("retest", "###### \u98ce\u9669\u4e0e\u590d\u9a8c"),
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
        confidence_match = re.fullmatch(r"(.+)\uff08(\d{1,3})%\uff09", title)
        if confidence_match is None:
            raise ValueError(
                "BG visible description must end with full-width '(confidence%)' notation"
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
        f"### {title}\u6ce2\u5f62 "
        f"<{waveform_record_tag(test_case_tag)}>"
    )


def parse_waveform_record_heading(line: str) -> tuple[str, str]:
    """Return the canonical TC tag and visible title from a waveform record heading."""

    match = re.fullmatch(r"###\s+(.+?)\s+<(WAVEFORM-TC-[^<>]+)>", str(line).strip())
    if match is None:
        raise ValueError(
            "use a level-3 heading with a visible test description, the required "
            "localized waveform suffix, and <WAVEFORM-TC-...> at line end"
        )
    visible = match.group(1)
    suffix = "\u6ce2\u5f62"
    if not visible.endswith(suffix):
        raise ValueError(
            "waveform record visible description must end with the required localized suffix"
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
