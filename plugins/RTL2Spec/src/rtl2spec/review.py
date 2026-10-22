"""Bind source-review records and final acceptance receipts to current artifacts."""

from __future__ import annotations

import json
import re
import os
import tempfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .documents import ARTIFACT_TEXT, artifact_paths, document_sections, prose_text, template_version, markdown_tokens
from .evidence import digest, local_path, output_root, read_json, receipt, validate_evidence
from .generic_evidence import validate_generic_evidence
from .contracts import contract_rows, ids as reference_ids, ID_RE, source_locations
from .sv_frontend import assignment_facts, expression_tokens

ASPECTS = (
    "acceptance", "storage_backpressure", "bypass", "configuration",
    "reset_recovery", "assumptions", "verification_plan",
)
ACCEPTANCE_START = "<!-- rtl2spec-acceptance:start -->"
ACCEPTANCE_END = "<!-- rtl2spec-acceptance:end -->"
REVIEW_SCHEMA_VERSION = 2


def write_record(path: Path, value: dict, *, expected_bytes: bytes | None) -> None:
    """Publish a complete JSON record atomically only while its prior content is unchanged."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        # Compare after serialization to preserve answers edited while a large
        # review was being encoded, including files created by another writer.
        if (path.read_bytes() if path.exists() else None) != expected_bytes:
            raise ValueError(f"{path}: record changed while publishing; preserve edits and retry")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def behavior_ids(text: str) -> list[str]:
    """Extract actual P-* heading definitions, excluding prose and examples."""
    return [match.group() for section in document_sections(text)
            if section["level"] == 3
            and (match := re.match(r"P-[A-Z0-9]+(?:-[A-Z0-9]+)*", section["title"]))]


def document_projection(text: str) -> list:
    """Project Markdown content without source-line positions or blank-line formatting."""
    projection = []
    for token in markdown_tokens(text):
        if token.type == "html_block" and "<!-- rtl2spec:" in token.content:
            continue
        if token.type == "inline":
            content = [(child.type, child.tag, child.content, child.attrs) for child in token.children or []]
        else:
            content = token.content
        projection.append((token.type, token.tag, content, token.info, token.attrs))
    return projection


def behavior_fingerprints(text: str, ids: list[str]) -> dict[str, str]:
    """Bind each P-* to its body, referenced behaviors/entities and shared context."""
    lines = text.splitlines()
    shared = list(lines)
    sections = document_sections(text)
    entities = {}
    for index, section in enumerate(sections):
        match = re.match(r"(?:P|CASE)-[A-Z0-9]+(?:-[A-Z0-9]+)*", section["title"])
        if section["level"] != 3 or match is None:
            continue
        start = section["line"] - 1
        end = next((s["line"] - 1 for s in sections[index + 1:] if s["level"] <= 3), len(lines))
        entities[match.group()] = "\n".join(lines[start:end])
        shared[start:end] = [""] * (end - start)
    tables = contract_rows(text)
    rows = []
    for key in ("plan", "coverage", "properties", "open", "evidence", "fc_trace", "ck_trace"):
        for row in tables[key]:
            cells = row["cells"]
            owner = cells[2] if key == "plan" else cells[0]
            rows.append((owner, key, cells))
            # Review answers may cite any OPEN-* item, so the open-items table
            # is shared context even without an explicit P-* body reference.
            if key != "open":
                shared[row["line"] - 1] = ""
    # Date updates are authoring metadata, while module/config/interface/state
    # rows remain part of the shared semantics for every behavior.
    for index, line in enumerate(shared):
        if line.startswith("<!-- rtl2spec:"):
            shared[index] = ""
        elif any(re.match(r"^\s*\|\s*" + re.escape(label) + r"\s*\|", line)
                 for label in ARTIFACT_TEXT["metadata_fields"]["date"]):
            shared[index] = ""
    common = document_projection("\n".join(shared))
    result = {}
    for identifier in ids:
        references = set(ID_RE.findall(entities[identifier]))
        selected_rows = []
        selected_entities = {}
        changed = True
        while changed:
            changed = False
            for row_index, (owner, key, cells) in enumerate(rows):
                if row_index in selected_rows:
                    continue
                if owner in references or references & reference_ids(" ".join(cells), "P"):
                    selected_rows.append(row_index)
                    references.update(item for item in ID_RE.findall(" ".join(cells)) if not item.startswith("P-"))
                    changed = True
            for name, section_text in entities.items():
                if name != identifier and name in references and name not in selected_entities:
                    selected_entities[name] = document_projection(section_text)
                    references.update(ID_RE.findall(section_text))
                    changed = True
        payload = {"behavior": document_projection(entities[identifier]), "shared": common,
                   "rows": [(rows[i][1], rows[i][2]) for i in sorted(selected_rows)],
                   "entities": selected_entities}
        result[identifier] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result


def assignment_projection(fact: dict) -> dict:
    """Normalize assignment fields as HDL tokens without changing guard order or polarity."""
    return {"lhs": expression_tokens(fact["lhs"]), "rhs": expression_tokens(fact["rhs"]),
            "operator": fact["operator"], "process": fact["process"],
            "event": expression_tokens(fact["event"], event=True) if fact["event"] is not None else None,
            "guards": [(expression_tokens(g["condition"]), g["branch"]) for g in fact["guards"]]}


def _ranges_overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    """Return whether two inclusive source ranges share at least one physical line."""
    return max(left_start, right_start) <= min(left_end, right_end)


def validate_behavior_facts(root: Path, behaviors: list[dict], baseline: dict, target: Path,
                            open_states: dict[str, str] | None = None,
                            evidence_ranges: dict[str, list[tuple[str, int, int]]] | None = None,
                            check_ranges: dict[str, dict[str, list[tuple[str, int, int]]]] | None = None) -> None:
    """Validate exact assignment guards/events against parsed HDL, never prose or comments."""
    require_open_reference = open_states is not None
    open_states = open_states or {}
    inventories = {}
    for behavior in behaviors:
        label = f"{behavior.get('id', '<unknown>')}/facts"
        # Every review needs source linkage, including behaviors for which no
        # supported assignment fact can be extracted.
        if check_ranges is not None and evidence_ranges is not None:
            for aspect, ranges in check_ranges.get(behavior.get("id"), {}).items():
                for path, start, end in ranges:
                    if not any(
                        evidence_path == path
                        and _ranges_overlap(start, end, evidence_start, evidence_end)
                        for evidence_path, evidence_start, evidence_end in evidence_ranges.get(behavior.get("id"), [])
                    ):
                        raise ValueError(f"{target}: {behavior.get('id', '<unknown>')}/{aspect}: review evidence must overlap an E-* range cited by the P-* body")
        facts = behavior.get("facts")
        status = behavior.get("fact_status")
        if status == "no_deterministic_fact":
            reason = behavior.get("fact_reason")
            if facts != [] or not isinstance(reason, str) or not reason.strip() or re.search(r"\b(?:TODO|TBD)\b", reason):
                raise ValueError(f"{target}: {label}: provide facts=[] and a concrete fact_reason")
            open_ids = reference_ids(reason, "OPEN")
            if require_open_reference and (len(open_ids) != 1 or open_states.get(next(iter(open_ids), "")) not in {"Open", "Deferred"}):
                raise ValueError(
                    f"{target}: {label}: no_deterministic_fact must cite exactly one OPEN-* item whose status is Open or Deferred"
                )
            continue
        if status != "asserted" or not isinstance(facts, list) or not facts:
            raise ValueError(f"{target}: {label}: provide asserted assignment facts or explain no_deterministic_fact")
        for index, fact in enumerate(facts):
            location = f"{target}: {label}[{index}]"
            required = {"kind", "lhs", "rhs", "operator", "process", "event", "guards", "evidence"}
            if not isinstance(fact, dict) or set(fact) != required or fact["kind"] != "assignment":
                raise ValueError(f"{location}: expected an assignment with lhs/rhs/operator/process/event/guards/evidence")
            if (not isinstance(fact["operator"], str) or fact["operator"] not in {"=", "<="}
                    or not isinstance(fact["process"], str) or fact["process"] not in {"continuous", "always", "always_ff", "always_comb", "always_latch"}
                    or not isinstance(fact["lhs"], str) or not fact["lhs"].strip()
                    or not isinstance(fact["rhs"], str) or not fact["rhs"].strip()
                    or (fact["event"] is not None and (not isinstance(fact["event"], str) or not fact["event"].strip()))):
                raise ValueError(f"{location}: invalid assignment expression, process, operator or event")
            guards = fact["guards"]
            if not isinstance(guards, list) or any(
                not isinstance(g, dict) or set(g) != {"condition", "branch"}
                or not isinstance(g["condition"], str) or not g["condition"].strip()
                or not isinstance(g["branch"], str) or g["branch"] not in {"then", "else"} for g in guards
            ):
                raise ValueError(f"{location}: guards must list each enclosing condition and then/else branch in outer-to-inner order")
            try:
                expected = assignment_projection(fact)
            except ValueError as exc:
                raise ValueError(f"{location}: invalid HDL expression or event; copy each lhs/rhs/condition and event from the cited RTL without extra statements") from exc
            evidence = fact["evidence"]
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"{location}: cite at least one complete RTL assignment range")
            if evidence_ranges is not None and not evidence_ranges.get(behavior.get("id")):
                raise ValueError(f"{location}: asserted facts require an E-* citation in the matching P-* body")
            for item in evidence:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str) or item["path"] not in baseline["sources"]:
                    raise ValueError(f"{location}: cite captured RTL or a registered source")
                path = item["path"]
                if Path(path).suffix.lower() not in {".sv", ".v", ".vh", ".svh"}:
                    raise ValueError(f"{location}: facts require HDL evidence; cite the captured RTL view")
                if path not in inventories:
                    text = local_path(root, path).read_text(encoding="utf-8")
                    try:
                        inventories[path] = (text.splitlines(), [
                            {**candidate, "projection": assignment_projection(candidate)}
                            for candidate in assignment_facts(text, baseline["module"])
                        ])
                    except ValueError as exc:
                        raise ValueError(f"{location}: cannot extract assignment facts from {path}: {str(exc)[:2000]}") from exc
                lines, candidates = inventories[path]
                start, end = item.get("start_line"), item.get("end_line")
                if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines) or end - start >= 100:
                    raise ValueError(f"{location}: cite 1 to 100 existing source lines")
                matched = False
                for candidate in candidates:
                    if candidate["projection"] == expected and start <= candidate["start_line"] <= candidate["end_line"] <= end:
                        matched = True
                        break
                if not matched:
                    raise ValueError(f"{location}: assignment, guard or event contradicts the cited RTL; repair the fact and cite its entire assignment")
                if evidence_ranges is not None and not any(
                    evidence_path == path
                    and _ranges_overlap(start, end, evidence_start, evidence_end)
                    for evidence_path, evidence_start, evidence_end in evidence_ranges[behavior.get("id")]
                ):
                    raise ValueError(f"{location}: fact evidence must overlap the source range of an E-* cited by the matching P-* body")


def review_sources(root: Path, manifest: dict, output_dir: str) -> dict[str, str]:
    """Bind review evidence to the checked manifest, rejecting files changed after validation."""
    sources = {f"{output_dir}/evidence/{manifest['module']}.sv": manifest["rtl_sha256"]}
    sources.update((item["path"], item["sha256"]) for item in manifest["related_sources"])
    if "source_baseline" in manifest:
        sources[manifest["rtl_source"]] = manifest["rtl_sha256"]
        sources[f"{output_dir}/evidence/{manifest['module']}.preprocessed.sv"] = manifest["preprocessed_sha256"]
    for name, expected in sources.items():
        if digest(local_path(root, name)) != expected:
            raise ValueError(f"Source changed while preparing or validating review: {name}; restore the captured evidence or regenerate it in a fresh output directory")
    return sources


def prepare_review(root: Path, module: str, config: str, *, generic: bool = False,
                   output_dir: str = "outputs") -> dict:
    """Prepare a signed review baseline and preserve answers for unchanged behaviors."""
    folder = output_root(root, output_dir)
    manifest_path = local_path(root, folder / "evidence/manifest.json")
    manifest_hash = digest(manifest_path)
    validator = validate_generic_evidence if generic else validate_evidence
    manifest, _ = validator(root, module, config, output_dir)
    design, _ = artifact_paths(root, module, output_dir)
    target = local_path(root, folder / "semantic_review.json")
    previous_bytes = target.read_bytes() if target.exists() else None
    design_text = design.read_bytes().decode("utf-8")
    ids = behavior_ids(design_text)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Define unique P-* behavior headings before preparing semantic_review.json")
    fingerprints = behavior_fingerprints(design_text, ids)
    baseline = {
        "module": module, "config": config, "document_sha256": hashlib.sha256(design_text.encode()).hexdigest(),
        "manifest_sha256": manifest_hash,
        "sources": review_sources(root, manifest, output_dir),
        "behavior_fingerprints": fingerprints,
    }
    previous_baseline = {}
    previous_behaviors = {}
    if previous_bytes is not None:
        previous = json.loads(previous_bytes)
        if not isinstance(previous, dict):
            raise ValueError(f"{target}: expected a review JSON object; repair the review before retrying")
        previous_baseline = previous.get("baseline")
        records = previous.get("behaviors")
        if previous.get("schema_version") != REVIEW_SCHEMA_VERSION or not isinstance(previous_baseline, dict):
            raise ValueError(f"{target}: expected schema_version={REVIEW_SCHEMA_VERSION}; remove the invalid review record and run review")
        receipt(root, previous_baseline)
        previous_fingerprints = previous_baseline.get("behavior_fingerprints")
        if (not isinstance(records, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in records)
                or len({item["id"] for item in records}) != len(records)
                or not isinstance(previous_fingerprints, dict)
                or {item["id"] for item in records} != set(previous_fingerprints)
                or any(item.get("fingerprint") != previous_fingerprints[item["id"]] for item in records)):
            raise ValueError(f"{target}: expected unique behavior records matching the signed fingerprints; repair their IDs/fingerprints before running review")
        previous_behaviors = {item["id"]: item for item in records}
        if {k: v for k, v in previous_baseline.items() if k != "signature"} == baseline:
            return {"ok": True, "artifact": str(target.relative_to(root)), "preserved": True,
                    "preserved_behaviors": len(ids), "changed_behaviors": [], "changed_count": 0}
    manifest_unchanged = (
        isinstance(previous_baseline, dict)
        and previous_baseline.get("module") == module
        and previous_baseline.get("config") == config
        and previous_baseline.get("manifest_sha256") == baseline["manifest_sha256"]
        and previous_baseline.get("sources") == baseline["sources"]
    )

    behaviors = []
    preserved = 0
    changed = []
    for identifier in ids:
        old = previous_behaviors.get(identifier)
        if (
            manifest_unchanged
            and isinstance(old, dict)
            and previous_baseline.get("behavior_fingerprints", {}).get(identifier) == fingerprints[identifier]
            and old.get("fingerprint") == fingerprints[identifier]
        ):
            kept = dict(old)
            kept["fingerprint"] = fingerprints[identifier]
            behaviors.append(kept)
            preserved += 1
        else:
            changed.append(identifier)
            behaviors.append({"id": identifier, "fingerprint": fingerprints[identifier],
                              "fact_status": "pending", "facts": [], "checks": {
                                  aspect: {"status": "pending", "conclusion": "", "evidence": [],
                                           **({"ck_ids": [], "coverage_ids": []} if aspect == "verification_plan" else {})}
                                  for aspect in ASPECTS
                              }})
    value = {
        "schema_version": REVIEW_SCHEMA_VERSION, "baseline": receipt(root, baseline, sign=True),
        "behaviors": behaviors,
    }
    if (digest(design) != baseline["document_sha256"] or digest(manifest_path) != manifest_hash
            or review_sources(root, manifest, output_dir) != baseline["sources"]
            or (target.read_bytes() if target.exists() else None) != previous_bytes):
        raise ValueError("Design, manifest, source or review changed while preparing review; preserve edits and retry review")
    write_record(target, value, expected_bytes=previous_bytes)
    return {"ok": True, "artifact": str(target.relative_to(root)), "behaviors": len(ids),
            "preserved_behaviors": preserved,
            "changed_behaviors": changed[:12], "changed_count": len(changed),
            "next_action": f"Read {target.relative_to(root)} for all pending P-* items, then Guide_Doc/source-review-guide.md and the cited RTL; complete their structured facts and review checks."}


def validate_review(root: Path, module: str, manifest: dict, output_dir: str) -> None:
    """Check review coverage, source locations and freshness without claiming semantic proof."""
    folder = output_root(root, output_dir)
    target = local_path(root, folder / "semantic_review.json")
    value = read_json(target)
    design, _ = artifact_paths(root, module, output_dir)
    text = design.read_text(encoding="utf-8")
    baseline = value.get("baseline")
    if value.get("schema_version") != REVIEW_SCHEMA_VERSION or not isinstance(baseline, dict):
        raise ValueError(f"{target}: expected schema_version={REVIEW_SCHEMA_VERSION} and a tool-created baseline; run review")
    receipt(root, baseline)
    ids = behavior_ids(text)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError(f"{target}: define unique P-* behavior headings before review")
    fingerprints = behavior_fingerprints(text, ids)
    expected = {"module": module, "config": manifest["config"], "document_sha256": digest(design),
                "manifest_sha256": digest(local_path(root, folder / "evidence/manifest.json")),
                "sources": review_sources(root, manifest, output_dir),
                "behavior_fingerprints": fingerprints}
    if {k: v for k, v in baseline.items() if k != "signature"} != expected:
        raise ValueError(f"{target}: stale review after document/source changes; run review to refresh changed behaviors")
    behaviors = value.get("behaviors")
    if (not isinstance(behaviors, list) or any(not isinstance(b, dict) for b in behaviors)
            or len(ids) != len(set(ids)) or not ids
            or sorted(b.get("id", "") for b in behaviors) != sorted(ids)):
        raise ValueError(f"{target}: behaviors must contain each current P-* exactly once")
    for behavior in behaviors:
        if behavior.get("fingerprint") != fingerprints.get(behavior.get("id")):
            raise ValueError(f"{target}: {behavior.get('id', '<unknown>')} is missing its current dependency fingerprint; run review")
        checks = behavior.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(ASPECTS):
            raise ValueError(f"{target}: {behavior['id']} must contain exactly these checks: {', '.join(ASPECTS)}")
    visible = prose_text(text)
    tables = contract_rows(text)
    open_states = {row['cells'][0]: row['cells'][4] for row in tables['open']}
    evidence_rows = {}
    for row in tables['evidence']:
        evidence_id = row['cells'][0]
        evidence_rows[evidence_id] = source_locations(
            row['source_cells'][2], root / f"{output_dir}/{module}_design_document_zh.md", root
        )
    behavior_evidence = {}
    behavior_check_ranges = {}
    sections = document_sections(text)
    for index, section in enumerate(sections):
        match = re.match(r"P-[A-Z0-9]+(?:-[A-Z0-9]+)*", section['title'])
        if section['level'] != 3 or match is None:
            continue
        end = next((candidate['line'] - 1 for candidate in sections[index + 1:] if candidate['level'] <= 3), len(text.splitlines()))
        body = "\n".join(text.splitlines()[section['line']:end])
        cited = reference_ids(body, 'E')
        ranges = [location for evidence_id in cited for location in evidence_rows.get(evidence_id, [])]
        behavior_evidence[match.group()] = ranges
        checks = next((item for item in behaviors if item.get('id') == match.group()), {}).get('checks', {})
        behavior_check_ranges[match.group()] = {
            aspect: [
                (item.get('path'), item.get('start_line'), item.get('end_line'))
                for item in check.get('evidence', [])
                if isinstance(item, dict) and isinstance(item.get('path'), str)
                and type(item.get('start_line')) is int and type(item.get('end_line')) is int
            ]
            for aspect, check in checks.items() if isinstance(check, dict)
        }
    validate_behavior_facts(root, behaviors, baseline, target, open_states, behavior_evidence, behavior_check_ranges)
    plans = {row['cells'][2]: row['cells'] for row in tables['plan']}
    for behavior in behaviors:
        for aspect, check in behavior["checks"].items():
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
    write_record(target, record, expected_bytes=target.read_bytes() if target.exists() else None)
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
