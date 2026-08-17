import argparse
import os
import re
import textwrap
from typing import List

import yaml


PROJECT_ROOT = os.getcwd()
DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
STATIC_BUG_SUMMARY_MARKER = "<STATIC-BUG-SUMMARY>"
STATIC_BUG_DETAILS_MARKER = "<STATIC-BUG-DETAILS>"
STATIC_BUG_PROGRESS_MARKER = "<STATIC-BUG-PROGRESS>"
DYNAMIC_BUG_TODO_MARKER = "<BUG-TODO>"
DYNAMIC_BUG_SOURCE_UNAVAILABLE_MARKER = "<BUG-SOURCE-UNAVAILABLE>"
DYNAMIC_BUG_SECTION_MARKERS = (
    ("overview", "<BUG-OVERVIEW>"),
    ("symptoms", "<BUG-SYMPTOMS>"),
    ("trigger", "<BUG-TRIGGER>"),
    ("root_cause", "<BUG-ROOT-CAUSE>"),
    ("source_evidence", "<BUG-SOURCE-EVIDENCE>"),
    ("causal_chain", "<BUG-CAUSAL-CHAIN>"),
    ("fix", "<BUG-FIX>"),
    ("retest", "<BUG-RETEST>"),
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Update the LINK-BUG relation of one BG-STATIC entry in "
            "{DUT}_static_bug_analysis.md."
        )
    )
    parser.add_argument(
        "-SBG",
        required=True,
        help="Static bug tag in static_bug_analysis.md, e.g. BG-STATIC-001-ADD-OVERFLOW",
    )
    parser.add_argument(
        "-LBG",
        required=True,
        help=(
            "Linked dynamic bug tag(s). Use one BG tag, BG-NA, or multiple "
            "BG tags joined by commas, e.g. BG-ADD-OVERFLOW-90,BG-ADD-CARRY-85"
        ),
    )
    return parser.parse_args()


def validate_static_bg(static_bg: str) -> None:
    if not re.fullmatch(r"BG-STATIC-\d{3}-[A-Z0-9]+(?:-[A-Z0-9]+)*", static_bg):
        raise ValueError(
            f"Error: -SBG parameter '{static_bg}' format invalid, should be "
            f"'BG-STATIC-NNN-NAME'. Modify the tag and use `RunSkillScript` tool again."
        )


def parse_link_targets(raw_link_bg: str) -> List[str]:
    raw_link_bg = raw_link_bg.strip()
    if not raw_link_bg:
        raise ValueError(
            "Error: -LBG parameter is empty. Modify the parameter and use `RunSkillScript` tool again."
        )

    targets = [item.strip() for item in raw_link_bg.split(",") if item.strip()]
    if not targets:
        raise ValueError(
            "Error: -LBG parameter is empty after parsing. Modify the parameter and use `RunSkillScript` tool again."
        )

    if "BG-NA" in targets:
        if len(targets) != 1:
            raise ValueError(
                "Error: BG-NA cannot be mixed with other BG tags in -LBG. Modify the parameter and use `RunSkillScript` tool again."
            )
        return targets

    seen = set()
    normalized = []
    for tag in targets:
        if tag.startswith("BG-STATIC-"):
            raise ValueError(
                f"Error: linked BG tag '{tag}' is a static Bug tag. -LBG must "
                "reference the distinct BG-NAME-xx tag created in the dynamic "
                "bug_analysis.md document."
            )
        if not re.fullmatch(r"BG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{1,3}", tag):
            raise ValueError(
                f"Error: linked BG tag '{tag}' format invalid. Expected 'BG-NAME-xx' "
                f"or 'BG-NA'. Modify the parameter and use `RunSkillScript` tool again."
            )
        if tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def build_link_payload(link_targets: List[str]) -> str:
    return "".join(f"[{tag}]" for tag in link_targets)


def get_target_md_path() -> str:
    dut = os.environ.get("DUT")
    out_dir = os.environ.get("OUT")
    if not dut or not out_dir:
        raise ValueError(
            "Error: environment variable DUT or OUT is missing. Please run this script via `RunSkillScript`."
        )

    path = os.path.join(PROJECT_ROOT, out_dir, f"{dut}_static_bug_analysis.md")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Error: target file not found: {path}. Please ensure static bug analysis has been generated first."
        )
    return path


