import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
import posixpath
import re
import stat
import tempfile
from pathlib import Path
from string import Template

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no POSIX advisory locks.
    fcntl = None

from ucagent.util.config import load_current_test_report, load_runtime_config
from ucagent.util.bug_analysis_contract import (
    DYNAMIC_BUG_DOCUMENT_PATH,
    BUG_ANALYSIS_SECTION_MARKERS,
    BUG_ANALYSIS_SECTION_TITLES,
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
UNSUPPORTED_ROOT_CLOSING_MARKERS = ("</RELATED-BUGS>", "</ROOT>")
SKILL_NAME = "unitytest/dynamic-bug-recording"
SKILL_SCRIPT = "record_dynamic_bug.py"
HEADING_COMPANION_MARKERS = frozenset(
    [marker for _field, marker in BUG_ANALYSIS_SECTION_MARKERS]
    + [marker for _field, marker in ROOT_ANALYSIS_SECTION_MARKERS]
    + [RELATED_BUGS_MARKER]
)
SOURCE_MARKERS = (
    "<ROOT-SOURCE-FIRST-ERROR>",
    "<ROOT-SOURCE-PROPAGATION>",
    "<ROOT-SOURCE-OBSERVABLE>",
)
SOURCE_UNAVAILABLE_MARKER = "<ROOT-SOURCE-UNAVAILABLE>"
SOURCE_LOCATION_PATTERN = re.compile(
    r"(?P<path>[^:\r\n]+\.(?P<extension>sv|svh|v|vh|vhd|vhdl|scala)):"
    r"(?P<start>\d+)-(?P<end>\d+)$",
    re.IGNORECASE,
)
SOURCE_LANGUAGE = {
    "sv": ("systemverilog", "//"),
    "svh": ("systemverilog", "//"),
    "v": ("verilog", "//"),
    "vh": ("verilog", "//"),
    "vhd": ("vhdl", "--"),
    "vhdl": ("vhdl", "--"),
    "scala": ("scala", "//"),
}
FORBIDDEN_FIELD_TOKENS = (
    DYNAMIC_BUGS_MARKER,
    DYNAMIC_BUGS_END_MARKER,
    ROOT_CAUSES_MARKER,
    ROOT_CAUSES_END_MARKER,
    WAVEFORM_EVIDENCE_MARKER,
    WAVEFORM_EVIDENCE_END_MARKER,
    TODO_MARKER,
    *[marker for _field, marker in BUG_ANALYSIS_SECTION_MARKERS],
    *[marker for _field, marker in ROOT_ANALYSIS_SECTION_MARKERS],
    RELATED_BUGS_MARKER,
    "<CAUSE-REF-",
    "<RELATED-BUG-",
    "<WAVEFORM-",
    "<FG-",
    "<FC-",
    "<CK-",
    "<BG-",
    "<TC-",
    *SOURCE_MARKERS,
    SOURCE_UNAVAILABLE_MARKER,
)


class SkillDocumentError(ValueError):
    """Describe a document failure with one deterministic Skill recovery action."""

    def __init__(
        self,
        error_code,
        error,
        *,
        details=None,
        next_action,
        workflow_context=None,
    ):
        super().__init__(error)
        self.error_code = error_code
        self.error = error
        self.details = details or {}
        self.next_action = next_action
        self.workflow_context = workflow_context

    def as_result(self, operation):
        result = {
            "operation": operation,
            "success": False,
            "error_code": self.error_code,
            "error": self.error,
            "details": self.details,
            "next_action": self.next_action,
        }
        result["workflow_context"] = self.workflow_context or _workflow_context(
            "skill_call_blocked",
            next_skill_mode=("repair" if operation in {"bug", "root"} else operation),
            resume_mode=operation,
        )
        return result


def _repair_skill_call():
    return {
        "tool": "RunSkillScript",
        "commands": [[SKILL_NAME, SKILL_SCRIPT, "-MODE repair"]],
    }


def _repair_next_action():
    return (
        "Call RunSkillScript with commands "
        f"{_repair_skill_call()['commands']}, then retry the original Skill mode. "
        "Do not edit the Bug document directly."
    )


def _workflow_context(
    phase,
    *,
    identity=None,
    completed=None,
    next_skill_mode=None,
    resume_mode=None,
):
    """Return compact continuation state for a multi-call Bug recording workflow."""

    remaining_sequence = []
    if next_skill_mode == "root":
        remaining_sequence.append(
            {
                "action": "RunSkillScript",
                "mode": "root",
                "purpose": "complete the five ROOT analysis fields",
                "reuse_identity": ["root_tag", "root_title"],
            }
        )
    elif next_skill_mode == "repair":
        remaining_sequence.append(
            {
                "action": "RunSkillScript",
                "mode": "repair",
                "purpose": "repair only machine-owned document structure and relations",
            }
        )
    elif next_skill_mode == "retry_previous":
        remaining_sequence.append(
            {
                "action": "RunSkillScript",
                "mode": resume_mode or "previous",
                "purpose": "retry the exact Skill operation that was blocked",
            }
        )
    if phase in {"bug_fields_recorded", "root_fields_recorded"}:
        remaining_sequence.extend(
            [
                {
                    "action": "WaveInfo",
                    "purpose": "produce the final signed receipt for the exact failed TC",
                },
                {
                    "action": "ApplyWaveInfoEvidence",
                    "purpose": "attach the receipt to each exact BG/TC/checkpoint path",
                },
                {"action": "Check", "purpose": "validate the current document"},
            ]
        )
    return {
        "document_owner": SKILL_NAME,
        "owned_target": "{OUT}/{DUT}_bug_analysis.md",
        "phase": phase,
        "completed": completed or [],
        "identity": identity or {},
        "next_skill_mode": next_skill_mode,
        "resume_mode": resume_mode,
        "remaining_sequence": remaining_sequence,
        "continuation_rule": (
            "Keep every reported BG, TC, checkpoint, and ROOT identity byte-for-byte "
            "unchanged across calls. Use only this Skill for the owned target; other "
            "documents and code are outside this ownership boundary."
        ),
    }


def load_asset_template(name):
    return Template((ASSET_DIR / name).read_text(encoding="utf-8"))


bug_analysis_template = load_asset_template("bug_analysis_document.md")
dynamic_bug_entry_template = load_asset_template("dynamic_bug_entry.md")


def make_bug_analysis_document(dut):
    return bug_analysis_template.substitute(DUT=dut)


def parse_args(test_output_dir="<resolved agent.cfg test output directory>"):
    parser = argparse.ArgumentParser(
        description=(
            "Deterministically upsert dynamic Bug and root-cause records in "
            "{DUT}_bug_analysis.md."
        )
    )
    parser.add_argument(
        "-MODE",
        choices=("repair", "bug", "root"),
        required=True,
        help=(
            "Use repair to rebuild machine-owned ROOT/BG relations, bug to upsert "
            "a BG/TC path, or root to upsert one ROOT entity."
        ),
    )
    parser.add_argument("-BG", help="Bug tag, e.g. BG-CIN-OVERFLOW-98")
    parser.add_argument(
        "-TC",
        help=(
            "Exact current FAILED report node ID with TC- added after removing only the "
            f"report file line range. The path must start with '{test_output_dir}/'."
        ),
    )
    parser.add_argument("-BD", help="Bug title and description")
    parser.add_argument("-CHECKPOINT", help="Exact current report path FG/FC/CK")
    parser.add_argument("-ROOT-TAG", dest="root_tag", help="Root entity tag, e.g. ROOT-RESULT-WIDTH")
    parser.add_argument("-ROOT-TITLE", help="Visible root entity title")
    parser.add_argument("-OVERVIEW", help="Complete Bug overview field body")
    parser.add_argument("-SYMPTOMS", help="Complete Bug symptoms field body")
    parser.add_argument("-TRIGGER", help="Complete Bug trigger field body")
    parser.add_argument("-ANALYSIS", help="Complete ROOT analysis field body")
    parser.add_argument("-CAUSAL-CHAIN", dest="causal_chain", help="Complete ROOT causal chain body")
    parser.add_argument("-FIX", help="Complete ROOT fix field body")
    parser.add_argument("-RETEST", help="Complete ROOT retest field body")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-SOURCE-LOCATION", dest="source_location")
    source.add_argument("-SOURCE-UNAVAILABLE", dest="source_unavailable_reason")
    parser.add_argument("-FIRST-ERROR-LINE", dest="first_error_line", type=int)
    parser.add_argument("-FIRST-ERROR-NOTE", dest="first_error_note")
    parser.add_argument("-PROPAGATION-LINE", dest="propagation_line", type=int)
    parser.add_argument("-PROPAGATION-NOTE", dest="propagation_note")
    parser.add_argument("-OBSERVABLE-LINE", dest="observable_line", type=int)
    parser.add_argument("-OBSERVABLE-NOTE", dest="observable_note")
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


def validate_root_tag(tag):
    if ROOT_ENTITY_TAG_PATTERN.fullmatch(str(tag or "").strip()) is None:
        raise ValueError(
            "Error: --root-tag must use the unique ROOT-NAME form and cannot reuse "
            "a ROOT control marker."
        )


def normalize_field_text(value, source):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Error: {source} must be non-empty.")
    if any(token in text for token in FORBIDDEN_FIELD_TOKENS):
        raise ValueError(
            f"Error: {source} contains a reserved Bug document marker. Pass only the "
            "field body; this script writes headings, markers, links, and anchors."
        )
    if re.search(r"(?m)^\s*#{1,6}\s", text) or "```" in text:
        raise ValueError(
            f"Error: {source} cannot contain Markdown headings or fenced blocks."
        )
    return text


def parse_checkpoint_path(checkpoint_path):
    parts = str(checkpoint_path or "").strip().strip("/").split("/")
    if len(parts) != 3:
        raise ValueError(
            "Error: -CHECKPOINT must contain exact FG-NAME/FC-NAME/CK-NAME tags."
        )
    expected = (("FG", parts[0]), ("FC", parts[1]), ("CK", parts[2]))
    for prefix, value in expected:
        if re.fullmatch(rf"{prefix}-[A-Z0-9][A-Z0-9-]*", value) is None:
            raise ValueError(
                "Error: -CHECKPOINT must contain exact FG-NAME/FC-NAME/CK-NAME tags."
            )
    return tuple(parts)


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

    current_report = load_current_test_report(os.getcwd())
    report = current_report["report"]

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
    root_tag=None,
):
    anchor = hashlib.sha256(tc.encode("utf-8")).hexdigest()[:16]
    root_tag = root_tag or root_cause_tag_for_bg(bg)
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


