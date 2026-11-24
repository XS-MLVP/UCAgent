"""Audit native receipts at their explicit output-bound or legacy input/recipe level."""

import json
from pathlib import Path
import re

from .paths import digest, local_path


def package_files(workspace, package):
    """Fingerprint SDK native identity assets plus port metadata, without loading the DUT.

    Like Toffee's native build identity, exclude runtime waves/coverage and Python
    caches. The wrapper gate remains structural, not an ELF/ABI or hardware test.
    """
    workspace = Path(workspace).resolve()
    package = Path(package)
    files = {}
    for path in sorted(package.iterdir()):
        if path.name in {"__init__.py", "build-provenance.json"} or path.suffix in {".so", ".v", ".sv", ".xscfg"}:
            path = local_path(workspace, path.relative_to(workspace).as_posix())
            if not path.is_file():
                raise ValueError(f"Native identity asset is not a regular file: {path}")
            files[path.name] = digest(path)
    if "__init__.py" not in files:
        raise ValueError(f"Native identity needs __init__.py: {package}")
    return files


def _hash_map(value, label):
    """Reject malformed or empty identities rather than accepting vacuous freshness."""
    if (not isinstance(value, dict) or not value
            or any(not isinstance(name, str) or not name or not isinstance(identity, str)
                   or re.fullmatch(r"[0-9a-f]{64}", identity) is None for name, identity in value.items())):
        raise ValueError(f"Build receipt needs nonempty SHA-256 {label}")


def _current_contract(workspace, layout, receipt, record):
    """Recompute the producer's input closure and canonical argv for a matching output."""
    # Import lazily: build_dut uses package_files when emitting its receipt.
    from .build import _input_snapshot

    root = layout["root"]
    if record.get("package") != f"dut/{layout['dut']}":
        raise ValueError("Build receipt package does not identify this DUT")
    options = record.get("options")
    keys = {"source_file", "filelist", "include_dirs", "timing", "rtl_defines", "top", "export_name", "jobs"}
    if not isinstance(options, dict) or set(options) != keys:
        raise ValueError("Matching build receipt lacks the structured build options")
    for name in ("filelist", "include_dirs", "rtl_defines"):
        if not isinstance(options[name], list) or any(not isinstance(value, str) for value in options[name]):
            raise ValueError(f"Matching build receipt has invalid {name}")
    if (type(options["timing"]) is not bool or type(options["jobs"]) is not int or not 1 <= options["jobs"] <= 32
            or not isinstance(options["top"], str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", options["top"]) is None
            or options["export_name"] != layout["export_name"] or record.get("top") != options["top"]):
        raise ValueError("Matching build receipt top/export/options do not match the native contract")
    if (record.get("ok") is not True or type(record.get("returncode")) is not int or record["returncode"] != 0
            or record.get("source_changed") is not False or record.get("interrupted") != ""
            or record.get("execution_error") != "" or record.get("input_error") != "" or record.get("changed_inputs") != []):
        raise ValueError("Matching build receipt is unsuccessful, interrupted or source_changed")
    sources = [local_path(workspace, name) for name in [options["source_file"], *options["filelist"]]]
    includes = [local_path(workspace, name) for name in options["include_dirs"]]
    if any(not path.is_file() or path.suffix not in {".v", ".sv"} for path in sources):
        raise ValueError("Build receipt source_file/filelist must declare existing .v/.sv inputs")
    if any(not path.is_dir() or any(path.resolve().is_relative_to(output.resolve())
            or output.resolve().is_relative_to(path.resolve()) for output in (root / "dut", root / "results"))
            for path in includes):
        raise ValueError("Build receipt include_dirs must be input directories, not build outputs")
    # Apply the producer's macro grammar without dispatching a build or adding flags.
    seen = set()
    for define in options["rtl_defines"]:
        name, equal, value = define.partition("=")
        if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None or name in seen or equal and not value
                or any(ord(char) < 32 or char.isspace() or char in '\x00$;"`\\#+' for char in value)):
            raise ValueError("Build receipt rtl_defines violate the structured producer contract")
        seen.add(name)
        for match in re.finditer("'", value):
            rest = value[match.end():]
            if not re.match(r"(?:[sS]?[bBoOdDhH]|[01xXzZ]|\{)", rest) and not (
                    rest.startswith("(") and match.start() > 0 and re.match(r"[A-Za-z0-9_\]]", value[match.start() - 1])):
                raise ValueError("Build receipt rtl_defines require single-token RTL literals")
    snapshot = _input_snapshot(Path(workspace).resolve(), sources, includes, root)
    if any(record.get(kind) != value for kind, value in snapshot.items()):
        raise ValueError("Matching build receipt inputs, input_targets or include_directories are stale/incomplete")
    if record.get("logs") != receipt.parent.relative_to(root).as_posix():
        raise ValueError("Matching build receipt logs path does not identify its own directory")
    extra = []
    generated = {}
    if sources[1:] or includes:
        recipe = receipt.parent / "inputs.f"
        local_path(workspace, recipe.relative_to(workspace).as_posix())
        content = "".join(f'"+incdir+{path}"\n' for path in includes) + "".join(f'"{path}"\n' for path in sources[1:])
        if recipe.read_text() != content:
            raise ValueError("Matching build receipt generated inputs.f differs from its declared inputs")
        generated = {"inputs.f": digest(recipe)}
        extra.extend(["--fs", str(recipe)])
    if record.get("generated_inputs") != generated:
        raise ValueError("Matching build receipt generated_inputs are changed or incomplete")
    if options["timing"]:
        extra.extend(["-V", "--timing"])
    for define in options["rtl_defines"]:
        extra.extend(["--rtl-define", define])
    command = record.get("command")
    if not isinstance(command, list) or not command or not isinstance(command[0], str) or not command[0]:
        raise ValueError("Matching build receipt needs the actual build command")
    expected = [command[0], "export", str(sources[0]), *extra, "--sim", "verilator", "--rw", "mem_direct",
                "--sname", options["top"], "--tname", options["export_name"], "--tdir", str(root / record["package"]),
                "-c", "-w", str(receipt.parent / "layout.fst"), "-j", str(options["jobs"])]
    if command != expected:
        raise ValueError("Matching build receipt command differs from its declared build options/paths")
    # jobs and timeout are resource budgets, not native semantics. All other
    # options (including top override, macros and their order) remain distinct.
    return json.dumps({"options": {key: value for key, value in options.items() if key != "jobs"},
                       **snapshot}, sort_keys=True)


