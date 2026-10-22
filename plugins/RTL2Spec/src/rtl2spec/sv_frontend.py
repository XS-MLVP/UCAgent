"""Extract typed ports and bounded assignment facts with the slang HDL frontend."""

from __future__ import annotations

import importlib
import re

from .verilog import strip_comments


def load_frontend():
    """Load the plugin-owned frontend or explain how to restore its dependency."""
    try:
        return importlib.import_module("pyslang")
    except ImportError as exc:
        raise ValueError("Missing pyslang; install the RTL2Spec plugin dependencies and retry") from exc


def slang_source_line(tree, offset) -> int:
    """Return a one-based physical source line for a pyslang source offset."""
    return tree.sourceManager.getLineNumber(offset)


def syntax_tree(text: str):
    """Parse an explicit source view without reading includes or guessing invalid syntax."""
    slang = load_frontend()
    # Inputs are already preprocessed within the allowed source tree. A syntax
    # parse must never let an include perform an additional filesystem read.
    if "`" in text:
        from .verilog import VerilogPreprocessor

        text = VerilogPreprocessor().process(text)[0]
    tree = slang.SyntaxTree.fromText(text)
    errors = [item for item in tree.diagnostics if item.isError()]
    if errors:
        details = slang.DiagnosticEngine.reportAll(tree.sourceManager, errors[:5])
        raise ValueError("Invalid SystemVerilog source: " + details[:2000])
    return slang, tree


def module_lines(text: str, module: str) -> list[int]:
    """Locate actual module declarations, excluding comments and string literals."""
    slang, tree = syntax_tree(text)
    lines = []

    def visit(node):
        """Collect the selected module's declaration lines from the syntax tree."""
        if (isinstance(node, slang.SyntaxNode) and node.kind == slang.SyntaxKind.ModuleDeclaration
                and node.header.name.valueText == module):
            lines.append(tree.sourceManager.getLineNumber(node.sourceRange.start))

    tree.root.visit(visit)
    return lines


