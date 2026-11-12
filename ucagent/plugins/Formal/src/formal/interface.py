"""Resolve a bounded Formal DUT interface from actual RTL under explicit overrides.

A plain filelist.txt selects ordered sources; otherwise direct .v then .sv files
are sorted. Sources share one preprocessing unit, with literal local includes
confined to the DUT tree. The same context is used by the parser and solver.
"""

from __future__ import annotations

from pathlib import Path
import re

from ucagent.util.file_policy import normalize_relative_path


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
INTEGER_LITERAL = re.compile(r"(?:[+-]?\d+|[+-]?(?:\d+)?'[sS]?[bBoOdDhH][0-9a-fA-F_]+)\Z")


def compile_context(workspace: str, dut: str) -> dict:
    """Admit ordered, local RTL sources and literal include dependencies without writes."""
    root = Path(workspace).resolve()
    dut = normalize_relative_path(dut)
    if not IDENTIFIER.fullmatch(dut):
        raise ValueError("Formal DUT must be one module identifier")
    source = root / dut
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"Missing or symlink DUT source directory: {dut}")
    manifest = source / "filelist.txt"
    def admitted(relative: str) -> Path:
        """Reject paths the parser or snapshot could interpret outside the DUT tree."""
        path = Path(relative)
        if (not relative or path.is_absolute() or ".." in path.parts or "\\" in relative
                or any(char in relative for char in "{}$[];\n\r") or relative.startswith(("-", "+"))):
            raise ValueError(f"Invalid RTL path {relative!r}: use plain relative paths within {dut}, without flags or parent traversal")
        target = source / path
        if (not target.resolve().is_relative_to(source.resolve()) or not target.is_file()
                or any(part.is_symlink() for part in (target, *target.parents) if part.is_relative_to(source))):
            raise ValueError(f"RTL dependency is missing, outside the DUT, or a symlink: {dut}/{relative}")
        if target.stat().st_size > 8 * 1024 * 1024:
            raise ValueError(f"RTL dependency exceeds the 8 MiB parsing budget: {dut}/{relative}")
        return target
    if manifest.exists():
        admitted("filelist.txt")
        if manifest.stat().st_size > 65536:
            raise ValueError("filelist.txt exceeds the 64 KiB manifest budget")
        names = []
        for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            name = line.strip()
            if not name or name.startswith(("#", "//")):
                continue
            if len(name.split()) != 1:
                raise ValueError(f"{dut}/filelist.txt:{line_number}: expected one plain relative source path, no options")
            names.append(name)
        if not names or len(names) > 512 or len(names) != len(set(names)):
            raise ValueError("filelist.txt must contain 1..512 unique relative source paths")
        files = [admitted(name) for name in names]
        if any(path.suffix not in {".v", ".sv", ".vh", ".svh"} for path in files):
            raise ValueError("filelist.txt supports Verilog/SystemVerilog source and header files only")
    else:
        files = [*sorted(source.glob("*.v")), *sorted(source.glob("*.sv"))]
        files = [admitted(str(path.relative_to(source))) for path in files]
        if not files or len(files) > 512:
            raise ValueError(f"Expected 1..512 direct RTL sources in {dut}, or provide filelist.txt")
    dependencies, pending = set(), list(files)
    include_dirs = [source, *dict.fromkeys(path.parent for path in files if path.parent != source)]
    while pending:
        path = pending.pop(0)
        if path in dependencies:
            continue
        dependencies.add(path)
        if len(dependencies) > 1024:
            raise ValueError("RTL include dependency budget exceeded")
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for match in re.finditer(r"`\s*include\s+([^\n]+)", code):
            literal = re.fullmatch(r'"([^"\n]+)"\s*', match.group(1))
            if literal is None:
                raise ValueError(f"{path.relative_to(root)}: include requires a literal quoted path within the DUT tree")
            name = literal.group(1)
            if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
                raise ValueError(f"{path.relative_to(root)}: include must use a local relative path without parent traversal")
            # Both tools search the including file's directory first, then the
            # deterministic shared directory list. No ambient CWD fallback is used.
            candidates = [path.parent / name, *[directory / name for directory in include_dirs]]
            found = next((candidate for candidate in candidates if candidate.is_file()), None)
            if found is None:
                raise ValueError(f"{path.relative_to(root)}: missing local include {name}")
            included = admitted(str(found.relative_to(source)))
            if included.parent not in include_dirs:
                include_dirs.append(included.parent)
            pending.append(included)
    return {"source_files": [str(path.relative_to(root)) for path in files],
            "include_dirs": [str(path.relative_to(root)) for path in include_dirs],
            "dependency_files": sorted(str(path.relative_to(root)) for path in dependencies),
            "source_manifest": str(manifest.relative_to(root)) if manifest.exists() else None,
            "compilation_context": "ordered_filelist_or_direct_sources_single_preprocessing_unit_local_includes"}


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
    context = compile_context(str(root), dut)
    files = [root / relative for relative in context["source_files"]]
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
        manager = slang.SourceManager()
        for directory in context["include_dirs"]:
            manager.addUserDirectories(str(root / directory))
        tree = slang.syntax.SyntaxTree.fromFiles([str(path) for path in files], manager)
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
        compilation.addSyntaxTree(slang.syntax.SyntaxTree.fromText(harness, manager))
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
        return {"dut": dut, **context,
                "parameters": resolved, "effective_parameters": constants, "explicit_overrides": overrides,
                "ports": ports, "port_info": [(port["name"], port["declaration"]) for port in ports]}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot resolve the actual Formal interface for {dut}; inspect the current sources and spec.parameters. {type(exc).__name__}: {str(exc)[:500]}") from exc
