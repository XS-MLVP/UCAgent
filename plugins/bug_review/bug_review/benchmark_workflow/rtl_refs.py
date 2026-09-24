"""Rtl refs for the Bug Review workflow."""
import os
import re
from collections import defaultdict
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .models import RtlRegion
from .utils import sha256_file
from .rtl_dependency import (
    build_assignment_dependency_index,
    build_region_bounds,
    expand_dependency_bounds,
    extract_dependency_signals,
    find_dependency_cone_regions,
)


RTL_EXTS = {".v", ".sv", ".vh", ".vhd", ".vhdl"}
_DRIVER_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]+\])?\s*(?:<=|=)"
)


@lru_cache(maxsize=64)
def _cached_rtl_analysis(
    path: str,
    size: int,
    mtime_ns: int,
) -> Tuple[Tuple[str, ...], Dict[str, List[Tuple[int, List[str]]]], Dict[str, List[int]], str]:
    """Read and index an immutable RTL snapshot once per process."""
    del size, mtime_ns  # These values form the cache invalidation key.
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = tuple(handle.readlines())
    assignment_index = build_assignment_dependency_index(lines)
    driver_index: Dict[str, List[int]] = defaultdict(list)
    for line_index, line in enumerate(lines):
        for match in _DRIVER_RE.finditer(line):
            driver_index[match.group(1)].append(line_index)
    return lines, assignment_index, dict(driver_index), sha256_file(path)


def _rtl_analysis(path: str):
    stat = os.stat(path)
    return _cached_rtl_analysis(os.path.abspath(path), stat.st_size, stat.st_mtime_ns)


def is_rtl_file(filename: str) -> bool:
    basename = os.path.basename(filename)
    _, ext = os.path.splitext(basename)
    ext = ext.lower()
    if ext in RTL_EXTS:
        return True
    if "test" in filename.lower():
        return False
    return False


def normalize_filename(filename: str) -> str:
    return os.path.basename(filename).strip("[]():\"'` ")


def parse_line_range(text: str) -> Set[int]:
    results: Set[int] = set()
    normalised = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("～", "-")
        .replace("、", ",")
        .replace("，", ",")
        .replace("第", "")
        .replace("行", "")
    )
    for part in normalised.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except ValueError:
                continue
            if start <= end:
                results.update(range(start, end + 1))
            continue
        try:
            results.add(int(token))
        except ValueError:
            continue
    return results


def _find_file_in_context(text: str) -> str:
    matches = re.findall(r"([A-Za-z0-9_./-]+\.(?:sv|v|vh|vhd|vhdl))", text)
    return matches[-1] if matches else ""


def extract_rtl_lines_from_text(text: str) -> Tuple[Set[Tuple[str, int]], Dict[Tuple[str, int], List[str]]]:
    results: Set[Tuple[str, int]] = set()
    contexts: Dict[Tuple[str, int], List[str]] = defaultdict(list)

    def add_match(filename: str, line_text: str, source_text: str) -> None:
        if not is_rtl_file(filename):
            return
        normalized = normalize_filename(filename)
        for line_number in parse_line_range(line_text):
            key = (normalized, line_number)
            results.add(key)
            if source_text not in contexts[key]:
                contexts[key].append(source_text)

    for match in re.finditer(r"<FILE-([^>]+)>", text):
        full = match.group(1)
        if ":" not in full:
            continue
        filename, line_text = full.split(":", 1)
        add_match(filename, line_text, match.group(0))

    for match in re.finditer(
        r"`?([^\s`]+?\.\w{1,5})`?\s+第\s*([\d,、，\-~～–—]+)\s*行",
        text,
    ):
        add_match(match.group(1), match.group(2), match.group(0))

    for match in re.finditer(
        r"`?([^\s`]+?\.\w{1,5})`?\s*[:：]\s*([\d,、，\-~～–—]+)",
        text,
    ):
        add_match(match.group(1), match.group(2), match.group(0))

    for match in re.finditer(
        r"`?([^\s`]+?\.\w{1,5})`?\s+lines?\s+([\d,、，\-~～–—]+)",
        text,
        re.IGNORECASE,
    ):
        add_match(match.group(1), match.group(2), match.group(0))

    for match in re.finditer(r"\(lines?\s+([\d,、，\-~～–—]+)\)", text, re.IGNORECASE):
        filename = _find_file_in_context(text[max(0, match.start() - 200):match.start()])
        if filename:
            add_match(filename, match.group(1), f"{filename} {match.group(0)}")

    return results, contexts


