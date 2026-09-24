"""Rtl dependency for the Bug Review workflow."""
import re
from collections import defaultdict
from typing import DefaultDict, Dict, List, Sequence, Set, Tuple

from .models import RtlRegion


VERILOG_CONTROL_KEYWORDS = {
    "always",
    "always_ff",
    "always_comb",
    "always_latch",
    "assign",
    "begin",
    "case",
    "casex",
    "casez",
    "default",
    "else",
    "end",
    "endcase",
    "endfunction",
    "endgenerate",
    "endmodule",
    "endtask",
    "for",
    "function",
    "if",
    "input",
    "logic",
    "module",
    "output",
    "parameter",
    "posedge",
    "negedge",
    "or",
    "reg",
    "signed",
    "typedef",
    "unique",
    "wire",
}

ASSIGNMENT_KEYWORDS = VERILOG_CONTROL_KEYWORDS | {
    "posedge",
    "negedge",
}


def build_region_bounds(lines: Sequence[str], line_index: int) -> Tuple[int, int]:
    start = line_index
    end = line_index
    while start > 0 and line_index - start < 12:
        previous = lines[start - 1].strip()
        if previous.startswith("always") or previous.startswith("assign") or previous.startswith("module"):
            start -= 1
            break
        if previous == "":
            break
        start -= 1
    while end < len(lines) - 1 and end - line_index < 12:
        current = lines[end].strip()
        if current.startswith("end") and end > line_index:
            break
        if end > line_index and current == "":
            break
        end += 1
    return start + 1, end + 1


def expand_dependency_bounds(
    lines: Sequence[str],
    line_index: int,
    base_start: int,
    base_end: int,
) -> Tuple[int, int]:
    start = max(0, base_start - 1)
    end = min(len(lines) - 1, base_end - 1)

    control_prefixes = (
        "if ",
        "if(",
        "else if",
        "case",
        "unique case",
        "priority case",
        "when ",
        "else",
        "begin",
        "always",
        "assign",
        "module",
    )

    for index in range(base_start - 2, max(-1, base_start - 17), -1):
        if index < 0:
            break
        current = lines[index].strip().lower()
        if not current:
            break
        if current.startswith(control_prefixes):
            start = index
            continue
        if any(token in current for token in ("<=", "=", "==", "?:")):
            start = index
            continue
        if index < line_index - 12:
            break

    for index in range(base_end, min(len(lines), base_end + 15)):
        current = lines[index].strip().lower()
        if not current:
            break
        if current.startswith(("else", "end", "begin", "case", "when", "if ")):
            end = index + 1
            continue
        if any(token in current for token in ("<=", "=", "==", "?:")):
            end = index + 1
            continue

    return start + 1, end + 1


def extract_dependency_signals(lines: Sequence[str], target_signal: str, start: int, end: int) -> List[str]:
    signals = []
    target = target_signal.lower()
    for index in range(max(0, start - 1), min(len(lines), end)):
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", lines[index]):
            lowered = token.lower()
            if lowered == target or lowered in VERILOG_CONTROL_KEYWORDS:
                continue
            if lowered not in signals:
                signals.append(lowered)
    return signals[:6]


