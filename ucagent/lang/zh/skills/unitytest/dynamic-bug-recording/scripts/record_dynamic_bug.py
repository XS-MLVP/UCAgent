import argparse
import ast
import hashlib
import json
import os
import posixpath
import re
from pathlib import Path
from string import Template

from ucagent.util.config import load_runtime_config

DYNAMIC_BUGS_MARKER = "<DYNAMIC-BUGS>"
DYNAMIC_BUGS_END_MARKER = "</DYNAMIC-BUGS>"
WAVEFORM_EVIDENCE_MARKER = "<WAVEFORM-EVIDENCE>"
WAVEFORM_EVIDENCE_END_MARKER = "</WAVEFORM-EVIDENCE>"
TODO_MARKER = "<BUG-TODO>"
OVERVIEW_MARKER = "<BUG-OVERVIEW>"
OVERVIEW_TITLE = "###### Bug \u6982\u8ff0"
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
GENERIC_VISIBLE_TITLES = {
    "\u529f\u80fd\u7ec4",
    "\u529f\u80fd",
    "\u68c0\u6d4b\u70b9",
    "\u52a8\u6001 Bug",
    "\u5931\u8d25\u7528\u4f8b",
}


def load_asset_template(name):
    return Template((ASSET_DIR / name).read_text(encoding="utf-8"))


bug_analysis_template = load_asset_template("bug_analysis_document.md")
dynamic_bug_entry_template = load_asset_template("dynamic_bug_entry.md")


def make_bug_analysis_document(dut):
    return bug_analysis_template.substitute(DUT=dut)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Insert one dynamic bug entry into {DUT}_bug_analysis.md. "
            "FG/FC/CK are inferred from TC target test function."
        )
    )
    parser.add_argument("-BG", required=True, help="Bug tag, e.g. BG-CIN-OVERFLOW-98")
    parser.add_argument(
        "-TC",
        required=True,
        help=(
            "Test case tag, e.g. "
            "TC-tests/test_ALU754_api.py::test_div"
        ),
    )
    parser.add_argument("-BD", required=True, help="Bug description")
    return parser.parse_args()


def validate_tag(tag, prefix):
    if not tag.startswith(prefix + "-"):
        raise ValueError(f"Error: {prefix} tag format invalid: {tag}")


def validate_dynamic_bg_tag(tag):
    validate_tag(tag, "BG")
    if tag.startswith("BG-STATIC-"):
        raise ValueError(
            "Error: -BG is a dynamic Bug tag and cannot use the BG-STATIC-* "
            "namespace. Keep <BG-STATIC-*> in {DUT}_static_bug_analysis.md, "
            "create a distinct BG-NAME-XX tag here, and link it with LINK-BUG."
        )
    if bg_confidence(tag) == 0:
        raise ValueError(
            "Error: -BG confidence must be greater than 0 for a confirmed dynamic Bug."
        )


def normalize_visible_title(value, source):
    title = re.sub(r"\s+", " ", str(value or "")).strip().rstrip("\uff1a:")
    if not title:
        raise ValueError(f"Error: {source} visible title is empty.")
    if "<" in title or ">" in title:
        raise ValueError(
            f"Error: {source} visible title cannot contain angle-bracket tags."
        )
    if title.startswith("[") and title.endswith("]"):
        raise ValueError(
            f"Error: {source} visible title must replace bracketed scaffold text."
        )
    if title in GENERIC_VISIBLE_TITLES:
        raise ValueError(
            f"Error: {source} visible title must describe the actual item, not its type."
        )
    return title


def parse_tc_target(tc_tag):
    validate_tag(tc_tag, "TC")
    payload = tc_tag[len("TC-") :]
    parts = payload.split("::")
    if len(parts) == 2:
        file_path, func_name = parts
        class_name = None
    elif len(parts) == 3:
        file_path, class_name, func_name = parts
    else:
        raise ValueError(
            "Error: TC format invalid. Expected TC-<path>::<test_func> "
            "or TC-<path>::<ClassName>::<test_func>."
        )
    if not file_path or not func_name:
        raise ValueError("Error: TC path/function is empty.")
    return file_path, class_name, func_name


def _workspace_relative_posix_path(path):
    normalized = posixpath.normpath(os.fspath(path).replace("\\", "/"))
    if not posixpath.isabs(normalized):
        return normalized

    cwd = posixpath.normpath(os.getcwd().replace("\\", "/"))
    return posixpath.relpath(normalized, cwd)


