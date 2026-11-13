"""Test complete source-to-rule explanations and binary-safe ELF descriptions."""

import copy
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile

import pytest
import yaml

from act4_privileged_suite import xiangshan_bundle as bundle
from act4_privileged_suite.xiangshan_trace import testcase_inventory as inventory_cases, validate_trace
from test_act4_xiangshan_handoff import HandoffHarness


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Build the same canonical source fixtures as the handoff integration tests."""
    return HandoffHarness(tmp_path, monkeypatch)


@pytest.mark.parametrize("mutation", [None, "instruction", "reason", "counter", "group", "stale"])
def test_expanded_labels_need_real_same_group_instruction_evidence(harness, mutation):
    """Parameter-expanded ACT labels retain real instruction-level links, never invented bin hits."""
    source = harness.source / "sample.S"
    source.write_text("Sstc_cg_cp_template_case0:\naddi a0, zero, 0\n")
    coverage = 'covergroup Sstc_cg;\ncp_asm_count: coverpoint ins.ins_str == "addi";\nendgroup\n'
    (harness.source / "coverage.svh").write_text(coverage)
    trace = harness.trace
    point = trace["coverpoints"][0]
    point["id"] = "Sstc_cg/cp_asm_count"
    point["definition"]["quote"] = coverage.splitlines()[1]
    point["rules"][0]["kind"] = "isa_reasoned"
    case = trace["tests"][0]["cases"][0]
    case.update(id="Sstc_cg_cp_template_case0", coverpoints=[point["id"]],
                mapping_reason="Only instruction execution is linked; the template's specialized bin is unresolved.")
    case["evidence"].update(lines=[1, 2], quote=source.read_text().strip())
    if mutation == "instruction":
        source.write_text(source.read_text().replace("addi", "sub"))
        case["evidence"]["quote"] = source.read_text().strip()
    elif mutation == "reason":
        case.pop("mapping_reason")
    elif mutation == "counter":
        case["coverpoints"] = ["Sstc_cg/cp_other"]
    elif mutation == "group":
        source.write_text(source.read_text().replace("Sstc_cg", "Other_cg"))
        case["id"] = "Other_cg_cp_template_case0"
        case["evidence"]["quote"] = source.read_text().strip()
    assert harness.checker("inputs").do_check(action="prepare")[0]
    root = harness.output / "bundle/act4"
    if mutation == "stale":
        validate_trace(root, copy.deepcopy(trace), ["priv/Sstc/sample.S"])
        (root / "tests/priv/Sstc/sample.S").write_text("Sstc_cg_cp_template_case0:\nsub a0, zero, zero\n")
    if mutation:
        with pytest.raises(ValueError):
            validate_trace(root, copy.deepcopy(trace), ["priv/Sstc/sample.S"])
    else:
        checked = validate_trace(root, copy.deepcopy(trace), ["priv/Sstc/sample.S"])
        rendered = bundle.annotate_source(source.read_bytes(), checked["tests"][0], bundle.test_description(checked, checked["tests"][0]))
        assert b"specialized bin is unresolved" in rendered


def test_annotation_preserves_only_native_configuration_delimiters():
    """Describing ACT's header must not create a second header recognized by its parser."""
    original = b"# START_TEST_CONFIG\n# NEEDS_SIGNATURE: true\n# END_TEST_CONFIG\naddi a0, zero, 0\n"
    test = {"cases": [{"lines": [4, 4], "id": "case", "description": "START_TEST_CONFIG description",
                      "stimulus": "END_TEST_CONFIG", "expected": "zero", "coverpoints": ["group/point"],
                      "mapping_reason": "START_TEST_CONFIG"}]}
    description = {"summary": "START_TEST_CONFIG is not a header here", "preconditions": "END_TEST_CONFIG",
                   "setup": "setup", "exercise": "execute", "check": "compare", "limitations": "fixture", "coverpoints": []}
    output = bundle.annotate_source(original, test, description)
    assert output.count(b"START_TEST_CONFIG") == 1
    assert output.count(b"END_TEST_CONFIG") == 1
    assert b"# START_TEST_CONFIG\n# NEEDS_SIGNATURE: true\n# END_TEST_CONFIG\n" in output
    assert b"START TEST CONFIG" in output


def test_frozen_trace_reuses_validation_only_for_unchanged_inputs(harness, monkeypatch):
    """Large traces need no reparsing after adapt, but changed evidence still invalidates the target."""
    from act4_privileged_suite.checkers import act4_xiangshan_checker

    harness.ready()

    def unexpected_validation(*args, **kwargs):
        """Detect redundant semantic validation of a fingerprint-identical frozen trace."""
        raise AssertionError("Unchanged trace should be verified through the frozen plan")

    monkeypatch.setattr(act4_xiangshan_checker, "validate_trace", unexpected_validation)
    assert harness.checker("target").do_check()[0]
    trace_path = harness.output / "traceability.yaml"
    trace_path.write_text(trace_path.read_text() + "\n")
    passed, result = harness.checker("target").do_check()
    assert not passed and "adapt" in result["error"]


