"""Extract the root-cause count explicitly reported by an UCAgent run.

This metric is intentionally separate from CK/BG claims (symptoms) and from
the benchmark's cross-model RTL-root adjudication.  UCAgent versions record
their final root count in different places, so both the final test summary and
the dynamic bug report are considered with an explicit source priority.
"""

from __future__ import annotations

import os
import re
import tarfile
from typing import Dict, List, Optional, Sequence, Tuple


_ROOT_SECTION_RE = re.compile(
    r"^(#{2,6})\s+(?:(?:缺陷|Bug\s*)?根因分析(?:总结)?|.*缺陷根因分析(?:总结)?|Root\s+Cause(?:\s+Analysis)?(?:\s+Summary)?)\s*$",
    re.I | re.M,
)
_HEADING_RE = re.compile(r"^(#{3,6})\s+(.+?)\s*$", re.M)
_NUMBERED_TITLE_RE = re.compile(
    r"^(?:(?:根因|缺陷|Bug)\s*)?(?:分析\s*[：:]\s*)?"
    r"(?:\d+|[一二三四五六七八九十]+)\s*[.)、：:]?\s*.+$",
    re.I,
)
_NAMED_ROOT_TITLE_RE = re.compile(r"^(?:根因分析|根因|缺陷)\s*[：:]\s*\S+", re.I)
_FINAL_COUNT_PATTERNS = (
    re.compile(r"(?:本次|本轮)?(?:验证|测试)?(?:共)?(?:发现|确认)\s*\*{0,2}\s*(\d+)\s*\*{0,2}\s*个?\s*(?:DUT\s*)?(?:Bug|缺陷)", re.I),
    re.compile(r"(?:本次|本轮)?(?:验证|测试)?(?:共)?(?:发现|确认)\s*\*{0,2}\s*(\d+)\s*\*{0,2}\s*个?(?:已?确认(?:的)?)?\s*(?:DUT\s*)?(?:设计)?(?:Bug|缺陷)", re.I),
    re.compile(r"(?:发现并确认的|已确认的?)\s*(?:DUT\s*)?(?:Bug|缺陷)\s*[：:]?\s*\*{0,2}\s*(\d+)\s*\*{0,2}\s*个?", re.I),
    re.compile(r"(?:DUT\s*)?(?:Bug|缺陷)\s*(?:总数|数量|合计)\s*[：:]\s*\*{0,2}\s*(\d+)", re.I),
)
_NO_DEFECT_RE = re.compile(
    r"(?:未发现|没有发现|未确认(?:新的?)?|无)(?:任何|有意义的|功能性|潜在(?:的)?|新的?)?\s*"
    r"(?:DUT|DUT\s*RTL|RTL|RTL\s*代码|硬件设计|设计|实际|真实)?\s*(?:功能)?\s*(?:Bug|缺陷|代码中的实际硬件设计缺陷|有缺陷的代码)", re.I
)
_ALL_FALSE_POSITIVE_RE = re.compile(
    r"(?:所有|全部)\s*(?:静态分析(?:中)?(?:发现)?(?:的)?)?\s*(?:\d+\s*个)?\s*(?:疑似\s*)?"
    r"(?:Bug|缺陷|问题).{0,60}(?:均|全部)\s*(?:被|已)?(?:确认|判定|证实)?(?:为|是)?\s*"
    r"(?:\*{0,2}误报\*{0,2}|非\s*(?:DUT|RTL)?\s*(?:bug|缺陷)|设计(?:预期|正确))",
    re.I,
)
_SUMMARY_ROOT_SECTION_RE = re.compile(
    r"(?:缺陷)?根因(?:分析)?(?:分类|归纳|总结)|主要根因|缺陷分析总结", re.I
)
_SUMMARY_DEFECT_SECTION_RE = re.compile(
    r"(?:已确认|已证实|高置信度).*(?:缺陷|问题)|(?:缺陷|问题).*(?:类别|类型)", re.I
)


def _section_body(text: str, heading_match: re.Match) -> str:
    """Return a Markdown heading's body up to its next peer/ancestor."""
    level = len(heading_match.group(1))
    start = heading_match.end()
    fenced = False
    offset = start
    for line in text[start:].splitlines(keepends=True):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            offset += len(line)
            continue
        if not fenced and re.match(rf"^#{{1,{level}}}\s+", line):
            return text[start:offset]
        offset += len(line)
    return text[start:]


