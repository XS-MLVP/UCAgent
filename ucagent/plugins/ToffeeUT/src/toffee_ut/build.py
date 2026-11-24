"""Build supplied RTL with bounded Picker options and checked input identities."""

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .paths import digest, local_path, write_json
from .layout import project_layout
from .process import execute
from .build_receipts import package_files


def _checked_path(workspace, path):
    """Reject escapes and characters reinterpreted by Picker's generated build files."""
    path = Path(path)
    if any(ord(char) < 32 or char in "\"'\\#$`;+,<>&|(){}!*?[]" for char in str(path)):
        raise ValueError(f"Picker input/output path contains unsupported characters: {path}")
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot resolve build input/output path: {path}") from error
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Build input/output path escapes the workspace: {path}")
    return path


def _input_snapshot(workspace, sources, include_dirs, cwd):
    """Hash include trees and literal include closure, rejecting unsafe or opaque inputs."""
    inputs, targets, directories = {}, {}, {}
    pending = list(sources)

    def visit(directory, ancestors):
        """Follow workspace-local directory links without permitting recursive aliases."""
        directory = _checked_path(workspace, directory)
        resolved = directory.resolve()
        if resolved in ancestors:
            raise ValueError(f"Recursive include directory link: {directory}")
        directories[directory.relative_to(workspace).as_posix()] = resolved.relative_to(workspace).as_posix()
        for path in sorted(directory.iterdir()):
            _checked_path(workspace, path)
            if path.is_dir():
                visit(path, ancestors | {resolved})
            elif path.is_file():
                pending.append(path)
            else:
                raise ValueError(f"Include input must be a regular file or directory: {path}")

    for directory in include_dirs:
        visit(directory, set())
    parsed = set(sources)
    scanned = set()
    while pending:
        path = _checked_path(workspace, pending.pop())
        relative = path.relative_to(workspace).as_posix()
        if relative not in inputs:
            if not path.is_file():
                raise ValueError(f"Build input is missing or not a regular file: {path}")
            inputs[relative] = digest(path)
            targets[relative] = path.resolve().relative_to(workspace).as_posix()
        if path not in parsed and path.suffix not in {".v", ".sv", ".vh", ".svh"}:
            continue
        if relative in scanned:
            continue
        scanned.add(relative)
        # This is a conservative dependency scan, not a preprocessor: inactive
        # literal includes are checked too; computed includes fail closed.
        text = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                      lambda match: match[0] if match[0].startswith('"') else " ",
                      path.read_text(), flags=re.S)
        for match in re.finditer(r'"(?:\\.|[^"\\])*"|`include\b([^\r\n]*)', text):
            if match[1] is None:
                continue
            literal = re.fullmatch(r'\s*"([^"\r\n]+)"\s*', match[1])
            if literal is None:
                raise ValueError(f"Build input requires a literal `include path for fingerprinting: {path}")
            name = Path(literal[1])
            if name.is_absolute():
                raise ValueError(f"Absolute `include path is not allowed: {path}: {name}")
            found = []
            for directory in dict.fromkeys((path.parent, path.resolve().parent, *include_dirs, cwd)):
                candidate = directory / name
                _checked_path(workspace, candidate)
                # Lexically deleting '..' would change symlink/.. semantics.
                # Retain the lookup target as evidence, then scan its real path.
                targets[candidate.relative_to(workspace).as_posix()] = candidate.resolve().relative_to(workspace).as_posix()
                if ".." in candidate.parts:
                    candidate = candidate.resolve()
                if candidate.is_file():
                    found.append(candidate)
            if not found:
                raise ValueError(f"Literal `include input not found: {path}: {name}; declare include_dirs")
            pending.extend(found)
            parsed.update(found)
    return {"inputs": inputs, "input_targets": targets, "include_directories": directories}


