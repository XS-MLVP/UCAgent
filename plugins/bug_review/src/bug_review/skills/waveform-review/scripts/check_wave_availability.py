# coding=utf8
"""盘点 dut_evidence 目标 case 的波形可用性（一次调用，替代逐 case 探测）。

每次运行的波形保存在 unity_test/data 下各自的时间戳 toffee_tmp 会话目录，
永不覆盖（full_replay 导入时已自动搬入并清理通过 case 的波形）。本脚本把
目标 case 对照全部会话（新会话优先）里的 dump 文件分为三类：
  - fst/vcd 可用 —— 直接 WaveInfo 取证，无需重跑；
  - 仅 dat       —— 测试写了数据但波形未生成，需要定向复跑；
  - 缺失         —— 无任何 dump，需要定向复跑。
并打印需要复跑 case 的精确 pytest 目标清单。不运行测试、不修改任何文件。

用法（workspace 根目录）：
    RunSkillScript(commands=[["ext/bug_review/waveform-review",
                              "check_wave_availability.py"]])
    # --all-failed  盘点全部基线失败 case（默认只盘点 suspected_dut）
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bug_review.core.layout import unity_test_root
from bug_review.core.replay import _sessions, _wave_function_stem


def _find_dump(sessions, stem: str, suffix: str):
    """按 WaveInfo 同款规则（新会话优先，stem[数字].后缀，忽略大小写）找一个 dump 文件。"""
    for session in sessions:
        for path in sorted(session.rglob("*")):
            if path.is_file() and re.fullmatch(
                    re.escape(stem) + r"\d*\." + suffix, path.name, re.IGNORECASE):
                return path
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-failed", action="store_true",
                        help="盘点全部基线失败 case，而非仅 suspected_dut")
    args = parser.parse_args()

    workspace = Path.cwd().resolve()
    out = workspace / json.loads(
        (workspace / ".ucagent/runtime_config.json").read_text(encoding="utf-8"))["OUT"]
    index = json.loads((out / "review_index.json").read_text(encoding="utf-8"))

    targets = []
    for case_id, entry in index.get("cases", {}).items():
        record = json.loads((out / entry["record_path"]).read_text(encoding="utf-8"))
        if args.all_failed:
            wanted = record.get("replay", {}).get("status") == "failed"
        else:
            wanted = record.get("failure_analysis", {}).get("category") == "suspected_dut"
        if wanted:
            targets.append((case_id, entry.get("replay_target", case_id),
                            entry.get("waveform_test_case_name") or case_id))

    sessions = _sessions(unity_test_root(workspace) / "data")
    location = "、".join(s.relative_to(workspace).as_posix() for s in sessions[:5]) \
        or "无（需先定向复跑生成波形）"
    if len(sessions) > 5:
        location += f"（共 {len(sessions)} 个会话）"
    print(f"波形会话: {location}")

    usable, dat_only, missing = [], [], []
    for case_id, replay_target, wtn in targets:
        stem = _wave_function_stem(wtn)
        fst = _find_dump(sessions, stem, r"(?:fst|vcd)") if sessions else None
        dat = _find_dump(sessions, stem, r"dat") if sessions else None
        if fst is not None:
            usable.append((case_id, replay_target, fst))
        elif dat is not None:
            dat_only.append((case_id, replay_target, dat))
        else:
            missing.append((case_id, replay_target, None))

    for title, rows in (("fst/vcd 可用（直接取证）", usable),
                        ("仅 dat（波形未生成，需复跑）", dat_only),
                        ("缺失（需复跑）", missing)):
        print(f"\n== {title}: {len(rows)} ==")
        for case_id, _replay_target, dump in rows:
            detail = f"  {dump.stat().st_size // 1024}KB {dump.name}" if dump else ""
            print(f"  {case_id}{detail}")

    rerun = dat_only + missing
    if rerun:
        print("\n需要定向复跑的 pytest 目标（RunTestCases pytest_args 逐字使用）:")
        for _case_id, replay_target, _dump in rerun:
            print(f"  {replay_target}")
    print(f"\n汇总: 可用 {len(usable)} / 仅dat {len(dat_only)} / 缺失 {len(missing)}")


if __name__ == "__main__":
    main()
