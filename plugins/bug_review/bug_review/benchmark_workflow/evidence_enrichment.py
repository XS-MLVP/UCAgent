"""Evidence enrichment for the Bug Review workflow."""
import copy
import hashlib
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple


_CONFIDENCE_PATTERNS = (
    re.compile(r"Bug\s*置信度\s*(\d+)%", re.I),
    re.compile(r"<BG-[^>]+-(\d+)>", re.I),
)

_ROOT_CAUSE_HEADINGS = (
    re.compile(r"(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?(?:Bug\s*)?(?:根本原因|根因)(?:分析)?(?:\*\*)?\s*[：:]\s*", re.I),
    re.compile(r"(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?Root\s+Cause(?:\s+Analysis)?(?:\*\*)?\s*[：:]\s*", re.I),
)

_ROOT_CAUSE_END = re.compile(
    r"\n\s*(?:[-*]\s*)?(?:\*\*)?(?:修复(?:建议|方案|说明)?|解决说明|Expected|预期|实际观测|Observed)(?:\*\*)?\s*[：:]",
    re.I,
)

_EXCLUSION_CUES = (
    "非bug",
    "非 bug",
    "zero_confidence",
    "zero confidence",
    "强制通过",
    "隐式覆盖",
    "测试通过",
    "pass",
)

_NON_RTL_CLAIM_CUES = (
    "non-rtl",
    "non rtl",
    "nonrtl",
    "testbench",
    "fixture",
    "infrastructure",
    "environment failure",
    "mock",
    "pytest failure",
)


def _first_text(values: Sequence[object]) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def extract_declared_confidence(text: object) -> Optional[int]:
    source = str(text or "")
    for pattern in _CONFIDENCE_PATTERNS:
        match = pattern.search(source)
        if match:
            return int(match.group(1))
    return None


def extract_root_cause(text: object) -> Optional[str]:
    source = str(text or "").strip()
    if not source:
        return None
    for heading in _ROOT_CAUSE_HEADINGS:
        match = heading.search(source)
        if not match:
            continue
        body = source[match.end():]
        end_match = _ROOT_CAUSE_END.search(body)
        if end_match:
            body = body[:end_match.start()]
        body = body.strip().strip("-*").strip()
        if body:
            return body
    tagged = re.search(r"(?m)^\s*<BUG-ROOT-CAUSE>\s*$", source)
    if tagged:
        body = source[tagged.end():]
        end_match = re.search(r"(?m)^#{1,6}\s+|^\s*</?BUG-[A-Z-]+>\s*$", body)
        if end_match:
            body = body[:end_match.start()]
        body = body.strip().strip("-*").strip()
        if body:
            return body
    return None


def infer_trigger(record: Dict[str, object]) -> Optional[str]:
    text = " ".join(
        str(value or "")
        for value in (record.get("property_text"), record.get("root_cause"), record.get("expected"), record.get("observed"))
    ).lower()
    signals = {str(value).lower() for value in record.get("signals", [])}
    if "reset" in text or "复位" in text or "rst" in signals:
        return "reset active / release boundary"
    if "done" in text or "完成" in text:
        return "completion handshake"
    if "load" in text or "加载" in text or "ld" in signals:
        return "load/start transaction"
    return None


def claim_exclusion(claim: Dict[str, object]) -> Dict[str, object]:
    source_report = claim.get("source_report", {})
    source_text = source_report.get("original_text", "") if isinstance(source_report, dict) else ""
    confidence = claim.get("confidence_percent")
    if confidence is None:
        confidence = extract_declared_confidence(source_text or claim.get("summary"))
    normalized = str(source_text or claim.get("summary") or "").lower()
    reason_codes = []
    if confidence == 0:
        reason_codes.append("declared_zero_confidence")
    if any(cue in normalized for cue in _EXCLUSION_CUES):
        reason_codes.append("source_marks_non_bug_or_placeholder")
    excluded = confidence == 0
    return {
        "excluded": excluded,
        "confidence_percent": confidence,
        "reason_codes": reason_codes,
        "source": {
            "path": source_report.get("path") if isinstance(source_report, dict) else None,
            "line_start": source_report.get("line_start") if isinstance(source_report, dict) else None,
            "line_end": source_report.get("line_end") if isinstance(source_report, dict) else None,
        },
    }