def typed_ports(text: str, module: str, overrides: dict | None = None) -> list[dict]:
    """Elaborate one selected top and return exact fixed-size integral port shapes."""
    slang, tree = syntax_tree(text)
    options = slang.CompilationOptions()
    options.topModules = {module}
    options.paramOverrides = [f"{module}.{name}={value}" for name, value in (overrides or {}).items()]
    bag = slang.Bag()
    bag.compilationOptions = options
    compilation = slang.Compilation(bag)
    compilation.addSyntaxTree(tree)
    tops = compilation.getRoot().topInstances
    errors = [item for item in compilation.getAllDiagnostics() if item.isError()]
    if errors:
        details = slang.DiagnosticEngine.reportAll(tree.sourceManager, errors[:5])
        raise ValueError("SystemVerilog elaboration failed: " + details[:2000])
    if len(tops) != 1 or tops[0].body.definition.name != module:
        raise ValueError(f"Expected exactly one top module {module}; select its compilation files")
    body = tops[0].body
    nonansi_ranges = {}

    def collect_port_declarations(node):
        """Collect active non-ANSI declaration ranges for the selected module."""
        if not isinstance(node, slang.SyntaxNode) or node.kind != slang.SyntaxKind.PortDeclaration:
            return
        owner = node.parent
        if not (
            isinstance(owner, slang.SyntaxNode)
            and owner.kind == slang.SyntaxKind.ModuleDeclaration
            and owner.header.name.valueText == module
        ):
            return
        for declarator in node.declarators:
            nonansi_ranges[declarator.name.valueText] = (
                slang_source_line(tree, node.sourceRange.start),
                slang_source_line(tree, node.sourceRange.end),
            )

    tree.root.visit(collect_port_declarations)
    parameters = {item.name for item in body.parameters if not item.isLocalParam}
    if set(overrides or {}) - parameters:
        raise ValueError("Unknown or non-overridable parameters: " + ", ".join(sorted(set(overrides) - parameters)))
    ports = []
    for index, port in enumerate(body.portList):
        if port.kind != slang.SymbolKind.Port:
            raise ValueError(f"Unsupported interface port {port.name}; supply an integral port view")
        direction = {slang.ArgumentDirection.In: "input", slang.ArgumentDirection.Out: "output",
                     slang.ArgumentDirection.InOut: "inout"}.get(port.direction)
        if direction is None or not port.name:
            raise ValueError("Unsupported unnamed or ref port; supply named input/output/inout ports")
        datatype = port.type.canonicalType
        unpacked = []
        while datatype.isUnpackedArray and datatype.isFixedSize:
            bounds = datatype.fixedRange
            unpacked.append(f"[{bounds.left}:{bounds.right}]")
            datatype = datatype.arrayElementType.canonicalType
        canonical_datatype = datatype
        if not datatype.isIntegral or not datatype.isFixedSize or datatype.bitWidth <= 0:
            raise ValueError(f"Unsupported non-integral or dynamic port type for {port.name}: {port.type}")
        width = datatype.bitWidth
        signedness = "signed" if datatype.isSigned else "unsigned"
        packed = []
        while datatype.isPackedArray:
            bounds = datatype.fixedRange
            packed.append(f"[{bounds.left}:{bounds.right}]")
            datatype = datatype.arrayElementType.canonicalType
        declaration_start, declaration_end = nonansi_ranges.get(
            port.name,
            (
                slang_source_line(tree, port.syntax.sourceRange.start),
                slang_source_line(tree, port.syntax.sourceRange.end),
            ),
        )
        header_start = slang_source_line(tree, port.syntax.sourceRange.start)
        header_end = slang_source_line(tree, port.syntax.sourceRange.end)
        ports.append({"index": index, "direction": direction, "name": port.name,
                      "range": "".join(packed), "width": width,
                      "unpacked_range": "".join(unpacked), "type": str(port.type),
                      "signedness": signedness,
                      "canonical_type": str(canonical_datatype),
                      "packed_dimensions": "".join(packed),
                      "unpacked_dimensions": "".join(unpacked),
                      # externalLoc points at the direction/type declaration for
                      # non-ANSI ports and at the ANSI declaration otherwise.
                      "source_line": declaration_start,
                      "source_end_line": declaration_end,
                      "header_line": header_start,
                      "header_end_line": header_end})
    return ports