def _normalize_tc_key(key, out_dir):
    # Report keys are workspace-relative while TC tags are test-dir-relative.
    normalized = re.sub(r":\d+(?:-\d+)?(?=::)", "", key)
    parts = normalized.split("::")
    file_path = _workspace_relative_posix_path(parts[0])
    out_path = _workspace_relative_posix_path(out_dir)
    if out_path not in ("", ".") and file_path.startswith(out_path + "/"):
        file_path = file_path[len(out_path) + 1 :]
    return "::".join([file_path, *parts[1:]])


def _normalize_report_tc_key(key, out_dir=""):
    return _normalize_tc_key(key, out_dir)


def _parse_fg_fc_ck_items(raw_items, source_key):
    parsed = []
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        parts = raw.split("/")
        if len(parts) != 3:
            raise ValueError(
                f"Error: invalid check point format in report for '{source_key}': {raw}"
            )
        parsed.append((parts[0], parts[1], parts[2]))
    return parsed


def resolve_fg_fc_ck_list_by_tc(tc_tag, out_dir):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    if class_name:
        tc_target = f"{file_path}::{class_name}::{func_name}"
    else:
        tc_target = f"{file_path}::{func_name}"
    normalized_tc_target = _normalize_tc_key(tc_target, out_dir)

    report_path = os.path.join(os.getcwd(), out_dir, ".TEST_TEMPLATE_IMP_REPORT.json")
    if not os.path.exists(report_path):
        raise FileNotFoundError(f"Error: report file not found: {report_path}")

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    mapping = report.get("failed_test_case_with_check_point_list")
    if not isinstance(mapping, dict):
        raise ValueError(
            "Error: 'failed_test_case_with_check_point_list' missing or invalid in report."
        )

    found = []
    for key, raw_items in mapping.items():
        if _normalize_report_tc_key(key, out_dir) != normalized_tc_target:
            continue
        if not isinstance(raw_items, list):
            raise ValueError(
                f"Error: report entry for '{key}' is not a list: {type(raw_items).__name__}"
            )
        found.extend(_parse_fg_fc_ck_items(raw_items, key))

    uniq = list(dict.fromkeys(found))
    if not uniq:
        raise ValueError(
            "Error: no FG/FC/CK mapping found in report for target TC: "
            f"{tc_target}"
        )
    return uniq


def _outside_fences(lines):
    visible = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            visible.append("")
        elif in_fence:
            visible.append("")
        else:
            visible.append(line)
    return visible


def _tag_line_index(lines, tag, start=0, end=None):
    indexes = [
        index
        for index in range(start, len(lines) if end is None else end)
        if f"<{tag}>" in lines[index]
    ]
    if len(indexes) != 1:
        raise ValueError(
            f"Error: expected one <{tag}> in the function specification, "
            f"found {len(indexes)}."
        )
    return indexes[0]


def _next_tag_index(lines, prefix, start, end):
    token = f"<{prefix}-"
    return next((index for index in range(start, end) if token in lines[index]), end)


def _nearest_heading(lines, tag_index, level, start, end, tag):
    pattern = re.compile(rf"^#{{{level}}}(?!#)\s+(.+?)\s*$")
    candidates = []
    for index in range(start, end):
        match = pattern.match(lines[index].strip())
        if match and f"<{tag}>" not in match.group(1):
            candidates.append((abs(index - tag_index), index, match.group(1).strip()))
    if not candidates:
        raise ValueError(
            f"Error: no visible level-{level} heading found for <{tag}> in "
            "the function specification."
        )
    distance, _index, title = min(candidates)
    if distance > 4:
        raise ValueError(
            f"Error: visible heading for <{tag}> is too far from its tag in "
            "the function specification."
        )
    return normalize_visible_title(title, tag)


def _checkpoint_title(line, tag):
    _prefix, suffix = line.split(f"<{tag}>", 1)
    title = suffix.strip().lstrip("-*: ")
    title = re.split(r"[:\uff1a]", title, maxsplit=1)[0].strip()
    if not title:
        raise ValueError(
            f"Error: <{tag}> must be followed by a visible checkpoint name in "
            "the function specification."
        )
    return normalize_visible_title(title, tag)


