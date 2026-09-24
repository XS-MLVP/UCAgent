"""Spec parser for the Bug Review workflow."""
import hashlib
import logging
import os
import re
from typing import List, Sequence

from .models import SpecProperty, SpecPropertyMatch
from .utils import (
    get_logger,
    infer_signal_names,
    jaccard_score,
    normalised_tokens,
    slugify,
)

logger = get_logger(__name__)


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"`", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" |:\n\t")


def _parse_table_cells(line: str) -> List[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return [_strip_md(cell) for cell in cells]


def _stable_readme_property_id(category: str, key: str, text: str = "") -> str:
    parts = [category, key]
    if text:
        parts.append(text)
    return slugify("_".join(part for part in parts if part))


def _quote_hash(path: str, line_number: int, quote: str) -> str:
    payload = f"{os.path.abspath(path)}:{line_number}:{quote}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normative_role(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in (
        "attempts to", "when ", "if ", "触发", "访问禁用", "访问已禁用",
    )):
        return "trigger"
    if any(token in lowered for token in (
        "should", "must", "shall", "required", "is kept", "immediately",
        "returns", "generated", "必须", "应当", "应该", "保持", "返回", "产生", "生成",
    )):
        return "expected_behavior"
    return "context"


def _semantic_concepts(text: str) -> set:
    lowered = text.lower()
    concepts = set()
    cues = {
        "ifu": ("ifu", "取指"),
        "disabled_target": ("disabled", "disable", "禁用", "未使能", "未 enable"),
        "error_response": ("error", "rsp_err", "错误", "拒绝"),
        "ready_handshake": ("cmd_ready", " ready", "就绪", "握手"),
        "valid_handshake": ("cmd_valid", " valid", "有效"),
        "reset": ("reset", "复位"),
    }
    for concept, tokens in cues.items():
        if any(token in lowered for token in tokens):
            concepts.add(concept)
    return concepts


