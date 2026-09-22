"""Own Markdown parsing, the template structure, document paths, and factual metadata."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .evidence import validate_evidence

# Visible table labels shared by metadata synchronization and validation.
FIELDS = {
    "template_version": ["使用模板版本", "使用模板"],
    "xiangshan_commit": ["XiangShan RTL 基线", "XiangShan commit"],
    "config": ["适用配置"],
    "generation_status": ["RTL 生成状态"],
    "date": ["生成日期", "日期"],
}
TEMPLATE = Path(__file__).resolve().parent / "Guide_Doc/chip_design_document_template_zh.md"
MARKDOWN = MarkdownIt("commonmark").enable("table")
METADATA_RE = re.compile(r"<!-- rtl2spec: (.*?) -->", re.S)


def markdown_tokens(text: str) -> list[Token]:
    """Parse actual Markdown blocks and reject unterminated fences."""
    tokens = MARKDOWN.parse(text)
    lines = text.splitlines()
    for token in tokens:
        if token.type != "fence":
            continue
        start, end = token.map
        closing = (
            r"(?:[ \t]*>[ \t]*)*[ \t]*"
            + re.escape(token.markup[0])
            + "{"
            + str(len(token.markup))
            + r",}[ \t]*"
        )
        if end - start < 2 or not re.fullmatch(closing, lines[end - 1]):
            raise ValueError(
                f"unclosed Markdown fence at line {start + 1}; close the block before Check"
            )
    return tokens


def mermaid_sources(text: str) -> list[str]:
    """Extract Mermaid fences for Markdown structure validation."""
    return [
        token.content.rstrip() + "\n"
        for token in markdown_tokens(text)
        if token.type == "fence" and token.info.strip().lower() == "mermaid"
    ]


def prose_text(text: str) -> str:
    """Exclude comments and code blocks from prose-level reference checks."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = text.splitlines()
    for token in markdown_tokens(text):
        if token.type in {"fence", "code_block"}:
            start, end = token.map
            lines[start:end] = [""] * (end - start)
    return "\n".join(lines)


def document_sections(text: str, *, template: bool = False) -> list[dict]:
    """Read top-level headings and each section's own tables, ignoring examples in code."""
    tokens = markdown_tokens(text)
    sections = []
    repeated = None
    for index, token in enumerate(tokens):
        if template and token.type == "html_block":
            marker = re.fullmatch(
                r"<!-- STRUCTURE: repeat min=([01]) -->\s*", token.content
            )
            if marker:
                repeated = int(marker.group(1))
        if token.type == "heading_open" and token.level == 0:
            title = "".join(
                child.content
                for child in tokens[index + 1].children
                if child.type in {"text", "code_inline"}
            )
            sections.append(
                dict(
                    level=int(token.tag[1:]),
                    title=title,
                    line=token.map[0] + 1,
                    tables=0,
                    repeat=repeated is not None,
                    minimum=1 if repeated is None else repeated,
                )
            )
            repeated = None
        elif token.type == "table_open" and token.level == 0:
            if not sections:
                sections.append(
                    dict(
                        level=0,
                        title="",
                        line=token.map[0] + 1,
                        tables=0,
                        repeat=False,
                        minimum=1,
                    )
                )
            sections[-1]["tables"] += 1
    return sections


def validate_structure(text: str, module: str) -> list[dict]:
    """Match heading titles/levels/order and per-section table counts to the sole template."""
    expected = document_sections(TEMPLATE.read_text(encoding="utf-8"), template=True)
    observed = document_sections(text)
    errors = []
    position = 0
    for section in expected:
        # Only bracketed template values vary; fixed titles and levels remain exact.
        title = section["title"].replace("[DUT]", module)
        parts = re.split(r"\[[^\]]+\]", title)
        pattern = r"[^\[\]\n]+".join(re.escape(part) for part in parts)
        count = 0
        while position < len(observed):
            current = observed[position]
            if current["level"] != section["level"] or not re.fullmatch(
                pattern, current["title"]
            ):
                break
            if current["tables"] != section["tables"]:
                errors.append(
                    dict(
                        error="table count differs from the template in this section",
                        line=current["line"],
                        section=current["title"],
                        expected=section["tables"],
                        observed=current["tables"],
                    )
                )
            position += 1
            count += 1
            if not section["repeat"]:
                break
        if count < section["minimum"]:
            current = observed[position] if position < len(observed) else None
            errors.append(
                dict(
                    error="heading missing, renamed, at the wrong level, or out of order",
                    expected={"level": section["level"], "title": title},
                    observed={key: current[key] for key in ("level", "title", "line")}
                    if current
                    else "end of document",
                )
            )
            break
    else:
        if position < len(observed):
            errors.append(
                dict(
                    error="extra heading outside a template repeat block",
                    observed=observed[position],
                )
            )
    for error in errors:
        error["next_action"] = (
            "Follow Guide_Doc/chip_design_document_template_zh.md: restore the indicated heading/order/table count; retain inapplicable sections with a reason."
        )
    return errors


