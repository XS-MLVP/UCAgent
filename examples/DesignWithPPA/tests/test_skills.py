"""Focused DesignWithPPA workflow tests: skills."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _config,
    _rtl_rows,
    _write_json,
    _write_yaml,
)

import ast
import json
from pathlib import Path
import shlex
import shutil
from typing import Any
from design_with_ppa.contracts import sha256_file
from design_with_ppa.plugin import get_plugin
from ucagent.tools.skill import RunSkillScript
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)




def test_optional_skill_scripts_use_runtime_snapshot_and_remain_read_only(
    tmp_path: Path,
) -> None:
    """Plugin Skill scripts must audit resolved artifacts through RunSkillScript."""

    source = PLUGIN_SOURCE / "design_with_ppa" / "skills"
    destination = tmp_path / ".ucagent" / "skills" / "ext" / "design-with-ppa"
    shutil.copytree(source, destination)
    cfg = _config(iterations=5)
    save_runtime_config(
        str(tmp_path),
        cfg,
        runtime_config_keys=list(get_plugin().workflows[0].runtime_config_keys),
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    sidecar = tmp_path / "output" / "performance" / "results" / "latency.json"
    waveform = tmp_path / "output" / "performance" / "waves" / "latency.vcd"
    sidecar.parent.mkdir(parents=True)
    waveform.parent.mkdir(parents=True)
    _write_json(sidecar, {"schema_version": "1.0", "test_case": "tc::latency"})
    waveform.write_text("$timescale 1ns $end\n#0\n#1\n", encoding="ascii")
    _write_json(
        tmp_path / "output" / "performance" / "performance_manifest.json",
        {
            "schema_version": "1.0",
            "tests": [
                {
                    "test_case": "tc::latency",
                    "result_path": sidecar.relative_to(tmp_path).as_posix(),
                    "result_sha256": sha256_file(sidecar),
                    "waveform": {
                        "path": waveform.relative_to(tmp_path).as_posix(),
                        "sha256": sha256_file(waveform),
                        "format": "vcd",
                    },
                }
            ],
        },
    )
    _write_json(
        tmp_path / "output" / "reports" / "ppa" / "current.json",
        {
            "schema_version": "1.1",
            "report_id": "ppa-" + "1" * 32,
            "status": "success",
            "summary": {"area": {"total": 10.0}},
            "comparison": {"status": "not_requested"},
            "details": {"area_by_cell_type": {"BUF_X1": 4.0}},
            "hotspots": {"power_instances": []},
            "diagnostics": [],
        },
    )
    runner = RunSkillScript(workspace=str(tmp_path))

    rtl_result = json.loads(
        runner._run(
            [["ext/design-with-ppa/rtl-tdd-backend", "summarize_rtl.py", ""]]
        )
    )
    performance_result = json.loads(
        runner._run(
            [
                [
                    "ext/design-with-ppa/performance-tc-scaffold",
                    "audit_performance_artifacts.py",
                    "",
                ]
            ]
        )
    )
    ppa_result = json.loads(
        runner._run(
            [["ext/design-with-ppa/ppa-iteration-analysis", "summarize_ppa.py", ""]]
        )
    )

    assert rtl_result["status"] == "ready_for_check"
    assert rtl_result["rtl_sources"] == _rtl_rows(tmp_path)
    assert rtl_result["resolved_optimization_minimum"] == 5
    assert rtl_result["resolved_optimization_maximum"] == 1000
    assert rtl_result["no_improvement_patience"] == 3
    assert performance_result["status"] == "consistent"
    assert performance_result["test_count"] == 1
    assert ppa_result["status"] == "success"
    assert ppa_result["area_hotspots"] == [
        {"area": 4.0, "cell_type": "BUF_X1"}
    ]
    assert ppa_result["resolved_optimization_minimum"] == 5
    assert ppa_result["resolved_optimization_maximum"] == 1000
    assert ppa_result["no_improvement_patience"] == 3
    assert not (tmp_path / ".ucagent" / "design_with_ppa").exists()




def test_structured_authoring_skills_generate_only_declared_artifacts(
    tmp_path: Path,
) -> None:
    """Structured Skills must preserve semantic ownership and current-batch scope."""

    source = PLUGIN_SOURCE / "design_with_ppa" / "skills"
    destination = tmp_path / ".ucagent" / "skills" / "ext" / "design-with-ppa"
    shutil.copytree(source, destination)
    save_runtime_config(str(tmp_path), _config())
    output = tmp_path / "output"
    tests = output / "tests"
    tests.mkdir(parents=True)
    contract = output / "dut_functions_and_checks.md"
    contract.write_text(
        "\n# Contract\n\n"
        "<FG-ARITH>\n\n<FC-ADD>\n\n<CK-NORMAL>\n\nNormal result.\n\n"
        "<CK-WRAP>\n\nWrapped result.\n\n<CK-NEGATIVE>\n\nNegative result.\n\n"
        "<FG-PPA>\n\n<FC-PPA-LATENCY>\n\n<CK-PPA-LATENCY>\n\nLatency.\n",
        encoding="utf-8",
    )
    coverage = tests / "dut_function_coverage_def.py"
    coverage.write_text(
        '"""Initial placeholder."""\n\n'
        "from toffee.funcov import CovGroup\n\n\n"
        "def get_coverage_groups(env):\n"
        '    group = CovGroup("FG-DESIGN")\n'
        "    group.add_watch_point(env, {\"CK-EXPECTED\": lambda _env: False}, "
        'name="FC-BEHAVIOR")\n'
        "    return [group]\n",
        encoding="utf-8",
    )
    runner = RunSkillScript(workspace=str(tmp_path))

    def run_skill(skill: str, script: str, args: str) -> dict[str, Any]:
        """Run one copied Skill script and decode its successful JSON result."""

        raw = runner._run([[f"ext/design-with-ppa/{skill}", script, args]])
        assert not raw.startswith("Command failed"), raw
        return json.loads(raw)

    structure = run_skill(
        "shared-ut-structure", "scaffold.py", "-MODE coverage-structure"
    )
    assert structure["checkpoint_count"] == 3
    coverage_text = coverage.read_text(encoding="utf-8")
    assert coverage_text.count("lambda _env: False") == 3
    assert "FG-PPA" not in coverage_text

    predicate_items = [
        {
            "checkpoint": "FG-ARITH/FC-ADD/CK-NORMAL",
            "expression": 'env.last_event == "response_observed" and env.last_event_data.get("result") == 3',
        },
        {
            "checkpoint": "FG-ARITH/FC-ADD/CK-WRAP",
            "expression": 'env.last_event == "response_observed" and env.last_event_data.get("result") == 0',
        },
    ]
    predicates = run_skill(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE coverage-predicates -ITEMS "
        + shlex.quote(json.dumps(predicate_items)),
    )
    assert predicates["updated"] == [item["checkpoint"] for item in predicate_items]
    coverage_text = coverage.read_text(encoding="utf-8")
    assert coverage_text.count("lambda _env: False") == 1
    assert "predicate_fg_arith_fc_add_ck_normal" in coverage_text
    ast.parse(coverage_text)

    template_paths = [
        "FG-ARITH/FC-ADD/CK-NORMAL",
        "FG-ARITH/FC-ADD/CK-WRAP",
    ]
    templates = run_skill(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE test-templates -ITEMS " + shlex.quote(json.dumps(template_paths)),
    )
    assert templates["created"] == template_paths
    template_file = tests / "test_dut_fg_arith.py"
    template_text = template_file.read_text(encoding="utf-8")
    assert template_text.count('assert False, "Not implemented"') == 2
    assert "CK-NEGATIVE" not in template_text
    repeated = run_skill(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE test-templates -ITEMS " + shlex.quote(json.dumps(template_paths)),
    )
    assert repeated["created"] == []
    assert repeated["unchanged"] == template_paths
    assert template_file.read_text(encoding="utf-8") == template_text

    spec = tmp_path / "dut" / "spec" / "interface.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Interface\n\nnormal result\nwrapped result\n", encoding="utf-8")
    map_relative = (
        "output/line_map/dut_spec_interface_md_line_func_map.txt"
    )
    map_items = [
        {
            "target": "IGNORE/FC-DOC/CK-HEADING",
            "ranges": [[1, 1]],
            "reason": "Document heading; it does not define DUT behavior.",
        },
        {
            "target": "FG-ARITH/FC-ADD/CK-NORMAL",
            "ranges": [[3, 3]],
        },
        {
            "target": "FG-ARITH/FC-ADD/CK-WRAP",
            "ranges": [[4, 4]],
        },
    ]
    mapped = run_skill(
        "spec-line-mapping",
        "write_line_map.py",
        "-SOURCE dut/spec/interface.md -START 1 -END 4 "
        f"-MAP-FILE {map_relative} -ITEMS "
        + shlex.quote(json.dumps(map_items)),
    )
    assert mapped["replaced_block"] == [1, 4]
    map_text = (tmp_path / map_relative).read_text(encoding="utf-8")
    assert "FG-ARITH/FC-ADD/CK-NORMAL: 3-3" in map_text
    assert "IGNORE/FC-DOC/CK-HEADING: 1-1 # Document heading" in map_text

    performance_contract = {
        "schema_version": "1.0",
        "dut": "dut",
        "top_module": "dut",
        "metrics": [
            {
                "id": "latency",
                "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_latency",
            },
            {
                "id": "throughput",
                "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_throughput",
            },
        ],
    }
    _write_yaml(output / "dut_performance_contract.yaml", performance_contract)
    performance = run_skill(
        "performance-tc-scaffold", "scaffold_performance_tests.py", ""
    )
    assert performance["status"] == "scaffolded"
    assert performance["test_count"] == 2
    performance_source = tests / "test_dut_performance.py"
    performance_text = performance_source.read_text(encoding="utf-8")
    assert performance_text.count("@pytest.mark.performance") == 2
    assert performance_text.count("def test_dut_performance_") == 2
    assert performance_text.count("write_performance_result(") == 2
    ast.parse(performance_text)




def test_structured_authoring_skills_reject_unsafe_or_stale_inputs(
    tmp_path: Path,
) -> None:
    """Structured Skills must reject destructive, stale, and out-of-scope input."""

    source = PLUGIN_SOURCE / "design_with_ppa" / "skills"
    destination = tmp_path / ".ucagent" / "skills" / "ext" / "design-with-ppa"
    shutil.copytree(source, destination)
    save_runtime_config(str(tmp_path), _config())
    output = tmp_path / "output"
    tests = output / "tests"
    tests.mkdir(parents=True)
    contract = output / "dut_functions_and_checks.md"
    contract.write_text(
        "\n# Contract\n\n"
        "<FG-ARITH>\n\n<FC-ADD>\n\n<CK-NORMAL>\n\nNormal result.\n\n"
        "<CK-WRAP>\n\nWrapped result.\n",
        encoding="utf-8",
    )
    runner = RunSkillScript(workspace=str(tmp_path))

    def invoke(skill: str, script: str, args: str) -> str:
        """Run one copied Skill script and return its complete bounded result."""

        return runner._run([[f"ext/design-with-ppa/{skill}", script, args]])

    def assert_failed(result: str, expected: str) -> None:
        """Require a script failure to include its actionable boundary reason."""

        assert result.startswith("Command failed"), result
        assert expected in result, result

    coverage = tests / "dut_function_coverage_def.py"
    implemented_coverage = (
        '\"\"\"Implemented coverage.\"\"\"\n\n'
        "from toffee.funcov import CovGroup\n\n\n"
        "def observed(env):\n"
        "    \"\"\"Return a real observation.\"\"\"\n\n"
        "    return env.last_event == 'response_observed'\n\n\n"
        "def get_coverage_groups(env):\n"
        '    group = CovGroup("FG-ARITH")\n'
        "    group.add_watch_point(\n"
        "        env,\n"
        '        {"CK-NORMAL": observed, "CK-WRAP": lambda _env: False},\n'
        '        name="FC-ADD",\n'
        "    )\n"
        "    return [group]\n"
    )
    coverage.write_text(implemented_coverage, encoding="utf-8")
    result = invoke(
        "shared-ut-structure", "scaffold.py", "-MODE coverage-structure"
    )
    assert_failed(result, "refusing to replace")
    assert coverage.read_text(encoding="utf-8") == implemented_coverage

    malformed_coverage = "def get_coverage_groups(:\n"
    coverage.write_text(malformed_coverage, encoding="utf-8")
    result = invoke(
        "shared-ut-structure", "scaffold.py", "-MODE coverage-structure"
    )
    assert_failed(result, "not a safe placeholder structure")
    assert coverage.read_text(encoding="utf-8") == malformed_coverage

    coverage.unlink()
    success = invoke(
        "shared-ut-structure", "scaffold.py", "-MODE coverage-structure"
    )
    assert not success.startswith("Command failed"), success
    placeholder_coverage = coverage.read_text(encoding="utf-8")
    unknown = [{"checkpoint": "FG-ARITH/FC-ADD/CK-UNKNOWN", "expression": "env.ready"}]
    result = invoke(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE coverage-predicates -ITEMS "
        + shlex.quote(json.dumps(unknown)),
    )
    assert_failed(result, "unknown functional checkpoint")
    assert coverage.read_text(encoding="utf-8") == placeholder_coverage

    no_env = [{"checkpoint": "FG-ARITH/FC-ADD/CK-NORMAL", "expression": "1 == 1"}]
    result = invoke(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE coverage-predicates -ITEMS "
        + shlex.quote(json.dumps(no_env)),
    )
    assert_failed(result, "must depend on the public env value")
    assert coverage.read_text(encoding="utf-8") == placeholder_coverage

    normal = [
        {
            "checkpoint": "FG-ARITH/FC-ADD/CK-NORMAL",
            "expression": 'env.last_event == "response_observed"',
        }
    ]
    success = invoke(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE coverage-predicates -ITEMS "
        + shlex.quote(json.dumps(normal)),
    )
    assert not success.startswith("Command failed"), success
    implemented_source = coverage.read_text(encoding="utf-8")
    changed = [
        {
            "checkpoint": "FG-ARITH/FC-ADD/CK-NORMAL",
            "expression": 'env.last_event == "different_event"',
        }
    ]
    result = invoke(
        "shared-ut-structure",
        "scaffold.py",
        "-MODE coverage-predicates -ITEMS "
        + shlex.quote(json.dumps(changed)),
    )
    assert_failed(result, "already implemented with different semantics")
    assert coverage.read_text(encoding="utf-8") == implemented_source

    spec = tmp_path / "dut" / "spec" / "interface.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("heading\nnormal\nwrap\ntrailing\n", encoding="utf-8")
    map_relative = "output/line_map/dut_spec_interface_md_line_func_map.txt"
    valid_items = [
        {"target": "FG-ARITH/FC-ADD/CK-NORMAL", "ranges": [[1, 2]]},
        {"target": "FG-ARITH/FC-ADD/CK-WRAP", "ranges": [[3, 4]]},
    ]
    result = invoke(
        "spec-line-mapping",
        "write_line_map.py",
        "-SOURCE ../outside.md -START 1 -END 4 "
        f"-MAP-FILE {map_relative} -ITEMS "
        + shlex.quote(json.dumps(valid_items)),
    )
    assert_failed(result, "escapes the permitted boundary")

    missing_items = [
        {"target": "FG-ARITH/FC-ADD/CK-NORMAL", "ranges": [[1, 2]]}
    ]
    result = invoke(
        "spec-line-mapping",
        "write_line_map.py",
        "-SOURCE dut/spec/interface.md -START 1 -END 4 "
        f"-MAP-FILE {map_relative} -ITEMS "
        + shlex.quote(json.dumps(missing_items)),
    )
    assert_failed(result, "do not cover current nonblank physical lines")

    result = invoke(
        "spec-line-mapping",
        "write_line_map.py",
        "-SOURCE dut/spec/interface.md -START 1 -END 4 "
        "-MAP-FILE output/line_map/wrong.txt -ITEMS "
        + shlex.quote(json.dumps(valid_items)),
    )
    assert_failed(result, "must be the canonical path")

    map_file = tmp_path / map_relative
    map_file.parent.mkdir(parents=True)
    cross_block = "FG-ARITH/FC-ADD/CK-NORMAL: 1-3\n"
    map_file.write_text(cross_block, encoding="utf-8")
    second_block = [
        {"target": "FG-ARITH/FC-ADD/CK-WRAP", "ranges": [[3, 4]]}
    ]
    result = invoke(
        "spec-line-mapping",
        "write_line_map.py",
        "-SOURCE dut/spec/interface.md -START 3 -END 4 "
        f"-MAP-FILE {map_relative} -ITEMS "
        + shlex.quote(json.dumps(second_block)),
    )
    assert_failed(result, "partially crosses current block")
    assert map_file.read_text(encoding="utf-8") == cross_block

    performance_contract = {
        "schema_version": "1.0",
        "dut": "dut",
        "top_module": "dut",
        "metrics": [
            {
                "id": "latency",
                "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_latency",
            },
            {
                "id": "throughput",
                "measurement_test": "output/tests/test_dut_performance.py::test_dut_performance_throughput",
            },
        ],
    }
    _write_yaml(output / "dut_performance_contract.yaml", performance_contract)
    success = invoke(
        "performance-tc-scaffold", "scaffold_performance_tests.py", ""
    )
    assert not success.startswith("Command failed"), success
    performance_file = tests / "test_dut_performance.py"
    implemented_performance = performance_file.read_text(encoding="utf-8").replace(
        '    assert False, "Not implemented"', "    assert True"
    )
    performance_file.write_text(implemented_performance, encoding="utf-8")
    result = invoke(
        "performance-tc-scaffold", "scaffold_performance_tests.py", ""
    )
    assert not result.startswith("Command failed"), result
    assert json.loads(result)["status"] == "already_implemented"
    assert performance_file.read_text(encoding="utf-8") == implemented_performance

    performance_file.write_text(
        implemented_performance
        + "\n\ndef test_dut_performance_stale(env, request):\n"
        '    \"\"\"Undeclared stale node.\"\"\"\n\n'
        "    assert True\n",
        encoding="utf-8",
    )
    stale_source = performance_file.read_text(encoding="utf-8")
    result = invoke(
        "performance-tc-scaffold", "scaffold_performance_tests.py", ""
    )
    assert_failed(result, "not declared by the current contract")
    assert performance_file.read_text(encoding="utf-8") == stale_source
