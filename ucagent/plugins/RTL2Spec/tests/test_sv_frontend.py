"""Exercise typed HDL ports and source-backed facts without accepting guessed semantics."""

import copy

import pytest

from rtl2spec import sv_frontend
from rtl2spec.documents import ARTIFACT_TEXT, generate_port_scaffold, port_locations
from rtl2spec.evidence import digest
from rtl2spec.generic_evidence import generate_generic, validate_generic_evidence
from rtl2spec.review import validate_behavior_facts
from rtl2spec.validation import validate_ports
from rtl2spec.verilog import VerilogPreprocessor


def test_missing_frontend_has_install_diagnostic(monkeypatch):
    """Missing optional plugin dependencies must fail before returning any HDL facts."""
    original = sv_frontend.importlib.import_module

    def missing(name):
        """Model an environment without the plugin's HDL frontend."""
        if name == "pyslang":
            raise ImportError("not installed")
        return original(name)

    monkeypatch.setattr(sv_frontend.importlib, "import_module", missing)
    with pytest.raises(ValueError, match="install the RTL2Spec plugin dependencies"):
        sv_frontend.typed_ports("module Block(input a); endmodule", "Block")


@pytest.mark.parametrize("source", ["", "module Other; endmodule", "module Block(input ; endmodule"])
def test_empty_missing_or_malformed_top_is_rejected(source):
    """No valid selected module means no usable typed port inventory."""
    with pytest.raises(ValueError):
        sv_frontend.typed_ports(source, "Block")


def test_package_struct_enum_and_parameter_types_are_elaborated():
    """Derive integral widths from package types and HDL parameter expressions."""
    source = """package p;
typedef struct packed {logic valid; logic [7:0] data;} payload_t;
typedef enum logic [2:0] {Idle, Busy} state_t;
endpackage
module Block import p::*; #(parameter W=4, parameter N=W*2)(
 input payload_t payload[0:3], input state_t state, output logic[N-1:0] result
); endmodule
"""
    ports = sv_frontend.typed_ports(source, "Block", {"W": 5})
    assert [(p["name"], p["width"], p["unpacked_range"]) for p in ports] == [
        ("payload", 9, "[0:3]"), ("state", 3, ""), ("result", 10, ""),
    ]
    assert sv_frontend.port_shape(ports[0]) == "I/9[0:3]"
    assert ports[0]["signedness"] == "unsigned"
    assert "struct packed" in ports[0]["canonical_type"]
    assert ports[0]["packed_dimensions"] == ""
    assert ports[0]["unpacked_dimensions"] == "[0:3]"


def test_signedness_and_packed_layout_are_preserved():
    """Elaboration retains signedness and every packed dimension separately from total width."""
    ports = sv_frontend.typed_ports(
        "package p; typedef logic signed [7:0] signed_t; endpackage\n"
        "module Block import p::*; (input signed_t signed_data, input logic [3:0][7:0] matrix); endmodule",
        "Block",
    )
    assert ports[0]["signedness"] == "signed"
    assert "logic signed[7:0]" in ports[0]["canonical_type"]
    assert ports[0]["packed_dimensions"] == "[7:0]"
    assert ports[1]["packed_dimensions"] == "[3:0][7:0]"
    assert ports[1]["width"] == 32


def test_nonansi_ports_ignore_function_local_declarations():
    """Function arguments are separate scopes and cannot redefine module port widths."""
    ports = sv_frontend.typed_ports("""module Block(a,b);
input [7:0] a; output [3:0] b;
function automatic f; input a; f=a; endfunction
endmodule""", "Block")
    assert [(p["name"], p["width"]) for p in ports] == [("a", 8), ("b", 4)]


def test_generic_port_locations_use_ast_symbol_ranges(tmp_path):
    """A same-named function argument cannot replace the module port source range."""
    source = tmp_path / "inputs/Block"
    source.mkdir(parents=True)
    (source / "top.v").write_text(
        "module Block(a,b);\ninput [7:0] a; output b;\n"
        "function automatic f; input a; f=a; endfunction\nendmodule\n"
    )
    generate_generic(tmp_path, "Block", "Generic")
    _, ports = validate_generic_evidence(tmp_path, "Block", "Generic")
    locations = port_locations(tmp_path, "Block", ports, generic=True)
    assert ("inputs/Block/top.v", 1) in locations["a"]
    assert ("inputs/Block/top.v", 2) in locations["a"]
    assert all(line != 3 for _, line in locations["a"])


def test_default_nettype_is_preserved_for_elaboration():
    """A no-implicit-net compilation must reject undeclared names rather than infer wires."""
    source = "`default_nettype none\nmodule Block(output logic q); assign undeclared = 1'b0; assign q = undeclared; endmodule"
    from rtl2spec.generic_evidence import parse_generic_ports

    with pytest.raises(ValueError, match="undeclared identifier"):
        parse_generic_ports(source, "Block")
    assert parse_generic_ports(source.replace("none", "wire"), "Block")[0]["width"] == 1