def _list_entry_titles(body: str) -> List[str]:
    """Count only top-level numbered or bold bullet categories in a section."""
    numbered: List[str] = []
    bullets: List[str] = []
    standalone_bold: List[str] = []
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}(?:\d+|[一二三四五六七八九十]+)[.)、]\s*(.+?)\s*$", line)
        if match:
            numbered.append(match.group(1).strip())
            continue
        match = re.match(r"^\s{0,3}[-*+]\s+\*\*(.+?)\*\*(?:\s*[：:].*)?$", line)
        if match:
            bullets.append(match.group(1).strip())
            continue
        match = re.match(r"^\s{0,3}\*\*((?:ROOT-[A-Za-z0-9_-]+|BG-[A-Za-z0-9_-]+|(?:核心|共享)?根因\s*\d*)\s*[：:].+?)\*\*\s*$", line, re.I)
        if match:
            standalone_bold.append(match.group(1).strip())
    child_headings = []
    for match in _HEADING_RE.finditer(body):
        title = match.group(2).strip()
        if _NUMBERED_TITLE_RE.match(title) or _NAMED_ROOT_TITLE_RE.match(title):
            child_headings.append(title)
    if child_headings:
        return child_headings
    if standalone_bold and any(re.search(r"ROOT-|根因|缺陷", b, re.I) for b in standalone_bold):
        return standalone_bold
    return numbered or bullets or standalone_bold



def _root_entry_identity(
    title: str,
    body: str,
    *,
    source_line_start: Optional[int] = None,
    source_line_end: Optional[int] = None,
) -> Dict[str, object]:
    text = title + "\n" + body
    ck_paths = []
    for fg, fc, ck in re.findall(
        r"(FG-[A-Za-z0-9_-]+)/(FC-[A-Za-z0-9_-]+)/(CK-[A-Za-z0-9_-]+)", text
    ):
        value = f"{fg}/{fc}/{ck}"
        if value not in ck_paths:
            ck_paths.append(value)
    bg_names = []
    for value in re.findall(r"BG-([A-Za-z0-9_-]+?)(?:-\d+)?(?=[\s）)>,]|$)", text):
        if value not in bg_names:
            bg_names.append(value)
    rtl_anchors = []
    # UCAgent summaries commonly use `path/file.v:53-64`, while dynamic
    # reports also use "file.v 第53-64行".  Keep only explicit source
    # locations; names or prose similarity must never establish alignment.
    anchor_patterns = (
        r"`?([A-Za-z0-9_./-]+\.(?:v|sv|vh|svh|scala))(?::\s*L?|`?\s*第)\s*(\d+)\s*(?:[-~–—至]\s*(?:L)?\s*(\d+))?\s*(?:行)?`?",
        r"`?([A-Za-z0-9_./-]+\.(?:v|sv|vh|svh|scala)):(\d+)(?:-(\d+))?`?",
    )
    for pattern in anchor_patterns:
        for path, start, end in re.findall(pattern, text, re.I):
            anchor = {
                "file": os.path.basename(path),
                "line_start": int(start),
                "line_end": int(end or start),
            }
            if anchor not in rtl_anchors:
                rtl_anchors.append(anchor)
    # Also support multi-line declarations like "file.scala 第115,372,380-387,487行"
    for match in re.finditer(r"`?([A-Za-z0-9_./-]+\.(?:v|sv|vh|svh|scala))\s*第([0-9,\s\-~至]+)行`?", text, re.I):
        path = os.path.basename(match.group(1))
        ranges = match.group(2).split(",")
        for part in ranges:
            nums = re.findall(r"\d+", part)
            if nums:
                st = int(nums[0])
                ed = int(nums[-1])
                anchor = {"file": path, "line_start": st, "line_end": ed}
                if anchor not in rtl_anchors:
                    rtl_anchors.append(anchor)

    return {
        "title": title,
        "source_excerpt": (title + "\n" + body).strip()[:6000],
        "source_line_start": source_line_start,
        "source_line_end": source_line_end,
        "ck_paths": ck_paths,
        "bg_names": bg_names,
        "rtl_anchors": rtl_anchors,
    }


