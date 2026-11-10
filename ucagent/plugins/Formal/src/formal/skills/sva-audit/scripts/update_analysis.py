"""Fill analysis fields in .formal_records.yaml for TT/FA entries.

This script supports searching entries by ID (e.g., FA-001) or by 
property name (e.g., A_CK_ADD_RESULT). It also auto-initializes the 
analysis scaffold if run_results are present but analysis is missing.

Usage:
  python3 update_analysis.py -action show
  python3 update_analysis.py -type fa -id A_CK_ADD_RESULT -resolution RTL_BUG -analysis "..."
"""

import argparse
import json
import os
import sys
from typing import Optional, Union

# Bootstrap: Add UCAgent project root to sys.path
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
    load_records, 
    save_records, 
    auto_scaffold_analysis_entries,
    typed_run_results
)
from lib.models import FormalRecords, AnalysisEntry, AnalysisData
from ucagent.util.log import str_error, str_info, warning

VALID_TT_ROOT_CAUSES = {"ASSUME_TOO_STRONG", "SIGNAL_CONSTANT", "WRAPPER_ERROR", "DESIGN_EXPECTED"}
VALID_TT_ACTIONS = {"FIXED", "ACCEPTED"}
VALID_FA_RESOLUTIONS = {"RTL_BUG", "ENV_FIXED", "ENV_PENDING", "COVER_EXPECTED_FAIL"}


def _ensure_analysis_data(records: FormalRecords, paths: FormalPaths) -> bool:
    """Always reconcile current machine results, including an existing empty object."""
    if not records.run_results:
        raise ValueError("Current machine run_results are required; call RunFormal and Check first.")
    with open(paths.checker, encoding="utf-8") as stream:
        checker_content = stream.read()
    if auto_scaffold_analysis_entries(records, typed_run_results(records), checker_content):
        save_records(paths.records_yaml, records)
    return True


def _find_target(records: FormalRecords, entry_type: str, search_id: str) -> Optional[AnalysisEntry]:
    if not records.analysis:
        return None
    
    entries = records.analysis.tt_entries if entry_type == "tt" else records.analysis.fa_entries
    
    matches = [entry for entry in entries if entry.id == search_id or entry.prop_name == search_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one exact analysis ID or full property name for {search_id}; found {len(matches)}.")
    return matches[0]


def _fill(records: FormalRecords, args):
    if not _ensure_analysis_data(records, runtime_formal_paths()):
        return str_error("Analysis data missing and could not be auto-scaffolded (is TCL executed?)")
    
    target = _find_target(records, args.entry_type, args.id)
    if not target:
        return str_error(f"{args.entry_type.upper()} entry '{args.id}' not found. Check ID or property name.")

    updated = []
    if args.root_cause:
        if args.root_cause.upper() not in VALID_TT_ROOT_CAUSES:
            raise ValueError(f"Invalid root_cause: {args.root_cause}")
        target.root_cause = args.root_cause.upper()
        updated.append("root_cause")
        
    if args.related_assume:
        target.related_assume = args.related_assume
        updated.append("related_assume")
        
    if args.evidence_ref:
        value = json.loads(args.evidence_ref)
        if not isinstance(value, dict):
            raise ValueError("evidence_ref must be a JSON object returned by RunFormal")
        target.evidence_ref = value
        updated.append("evidence_ref")

    if args.analysis:
        target.analysis = args.analysis
        updated.append("analysis")
        
    if args.action_val:
        if args.action_val.upper() not in VALID_TT_ACTIONS:
            raise ValueError(f"Invalid action: {args.action_val}")
        target.action = args.action_val.upper()
        updated.append("action")
        
    if args.action_detail:
        target.action_detail = args.action_detail
        updated.append("action_detail")
        
    if args.resolution:
        if args.resolution.upper() not in VALID_FA_RESOLUTIONS:
            raise ValueError(f"Invalid resolution: {args.resolution}")
        target.resolution = args.resolution.upper()
        updated.append("resolution")

    if not updated:
        raise ValueError("No fields provided to update")
    return str_info(f"✅ Updated {target.id} ({target.prop_name}): {', '.join(updated)}")


def _show(records: FormalRecords, args):
    _ensure_analysis_data(records, runtime_formal_paths())
    
    if records.analysis is None:
        raise ValueError("No current analysis queue; call Check first.")
    
    tt = records.analysis.tt_entries
    fa = records.analysis.fa_entries
    lines = ["📋 Current analysis:"]
    if tt:
        lines.append(f"\n  TRIVIALLY_TRUE ({len(tt)}):")
        for e in tt:
            filled = "✅" if e.root_cause != "[LLM-TODO]" and e.root_cause else "❌"
            lines.append(f"    {filled} {e.id}: {e.prop_name} → {e.root_cause or '?'}")
    if fa:
        lines.append(f"\n  FALSE ({len(fa)}):")
        for e in fa:
            filled = "✅" if e.resolution != "[LLM-TODO]" and e.resolution else "❌"
            lines.append(f"    {filled} {e.id}: {e.prop_name} → {e.resolution or '?'}")
            
    if not tt and not fa:
        lines.append("  (No abnormal properties detected)")
        
    return str_info("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Update formal environment analysis")
    parser.add_argument("-action", choices=["fill", "show"], default="fill")
    parser.add_argument("-type", choices=["tt", "fa"], default="tt", dest="entry_type")
    parser.add_argument("-id", default="", help="Entry ID (e.g. FA-001) or Property Name")
    parser.add_argument("-root_cause", default="", help="TT root cause")
    parser.add_argument("-related_assume", default="", help="Related assume")
    parser.add_argument("-evidence_ref", default="", help="Current RunFormal evidence_ref as a JSON object")
    parser.add_argument("-analysis", default="", help="Analysis process details")
    parser.add_argument("-action_val", default="", help="TT action: FIXED/ACCEPTED")
    parser.add_argument("-action_detail", default="", help="Action detail")
    parser.add_argument("-resolution", default="", help="FA resolution: RTL_BUG/ENV_FIXED/etc.")
    args = parser.parse_args()

    paths = runtime_formal_paths()
    if paths.dut == "N/A":
        raise ValueError("Cannot determine DUT from the runtime snapshot; restart UCAgent.")

    records = load_records(paths.records_yaml)
    if not records:
        raise ValueError(f"Records file not found at {paths.records_yaml}")

    if args.action == "show":
        print(_show(records, args))
        return

    if not args.id:
        raise ValueError("Missing -id (exact entry ID or full property name required)")

    result = _fill(records, args)
    print(result)
    save_records(paths.records_yaml, records)


if __name__ == "__main__":
    main()
