"""Own Markdown parsing, the template structure, document paths, and factual metadata."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.rules_block.table import escapedSplit

from .evidence import local_path, output_root, validate_evidence
from .generic_evidence import validate_generic_evidence
from .sv_frontend import port_shape

# Localized artifact labels live with the runtime writing resources.
TEMPLATE = Path(__file__).resolve().parent / "Guide_Doc/chip_design_document_template_zh.md"
ARTIFACT_TEXT = json.loads(TEMPLATE.with_name("artifact-templates.json").read_text(encoding="utf-8"))
FIELDS = ARTIFACT_TEXT["metadata_fields"]
MARKDOWN = MarkdownIt("commonmark").enable("table")
METADATA_RE = re.compile(r"<!-- rtl2spec: (.*?) -->", re.S)
RELATED_SOURCES_START = "<!-- rtl2spec-related-sources:start -->"
RELATED_SOURCES_END = "<!-- rtl2spec-related-sources:end -->"


def markdown_rows(text: str) -> list[dict]:
    """Read real table cells with line numbers, excluding quoted and fenced examples."""
    rows = []
    row = None
    table = False
    header = False
    lines = text.splitlines()
    for token in markdown_tokens(text):
        if token.type == "table_open":
            table = token.level == 0
        elif token.type == "table_close":
            table = False
        elif token.type == "thead_open":
            header = True
        elif token.type == "thead_close":
            header = False
        elif table and token.type == "tr_open":
            raw = lines[token.map[0]].strip()
            raw_cells = escapedSplit(raw)
            if raw.startswith("|"):
                raw_cells.pop(0)
            if raw.endswith("|") and not raw.endswith("\\|"):
                raw_cells.pop()
            row = {"line": token.map[0], "cells": [], "header": header, "raw_count": len(raw_cells)}
        elif table and token.type == "inline" and row is not None:
            row["cells"].append(token.content)
        elif table and token.type == "tr_close" and row is not None:
            rows.append(row)
            row = None
    return rows


def appendix_rows(text: str) -> list[dict]:
    """Return Appendix A interface rows with their exact original cell contents."""
    sections = document_sections(text)
    section = next((s for s in sections if s["title"] == ARTIFACT_TEXT["appendix_title"]), None)
    if section is None:
        return []
    end = next((s["line"] for s in sections if s["line"] > section["line"] and s["level"] <= 2), len(text.splitlines()) + 1)
    return [r for r in markdown_rows(text) if not r["header"] and section["line"] <= r["line"] < end - 1
            and r["cells"] and re.fullmatch(r"`?IO-[A-Z0-9-]+`?", r["cells"][0])]


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
            # Repeated behavior and scenario headings are part of the public
            # contract; formal artifacts cannot carry template HTML comments.
            intrinsic_repeat = (
                title.startswith("P-[NAME]") or title.startswith("CASE-[NAME]")
            )
            sections.append(
                dict(
                    level=int(token.tag[1:]),
                    title=title,
                    line=token.map[0] + 1,
                    tables=0,
                    repeat=intrinsic_repeat or repeated is not None,
                    minimum=(
                        0
                        if title.startswith("CASE-[NAME]")
                        else 1
                        if repeated is None
                        else repeated
                    ),
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
    """Match required headings/order and minimum table counts to the template."""
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
            if current["tables"] < section["tables"]:
                errors.append(
                    dict(
                        error="table count is below the template minimum in this section",
                        line=current["line"],
                        section=current["title"],
                        expected_minimum=section["tables"],
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
            "Follow Guide_Doc/chip_design_document_template_zh.md: restore the indicated heading/order/minimum table; retain inapplicable sections with a reason. Additional evidence tables are allowed when they do not redefine an existing fact."
        )
    return errors


def template_version() -> str:
    """Read the sole current template version from the bundled writing reference."""
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"^> .*?(v\d+\.\d+\.\d+)\s*$", text, re.M)
    if not match:
        raise ValueError("plugin template version missing; reinstall the plugin")
    return match.group(1)


def artifact_paths(
    root: Path, module: str, output_dir: str = "outputs"
) -> tuple[Path, Path]:
    """Return the current design document and quality report paths."""
    from .evidence import local_path, output_root

    folder = output_root(root, output_dir)
    return tuple(
        local_path(root, folder / path)
        for path in (
            f"{module}_design_document_zh.md",
            f"{module}_document_quality_review.md",
        )
    )


def require_clean_output(root: Path, output_dir: str = "outputs") -> None:
    """Refuse a new run when its selected output directory contains any prior data."""
    from .evidence import output_root

    root = root.resolve()
    path = output_root(root, output_dir)
    # Do not read or follow old children while checking for an occupied run directory.
    occupied = next(path.iterdir(), None) is not None if path.is_dir() else (
        path.exists() or (root / output_dir).is_symlink()
    )
    if occupied:
        raise FileExistsError(
            "RTL2Spec generation stopped: existing output in "
            + output_dir
            + ". Ask the user to package/archive the previous documents, quality report "
            "and evidence, then clear this output directory or select a new --output and restart. "
            "Do not delete, overwrite or archive the files automatically."
        )


def port_scaffold_text(root: Path, module: str, ports: list[dict], *, generic: bool = False,
                       output_dir: str = "outputs") -> str:
    """Render the protected port scaffold from current parsed facts without writing it."""
    locations = port_locations(root, module, ports, generic=generic, output_dir=output_dir)
    lines = ["", "# " + ARTIFACT_TEXT["ports_title"], "", ARTIFACT_TEXT["ports_instruction"], "",
             "| " + " | ".join(ARTIFACT_TEXT["port_header"]) + " |",
             "| " + " | ".join(["---"] * 9) + " |"]
    for port in ports:
        path, line = locations[port['name']][0]
        location = f"{path}:{line}"
        cells = [f"`IO-{port['index']:03d}`", "TODO", "TODO", f"`{location}`",
                 f"`{port_shape(port)}`", "Generated", f"`{port['name']}`", "TODO", "`E-RTL-PORTS`"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def generate_port_scaffold(root: Path, module: str, config: str, *, generic: bool = False,
                           output_dir: str = "outputs") -> Path:
    """Generate factual Appendix A cells from verified ports, leaving only prose to fill."""
    validator = validate_generic_evidence if generic else validate_evidence
    _, ports = validator(root, module, config, output_dir)
    folder = local_path(root, output_root(root, output_dir) / "evidence")
    target = local_path(root, folder / "ports.md")
    target.write_text(port_scaffold_text(root, module, ports, generic=generic, output_dir=output_dir), encoding="utf-8")
    return target


def port_locations(root: Path, module: str, ports: list[dict], *, generic: bool = False,
                   output_dir: str = "outputs") -> dict[str, list[tuple[str, int]]]:
    """Locate each port in verified RTL and equivalent captured/original source views."""
    from .verilog import strip_comments

    folder = f"{output_dir}/evidence"
    paths = [f"{folder}/{module}.sv"]
    source_map = None
    original_top = None
    if generic:
        paths = [f"{folder}/{module}.preprocessed.sv"]
        source_map = json.loads(local_path(root, f"{folder}/source_map.json").read_text(encoding="utf-8"))
        original_top = json.loads(local_path(root, f"{folder}/manifest.json").read_text(encoding="utf-8"))['rtl_source']
    result = {port['name']: [] for port in ports}
    for path in paths:
        text = strip_comments(local_path(root, path).read_text(encoding="utf-8"))
        declaration = re.search(rf"\bmodule\s+{re.escape(module)}\b", text)
        if declaration is None:
            continue
        end = re.search(r"\bendmodule\b", text[declaration.end():])
        body = text[declaration.end():declaration.end() + end.start()] if end else text[declaration.end():]
        for port in ports:
            name = port['name']
            if generic and isinstance(port.get('source_line'), int):
                ranges = [
                    (port.get('header_line', port['source_line']), port.get('header_end_line', port['source_line'])),
                    (port['source_line'], port.get('source_end_line', port['source_line'])),
                ]
                for line, end_line in ranges:
                    if not isinstance(line, int) or not isinstance(end_line, int) or not 1 <= line <= len(text.splitlines()) or end_line < line:
                        raise ValueError(f"Invalid AST source range for port {name}: {line}-{end_line}")
                    if source_map is not None and path == paths[0]:
                        for mapped_line in range(line, min(end_line, len(source_map)) + 1):
                            origin = source_map[mapped_line - 1]
                            result[name].append((origin['path'], origin['line']))
                            if origin['path'] == original_top:
                                result[name].append((f"{folder}/{module}.sv", origin['line']))
                    result[name].append((path, line))
                continue
            pattern = rf"(?<![\w$]){re.escape(name)}(?![\w$])"
            match = re.search(pattern, body)
            positions = {match.start()} if match else set()
            # Non-ANSI ports have both a header name and a body direction declaration.
            for part in re.finditer(r'\b(?:input|output|inout)\b[^;]*;', body):
                positions.update(part.start() + m.start() for m in re.finditer(pattern, part.group()))
            for position in sorted(positions):
                line = text.count("\n", 0, declaration.end() + position) + 1
                if source_map is not None and path == paths[0]:
                    origin = source_map[line - 1]
                    result[name].append((origin['path'], origin['line']))
                    if origin['path'] == original_top:
                        result[name].append((f"{folder}/{module}.sv", origin['line']))
                result[name].append((path, line))
    for name, locations in result.items():
        if not locations:
            raise ValueError(f"Cannot locate declared port {name} in the captured RTL")
    return result


def update_metadata(
    root: Path,
    module: str,
    config: str,
    *,
    generic: bool = False,
    output_dir: str = "outputs",
) -> None:
    """Add current evidence metadata to the design document and quality report."""
    validator = validate_generic_evidence if generic else validate_evidence
    manifest, _ = validator(root, module, config, output_dir)
    design, report = artifact_paths(root, module, output_dir)
    texts = [path.read_bytes().decode("utf-8") for path in (design, report)]
    source_field = "source_baseline" if generic else "xiangshan_commit"
    values = {
        key: manifest[key]
        for key in ("module", "config", source_field, "rtl_sha256", "generation_status")
    }
    values["source_baseline"] = values[source_field]
    values.update(
        template_version=template_version(),
        date=date.today().isoformat(),
    )
    marker_values = {
        key: values[key]
        for key in ("module", "config", source_field, "rtl_sha256", "generation_status")
    }
    marker_values.update(template_version=values["template_version"], date=values["date"])
    marker = (
        "<!-- rtl2spec: "
        + json.dumps(marker_values, ensure_ascii=False, sort_keys=True)
        + " -->"
    )
    for index in range(2):
        text = texts[index]
        lines = text.splitlines(keepends=True)
        source_records = {s["evidence_id"]: s for s in manifest["related_sources"]}
        for row in markdown_rows(text):
            cells = row["cells"]
            label = cells[0].strip("` ")
            updated = list(cells)
            # Only known value cells belong to this operation. Never rewrite prose hashes.
            field = next((key for key, labels in FIELDS.items() if label in labels), None)
            if field is not None and len(cells) in {2, 3}:
                value_index = len(cells) - 1
                value = str(values[field])
                old = cells[value_index]
                pattern = {
                    "template_version": r"v\d+\.\d+\.\d+",
                    "source_baseline": r"[0-9a-f]{40,64}",
                    "date": r"\d{4}-\d{2}-\d{2}",
                }.get(field, r"`[^`]*`")
                if re.search(pattern, old):
                    replacement = f"`{value}`" if pattern == r"`[^`]*`" else value
                    updated[value_index] = re.sub(pattern, lambda _: replacement, old, count=1)
                else:
                    updated[value_index] = value
            elif label in ARTIFACT_TEXT["rtl_hash_labels"] and len(cells) in {2, 3}:
                updated[-1] = f"`{values['rtl_sha256']}`"
            elif label == ARTIFACT_TEXT["rtl_evidence_label"] and len(cells) == 2:
                updated[1] = re.sub(r"SHA-256\s+`[0-9a-f]{64}`",
                                    lambda _: f"SHA-256 `{values['rtl_sha256']}`", cells[1])
            elif label in source_records and len(cells) == 5:
                updated[3] = re.sub(r"[0-9a-f]{64}", source_records[label]["sha256"], cells[3])
            if updated != cells:
                newline = "\r\n" if lines[row["line"]].endswith("\r\n") else "\n"
                lines[row["line"]] = "| " + " | ".join(updated) + " |" + newline
        text = "".join(lines)
        if index == 1:
            text = update_related_sources_report(
                text, manifest["related_sources"], texts[0], generic=generic
            )
        newline = "\r\n" if "\r\n" in text else "\n"
        if len(METADATA_RE.findall(text)) == 1:
            text = METADATA_RE.sub(lambda _: marker, text)
        else:
            text = METADATA_RE.sub("", text).rstrip() + newline * 2 + marker + newline
        texts[index] = text if text.startswith(("\n", "\r\n")) else newline + text
    for path, text in zip((design, report), texts):
        path.write_text(text, encoding="utf-8")
    print(
        "Updated document metadata; content and signoff conclusions require author review."
    )


def update_related_sources_report(
    text: str,
    related_sources: list[dict[str, object]],
    document_text: str = "",
    *,
    generic: bool = False,
) -> str:
    """Replace the deterministic related-source section in the quality report."""
    rows = [
        RELATED_SOURCES_START,
        "",
        (
            "### Related source file references"
            if generic
            else "### Related module source references"
        ),
        "",
    ]
    if related_sources:
        rows.extend(
            [
                (
                    "The current document may cite these source files with the listed evidence IDs."
                    if generic
                    else "The current document may cite these modules with the listed evidence IDs."
                ),
                "",
                "| Evidence ID | Module | Source location | Source SHA-256 | Document references |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for source in related_sources:
            references = [
                str(index)
                for index, line in enumerate(document_text.splitlines(), 1)
                if source["evidence_id"] in line
            ]
            rows.append(
                "| {evidence_id} | {module} | `{path}:{line}` | `{sha256}` | {references} |".format(
                    references=("lines " + ", ".join(references)) if references else "not cited yet",
                    **source,
                )
            )
    else:
        rows.append("No additional related module source was recorded for this generation.")
    rows.extend(["", RELATED_SOURCES_END])
    newline = "\r\n" if "\r\n" in text else "\n"
    block = newline.join(rows)
    pattern = re.compile(
        re.escape(RELATED_SOURCES_START) + r".*?" + re.escape(RELATED_SOURCES_END),
        re.S,
    )
    if pattern.search(text):
        return pattern.sub(block, text, count=1)
    return text.rstrip() + newline * 2 + block + newline
