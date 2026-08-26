# -*- coding: utf-8 -*-
"""Checkers for <BG-STATIC-*> tagged static bug analysis documents.

Two checker classes are provided:

* ``UnityChipCheckerStaticBugFormat``      — used inside ``static_bug_analysis``
  and its sub-stages.  Verifies that every ``<BG-STATIC-*>`` tag has a
  corresponding ``<LINK-BUG-[BG-TBD]>`` child tag.

* ``UnityChipCheckerStaticBugValidation``  — used in ``static_bug_validation``.
  Verifies that no ``<LINK-BUG-[BG-TBD]>`` remains, that each resolved
  ``<LINK-BUG-*>`` value is syntactically valid, and that every confirmed
  dynamic-bug reference actually exists in the dynamic bug analysis document.

Tag hierarchy parsed by ``parse_nested_keys``::

    <FG-*>
      <FC-*>
        <CK-*>                              ← one CK can have multiple BG-STATIC children
          <BG-STATIC-*>
            <LINK-BUG-[BG-TBD]>             ← pending
              <FILE-filepath:line1-line2>   ← source location (required)
          <BG-STATIC-*>
            <LINK-BUG-[BG-NA]>              ← false positive
              <FILE-filepath:line1-line2>   ← source location (required)
          <BG-STATIC-*>
            <LINK-BUG-[BG-NAME-xx]>         ← single confirmed
              <FILE-filepath:line1-line2>   ← source location (required)
          <BG-STATIC-*>
            <LINK-BUG-[BG-N1-xx][BG-N2-xx]> ← multiple confirmed
              <FILE-filepath:line1-line2>   ← source location (required)
"""

import re
import os
from typing import List, Tuple

import ucagent.util.functions as fc
from ucagent.util.bug_analysis_contract import STATIC_BUG_SECTION_MARKERS
from ucagent.util.log import info, warning
from ucagent.checkers.base import Checker, UnityChipBatchTask

# ---------------------------------------------------------------------------
# Parse hierarchy constants
# ---------------------------------------------------------------------------

_STATIC_KEYNAMES = ["FG", "FC", "CK", "BG-STATIC", "LINK-BUG", "FILE"]
_STATIC_PREFIXES = ["<FG-", "<FC-", "<CK-", "<BG-STATIC-", "<LINK-BUG-", "<FILE-"]
_STATIC_SUFFIXES = [">", ">", ">", ">", ">", ">"]

# ---------------------------------------------------------------------------
# Regex patterns for LINK-BUG key values
# ---------------------------------------------------------------------------
#
# parse_nested_keys returns the full extracted key including the tag prefix,
# e.g. for <LINK-BUG-[BG-TBD]> the key stored is "LINK-BUG-[BG-TBD]".
#

# LINK-BUG-[BG-TBD]  — pending
_RE_LINK_TBD = re.compile(r'^LINK-BUG-\[BG-TBD\]$', re.IGNORECASE)
# LINK-BUG-[BG-NA]   — false positive
_RE_LINK_NA = re.compile(r'^LINK-BUG-\[BG-NA\]$', re.IGNORECASE)
# LINK-BUG-[BG-NAME-xx]...— one or more confirmed bracket groups
_RE_LINK_CONFIRMED = re.compile(
    r'^LINK-BUG-(\[BG-[A-Za-z][A-Za-z0-9_-]+-\d{1,3}\])+$', re.IGNORECASE
)
# Extract individual BG-NAME-xx from a confirmed key like
# LINK-BUG-[BG-N1-92][BG-N2-85]
_RE_BRACKET_TAG = re.compile(
    r'\[BG-([A-Za-z][A-Za-z0-9_-]+-\d{1,3})\]', re.IGNORECASE
)

# Key value for <BG-STATIC-NULL>: no bugs found after review
# parse_nested_keys keeps the key-prefix in the extracted value, so the
# dict key for <BG-STATIC-NULL> is "BG-STATIC-NULL" and the path
# segment returned by nested_keys_as_list is exactly this string.
_NULL_SENTINEL_KEY = "BG-STATIC-NULL"

# NULL sentinel path components for FG/FC/CK
_NULL_FG_KEY = "FG-NULL"
_NULL_FC_KEY = "FC-NULL"
_NULL_CK_KEY = "CK-NULL"

# <FILE-filepath:linerange> — source file location evidence for a static bug.
# filepath : any non-empty path string (no whitespace, relative to project root)
# linerange: N-M or comma-separated N-M groups (use N-N for one line)
_RE_FILE_KEY = re.compile(
    r'^(.+):(\d+-\d+(?:,\d+-\d+)*)$'
)


def _check_static_bug_section_markers(path: str) -> List[str]:
    """Validate the canonical language-independent static report sections."""

    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    positions = []
    errors = []
    for marker in STATIC_BUG_SECTION_MARKERS:
        matches = [index + 1 for index, line in enumerate(lines) if line.strip() == marker]
        if len(matches) != 1:
            errors.append(
                f"Static report marker '{marker}' must occur on a standalone line "
                f"exactly once; found {len(matches)} occurrence(s)."
            )
        else:
            positions.append(matches[0])
    if not errors and positions != sorted(positions):
        errors.append(
            "Static report section markers are out of canonical order; expected "
            + " -> ".join(STATIC_BUG_SECTION_MARKERS)
            + "."
        )
    return errors