def _replace_body(lines, start, end, value, source):
    text = str(value or "").strip() if source == "root source_evidence" else normalize_field_text(value, source)
    if not text:
        raise ValueError(f"Error: {source} must be non-empty.")
    replacement = [line + "\n" for line in text.splitlines()]
    old_length = end - start
    lines[start:end] = replacement + ["\n"]
    return len(replacement) + 1 - old_length


def _checkpoint_bg_range(lines, checkpoint_path, bg):
    fg, fc, ck = parse_checkpoint_path(checkpoint_path)
    sec_start, sec_end = locate_section(lines)
    fg_line = find_tag_line(lines, sec_start + 1, sec_end, fg)
    if fg_line < 0:
        raise ValueError(f"Error: dynamic Bug path {checkpoint_path} is missing <{fg}>.")
    fg_end = next_boundary(lines, fg_line + 1, sec_end, [lambda t: "<FG-" in t])
    fc_line = find_tag_line(lines, fg_line + 1, fg_end, fc)
    if fc_line < 0:
        raise ValueError(f"Error: dynamic Bug path {checkpoint_path} is missing <{fc}>.")
    fc_end = next_boundary(lines, fc_line + 1, fg_end, [lambda t: "<FC-" in t])
    ck_line = find_tag_line(lines, fc_line + 1, fc_end, ck)
    if ck_line < 0:
        raise ValueError(f"Error: dynamic Bug path {checkpoint_path} is missing <{ck}>.")
    ck_end = next_boundary(
        lines,
        ck_line + 1,
        fc_end,
        [lambda t: "<CK-" in t, lambda t: "<FC-" in t],
    )
    bg_line = find_tag_line(lines, ck_line + 1, ck_end, bg)
    if bg_line < 0:
        raise ValueError(
            f"Error: dynamic Bug path {checkpoint_path} is missing <{bg}>."
        )
    bg_end = next_boundary(
        lines,
        bg_line + 1,
        ck_end,
        [lambda t: "<BG-" in t, lambda t: "<CK-" in t, lambda t: "<FC-" in t],
    )
    return bg_line, bg_end


