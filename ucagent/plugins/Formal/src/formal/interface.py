"""Resolve a bounded Formal DUT interface from actual RTL under explicit overrides.

The supported compilation context is the ordered set of direct .v then .sv files,
compiled as one unit without include paths, defines, or external packages. More
complex contexts fail explicitly instead of guessing declarations from prose.
"""

from __future__ import annotations

from pathlib import Path
import re

from ucagent.util.file_policy import normalize_relative_path


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
INTEGER_LITERAL = re.compile(r"(?:[+-]?\d+|[+-]?(?:\d+)?'[sS]?[bBoOdDhH][0-9a-fA-F_]+)\Z")


def inspect_interface(workspace: str, out: str, dut: str, parameters: dict | None = None) -> dict:
    """Return resolved scalar integral ports and effective constants without writes.

    spec.parameters contains explicit public parameter overrides only. Omitted
    values retain RTL defaults; dependent defaults are elaborated after overrides.
    No value is inferred from basic_info, environment variables, or module names.
    """
    try:
        import pyslang as slang
    except ImportError as exc:
        raise ValueError("Formal interface parsing is unavailable. Ask the operator to install the Formal plugin's declared dependencies, then retry; do not guess spec.parameters.") from exc
    root = Path(workspace).resolve()
    output = normalize_relative_path(out)
    dut = normalize_relative_path(dut)
    if not IDENTIFIER.fullmatch(dut) or len(Path(dut).parts) != 1:
        raise ValueError("Formal DUT must be a single SystemVerilog module identifier")
    for target in (root / dut, root / output):
        if not target.resolve().is_relative_to(root) or any(part.is_symlink() for part in (target, *target.parents) if part.is_relative_to(root)):
            raise ValueError("Formal interface paths must remain inside the workspace without symlinks")
    source = root / dut
    files = [*sorted(source.glob("*.v")), *sorted(source.glob("*.sv"))]
    if not files:
        raise ValueError(f"No direct .v/.sv sources in {dut}; provide the current DUT source set before rendering")
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Formal RTL sources must not escape the workspace or use symlinks")
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("A Formal RTL file exceeds the interface parsing budget")
        text = path.read_text(encoding="utf-8")
        # This is context admission, not a replacement RTL parser. Strip comments
        # before recognizing directives; the actual declarations are parsed below.
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
        if re.search(r"`\s*(?:include|define|undef|ifdef|ifndef|elsif|else|endif|resetall)\b", code):
            raise ValueError(f"{path.relative_to(root)} needs a preprocessor context. The Formal interface path supports direct sources without includes/defines/conditional compilation; supply a self-contained ordered source set.")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict) or any(not isinstance(name, str) or not IDENTIFIER.fullmatch(name) for name in parameters):
        raise ValueError("spec.parameters must be a mapping of public parameter identifiers to integer literals")
    overrides = {}
    for name, value in parameters.items():
        if type(value) is int:
            if value.bit_length() > 4096:
                raise ValueError(f"spec.parameters.{name} exceeds the supported constant width")
            # Sized values avoid truncating Python integers larger than an SV int.
            width = max(32, value.bit_length() + 1)
            overrides[name] = f"{width}'sh{value % (1 << width):x}"
        elif isinstance(value, str) and len(value) <= 2048 and INTEGER_LITERAL.fullmatch(value.replace("_", "")):
            overrides[name] = value
        else:
            raise ValueError(f"spec.parameters.{name} must be an integer or sized integer literal, not a guessed expression/type/string")
    try:
        tree = slang.syntax.SyntaxTree.fromFiles([str(path) for path in files])
        options = slang.ast.CompilationOptions()
        options.topModules = {dut}
        bag = slang.Bag()
        bag.compilationOptions = options
        declaration = slang.ast.Compilation(bag)
        declaration.addSyntaxTree(tree)
        tops = [instance for instance in declaration.getRoot().topInstances if instance.definition.name == dut]
        if len(tops) != 1:
            raise ValueError(f"Cannot resolve unique top module {dut} from the ordered RTL sources")
        symbols = {symbol.name: symbol for symbol in tops[0].body
                   if isinstance(symbol, (slang.ast.ParameterSymbol, slang.ast.TypeParameterSymbol))}
        for name in overrides:
            symbol = symbols.get(name)
            if (symbol is None or isinstance(symbol, slang.ast.TypeParameterSymbol) or symbol.isLocalParam
                    or symbol.initializer is not None and symbol.initializer.isImplicitString):
                raise ValueError(f"spec.parameters.{name} is unknown, local, or a type parameter; only actual public integral value parameters may be overridden")
        probe = "__ucagent_interface_probe"
        if any(definition.name == probe for definition in declaration.getDefinitions()):
            raise ValueError("RTL collides with the reserved interface probe name")
        assignments = ", ".join(f".{name}({literal})" for name, literal in overrides.items())
        harness = f"module {probe}; {dut}" + (f" #({assignments})" if assignments else "") + " __dut(); endmodule\n"
        options = slang.ast.CompilationOptions()
        options.topModules = {probe}
        bag = slang.Bag()
        bag.compilationOptions = options
        compilation = slang.ast.Compilation(bag)
        compilation.addSyntaxTree(tree)
        compilation.addSyntaxTree(slang.syntax.SyntaxTree.fromText(harness))
        top = next(instance for instance in compilation.getRoot().topInstances if instance.definition.name == probe)
        instance = next(symbol for symbol in top.body if isinstance(symbol, slang.ast.InstanceSymbol) and symbol.name == "__dut")
        diagnostics = [diagnostic for diagnostic in compilation.getAllDiagnostics() if diagnostic.isError()]
        if diagnostics:
            messages = slang.DiagnosticEngine.reportAll(compilation.sourceManager, diagnostics)
            raise ValueError("Formal RTL interface elaboration failed under spec.parameters; correct the named source or override before rendering. " + messages[:2500])
        resolved = []
        constants = {}
        for symbol in instance.body:
            if isinstance(symbol, slang.ast.TypeParameterSymbol):
                raise ValueError(f"DUT type parameter {symbol.name} is unsupported by the scalar Formal interface; provide a concrete scalar-integral source interface")
            if not isinstance(symbol, slang.ast.ParameterSymbol):
                continue
            if not IDENTIFIER.fullmatch(symbol.name):
                raise ValueError("Escaped parameter identifiers are unsupported in Formal interface generation")
            value_type = symbol.type.canonicalType
            value = symbol.value.value
            if (not value_type.isIntegral or value_type.isStruct or value_type.isUnpackedArray
                    or symbol.initializer is not None and symbol.initializer.isImplicitString
                    or not isinstance(value, slang.SVInt) or value.hasUnknown):
                raise ValueError(f"DUT parameter {symbol.name} has an unresolved or unsupported non-scalar integral value")
            width = value.bitWidth
            if not 0 < width <= 4096:
                raise ValueError(f"DUT parameter {symbol.name} exceeds the supported scalar width")
            number = int(value)
            literal = f"{width}'{'s' if value.isSigned else ''}h{number % (1 << width):x}"
            constants[symbol.name] = literal
            resolved.append({"name": symbol.name, "value": number, "width": width, "signed": value.isSigned,
                             "sv_literal": literal, "overridden": bool(symbol.isOverridden), "local": bool(symbol.isLocalParam)})
        ports = []
        for symbol in instance.body:
            if not isinstance(symbol, slang.ast.PortSymbol):
                continue
            if not IDENTIFIER.fullmatch(symbol.name):
                raise ValueError("Escaped port identifiers are unsupported in Formal interface generation")
            kind = symbol.type.canonicalType
            if (not kind.isIntegral or kind.isUnpackedArray or kind.isStruct or kind.isEnum
                    or kind.isPackedArray and kind.elementType.isPackedArray):
                raise ValueError(f"DUT port {symbol.name} requires an unsupported array/interface/aggregate type; provide a concrete integral port interface")
            direction = {slang.ast.ArgumentDirection.In: "input", slang.ast.ArgumentDirection.Out: "output",
                         slang.ast.ArgumentDirection.InOut: "inout"}.get(symbol.direction)
            if direction is None:
                raise ValueError(f"DUT port {symbol.name} uses an unsupported direction")
            width = kind.bitWidth
            if not 0 < width <= 1048576:
                raise ValueError(f"DUT port {symbol.name} has an invalid or excessive resolved width")
            selected = kind.fixedRange
            left, right = selected.left, selected.right
            dimensions = f" [{left}:{right}]" if width > 1 or kind.isPackedArray else ""
            declaration_text = f"{direction} logic{' signed' if kind.isSigned else ''}{dimensions} {symbol.name}"
            ports.append({"name": symbol.name, "direction": direction, "width": width, "signed": kind.isSigned,
                          "left": left, "right": right, "declaration": declaration_text})
        if not ports or any(isinstance(symbol, slang.ast.InterfacePortSymbol) for symbol in instance.body):
            raise ValueError("DUT must expose a nonempty scalar-integral port list; interface ports are unsupported")
        return {"dut": dut, "source_files": [str(path.relative_to(root)) for path in files],
                "parameters": resolved, "effective_parameters": constants, "explicit_overrides": overrides,
                "ports": ports, "port_info": [(port["name"], port["declaration"]) for port in ports],
                "compilation_context": "ordered_direct_v_then_sv_single_unit_no_external_preprocessor_context"}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot resolve the actual Formal interface for {dut}; inspect the current sources and spec.parameters. {type(exc).__name__}: {str(exc)[:500]}") from exc
