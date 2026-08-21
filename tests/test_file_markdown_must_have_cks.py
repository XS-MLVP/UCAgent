#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the MustHaveCKs markdown checker."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers.file_markdown import MustHaveCKs


def write_doc(path, labels):
    body = []
    seen_fg = set()
    seen_fc = set()
    for fg, fc, ck in labels:
        if fg not in seen_fg:
            body.extend([f"<FG-{fg}>", ""])
            seen_fg.add(fg)
        fc_key = (fg, fc)
        if fc_key not in seen_fc:
            body.extend([f"<FC-{fc}>", ""])
            seen_fc.add(fc_key)
        body.extend([f"<CK-{ck}>", ""])
    path.write_text("\n".join(body), encoding="utf-8")


def test_must_have_cks_passes_when_source_contains_all_required_cks(tmp_path):
    write_doc(
        tmp_path / "functions_and_checks.md",
        [
            ("API", "BASIC", "RESET"),
            ("API", "BASIC", "READY"),
        ],
    )
    write_doc(
        tmp_path / "source.md",
        [
            ("API", "BASIC", "RESET"),
            ("API", "BASIC", "READY"),
        ],
    )

    checker = MustHaveCKs(
        source_files="source.md",
        funcs_and_checks_doc="functions_and_checks.md",
    ).set_workspace(str(tmp_path))

    passed, msg = checker.do_check()

    assert passed is True
    assert "All source files contain only CK labels" in msg["note"]


def test_must_have_cks_fails_when_source_contains_ck_missing_from_doc(tmp_path):
    write_doc(
        tmp_path / "functions_and_checks.md",
        [
            ("API", "BASIC", "RESET"),
        ],
    )
    write_doc(
        tmp_path / "source.md",
        [
            ("API", "BASIC", "RESET"),
            ("API", "BASIC", "READY"),
        ],
    )

    checker = MustHaveCKs(
        source_files="source.md",
        funcs_and_checks_doc="functions_and_checks.md",
    ).set_workspace(str(tmp_path))

    passed, msg = checker.do_check()

    assert passed is False
    assert "Some 1 source file(s) contain 1 CK labels" in msg["error"]
    assert "FG-API/FC-BASIC/CK-READY (source.md:7)" in msg["details"]


def test_must_have_cks_fails_when_no_source_file_matches(tmp_path):
    write_doc(
        tmp_path / "functions_and_checks.md",
        [
            ("API", "BASIC", "RESET"),
        ],
    )

    checker = MustHaveCKs(
        source_files="missing*.md",
        funcs_and_checks_doc="functions_and_checks.md",
    ).set_workspace(str(tmp_path))

    passed, msg = checker.do_check()

    assert passed is False
    assert "No source files found" in msg["error"]


def test_must_have_cks_requires_each_matched_source_file_to_cover_required_cks(tmp_path):
    write_doc(
        tmp_path / "functions_and_checks.md",
        [
            ("API", "BASIC", "RESET"),
        ],
    )
    write_doc(
        tmp_path / "source_good.md",
        [
            ("API", "BASIC", "RESET"),
        ],
    )
    write_doc(
        tmp_path / "source_bad.md",
        [
            ("API", "BASIC", "RESET"),
            ("API", "BASIC", "READY"),
        ],
    )

    checker = MustHaveCKs(
        source_files="source_*.md",
        funcs_and_checks_doc="functions_and_checks.md",
    ).set_workspace(str(tmp_path))

    passed, msg = checker.do_check()

    assert passed is False
    assert "Some 1 source file(s) contain 1 CK labels" in msg["error"]
    assert "source_bad.md" in msg["details"]
    assert "FG-API/FC-BASIC/CK-READY (source_bad.md:7)" in msg["details"]
    assert "source_good.md" not in msg["details"]


def test_must_have_cks_reports_target_doc_parse_error(tmp_path):
    (tmp_path / "functions_and_checks.md").write_text(
        "<CK-RESET>\n",
        encoding="utf-8",
    )
    write_doc(
        tmp_path / "source.md",
        [
            ("API", "BASIC", "RESET"),
        ],
    )

    checker = MustHaveCKs(
        source_files="source.md",
        funcs_and_checks_doc="functions_and_checks.md",
    ).set_workspace(str(tmp_path))

    passed, msg = checker.do_check()

    assert passed is False
    assert "functions_and_checks.md" in msg["error"]
    assert "parent FC tag" in msg["error"]