def _update_bug_fields(
    lines,
    checkpoint_path,
    bg,
    bug_title,
    fields,
    root_tag,
    root_label,
):
    bg_line, bg_end = _checkpoint_bg_range(lines, checkpoint_path, bg)
    lines[bg_line] = f"###### {bug_title}（{bg_confidence(bg)}%） <{bg}>\n"
    marker_indexes = {}
    title_indexes = {}
    titles = dict(BUG_ANALYSIS_SECTION_TITLES)
    for key, marker in BUG_ANALYSIS_SECTION_MARKERS:
        marker_index = next(
            (
                index
                for index in range(bg_line + 1, bg_end)
                if lines[index].strip() == marker
            ),
            -1,
        )
        if marker_index < 0:
            raise ValueError(f"Error: <{bg}> is missing {marker}.")
        marker_indexes[key] = marker_index
        title_indexes[key] = next(
            (
                index
                for index in range(bg_line + 1, marker_index)
                if lines[index].strip() == titles[key]
            ),
            -1,
        )
        if title_indexes[key] < 0:
            raise ValueError(f"Error: <{bg}> is missing {titles[key]}.")

    ordered_keys = [key for key, _marker in BUG_ANALYSIS_SECTION_MARKERS]
    for position, key in enumerate(ordered_keys):
        value = fields.get(key)
        if key not in marker_indexes or value is None:
            continue
        marker_index = marker_indexes[key]
        body_end = (
            title_indexes[ordered_keys[position + 1]]
            if position + 1 < len(ordered_keys)
            else bg_end
        )
        delta = _replace_body(
            lines, marker_index + 1, body_end, value, f"bug {key}"
        )
        for marker_key, index in list(marker_indexes.items()):
            if index > marker_index:
                marker_indexes[marker_key] = index + delta
        for title_key, index in list(title_indexes.items()):
            if index > marker_index:
                title_indexes[title_key] = index + delta
        bg_end += delta

    trigger_index = marker_indexes["trigger"]
    trigger_end = bg_end
    trigger_body = [
        line
        for line in lines[trigger_index + 1 : trigger_end]
        if not line.strip().startswith("<CAUSE-REF-ROOT-")
    ]
    if root_tag:
        root_reference = root_cause_reference(root_tag, root_label)
        while trigger_body and not trigger_body[-1].strip():
            trigger_body.pop()
        trigger_body.extend([root_reference + "\n"])
    lines[trigger_index + 1 : trigger_end] = trigger_body


def _root_entity_range(lines, root_tag):
    starts = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError("Error: target markdown must contain one closed ROOT-CAUSES container.")
    start, end = starts[0], ends[0]
    token = f"<{root_tag}>"
    root_line = next((i for i in range(start + 1, end) if token in lines[i]), -1)
    if root_line < 0:
        raise ValueError(f"Error: root cause entity <{root_tag}> does not exist.")
    entity_start = _root_entity_start(lines, root_line, start)
    entity_end = next(
        (
            i
            for i in range(root_line + 1, end)
            if re.match(r"^###\s+.+\s+<ROOT-[A-Z0-9][A-Z0-9-]*>\s*$", lines[i].strip())
        ),
        end,
    )
    return entity_start, root_line, entity_end


def _root_entity_start(lines, heading_index, container_start):
    index = heading_index - 1
    while index > container_start and not lines[index].strip():
        index -= 1
    if index > container_start and lines[index].lstrip().startswith(
        '<a id="root-cause-'
    ):
        return index
    return heading_index


def _update_root_fields(lines, root_tag, root_title, fields):
    _entity_start, root_line, entity_end = _root_entity_range(lines, root_tag)
    if root_title:
        heading = lines[root_line].rstrip("\n")
        lines[root_line] = re.sub(
            r"^###\s+.+?\s+(<ROOT-[A-Z0-9][A-Z0-9-]*>)\s*$",
            lambda match: f"### {normalize_visible_title(root_title, root_tag)} {match.group(1)}\n",
            heading,
        )
    marker_indexes = {}
    title_indexes = {}
    titles = dict(ROOT_ANALYSIS_SECTION_TITLES)
    for key, marker in ROOT_ANALYSIS_SECTION_MARKERS:
        marker_indexes[key] = next(
            (i for i in range(root_line + 1, entity_end) if lines[i].strip() == marker),
            -1,
        )
        if marker_indexes[key] < 0:
            raise ValueError(f"Error: <{root_tag}> is missing {marker}.")
        title_indexes[key] = next(
            (
                i
                for i in range(root_line + 1, marker_indexes[key])
                if lines[i].strip() == titles[key]
            ),
            -1,
        )
        if title_indexes[key] < 0:
            raise ValueError(f"Error: <{root_tag}> is missing {titles[key]}.")
    related_title_index = next(
        (i for i in range(root_line + 1, entity_end) if lines[i].strip() == RELATED_BUGS_TITLE),
        -1,
    )
    if related_title_index < 0:
        raise ValueError(f"Error: <{root_tag}> is missing {RELATED_BUGS_TITLE}.")
    ordered_keys = [key for key, _marker in ROOT_ANALYSIS_SECTION_MARKERS]
    for position, key in enumerate(ordered_keys):
        value = fields.get(key)
        if key not in marker_indexes or value is None:
            continue
        marker_index = marker_indexes[key]
        body_end = (
            title_indexes[ordered_keys[position + 1]]
            if position + 1 < len(ordered_keys)
            else related_title_index
        )
        delta = _replace_body(
            lines, marker_index + 1, body_end, value, f"root {key}"
        )
        for field_key, index in list(marker_indexes.items()):
            if index > marker_index:
                marker_indexes[field_key] = index + delta
        for title_key, index in list(title_indexes.items()):
            if index > marker_index:
                title_indexes[title_key] = index + delta
        if related_title_index > marker_index:
            related_title_index += delta
        entity_end += delta


