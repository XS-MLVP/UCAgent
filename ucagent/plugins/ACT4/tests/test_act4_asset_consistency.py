from pathlib import Path

import pytest
import yaml

from act4_privileged_suite.checkers import act4_asset_consistency as consistency
from act4_privileged_suite.checkers.act4_asset_checker import ACT4AssetChecker


@pytest.mark.parametrize(
    "source",
    [
        "import act4_privileged_suite",
        "from act4_privileged_suite.checkers import act4_asset_consistency",
        "import importlib\nimportlib.import_module('act4_privileged_suite')",
        "open('act4_privileged_suite/data.json')",
    ],
)
def test_generator_cannot_depend_on_plugin_package(tmp_path, source):
    generator = tmp_path / "Example.py"
    generator.write_text(source)
    report = consistency.run_asset_checks(
        act4_root=tmp_path,
        generator_files=[generator],
        check_consistency=False,
        require_standalone_generator=True,
    )
    assert any(
        item["check"] == "generator_workspace_dependency"
        for item in report["findings"]
    )


@pytest.mark.parametrize("source", [
    '''from pathlib import Path
def load_contract():
    suite = Path(__file__).resolve().parents[7] / "unity_test/H"
    projection = suite / "H_generator_contract.json"
    if not projection.exists():
        return
    return projection.read_text()
''',
    'from pathlib import Path as P\np = P("H_vm_resource_contract.yaml")\ndata = p.read_bytes()',
    'import pathlib as pl\np = pl.Path("unity_test") / "H" / "data.json"\ndata = p.read_text()',
    'import os.path as op\np = op.join("unity_test", "H", "data.json")\nopen(p)',
    'from io import open as read_file\nread_file(file="../unity_test/H/data.json")',
    'from act4_privileged_suite.checkers import validate_contract',
    'try:\n    import ucagent\nexcept ImportError:\n    pass',
    'import importlib as imp\nimp.import_module("itgen.checker")',
    'import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parents[7] / "unity_test/H"))',
    'import sys\nsys.path.extend(["../unity_test/H"] )',
    'import os\nopen(os.getenv("ITGEN_CONTRACT_PATH"))',
    'import os\nopen(os.environ["UCAGENT_WORKSPACE"])',
    'import os\nopen(os.environ["ACT4_MANUAL_ROOT"])',
    'from os import getenv\ngetenv("ACT4_MANUAL_ROOT")',
    'from os import environ\nenviron.get("ACT4_MANUAL_ROOT")',
])
def test_standalone_generator_rejects_private_dependencies(tmp_path, source):
    generator = tmp_path / "H.py"
    generator.write_text(source)
    checker = ACT4AssetChecker(
        generator_files=[str(generator)], check_consistency=False,
        require_standalone_generator=True,
    ).set_workspace(str(tmp_path))
    passed, data = checker.do_check()
    failures = [f for f in data["report"]["findings"] if f["check"] == "generator_workspace_dependency"]
    assert not passed
    assert len(failures) == 1  # Aggregate file probes into one actionable finding.
    assert failures[0]["dependencies"]


@pytest.mark.parametrize("source", [
    '"""ITGen must not read unity_test/H/H_vm_resource_contract.yaml."""\n# import itgen',
    'import json\nfrom pathlib import Path\ndata = json.loads(Path("testplans/H.json").read_text())',
    'from pathlib import Path\np = Path(__file__).parent / "data.json"\ndata = p.read_text()',
    'def load_contract():\n    return {"mode": "Sv39"}',
    'code = ["# H_VM_PROFILE rv64_hlv_m", "# H_RESOURCE_MODE two_stage"]',
    'raise ValueError("missing unity_test/H/H_vm_resource_contract.yaml")',
    'def first():\n    path = "unity_test/H/private.json"\ndef second():\n    path = "testplans/H.json"\n    open(path)',
    'path = "unity_test/H/private.json"\ndef read_native(path):\n    open(path)',
    'import os\nimport sys\nsys.path.append("generators/testgen/src")\nvalue = os.getenv("ACT4_CONFIG")',
])
def test_standalone_generator_allows_native_inputs_and_annotations(tmp_path, source):
    generator = tmp_path / "H.py"
    generator.write_text(source)
    report = consistency.run_asset_checks(
        act4_root=tmp_path, generator_files=[generator],
        check_consistency=False, require_standalone_generator=True,
    )
    assert report["summary"]["errors"] == 0