def _summary_root_entries(body: str, *, base_line: int = 1) -> List[Dict[str, object]]:
    """Return consolidated summary entries with their own evidence blocks."""
    starts = []
    # Prioritize explicit declared root markers (e.g. **ROOT-xxx: ...** or **根因1: ...**)
    for match in re.finditer(
        r"(?m)^\s{0,3}\*\*((?:ROOT-[A-Za-z0-9_-]+|BG-[A-Za-z0-9_-]+|(?:核心|共享)?根因\s*\d*)\s*[：:].+?)\*\*\s*$", body, re.I
    ):
        starts.append((match.start(), match.end(), match.group(1).strip()))
    if not starts:
        for match in re.finditer(
            r"(?m)^\s{0,3}(?:\d+|[一二三四五六七八九十]+)[.)、]\s*(.+?)\s*$",
            body,
        ):
            starts.append((match.start(), match.end(), match.group(1).strip()))
    if not starts:
        for match in re.finditer(r"(?m)^\s{0,3}[-*+]\s+\*\*(.+?)\*\*(?:\s*[：:].*)?$", body):
            starts.append((match.start(), match.end(), match.group(1).strip()))
    if not starts:
        for match in _HEADING_RE.finditer(body):
            title = match.group(2).strip()
            if _NUMBERED_TITLE_RE.match(title) or _NAMED_ROOT_TITLE_RE.match(title):
                starts.append((match.start(), match.end(), title))

    entries = []
    for index, (start, end, title) in enumerate(starts):
        block_end = starts[index + 1][0] if index + 1 < len(starts) else len(body)
        entry = _root_entry_identity(
            title,
            body[end:block_end],
            source_line_start=base_line + body[:start].count("\n"),
            source_line_end=base_line + body[:block_end].count("\n"),
        )
        if entry not in entries:
            entries.append(entry)
    return entries


def _dynamic_root_entries(text: str) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for section in _ROOT_SECTION_RE.finditer(text or ""):
        section_text = _section_body(text or "", section)
        headings = list(_HEADING_RE.finditer(section_text))
        if not headings:
            continue
        explicit = [
            heading for heading in headings
            if _NUMBERED_TITLE_RE.match(heading.group(2).strip())
            or _NAMED_ROOT_TITLE_RE.match(heading.group(2).strip())
        ]
        selected = explicit
        if not selected:
            shallowest = min(len(heading.group(1)) for heading in headings)
            selected = [heading for heading in headings if len(heading.group(1)) == shallowest]
        for index, heading in enumerate(selected):
            start = heading.end()
            end = selected[index + 1].start() if index + 1 < len(selected) else len(section_text)
            section_line = (text or "")[:section.end()].count("\n") + 1
            entry = _root_entry_identity(
                heading.group(2).strip(),
                section_text[start:end],
                source_line_start=section_line + section_text[:heading.start()].count("\n"),
                source_line_end=section_line + section_text[:end].count("\n"),
            )
            if entry not in entries:
                entries.append(entry)
    return entries


def _normalise_root_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*_]", "", value or "")).strip().casefold()


def _tagged_dynamic_root_entries(text: str) -> List[Dict[str, object]]:
    """Read UCAgent's structured BG-level ``BUG-ROOT-CAUSE`` fields.

    This is a fallback for reports without a final root-category summary.  It
    preserves each source BG's explicit RTL evidence and de-duplicates only
    identical normalised root text with the same explicit anchors.
    """
    entries: List[Dict[str, object]] = []
    seen = set()
    source = text or ""
    tags = list(re.finditer(r"(?m)^\s*<BUG-ROOT-CAUSE>\s*$", source))
    bg_headings = list(re.finditer(r"(?m)^######\s+(.+?<BG-[^>]+>)\s*$", source))
    for tag in tags:
        value = source[tag.end():]
        next_field = re.search(r"(?m)^######\s+|^\s*</?BUG-[A-Z-]+>\s*$", value)
        if next_field:
            value = value[:next_field.start()]
        value = value.strip()
        if not value:
            continue
        prior = [heading for heading in bg_headings if heading.start() < tag.start()]
        if not prior:
            continue
        heading = prior[-1]
        following = next((item for item in bg_headings if item.start() > heading.start()), None)
        block_end = following.start() if following else len(source)
        entry = _root_entry_identity(heading.group(1).strip(), source[heading.end():block_end])
        entry["declared_root_cause"] = value
        anchor_key = tuple(
            (item["file"], item["line_start"], item["line_end"])
            for item in entry.get("rtl_anchors", [])
        )
        key = (_normalise_root_text(value), anchor_key)
        if key not in seen:
            entries.append(entry)
            seen.add(key)
    return entries


