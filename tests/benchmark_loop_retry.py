"""Compare loop attempts and simulated backoff for an unchanged rejected model request."""

import argparse
import ast
import json
from pathlib import Path
from types import MethodType

import pytest
import subprocess

import ucagent.verify_agent as agent_module
import ucagent.verify_pdb as pdb_module
from test_backend_loop_retry import _HTTPError, retry_probe


def main() -> None:
    """Run old and current work/loop methods offline with counted, rather than real, sleeps."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = {}
    for key, path, cls_name, method_name, namespace in [
        ("work", "ucagent/verify_agent.py", "VerifyAgent", "do_work", vars(agent_module)),
        ("loop", "ucagent/verify_pdb.py", "VerifyPDB", "do_loop", vars(pdb_module)),
    ]:
        source = subprocess.check_output(["git", "show", f"{args.base_ref}:{path}"], text=True)
        cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == cls_name)
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
        scope = dict(namespace)
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<baseline>", "exec"), scope)
        baseline[key] = scope[method_name]
    cases = []
    for delay in (5, 10):
        for version in ("before", "after"):
            patch = pytest.MonkeyPatch()
            try:
                probe = retry_probe.__wrapped__(patch)
                probe.controller.retry_delay_start = delay
                probe.controller.retry_delay_end = delay
                calls = []

                def rejected_request(*unused):
                    """Count submissions of the same invalid request without contacting a provider."""
                    calls.append(400)
                    raise _HTTPError(400)

                probe.agent.do_work_values = rejected_request
                if version == "before":
                    probe.agent.do_work = MethodType(baseline["work"], probe.agent)
                    baseline["loop"].__globals__.update({name: probe.messages.append
                                                       for name in ("echo_y", "echo_r", "echo_g")})
                    baseline["loop"](probe.controller, "")
                else:
                    probe.controller.do_loop("")
                cases.append({"version": version, "delay_seconds": delay,
                              "mock_request_attempts": len(calls), "repeated_attempts": len(calls) - 1,
                              "simulated_wait_seconds": sum(probe.waits)})
            finally:
                patch.undo()
    result = {"baseline_ref": args.base_ref, "max_loop_retry": 10, "cases": cases,
              "limits": "Offline failures and counted sleeps only; no measured network latency or end-to-end workflow speedup."}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