def resolve_checkpoint_titles(function_file, fg, fc, ck):
    if not os.path.isfile(function_file):
        raise FileNotFoundError(
            f"Error: function specification not found: {function_file}"
        )
    with open(function_file, "r", encoding="utf-8") as handle:
        lines = _outside_fences(handle.readlines())

    fg_index = _tag_line_index(lines, fg)
    fg_end = _next_tag_index(lines, "FG", fg_index + 1, len(lines))
    previous_fg = max(
        (index for index in range(0, fg_index) if "<FG-" in lines[index]),
        default=-1,
    )
    fg_title = _nearest_heading(
        lines, fg_index, 3, previous_fg + 1, fg_end, fg
    )

    fc_index = _tag_line_index(lines, fc, fg_index + 1, fg_end)
    fc_end = min(
        _next_tag_index(lines, "FC", fc_index + 1, fg_end),
        fg_end,
    )
    fc_title = _nearest_heading(lines, fc_index, 4, fg_index + 1, fc_end, fc)

    ck_index = _tag_line_index(lines, ck, fc_index + 1, fc_end)
    ck_title = _checkpoint_title(lines[ck_index], ck)
    return fg_title, fc_title, ck_title


def resolve_test_title(tc_tag, out_dir):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    normalized_out = _workspace_relative_posix_path(out_dir)
    normalized_file = _workspace_relative_posix_path(file_path)
    if normalized_out not in ("", ".") and normalized_file.startswith(
        normalized_out + "/"
    ):
        source_path = normalized_file
    else:
        source_path = posixpath.join(normalized_out, normalized_file)
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Error: test source not found: {source_path}")
    with open(source_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=source_path)

    scope = tree.body
    if class_name:
        class_node = next(
            (
                node
                for node in scope
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if class_node is None:
            raise ValueError(
                f"Error: test class '{class_name}' not found in {source_path}."
            )
        scope = class_node.body
    function_node = next(
        (
            node
            for node in scope
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func_name
        ),
        None,
    )
    if function_node is None:
        raise ValueError(
            f"Error: test function '{func_name}' not found in {source_path}."
        )
    docstring = ast.get_docstring(function_node, clean=True)
    if not docstring:
        raise ValueError(
            f"Error: test function '{func_name}' needs a visible description in its docstring."
        )
    title = next(line.strip() for line in docstring.splitlines() if line.strip())
    return normalize_visible_title(title, tc_tag)


def bg_confidence(bg_tag):
    m = re.match(r"^BG-.+-(\d{1,3})$", bg_tag)
    if not m:
        raise ValueError(
            f"Error: BG tag format invalid: {bg_tag}. Expected BG-<NAME>-<0~100>."
        )
    conf = int(m.group(1))
    if conf < 0 or conf > 100:
        raise ValueError(f"Error: BG confidence out of range 0~100: {conf}")
    return conf


def locate_section(lines):
    starts = [i for i, line in enumerate(lines) if line.strip() == DYNAMIC_BUGS_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == DYNAMIC_BUGS_END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            "Error: target markdown must contain one closed DYNAMIC-BUGS container."
        )
    return starts[0], ends[0]


def find_tag_line(lines, start, end, tag):
    token = f"<{tag}>"
    for i in range(start, end):
        if token in lines[i]:
            return i
    return -1


def next_boundary(lines, start, end, patterns):
    for i in range(start, end):
        text = lines[i].strip()
        for p in patterns:
            if p(text):
                return i
    return end


def ensure_trailing_newline_block(block):
    if not block.endswith("\n"):
        return block + "\n"
    return block


def escape_markdown_asterisk(text):
    if not text:
        return text
    return re.sub(r"(?<!\\)\*", r"\\*", text)


def render_bug_entry(
    fg,
    fc,
    ck,
    bg,
    tc,
    bd,
    confidence,
    fg_title,
    fc_title,
    ck_title,
    tc_title,
):
    anchor = hashlib.sha256(tc.encode("utf-8")).hexdigest()[:16]
    return ensure_trailing_newline_block(
        dynamic_bug_entry_template.substitute(
            FG=fg,
            FC=fc,
            CK=ck,
            BG=bg,
            TC=tc,
            BD=bd,
            CONFIDENCE=confidence,
            ANCHOR=anchor,
            FG_TITLE=fg_title,
            FC_TITLE=fc_title,
            CK_TITLE=ck_title,
            TC_TITLE=tc_title,
        )
    )


def subtree_from_tag(block, tag, end_marker=None):
    lines = block.splitlines(keepends=True)
    start = find_tag_line(lines, 0, len(lines), tag)
    if start < 0:
        raise ValueError(f"Error: scaffold asset does not contain <{tag}>.")
    end = len(lines)
    if end_marker is not None:
        marker_line = next(
            (i for i in range(start + 1, len(lines)) if lines[i].strip() == end_marker),
            -1,
        )
        if marker_line < 0:
            raise ValueError(
                f"Error: scaffold asset does not contain closing marker {end_marker}."
            )
        end = marker_line
    return ensure_trailing_newline_block("".join(lines[start:end]))


def insert_content(
    lines, fg, fc, ck, bg, tc, bd, fg_title, fc_title, ck_title, tc_title
):
    lines[:] = "".join(lines).splitlines(keepends=True)
    confidence = bg_confidence(bg)
    sec_start, sec_end = locate_section(lines)

    fg_line = find_tag_line(lines, sec_start + 1, sec_end, fg)
    entry_block = render_bug_entry(
        fg,
        fc,
        ck,
        bg,
        tc,
        bd,
        confidence,
        fg_title,
        fc_title,
        ck_title,
        tc_title,
    )
    fc_block = subtree_from_tag(entry_block, fc)
    ck_bg_block = subtree_from_tag(entry_block, ck)
    bg_tc_block = subtree_from_tag(entry_block, bg)
    tc_block = subtree_from_tag(entry_block, tc, OVERVIEW_TITLE)

    if fg_line < 0:
        new_block = f"\n{entry_block}"
        lines.insert(sec_end, new_block)
        return "Inserted new FG/FC/CK/BG/TC block."

    fg_end = next_boundary(
        lines,
        fg_line + 1,
        sec_end,
        [lambda t: "<FG-" in t],
    )

    fc_line = find_tag_line(lines, fg_line + 1, fg_end, fc)
    if fc_line < 0:
        new_fc_block = ensure_trailing_newline_block(f"\n{fc_block}")
        lines.insert(fg_end, new_fc_block)
        return "Inserted new FC/CK/BG/TC block under existing FG."

    fc_end = next_boundary(
        lines,
        fc_line + 1,
        fg_end,
        [lambda t: "<FC-" in t],
    )

    ck_line = find_tag_line(lines, fc_line + 1, fc_end, ck)
    if ck_line >= 0:
        ck_end = next_boundary(
            lines,
            ck_line + 1,
            fc_end,
            [lambda t: "<CK-" in t, lambda t: "<FC-" in t],
        )

        # Only treat BG as duplicate when it already exists under the same CK block.
        bg_line = find_tag_line(lines, ck_line, ck_end, bg)
        if bg_line >= 0:
            bg_end = next_boundary(
                lines,
                bg_line + 1,
                ck_end,
                [
                    lambda t: "<BG-" in t,
                    lambda t: "<CK-" in t,
                    lambda t: "<FC-" in t,
                ],
            )
            tc_line = find_tag_line(lines, bg_line + 1, bg_end, tc)
            if tc_line >= 0:
                return "CK/BG/TC already exist. Nothing changed."

            details_line = next(
                (
                    i
                    for i in range(bg_line + 1, bg_end)
                    if lines[i].strip() == OVERVIEW_TITLE
                ),
                bg_end,
            )
            lines.insert(details_line, tc_block)
            return "CK/BG exist; appended missing TC scaffold."

        # Same CK exists but different BG: append another bug item after this CK block.
        lines.insert(ck_end, bg_tc_block)
        return "CK exists; appended new BG/TC under this FC."

    lines.insert(fc_end, ck_bg_block)
    return "Inserted new CK/BG/TC under existing FG/FC."


def main():
    args = parse_args()
    validate_dynamic_bg_tag(args.BG)
    validate_tag(args.TC, "TC")

    escaped_bd = escape_markdown_asterisk(
        normalize_visible_title(args.BD, args.BG)
    )

    runtime_config = load_runtime_config(os.getcwd())
    dut = runtime_config["DUT"]
    out = runtime_config["OUT"]

    fg_fc_ck_list = resolve_fg_fc_ck_list_by_tc(args.TC, out)
    function_file = os.path.join(os.getcwd(), out, f"{dut}_functions_and_checks.md")
    tc_title = resolve_test_title(args.TC, out)

    target = os.path.join(os.getcwd(), out, f"{dut}_bug_analysis.md")

    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        initial_content = make_bug_analysis_document(dut)
        with open(target, "w", encoding="utf-8") as f:
            f.write(initial_content)

    with open(target, "r", encoding="utf-8") as f:
        lines = f.readlines()

    msgs = []
    for fg, fc, ck in fg_fc_ck_list:
        fg_title, fc_title, ck_title = resolve_checkpoint_titles(
            function_file, fg, fc, ck
        )
        msg = insert_content(
            lines,
            fg,
            fc,
            ck,
            args.BG,
            args.TC,
            escaped_bd,
            fg_title,
            fc_title,
            ck_title,
            tc_title,
        )
        msgs.append(f"{msg} (resolved: {fg}/{fc}/{ck})")

    with open(target, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(
        "; ".join(msgs)
        + f" -> {target}. Incomplete scaffold marker: {TODO_MARKER}."
    )


if __name__ == "__main__":
    main()
