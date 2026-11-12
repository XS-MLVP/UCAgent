"""Incrementally update formal environment analysis.

Parses avis.log and appends new analysis entries into .formal_records.yaml
for the LLM to fill via update_analysis.py. Note: initial scaffolding is 
now handled automatically by the Checker.
"""

import argparse
import os
import sys

# Bootstrap: Add UCAgent project root to sys.path so we can import 'ucagent'.
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

_skill_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _skill_root not in sys.path:
    sys.path.insert(0, _skill_root)

from lib.formal_paths import FormalPaths
from lib.formal_tools import runtime_formal_paths
from lib.formal_tools import (
    typed_run_results,
    extract_property_code,
    load_records,
    save_records,
    auto_scaffold_analysis_entries,
)
from ucagent.util.log import str_error, str_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Update formal environment analysis")
    parser.add_argument("-mode", choices=["update"], default="update", help="Update mode (incremental)")
    args = parser.parse_args()

    paths = runtime_formal_paths()
    log_path = paths.log
    checker_path = paths.checker

    if not os.path.exists(log_path):
        raise ValueError(f"Current log file not found at {log_path}; call RunFormal and Check first.")

    records = load_records(paths.records_yaml)
    if not records:
        raise ValueError(f"Records file not found at {paths.records_yaml}")

    log_result = typed_run_results(records)
    
    checker_content = ""
    if os.path.exists(checker_path):
        with open(checker_path, "r", encoding="utf-8", errors="ignore") as f:
            checker_content = f.read()

    if auto_scaffold_analysis_entries(records, log_result, checker_content):
        save_records(paths.records_yaml, records)
        print(str_info(f"✅ Analysis entries incrementally updated in {paths.records_yaml}"))
    else:
        print(str_info("ℹ️ No new abnormal properties found. Analysis is up-to-date."))


if __name__ == "__main__":
    main()