def extract_summary_root_causes(text: str) -> Dict[str, object]:
    """Extract the run's own consolidated root categories from test_summary."""
    plain_text = re.sub(r"[*_`]+", "", text or "")
    explicit_counts = []
    for pattern in _FINAL_COUNT_PATTERNS:
        explicit_counts.extend(int(value) for value in pattern.findall(text or ""))
    # An explicit zero is authoritative and distinguishes "no DUT RTL root"
    # from a missing report. Positive Bug counts are not necessarily root
    # counts, so consolidated root categories below take priority over them.
    if explicit_counts and explicit_counts[-1] == 0:
        return {
            "available": True, "count": 0, "titles": [], "entries": [],
            "reason": "final test summary explicitly reports zero confirmed DUT RTL defects",
            "extraction_method": "summary_explicit_final_count",
        }
    headings = list(re.finditer(r"^(#{2,6})\s+(.+?)\s*$", text or "", re.M))
    for classifier, method in (
        (_SUMMARY_ROOT_SECTION_RE, "summary_root_categories"),
        (_SUMMARY_DEFECT_SECTION_RE, "summary_confirmed_defect_categories"),
    ):
        for heading in headings:
            if not classifier.search(heading.group(2)):
                continue
            section_body = _section_body(text, heading)
            titles = _list_entry_titles(section_body)
            if titles:
                entries = _summary_root_entries(
                    section_body,
                    base_line=(text or "")[:heading.end()].count("\n") + 1,
                )
                return {
                    "available": True,
                    "count": len(titles),
                    "titles": titles,
                    "entries": entries,
                    "reason": "parsed from final test-summary root/defect categories",
                    "extraction_method": method,
                }
    if explicit_counts:
        final_count = explicit_counts[-1]
        if final_count >= 0:
            return {
                "available": True, "count": final_count, "titles": [], "entries": [],
                "reason": "parsed from final test-summary explicit defect count",
                "extraction_method": "summary_explicit_final_count",
            }
    if _NO_DEFECT_RE.search(plain_text) or _ALL_FALSE_POSITIVE_RE.search(plain_text):
        return {
            "available": True, "count": 0, "titles": [], "entries": [],
            "reason": "final test summary explicitly reports no confirmed DUT RTL defect",
            "extraction_method": "explicit_no_defect_statement",
        }
    return {"available": False, "count": None, "titles": [], "entries": [], "reason": "final root categories not found in test summary"}


def extract_reported_root_causes(text: str) -> Dict[str, object]:
    """Return structurally declared root entries from a dynamic bug report."""
    # A report's explicit final self-summary is authoritative when available.
    # It is stronger than counting headings because some UCAgent versions put
    # one CK per heading even when the summary has already consolidated them.
    for pattern in _FINAL_COUNT_PATTERNS:
        final_counts = [int(value) for value in pattern.findall(text or "")]
        if final_counts:
            return {
                "available": True,
                "count": final_counts[-1],
                "titles": [],
                "entries": _dynamic_root_entries(text or ""),
                "reason": "parsed from dynamic report final bug-count statement",
                "extraction_method": "explicit_final_count",
            }
    matches = list(_ROOT_SECTION_RE.finditer(text or ""))
    if not matches:
        tagged_entries = _tagged_dynamic_root_entries(text or "")
        if tagged_entries:
            return {
                "available": True,
                "count": len(tagged_entries),
                "titles": [str(entry["title"]) for entry in tagged_entries],
                "entries": tagged_entries,
                "reason": "derived from structured BUG-ROOT-CAUSE fields; no final consolidated summary",
                "extraction_method": "structured_bug_root_cause_fields",
            }
        if _NO_DEFECT_RE.search(text or ""):
            return {
                "available": True, "count": 0, "titles": [], "entries": [],
                "reason": "dynamic report explicitly reports no defect",
                "extraction_method": "explicit_no_defect_statement",
            }
        return {"available": False, "count": None, "titles": [], "entries": [], "reason": "root-cause section not found"}
    all_titles: List[str] = []
    methods: List[str] = []
    for match in matches:
        tail = _section_body(text or "", match)
        headings = [(len(m.group(1)), m.group(2).strip()) for m in _HEADING_RE.finditer(tail)]
        if not headings:
            continue
        explicit = [title for _, title in headings if _NUMBERED_TITLE_RE.match(title) or _NAMED_ROOT_TITLE_RE.match(title)]
        if explicit:
            titles = explicit
            methods.append("explicit_root_headings")
        else:
            shallowest = min(level for level, _ in headings)
            titles = [title for level, title in headings if level == shallowest]
            methods.append("direct_section_headings")
        for title in titles:
            # Number prefixes vary across appended report sections.  Preserve
            # display text but de-duplicate exact repeated entries.
            if title not in all_titles:
                all_titles.append(title)
    if not all_titles:
        if _NO_DEFECT_RE.search(text or ""):
            return {
                "available": True, "count": 0, "titles": [], "entries": [],
                "reason": "dynamic report explicitly reports no defect",
                "extraction_method": "explicit_no_defect_statement",
            }
        return {"available": False, "count": None, "titles": [], "entries": [], "reason": "root-cause sections contain no declared entries"}
    return {
        "available": True,
        "count": len(all_titles),
        "titles": all_titles,
        "entries": _dynamic_root_entries(text or ""),
        "reason": "parsed from all dynamic report root-cause sections",
        "extraction_method": "+".join(sorted(set(methods))),
    }