def _normalize_nodeid(value: object) -> str:
    return str(value or "").replace("unity_test/", "").strip()


def classify_test_trace(
    test: Dict[str, object],
    explicitly_referenced: Sequence[str],
) -> Tuple[str, str]:
    nodeid = _normalize_nodeid(test.get("nodeid"))
    referenced = {_normalize_nodeid(value) for value in explicitly_referenced}
    if nodeid and nodeid in referenced:
        return "bug_specific", "explicitly_referenced_by_claim"

    outcome = str(test.get("outcome") or "").lower()
    path_text = f"{nodeid} {test.get('source_file') or ''}".lower()
    if outcome in {"failed", "error"} and (
        test.get("exception_message") or test.get("assertion_preview")
    ):
        return "bug_specific", "failing_assertion_or_exception"
    if any(token in path_text for token in ("env_fixture", "fixture", "implicit_coverage_placeholder")):
        return "supporting_infrastructure", "fixture_or_placeholder_test"
    if outcome in {"passed", "skipped"}:
        return "supporting_infrastructure", "non_failing_indirect_support"
    return "bug_specific", "candidate_linked_test"


def _oracle_evidence(tests: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    rows = []
    for test in tests:
        if test.get("test_role") != "bug_specific":
            continue
        rows.append(
            {
                "nodeid": test.get("nodeid"),
                "outcome": test.get("outcome"),
                "duration_seconds": test.get("duration_seconds"),
                "phases": test.get("phases", []),
                "assertions": test.get("assertions", []),
                "assertion_preview": test.get("assertion_preview", []),
                "exception_type": test.get("exception_type"),
                "exception_message": test.get("exception_message"),
            }
        )
    return rows


def _claim_text(claim: Dict[str, object]) -> str:
    source_report = claim.get("source_report", {})
    source_text = source_report.get("original_text", "") if isinstance(source_report, dict) else ""
    parts = [
        claim.get("claim_class"),
        claim.get("bg_name"),
        claim.get("summary"),
        claim.get("root_cause"),
        source_text,
    ]
    return " ".join(str(part or "") for part in parts).strip().lower()


def _claim_is_non_rtl(claim: Dict[str, object], record: Dict[str, object]) -> bool:
    claim_class = str(claim.get("claim_class") or "").upper()
    if claim_class in {"NON_RTL_CLAIM", "TESTBENCH", "INFRASTRUCTURE"}:
        return True
    text = _claim_text(claim)
    if any(cue in text for cue in _NON_RTL_CLAIM_CUES):
        return True
    if not record.get("rtl_regions") and any(token in text for token in ("fixture", "infrastructure", "testbench")):
        return True
    return False


def _make_diagnostic(
    code: str,
    severity: str,
    message: str,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, object]] = None,
    suggested_action: Optional[str] = None,
    source: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    seed = f"{code}|{entity_id or ''}|{message}"
    diagnostic_id = f"DIAG-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    return {
        "code": code,
        "details": details or {},
        "diagnostic_id": diagnostic_id,
        "entity_id": entity_id,
        "message": message,
        "severity": severity,
        "source": source,
        "suggested_action": suggested_action,
    }