def _source_evidence_body(args):
    if args.source_unavailable_reason is not None:
        if any(
            value is not None
            for value in (
                args.first_error_line,
                args.first_error_note,
                args.propagation_line,
                args.propagation_note,
                args.observable_line,
                args.observable_note,
            )
        ):
            raise ValueError(
                "Error: --source-unavailable cannot be combined with source line evidence."
            )
        reason = normalize_field_text(args.source_unavailable_reason, "source-unavailable reason")
        return f"{SOURCE_UNAVAILABLE_MARKER}\n{reason}"
    if not args.source_location:
        raise ValueError(
            "Error: --source-location is required for the HDL source branch."
        )
    match = SOURCE_LOCATION_PATTERN.fullmatch(args.source_location.strip())
    if match is None or int(match.group("start")) > int(match.group("end")):
        raise ValueError(
            "Error: --source-location must use path:start-end with start <= end."
        )
    if any(value is None for value in (
        args.first_error_line,
        args.first_error_note,
        args.propagation_line,
        args.propagation_note,
        args.observable_line,
        args.observable_note,
    )):
        raise ValueError(
            "Error: HDL source evidence requires each of the three line and note pairs."
        )
    extension = match.group("extension").lower()
    language, comment = SOURCE_LANGUAGE[extension]
    location_start = int(match.group("start"))
    location_end = int(match.group("end"))
    for line in (args.first_error_line, args.propagation_line, args.observable_line):
        if not location_start <= line <= location_end:
            raise ValueError(
                "Error: each source evidence line must be inside --source-location."
            )
    notes = (
        (
            "ROOT-SOURCE-FIRST-ERROR",
            args.first_error_line,
            normalize_field_text(args.first_error_note, "first-error note"),
        ),
        (
            "ROOT-SOURCE-PROPAGATION",
            args.propagation_line,
            normalize_field_text(args.propagation_note, "propagation note"),
        ),
        (
            "ROOT-SOURCE-OBSERVABLE",
            args.observable_line,
            normalize_field_text(args.observable_note, "observable note"),
        ),
    )
    workspace = os.path.realpath(os.getcwd())
    source_relative_path = match.group("path")
    if os.path.isabs(source_relative_path):
        raise ValueError("Error: --source-location path must be workspace-relative.")
    source_path = os.path.realpath(os.path.join(workspace, source_relative_path))
    if os.path.commonpath([workspace, source_path]) != workspace:
        raise ValueError("Error: --source-location escapes the workspace.")
    if not os.path.isfile(source_path):
        raise FileNotFoundError(
            f"Error: source file from --source-location does not exist: {match.group('path')}"
        )
    with open(source_path, "r", encoding="utf-8") as source_file:
        all_source_lines = source_file.read().splitlines()
    if location_end > len(all_source_lines):
        raise ValueError(
            f"Error: --source-location ends at line {location_end}, but the source has "
            f"only {len(all_source_lines)} lines."
        )
    code_lines = list(all_source_lines[location_start - 1 : location_end])
    if any(marker in "\n".join(code_lines) for marker in SOURCE_MARKERS):
        raise ValueError(
            "Error: the selected source excerpt already contains ROOT-SOURCE markers. "
            "Use the unmodified RTL source range."
        )
    annotations = {}
    for marker, line_number, note in notes:
        annotations.setdefault(line_number, []).append(f"<{marker}> {note}")
    for line_number, values in annotations.items():
        index = line_number - location_start
        separator = " " if code_lines[index].strip() else ""
        code_lines[index] = (
            code_lines[index]
            + separator
            + comment
            + " "
            + f" {comment} ".join(values)
        )
    return (
        f"{args.source_location}\n\n```{language}\n"
        + "\n".join(code_lines)
        + "\n```"
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
    lines,
    fg,
    fc,
    ck,
    bg,
    tc,
    bd,
    fg_title,
    fc_title,
    ck_title,
    tc_title,
    root_tag=None,
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
        root_tag,
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


def ensure_root_cause_entry(
    lines,
    bg,
    bd,
    checkpoint_path,
    root_tag=None,
    root_title=None,
):
    """Create one root entity and keep its reverse BG link idempotent."""

    starts = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            "Error: target markdown must contain one closed ROOT-CAUSES container "
            "before WAVEFORM-EVIDENCE."
        )
    start, end = starts[0], ends[0]
    root_tag = root_tag or root_cause_tag_for_bg(bg)
    root_token = f"<{root_tag}>"
    entity_line = next(
        (i for i in range(start + 1, end) if root_token in lines[i]),
        -1,
    )
    relation = related_bug_reference(checkpoint_path, bg)
    if entity_line < 0:
        lines.insert(
            end,
            render_root_cause_entry(
                root_tag, root_title or bd, checkpoint_path, bg
            ),
        )
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
            raise SkillDocumentError(
                "ROOT_CAUSE_CONTAINER_MALFORMED",
                "The Bug document must contain one closed ROOT-CAUSES container.",
                details={
                    "root_causes_start_count": len(starts),
                    "root_causes_end_count": len(ends),
                    "repair_call": _repair_skill_call(),
                },
                next_action=_repair_next_action(),
            )
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
    lines,
    fg,
    fc,
    ck,
    bg,
    tc,
    bd,
    fg_title,
    fc_title,
    ck_title,
    tc_title,
    root_tag=None,
    root_title=None,
):
    message = _insert_dynamic_content(
        lines,
        fg,
        fc,
        ck,
        bg,
        tc,
        bd,
        fg_title,
        fc_title,
        ck_title,
        tc_title,
        root_tag,
    )
    lines[:] = "".join(lines).splitlines(keepends=True)
    ensure_root_cause_entry(
        lines,
        bg,
        bd,
        f"{fg}/{fc}/{ck}",
        root_tag=root_tag,
        root_title=root_title,
    )
    lines[:] = ensure_markdown_heading_spacing(
        "".join(lines), HEADING_COMPANION_MARKERS
    ).splitlines(keepends=True)
    return message


