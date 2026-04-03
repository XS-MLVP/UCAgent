#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


FG_LINE_RE = re.compile(r"^\s*<(?P<name>FG-[A-Z0-9\-_]+)>\s*(?:#.*)?$")
FC_LINE_RE = re.compile(r"<(?P<name>FC-[A-Z0-9\-_]+)>(?:\s|$)")
CK_LINE_RE = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s*)?<(?P<name>CK-[^>]+)>(?:\s|$)")
SECTION_HEADING_RE = re.compile(r"^\s*##\s+(?P<title>.+?)\s*$")
FENCE_START_RE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})(?P<lang>[A-Za-z0-9_-]*)\s*$")
STRUCTURE_SECTION_TITLES = {"功能分组与检测点", "功能点与检测点"}
MARKDOWN_FENCE_LANGS = {"", "markdown", "md"}
GUIDE_TITLE_RE = re.compile(r"^\s*#\s+.*(指南|Guide)\b")


def is_structure_section_title(title: str) -> bool:
    if title in STRUCTURE_SECTION_TITLES:
        return True

    words = set(re.findall(r"[a-z0-9]+", title.casefold()))
    has_check = bool(words & {"check", "checks", "checkpoint", "checkpoints", "ck"})
    has_group_or_function = bool(words & {"fg", "fc", "function", "functions", "functional", "group", "groups"})
    return has_check and has_group_or_function


def is_guide_doc(markdown_text: str) -> bool:
    """Return True for tutorial/guide docs that should not produce a DUT structure.

    These documents describe how to write specs and often embed example FG/FC/CK
    blocks inside fenced markdown. They should not be treated as real DUT maps.
    """
    in_frontmatter = False
    saw_leading_content = False
    in_comment = False
    in_fence = False
    fence_char = None
    fence_len = 0

    for line in markdown_text.splitlines():
        stripped = line.strip()

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue

        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue

        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group("marker")
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
                fence_char = None
                fence_len = 0
            continue

        if in_fence:
            continue

        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue

        if not stripped:
            continue

        if not saw_leading_content and stripped == "---":
            in_frontmatter = True
            saw_leading_content = True
            continue

        heading_match = SECTION_HEADING_RE.match(line)
        if heading_match:
            return bool(GUIDE_TITLE_RE.match(stripped))

        if stripped.startswith("#"):
            return bool(GUIDE_TITLE_RE.match(stripped))

        saw_leading_content = True

    return False


def iter_structural_lines(markdown_text: str, *, include_fences: bool = False):
    in_comment = False
    in_fence = False
    fence_char = None
    fence_len = 0
    in_structure_section = False

    for line in markdown_text.splitlines():
        stripped = line.strip()

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue

        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue

        fence_match = FENCE_START_RE.match(line)
        if fence_match:
            marker = fence_match.group("marker")
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
                fence_char = None
                fence_len = 0
            continue

        if in_fence and not include_fences:
            continue

        section_match = SECTION_HEADING_RE.match(line)
        if section_match:
            in_structure_section = is_structure_section_title(section_match.group("title"))
            continue

        if not in_structure_section:
            continue

        yield line


def iter_markdown_fragments(markdown_text: str):
    # First, yield the full document so that structure-section headings like
    # "## 功能分组与检测点" are always visible to iter_structural_lines(...).
    yield markdown_text, False

    lines = markdown_text.splitlines()
    index = 0
    active_structure_heading = None
    in_comment = False
    while index < len(lines):
        stripped = lines[index].strip()

        if in_comment:
            if "-->" in stripped:
                in_comment = False
            index += 1
            continue

        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            index += 1
            continue

        section_match = SECTION_HEADING_RE.match(lines[index])
        if section_match:
            title = section_match.group("title")
            active_structure_heading = title if is_structure_section_title(title) else None

        match = FENCE_START_RE.match(lines[index])
        if not match:
            index += 1
            continue

        marker = match.group("marker")
        marker_char = marker[0]
        marker_len = len(marker)
        language = match.group("lang").lower()
        index += 1
        block_lines = []

        while index < len(lines):
            stripped = lines[index].strip()
            if re.match(rf"^{re.escape(marker_char)}{{{marker_len},}}$", stripped):
                break
            block_lines.append(lines[index])
            index += 1

        if language in MARKDOWN_FENCE_LANGS:
            # Preserve the outer structure heading so fenced markdown fragments
            # remain parseable even when they only contain FG/FC/CK tags.
            fragment_lines = block_lines
            if active_structure_heading is not None:
                fragment_lines = [f"## {active_structure_heading}", *fragment_lines]
            yield "\n".join(fragment_lines), True

        if index < len(lines):
            index += 1