def assignment_facts(text: str, module: str) -> list[dict]:
    """Extract assignments with exact guards/events, excluding unsupported control scopes."""
    # Re-preprocessing authored evidence without its compilation-unit macro
    # state could turn an inactive branch into a fact about the selected build.
    directives = re.sub(r'"(?:\\.|[^"\\])*"', '""', strip_comments(text))
    directives = re.sub(r"(?m)^[ \t]*`(?:timescale|default_nettype|celldefine|endcelldefine)\b[^\n]*", "", directives)
    if "`" in directives:
        raise ValueError(f"Assignment facts require the captured preprocessed RTL view for macros/includes/conditional compilation; cite evidence/{module}.preprocessed.sv if available, otherwise use no_deterministic_fact and explain the unresolved compilation context")
    slang, tree = syntax_tree(text)
    facts = []

    def visit(node):
        """Inspect assignment nodes while preserving their enclosing process conditions."""
        if not isinstance(node, slang.SyntaxNode) or node.kind not in {
            slang.SyntaxKind.AssignmentExpression, slang.SyntaxKind.NonblockingAssignmentExpression,
        }:
            return
        if node.right.kind == slang.SyntaxKind.TimingControlExpression:
            return
        parent = node.parent
        guards = []
        event = None
        event_edge = None
        process = None
        while parent is not None:
            kind = parent.kind
            if kind == slang.SyntaxKind.ContinuousAssign:
                if parent.delay is not None:
                    return
                process = "continuous"
            elif kind == slang.SyntaxKind.ConditionalStatement:
                # ElseClause is a separate child, so ancestry records polarity.
                child = node
                while child.parent != parent:
                    child = child.parent
                guards.append({"condition": str(parent.predicate).strip(),
                               "branch": "else" if child.kind == slang.SyntaxKind.ElseClause else "then"})
            elif kind == slang.SyntaxKind.TimingControlStatement:
                if event is not None or parent.timingControl.kind not in {
                    slang.SyntaxKind.EventControl, slang.SyntaxKind.EventControlWithExpression,
                    slang.SyntaxKind.ImplicitEventControl,
                }:
                    return
                if parent.timingControl.kind != slang.SyntaxKind.ImplicitEventControl:
                    event_signals = []

                    def collect_event_signal(child):
                        """Count explicit signal event terms without interpreting their predicates."""
                        if (isinstance(child, slang.SyntaxNode)
                                and child.kind == slang.SyntaxKind.SignalEventExpression):
                            event_signals.append(child)

                    parent.timingControl.visit(collect_event_signal)
                    if len(event_signals) != 1:
                        return
                    event_edge = str(event_signals[0].edge).strip()
                event = str(parent.timingControl).strip()
            elif kind in {slang.SyntaxKind.AlwaysBlock, slang.SyntaxKind.AlwaysFFBlock,
                          slang.SyntaxKind.AlwaysCombBlock, slang.SyntaxKind.AlwaysLatchBlock}:
                process = str(parent.keyword).strip()
            elif kind == slang.SyntaxKind.ModuleDeclaration:
                if str(parent.header.name.valueText) != module or process is None:
                    return
                # A plain eventless ``always`` is an infinite zero-delay
                # process, not a bounded combinational fact.  always_comb and
                # always_latch intentionally have implicit sensitivity and are
                # handled as valid eventless processes.
                if process in {"always", "always_ff"} and event is None:
                    return
                if process == "always_ff" and event_edge not in {"posedge", "negedge", "edge"}:
                    return
                start = tree.sourceManager.getLineNumber(node.sourceRange.start)
                end = tree.sourceManager.getLineNumber(node.sourceRange.end)
                facts.append({"lhs": str(node.left).strip(), "rhs": str(node.right).strip(),
                              "operator": node.operatorToken.rawText, "process": process,
                              "event": event, "guards": list(reversed(guards)),
                              "start_line": start, "end_line": end})
                return
            elif kind not in {slang.SyntaxKind.ExpressionStatement, slang.SyntaxKind.SequentialBlockStatement,
                              slang.SyntaxKind.ElseClause}:
                # Case, loop, generate and function scopes need their own
                # semantics; accepting them as an unconditional fact is unsafe.
                return
            parent = parent.parent

    tree.root.visit(visit)
    return facts


def expression_tokens(value: str, *, event: bool = False) -> tuple[str, ...]:
    """Compare HDL text as tokens so whitespace/comments cannot change literal contents."""
    wrapper = "always " + value + ";" if event else "assign __value = " + value + ";"
    slang, tree = syntax_tree("module __fact; " + wrapper + " endmodule")
    if tree.root.kind != slang.SyntaxKind.ModuleDeclaration or len(tree.root.members) != 1:
        raise ValueError("Expected one HDL expression or event; remove extra statements or declarations")
    member = tree.root.members[0]
    if event:
        if (member.kind != slang.SyntaxKind.AlwaysBlock
                or member.statement.kind != slang.SyntaxKind.TimingControlStatement
                or member.statement.statement.kind != slang.SyntaxKind.EmptyStatement
                or member.statement.timingControl.kind not in {
                    slang.SyntaxKind.EventControl, slang.SyntaxKind.EventControlWithExpression,
                    slang.SyntaxKind.ImplicitEventControl,
                }):
            raise ValueError("Expected one HDL event control such as @(posedge clock)")
        expression = member.statement.timingControl
    else:
        if member.kind != slang.SyntaxKind.ContinuousAssign or len(member.assignments) != 1:
            raise ValueError("Expected one HDL expression; remove extra assignments")
        expression = member.assignments[0].right
    tokens = []
    expression.visit(lambda child: tokens.append(child.rawText) if isinstance(child, slang.Token) else None)
    return tuple(tokens)


def port_shape(port: dict) -> str:
    """Serialize direction, packed element width and any fixed unpacked dimensions."""
    direction = {"input": "I", "output": "O", "inout": "IO"}[port["direction"]]
    return f"{direction}/{port['width']}" + port.get("unpacked_range", "")
