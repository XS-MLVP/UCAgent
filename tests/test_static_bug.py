#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprehensive tests for UnityChipCheckerStaticBugFormat and
UnityChipCheckerStaticBugValidation.

Test data lives under tests/test_data/static_bug/.

Directory layout:
  rtl/DUT.v                          — minimal RTL stub (workspace-relative source)
  fc_doc.md                          — valid functions_and_checks doc with FG/FC/CK tags
  empty_doc.md                       — completely empty document
  bug_analysis.md                    — valid dynamic bug analysis doc
  static_null.md                     — single <BG-STATIC-000-NULL> sentinel (no bugs)
  static_ok_one.md                   — one bug, single FILE tag, valid
  static_ok_multi.md                 — three bugs across two FG/FC groups, valid
  static_ok_multifile.md             — one bug with two FILE tags on different lines
  static_no_link_bug.md              — BG-STATIC without LINK-BUG child
  static_no_file_tag.md              — LINK-BUG without FILE child
  static_bad_file_format.md          — FILE tag key missing line range (bad format)
  static_file_not_exist.md           — FILE tag points to non-existent source file
  static_dup_ck.md                   — duplicate CK tag
  static_dup_ck2.md                  — duplicate CK tag (different BG under same CK)
  static_dup_link_bug.md             — duplicate LINK-BUG keys under same BG-STATIC
  static_null_mixed.md               — NULL sentinel coexists with real bug entries
  static_ck_not_in_fc.md             — CK tag not present in fc_doc
  static_still_tbd_format_stage.md   — LINK-BUG already resolved at format-check stage
  static_resolved_confirmed.md       — single confirmed LINK-BUG (for validation tests)
  static_resolved_na.md              — LINK-BUG = [BG-NA] (false positive)
  static_resolved_multi_confirmed.md — LINK-BUG with two confirmed tags
  static_tbd_remaining.md            — LINK-BUG still [BG-TBD] (validation stage fail)
  static_invalid_link_value.md       — LINK-BUG value not [BG-TBD]/[BG-NA]/confirmed
  static_confirmed_tag_missing.md    — confirmed LINK-BUG whose BG tag is absent from bug_analysis.md
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

