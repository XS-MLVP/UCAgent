"""Parse saved pytest stdout into per-case failure digests and prefill facts."""

from __future__ import annotations

import re

_KEEP_OUTCOMES = {"failed", "error", "xpassed"}
_E_LINE_LIMIT = 6

_SECTION_RE = re.compile(r"^_{5,}\s+(\S+)\s+_{5,}$", re.M)
_LOC_RE = re.compile(r"^(\S+\.py):(\d+): ")
_FRAME_RE = re.compile(r"^(\S+\.py):(\d+): in (\S+)")


def parse_failures(stdout: str) -> dict[str, str]:
    """Split pytest stdout into {section_name: traceback_text}."""
    match = re.search(r"=+ FAILURES =+", stdout)
    if not match:
        return {}
    body = stdout[match.end():]
    stop = re.search(r"=+ (?:short test summary|warnings summary|no tests ran)", body)
    if stop:
        body = body[:stop.start()]
    marks = list(_SECTION_RE.finditer(body))
    return {mark.group(1): body[mark.end():marks[index + 1].start() if index + 1 < len(marks) else len(body)]
            for index, mark in enumerate(marks)}


def failure_digest(trace: str) -> dict:
    """Condense one traceback into mechanical facts the tools can record."""
    lines = [line.strip() for line in trace.splitlines() if line.strip()]
    e_lines: list[str] = []
    loc = fail_line = ""
    frames: list[str] = []
    for line in lines:
        if line.startswith("E ") and line[2:].strip() not in e_lines:
            e_lines.append(line[2:].strip())
        if not loc:
            hit = _LOC_RE.match(line)
            if hit:
                loc = f"{hit.group(1)}:{hit.group(2)}"
        if not fail_line and line.startswith("> "):
            fail_line = line[2:].strip()
        frame = _FRAME_RE.match(line)
        if frame:
            frames.append(f"{frame.group(1)}:{frame.group(2)}:{frame.group(3)}")
    return {"exc": e_lines[0] if e_lines else "", "loc": loc, "fail_line": fail_line,
            "e_lines": e_lines[:_E_LINE_LIMIT], "frames": frames[:8],
            "tail": "\n".join(lines[-10:])}


def section_key(section_name: str) -> str:
    """Reduce a pytest FAILURES section name to the bare test function part."""
    return section_name.strip().split("::")[-1]


def match_failure_digests(stdout: str, outcomes: dict[str, str]) -> tuple[dict, list[str]]:
    """Align parsed FAILURES sections to exact anomalous case IDs.

    Returns (digests, ambiguous) where digests maps case_id to its digest and
    ambiguous lists section names shared by multiple candidate cases, which are
    never guessed.
    """
    failed = {case_id for case_id, status in outcomes.items() if status in _KEEP_OUTCOMES}
    by_name: dict[str, list[str]] = {}
    for case_id in failed:
        by_name.setdefault(case_id.rsplit("::", 1)[-1], []).append(case_id)
    digests: dict[str, dict] = {}
    ambiguous: list[str] = []
    for section, trace in parse_failures(stdout).items():
        candidates = by_name.get(section_key(section), [])
        if len(candidates) != 1:
            ambiguous.append(section)
            continue
        digests[candidates[0]] = failure_digest(trace)
    return digests, ambiguous


def prefill_failure_analysis(case, digest: dict, evidence_ref: str = "") -> list[str]:
    """Fill only empty mechanical failure fields; never overwrite reviewer work.

    The traceback facts (assertion line, failing location, observed values) are
    tool-computed; the category, scenario and rationale stay with the reviewer.
    """
    analysis = case.failure_analysis
    filled: list[str] = []
    test = analysis.test_expected
    if not test.summary.strip() and digest["exc"]:
        message = digest["exc"]
        prefix = "AssertionError: "
        test.summary = message[len(prefix):] if message.startswith(prefix) else message
        filled.append("failure_analysis.test_expected.summary")
    if not test.assertion.strip() and digest["fail_line"]:
        test.assertion = digest["fail_line"]
        filled.append("failure_analysis.test_expected.assertion")
    if not test.source_refs and digest["loc"]:
        test.source_refs = [digest["loc"]]
        filled.append("failure_analysis.test_expected.source_refs")
    actual = analysis.actual
    if not actual.summary.strip() and digest["exc"]:
        actual.summary = digest["exc"]
        filled.append("failure_analysis.actual.summary")
    if not actual.observations and digest["e_lines"]:
        actual.observations = list(digest["e_lines"])
        filled.append("failure_analysis.actual.observations")
    if not actual.evidence_refs and evidence_ref:
        actual.evidence_refs = [evidence_ref]
        filled.append("failure_analysis.actual.evidence_refs")
    test_file = case.case_id.split("::")[0]
    if analysis.phase == "unknown" and digest["loc"] and digest["loc"].split(":")[0] == test_file:
        analysis.phase = "assertion"
        filled.append("failure_analysis.phase")
    return filled


_LOG_CLUES = (
    ("assertion", re.compile(r"AssertionError|assertion\s+(?:failed|failure)|^\s*E\s+assert\b", re.I)),
    ("stuck", re.compile(r"\bstuck\b|\bno[- ](?:commit|progress)\b|\btimed?\s*out\b|\bTimeoutError\b", re.I)),
    ("fatal", re.compile(r"\bABORT(?:ED)?\b|\bSIG(?:ABRT|SEGV)\b|\bfatal\b|segmentation fault", re.I)),
    ("mismatch", re.compile(r"\bmismatch\b|\bexpected\b.*\b(?:got|actual)\b", re.I)),
)


def triage_log(stdout: str, source_file: str, invocation_id: str, max_clues: int = 32) -> dict:
    """Return bounded, source-ordered hints without inferring any DUT verdict.

    Pytest may group traceback and captured-output sections rather than emit
    event-time order. A saved stdout does not establish stderr chronology.
    Every excerpt therefore names its original line and preserves that limit.
    """
    import hashlib

    if not 1 <= max_clues <= 256:
        raise ValueError("max_clues must be within 1..256")
    clues = []
    matched = 0
    lines = stdout.splitlines()
    for number, line in enumerate(lines, 1):
        kinds = [kind for kind, pattern in _LOG_CLUES if pattern.search(line)]
        if not kinds:
            continue
        matched += 1
        if len(clues) < max_clues:
            clues.append({"clue_id": f"line-{number}", "candidate_types": kinds,
                          "source_ref": f"{source_file}:{number}", "source_line": number,
                          "text": line[:1600], "excerpt_truncated": len(line) > 1600})
    return {"schema": "bug_review.log_clues.v1", "invocation_id": invocation_id,
            "source_file": source_file, "source_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "streams_included": ["pytest_stdout"], "order_scope": "source_line_order",
            "temporal_order_verified": False,
            "ordering_gap": "Pytest output sections may be regrouped; separate stderr and cross-stream event order are unavailable",
            "purpose": "investigation_hints_only", "case_association": "not_inferred",
            "scanned_lines": len(lines), "matched_lines": matched,
            "truncated_count": matched - len(clues), "clues": clues}
