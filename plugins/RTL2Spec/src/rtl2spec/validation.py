"""Check template structure, evidence and current artifact integrity."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .evidence import local_path, validate_evidence
from .documents import (
    FIELDS,
    METADATA_RE,
    RELATED_SOURCES_END,
    RELATED_SOURCES_START,
    artifact_paths,
    template_version,
    mermaid_sources,
    prose_text,
    validate_structure,
)

ID_RE = re.compile(r"\b(?:FG|FC|CK|P|E|COV)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def validate(root: Path, module: str, config: str, phase: str = "final") -> dict:
    """Return bounded diagnostics for actual evidence, references, and Mermaid source."""
    errors: list[dict] = []
    warnings: list[str] = []
    artifact = f"evidence/{module}/manifest.json"
    try:
        manifest, ports = validate_evidence(root, module, config)
        if manifest["generation_status"] == "partial":
            warnings.append(
                "RTL generation was partial; document the downstream failure and limit conclusions to the available module RTL."
            )
        if phase != "evidence":
            paths = artifact_paths(root, module)
            current_template = template_version()
            texts = []
            for index, path in enumerate(paths):
                artifact = str(path.relative_to(root))
                text = path.read_text(encoding="utf-8")
                texts.append(text)
                mermaid_sources(text)
                # Template comments are authoring constraints and must not leak
                # into a formal artifact. Keep only the tool-owned metadata and
                # related-source markers that are required for auditability.
                comments = METADATA_RE.sub("", text)
                comments = comments.replace(RELATED_SOURCES_START, "")
                comments = comments.replace(RELATED_SOURCES_END, "")
                if "<!--" in comments:
                    errors.append(
                        {
                            "artifact": artifact,
                            "error": "formal artifact contains HTML comments; remove template/generation comments",
                            "next_action": "Delete HTML comments from the design document and quality report, preserving only the rtl2spec metadata and related-source markers added by the tool.",
                        }
                    )
                if index == 0:
                    errors.extend(
                        {"artifact": artifact, **issue}
                        for issue in validate_structure(text, module)
                    )
                visible = re.sub(r"<!--.*?-->", "", text, flags=re.S)
                content = "\n".join(
                    line
                    for line in visible.splitlines()
                    if line.strip()
                    and not re.match(r"^\s*(?:#{1,6}\s|[-|: ]+$|```|~~~)", line)
                )
                if not content.strip():
                    errors.append(
                        {
                            "artifact": artifact,
                            "error": "file has no substantive content; write the required artifact",
                        }
                    )
                markers = METADATA_RE.findall(text)
                if len(markers) != 1:
                    errors.append(
                        {
                            "artifact": artifact,
                            "error": 'run RTL2SpecCommand(action="metadata") to add one current metadata record',
                        }
                    )
                else:
                    metadata = json.loads(markers[0])
                    expected = {
                        key: manifest[key]
                        for key in (
                            "module",
                            "config",
                            "xiangshan_commit",
                            "rtl_sha256",
                            "generation_status",
                        )
                    }
                    expected.update(template_version=current_template)
                    if not isinstance(metadata, dict) or any(
                        metadata.get(key) != value
                        for key, value in expected.items()
                    ):
                        errors.append(
                            {
                                "artifact": artifact,
                                "error": "metadata differs from the current template or verified RTL; review inputs and rerun metadata",
                            }
                        )
                # Optional visible metadata must not contradict the verified facts.
                for key, labels in FIELDS.items():
                    if key == "date":
                        continue
                    expected_value = (
                        current_template
                        if key == "template_version"
                        else str(manifest[key])
                    )
                    for label in labels:
                        cells = re.findall(
                            rf"^\s*\|\s*{re.escape(label)}\s*\|\s*(.*?)\s*\|\s*$",
                            visible,
                            re.M,
                        )
                        for cell in cells:
                            tokens = (
                                re.findall(r"v\d+\.\d+\.\d+", cell)
                                if key == "template_version"
                                else [cell]
                            )
                            if not tokens or any(
                                not re.search(
                                    rf"(?<![\w.]){re.escape(expected_value)}(?![\w.])",
                                    token,
                                    re.I if key == "generation_status" else 0,
                                )
                                for token in tokens
                            ):
                                errors.append(
                                    {
                                        "artifact": artifact,
                                        "error": f"{key} contradicts verified metadata; run metadata after reviewing the inputs",
                                    }
                                )
                prose = prose_text(visible)
                for raw in re.findall(r"\[[^\]]*\]\((<[^>]+>|[^)]+)\)", prose):
                    raw = raw.strip("<>")
                    link = urlsplit(raw)
                    if link.scheme or link.netloc or not link.path:
                        continue
                    target = local_path(root, path.parent / unquote(link.path))
                    if not target.exists():
                        errors.append(
                            {"artifact": artifact, "error": f"broken local link: {raw}"}
                        )
                    elif (
                        re.fullmatch(r"L[1-9][0-9]*", link.fragment)
                        and target.is_file()
                    ):
                        if int(link.fragment[1:]) > len(
                            target.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                        ):
                            errors.append(
                                {
                                    "artifact": artifact,
                                    "error": f"line reference out of range: {raw}",
                                }
                            )
            artifact = str(paths[0].relative_to(root))
            prose = prose_text(texts[0])
            related_sources = manifest["related_sources"]
            related_ids = {source["evidence_id"] for source in related_sources}
            definitions: set[str] = set()
            explicit: list[str] = []
            for line in prose.splitlines():
                tags = re.findall(r"<((?:FG|FC|CK)-[A-Z0-9-]+)>", line)
                explicit.extend(tags)
                definitions.update(tags)
                plain = line.replace("`", "").replace("**", "")
                match = re.match(
                    r"^\s*(?:#{1,6}\s+|\|\s*|[-*]\s+)((?:FG|FC|CK|P|E|COV)-[A-Z0-9-]+)\b",
                    plain,
                )
                if match:
                    definitions.add(match.group(1))
            missing = sorted(set(ID_RE.findall(prose)) - definitions)
            unknown_related = sorted(
                tag
                for tag in set(ID_RE.findall(prose))
                if tag.startswith("E-REL-") and tag not in related_ids
            )
            if unknown_related:
                errors.append(
                    {
                        "artifact": artifact,
                        "error": f"unrecorded related source evidence: {', '.join(unknown_related[:12])}",
                        "next_action": "Record each cited related module with related_sources, or remove the unsupported E-REL citation.",
                    }
                )
            citation_text = re.sub(
                r"## 附录 C：范围、文档控制、证据与版本变更.*?(?=## 附录 D：CK 追溯矩阵)",
                "",
                prose,
                flags=re.S,
            )
            report_text = texts[1]
            for source in related_sources:
                evidence_id = source["evidence_id"]
                cited_by_body = bool(
                    re.search(rf"\b{re.escape(evidence_id)}\b", citation_text)
                )
                # A related source may have been read for context and retained
                # in the run report without supporting a final document claim.
                # Only a source cited by the document body must be defined in
                # Appendix C; the report remains the complete read-source audit.
                if cited_by_body and evidence_id not in definitions:
                    errors.append(
                        {
                            "artifact": artifact,
                            "error": f"cited related source evidence {evidence_id} is missing from Appendix C",
                            "next_action": "Add an Appendix C evidence row for the cited related source, including its source path and hash.",
                        }
                    )
                if not (
                    RELATED_SOURCES_START in report_text
                    and RELATED_SOURCES_END in report_text
                    and all(
                        str(source[field]) in report_text
                        for field in ("evidence_id", "module", "path", "sha256")
                    )
                ):
                    errors.append(
                        {
                            "artifact": str(paths[1].relative_to(root)),
                            "error": f"quality report does not list related source {evidence_id}",
                            "next_action": 'Run RTL2SpecCommand(action="metadata") after recording related_sources to refresh the report section.',
                        }
                    )
            duplicate = sorted({tag for tag in explicit if explicit.count(tag) > 1})
            if missing:
                errors.append(
                    {
                        "artifact": artifact,
                        "error": f"undefined references: {', '.join(missing[:12])}; define IDs in headings/table first cells, or correct the reference",
                    }
                )
            if duplicate:
                errors.append(
                    {
                        "artifact": artifact,
                        "error": f"duplicate definition tags: {', '.join(duplicate[:12])}; use plain IDs for references",
                    }
                )
            port_names = {port["name"] for port in ports}
            documented = set()
            for line in prose.splitlines():
                if re.search(r"\bElided\b", line, re.I):
                    continue
                for token in re.findall(
                    r"`((?:io_[A-Za-z0-9_\[\]*]+|clock|reset))`", line
                ):
                    pattern = re.escape(token).replace(r"\*", ".*")
                    pattern = re.sub(r"\\\[[A-Za-z][A-Za-z0-9_]*\\\]", r"\\d+", pattern)
                    matches = {
                        name for name in port_names if re.fullmatch(pattern, name)
                    }
                    if not matches:
                        errors.append(
                            {
                                "artifact": artifact,
                                "error": f"RTL port/pattern not present: {token}; correct it or explicitly mark an Elided interface",
                            }
                        )
                    documented.update(matches)
                    shape = re.search(r"\b([IO])/\s*([0-9]+)\b", line)
                    if shape and len(re.findall(r"`io_[^`]+`", line)) == 1:
                        direction = {"I": "input", "O": "output"}[shape.group(1)]
                        if any(
                            p["name"] in matches
                            and (
                                p["direction"] != direction
                                or p["width"] != int(shape.group(2))
                            )
                            for p in ports
                        ):
                            errors.append(
                                {
                                    "artifact": artifact,
                                    "error": f"RTL direction/width contradicts ports.csv for {token}",
                                }
                            )
                cells = [
                    cell.strip(" `<>") for cell in line.strip().strip("|").split("|")
                ]
                if (
                    len(cells) >= 4
                    and cells[0].startswith("CK-")
                    and cells[-1] == "Closed"
                ):
                    required = "Covered" if cells[1] == "Cover" else "Proved"
                    if cells[-2] != required:
                        errors.append(
                            {
                                "artifact": artifact,
                                "error": f"{cells[0]}: Closed contradicts property state; record the actual execution/signoff state",
                            }
                        )
            if port_names - documented:
                warnings.append(
                    f"{artifact}: {len(port_names - documented)} ports are not explicitly mapped; review interface coverage against ports.csv."
                )
            if "<!-- GENERATOR:" in texts[0] or re.search(r"\b(?:TODO|TBD)\b", prose):
                warnings.append(
                    f"{artifact}: review remaining writing instructions/placeholders; record unresolved facts as OPEN-* with evidence needs."
                )

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        errors.append({"artifact": artifact, "error": str(exc)})
    result = {"ok": not errors, "phase": phase, "warnings": warnings[:10]}
    if errors:
        result.update(
            error_code="SPEC_ARTIFACT_INVALID",
            error=errors[0]["error"],
            artifact=errors[0]["artifact"],
            observed=errors[:12],
            error_count=len(errors),
            next_action=errors[0].get(
                "next_action",
                "Repair the listed artifacts. Use RTL2SpecCommand evidence or metadata as directed, then rerun Check.",
            ),
        )
    return result
