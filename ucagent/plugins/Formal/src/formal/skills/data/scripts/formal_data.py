"""Run structured Formal data actions through the existing Skill script runner."""

import argparse
import json
from pathlib import Path
import sys

from formal.data import FormalDataStore
from formal.runtime import FormalDataRuntimeHook
from ucagent.util.config import Config, load_runtime_config
from ucagent.util.file_policy import is_file_writeable, normalize_relative_path


class Arguments(argparse.ArgumentParser):
    """Report invalid command arguments using the same structured error contract."""

    def error(self, message):
        """Raise instead of printing an unstructured argparse failure."""
        raise ValueError(message)


def main() -> int:
    """Resolve trusted runtime context and dispatch one canonical data-store action."""
    try:
        parser = Arguments(description=__doc__)
        commands = parser.add_subparsers(dest="action", required=True, parser_class=Arguments)
        inspect = commands.add_parser("inspect")
        inspect.add_argument("section", choices=("overview", "planning", "basic_info", "spec", "analysis", "bugs", "summary"))
        prepare = commands.add_parser("prepare")
        prepare.add_argument("section", choices=("analysis", "bugs"))
        for operation in (inspect, prepare):
            operation.add_argument("--offset", type=int, default=0)
            operation.add_argument("--limit", type=int, default=20)
        update = commands.add_parser("update")
        update.add_argument("--request-file", required=True)
        args = parser.parse_args()
        workspace = Path.cwd().resolve()
        snapshot = load_runtime_config(str(workspace))
        FormalDataRuntimeHook().validate_runtime_snapshot(snapshot)
        output = normalize_relative_path(snapshot["OUT"])
        dut = normalize_relative_path(snapshot["DUT"])
        if len(Path(dut).parts) != 1:
            raise ValueError("Runtime DUT must be one workspace directory; restart UCAgent with a valid task")
        policy = snapshot["formal_data"]
        cfg = Config({"runtime_options": snapshot["runtime_options"], "output": output,
                      "write_dirs": policy["write_dirs"], "un_write_dirs": policy["un_write_dirs"]})
        store = FormalDataStore(str(workspace), output, dut, cfg=cfg, **policy)
        if args.action == "inspect":
            result = store.inspect(args.section, args.offset, args.limit)
        elif args.action == "prepare":
            result = store.prepare(args.section, args.offset, args.limit)
        else:
            relative = normalize_relative_path(args.request_file)
            relative_path = Path(relative)
            if not relative_path.is_relative_to(Path(output)):
                raise ValueError("The update request file must be inside the current OUT directory")
            allowed, reason = is_file_writeable(relative, policy["un_write_dirs"], policy["write_dirs"])
            if not allowed:
                raise ValueError(reason)
            request_path = workspace / relative
            if not request_path.resolve().is_relative_to(workspace):
                raise ValueError("The update request file must remain inside the workspace")
            if any(path.is_symlink() for path in (request_path, *request_path.parents) if path.is_relative_to(workspace)):
                raise ValueError("The update request file must not contain symlink components")
            if not request_path.is_file() or request_path.stat().st_size > 270000:
                raise ValueError("The update request must be an existing regular JSON file of at most 270000 bytes")
            payload = request_path.read_bytes()
            if len(payload) > 270000:
                raise ValueError("The update request exceeds 270000 bytes")
            request = json.loads(payload)
            required = {"section", "expected_sha256"}
            if not isinstance(request, dict) or not required <= set(request) or set(request) - required not in ({"data"}, {"bodies"}):
                raise ValueError("Update JSON must contain exactly section, expected_sha256, and one of data or bodies")
            result = store.update(request["section"], request.get("data"), request.get("bodies"), request["expected_sha256"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"error", "conflict"} else 2
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "error", "error_code": "formal_data_skill_invalid", "error": str(exc)[:2500],
                          "next_action": "Correct the named request or task field. For missing or stale runtime context, restart UCAgent to regenerate the runtime snapshot, then retry this Skill script."}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