@contextmanager
def _document_lock(path):
    """Serialize process-level updates to one Bug document."""
    directory = os.path.dirname(path) or os.curdir
    os.makedirs(directory, exist_ok=True)
    lock_path = os.path.join(directory, f".{os.path.basename(path)}.lock")
    with open(lock_path, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(path, content, expected_content=None):
    """Replace one Bug document atomically after a complete in-memory mutation."""
    directory = os.path.dirname(path) or os.curdir
    temporary = None
    existing_mode = stat.S_IMODE(os.stat(path).st_mode) if os.path.exists(path) else None
    try:
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_content is not None:
            with open(path, "r", encoding="utf-8") as current_handle:
                if current_handle.read() != expected_content:
                    raise RuntimeError(
                        "target Bug document changed while the update was prepared; "
                        "retry the same command with the current document"
                    )
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _target_document(runtime_config):
    return os.path.join(
        os.getcwd(),
        DYNAMIC_BUG_DOCUMENT_PATH.format(
            OUT=runtime_config["OUT"],
            DUT=runtime_config["DUT"],
        ),
    )


def _ensure_target_document(target, dut):
    if not os.path.exists(target):
        _atomic_write_text(target, make_bug_analysis_document(dut))


def _load_document(target):
    with open(target, "r", encoding="utf-8") as handle:
        original = handle.read()
    lines = original.splitlines(keepends=True)
    ensure_root_cause_container(lines)
    return lines, original


def _remove_stale_root_relation(lines, checkpoint_path, bg, root_tag):
    """Move one BG path between roots without leaving an orphan reverse link."""
    relation_token = f"<RELATED-BUG-{checkpoint_path}/{bg}>"
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_MARKER),
        -1,
    )
    end = next(
        (i for i, line in enumerate(lines) if line.strip() == ROOT_CAUSES_END_MARKER),
        -1,
    )
    if start < 0 or end < 0 or start >= end:
        return
    heading_pattern = re.compile(r"^###\s+.+\s+(<ROOT-[A-Z0-9][A-Z0-9-]*>)\s*$")
    headings = [
        i
        for i in range(start + 1, end)
        if heading_pattern.match(lines[i].strip())
    ]
    entity_starts = [
        _root_entity_start(lines, heading_index, start)
        for heading_index in headings
    ]
    for position, heading_index in reversed(list(enumerate(headings))):
        heading_match = heading_pattern.match(lines[heading_index].strip())
        if heading_match is None:
            continue
        existing_root = heading_match.group(1)[1:-1]
        if existing_root == root_tag:
            continue
        entity_start = entity_starts[position]
        entity_end = entity_starts[position + 1] if position + 1 < len(headings) else end
        if entity_end >= end or not heading_pattern.match(lines[entity_end].strip()):
            entity_end = end
        entity_lines = lines[entity_start:entity_end]
        original_length = len(entity_lines)
        entity_lines = [
            line for line in entity_lines if relation_token not in line
        ]
        lines[entity_start:entity_end] = entity_lines
        if len(entity_lines) == original_length:
            continue
        remaining = any(
            "<RELATED-BUG-" in line for line in entity_lines
        )
        if not remaining:
            del lines[entity_start : entity_start + len(entity_lines)]
            end -= len(entity_lines)


def _repair_argument_values(args):
    return {
        "-BG": args.BG,
        "-TC": args.TC,
        "-BD": args.BD,
        "-CHECKPOINT": args.CHECKPOINT,
        "-ROOT-TAG": args.root_tag,
        "-ROOT-TITLE": args.ROOT_TITLE,
        "-OVERVIEW": args.OVERVIEW,
        "-SYMPTOMS": args.SYMPTOMS,
        "-TRIGGER": args.TRIGGER,
        "-ANALYSIS": args.ANALYSIS,
        "-CAUSAL-CHAIN": args.causal_chain,
        "-FIX": args.FIX,
        "-RETEST": args.RETEST,
        "-SOURCE-LOCATION": args.source_location,
        "-SOURCE-UNAVAILABLE": args.source_unavailable_reason,
        "-FIRST-ERROR-LINE": args.first_error_line,
        "-FIRST-ERROR-NOTE": args.first_error_note,
        "-PROPAGATION-LINE": args.propagation_line,
        "-PROPAGATION-NOTE": args.propagation_note,
        "-OBSERVABLE-LINE": args.observable_line,
        "-OBSERVABLE-NOTE": args.observable_note,
    }


def _document_lines_with_normalized_root_closers(content):
    """Split merged ROOT closers and remove unsupported machine closing tags."""

    has_only_crlf = "\r\n" in content and "\n" not in content.replace("\r\n", "")
    newline = "\r\n" if has_only_crlf else "\n"
    trailing_newline = content.endswith(("\n", "\r"))
    repaired = []
    removed = {marker: 0 for marker in UNSUPPORTED_ROOT_CLOSING_MARKERS}
    in_fence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            repaired.append(line)
            in_fence = not in_fence
            continue
        if in_fence:
            repaired.append(line)
            continue

        value = line
        for marker in UNSUPPORTED_ROOT_CLOSING_MARKERS:
            count = value.count(marker)
            if count:
                removed[marker] += count
                value = value.replace(marker, "")

        parts = value.split(ROOT_CAUSES_END_MARKER)
        if len(parts) == 1:
            if value.strip():
                repaired.append(value)
            elif line.strip() == "":
                repaired.append(line)
            continue
        for index, part in enumerate(parts):
            if part.strip():
                repaired.append(part)
            if index < len(parts) - 1:
                repaired.append(ROOT_CAUSES_END_MARKER)

    removed = {marker: count for marker, count in removed.items() if count}
    return repaired, newline, trailing_newline, removed


def _join_document_lines(lines, newline, trailing_newline):
    content = newline.join(lines)
    if trailing_newline:
        content += newline
    return content


def _outside_fence_lines(lines):
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
            visible.append(stripped)
    return visible


def _repair_failure(error_code, error, *, details=None, mode="bug"):
    action = (
        "Use -MODE bug for each reported BG path to establish exactly one valid "
        "ROOT reference, then call -MODE repair again. Do not edit the Bug document "
        "directly."
    )
    if mode == "root":
        action = (
            "Use -MODE root to restore the reported ROOT entity fields, then call "
            "-MODE repair again. Do not edit the Bug document directly."
        )
    raise SkillDocumentError(
        error_code,
        error,
        details=details,
        next_action=action,
        workflow_context=_workflow_context(
            "repair_blocked",
            next_skill_mode=mode,
            resume_mode="repair",
        ),
    )


