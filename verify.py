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
    parser.add_argument("dut", type=str, help="a sub-directory name in worspace, e.g., DualPort, Adder, ALU")
    parser.add_argument("--config", type=str, default=None, help="Path to the configuration file")
    parser.add_argument("--template-dir", type=str, default=None, help="Path to the template directory")
    parser.add_argument("--template-overwrite", action="store_true", default=False, help="Overwrite existing templates in the workspace")
    parser.add_argument("--output", type=str, default="unity_test", help="Path to the configuration file")
    parser.add_argument("--override", type=get_override_dict, default=None, help="Override configuration settings in the format A.B.C=value")
    parser.add_argument("--stream-output", "-s", action="store_true", default=False, help="Stream output to the console")
    parser.add_argument("--human", "-hm", action="store_true", default=False, help="Enable human input mode in the beginning of the run")
    parser.add_argument("--seed", type=int, default=None, help="Seed for random number generation, if applicable")
    return parser.parse_args()


def run():
    args = get_args()
    agent = VerifyAgent(
        workspace=args.workspace,
        dut_name=args.dut,
        output=args.output,
        config_file=args.config,
        cfg_override=args.override,
        tmp_overwrite=args.template_overwrite,
        template_dir=args.template_dir,
        stream_output = args.stream_output,
        seed=args.seed,
    )
    if args.human:
        agent.set_human_input(True)
    agent.run()


if __name__ == "__main__":
    run()
