# -*- coding: utf-8 -*-
"""Command-line interface for initializing and validating evaluation JSON state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .approvals import create_suggestion, decide_item, review_items
from .json_store import (
    JsonStoreError,
    aggregate_summary,
    initialize_workspace,
    mutate_document,
    update_run_request,
    validate_workspace,
)
from .incremental_runs import (
    IncrementalRunError,
    current_incremental_run,
    start_incremental_run,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("initialize")
    sub.add_parser("validate")
    sub.add_parser("aggregate")
    sub.add_parser("start-inc-run", help="Create one isolated incremental repair run.")
    current_run = sub.add_parser("current-inc-run", help="Show the current incremental run.")
    current_run.add_argument("--plain", action="store_true", help="Print only the run id.")
    request = sub.add_parser("request-run")
    request.add_argument("--mode", choices=("default", "inc"), required=True)
    request.add_argument("--workflow-root", default="workflow")
    request.add_argument("--target", default="example")
    request.add_argument("--stall-timeout", type=int, default=300)
    request.add_argument("--max-runtime", type=int, default=1800)
    crud = sub.add_parser("crud")
    crud.add_argument("--action", choices=("list", "get", "create", "update", "delete", "upsert"), required=True)
    crud.add_argument("--document", required=True)
    crud.add_argument("--id", default="")
    crud.add_argument("--record-json", default="")
    crud.add_argument("--expected-revision", type=int)
    sub.add_parser("list-review", help="List open findings and user suggestions.")
    review = sub.add_parser("review", help="Interactively review findings and suggestions.")
    review.add_argument("--show-evidence", action="store_true")
    for command in ("approve", "reject", "defer"):
        decision = sub.add_parser(command, help=f"{command.title()} one current finding or suggestion.")
        decision.add_argument("--id", required=True, help="Finding or suggestion id.")
        decision.add_argument("--reason", required=True)
    suggest = sub.add_parser("suggest", help="Create a user suggestion without editing JSON.")
    suggest.add_argument("--title", required=True)
    suggest.add_argument("--description", required=True)
    suggest.add_argument("--priority", choices=("critical", "high", "medium", "low"), default="medium")
    return parser


def _print_review_items(items: list[dict], show_evidence: bool = False) -> None:
    if not items:
        print("No open findings or suggestions.")
        return
    for index, item in enumerate(items, 1):
        print(
            f"[{index}] {item['review_id']}  {item['source_kind']}  "
            f"{item['severity']}  {item['title']}"
        )
        print(f"    {item['description']}")
        if show_evidence and item.get("evidence"):
            print("    evidence:")
            for evidence in item["evidence"]:
                print(f"      {json.dumps(evidence, ensure_ascii=False)}")


def _interactive_review(workspace: Path, show_evidence: bool) -> dict:
    if not sys.stdin.isatty():
        raise JsonStoreError("interactive review requires a terminal; use list-review/approve/reject/suggest in scripts")
    decisions = []
    while True:
        items = review_items(workspace)
        _print_review_items(items, show_evidence)
        if not items:
            break
        answer = input("Select number, (s)uggest, or (q)uit: ").strip().lower()
        if answer == "q":
            break
        if answer == "s":
            title = input("Suggestion title: ").strip()
            description = input("Suggestion description: ").strip()
            priority = input("Priority [medium]: ").strip().lower() or "medium"
            decisions.append(create_suggestion(workspace, title, description, priority))
            continue
        try:
            selected = items[int(answer) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            continue
        print(json.dumps(selected, indent=2, ensure_ascii=False))
        action = input("Decision: (a)pprove, (r)eject, (d)efer, (b)ack: ").strip().lower()
        mapping = {"a": "approved", "r": "rejected", "d": "deferred"}
        if action == "b":
            continue
        if action not in mapping:
            print("Invalid decision.")
            continue
        reason = input("Reason: ").strip()
        confirm = input(f"Confirm {mapping[action]} for {selected['review_id']}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Decision cancelled.")
            continue
        decisions.append(decide_item(workspace, selected["review_id"], mapping[action], reason))
    return {"decisions": decisions}


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    try:
        if args.command == "initialize":
            result = initialize_workspace(workspace)
        elif args.command == "validate":
            result = validate_workspace(workspace)
        elif args.command == "aggregate":
            result = aggregate_summary(workspace)
        elif args.command == "start-inc-run":
            result = start_incremental_run(workspace)
        elif args.command == "current-inc-run":
            result = current_incremental_run(workspace)
            result = {key: value for key, value in result.items() if key != "path"}
            if args.plain:
                print(result["run_id"])
                return 0
        elif args.command == "request-run":
            result = update_run_request(
                workspace,
                args.mode,
                args.workflow_root,
                args.target,
                args.stall_timeout,
                args.max_runtime,
            )
        elif args.command == "list-review":
            result = review_items(workspace)
        elif args.command == "review":
            result = _interactive_review(workspace, args.show_evidence)
        elif args.command in {"approve", "reject", "defer"}:
            decision = {"approve": "approved", "reject": "rejected", "defer": "deferred"}[args.command]
            result = decide_item(workspace, args.id, decision, args.reason)
        elif args.command == "suggest":
            result = create_suggestion(
                workspace,
                args.title,
                args.description,
                args.priority,
            )
        else:
            record = json.loads(args.record_json) if args.record_json else None
            result = mutate_document(
                workspace,
                args.action,
                args.document,
                record=record,
                record_id=args.id,
                expected_revision=args.expected_revision,
            )
    except (JsonStoreError, IncrementalRunError, json.JSONDecodeError, EOFError, KeyboardInterrupt) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
