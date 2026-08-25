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
from ucagent.util.bug_analysis_contract import (
    DYNAMIC_BUG_DOCUMENT_PATH,
    BUG_ANALYSIS_SECTION_MARKERS,
    RELATED_BUGS_TITLE,
    ROOT_ANALYSIS_SECTION_MARKERS,
    ROOT_ANALYSIS_SECTION_TITLES,
    ROOT_ENTITY_TAG_PATTERN,
    dynamic_bug_anchor_id,
    related_bug_reference,
    root_cause_anchor_id,
    root_cause_reference,
)
from ucagent.util.markdown import ensure_markdown_heading_spacing

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
ROOT_CAUSES_MARKER = "<ROOT-CAUSES>"
ROOT_CAUSES_END_MARKER = "</ROOT-CAUSES>"
RELATED_BUGS_MARKER = "<RELATED-BUGS>"
HEADING_COMPANION_MARKERS = frozenset(
    [marker for _field, marker in BUG_ANALYSIS_SECTION_MARKERS]
    + [marker for _field, marker in ROOT_ANALYSIS_SECTION_MARKERS]
    + [RELATED_BUGS_MARKER]
)


def load_asset_template(name):
    return Template((ASSET_DIR / name).read_text(encoding="utf-8"))


bug_analysis_template = load_asset_template("bug_analysis_document.md")
dynamic_bug_entry_template = load_asset_template("dynamic_bug_entry.md")


def make_bug_analysis_document(dut):
    return bug_analysis_template.substitute(DUT=dut)


def parse_args(test_output_dir="<resolved agent.cfg test output directory>"):
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
            "Exact current FAILED report node ID with TC- added after removing only the "
            f"report file line range. Its file path must start with '{test_output_dir}/', "
            "the value resolved from .ucagent/runtime_config.json."
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
    del out_dir
    return re.sub(r":\d+(?:-\d+)?(?=::)", "", str(key).strip())


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


def resolve_fg_fc_ck_list_by_tc(tc_tag, out_dir, test_output_dir):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    if class_name:
        tc_target = f"{file_path}::{class_name}::{func_name}"
    else:
        tc_target = f"{file_path}::{func_name}"
    normalized_tc_target = _normalize_tc_key(tc_target, out_dir)
    configured_test_dir = _workspace_relative_posix_path(test_output_dir)
    has_configured_prefix = normalized_tc_target.split("::", 1)[0].startswith(
        configured_test_dir + "/"
    )

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
    report_nodes = []
    for key, raw_items in mapping.items():
        report_node = _normalize_report_tc_key(key, out_dir)
        report_nodes.append(report_node)
        if not has_configured_prefix or report_node != normalized_tc_target:
            continue
        if not isinstance(raw_items, list):
            raise ValueError(
                f"Error: report entry for '{key}' is not a list: {type(raw_items).__name__}"
            )
        found.extend(_parse_fg_fc_ck_items(raw_items, key))

    uniq = list(dict.fromkeys(found))
    if not uniq:
        target_parts = normalized_tc_target.split("::")
        target_file = target_parts[0]
        target_function = target_parts[-1]
        similar_nodes = [
            node
            for node in report_nodes
            if os.path.basename(node.split("::", 1)[0]) == os.path.basename(target_file)
            or node.split("::")[-1] == target_function
        ][:10]
        candidate_text = ", ".join(similar_nodes) if similar_nodes else "None"
        raise ValueError(
            "Error: no exact FG/FC/CK report mapping exists for target TC "
            f"'{tc_target}'. Configured TC output directory from "
            f".ucagent/runtime_config.json: '{configured_test_dir}'. The TC file path must "
            f"start with '{configured_test_dir}/'. Similar current FAILED report node IDs: "
            f"{candidate_text}. "
            "Similar nodes are lookup hints only and are not equivalent identities. Copy "
            "the intended report node ID verbatim, remove only its file line range, add "
            "TC-, and call this script again with the configured directory unchanged."
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


def resolve_test_title(tc_tag):
    file_path, class_name, func_name = parse_tc_target(tc_tag)
    source_path = _workspace_relative_posix_path(file_path)
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


def root_cause_tag_for_bg(bg_tag):
    """Return the deterministic initial root-cause tag for a BG scaffold."""

    match = re.fullmatch(r"BG-(.+)-\d{1,3}", bg_tag)
    if match is None:
        raise ValueError(f"Error: BG tag format invalid: {bg_tag}")
    name = re.sub(r"[^A-Z0-9-]+", "-", match.group(1).upper()).strip("-")
    candidate = f"ROOT-{name or 'UNNAMED'}"
    if ROOT_ENTITY_TAG_PATTERN.fullmatch(candidate) is None:
        candidate = f"ROOT-BUG-{name or 'UNNAMED'}"
    return candidate


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
    checkpoint_path,
):
    anchor = hashlib.sha256(tc.encode("utf-8")).hexdigest()[:16]
    root_tag = root_cause_tag_for_bg(bg)
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
            BUG_ANCHOR=dynamic_bug_anchor_id(checkpoint_path, bg),
            ROOT_CAUSE_REFERENCE=root_cause_reference(root_tag, bd),
        )
    )