@pytest.mark.parametrize("mutation", ["missing_test", "extra_test", "missing_case", "duplicate_case", "description", "stimulus", "expected", "missing_point", "missing_rule", "quote", "group", "mapping", "rule_quote", "case_range"])
def test_trace_rejects_incomplete_or_fabricated_links(harness, mutation):
    """Reject omitted testcase explanations, undefined identities and false source relationships."""
    trace = copy.deepcopy(harness.trace)
    if mutation == "missing_test":
        trace["tests"] = []
    elif mutation == "extra_test":
        trace["tests"].append({**trace["tests"][0], "path": "extra.S"})
    elif mutation == "missing_case":
        trace["tests"][0]["cases"] = []
    elif mutation == "duplicate_case":
        trace["tests"][0]["cases"] *= 2
    elif mutation in {"description", "stimulus", "expected"}:
        trace["tests"][0]["cases"][0][mutation] = "TODO"
    elif mutation == "missing_point":
        trace["tests"][0]["cases"][0]["coverpoints"] = ["Sstc_cg/invented"]
    elif mutation == "missing_rule":
        trace["rules"] = []
    elif mutation == "quote":
        trace["coverpoints"][0]["definition"]["quote"] = "invented"
    elif mutation == "group":
        trace["coverpoints"][0]["id"] = "Another_cg/cp_timer"
        trace["tests"][0]["cases"][0]["coverpoints"] = ["Another_cg/cp_timer"]
    elif mutation == "mapping":
        (harness.source / "norm.yaml").write_text("normative_rule_definitions:\n  - name: timer_enabled\n    coverpoint: ['Other_cg/cp_timer']\n")
        for record in (trace["rules"][0]["definition"], trace["coverpoints"][0]["rules"][0]["evidence"]):
            record["quote"] = record["quote"].replace("Sstc_cg", "Other_cg")
    elif mutation == "rule_quote":
        trace["rules"][0]["id"] = "fake_rule"
        trace["coverpoints"][0]["rules"][0]["id"] = "fake_rule"
    else:
        trace["tests"][0]["cases"][0]["evidence"]["path"] = "coverpoints/norm/Sstc.yaml"
    harness.write("traceability.yaml", trace)
    assert harness.checker("inputs").do_check(action="prepare")[0]
    passed, result = harness.checker("target").do_check(action="adapt")
    assert not passed, result


def test_every_native_testcase_has_its_own_design_and_comment(harness):
    """A file with two ACT labels needs two explanations and preserves the original bytes."""
    path = harness.source / "sample.S"
    original = path.read_text() + "Sstc_cg_cp_timer_first:\naddi a0, zero, 0\nSstc_cg_cp_timer_second:\naddi a0, zero, 1\n"
    path.write_text(original)
    case = harness.trace["tests"][0]["cases"][0]
    harness.trace["tests"][0]["cases"] = [
        {**case, "id": "Sstc_cg_cp_timer_first", "evidence": {"path": "tests/priv/Sstc/sample.S", "lines": [5, 6], "quote": "Sstc_cg_cp_timer_first:\naddi a0, zero, 0"}},
        {**case, "id": "Sstc_cg_cp_timer_second", "stimulus": "Set a0 to one", "expected": "a0 equals one", "evidence": {"path": "tests/priv/Sstc/sample.S", "lines": [7, 8], "quote": "Sstc_cg_cp_timer_second:\naddi a0, zero, 1"}},
    ]
    harness.write("traceability.yaml", harness.trace)
    harness.built()
    assert path.read_text() == original
    selected = (harness.output / "bundle/act4/selected-tests/priv/Sstc/sample.S").read_text()
    assert selected.startswith("// ACT4 XiangShan test description\n")
    assert selected.count("// ACT4 testcase ") == 2
    assert "// Stimulus: Set a0 to one" in selected
    assert harness.checker("delivery").do_check(action="package")[0]
    report = (harness.output / "delivery/TESTS.md").read_text()
    assert "Sstc_cg_cp_timer_second" in report and "Set a0 to one" in report
    assert "timer_enabled" in report and "Observe timer enable selection" in report
    with tarfile.open(harness.output / "Sstc-kunminghu-v3.tar.gz") as archive:
        assert not any(name.endswith(".elf.md") for name in archive.getnames())
        assert "Sstc-kunminghu-v3/TESTS.md" in archive.getnames()


