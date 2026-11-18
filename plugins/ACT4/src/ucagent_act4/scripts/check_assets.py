"""Standalone CLI for ACT4 asset checks; run with python -m ucagent_act4.scripts.check_assets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from ..checkers import act4_asset_consistency as core


def build_arg_parser() -> argparse.ArgumentParser:
    """Describe the standalone asset-check arguments shared with the checker engine."""
    parser = argparse.ArgumentParser(description="Check ACT4 assets, formats, and cross-asset consistency")
    parser.add_argument("--suite", default="")
    parser.add_argument("--act4-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--sheet-csv", type=Path)
    parser.add_argument("--norm-rules", type=Path)
    parser.add_argument("--inventory", type=Path, help="suite_inventory.json used to confirm plan ownership")
    parser.add_argument("--asset-plan", type=Path, help="asset_plan.json used for required asset completeness")
    parser.add_argument(
        "--checker-type",
        choices=sorted(core.CHECKER_PROFILES),
        default="all",
        help="asset-plan kind profile; all keeps the full canonical ACT4 gate",
    )
    parser.add_argument(
        "--completeness",
        choices=["source", "full"],
        default="source",
        help="source checks required source assets; full also checks generated and validation assets",
    )
    parser.add_argument("--coverage-file", action="append", default=[])
    parser.add_argument(
        "--coverage-symbol-kind",
        action="append",
        default=[],
        choices=["coverpoint", "cross"],
        help="coverage symbol kinds used for plan/generator comparisons",
    )
    parser.add_argument("--coverage-pattern", action="append", default=[])
    parser.add_argument("--generator", action="append", default=[])
    parser.add_argument("--generator-pattern", action="append", default=[])
    parser.add_argument("--require-priv-testchunk-api", action="store_true")
    parser.add_argument("--require-generator-auto-split", action="store_true")
    parser.add_argument("--require-standalone-generator", action="store_true")
    parser.add_argument("--ctp-file", action="append", default=[])
    parser.add_argument("--asset", action="append", default=[], help="Generic asset path; use --manifest for schema/hash rules")
    parser.add_argument("--require-norm-rules", action="store_true")
    parser.add_argument("--no-require-ctp", action="store_true")
    parser.add_argument("--exact-sheet-coverpoints", action="store_true")
    parser.add_argument(
        "--coverage-comparison-mode",
        choices=["all", "mapping_targets"],
        default="all",
    )
    parser.add_argument("--allow-extra-sheet-rules", action="store_true")
    parser.add_argument("--no-compare-source-mapping", action="store_true")
    parser.add_argument("--allow-cross-suite-group", action="append", default=[])
    parser.add_argument("--no-strict-ownership", action="store_true")
    parser.add_argument("--no-require-suite-group", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--stdout", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run deterministic checks and write JSON/Markdown reports with a process exit status."""
    args = build_arg_parser().parse_args(argv)
    try:
        report = core.run_asset_checks(
            suite=args.suite,
            act4_root=args.act4_root,
            mapping=args.mapping,
            sheet_csv=args.sheet_csv,
            norm_rules=args.norm_rules,
            inventory=args.inventory,
            asset_plan=args.asset_plan,
            completeness=args.completeness if args.asset_plan else "none",
            checker_type=args.checker_type,
            coverage_files=args.coverage_file,
            coverage_symbol_kinds=args.coverage_symbol_kind,
            coverage_patterns=args.coverage_pattern,
            generator_files=args.generator,
            generator_patterns=args.generator_pattern,
            require_priv_testchunk_api=args.require_priv_testchunk_api,
            require_generator_auto_split=args.require_generator_auto_split,
            require_standalone_generator=args.require_standalone_generator,
            ctp_files=args.ctp_file,
            assets=args.asset,
            manifest=args.manifest,
            require_norm_rules=args.require_norm_rules,
            require_ctp=not args.no_require_ctp,
            exact_sheet_coverpoints=args.exact_sheet_coverpoints,
            coverage_comparison_mode=args.coverage_comparison_mode,
            exact_sheet_rules=not args.allow_extra_sheet_rules,
            compare_source_mapping=not args.no_compare_source_mapping,
            strict_ownership=not args.no_strict_ownership,
            require_suite_group=not args.no_require_suite_group,
            allow_cross_suite_groups=args.allow_cross_suite_group,
            fail_on_warning=args.fail_on_warning,
        )
    except core.AssetCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output_dir = (args.output_dir or Path(os.environ.get("OUT", "output")) / "act4_asset_check").expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{args.suite or 'manifest'}.asset-consistency.json"
    md_path = output_dir / f"{args.suite or 'manifest'}.asset-consistency.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(core._format_report_markdown(report), encoding="utf-8")
    if args.stdout:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {report['status']}")
        print(f"Errors: {report['summary']['errors']}; warnings: {report['summary']['warnings']}")
        print(f"JSON: {json_path}")
        print(f"Markdown: {md_path}")
    if report["summary"]["errors"] or (args.fail_on_warning and report["summary"]["warnings"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
