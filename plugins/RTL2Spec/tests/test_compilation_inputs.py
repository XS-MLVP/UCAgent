"""Verify explicit compilation inputs, source mapping and fail-closed HDL parsing."""

import json

import pytest

from rtl2spec.generic_evidence import generate_generic, generic_input_preflight, parse_generic_ports, validate_generic_evidence


@pytest.fixture
def configured_input(tmp_path):
    """Prepare ordered files, an included macro, and a dependent parameter override."""
    source = tmp_path / "inputs/Block"
    (source / "include").mkdir(parents=True)
    (source / "config.vh").write_text("`define ENABLE\n")
    (source / "include/width.vh").write_text("`define WIDTH `BASE\n")
    (source / "top.sv").write_text('''`include "width.vh"
module Block #(parameter W=4, parameter SIZE=W*2)(
 input [`WIDTH-1:0] data,
`ifdef ENABLE
 output [SIZE-1:0] value
`else
 output disabled
`endif
);
endmodule
''')
    config = {"files": ["config.vh", "top.sv"], "include_dirs": ["include"],
              "defines": {"BASE": "16"}, "parameters": {"W": 5}}
    (source / "rtl2spec.json").write_text(json.dumps(config))
    return tmp_path, source, config


def test_compilation_configuration_controls_ports_and_source_map(configured_input):
    """Resolve the actual selected ports, derived widths and original declaration lines."""
    root, source, config = configured_input
    facts = generic_input_preflight(root, "Block")
    assert [(p["name"], p["width"]) for p in facts["ports"]] == [("data", 16), ("value", 10)]
    assert facts["compilation"] == config
    line = next(i for i, text in enumerate(facts["preprocessed"].splitlines()) if "output [SIZE" in text)
    assert facts["source_map"][line] == {"path": "inputs/Block/top.sv", "line": 5}
    assert len(facts["source_map"]) == len(facts["preprocessed"].splitlines())
    generate_generic(root, "Block", "Configured")
    manifest, ports = validate_generic_evidence(root, "Block", "Configured")
    assert manifest["compilation"] == config and ports == facts["ports"]
    assert (root / "outputs/evidence/Block.sv").read_bytes() == (source / "top.sv").read_bytes()


def test_explicit_file_order_and_top_selection(configured_input):
    """Unselected variants are excluded; preceding compilation files define active macros."""
    root, source, config = configured_input
    (source / "unused.sv").write_text("module Block(input wrong); endmodule\n")
    config["files"] = ["top.sv", "config.vh"]
    (source / "rtl2spec.json").write_text(json.dumps(config))
    assert [p["name"] for p in generic_input_preflight(root, "Block")["ports"]] == ["data", "disabled"]


@pytest.mark.parametrize("changed", ["config", "include", "view", "map"])
def test_compilation_changes_invalidate_evidence(configured_input, changed):
    """Neither configuration changes nor edited preprocessing artifacts retain acceptance."""
    root, source, config = configured_input
    generate_generic(root, "Block", "Configured")
    if changed == "config":
        config["parameters"]["W"] = 6
        (source / "rtl2spec.json").write_text(json.dumps(config))
    elif changed == "include":
        (source / "include/width.vh").write_text("`define WIDTH 7\n")
    elif changed == "view":
        (root / "outputs/evidence/Block.preprocessed.sv").write_text("module Block; endmodule\n")
    else:
        (root / "outputs/evidence/source_map.json").write_text("[]\n")
    with pytest.raises(ValueError, match="changed"):
        validate_generic_evidence(root, "Block", "Configured")