def test_isa_reasoned_mapping_remains_explicit_and_source_bound(harness):
    """Allow a documented ISA-derived link without presenting it as an upstream norm mapping."""
    link = harness.trace["coverpoints"][0]["rules"][0]
    link.update(kind="isa_reasoned", evidence=copy.deepcopy(harness.trace["rules"][0]["definition"]), reason="Inferred from the stated fixture rule")
    harness.write("traceability.yaml", harness.trace)
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    assert "isa_reasoned" in (harness.output / "delivery/TESTS.md").read_text()


def test_point_must_belong_to_the_cited_group(harness):
    """A declaration from another group cannot be attached to a real but unrelated group."""
    (harness.source / "coverage.svh").write_text("covergroup Sstc_cg;\nendgroup\ncovergroup Other_cg;\ncp_timer: coverpoint enabled;\nendgroup\n")
    harness.trace["coverpoints"][0]["definition"]["lines"] = [4, 4]
    harness.write("traceability.yaml", harness.trace)
    assert harness.checker("inputs").do_check(action="prepare")[0]
    passed, result = harness.checker("target").do_check(action="adapt")
    assert not passed and "not in the named covergroup" in result["error"]


def test_trace_tamper_and_missing_elf_note_block_completion(harness):
    """Freeze explanatory content as build input and reject an ELF stripped of its note."""
    harness.built()
    result = json.loads((harness.output / "bundle/build-result.json").read_text())
    elf = harness.output / "bundle" / result["tests"][0]["elf"]
    content = bytearray(elf.read_bytes())
    struct.pack_into("<HHH", content, 58, 0, 0, 0)
    elf.write_bytes(content)
    assert not harness.checker("build").do_check(is_complete=True)[0]
    with pytest.raises(ValueError, match="section table"):
        bundle.elf_description(elf)
    harness.trace["tests"][0]["summary"] = "Changed purpose"
    harness.write("traceability.yaml", harness.trace)
    assert not harness.checker("target").do_check()[0]


@pytest.mark.parametrize("mutation", ["allocated", "loaded", "extra_note", "no_loaded_selfcheck"])
def test_description_cannot_alter_execution_or_supply_fake_selfcheck_markers(harness, mutation):
    """Keep notes outside loaded memory and keep executable validation independent from prose."""
    harness.built()
    result = json.loads((harness.output / "bundle/build-result.json").read_text())
    elf = harness.output / "bundle" / result["tests"][0]["elf"]
    data = bytearray(elf.read_bytes())
    table = struct.unpack_from("<Q", data, 40)[0]
    note_offset, note_length = struct.unpack_from("<QQ", data, table + 64 + 24)
    if mutation == "allocated":
        struct.pack_into("<Q", data, table + 64 + 8, 2)
    elif mutation == "loaded":
        struct.pack_into("<QQ", data, 64 + 32, len(data), len(data))
    elif mutation == "extra_note":
        struct.pack_into("<Q", data, table + 64 + 32, note_length + 4)
    else:
        data[128:240] = bytes(112)
        data.extend(b"RVCP-SUMMARY: TEST PASSED TEST FAILED\x6b\x00\x05\x00")
    elf.write_bytes(data)
    with pytest.raises(ValueError):
        if mutation == "no_loaded_selfcheck":
            bundle.inspect_elf(elf, {"base": 0x80000000, "size": 0x10000000})
        else:
            bundle.elf_description(elf)


def test_describe_works_after_relocation_without_ucagent(harness, tmp_path):
    """Read the exact embedded description using the standalone standard-library runner."""
    harness.built()
    assert harness.checker("delivery").do_check(action="package")[0]
    result = json.loads((harness.output / "delivery/manifest.json").read_text())
    command = subprocess.run([sys.executable, str(harness.output / "delivery/handoff.py"), "describe", result["tests"][0]["elf"]],
                             cwd=tmp_path, capture_output=True, text=True, check=True)
    description = json.loads(command.stdout)
    assert description["coverpoints"][0]["rules"] == ["timer_enabled"]