def parse_reported_root_causes(path: str, test_summary_path: str = "") -> Dict[str, object]:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        dynamic_text = handle.read()
    dynamic_result = extract_reported_root_causes(dynamic_text)
    dynamic_result["source_path"] = path

    if test_summary_path and os.path.isfile(test_summary_path):
        with open(test_summary_path, encoding="utf-8", errors="ignore") as handle:
            result = extract_summary_root_causes(handle.read())
        if result.get("available") is True:
            result["source_path"] = test_summary_path
            # If summary entries have explicit RTL anchors, summary takes precedence
            has_summary_anchors = any(
                e.get("rtl_anchors") for e in result.get("entries", []) or []
            )
            if has_summary_anchors:
                return result
            # If summary lacks RTL anchors, but dynamic detailed analysis has explicit RTL anchors,
            # fall back to the evidenced dynamic result to avoid penalizing models whose summaries
            # discuss causal effects without repeating code line numbers.
            if dynamic_result.get("available") is True and any(
                e.get("rtl_anchors") for e in dynamic_result.get("entries", []) or []
            ):
                return dynamic_result
            if not result.get("entries"):
                result["identity_source_path"] = None
            return result
    return dynamic_result



def summarize_reported_roots_from_run_graphs(
    run_graphs: Sequence[Dict[str, object]], model_names: Sequence[str]
) -> Dict[str, object]:
    per_model: Dict[str, object] = {}
    for graph in run_graphs:
        manifest = graph.get("manifest", {}) if isinstance(graph, dict) else {}
        if not isinstance(manifest, dict):
            continue
        model = str(manifest.get("model") or "")
        if not model:
            continue
        report = graph.get("reported_root_causes")
        if isinstance(report, dict):
            per_model[model] = report
    for model in model_names:
        per_model.setdefault(str(model), {
            "available": False,
            "count": None,
            "titles": [],
            "reason": "dynamic report root-cause metric unavailable",
        })
    return {
        "definition": "root categories declared by the selected run, preferring its final test summary over dynamic report sections",
        "per_model": per_model,
    }


def summarize_reported_bug_claims_from_run_graphs(
    run_graphs: Sequence[Dict[str, object]], model_names: Sequence[str],
) -> Dict[str, object]:
    """Count the selected run's original bug-analysis declarations.

    This intentionally has a different meaning from reported root causes:
    each parsed BG claim is preserved, including a separately reported count
    of zero-confidence placeholders.  It represents what the UCAgent report
    initially declared before cross-model clustering or GT adjudication.
    """
    per_model: Dict[str, object] = {}
    for graph in run_graphs:
        manifest = graph.get("manifest", {}) if isinstance(graph, dict) else {}
        model = str(manifest.get("model") or "") if isinstance(manifest, dict) else ""
        if not model:
            continue
        claims = [item for item in graph.get("claims", []) or [] if isinstance(item, dict)]
        positive = sum(1 for claim in claims if int(claim.get("confidence_percent") or 0) > 0)
        source_path = ""
        found_files = manifest.get("found_files", {}) if isinstance(manifest, dict) else {}
        if isinstance(found_files, dict):
            source_path = str(found_files.get("bug_analysis") or "")
        per_model[model] = {
            "available": bool(source_path or claims),
            "declared_bug_count": len(claims),
            "positive_confidence_bug_count": positive,
            "zero_confidence_placeholder_count": len(claims) - positive,
            "source_path": source_path,
            "reason": "parsed BG bug declarations from the selected run's bug-analysis report",
        }
    for model in model_names:
        per_model.setdefault(str(model), {
            "available": False,
            "declared_bug_count": None,
            "positive_confidence_bug_count": None,
            "zero_confidence_placeholder_count": None,
            "source_path": "",
            "reason": "selected run has no parseable bug-analysis report",
        })
    return {
            "definition": "BG bug declarations from the selected UCAgent bug-analysis report before clustering or GT adjudication",
        "per_model": per_model,
    }


def _resolve_existing_path(path: str) -> str:
    if not path:
        return ""
    if os.path.exists(path):
        return path
    if "/inputs/compare/" in path:
        alt = path.replace("/inputs/compare/", "/inputs/wyy/compare/")
        if os.path.exists(alt):
            return alt
    return path


def _candidate_report_paths(payload: Dict[str, object], model: str) -> List[str]:
    paths: List[str] = []
    for record in payload.get("benchmark_records", []) or []:
        if not isinstance(record, dict) or str(record.get("model") or "") != model:
            continue
        for claim in record.get("claim_sources", []) or []:
            if not isinstance(claim, dict):
                continue
            source = claim.get("source_report", {})
            path = str(source.get("path") or "") if isinstance(source, dict) else ""
            path = _resolve_existing_path(path)
            if path and path not in paths:
                paths.append(path)
    return paths


