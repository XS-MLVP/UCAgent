import argparse
import os
import re
from typing import List


PROJECT_ROOT = os.getcwd()
SUMMARY_TITLE = "## 一、潜在Bug汇总"
DETAIL_TITLE = "## 二、详细分析"
PROGRESS_TITLE = "## 三、批次分析进度"


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


def find_section_index(lines: List[str], title: str) -> int:
    for idx, line in enumerate(lines):
        if line.strip() == title:
            return idx
    raise ValueError(
        f"Error: section '{title}' not found in target markdown. Please ensure the file format is correct and use `RunSkillScript` tool again."
    )


def find_detail_start_index(lines: List[str]) -> int:
    for idx, line in enumerate(lines):
        if line.strip() == DETAIL_TITLE:
            return idx + 1

    summary_start = find_section_index(lines, SUMMARY_TITLE)
    in_summary_table = False
    summary_end = summary_start
    for idx in range(summary_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("|"):
            in_summary_table = True
            summary_end = idx
            continue
        if in_summary_table and not stripped:
            summary_end = idx
            continue
        if in_summary_table:
            return idx

    raise ValueError(
        "Error: detailed analysis content not found in target markdown. "
        "Please ensure the file format is correct and use `RunSkillScript` tool again."
    )


def collect_bg_tags_from_bug_analysis(lines: List[str]) -> set[str]:
    tags = set()
    pattern = re.compile(r"<(BG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{1,3})>")
    alt_pattern = re.compile(r"^\*\*Bug标签\*\*:\s*(BG-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{1,3})\s*$")
    for line in lines:
        for match in pattern.findall(line):
            tags.add(match)
        alt_match = alt_pattern.match(line.strip())
        if alt_match:
            tags.add(alt_match.group(1))
    return tags


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

    existing_bg_tags = collect_bg_tags_from_bug_analysis(bug_lines)
    missing = [tag for tag in link_targets if tag not in existing_bg_tags]
    if missing:
        raise ValueError(
            "Error: linked BG tag(s) not found in bug_analysis.md: "
            + ", ".join(missing)
            + ". Record the dynamic bug first, then use `RunSkillScript` tool again."
        )


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
    progress_start = find_section_index(lines, PROGRESS_TITLE)
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

    find_section_index(lines, SUMMARY_TITLE)
    find_section_index(lines, PROGRESS_TITLE)
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
