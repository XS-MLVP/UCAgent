# coding=utf8
"""按 case_id 快速读取保存的 pytest stdout 失败段（case_triage 逐 case 取证）。

前提：RunTestCases 的文本返回已由评审者保存到 {OUT}/diagnostics/run_logs/*.txt
（约定：每批一个 .txt，文件名含批次标签）。本脚本在日志中定位指定 case 的
FAILURES 段并打印，不运行测试、不改任何记录。

用法（workspace 根目录）：
    RunSkillScript(commands=[["ext/bug_review/replay-review", "read_case_stdout.py",
                              "unity_test/tests/test_raid_enc_top_cmd.py::test_cmd_0_init --tail 20"]])
    # 位置参数: 一个或多个 case_id（完整 unity_test/...::name，或仅 test 名）
    # --tail N: 每个失败只保留 traceback 尾部 N 行（默认 25；--full 打印整段）

输出即证据原文（pytest traceback），可直接摘录进 failure_analysis。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SUMMARIZE = "summarize_case_failures.py"


def load_shared():
    """复用同目录 summarize_case_failures.py 的解析函数。"""
    import importlib.util
    path = Path(__file__).with_name(SUMMARIZE)
    spec = importlib.util.spec_from_file_location("summarize_case_failures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_section(logs_dir: Path, name: str):
    """按 mtime 从新到旧找含该 test 名 FAILURES 段的最新日志。"""
    shared = load_shared()
    for path in sorted(Path(logs_dir).glob("*.txt"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        stdout = shared.decode_stdout(
            path.read_text(encoding="utf-8", errors="replace"))
        failures = shared.parse_failures(stdout)
        if name in failures:
            return path.name, failures[name]
    return None, None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="+", help="case_id 或 test 名")
    parser.add_argument("--logs", default="", help="运行日志目录（默认 OUT/diagnostics/run_logs）")
    parser.add_argument("--tail", type=int, default=25)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    workspace = Path.cwd().resolve()
    out = workspace / json.loads(
        (workspace / ".ucagent/runtime_config.json").read_text(encoding="utf-8"))["OUT"]
    logs_dir = Path(args.logs) if args.logs else out / "diagnostics/run_logs"

    not_found = []
    for case_id in args.case_ids:
        name = case_id.split("::")[-1]
        log, section = find_section(logs_dir, name)
        print("=" * 24, case_id)
        if section is None:
            not_found.append(case_id)
            print(f"!! 未在任何日志找到 FAILURES 段（确认已保存 RunTestCases 返回到 {logs_dir}）")
            continue
        print(f"source log: {log}")
        if args.full:
            print(section.strip()[:8000])
        else:
            lines = [line for line in section.splitlines() if line.strip()]
            kept = [line for line in lines
                    if re.match(r"^\s{0,4}(\S+\.py:\d+|E )", line.strip())]
            body = kept if kept else lines
            print("\n".join(body[:40]))
            tail = lines[-args.tail:]
            if tail and lines.index(tail[0]) > len(body) + 1:
                print("... (尾部)")
            print("\n".join(tail))
    if not_found:
        print(f"\nmissing: {not_found}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
