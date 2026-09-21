"""Execute packaged generation/rendering programs and verify their resulting artifacts."""

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
    digest,
    local_path,
    parse_ports,
    read_json,
    receipt,
    source_state,
    validate_evidence,
)

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


def generate(root: Path, module: str, version: str, config: str) -> None:
    """Generate or verify current evidence, retaining the actual RTL independently of caches."""
    folder = local_path(root, f"evidence/{module}/{version}")
    if (folder / "manifest.json").exists():
        validate_evidence(root, module, version, config)
        print("Verified existing evidence; no files overwritten.")
        return
    before = source_state(root)
    result_path = local_path(root, f".cache/generation-{module}-{version}.json")
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
    validate_evidence(root, module, version, config)
    print(f"Generated {folder.relative_to(root)}: {len(ports)} ports")


def main() -> int:
    """Run one action from the installed plugin, never from workspace scripts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "preflight",
            "evidence",
            "metadata",
            "render",
            "validate",
            "lint",
            "cache-check",
        ),
    )
    parser.add_argument("--module", required=True)
    parser.add_argument("--config", default="DefaultConfig")
    parser.add_argument("--version", default="")
    parser.add_argument("--rtl", type=Path)
    parser.add_argument("--change-type", choices=("Major", "Minor", "Patch"))
    parser.add_argument("--summary", default="")
    args = parser.parse_args()
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
            generate(root, args.module, args.version, args.config)
        elif args.action == "metadata":
            from .documents import update_metadata

            update_metadata(
                root,
                args.module,
                args.version,
                args.config,
                args.change_type,
                args.summary,
            )
        elif args.action == "render":
            from .rendering import render

            document = local_path(
                root,
                f"outputs/{args.module}/{args.module}_design_document_zh_{args.version}.md",
            )
            output = local_path(root, f"evidence/{args.module}/{args.version}/diagrams")
            render(document, output)
            manifest = read_json(output / "manifest.json")
            (output / "manifest.json").write_text(
                json.dumps(receipt(root, manifest, sign=True), indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            from .validation import validate

            result = validate(
                root,
                args.module,
                args.version,
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