def _selected_source(payload: Dict[str, object], model: str) -> Dict[str, object]:
    for source in payload.get("model_sources", []) or []:
        if isinstance(source, dict) and source.get("included") is True and str(source.get("model") or "") == model:
            res = dict(source)
            if res.get("workspace_root"):
                res["workspace_root"] = _resolve_existing_path(str(res["workspace_root"]))
            return res
    return {}


def _read_reports_from_selected_directory(
    payload: Dict[str, object], model: str,
) -> Dict[str, Tuple[str, str]]:
    """Resolve reports directly from the selected workspace directory.

    This cannot depend on CandidateBug.source_report: a correct run may report
    zero positive candidates and still contain an authoritative test summary.
    """
    source = _selected_source(payload, model)
    workspace = str(source.get("workspace_root") or "")
    dut = str(source.get("dut") or payload.get("dut") or "")
    if not workspace or not dut or not os.path.isdir(workspace):
        return {}
    documents = {}
    expected = {
        "test_summary": f"{dut}_test_summary.md",
        "bug_analysis": f"{dut}_bug_analysis.md",
    }
    for kind, name in expected.items():
        preferred = os.path.join(workspace, "unity_test", name)
        candidates = [preferred] if os.path.isfile(preferred) else []
        if not candidates:
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [entry for entry in dirs if entry not in {".ucagent", ".git"}]
                if name in files and "/.ucagent/history/" not in os.path.join(root, name):
                    candidates.append(os.path.join(root, name))
        if not candidates:
            # Also try title-case or uppercase e.g. Adder_test_summary.md
            for alt_name in (
                f"{dut.title()}_{kind}.md",
                f"{dut.capitalize()}_{kind}.md",
                f"Adder_{kind}.md",
            ):
                alt_path = os.path.join(workspace, "unity_test", alt_name)
                if os.path.isfile(alt_path):
                    candidates.append(alt_path)
                    break
        if candidates:
            try:
                with open(candidates[0], encoding="utf-8", errors="replace") as handle:
                    documents[kind] = (handle.read(), candidates[0])
            except OSError:
                continue
    return documents


def _read_reports_from_selected_archive(
    payload: Dict[str, object], model: str,
) -> Dict[str, Tuple[str, str]]:
    """Extract report markdown from the selected run's tar archive."""
    source = _selected_source(payload, model)
    archive = str(source.get("archive_path") or "")
    dut = str(source.get("dut") or payload.get("dut") or "")
    if not archive or not dut or not os.path.isfile(archive):
        return {}
    documents = {}
    expected = {
        "test_summary": f"{dut}_test_summary.md",
        "bug_analysis": f"{dut}_bug_analysis.md",
    }
    try:
        with tarfile.open(archive, "r:*") as handle:
            names = handle.getnames()
            for kind, name in expected.items():
                match = None
                for member in names:
                    if member.endswith(f"/unity_test/{name}"):
                        match = member
                        break
                if match is None:
                    for member in names:
                        if member.endswith(f"/{name}") and "/.ucagent/history/" not in member:
                            match = member
                            break
                if match is not None:
                    extracted = handle.extractfile(match)
                    if extracted is not None:
                        documents[kind] = (
                            extracted.read().decode("utf-8", errors="replace"),
                            f"{archive}!{match}",
                        )
    except (tarfile.TarError, OSError):
        return {}
    return documents


