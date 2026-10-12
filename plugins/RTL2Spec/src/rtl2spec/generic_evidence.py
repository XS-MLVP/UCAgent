"""Collect and verify evidence for modules supplied outside XiangShan.

The generic workflow consumes an existing Verilog/SystemVerilog source tree. It
does not invoke a simulator, synthesizer, or HDL compiler because no single
toolchain is valid for arbitrary modules. The source tree and its top-level RTL
are therefore treated as explicit user inputs and are signed before document
writing begins.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .evidence import digest, local_path, output_root, read_json, receipt
from .verilog import VerilogPreprocessor, compilation_config, strip_comments

GENERIC_SCHEMA_VERSION = 2
GENERIC_INPUT_ROOT = "inputs"
HDL_SUFFIXES = {".v", ".sv", ".vh", ".svh"}
_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s+"
    r"(?P<qualifiers>(?:(?:wire|logic|reg|tri|signed|unsigned)\s+)*)"
    r"(?P<range>\[[^\]]+\]\s+)?(?P<names>[^;]+);",
    re.S,
)
def _balanced_group(text: str, opening: int) -> tuple[str, int]:
    """Return one balanced parenthesized group and the index after it."""

    if opening >= len(text) or text[opening] != "(":
        raise ValueError("module declaration does not contain a port group")
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index], index + 1
    raise ValueError("unterminated module parameter or port group")


def _module_port_group(text: str, module: str, overrides: dict | None = None) -> tuple[str, int, dict[str, int]]:
    """Extract one module's port group and the end of its declaration."""

    declaration = re.search(
        rf"\bmodule\s+{re.escape(module)}\b", text
    )
    if declaration is None:
        raise ValueError(f"module declaration not found: {module}")
    position = declaration.end()
    while position < len(text) and text[position].isspace():
        position += 1
    parameters: dict[str, int] = {}
    if position < len(text) and text[position] == "#":
        position += 1
        while position < len(text) and text[position].isspace():
            position += 1
        parameter_text, position = _balanced_group(text, position)
        parameters = _parameter_values(parameter_text, overrides or {})
        while position < len(text) and text[position].isspace():
            position += 1
    if overrides and set(overrides) - parameters.keys():
        raise ValueError("unknown parameter overrides: " + ", ".join(sorted(set(overrides) - parameters.keys())))
    if position < len(text) and text[position] == ";":
        return "", position, parameters
    while position < len(text) and text[position].isspace():
        position += 1
    ports, end = _balanced_group(text, position)
    semicolon = text.find(";", end)
    if semicolon < 0:
        raise ValueError(f"module declaration has no terminating semicolon: {module}")
    return ports, semicolon, parameters


def _constant_value(expression: str, parameters: dict[str, int]) -> int:
    """Evaluate a small integer width expression without executing arbitrary code."""

    def visit(node: ast.AST) -> int:
        """Evaluate supported integer-only HDL arithmetic with bounded shifts."""
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in parameters:
            return parameters[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.LShift, ast.RShift, ast.BitOr, ast.BitAnd, ast.BitXor)
        ):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, (ast.LShift, ast.RShift)):
                if not 0 <= right <= 64:
                    raise ValueError("unsupported shift count in port width")
                return left << right if isinstance(node.op, ast.LShift) else left >> right
            if isinstance(node.op, ast.BitOr):
                return left | right
            if isinstance(node.op, ast.BitAnd):
                return left & right
            if isinstance(node.op, ast.BitXor):
                return left ^ right
            if right == 0:
                raise ValueError("division by zero in port width")
            quotient = (abs(left) // abs(right)) * (-1 if (left < 0) != (right < 0) else 1)
            return left - quotient * right if isinstance(node.op, ast.Mod) else quotient
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "clog2" and len(node.args) == 1 and not node.keywords:
            value = visit(node.args[0])
            if value < 0:
                raise ValueError("negative clog2 argument")
            return max(0, value - 1).bit_length()
        raise ValueError("unsupported expression in port width")

    try:
        for match in reversed(list(re.finditer(r"(?:(\d+))?'([bBoOdDhH])([0-9a-fA-F_]+)", expression))):
            value = int(match[3].replace("_", ""), {"b": 2, "o": 8, "d": 10, "h": 16}[match[2].lower()])
            if match[1]:
                bits = int(match[1])
                if not 1 <= bits <= 4096:
                    raise ValueError("unsupported sized integer width")
                value &= (1 << bits) - 1
            expression = expression[:match.start()] + str(value) + expression[match.end():]
        return visit(ast.parse(expression.strip().replace("$clog2", "clog2"), mode="eval").body)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"unresolved or unsupported port width: {expression.strip()}") from exc