_ROOT_TAG_PATTERN = ROOT_ENTITY_TAG_PATTERN.pattern
_CAUSE_REFERENCE_PATTERN = re.compile(
    rf"^<CAUSE-REF-({_ROOT_TAG_PATTERN})>\s+\[([^\]\n]+)\]\(#([^)]+)\)\s*$"
)
_DYNAMIC_REPAIR_HEADING_PATTERNS = {
    "FG": re.compile(r"^###\s+.+?\s+<(FG-[^<>/]+)>\s*$"),
    "FC": re.compile(r"^####\s+.+?\s+<(FC-[^<>/]+)>\s*$"),
    "CK": re.compile(r"^#####\s+.+?\s+<(CK-[^<>/]+)>\s*$"),
    "BG": re.compile(r"^######\s+.+?\s+<(BG-[^<>/]+)>\s*$"),
}


def _parse_repair_root_entities(lines, visible, start, end):
    heading_pattern = re.compile(
        rf"^###\s+(.+?)\s+<({_ROOT_TAG_PATTERN})>\s*$"
    )
    headings = []
    for index in range(start + 1, end):
        match = heading_pattern.fullmatch(visible[index])
        if match:
            headings.append((index, match.group(2), match.group(1).strip()))
    tags = [tag for _index, tag, _title in headings]
    duplicates = sorted(tag for tag in set(tags) if tags.count(tag) > 1)
    if duplicates:
        _repair_failure(
            "REPAIR_ROOT_IDENTITY_AMBIGUOUS",
            "ROOT entity tags must be document-wide unique before relations can be rebuilt.",
            details={"duplicate_root_tags": duplicates},
            mode="root",
        )

    entity_starts = [
        _root_entity_start(lines, heading_index, start)
        for heading_index, _tag, _title in headings
    ]
    entities = []
    for position, (heading_index, tag, title) in enumerate(headings):
        entity_end = (
            entity_starts[position + 1] if position + 1 < len(headings) else end
        )
        related_indexes = [
            index
            for index in range(heading_index + 1, entity_end)
            if visible[index] == RELATED_BUGS_MARKER
        ]
        if len(related_indexes) != 1:
            _repair_failure(
                "REPAIR_RELATED_BUGS_MARKER_INVALID",
                f"<{tag}> must contain exactly one {RELATED_BUGS_MARKER} marker.",
                details={
                    "root_tag": tag,
                    "related_bugs_marker_count": len(related_indexes),
                },
                mode="root",
            )
        entities.append(
            {
                "tag": tag,
                "title": title,
                "entity_end": entity_end,
                "related_index": related_indexes[0],
            }
        )
    return entities


def _parse_repair_bg_assignments(visible, start, end, root_tags):
    hierarchy = {"FG": None, "FC": None, "CK": None}
    records = []
    current = None

    def close_current(boundary):
        nonlocal current
        if current is None:
            return
        current["end"] = boundary
        records.append(current)
        current = None

    for index in range(start + 1, end):
        matched = next(
            (
                (kind, match)
                for kind, pattern in _DYNAMIC_REPAIR_HEADING_PATTERNS.items()
                if (match := pattern.fullmatch(visible[index])) is not None
            ),
            None,
        )
        if matched is None:
            continue
        close_current(index)
        kind, match = matched
        tag = match.group(1)
        if kind == "FG":
            hierarchy.update({"FG": tag, "FC": None, "CK": None})
        elif kind == "FC":
            hierarchy.update({"FC": tag, "CK": None})
        elif kind == "CK":
            hierarchy["CK"] = tag
        else:
            if not all(hierarchy.values()):
                _repair_failure(
                    "REPAIR_BUG_PATH_INCOMPLETE",
                    f"<{tag}> does not have one complete FG/FC/CK parent path.",
                    details={"bug_tag": tag, "hierarchy": hierarchy.copy()},
                )
            current = {
                "bug": tag,
                "path": "/".join([*hierarchy.values(), tag]),
                "checkpoint": "/".join(hierarchy.values()),
                "start": index,
            }
    close_current(end)

    paths = [record["path"] for record in records]
    duplicates = sorted(path for path in set(paths) if paths.count(path) > 1)
    if duplicates:
        _repair_failure(
            "REPAIR_BUG_IDENTITY_AMBIGUOUS",
            "Each exact FG/FC/CK/BG path must occur only once before relations can be rebuilt.",
            details={"duplicate_bug_paths": duplicates},
        )

    assignments = {}
    for record in records:
        references = []
        hinted_lines = []
        for index in range(record["start"] + 1, record["end"]):
            if "<CAUSE-REF-ROOT-" in visible[index]:
                hinted_lines.append(index + 1)
            match = _CAUSE_REFERENCE_PATTERN.fullmatch(visible[index])
            if match:
                references.append(
                    {
                        "tag": match.group(1),
                        "line": index + 1,
                    }
                )
        if len(references) != 1:
            _repair_failure(
                "REPAIR_BUG_ROOT_REFERENCE_INVALID",
                f"{record['path']} must contain exactly one canonical CAUSE-REF-ROOT reference.",
                details={
                    "bug_path": record["path"],
                    "reference_count": len(references),
                    "candidate_lines": hinted_lines,
                },
            )
        root_tag = references[0]["tag"]
        if root_tag not in root_tags:
            _repair_failure(
                "REPAIR_REFERENCED_ROOT_MISSING",
                f"{record['path']} points to missing root entity <{root_tag}>.",
                details={
                    "bug_path": record["path"],
                    "root_tag": root_tag,
                    "reference_line": references[0]["line"],
                },
            )
        assignments.setdefault(root_tag, []).append(record)
    return assignments


