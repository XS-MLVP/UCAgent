#!/usr/bin/env python3
"""Prepare one shared module input for the default and Bug Review workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


TEXT_SUFFIXES = {
    ".md", ".py", ".txt", ".yaml", ".yml", ".json", ".ini", ".cfg",
    ".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl", ".scala", ".f",
}
RTL_SUFFIXES = {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl", ".scala", ".f"}
IGNORED_PARTS = {
    ".git", ".ucagent", "__pycache__", ".pytest_cache", ".venv", "venv",
    "build", "dist", "output", "results", "coverage", "uc_test_report", "unity_test",
}


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one copied input file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _launch_dut(source: Path) -> str:
    """Read the DUT name from a module launch manifest when one is present."""
    for filename in ("launch.yaml", "launch.yml"):
        manifest = source / filename
        if not manifest.is_file():
            continue
        try:
            import yaml

            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception as error:
            raise SystemExit(f"failed to read {manifest}: {error}") from error
        if isinstance(data, dict):
            for key in ("dut", "dut_name", "target_dut", "module"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return source.name.removeprefix("workspace_")


def _is_ignored(path: Path, root: Path, dut: str) -> bool:
    """Return whether a path belongs to generated or runtime-only material."""
    relative = path.relative_to(root)
    if any(part in IGNORED_PARTS or part.startswith("toffee_tmp_") for part in relative.parts):
        return True
    return bool(relative.parts and relative.parts[0] == dut and len(relative.parts) > 1)


def _copy_module_text(source: Path, target: Path) -> None:
    """Copy module-level launch, requirement, and helper text files."""
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES - RTL_SUFFIXES:
            shutil.copy2(path, target / path.name)


def _copy_rtl(rtl: Path, target: Path, dut: str) -> list[Path]:
    """Copy RTL and filelist inputs into the shared module root."""
    copied: list[Path] = []
    for path in sorted(rtl.rglob("*")):
        if not path.is_file() or path.is_symlink() or _is_ignored(path, rtl, dut):
            continue
        if path.name.lower() != "filelist.txt" and path.suffix.lower() not in RTL_SUFFIXES:
            continue
        relative = path.relative_to(rtl)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(destination)
    return copied


def _copy_legacy_bug_reports(source: Path, target: Path, dut: str) -> list[Path]:
    """Preserve legacy Bug reports for explicit LLM re-analysis."""
    copied: list[Path] = []
    unity_test = source / "unity_test"
    for path in sorted(unity_test.rglob("*.md")):
        if not path.is_file() or path.is_symlink() or "tests" in path.relative_to(unity_test).parts:
            continue
        name = path.name.lower()
        if "bug" not in name or not ("analysis" in name or "summary" in name or "report" in name):
            continue
        if "static_bug_analysis" in name:
            continue
        relative = path.relative_to(unity_test)
        canonical_names = {f"{dut}_bug_analysis.md", f"{dut}_bug_summary.md"}
        if len(relative.parts) == 1 and path.name in canonical_names:
            continue
        destination = target / "unity_test" / relative
        if path.name not in canonical_names and len(relative.parts) == 1:
            destination = target / "unity_test" / "legacy_reports" / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(destination)
    return copied


def main() -> int:
    """Copy a default-style module directory and record its immutable RTL inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True,
                        help="module directory in the examples/Adder layout")
    parser.add_argument("--rtl", type=Path, default=None,
                        help="optional RTL root; defaults to --source")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--dut", default=None)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    root = args.input_root.expanduser().resolve()
    dut = (args.dut or _launch_dut(source)).strip()
    rtl = (args.rtl or source).expanduser().resolve()
    if not source.is_dir() or not source.joinpath("unity_test/tests").is_dir():
        raise SystemExit(f"source must be a module directory with unity_test/tests: {source}")
    if not rtl.is_dir():
        raise SystemExit(f"RTL root does not exist: {rtl}")
    if not dut or not all(char.isalnum() or char in "_.-" for char in dut):
        raise SystemExit(f"invalid DUT name: {dut!r}")

    target = root / f"workspace_{dut}"
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise SystemExit("input target and source must be separate")
    target.mkdir(parents=True, exist_ok=True)
    for stale in (target / "unity_test", target / "reference_rtl", target / "prepare_manifest.json"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()

    (target / "unity_test/tests").mkdir(parents=True, exist_ok=True)
    if source.joinpath("AGENTS.md").is_file():
        shutil.copy2(source / "AGENTS.md", target / "AGENTS.md")
    _copy_module_text(source, target)
    for item in source.joinpath("unity_test").iterdir():
        if item.name == "tests" or not item.is_file() or item.suffix.lower() not in TEXT_SUFFIXES:
            continue
        shutil.copy2(item, target / "unity_test" / item.name)
    for item in source.joinpath("unity_test/tests").rglob("*"):
        if item.is_file() and item.suffix.lower() in TEXT_SUFFIXES:
            destination = target / "unity_test/tests" / item.relative_to(source.joinpath("unity_test/tests"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)

    legacy_reports = _copy_legacy_bug_reports(source, target, dut)
    canonical_reports = {
        "summary": target / "unity_test" / f"{dut}_bug_summary.md",
        "analysis": target / "unity_test" / f"{dut}_bug_analysis.md",
    }
    report_reanalysis_required = [
        kind for kind, path in canonical_reports.items() if not path.is_file()
    ]

    rtl_files = _copy_rtl(rtl, target, dut)
    filelists = [path for path in rtl_files
                 if path.name.lower() == "filelist.txt" or path.suffix.lower() == ".f"]
    source_files = [path for path in rtl_files if path.suffix.lower() in RTL_SUFFIXES - {".f"}]
    if not filelists and not source_files:
        raise SystemExit(
            f"no RTL source or filelist found under {rtl}; provide filelist.txt when no top .v/.sv is present"
        )
    for filelist in filelists:
        if not any(line.strip() and not line.lstrip().startswith(("//", "#"))
                   for line in filelist.read_text(encoding="utf-8", errors="replace").splitlines()):
            raise SystemExit(f"filelist is empty: {filelist}")

    manifest = {
        "schema": "bug_review_input.v2",
        "dut": dut,
        "source": str(source),
        "rtl_source": str(rtl),
        "layout": "examples-style",
        "bug_reports": {
            "canonical": {
                kind: str(path.relative_to(target)) if path.is_file() else ""
                for kind, path in canonical_reports.items()
            },
            "reanalysis_required": report_reanalysis_required,
            "preserved_legacy_reports": [str(path.relative_to(target)) for path in legacy_reports],
        },
        "picker": {
            "filelists": [str(path.relative_to(target)) for path in filelists],
            "main_rtl_required": not bool(filelists),
        },
        "rtl_files": [
            {"path": str(path.relative_to(target)), "sha256": sha256(path)}
            for path in rtl_files
        ],
    }
    (target / "prepare_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "workspace": str(target),
        "dut": dut,
        "layout": "examples-style",
        "rtl_files": len(rtl_files),
        "filelists": [str(path.relative_to(target)) for path in filelists],
        "tests": len(list((target / "unity_test/tests").rglob("*.py"))),
        "bug_report_reanalysis_required": report_reanalysis_required,
        "preserved_legacy_reports": [str(path.relative_to(target)) for path in legacy_reports],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
