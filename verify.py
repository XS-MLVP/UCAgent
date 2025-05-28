#!/usr/bin/env python3

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.join(current_dir))


import argparse
from vagent.verify_agent import VerifyAgent


def get_args():
    def get_override_dict(override_str):
        if override_str is None:
            return {}
        overrides = {}
        for item in override_str.split(","):
            key, value = item.split("=")
            value = value.strip()
            if value.startswith('"') or value.endswith("'"):
                assert value.endswith('"') or value.endswith("'"), "Value must be enclosed in quotes"
                value = value[1:-1]  # Remove quotes
            else:
                value = eval(value)  # Evaluate the value to convert it to the appropriate type
            overrides[key.strip()] = value
        return overrides
    parser = argparse.ArgumentParser(description="Verify Agent")
    parser.add_argument("workspace", type=str, default=os.getcwd(), help="Workspace directory to run the agent in")
    parser.add_argument("--config", type=str, default=None, help="Path to the configuration file")
    parser.add_argument("--override", type=get_override_dict, default=None, help="Override configuration settings in the format A.B.C=value")
    return parser.parse_args()


def run():
    args = get_args()
    agent = VerifyAgent(
        workspace=args.workspace,
        config_file=args.config,
        cfg_override=args.override,
    )
    agent.run()


if __name__ == "__main__":
    run()
