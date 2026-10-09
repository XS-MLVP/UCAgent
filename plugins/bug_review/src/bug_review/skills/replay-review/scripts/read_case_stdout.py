# coding=utf8
"""按 case_id 快速读取 pytest stdout 失败段（case_triage 逐 case 取证）。

证据来源自动合并（无需手工保存）：
  1. .ucagent/current_test_report.json 的 pytest_stdout —— RunTestCases 每次运行
     都自动写入最新一次 pytest 原始输出；
  2. {OUT}/diagnostics/run_logs/*.txt —— full_replay 导入时自动归档的历史批次。

本脚本在证据中定位指定 case 的 FAILURES 段并打印，不运行测试、不改任何记录。

用法（workspace 根目录）：
    RunSkillScript(commands=[["ext/bug_review/replay-review", "read_case_stdout.py",
                              "unity_test/tests/test_raid_enc_top_cmd.py::test_cmd_0_init --tail 20"]])
    # 位置参数: 一个或多个 case_id（完整 unity_test/...::name，或仅 test 名）
    # --tail N: 每个失败只保留 traceback 尾部 N 行（默认 25；--full 打印整段）

输出即证据原文（pytest traceback），可直接摘录进 failure_analysis。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bug_review.core.failures import parse_failures

SUMMARIZE = "summarize_case_failures.py"


def load_shared():
    """复用同目录 summarize_case_failures.py 的证据装载函数。"""
    import importlib.util
    path = Path(__file__).with_name(SUMMARIZE)
    spec = importlib.util.spec_from_file_location("summarize_case_failures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="+", help="case_id 或 test 名")
    parser.add_argument("--logs", default="", help="历史归档目录（默认 OUT/diagnostics/run_logs）")
    parser.add_argument("--tail", type=int, default=25)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    workspace = Path.cwd().resolve()
    shared = load_shared()
    out = shared.resolve_out(workspace)
    logs_dir = Path(args.logs) if args.logs else out / "diagnostics/run_logs"
    parsed = [(name, parse_failures(stdout))
              for name, stdout in shared.load_sources(workspace, logs_dir)]

    not_found = []
    for case_id in args.case_ids:
        name = case_id.split("::")[-1]
        source, section = next(((s, sections[name]) for s, sections in parsed if name in sections),
                               (None, None))
        print("=" * 24, case_id)
        if section is None:
            not_found.append(case_id)
            print(f"!! 未在任何证据中找到 FAILURES 段（case 可能未失败，或来源里无该 test 名）")
            continue
        print(f"source: {source}")
        if args.full:
            print(section.strip()[:8000])
        else:
            lines = [line for line in section.splitlines() if line.strip()]
            kept = [line for line in lines
                    if line.strip().startswith("E ") or ".py:" in line]
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