def test_generator_scan_does_not_execute_source(tmp_path):
    """Inspect generated Python as data without running its top-level code."""
    marker = tmp_path / "executed.txt"
    generator = tmp_path / "Example.py"
    generator.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    )
    report = consistency.run_asset_checks(
        act4_root=tmp_path, generator_files=[generator],
        check_consistency=False, require_standalone_generator=True,
    )
    assert not marker.exists()
    assert report["summary"]["errors"] == 0


def test_standalone_generator_check_is_opt_in(tmp_path):
    generator = tmp_path / "H.py"
    generator.write_text('import itgen')
    report = consistency.run_asset_checks(
        act4_root=tmp_path, generator_files=[generator], check_consistency=False,
    )
    assert report["summary"]["errors"] == 0
    assert consistency.build_arg_parser().parse_args([
        "--require-standalone-generator",
    ]).require_standalone_generator


def _write_contract(path: Path, profiles: list[dict], dispositions: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "profiles": profiles,
                "coverage_disposition": dispositions,
            }
        ),
        encoding="utf-8",
    )


def test_scoped_coverage_only_exempts_fully_blocked_targets(
    tmp_path: Path,
) -> None:
    contract = tmp_path / "contract.yaml"
    _write_contract(
        contract,
        profiles=[
            {
                "profile_id": "allowed",
                "decision": "allowed",
                "coverage_targets": ["cp_allowed", "cp_partial"],
            },
            {
                "profile_id": "blocked_partial",
                "decision": "blocked",
                "coverage_targets": ["cp_partial"],
            },
            {
                "profile_id": "blocked_only",
                "decision": "blocked",
                "coverage_targets": ["cp_blocked"],
            },
        ],
        dispositions=[
            {
                "target": "cp_allowed",
                "planned_status": "required",
                "generated_profiles": ["allowed"],
                "blocked_profiles": [],
                "blocked_subcases": [],
            },
            {
                "target": "cp_partial",
                "planned_status": "partial",
                "generated_profiles": ["allowed"],
                "blocked_profiles": ["blocked_partial"],
                "blocked_subcases": [
                    {"scope": "guest fault path", "dependency": "guest trap"}
                ],
            },
            {
                "target": "cp_blocked",
                "planned_status": "blocked",
                "generated_profiles": [],
                "blocked_profiles": ["blocked_only"],
                "blocked_subcases": [
                    {"scope": "guest execution", "dependency": "guest entry"}
                ],
            },
        ],
    )
    findings = []

    required, blocked, experimental = consistency._load_generator_target_scope(
        tmp_path,
        contract,
        True,
        findings,
    )

    assert required == {"cp_allowed", "cp_partial"}
    assert blocked == {"cp_blocked"}
    assert experimental == set()
    assert findings == []


def test_scoped_coverage_keeps_experimental_targets_out_of_main_gate(
    tmp_path: Path,
) -> None:
    contract = tmp_path / "contract.yaml"
    _write_contract(
        contract,
        profiles=[
            {
                "profile_id": "candidate",
                "decision": "experimental",
                "coverage_targets": ["cp_candidate"],
            }
        ],
        dispositions=[],
    )
    findings = []

    required, blocked, experimental = consistency._load_generator_target_scope(
        tmp_path,
        contract,
        True,
        findings,
    )

    assert required == set()
    assert blocked == set()
    assert experimental == {"cp_candidate"}
    assert findings == []


def test_scoped_coverage_rejects_overbroad_blocked_disposition(
    tmp_path: Path,
) -> None:
    contract = tmp_path / "contract.yaml"
    _write_contract(
        contract,
        profiles=[
            {
                "profile_id": "allowed",
                "decision": "allowed",
                "coverage_targets": ["cp_mixed"],
            },
            {
                "profile_id": "blocked",
                "decision": "blocked",
                "coverage_targets": ["cp_mixed"],
            },
        ],
        dispositions=[
            {
                "target": "cp_mixed",
                "planned_status": "blocked",
                "generated_profiles": ["allowed"],
                "blocked_profiles": ["blocked"],
                "blocked_subcases": [
                    {"scope": "guest path", "dependency": "guest entry"}
                ],
            }
        ],
    )
    findings = []

    consistency._load_generator_target_scope(
        tmp_path,
        contract,
        True,
        findings,
    )

    assert any(item["check"] == "generator_coverage_disposition" for item in findings)