import pytest
from ucagent.checkers.static_bug import (
    UnityChipCheckerStaticBugFormat,
    UnityChipCheckerStaticBugValidation,
    UnityChipBatchCheckerStaticBug,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(current_dir, "test_data", "static_bug")

# The workspace is the test_data/static_bug directory itself, so all
# workspace-relative paths (e.g. "rtl/DUT.v") resolve inside it.
WORKSPACE = DATA_DIR

FC_DOC       = "fc_doc.md"
BUG_ANALYSIS = "bug_analysis.md"


def fmt_checker(static_doc: str, fc_doc: str = FC_DOC) -> UnityChipCheckerStaticBugFormat:
    return UnityChipCheckerStaticBugFormat(
        static_doc=static_doc,
        functions_and_checks_doc=fc_doc,
    ).set_workspace(WORKSPACE)


def val_checker(
    static_doc: str,
    fc_doc: str = FC_DOC,
    bug_doc: str = BUG_ANALYSIS,
) -> UnityChipCheckerStaticBugValidation:
    return UnityChipCheckerStaticBugValidation(
        static_doc=static_doc,
        bug_analysis_doc=bug_doc,
        functions_and_checks_doc=fc_doc,
    ).set_workspace(WORKSPACE)


# ---------------------------------------------------------------------------
# Shared helpers for assertion
# ---------------------------------------------------------------------------

def assert_pass(result, checker_name=""):
    passed, msg = result
    assert passed is True, (
        f"{checker_name} expected PASS but got FAIL.\n"
        f"Message: {msg}"
    )


def assert_fail(result, *expected_fragments, checker_name=""):
    """Assert the check failed and all expected_fragments appear in error output."""
    passed, msg = result
    assert passed is False, (
        f"{checker_name} expected FAIL but got PASS.\n"
        f"Message: {msg}"
    )
    error_text = str(msg.get("error", ""))
    for fragment in expected_fragments:
        assert fragment in error_text, (
            f"{checker_name}: expected fragment '{fragment}' not found in error:\n{error_text}"
        )


# ===========================================================================
# UnityChipCheckerStaticBugFormat — FORMAT CHECKS
# ===========================================================================


class TestFormatCheckerPassScenarios:

    def test_null_sentinel_only(self):
        """Single <BG-STATIC-000-NULL> under a CK: no bugs, should pass."""
        assert_pass(fmt_checker("static_null.md").do_check(), "null_sentinel")

    def test_null_sentinel_returns_zero_count(self):
        passed, msg = fmt_checker("static_null.md").do_check()
        assert passed is True
        assert msg.get("static_bug_count") == 0

    def test_one_valid_bug(self):
        """One bug with LINK-BUG=[BG-TBD] and a valid FILE tag."""
        res = fmt_checker("static_ok_one.md").do_check()
        assert_pass(res, "one_valid_bug")

    def test_one_valid_bug_count(self):
        passed, msg = fmt_checker("static_ok_one.md").do_check()
        assert passed is True
        assert msg.get("static_bug_count") == 1

    def test_multi_bug_across_groups(self):
        """Three bugs across two FG/FC groups all pass."""
        res = fmt_checker("static_ok_multi.md").do_check()
        assert_pass(res, "multi_bug")
        _, msg = res
        assert msg.get("static_bug_count") == 3

    def test_multiple_file_tags_under_one_link_bug(self):
        """A single LINK-BUG may have several FILE children."""
        assert_pass(fmt_checker("static_ok_multifile.md").do_check(), "multifile")


class TestFormatCheckerMissingDocument:

    def test_static_doc_not_exist(self):
        assert_fail(
            fmt_checker("nonexistent_static.md").do_check(),
            "does not exist",
        )

    def test_fc_doc_not_exist(self):
        assert_fail(
            fmt_checker("static_ok_one.md", fc_doc="no_such_fc.md").do_check(),
            "not found",
        )

    def test_empty_static_doc(self):
        """Empty document has no BG-STATIC tags at all — should fail."""
        assert_fail(
            fmt_checker("empty_doc.md").do_check(),
            "No <BG-STATIC-*> tags found",
        )


class TestFormatCheckerMissingChildren:

    def test_bg_static_without_link_bug(self):
        """<BG-STATIC-*> without a <LINK-BUG-*> child."""
        assert_fail(
            fmt_checker("static_no_link_bug.md").do_check(),
            "has no <LINK-BUG-*> child tag",
        )

    def test_link_bug_without_file_tag(self):
        """<LINK-BUG-*> without any <FILE-*> child."""
        assert_fail(
            fmt_checker("static_no_file_tag.md").do_check(),
            "missing required <FILE-*> child tag",
        )


class TestFormatCheckerFileTag:

    def test_bad_file_format_no_linerange(self):
        """<FILE-rtl/DUT.v> — missing ':linerange' suffix."""
        assert_fail(
            fmt_checker("static_bad_file_format.md").do_check(),
            "invalid format",
        )

    def test_file_not_exist_in_workspace(self):
        """FILE tag pointing to a file that does not exist in the workspace."""
        assert_fail(
            fmt_checker("static_file_not_exist.md").do_check(),
            "does not exist in the workspace",
        )


class TestFormatCheckerDuplicateTags:

    def test_duplicate_ck_tag(self):
        """Two identical <CK-FSM-GUARD> tags under the same FC."""
        assert_fail(
            fmt_checker("static_dup_ck2.md").do_check(),
            # parse_nested_keys raises AssertionError for duplicates
        )
        # Only check it failed — the exact duplicate-key message may vary
        passed, _ = fmt_checker("static_dup_ck2.md").do_check()
        assert passed is False

    def test_duplicate_link_bug_under_same_bg_static(self):
        """Two identical <LINK-BUG-[BG-TBD]> under the same <BG-STATIC-*>."""
        passed, _ = fmt_checker("static_dup_link_bug.md").do_check()
        assert passed is False


class TestFormatCheckerNullSentinelMixed:

    def test_null_mixed_with_real_bug(self):
        """<BG-STATIC-000-NULL> coexisting with a real bug entry — must fail."""
        assert_fail(
            fmt_checker("static_null_mixed.md").do_check(),
            "must not coexist",
        )


class TestFormatCheckerCKCrossReference:

    def test_ck_tag_not_in_fc_doc(self):
        """CK tag path used in static doc does not exist in functions_and_checks."""
        assert_fail(
            fmt_checker("static_ck_not_in_fc.md").do_check(),
            "not found in",
        )


class TestFormatCheckerLinkBugValueAtFormatStage:

    def test_link_bug_already_resolved_at_format_stage(self):
        """LINK-BUG value is already resolved (not [BG-TBD]) during static_bug_analysis stage."""
        assert_fail(
            fmt_checker("static_still_tbd_format_stage.md").do_check(),
            "expected '[BG-TBD]'",
        )


# ===========================================================================
# UnityChipCheckerStaticBugValidation — VALIDATION CHECKS
# ===========================================================================


class TestValidationCheckerPassScenarios:

    def test_null_sentinel_passes_validation(self):
        """NULL sentinel in validation stage — nothing to check, pass."""
        assert_pass(val_checker("static_null.md").do_check(), "val_null")

    def test_null_sentinel_confirmed_count(self):
        passed, msg = val_checker("static_null.md").do_check()
        assert passed is True
        assert msg.get("confirmed_count") == 0

    def test_single_confirmed_bug(self):
        """Single confirmed LINK-BUG with matching entry in bug_analysis.md."""
        assert_pass(
            val_checker("static_resolved_confirmed.md").do_check(),
            "val_single_confirmed",
        )

    def test_single_confirmed_count(self):
        passed, msg = val_checker("static_resolved_confirmed.md").do_check()
        assert passed is True
        assert msg.get("confirmed_count") == 1

    def test_false_positive_na(self):
        """LINK-BUG=[BG-NA] (false positive) — should pass with zero confirmed refs."""
        passed, msg = val_checker("static_resolved_na.md").do_check()
        assert passed is True
        assert msg.get("confirmed_count") == 0

    def test_multi_confirmed_tags(self):
        """LINK-BUG=[BG-GUARD-92][BG-GUARD2-85] with both in bug_analysis.md."""
        passed, msg = val_checker("static_resolved_multi_confirmed.md").do_check()
        assert passed is True
        assert msg.get("confirmed_count") == 2


class TestValidationCheckerMissingDocument:

    def test_static_doc_not_exist(self):
        assert_fail(
            val_checker("nonexistent.md").do_check(),
            "does not exist",
        )

    def test_fc_doc_not_exist(self):
        assert_fail(
            val_checker("static_resolved_confirmed.md", fc_doc="no_fc.md").do_check(),
            "not found",
        )

    def test_bug_analysis_doc_not_exist(self):
        """Confirmed tag but bug_analysis_doc is missing."""
        assert_fail(
            val_checker(
                "static_resolved_confirmed.md",
                bug_doc="no_bug_analysis.md",
            ).do_check(),
            "not found",
        )


class TestValidationCheckerTBDRemaining:

    def test_tbd_still_present(self):
        """[BG-TBD] value remaining in validation stage — must fail."""
        assert_fail(
            val_checker("static_tbd_remaining.md").do_check(),
            "[BG-TBD]",
        )


class TestValidationCheckerInvalidLinkBugValue:

    def test_invalid_link_bug_format(self):
        """LINK-BUG value doesn't match any valid pattern."""
        assert_fail(
            val_checker("static_invalid_link_value.md").do_check(),
            "invalid value",
        )


class TestValidationCheckerConfirmedTagMissing:

    def test_confirmed_tag_absent_from_bug_analysis(self):
        """Confirmed BG tag referenced in LINK-BUG not present in bug_analysis.md."""
        # static_confirmed_tag_missing.md uses [BG-CONFIRMED-92] which IS in
        # bug_analysis.md, so use a static doc that references a nonexistent tag.
        # We reuse static_resolved_confirmed.md but point at an empty bug analysis.
        assert_fail(
            val_checker(
                "static_resolved_confirmed.md",
                bug_doc="empty_doc.md",
            ).do_check(),
            "not found in",
        )


class TestValidationCheckerFileTag:

    def test_link_bug_without_file_tag_validation(self):
        """<LINK-BUG-*> missing FILE child — caught by validation too."""
        assert_fail(
            val_checker("static_no_file_tag.md").do_check(),
            "missing required <FILE-*> child tag",
        )

    def test_file_not_exist_in_workspace_validation(self):
        """FILE tag source file missing — caught by validation too."""
        assert_fail(
            val_checker("static_file_not_exist.md").do_check(),
            "does not exist in the workspace",
        )

    def test_bad_file_format_validation(self):
        assert_fail(
            val_checker("static_bad_file_format.md").do_check(),
            "invalid format",
        )


class TestValidationCheckerCKCrossReference:

    def test_ck_tag_not_in_fc_doc_validation(self):
        assert_fail(
            val_checker("static_ck_not_in_fc.md").do_check(),
            "not found in",
        )


class TestValidationCheckerNullMixed:

    def test_null_mixed_with_real_bug_validation(self):
        assert_fail(
            val_checker("static_null_mixed.md").do_check(),
            "must not coexist",
        )


class TestValidationCheckerMissingLinkBug:

    def test_bg_static_without_link_bug_validation(self):
        assert_fail(
            val_checker("static_no_link_bug.md").do_check(),
            "has no <LINK-BUG-*> child tag",
        )


# ===========================================================================
# Edge / boundary cases
# ===========================================================================


class TestEdgeCases:

    def test_file_tag_multirange(self):
        """FILE tag with comma-separated multi-range (e.g. :11-12) is valid."""
        # static_ok_multi.md uses <FILE-rtl/DUT.v:11-12> — that file exists
        assert_pass(fmt_checker("static_ok_multi.md").do_check(), "multirange")

    def test_file_tag_single_line(self):
        """FILE tag with a single line number (e.g. :13) is valid."""
        # static_ok_one.md uses <FILE-rtl/DUT.v:13>
        assert_pass(fmt_checker("static_ok_one.md").do_check(), "single_line")

    def test_format_and_validation_agree_on_null(self):
        """Both checkers must pass for the NULL sentinel doc."""
        assert_pass(fmt_checker("static_null.md").do_check())
        assert_pass(val_checker("static_null.md").do_check())

    def test_format_passes_validation_fails_on_tbd(self):
        """static_ok_one.md passes format check (LINK-BUG=[BG-TBD] is correct there)
        but fails validation (TBD must be replaced)."""
        assert_pass(fmt_checker("static_ok_one.md").do_check())
        passed, msg = val_checker("static_ok_one.md").do_check()
        assert passed is False
        assert "[BG-TBD]" in str(msg.get("error", ""))

    def test_resolved_na_passes_format_stage(self):
        """Format checker rejects a resolved LINK-BUG; validation accepts [BG-NA]."""
        fmt_passed, _ = fmt_checker("static_resolved_na.md").do_check()
        assert fmt_passed is False  # format stage requires [BG-TBD]
        val_passed, _ = val_checker("static_resolved_na.md").do_check()
        assert val_passed is True

    def test_resolved_confirmed_fails_format_stage(self):
        """Confirmed LINK-BUG is not [BG-TBD], so format stage should fail."""
        fmt_passed, msg = fmt_checker("static_resolved_confirmed.md").do_check()
        assert fmt_passed is False
        assert "expected '[BG-TBD]'" in str(msg.get("error", ""))

    def test_resolved_confirmed_passes_validation_stage(self):
        val_passed, _ = val_checker("static_resolved_confirmed.md").do_check()
        assert val_passed is True


# ---------------------------------------------------------------------------
# UnityChipBatchCheckerStaticBug tests
# ---------------------------------------------------------------------------

def batch_checker(
    static_doc: str,
    file_list=None,
    fc_doc: str = FC_DOC,
    batch_size: int = 1,
) -> UnityChipBatchCheckerStaticBug:
    if file_list is None:
        file_list = ["rtl/*.v"]
    return UnityChipBatchCheckerStaticBug(
        static_doc=static_doc,
        functions_and_checks_doc=fc_doc,
        file_list=file_list,
        batch_size=batch_size,
    ).set_workspace(WORKSPACE)


class TestBatchCheckerNoSourceFiles:
    """Behaviour when no source files match the patterns."""

    def test_no_files_found_returns_false(self):
        c = batch_checker("batch_progress_none.md", file_list=["rtl/*.xyz"])
        passed, msg = c.do_check()
        assert passed is False
        assert "No source files found" in str(msg.get("error", ""))

    def test_empty_file_list_returns_false(self):
        c = batch_checker("batch_progress_none.md", file_list=[])
        passed, msg = c.do_check()
        assert passed is False
        assert "No source files found" in str(msg.get("error", ""))


class TestBatchCheckerProgressTracking:
    """File-progress tracking via <file> tags in static_doc."""

    def test_no_analyzed_files_returns_current_batch(self):
        """Static doc with no <file> tags → first batch is requested."""
        c = batch_checker("batch_progress_none.md")
        passed, msg = c.do_check()
        assert passed is False
        batch = msg.get("current_batch", [])
        assert len(batch) == 1         # batch_size=1
        assert "rtl/DUT.v" in batch or "rtl/DUT2.v" in batch

    def test_static_doc_not_exist_starts_first_batch(self):
        """Missing static doc behaves like zero progress."""
        c = batch_checker("nonexistent_static_doc.md")
        passed, msg = c.do_check()
        assert passed is False
        assert "current_batch" in msg

    def test_one_of_two_files_analyzed(self):
        """Doc with one <file> tag → second file becomes current batch."""
        c = batch_checker("batch_progress_one.md", file_list=["rtl/*.v"])
        passed, msg = c.do_check()
        assert passed is False
        batch = msg.get("current_batch", [])
        assert len(batch) == 1
        assert "rtl/DUT.v" not in batch   # already done
        assert "rtl/DUT2.v" in batch

    def test_progress_field_is_correct(self):
        """progress key reflects analyzed/total ratio."""
        c = batch_checker("batch_progress_one.md", file_list=["rtl/*.v"])
        passed, msg = c.do_check()
        assert passed is False
        assert msg.get("progress") == "1/2"

    def test_remaining_files_field(self):
        c = batch_checker("batch_progress_one.md", file_list=["rtl/*.v"])
        _, msg = c.do_check()
        assert msg.get("remaining_files") == 1

    def test_unknown_file_in_tag_not_counted(self):
        """A <file> tag whose path is not in the source list is ignored."""
        c = batch_checker("batch_progress_wrong_path.md", file_list=["rtl/*.v"])
        passed, msg = c.do_check()
        assert passed is False
        # Both DUT.v and DUT2.v are still pending
        assert msg.get("progress", "").startswith("0/")


class TestBatchCheckerBatchSize:
    """batch_size parameter controls how many files per batch."""

    def test_batch_size_two_returns_two_files(self):
        c = batch_checker(
            "batch_progress_none.md",
            file_list=["rtl/*.v"],
            batch_size=2,
        )
        passed, msg = c.do_check()
        assert passed is False
        batch = msg.get("current_batch", [])
        assert len(batch) == 2

    def test_batch_size_larger_than_total(self):
        """batch_size > total files → all files in first batch."""
        c = batch_checker(
            "batch_progress_none.md",
            file_list=["rtl/*.v"],
            batch_size=100,
        )
        passed, msg = c.do_check()
        assert passed is False
        batch = msg.get("current_batch", [])
        assert len(batch) == 2   # only 2 files exist


class TestBatchCheckerCompletion:
    """Behaviour when all files have been analyzed."""

    def test_all_files_done_valid_doc_passes(self):
        """All <file> tags present and doc passes format check → True."""
        c = batch_checker("batch_progress_all_valid.md", file_list=["rtl/*.v"])
        passed, msg = c.do_check()
        assert passed is True
        assert "analyzed_files" in msg
        assert msg.get("analysis_progress") == "2/2"

    def test_all_files_done_bad_format_fails(self):
        """All <file> tags present but doc fails UnityChipCheckerStaticBugFormat."""
        c = batch_checker("batch_progress_all_bad_format.md", file_list=["rtl/*.v"])
        passed, msg = c.do_check()
        assert passed is False
        # The format checker's error should mention missing LINK-BUG
        assert "error" in msg


class TestBatchCheckerTemplateData:
    """get_template_data returns correct progress variables."""

    def _get_data(self, static_doc, file_list=None, batch_size=1):
        c = batch_checker(static_doc, file_list=file_list or ["rtl/*.v"],
                          batch_size=batch_size)
        c.do_check()
        return c.get_template_data()

    def test_template_progress_none(self):
        data = self._get_data("batch_progress_none.md")
        assert data["TOTAL_FILES"] == 2
        assert data["ANALYZED_FILES"] == 0
        assert data["ANALYSIS_PROGRESS"] == "0/2"
        assert data["CURRENT_FILE_NAMES"] != ""

    def test_template_progress_one(self):
        data = self._get_data("batch_progress_one.md")
        assert data["ANALYZED_FILES"] == 1
        assert data["ANALYSIS_PROGRESS"] == "1/2"

    def test_template_progress_all(self):
        data = self._get_data("batch_progress_all_valid.md")
        assert data["ANALYZED_FILES"] == 2
        assert data["ANALYSIS_PROGRESS"] == "2/2"
        assert data["CURRENT_FILE_NAMES"] == ""  # nothing pending

    def test_template_no_files(self):
        data = self._get_data("batch_progress_none.md", file_list=["rtl/*.xyz"])
        assert data["TOTAL_FILES"] == "-"
        assert data["ANALYZED_FILES"] == "-"


class TestBatchCheckerStateless:
    """Checker re-reads state from document on every invocation."""

    def test_repeated_calls_reflect_updated_doc(self):
        """First call with no progress → pending; second call with one <file> tag → fewer pending."""
        c1 = batch_checker("batch_progress_none.md", file_list=["rtl/*.v"])
        p1, m1 = c1.do_check()
        assert p1 is False
        # Remaining before
        remaining_before = m1.get("remaining_files")

        c2 = batch_checker("batch_progress_one.md", file_list=["rtl/*.v"])
        p2, m2 = c2.do_check()
        assert p2 is False
        remaining_after = m2.get("remaining_files")

        assert remaining_after < remaining_before

    def test_task_field_contains_file_names(self):
        """The 'task' list in the error payload mentions the target files."""
        c = batch_checker("batch_progress_none.md", file_list=["rtl/DUT.v"])
        _, msg = c.do_check()
        task_str = " ".join(msg.get("task", []))
        assert "rtl/DUT.v" in task_str