def get_bug_analysis_md_path() -> str:
    dut = os.environ.get("DUT")
    out_dir = os.environ.get("OUT")
    if not dut or not out_dir:
        raise ValueError(
            "Error: environment variable DUT or OUT is missing. Please run this script via `RunSkillScript`."
        )

    path = os.path.join(PROJECT_ROOT, out_dir, f"{dut}_bug_analysis.md")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Error: target file not found: {path}. Please ensure bug analysis has been generated first."
        )
    return path


def find_marker_index(lines: List[str], marker: str) -> int:
    matches = [idx for idx, line in enumerate(lines) if line.strip() == marker]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"Error: marker '{marker}' must occur exactly once in target markdown; "
        f"found {len(matches)} occurrence(s). Use the canonical tagged format."
    )


def find_detail_start_index(lines: List[str]) -> int:
    summary_start = find_marker_index(lines, STATIC_BUG_SUMMARY_MARKER)
    detail_start = find_marker_index(lines, STATIC_BUG_DETAILS_MARKER)
    progress_start = find_marker_index(lines, STATIC_BUG_PROGRESS_MARKER)
    if not summary_start < detail_start < progress_start:
        raise ValueError(
            "Error: static Bug section markers are out of canonical order; expected "
            f"{STATIC_BUG_SUMMARY_MARKER} -> {STATIC_BUG_DETAILS_MARKER} -> "
            f"{STATIC_BUG_PROGRESS_MARKER}."
        )
    return detail_start + 1


def collect_bg_tags_from_bug_analysis(lines: List[str]) -> set[str]:
    tags = set()
    pattern = re.compile(r"<(BG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{1,3})>")
    for line in lines:
        for match in pattern.findall(line):
            tags.add(match)
    return tags


def collect_dynamic_bg_blocks(lines: List[str], target_bg: str) -> List[str]:
    blocks = []
    tag_pattern = re.compile(r"<(FG|FC|CK|BG)-([^<>]+)>")
    start = None
    fence_open = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence_open = not fence_open
            continue
        if fence_open:
            continue
        matches = list(tag_pattern.finditer(line))
        boundary_matches = [
            match for match in matches if match.group(1) in {"FG", "FC", "CK", "BG"}
        ]
        if start is not None and boundary_matches:
            blocks.append("".join(lines[start:index]))
            start = None
        if any(
            match.group(1) == "BG" and f"BG-{match.group(2)}" == target_bg
            for match in matches
        ):
            start = index
    if start is not None:
        blocks.append("".join(lines[start:]))
    return blocks


def parse_dynamic_bug_sections(block: str) -> tuple[dict[str, str], List[str]]:
    matches_by_key = {}
    problems = []
    for key, marker in DYNAMIC_BUG_SECTION_MARKERS:
        matches = list(
            re.finditer(rf"(?m)^[ \t]*{re.escape(marker)}[ \t]*$", block)
        )
        if len(matches) != 1:
            problems.append(f"{marker} occurs {len(matches)} time(s)")
        else:
            matches_by_key[key] = matches[0]

    if len(matches_by_key) != len(DYNAMIC_BUG_SECTION_MARKERS):
        return {}, problems

    expected_keys = [key for key, _marker in DYNAMIC_BUG_SECTION_MARKERS]
    ordered = sorted(matches_by_key.items(), key=lambda item: item[1].start())
    if [key for key, _match in ordered] != expected_keys:
        problems.append(
            "markers are out of canonical order; expected "
            + " -> ".join(marker for _key, marker in DYNAMIC_BUG_SECTION_MARKERS)
        )
        return {}, problems

    sections = {}
    for index, (key, match) in enumerate(ordered):
        content_end = (
            ordered[index + 1][1].start()
            if index + 1 < len(ordered)
            else len(block)
        )
        sections[key] = block[match.end() : content_end].strip()
    return sections, problems


def has_dynamic_bug_field_content(content: str) -> bool:
    without_display_headings = re.sub(
        r"(?m)^[ \t]*(?:#{1,6}[ \t]+.+|\*\*[^*\n]+\*\*)[ \t]*$",
        "",
        content,
    )
    without_optional_markers = re.sub(
        rf"(?m)^[ \t]*(?:{re.escape(DYNAMIC_BUG_SOURCE_UNAVAILABLE_MARKER)}|"
        rf"{re.escape(DYNAMIC_BUG_TODO_MARKER)})[ \t]*$",
        "",
        without_display_headings,
    )
    return bool(re.sub(r"\s+", "", without_optional_markers))


