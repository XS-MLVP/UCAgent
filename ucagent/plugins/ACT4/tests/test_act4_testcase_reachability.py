from pathlib import Path
from types import SimpleNamespace

import pytest

from act4_privileged_suite.checkers import act4_testcase_reachability as reachability
from act4_privileged_suite.checkers.act4_test_asset_checker import ACT4TestAssetChecker


def _source(code: str, labels=("case_a",)) -> str:
    return code + "\n" + "\n".join(
        f'{label}_str: .string "test: 1; cg: H_cg; cp: cp_walk; bin: {label}"'
        for label in labels
    ) + "\n"


@pytest.mark.parametrize("condition", [
    "(__riscv_xlen == 32 && defined(ZICNTR_SUPPORTED)) && __riscv_xlen == 64",
    "defined(SSTC_SUPPORTED) && (64 == __riscv_xlen) && (__riscv_xlen == 32U)",
    "(__riscv_xlen < 40) && (__riscv_xlen >= 64)",
    "0",
])
def test_proves_dead_testcase_conditions(condition: str) -> None:
    result = reachability.inspect_source(_source(f"#if {condition}\ncase_a: csrr a0, htimedeltah\n#endif"))

    assert result["descriptor_count"] == 1
    assert result["impossible"][0]["testcase"] == "case_a"
    assert result["impossible"][0]["occurrences"][0]["conditions"][0]["line"] == 1


@pytest.mark.parametrize("code", [
    "#if __riscv_xlen == 32\n#if __riscv_xlen == 64\ncase_a: nop\n#endif\n#endif",
    "#if __riscv_xlen == 32\n#else\n#if __riscv_xlen == 32\ncase_a: nop\n#endif\n#endif",
    "#if __riscv_xlen == 32\n#elif __riscv_xlen == 32\ncase_a: nop\n#endif",
    "#if __riscv_xlen == 32\n#elif __riscv_xlen == 64\n#else\ncase_a: nop\n#endif",
    "#if (__riscv_xlen == 32) && \\\n (__riscv_xlen == 64)\ncase_a: nop\n#endif",
])
def test_nested_and_alternative_branches_are_checked(code: str) -> None:
    assert len(reachability.inspect_source(_source(code))["impossible"]) == 1


@pytest.mark.parametrize("condition", [
    "__riscv_xlen == 32 && defined(ZICNTR_SUPPORTED)",
    "(__riscv_xlen == 32) || (__riscv_xlen == 64)",
    "UDB_NUM_EXTERNAL_GUEST_INTERRUPTS >= 39",
    "defined(OPTIONAL_SUPPORTED)",
    "__riscv_xlen == 64 && CUSTOM_MACRO(3)",
    "(__riscv_xlen == 32 && __riscv_xlen == 64) || CUSTOM_MACRO(3)",
    "CUSTOM_MACRO(3) ? (__riscv_xlen == 32 && __riscv_xlen == 64) : 1",
    "(__riscv_xlen & 32) != 0",
    "!__riscv_xlen == 32",  # Unsupported C unary/comparison precedence is unknown.
    "-1 > 1U",  # C unsigned conversion must not be replaced with Python comparison.
    "0xffffffffU > -1",
])
def test_optional_or_unknown_conditions_are_not_errors(condition: str) -> None:
    result = reachability.inspect_source(_source(f"#if {condition}\ncase_a: nop\n#endif"))

    assert not result["impossible"]


def test_one_viable_definition_is_enough() -> None:
    code = "#if 0\ncase_a: nop\n#else\ncase_a: add a0, a0, a1\n#endif"
    assert not reachability.inspect_source(_source(code))["impossible"]


def test_comments_and_strings_do_not_create_conditional_branches() -> None:
    code = '/*\n#if 0\n*/\n// #if 0\ncase_a: nop\nother: .string "#if 0"'
    result = reachability.inspect_source(_source(code))
    assert not result["impossible"]
    assert not result["parse_issues"]


def test_unbalanced_conditionals_are_unverified() -> None:
    result = reachability.inspect_source(_source("#if 0\ncase_a: nop"))
    assert result["parse_issues"]
    assert not result["impossible"]


def test_line_splicing_precedes_comment_removal() -> None:
    code = "// continued comment " + "\\\n" + "#if 0\ncase_a: nop\n// continued comment " + "\\\n" + "#endif"
    result = reachability.inspect_source(_source(code))
    assert not result["impossible"]
    assert not result["parse_issues"]


def test_redefined_compiler_xlen_is_not_assumed() -> None:
    result = reachability.inspect_source(_source(
        "#undef __riscv_xlen\n#define __riscv_xlen CUSTOM_XLEN\n"
        "#if __riscv_xlen == 128\ncase_a: nop\n#endif"
    ))
    assert not result["impossible"]