def _parameter_values(text: str, overrides: dict) -> dict[str, int]:
    """Resolve declared defaults in order, applying explicit top-level integer overrides."""
    values = {}
    for item in _split_ports(text):
        match = re.fullmatch(r"(?:(parameter|localparam)\s+)?(?:(?:integer|int|signed|unsigned)\s+)*"
                             r"([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(.+)", item)
        if match is None:
            raise ValueError(f"unsupported module parameter declaration: {item}")
        kind, name, expression = match.groups()
        if name in values or (kind == "localparam" and name in overrides):
            raise ValueError(f"duplicate or non-overridable parameter: {name}")
        values[name] = overrides[name] if name in overrides else _constant_value(expression, values)
    return values


def _range_width(
    bit_range: str | None, parameters: dict[str, int] | None = None
) -> tuple[str, int]:
    """Return a canonical range and width, resolving numeric parameters."""

    if not bit_range:
        return "", 1
    value = bit_range.strip()
    match = re.fullmatch(r"\[\s*(.*?)\s*:\s*(.*?)\s*\]", value)
    if match is None:
        raise ValueError(f"unresolved or unsupported port width: {value}")
    parameters = parameters or {}
    left = _constant_value(match.group(1), parameters)
    right = _constant_value(match.group(2), parameters)
    width = abs(left - right) + 1
    return value, width


def _split_ports(group: str) -> list[str]:
    """Split a port group at top-level commas."""

    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(group):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(group[start:index].strip())
            start = index + 1
    parts.append(group[start:].strip())
    return [part for part in parts if part]


def _declared_ports(
    group: str, parameters: dict[str, int]
) -> list[dict[str, object]]:
    """Parse ANSI declarations from a module port group."""

    ports: list[dict[str, object]] = []
    inherited: tuple[str, str, int] | None = None
    for part in _split_ports(group):
        match = re.fullmatch(
            r"(?:(input|output|inout)\s+)?"
            r"(?:(?:wire|logic|reg|tri|signed|unsigned)\s+)*"
            r"(\[[^\]]+\]\s+)?(.+)",
            part,
        )
        if match is None:
            raise ValueError(f"unsupported ANSI port declaration: {part}")
        direction, bit_range, names = match.groups()
        if direction is None:
            if inherited is None or bit_range:
                raise ValueError(f"port direction is missing: {part}")
            direction, range_text, width = inherited
        else:
            range_text, width = _range_width(bit_range, parameters)
            inherited = (direction, range_text, width)
        for raw_name in names.split(","):
            name = raw_name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
                raise ValueError(f"unsupported port name: {name}")
            ports.append(
                {
                    "index": len(ports),
                    "direction": direction,
                    "name": name,
                    "range": range_text,
                    "width": width,
                }
            )
    return ports


def _non_ansi_ports(
    text: str,
    group: str,
    declaration_end: int,
    parameters: dict[str, int],
) -> list[dict[str, object]]:
    """Parse classic Verilog port names followed by body declarations."""

    names = [name.strip() for name in _split_ports(group)]
    if not names or any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) for name in names
    ):
        raise ValueError("unsupported non-ANSI module port list")
    declarations: dict[str, tuple[str, str, int]] = {}
    body = re.split(r"\bendmodule\b", text[declaration_end:], maxsplit=1)[0]
    for match in _DECL_RE.finditer(body):
        direction = match.group(1)
        range_text, width = _range_width(match.group("range"), parameters)
        for raw_name in match.group("names").split(","):
            name = raw_name.strip()
            name = re.sub(r"\s*=.*$", "", name).strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
                raise ValueError(f"unsupported non-ANSI port declaration: {raw_name.strip()}")
            if name in declarations:
                raise ValueError(f"ambiguous direction declaration for port: {name}")
            declarations[name] = (direction, range_text, width)
    ports: list[dict[str, object]] = []
    for name in names:
        if name not in declarations:
            raise ValueError(f"missing direction declaration for port: {name}")
        direction, range_text, width = declarations[name]
        ports.append(
            {
                "index": len(ports),
                "direction": direction,
                "name": name,
                "range": range_text,
                "width": width,
            }
        )
    return ports