def test_only_active_compilation_directives_reach_frontend():
    """Retain active timescale/nettype directives and suppress inactive conditional directives."""
    source = """`timescale 1ns/1ps
`ifdef ENABLE
`default_nettype none
`else
`default_nettype wire
`endif
module Block; endmodule
"""
    text, source_map = VerilogPreprocessor(defines={"ENABLE": ""}).process(source)
    assert "`timescale 1ns/1ps" in text and "`default_nettype none" in text
    assert "`default_nettype wire" not in text
    assert len(text.splitlines()) == len(source_map) == len(source.splitlines())


@pytest.mark.parametrize("source,overrides,error", [
    ("module Block(input string a); endmodule", {}, "non-integral"),
    ("module Block(input logic a[]); endmodule", {}, "dynamic"),
    ("module Block(ref logic a); endmodule", {}, "ref port"),
    ("interface bus; logic a; endinterface module Block(bus p); endmodule", {}, "interface port"),
    ("module Block #(parameter W=4)(input [W-1:0] a); endmodule", {"BAD": 2}, "resolve"),
    ("module Block #(localparam W=4)(input [W-1:0] a); endmodule", {"W": 2}, "localparam"),
])
def test_unsupported_types_and_parameter_overrides_fail(source, overrides, error):
    """Unsupported or unresolved types must never silently become one-bit ports."""
    with pytest.raises(ValueError, match=error):
        sv_frontend.typed_ports(source, "Block", overrides)


def test_generic_array_scaffold_and_frontend_version_are_checked(tmp_path, monkeypatch):
    """Capture array shape end-to-end and invalidate evidence after frontend drift."""
    source = tmp_path / "inputs/Block"
    source.mkdir(parents=True)
    (source / "top.sv").write_text("module Block(input logic [7:0] data[0:3]); endmodule\n")
    generate_generic(tmp_path, "Block", "Generic")
    manifest, ports = validate_generic_evidence(tmp_path, "Block", "Generic")
    assert manifest["tool_versions"] == {"pyslang": sv_frontend.load_frontend().__version__}
    scaffold = generate_port_scaffold(tmp_path, "Block", "Generic", generic=True).read_text()
    # The scaffold's canonical header is sufficient inside the template's Appendix A heading.
    appendix = "\n## " + ARTIFACT_TEXT["appendix_title"] + "\n\n" + scaffold.split("\n\n", 2)[2]
    assert validate_ports(appendix, ports) == []
    assert validate_ports(appendix.replace("I/8[0:3]", "I/8"), ports)
    monkeypatch.setattr(sv_frontend.load_frontend(), "__version__", "different")
    with pytest.raises(ValueError, match="frontend version changed"):
        validate_generic_evidence(tmp_path, "Block", "Generic")


def test_module_declarations_ignore_strings_and_comments():
    """Only syntax declarations may select a top module."""
    source = '// module Fake; endmodule\nmodule Block; string s="module Fake; endmodule"; endmodule\n'
    assert sv_frontend.module_lines(source, "Fake") == []
    assert sv_frontend.module_lines(source, "Block") == [2]


@pytest.fixture
def guarded_fact(tmp_path):
    """Create a multiline assignment with nested reset and enable guards."""
    source = """module Block(input clock, reset_n, enable, input [7:0] data, output logic [7:0] state);
always_ff @(posedge clock) begin
 if (!reset_n) state <= 8'h00;
 else if (enable) state <=
   data;
end
endmodule
"""
    path = tmp_path / "Block.sv"
    path.write_text(source)
    candidate = sv_frontend.assignment_facts(source, "Block")[1]
    fact = {k: v for k, v in candidate.items() if k not in {"start_line", "end_line"}}
    fact.update(kind="assignment", evidence=[{"path": "Block.sv", "start_line": 4, "end_line": 5}])
    behavior = {"id": "P-STATE", "fact_status": "asserted", "facts": [fact]}
    return tmp_path, behavior, {"module": "Block", "sources": {"Block.sv": digest(path)}}


def test_exact_event_nested_guards_and_multiline_range_pass(guarded_fact):
    """Verify clock event and outer-to-inner then/else polarity for a full source range."""
    root, behavior, baseline = guarded_fact
    fact = behavior["facts"][0]
    assert fact["guards"] == [{"condition": "!reset_n", "branch": "else"},
                              {"condition": "enable", "branch": "then"}]
    fact["rhs"] = " /* equivalent formatting */ data "
    validate_behavior_facts(root, [behavior], baseline, root / "review.json")