def render_root_cause_entry(root_tag, bd, checkpoint_path, bg):
    root_titles = dict(ROOT_ANALYSIS_SECTION_TITLES)
    return ensure_trailing_newline_block(
        "\n".join(
            [
                f'<a id="{root_cause_anchor_id(root_tag)}"></a>',
                f"### {bd} <{root_tag}>",
                "",
                *(
                    value
                    for field, marker in ROOT_ANALYSIS_SECTION_MARKERS
                    for value in (root_titles[field], marker, TODO_MARKER, "")
                ),
                RELATED_BUGS_TITLE,
                RELATED_BUGS_MARKER,
                related_bug_reference(checkpoint_path, bg),
                "",
            ]
        )
    )


def subtree_from_tag(block, tag, end_marker=None):
    lines = block.splitlines(keepends=True)
    start = find_tag_line(lines, 0, len(lines), tag)
    if start < 0:
        raise ValueError(f"Error: scaffold asset does not contain <{tag}>.")
    if tag.startswith("BG-") and start > 0 and lines[start - 1].lstrip().startswith(
        '<a id="bug-'
    ):
        start -= 1
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


def _insert_dynamic_content(
    lines, fg, fc, ck, bg, tc, bd, fg_title, fc_title, ck_title, tc_title
):
    lines[:] = "".join(lines).splitlines(keepends=True)
    confidence = bg_confidence(bg)
    sec_start, sec_end = locate_section(lines)
    checkpoint_path = f"{fg}/{fc}/{ck}"

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
        checkpoint_path,
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


def ensure_root_cause_entry(lines, bg, bd, checkpoint_path):
    """Create one root entity and keep its reverse BG link idempotent."""

    starts = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            "Error: target markdown must contain one closed ROOT-CAUSES container "
            "before WAVEFORM-EVIDENCE."
        )
    start, end = starts[0], ends[0]
    root_tag = root_cause_tag_for_bg(bg)
    root_token = f"<{root_tag}>"
    entity_line = next(
        (i for i in range(start + 1, end) if root_token in lines[i]),
        -1,
    )
    relation = related_bug_reference(checkpoint_path, bg)
    if entity_line < 0:
        lines.insert(end, render_root_cause_entry(root_tag, bd, checkpoint_path, bg))
        return
    entity_end = next(
        (
            i
            for i in range(entity_line + 1, end)
            if re.fullmatch(
                rf"###\s+.+\s+<{ROOT_ENTITY_TAG_PATTERN.pattern}>",
                lines[i].strip(),
            )
        ),
        end,
    )
    if any(relation.strip() == lines[i].strip() for i in range(entity_line, entity_end)):
        return
    related_line = next(
        (i for i in range(entity_line, entity_end) if lines[i].strip() == RELATED_BUGS_MARKER),
        -1,
    )
    if related_line < 0:
        raise ValueError(f"Error: root cause entity {root_tag} is missing {RELATED_BUGS_MARKER}.")
    lines.insert(entity_end, relation)


def ensure_root_cause_container(lines):
    starts = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_END_MARKER]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError("Error: malformed ROOT-CAUSES container.")
        return
    evidence = next(
        (i for i, line in enumerate(lines) if line.strip() == WAVEFORM_EVIDENCE_MARKER),
        -1,
    )
    if evidence < 0:
        raise ValueError("Error: target markdown is missing WAVEFORM-EVIDENCE marker.")
    lines[evidence:evidence] = [
        "## \u6839\u56e0\u5206\u6790\n",
        "\n",
        ROOT_CAUSES_MARKER + "\n",
        ROOT_CAUSES_END_MARKER + "\n",
        "\n",
    ]


def insert_content(
    lines, fg, fc, ck, bg, tc, bd, fg_title, fc_title, ck_title, tc_title
):
    message = _insert_dynamic_content(
        lines, fg, fc, ck, bg, tc, bd, fg_title, fc_title, ck_title, tc_title
    )
    lines[:] = "".join(lines).splitlines(keepends=True)
    ensure_root_cause_entry(lines, bg, bd, f"{fg}/{fc}/{ck}")
    lines[:] = ensure_markdown_heading_spacing(
        "".join(lines), HEADING_COMPANION_MARKERS
    ).splitlines(keepends=True)
    return message


def main():
    runtime_config = load_runtime_config(os.getcwd())
    dut = runtime_config["DUT"]
    out = runtime_config["OUT"]
    configured_test_dir = runtime_config["test_output_dir"]
    args = parse_args(configured_test_dir)
    validate_dynamic_bg_tag(args.BG)
    validate_tag(args.TC, "TC")

    escaped_bd = escape_markdown_asterisk(
        normalize_visible_title(args.BD, args.BG)
    )

    fg_fc_ck_list = resolve_fg_fc_ck_list_by_tc(
        args.TC, out, configured_test_dir
    )
    function_file = os.path.join(os.getcwd(), out, f"{dut}_functions_and_checks.md")
    tc_title = resolve_test_title(args.TC)

    target = os.path.join(
        os.getcwd(), DYNAMIC_BUG_DOCUMENT_PATH.format(OUT=out, DUT=dut)
    )

    if not os.path.isabs(target):
        target = os.path.join(os.getcwd(), target)
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        initial_content = make_bug_analysis_document(dut)
        with open(target, "w", encoding="utf-8") as f:
            f.write(initial_content)

    with open(target, "r", encoding="utf-8") as f:
        lines = f.readlines()
    ensure_root_cause_container(lines)

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
        f.write(
            ensure_markdown_heading_spacing("".join(lines), HEADING_COMPANION_MARKERS)
        )

    print(
        "; ".join(msgs)
        + f" -> {target}. Incomplete scaffold marker: {TODO_MARKER}."
    )


if __name__ == "__main__":
    main()