def parse_generic_ports(text: str, module: str, *, parameter_overrides: dict | None = None, preprocessed: bool = False) -> list[dict[str, object]]:
    """Parse common ANSI and non-ANSI Verilog/SystemVerilog port declarations."""

    cleaned = strip_comments(text) if preprocessed else VerilogPreprocessor().process(text)[0]
    group, declaration_end, parameters = _module_port_group(cleaned, module, parameter_overrides)
    if not group.strip():
        ports = []
    elif any(re.match(r"\s*(?:input|output|inout)\b", part) for part in _split_ports(group)):
        ports = _declared_ports(group, parameters)
    else:
        ports = _non_ansi_ports(cleaned, group, declaration_end, parameters)
    if len({port["name"] for port in ports}) != len(ports):
        raise ValueError(f"duplicate ports in {module}")
    return ports


def _input_root(root: Path, module: str) -> Path:
    """Return the workspace-local generic input directory."""

    return local_path(root, Path(GENERIC_INPUT_ROOT) / module)


def _source_files(root: Path, module: str) -> list[Path]:
    """Return all regular files in a generic input tree in stable order."""

    source_root = _input_root(root, module)
    if not source_root.is_dir():
        raise ValueError(f"{source_root}: generic module input directory is missing")
    files: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{path}: symlinks are not allowed in generic module inputs")
        if path.is_file():
            files.append(path)
    if not files:
        raise ValueError(f"{source_root}: generic module input directory is empty")
    return files


def _default_top(root: Path, module: str) -> Path:
    """Locate the unique HDL file that declares the requested top module."""

    matches: list[Path] = []
    for path in _source_files(root, module):
        if path.suffix.lower() not in HDL_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{path}: generic HDL input must be UTF-8 text") from exc
        if re.search(rf"\bmodule\s+{re.escape(module)}\b", strip_comments(text)):
            matches.append(path)
    if not matches:
        raise ValueError(
            f"{_input_root(root, module)}: no Verilog/SystemVerilog file declares top module {module}"
        )
    if len(matches) > 1:
        names = ", ".join(path.relative_to(root).as_posix() for path in matches[:8])
        raise ValueError(f"top module declaration is ambiguous: {module} ({names})")
    return matches[0]


def generic_source_state(root: Path, module: str) -> dict[str, object]:
    """Hash every generic input file so later checks detect source changes."""

    files = _source_files(root, module)
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": digest(path),
            "size": path.stat().st_size,
        }
        for path in files
    ]
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {
        "input_root": f"{GENERIC_INPUT_ROOT}/{module}",
        "files": records,
        "digest": hashlib.sha256(payload).hexdigest(),
    }


def generic_related_source_id(path: str) -> str:
    """Return a stable evidence identifier for one generic source path."""

    return "E-REL-" + hashlib.sha256(path.encode()).hexdigest()[:12].upper()


def collect_generic_related_sources(
    root: Path, module: str, related_files: list[str]
) -> list[dict[str, object]]:
    """Hash explicitly selected source files used to support document claims."""

    source_root = _input_root(root, module)
    if len(set(related_files)) != len(related_files):
        raise ValueError("related_files contains duplicates")
    top_rtl = find_generic_rtl(root, module)
    records: list[dict[str, object]] = []
    used_ids: set[str] = set()
    for relative in related_files:
        if (
            not relative
            or Path(relative).is_absolute()
            or "\\" in relative
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"invalid related source path: {relative}")
        path = local_path(source_root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"related source file is missing: {relative}")
        if path == top_rtl:
            raise ValueError("related_files must not contain the top-level RTL file")
        normalized = path.relative_to(root).as_posix()
        evidence_id = generic_related_source_id(normalized)
        if evidence_id in used_ids:
            raise ValueError(f"related source paths collide on evidence ID: {evidence_id}")
        used_ids.add(evidence_id)
        records.append(
            {
                "evidence_id": evidence_id,
                "module": Path(relative).as_posix(),
                "path": normalized,
                "line": 1,
                "sha256": digest(path),
            }
        )
    return records


