# -*- coding: utf-8 -*-
"""CLI for deterministic checker generation."""

from __future__ import annotations

import argparse

from .core import CheckerGenerationError, generate_checkers_from_specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate workflow checkers from checker specs.")
    parser.add_argument("workflow_root")
    parser.add_argument("--from-spec", action="append", dest="spec_paths", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-update-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = generate_checkers_from_specs(
            args.workflow_root,
            args.spec_paths,
            overwrite=args.overwrite,
            update_config=not args.no_update_config,
        )
    except CheckerGenerationError as exc:
        print(str(exc))
        return 1
    print(f"[workflow_checker_generator] root: {report.workflow_root}")
    print(f"[workflow_checker_generator] generated_checkers: {', '.join(report.generated_checkers)}")
    print(f"[workflow_checker_generator] updated_config: {report.updated_config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
