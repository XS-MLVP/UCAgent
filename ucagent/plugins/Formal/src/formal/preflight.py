"""Check author SVA bodies and elaborated generated Formal sources."""

import hashlib
import json
import re
from pathlib import Path


class PreflightError(ValueError):
    """Expose bounded, source-linked diagnostics to tools and stage checkers."""

    def __init__(self, layer, diagnostics):
        self.diagnostic = {
            "status": "error",
            "error_code": "formal_sva_preflight",
            "layer": layer,
            "diagnostic_total": len(diagnostics),
            "diagnostics": diagnostics[:32],
            "error": "SVA preflight found blocking diagnostics; correct the referenced CK or source.",
        }
        super().__init__(self.diagnostic["error"] + " " + str(diagnostics[:8]))


def check_bodies(bodies: dict, source: str) -> None:
    """Validate one property fragment without requiring its declarations or macros."""
    import pyslang as slang

    diagnostics = []
    for ck, body in bodies.items():
        if not isinstance(body, str) or not body.strip() or "[LLM-TODO]" in body:
            continue
        # Active preprocessing and macro expansion require the ordered source unit.
        if "`" in re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.DOTALL):
            continue
        manager = slang.SourceManager()
        engine = slang.DiagnosticEngine(manager)
        text = f"module __formal_probe;\nproperty p;\n{body}\nendproperty\nA: assert property(p);\nendmodule\n"
        tree = slang.syntax.SyntaxTree.fromText(text, manager)
        errors = [diag for diag in tree.diagnostics if diag.isError()]
        for diag in errors:
            diagnostics.append({"ck_id": ck, "path": source, "body_line": max(1, manager.getLineNumber(diag.location) - 2),
                                "column": manager.getColumnNumber(diag.location), "message": engine.formatMessage(diag)})
        if not errors and (
            tree.root.kind != slang.syntax.SyntaxKind.ModuleDeclaration
            or [item.kind for item in tree.root.members] != [
                slang.syntax.SyntaxKind.PropertyDeclaration, slang.syntax.SyntaxKind.ConcurrentAssertionMember
            ]
        ):
            diagnostics.append({"ck_id": ck, "path": source, "body_line": 1,
                                "message": "Expected a single property body."})
    if diagnostics:
        raise PreflightError("property_body", diagnostics)


def check_generated(root: Path, output: str, dut: str, staged: Path, interface: dict, records) -> dict:
    """Elaborate the same ordered RTL, checker and wrapper used by FormalMC."""
    import pyslang as slang
    from .skills.lib.formal_tools import _ck_to_sv_names

    manager = slang.SourceManager()
    engine = slang.DiagnosticEngine(manager)
    for directory in interface["include_dirs"]:
        manager.addUserDirectories(str(root / directory))
    checker = staged / f"{dut}_checker.sv"
    wrapper = staged / f"{dut}_wrapper.sv"
    tree = slang.syntax.SyntaxTree.fromFiles(
        [str(root / relative) for relative in interface["source_files"]] + [str(checker), str(wrapper)], manager
    )
    options = slang.ast.CompilationOptions()
    top = f"{dut}_wrapper"
    options.topModules = {top}
    bag = slang.Bag()
    bag.compilationOptions = options
    compilation = slang.ast.Compilation(bag)
    compilation.addSyntaxTree(tree)

    names = {_ck_to_sv_names(ck.id, ck.style)[0]: ck.id for fg in records.spec.function_groups
             for fc in fg.functions for ck in fc.check_points}
    ranges = []
    for match in re.finditer(r"^\s*property ([\w]+);.*?\bendproperty\b", checker.read_text(), re.M | re.S):
        text = match.string
        ranges.append((text.count("\n", 0, match.start()) + 1, text.count("\n", 0, match.end()) + 1,
                       names.get(match[1])))

    def location(loc):
        """Map generated positions back to stable output paths and CK identities."""
        loc = manager.getFullyOriginalLoc(loc)
        path = Path(manager.getFileName(loc))
        line = manager.getLineNumber(loc)
        result = {"path": f"{output}/tests/{path.name}" if path.name in {checker.name, wrapper.name}
                  else str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                  "line": line, "column": manager.getColumnNumber(loc)}
        if path.name == checker.name:
            result["ck_id"] = next((key for start, end, key in ranges if start <= line <= end), None)
        return result

    errors = []
    warnings = []
    for diag in compilation.getAllDiagnostics():
        row = {**location(diag.location), "code": str(diag.code), "message": engine.formatMessage(diag)}
        # A default timing directive in an RTL module need not be copied to
        # generated, delay-free checker and wrapper modules.
        if diag.isError() and str(diag.code) != "DiagCode(MissingTimeScale)":
            errors.append(row)
    if errors:
        raise PreflightError("generated_design", errors)

    operators = {"Equality", "Inequality", "CaseEquality", "CaseInequality", "WildcardEquality",
                 "WildcardInequality", "GreaterThan", "GreaterThanEqual", "LessThan", "LessThanEqual"}
    visited = set()

    def check_widths(node):
        """Report original operand widths for comparisons in generated properties."""
        if not isinstance(node, slang.ast.BinaryExpression) or node.op.name not in operators:
            return
        row = location(node.sourceRange.start)
        if not row.get("ck_id"):
            return
        operands = []
        for value in (node.left, node.right):
            while isinstance(value, slang.ast.ConversionExpression) and value.isImplicit:
                value = value.operand
            kind = value.type
            operands.append({"type": str(kind), "width": kind.bitWidth, "signed": kind.isSigned})
        key = (row["line"], row["column"])
        if key not in visited and all(item["width"] for item in operands) and operands[0]["width"] != operands[1]["width"]:
            visited.add(key)
            warnings.append({**row, "code": "formal_comparison_width", "operands": operands,
                             "message": "Comparison uses different original widths; confirm the intended extension or conversion."})

    compilation.getRoot().visit(check_widths)
    from .skills.lib.models import semantic_inputs
    digest = hashlib.sha256(json.dumps(semantic_inputs(records), sort_keys=True).encode()).hexdigest()
    return {"status": "passed", "warning_total": len(warnings), "warnings": warnings[:32],
            "semantic_sha256": digest,
            "generated": {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in staged.iterdir()}}