def _evidence_quality(record: Dict[str, object]) -> Dict[str, str]:
    tests = [item for item in record.get("bug_specific_tests", []) if isinstance(item, dict)]
    oracle_evidence = [item for item in record.get("oracle_evidence", []) if isinstance(item, dict)]
    replay_results = [item for item in record.get("replay_results", []) if isinstance(item, dict)]
    replay_statuses = {str(item.get("status") or "").strip() for item in replay_results if item.get("status")}
    completed_replay_statuses = {
        "reproduced", "not_reproduced", "not_reproduced_same_snapshot",
        "not_reproduced_snapshot_changed",
    }
    has_failed_test = any(str(item.get("outcome") or "").lower() in {"failed", "error"} for item in tests)
    has_passed_test = any(str(item.get("outcome") or "").lower() == "passed" for item in tests)
    has_oracle = any(item.get("assertions") or item.get("exception_message") for item in oracle_evidence)
    has_spec = bool(record.get("spec_matches"))
    has_rtl = bool(record.get("rtl_regions"))
    has_waveform = any(
        item.get("waveform_observations") or item.get("waveform_summary")
        for item in [item for item in record.get("artifact_evidence", []) if isinstance(item, dict)]
    )
    has_coverage = record.get("coverage_evidence_summary") not in (None, "", "none")
    evidence_layers = sum(
        1
        for enabled in (
            bool(tests),
            has_oracle,
            has_coverage,
            has_waveform,
            has_rtl,
            has_spec,
            bool(completed_replay_statuses & replay_statuses),
        )
        if enabled
    )

    if record.get("candidate_disposition") == "excluded_declared_candidate":
        qualification = "NON_RTL_CLAIM"
    elif "reproduced" in replay_statuses and has_rtl and has_spec and has_oracle:
        qualification = "SUPPORTED_DECLARATION"
    elif has_rtl or has_spec or has_waveform or has_oracle or has_coverage:
        qualification = "PARTIALLY_SUPPORTED"
    else:
        qualification = "NON_RTL_CLAIM"

    if not tests:
        execution_support = "NO_CALL_EXECUTION"
    elif has_failed_test:
        execution_support = "FAILED_CALL_EXECUTION_MATCH"
    elif has_passed_test:
        execution_support = "PASSED_CALL_EXECUTION_MATCH"
    else:
        execution_support = "FAILED_CALL_EXECUTION_MATCH" if has_oracle else "NO_CALL_EXECUTION"

    if has_failed_test and has_oracle:
        oracle_quality = "DYNAMIC_DUT_ORACLE"
    elif has_failed_test:
        oracle_quality = "AMBIGUOUS_FAILED_ASSERTION"
    else:
        oracle_quality = "NO_DUT_ORACLE"

    if ({"not_reproduced", "not_reproduced_same_snapshot"} & replay_statuses) and has_rtl:
        report_consistency = "CONTRADICTORY"
    else:
        report_consistency = "CONSISTENT_OR_UNKNOWN"

    if has_rtl:
        rtl_traceability = "RTL_VALIDATED"
    elif record.get("rtl_dependency_preview"):
        rtl_traceability = "RTL_PLAUSIBLE"
    else:
        rtl_traceability = "RTL_UNAVAILABLE"

    semantic_completeness = "COMPLETE" if all(
        record.get(field) for field in ("expected", "observed", "root_cause", "trigger")
    ) else "PARTIAL"
    spec_traceability = "SPEC_TRACEABLE" if has_spec else "SPEC_UNAVAILABLE"

    return {
        "execution_support": execution_support,
        "oracle_quality": oracle_quality,
        "qualification": qualification,
        "report_consistency": report_consistency,
        "rtl_traceability": rtl_traceability,
        "semantic_completeness": semantic_completeness,
        "spec_traceability": spec_traceability,
        "evidence_layers": str(evidence_layers),
    }


