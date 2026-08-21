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
