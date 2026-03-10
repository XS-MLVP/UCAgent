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
        <CK-*>  <BG-STATIC-*>
          <LINK-BUG-[BG-TBD]>                    ← pending
            <FILE-filepath:line1-line2>           ← source location (required)
          <LINK-BUG-[BG-NA]>                      ← false positive
            <FILE-filepath:line1-line2>           ← source location (required)
          <LINK-BUG-[BG-NAME-xx]>                 ← single confirmed
            <FILE-filepath:line1-line2>           ← source location (required)
          <LINK-BUG-[BG-N1-xx][BG-N2-xx]>         ← multiple confirmed
            <FILE-filepath:line1-line2>           ← source location (required)
"""

import re
import os
from typing import List, Tuple

import ucagent.util.functions as fc
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

# Key value for <BG-STATIC-000-NULL>: no bugs found after review
# parse_nested_keys keeps the key-prefix in the extracted value, so the
# dict key for <BG-STATIC-000-NULL> is "BG-STATIC-000-NULL" and the path
# segment returned by nested_keys_as_list is exactly this string.
_NULL_SENTINEL_KEY = "BG-STATIC-000-NULL"

# <FILE-filepath:linerange> — source file location evidence for a static bug.
# filepath : any non-empty path string (no whitespace, relative to project root)
# linerange: N, N-M, or comma-separated N-M groups (e.g. 50-56,100-120)
_RE_FILE_KEY = re.compile(
    r'^(.+):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)$'
)

# Regex for parsing <file>path</file> completion markers written by the LLM
# into the static doc at the end of each batch.  Using a plain regex (not
# an XML parser) because the surrounding markdown contains unclosed
# angle-bracket tags like <FG-*> that would confuse an XML parser.
_RE_FILE_PROGRESS_TAG = re.compile(r'<file>(.*?)</file>', re.DOTALL)

# Index at which the FILE key appears in path segments produced by
# nested_keys_as_list (0-based: FG=0, FC=1, CK=2, BG-STATIC=3, LINK-BUG=4, FILE=5).
# Used to split file_path strings without losing "/" inside a filepath.
_STATIC_FILE_LEVEL = len(_STATIC_KEYNAMES) - 1  # 5


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

    ck_klist, _ = fc.nested_keys_as_list(data, "CK", _STATIC_KEYNAMES)
    if not ck_klist:
        return errors  # no CK tags in static doc — nothing to cross-check

    try:
        fc_ck_paths: set = set(fc.get_unity_chip_doc_marks(fc_path, "CK"))
    except (AssertionError, ValueError) as e:
        errors.append(
            f"Failed to parse '{fc_doc_name}' for CK tag cross-reference: {e}. "
            f"Ensure '{fc_doc_name}' has valid tag structure before running this check."
        )
        return errors

    for ck_path in ck_klist:
        if ck_path not in fc_ck_paths:
            parts = ck_path.split("/")
            fg_tag = f"<FG-{parts[0]}>" if len(parts) > 0 else "?"
            fc_tag = f"<FC-{parts[1]}>" if len(parts) > 1 else "?"
            ck_tag = f"<CK-{parts[2]}>" if len(parts) > 2 else "?"
            errors.append(
                f"Tag '{ck_tag}' (path: {fg_tag}/{fc_tag}/{ck_tag}) used in the static "
                f"bug doc is not found in '{fc_doc_name}'. "
                f"Add this tag hierarchy to '{fc_doc_name}' first, or fix the tag name "
                f"in the static bug doc to match an existing entry."
            )
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
       ``<BG-STATIC-*>`` is preceded by a ``<CK-*>`` parent, etc.).
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
        self.static_doc               = static_doc
        self.functions_and_checks_doc = functions_and_checks_doc

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Validate static bug tag format and mandatory LINK-BUG/FILE child tags."""
        real_path = self.get_path(self.static_doc)
        if not os.path.exists(real_path):
            return False, {
                "error": f"Static bug analysis document '{self.static_doc}' does not exist."
            }

        # ── parse hierarchy ──────────────────────────────────────────────────
        try:
            data = fc.parse_nested_keys(
                real_path, _STATIC_KEYNAMES, _STATIC_PREFIXES, _STATIC_SUFFIXES
            )
        except (AssertionError, ValueError) as e:
            return False, {
                "error": f"Tag hierarchy parse error: {e}",
                "check_list": [
                    "Each <BG-STATIC-*> must be preceded by a <CK-*> tag on a previous line",
                    "Each <LINK-BUG-*> must be preceded by a <BG-STATIC-*> tag",
                    "Each prefix (<FG-*, <BG-STATIC-*, etc.) must appear at most once per line",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        # ── get all LINK-BUG leaf entries ────────────────────────────────────
        klist, blist = fc.nested_keys_as_list(data, "LINK-BUG", _STATIC_KEYNAMES)

        # <BG-STATIC-000-NULL> has no LINK-BUG child, so it appears in blist.
        # Separate it from genuinely broken entries.
        null_entries = [item for item in blist if item[1].split("/")[-1] == _NULL_SENTINEL_KEY]
        real_broken  = [item for item in blist if item[1].split("/")[-1] != _NULL_SENTINEL_KEY]

        # ── no BG-STATIC tags at all ──────────────────────────────────────────
        if not klist and not blist:
            return False, {
                "error": (
                    f"No <BG-STATIC-*> tags found in '{self.static_doc}'. "
                    "Static analysis result must be explicitly recorded. "
                    "If no bugs were found, add <BG-STATIC-000-NULL> under a <CK-*> tag. "
                    "If bugs were found, add <BG-STATIC-NNN-NAME> tags each with a "
                    "<LINK-BUG-[BG-TBD]> child tag."
                ),
                "check_list": [
                    "No bugs found: add <BG-STATIC-000-NULL> under a <CK-*> tag "
                    "(no <LINK-BUG-*> child needed)",
                    "Bugs found: use <BG-STATIC-NNN-NAME> tags, each with a <LINK-BUG-[BG-TBD]> child",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        errors: List[str] = []

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
            if errors:
                return False, {
                    "error": errors,
                    "check_list": [
                        "Ensure all <CK-*> tags used in the static doc exist in "
                       f"'{self.functions_and_checks_doc}'",
                        "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                    ],
                }
            return True, {
                "message": (
                    f"UnityChipCheckerStaticBugFormat passed: "
                    f"<BG-STATIC-000-NULL> sentinel confirmed — "
                    f"no static bugs found after review."
                ),
                "static_bug_count": 0,
            }

        # ── NULL sentinel mixed with real bugs ────────────────────────────────
        if null_entries:
            errors.append(
                "<BG-STATIC-000-NULL> must not coexist with real <BG-STATIC-*> bug entries. "
                "Remove <BG-STATIC-000-NULL> when actual bugs are documented."
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
        # item[0] == "LINK-BUG"; BG-STATIC-000-NULL entries have item[0] == "BG-STATIC"
        file_klist, file_blist = fc.nested_keys_as_list(data, "FILE", _STATIC_KEYNAMES)
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
            m = _RE_FILE_KEY.match(file_content)
            if not m:
                errors.append(
                    f"FILE tag '<{file_key}>' in path '{file_path}': invalid format. "
                    f"Expected '<FILE-filepath:line1-line2[,line3-line4]>' "
                    f"(e.g. '<FILE-src/dut.v:50-56>')."
                )
            else:
                src_filepath = m.group(1)
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
                    "FILE format: <FILE-path/to/file.v:50-56> or <FILE-path/to/file.v:50-56,100-120>",
                    "LINK-BUG format: <LINK-BUG-[BG-TBD]> (pending), placed on its own line",
                    "<BG-STATIC-000-NULL> declares no bugs found and must not coexist with "
                    "real bug entries",
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

        # ── parse hierarchy ──────────────────────────────────────────────────
        try:
            data = fc.parse_nested_keys(
                static_path, _STATIC_KEYNAMES, _STATIC_PREFIXES, _STATIC_SUFFIXES
            )
        except (AssertionError, ValueError) as e:
            return False, {
                "error": f"Tag hierarchy parse error: {e}",
                "check_list": [
                    "Each <LINK-BUG-*> must be preceded by a <BG-STATIC-*> tag",
                    "Each prefix must appear at most once per line",
                    "See Guide_Doc/dut_bug_analysis.md for the full format specification",
                ],
            }

        klist, blist = fc.nested_keys_as_list(data, "LINK-BUG", _STATIC_KEYNAMES)

        null_entries = [item for item in blist if item[1].split("/")[-1] == _NULL_SENTINEL_KEY]
        real_broken  = [item for item in blist if item[1].split("/")[-1] != _NULL_SENTINEL_KEY]

        errors:         List[str]              = []
        confirmed_refs: List[Tuple[str, int]]  = []   # (tag_name_upper, line_no_placeholder)

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
            if errors:
                return False, {
                    "error": errors,
                    "check_list": [
                        f"Ensure all <CK-*> tags in the static doc exist in "
                        f"'{self.functions_and_checks_doc}'",
                    ],
                }
            return True, {
                "message": (
                    f"UnityChipCheckerStaticBugValidation passed: "
                    f"<BG-STATIC-000-NULL> sentinel confirmed — no static bugs to validate."
                ),
                "confirmed_count": 0,
            }

        # ── NULL sentinel mixed with real bugs ────────────────────────────────
        if null_entries:
            errors.append(
                "<BG-STATIC-000-NULL> must not coexist with real <BG-STATIC-*> bug entries."
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

            # ── collect confirmed tag names for cross-reference ──────────────
            for m in _RE_BRACKET_TAG.finditer(link_key):
                confirmed_refs.append((m.group(1).upper(), 0))
        # ── FILE tag presence and format ──────────────────────────────────
        file_klist, file_blist = fc.nested_keys_as_list(data, "FILE", _STATIC_KEYNAMES)
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
            m = _RE_FILE_KEY.match(file_content)
            if not m:
                errors.append(
                    f"FILE tag '<{file_key}>' in path '{file_path}': invalid format. "
                    f"Expected '<FILE-filepath:line1-line2[,line3-line4]>'."
                )
            else:
                src_filepath = m.group(1)
                abs_src = self.get_path(src_filepath)
                if not os.path.exists(abs_src):
                    errors.append(
                        f"FILE tag '<{file_key}>' in path '{file_path}': "
                        f"source file '{src_filepath}' does not exist in the workspace. "
                        f"Use a path relative to the workspace root "
                        f"(e.g. 'rtl/dut.v:50-56' not '/abs/path/dut.v:50-56')."
                    )
        # ── check 3: cross-reference confirmed tags against bug_analysis_doc ─
        if confirmed_refs:
            bug_path = self.get_path(self.bug_analysis_doc)
            if not os.path.exists(bug_path):
                errors.append(
                    f"Bug analysis document '{self.bug_analysis_doc}' not found. "
                    f"Confirmed static bugs require a corresponding entry in this file."
                )
            else:
                known = _extract_confirmed_dynamic_tags(bug_path)
                for tag_name, _ in confirmed_refs:
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
                f"{len(confirmed_refs)} confirmed tag reference(s) verified."
            ),
            "confirmed_count": len(confirmed_refs),
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
        self.static_doc = static_doc
        self.functions_and_checks_doc = functions_and_checks_doc
        self.file_list = file_list if isinstance(file_list, list) else [file_list]
        self.batch_size = batch_size
        self.batch_task = UnityChipBatchTask("source_files", self)

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

        total = len(self.batch_task.source_task_list)
        analyzed_count = len(self.batch_task.gen_task_list)

        passed, result = self.batch_task.do_complete(
            note_msg, is_complete,
            f"in source file patterns {self.file_list}",
            f"in {self.static_doc} <file> progress tags",
            " Refer to the 'task' field for detailed analysis steps.",
        )

        # ── All files analyzed — run format validation ────────────────────────
        if passed:
            fmt_checker = UnityChipCheckerStaticBugFormat(
                self.static_doc, self.functions_and_checks_doc
            )
            fmt_checker.set_workspace(self.workspace)
            fmt_passed, fmt_result = fmt_checker.do_check(**kw)
            if fmt_passed and isinstance(fmt_result, dict):
                fmt_result["analysis_progress"] = f"{analyzed_count}/{total}"
                fmt_result["analyzed_files"] = self.batch_task.gen_task_list
            return fmt_passed, fmt_result

        # ── Files remaining — enrich result with analysis task details ────────
        current_batch = self.batch_task.tbd_task_list
        remaining = total - analyzed_count

        if isinstance(result, dict) and current_batch:
            result["task"] = [
                f"Perform static bug analysis on the following {len(current_batch)} source file(s) "
                f"and record any findings in {self.static_doc}:",
                *[f"  - {f}" for f in current_batch],
                "",
                "Analysis steps:",
                "  1. Read the source file(s) and understand the module structure and data flow.",
                "  2. Cross-reference each <CK-*> check-point in functions_and_checks.md against the RTL implementation.",
                "  3. Systematically check: FSM completeness, arithmetic overflow, reset/clock logic, interface protocols, control paths.",
                "  4. Record each potential bug with a <BG-STATIC-NNN-NAME> tag, add <LINK-BUG-[BG-TBD]> and <FILE-path:lines> child tags.",
                "  5. If no bugs are found for a check-point, add <BG-STATIC-000-NULL> under the corresponding <CK-*>.",
                "  6. For high/medium confidence bugs, add new <CK-*> check-points to functions_and_checks.md.",
                "",
                f"After finishing this batch, update the '## Batch Analysis Progress' section at the end of {self.static_doc}.",
                "If this section does not exist yet, create it at the very end of the document with the table header:",
                "",
                "  ## Batch Analysis Progress",
                "",
                "  | Source file | Potential bugs | Status |",
                "  |-------------|---------------|--------|",
                "",
                "Then append one table row per analyzed file in this batch:",
                "  | <file>path/to/file.v</file> | N | ✅ Done |",
                "",
                "Note: the path inside <file> tags must match the workspace-relative source path exactly.",
            ]
            result["current_batch"] = current_batch
            result["progress"] = f"{analyzed_count}/{total}"
            result["remaining_files"] = remaining

        return passed, result