def _repair_document_content(content):
    """Rebuild ROOT reverse relations from canonical BG-side cause references."""

    lines, newline, trailing_newline, removed = (
        _document_lines_with_normalized_root_closers(content)
    )
    visible = _outside_fence_lines(lines)
    root_starts = [i for i, value in enumerate(visible) if value == ROOT_CAUSES_MARKER]
    root_ends = [i for i, value in enumerate(visible) if value == ROOT_CAUSES_END_MARKER]
    if len(root_starts) != 1 or len(root_ends) != 1 or root_starts[0] >= root_ends[0]:
        raise SkillDocumentError(
            "ROOT_CAUSE_CONTAINER_MALFORMED",
            "The Bug document must contain one closed ROOT-CAUSES container.",
            details={
                "root_causes_start_count": len(root_starts),
                "root_causes_end_count": len(root_ends),
                "repair_call": _repair_skill_call(),
            },
            next_action=(
                "Restore one unambiguous ROOT-CAUSES container through the owning Skill "
                "mode, then call -MODE repair again. Do not edit semantic analysis fields."
            ),
        )
    dynamic_starts = [i for i, value in enumerate(visible) if value == DYNAMIC_BUGS_MARKER]
    dynamic_ends = [i for i, value in enumerate(visible) if value == DYNAMIC_BUGS_END_MARKER]
    if (
        len(dynamic_starts) != 1
        or len(dynamic_ends) != 1
        or dynamic_starts[0] >= dynamic_ends[0]
    ):
        _repair_failure(
            "REPAIR_DYNAMIC_BUG_CONTAINER_INVALID",
            "The Bug document must contain one closed DYNAMIC-BUGS container.",
            details={
                "dynamic_start_count": len(dynamic_starts),
                "dynamic_end_count": len(dynamic_ends),
            },
        )

    root_start, root_end = root_starts[0], root_ends[0]
    entities = _parse_repair_root_entities(lines, visible, root_start, root_end)
    root_tags = {entity["tag"] for entity in entities}
    assignments = _parse_repair_bg_assignments(
        visible,
        dynamic_starts[0],
        dynamic_ends[0],
        root_tags,
    )
    orphaned = sorted(root_tags - set(assignments))
    if orphaned:
        _repair_failure(
            "REPAIR_ROOT_WITHOUT_FORWARD_REFERENCE",
            "Every ROOT entity must be selected by at least one BG before relations can be rebuilt.",
            details={"root_tags": orphaned},
        )

    rebuilt = {}
    for entity in reversed(entities):
        records = sorted(assignments[entity["tag"]], key=lambda item: item["path"])
        relations = [
            related_bug_reference(record["checkpoint"], record["bug"])
            for record in records
        ]
        lines[entity["related_index"] + 1 : entity["entity_end"]] = relations + [""]
        rebuilt[entity["tag"]] = [record["path"] for record in records]

    repaired_content = _join_document_lines(lines, newline, trailing_newline)
    return repaired_content, {
        "removed_markers": removed,
        "rebuilt_roots": dict(sorted(rebuilt.items())),
        "relation_count": sum(len(paths) for paths in rebuilt.values()),
    }


def _run_repair_operation(runtime_config, args, target):
    del runtime_config
    unexpected = [
        name for name, value in _repair_argument_values(args).items() if value is not None
    ]
    if unexpected:
        raise ValueError(
            "Error: repair mode accepts no semantic Bug or ROOT arguments: "
            + ", ".join(unexpected)
            + ". Call only -MODE repair."
        )
    with open(target, "r", encoding="utf-8", newline="") as handle:
        original = handle.read()
    repaired, details = _repair_document_content(original)
    changed = repaired != original
    if changed:
        _atomic_write_text(target, repaired, expected_content=original)
    return {
        "operation": "repair",
        "success": True,
        "status": "repaired" if changed else "already_canonical",
        "target": target,
        **details,
        "next_action": (
            "Retry the pending -MODE bug or -MODE root call, then call Check. "
            "Do not edit the Bug document directly."
        ),
        "workflow_context": _workflow_context(
            "relations_repaired",
            identity={"root_paths": details["rebuilt_roots"]},
            completed=[
                "normalized ROOT closing markers",
                "rebuilt ROOT reverse relations from BG references",
            ],
            next_skill_mode="retry_previous",
            resume_mode="bug_or_root",
        ),
    }


