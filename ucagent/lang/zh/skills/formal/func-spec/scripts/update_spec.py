# -*- coding: utf-8 -*-
"""CRUD operations on the spec field of .formal_records.yaml.

Allows the LLM to add/update/delete FG/FC/CK entries via RunSkillScript
instead of directly editing JSON.

Usage:
  python3 update_spec.py -action add_fg -id FG-API -name "验证环境约束"
  python3 update_spec.py -action add_fc -fg FG-API -id FC-API-INPUT -desc "输入约束"
  python3 update_spec.py -action add_ck -fc FC-API-INPUT -id CK-API-NO-X -style Assume -desc "输入不能X态"
  python3 update_spec.py -action update -id CK-API-NO-X -style Comb -desc "更新描述"
  python3 update_spec.py -action delete -id CK-API-NO-X
  python3 update_spec.py -action set_param -id WIDTH -value 64
  python3 update_spec.py -action add_signal -desc "logic [7:0] my_sig"
  python3 update_spec.py -action show
"""

import argparse
import json
import os
import sys
from typing import Optional

_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records
from ucagent.lang.zh.skills.formal.lib.models import FormalRecords, FormalSpec, FunctionGroup, FunctionPoint, CheckPoint
from ucagent.util.log import str_error, str_info


VALID_STYLES = {"Assume", "Comb", "Seq", "Cover"}


def _find_fg(spec: FormalSpec, fg_id: str) -> Optional[FunctionGroup]:
    for fg in spec.function_groups:
        if fg.id == fg_id:
            return fg
    return None


def _find_fc_in_fg(fg: FunctionGroup, fc_id: str) -> Optional[FunctionPoint]:
    for fc in fg.functions:
        if fc.id == fc_id:
            return fc
    return None


def _find_ck_in_fc(fc: FunctionPoint, ck_id: str) -> Optional[CheckPoint]:
    for ck in fc.check_points:
        if ck.id == ck_id:
            return ck
    return None


def _action_add_fg(records: FormalRecords, args):
    if not args.id:
        return str_error("Missing -id for add_fg")
    if not records.spec: records.spec = FormalSpec()
    if _find_fg(records.spec, args.id):
        return str_error(f"FG '{args.id}' already exists")
    records.spec.function_groups.append(FunctionGroup(
        id=args.id,
        name=args.name or args.id,
    ))
    return str_info(f"✅ Added FG: {args.id}")


def _action_add_fc(records: FormalRecords, args):
    if not args.fg:
        return str_error("Missing -fg for add_fc")
    if not args.id:
        return str_error("Missing -id for add_fc")
    if not records.spec: return str_error("Spec not initialized. Add FG first.")
    
    fg = _find_fg(records.spec, args.fg)
    if not fg:
        return str_error(f"FG '{args.fg}' not found")
    if _find_fc_in_fg(fg, args.id):
        return str_error(f"FC '{args.id}' already exists in {args.fg}")
    
    fg.functions.append(FunctionPoint(
        id=args.id,
        description=args.desc or "",
    ))
    return str_info(f"✅ Added FC: {args.id} → {args.fg}")


def _action_add_ck(records: FormalRecords, args):
    if not args.fc:
        return str_error("Missing -fc for add_ck")
    if not args.id:
        return str_error("Missing -id for add_ck")
    if not args.style:
        return str_error("Missing -style for add_ck")
    if args.style not in VALID_STYLES:
        return str_error(f"Invalid style '{args.style}'. Must be one of: {', '.join(sorted(VALID_STYLES))}")
    if not args.id.startswith("CK-"):
        return str_error(f"CK id must start with 'CK-', got '{args.id}'")
    if not records.spec: return str_error("Spec not initialized. Add FG and FC first.")

    for fg in records.spec.function_groups:
        fc = _find_fc_in_fg(fg, args.fc)
        if fc:
            if _find_ck_in_fc(fc, args.id):
                return str_error(f"CK '{args.id}' already exists in {args.fc}")
            fc.check_points.append(CheckPoint(
                id=args.id,
                style=args.style,
                description=args.desc or "",
            ))
            return str_info(f"✅ Added CK: {args.id} (Style: {args.style}) → {args.fc}")
    return str_error(f"FC '{args.fc}' not found in any FG")


def _action_update(records: FormalRecords, args):
    if not args.id:
        return str_error("Missing -id for update")
    if not records.spec: return str_error("Spec empty.")
    
    target_id = args.id
    # Search all levels
    for fg in records.spec.function_groups:
        if fg.id == target_id:
            if args.name: fg.name = args.name
            return str_info(f"✅ Updated FG: {target_id}")
        for fc in fg.functions:
            if fc.id == target_id:
                if args.desc: fc.description = args.desc
                return str_info(f"✅ Updated FC: {target_id}")
            for ck in fc.check_points:
                if ck.id == target_id:
                    if args.style:
                        if args.style not in VALID_STYLES:
                            return str_error(f"Invalid style '{args.style}'")
                        ck.style = args.style
                    if args.desc:
                        ck.description = args.desc
                    return str_info(f"✅ Updated CK: {target_id}")
    return str_error(f"ID '{target_id}' not found")


