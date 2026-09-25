"""Build and validate a structured inventory of a reported Bug analysis."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from .markdown_parser import parse_bug_claims
from .reported_roots import parse_reported_root_causes
from .utils import normalize_nodeid


SCHEMA = "reported_bug_inventory.v1"


def _sha256(path: Path) -> str:
    """Return the content digest used to bind an inventory to its report."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _claim_dict(claim: Any) -> dict[str, Any]:
    """Convert a ClaimRecord into a JSON-safe report-facing record."""
    location = claim.source_location
    return {
        "claim_id": claim.claim_id,
        "bug_id": claim.bg_name or claim.bug_identity or claim.claim_id,
        "bug_identity": claim.bug_identity,
        "identity_type": claim.identity_type,
        "summary": claim.summary,
        "fg": claim.fg,
        "fc": claim.fc,
        "ck": claim.ck,
        "confidence_percent": claim.confidence_percent,
        "root_cause": claim.root_cause,
        "proposed_fix": claim.proposed_fix,
        "expected": claim.expected,
        "observed": claim.observed,
        "referenced_tests": sorted(set(normalize_nodeid(x) for x in claim.referenced_tests)),
        "rtl_regions": list(claim.proposed_rtl_refs),
        "parse_diagnostics": list(claim.parse_diagnostics),
        "source": {
            "path": location.path,
            "line_start": location.line_start,
            "line_end": location.line_end,
            "excerpt": location.original_text,
        },
    }


def build_report_inventory(path: str | Path, *, run_key: str, model: str, dut: str,
                           test_summary_path: str = "", claims: Iterable[Any] | None = None) -> dict[str, Any]:
    """Parse one Markdown report into a stable, replay-ready inventory."""
    report_path = Path(path)
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    parsed_claims = list(claims) if claims is not None else parse_bug_claims(
        str(report_path), run_key=run_key, model=model, dut=dut
    )
    roots = parse_reported_root_causes(str(report_path), test_summary_path)
    bug_rows = [_claim_dict(claim) for claim in parsed_claims]
    root_entries = roots.get("entries", []) if isinstance(roots, dict) else []
    root_by_id: dict[str, dict[str, Any]] = {}
    for entry in root_entries:
        root_match = re.search(r"<ROOT-([A-Za-z0-9_-]+)>", str(entry.get("title", "")))
        if root_match:
            root_by_id[root_match.group(1)] = entry
    for bug in bug_rows:
        trigger = str(bug.get("source", {}).get("excerpt", ""))
        refs = re.findall(r"<CAUSE-REF-(ROOT-[A-Za-z0-9_-]+)>", trigger)
        matching_entries = [entry for entry in root_entries if bug.get("bug_id") in {
            str(name) for name in entry.get("bg_names", [])
        }]
        if matching_entries:
            refs = re.findall(
                r"<ROOT-([A-Za-z0-9_-]+)>",
                "\n".join(str(entry.get("title", "")) for entry in matching_entries),
            )
            refs = ["ROOT-" + ref for ref in refs]
        bug["root_refs"] = sorted(set(refs))
        if refs and not bug.get("root_cause"):
            entry = root_by_id.get(refs[0].removeprefix("ROOT-"), {})
            bug["root_cause"] = re.sub(r"\s*<ROOT-[^>]+>", "", str(entry.get("title", ""))).strip() or None
    clusters: dict[str, dict[str, Any]] = {}
    for bug in bug_rows:
        label = str(bug.get("root_cause") or "").strip()
        if not label:
            continue
        key = " ".join(sorted(_tokens(label))) or label.lower()
        cluster = clusters.setdefault(key, {
            "cluster_id": "REPORTED-ROOT-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12],
            "label": label,
            "bug_ids": [],
            "source_labels": [],
        })
        cluster["bug_ids"].append(bug["bug_id"])
        if label not in cluster["source_labels"]:
            cluster["source_labels"].append(label)
    return {
        "schema": SCHEMA,
        "source": {
            "path": str(report_path),
            "sha256": _sha256(report_path),
            "run_key": run_key,
            "model": model,
            "dut": dut,
        },
        "bugs": bug_rows,
        "root_cause_clusters": list(clusters.values()),
        "root_causes": roots,
        "diagnostics": [
            diagnostic
            for claim in parsed_claims
            for diagnostic in claim.parse_diagnostics
        ],
    }


