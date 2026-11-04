"""Summarize selected-language RTL sources without building the test DUT."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ucagent.util.config import load_runtime_config


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one regular source file."""

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    """Print a bounded source summary and leave RTL validation to Check."""

    workspace = Path(os.getcwd()).resolve()
    runtime = load_runtime_config(str(workspace))
    plugin_options = runtime.get("plugin_options", {})
    language = plugin_options.get("design_with_ppa.rtl.language")
    source_glob = plugin_options.get("design_with_ppa.rtl.source_glob")
    if not isinstance(language, str) or not language:
        raise ValueError("Runtime config has no selected RTL language")
    if not isinstance(source_glob, str) or not source_glob:
        raise ValueError("Runtime config has no selected RTL source glob")
    source_pattern = Path(source_glob)
    if source_pattern.is_absolute() or ".." in source_pattern.parts:
        raise ValueError("Runtime RTL source glob must remain workspace-relative")
    sources = [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": _sha256(path),
        }
        for path in sorted(workspace.glob(source_glob))
        if path.is_file() and not path.is_symlink()
    ]
    payload = {
        "schema_version": "1.0",
        "status": "ready_for_check" if sources else "missing_rtl",
        "dut": runtime["DUT"],
        "rtl_language": language,
        "source_glob": source_glob,
        "rtl_sources": sources,
        "resolved_optimization_minimum": runtime.get("plugin_options", {}).get(
            "design_with_ppa.min_optimization_iterations"
        ),
        "resolved_optimization_maximum": runtime.get("plugin_options", {}).get(
            "design_with_ppa.max_optimization_iterations"
        ),
        "no_improvement_patience": runtime.get("plugin_options", {}).get(
            "design_with_ppa.no_improvement_patience"
        ),
        "next_action": (
            "Call Check or Complete to perform the authoritative RTL validation."
            if sources
            else f"Create the {language} top and required submodules matching {source_glob}."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