def test_current_priv_generator_api_and_auto_split_pass(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

@add_priv_test_generator("H", testcases_per_file=128)
def make_h(test_data) -> list[TestChunk]:
    chunks: list[TestChunk] = []
    chunk = test_data.begin_test_chunk("csr")
    chunk.code.append(test_data.add_testcase("one", "cp_one", "H_cg"))
    chunks.append(test_data.end_test_chunk())
    chunk = test_data.begin_test_chunk("vm")
    chunk.code.append(test_data.add_testcase("two", "cp_two", "H_cg"))
    chunks.append(test_data.end_test_chunk())
    return chunks
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert findings == []
    assert result["priv_generators"][0]["testcases_per_file"] == 128
    assert result["priv_generators"][0]["chunk_start_calls"] == 2


def test_generator_scan_propagates_coverpoint_through_simple_wrapper(
    tmp_path: Path,
) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        '''def _case(test_data, bin_name, coverpoint):
    return test_data.add_testcase(bin_name, coverpoint, "H_cg")

def _generate(test_data):
    return [_case(test_data, "one", "cp_one")]
''',
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)

    assert any(
        testcase["coverpoint"] == "cp_one"
        and testcase["covergroup"] == "H_cg"
        and testcase["inferred_through_helper"] is True
        for testcase in result["testcases"]
    )


def test_duplicate_priv_generator_definition_fails(
    tmp_path: Path,
) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

@add_priv_test_generator("H", testcases_per_file=64)
def make_h(test_data) -> list[TestChunk]:
    return []

@add_priv_test_generator("H", testcases_per_file=64)
def make_h(test_data) -> list[TestChunk]:
    return []
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=False,
        max_testcases_per_file=512,
    )

    checks = {item["check"] for item in findings}
    assert "generator_duplicate_function" in checks
    assert "generator_duplicate_registration" not in checks


@pytest.mark.parametrize("annotation", [
    "list[TestChunk]", "typing.Sequence[TestChunk]", "collections.abc.Sequence[TestChunk]",
    '"list[TestChunk]"', "tuple[TestChunk, ...]",
])
def test_multiple_native_generator_entries_and_sequence_annotations(tmp_path, annotation):
    generator = tmp_path / "H.py"
    generator.write_text("\n".join(
        f'''@add_priv_test_generator("H", testcases_per_file=16)
def {name}(td) -> {annotation}:
    td.begin_test_chunk()
    td.add_testcase("one", "cp_one", "H_cg")
    return [td.end_test_chunk()]
''' for name in ("make_host", "make_guest")
    ))
    findings = []
    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result, "H", findings, require_testchunk_api=True, require_auto_split=True,
        max_testcases_per_file=512,
    )
    assert len(result["priv_generators"]) == 2
    assert findings == []


def test_indirect_chunk_lifecycle_requires_review_not_rejection(tmp_path):
    generator = tmp_path / "H.py"
    generator.write_text('''@add_priv_test_generator("H", testcases_per_file=16)
def make_h(td) -> list[TestChunk]:
    td.begin_test_chunk()
    return helper.finish_chunks(td)
''')
    findings = []
    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result, "H", findings, require_testchunk_api=True, require_auto_split=True,
        max_testcases_per_file=512,
    )
    assert [(f["check"], f["severity"]) for f in findings] == [
        ("generator_testchunk_lifecycle_unverified", "warning"),
    ]


