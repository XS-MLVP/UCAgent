# -*- coding: utf-8 -*-
"""Canonical machine-readable contract for dynamic Bug analysis documents."""

import hashlib
import json
from pathlib import Path
import posixpath
import re


DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
DYNAMIC_BUGS_END_MARKER = "</DYNAMIC-BUGS>"
ROOT_CAUSES_MARKER = "<ROOT-CAUSES>"
ROOT_CAUSES_END_MARKER = "</ROOT-CAUSES>"
ROOT_CAUSE_ANALYSIS_MARKER = "<ROOT-CAUSE-ANALYSIS>"
ROOT_SOURCE_EVIDENCE_MARKER = "<ROOT-SOURCE-EVIDENCE>"
ROOT_CAUSAL_CHAIN_MARKER = "<ROOT-CAUSAL-CHAIN>"
ROOT_FIX_MARKER = "<ROOT-FIX>"
ROOT_RETEST_MARKER = "<ROOT-RETEST>"
RELATED_BUGS_MARKER = "<RELATED-BUGS>"
RELATED_BUG_TAG_PREFIX = "RELATED-BUG-"
ROOT_CAUSE_REFERENCE_TAG_PREFIX = "CAUSE-REF-"
ROOT_CAUSE_REFERENCE_MARKER = "<CAUSE-REF-ROOT-NAME>"
ROOT_ENTITY_TAG_PATTERN = re.compile(
    r"ROOT-(?!(?:CAUSES|CAUSE-REF|CAUSE-ANALYSIS|SOURCE-EVIDENCE|"
    r"SOURCE-UNAVAILABLE|SOURCE-FIRST-ERROR|SOURCE-PROPAGATION|"
    r"SOURCE-OBSERVABLE|CAUSAL-CHAIN|FIX|RETEST)(?:$|>))"
    r"[A-Z0-9][A-Z0-9-]*"
)
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
ROOT_SOURCE_UNAVAILABLE_MARKER = "<ROOT-SOURCE-UNAVAILABLE>"
ROOT_SOURCE_EVIDENCE_MARKERS = (
    "<ROOT-SOURCE-FIRST-ERROR>",
    "<ROOT-SOURCE-PROPAGATION>",
    "<ROOT-SOURCE-OBSERVABLE>",
)
BUG_ANALYSIS_SECTION_MARKERS = (
    ("overview", "<BUG-OVERVIEW>"),
    ("symptoms", "<BUG-SYMPTOMS>"),
    ("trigger", "<BUG-TRIGGER>"),
)
ROOT_ANALYSIS_SECTION_MARKERS = (
    ("analysis", ROOT_CAUSE_ANALYSIS_MARKER),
    ("source_evidence", ROOT_SOURCE_EVIDENCE_MARKER),
    ("causal_chain", ROOT_CAUSAL_CHAIN_MARKER),
    ("fix", ROOT_FIX_MARKER),
    ("retest", ROOT_RETEST_MARKER),
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
    root_cause_titles = payload.get("root_cause_titles")
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
    if (
        not isinstance(root_cause_titles, dict)
        or list(root_cause_titles)
        != [
            "analysis",
            "source_evidence",
            "causal_chain",
            "fix",
            "retest",
            "related_bugs",
        ]
        or not all(
            isinstance(value, str)
            and value.startswith("#### ")
            and "\n" not in value
            for value in root_cause_titles.values()
        )
    ):
        raise RuntimeError(
            "root_cause_titles must define the canonical ROOT level-4 headings"
        )
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
ROOT_CAUSE_ANALYSIS_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["analysis"]
ROOT_SOURCE_EVIDENCE_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["source_evidence"]
ROOT_CAUSAL_CHAIN_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["causal_chain"]
ROOT_FIX_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["fix"]
ROOT_RETEST_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["retest"]
RELATED_BUGS_TITLE = _LOCALE_CONTRACT["root_cause_titles"]["related_bugs"]
BUG_ANALYSIS_SECTION_TITLES = tuple(
    (key, _LOCALE_CONTRACT["analysis_section_titles"][key])
    for key, _marker in BUG_ANALYSIS_SECTION_MARKERS
)
ROOT_ANALYSIS_SECTION_TITLES = (
    ("analysis", ROOT_CAUSE_ANALYSIS_TITLE),
    ("source_evidence", ROOT_SOURCE_EVIDENCE_TITLE),
    ("causal_chain", ROOT_CAUSAL_CHAIN_TITLE),
    ("fix", ROOT_FIX_TITLE),
    ("retest", ROOT_RETEST_TITLE),
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


def root_cause_anchor_id(root_cause_tag: str) -> str:
    """Return the stable Markdown anchor for one root-cause entity."""

    normalized = str(root_cause_tag or "").strip().strip("<>")
    if ROOT_ENTITY_TAG_PATTERN.fullmatch(normalized) is None:
        raise ValueError("root cause tag must use unique ROOT-NAME form")
    return "root-cause-" + normalized[len("ROOT-") :].lower()


def dynamic_bug_anchor_id(checkpoint_path: str, bug_tag: str) -> str:
    """Return a collision-resistant anchor for one checkpoint-scoped BG path."""

    checkpoint = str(checkpoint_path or "").strip().strip("/")
    bug = str(bug_tag or "").strip().strip("<>")
    if not checkpoint or not re.fullmatch(r"BG-[^<>]+", bug):
        raise ValueError("a BG anchor requires a checkpoint path and BG tag")
    digest = hashlib.sha256(f"{checkpoint}/{bug}".encode("utf-8")).hexdigest()[:16]
    return f"bug-{digest}"


def root_cause_reference(root_cause_tag: str, label: str = "ROOT-CAUSE") -> str:
    """Return the canonical BG-side link to a root-cause entity."""

    tag = str(root_cause_tag or "").strip().strip("<>")
    anchor = root_cause_anchor_id(tag)
    return f"<{ROOT_CAUSE_REFERENCE_TAG_PREFIX}{tag}> [{label}](#{anchor})"


def related_bug_reference(
    checkpoint_path: str,
    bug_tag: str,
) -> str:
    """Return the canonical root-cause-side link to one checkpoint-scoped BG."""

    checkpoint = str(checkpoint_path or "").strip().strip("/")
    parts = checkpoint.split("/")
    if (
        len(parts) != 3
        or not re.fullmatch(r"FG-[^<>/]+", parts[0])
        or not re.fullmatch(r"FC-[^<>/]+", parts[1])
        or not re.fullmatch(r"CK-[^<>/]+", parts[2])
    ):
        raise ValueError("related Bug path must contain exact FG/FC/CK tags")
    bug = str(bug_tag or "").strip().strip("<>")
    anchor = dynamic_bug_anchor_id(checkpoint, bug)
    path = "/".join([*parts, bug])
    return f"- <{RELATED_BUG_TAG_PREFIX}{path}> [{path}](#{anchor})"
