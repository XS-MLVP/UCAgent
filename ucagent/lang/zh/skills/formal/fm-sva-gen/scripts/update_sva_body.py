# -*- coding: utf-8 -*-
"""Skill script for updating SVA property body in .formal_records.yaml."""

import os
import sys
import argparse

# Setup path for internal imports
_root = os.path.dirname(os.path.abspath(__file__))
while _root != os.path.dirname(_root) and not os.path.exists(os.path.join(_root, "ucagent", "__init__.py")):
    _root = os.path.dirname(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)

from ucagent.lang.zh.skills.formal.lib.formal_paths import FormalPaths
from ucagent.lang.zh.skills.formal.lib.formal_tools import load_records, save_records
from ucagent.util.log import str_error, str_info

def update_sva_body(ck_id: str, body: str) -> bool:
    paths = FormalPaths()
    records = load_records(paths.records_yaml)
    if not records or not records.spec:
        print(str_error(f"Records not found at {paths.records_yaml}. Run func-spec first."))
        return False

    found = False
    for fg in records.spec.function_groups:
        for fc in fg.functions:
            for ck in fc.check_points:
                if ck.id == ck_id:
                    ck.sva_body = body.strip()
                    found = True
                    break
            if found: break
        if found: break

    if found:
        save_records(paths.records_yaml, records)
        print(str_info(f"✅ Successfully updated SVA body for {ck_id} in YAML."))
        return True
    else:
        print(str_error(f"❌ Checkpoint ID '{ck_id}' not found in the records."))
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update SVA body for a checkpoint in YAML.")
    parser.add_argument("ck_id", help="The Checkpoint ID (e.g., CK-ADD-CORE-EQUATION)")
    parser.add_argument("body", help="The SVA code body string")
    args = parser.parse_args()
    update_sva_body(args.ck_id, args.body)