def test_priv_coverage_semantics_only_rejects_structural_false_hit_patterns(
    tmp_path: Path,
) -> None:
    coverage_file = tmp_path / "H_coverage.svh"
    coverage_file.write_text(
        """covergroup H_cg with function sample(ins_t ins);
csr_access: coverpoint ins.current.insn { bins op = {1}; }
csr_name: coverpoint ins.current.insn[31:20] { bins hstatus = {1}; }
walking_one: coverpoint $clog2(ins.current.rs1_val) iff ($onehot(ins.current.rs1_val)) {
  bins one = {[0:63]};
}
value: coverpoint ins.current.rs1_val { bins other = default; }
standalone_default: coverpoint ins.current.rs2_val { bins other = default; }
cp_value: cross csr_name, value;
endgroup
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    coverage = consistency.scan_systemverilog([coverage_file], findings)
    consistency._validate_priv_coverage_semantics(coverage, findings)

    checks = {item["check"] for item in findings}
    assert checks == {"coverage_bitwalk_bins", "coverage_default_bin"}


def test_coverage_intent_checks_cross_members_and_xlen_guard(tmp_path: Path) -> None:
    coverage_file = tmp_path / "H_coverage.svh"
    coverage_file.write_text(
        """covergroup H_cg with function sample(ins_t ins);
mode: coverpoint ins.mode { bins hs = {1}; }
csr_op: coverpoint ins.insn { bins op = {1}; }
csr_addr: coverpoint ins.insn[31:20] { bins csr = {1}; }
outcome: coverpoint ins.cause { bins ok = {0}; }
cp_csr: cross mode, csr_op, csr_addr;
`ifdef UDB_MXLEN_64
cp_high: cross mode, csr_op, csr_addr, outcome;
`endif
endgroup
""",
        encoding="utf-8",
    )
    intent = tmp_path / "H_coverage_intent.yaml"
    intent.write_text(
        """schema_version: 1
suite: H
supported_xlens: [64]
targets:
  cp_csr:
    required_cross_members: [mode, csr_op, csr_addr, outcome]
  cp_high:
    required_cross_members: [mode, csr_op, csr_addr, outcome]
    required_conditions: [ifdef:UDB_MXLEN_64]
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    coverage = consistency.scan_systemverilog([coverage_file], findings)
    summary = consistency._validate_coverage_intent(
        coverage, intent, "H", findings
    )

    assert summary["targets"] == 2
    assert [item["check"] for item in findings] == [
        "coverage_intent_cross_members"
    ]
    assert findings[0]["missing"] == ["outcome"]


def test_coverage_intent_accepts_scalar_coverpoint_requirements(
    tmp_path: Path,
) -> None:
    coverage_file = tmp_path / "H_coverage.svh"
    coverage_file.write_text(
        """covergroup H_cg with function sample(ins_t ins);
mode: coverpoint ins.mode { bins hs = {1}; bins vs = {2}; }
endgroup
""",
        encoding="utf-8",
    )
    intent = tmp_path / "H_coverage_intent.yaml"
    intent.write_text(
        """schema_version: 1
suite: H
supported_xlens: [64]
targets:
  mode:
    target_kind: coverpoint
    required_bins: [hs, vs]
    required_expression_terms: [ins.mode]
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    coverage = consistency.scan_systemverilog([coverage_file], findings)
    summary = consistency._validate_coverage_intent(
        coverage, intent, "H", findings
    )

    assert summary["targets"] == 1
    assert findings == []


def test_priv_generator_rejects_discarded_assembly_helper(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

def _csrw(csr, register):
    return f"csrw {csr}, x{register}"

@add_priv_test_generator("H", testcases_per_file=64)
def make_h(test_data) -> list[TestChunk]:
    chunks = []
    for name in ("one", "two"):
        test_data.begin_test_chunk(name)
        _csrw("mtval", 1)
        chunks.append(test_data.end_test_chunk())
    return chunks
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert any(
        item["check"] == "generator_discarded_assembly"
        and item["helper"] == "_csrw"
        for item in findings
    )


def test_normative_metadata_rejects_invented_rule(tmp_path: Path) -> None:
    coverage = tmp_path / "H_coverage.svh"
    mapping = tmp_path / "H.yaml"
    metadata = tmp_path / "hypervisor.yaml"
    coverage.write_text(
        """covergroup H_cg with function sample(ins_t ins);
cp_one: coverpoint ins.current.insn { bins one = {1}; }
endgroup
""",
        encoding="utf-8",
    )
    mapping.write_text(
        yaml.safe_dump(
            {
                "normative_rule_definitions": [
                    {"name": "invented_h_rule", "coverpoint": ["H_cg/cp_one"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    metadata.write_text(
        yaml.safe_dump(
            {
                "chapter_name": "H Extension",
                "normative_rule_definitions": [
                    {
                        "names": ["real_h_rule", "real_h_rule_alias"],
                        "tags": ["norm:real_h_rule"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = consistency.run_asset_checks(
        suite="H",
        act4_root=tmp_path,
        mapping=mapping,
        normative_metadata=metadata,
        coverage_files=[coverage],
        require_norm_metadata=True,
        checker_type="all",
    )

    assert report["checks"]["normative_metadata"] == str(metadata)
    assert any(
        item["check"] == "mapping_rule_exists"
        and item.get("rule") == "invented_h_rule"
        for item in report["findings"]
    )


def test_required_normative_metadata_cannot_fall_back_to_prose(
    tmp_path: Path,
) -> None:
    report = consistency.run_asset_checks(
        suite="H",
        act4_root=tmp_path,
        require_norm_metadata=True,
        checker_type="all",
    )

    assert any(
        item["check"] == "norm_metadata_exists" for item in report["findings"]
    )


def test_raw_sheet_shape_cannot_bypass_canonical_source_item_schema(
    tmp_path: Path,
) -> None:
    sheet = tmp_path / "raw.csv"
    sheet.write_text(
        "Coverpoint,Normative Rule\\ncp_one,sheet_rule_hint\\n",
        encoding="utf-8",
    )
    findings: list[dict] = []

    consistency.parse_canonical_sheet(sheet, findings)

    assert any(
        item["check"] == "sheet_schema"
        and "source_items" in item["message"]
        for item in findings
    )


def test_obsolete_string_generator_fails_current_api_and_split(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.priv.registry import add_priv_test_generator

@add_priv_test_generator("H")
def make_h(test_data) -> list[str]:
    return [test_data.add_testcase("one", "cp_one", "H_cg")]
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    checks = {item["check"] for item in findings}
    assert "generator_testchunk_return" in checks
    assert "generator_testchunk_lifecycle" not in checks
    assert "generator_auto_split_threshold" in checks


def test_small_generator_may_use_one_chunk_with_split_threshold(
    tmp_path: Path,
) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

@add_priv_test_generator("H", testcases_per_file=64)
def make_h(test_data) -> list[TestChunk]:
    chunks: list[TestChunk] = []
    test_data.begin_test_chunk("small")
    test_data.add_testcase("one", "cp_one", "H_cg")
    chunks.append(test_data.end_test_chunk())
    return chunks
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert findings == []


def test_auto_split_rejects_threshold_above_pinned_default(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

@add_priv_test_generator("H", testcases_per_file=1024)
def make_h(test_data) -> list[TestChunk]:
    chunks: list[TestChunk] = []
    for split_name in ("one", "two"):
        chunk = test_data.begin_test_chunk(split_name)
        chunks.append(test_data.end_test_chunk())
    return chunks
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert any(
        item["check"] == "generator_auto_split_threshold"
        and item["testcases_per_file"] == 1024
        for item in findings
    )


def test_auto_split_follows_local_chunk_helpers(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator

def add_chunks(test_data, chunks):
    for split_name in ("one", "two"):
        chunk = test_data.begin_test_chunk(split_name)
        chunks.append(test_data.end_test_chunk())

@add_priv_test_generator("H", testcases_per_file=128)
def make_h(test_data) -> list[TestChunk]:
    chunks: list[TestChunk] = []
    add_chunks(test_data, chunks)
    return chunks
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert findings == []
    assert result["priv_generators"][0]["chunk_start_calls"] == 1
    assert result["priv_generators"][0]["loop_has_chunk_start"] is True


def test_imported_helper_delegation_is_reported_as_unverified(tmp_path: Path) -> None:
    generator = tmp_path / "H.py"
    generator.write_text(
        """from testgen.data.test_chunk import TestChunk
from testgen.priv.registry import add_priv_test_generator
from shared import generate_h_suite

@add_priv_test_generator("H", testcases_per_file=128)
def make_h(test_data) -> list[TestChunk]:
    return generate_h_suite(test_data)
""",
        encoding="utf-8",
    )
    findings: list[dict] = []

    result = consistency.scan_python_generator(generator, findings)
    consistency._validate_priv_generator_api(
        result,
        "H",
        findings,
        require_testchunk_api=True,
        require_auto_split=True,
        max_testcases_per_file=512,
    )

    assert {item["check"] for item in findings} == {
        "generator_testchunk_lifecycle_unverified"
    }
    assert all(item["severity"] == "warning" for item in findings)


def test_priv_testcase_limit_is_read_from_current_act4_source(tmp_path: Path) -> None:
    constants = tmp_path / "generators/testgen/src/testgen/constants.py"
    constants.parent.mkdir(parents=True)
    constants.write_text("TESTCASES_PER_PRIV_FILE = 96\n", encoding="utf-8")
    findings: list[dict] = []

    limit = consistency._read_priv_testcase_limit(
        tmp_path,
        findings,
        required=True,
    )

    assert limit == 96
    assert findings == []


def test_missing_priv_testcase_limit_is_an_error(tmp_path: Path) -> None:
    findings: list[dict] = []

    limit = consistency._read_priv_testcase_limit(
        tmp_path,
        findings,
        required=True,
    )

    assert limit is None
    assert [item["check"] for item in findings] == ["generator_auto_split_limit"]


def test_normative_metadata_cli_arguments(tmp_path: Path) -> None:
    metadata = tmp_path / "hypervisor.yaml"

    args = consistency.build_arg_parser().parse_args(
        [
            "--normative-metadata",
            str(metadata),
            "--require-norm-metadata",
        ]
    )

    assert args.normative_metadata == metadata
    assert args.require_norm_metadata is True
