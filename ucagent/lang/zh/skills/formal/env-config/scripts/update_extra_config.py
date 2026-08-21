"""Update Stage-5 environment config views in .formal_records.yaml."""

import argparse
import os
import sys
import yaml

_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records, set_nested_value, append_nested_value
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords
from ucagent.util.log import str_error, str_info


def _parse_value(raw: str):
    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def main():
    parser = argparse.ArgumentParser(description="Update Stage-5 env config in .formal_records.yaml")
    parser.add_argument("-action", choices=["set", "append", "show"], default="show")
    parser.add_argument("-path", default="")
    parser.add_argument("-value", default="")
    args = parser.parse_args()

    paths = FormalPaths()
    if paths.dut == "N/A":
        print(str_error("Cannot determine DUT. Set DUT env var or ensure .formal_records.yaml exists."))
        return

    records = load_records(paths.records_yaml)
    if not records:
        records = FormalRecords(dut=paths.dut)
    if args.action == "show":
        print(str_info(yaml.safe_dump(_build_env_view(records), allow_unicode=True, sort_keys=False)))
        return

    if not args.path:
        print(str_error("Missing -path"))
        return

    value = _parse_value(args.value)
    try:
        target_root, root_name, sub_path = _resolve_target(records, args.path)
        if args.action == "set":
            if root_name == "extra_config":
                set_nested_value(target_root.extra_config, sub_path, value)
            elif sub_path:
                set_nested_value(target_root[root_name], sub_path, value)
            else:
                target_root[root_name] = value
        else:
            if root_name == "extra_config":
                append_nested_value(target_root.extra_config, sub_path, value)
            elif sub_path:
                append_nested_value(target_root[root_name], sub_path, value)
            else:
                raise ValueError("append requires a nested list path")
    except Exception as exc:
        print(str_error(str(exc)))
        return

    save_records(paths.records_yaml, records)
    print(str_info(f"Updated {args.path}"))


if __name__ == "__main__":
    main()
def _build_env_view(records):
    basic_info = records.basic_info or {}
    return {
        "clock_reset": basic_info.get("clock_reset", {}) if isinstance(basic_info, dict) else {},
        "tcl": ((records.extra_config or {}).get("tcl", {})),
    }


def _resolve_target(records, path: str):
    if path == "clock_reset" or path.startswith("clock_reset."):
        if records.basic_info is None:
            records.basic_info = {}
        if not isinstance(records.basic_info, dict):
            raise ValueError("basic_info is not a mapping")
        if "clock_reset" not in records.basic_info or not isinstance(records.basic_info.get("clock_reset"), dict):
            records.basic_info["clock_reset"] = {}
        sub_path = path[len("clock_reset."): ] if path.startswith("clock_reset.") else ""
        return records.basic_info, "clock_reset", sub_path

    if records.extra_config is None:
        records.extra_config = {}
    if not isinstance(records.extra_config, dict):
        raise ValueError("extra_config is not a mapping")
    sub_path = path
    return records, "extra_config", sub_path
