import argparse
import json
import os
import re
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = os.getcwd()
SECTION_TITLE = "## 功能点与检测点"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Insert FG/FC/CK entries into {DUT}_functions_and_checks.md in batch."
        )
    )
    parser.add_argument(
        "-MODE",
        required=True,
        choices=["FG", "FC", "CK"],
        help="Insertion mode: FG, FC, or CK.",
    )
    parser.add_argument(
        "-ITEMS",
        required=True,
        help=(
            "JSON list of items. FG items need fg/desc and optional title. "
            "FC items need fc/desc and optional title. CK items need ck/desc."
        ),
    )
    parser.add_argument(
        "-FG",
        default="",
        help="Parent FG tag used in FC/CK mode, e.g. FG-API.",
    )
    parser.add_argument(
        "-FC",
        default="",
        help="Parent FC tag used in CK mode, e.g. FC-OPERATION.",
    )
    return parser.parse_args()


def load_doc_path() -> str:
    dut = os.environ.get("DUT")
    out_dir = os.environ.get("OUT")
    if not dut or not out_dir:
        raise ValueError(
            "Error: environment variable DUT or OUT is missing. Run this script via `RunSkillScript`."
        )

    path = os.path.join(PROJECT_ROOT, out_dir, f"{dut}_functions_and_checks.md")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Error: target file not found: {path}. Please create the base document first."
        )
    return path


def validate_tag(tag: str, prefix: str) -> None:
    if not re.fullmatch(rf"{prefix}-[A-Z0-9]+(?:-[A-Z0-9]+)*", tag):
        raise ValueError(
            f"Error: {prefix} tag format invalid: {tag}. Modify the tag and use `RunSkillScript` again."
        )


def parse_items(raw_items: str) -> List[Dict[str, Any]]:
    try:
        items = json.loads(raw_items)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Error: -ITEMS must be valid JSON, e.g. "
            "'[{\"fg\":\"FG-API\",\"desc\":\"...\"}]'."
        ) from exc
    if not isinstance(items, list) or not items:
        raise ValueError("Error: -ITEMS must be a non-empty JSON list.")
    return items


def split_lines(text: str) -> List[str]:
    if not text.endswith("\n"):
        text += "\n"
    return text.splitlines(keepends=True)


def title_from_tag(tag: str, kind: str) -> str:
    suffix = tag.split("-", 1)[1].replace("-", " ")
    return f"{suffix} {kind}"

def get_section_bounds(lines: List[str]) -> Tuple[int, int]:
    start = -1
    for idx, line in enumerate(lines):
        if line.strip() == SECTION_TITLE:
            start = idx
            break
    if start < 0:
        raise ValueError(
            f"Error: section '{SECTION_TITLE}' not found in target markdown."
        )

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return start, end


def is_fg_line(line: str) -> bool:
    return bool(re.fullmatch(r"\s*<FG-[A-Z0-9]+(?:-[A-Z0-9]+)*>\s*", line))


def is_fc_line(line: str) -> bool:
    return bool(re.fullmatch(r"\s*<FC-[A-Z0-9]+(?:-[A-Z0-9]+)*>\s*", line))


def exact_tag_line(tag: str) -> str:
    return f"<{tag}>"


def find_tag_index(lines: List[str], start: int, end: int, tag: str) -> int:
    token = exact_tag_line(tag)
    for idx in range(start, end):
        if lines[idx].strip() == token:
            return idx
    return -1


def find_next_boundary(lines: List[str], start: int, end: int, predicates) -> int:
    for idx in range(start, end):
        line = lines[idx]
        if any(predicate(line) for predicate in predicates):
            return adjust_boundary_start(lines, idx, start)
    return end


def adjust_boundary_start(lines: List[str], boundary_idx: int, lower_bound: int) -> int:
    idx = boundary_idx
    while idx > lower_bound and not lines[idx - 1].strip():
        idx -= 1

    if idx > lower_bound and re.fullmatch(r"#{3,6}\s+.+", lines[idx - 1].strip()):
        idx -= 1
        while idx > lower_bound and not lines[idx - 1].strip():
            idx -= 1
    return idx


def ensure_unique(tags: List[str], scope_desc: str) -> None:
    seen = set()
    for tag in tags:
        if tag in seen:
            raise ValueError(
                f"Error: duplicate tag '{tag}' found in {scope_desc}. Use unique tags and try again."
            )
        seen.add(tag)


def make_fg_block(item: Dict[str, Any]) -> List[str]:
    fg = item["fg"]
    desc = str(item["desc"]).strip()
    title = str(item.get("title") or title_from_tag(fg, "功能组")).strip()
    return split_lines(
        f"\n### {title}\n\n<{fg}>\n\n{desc}\n"
    )


def make_fc_block(item: Dict[str, Any]) -> List[str]:
    fc = item["fc"]
    desc = str(item["desc"]).strip()
    title = str(item.get("title") or title_from_tag(fc, "功能点")).strip()
    return split_lines(
        f"\n#### {title}\n\n<{fc}>\n\n{desc}\n"
    )


