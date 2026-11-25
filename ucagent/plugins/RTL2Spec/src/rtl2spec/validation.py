"""Check template structure, evidence and current artifact integrity."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .evidence import local_path, validate_evidence
from .generic_evidence import validate_generic_evidence
from .contracts import contract_rows, validate_contract, ID_RE
from .review import ACCEPTANCE_START, ACCEPTANCE_END, validate_review, validate_acceptance
from .sv_frontend import port_shape
from .documents import (
    ARTIFACT_TEXT,
    FIELDS,
    METADATA_RE,
    RELATED_SOURCES_END,
    RELATED_SOURCES_START,
    artifact_paths,
    template_version,
    mermaid_sources,
    prose_text,
    validate_structure,
    appendix_rows,
    markdown_rows,
    document_sections,
    markdown_tokens,
)


def validate_quality_report(text: str) -> list[dict]:
    """Require the review report's independent audit sections before review/final."""
    errors = []
    headings = document_sections(text)
    title = ARTIFACT_TEXT["quality_report"]["title"]
    top_level = [section for section in headings if section["level"] == 1]
    if len(top_level) != 1 or top_level[0]["title"] != title or headings[0] != top_level[0]:
        errors.append({"rule": "QUALITY_REPORT_TITLE", "error": "quality report must start with its single canonical level-one title; follow Guide_Doc/document-quality-review-template.md"})
    required = ARTIFACT_TEXT["quality_report"]["sections"]
    lines = text.splitlines()
    previous_line = -1
    for expected in required:
        matches = [
            item for item in headings
            if item["title"] == expected["title"] and item["level"] == 2
        ]
        if len(matches) > 1:
            errors.append({"rule": "QUALITY_REPORT_DUPLICATE", "error": f"quality report repeats section '{expected['title']}'"})
            continue
        section = matches[0] if matches else None
        if section is None:
            errors.append({"rule": "QUALITY_REPORT_SECTION", "error": f"quality report is missing section '{expected['title']}'"})
            continue
        if section["line"] <= previous_line:
            errors.append({"rule": "QUALITY_REPORT_ORDER", "error": f"quality report sections are out of order at '{expected['title']}'"})
        previous_line = section["line"]
        index = headings.index(section)
        end = next((candidate["line"] - 1 for candidate in headings[index + 1:] if candidate["level"] <= section["level"]), len(lines))
        body = "\n".join(lines[section["line"]:end])
        visible = prose_text(body)
        meaningful = [
            line.strip() for line in visible.splitlines()
            if line.strip() and not line.lstrip().startswith("|")
            and not re.match(r"^#{1,6}\s", line.lstrip())
            and not re.fullmatch(r"[-:| ]+", line.strip())
        ]
        has_data = any(not row["header"] and any(cell.strip() for cell in row["cells"])
                       for row in markdown_rows(visible))
        if not meaningful and not has_data:
            errors.append({"rule": "QUALITY_REPORT_CONTENT", "error": f"quality report section '{expected['title']}' needs findings or an explicit limitation"})
    return errors


def validate_ports(text: str, ports: list[dict]) -> list[dict]:
    """Require exactly one correctly sized/directed Appendix A row per actual port."""
    expected = {p["name"]: p for p in ports}
    seen = set()
    ids = set()
    errors = []
    for row in appendix_rows(text):
        cells = [c.strip("` ") for c in row["cells"]]
        issue = None
        if len(cells) != 9:
            issue = "interface row must have all 9 Appendix A columns"
        elif cells[0] in ids:
            issue = f"duplicate interface ID: {cells[0]}"
        elif cells[6] not in expected:
            issue = f"RTL port not present: {cells[6]}"
        elif cells[6] in seen:
            issue = f"duplicate RTL port mapping: {cells[6]}"
        else:
            port = expected[cells[6]]
            shape = port_shape(port)
            if cells[4] != shape:
                issue = f"RTL direction/width contradicts ports.csv for {cells[6]}; expected {shape}"
            seen.add(cells[6])
        ids.add(cells[0])
        if issue:
            errors.append({"error": issue, "line": row["line"] + 1})
    missing = sorted(expected.keys() - seen)
    if missing:
        errors.append({"error": "unmapped RTL ports", "count": len(missing), "ports": missing[:12]})
    for error in errors:
        error["next_action"] = "Reconcile Appendix A with evidence/ports.csv; use the ports action to regenerate its scaffold."
    return errors


