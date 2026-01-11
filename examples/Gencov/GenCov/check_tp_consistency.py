#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, Set, Tuple

DEFAULT_PATTERN = r"TP_[A-Z0-9_]+"


def extract_tp_labels(text: str, pattern: str = DEFAULT_PATTERN) -> Set[str]:
    return set(re.findall(pattern, text))


def compare_tp_sets(
    hvp_text: str, cov_text: str, pattern: str = DEFAULT_PATTERN
) -> Tuple[Set[str], Set[str]]:
    hvp_set = extract_tp_labels(hvp_text, pattern)
    cov_set = extract_tp_labels(cov_text, pattern)
    missing = hvp_set - cov_set
    extra = cov_set - hvp_set
    return missing, extra


def _format_list(items: Iterable[str]) -> str:
    items = sorted(items)
    if not items:
        return "（无）"
    return "\n".join(f"- {item}" for item in items)


def render_report(
    hvp_path: Path,
    cov_path: Path,
    hvp_set: Set[str],
    cov_set: Set[str],
    missing: Set[str],
    extra: Set[str],
) -> str:
    return "\n".join(
        [
            "# TP 一致性检查报告",
            f"- HVP 文件：`{hvp_path}`",
            f"- 覆盖文件：`{cov_path}`",
            f"- HVP TP 总数：{len(hvp_set)}",
            f"- 覆盖 TP 总数：{len(cov_set)}",
            "",
            "## 缺失（HVP 中有、覆盖中没有）",
            _format_list(missing),
            "",
            "## 多余（覆盖中有、HVP 中没有）",
            _format_list(extra),
            "",
        ]
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="TP 一致性检查")
    parser.add_argument("--hvp", required=True, help="HVP 文件路径")
    parser.add_argument("--cov", required=True, help="覆盖率 Verilog 文件路径")
    parser.add_argument("--out", help="输出报告路径（markdown）")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="TP 标签匹配正则")
    args = parser.parse_args()

    hvp_path = Path(args.hvp)
    cov_path = Path(args.cov)
    if not hvp_path.is_file():
        print(f"找不到 HVP 文件：{hvp_path}", file=sys.stderr)
        return 2
    if not cov_path.is_file():
        print(f"找不到覆盖文件：{cov_path}", file=sys.stderr)
        return 2

    hvp_text = _read_text(hvp_path)
    cov_text = _read_text(cov_path)
    hvp_set = extract_tp_labels(hvp_text, args.pattern)
    cov_set = extract_tp_labels(cov_text, args.pattern)
    missing, extra = compare_tp_sets(hvp_text, cov_text, args.pattern)
    report = render_report(hvp_path, cov_path, hvp_set, cov_set, missing, extra)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(report, encoding="utf-8")
    else:
        print(report)

    return 1 if missing or extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
