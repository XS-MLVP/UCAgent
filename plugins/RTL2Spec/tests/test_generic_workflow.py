"""Exercise the generic RTL input workflow and its source evidence contract."""

import json
from pathlib import Path

import pytest
from conftest import complete_review

from rtl2spec.documents import METADATA_RE, artifact_paths
from rtl2spec.generic_evidence import parse_generic_ports
from rtl2spec.plugin import get_plugin
from rtl2spec.tools import RTL2SpecCommand


RTL = """// Synthetic test input.
module GenericBlock #(parameter WIDTH=8) (
  input logic clock,
  input logic reset,
  input logic [WIDTH-1:0] io_data,
  output logic [WIDTH-1:0] io_result
);
assign io_result = io_data;
endmodule
"""


@pytest.fixture
def generic_workspace(tmp_path: Path) -> Path:
    """Create a generic workspace with one top RTL and one related source file."""

    root = tmp_path / "generic workspace"
    source = root / "inputs/GenericBlock"
    source.mkdir(parents=True)
    (source / "GenericBlock.sv").write_text(RTL, encoding="utf-8")
    (source / "helper.sv").write_text(
        "module helper(input wire clock); endmodule\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def generic_command(generic_workspace: Path) -> RTL2SpecCommand:
    """Bind the command to the generic workflow's resolved write policy."""

    return RTL2SpecCommand(
        workspace=str(generic_workspace),
        write_dirs=["outputs"],
        un_write_dirs=["inputs", ".ucagent"],
    )


def write_generic_documents(root: Path, output_dir: str = "outputs") -> None:
    """Write the maintained complete template fixture for the generic module."""

    design, report = artifact_paths(root, "GenericBlock", output_dir)
    design.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    text = (Path(__file__).parent / "fixtures/design_document.md").read_text(
        encoding="utf-8"
    )
    text = text.replace("Sbuffer", "GenericBlock").replace("outputs/evidence/", f"{output_dir}/evidence/")
    design.write_text(text, encoding="utf-8")
    report.write_text(
        "# Review\n\nThe supplied RTL was captured; no external verification tool was run.\n",
        encoding="utf-8",
    )


def capture_generic(generic_command: RTL2SpecCommand, root: Path) -> None:
    """Capture evidence and synchronize a complete generic document fixture."""

    for action, kwargs in (
        ("generic_preflight", {}),
        ("generic_evidence", {}),
        ("generic_related_sources", {"related_files": ["helper.sv"]}),
    ):
        result = generic_command._run(
            action, "GenericBlock", config="Generic", **kwargs
        )
        assert result["ok"], result
    write_generic_documents(root, generic_command.output_dir)
    assert generic_command._run("generic_metadata", "GenericBlock", config="Generic")["ok"]
    complete_review(root, "GenericBlock", "Generic", generic=True, output_dir=generic_command.output_dir)
    for action in ("generic_lint", "generic_finalize"):
        result = generic_command._run(action, "GenericBlock", config="Generic")
        assert result["ok"], result


def test_generic_workflow_is_registered() -> None:
    """Expose the generic workflow and its dedicated checker through the plugin."""

    plugin = get_plugin()
    assert [workflow.name for workflow in plugin.workflows] == [
        "xiangshan-design-document",
        "generic-design-document",
    ]
    assert plugin.workflows[1].config_file.name == "generic-design-document.yaml"
    assert any(
        checker.__name__ == "RTL2SpecGenericArtifactsChecker"
        for checker in plugin.checkers
    )


def test_generic_output_directory_preserves_previous_run(generic_workspace, generic_command):
    """A second generic run keeps its related evidence and documents in its own directory."""
    capture_generic(generic_command, generic_workspace)
    original = {
        path: path.read_bytes()
        for path in (generic_workspace / "outputs").rglob("*") if path.is_file()
    }
    output_dir = "runs/second output"
    generic_command.output_dir = output_dir
    generic_command.write_dirs = [output_dir]
    capture_generic(generic_command, generic_workspace)
    manifest = json.loads(
        (generic_workspace / output_dir / "evidence/manifest.json").read_text()
    )
    assert manifest["related_sources"][0]["module"] == "helper.sv"
    assert all(path.read_bytes() == data for path, data in original.items())
    generic_command.un_write_dirs.append(f"{output_dir}/evidence/manifest.json")
    result = generic_command._run(
        "generic_related_sources", "GenericBlock", config="Generic", related_files=["helper.sv"]
    )
    assert result["error_code"] == "WRITE_POLICY_DENIED"


def test_generic_workflow_config_contains_generic_actions() -> None:
    """Keep the selected workflow contract independent from XiangShan actions."""

    import yaml

    config = yaml.safe_load(
        get_plugin().workflows[1].config_file.read_text(encoding="utf-8")
    )
    assert config["template_overwrite"]["GENERIC_CONFIG"] == "$(RTL2SPEC_CONFIG: Generic)"
    assert config["stage"][0]["checker"][0]["clss"] == "RTL2SpecGenericArtifactsChecker"
    joined = "\n".join(config["mission"]["prompt"]["system"].splitlines())
    assert "generic_evidence" in joined
    assert "third_party/XiangShan" not in joined
    assert len(config["stage"]) == 4
    assert config["stage"][2]["name"] == "review_source_semantics"
    assert config["stage"][3]["reference_files"] == ["Guide_Doc/finalization-guide.md"]



def test_generic_workflow_preserves_output_lifecycle_guard(tmp_path: Path) -> None:
    """The generic workflow applies the same user-controlled archive boundary."""

    old = tmp_path / "outputs/old.md"
    old.parent.mkdir(parents=True)
    old.write_text("old\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="package/archive"):
        get_plugin().workflows[1].template_context_factory(
            None,
            {
                "WORKSPACE": str(tmp_path),
                "DUT": "GenericBlock",
                "OUT": "outputs",
            },
        )


def test_generic_capture_signs_input_and_ports(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """Capture a non-XiangShan module without requiring an HDL build tool."""

    result = generic_command._run("generic_evidence", "GenericBlock", config="Generic")
    assert result["ok"], result
    manifest = json.loads(
        (generic_workspace / "outputs/evidence/manifest.json").read_text()
    )
    assert manifest["schema_version"] == 2
    assert manifest["generation_status"] == "provided"
    assert manifest["rtl_source"] == "inputs/GenericBlock/GenericBlock.sv"
    assert manifest["source_baseline"] == manifest["source_state"]["digest"]
    assert manifest["port_count"] == 4
    assert (generic_workspace / "outputs/evidence/ports.csv").is_file()


def test_generic_related_source_is_hashed_and_reported(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """Record an input file by relative path and retain its signed hash."""

    assert generic_command._run(
        "generic_evidence", "GenericBlock", config="Generic"
    )["ok"]
    result = generic_command._run(
        "generic_related_sources",
        "GenericBlock",
        config="Generic",
        related_files=["helper.sv"],
    )
    assert result["ok"], result
    manifest = json.loads(
        (generic_workspace / "outputs/evidence/manifest.json").read_text()
    )
    record = manifest["related_sources"][0]
    assert record["module"] == "helper.sv"
    assert record["path"] == "inputs/GenericBlock/helper.sv"
    assert record["evidence_id"].startswith("E-REL-")


def test_generic_related_source_rejects_path_escape(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """Reject a related source path that leaves the module input directory."""

    result = generic_command._run(
        "generic_related_sources",
        "GenericBlock",
        config="Generic",
        related_files=["../outside.sv"],
    )
    assert result["error_code"] == "INVALID_ARGUMENTS"


def test_generic_document_metadata_uses_source_baseline(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """The shared template receives generic source metadata instead of XiangShan fields."""

    capture_generic(generic_command, generic_workspace)
    design = artifact_paths(generic_workspace, "GenericBlock")[0]
    marker = json.loads(METADATA_RE.findall(design.read_text())[0])
    assert "source_baseline" in marker
    assert "xiangshan_commit" not in marker
    assert "RTL/source 基线" in design.read_text()


def test_generic_lint_accepts_arbitrary_port_names_mapped_in_appendix_a(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """Appendix A supplies coverage when the body uses logical aliases."""

    source = generic_workspace / "inputs/GenericBlock/GenericBlock.sv"
    source.write_text(
        RTL.replace("io_data", "data_i").replace("io_result", "data_o"),
        encoding="utf-8",
    )
    for action, kwargs in (
        ("generic_preflight", {}),
        ("generic_evidence", {}),
        ("generic_related_sources", {"related_files": ["helper.sv"]}),
    ):
        result = generic_command._run(
            action, "GenericBlock", config="Generic", **kwargs
        )
        assert result["ok"], result
    write_generic_documents(generic_workspace)
    design, _ = artifact_paths(generic_workspace, "GenericBlock")
    design.write_text(
        design.read_text()
        .replace("io_data", "data_i")
        .replace("io_result", "data_o"),
        encoding="utf-8",
    )
    assert generic_command._run(
        "generic_metadata", "GenericBlock", config="Generic"
    )["ok"]
    complete_review(generic_workspace, "GenericBlock", "Generic", generic=True)
    result = generic_command._run("generic_lint", "GenericBlock", config="Generic")
    assert result["ok"], result
    assert json.loads(result["stdout"])["warnings"] == []


def test_generic_source_change_invalidates_existing_evidence(
    generic_workspace: Path, generic_command: RTL2SpecCommand
) -> None:
    """A changed input source cannot silently pass a later document check."""

    capture_generic(generic_command, generic_workspace)
    helper = generic_workspace / "inputs/GenericBlock/helper.sv"
    helper.write_text(helper.read_text() + "// changed\n", encoding="utf-8")
    result = generic_command._run("generic_lint", "GenericBlock", config="Generic")
    assert not result["ok"]
    assert "generic input source changed" in result["stdout"]


def test_generic_preflight_rejects_ambiguous_top(tmp_path: Path) -> None:
    """Two files declaring the same top module fail before evidence is published."""

    source = tmp_path / "inputs/Duplicate"
    source.mkdir(parents=True)
    for name in ("a.sv", "b.sv"):
        (source / name).write_text("module Duplicate(input clock); endmodule\n")
    command = RTL2SpecCommand(
        workspace=str(tmp_path), write_dirs=["evidence"], un_write_dirs=["inputs"]
    )
    result = command._run("generic_preflight", "Duplicate", config="Generic")
    assert not result["ok"]
    assert "ambiguous" in result["stdout"]


@pytest.mark.parametrize(
    "text,expected_widths",
    [
        (
            "module X(clk, data, result); input clk; input [7:0] data; output [7:0] result; endmodule",
            [1, 8, 8],
        ),
        (
            "module X #(parameter W=4) (input [W-1:0] data, output result); endmodule",
            [4, 1],
        ),
    ],
)
def test_generic_port_parser_supports_common_verilog_forms(
    text: str, expected_widths: list[int]
) -> None:
    """Accept ANSI, non-ANSI, and numeric-parameter port declarations."""

    assert [port["width"] for port in parse_generic_ports(text, "X")] == expected_widths


def test_generic_port_parser_accepts_a_zero_port_module() -> None:
    """Permit a legal module with no external interface."""

    assert parse_generic_ports("module X; endmodule", "X") == []


@pytest.mark.parametrize("enabled", [False, True])
def test_generic_ports_follow_local_conditional_configuration(enabled: bool) -> None:
    """Optional ports follow source-local defines without retaining disabled branches."""

    text = ("`define HAS_BUS\n" if enabled else "") + """
module X(input clk,
`ifdef HAS_BUS
    input [31:0] data,
`else
    input fallback,
`endif
    output done);
endmodule
"""
    ports = parse_generic_ports(text, "X")
    assert [(port["name"], port["width"]) for port in ports] == [
        ("clk", 1), ("data", 32) if enabled else ("fallback", 1), ("done", 1)
    ]


def test_generic_ports_track_nested_defines_undef_and_elsif() -> None:
    """Inactive defines do not leak and nested conditionals retain the chosen branch."""

    text = """
`define OUTER
`define REMOVED
`undef REMOVED
`ifdef ABSENT
    `define LEAK
    `undef OUTER
`endif
module X(input clk,
`ifdef OUTER
    `ifndef REMOVED
        `ifdef LEAK
            output wrong,
        `elsif OUTER
            output [7:0] selected,
        `else
            output other,
        `endif
    `endif
`endif
    input rst_n);
endmodule
"""
    assert [(p["name"], p["width"]) for p in parse_generic_ports(text, "X")] == [
        ("clk", 1), ("selected", 8), ("rst_n", 1)
    ]


def test_generic_non_ansi_ports_follow_conditional_declarations() -> None:
    """Classic port declarations use only the active direction and width."""

    text = """
`define WIDE
module X(clk, data);
input clk;
`ifdef WIDE
output [15:0] data;
`else
input data;
`endif
endmodule
"""
    assert [(p["name"], p["direction"], p["width"]) for p in parse_generic_ports(text, "X")] == [
        ("clk", "input", 1), ("data", "output", 16)
    ]


@pytest.mark.parametrize(
    "directives,error",
    [
        ("`else\n", "without a matching"),
        ("`elsif FLAG\n", "without a matching"),
        ("`endif\n", "without a matching"),
        ("`ifdef FLAG\n", "unterminated"),
        ("`ifdef FLAG\n`else\n`else\n`endif\n", "duplicate"),
        ("`ifdef FLAG\n`else\n`elsif OTHER\n`endif\n", "after `else"),
        ("`ifdef\n`endif\n", "requires a macro name"),
        ("`ifndef\n`endif\n", "requires a macro name"),
        ("`define\n", "requires a macro name"),
        ("`undef\n", "requires a macro name"),
        ("`ifdef FLAG\n`else FLAG\n`endif\n", "unexpected arguments"),
    ],
)
def test_generic_ports_reject_malformed_conditionals(directives: str, error: str) -> None:
    """Malformed directives must fail instead of signing an inferred port set."""

    with pytest.raises(ValueError, match=error):
        parse_generic_ports(directives + "module X(input clk); endmodule\n", "X")
