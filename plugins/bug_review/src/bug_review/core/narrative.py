"""Validate compact, sourced explanations without changing execution evidence."""

from __future__ import annotations

from pathlib import Path
import re

from .evidence import case_waveforms, signal_identity
from .records import REF_PATTERN, source_lines

RTL_SUFFIXES = {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"}


def summary_issues(summary, location, source_root, required=True):
    """Require a sourced explanation or a concrete unavailable reason."""
    issues = []
    if summary.text.strip():
        if not summary.source_refs:
            issues.append({"field": location + "/source_refs", "problem": "explanation needs source line references"})
        if summary.unavailable_reason.strip():
            issues.append({"field": location, "problem": "use sourced text or an unavailable reason, not both"})
    elif required and not summary.unavailable_reason.strip():
        issues.append({"field": location, "problem": "read the DUT/interface documentation and supply text with sources, or explain the unavailable input"})
    elif summary.source_refs:
        issues.append({"field": location, "problem": "source references need an explanation"})
    for reference in summary.source_refs:
        try:
            source_lines(source_root, reference, 1)
        except (ValueError, OSError) as error:
            issues.append({"field": location + "/source_refs", "problem": str(error)})
    return issues


def narrative_issues(index, cases, bugs, roots, source_root):
    """Check explanation provenance, real RTL names and root-local causal evidence."""
    issues = summary_issues(index.dut_context, "dut_context", source_root)
    bindings = {binding.evidence_id: (bug_id, binding)
                for bug_id, bug in bugs.items() for binding in bug.evidence_bindings}
    for root in roots.roots:
        base = "roots/" + root.root_id
        issues.extend(summary_issues(root.affected_behavior, base + "/affected_behavior", source_root))
        if not root.causal_steps:
            issues.append({"field": base + "/causal_steps", "problem": "explain the sourced RTL propagation in bounded steps"})
        for position, step in enumerate(root.causal_steps):
            location = base + f"/causal_steps/{position}"
            for reference in step.rtl_refs:
                try:
                    source_lines(source_root, reference, 1)
                    match = REF_PATTERN.fullmatch(reference)
                    if Path(match.group(1)).suffix.lower() not in RTL_SUFFIXES:
                        raise ValueError("causal step requires RTL lines, not a test or project requirement")
                except (ValueError, OSError) as error:
                    issues.append({"field": location + "/rtl_refs", "problem": str(error)})
            if len(set(step.evidence_ids)) != len(step.evidence_ids):
                issues.append({"field": location + "/evidence_ids", "problem": "duplicate evidence ID"})
            for evidence_id in step.evidence_ids:
                owner = bindings.get(evidence_id)
                binding = owner[1] if owner else None
                case = cases.get(binding.case_id) if binding else None
                if (not owner or owner[0] not in root.bug_ids or not case
                        or binding.role == "reported_only"
                        or not any(e.event_id == binding.event_id for e in case.events)):
                    issues.append({"field": location + "/evidence_ids", "problem": f"{evidence_id} must name an actual event of this root's member"})
    for bug_id, bug in bugs.items():
        if bug.decision.verdict != "confirmed":
            continue
        location = "bugs/" + bug_id + "/phenomenon/signal_explanations"
        if not bug.phenomenon.signal_explanations:
            issues.append({"field": location, "problem": "explain at least the relevant RTL input or output; keep API aliases separate"})
        signed_names = {signal_identity(name) for case_id in bug.case_ids if case_id in cases
                        for wave in case_waveforms(cases[case_id])
                        for group in wave.signal_groups.values() if isinstance(group, list)
                        for name in group if isinstance(name, str)}
        for position, explanation in enumerate(bug.phenomenon.signal_explanations):
            field = location + f"/{position}"
            short_name = signal_identity(explanation.rtl_name).rsplit(".", 1)[-1]
            rtl_text = []
            for reference in explanation.source_refs:
                try:
                    excerpt = source_lines(source_root, reference, 1000)
                    match = REF_PATTERN.fullmatch(reference)
                    if Path(match.group(1)).suffix.lower() in RTL_SUFFIXES:
                        rtl_text.append(excerpt["text"])
                except (ValueError, OSError) as error:
                    issues.append({"field": field + "/source_refs", "problem": str(error)})
            if not any(re.search(r"(?<![\w$])" + re.escape(short_name) + r"(?![\w$])", text) for text in rtl_text):
                issues.append({"field": field + "/rtl_name", "problem": "the exact RTL identifier must occur in its cited RTL lines"})
            if explanation.signal_path:
                path = signal_identity(explanation.signal_path)
                if path not in signed_names or path.rsplit(".", 1)[-1] != short_name:
                    issues.append({"field": field + "/signal_path", "problem": "waveform path must match the RTL name and this phenomenon's signed signals"})
    return issues
