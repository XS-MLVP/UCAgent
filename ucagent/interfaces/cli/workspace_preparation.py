"""Parse the workspace preparation command used by Make and operators."""
import argparse
import json


def parse_preparation_options(argv):
    """Return a plain validated argument mapping for the application preparation service."""
    parser = argparse.ArgumentParser(prog="ucagent prepare-workspace", description=__doc__)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--dut", required=True)
    parser.add_argument("--options", type=json.loads, default={})
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    if not isinstance(args.options, dict) or args.timeout < 1:
        parser.error("--options must be a JSON object and --timeout must be positive")
    return vars(args)