def build_dut(workspace, dut, project, source_file, *, top=None, filelist=None, jobs=2,
              timing=False, rtl_defines=None, include_dirs=None,
              timeout=1200, cancelled=lambda: False, progress=lambda message: None):
    """Export new RTL with optional timing, canonical macros and workspace-local includes."""
    if type(timeout) is not int or not 1 <= timeout <= 14400:
        raise ValueError("Build timeout must be an integer in 1..14400 seconds")
    workspace = Path(workspace).resolve()
    layout = project_layout(workspace, dut, project)
    top = layout["top"] if top is None else top
    if (not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", top)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", layout["export_name"])
            or type(jobs) is not int or not 1 <= jobs <= 32):
        raise ValueError("top/export_name must be identifiers and jobs must be an integer in 1..32")
    if type(timing) is not bool:
        raise ValueError("timing must be a boolean")
    lists = {"filelist": filelist, "rtl_defines": rtl_defines, "include_dirs": include_dirs}
    for name, value in lists.items():
        if value is not None and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ValueError(f"{name} must be a list of strings")
    defines, seen = list(rtl_defines or []), set()
    for entry in defines:
        name, equal, value = entry.partition("=")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or (equal and not value):
            raise ValueError("rtl_defines expects nonempty NAME or NAME=VALUE with identifier names")
        if name in seen:
            raise ValueError(f"Duplicate rtl_defines macro: {name}")
        seen.add(name)
        # Picker forwards values through Make and CMake. Keep single-token SV
        # literals, but reject separators/expansions rather than adding flags.
        if any(ord(char) < 32 or char.isspace() or char in '\x00$;"`\\#+' for char in value):
            raise ValueError(f"Unsafe rtl_defines value for {name}; use a single-token RTL literal")
        for match in re.finditer("'", value):
            rest = value[match.end():]
            if not re.match(r"(?:[sS]?[bBoOdDhH]|[01xXzZ]|\{)", rest) and not (
                    rest.startswith("(") and match.start() > 0 and re.match(r"[A-Za-z0-9_\]]", value[match.start() - 1])):
                raise ValueError(f"Unsafe rtl_defines apostrophe for {name}; use an RTL literal")
    root = _checked_path(workspace, layout["root"])
    source = _checked_path(workspace, local_path(workspace, source_file))
    if not source.is_file() or source.suffix not in {".v", ".sv"}:
        raise ValueError("source_file must name an existing .v or .sv file")
    destination = local_path(workspace, (Path(project) / "dut" / dut).as_posix())
    if destination.exists() or destination.is_symlink():
        raise ValueError("DUT package already exists; use it or ask the operator to archive it before rebuilding")
    for directory in (destination.parent, root / "results"):
        _checked_path(workspace, directory)
        if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Build outputs must remain in the project's own dut/results directories: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"Build output directory is not a directory: {directory}")
    sources = [source]
    for relative in filelist or []:
        path = _checked_path(workspace, local_path(workspace, relative))
        if not path.is_file() or path.suffix not in {".v", ".sv"}:
            raise ValueError("filelist must contain explicit .v/.sv files inside the workspace")
        sources.append(path)
    includes = []
    for relative in include_dirs or []:
        path = _checked_path(workspace, local_path(workspace, relative))
        if not path.is_dir():
            raise ValueError(f"include_dirs must contain existing workspace-relative directories: {relative}")
        if any(path.resolve().is_relative_to(output.resolve()) or output.resolve().is_relative_to(path.resolve())
               for output in (destination.parent, root / "results")):
            raise ValueError(f"include_dirs must not overlap build output directories: {relative}")
        includes.append(path)
    before = _input_snapshot(workspace, sources, includes, root)
    options = {"timing": timing, "rtl_defines": defines, "include_dirs": list(include_dirs or []),
               "source_file": source_file, "filelist": list(filelist or []), "top": top,
               "export_name": layout["export_name"], "jobs": jobs}
    picker = shutil.which("picker")
    if picker is None:
        raise ValueError("Picker is unavailable; ask the operator to install the native toolchain")
    destination.parent.mkdir(parents=True, exist_ok=True)
    log = local_path(root, "results/build-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    log.mkdir(parents=True, exist_ok=False)
    extra = []
    if sources[1:] or includes:
        # Picker's .f tokenizer preserves double-quoted spaces; no user-supplied
        # command file or arbitrary filelist option is accepted at this boundary.
        recipe = log / "inputs.f"
        recipe.write_text("".join(f'"+incdir+{path}"\n' for path in includes)
                          + "".join(f'"{path}"\n' for path in sources[1:]))
        extra.extend(["--fs", str(recipe)])
    if timing:
        extra.extend(["-V", "--timing"])
    for entry in defines:
        extra.extend(["--rtl-define", entry])
    command = [picker, "export", str(source), *extra, "--sim", "verilator", "--rw", "mem_direct",
               "--sname", top, "--tname", layout["export_name"], "--tdir", str(destination),
               "-c", "-w", str(log / "layout.fst"), "-j", str(jobs)]
    generated = {"inputs.f": digest(recipe)} if sources[1:] or includes else {}
    execution_error, input_error = "", ""
    returncode, interrupted = None, ""
    try:
        if cancelled():
            interrupted = "cancelled"
        elif _input_snapshot(workspace, sources, includes, root) != before:
            input_error = "Build inputs changed before Picker was started"
        elif destination.exists() or destination.is_symlink():
            execution_error = "DUT package appeared before Picker was started; nothing was replaced"
        else:
            returncode, interrupted = execute(command, root, log / "stdout.log", log / "stderr.log",
                                              timeout, cancelled, progress)
    except (OSError, ValueError, RuntimeError) as error:
        execution_error = str(error)
    changed_inputs = []
    try:
        after = _input_snapshot(workspace, sources, includes, root)
        for kind in before:
            changed_inputs.extend(name for name in before[kind].keys() | after[kind].keys()
                                  if before[kind].get(name) != after[kind].get(name))
        changed_inputs.extend(str(log / name) for name, identity in generated.items() if digest(log / name) != identity)
        changed_inputs = sorted(set(changed_inputs))
        changed = bool(changed_inputs)
    except (OSError, ValueError, RuntimeError) as error:
        changed, input_error = True, str(error)
    changed = changed or bool(input_error)
    for name in ("stdout.log", "stderr.log"):
        (log / name).touch(exist_ok=True)
    ok = (not interrupted and not changed and not execution_error and returncode == 0
          and (destination / "__init__.py").is_file())
    report = {"ok": ok, "command": command, "timeout": timeout, "returncode": returncode, "interrupted": interrupted,
              "source_changed": changed, **before, "options": options, "generated_inputs": generated,
              "changed_inputs": changed_inputs,
              "execution_error": execution_error, "input_error": input_error, "top": top,
               "package": destination.relative_to(root).as_posix(), "logs": log.relative_to(root).as_posix()}
    if ok:
        try:
            report["package_files"] = package_files(workspace, destination)
        except (ValueError, OSError) as error:
            ok = report["ok"] = False
            execution_error = report["execution_error"] = f"Cannot fingerprint native build output: {error}"
    if not ok:
        report.update(error_code="DUT_BUILD_FAILED", error=(input_error or execution_error or
                      (f"Build inputs changed: {changed_inputs[:12]}" if changed else
                       f"Build failed: returncode={returncode}, interrupted={interrupted!r}; expected {destination / '__init__.py'}.")),
                       next_action="Read the build logs; fix inputs or ask the operator before replacing partial output.")
    write_json(log / "build.json", report)
    return report
