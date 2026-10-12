"""Resolve an explicit, bounded Verilog compilation view without claiming elaboration."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .evidence import local_path

IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_$]*"


def strip_comments(text: str) -> str:
    """Remove comments while preserving physical line positions and string literals."""
    return re.sub(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*',
                  lambda m: m.group() if m.group().startswith('"') else re.sub(r"[^\r\n]", " ", m.group()),
                  text, flags=re.S)


def compilation_config(source_root: Path, default_top: Path | None) -> dict:
    """Read strict source-relative file order, include paths, defines and parameter overrides."""
    path = source_root / "rtl2spec.json"
    if not path.exists():
        if default_top is None:
            raise ValueError("Select the top source or provide inputs/{module}/rtl2spec.json")
        return {"files": [default_top.relative_to(source_root).as_posix()], "include_dirs": [], "defines": {}, "parameters": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: invalid compilation JSON: {exc}") from exc
    keys = {"files", "include_dirs", "defines", "parameters"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{path}: required fields are exactly files, include_dirs, defines, parameters")
    for key in ("files", "include_dirs"):
        entries = value[key]
        if (not isinstance(entries, list) or any(not isinstance(item, str) for item in entries)
                or len(entries) != len(set(entries)) or (key == "files" and not entries)):
            raise ValueError(f"{path}: {key} must be a unique list of relative paths; files cannot be empty")
        for entry in entries:
            if not entry or Path(entry).is_absolute() or ".." in Path(entry).parts or "\\" in entry:
                raise ValueError(f"{path}: invalid {key} path: {entry}")
            target = local_path(source_root, entry)
            if not (target.is_file() if key == "files" else target.is_dir()):
                raise ValueError(f"{path}: missing {key} entry: {entry}")
            if key == "files" and target.suffix.lower() not in {".v", ".sv", ".vh", ".svh"}:
                raise ValueError(f"{path}: files must name Verilog/SystemVerilog sources: {entry}")
    for key in ("defines", "parameters"):
        values = value[key]
        if not isinstance(values, dict) or any(not re.fullmatch(IDENTIFIER, name) for name in values):
            raise ValueError(f"{path}: {key} must map HDL identifiers to values")
        for name, item in values.items():
            if key == "parameters" and type(item) is not int:
                raise ValueError(f"{path}: parameter override {name} must be an integer")
            if key == "defines" and (not isinstance(item, str) or any(c in item for c in ('\n', '\r', '\\'))):
                raise ValueError(f"{path}: define {name} must be a single-line object macro string")
    return value


class VerilogPreprocessor:
    """Select active branches and resolve object macros/includes with an original-source map."""

    def __init__(self, root: Path | None = None, *, include_dirs: list[str] = (), defines: dict | None = None):
        """Keep the compilation-unit macro state and allowed source search roots."""
        self.root = root
        self.include_dirs = [local_path(root, path) for path in include_dirs] if root else []
        self.macros = dict(defines or {})
        self.stack: list[Path] = []

    def expand(self, text: str) -> str:
        """Expand object macros outside strings, rejecting unresolved or recursive definitions."""
        pattern = re.compile(r'"(?:\\.|[^"\\])*"|`(' + IDENTIFIER + ')')
        for _ in range(64):
            found = False

            def replace(match):
                """Replace a known macro while preserving quoted literals."""
                nonlocal found
                name = match.group(1)
                if name is None:
                    return match.group()
                if name not in self.macros:
                    raise ValueError(f"unresolved macro `{name}; supply defines/includes in rtl2spec.json")
                found = True
                return self.macros[name]

            text = pattern.sub(replace, text)
            if not found:
                return text
        raise ValueError("recursive or excessive macro expansion; supply a supported source view")

    def process(self, text: str, path: Path | None = None) -> tuple[str, list[dict]]:
        """Process a source file; line entries identify actual original physical lines."""
        if path is not None:
            if path in self.stack:
                raise ValueError(f"{path}: recursive include cycle")
            self.stack.append(path)
        frames = []
        output, locations = [], []
        try:
            for number, line in enumerate(strip_comments(text).splitlines(keepends=True), 1):
                location = {"path": str(path.relative_to(self.root)) if path and self.root else "<text>", "line": number}
                directive = re.match(r"^[ \t]*`(" + IDENTIFIER + r")(.*)$", line.rstrip('\r\n'))
                active = all(frame["active"] for frame in frames)
                emitted = "\n"
                if directive and directive[1] in {"ifdef", "ifndef", "elsif", "else", "endif", "define", "undef", "include", "undefineall", "timescale", "default_nettype", "celldefine", "endcelldefine"}:
                    kind, argument = directive[1], directive[2].strip()
                    if kind in {"ifdef", "ifndef", "elsif", "undef"} and not re.fullmatch(IDENTIFIER, argument):
                        raise ValueError(f"`{kind} requires a macro name")
                    if kind in {"else", "endif"} and argument:
                        raise ValueError(f"unexpected arguments after `{kind}")
                    if kind in {"ifdef", "ifndef"}:
                        condition = argument in self.macros
                        if kind == "ifndef":
                            condition = not condition
                        frames.append({"parent": active, "active": active and condition,
                                       "taken": active and condition, "else": False})
                    elif kind in {"else", "elsif", "endif"}:
                        if not frames:
                            raise ValueError(f"`{kind} without a matching `ifdef or `ifndef")
                        frame = frames[-1]
                        if kind == "endif":
                            frames.pop()
                        else:
                            if frame["else"]:
                                raise ValueError("duplicate `else or `elsif after `else")
                            condition = kind == "else" or argument in self.macros
                            frame["active"] = frame["parent"] and not frame["taken"] and condition
                            frame["taken"] |= frame["active"]
                            frame["else"] = kind == "else"
                    elif kind == "define" and active:
                        match = re.fullmatch('(' + IDENTIFIER + r')(?:[ \t]+(.*))?', argument)
                        if match is None:
                            raise ValueError("`define requires a macro name and a supported object value; function macros are unsupported")
                        if line.rstrip().endswith('\\'):
                            raise ValueError("multiline macros are unsupported; supply a preprocessed source view")
                        self.macros[match[1]] = match[2] or ""
                    elif kind == "undef" and active:
                        self.macros.pop(argument, None)
                    elif kind == "undefineall" and active:
                        self.macros.clear()
                    elif kind == "include" and active:
                        name = re.fullmatch(r'"([^"\n]+)"', argument)
                        if name is None or self.root is None or path is None:
                            raise ValueError("literal `include requires a source tree and rtl2spec.json include_dirs")
                        relative = name[1]
                        if Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
                            raise ValueError(f"invalid include path: {relative}")
                        candidates = [local_path(self.root, base / relative) for base in [path.parent, *self.include_dirs]]
                        included = next((candidate for candidate in candidates if candidate.is_file()), None)
                        if included is None:
                            raise ValueError(f"include {relative} not found; searched: {', '.join(map(str, candidates))}")
                        view, source_map = self.process(included.read_text(encoding="utf-8"), included)
                        output.append(view)
                        locations.extend(source_map)
                elif active:
                    emitted = self.expand(line).rstrip('\r\n') + '\n'
                output.append(emitted)
                locations.append(location)
            if frames:
                raise ValueError("unterminated Verilog preprocessor conditional")
            return "".join(output), locations
        except ValueError as exc:
            raise ValueError(f"{path or '<text>'}:{number if 'number' in locals() else 1}: {exc}") from exc
        finally:
            if path is not None:
                self.stack.pop()