def extract_structure_from_fragment(markdown_text: str, *, include_fences: bool = False):
    groups = []
    current_group = None
    current_function = None

    for line in iter_structural_lines(markdown_text, include_fences=include_fences):
        fg_match = FG_LINE_RE.match(line)
        if fg_match:
            current_group = {"name": fg_match.group("name"), "functions": []}
            groups.append(current_group)
            current_function = None
            continue

        fc_match = FC_LINE_RE.search(line)
        if fc_match and current_group is not None:
            current_function = {"name": fc_match.group("name"), "checks": []}
            current_group["functions"].append(current_function)
            continue

        ck_match = CK_LINE_RE.match(line)
        if ck_match and current_function is not None:
            current_function["checks"].append(ck_match.group("name"))

    return {"groups": groups}


def structure_score(structure):
    groups = structure["groups"]
    function_count = sum(len(group["functions"]) for group in groups)
    check_count = sum(len(function["checks"]) for group in groups for function in group["functions"])
    populated_group_count = sum(1 for group in groups if group["functions"])
    return (check_count, function_count, populated_group_count, len(groups))


def structure_has_groups(structure):
    return bool(structure["groups"])


def structure_has_populated_groups(structure):
    return any(group["functions"] for group in structure["groups"])


def structure_has_checks(structure):
    return any(function["checks"] for group in structure["groups"] for function in group["functions"])


def structure_contains_structure(container, contained):
    contained_checks = {
        (group["name"], function["name"], check)
        for group in contained["groups"]
        for function in group["functions"]
        for check in function["checks"]
    }
    if not contained_checks:
        if structure_has_checks(contained) or not structure_has_checks(container):
            return False

        contained_functions = {
            (group["name"], function["name"])
            for group in contained["groups"]
            for function in group["functions"]
        }
        container_functions = {
            (group["name"], function["name"])
            for group in container["groups"]
            for function in group["functions"]
        }
        return contained_functions.issubset(container_functions)

    container_checks = {
        (group["name"], function["name"], check)
        for group in container["groups"]
        for function in group["functions"]
        for check in function["checks"]
    }
    return contained_checks.issubset(container_checks)


def extract_structure(markdown_text: str):
    if is_guide_doc(markdown_text):
        # Guide/tutorial docs intentionally do not define a concrete DUT map.
        # Returning an empty structure prevents embedded examples from being
        # mistaken for real FG/FC/CK definitions.
        return {"groups": []}

    body_structure = extract_structure_from_fragment(markdown_text, include_fences=False)
    best_structure = body_structure
    best_score = structure_score(best_structure)

    for fragment, is_fenced in iter_markdown_fragments(markdown_text):
        if not is_fenced:
            continue
        structure = extract_structure_from_fragment(fragment, include_fences=True)
        score = structure_score(structure)
        if score > best_score and structure_contains_structure(structure, body_structure):
            best_structure = structure
            best_score = score

    return best_structure


def main():
    parser = argparse.ArgumentParser(description="Extract FG/FC/CK structure from a *_functions_and_checks.md file.")
    parser.add_argument("markdown_file", help="Path to the markdown file to parse.")
    args = parser.parse_args()

    markdown_file = Path(args.markdown_file).expanduser().resolve()
    result = extract_structure(markdown_file.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