def _record_diagnostics(record: Dict[str, object]) -> List[Dict[str, object]]:
    diagnostics: List[Dict[str, object]] = []
    if record.get("candidate_disposition") == "excluded_declared_candidate":
        diagnostics.append(
            _make_diagnostic(
                "NON_RTL_CLAIM",
                "INFO",
                "candidate was explicitly excluded by the source declaration",
                entity_id=f"{record.get('canonical_bug')}::{record.get('model')}",
                details={"reason_codes": record.get("exclusion_reason_codes", [])},
            )
        )
    for claim in record.get("claim_sources", []) or []:
        if not isinstance(claim, dict):
            continue
        if _claim_is_non_rtl(claim, record):
            diagnostics.append(
                _make_diagnostic(
                    "NON_RTL_CLAIM",
                    "WARNING",
                    "claim appears to describe testbench, API, or infrastructure behavior rather than RTL",
                    entity_id=claim.get("claim_id"),
                    details={
                        "bg_name": claim.get("bg_name"),
                        "summary": claim.get("summary"),
                    },
                    source=claim.get("source_report") if isinstance(claim.get("source_report"), dict) else None,
                )
            )
    if record.get("evidence_tier") == "replay_contradicted_review" or record.get("root_cause_validation") == "replay_conflict_review":
        diagnostics.append(
            _make_diagnostic(
                "HUMAN_REVIEW_REQUIRED",
                "WARNING",
                "replay contradicted the candidate but structural evidence remains",
                entity_id=f"{record.get('canonical_bug')}::{record.get('model')}",
                details={
                    "evidence_tier": record.get("evidence_tier"),
                    "score_reason": record.get("score_reason"),
                },
            )
        )
    if record.get("rtl_regions") and not record.get("rtl_dependency_preview"):
        diagnostics.append(
            _make_diagnostic(
                "STATIC_LINK_TARGET_MISSING",
                "WARNING",
                "RTL regions exist but no dependency preview was attached",
                entity_id=f"{record.get('canonical_bug')}::{record.get('model')}",
                details={"rtl_region_count": len(record.get("rtl_regions", []))},
            )
        )
    if record.get("replay_manifests") and not record.get("replay_results"):
        diagnostics.append(
            _make_diagnostic(
                "REPLAY_RESULT_MISSING",
                "WARNING",
                "candidate has a replay manifest but no replay result is attached",
                entity_id=f"{record.get('canonical_bug')}::{record.get('model')}",
            )
        )
    return diagnostics


def _evidence_dimensions(record: Dict[str, object]) -> Dict[str, bool]:
    artifacts = [item for item in record.get("artifact_evidence", []) if isinstance(item, dict)]
    replay_results = [item for item in record.get("replay_results", []) if isinstance(item, dict)]
    return {
        "execution": bool(record.get("bug_specific_tests")),
        "oracle": any(
            item.get("assertions") or item.get("exception_message")
            for item in record.get("oracle_evidence", [])
        ),
        "coverage": record.get("coverage_evidence_summary") not in (None, "", "none"),
        "waveform": any(
            item.get("waveform_observations") or item.get("waveform_summary")
            for item in artifacts
        ),
        "rtl": bool(record.get("rtl_regions")),
        "spec": bool(record.get("spec_matches")),
        "replay": any(item.get("status") not in (None, "", "not_run", "pending") for item in replay_results),
    }


def _validation_fact(value: object, reason: str, evidence: Sequence[str]) -> Dict[str, object]:
    return {"value": value, "reason": reason, "evidence": list(evidence)}