def find_generic_rtl(root: Path, module: str) -> Path:
    """Locate the selected top definition in the resolved compilation input."""
    return generic_input_preflight(root, module)["rtl"]


def generic_input_preflight(root: Path, module: str) -> dict[str, object]:
    """Validate configuration and resolve only the selected compilation unit's active ports."""
    source_root = _input_root(root, module)
    state = generic_source_state(root, module)
    default_top = None if (source_root / "rtl2spec.json").exists() else _default_top(root, module)
    compilation = compilation_config(source_root, default_top)
    processor = VerilogPreprocessor(source_root, include_dirs=compilation["include_dirs"], defines=compilation["defines"])
    chunks, source_map = [], []
    for name in compilation["files"]:
        path = local_path(source_root, name)
        view, locations = processor.process(path.read_text(encoding="utf-8"), path)
        chunks.append(view)
        source_map.extend(locations)
    view = "".join(chunks)
    declarations = list(re.finditer(rf"\bmodule\s+{re.escape(module)}\b", view))
    if len(declarations) != 1:
        raise ValueError(f"expected exactly one active top module {module}; found {len(declarations)}; check rtl2spec.json files/defines")
    location = source_map[view.count("\n", 0, declarations[0].start())]
    rtl = local_path(source_root, location["path"])
    ports = parse_generic_ports(view, module, parameter_overrides=compilation["parameters"], preprocessed=True)
    source_map = [{"path": f"{GENERIC_INPUT_ROOT}/{module}/{item['path']}", "line": item["line"]} for item in source_map]
    return {"rtl": rtl, "ports": ports, "source_state": state, "compilation": compilation,
            "preprocessed": view, "source_map": source_map}


