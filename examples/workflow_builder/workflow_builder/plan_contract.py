# -*- coding: utf-8 -*-
"""Append-only implementation-plan contract shared by the WFB tool and checker."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


STAGE_ORDER = (
    "extract_requirements_and_plan",
    "design_workflow_build_config",
    "build_initial_template",
    "verify_tool_generation_loop",
    "design_smoke_business_tool_spec",
    "implement_smoke_business_tool",
    "strengthen_smoke_business_tool_tests",
    "initialize_smoke_workflow",
    "verify_generated_tools_through_mcp",
    "freeze_smoke_baseline",
    "design_complete_runtime_configs",
    "generate_complete_runtime_configs",
    "design_all_business_tool_specs",
    "generate_all_business_tools",
    "run_full_tool_test_suite",
    "design_all_document_specs",
    "generate_all_documentation_and_dependencies",
    "generate_all_reusable_templates",
    "complete_readme_and_makefile",
    "mark_feature_complete",
    "verify_final_requirement_coverage",
    "clean_release_candidate",
    "prepare_and_verify_migration_packages",
    "verify_migrated_release",
)

REQUIRED_RECORD_HEADINGS = (
    "阶段目标",
    "决策与变更",
    "产物与验证证据",
    "问题与处理",
    "后续约束",
)
MIN_RECORD_PROSE = 200

_BLOCK_RE = re.compile(
    r"(?P<begin><!-- WFB-STAGE-PLAN:(?P<index>\d{2}):"
    r"(?P<name>[a-z0-9_]+):BEGIN -->)\n"
    r"前序内容SHA256: `(?P<digest>[0-9a-f]{64})`\n"
    r"(?P<body>.*?)\n"
    r"<!-- WFB-STAGE-PLAN:(?P=index):(?P=name):END -->",
    re.DOTALL,
)


@dataclass(frozen=True)
class PlanRecord:
    index: int
    name: str
    digest: str
    body: str
    start: int
    end: int


def effective_prose_length(text: str) -> int:
    """Count meaningful prose while ignoring Markdown and path punctuation."""
    return len(re.sub(r"[\s`*#\-_:：/<>|()[\]{}]+", "", text))


def parse_records(text: str) -> list[PlanRecord]:
    """Parse all well-formed append-only stage records from a plan."""
    return [
        PlanRecord(
            index=int(match.group("index")),
            name=match.group("name"),
            digest=match.group("digest"),
            body=match.group("body"),
            start=match.start(),
            end=match.end(),
        )
        for match in _BLOCK_RE.finditer(text)
    ]


def validate_records(text: str, current_stage: str) -> dict[str, object]:
    """Return structured append-only plan violations through current_stage."""
    if current_stage not in STAGE_ORDER:
        return {"unknown_stage": current_stage}
    current_index = STAGE_ORDER.index(current_stage)
    expected = list(STAGE_ORDER[: current_index + 1])
    records = parse_records(text)
    actual = [record.name for record in records]
    problems: dict[str, object] = {}
    if actual != expected:
        problems["stage_sequence"] = {"expected": expected, "actual": actual}

    malformed_markers = len(re.findall(r"<!-- WFB-STAGE-PLAN:.*?:BEGIN -->", text)) - len(records)
    if malformed_markers:
        problems["malformed_record_count"] = malformed_markers

    record_errors: dict[str, list[str]] = {}
    for position, record in enumerate(records):
        errors = []
        if record.index != position:
            errors.append(f"index must be {position:02d}")
        prefix_digest = hashlib.sha256(text[: record.start].encode("utf-8")).hexdigest()
        if record.digest != prefix_digest:
            errors.append("previous-content SHA256 does not match")
        compact_body = re.sub(r"\s+", "", record.body)
        missing = [
            heading
            for heading in REQUIRED_RECORD_HEADINGS
            if f"###{heading}" not in compact_body
        ]
        if missing:
            errors.append("missing headings: " + ", ".join(missing))
        prose_length = effective_prose_length(record.body)
        if prose_length < MIN_RECORD_PROSE:
            errors.append(
                f"effective prose must be at least {MIN_RECORD_PROSE}, got {prose_length}"
            )
        if errors:
            record_errors[record.name] = errors
    if record_errors:
        problems["record_errors"] = record_errors
    return problems


def append_record(text: str, stage_name: str, body: str) -> str:
    """Append the next valid stage record and return the complete new text."""
    if stage_name not in STAGE_ORDER:
        raise ValueError(f"unknown workflow-builder stage: {stage_name}")
    stage_index = STAGE_ORDER.index(stage_name)
    records = parse_records(text)
    expected_prior = list(STAGE_ORDER[:stage_index])
    actual_prior = [record.name for record in records]
    if actual_prior != expected_prior:
        raise ValueError(
            f"plan must contain exactly the prior stages {expected_prior}; got {actual_prior}"
        )
    compact_body = re.sub(r"\s+", "", body)
    missing = [
        heading
        for heading in REQUIRED_RECORD_HEADINGS
        if f"###{heading}" not in compact_body
    ]
    if missing:
        raise ValueError("stage record is missing headings: " + ", ".join(missing))
    prose_length = effective_prose_length(body)
    if prose_length < MIN_RECORD_PROSE:
        raise ValueError(
            f"stage record needs at least {MIN_RECORD_PROSE} effective prose characters; "
            f"got {prose_length}"
        )

    separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    prefix = text + separator
    marker = f"{stage_index:02d}:{stage_name}"
    visible_heading = f"## 阶段 {stage_index:02d}：{stage_name}\n\n"
    record_prefix = prefix + visible_heading
    digest = hashlib.sha256(record_prefix.encode("utf-8")).hexdigest()
    return (
        record_prefix
        + f"<!-- WFB-STAGE-PLAN:{marker}:BEGIN -->\n"
        + f"前序内容SHA256: `{digest}`\n"
        + body.strip()
        + "\n"
        + f"<!-- WFB-STAGE-PLAN:{marker}:END -->\n"
    )