def has_confirmed_waveform_analysis(block: str) -> bool:
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "```yaml":
            index += 1
            continue
        payload_lines = []
        index += 1
        while index < len(lines) and lines[index].strip() != "```":
            payload_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            return False
        try:
            payload = yaml.safe_load(textwrap.dedent("\n".join(payload_lines)))
        except yaml.YAMLError:
            index += 1
            continue
        if (
            isinstance(payload, dict)
            and set(payload) == {"waveform_analysis"}
            and isinstance(payload["waveform_analysis"], dict)
            and payload["waveform_analysis"].get("status") == "confirmed"
        ):
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and re.fullmatch(
                r"\s*<WAVEFORM-VIEWER>\s+\[[^\]\r\n]+\]"
                r"\(/surfer/\?wave=[A-Za-z0-9_-]+\)\s*",
                lines[index],
            ):
                return True
        index += 1
    return False


def ensure_dynamic_bg_complete(lines: List[str], target_bg: str) -> None:
    blocks = collect_dynamic_bg_blocks(lines, target_bg)
    if not blocks:
        raise ValueError(
            f"Error: linked BG tag '{target_bg}' has no canonical dynamic Bug block."
        )
    for block in blocks:
        sections, marker_problems = parse_dynamic_bug_sections(block)
        empty_fields = [
            key
            for key, content in sections.items()
            if not has_dynamic_bug_field_content(content)
        ]
        has_todo = DYNAMIC_BUG_TODO_MARKER in block
        missing_waveform = not has_confirmed_waveform_analysis(block)
        if marker_problems or empty_fields or has_todo or missing_waveform:
            detail = (
                "invalid markers: " + "; ".join(marker_problems)
                if marker_problems
                else "empty analysis fields: " + ", ".join(empty_fields)
                if empty_fields
                else f"unfinished marker {DYNAMIC_BUG_TODO_MARKER!r} remains"
                if has_todo
                else "confirmed waveform_analysis or its WAVEFORM-VIEWER link is missing"
            )
            raise ValueError(
                f"Error: linked BG tag '{target_bg}' is only an incomplete scaffold ({detail}). "
                "Fill its real WaveInfo evidence and all analysis fields before linking."
            )


def ensure_static_bg_exists_in_static_report(lines: List[str], static_bg: str) -> None:
    summary_found = False
    detail_found = False
    for line in lines:
        if f"| {static_bg} |" in line:
            summary_found = True
            break
    for line in lines:
        if f"<{static_bg}>" in line:
            detail_found = True
            break

    if not summary_found:
        raise ValueError(
            f"Error: static bug '{static_bg}' not found in summary table of static_bug_analysis.md. "
            f"Please use the correct tag and use `RunSkillScript` tool again."
        )
    if not detail_found:
        raise ValueError(
            f"Error: static bug '{static_bg}' not found in detailed analysis of static_bug_analysis.md. "
            f"Please use the correct tag and use `RunSkillScript` tool again."
        )


def ensure_link_targets_exist_in_bug_analysis(link_targets: List[str], bug_analysis_path: str) -> None:
    if link_targets == ["BG-NA"]:
        return

    with open(bug_analysis_path, "r", encoding="utf-8") as f:
        bug_lines = f.readlines()

    container_lines = [
        index + 1
        for index, line in enumerate(bug_lines)
        if line.strip() == DYNAMIC_BUGS_MARKER
    ]
    if len(container_lines) != 1:
        raise ValueError(
            f"Error: dynamic Bug document marker '{DYNAMIC_BUGS_MARKER}' must occur "
            f"on a standalone line exactly once; found {len(container_lines)} occurrence(s)."
        )

    existing_bg_tags = collect_bg_tags_from_bug_analysis(bug_lines)
    missing = [tag for tag in link_targets if tag not in existing_bg_tags]
    if missing:
        raise ValueError(
            "Error: linked BG tag(s) not found in bug_analysis.md: "
            + ", ".join(missing)
            + ". Record the dynamic bug first, then use `RunSkillScript` tool again."
        )
    for tag in link_targets:
        ensure_dynamic_bg_complete(bug_lines, tag)