def generate_generic(
    root: Path, module: str, config: str, output_dir: str = "outputs"
) -> None:
    """Capture supplied RTL and signed source facts as generic module evidence."""

    from .documents import require_clean_output

    require_clean_output(root, output_dir)
    facts = generic_input_preflight(root, module)
    rtl = facts["rtl"]
    ports = facts["ports"]
    state = facts["source_state"]
    assert isinstance(rtl, Path)
    assert isinstance(ports, list)
    assert isinstance(state, dict)
    data = rtl.read_bytes()
    if generic_source_state(root, module) != state:
        raise ValueError("generic input source changed during evidence capture; retry with stable input")
    folder = local_path(root, output_root(root, output_dir) / "evidence")
    require_clean_output(root, output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    copied_rtl = local_path(root, folder / f"{module}.sv")
    copied_rtl.write_bytes(data)
    view_path = local_path(root, folder / f"{module}.preprocessed.sv")
    view_path.write_text(facts["preprocessed"], encoding="utf-8")
    map_path = local_path(root, folder / "source_map.json")
    map_path.write_text(json.dumps(facts["source_map"], indent=2) + "\n", encoding="utf-8")
    with local_path(root, folder / "ports.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["index", "direction", "name", "range", "width"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(ports)
    manifest = receipt(
        root,
        {
            "schema_version": GENERIC_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": module,
            "config": config,
            "source_state": state,
            "compilation": facts["compilation"],
            "preprocessed_sha256": digest(view_path),
            "source_map_sha256": digest(map_path),
            "source_baseline": state["digest"],
            "generation_status": "provided",
            "command": "user-supplied Verilog/SystemVerilog input",
            "generator_flags": [],
            "tool_versions": {},
            "related_sources": [],
            "rtl_source": rtl.relative_to(root).as_posix(),
            "rtl_sha256": hashlib.sha256(data).hexdigest(),
            "port_count": len(ports),
            "port_counts": {
                direction: sum(p["direction"] == direction for p in ports)
                for direction in ("input", "output", "inout")
            },
            "ports_file": "ports.csv",
        },
        sign=True,
    )
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    local_path(root, folder / "manifest.json").write_text(payload, encoding="utf-8")
    validate_generic_evidence(root, module, config, output_dir)
    print(f"Captured {folder.relative_to(root)}: {len(ports)} ports")


def record_generic_related_sources(
    root: Path, module: str, config: str, related_files: list[str],
    output_dir: str = "outputs",
) -> None:
    """Add signed generic source references to an existing evidence manifest."""

    manifest, _ = validate_generic_evidence(root, module, config, output_dir)
    manifest["related_sources"] = collect_generic_related_sources(
        root, module, related_files
    )
    signed = receipt(root, manifest, sign=True)
    folder = local_path(root, output_root(root, output_dir) / "evidence")
    local_path(root, folder / "manifest.json").write_text(
        json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_generic_evidence(root, module, config, output_dir)
    print(
        f"Recorded {len(related_files)} generic source file(s) in "
        f"{folder.relative_to(root)}/manifest.json"
    )


def validate_generic_evidence(
    root: Path, module: str, config: str, output_dir: str = "outputs"
) -> tuple[dict, list[dict[str, object]]]:
    """Recompute generic source, RTL and port facts from workspace inputs."""

    folder = local_path(root, output_root(root, output_dir) / "evidence")
    manifest = read_json(local_path(root, folder / "manifest.json"))
    receipt(root, manifest)
    if (
        manifest.get("schema_version"),
        manifest.get("module"),
        manifest.get("config"),
    ) != (GENERIC_SCHEMA_VERSION, module, config):
        raise ValueError(
            f"{folder}/manifest.json: expected generic schema {GENERIC_SCHEMA_VERSION}, module {module}, config {config}"
        )
    state = generic_source_state(root, module)
    if manifest.get("source_state") != state or manifest.get("source_baseline") != state["digest"]:
        raise ValueError(
            f"{folder}/manifest.json: generic input source changed; rerun generic_evidence"
        )
    rtl = local_path(root, folder / f"{module}.sv")
    source_rtl = find_generic_rtl(root, module)
    if manifest.get("rtl_source") != source_rtl.relative_to(root).as_posix():
        raise ValueError(
            f"{folder}/manifest.json: rtl_source does not identify the current top RTL; rerun generic_evidence"
        )
    if not rtl.is_file() or digest(rtl) != manifest.get("rtl_sha256"):
        raise ValueError(f"{rtl}: captured RTL is missing or its hash changed; rerun generic_evidence")
    if digest(source_rtl) != manifest.get("rtl_sha256"):
        raise ValueError(f"{source_rtl}: input RTL differs from captured evidence; rerun generic_evidence")
    facts = generic_input_preflight(root, module)
    ports = facts["ports"]
    view_path = local_path(root, folder / f"{module}.preprocessed.sv")
    map_path = local_path(root, folder / "source_map.json")
    if (manifest.get("compilation") != facts["compilation"]
            or digest(view_path) != manifest.get("preprocessed_sha256")
            or digest(map_path) != manifest.get("source_map_sha256")
            or view_path.read_text(encoding="utf-8") != facts["preprocessed"]
            or json.loads(map_path.read_text(encoding="utf-8")) != facts["source_map"]):
        raise ValueError(f"{folder}: compilation configuration or preprocessing evidence changed; regenerate evidence")
    csv_path = local_path(root, folder / "ports.csv")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = [{key: str(value) for key, value in row.items()} for row in ports]
    counts = {
        direction: sum(row["direction"] == direction for row in ports)
        for direction in ("input", "output", "inout")
    }
    if (
        rows != expected
        or manifest.get("port_count") != len(ports)
        or manifest.get("port_counts") != counts
    ):
        raise ValueError(f"{csv_path}: ports differ from captured RTL; rerun generic_evidence")
    related_sources = manifest.get("related_sources")
    if not isinstance(related_sources, list):
        raise ValueError(f"{folder}/manifest.json: related_sources must be a list")
    related_files = [
        item.get("module") for item in related_sources if isinstance(item, dict)
    ]
    if len(related_files) != len(related_sources) or any(
        not isinstance(value, str) for value in related_files
    ):
        raise ValueError(f"{folder}/manifest.json: related_sources contains an invalid record")
    if collect_generic_related_sources(root, module, related_files) != related_sources:
        raise ValueError(
            f"{folder}/manifest.json: related source paths or hashes changed; rerun generic_related_sources"
        )
    if manifest.get("generation_status") != "provided":
        raise ValueError(f"{folder}/manifest.json: generic RTL evidence has an invalid status")
    return manifest, ports