def make_ck_lines(items: List[Dict[str, Any]]) -> List[str]:
    lines = ["\n", "**检测点：**\n", "\n"]
    for item in items:
        ck = item["ck"]
        desc = str(item["desc"]).strip()
        lines.append(f"- <{ck}> {desc}\n")
    return lines


def update_fg(lines: List[str], items: List[Dict[str, Any]]) -> str:
    section_start, section_end = get_section_bounds(lines)
    for item in items:
        fg = item.get("fg")
        desc = item.get("desc")
        if not fg or desc is None:
            raise ValueError("Error: FG items must contain 'fg' and 'desc'.")
        validate_tag(fg, "FG")
        if find_tag_index(lines, section_start + 1, section_end, fg) >= 0:
            raise ValueError(
                f"Error: FG tag '{fg}' already exists in {SECTION_TITLE}. Use a new tag and try again."
            )

    insert_at = section_end
    block = []
    for item in items:
        block.extend(make_fg_block(item))
    lines[insert_at:insert_at] = block
    return f"Inserted {len(items)} FG item(s)."


def update_fc(lines: List[str], fg_tag: str, items: List[Dict[str, Any]]) -> str:
    validate_tag(fg_tag, "FG")
    section_start, section_end = get_section_bounds(lines)
    fg_idx = find_tag_index(lines, section_start + 1, section_end, fg_tag)
    if fg_idx < 0:
        raise ValueError(
            f"Error: parent FG tag '{fg_tag}' not found. Insert the FG block first and try again."
        )

    fg_end = find_next_boundary(lines, fg_idx + 1, section_end, [is_fg_line])
    for item in items:
        fc = item.get("fc")
        desc = item.get("desc")
        if not fc or desc is None:
            raise ValueError("Error: FC items must contain 'fc' and 'desc'.")
        validate_tag(fc, "FC")
        if find_tag_index(lines, fg_idx + 1, fg_end, fc) >= 0:
            raise ValueError(
                f"Error: FC tag '{fc}' already exists under '{fg_tag}'. Use a new tag and try again."
            )

    block = []
    for item in items:
        block.extend(make_fc_block(item))
    lines[fg_end:fg_end] = block
    return f"Inserted {len(items)} FC item(s) under {fg_tag}."


def update_ck(lines: List[str], fg_tag: str, fc_tag: str, items: List[Dict[str, Any]]) -> str:
    validate_tag(fg_tag, "FG")
    validate_tag(fc_tag, "FC")
    section_start, section_end = get_section_bounds(lines)

    fg_idx = find_tag_index(lines, section_start + 1, section_end, fg_tag)
    if fg_idx < 0:
        raise ValueError(
            f"Error: parent FG tag '{fg_tag}' not found. Insert the FG block first and try again."
        )

    fg_end = find_next_boundary(lines, fg_idx + 1, section_end, [is_fg_line])
    fc_idx = find_tag_index(lines, fg_idx + 1, fg_end, fc_tag)
    if fc_idx < 0:
        raise ValueError(
            f"Error: parent FC tag '{fc_tag}' not found under '{fg_tag}'. Insert the FC block first and try again."
        )

    fc_end = find_next_boundary(lines, fc_idx + 1, fg_end, [is_fc_line, is_fg_line])
    for item in items:
        ck = item.get("ck")
        desc = item.get("desc")
        if not ck or desc is None:
            raise ValueError("Error: CK items must contain 'ck' and 'desc'.")
        validate_tag(ck, "CK")
        if find_tag_index(lines, fc_idx + 1, fc_end, ck) >= 0:
            raise ValueError(
                f"Error: CK tag '{ck}' already exists under '{fg_tag}/{fc_tag}'. Use a new tag and try again."
            )

    has_ck_header = any(lines[idx].strip() == "**检测点：**" for idx in range(fc_idx + 1, fc_end))
    if has_ck_header:
        block = []
        for item in items:
            block.append(f"- <{item['ck']}> {str(item['desc']).strip()}\n")
        lines[fc_end:fc_end] = block
    else:
        lines[fc_end:fc_end] = make_ck_lines(items)
    return f"Inserted {len(items)} CK item(s) under {fg_tag}/{fc_tag}."


def main():
    args = parse_args()
    doc_path = load_doc_path()
    items = parse_items(args.ITEMS)

    if args.MODE == "FG":
        ensure_unique([str(item.get("fg", "")) for item in items], "FG batch")
    elif args.MODE == "FC":
        if not args.FG:
            raise ValueError("Error: -FG is required in FC mode.")
        ensure_unique([str(item.get("fc", "")) for item in items], "FC batch")
    else:
        if not args.FG or not args.FC:
            raise ValueError("Error: -FG and -FC are required in CK mode.")
        ensure_unique([str(item.get("ck", "")) for item in items], "CK batch")

    with open(doc_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if args.MODE == "FG":
        message = update_fg(lines, items)
    elif args.MODE == "FC":
        message = update_fc(lines, args.FG, items)
    else:
        message = update_ck(lines, args.FG, args.FC, items)

    with open(doc_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(message)


if __name__ == "__main__":
    main()