def _normalise_signal_token(token: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", token or "").strip().lower()


def _extract_assignment_sources(expression: str) -> List[str]:
    signals = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", expression or ""):
        lowered = token.lower()
        if lowered in ASSIGNMENT_KEYWORDS:
            continue
        if lowered not in signals:
            signals.append(lowered)
    return signals


def build_assignment_dependency_index(lines: Sequence[str]) -> Dict[str, List[Tuple[int, List[str]]]]:
    index: DefaultDict[str, List[Tuple[int, List[str]]]] = defaultdict(list)
    for line_index, raw_line in enumerate(lines):
        line = raw_line.split("//", 1)[0].strip()
        if not line or line.startswith("if ") or line.startswith("if(") or line.startswith("else") or line.startswith("case"):
            continue
        # Keep assignments written on an always/assign header discoverable;
        # the procedural wrapper is not part of the assignment target.
        line = re.sub(r"^(?:always(?:_ff|_comb|_latch)?(?:\s*@[^ ]+)?|assign)\s+", "", line)
        match = re.match(
            r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]+\])?\s*(<=|=)\s*(.+?);?$",
            line,
        )
        if not match:
            continue
        target = _normalise_signal_token(match.group(1))
        if not target or target in ASSIGNMENT_KEYWORDS:
            continue
        rhs = match.group(3)
        if "==" in rhs or "!=" in rhs or ">=" in rhs or "<=" in rhs:
            # skip comparisons masquerading as assignments
            pass
        sources = _extract_assignment_sources(rhs)
        sources = [source for source in sources if source != target]
        if sources:
            index[target].append((line_index, sources))
    return dict(index)


def find_one_hop_upstream_regions(
    rtl_path: str,
    lines: Sequence[str],
    target_signal: str,
    dependency_signals: Sequence[str],
) -> List[RtlRegion]:
    regions: List[RtlRegion] = []
    seen = set()
    for dependency_signal in dependency_signals[:3]:
        if dependency_signal == target_signal.lower():
            continue
        for index, line in enumerate(lines):
            if not re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(dependency_signal)}(?:\[[^\]]+\])?\s*(?:<=|=)",
                line,
            ):
                continue
            base_start, base_end = build_region_bounds(lines, index)
            dep_start, dep_end = expand_dependency_bounds(lines, index, base_start, base_end)
            key = (rtl_path, dep_start, dep_end, dependency_signal)
            if key in seen:
                continue
            seen.add(key)
            regions.append(
                RtlRegion(
                    path=rtl_path,
                    line_start=dep_start,
                    line_end=dep_end,
                    reason=f"one-hop upstream dependency for {target_signal} via {dependency_signal}",
                    evidence="rtl_signal_scan+local_block_expand+one_hop_upstream",
                )
            )
            break
    return regions


def find_dependency_cone_regions(
    rtl_path: str,
    lines: Sequence[str],
    target_signal: str,
    dependency_signals: Sequence[str],
    max_depth: int = 8,
    assignment_index: Dict[str, List[Tuple[int, List[str]]]] | None = None,
) -> List[RtlRegion]:
    if max_depth < 1:
        return []

    regions: List[RtlRegion] = []
    if assignment_index is None:
        assignment_index = build_assignment_dependency_index(lines)
    visited: Set[str] = {target_signal.lower()}
    frontier: List[Tuple[str, int]] = [(dependency_signal, 1) for dependency_signal in dependency_signals[:3]]

    while frontier:
        current_signal, depth = frontier.pop(0)
        lowered_current = current_signal.lower()
        if depth > max_depth or lowered_current in visited:
            continue
        visited.add(lowered_current)
        assignment_sites = assignment_index.get(lowered_current, [])
        for line_index, sources in assignment_sites:
            base_start, base_end = build_region_bounds(lines, line_index)
            dep_start, dep_end = expand_dependency_bounds(lines, line_index, base_start, base_end)
            regions.append(
                RtlRegion(
                    path=rtl_path,
                    line_start=dep_start,
                    line_end=dep_end,
                    reason=f"{'one-hop' if depth == 1 else f'rt{depth}'} upstream dependency for {target_signal} via {lowered_current}",
                    evidence="rtl_signal_scan+local_block_expand+dependency_graph",
                    evidence_source="derived_dependency_cone",
                    dependency_depth=depth,
                )
            )
            if depth < max_depth:
                for next_signal in sources[:3]:
                    if next_signal not in visited:
                        frontier.append((next_signal, depth + 1))

    deduped = {}
    for region in regions:
        key = (region.path, region.line_start, region.line_end, region.reason)
        deduped[key] = region
    return sorted(deduped.values(), key=lambda item: (item.path, item.line_start, item.line_end))
