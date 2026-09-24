"""Markdown parser for the Bug Review workflow."""
import logging
import re
from typing import Dict, List, Optional, Tuple

from .models import ClaimRecord, SourceLocation
from .rtl_refs import extract_rtl_lines_from_text, group_line_refs
from .utils import (
    clean_markdown_text,
    extract_local_name,
    extract_local_names,
    get_logger,
    normalize_nodeid,
    slugify,
)

logger = get_logger(__name__)


def parse_functions_and_checks(path: str) -> Dict[str, Dict[str, object]]:
    catalog: Dict[str, Dict[str, object]] = {}
    current_fg = None
    current_fc = None
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            fg = extract_local_name(raw_line, "FG")
            if fg:
                current_fg = fg
            fc = extract_local_name(raw_line, "FC")
            if fc:
                current_fc = fc
            ck = extract_local_name(raw_line, "CK")
            if ck:
                catalog[ck] = {
                    "fg": current_fg,
                    "fc": current_fc,
                    "description": clean_markdown_text(raw_line),
                    "source_path": path,
                    "line": line_number,
                }
    return catalog


_LOCAL_FIELD_LABELS = (
    "Bug根本原因", "Bug 根本原因", "Bug根因分析", "Bug 根因分析",
    "根本原因", "根因分析", "根因", "Root cause", "Root cause analysis",
    "修复建议", "修复方案", "Proposed fix", "Fix",
    "预期", "Expected", "实际观测", "Observed",
    "失效测试用例", "失败测试用例", "Failing tests",
)


def _field_line_match(line: str, labels: Tuple[str, ...]) -> Optional[Tuple[str, str]]:
    """Match common Markdown field spellings without crossing BG blocks.

    Colons may be ASCII/full-width and may appear inside or outside the bold
    markers, for example ``**根本原因：**`` and ``**根本原因**:``.
    """
    ordered = sorted(labels, key=len, reverse=True)
    label_pattern = "|".join(re.escape(item) for item in ordered)
    bold = re.match(
        rf"^\s*(?:[-*+]\s*)?\*\*\s*({label_pattern})\s*([：:]?)\s*\*\*\s*([：:]?)\s*(.*)$",
        line, flags=re.I,
    )
    if bold and (bold.group(2) or bold.group(3)):
        return bold.group(1), bold.group(4)
    plain = re.match(
        rf"^\s*(?:[-*+]\s*)?({label_pattern})\s*[：:]\s*(.*)$",
        line, flags=re.I,
    )
    return (plain.group(1), plain.group(2)) if plain else None


def _extract_marked_value(labels: object, text: str) -> str:
    wanted = (labels,) if isinstance(labels, str) else tuple(labels)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _field_line_match(line, wanted)
        if not match:
            continue
        collected = [match[1]] if match[1].strip() else []
        for continuation in lines[index + 1:]:
            stripped = continuation.strip()
            if stripped.startswith(("## ", "### ", "#### ", "##### ")):
                break
            if _extract_bg_fields(continuation)[0] or _field_line_match(continuation, _LOCAL_FIELD_LABELS):
                break
            collected.append(continuation)
        return clean_markdown_text("\n".join(collected).strip())
    return ""


def _extract_tagged_bug_field(tag: str, text: str) -> str:
    """Extract a UCAgent ``<BUG-...>`` field from one BG block.

    UCAgent's current report contract stores field values on the lines after
    the tag, rather than on the heading line.  This is deliberately parsed
    structurally, without a semantic model.
    """
    match = re.search(rf"(?m)^\s*<{re.escape(tag)}>\s*$", text or "")
    if not match:
        return ""
    body = (text or "")[match.end():]
    end = re.search(r"(?m)^#{1,6}\s+|^\s*</?BUG-[A-Z-]+>\s*$", body)
    if end:
        body = body[:end.start()]
    return clean_markdown_text(body.strip())


def _extract_bg_fields(text: str) -> Tuple[Optional[str], Optional[int]]:
    match = re.search(r"<BG-([A-Za-z0-9_-]+?)-(\d+)>", text)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def derive_bug_identity(
    fg: Optional[str],
    fc: Optional[str],
    ck: Optional[str],
    bg_name: str,
) -> Tuple[str, str]:
    if fg and fc:
        parts = [fg, fc]
        if ck:
            parts.append(ck)
        return "/".join(parts), "ck_path"
    return bg_name, "bg_name"