def validate_package_receipts(workspace, layout):
    """Return explicit credit and checkable receipt references without upgrading legacy trust.

    Any same-package package_files field selects the strong mode, even on a failed
    attempt. Legacy-only success retains the original wrapper input/recipe level;
    it cannot rule out a same-class, same-input partial replacement. Neither mode
    sorts attempts by time, changes historical files, or proves hardware behavior.
    """
    workspace = Path(workspace).resolve()
    root, dut = layout["root"], layout["dut"]
    package = root / "dut" / dut
    records = []
    for receipt in sorted((root / "results").glob("build-*/build.json")):
        local_path(workspace, receipt.relative_to(workspace).as_posix())
        try:
            record = json.loads(receipt.read_text())
        except (ValueError, OSError) as error:
            raise ValueError(f"Unreadable build receipt {receipt}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"Build receipt is not an object: {receipt}")
        if record.get("package") != f"dut/{dut}":
            command = record.get("command")
            if isinstance(command, list) and any(value == "--tdir" and command[index + 1] == str(package)
                    for index, value in enumerate(command[:-1])):
                raise ValueError(f"Build receipt package conflicts with this DUT's command target: {receipt}")
            continue
        try:
            _hash_map(record.get("inputs"), "inputs")
            for name in record["inputs"]:
                local_path(workspace, name)
            if type(record.get("ok")) is not bool:
                raise ValueError("Build receipt ok must be boolean")
            if "package_files" in record:
                _hash_map(record["package_files"], "package_files")
                if "__init__.py" not in record["package_files"] or any(Path(name).name != name for name in record["package_files"]):
                    raise ValueError("Build receipt package_files must name native package assets including __init__.py")
        except ValueError as error:
            raise ValueError(f"Malformed native build receipt {receipt}: {error}") from error
        records.append((receipt, record))
    if not records:
        return {"credit": "receipt-free-adoption", "package": f"dut/{dut}", "receipts": [],
                "limitations": ["Native class/path structure only; no tool build receipt, build-time output SHA or hardware proof."]}
    output_bound = any("package_files" in record for _, record in records)
    credit = "package-files" if output_bound else "legacy-input-recipe"
    current = package_files(workspace, package) if output_bound else None
    contracts, errors, accepted = set(), [], []
    for receipt, record in records:
        if not record["ok"] or output_bound and record.get("package_files") != current:
            continue
        try:
            contracts.add(_current_contract(workspace, layout, receipt, record))
            accepted.append({"path": receipt.relative_to(root).as_posix(), "sha256": digest(receipt)})
        except (ValueError, KeyError, TypeError, OSError) as error:
            errors.append(f"{receipt}: {error}")
    if not contracts:
        detail = "; ".join(errors) or ("no eligible successful receipt: " + ", ".join(str(path) for path, _ in records))
        boundary = " New-format receipt exists: no fallback to legacy input/recipe credit." if output_bound else ""
        raise ValueError(f"No current native build evidence for dut/{dut} ({credit}): {detail}.{boundary} "
                         "Preserve all build-* history; repair the named inputs/recipe or report the provenance conflict, "
                         "not rename/delete receipts or infer latest from time")
    if len(contracts) != 1:
        raise ValueError(f"Conflicting current native build contracts for dut/{dut} ({credit}): "
                         "multiple valid top/macros/inputs/options recipes: " + ", ".join(row["path"] for row in accepted) +
                         ". Preserve receipts and resolve the declared "
                         "current recipe; neither names nor time determine it")
    limitations = (["Static native identity assets and current input/recipe only; not an ABI or hardware proof."]
                   if output_bound else ["No build-time output SHA; inherits the original wrapper class/path and input/recipe level.",
                   "A later partial package with the same class and inputs is indistinguishable at this legacy level; not a hardware proof."])
    return {"credit": credit, "package": f"dut/{dut}", "receipts": accepted, "limitations": limitations}