def test_data_descriptor_alone_is_not_a_testcase_entry() -> None:
    result = reachability.inspect_source(_source(""))
    assert result["unresolved_descriptors"] == ["case_a"]
    assert not result["linked_labels"]


def test_unknown_macro_is_reported_without_claiming_reachability() -> None:
    result = reachability.inspect_source(_source("#if CUSTOM_MACRO(3)\ncase_a: nop\n#endif"))
    assert result["conditional_unverified_labels"] == ["case_a"]
    assert not result["impossible"]


@pytest.mark.parametrize("stdout, expected", [
    ("case_a t 80000000 4\ncase_a_str d 80001000 40\n", 1),
    ("case_a_str d 80001000 40\nrvmodel_halt_pass T 80000004 4\n", 0),
    ("case_a d 80001000 40\ncase_a_str d 80002000 40\n", 0),
    ("", None),
    ("rvmodel_halt_pass T 80000004 4\n", None),
])
def test_elf_counts_only_retained_text_labels(monkeypatch, stdout, expected) -> None:
    monkeypatch.setattr(reachability.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    result = reachability.inspect_elf(Path("case.elf"), ["case_a"], "/tools/nm")
    assert result["compiled_testcases"] == expected
    assert result["command"] == ["/tools/nm", "-P", "--defined-only", "case.elf"]


def test_symbol_tool_failure_is_unverified(monkeypatch) -> None:
    monkeypatch.setattr(reachability.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="", stderr="Unsupported ELF"))
    result = reachability.inspect_elf(Path("case.elf"), ["case_a"], "/tools/nm")
    assert result["compiled_testcases"] is None
    assert result["limitation"] == "Unsupported ELF"


def _assets(tmp_path, code):
    source = tmp_path / "H-00.S"
    source.write_text(_source(code))
    elf = tmp_path / "H-00.elf"
    elf.write_bytes(b"\x7fELF\x02" + b"\0" * 59)
    return source, elf


def test_dead_case_blocks_checker_even_with_other_successful_assets(tmp_path, monkeypatch) -> None:
    source, elf = _assets(tmp_path, "#if __riscv_xlen == 32 && __riscv_xlen == 64\ncase_a: nop\n#endif")
    monkeypatch.setattr(reachability, "find_nm", lambda _: None)
    checker = ACT4TestAssetChecker(source_files=[str(source)], elf_files=[str(elf)],
                                  validate_test_config=False, check_testcase_reachability=True).set_workspace(str(tmp_path))

    ok, result = checker.do_check()

    assert not ok
    report = result["report"]
    assert report["checks"]["testcase_reachability"]["impossible_testcases"] == 1
    assert any(f["check"] == "testcase_guard_unsatisfiable" and f["severity"] == "error"
               for f in report["findings"])
    assert not report["checks"]["testcase_reachability"]["compiled_counts_complete"]


def test_target_exclusion_is_a_warning_not_a_generation_blocker(tmp_path, monkeypatch) -> None:
    source, elf = _assets(tmp_path, "#if __riscv_xlen == 32\ncase_a: nop\n#endif")
    monkeypatch.setattr(reachability, "find_nm", lambda _: "/tools/nm")
    monkeypatch.setattr(reachability.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="case_a_str d 1000 40\n", stderr=""))
    checker = ACT4TestAssetChecker(source_files=[str(source)], elf_files=[str(elf)],
                                  validate_test_config=False, check_testcase_reachability=True).set_workspace(str(tmp_path))

    ok, result = checker.do_check()

    assert ok
    report = result["report"]
    assert report["checks"]["testcase_reachability"]["elfs"][0]["compiled_testcases"] == 0
    assert any(f["check"] == "testcase_empty_for_target" for f in report["findings"])


def test_only_selected_elf_paths_are_inspected(tmp_path, monkeypatch) -> None:
    source, selected = _assets(tmp_path, "case_a: nop")
    stale = tmp_path / "stale" / selected.name
    stale.parent.mkdir()
    stale.write_bytes(selected.read_bytes())
    monkeypatch.setattr(reachability, "find_nm", lambda _: "/tools/nm")
    commands = []

    def nm(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="case_a t 1000 4\n", stderr="")

    monkeypatch.setattr(reachability.subprocess, "run", nm)
    checker = ACT4TestAssetChecker(source_files=[str(source)], elf_files=[str(selected)],
                                  validate_test_config=False, check_testcase_reachability=True).set_workspace(str(tmp_path))
    ok, _ = checker.do_check()
    assert ok
    assert [command[-1] for command in commands] == [str(selected)]
