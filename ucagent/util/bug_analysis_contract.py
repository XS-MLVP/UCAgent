# -*- coding: utf-8 -*-
"""Canonical machine-readable contract for dynamic Bug analysis documents."""

import re


DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
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
    "observed_behavior",
    "source_correlation",
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
