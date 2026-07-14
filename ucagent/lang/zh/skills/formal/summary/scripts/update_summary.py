"""Update the summary section in .formal_records.yaml."""

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
    parser = argparse.ArgumentParser(description="Update summary section in .formal_records.yaml")
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
    if records.summary is None:
        records.summary = {}

    if args.action == "show":
        print(str_info(yaml.safe_dump(records.summary, allow_unicode=True, sort_keys=False) if records.summary else "{}"))
        return

    if not args.path:
        print(str_error("Missing -path"))
        return

    value = _parse_value(args.value)
    try:
        if args.action == "set":
            set_nested_value(records.summary, args.path, value)
        else:
            append_nested_value(records.summary, args.path, value)
    except Exception as exc:
        print(str_error(str(exc)))
        return

    save_records(paths.records_yaml, records)
    print(str_info(f"Updated summary.{args.path}"))


if __name__ == "__main__":
    main()