def validate(
    root: Path,
    module: str,
    config: str,
    phase: str = "final",
    *,
    generic: bool = False,
    output_dir: str = "outputs",
    check_acceptance_record: bool = True,
) -> dict:
    """Validate current phase artifacts; the publisher may check final content before issuing a receipt."""
    errors: list[dict] = []
    warnings: list[str] = []
    artifact = f"{output_dir}/evidence/manifest.json"
    metadata_action = "generic_metadata" if generic else "metadata"
    try:
        evidence_validator = validate_generic_evidence if generic else validate_evidence
        source_field = "source_baseline" if generic else "xiangshan_commit"
        manifest, ports = evidence_validator(root, module, config, output_dir)
        if manifest["generation_status"] == "partial":
            warnings.append(
                "RTL generation was partial; document the downstream failure and limit conclusions to the available module RTL."
            )
        if phase != "evidence":
            paths = artifact_paths(root, module, output_dir)
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
                comments = comments.replace(ACCEPTANCE_START, "").replace(ACCEPTANCE_END, "")
                if "<!--" in comments:
                    errors.append(
                        {
                            "artifact": artifact,
                            "error": "formal artifact contains HTML comments; remove template/generation comments",
                            "next_action": "Delete HTML comments from the design document and quality report, preserving only the rtl2spec metadata, related-source and acceptance markers added by the tool.",
                        }
                    )
                if index == 0:
                    errors.extend(
                        {"artifact": artifact, **issue}
                        for issue in validate_structure(text, module)
                    )
                elif phase in {"review", "final"}:
                    errors.extend(
                        {
                            "artifact": artifact,
                            **issue,
                            "next_action": "Complete the canonical quality report sections using Guide_Doc/document-quality-review-template.md, then rerun Check.",
                        }
                        for issue in validate_quality_report(text)
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
                            "error": f'run RTL2SpecCommand(action="{metadata_action}") to add one current metadata record',
                        }
                    )
                else:
                    metadata = json.loads(markers[0])
                    expected = {
                        key: manifest[key]
                        for key in (
                            "module",
                            "config",
                            source_field,
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
                        else str(
                            manifest[source_field]
                            if key == "source_baseline"
                            else manifest[key]
                        )
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
            errors.extend(validate_contract(root, module, manifest, ports, texts[0], texts[1], output_dir))
            definitions = {row["cells"][0] for row in contract_rows(texts[0])["evidence"]}
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
            cited_rows = contract_rows(texts[0])["evidence"]
            citation_lines = prose.splitlines()
            for row in cited_rows:
                citation_lines[row["line"] - 1] = ""
            citation_text = "\n".join(citation_lines)
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
                if cited_by_body:
                    rows = [row["cells"] for row in markdown_rows(texts[0])
                            if row["cells"][0].strip("` ") == evidence_id]
                    if not any(source["path"] in " ".join(row) and source["sha256"] in " ".join(row) for row in rows):
                        errors.append({"artifact": artifact,
                                       "error": f"{evidence_id}: evidence row must identify its own registered path and source hash",
                                       "next_action": f"Correct its Appendix C row, then run {metadata_action}."})
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
                            "next_action": f'Run RTL2SpecCommand(action="{metadata_action}") after recording related sources to refresh the report section.',
                        }
                    )
            errors.extend({"artifact": artifact, **issue} for issue in validate_ports(texts[0], ports))
            if phase == "final" and manifest.get("generation_status") == "partial":
                open_rows = contract_rows(texts[0])["open"]
                partial_open = next(
                    (row for row in open_rows if row["cells"][0] == "OPEN-GENERATION-PARTIAL"),
                    None,
                )
                if partial_open is None or partial_open["cells"][4] not in {"Open", "Deferred"}:
                    errors.append({
                        "artifact": artifact,
                        "rule": "PARTIAL_SIGNOFF",
                        "error": "partial RTL generation cannot reach final without OPEN-GENERATION-PARTIAL in Open or Deferred state",
                        "next_action": "Add OPEN-GENERATION-PARTIAL with the failed generation scope and constrained conclusion, then rerun Check.",
                    })
            if phase in {"review", "final"}:
                artifact = f"{output_dir}/semantic_review.json"
                validate_review(root, module, manifest, output_dir)
            if phase == "final" and check_acceptance_record:
                artifact = f"{output_dir}/validation.json"
                validate_acceptance(root, module, config, output_dir)

    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        issue = {"artifact": artifact, "error": str(exc)}
        action_prefix = "generic_" if generic else ""
        if artifact == f"{output_dir}/semantic_review.json":
            issue["next_action"] = (
                f"Run RTL2SpecCommand(action='{action_prefix}review', module='{module}', config='{config}') "
                "to prepare the current baseline; repair the listed P-*/check using Guide_Doc/source-review-guide.md and the actual source, then rerun Check."
            )
        elif artifact == f"{output_dir}/validation.json":
            issue["next_action"] = (
                f"Run RTL2SpecCommand(action='{action_prefix}finalize', module='{module}', config='{config}') "
                "to validate and publish current acceptance; resolve any reported review failures, then rerun Complete."
            )
        errors.append(issue)
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