def update_summary_table(lines: List[str], static_bg: str, summary_value: str) -> bool:
    row_pattern = re.compile(
        rf"^(\|\s*[^|]+\|\s*{re.escape(static_bg)}\s*\|.*?\|\s*)([^|]+?)(\s*\|\s*)$"
    )
    updated = False
    for idx, line in enumerate(lines):
        match = row_pattern.match(line.rstrip("\n"))
        if not match:
            continue
        lines[idx] = f"{match.group(1)}{summary_value}{match.group(3)}\n"
        updated = True
        break
    return updated


def find_bg_detail_range(lines: List[str], static_bg: str, detail_start: int, detail_end: int):
    bg_token = f"<{static_bg}>"
    bg_line_idx = -1
    for idx in range(detail_start, detail_end):
        if bg_token in lines[idx]:
            bg_line_idx = idx
            break

    if bg_line_idx < 0:
        return -1, -1

    end_idx = detail_end
    boundary_pattern = re.compile(r"<(?:FG|FC|CK|BG-STATIC)-")
    for idx in range(bg_line_idx + 1, detail_end):
        if boundary_pattern.search(lines[idx]):
            end_idx = idx
            break

    return bg_line_idx, end_idx


def update_detail_link(lines: List[str], static_bg: str, detail_value: str) -> bool:
    detail_start = find_detail_start_index(lines)
    progress_start = find_marker_index(lines, STATIC_BUG_PROGRESS_MARKER)
    bg_line_idx, bg_end_idx = find_bg_detail_range(lines, static_bg, detail_start, progress_start)
    if bg_line_idx < 0:
        return False

    link_pattern = re.compile(r"<LINK-BUG-\[(.*?)\]>")
    link_line_idx = -1
    for idx in range(bg_line_idx + 1, bg_end_idx):
        if link_pattern.search(lines[idx]):
            link_line_idx = idx
            break

    if link_line_idx < 0:
        raise ValueError(
            f"Error: no LINK-BUG tag found under <{static_bg}> in detailed analysis. "
            f"Please ensure the file format is correct and use `RunSkillScript` tool again."
        )

    original_line = lines[link_line_idx]
    new_line, count = link_pattern.subn(f"<LINK-BUG-{detail_value}>", original_line, count=1)
    if count != 1:
        raise ValueError(
            f"Error: failed to replace LINK-BUG tag under <{static_bg}>. "
            f"Please ensure the file format is correct and use `RunSkillScript` tool again."
        )
    lines[link_line_idx] = new_line
    return True


def update_static_bug_link(target_md: str, static_bg: str, link_targets: List[str]) -> str:
    summary_value = f"LINK-BUG-{build_link_payload(link_targets)}"
    detail_value = build_link_payload(link_targets)

    with open(target_md, "r", encoding="utf-8") as f:
        lines = f.readlines()

    find_marker_index(lines, STATIC_BUG_SUMMARY_MARKER)
    find_marker_index(lines, STATIC_BUG_PROGRESS_MARKER)
    find_detail_start_index(lines)
    ensure_static_bg_exists_in_static_report(lines, static_bg)

    summary_updated = update_summary_table(lines, static_bg, summary_value)
    if not summary_updated:
        raise ValueError(
            f"Error: static bug '{static_bg}' not found in summary table. "
            f"Please use the correct tag and use `RunSkillScript` tool again."
        )

    detail_updated = update_detail_link(lines, static_bg, detail_value)
    if not detail_updated:
        raise ValueError(
            f"Error: static bug '{static_bg}' not found in detailed analysis. "
            f"Please use the correct tag and use `RunSkillScript` tool again."
        )

    with open(target_md, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return (
        f"Successfully linked {static_bg} to {summary_value} in "
        f"{os.path.relpath(target_md, PROJECT_ROOT)}"
    )


def main():
    args = parse_args()
    validate_static_bg(args.SBG)
    link_targets = parse_link_targets(args.LBG)
    target_md = get_target_md_path()
    bug_analysis_md = get_bug_analysis_md_path()
    ensure_link_targets_exist_in_bug_analysis(link_targets, bug_analysis_md)
    print(update_static_bug_link(target_md, args.SBG, link_targets))


if __name__ == "__main__":
    main()