def template_version() -> str:
    """Read the sole current template version from the bundled writing reference."""
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"^> .*?(v\d+\.\d+\.\d+)\s*$", text, re.M)
    if not match:
        raise ValueError("plugin template version missing; reinstall the plugin")
    return match.group(1)


def artifact_paths(root: Path, module: str) -> tuple[Path, Path]:
    """Return the current design document and quality report paths."""
    from .evidence import local_path

    return tuple(
        local_path(root, path)
        for path in (
            f"outputs/{module}/{module}_design_document_zh.md",
            f"reports/{module}/{module}_document_quality_review.md",
        )
    )


def require_clean_output(root: Path, module: str, output_dir: str | None = None) -> None:
    """Refuse generation if a module artifact directory or selected output contains data."""
    from .evidence import local_path

    root = root.resolve()
    directories = [f"outputs/{module}", f"reports/{module}", f"evidence/{module}"]
    if output_dir is not None and output_dir not in directories:
        directories.append(output_dir)
    occupied = []
    for name in directories:
        path = local_path(root, name)
        # Check directory entries without following child symlinks or reading old content.
        if path.is_dir():
            if next(path.iterdir(), None) is not None:
                occupied.append(name)
        elif path.exists() or (root / name).is_symlink():
            occupied.append(name)
    if occupied:
        raise FileExistsError(
            "RTL2Spec generation stopped: existing output in "
            + ", ".join(occupied)
            + ". Ask the user to package/archive the previous documents, quality report "
            "and evidence, then clear these output directories and restart. "
            "Do not delete, overwrite or archive the files automatically."
        )


def update_metadata(
    root: Path,
    module: str,
    config: str,
) -> None:
    """Add current evidence metadata to the design document and quality report."""
    manifest, _ = validate_evidence(root, module, config)
    design, report = artifact_paths(root, module)
    texts = [path.read_text(encoding="utf-8") for path in (design, report)]
    values = {
        key: manifest[key]
        for key in (
            "module",
            "config",
            "xiangshan_commit",
            "rtl_sha256",
            "generation_status",
        )
    }
    values.update(
        template_version=template_version(),
        date=date.today().isoformat(),
    )
    marker = (
        "<!-- rtl2spec: "
        + json.dumps(values, ensure_ascii=False, sort_keys=True)
        + " -->"
    )
    for index in range(2):
        text = texts[index]
        for field, labels in FIELDS.items():
            for label in labels:
                pattern = rf"^(\s*\|\s*{re.escape(label)}\s*\|\s*)(.*?)(\s*\|\s*)$"

                # Update recognized factual cells only; their presence is optional.
                def replace(match, field=field):
                    """Preserve annotations while updating the first factual token."""
                    cell = match.group(2)
                    value = str(values[field])
                    if field == "template_version":
                        cell = (
                            re.sub(r"v\d+\.\d+\.\d+", value, cell)
                            if re.search(r"v\d+\.\d+\.\d+", cell)
                            else value
                        )
                    elif field in {"xiangshan_commit", "config"} and "`" in cell:
                        cell = re.sub(r"`[^`]*`", lambda _: f"`{value}`", cell, count=1)
                    elif field == "generation_status":
                        cell = re.sub(r"^\w+", value, cell)
                    else:
                        cell = value
                    return match.group(1) + cell + match.group(3)

                text = re.sub(pattern, replace, text, flags=re.M)
        text = re.sub(
            r"SHA-256\s+`[0-9a-f]{64}`",
            lambda _: f"SHA-256 `{values['rtl_sha256']}`",
            text,
        )
        text = METADATA_RE.sub("", text).strip()
        texts[index] = "\n" + text + "\n\n" + marker + "\n"
    for path, text in zip((design, report), texts):
        path.write_text(text, encoding="utf-8")
    print(
        "Updated document metadata; content and signoff conclusions require author review."
    )