def group_line_refs(line_refs: Iterable[Tuple[str, int]], reason: str, evidence: str) -> List[RtlRegion]:
    grouped: Dict[str, List[int]] = defaultdict(list)
    for filename, line_number in sorted(line_refs):
        grouped[filename].append(line_number)

    regions: List[RtlRegion] = []
    for filename, line_numbers in grouped.items():
        if not line_numbers:
            continue
        start = prev = line_numbers[0]
        for current in line_numbers[1:]:
            if current == prev + 1:
                prev = current
                continue
            regions.append(RtlRegion(filename, start, prev, reason, evidence))
            start = prev = current
        regions.append(RtlRegion(filename, start, prev, reason, evidence))
    return regions


def discover_rtl_files(root: str) -> List[str]:
    paths = []
    for dirpath, _, filenames in os.walk(root):
        lowered = dirpath.lower()
        if "uc_test_report" in lowered or "unity_test" in lowered or "guide_doc" in lowered:
            continue
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if is_rtl_file(full_path):
                paths.append(full_path)
    return sorted(paths)


def _resolve_rtl_path(rtl_root: str, declared_path: str) -> str:
    """Resolve a declared RTL path without allowing it outside rtl_root."""
    root = os.path.abspath(rtl_root)
    declared = str(declared_path or "").replace("\\", "/")
    candidate = declared if os.path.isabs(declared) else os.path.join(root, declared)
    candidate = os.path.abspath(candidate)
    try:
        if os.path.commonpath([root, candidate]) == root and os.path.isfile(candidate):
            return candidate
    except ValueError:
        pass
    matches = [path for path in discover_rtl_files(root) if path.endswith("/" + declared.lstrip("./"))]
    if not matches:
        matches = [path for path in discover_rtl_files(root) if os.path.basename(path) == os.path.basename(declared)]
    return matches[0] if len(matches) == 1 else ""


def validate_rtl_region(rtl_root: str, region: RtlRegion) -> RtlRegion:
    """Attach Qwen-style source validation metadata while preserving the region."""
    path = _resolve_rtl_path(rtl_root, region.path) if rtl_root else ""
    if not path:
        region.validation_status = "INVALID_RTL_PATH"
        return region
    try:
        cached_lines, _, _, digest = _rtl_analysis(path)
        lines = [line.rstrip("\r\n") for line in cached_lines]
        if region.line_start < 1 or region.line_end < region.line_start or region.line_end > len(lines):
            region.validation_status = "INVALID_LINE_RANGE"
            return region
        region.excerpt = "\n".join(lines[region.line_start - 1:region.line_end])
        region.sha256 = digest
        if region.evidence_source == "declared_dynamic":
            region.validation_status = "VALIDATED_DYNAMIC_LOCATION"
        elif region.evidence_source == "static_link":
            region.validation_status = "VALIDATED_STATIC_LINK_LOCATION"
        elif region.evidence_source == "lexical_retrieval":
            region.validation_status = "PLAUSIBLE_RETRIEVED_LOCATION"
        else:
            region.validation_status = "VALIDATED_DERIVED_LOCATION"
    except OSError:
        region.validation_status = "RTL_SOURCE_UNREADABLE"
    return region


def infer_driver_signal_names_from_regions(regions: Sequence[RtlRegion]) -> List[str]:
    """Recover assignment targets from already validated report locations."""
    signals: List[str] = []
    for region in regions:
        if region.validation_status not in {
            "VALIDATED_DYNAMIC_LOCATION",
            "VALIDATED_STATIC_LINK_LOCATION",
            "VALIDATED_DERIVED_LOCATION",
        }:
            continue
        for line in region.excerpt.splitlines():
            match = re.search(
                r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]+\])?\s*(?:<=|=)",
                line.split("//", 1)[0],
            )
            if match and match.group(1).lower() not in {"if", "else", "assign", "always"}:
                signals.append(match.group(1))
    return list(dict.fromkeys(signals))