@pytest.mark.parametrize("key,value", [
    ("files", []), ("files", ["../top.sv"]), ("files", ["/tmp/top.sv"]),
    ("files", ["top.sv", "top.sv"]), ("files", ["missing.sv"]),
    ("include_dirs", ["missing"]), ("defines", {"X": 1}), ("defines", {"X": "1\n`define BAD"}),
    ("parameters", {"W": True}), ("parameters", {"UNKNOWN": 2}),
    ("unknown_field", []),
])
def test_invalid_compilation_config_is_rejected_before_capture(configured_input, key, value):
    """Reject unknown/invalid values without producing a plausible port inventory."""
    root, source, config = configured_input
    config[key] = value
    (source / "rtl2spec.json").write_text(json.dumps(config))
    with pytest.raises(ValueError):
        generate_generic(root, "Block", "Configured")
    assert not (root / "outputs").exists()


@pytest.mark.parametrize("text,error", [
    ('`include "absent.vh"\nmodule Block; endmodule\n', "not found"),
    ('`include "../escape.vh"\nmodule Block; endmodule\n', "invalid include"),
    ('`define F(x) x\nmodule Block; endmodule\n', "function macros"),
    ('module Block(input [`MISSING-1:0] data); endmodule\n', "unresolved macro"),
    ('`define R `R\nmodule Block(input [`R:0] data); endmodule\n', "recursive"),
    ('module Block(bus.modport p); endmodule\n', "SystemVerilog"),
])
def test_unsupported_hdl_fails_with_a_concrete_diagnostic(configured_input, text, error):
    """Unsupported preprocessing and interfaces must fail rather than sign guessed facts."""
    root, source, config = configured_input
    config["parameters"] = {}
    (source / "rtl2spec.json").write_text(json.dumps(config))
    (source / "top.sv").write_text(text)
    with pytest.raises(ValueError, match=error):
        generic_input_preflight(root, "Block")


def test_include_cycle_and_symlink_are_rejected(configured_input):
    """Nested includes cannot recurse forever or escape through a symlink."""
    root, source, _ = configured_input
    (source / "include/width.vh").write_text('`include "width.vh"\n')
    with pytest.raises(ValueError, match="cycle"):
        generic_input_preflight(root, "Block")
    (source / "include/width.vh").unlink()
    external = root / "external.vh"
    external.write_text("`define WIDTH 3\n")
    (source / "include/width.vh").symlink_to(external)
    with pytest.raises(ValueError, match="symlinks"):
        generic_input_preflight(root, "Block")


@pytest.mark.parametrize("expression,width", [
    ("8'H10", 16), ("4'h1f", 15), ("'d12", 12),
    ("$clog2(17)", 5), ("8 + (-5 / 2)", 6), ("8 + (-5 % 2)", 7),
])
def test_width_expressions_preserve_hdl_integer_rules(expression, width):
    """Sized literals truncate and signed division/remainder round toward zero."""
    ports = parse_generic_ports(f"module Block(input [({expression})-1:0] data); endmodule", "Block")
    assert ports[0]["width"] == width


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "module Block(input logic [1:0][7:0] data); endmodule",
            ("data", "[1:0][7:0]", "", 16),
        ),
        (
            "module Block(input logic [7:0] data [0:3]); endmodule",
            ("data", "[7:0]", "[0:3]", 8),
        ),
        (
            "package p; typedef logic [7:0] data_t; endpackage\n"
            "module Block(input p::data_t data); endmodule",
            ("data", "[7:0]", "", 8),
        ),
    ],
)
def test_systemverilog_port_shapes_are_preserved(source, expected):
    """Accept common packed, unpacked and package-scoped SystemVerilog port forms."""
    port = parse_generic_ports(source, "Block")[0]
    assert (port["name"], port["range"], port["unpacked_range"], port["width"]) == expected


@pytest.mark.parametrize("source,error", [
    ("module Block(input [True:0] data); endmodule", "undeclared identifier"),
    ("module Block(input missing_pkg::data_t data); endmodule", "unknown class or package"),
    ("module Block(a); input a; output [3:0] a; endmodule", "redefinition"),
])
def test_ambiguous_or_non_hdl_declarations_fail(source, error):
    """Do not silently accept Python constants or overwrite ambiguous declarations."""
    with pytest.raises(ValueError, match=error):
        parse_generic_ports(source, "Block")