def _failed(execution: dict[str, Any]) -> bool:
    """Return whether a parsed execution or one of its phases failed."""
    failed = {"failed", "fail", "error"}
    return str(execution.get("outcome", "")).lower() in failed or any(
        str(phase.get("outcome", "")).lower() in failed
        for phase in execution.get("phases", [])
    )


def _tokens(value: object) -> set[str]:
    """Extract conservative comparison tokens from report and replay text."""
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]{3,}", str(value or ""))}


def validate_report_inventory(inventory: dict[str, Any], executions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compare report-associated cases with a fresh suite replay.

    Missing executions remain explicit and are never treated as passes. Cause
    comparison is intentionally advisory: text overlap is evidence for review,
    not an automatic Bug verdict.
    """
    execution_rows = [dict(row) for row in executions]
    by_node = {normalize_nodeid(row.get("nodeid", "")): row for row in execution_rows}

    def matching_rows(nodeid: str) -> list[dict[str, Any]]:
        """Match exact and parameterized descendants of one report node."""
        canonical = normalize_nodeid(nodeid)
        exact = by_node.get(canonical)
        if exact is not None:
            return [exact]
        base = canonical.split("[", 1)[0]
        return [row for key, row in by_node.items() if key.split("[", 1)[0] == base]
    reported_cases = {
        normalize_nodeid(case)
        for bug in inventory.get("bugs", [])
        for case in bug.get("referenced_tests", [])
        if normalize_nodeid(case)
    }
    cases = []
    for bug in inventory.get("bugs", []):
        for nodeid in bug.get("referenced_tests", []):
            canonical = normalize_nodeid(nodeid)
            matched = matching_rows(canonical)
            if not matched:
                status = "not_collected"
                observed = ""
            else:
                status = "reproduced_failure" if any(_failed(row) for row in matched) else "passed"
                observed = " ".join(
                    text for row in matched
                    for text in (row.get("exception_type"), row.get("exception_message"))
                    if text
                )
            report_text = " ".join(filter(None, [bug.get("root_cause"), bug.get("observed"), bug.get("expected")]))
            overlap = len(_tokens(report_text) & _tokens(observed))
            cause_status = "not_comparable" if not report_text or not observed else (
                "consistent_text_only" if overlap else "inconclusive_requires_waveform"
            )
            cases.append({
                "bug_id": bug.get("bug_id"),
                "nodeid": canonical,
                "status": status,
                "observed": observed,
                "cause_comparison": {
                    "status": cause_status,
                    "token_overlap": overlap,
                    "waveform_required": status == "reproduced_failure",
                },
            })
    unreported = []
    for row in execution_rows:
        nodeid = normalize_nodeid(row.get("nodeid", ""))
        if _failed(row) and nodeid not in reported_cases:
            unreported.append({
                "nodeid": nodeid,
                "outcome": row.get("outcome", ""),
                "exception_type": row.get("exception_type"),
                "exception_message": row.get("exception_message"),
            })
    return {
        "schema": "reported_bug_replay_validation.v1",
        "report_source": inventory.get("source", {}),
        "associated_cases": cases,
        "unreported_failures": unreported,
        "summary": {
            "execution_count": len(execution_rows),
            "current_failure_count": sum(_failed(row) for row in execution_rows),
            "current_pass_count": sum(not _failed(row) for row in execution_rows),
            "reported_bug_count": len(inventory.get("bugs", [])),
            "associated_case_count": len(cases),
            "reproduced_failure_count": sum(row["status"] == "reproduced_failure" for row in cases),
            "passed_count": sum(row["status"] == "passed" for row in cases),
            "not_collected_count": sum(row["status"] == "not_collected" for row in cases),
            "unreported_failure_count": len(unreported),
        },
        "root_cause_review": [
            {
                "bug_id": bug.get("bug_id"),
                "reported_root_cause": bug.get("root_cause") or "",
                "status": "reproduced" if any(
                    row["bug_id"] == bug.get("bug_id") and row["status"] == "reproduced_failure"
                    for row in cases
                ) else "not_reproduced",
            }
            for bug in inventory.get("bugs", [])
        ],
    }
