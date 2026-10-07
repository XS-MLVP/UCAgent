"""Create Bug Review input directories from explicit manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

import yaml


SCHEMA = "bug_review_input.v1"


def _source_file(root: Path, value: str) -> Path:
    """Resolve one ordinary source file without escaping its root."""
    relative = Path(value)
    if relative.is_absolute() or not value or ".." in relative.parts:
        raise ValueError(f"path must be relative to {root}: {value}")
    path = root / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"source file missing or unsafe: {path}")
    return path


def _init(args: argparse.Namespace) -> None:
    """Create an input manifest skeleton for the reviewer to fill."""
    dut = args.dut
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dut):
        raise ValueError("dut must be a Python package identifier")
    source = Path(args.source_workspace).expanduser().resolve()
    rtl = Path(args.rtl_root).expanduser().resolve()
    if not (source / "unity_test/tests").is_dir() or not rtl.is_dir():
        raise ValueError("source needs unity_test/tests and rtl-root must be a directory")
    manifest = Path(args.manifest).expanduser().absolute()
    if manifest.exists():
        raise FileExistsError(manifest)
    data = {"schema": SCHEMA, "dut": dut, "module": dut,
            "source_workspace": str(source), "rtl_root": str(rtl), "rtl_top": "", "rtl_files": [],
            "spec_files": [], "copy_runtime_package": False}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest)


def _apply(args: argparse.Namespace) -> None:
    """Copy selected input files and write the Picker file list."""
    data = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"manifest schema must be {SCHEMA}")
    dut = data["dut"]
    if not isinstance(dut, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dut):
        raise ValueError("manifest dut is invalid")
    module = data.get("module", dut)
    if not isinstance(module, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module):
        raise ValueError("manifest module is invalid")
    source = Path(data["source_workspace"]).expanduser().resolve()
    rtl_root = Path(data["rtl_root"]).expanduser().resolve()
    if not (source / "unity_test/tests").is_dir() or not rtl_root.is_dir():
        raise ValueError("source workspace or RTL root is missing")
    top = data["rtl_top"]
    files = data["rtl_files"]
    specs = data["spec_files"]
    if (not isinstance(top, str) or not isinstance(files, list) or not files
            or not all(isinstance(item, str) for item in files)
            or top not in files or len(files) != len(set(files))):
        raise ValueError("rtl_top must occur exactly once in nonempty rtl_files")
    if (not isinstance(specs, list) or not all(isinstance(item, str) for item in specs)
            or len(specs) != len(set(specs))):
        raise ValueError("spec_files must be a list of relative file paths")
    if any(Path(item).suffix.lower() not in {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"}
           for item in files):
        raise ValueError("rtl_files must contain HDL source files")
    if not isinstance(data["copy_runtime_package"], bool):
        raise ValueError("copy_runtime_package must be boolean")
    rtl_paths = [_source_file(rtl_root, item) for item in files]
    spec_paths = [_source_file(source, item) for item in specs]
    if any(Path(item).parts[0] == "unity_test" for item in specs):
        raise ValueError("spec_files must not repeat files already copied from unity_test")
    runtime = source / dut
    if data["copy_runtime_package"] and not runtime.is_dir():
        raise ValueError(f"DUT runtime package missing: {runtime}")
    target = Path(args.inputs_root).expanduser().resolve() / dut
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError(f"target exists or overlaps source workspace: {target}")
    target.mkdir(parents=True)
    shutil.copytree(source / "unity_test", target / "unity_test",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "uc_test_report", "toffee_tmp_*"))
    for item, path in zip(specs, spec_paths):
        destination = target / item
        if destination.exists():
            raise ValueError(f"spec file would replace copied unity_test file: {item}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    rtl_target = target / "rtl"
    for item, path in zip(files, rtl_paths):
        destination = rtl_target / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    ordered = [top, *(item for item in files if item != top)]
    (target / "filelist.f").write_text(
        "\n".join(f"rtl/{item}" for item in ordered) + "\n", encoding="utf-8")
    launch = {"dut": dut, "module": module, "files": {"filelist": "filelist.f"}}
    (target / "launch.yaml").write_text(yaml.safe_dump(launch, sort_keys=False), encoding="utf-8")
    if data["copy_runtime_package"]:
        shutil.copytree(runtime, target / dut,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "toffee_tmp_*"))
    print(json.dumps({"workspace": str(target), "rtl_files": len(files),
                      "runtime_package": data["copy_runtime_package"]}, ensure_ascii=False))


def _complete(args: argparse.Namespace) -> None:
    """Add only missing launch and RTL files to an existing input workspace."""
    data = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"manifest schema must be {SCHEMA}")
    dut = data["dut"]
    if not isinstance(dut, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", dut):
        raise ValueError("manifest dut must be a Python package identifier")
    module = data.get("module", dut)
    if not isinstance(module, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module):
        raise ValueError("manifest module is invalid")
    target = Path(args.workspace).expanduser().resolve()
    rtl_root = Path(data["rtl_root"]).expanduser().resolve()
    if target.name != dut or not (target / "unity_test/tests").is_dir():
        raise ValueError(f"expected an existing inputs/{dut} with unity_test/tests: {target}")
    files = data["rtl_files"]
    top = data["rtl_top"]
    if (not isinstance(files, list) or not files or top not in files
            or len(files) != len(set(files))):
        raise ValueError("rtl_top must occur in unique, nonempty rtl_files")
    paths = [_source_file(rtl_root, item) for item in files]
    launch_path = target / "launch.yaml"
    ordered = [top, *(item for item in files if item != top)]
    expected_filelist = "\n".join(f"rtl/{item}" for item in ordered) + "\n"
    declared = None
    if launch_path.exists():
        existing_launch = yaml.safe_load(launch_path.read_text(encoding="utf-8"))
        if (not isinstance(existing_launch, dict)
                or existing_launch.get("dut") != dut
                or existing_launch.get("module") != module
                or not isinstance(existing_launch.get("files"), dict)
                or existing_launch["files"].get("filelist") not in ("filelist.f", "filelist.txt")):
            raise ValueError(f"existing launch settings differ from selected module; review {launch_path}")
        declared = existing_launch["files"]["filelist"]
    filelist = target / (declared or "filelist.f")
    if filelist.exists() and filelist.read_text(encoding="utf-8") != expected_filelist:
        raise ValueError(f"existing filelist differs from selected RTL; review {filelist}")
    launch = {"dut": dut, "module": module, "files": {"filelist": filelist.name}}
    for item, source in zip(files, paths):
        destination = target / "rtl" / item
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError(f"existing RTL differs from selected source; review {destination}")
    for item, source in zip(files, paths):
        destination = target / "rtl" / item
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    if not filelist.exists():
        filelist.write_text(expected_filelist, encoding="utf-8")
    if not launch_path.exists():
        launch_path.write_text(yaml.safe_dump(launch, sort_keys=False), encoding="utf-8")
    print(json.dumps({"workspace": str(target), "rtl_files": len(files),
                      "launch": str(launch_path)}, ensure_ascii=False))


def main() -> None:
    """Dispatch input manifest creation, copying, or completion."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create an editable input manifest")
    init.add_argument("--source-workspace", required=True)
    init.add_argument("--rtl-root", required=True)
    init.add_argument("--dut", required=True)
    init.add_argument("--manifest", required=True)
    apply = commands.add_parser("apply", help="copy files named by the filled manifest")
    apply.add_argument("--manifest", required=True)
    apply.add_argument("--inputs-root", required=True)
    complete = commands.add_parser("complete", help="add missing launch materials to an existing input")
    complete.add_argument("--manifest", required=True)
    complete.add_argument("--workspace", required=True)
    args = parser.parse_args()
    {"init": _init, "apply": _apply, "complete": _complete}[args.command](args)


if __name__ == "__main__":
    main()
