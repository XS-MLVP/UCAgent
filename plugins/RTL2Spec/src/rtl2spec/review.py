"""Bind source-review records and final acceptance receipts to current artifacts."""

from __future__ import annotations

import json
import re
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .documents import ARTIFACT_TEXT, artifact_paths, document_sections, prose_text, template_version
from .evidence import digest, local_path, output_root, read_json, receipt, validate_evidence
from .generic_evidence import validate_generic_evidence
from .contracts import contract_rows, ids as reference_ids

ASPECTS = (
    "acceptance", "storage_backpressure", "bypass", "configuration",
    "reset_recovery", "assumptions", "verification_plan",
)
ACCEPTANCE_START = "<!-- rtl2spec-acceptance:start -->"
ACCEPTANCE_END = "<!-- rtl2spec-acceptance:end -->"


def write_record(path: Path, value: dict) -> None:
    """Publish a complete JSON record atomically in its already validated directory."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def behavior_ids(text: str) -> list[str]:
    """Extract actual P-* heading definitions, excluding prose and examples."""
    return [match.group() for section in document_sections(text)
            if section["level"] == 3
            and (match := re.match(r"P-[A-Z0-9]+(?:-[A-Z0-9]+)*", section["title"]))]


def review_sources(root: Path, manifest: dict, output_dir: str) -> dict[str, str]:
    """Expose only captured RTL and registered source files as review evidence."""
    paths = [f"{output_dir}/evidence/{manifest['module']}.sv"]
    paths.extend(item["path"] for item in manifest["related_sources"])
    if "source_baseline" in manifest:
        paths.append(manifest["rtl_source"])
        paths.append(f"{output_dir}/evidence/{manifest['module']}.preprocessed.sv")
    return {name: digest(local_path(root, name)) for name in paths}


def prepare_review(root: Path, module: str, config: str, *, generic: bool = False,
                   output_dir: str = "outputs") -> dict:
    """Create fresh review questions for the current document, preserving current answers."""
    validator = validate_generic_evidence if generic else validate_evidence
    manifest, _ = validator(root, module, config, output_dir)
    design, _ = artifact_paths(root, module, output_dir)
    folder = output_root(root, output_dir)
    baseline = {
        "module": module, "config": config, "document_sha256": digest(design),
        "manifest_sha256": digest(local_path(root, folder / "evidence/manifest.json")),
        "sources": review_sources(root, manifest, output_dir),
    }
    target = local_path(root, folder / "semantic_review.json")
    if target.exists():
        previous = read_json(target)
        signed = previous.get("baseline", {})
        if isinstance(signed, dict) and {k: v for k, v in signed.items() if k != "signature"} == baseline:
            receipt(root, signed)
            return {"ok": True, "artifact": str(target.relative_to(root)), "preserved": True}
    ids = behavior_ids(design.read_text(encoding="utf-8"))
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Define unique P-* behavior headings before preparing semantic_review.json")
    value = {
        "schema_version": 1, "baseline": receipt(root, baseline, sign=True),
        "behaviors": [{"id": name, "checks": {
            aspect: {"status": "pending", "conclusion": "", "evidence": [],
                     **({"ck_ids": [], "coverage_ids": []} if aspect == "verification_plan" else {})}
            for aspect in ASPECTS}} for name in ids],
    }
    write_record(target, value)
    return {"ok": True, "artifact": str(target.relative_to(root)), "behaviors": len(ids),
            "next_action": "Read Guide_Doc/source-review-guide.md and the cited RTL; complete every review check. These records are not a proof of semantic correctness."}


def validate_review(root: Path, module: str, manifest: dict, output_dir: str) -> None:
    """Check review coverage, source locations and freshness without claiming semantic proof."""
    folder = output_root(root, output_dir)
    target = local_path(root, folder / "semantic_review.json")
    value = read_json(target)
    design, _ = artifact_paths(root, module, output_dir)
    text = design.read_text(encoding="utf-8")
    baseline = value.get("baseline")
    if value.get("schema_version") != 1 or not isinstance(baseline, dict):
        raise ValueError(f"{target}: expected schema_version=1 and a tool-created baseline; run review")
    receipt(root, baseline)
    expected = {"module": module, "config": manifest["config"], "document_sha256": digest(design),
                "manifest_sha256": digest(local_path(root, folder / "evidence/manifest.json")),
                "sources": review_sources(root, manifest, output_dir)}
    if {k: v for k, v in baseline.items() if k != "signature"} != expected:
        raise ValueError(f"{target}: stale review after document/source changes; run review and recheck all P-* items")
    behaviors = value.get("behaviors")
    ids = behavior_ids(text)
    if (not isinstance(behaviors, list) or any(not isinstance(b, dict) for b in behaviors)
            or len(ids) != len(set(ids)) or not ids
            or sorted(b.get("id", "") for b in behaviors) != sorted(ids)):
        raise ValueError(f"{target}: behaviors must contain each current P-* exactly once")
    visible = prose_text(text)
    tables = contract_rows(text)
    open_states = {row['cells'][0]: row['cells'][4] for row in tables['open']}
    plans = {row['cells'][2]: row['cells'] for row in tables['plan']}
    for behavior in behaviors:
        checks = behavior.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(ASPECTS):
            raise ValueError(f"{target}: {behavior['id']} must contain exactly these checks: {', '.join(ASPECTS)}")
        for aspect, check in checks.items():
            location = f"{target}: {behavior['id']}/{aspect}"
            if not isinstance(check, dict) or check.get("status") not in {"reviewed", "not_applicable", "open"}:
                raise ValueError(f"{location}: review the source and use reviewed, not_applicable or open")
            conclusion = check.get("conclusion")
            if not isinstance(conclusion, str) or not conclusion.strip() or re.search(r"\b(?:TODO|TBD)\b", conclusion):
                raise ValueError(f"{location}: provide a concrete conclusion or an inapplicability reason")
            if check["status"] == "open":
                open_id = check.get("open_id", "")
                if not isinstance(open_id, str) or open_states.get(open_id) not in {"Open", "Deferred"}:
                    raise ValueError(f"{location}: name an Open/Deferred OPEN-* item defined in the open-items table")
            evidence = check.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"{location}: cite at least one registered source path and line range")
            for item in evidence:
                if not isinstance(item, dict) or item.get("path") not in baseline["sources"]:
                    raise ValueError(f"{location}: evidence path must be captured RTL or a registered related source")
                start, end = item.get("start_line"), item.get("end_line")
                lines = local_path(root, item["path"]).read_text(encoding="utf-8").splitlines()
                if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)
                        or end - start >= 100 or not any(line.strip() for line in lines[start - 1:end])):
                    raise ValueError(f"{location}: invalid or empty source range; cite 1 to 100 existing lines")
            if aspect == "verification_plan":
                for field, prefix in (("ck_ids", "CK"), ("coverage_ids", "COV")):
                    tags = check.get(field)
                    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags) or len(tags) != len(set(tags)) or any(
                        not isinstance(tag, str) or not re.fullmatch(prefix + r"-[A-Z0-9-]+", tag)
                        or not re.search(r"(?<![A-Z0-9-])" + re.escape(tag) + r"(?![A-Z0-9-])", visible) for tag in tags
                    ) or (check["status"] == "reviewed" and not tags):
                        raise ValueError(f"{location}: {field} must reference existing unique {prefix}-* items; explain open/inapplicable plans")
                selected = check['ck_ids']
                if any(ck not in plans or behavior['id'] not in reference_ids(plans[ck][4], 'P') for ck in selected):
                    raise ValueError(f"{location}: ck_ids must select Testplan checks belonging to this P-*")
                available = set().union(*(reference_ids(plans[ck][8], 'COV') for ck in selected))
                if not set(check['coverage_ids']).issubset(available):
                    raise ValueError(f"{location}: coverage_ids must belong to the selected Testplan checks")



def acceptance_hashes(root: Path, module: str, output_dir: str) -> dict[str, str]:
    """Hash all published evidence and the three authored/reviewed documents."""
    folder = output_root(root, output_dir)
    paths = [*artifact_paths(root, module, output_dir), local_path(root, folder / "semantic_review.json")]
    paths.extend(path for path in local_path(root, folder / "evidence").rglob("*") if path.is_file())
    return {str(path.relative_to(folder)): digest(local_path(root, path)) for path in sorted(paths)}


def finalize(root: Path, module: str, config: str, *, generic: bool = False,
             output_dir: str = "outputs") -> dict:
    """Run acceptance once, publish the report block and sign exact final artifact hashes."""
    from .validation import validate
    from . import __version__

    before = acceptance_hashes(root, module, output_dir)
    result = validate(root, module, config, "review", generic=generic, output_dir=output_dir)
    if not result["ok"]:
        return result
    if acceptance_hashes(root, module, output_dir) != before:
        raise ValueError("Artifacts changed during final validation; preserve edits and rerun finalize")
    _, report = artifact_paths(root, module, output_dir)
    original = report.read_text(encoding="utf-8")
    block = [ACCEPTANCE_START, "", "## " + ARTIFACT_TEXT["acceptance_title"], "",
             ARTIFACT_TEXT["acceptance_scope"], "",
             "| " + " | ".join(ARTIFACT_TEXT["acceptance_header"]) + " |", "| --- | --- | --- |"]
    block.extend("| " + " | ".join(row) + " |" for row in ARTIFACT_TEXT["acceptance_rows"])
    block.extend(["", ACCEPTANCE_END])
    updated = re.sub(re.escape(ACCEPTANCE_START) + r".*?" + re.escape(ACCEPTANCE_END), "", original, flags=re.S).rstrip()
    published_report = updated + "\n\n" + "\n".join(block) + "\n"
    report.write_text(published_report, encoding="utf-8")
    folder = output_root(root, output_dir)
    import hashlib

    expected = {**before, str(report.relative_to(folder)): hashlib.sha256(published_report.encode()).hexdigest()}
    if acceptance_hashes(root, module, output_dir) != expected:
        raise ValueError("Artifacts changed while publishing acceptance; preserve edits and rerun finalize")
    record = receipt(root, {
        "schema_version": 1, "module": module, "config": config,
        "workflow": "generic-design-document" if generic else "xiangshan-design-document",
        "plugin_version": __version__, "template_version": template_version(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "checks": result, "semantic_proof": "Unrun", "simulation": "Unrun", "formal": "Unrun",
        "artifact_sha256": expected,
    }, sign=True)
    target = local_path(root, folder / "validation.json")
    write_record(target, record)
    return {"ok": True, "phase": "final", "warnings": result["warnings"], "artifact": str(target.relative_to(root))}


def validate_acceptance(root: Path, module: str, config: str, output_dir: str) -> None:
    """Reject forged or stale final acceptance after any delivered artifact changes."""
    target = local_path(root, output_root(root, output_dir) / "validation.json")
    value = read_json(target)
    receipt(root, value)
    from . import __version__

    if (value.get("schema_version"), value.get("module"), value.get("config")) != (1, module, config):
        raise ValueError(f"{target}: wrong acceptance identity; run finalize")
    if value.get("plugin_version") != __version__ or value.get("template_version") != template_version():
        raise ValueError(f"{target}: acceptance uses a different plugin/template version; review changes and run finalize")
    if value.get("artifact_sha256") != acceptance_hashes(root, module, output_dir):
        raise ValueError(f"{target}: stale acceptance after artifact changes; review changes and run finalize")
