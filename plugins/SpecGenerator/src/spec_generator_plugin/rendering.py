#!/usr/bin/env python3
"""Render every Mermaid fence in a Markdown document with pinned mmdc."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


from .documents import mermaid_sources


def browser_path() -> str | None:
    """Locate an explicitly configured or installed browser."""
    configured = os.environ.get("MERMAID_BROWSER_PATH") or os.environ.get(
        "PUPPETEER_EXECUTABLE_PATH"
    )
    if configured and Path(configured).is_file():
        return configured
    for command in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
    ):
        resolved = shutil.which(command)
        if resolved:
            return resolved
    if platform.system() == "Darwin":
        candidates = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
    return None


def render(document: Path, output_dir: Path, mmdc: Path | None = None) -> None:
    """Render each source fence; an artifact with no diagrams needs no browser."""
    scripts = Path(__file__).resolve().parent / "scripts"
    text = document.read_text(encoding="utf-8")
    diagrams = mermaid_sources(text)
    if not diagrams:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "document": document.name,
                    "diagram_count": 0,
                    "diagrams": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return

    node_result = subprocess.run(
        ["bash", str(scripts / "bootstrap_node.sh")], text=True, capture_output=True
    )
    if node_result.returncode:
        print(node_result.stderr, file=sys.stderr)
        raise ValueError("Node bootstrap failed")
    node_home = Path(node_result.stdout.strip().splitlines()[-1])
    command_env = os.environ.copy()
    command_env["PATH"] = (
        f"{node_home / 'bin'}{os.pathsep}{command_env.get('PATH', '')}"
    )
    if not mmdc:
        result = subprocess.run(
            ["bash", str(scripts / "bootstrap_mermaid.sh")],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise ValueError("Mermaid render/bootstrap failed")
        mmdc = Path(result.stdout.strip().splitlines()[-1])
    browser = browser_path()
    if not browser:
        result = subprocess.run(
            ["bash", str(scripts / "bootstrap_mermaid_browser.sh")],
            text=True,
            capture_output=True,
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise ValueError("Mermaid render/bootstrap failed")
        browser = result.stdout.strip().splitlines()[-1]

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("diagram-*.svg"):
        stale.unlink()
    manifest_entries: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="mermaid-") as temp_name:
        temp = Path(temp_name)
        config = temp / "puppeteer.json"
        config.write_text(
            json.dumps(
                {"executablePath": browser, "headless": True, "args": ["--no-sandbox"]}
            ),
            encoding="utf-8",
        )
        for index, source in enumerate(diagrams, start=1):
            first = next(
                (line.strip() for line in source.splitlines() if line.strip()),
                "unknown",
            )
            kind = first.split()[0]
            input_path = temp / f"diagram-{index:02d}.mmd"
            output_name = f"diagram-{index:02d}.svg"
            output_path = output_dir / output_name
            input_path.write_text(source, encoding="utf-8")
            command = [
                str(mmdc),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--puppeteerConfigFile",
                str(config),
                "--backgroundColor",
                "transparent",
                "--quiet",
            ]
            result = subprocess.run(
                command, text=True, capture_output=True, env=command_env
            )
            if result.returncode:
                print(
                    f"error: Mermaid diagram {index} ({kind}) failed", file=sys.stderr
                )
                print(result.stderr or result.stdout, file=sys.stderr)
                raise ValueError("Mermaid render/bootstrap failed")
            data = output_path.read_bytes()
            svg = data.decode("utf-8", errors="replace")
            if (
                len(data) < 200
                or "<svg" not in svg
                or "viewBox=" not in svg
                or not re.search(r"<(?:path|rect|g|text)\b", svg)
            ):
                print(
                    f"error: Mermaid diagram {index} rendered an invalid/blank SVG",
                    file=sys.stderr,
                )
                raise ValueError("invalid rendered SVG")
            manifest_entries.append(
                {
                    "index": index,
                    "type": kind,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "output": output_name,
                    "svg_sha256": hashlib.sha256(data).hexdigest(),
                    "svg_bytes": len(data),
                }
            )

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document": document.name,
        "renderer": f"@mermaid-js/mermaid-cli/{os.environ.get('MERMAID_CLI_VERSION', '11.16.0')}",
        "browser": Path(browser).name,
        "diagram_count": len(manifest_entries),
        "diagrams": manifest_entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Rendered {len(manifest_entries)} Mermaid diagram(s) to {output_dir}")


def main() -> int:
    """Provide the maintainer's template-render check using the same renderer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    render(args.document, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