@pytest.mark.parametrize("defect", ["value", "clock", "edge", "polarity", "guard", "process", "operator",
                                     "range", "source", "enum_type", "guard_type", "expression_injection"])
def test_contradictory_facts_are_rejected(guarded_fact, defect):
    """Wrong values, timing, context, source or incomplete evidence cannot pass review."""
    root, original, baseline = guarded_fact
    behavior = copy.deepcopy(original)
    fact = behavior["facts"][0]
    if defect == "value":
        fact["rhs"] = "8'h00"
    elif defect in {"clock", "edge"}:
        fact["event"] = "@(posedge other_clock)" if defect == "clock" else "@(negedge clock)"
    elif defect == "polarity":
        fact["guards"][0]["branch"] = "then"
    elif defect == "guard":
        fact["guards"].pop()
    elif defect == "process":
        fact["process"] = "always_comb"
    elif defect == "operator":
        fact["operator"] = "="
    elif defect == "range":
        fact["evidence"][0]["end_line"] = 4
    elif defect == "source":
        fact["evidence"][0]["path"] = "../outside.sv"
    elif defect == "enum_type":
        fact["operator"] = []
    elif defect == "guard_type":
        fact["guards"][0]["branch"] = {}
    else:
        fact["rhs"] = "data; assign other = value"
    with pytest.raises(ValueError):
        validate_behavior_facts(root, [behavior], baseline, root / "review.json")


@pytest.mark.parametrize("statement", [
    "always_comb case (s) 0: q=d; default: q=0; endcase",
    "always_comb for (int i=0;i<1;i++) q=d;",
    "if (1) begin assign q=d; end",
    "function f; f=d; endfunction",
    "always @(posedge clk) begin @(posedge other) q<=d; end",
    "always @(posedge clk or negedge rst) q<=d;",
    "always q=d;",
    "always_ff q<=d;",
    "always_ff @* q<=d;",
    "always_ff @(clk) q<=d;",
    "always @(posedge clk) q<=#1 d;",
    "assign #1 q=d;",
])
def test_unsupported_control_scopes_are_not_unconditional_facts(statement):
    """Complex scopes and extra delays require explicit manual review rather than guessed facts."""
    assert sv_frontend.assignment_facts("module Block; " + statement + " endmodule", "Block") == []


def test_comments_strings_and_other_modules_are_not_assignment_evidence():
    """Discard textual lookalikes and assignments owned by a different module."""
    source = '''module Other; assign q=d; endmodule
module Block;
// assign q=d;
string text="assign q=d;";
assign actual = input_value;
endmodule'''
    facts = sv_frontend.assignment_facts(source, "Block")
    assert [(f["lhs"], f["rhs"]) for f in facts] == [("actual", "input_value")]
    assert sv_frontend.expression_tokens('"a b"') != sv_frontend.expression_tokens('"ab"')


@pytest.mark.parametrize(
    "source,expected_event,expected_rhs",
    [
        ("module Block(input d, output logic q); always @* q = d; endmodule", "@*", "d"),
        ("module Block(input clk,en,d, output logic q); always_ff @(posedge clk iff en) q <= d; endmodule",
         "@(posedge clk iff en)", "d"),
        ("module Block(input d, output logic q); function automatic logic f(input logic x); f=x; endfunction always_comb q = f(d); endmodule",
         None, "f(d)"),
    ],
)
def test_supported_event_forms_and_function_rhs_are_recorded_as_exact_assignments(
    source, expected_event, expected_rhs
):
    """Record bounded assignment syntax without claiming function-body semantics."""
    facts = sv_frontend.assignment_facts(source, "Block")
    assert len(facts) == 1
    assert facts[0]["event"] == expected_event
    assert facts[0]["rhs"] == expected_rhs


def test_raw_conditional_fact_cannot_guess_compilation_macros():
    """An inactive branch must not become evidence by guessing a fresh macro environment."""
    source = """module Block;
`ifdef ENABLE
assign q=d;
`else
assign q=0;
`endif
endmodule
"""
    with pytest.raises(ValueError, match="preprocessed RTL view"):
        sv_frontend.assignment_facts(source, "Block")
    source = '`timescale 1ns/1ps\nmodule Block; string s="`ENABLE"; assign q=d; endmodule'
    assert len(sv_frontend.assignment_facts(source, "Block")) == 1


@pytest.mark.parametrize("value,event", [
    ("x; logic other", False), ("x, y=z", False),
    ("x; endmodule module Injected;", False),
    ("@(posedge clk) q=0", True), ("#1", True),
])
def test_fact_expressions_cannot_inject_other_constructs(value, event):
    """A fact field must contain exactly one expression or event control."""
    with pytest.raises(ValueError):
        sv_frontend.expression_tokens(value, event=event)