# Regex for parsing <file>path</file> completion markers written by the LLM
# into the static doc at the end of each batch.  Using a plain regex (not
# an XML parser) because the surrounding markdown contains unclosed
# angle-bracket tags like <FG-*> that would confuse an XML parser.
_RE_FILE_PROGRESS_TAG = re.compile(r'<file>(.*?)</file>', re.DOTALL)

# Index at which the FILE key appears in path segments produced by
# nested_keys_as_list (0-based: FG=0, FC=1, CK=2, BG-STATIC=3, LINK-BUG=4, FILE=5).
# Used to split file_path strings without losing "/" inside a filepath.
_STATIC_FILE_LEVEL = len(_STATIC_KEYNAMES) - 1  # 5


def parse_source_location(location: str) -> dict:
    """Parse a workspace-relative ``path:line-range`` source location."""
    if not isinstance(location, str) or not location.strip():
        raise ValueError("source location must be a non-empty string")
    raw = location.strip()
    match = _RE_FILE_KEY.fullmatch(raw)
    if not match:
        malformed = re.fullmatch(
            r"(?P<path>.+):L?(?P<start>\d+)(?:-L?(?P<end>\d+))?", raw
        )
        if malformed:
            start = malformed.group("start")
            end = malformed.group("end") or start
            replacement = f"{malformed.group('path')}:{start}-{end}"
            raise ValueError(f"replace '{raw}' with '{replacement}'")
        raise ValueError(
            f"'{location}' must use filepath:line1-line2[,line3-line4] format"
        )
    ranges = []
    for line_range in match.group(2).split(","):
        start_text, separator, end_text = line_range.partition("-")
        start = int(start_text)
        end = int(end_text)
        if start < 1 or end < start:
            raise ValueError(f"'{location}' contains an invalid line range '{line_range}'")
        ranges.append({"start": start, "end": end})
    return {"location": raw, "path": match.group(1), "ranges": ranges}


def parse_confirmed_static_bug_links(static_path: str, parsed_data=None) -> List[dict]:
    """Return confirmed static-to-dynamic Bug links and their document ranges.

    ``BG-TBD``, ``BG-NA``, and ``BG-STATIC-NULL`` entries are intentionally
    excluded. Each returned item represents one static Bug, while
    ``dynamic_bug_tags`` preserves every confirmed dynamic Bug linked from it.
    """
    data = parsed_data
    if data is None:
        data = fc.parse_nested_keys(
            static_path,
            _STATIC_KEYNAMES,
            _STATIC_PREFIXES,
            _STATIC_SUFFIXES,
        )
    link_paths, _, _ = fc.nested_keys_as_list(
        data,
        "LINK-BUG",
        _STATIC_KEYNAMES,
    )

    with open(static_path, "r", encoding="utf-8") as static_file:
        lines = static_file.read().splitlines()
    occurrences = []
    for line_number, line in enumerate(lines, start=1):
        match = re.search(r"<(BG-STATIC-[^<>]+)>", line)
        if match:
            occurrences.append((match.group(1), line_number))

    ranges_by_start = {}
    for index, (alias, start) in enumerate(occurrences):
        end = len(lines)
        next_start = occurrences[index + 1][1] if index + 1 < len(occurrences) else None
        for candidate in range(start + 1, (next_start or len(lines) + 1)):
            line = lines[candidate - 1]
            if re.search(r"<(?:FG|FC|CK)-[^<>]+>", line) or re.match(
                r"^\s*#{1,3}\s+", line
            ):
                end = candidate - 1
                break
        else:
            if next_start is not None:
                end = next_start - 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        ranges_by_start[start] = {"start": start, "end": end}

    confirmed_links = []
    for path in link_paths:
        parts = path.split("/")
        if len(parts) < 5:
            continue
        alias = parts[-2]
        link_key = parts[-1]
        if alias == _NULL_SENTINEL_KEY or not _RE_LINK_CONFIRMED.fullmatch(link_key):
            continue
        try:
            alias_node = data[parts[0]]["FC"][parts[1]]["CK"][parts[2]][
                "BG-STATIC"
            ][alias]
            document_range = ranges_by_start[alias_node["line"]]
        except (KeyError, TypeError):
            raise ValueError(
                f"Cannot determine the document range for static Bug '<{alias}>'."
            ) from None
        confirmed_links.append({
            "alias": alias,
            "dynamic_bug_tags": [
                f"BG-{match.group(1)}" for match in _RE_BRACKET_TAG.finditer(link_key)
            ],
            "range": document_range,
        })
    return confirmed_links


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_ck_paths_against_fc_doc(
    data: dict, fc_path: str, fc_doc_name: str
) -> List[str]:
    """Cross-check every ``<CK-*>`` tag path used in the parsed static doc
    *data* against those registered in *fc_path*
    (``{DUT}_functions_and_checks.md``).

    Returns a list of error strings (empty if all checks pass).
    """
    errors: List[str] = []

    ck_klist, _, _ = fc.nested_keys_as_list(data, "CK", _STATIC_KEYNAMES)
    if not ck_klist:
        return errors  # no CK tags in static doc — nothing to cross-check

    try:
        fc_ck_paths = fc.get_unity_chip_doc_marks(fc_path, "CK")
    except (AssertionError, ValueError) as e:
        errors.append(
            f"Failed to parse '{fc_doc_name}' for CK tag cross-reference: {e}. "
            f"Ensure '{fc_doc_name}' has valid tag structure before running this check."
        )
        return errors

    diff_ck_path = []
    related_fc_ck_paths = {k:0 for k in fc_ck_paths}
    for ck_path in ck_klist:
        # Skip NULL sentinel path - FG-NULL/FC-NULL/CK-NULL is a special case
        # that doesn't need to exist in functions_and_checks.md
        if ck_path == f"{_NULL_FG_KEY}/{_NULL_FC_KEY}/{_NULL_CK_KEY}":
            continue
        if ck_path not in fc_ck_paths:
            related_fc_ck_paths[fc.find_most_similar_strings(ck_path, fc_ck_paths)] += 1
            diff_ck_path.append(ck_path)
    if len(diff_ck_path) > 0:
        parts = diff_ck_path[-1].split("/")
        fg_tag = f"<{parts[0]}>" if len(parts) > 0 else "?"
        fc_tag = f"<{parts[1]}>" if len(parts) > 1 else "?"
        ck_tag = f"<{parts[2]}>" if len(parts) > 2 else "?"
        # CK tags are defined in the static bug doc, but not found in the FC doc
        errors.append({f"The following CK tags defined in the static bug doc are not found in {fc_doc_name}": diff_ck_path})
        errors.append(
            f"The CK tag hierarchy in doc is like: {fg_tag} ... {fc_tag} ... {ck_tag}. "
            f"You need first to fix the tag name to match the existing entry, or add the new tag hierarchy to `{fc_doc_name}`."
        )
        # sort related_fc_ck_paths by value
        all_ck_count = len(related_fc_ck_paths)
        max_ck_list = max(10, len(diff_ck_path))
        sorted_fc_ck_paths = sorted(related_fc_ck_paths.items(), key=lambda x: x[1], reverse=True)[:max_ck_list]
        sorted_fc_ck_paths = [k for k, _ in sorted_fc_ck_paths]
        if all_ck_count > max_ck_list:
            sorted_fc_ck_paths.append(f"... {all_ck_count - max_ck_list} more")
        errors.append({f"There are {all_ck_count} existing CK tags in {fc_doc_name}": sorted_fc_ck_paths})
    return errors