def parse_dut_readme(path: str) -> List[SpecProperty]:
    if not path or not os.path.exists(path):
        logger.info("DUT README not found or empty path: %s", path)
        return []

    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = handle.readlines()

    properties: List[SpecProperty] = []
    current_heading = ""
    in_interface_table = False
    in_register_table = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        if line.startswith("**") and line.endswith("**"):
            current_heading = _strip_md(line)
        if re.match(r"^#{2,6}\s+", line):
            current_heading = _strip_md(re.sub(r"^#{2,6}\s+", "", line))

        if "Signal Name" in line and "Direction" in line and "Description" in line:
            in_interface_table = True
            in_register_table = False
            continue
        if "Register Name" in line and "Reset Value" in line and "Description" in line:
            in_register_table = True
            in_interface_table = False
            continue
        if line.strip() == "":
            in_interface_table = False
            in_register_table = False

        if in_interface_table and line.strip().startswith("|") and "---" not in line:
            cells = _parse_table_cells(line)
            if len(cells) < 4:
                continue
            signal_name = cells[0]
            description = cells[3]
            if not signal_name or signal_name.lower() == "signal name":
                continue
            properties.append(
                SpecProperty(
                    property_id=_stable_readme_property_id("interface_signal", signal_name),
                    source_path=path,
                    line_start=line_number,
                    line_end=line_number,
                    source_kind="dut_readme",
                    category="interface_signal",
                    title=f"{signal_name} interface description",
                    property_text=description,
                    signal_names=[signal_name],
                )
            )
            continue

        if in_register_table and line.strip().startswith("|") and "---" not in line:
            cells = _parse_table_cells(line)
            if len(cells) < 5:
                continue
            register_name = cells[0]
            reset_value = cells[3]
            description = cells[4]
            if not register_name or register_name.lower() == "register name":
                continue
            signal_name = register_name.split("[", 1)[0]
            property_text = f"{signal_name} reset value should be {reset_value}. {description}"
            properties.append(
                SpecProperty(
                    property_id=_stable_readme_property_id("register_reset", signal_name, reset_value),
                    source_path=path,
                    line_start=line_number,
                    line_end=line_number,
                    source_kind="dut_readme",
                    category="register_reset",
                    title=f"{signal_name} reset value",
                    property_text=property_text,
                    signal_names=[signal_name],
                    trigger="during reset / after reset",
                    expected=reset_value,
                )
            )
            continue

        transition_match = re.match(r"([A-Z_]+):\s*(.+)", _strip_md(line))
        if transition_match:
            state_name = transition_match.group(1)
            description = transition_match.group(2)
            properties.append(
                SpecProperty(
                    property_id=_stable_readme_property_id("state_transition", state_name, description),
                    source_path=path,
                    line_start=line_number,
                    line_end=line_number,
                    source_kind="dut_readme",
                    category="state_transition",
                    title=state_name,
                    property_text=description,
                    signal_names=infer_signal_names(description, []),
                )
            )
            continue

        if "should" in line.lower() and (
            "done" in line.lower() or "reset" in line.lower() or "output" in line.lower()
        ):
            description = _strip_md(line.lstrip("- ").lstrip("0123456789. "))
            properties.append(
                SpecProperty(
                    property_id=_stable_readme_property_id(
                        "behavior_statement",
                        current_heading or "behavior",
                        description,
                    ),
                    source_path=path,
                    line_start=line_number,
                    line_end=line_number,
                    source_kind="dut_readme",
                    category="behavior_statement",
                    title=current_heading or "behavior_statement",
                    property_text=description,
                    signal_names=infer_signal_names(description, []),
                )
            )
            continue

        description = _strip_md(line.lstrip().lstrip("-+* "))
        semantic_role = _normative_role(description)
        if line.lstrip().startswith(("- ", "* ", "+ ")) and semantic_role != "context":
            properties.append(
                SpecProperty(
                    property_id=_stable_readme_property_id(
                        "normative_behavior", current_heading or semantic_role, description
                    ),
                    source_path=path,
                    line_start=line_number,
                    line_end=line_number,
                    source_kind="dut_readme",
                    category="normative_behavior",
                    title=current_heading or semantic_role,
                    property_text=description,
                    signal_names=infer_signal_names(description, []),
                    trigger=description if semantic_role == "trigger" else None,
                    expected=description if semantic_role == "expected_behavior" else None,
                    quote=description,
                    sha256=_quote_hash(path, line_number, description),
                    validation_status="VALIDATED_SOURCE_QUOTE",
                    semantic_role=semantic_role,
                )
            )
    return properties


def build_spec_catalog(dut_readme: str, ck_catalog: dict) -> List[SpecProperty]:
    properties = parse_dut_readme(dut_readme)
    for ck_name, entry in ck_catalog.items():
        description = entry.get("description") or ck_name
        properties.append(
            SpecProperty(
                property_id=slugify(f"{ck_name}_ck"),
                source_path=entry.get("source_path", ""),
                line_start=entry.get("line", 0),
                line_end=entry.get("line", 0),
                source_kind="functions_and_checks",
                category="functional_check",
                title=ck_name,
                property_text=description,
                signal_names=infer_signal_names(description, []),
                linked_ck=ck_name,
            )
        )
    deduped = {}
    for prop in properties:
        key = (prop.source_path, prop.line_start, prop.title, prop.property_text)
        deduped[key] = prop
    return list(deduped.values())


