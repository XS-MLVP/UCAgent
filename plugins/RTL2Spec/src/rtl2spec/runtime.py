"""Execute packaged RTL evidence and document validation programs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .evidence import (
    collect_related_sources,
    digest,
    local_path,
    parse_ports,
    RELATED_SOURCES_KEY,
    read_json,
    receipt,
    validate_evidence,
    source_state,
)
from .documents import require_clean_output

SCRIPTS = Path(__file__).resolve().parent / "scripts"


def check_cache(root: Path, rtl: Path, module: str, config: str) -> dict:
    """Permit reuse only of cache bytes attested by a previous successful tool execution."""
    manifest = read_json(local_path(root, rtl.parent.parent / f"{module}.receipt.json"))
    receipt(root, manifest)
    if (
        manifest.get("module"),
        manifest.get("config"),
        manifest.get("rtl_sha256"),
        manifest.get("source_state"),
    ) != (module, config, digest(local_path(root, rtl)), source_state(root)):
        raise ValueError(
            f"{rtl}: cached RTL receipt does not match the source/configuration/content"
        )
    return manifest


def generate(root: Path, module: str, config: str) -> None:
    """Generate fresh evidence, retaining the actual RTL independently of caches."""
    require_clean_output(root, module)
    folder = local_path(root, f"evidence/{module}")
    before = source_state(root)
    result_path = local_path(root, f".cache/generation-{module}.json")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.unlink(missing_ok=True)
    subprocess.run(
        [
            "bash",
            str(SCRIPTS / "generate_rtl.sh"),
            "--module",
            module,
            "--config",
            config,
            "--result",
            str(result_path),
        ],
        check=True,
    )
    result = read_json(result_path)
    if source_state(root) != before:
        raise ValueError(
            "third_party/XiangShan: source changed during generation; retry with stable source"
        )
    rtl = local_path(root, result["rtl"])
    if result.get("cache_reused"):
        verified = check_cache(root, rtl, module, config)
        for key in ("generation_status", "command", "generator_flags", "tool_versions"):
            result[key] = verified[key]
    data = rtl.read_bytes()
    ports = parse_ports(data.decode("utf-8"), module)
    if not ports:
        raise ValueError(f"{rtl}: generation produced no ports")
    # Recheck after the compiler returns so newly arrived output is preserved.
    require_clean_output(root, module)
    manifest = receipt(
        root,
        {
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "module": module,
            "config": config,
            "source_state": before,
            "xiangshan_commit": before["commit"],
            "generation_status": result["generation_status"],
            "command": result["command"],
            "generator_flags": result["generator_flags"],
            "tool_versions": result["tool_versions"],
            RELATED_SOURCES_KEY: [],
            "rtl_source": f"{module}.sv",
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
    folder.mkdir(parents=True, exist_ok=True)
    local_path(root, folder / f"{module}.sv").write_bytes(data)
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
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    # Publish the receipt last: interrupted writes cannot look like completed evidence.
    local_path(root, rtl.parent.parent / f"{module}.receipt.json").write_text(
        payload, encoding="utf-8"
    )
    local_path(root, folder / "manifest.json").write_text(payload, encoding="utf-8")
    validate_evidence(root, module, config)
    print(f"Generated {folder.relative_to(root)}: {len(ports)} ports")


def record_related_sources(
    root: Path, module: str, config: str, related_modules: list[str]
) -> None:
    """Record signed source evidence for related modules in the current manifest."""
    manifest, _ = validate_evidence(root, module, config)
    additions = collect_related_sources(root, module, related_modules)
    manifest[RELATED_SOURCES_KEY] = additions
    signed = receipt(root, manifest, sign=True)
    folder = local_path(root, f"evidence/{module}")
    local_path(root, folder / "manifest.json").write_text(
        json.dumps(signed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_evidence(root, module, config)
    print(
        f"Recorded {len(additions)} related module source(s) in "
        f"{folder.relative_to(root)}/manifest.json"
    )


def main() -> int:
    """Run one action from the installed plugin, never from workspace scripts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "preflight",
            "evidence",
            "related_sources",
            "metadata",
            "validate",
            "lint",
            "cache-check",
        ),
    )
    parser.add_argument("--module", required=True)
    parser.add_argument("--config", default="DefaultConfig")
    parser.add_argument("--rtl", type=Path)
    parser.add_argument("--related-module", action="append", default=[])
    args = parser.parse_args()
    if args.action != "related_sources" and args.related_module:
        parser.error("--related-module is only valid with related_sources")
    if args.action == "related_sources" and not args.related_module:
        parser.error("related_sources requires at least one --related-module")
    root = Path.cwd().resolve()
    os.environ.update(
        RTL2SPEC_WORKSPACE=str(root),
        XIANGSHAN_ROOT=str(root / "third_party/XiangShan"),
        RTL2SPEC_CACHE=str(root / ".cache"),
    )
    try:
        if args.action == "cache-check":
            check_cache(root, args.rtl, args.module, args.config)
        elif args.action == "preflight":
            require_clean_output(root, args.module)
            source_state(root)
            subprocess.run(
                [
                    "bash",
                    str(SCRIPTS / "preflight.sh"),
                    "--module",
                    args.module,
                    "--config",
                    args.config,
                ],
                check=True,
            )
        elif args.action == "evidence":
            generate(root, args.module, args.config)
        elif args.action == "related_sources":
            record_related_sources(
                root, args.module, args.config, args.related_module
            )
        elif args.action == "metadata":
            from .documents import update_metadata

            update_metadata(root, args.module, args.config)
        else:
            from .validation import validate

            result = validate(
                root,
                args.module,
                args.config,
                "final" if args.action == "lint" else "draft",
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