def derive_validation_facts(record: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    """Derive independent status facts from preserved evidence without new mutable state."""
    active = record.get("candidate_disposition") != "excluded_declared_candidate"
    claims = [item for item in record.get("claim_sources", []) if isinstance(item, dict)]
    declared = record.get("status") == "found" and active and bool(claims)
    failed_tests = [
        item for item in record.get("bug_specific_tests", [])
        if isinstance(item, dict) and str(item.get("outcome") or "").lower() in {"failed", "error"}
    ]
    oracle_quality = str(record.get("evidence_quality", {}).get("oracle_quality") or "")
    valid_oracle = bool(failed_tests) and oracle_quality == "DYNAMIC_DUT_ORACLE"
    exact_spec = [
        item for item in record.get("spec_matches", [])
        if isinstance(item, dict) and item.get("validation_status") == "EXACT_SPEC_SUPPORT"
    ]
    validated_rtl = [
        item for item in record.get("rtl_regions", [])
        if isinstance(item, dict) and str(item.get("validation_status") or "").startswith("VALIDATED")
    ]
    replay_statuses = [
        str(item.get("status") or "")
        for item in record.get("replay_results", [])
        if isinstance(item, dict) and item.get("status")
    ]
    if "reproduced" in replay_statuses:
        replay_state = "reproduced"
    elif "not_reproduced_same_snapshot" in replay_statuses or "not_reproduced" in replay_statuses:
        replay_state = "not_reproduced_same_snapshot"
    elif "not_reproduced_snapshot_changed" in replay_statuses:
        replay_state = "not_reproduced_snapshot_changed"
    elif any(status not in {"not_run", "pending"} for status in replay_statuses):
        replay_state = "inconclusive"
    else:
        replay_state = "not_run"
    comparison_ready = declared and valid_oracle and bool(exact_spec) and bool(validated_rtl)
    ground_truth_confirmed = comparison_ready and replay_state == "reproduced"

    return {
        "declared_by_ucagent": _validation_fact(
            declared,
            "active positive source declaration is present" if declared else "no active positive source declaration",
            [str(item.get("claim_id")) for item in claims if item.get("claim_id")],
        ),
        "failed_test_mapped": _validation_fact(
            bool(failed_tests),
            "a failed/error bug-specific test is mapped" if failed_tests else "no failed bug-specific test is mapped",
            [str(item.get("nodeid")) for item in failed_tests if item.get("nodeid")],
        ),
        "valid_dut_oracle": _validation_fact(
            valid_oracle,
            f"oracle_quality={oracle_quality or 'unknown'}",
            [str(item.get("nodeid")) for item in failed_tests if item.get("nodeid")],
        ),
        "specification_supported": _validation_fact(
            bool(exact_spec),
            "deterministically validated normative specification evidence exists" if exact_spec else "no EXACT_SPEC_SUPPORT evidence",
            [str(item.get("property_id")) for item in exact_spec if item.get("property_id")],
        ),
        "rtl_region_localized": _validation_fact(
            bool(validated_rtl),
            "source-validated RTL region exists" if validated_rtl else "no source-validated RTL region",
            [
                f"{item.get('path')}:{item.get('line_start')}-{item.get('line_end')}"
                for item in validated_rtl[:8]
            ],
        ),
        "independent_replay": _validation_fact(
            replay_state,
            "derived only from replay result statuses",
            replay_statuses,
        ),
        "comparison_ready": _validation_fact(
            comparison_ready,
            "requires declaration + valid DUT oracle + exact spec + validated RTL",
            [
                "declared_by_ucagent", "valid_dut_oracle",
                "specification_supported", "rtl_region_localized",
            ],
        ),
        "ground_truth_confirmed": _validation_fact(
            ground_truth_confirmed,
            "requires comparison_ready and independent replay reproduced",
            ["comparison_ready", "independent_replay"],
        ),
    }


def enrich_benchmark_record(record: Dict[str, object]) -> Dict[str, object]:
    enriched = copy.deepcopy(record)
    claims = [item for item in enriched.get("claim_sources", []) if isinstance(item, dict)]
    exclusions = []
    root_causes = []
    confidences = []
    explicit_tests = []
    for claim in claims:
        source_report = claim.get("source_report", {})
        source_text = source_report.get("original_text", "") if isinstance(source_report, dict) else ""
        confidence = claim.get("confidence_percent")
        if confidence is None:
            confidence = extract_declared_confidence(source_text or claim.get("summary"))
        claim["confidence_percent"] = confidence
        if confidence is not None:
            confidences.append(confidence)
        root_cause = claim.get("root_cause") or extract_root_cause(source_text)
        if root_cause:
            claim["root_cause"] = root_cause
            # Saved payloads can carry a diagnostic produced before the
            # structured BUG-ROOT-CAUSE fallback was available.  Once a
            # deterministic extraction succeeds, that diagnostic is stale.
            claim["parse_diagnostics"] = [
                item for item in claim.get("parse_diagnostics", [])
                if item != "ROOT_CAUSE_PARSE_MISSING"
            ]
            root_causes.append(root_cause)
        explicit_tests.extend(claim.get("referenced_tests", []))
        exclusion = claim_exclusion(claim)
        if exclusion["excluded"]:
            exclusion["claim_id"] = claim.get("claim_id")
            exclusion["bg_name"] = claim.get("bg_name")
            exclusions.append(exclusion)

    enriched["root_cause"] = enriched.get("root_cause") or _first_text(root_causes)
    enriched["reported_root_causes"] = list(dict.fromkeys(root_causes))
    enriched["declared_confidence_percent"] = max(confidences) if confidences else None
    enriched["trigger"] = enriched.get("trigger") or infer_trigger(enriched)
    enriched["failure_mode"] = enriched.get("failure_mode") or _first_text(
        [
            test.get("exception_type") or test.get("exception_message")
            for test in enriched.get("tests", [])
            if isinstance(test, dict) and str(test.get("outcome") or "").lower() in {"failed", "error"}
        ]
    )
    enriched["candidate_exclusions"] = exclusions
    replay_reproduced = any(
        isinstance(item, dict) and item.get("status") == "reproduced"
        for item in enriched.get("replay_results", [])
    )
    if claims and len(exclusions) == len(claims) and not replay_reproduced:
        enriched["candidate_disposition"] = "excluded_declared_candidate"
        enriched["exclusion_reason_codes"] = list(
            dict.fromkeys(code for item in exclusions for code in item.get("reason_codes", []))
        )
    else:
        enriched["candidate_disposition"] = "active_replay_override" if exclusions and replay_reproduced else "active"
        enriched["exclusion_reason_codes"] = []

    tests = []
    for test in enriched.get("tests", []):
        if not isinstance(test, dict):
            continue
        classified = copy.deepcopy(test)
        role, reason = classify_test_trace(classified, explicit_tests)
        classified["test_role"] = role
        classified["association_reason"] = reason
        tests.append(classified)
    enriched["tests"] = tests
    enriched["bug_specific_tests"] = [item for item in tests if item.get("test_role") == "bug_specific"]
    enriched["supporting_infrastructure_tests"] = [
        item for item in tests if item.get("test_role") == "supporting_infrastructure"
    ]
    enriched["oracle_evidence"] = _oracle_evidence(tests)
    enriched["evidence_dimensions"] = _evidence_dimensions(enriched)
    enriched["evidence_quality"] = _evidence_quality(enriched)
    enriched["diagnostics"] = _record_diagnostics(enriched)
    replay_statuses = {
        item.get("status") for item in enriched.get("replay_results", []) if isinstance(item, dict)
    }
    if "reproduced" in replay_statuses:
        enriched["root_cause_validation"] = "replay_confirmed"
    elif ({"not_reproduced", "not_reproduced_same_snapshot"} & replay_statuses) and enriched.get("root_cause"):
        enriched["root_cause_validation"] = "replay_conflict_review"
    elif "not_reproduced_snapshot_changed" in replay_statuses and enriched.get("root_cause"):
        enriched["root_cause_validation"] = "replay_snapshot_changed_review"
    elif enriched.get("root_cause") and enriched.get("rtl_regions"):
        enriched["root_cause_validation"] = "rtl_located"
    elif enriched.get("root_cause"):
        enriched["root_cause_validation"] = "reported_only"
    else:
        enriched["root_cause_validation"] = "missing"
    enriched["validation_facts"] = derive_validation_facts(enriched)
    return enriched


def enrich_benchmark_payload(payload: Dict[str, object]) -> Dict[str, object]:
    enriched = copy.deepcopy(payload)
    records = [
        enrich_benchmark_record(record) if isinstance(record, dict) else record
        for record in enriched.get("benchmark_records", [])
    ]
    diagnostics: List[Dict[str, object]] = []
    non_rtl_claims: List[Dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        diagnostics.extend(record.get("diagnostics", []) or [])
        for claim in record.get("claim_sources", []) or []:
            if not isinstance(claim, dict):
                continue
            if _claim_is_non_rtl(claim, record):
                non_rtl_claims.append(
                    {
                        "canonical_bug": record.get("canonical_bug"),
                        "dut": record.get("dut"),
                        "model": record.get("model"),
                        "claim_id": claim.get("claim_id"),
                        "bg_name": claim.get("bg_name"),
                        "summary": claim.get("summary"),
                        "source": claim.get("source_report") if isinstance(claim.get("source_report"), dict) else None,
                    }
                )
    current_exclusions = [
        {
            "canonical_bug": record.get("canonical_bug"),
            "dut": record.get("dut"),
            "model": record.get("model"),
            "candidate_ids": record.get("candidate_ids", []),
            "disposition": record.get("candidate_disposition"),
            "reason_codes": record.get("exclusion_reason_codes", []),
            "claims": record.get("candidate_exclusions", []),
        }
        for record in records
        if isinstance(record, dict) and record.get("candidate_disposition") == "excluded_declared_candidate"
    ]
    existing_exclusions = [
        item for item in enriched.get("candidate_exclusions", []) if isinstance(item, dict)
    ]
    exclusion_index = {
        (
            item.get("canonical_bug")
            or tuple(str(value) for value in (item.get("candidate_ids", []) or [])),
            item.get("model"),
        ): item
        for item in existing_exclusions + current_exclusions
    }
    enriched["candidate_exclusions"] = list(exclusion_index.values())

    active_bug_ids = {
        record.get("canonical_bug")
        for record in records
        if isinstance(record, dict)
        and record.get("status") == "found"
        and record.get("candidate_disposition") != "excluded_declared_candidate"
    }
    excluded_only_bug_ids = {
        record.get("canonical_bug")
        for record in records
        if isinstance(record, dict) and record.get("canonical_bug") not in active_bug_ids
    }
    enriched["excluded_canonical_bug_ids"] = sorted(value for value in excluded_only_bug_ids if value)
    enriched["benchmark_records"] = [
        record for record in records
        if not isinstance(record, dict) or record.get("canonical_bug") in active_bug_ids
    ]
    enriched["diagnostics"] = diagnostics
    enriched["non_rtl_claims"] = non_rtl_claims
    enriched["diagnostics_summary"] = {
        "total": len(diagnostics),
        "by_code": dict(sorted(Counter(item.get("code", "unknown") for item in diagnostics).items())),
        "by_severity": dict(sorted(Counter(item.get("severity", "unknown") for item in diagnostics).items())),
    }
    enriched["matrix"] = [
        row for row in enriched.get("matrix", [])
        if not isinstance(row, dict) or not row.get("canonical_bug") or row.get("canonical_bug") in active_bug_ids
    ]
    enriched["canonical_bugs"] = [
        bug for bug in enriched.get("canonical_bugs", [])
        if not isinstance(bug, dict) or bug.get("canonical_id") in active_bug_ids
    ]
    for row in enriched.get("matrix", []):
        if not isinstance(row, dict):
            continue
        bug_id = row.get("canonical_bug")
        for model, details in row.get("per_model", {}).items():
            record = next(
                (
                    item for item in enriched["benchmark_records"]
                    if isinstance(item, dict)
                    and item.get("canonical_bug") == bug_id
                    and item.get("model") == model
                ),
                None,
            )
            if record and record.get("candidate_disposition") == "excluded_declared_candidate":
                record["status"] = "excluded"
                details["found"] = False
                details["status"] = "excluded"
    return enriched
