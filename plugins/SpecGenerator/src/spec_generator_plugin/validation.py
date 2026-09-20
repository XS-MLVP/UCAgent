"""Check template structure, evidence and current artifact integrity."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .evidence import digest, local_path, read_json, receipt, validate_evidence
from .documents import (
    FIELDS,
    METADATA_RE,
    artifact_paths,
    template_version,
    mermaid_sources,
    prose_text,
    validate_structure,
)

ID_RE = re.compile(r"\b(?:FG|FC|CK|P|E|COV)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def validate(
    root: Path, module: str, version: str, config: str, phase: str = "final"
) -> dict:
    """Return bounded diagnostics for actual evidence, references, and current diagram renders."""
    errors: list[dict] = []
    warnings: list[str] = []
    artifact = f"evidence/{module}/{version}/manifest.json"
    try:
        manifest, ports = validate_evidence(root, module, version, config)
        if manifest["generation_status"] == "partial":
            warnings.append(
                "RTL generation was partial; document the downstream failure and limit conclusions to the available module RTL."
            )
        if phase != "evidence":
            paths = artifact_paths(root, module, version)
            current_template = template_version()
            texts = []
            for index, path in enumerate(paths):
                artifact = str(path.relative_to(root))
                text = path.read_text(encoding="utf-8")
                texts.append(text)
                mermaid_sources(text)
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
                if index < 2:
                    markers = METADATA_RE.findall(text)
                    if len(markers) != 1:
                        errors.append(
                            {
                                "artifact": artifact,
                                "error": 'run SpecGeneratorCommand(action="metadata") to add one current metadata record',
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
                        expected.update(
                            version=version, template_version=current_template
                        )
                        if not isinstance(metadata, dict) or any(
                            metadata.get(key) != value
                            for key, value in expected.items()
                        ):
                            errors.append(
                                {
                                    "artifact": artifact,
                                    "error": "metadata differs from the current template, version or verified RTL; review inputs and rerun metadata",
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
            if not re.search(rf"(?<![\w.]){re.escape(version)}(?![\w.])", texts[2]):
                errors.append(
                    {
                        "artifact": str(paths[2].relative_to(root)),
                        "error": f"add a history entry for {version}",
                    }
                )

            artifact = str(paths[0].relative_to(root))
            prose = prose_text(texts[0])
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
            for prefix in ("FG-", "FC-", "CK-", "P-", "E-", "COV-"):
                if not any(tag.startswith(prefix) for tag in definitions):
                    warnings.append(
                        f"{artifact}: consider adding {prefix} traceability where applicable; explain omissions in the quality review."
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

            if phase == "final":
                artifact = f"evidence/{module}/{version}/diagrams/manifest.json"
                diagram_path = local_path(root, artifact)
                diagrams = read_json(diagram_path)
                receipt(root, diagrams)
                sources = mermaid_sources(texts[0])
                entries = diagrams.get("diagrams")
                if (
                    diagrams.get("document") != paths[0].name
                    or not isinstance(entries, list)
                    or diagrams.get("diagram_count") != len(sources)
                    or len(entries) != len(sources)
                ):
                    raise ValueError(
                        'diagram sources changed; run SpecGeneratorCommand(action="render")'
                    )
                for source, entry in zip(sources, entries):
                    svg = local_path(root, diagram_path.parent / entry["output"])
                    if (
                        entry.get("source_sha256")
                        != hashlib.sha256(source.encode()).hexdigest()
                        or not svg.is_file()
                        or entry.get("svg_sha256") != digest(svg)
                    ):
                        raise ValueError(
                            f"{svg}: stale/missing diagram; rerun render for the current document"
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
                "Repair the listed artifacts. Use SpecGeneratorCommand evidence/metadata/render as directed, then rerun Check.",
            ),
        )
    return result
