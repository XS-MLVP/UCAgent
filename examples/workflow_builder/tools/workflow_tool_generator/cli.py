# -*- coding: utf-8 -*-
"""CLI for deterministic workflow tool generation."""

from __future__ import annotations

import argparse

from .core import ToolGenerationError, generate_tools, generate_tools_from_specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate workflow tools into an existing workflow root.")
    parser.add_argument("workflow_root", help="Path to generated workflow root")
    parser.add_argument("--tool", action="append", dest="tools", help="Tool name to generate; repeatable")
    parser.add_argument(
        "--from-spec",
        action="append",
        dest="spec_paths",
        help="Generate a tool implementation from this tool_spec path; repeatable",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated tool files")
    parser.add_argument(
        "--existing-policy",
        choices=("create_only", "refresh_scaffold", "force_replace"),
        default=None,
        help="Policy for existing generated files; defaults to create_only.",
    )
    parser.add_argument("--no-update-config", action="store_true", help="Do not update config.yaml tool registration")
    args = parser.parse_args(argv)
    try:
        if args.spec_paths:
            report = generate_tools_from_specs(
                args.workflow_root,
                spec_paths=args.spec_paths,
                overwrite=args.overwrite,
                existing_policy=args.existing_policy,
                update_config=not args.no_update_config,
            )
        else:
            report = generate_tools(
                args.workflow_root,
                tool_names=args.tools,
                overwrite=args.overwrite,
                existing_policy=args.existing_policy,
                update_config=not args.no_update_config,
            )
    except ToolGenerationError as exc:
        print(str(exc))
        return 1
    print(f"[workflow_tool_generator] root: {report.workflow_root}")
    print(f"[workflow_tool_generator] generated_tools: {', '.join(report.generated_tools)}")
    print(f"[workflow_tool_generator] source_specs: {', '.join(report.source_specs)}")
    print(f"[workflow_tool_generator] created_files: {len(report.created_files)}")
    print(f"[workflow_tool_generator] skipped_files: {len(report.skipped_files)}")
    print(f"[workflow_tool_generator] refreshed_files: {len(report.refreshed_files)}")
    print(f"[workflow_tool_generator] replaced_files: {len(report.replaced_files)}")
    print(f"[workflow_tool_generator] warnings: {'; '.join(report.warnings)}")
    print(f"[workflow_tool_generator] updated_config: {report.updated_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