def match_candidate_to_spec_properties(
    property_text: str,
    signal_names: Sequence[str],
    ck_name: str,
    root_cause: str,
    candidate_expected: str,
    spec_properties: Sequence[SpecProperty],
) -> List[SpecPropertyMatch]:
    results: List[SpecPropertyMatch] = []
    candidate_tokens = normalised_tokens(f"{property_text} {root_cause or ''}")
    candidate_concepts = _semantic_concepts(f"{property_text} {root_cause or ''} {candidate_expected or ''}")
    candidate_signals = set(signal_names)

    for prop in spec_properties:
        score = 0.0
        reasons = []
        if ck_name and prop.linked_ck and ck_name == prop.linked_ck:
            score += 5.0
            reasons.append("same CK")
        shared_signals = candidate_signals & set(prop.signal_names)
        if shared_signals:
            score += 2.5 + min(1.5, 0.5 * len(shared_signals))
            reasons.append(f"shared signals: {', '.join(sorted(shared_signals))}")
        text_score = jaccard_score(candidate_tokens, normalised_tokens(prop.property_text))
        if text_score > 0:
            score += text_score * 4.0
            reasons.append(f"text overlap {text_score:.2f}")
        shared_concepts = candidate_concepts & _semantic_concepts(prop.property_text)
        if shared_concepts:
            concept_weights = {"disabled_target": 2.25, "reset": 2.0}
            score += sum(concept_weights.get(item, 1.5) for item in shared_concepts)
            reasons.append(f"shared semantic concepts: {', '.join(sorted(shared_concepts))}")
        if candidate_expected and prop.expected and candidate_expected == prop.expected:
            score += 1.0
            reasons.append("same expected value")
        if prop.trigger and "reset" in prop.trigger.lower() and any(
            item in {"rst", "text_out", "done"} for item in candidate_signals
        ):
            score += 0.5
            reasons.append("compatible trigger")
        if score < 1.2:
            continue
        exact_support = bool(
            prop.validation_status == "VALIDATED_SOURCE_QUOTE"
            and prop.semantic_role in {"trigger", "expected_behavior"}
            and (shared_signals or text_score >= 0.12 or len(shared_concepts) >= 2)
        )
        results.append(
            SpecPropertyMatch(
                property_id=prop.property_id,
                score=round(score, 3),
                source_path=prop.source_path,
                line_start=prop.line_start,
                line_end=prop.line_end,
                property_text=prop.property_text,
                signal_names=prop.signal_names,
                trigger=prop.trigger,
                expected=prop.expected,
                linked_ck=prop.linked_ck,
                match_reason="; ".join(reasons),
                quote=prop.quote or prop.property_text,
                sha256=prop.sha256,
                validation_status=("EXACT_SPEC_SUPPORT" if exact_support else "POSSIBLE_SPEC_SUPPORT"),
                semantic_role=prop.semantic_role,
            )
        )
    results.sort(key=lambda item: (-item.score, item.source_path, item.line_start))
    selected: List[SpecPropertyMatch] = []
    seen_ids = set()

    # Keep the strongest CK-linked match when present.
    ck_linked = next((item for item in results if item.linked_ck), None)
    if ck_linked:
        selected.append(ck_linked)
        seen_ids.add(ck_linked.property_id)

    # Preserve complementary normative roles. A high-scoring interface-table
    # row must not crowd out the exact trigger or expected behavior.
    for role in ("trigger", "expected_behavior"):
        role_match = next(
            (
                item for item in results
                if item.validation_status == "EXACT_SPEC_SUPPORT" and item.semantic_role == role
            ),
            None,
        )
        if role_match and role_match.property_id not in seen_ids and len(selected) < 3:
            selected.append(role_match)
            seen_ids.add(role_match.property_id)

    # Preserve at least one README/spec-derived match when role diversity left
    # room, for cross-run comparability with older specifications.
    readme_linked = next((item for item in results if not item.linked_ck), None)
    if readme_linked and readme_linked.property_id not in seen_ids and len(selected) < 3:
        selected.append(readme_linked)
        seen_ids.add(readme_linked.property_id)

    for item in results:
        if item.property_id in seen_ids:
            continue
        selected.append(item)
        seen_ids.add(item.property_id)
        if len(selected) >= 3:
            break
    return selected[:3]
