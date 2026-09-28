"""Assemble a bounded Bug context from indexed records and original text."""

from __future__ import annotations

from pathlib import Path
import json

from .json_io import read_object
from .review_claims import source_role
from .review_store import REF_PATTERN, ReviewIndex, load_record, source_lines


SECTIONS = ("summary", "cases", "waveform", "spec", "rtl", "decision", "claims")


def bug_context(output: Path, bug_id: str, sections: list[str] | None = None,
                max_lines: int = 20, max_chars: int = 16000,
                case_offset: int = 0, ref_offset: int = 0) -> dict:
    """Return only requested source slices and existing evidence for one exact Bug ID."""
    index = load_record(output, "review_index.json", "index")
    if not isinstance(index, ReviewIndex) or bug_id not in index.bugs:
        raise ValueError(f"Bug ID not indexed: {bug_id}; available={index.bug_order[:30]}")
    chosen = sections or list(SECTIONS[:-1])
    unknown = set(chosen) - set(SECTIONS)
    if (unknown or not 1 <= max_lines <= 80 or not 1000 <= max_chars <= 30000
            or case_offset < 0 or ref_offset < 0):
        raise ValueError(f"sections must be from {SECTIONS}; max_lines=1..80, max_chars=1000..30000, offsets>=0")
    if index.stage_status.get("dut_evidence") != "complete" and set(chosen) - {"cases", "waveform"}:
        raise ValueError("original claim context is available after independent case triage and DUT evidence")
    entry = index.bugs[bug_id]
    source_root = output / "inputs" / index.workspace["name"]
    assignment = None
    draft = output / "drafts/attribution.json"
    if not index.claim_mapping_path and draft.is_file():
        assignment = next((item for item in read_object(draft).get("bugs", [])
                           if isinstance(item, dict) and item.get("bug_id") == bug_id), None)
    analysis_refs = entry.analysis_refs or (assignment.get("claim_refs", []) if assignment else [])
    case_ids = entry.case_ids or (assignment.get("case_ids", []) if assignment else [])
    attribution_rationale = str(entry.attribution_rationale or (
        assignment.get("rationale", "") if assignment else ""))

    def excerpt(reference: str) -> dict:
        """Preserve an invalid candidate as a diagnostic in the bounded view."""
        try:
            return {**source_lines(source_root, reference, max_lines),
                    "source_role": source_role(reference)}
        except (ValueError, OSError) as error:
            return {"ref": reference, "error": str(error)}

    result: dict = {"bug_id": bug_id, "origin": entry.origin,
                    "reported_confidence": entry.reported_confidence,
                    "attribution": {
                        "status": "committed" if index.claim_mapping_path else "draft" if assignment else "unfilled",
                        "source_labels": entry.source_labels or (assignment.get("source_labels", []) if assignment else []),
                        "bg_ids": entry.bg_ids or (assignment.get("bg_ids", []) if assignment else []),
                        "fg_ids": entry.fg_ids or (assignment.get("fg_ids", []) if assignment else []),
                        "fc_ids": entry.fc_ids or (assignment.get("fc_ids", []) if assignment else []),
                        "ck_ids": entry.ck_ids or (assignment.get("ck_ids", []) if assignment else []),
                        "rationale": attribution_rationale[:min(600, max_chars // 4)],
                        "rationale_truncated": len(attribution_rationale) > min(600, max_chars // 4)}}
    if "claims" in chosen:
        if not analysis_refs and not index.claim_mapping_path:
            result["claim_mapping_required"] = (
                "Read original blocks with ReportClaimBlocks and fill drafts/attribution.json; "
                "claim ownership is not inferred from CK paths or keywords")
        claims = []
        markers = {"<BUG-OVERVIEW>": "overview", "<BUG-SYMPTOMS>": "symptoms",
                   "<BUG-TRIGGER>": "trigger"}
        for reference in analysis_refs[ref_offset:ref_offset + 8]:
            match = REF_PATTERN.fullmatch(reference)
            if match is None:
                continue
            source_lines(source_root, reference, 1)
            lines = (source_root / match.group(1)).read_text(encoding="utf-8", errors="replace").splitlines()
            start, end = int(match.group(2)), int(match.group(3) or match.group(2))
            item = {"ref": reference, "fields": {}}
            item["source_role"] = "original_report_claim"
            for position in range(start - 1, min(end, len(lines))):
                field = markers.get(lines[position].strip())
                if not field:
                    continue
                body = []
                for line in lines[position + 1:min(end, position + 11)]:
                    if line.startswith(("<", "#")):
                        break
                    body.append(line)
                item["fields"][field] = {"ref": f"{match.group(1)}:{position + 1}-{position + len(body) + 1}",
                                         "text": "\n".join(body).strip()}
            item["validation_scenario"] = item["fields"].get("trigger")
            item["observed_behavior"] = item["fields"].get("symptoms")
            overview = item["fields"].get("overview")
            item["expected_behavior"] = {"status": "needs_review", "candidate_ref": overview["ref"]} if overview else None
            claims.append(item)
        result["claims"] = claims
        result["next_ref_offset"] = ref_offset + len(claims) if len(analysis_refs) > ref_offset + len(claims) else None
    if "summary" in chosen:
        result["summary"] = [excerpt(ref)
                             for ref in [entry.summary_ref, *analysis_refs[ref_offset:ref_offset + 8]] if ref]
        result["check_points"] = entry.check_points
    if "cases" in chosen or "waveform" in chosen:
        records = []
        for case_id in case_ids[case_offset:case_offset + 20]:
            if case_id not in index.cases:
                continue
            case_entry = index.cases[case_id]
            case = load_record(output, case_entry.record_path, "case")
            item = {"case_id": case_id, "replay_target": case_entry.replay_target,
                    "waveform_test_case_name": case_entry.waveform_test_case_name}
            if "cases" in chosen:
                item["replay"] = case.replay.model_dump(mode="json")
                item["test_review"] = case.test_review.model_dump(mode="json")
                item["failure_analysis"] = case.failure_analysis.model_dump(mode="json")
            if "waveform" in chosen:
                item["waveform"] = case.waveform.model_dump(mode="json")
            records.append(item)
        result["cases"] = records
        result["next_case_offset"] = case_offset + len(records) if len(case_ids) > case_offset + len(records) else None
    bug = load_record(output, entry.review_path, "bug") if entry.review_path else None
    if "spec" in chosen:
        refs = list(dict.fromkeys([*entry.spec_candidates, *(bug.spec_refs if bug else [])]))
        result["spec"] = [excerpt(ref) for ref in refs[ref_offset:ref_offset + 10]]
        result["spec_truncated"] = len(refs) > ref_offset + 10
    if "rtl" in chosen:
        refs = list(dict.fromkeys([*entry.rtl_candidates, *(bug.rtl_refs if bug else [])]))
        result["rtl"] = [excerpt(ref) for ref in refs[ref_offset:ref_offset + 10]]
        result["rtl_truncated"] = len(refs) > ref_offset + 10
    if "decision" in chosen:
        result["decision"] = bug.model_dump(mode="json") if bug else None
        if bug and bug.decision.root_id and index.root_path:
            roots = load_record(output, index.root_path, "roots")
            result["root"] = next((root.model_dump(mode="json") for root in roots.roots
                                   if root.root_id == bug.decision.root_id), None)
    result["output_truncated"] = False
    while len(json.dumps(result, ensure_ascii=False)) > max_chars:
        lists = [(key, value) for key, value in result.items() if isinstance(value, list) and value]
        if lists:
            key, values = max(lists, key=lambda pair: len(json.dumps(pair[1], ensure_ascii=False)))
            values.pop()
            if key == "claims":
                result["next_ref_offset"] = ref_offset + len(values)
            if key == "cases":
                result["next_case_offset"] = case_offset + len(values)
            result["output_truncated"] = True
            result["truncated_section"] = key
            continue
        if result.get("decision") is not None:
            result["decision"] = None
            result["output_truncated"] = True
            result["truncated_section"] = "decision"
            continue
        if result.get("root") is not None:
            result["root"] = None
            result["output_truncated"] = True
            result["truncated_section"] = "root"
            continue
        for key, value in result.items():
            if isinstance(value, str) and len(value) > 100:
                result[key] = value[:100]
                result["output_truncated"] = True
                break
        else:
            break
    return result