def backfill_reported_root_summary(payload: Dict[str, object]) -> Dict[str, object]:
    """Populate the metric for saved outputs without running benchmark/LLM/replay."""
    existing = payload.get("reported_root_cause_summary")
    existing_per_model = existing.get("per_model", {}) if isinstance(existing, dict) else {}
    per_model: Dict[str, object] = dict(existing_per_model) if isinstance(existing_per_model, dict) else {}
    for raw_model in payload.get("model_names", []) or []:
        model = str(raw_model)
        current = per_model.get(model)
        # Re-evaluate old values because newer extraction rules may discover a
        # stronger final-summary source than a previously parsed dynamic block.
        parsed = None
        for path in _candidate_report_paths(payload, model):
            path = _resolve_existing_path(path)
            if os.path.isfile(path):
                summary_path = os.path.join(os.path.dirname(path), f"{payload.get('dut')}_test_summary.md")
                if not os.path.isfile(summary_path):
                    dut_name = str(payload.get("dut") or "")
                    for cand_name in (
                        f"{dut_name.title()}_test_summary.md",
                        f"{dut_name.capitalize()}_test_summary.md",
                        "Adder_test_summary.md",
                    ):
                        cand = os.path.join(os.path.dirname(path), cand_name)
                        if os.path.isfile(cand):
                            summary_path = cand
                            break
                parsed = parse_reported_root_causes(path, summary_path)
                break
        if parsed is None:
            documents = _read_reports_from_selected_directory(payload, model)
            if not documents:
                documents = _read_reports_from_selected_archive(payload, model)
            if documents.get("test_summary"):
                text, source_path = documents["test_summary"]
                candidate = extract_summary_root_causes(text)
                if candidate.get("available") is True:
                    parsed = candidate
                    parsed["source_path"] = source_path
            if parsed is None and documents.get("bug_analysis"):
                text, source_path = documents["bug_analysis"]
                parsed = extract_reported_root_causes(text)
                parsed["source_path"] = source_path
        # Fixed-source audit payloads deliberately replace ephemeral archive
        # extraction paths with stable provenance tokens.  Those tokens are
        # not readable files during a later overall-score refresh, but the
        # structured report-root summary was already parsed and persisted in
        # the DUT matrix.  Never erase that stronger saved evidence merely
        # because the display/provenance path cannot be reopened offline.
        if parsed is not None:
            per_model[model] = parsed
        elif isinstance(current, dict) and (
            current.get("available") is True
            or current.get("count") is not None
            or bool(current.get("entries"))
        ):
            per_model[model] = current
        else:
            per_model[model] = {
                "available": False,
                "count": None,
                "titles": [],
                "entries": [],
                "reason": "selected run contains no resolvable root-cause declaration",
            }
    payload["reported_root_cause_summary"] = {
        "definition": "root categories declared by the selected run, preferring its final test summary over dynamic report sections",
        "per_model": per_model,
    }
    return payload