def _action_delete(records: FormalRecords, args):
    if not args.id:
        return str_error("Missing -id for delete")
    if not records.spec: return str_error("Spec empty.")
    
    target_id = args.id
    # Delete FG
    for i, fg in enumerate(records.spec.function_groups):
        if fg.id == target_id:
            records.spec.function_groups.pop(i)
            return str_info(f"✅ Deleted FG: {target_id}")
        # Delete FC
        for j, fc in enumerate(fg.functions):
            if fc.id == target_id:
                fg.functions.pop(j)
                return str_info(f"✅ Deleted FC: {target_id} from {fg.id}")
            # Delete CK
            for k, ck in enumerate(fc.check_points):
                if ck.id == target_id:
                    fc.check_points.pop(k)
                    return str_info(f"✅ Deleted CK: {target_id} from {fc.id}")
    return str_error(f"ID '{target_id}' not found")


def _action_set_param(records: FormalRecords, args):
    if not args.id:
        return str_error("Missing -id (parameter name) for set_param")
    if not args.value:
        return str_error("Missing -value for set_param")
    
    if not records.spec: records.spec = FormalSpec()
    if records.spec.parameters is None:
        records.spec.parameters = {}
    
    # Try to convert to int if possible, else keep as string
    val = args.value
    try:
        if val.isdigit():
            val = int(val)
        elif val.startswith("0x"):
            val = int(val, 16)
    except:
        pass
        
    records.spec.parameters[args.id] = val
    return str_info(f"✅ Set parameter: {args.id} = {val}")


def _action_delete_param(records: FormalRecords, args):
    if not args.id:
        return str_error("Missing -id (parameter name) for delete_param")
    if not records.spec or not records.spec.parameters:
        return str_error("No parameters found.")
    if args.id in records.spec.parameters:
        del records.spec.parameters[args.id]
        return str_info(f"✅ Deleted parameter: {args.id}")
    return str_error(f"Parameter '{args.id}' not found.")


def _action_add_signal(records: FormalRecords, args):
    if not args.desc:
        return str_error("Missing -desc (signal declaration, e.g. 'logic [7:0] data') for add_signal")
    
    if not records.spec: records.spec = FormalSpec()
    if records.spec.whitebox_signals is None:
        records.spec.whitebox_signals = []
    
    records.spec.whitebox_signals.append(args.desc.strip())
    return str_info(f"✅ Added whitebox signal: {args.desc}")


def _action_delete_signal(records: FormalRecords, args):
    if not args.desc:
        return str_error("Missing -desc (exact signal string) for delete_signal")
    if not records.spec or not records.spec.whitebox_signals:
        return str_error("No whitebox signals found.")
    
    if args.desc in records.spec.whitebox_signals:
        records.spec.whitebox_signals.remove(args.desc)
        return str_info(f"✅ Deleted whitebox signal: {args.desc}")
    return str_error(f"Signal '{args.desc}' not found.")


def _action_show(records: FormalRecords, args):
    if not records or not records.spec:
        return str_info("📋 Spec is empty.")
    
    lines = []
    if records.spec.parameters:
        lines.append("📋 Parameters:")
        for k, v in records.spec.parameters.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    if records.spec.whitebox_signals:
        lines.append("📋 Whitebox Signals:")
        for s in records.spec.whitebox_signals:
            lines.append(f"  {s}")
        lines.append("")

    lines.append("📋 Spec structure:")
    for fg in records.spec.function_groups:
        lines.append(f"  {fg.id}: {fg.name}")
        for fc in fg.functions:
            lines.append(f"    {fc.id}: {fc.description}")
            for ck in fc.check_points:
                lines.append(f"      {ck.id} (Style: {ck.style}) {ck.description}")
    
    fg_count = len(records.spec.function_groups)
    fc_count = sum(len(fg.functions) for fg in records.spec.function_groups)
    ck_count = sum(len(fc.check_points) for fg in records.spec.function_groups for fc in fg.functions)
    lines.append(f"\n  Total: {fg_count} FG, {fc_count} FC, {ck_count} CK")
    return str_info("\n".join(lines))


ACTIONS = {
    "add_fg": _action_add_fg,
    "add_fc": _action_add_fc,
    "add_ck": _action_add_ck,
    "update": _action_update,
    "delete": _action_delete,
    "show": _action_show,
    "set_param": _action_set_param,
    "delete_param": _action_delete_param,
    "add_signal": _action_add_signal,
    "delete_signal": _action_delete_signal,
}


def main():
    parser = argparse.ArgumentParser(description="CRUD operations on spec in .formal_records.yaml")
    parser.add_argument("-action", choices=list(ACTIONS.keys()), required=True)
    parser.add_argument("-id", default="")
    parser.add_argument("-fg", default="", help="Parent FG id (for add_fc)")
    parser.add_argument("-fc", default="", help="Parent FC id (for add_ck)")
    parser.add_argument("-name", default="", help="Name (for FG)")
    parser.add_argument("-desc", default="", help="Description (for FC/CK/Signal)")
    parser.add_argument("-style", default="", help="Style: Assume/Comb/Seq/Cover (for CK)")
    parser.add_argument("-value", default="", help="Value (for set_param)")
    args = parser.parse_args()

    paths = FormalPaths()
    if paths.dut == "N/A":
        print(str_error("Cannot determine DUT. Set DUT env var or ensure .formal_records.yaml exists."))
        return

    records = load_records(paths.records_yaml)
    if not records:
        records = FormalRecords(dut=paths.dut, spec=FormalSpec())
    
    result = ACTIONS[args.action](records, args)
    print(result)

    if args.action != "show":
        save_records(paths.records_yaml, records)


if __name__ == "__main__":
    main()
