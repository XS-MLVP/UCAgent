"""Fill bug detail fields in .formal_records.yaml.

This script supports auto-scaffolding if bugs are missing but RTL_BUG 
resolutions are present in the analysis section.

Usage:
  python3 update_bug.py -id BG-FORMAL-001 -description "..."
  python3 update_bug.py -action show
"""

import argparse
import os
import sys
from typing import Optional

_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records, auto_scaffold_bug_entries
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords, BugEntry
from ucagent.util.log import str_error, str_info

VALID_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}
VALID_CONFIDENCES = {"HIGH", "MEDIUM", "LOW"}

# All fillable fields and their arg names
_FIELDS = [
    "fg_id", "fc_id", "rtl_file", "rtl_line",
    "description", "root_cause", "trigger",
    "expected", "actual", "fix", "severity", "confidence",
]


def _ensure_bug_data(records: FormalRecords, paths: FormalPaths) -> bool:
    """Auto-scaffold bug entries if missing but RTL_BUG present in analysis."""
    if records.bugs:
        return True
    
    print(str_info("🏗️ Bug entries missing, attempting auto-scaffolding from analysis..."))
    if auto_scaffold_bug_entries(records):
        save_records(paths.records_yaml, records)
        return True
    return False


def _fill(records: FormalRecords, args):
    if not _ensure_bug_data(records, FormalPaths()):
        return str_error("No bug entries found and none could be scaffolded (check analysis resolutions).")
    
    target = next((b for b in records.bugs if b.id == args.id or b.property == args.id), None)
    if not target:
        return str_error(f"Bug '{args.id}' not found")

    updated = []
    for field in _FIELDS:
        val = getattr(args, field, None)
        if val is not None and val != "" and val != 0:
            if field == "severity" and val.upper() not in VALID_SEVERITIES:
                return str_error(f"Invalid severity '{val}'. Valid: {VALID_SEVERITIES}")
            if field == "confidence" and val.upper() not in VALID_CONFIDENCES:
                return str_error(f"Invalid confidence '{val}'. Valid: {VALID_CONFIDENCES}")
            if field in ("severity", "confidence"):
                val = val.upper()
            
            setattr(target, field, val)
            updated.append(field)

    if not updated:
        return str_error("No fields provided to update")
    return str_info(f"✅ Updated {target.id} ({target.property}): {', '.join(updated)}")


def _show(records: FormalRecords, args):
    _ensure_bug_data(records, FormalPaths())
    bugs = records.bugs or []
    lines = [f"📋 Bug entries ({len(bugs)}):"]
    for b in bugs:
        b_dict = b.model_dump()
        todo_count = sum(1 for f in _FIELDS if str(b_dict.get(f, "")).strip() in ("", "[LLM-TODO]", "0"))
        status = "✅" if todo_count == 0 else f"❌ ({todo_count} unfilled)"
        lines.append(f"  {status} {b.id}: {b.property} → {b.description}")
    return str_info("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Fill bug fields in .formal_records.yaml")
    parser.add_argument("-action", choices=["fill", "show"], default="fill")
    parser.add_argument("-id", default="", help="Bug ID (e.g. BG-FORMAL-001) or Property Name")
    parser.add_argument("-fg_id", default="")
    parser.add_argument("-fc_id", default="")
    parser.add_argument("-rtl_file", default="")
    parser.add_argument("-rtl_line", type=int, default=0)
    parser.add_argument("-description", default="")
    parser.add_argument("-root_cause", default="")
    parser.add_argument("-trigger", default="")
    parser.add_argument("-expected", default="")
    parser.add_argument("-actual", default="")
    parser.add_argument("-fix", default="")
    parser.add_argument("-severity", default="", help="HIGH/MEDIUM/LOW")
    parser.add_argument("-confidence", default="", help="HIGH/MEDIUM/LOW")
    args = parser.parse_args()

    paths = FormalPaths()
    if paths.dut == "N/A":
        print(str_error("Cannot determine DUT. Set DUT env var or ensure .formal_records.yaml exists."))
        return

    records = load_records(paths.records_yaml)
    if not records:
        print(str_error(f"Records not found at {paths.records_yaml}"))
        return

    if args.action == "show":
        print(_show(records, args))
        return

    if not args.id:
        print(str_error("Missing -id (ID or Property Name required)"))
        return

    result = _fill(records, args)
    print(result)
    save_records(paths.records_yaml, records)


if __name__ == "__main__":
    main()