def test_real_riscv_link_preserves_instructions_and_nonallocated_note(tmp_path):
    """Assemble and link descriptions with a real toolchain; compare executable instruction bytes."""
    compiler = shutil.which("riscv64-unknown-elf-gcc")
    if not compiler:
        pytest.skip("RISC-V compiler not installed")
    source = b'.section .text\n.global _start\n_start:\naddi a0, zero, 0\n.word 0x0005006b\n.section .rodata\n.asciz "RVCP-SUMMARY: TEST PASSED"\n.asciz "RVCP-SUMMARY: TEST FAILED"\n'
    test = {"cases": [{"id": "file", "lines": [1, 9], "description": "Zero result", "stimulus": "Write zero", "expected": "a0=0", "coverpoints": ["Fixture_cg/cp_zero"]}]}
    description = {"summary": "Test description with unicode: \u96f6", "coverpoints": [{"id": "Fixture_cg/cp_zero", "intent": "Observe zero", "rules": ["zero"]}]}
    description.update({field: "Synthetic design explanation" for field in ("preconditions", "setup", "exercise", "check", "limitations")})
    script = tmp_path / "link.ld"
    script.write_text('OUTPUT_ARCH("riscv")\nENTRY(_start)\nSECTIONS { . = 0x80000000; .text : { *(.text) } .rodata : { *(.rodata) } .note.ucagent.act4 0 : { KEEP(*(.note.ucagent.act4)) } }\n')
    outputs = []
    for name, content in (("plain", source), ("annotated", bundle.annotate_source(source, test, description))):
        assembly = tmp_path / f"{name}.S"
        assembly.write_bytes(content)
        elf = tmp_path / f"{name}.elf"
        subprocess.run([compiler, "-nostdlib", "-march=rv64i", "-mabi=lp64", "-Wl,--build-id=none", "-T", str(script), str(assembly), "-o", str(elf)], check=True, capture_output=True)
        outputs.append(elf)
    assert bundle.elf_description(outputs[1]) == description
    assert bundle.inspect_elf(outputs[1], {"base": 0x80000000, "size": 0x10000})["entry"] == 0x80000000
    instructions = []
    for elf in outputs:
        data = elf.read_bytes()
        table = struct.unpack_from("<Q", data, 32)[0]
        size, count = struct.unpack_from("<HH", data, 54)
        instructions.append([data[offset:offset + length] for kind, flags, offset, virtual, physical, length, memory, align in
            (struct.unpack_from("<IIQQQQQQ", data, table + index * size) for index in range(count)) if kind == 1 and flags & 1])
    assert instructions[0] == instructions[1]
    objcopy = shutil.which("riscv64-unknown-elf-objcopy")
    objdump = shutil.which("riscv64-unknown-elf-objdump")
    if objcopy and objdump:
        binary = tmp_path / "annotated.bin"
        subprocess.run([objcopy, "-O", "binary", str(outputs[1]), str(binary)], check=True, capture_output=True)
        base, length = bundle.binary_extent(outputs[1])
        assert base == 0x80000000 and length == binary.stat().st_size
        assert b"UCAGENT" not in binary.read_bytes()
        disassembly = subprocess.run([objdump, "-d", str(outputs[1])], check=True, capture_output=True, text=True)
        assert "80000000" in disassembly.stdout and "<_start>" in disassembly.stdout


def test_complete_guide_trace_example(tmp_path):
    """Exercise the published complete trace document against its stated example sources."""
    guide = Path(__file__).resolve().parents[1] / "src/act4_privileged_suite/Guide_Doc/ACT4_XiangShan_Handoff_Guide.md"
    text = guide.read_text(encoding="utf-8").split("## 5.", 1)[1]
    document = yaml.safe_load(re.search(r"```yaml\n(.*?)```", text, re.DOTALL)[1])
    sources = {"tests/priv/Fixture/one.S": "Fixture_cg_cp_zero_case0:\naddi a0, zero, 0\n",
               "coverpoints/priv/Fixture.svh": "covergroup Fixture_cg;\ncp_zero: coverpoint value;\nendgroup\n",
               "references/rules.adoc": "[[fixture_zero]]\nThe fixture requires a zero result.\n",
               "coverpoints/norm/Fixture.yaml": "normative_rule_definitions:\n  - name: fixture_zero\n    coverpoint: [Fixture_cg/cp_zero]\n"}
    for name, content in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    result = validate_trace(tmp_path, document, ["priv/Fixture/one.S"])
    assert len(result["tests"][0]["cases"]) == 1


def test_inventory_rejects_duplicate_labels_and_ignores_string_labels(tmp_path):
    """Count actual code labels while rejecting duplicates and omitting signature strings."""
    path = tmp_path / "tests/one.S"
    path.parent.mkdir()
    path.write_text('Fixture_cg_cp_zero_case0:\naddi a0, zero, 0\nFixture_cg_cp_zero_case0_str:\n.asciz "name"\n')
    assert len(inventory_cases(tmp_path, ["one.S"])["one.S"]["cases"]) == 1
    with path.open("a") as stream:
        stream.write("Fixture_cg_cp_zero_case0:\n")
    with pytest.raises(ValueError, match="Duplicate"):
        inventory_cases(tmp_path, ["one.S"])