def _extract_root_cause_rtl_refs(lines: List[str]) -> Dict[str, List[Dict[str, object]]]:
    root_heading_index = None
    for index, line in enumerate(lines):
        if line.strip().startswith("## 缺陷根因分析"):
            root_heading_index = index
            break
    if root_heading_index is None:
        return {}

    root_lines = lines[root_heading_index:]
    section_ranges: List[Tuple[int, int]] = []
    section_start = None
    for index, line in enumerate(root_lines):
        if line.startswith("### "):
            if section_start is not None:
                section_ranges.append((section_start, index))
            section_start = index
    if section_start is not None:
        section_ranges.append((section_start, len(root_lines)))

    refs_by_identity: Dict[str, List[Dict[str, object]]] = {}
    for start, end in section_ranges:
        section_text = "".join(root_lines[start:end])
        line_refs, _ = extract_rtl_lines_from_text(section_text)
        rtl_regions = [
            {
                "path": region.path,
                "line_start": region.line_start,
                "line_end": region.line_end,
                "reason": region.reason,
                "evidence": region.evidence,
            }
            for region in group_line_refs(
                line_refs,
                "root_cause_rtl_reference",
                "bug_analysis_root_cause",
            )
        ]
        if not rtl_regions:
            continue
        for fg, fc, ck in re.findall(
            r"(FG-[A-Za-z0-9_-]+)/(FC-[A-Za-z0-9_-]+)/(CK-[A-Za-z0-9_-]+)",
            section_text,
        ):
            bug_identity, _ = derive_bug_identity(fg, fc, ck, "")
            refs_by_identity.setdefault(bug_identity, [])
            existing = {
                (item["path"], item["line_start"], item["line_end"])
                for item in refs_by_identity[bug_identity]
            }
            for item in rtl_regions:
                key = (item["path"], item["line_start"], item["line_end"])
                if key not in existing:
                    refs_by_identity[bug_identity].append(item)
                    existing.add(key)
    return refs_by_identity