def _extract_confirmed_dynamic_tags(bug_analysis_path: str) -> set:
    """Return a set of all dynamic BG tag names (uppercase, without ``<BG-``
    and ``>``) found in *bug_analysis_path*, excluding STATIC, TBD, NA.

    Uses a raw content scan so it works even when the file's tag hierarchy
    is incomplete or has validation errors.
    """
    try:
        with open(bug_analysis_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return set()
    result: set = set()
    for m in re.finditer(
        r'<BG-([A-Za-z][A-Za-z0-9_-]+-\d{1,3})>', content, re.IGNORECASE
    ):
        name = m.group(1).upper()
        if not name.startswith('STATIC-') and name not in ('TBD', 'NA'):
            result.add(name)
    return result


# ---------------------------------------------------------------------------
# Checker 1 – static_bug_analysis stage
# ---------------------------------------------------------------------------

class UnityChipCheckerStaticBugFormat(Checker):
    """Validates ``<BG-STATIC-*>`` tag format and mandatory ``<LINK-BUG-[BG-TBD]>``
    and ``<FILE-*>`` child tags in a static bug analysis document
    (``{DUT}_static_bug_analysis.md``).

    Uses ``parse_nested_keys`` with the six-level hierarchy
    ``FG → FC → CK → BG-STATIC → LINK-BUG → FILE`` to parse the document.

    Checks:

    1. The document is parseable without hierarchy violations (each
       ``<BG-STATIC-*>`` is under a ``<CK-*>`` parent, etc.; one CK can have
       multiple BG-STATIC children).
    2. No duplicate tags at any level.
    3. Every ``<BG-STATIC-*>`` has exactly one ``<LINK-BUG-*>`` child tag.
    4. All ``<LINK-BUG-*>`` values are ``[BG-TBD]`` during the
       ``static_bug_analysis`` stage; they are resolved later.
    5. Every ``<FG-*>``/``<FC-*>``/``<CK-*>`` path used in the static doc
       exists in ``functions_and_checks_doc``.
    6. Every ``<LINK-BUG-*>`` entry has at least one ``<FILE-filepath:lines>``
       child tag, and all ``<FILE-*>`` keys match the expected format
       ``filepath:line1[-line2][,line3[-line4]...]``.
    """

    def __init__(self, static_doc: str, functions_and_checks_doc: str, **kw):
        super().__init__()
        self.static_doc               = static_doc
        self.functions_and_checks_doc = functions_and_checks_doc

    def do_check(self, timeout=0, empty_is_ok=False, **kw) -> Tuple[bool, object]:
        """Validate static bug tag format and mandatory LINK-BUG/FILE child tags."""
        real_path = self.get_path(self.static_doc)
        if not os.path.exists(real_path):
            return False, {
                "error": f"Static bug analysis document '{self.static_doc}' does not exist."
            }

        section_errors = _check_static_bug_section_markers(real_path)

        # ── parse hierarchy ──────────────────────────────────────────────────
        try:
            data = fc.parse_nested_keys(
                real_path, _STATIC_KEYNAMES, _STATIC_PREFIXES, _STATIC_SUFFIXES
            )
        except (AssertionError, ValueError) as e:
            return False, {
                "error": f"Tag hierarchy parse error: {e}",
                "check_list": [
                    "Each <BG-STATIC-*> must be under a <CK-*> tag (one CK can have multiple BG-STATIC children)",
                    "Each <LINK-BUG-*> must be under a <BG-STATIC-*> tag",
                    "Each prefix (<FG-*, <BG-STATIC-*, etc.) must appear at most once per line",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        # ── get all LINK-BUG leaf entries ────────────────────────────────────
        klist, blist, _ = fc.nested_keys_as_list(data, "LINK-BUG", _STATIC_KEYNAMES)

        # <BG-STATIC-NULL> has no LINK-BUG child, so it appears in blist.
        # Separate it from genuinely broken entries.
        null_entries = [item for item in blist if item[1].split("/")[-1] == _NULL_SENTINEL_KEY]
        real_broken  = [item for item in blist if item[1].split("/")[-1] != _NULL_SENTINEL_KEY]

        # ── no BG-STATIC tags at all ──────────────────────────────────────────
        if not klist and not blist:
            if empty_is_ok:
                if section_errors:
                    return False, {
                        "error": section_errors,
                        "check_list": [
                            "Keep the three canonical static report section markers even while a batch is in progress",
                            "Display headings may be localized and are not parsed",
                        ],
                    }
                return True, {"message": "No static bugs recorded."}
            return False, {
                "error": (
                    f"No <BG-STATIC-*> tags found in '{self.static_doc}'. "
                    "Static analysis result must be explicitly recorded. "
                    "If no bugs were found in any file, add <FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL>. "
                    "If bugs were found, add <BG-STATIC-NNN-NAME> tags each with a "
                    "<LINK-BUG-[BG-TBD]> child tag."
                ),
                "check_list": [
                    "No bugs found in any file: add <FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL> "
                    "(no <LINK-BUG-*> child needed)",
                    "Bugs found: use <BG-STATIC-NNN-NAME> tags, each with a <LINK-BUG-[BG-TBD]> child",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        errors: List[str] = list(section_errors)

        # ── CK path cross-reference against functions_and_checks ─────────────
        fc_path = self.get_path(self.functions_and_checks_doc)
        if not os.path.exists(fc_path):
            errors.append(
                f"Functions-and-checks document '{self.functions_and_checks_doc}' not found. "
                f"It must exist and contain all <FG-*>/<FC-*>/<CK-*> tags referenced in "
                f"the static bug doc."
            )
        else:
            errors += _check_ck_paths_against_fc_doc(data, fc_path, self.functions_and_checks_doc)

        # ── NULL sentinel only, no real bugs ──────────────────────────────────
        if null_entries and not klist and not real_broken:
            # Validate that BG-STATIC-NULL is used with FG-NULL/FC-NULL/CK-NULL
            for _, path, _ in null_entries:
                parts = path.split("/")
                if len(parts) >= 4:
                    fg_key = parts[0]
                    fc_key = parts[1]
                    ck_key = parts[2]
                    if fg_key != _NULL_FG_KEY or fc_key != _NULL_FC_KEY or ck_key != _NULL_CK_KEY:
                        errors.append(
                            f"<BG-STATIC-NULL> must be used with <FG-NULL><FC-NULL><CK-NULL>, "
                            f"but found path: <{fg_key}><{fc_key}><{ck_key}><BG-STATIC-NULL>. "
                            f"When no bugs are found in any file, use: "
                            f"<FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL>."
                        )
            if errors:
                return False, {
                    "error": errors,
                    "check_list": [
                        "<BG-STATIC-NULL> must be used with <FG-NULL><FC-NULL><CK-NULL>",
                        "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                    ],
                }
            return True, {
                "message": (
                    f"UnityChipCheckerStaticBugFormat passed: "
                    f"<BG-STATIC-NULL> sentinel confirmed — "
                    f"no static bugs found after review."
                ),
                "static_bug_count": 0,
            }

        # ── NULL sentinel mixed with real bugs ────────────────────────────────
        if null_entries:
            errors.append(
                "<BG-STATIC-NULL> must not coexist with real <BG-STATIC-*> bug entries. "
                "Remove <BG-STATIC-NULL> when actual bugs are documented."
            )

        # ── broken real entries (missing LINK-BUG child) ──────────────────────
        for parent_key, path, _ in real_broken:
            errors.append(
                f"<BG-STATIC-*> entry '{path}' has no <LINK-BUG-*> child tag. "
                f"Add '<LINK-BUG-[BG-TBD]>' as a sub-item directly under each "
                f"<BG-STATIC-*> line."
            )

        # ── all LINK-BUG values must be [BG-TBD] ─────────────────────────────
        for path in klist:
            link_key = path.split("/")[-1]
            if not _RE_LINK_TBD.match(link_key):
                errors.append(
                    f"LINK-BUG '{path}': expected '[BG-TBD]' during "
                    f"static_bug_analysis stage, but found '{link_key}'. "
                    f"All <LINK-BUG-*> tags must be <LINK-BUG-[BG-TBD]> at this "
                    f"stage; resolve them in static_bug_validation."
                )
        # ── FILE tag presence and format ──────────────────────────────────
        # LINK-BUG entries without FILE children appear in file_blist with
        # item[0] == "LINK-BUG"; BG-STATIC-NULL entries have item[0] == "BG-STATIC"
        file_klist, file_blist, _ = fc.nested_keys_as_list(data, "FILE", _STATIC_KEYNAMES)
        for _, path, _ in (item for item in file_blist if item[0] == "LINK-BUG"):
            errors.append(
                f"LINK-BUG '{path}': missing required <FILE-*> child tag. "
                f"Add at least one '<FILE-filepath:line1-line2>' sub-item "
                f"directly under the <LINK-BUG-*> line, specifying the source "
                f"file path and line range where the bug was found."
            )
        for file_path in file_klist:
            # The first _STATIC_FILE_LEVEL segments are FG/FC/CK/BG-STATIC/LINK-BUG
            # keys (none of which contain "/"). The last segment is the FILE key
            # which may itself contain "/" (e.g. "FILE-rtl/DUT.v:13").
            # Using maxsplit=_STATIC_FILE_LEVEL preserves the full filepath.
            parts = file_path.split("/", _STATIC_FILE_LEVEL)
            file_key = parts[_STATIC_FILE_LEVEL] if len(parts) > _STATIC_FILE_LEVEL else file_path.split("/")[-1]
            # strip the "FILE-" prefix to get the user-written filepath:linerange
            file_content = file_key[5:] if file_key.startswith("FILE-") else file_key
            try:
                parsed_location = parse_source_location(file_content)
            except ValueError as error:
                errors.append(
                    f"FILE tag '<{file_key}>' in path '{file_path}': invalid format. "
                    f"{error}. "
                    f"Expected '<FILE-filepath:line1-line2[,line3-line4]>' "
                    f"(e.g. '<FILE-src/dut.v:50-56>')."
                )
            else:
                src_filepath = parsed_location["path"]
                abs_src = self.get_path(src_filepath)
                if not os.path.exists(abs_src):
                    errors.append(
                        f"FILE tag '<{file_key}>' in path '{file_path}': "
                        f"source file '{src_filepath}' does not exist in the workspace. "
                        f"Use a path relative to the workspace root "
                        f"(e.g. 'rtl/dut.v:50-56' not '/abs/path/dut.v:50-56')."
                    )
        if errors:
            return False, {
                "error": errors,
                "check_list": [
                    "Each <BG-STATIC-*> must have exactly one <LINK-BUG-[BG-TBD]> child tag",
                    "Each <LINK-BUG-*> must have at least one <FILE-filepath:line1-line2> child tag",
                    "Multiple <BG-STATIC-*> tags can be placed under the same <CK-*> tag "
                    "(one per discovered bug)",
                    "FILE format: <FILE-path/to/file.v:50-56> or <FILE-path/to/file.v:50-56,100-120>",
                    "LINK-BUG format: <LINK-BUG-[BG-TBD]> (pending), placed on its own line",
                    "<BG-STATIC-NULL> declares no bugs found in any file and must be used with "
                    "<FG-NULL><FC-NULL><CK-NULL>; it must not coexist with real bug entries",
                    f"All <CK-*> tags in the static doc must exist in "
                    f"'{self.functions_and_checks_doc}'",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        return True, {
            "message": (
                f"UnityChipCheckerStaticBugFormat passed: "
                f"{len(klist)} <BG-STATIC-*> tag(s) verified with correct "
                f"<LINK-BUG-[BG-TBD]> associations and valid CK tag hierarchy."
            ),
            "static_bug_count": len(klist),
        }


# ---------------------------------------------------------------------------
# Checker 2 – static_bug_validation stage
# ---------------------------------------------------------------------------

class UnityChipCheckerStaticBugValidation(Checker):
    """Validates that all ``<LINK-BUG-[BG-TBD]>`` placeholders have been
    resolved and that confirmed dynamic-bug references exist in the dynamic
    analysis document.

    Uses ``parse_nested_keys`` with the six-level hierarchy
    ``FG → FC → CK → BG-STATIC → LINK-BUG → FILE`` to parse both documents.

    Checks:

    1. No ``<LINK-BUG-[BG-TBD]>`` tag remains in the static doc.
    2. Every ``<LINK-BUG-*>`` value is syntactically valid:
       ``[BG-NA]``, ``[BG-NAME-xx]``, or ``[BG-N1-xx][BG-N2-xx]...``.
    3. Each confirmed dynamic-bug tag referenced via ``[BG-NAME-xx]`` bracket
       groups must appear as a ``<BG-NAME-xx>`` tag in *bug_analysis_doc*.
    4. Every ``<FG-*>``/``<FC-*>``/``<CK-*>`` path used in the static doc
       exists in ``functions_and_checks_doc``.
    5. Every ``<LINK-BUG-*>`` entry has at least one ``<FILE-filepath:lines>``
       child tag, and all ``<FILE-*>`` keys match the expected format.
    """

    def __init__(self, static_doc: str, bug_analysis_doc: str,
                 functions_and_checks_doc: str, **kw):
        super().__init__()
        self.static_doc               = static_doc
        self.bug_analysis_doc         = bug_analysis_doc
        self.functions_and_checks_doc = functions_and_checks_doc

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Validate static bug analysis: resolve placeholders and cross-reference dynamic bugs."""
        static_path = self.get_path(self.static_doc)
        if not os.path.exists(static_path):
            return False, {
                "error": f"Static bug analysis document '{self.static_doc}' does not exist."
            }

        section_errors = _check_static_bug_section_markers(static_path)

        # ── parse hierarchy ──────────────────────────────────────────────────
        try:
            data = fc.parse_nested_keys(
                static_path, _STATIC_KEYNAMES, _STATIC_PREFIXES, _STATIC_SUFFIXES
            )
        except (AssertionError, ValueError) as e:
            return False, {
                "error": f"Tag hierarchy parse error: {e}",
                "check_list": [
                    "Each <BG-STATIC-*> must be under a <CK-*> tag (one CK can have multiple BG-STATIC children)",
                    "Each <LINK-BUG-*> must be under a <BG-STATIC-*> tag",
                    "Each prefix must appear at most once per line",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        klist, blist, _ = fc.nested_keys_as_list(data, "LINK-BUG", _STATIC_KEYNAMES)

        null_entries = [item for item in blist if item[1].split("/")[-1] == _NULL_SENTINEL_KEY]
        real_broken  = [item for item in blist if item[1].split("/")[-1] != _NULL_SENTINEL_KEY]

        errors: List[str] = list(section_errors)
        confirmed_refs = [
            (tag[3:].upper(), 0)
            for link in parse_confirmed_static_bug_links(static_path, data)
            for tag in link["dynamic_bug_tags"]
        ]

        # ── CK path cross-reference against functions_and_checks ─────────────
        fc_path = self.get_path(self.functions_and_checks_doc)
        if not os.path.exists(fc_path):
            errors.append(
                f"Functions-and-checks document '{self.functions_and_checks_doc}' not found."
            )
        else:
            errors += _check_ck_paths_against_fc_doc(data, fc_path, self.functions_and_checks_doc)

        # ── NULL sentinel only — nothing further to validate ─────────────────
        if null_entries and not klist and not real_broken:
            # Validate that BG-STATIC-NULL is used with FG-NULL/FC-NULL/CK-NULL
            for _, path, _ in null_entries:
                parts = path.split("/")
                if len(parts) >= 4:
                    fg_key = parts[0]
                    fc_key = parts[1]
                    ck_key = parts[2]
                    if fg_key != _NULL_FG_KEY or fc_key != _NULL_FC_KEY or ck_key != _NULL_CK_KEY:
                        errors.append(
                            f"<BG-STATIC-NULL> must be used with <FG-NULL><FC-NULL><CK-NULL>, "
                            f"but found path: <{fg_key}><{fc_key}><{ck_key}><BG-STATIC-NULL>."
                        )
            if errors:
                return False, {
                    "error": errors,
                    "check_list": [
                        "<BG-STATIC-NULL> must be used with <FG-NULL><FC-NULL><CK-NULL>",
                    ],
                }
            return True, {
                "message": (
                    f"UnityChipCheckerStaticBugValidation passed: "
                    f"<BG-STATIC-NULL> sentinel confirmed — no static bugs to validate."
                ),
                "confirmed_count": 0,
            }

        # ── NULL sentinel mixed with real bugs ────────────────────────────────
        if null_entries:
            errors.append(
                "<BG-STATIC-NULL> must not coexist with real <BG-STATIC-*> bug entries."
            )

        # ── broken real entries (BG-STATIC without LINK-BUG) ─────────────────
        for parent_key, path, _ in real_broken:
            errors.append(
                f"<BG-STATIC-*> entry '{path}' has no <LINK-BUG-*> child tag."
            )

        for path in klist:
            link_key = path.split("/")[-1]

            # ── check 1: no [BG-TBD] remaining ──────────────────────────────
            if _RE_LINK_TBD.match(link_key):
                errors.append(
                    f"LINK-BUG '{path}' still has [BG-TBD] value. "
                    f"Replace <LINK-BUG-[BG-TBD]> with the actual dynamic bug tag "
                    f"(e.g. <LINK-BUG-[BG-FSM-DEAD-92]>) or <LINK-BUG-[BG-NA]> "
                    f"for false positives."
                )
                continue

            # ── check 2: valid resolved format ───────────────────────────────
            if _RE_LINK_NA.match(link_key):
                continue  # false positive — always valid

            if not _RE_LINK_CONFIRMED.match(link_key):
                errors.append(
                    f"LINK-BUG '{path}': invalid value '{link_key}'. "
                    f"Expected '[BG-NA]', a single tag like '[BG-NAME-xx]', "
                    f"or multiple tags like '[BG-N1-xx][BG-N2-xx]'."
                )
                continue

        # ── FILE tag presence and format ──────────────────────────────────
        file_klist, file_blist, _ = fc.nested_keys_as_list(data, "FILE", _STATIC_KEYNAMES)
        for _, path, _ in (item for item in file_blist if item[0] == "LINK-BUG"):
            errors.append(
                f"LINK-BUG '{path}': missing required <FILE-*> child tag. "
                f"Each <LINK-BUG-*> must have at least one '<FILE-filepath:line1-line2>' "
                f"sub-item specifying where the bug was found in the source."
            )
        for file_path in file_klist:
            parts = file_path.split("/", _STATIC_FILE_LEVEL)
            file_key = parts[_STATIC_FILE_LEVEL] if len(parts) > _STATIC_FILE_LEVEL else file_path.split("/")[-1]
            file_content = file_key[5:] if file_key.startswith("FILE-") else file_key
            try:
                parsed_location = parse_source_location(file_content)
            except ValueError as error:
                errors.append(
                    f"FILE tag '<{file_key}>' in path '{file_path}': invalid format. "
                    f"{error}. "
                    f"Expected '<FILE-filepath:line1-line2[,line3-line4]>'."
                )
            else:
                src_filepath = parsed_location["path"]
                abs_src = self.get_path(src_filepath)
                if not os.path.exists(abs_src):
                    errors.append(
                        f"FILE tag '<{file_key}>' in path '{file_path}': "
                        f"source file '{src_filepath}' does not exist in the workspace. "
                        f"Use a path relative to the workspace root "
                        f"(e.g. 'rtl/dut.v:50-56' not '/abs/path/dut.v:50-56')."
                    )
        # ── check 3: cross-reference confirmed tags against bug_analysis_doc ─
        unique_confirmed = {tag_name for tag_name, _ in confirmed_refs}
        if unique_confirmed:
            bug_path = self.get_path(self.bug_analysis_doc)
            if not os.path.exists(bug_path):
                errors.append(
                    f"Bug analysis document '{self.bug_analysis_doc}' not found. "
                    f"Confirmed static bugs require a corresponding entry in this file."
                )
            else:
                known = _extract_confirmed_dynamic_tags(bug_path)
                for tag_name in unique_confirmed:
                    if tag_name not in known:
                        errors.append(
                            f"Confirmed dynamic bug tag '<BG-{tag_name}>' not found in "
                            f"'{self.bug_analysis_doc}'. "
                            f"Add the complete record "
                            f"(<FG-*>/<FC-*>/<CK-*>/<BG-{tag_name}>/<TC-*>) to that "
                            f"document before completing this stage."
                        )

        if errors:
            return False, {
                "error": errors,
                "check_list": [
                    "Replace all <LINK-BUG-[BG-TBD]> with <LINK-BUG-[BG-NA]> (false positive) "
                    "or <LINK-BUG-[BG-NAME-xx]> (confirmed)",
                    "Multiple confirmed bugs: use <LINK-BUG-[BG-N1-xx][BG-N2-xx]> format",
                    "Multiple <BG-STATIC-*> tags can be placed under the same <CK-*> tag "
                    "(one per discovered bug)",
                    "Each <LINK-BUG-*> must have at least one <FILE-filepath:line1-line2> child tag",
                    f"Each confirmed tag must have a full <BG-*>+<TC-*> record in "
                    f"'{self.bug_analysis_doc}'",
                    "See the 'Dynamic Bug Link Tag Specification' section in Guide_Doc/dut_bug_analysis.md",
                ],
            }

        return True, {
            "message": (
                f"UnityChipCheckerStaticBugValidation passed: "
                f"no <LINK-BUG-[BG-TBD]> remaining, "
                f"{len(unique_confirmed)} confirmed tag reference(s) verified."
            ),
            "confirmed_count": len(unique_confirmed),
        }


# ---------------------------------------------------------------------------
# Checker 3 – batch static_bug_analysis stage
# ---------------------------------------------------------------------------

class UnityChipBatchCheckerStaticBug(Checker):
    """Batch RTL static bug analysis checker.

    Drives the LLM to analyze RTL source files in batches of *batch_size*.
    After each batch the LLM must update (or create) a progress-table section
    at the end of ``static_doc``::

        ## Batch Analysis Progress

        | Source file | Potential bugs | Status |
        |-------------|---------------|--------|
        | <file>path/to/file.v</file> | N | ✅ Done |

    On the next invocation the checker parses every ``<file>…</file>`` tag
    in ``static_doc`` to determine which files have been analyzed and which
    remain.  This makes the checker fully stateless — it derives all
    progress information from the document itself.

    When all files have been analyzed the checker delegates final format
    validation to :class:`UnityChipCheckerStaticBugFormat`.

    Template variables provided via :meth:`get_template_data`:

    ``ANALYSIS_PROGRESS``
        Progress string ``"done/total"`` (e.g. ``"3/7"``).
    ``TOTAL_FILES``
        Total number of source files to analyze.
    ``ANALYZED_FILES``
        Number of files that have already been analyzed.
    ``CURRENT_FILE_NAMES``
        Comma-separated list of files in the current batch.
    """

    def __init__(self, static_doc: str, functions_and_checks_doc: str,
                 file_list, batch_size: int = 1, **kw):
        super().__init__()
        self.static_doc = static_doc
        self.functions_and_checks_doc = functions_and_checks_doc
        self.file_list = file_list if isinstance(file_list, list) else [file_list]
        self.batch_size = batch_size
        self.batch_task = UnityChipBatchTask("RTL_file_to_analyze", self)
        self.fmt_checker = UnityChipCheckerStaticBugFormat(self.static_doc, self.functions_and_checks_doc)

    def set_workspace(self, workspace: str):
        super().set_workspace(workspace)
        self.fmt_checker.set_workspace(workspace)
        return self

    # ── internal helpers ─────────────────────────────────────────────────────

    def _get_all_source_files(self) -> List[str]:
        """Expand glob/regex patterns → sorted workspace-relative file list."""
        found: List[str] = []
        for pattern in self.file_list:
            found.extend(fc.find_files_by_pattern(self.workspace, pattern))
        return sorted(set(found))

    def _get_analyzed_files(self) -> List[str]:
        """Parse ``<file>…</file>`` completion markers from *static_doc*.

        Uses a plain regex instead of an XML parser because the surrounding
        markdown content contains unclosed angle-bracket tags (``<FG-*>`` etc.)
        that would break XML parsing.
        """
        doc_path = self.get_path(self.static_doc)
        if not os.path.exists(doc_path):
            return []
        try:
            with open(doc_path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            return [m.group(1).strip() for m in _RE_FILE_PROGRESS_TAG.finditer(content)]
        except Exception as e:
            info(
                f"UnityChipBatchCheckerStaticBug: failed to read <file> tags "
                f"from '{self.static_doc}': {e}"
            )
            return []

    def _init_batch_state(self) -> bool:
        """Refresh source/gen lists from the filesystem and *static_doc*.

        Called by :meth:`on_init` to populate lists before the framework
        renders stage descriptions, and NOT from :meth:`do_check` — the
        ``do_check`` path uses ``sync_source_task`` / ``sync_gen_task``
        + ``do_complete`` for proper lifecycle management.

        Returns ``False`` when no source files match the configured patterns.
        """
        all_files = self._get_all_source_files()
        if not all_files:
            return False

        analyzed = self._get_analyzed_files()
        source = sorted(all_files)
        gen = [f for f in analyzed if f in source]

        self.batch_task.source_task_list = source
        self.batch_task.gen_task_list = gen
        # Retain only still-valid tbd items loaded from checkpoint
        # (drop items already analyzed or no longer in source).
        self.batch_task.tbd_task_list = [
            f for f in self.batch_task.tbd_task_list
            if f in source and f not in gen
        ]
        self.batch_task.cmp_task_list = []
        self.batch_task.update_current_tbd()

        info(
            f"UnityChipBatchCheckerStaticBug: {len(gen)}/{len(source)} files "
            f"analyzed; current batch: {self.batch_task.tbd_task_list}"
        )
        return True

    def _handle_no_source_files(self) -> Tuple[bool, object]:
        """Handle the case where no RTL source files match the patterns.

        In black-box verification scenarios the DUT has no accessible source
        code.  If the LLM has already documented this situation in
        *static_doc* (non-empty content), the check passes with a warning.
        Otherwise it fails and instructs the LLM to write an explanation.
        """
        doc_path = self.get_path(self.static_doc)
        content = ""
        if os.path.exists(doc_path):
            try:
                with open(doc_path, 'r', encoding='utf-8') as fh:
                    content = fh.read().strip()
            except Exception:
                content = ""

        if content:
            section_errors = _check_static_bug_section_markers(doc_path)
            if section_errors:
                return False, {
                    "error": section_errors,
                    "task": [
                        "Use the canonical tagged static report structure even in black-box mode.",
                        "Keep the explanation between <STATIC-BUG-DETAILS> and <STATIC-BUG-PROGRESS>.",
                    ],
                }
            warning(
                f"UnityChipBatchCheckerStaticBug: No source files found "
                f"matching {self.file_list}. Black-box verification mode — "
                f"static bug analysis skipped."
            )
            return True, {
                "message": (
                    "No RTL source files found (black-box verification). "
                    "Static bug analysis is not applicable. "
                    f"Explanation documented in '{self.static_doc}'."
                ),
            }

        return False, {
            "error": (
                f"No source files found matching patterns: {self.file_list}. "
                "This appears to be a black-box verification scenario. "
                f"Document this in '{self.static_doc}' — explain that static "
                "bug analysis is not applicable because no RTL source files "
                "are available."
            ),
            "task": [
                f"No RTL source files were found matching: {self.file_list}",
                "This is likely a black-box verification scenario.",
                f"Create or update '{self.static_doc}' to explain that:",
                "  - Static bug analysis cannot be performed because no RTL source files are accessible",
                "  - The verification is running in black-box mode",
                "  - Any other relevant context about the verification approach",
                f"The document '{self.static_doc}' must not be empty.",
            ],
        }

    # ── Checker interface ─────────────────────────────────────────────────────

    def on_init(self):
        """Populate batch state from the static doc so that get_template_data()
        returns correct values when called by the framework before do_check()."""
        self._init_batch_state()
        return super().on_init()

    def get_template_data(self) -> dict:
        source = self.batch_task.source_task_list
        gen = self.batch_task.gen_task_list
        total: object = len(source) if source else "-"
        done: object = len(gen) if source else "-"
        return {
            "TOTAL_FILES": total,
            "ANALYZED_FILES": done,
            "ANALYSIS_PROGRESS": f"{done}/{total}",
            "CURRENT_FILE_NAMES": ", ".join(self.batch_task.tbd_task_list),
        }

    def do_check(self, is_complete: bool = False, **kw) -> Tuple[bool, object]:
        """Drive batch static bug analysis."""
        all_files = self._get_all_source_files()
        if not all_files:
            return self._handle_no_source_files()

        analyzed = self._get_analyzed_files()
        gen = [f for f in analyzed if f in all_files]

        note_msg: List[str] = []
        self.batch_task.sync_source_task(
            sorted(all_files), note_msg, "Source file list changed."
        )
        self.batch_task.sync_gen_task(
            gen, note_msg, "Analyzed files updated from document."
        )
        passed, result = self.batch_task.do_complete(
            note_msg, is_complete,
            f"in source file patterns {self.file_list}",
            f"in {self.static_doc} <file> progress tags",
            " Please use tool `CurrentFileTips` to get detailed task description.",
        )
        # Add current_batch to result for LLM prompts
        current_batch = list(self.batch_task.tbd_task_list)
        progress = f"{len(gen)}/{len(all_files)}"
        remaining_files = len(all_files) - len(gen)
        if isinstance(result, dict):
            result["current_batch"] = current_batch
            result["progress"] = progress
            result["remaining_files"] = remaining_files
            result["analyzed_files"] = len(gen)
            result["analysis_progress"] = progress
            result["task"] = current_batch
        kw["empty_is_ok"] = not passed
        fmt_passed, fmt_result = self.fmt_checker.do_check(**kw)
        if not fmt_passed:
            # Add batch info to fmt_result even on failure
            if isinstance(fmt_result, dict):
                fmt_result["current_batch"] = current_batch
                fmt_result["progress"] = progress
                fmt_result["remaining_files"] = remaining_files
                fmt_result["task"] = current_batch
            return fmt_passed, fmt_result
        return passed, result
