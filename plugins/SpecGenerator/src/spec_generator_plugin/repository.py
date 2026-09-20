#!/usr/bin/env python3
"""Check source-repository links, template resources, and packaging from the project root."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path.cwd()
EXCLUDED_PARTS = {
    ".git",
    ".cache",
    ".ucagent",
    "node_modules",
    "third_party",
    "build",
    "dist",
}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def is_repository_owned(path: Path) -> bool:
    """Exclude generated workspaces and build artifacts from source documentation checks."""
    parts = path.relative_to(ROOT).parts
    if not parts or EXCLUDED_PARTS.intersection(parts):
        return False
    if parts[0] in {"inputs", "outputs", "reports", "evidence", "Guide_Doc"}:
        return False
    return True


def main() -> int:
    """Report broken source links and missing or inconsistent plugin resources."""
    if not all((ROOT / name).is_file() for name in ("pyproject.toml", "ucagent-plugin.toml")):
        print("ERROR: Run make repo-lint from the Spec Generator project root.", file=sys.stderr)
        return 1
    errors: list[str] = []
    markdown_files = [path for path in ROOT.rglob("*.md") if is_repository_owned(path)]
    for source in markdown_files:
        for raw in LINK_RE.findall(source.read_text(encoding="utf-8")):
            if raw.startswith(("http://", "https://", "#")):
                continue
            target_text, _, fragment = raw.partition("#")
            target = (source.parent / target_text).resolve()
            if not target.exists():
                errors.append(f"broken link: {source.relative_to(ROOT)} -> {raw}")
                continue
            if fragment.startswith("L") and fragment[1:].isdigit() and target.is_file():
                line_count = sum(
                    1 for _ in target.open(encoding="utf-8", errors="replace")
                )
                if int(fragment[1:]) > line_count:
                    errors.append(
                        f"line out of range: {source.relative_to(ROOT)} -> {raw}"
                    )

    resources = ROOT / "src/spec_generator_plugin"
    template = (
        resources / "Guide_Doc/chip_design_document_template_zh.md"
    )
    if not template.is_file() or not re.search(
        r"^> 模板结构版本：v\d+\.\d+\.\d+$", template.read_text(encoding="utf-8"), re.M
    ):
        errors.append("template structure version missing or invalid")
    if sorted(resources.rglob(template.name)) != [template]:
        errors.append(
            "plugin resources must contain exactly one canonical document template"
        )
    for relative in ("Guide_Doc/generation-guide.md", "workflows/design-document.yaml"):
        if not (resources / relative).is_file():
            errors.append(f"missing plugin resource: {relative}")
    manifest = tomllib.loads((ROOT / "ucagent-plugin.toml").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    if (
        project["entry-points"]["ucagent.plugins"].get(manifest["name"])
        != manifest["entry"]
    ):
        errors.append("source manifest and installed plugin entry point disagree")

    print(
        f"Repository Markdown files={len(markdown_files)}; "
        "module artifacts are validated by the plugin stage checkers"
    )
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