def parse_bug_claims(path: str, run_key: str, model: str, dut: str) -> List[ClaimRecord]:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = handle.readlines()

    claims_by_identity: Dict[str, ClaimRecord] = {}
    current_fg = None
    current_fc = None
    current_ck = None

    def upsert_claim(
        bg_name: str,
        start_line: int,
        end_line: int,
        block_lines: List[str],
        block_fg: str,
        block_fc: str,
        block_ck: str,
    ) -> None:
        text = "".join(block_lines).strip()
        referenced_tests = [
            normalize_nodeid(match.group(1))
            for match in re.finditer(r"<TC-([^>]+)>", text)
        ]
        cleaned_summary = clean_markdown_text(block_lines[0])
        cleaned_summary = re.sub(r"Bug 置信度\s*\d+%.*", "", cleaned_summary).strip()
        tag_bg_name, tag_confidence = _extract_bg_fields(text)
        confidence_match = re.search(r"Bug 置信度\s*(\d+)%", text)
        confidence = int(confidence_match.group(1)) if confidence_match else tag_confidence
        root_cause = _extract_marked_value(
            (
                "Bug根本原因", "Bug 根本原因", "Bug根因分析", "Bug 根因分析",
                "根本原因", "根因分析", "根因", "Root cause", "Root cause analysis",
            ),
            text,
        ) or _extract_tagged_bug_field("BUG-ROOT-CAUSE", text) or None
        proposed_fix = _extract_marked_value(
            ("修复建议", "修复方案", "Proposed fix", "Fix"), text
        ) or None
        expected = _extract_marked_value(("预期", "Expected"), text) or None
        observed = _extract_marked_value(("实际观测", "Observed"), text) or None
        parse_diagnostics = []
        if confidence and confidence > 0 and re.search(r"(?:根本原因|根因|Root\s+cause)", text, re.I) and not root_cause:
            parse_diagnostics.append("ROOT_CAUSE_PARSE_MISSING")
        normalized_bg_name = tag_bg_name or bg_name
        bug_identity, identity_type = derive_bug_identity(block_fg, block_fc, block_ck, normalized_bg_name)

        line_refs, _ = extract_rtl_lines_from_text(text)
        rtl_regions = [
            {
                "path": region.path,
                "line_start": region.line_start,
                "line_end": region.line_end,
                "reason": region.reason,
                "evidence": region.evidence,
            }
            for region in group_line_refs(line_refs, "report_rtl_reference", "bug_analysis")
        ]

        claim = claims_by_identity.get(bug_identity)
        if not claim:
            claim = ClaimRecord(
                claim_id=slugify(f"{run_key}_{bug_identity}"),
                run_key=run_key,
                model=model,
                dut=dut,
                summary=cleaned_summary,
                source_location=SourceLocation(path=path, line_start=start_line, line_end=end_line, original_text=text),
                fg=block_fg,
                fc=block_fc,
                ck=block_ck,
                confidence_percent=confidence,
                root_cause=root_cause,
                proposed_fix=proposed_fix,
                expected=expected,
                observed=observed,
                parse_diagnostics=parse_diagnostics,
                proposed_rtl_refs=rtl_regions,
                bg_name=normalized_bg_name,
                bug_identity=bug_identity,
                identity_type=identity_type,
            )
            claims_by_identity[bug_identity] = claim
        claim.local_names = sorted(set(claim.local_names + extract_local_names(text)))
        claim.referenced_tests = sorted(set(claim.referenced_tests + referenced_tests))
        claim.source_location.line_end = max(claim.source_location.line_end, end_line)
        if block_fg and not claim.fg:
            claim.fg = block_fg
        if block_fc and not claim.fc:
            claim.fc = block_fc
        if block_ck and not claim.ck:
            claim.ck = block_ck
        if normalized_bg_name and not claim.bg_name:
            claim.bg_name = normalized_bg_name
        if confidence is not None and (
            claim.confidence_percent is None or confidence > claim.confidence_percent
        ):
            claim.confidence_percent = confidence
        if root_cause and not claim.root_cause:
            claim.root_cause = root_cause
        if proposed_fix and not claim.proposed_fix:
            claim.proposed_fix = proposed_fix
        if expected and not claim.expected:
            claim.expected = expected
        if observed and not claim.observed:
            claim.observed = observed
        claim.parse_diagnostics = sorted(set(claim.parse_diagnostics + parse_diagnostics))
        if rtl_regions:
            existing = {(item["path"], item["line_start"], item["line_end"]) for item in claim.proposed_rtl_refs}
            for item in rtl_regions:
                key = (item["path"], item["line_start"], item["line_end"])
                if key not in existing:
                    claim.proposed_rtl_refs.append(item)

    index = 0
    while index < len(lines):
        line = lines[index]
        fg = extract_local_name(line, "FG")
        if fg:
            current_fg = fg
        fc = extract_local_name(line, "FC")
        if fc:
            current_fc = fc
        ck = extract_local_name(line, "CK")
        if ck:
            current_ck = ck

        bg_name, _ = _extract_bg_fields(line)
        if bg_name:
            start_line = index + 1
            end_index = index + 1
            while end_index < len(lines):
                next_line = lines[end_index]
                next_bg, _ = _extract_bg_fields(next_line)
                same_or_higher_heading = (
                    next_line.startswith("#### ")
                    or next_line.startswith("### ")
                    or next_line.startswith("## ")
                )
                next_fg = extract_local_name(next_line, "FG")
                next_fc = extract_local_name(next_line, "FC")
                bullet_claim = next_line.lstrip().startswith("- <CK-") and next_bg and end_index > index
                if bullet_claim or next_fg or next_fc or same_or_higher_heading and end_index > index:
                    break
                end_index += 1
            upsert_claim(
                bg_name=bg_name,
                start_line=start_line,
                end_line=end_index,
                block_lines=lines[index:end_index],
                block_fg=current_fg,
                block_fc=current_fc,
                block_ck=current_ck or ck,
            )
            index = end_index
            continue
        index += 1

    root_cause_refs = _extract_root_cause_rtl_refs(lines)
    for bug_identity, rtl_regions in root_cause_refs.items():
        claim = claims_by_identity.get(bug_identity)
        if not claim:
            continue
        existing = {(item["path"], item["line_start"], item["line_end"]) for item in claim.proposed_rtl_refs}
        for item in rtl_regions:
            key = (item["path"], item["line_start"], item["line_end"])
            if key not in existing:
                claim.proposed_rtl_refs.append(item)
                existing.add(key)

    return list(claims_by_identity.values())
