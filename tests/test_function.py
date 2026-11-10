#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for utility functions."""

import os
import pytest
current_dir = os.path.dirname(os.path.abspath(__file__))

from ucagent.util.functions import find_files_by_glob, find_files_by_regex, find_files_by_pattern, render_template_dir, chmode_ro_by_pattern, chmode_rw
import ucagent.util.functions as fc


def test_find_files_by_glob():
    """Test the find_files_by_glob function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_glob(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_regex():
    """Test the find_files_by_regex function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = r".*\.md$"
    
    # Call the function to find files
    found_files = find_files_by_regex(test_dir, pattern)

    # Print the found files
    print("Found files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_find_files_by_pattern():
    """Test the find_files_by_pattern function."""
    # Define the directory and pattern
    test_dir = os.path.join(current_dir, "../examples")
    pattern = "*.md"
    
    # Call the function to find files
    found_files = find_files_by_pattern(test_dir, pattern)

    # Print the found files
    print("Found files matching pattern '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = r".*\.md$"
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching regex '{}':".format(pattern))
    for file in found_files:
        print(file)

    pattern = ["*.md", r".*\.md$", "alu.md"]
    found_files = find_files_by_pattern(test_dir, pattern)
    print("\nFound files matching patterns '{}':".format(pattern))
    for file in found_files:
        print(file)
    print("------------------------")


def test_render_template_dir(tmp_path):
    """Test the render_template_dir function."""
    workspace = str(tmp_path)
    template = os.path.abspath(
        os.path.join(current_dir, "../ucagent/plugins/UnitTest/src/unit_test/templates/unit_test")
    )
    context = {"DUT": "alu"}

    rendered_files = render_template_dir(workspace, template, context)

    assert "unit_test/alu_bug_analysis.md" in rendered_files
    assert "unit_test/alu_functions_and_checks.md" in rendered_files
    assert "unit_test/tests/alu_api.py" in rendered_files
    assert (tmp_path / "unit_test" / "alu_bug_analysis.md").is_file()


def test_chmode_ro_by_pattern_keeps_write_dirs_carve_outs(tmp_path):
    """Read-only chmod must skip paths a deeper write entry re-allows."""
    dut = tmp_path / "dut"
    dut.mkdir()
    (dut / "spec.md").write_text("spec\n", encoding="utf-8")
    (dut / "top.v").write_text("module top();\n", encoding="utf-8")
    db = dut / "dut.db"
    db.mkdir()
    (db / "state.log").write_text("log\n", encoding="utf-8")

    chmode_ro_by_pattern(
        str(tmp_path), ["dut"], write_dirs=["dut/*.md", "dut/dut.db"]
    )

    assert (dut / "spec.md").stat().st_mode & 0o200, "carved file must stay writable"
    assert (db / "state.log").stat().st_mode & 0o200, "carved subtree must stay writable"
    assert db.stat().st_mode & 0o200, "carved directory must stay writable"
    assert dut.stat().st_mode & 0o200, "parent holding carve-outs must stay writable"
    assert not (dut / "top.v").stat().st_mode & 0o200, "sibling must be read-only"

    chmode_rw([str(dut / "top.v")])
    # Without write_dirs the whole protected tree becomes read-only.
    chmode_ro_by_pattern(str(tmp_path), ["dut"])
    assert not (dut / "spec.md").stat().st_mode & 0o200
    chmode_rw([str(dut / "spec.md")])


def test_render_template_target_preserves_non_template_files(tmp_path):
    """Target-mode rendering must merge only template-owned files."""

    template = tmp_path / "template"
    template.mkdir()
    (template / "{{DUT}}.txt").write_text("DUT={{DUT}} OUT={{OUT}}\n", encoding="utf-8")
    output = tmp_path / "generated"
    output.mkdir()
    preserved = output / "existing.txt"
    preserved.write_text("literal {{DUT}}\n", encoding="utf-8")

    rendered = render_template_dir(
        str(tmp_path),
        str(template),
        {"DUT": "alu", "OUT": "generated"},
        target_dir="{OUT}",
    )

    assert rendered == ["generated/alu.txt"]
    assert (output / "alu.txt").read_text(encoding="utf-8") == "DUT=alu OUT=generated\n"
    assert preserved.read_text(encoding="utf-8") == "literal {{DUT}}\n"
    assert not (tmp_path / "unit_test" / "{{DUT}}_bug_analysis.md").exists()


def test_render_template_dir_excludes_installer_bytecode(tmp_path):
    """Installed template bytecode must never be copied into a workspace."""

    template = tmp_path / "installed" / "templates" / "unit_design"
    cache = template / "tests" / "__pycache__"
    cache.mkdir(parents=True)
    (template / "tests" / "{{DUT}}_reference.py").write_text(
        'DUT = "{{DUT}}"\n', encoding="utf-8"
    )
    (cache / "{{DUT}}_reference.cpython-312.pyc").write_bytes(b"compiled")
    (template / "tests" / "stale.pyo").write_bytes(b"optimized")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    rendered = render_template_dir(
        str(workspace),
        str(template),
        {"DUT": "alu", "OUT": "output"},
        target_dir="{OUT}",
    )

    assert rendered == ["output/tests/alu_reference.py"]
    assert (workspace / "output" / "tests" / "alu_reference.py").read_text(
        encoding="utf-8"
    ) == 'DUT = "alu"\n'
    assert not (workspace / "output" / "tests" / "__pycache__").exists()
    assert not (workspace / "output" / "tests" / "stale.pyo").exists()

    default_workspace = tmp_path / "default-workspace"
    default_workspace.mkdir()
    default_rendered = render_template_dir(
        str(default_workspace),
        str(template),
        {"DUT": "alu"},
    )

    assert default_rendered == ["unit_design/tests/alu_reference.py"]
    assert not (
        default_workspace / "unit_design" / "tests" / "__pycache__"
    ).exists()
    assert not (
        default_workspace / "unit_design" / "tests" / "stale.pyo"
    ).exists()


def test_sync_dir_to_matches_relative_ignore_paths_without_broad_name_matches(
    tmp_path,
):
    """History sync must honor path rules while retaining similarly named artifacts."""

    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "performance" / "waves").mkdir(parents=True)
    (source / "performance" / "results").mkdir(parents=True)
    (source / "metadata").mkdir(parents=True)
    (source / "tests" / "database").mkdir(parents=True)
    (source / "performance" / "waves" / "tc.vcd").write_text(
        "wave\n", encoding="utf-8"
    )
    (source / "performance" / "results" / "tc.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (source / "metadata" / "ledger.json").write_text("{}\n", encoding="utf-8")
    (source / "tests" / "database" / "kept.json").write_text(
        "{}\n", encoding="utf-8"
    )

    fc.sync_dir_to(
        str(source),
        str(target),
        ["performance/waves", "tests/data"],
    )

    assert not (target / "performance" / "waves").exists()
    assert (target / "performance" / "results" / "tc.json").is_file()
    assert (target / "metadata" / "ledger.json").is_file()
    assert (target / "tests" / "database" / "kept.json").is_file()


def test_replace_bash_var():
    """Test the replace_bash_var function."""
    template_str = "Hello, $(name: Bob )! Welcome to $( place: Wonderland ). Your score is $(score: 100)."
    data = {
        "name": "Alice",
        "place": "Wonderland"
        # 'score' is intentionally left out to test default value
    }
    result = fc.replace_bash_var(template_str, data)
    print("Original string:", template_str)
    print("Data:", data)
    print("Replaced string:", result)
    print("------------------------")
    assert result == "Hello, Alice! Welcome to Wonderland. Your score is 100."
    assert fc.replace_bash_var("$(missing:)", {}) == ""
    assert fc.replace_bash_var("$(missing: fallback)", {}) == "fallback"
    assert fc.replace_bash_var("$(present: fallback)", {"present": ""}) == ""


def test_newest_file_mtime_reuses_recent_scan(tmp_path):
    """A fresh changed-files scan is reused instead of rescanning."""

    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")

    calls = {"count": 0}
    original = fc.list_files_by_mtime

    def counting_call(directory, *args, **kwargs):
        calls["count"] += 1
        return original(directory, *args, **kwargs)

    first = fc.newest_file_mtime(str(tmp_path), max_age=5.0)
    assert first == (tmp_path / "a.txt").stat().st_mtime

    import ucagent.util.functions as functions_module
    functions_module._FILE_ACTIVITY_CACHE.clear()
    functions_module.list_files_by_mtime = counting_call
    try:
        original(tmp_path)  # any existing caller (TUI/server) refreshes the cache
        reused = fc.newest_file_mtime(str(tmp_path), max_age=5.0)
        assert reused == first
        assert calls["count"] == 0, "fresh cache must be reused without a rescan"

        stale = fc.newest_file_mtime(str(tmp_path), max_age=0.0)
        assert stale == first
        assert calls["count"] == 1, "a stale cache triggers exactly one proactive rescan"
    finally:
        functions_module.list_files_by_mtime = original


@pytest.mark.parametrize('mode', [0o644, 0o700, 0o755])
def test_read_only_protection_preserves_executable_bits(tmp_path, mode):
    """Compiled coverage tools remain runnable across protection and restoration."""
    import stat
    from ucagent.util.functions import chmode_ro
    path = tmp_path / 'coverage-helper'
    path.write_text('helper')
    path.chmod(mode)
    chmode_ro([str(path)])
    protected = stat.S_IMODE(path.stat().st_mode)
    assert protected & 0o222 == 0
    assert protected & 0o111 == mode & 0o111
    chmode_rw([str(path)])
    restored = stat.S_IMODE(path.stat().st_mode)
    assert restored & 0o200
    assert restored & 0o111 == mode & 0o111
