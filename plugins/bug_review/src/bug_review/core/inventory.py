"""Build the reported-Bug skeleton inventory from the original summary and analysis."""
from __future__ import annotations

from pathlib import Path
import re

from .claims import normalize_tc_label, report_claim_blocks
from .layout import resolve_logical_path, unity_test_root


def parse_summary(path):
    """Read the summary table while retaining its source row and analysis links."""
    if not path.is_file():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in {"Name", "---"}:
            continue
        name = cells[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            continue
        ranges = [(int(a), int(b)) for a, b in re.findall(
            r"bug_analysis\.md:(\d+)-(\d+)", cells[7])]
        rows.append({"bug_id": name, "summary": cells[4], "severity": cells[1],
                     "raw": line, "summary_item_present": True,
                     "reported_confidence": float(cells[6]) if re.fullmatch(r"0(?:\.\d+)?|1(?:\.0+)?", cells[6]) else None,
                     "ck": re.findall(r"FG-[^< ]+/FC-[^< ]+/CK-[^< ]+", cells[3]),
                     "rtl_refs": re.findall(r"[A-Za-z0-9_./-]+\.(?:sv|v):\d+(?:-\d+)?", cells[5]),
                     "source": {"path": str(path), "line": line_number},
                     "analysis_ranges": ranges})
    ids = [row["bug_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate Bug name in {path}")
    return rows


def build_inventory(source, name):
    """Build one reported-Bug inventory and a readable outline."""
    dut = name
    summary = resolve_logical_path(source, f"unity_test/{dut}_bug_summary.md")
    analysis = resolve_logical_path(source, f"unity_test/{dut}_bug_analysis.md")
    table = parse_summary(summary)
    for row in table:
        row["source"]["path"] = f"unity_test/{Path(row['source']['path']).name}"
    blocks = report_claim_blocks(source, name)
    analysis_lines = analysis.read_text(encoding="utf-8", errors="replace").splitlines() if analysis.is_file() else []
    bugs = []
    for row in table:
        aggregate = []
        for start, end in row["analysis_ranges"]:
            for line in analysis_lines[max(0, start - 1):end]:
                aggregate.extend(normalize_tc_label(node)
                                 for node in re.findall(r"<TC-([^>]+)>", line))
        bugs.append({**row, "origin": "reported", "claims": [], "tests": [],
                     "aggregate_tests": sorted(set(aggregate)),
                     "aggregate_refs": [f"unity_test/{analysis.name}:{start}-{end}"
                                        for start, end in row["analysis_ranges"]],
                     "root_refs": []})
    for block in blocks:
        identity = re.sub(r"-\d+$", "", block["source_label"].removeprefix("BG-"))
        if any(item["bug_id"] == identity for item in bugs):
            continue
        confidence = re.search(r"-(\d+)$", block["source_label"])
        reported_confidence = (int(confidence.group(1)) / 100 if confidence
                               and int(confidence.group(1)) <= 100 else None)
        bugs.append({"bug_id": identity, "origin": "reported", "summary": "",
                     "summary_item_present": False, "severity": "",
                     "reported_confidence": reported_confidence, "ck": [], "rtl_refs": [],
                     "source": {"path": f"unity_test/{analysis.name}", "line": int(block["ref"].split(":")[-1].split("-")[0])},
                     "analysis_ranges": [], "claims": [], "tests": [],
                     "aggregate_tests": [], "aggregate_refs": [], "root_refs": []})
    line_maps = resolve_logical_path(source, "unity_test/line_map")
    spec_files = {path.relative_to(source).as_posix().replace("/", "_").replace(".", "_"): path
                  for path in source.rglob("*.md") if "Guide_Doc" not in path.parts}
    for bug in bugs:
        refs = []
        for mapping in sorted(line_maps.glob("*_line_func_map.txt")):
            key = mapping.name.removesuffix("_line_func_map.txt")
            spec = spec_files.get(key)
            if spec is None:
                continue
            for line in mapping.read_text(encoding="utf-8", errors="replace").splitlines():
                for ck in bug["ck"]:
                    match = re.match(rf"^{re.escape(ck)}:\s*(\d+)-(\d+)", line)
                    if match:
                        refs.append(f"{spec.relative_to(source)}:{match.group(1)}-{match.group(2)}")
        bug["spec_refs"] = sorted(set(refs))[:32]
    if not summary.is_file() and not analysis.is_file():
        raise ValueError(f"Bug reports missing for {name}: {summary}, {analysis}")
    lines = ["", f"# {dut} Bug 复核骨架", "", f"输入工作区：{source}", ""]
    if not bugs:
        lines.extend(["## 原报告 Bug", "", "原报告没有 Bug 条目。", ""])
    for row in bugs:
        lines.extend([f"## {row['bug_id']}", "", row["summary"] or "待核对原报告声明", "",
                      f"- 关联测试：{', '.join(row['tests']) or '待查'}",
                      f"- CK：{', '.join(row['ck']) or '待查'}",
                      f"- Spec 候选：{', '.join(row['spec_refs']) or '待查'}",
                      f"- RTL 候选：{', '.join(row['rtl_refs']) or '待查'}",
                      f"- ROOT 候选：{', '.join(row['root_refs']) or '待查'}",
                      "- 待核实：测试正确性、规格预期、重跑结果、波形有效窗口和 RTL 因果链", ""])
    return {"schema": "bug_review_inventory.v2", "name": name, "dut": dut,
            "source_workspace": str(source), "summary_path": str(summary) if summary.is_file() else "",
            "analysis_path": str(analysis) if analysis.is_file() else "",
            "diagnostics": [f"missing {path}" for path in (summary, analysis) if not path.is_file()],
            "bugs": bugs}, "\n".join(lines)
