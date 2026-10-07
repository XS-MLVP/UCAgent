# coding=utf8
"""按失败签名汇总全部失败 case 的 pytest 证据（case_triage 阶段快速分诊入口）。

从 {OUT}/diagnostics/run_logs/*.txt 中保存的 RunTestCases 文本返回里解析
FAILURES 段，为每个 failed case 提炼：异常行、失败位置、调用帧、traceback 尾部，
并按 (异常, 位置) 签名分组。与 {OUT}/replay_summary.json 的 failed 清单对账，
列出没有任何 traceback 证据的 case。

用法（workspace 根目录）：
    RunSkillScript(commands=[["ext/bug_review/replay-review",
                              "summarize_case_failures.py", "--save"]])
    # --save 额外落盘 {OUT}/diagnostics/failure_signatures.json 供逐 case 引用
    # --case <case_id> 只汇总指定 case；--limit N 每组只打印 N 个成员

本脚本只读取既有日志，不运行测试、不修改任何权威记录。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


def resolve_out(workspace: Path) -> Path:
    """复用 review-notes 的约定：从 .ucagent/runtime_config.json 解析 OUT。"""
    runtime = workspace / ".ucagent/runtime_config.json"
    out = workspace / json.loads(runtime.read_text(encoding="utf-8"))["OUT"]
    if not out.is_relative_to(workspace):
        raise ValueError(f"OUT 解析结果越界: {out}")
    return out


def canonical(node: str) -> str:
    return re.sub(r"(?<=\.py):\d+(?:-\d+)?(?=::|$)", "", str(node))


def decode_stdout(text: str) -> str:
    """取 RunTestCases 返回文本中的 STDOUT: "<json>" 并解码。"""
    for line in text.splitlines():
        if line.startswith('STDOUT: "') or line.startswith("STDOUT: '"):
            raw = line[len("STDOUT: "):].strip()
            try:
                return json.loads(raw)
            except Exception:
                return raw.encode().decode("unicode_escape", errors="replace")
    return ""


SECTION_RE = re.compile(r"^_{5,}\s+(\S+)\s+_{5,}$", re.M)


def parse_failures(stdout: str) -> dict:
    """从 pytest 输出切出 {test_name: traceback_text}。"""
    out = {}
    match = re.search(r"=+ FAILURES =+", stdout)
    if not match:
        return out
    body = stdout[match.end():]
    stop = re.search(r"=+ (?:short test summary|warnings summary|no tests ran)", body)
    if stop:
        body = body[:stop.start()]
    marks = list(SECTION_RE.finditer(body))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        out[mark.group(1)] = body[mark.end():end]
    return out


def condense(trace: str) -> dict:
    """把一个 traceback 压成 {exc, loc, frames, tail}。"""
    lines = [line for line in trace.splitlines() if line.strip()]
    exc, loc, frames = "", "", []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("E ") and not exc:
            exc = stripped[2:].strip()
        if not loc:
            hit = re.match(r"^(\S+\.py):(\d+): ", stripped)
            if hit:
                loc = f"{hit.group(1)}:{hit.group(2)}"
        frame = re.match(r"^(\S+\.py):(\d+): in (\S+)", stripped)
        if frame:
            frames.append(f"{frame.group(1)}:{frame.group(2)}:{frame.group(3)}")
    return {"exc": exc, "loc": loc, "frames": frames[:8],
            "tail": "\n".join(lines[-10:])}


def collect(logs_dir: Path) -> dict:
    """按 mtime 从新到旧解析日志，同 case 保留最新一次失败。"""
    details = {}
    if not logs_dir.is_dir():
        return details
    for path in sorted(logs_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime,
                       reverse=True):
        stdout = decode_stdout(path.read_text(encoding="utf-8", errors="replace"))
        for name, trace in parse_failures(stdout).items():
            summary = condense(trace)
            entry = {**summary, "log": path.name}
            for case_id, seen in list(details.items()):
                if case_id.split("::")[-1] == name:
                    del details[case_id]  # 旧日志的同名失败被更新的一次覆盖
            details.setdefault(f"<file内同名待归位>::{name}", entry)
    return details


def match_cases(details: dict, replay: dict) -> tuple:
    """把解析出的失败按 test 名对位到 replay_summary 的 failed case id。"""
    failed = [case_id for case_id, status in replay.get("outcomes", {}).items()
              if status in {"failed", "error", "xpassed"}]
    by_name = defaultdict(list)
    for case_id in failed:
        by_name[case_id.split("::")[-1]].append(case_id)
    aligned, merged = {}, {}
    for placeholder, entry in details.items():
        name = placeholder.split("::")[-1]
        hits = by_name.get(name, [])
        if len(hits) == 1:
            aligned[hits[0]] = entry
        else:
            merged[placeholder] = entry
    missing = [case_id for case_id in failed if case_id not in aligned]
    return aligned, merged, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", default="", help="运行日志目录（默认 OUT/diagnostics/run_logs）")
    parser.add_argument("--limit", type=int, default=5, help="每组打印成员数上限")
    parser.add_argument("--case", action="append", default=[], help="只汇总指定 case_id")
    parser.add_argument("--save", action="store_true", help="落盘 failure_signatures.json")
    args = parser.parse_args()

    workspace = Path.cwd().resolve()
    out = resolve_out(workspace)
    logs_dir = Path(args.logs) if args.logs else out / "diagnostics/run_logs"
    replay_path = out / "replay_summary.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8")) if replay_path.is_file() else {}

    aligned, merged, missing = match_cases(collect(logs_dir), replay)
    if args.case:
        wanted = set(args.case)
        aligned = {k: v for k, v in aligned.items() if k in wanted}
        merged = {k: v for k, v in merged.items()
                  if any(k.endswith("::" + c.split("::")[-1]) for c in wanted)}
        missing = [c for c in missing if c in wanted]

    groups = defaultdict(list)
    for case_id, entry in {**aligned, **merged}.items():
        groups[(entry["exc"][:140], entry["loc"])].append((case_id, entry))
    print(json.dumps({
        "replay_failed": len(replay.get("outcomes", {}) or {}) and sum(
            1 for s in replay.get("outcomes", {}).values()
            if s in {"failed", "error", "xpassed"}),
        "with_traceback": len(aligned),
        "ambiguous_names": len(merged),
        "missing_evidence": missing,
        "signature_groups": len(groups),
    }, ensure_ascii=False, indent=1))
    for (exc, loc), members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"\n[{len(members)}] {exc}  @ {loc}")
        files = defaultdict(int)
        for case_id, _ in members:
            files[case_id.split("::")[0].replace("unity_test/tests/", "")] += 1
        for path, count in sorted(files.items()):
            print(f"      {path}: {count}")
        for case_id, entry in members[:args.limit]:
            print(f"      e.g. {case_id}")
    if args.save:
        target = out / "diagnostics/failure_signatures.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(
            {"aligned": aligned, "ambiguous": merged, "missing": missing},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nsaved {target}")


if __name__ == "__main__":
    sys.exit(main())