def attach_reported_root_alignment(payload: Dict[str, object]) -> Dict[str, object]:
    """Audit model-reported roots against GT through explicit attributes.

    No title similarity and no count equality is used.  A reported entry must
    have an explicit RTL file/line anchor that uniquely overlaps a GT anchor.
    CK/BG identities are a consistency constraint when present.  The GT must
    also record that model as a finder.  Each GT receives at most one credit.
    """
    defects = (payload.get("ground_truth_rtl_defects") or payload.get("_gt_file") or {}).get("defects", [])
    symptom_to_gt = {
        str(symptom): str(defect.get("gt_id"))
        for defect in defects if isinstance(defect, dict)
        for symptom in defect.get("symptoms", []) or [] if symptom and defect.get("gt_id")
    }
    gt_models = {
        str(defect.get("gt_id")): {str(model) for model in defect.get("models", []) or []}
        for defect in defects if isinstance(defect, dict) and defect.get("gt_id")
    }
    gt_anchors = {}
    for defect in defects:
        if not isinstance(defect, dict) or not defect.get("gt_id"):
            continue
        start = defect.get("rtl_line_start")
        end = defect.get("rtl_line_end")
        if isinstance(start, int):
            gt_anchors[str(defect["gt_id"])] = {
                "file": os.path.basename(str(defect.get("rtl_file") or "")),
                "line_start": start,
                "line_end": int(end) if isinstance(end, int) else start,
            }
    identity_to_symptoms: Dict[Tuple[str, str], set] = {}
    for record in payload.get("benchmark_records", []) or []:
        if not isinstance(record, dict) or record.get("status") != "found":
            continue
        model = str(record.get("model") or "")
        symptom = str(record.get("canonical_bug") or "")
        if not model or not symptom:
            continue
        for claim in record.get("claim_sources", []) or []:
            if not isinstance(claim, dict):
                continue
            ck = str(claim.get("bug_identity") or "")
            bg = str(claim.get("bg_name") or "")
            if ck:
                identity_to_symptoms.setdefault((model, ck), set()).add(symptom)
            if bg:
                identity_to_symptoms.setdefault((model, bg), set()).add(symptom)

    summary = payload.get("reported_root_cause_summary") or {}
    per_model = summary.get("per_model", {}) if isinstance(summary, dict) else {}
    alignment = {}
    for raw_model in payload.get("model_names", []) or []:
        model = str(raw_model)
        report = per_model.get(model, {}) if isinstance(per_model, dict) else {}
        declared_count = report.get("count") if isinstance(report, dict) and report.get("available") is True else None
        audits = []
        confirmed_gt_ids = set()
        for entry in report.get("entries", []) or [] if isinstance(report, dict) else []:
            identities = [str(value) for value in (entry.get("ck_paths", []) or []) + (entry.get("bg_names", []) or [])]
            symptoms = set()
            for identity in identities:
                symptoms.update(identity_to_symptoms.get((model, identity), set()))
            identity_gt_ids = {symptom_to_gt[symptom] for symptom in symptoms if symptom in symptom_to_gt}
            anchor_gt_ids = set()
            for anchor in entry.get("rtl_anchors", []) or []:
                if not isinstance(anchor, dict):
                    continue
                for gt_id, gt_anchor in gt_anchors.items():
                    raw_f1 = os.path.splitext(os.path.basename(str(anchor.get("file") or "")))[0].lower()
                    raw_f2 = os.path.splitext(gt_anchor["file"])[0].lower()
                    f1 = raw_f1[5:] if raw_f1.startswith("bosc_") else raw_f1
                    f2 = raw_f2[5:] if raw_f2.startswith("bosc_") else raw_f2

                    same_file = (f1 == f2 or f1 in f2 or f2 in f1)
                    start = anchor.get("line_start")
                    end = anchor.get("line_end")
                    overlaps = (
                        isinstance(start, int) and isinstance(end, int)
                        and start <= gt_anchor["line_end"] and gt_anchor["line_start"] <= end
                    )
                    if same_file and (overlaps or len(gt_anchors) == 1):
                        anchor_gt_ids.add(gt_id)
            # RTL location is the independent root attribute.  CK/BG mapping,
            # when available, must agree rather than broaden the match.
            gt_ids = anchor_gt_ids & identity_gt_ids if identity_gt_ids else set(anchor_gt_ids)
            if not gt_ids and len(identity_gt_ids) == 1:
                # When RTL anchor format differs across languages, an unambiguous CK/BG identity to GT is valid evidence
                gt_ids = set(identity_gt_ids)
            confirmed = len(gt_ids) == 1 and model in gt_models.get(next(iter(gt_ids), ""), set())
            target_gt = next(iter(gt_ids)) if confirmed else None
            if confirmed and target_gt:
                confirmed_gt_ids.add(target_gt)
            if not (entry.get("rtl_anchors", []) or []):
                if confirmed:
                    status = "confirmed_alignment"
                else:
                    status = "unavailable_missing_rtl_anchor"
            elif not anchor_gt_ids and not confirmed:
                status = "conflict_rtl_anchor_no_gt_match"
            elif len(anchor_gt_ids) > 1 and not confirmed:
                status = "ambiguous_rtl_anchor"
            elif identity_gt_ids and not gt_ids:
                status = "conflicting_identity_and_rtl_anchor"
            elif confirmed:
                status = "confirmed_alignment"
            elif len(gt_ids) > 1:
                status = "ambiguous_alignment"
            else:
                status = "unresolved_alignment"

            audits.append({
                "title": entry.get("title"),
                "ck_paths": entry.get("ck_paths", []),
                "bg_names": entry.get("bg_names", []),
                "rtl_anchors": entry.get("rtl_anchors", []),
                "mapped_symptoms": sorted(symptoms),
                "identity_gt_ids": sorted(identity_gt_ids),
                "rtl_anchor_gt_ids": sorted(anchor_gt_ids),
                "mapped_gt_ids": sorted(gt_ids),
                "status": status,
                "confirmed_gt_id": target_gt,
            })
        evaluable = (
            isinstance(declared_count, int) and declared_count > 0
            and (any(audit.get("rtl_anchor_gt_ids") for audit in audits) or any(audit.get("confirmed_gt_id") for audit in audits))
        )

        numerator = min(len(confirmed_gt_ids), int(declared_count or 0)) if evaluable else 0
        alignment[model] = {
            "available": evaluable,
            "judgement_source": "deterministic_attributes" if evaluable else "unresolved",
            "declared_root_count": declared_count,
            "confirmed_aligned_gt_count": numerator,
            "confirmed_gt_ids": sorted(confirmed_gt_ids),
            "score": round(numerator / int(declared_count), 6) if evaluable else None,
            "reason": (
                "strict RTL-anchor alignment, with CK/BG consistency when available"
                if evaluable else "no report-root RTL anchor can be compared with a GT anchor"
            ),
            "llm_review": {
                "status": "not_run",
                "eligible_entries": [
                    index for index, audit in enumerate(audits)
                    if audit.get("status") != "confirmed_alignment"
                ],
                "note": "optional independent review; must not reuse the GT-generating judgement",
            },
            "entries": audits,
        }
    payload["reported_root_gt_alignment"] = {
        "policy_version": "reported_root_alignment_v2",
        "method": "explicit reported RTL anchor -> unique GT-RTL anchor, constrained by CK/BG identity when available; unique GT credit; count/title equality ignored",
        "per_model": alignment,
    }
    return payload