def _run_bug_operation(runtime_config, args, target):
    root_only = {
        "-ANALYSIS": args.ANALYSIS,
        "-CAUSAL-CHAIN": args.causal_chain,
        "-FIX": args.FIX,
        "-RETEST": args.RETEST,
        "-SOURCE-LOCATION": args.source_location,
        "-SOURCE-UNAVAILABLE": args.source_unavailable_reason,
        "-FIRST-ERROR-LINE": args.first_error_line,
        "-FIRST-ERROR-NOTE": args.first_error_note,
        "-PROPAGATION-LINE": args.propagation_line,
        "-PROPAGATION-NOTE": args.propagation_note,
        "-OBSERVABLE-LINE": args.observable_line,
        "-OBSERVABLE-NOTE": args.observable_note,
    }
    unexpected = [name for name, value in root_only.items() if value is not None]
    if unexpected:
        raise ValueError(
            "Error: bug mode does not accept root-only arguments: "
            + ", ".join(unexpected)
            + ". Use a separate -MODE root call."
        )
    required = (
        args.BG,
        args.TC,
        args.BD,
        args.CHECKPOINT,
        args.root_tag,
        args.ROOT_TITLE,
        args.OVERVIEW,
        args.SYMPTOMS,
        args.TRIGGER,
    )
    if not all(required):
        raise ValueError(
            "Error: bug mode requires -BG, -TC, -BD, -CHECKPOINT, -ROOT-TAG, "
            "-ROOT-TITLE, -OVERVIEW, -SYMPTOMS, and -TRIGGER."
        )
    validate_dynamic_bg_tag(args.BG)
    validate_tag(args.TC, "TC")
    escaped_bd = escape_markdown_asterisk(normalize_visible_title(args.BD, args.BG))
    resolved_paths = resolve_fg_fc_ck_list_by_tc(
        args.TC,
        runtime_config["OUT"],
        runtime_config["test_output_dir"],
    )
    checkpoint = parse_checkpoint_path(args.CHECKPOINT)
    if checkpoint not in resolved_paths:
        available = ", ".join("/".join(path) for path in resolved_paths)
        raise ValueError(
            f"Error: -CHECKPOINT '{args.CHECKPOINT}' is not associated with -TC "
            f"in the current report. Available paths: {available}."
        )
    resolved_paths = [checkpoint]
    function_file = os.path.join(
        os.getcwd(),
        runtime_config["OUT"],
        f"{runtime_config['DUT']}_functions_and_checks.md",
    )
    tc_title = resolve_test_title(args.TC)
    root_tag = args.root_tag
    validate_root_tag(root_tag)
    root_title = normalize_visible_title(args.ROOT_TITLE, root_tag)
    fields = {
        "overview": args.OVERVIEW,
        "symptoms": args.SYMPTOMS,
        "trigger": args.TRIGGER,
    }
    lines, original = _load_document(target)
    messages = []
    for fg, fc, ck in resolved_paths:
        checkpoint_path = f"{fg}/{fc}/{ck}"
        _remove_stale_root_relation(lines, checkpoint_path, args.BG, root_tag)
        message = insert_content(
            lines,
            fg,
            fc,
            ck,
            args.BG,
            args.TC,
            escaped_bd,
            *resolve_checkpoint_titles(function_file, fg, fc, ck),
            tc_title,
            root_tag=root_tag,
            root_title=root_title,
        )
        _update_bug_fields(
            lines,
            checkpoint_path,
            args.BG,
            escaped_bd,
            fields,
            root_tag,
            root_title,
        )
        messages.append(f"{message} ({fg}/{fc}/{ck})")
    lines[:] = ensure_markdown_heading_spacing(
        "".join(lines), HEADING_COMPANION_MARKERS
    ).splitlines(keepends=True)
    _atomic_write_text(target, "".join(lines), expected_content=original)
    return {
        "operation": "bug",
        "success": True,
        "target": target,
        "paths": ["/".join(path) for path in resolved_paths],
        "bug_tag": args.BG,
        "test_case": args.TC,
        "root_tag": root_tag,
        "bug_fields_completed": True,
        "next_action": (
            "Use -MODE root to complete the ROOT fields. Run final WaveInfo, then call "
            "ApplyWaveInfoEvidence for each exact BG/TC path."
        ),
        "workflow_context": _workflow_context(
            "bug_fields_recorded",
            identity={
                "bug_tag": args.BG,
                "test_case": args.TC,
                "checkpoint_paths": ["/".join(path) for path in resolved_paths],
                "root_tag": root_tag,
                "root_title": root_title,
            },
            completed=[
                "upserted the exact BG/TC path",
                "completed the three BG analysis fields",
                "established the BG-to-ROOT identity",
            ],
            next_skill_mode="root",
            resume_mode="bug",
        ),
        "messages": messages,
    }


def _run_root_operation(runtime_config, args, target):
    del runtime_config
    bug_only = {
        "-BG": args.BG,
        "-TC": args.TC,
        "-BD": args.BD,
        "-CHECKPOINT": args.CHECKPOINT,
        "-OVERVIEW": args.OVERVIEW,
        "-SYMPTOMS": args.SYMPTOMS,
        "-TRIGGER": args.TRIGGER,
    }
    unexpected = [name for name, value in bug_only.items() if value is not None]
    if unexpected:
        raise ValueError(
            "Error: root mode does not accept bug-only arguments: "
            + ", ".join(unexpected)
            + ". Use a separate -MODE bug call."
        )
    required = (
        args.root_tag,
        args.ROOT_TITLE,
        args.ANALYSIS,
        args.causal_chain,
        args.FIX,
        args.RETEST,
    )
    if not all(required):
        raise ValueError(
            "Error: root mode requires -ROOT-TAG, -ROOT-TITLE, -ANALYSIS, "
            "-CAUSAL-CHAIN, -FIX, and -RETEST."
        )
    validate_root_tag(args.root_tag)
    lines, original = _load_document(target)
    fields = {
        "analysis": args.ANALYSIS,
        "source_evidence": _source_evidence_body(args),
        "causal_chain": args.causal_chain,
        "fix": args.FIX,
        "retest": args.RETEST,
    }
    _update_root_fields(lines, args.root_tag, args.ROOT_TITLE, fields)
    entity_start, _root_line, entity_end = _root_entity_range(lines, args.root_tag)
    related_bug_paths = re.findall(
        r"<RELATED-BUG-([^<>]+)>",
        "".join(lines[entity_start:entity_end]),
    )
    lines[:] = ensure_markdown_heading_spacing(
        "".join(lines), HEADING_COMPANION_MARKERS
    ).splitlines(keepends=True)
    _atomic_write_text(target, "".join(lines), expected_content=original)
    return {
        "operation": "root",
        "success": True,
        "target": target,
        "root_tag": args.root_tag,
        "root_fields_completed": list(fields),
        "next_action": (
            "Run final WaveInfo and ApplyWaveInfoEvidence for every confirmed BG/TC path, "
            "then call Check. Do not edit the Bug Markdown file manually."
        ),
        "workflow_context": _workflow_context(
            "root_fields_recorded",
            identity={
                "root_tag": args.root_tag,
                "related_bug_paths": related_bug_paths,
            },
            completed=["completed the five ROOT analysis fields"],
            next_skill_mode=None,
            resume_mode="root",
        ),
    }


def main():
    runtime_config = load_runtime_config(os.getcwd())
    configured_test_dir = runtime_config["test_output_dir"]
    args = parse_args(configured_test_dir)
    try:
        target = _target_document(runtime_config)
        with _document_lock(target):
            _ensure_target_document(target, runtime_config["DUT"])
            if args.MODE == "repair":
                result = _run_repair_operation(runtime_config, args, target)
            elif args.MODE == "root":
                result = _run_root_operation(runtime_config, args, target)
            else:
                result = _run_bug_operation(runtime_config, args, target)
    except SkillDocumentError as error:
        print(
            json.dumps(
                error.as_result(args.MODE),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(2) from error
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "operation": args.MODE,
                    "success": False,
                    "error_code": "DYNAMIC_BUG_SKILL_CALL_INVALID",
                    "error": str(error),
                    "next_action": (
                        "Fix the reported input or source evidence, then retry the same "
                        "MODE with the current report and document."
                    ),
                    "workflow_context": _workflow_context(
                        "skill_call_blocked",
                        next_skill_mode=args.MODE,
                        resume_mode=args.MODE,
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(2) from error
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
