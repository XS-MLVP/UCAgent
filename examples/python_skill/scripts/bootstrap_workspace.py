#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


WORKSPACE_METADATA = "workspace.json"


def fail(message: str):
    raise SystemExit(f"FAIL workspace: {message}")


def build_metadata(args, workspace: Path):
    metadata = {
        "workspace": str(workspace),
        "dut": args.dut,
        "project_root": str(Path(args.project_root).expanduser().resolve()) if args.project_root else None,
        "tests_dir": str(Path(args.tests_dir).expanduser().resolve()) if args.tests_dir else None,
        "docs_dir": str(Path(args.docs_dir).expanduser().resolve()) if args.docs_dir else None,
        "exports_dir": str((workspace / "exports").resolve()),
        "generated_dir": str((workspace / "generated").resolve()),
        "logs_dir": str((workspace / "logs").resolve()),
    }
    return metadata


def create_workspace(workspace: Path, metadata: dict):
    if workspace.exists() and any(workspace.iterdir()):
        fail(f"refusing to initialize non-empty workspace directory {workspace}")

    workspace.mkdir(parents=True, exist_ok=True)
    for child in ("exports", "generated", "logs"):
        (workspace / child).mkdir(exist_ok=True)

    metadata_path = workspace / WORKSPACE_METADATA
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"PASS workspace root: {workspace}")
    print(f"PASS workspace exports: {workspace / 'exports'}")
    print(f"PASS workspace generated: {workspace / 'generated'}")
    print(f"PASS workspace logs: {workspace / 'logs'}")
    print(f"PASS workspace metadata: {metadata_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Create a disposable verification workspace for pytoffee workflow artifacts."
    )
    parser.add_argument("--workspace", required=True, help="Workspace directory to create.")
    parser.add_argument("--dut", help="DUT name for workspace metadata.")
    parser.add_argument("--project-root", help="Project root associated with the workspace.")
    parser.add_argument("--tests-dir", help="Tests directory associated with the workspace.")
    parser.add_argument("--docs-dir", help="Documentation directory associated with the workspace.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    metadata = build_metadata(args, workspace)
    create_workspace(workspace, metadata)


if __name__ == "__main__":
    main()