def find_driver_regions(
    rtl_root: str,
    signal_names: Sequence[str],
    *,
    max_dependency_depth: int = 8,
) -> List[RtlRegion]:
    if not rtl_root or not os.path.isdir(rtl_root):
        return []

    regions: List[RtlRegion] = []
    for rtl_path in discover_rtl_files(rtl_root):
        lines, assignment_index, driver_index, _ = _rtl_analysis(rtl_path)
        for signal_name in signal_names:
            for index in driver_index.get(signal_name, []):
                line_start, line_end = build_region_bounds(lines, index)
                dep_start, dep_end = expand_dependency_bounds(lines, index, line_start, line_end)
                dependency_signals = extract_dependency_signals(lines, signal_name, dep_start, dep_end)
                direct_sources = assignment_index.get(signal_name.lower(), [])
                cone_signals = dependency_signals[:3]
                if direct_sources:
                    direct = [source for _, sources in direct_sources for source in sources]
                    dependency_signals = list(dict.fromkeys(direct + dependency_signals))
                    cone_signals = direct
                reason = f"heuristic dependency cone for {signal_name}"
                if dependency_signals:
                    reason += f" via {', '.join(dependency_signals)}"
                regions.append(
                    RtlRegion(
                        path=rtl_path,
                        line_start=dep_start,
                        line_end=dep_end,
                        reason=reason,
                        evidence="rtl_signal_scan+local_block_expand",
                        evidence_source="derived_dependency_cone",
                        dependency_depth=0,
                    )
                )
                regions.extend(
                    find_dependency_cone_regions(
                        rtl_path,
                        lines,
                        signal_name,
                        cone_signals,
                        max_depth=max_dependency_depth,
                        assignment_index=assignment_index,
                    )
                )
    deduped = {}
    for region in regions:
        key = (region.path, region.line_start, region.line_end, region.reason)
        deduped[key] = region
    return sorted(deduped.values(), key=lambda item: (item.path, item.line_start, item.line_end))


def validated_rtl_identifiers_from_text(
    rtl_root: str,
    text: str,
    *,
    limit: int = 64,
) -> List[str]:
    """Extract unquoted Verilog-like names and retain only real RTL symbols."""
    if not rtl_root or not os.path.isdir(rtl_root) or not text:
        return []
    candidates = list(dict.fromkeys(re.findall(r"\b[A-Za-z_][A-Za-z0-9_$]{2,}\b", text)))
    ignored = {
        "and", "or", "not", "when", "while", "should", "must", "true", "false",
        "wire", "reg", "logic", "input", "output", "assign", "always", "begin", "end",
    }
    candidates = [item for item in candidates if item.lower() not in ignored]
    if not candidates:
        return []
    found = set()
    rtl_symbols = set()
    patterns = {
        item: re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(item)}(?![A-Za-z0-9_$])")
        for item in candidates
    }
    for rtl_path in discover_rtl_files(rtl_root):
        with open(rtl_path, "r", encoding="utf-8", errors="ignore") as handle:
            source = handle.read()
        rtl_symbols.update(re.findall(r"\b[A-Za-z_][A-Za-z0-9_$]{2,}\b", source))
        for item, pattern in patterns.items():
            if item not in found and pattern.search(source):
                found.add(item)
    validated: List[str] = []
    for item in candidates:
        if item in found:
            validated.append(item)
            continue
        # Channel aliases such as ``ifuerr`` are useful only after expansion
        # to concrete symbols that really exist in this RTL snapshot.
        if len(item) < 6:
            continue
        expanded = sorted(
            symbol for symbol in rtl_symbols
            if item.lower() in symbol.lower() and "_" in symbol
        )[:8]
        validated.extend(expanded)
    return list(dict.fromkeys(validated))[:limit]


def retrieve_rtl_windows(
    rtl_root: str,
    signal_names: Sequence[str],
    *,
    limit: int = 3,
    context_lines: int = 3,
) -> List[RtlRegion]:
    """Return weak, explicitly non-causal lexical RTL candidates.

    This mirrors Qwen36's retrieval fallback.  Callers must never promote
    these regions to a precise root-cause location without stronger evidence.
    """
    if not rtl_root or not os.path.isdir(rtl_root) or not signal_names:
        return []
    hits = []
    for rtl_path in discover_rtl_files(rtl_root):
        with open(rtl_path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
        for index, line in enumerate(lines):
            score = sum(
                1
                for signal in signal_names
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(signal)}(?![A-Za-z0-9_])", line)
            )
            if score:
                hits.append((-score, rtl_path, index, len(lines)))
    regions = []
    for _, rtl_path, index, line_count in sorted(hits)[:limit]:
        regions.append(
            RtlRegion(
                path=rtl_path,
                line_start=max(1, index + 1 - context_lines),
                line_end=min(line_count, index + 1 + context_lines),
                reason="plausible lexical RTL retrieval",
                evidence="rtl_lexical_retrieval",
                evidence_source="lexical_retrieval",
            )
        )
    return regions
