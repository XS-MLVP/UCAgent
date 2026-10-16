"""Validate dynamic-object ownership and bounded first-violation investigations."""

from __future__ import annotations

from .narrative import summary_issues
from .records import source_lines


def investigation_issues(index, cases, bugs, roots, source_root):
    """Check new investigations while retaining read compatibility with older runs."""
    if index.investigation_contract != "first_violation.v1":
        return []
    issues = []
    bindings = {item.evidence_id: (bug_id, item)
                for bug_id, bug in bugs.items() for item in bug.evidence_bindings}
    for root in roots.roots:
        base = "roots/" + root.root_id + "/investigation"
        investigation = root.investigation
        if investigation is None:
            issues.append({"field": base, "problem": "first_violation.v1 requires an investigation; see Guide_Doc/bug_review_investigation.md"})
            continue

        def add(field, problem):
            """Attach an actionable issue to the current ROOT investigation."""
            issues.append({"field": base + "/" + field, "problem": problem})

        def event_for(evidence_id, field):
            """Resolve actual root-local evidence without inheriting another ROOT's event."""
            owner = bindings.get(evidence_id)
            if not owner or owner[0] not in root.bug_ids or owner[1].role == "reported_only":
                add(field, f"{evidence_id} must reference this ROOT's actual member evidence")
                return None
            binding = owner[1]
            case = cases.get(binding.case_id)
            event = next((item for item in case.events if item.event_id == binding.event_id), None) if case else None
            if event is None:
                add(field, f"{evidence_id} has no actual execution event")
                return None
            return binding, event

        issues.extend(summary_issues(investigation.invariant, base + "/invariant", source_root))
        if not investigation.invariant.text.strip():
            add("invariant", "state a sourced constraint; missing requirements do not establish a ROOT invariant")
        if investigation.earliest_status == "earliest_observed" and not investigation.earlier_boundary_gap.strip():
            add("earlier_boundary_gap", "name the earlier boundary or identity evidence that was not observed")
        if investigation.earliest_status == "located" and investigation.earlier_boundary_gap.strip():
            add("earliest_status", "an unresolved earlier boundary requires earliest_observed")
        first = event_for(investigation.first_evidence_id, "first_evidence_id")
        if first and (first[0].role != "direct" or first[1].kind != "first_deviation"):
            add("first_evidence_id", "use direct first_deviation evidence, not a later assertion or normal reference")
        if investigation.detection_evidence_id:
            detected = event_for(investigation.detection_evidence_id, "detection_evidence_id")
            if detected and detected[1].kind not in {"assertion", "first_deviation"}:
                add("detection_evidence_id", "identify the detection event or leave it empty when unavailable")
            if first and detected and (first[0].case_id != detected[0].case_id
                                       or first[1].execution_id != detected[1].execution_id):
                add("detection_evidence_id", "detection must belong to the same case and invocation as the first deviation")

        object_ids = set()
        first_owners = 0
        for position, obj in enumerate(investigation.objects):
            field = f"objects/{position}"
            if obj.object_id in object_ids:
                add(field + "/object_id", "duplicate object_id within ROOT")
            object_ids.add(obj.object_id)
            issues.extend(summary_issues(obj.identity, base + "/" + field + "/identity", source_root))
            if len(set(obj.evidence_ids)) != len(obj.evidence_ids):
                add(field + "/evidence_ids", "duplicate evidence ID")
            first_owners += investigation.first_evidence_id in obj.evidence_ids
            for evidence_id in obj.evidence_ids:
                resolved = event_for(evidence_id, field + "/evidence_ids")
                if resolved and (resolved[0].case_id != obj.case_id or resolved[1].execution_id != obj.invocation_id):
                    add(field + "/evidence_ids", f"{evidence_id} belongs to a different case or invocation; separate dynamic objects")
        if first_owners != 1:
            add("objects", "the first deviation must belong to exactly one dynamic object trace")
        for position, alternative in enumerate(investigation.alternatives):
            field = f"alternatives/{position}"
            if alternative.status == "unresolved" and not alternative.remaining_gap.strip():
                add(field + "/remaining_gap", "state what would distinguish this unresolved explanation")
            if alternative.status == "ruled_out" and (alternative.basis == "unresolved" or alternative.remaining_gap.strip()):
                add(field + "/status", "an unresolved explanation cannot be marked ruled_out")
            if alternative.basis == "observed" and not alternative.evidence_ids:
                add(field + "/evidence_ids", "an observed refutation needs actual event evidence")
            if alternative.basis == "static_inference" and not alternative.source_refs:
                add(field + "/source_refs", "static reasoning needs source lines and must not claim waveform observation")
            for evidence_id in alternative.evidence_ids:
                event_for(evidence_id, field + "/evidence_ids")
            for reference in alternative.source_refs:
                try:
                    source_lines(source_root, reference, 1)
                except (ValueError, OSError) as error:
                    add(field + "/source_refs", str(error))
    return issues
