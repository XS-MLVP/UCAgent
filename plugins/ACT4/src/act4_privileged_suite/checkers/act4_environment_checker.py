"""Gate early ACT4 environment preparation with real, reusable installation evidence."""

import json
import os
from pathlib import Path
import signal

import yaml

from ucagent.checkers.base import Checker

from ..environment import HOST_PROBES, prepare, prepared_environment, read_plan, state_key
from ..xiangshan_bundle import execute, safe_path, sha256, write_json


class ACT4EnvironmentChecker(Checker):
    """Prepare workflow tools before asset analysis without reading existing test content."""

    accepted_stage_args = ("action", "timeout")

    def __init__(self, environment_dir: str, cfg=None, **kwargs):
        """Store the output location; defer all probes and installation to explicit Check actions."""
        super().__init__()
        if kwargs:
            raise ValueError(f"Unknown environment arguments: {sorted(kwargs)}")
        self.environment_dir = environment_dir
        self._active_log = None
        self._cancelled = False

    def _track(self, process, timeout, log):
        """Expose the active process and honor cancellation before starting another command."""
        self.set_check_process(process, timeout)
        self._active_log = log
        if self._cancelled:
            raise InterruptedError("Preparation cancelled; retry explicitly when ready")

    def kill(self):
        """Stop the current installer and its children, retaining its log for diagnosis."""
        self._cancelled = True
        if self._process is not None and self._process.poll() is None:
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return "Environment preparation cancelled; inspect the active log before retrying"

    def check_std(self, lines):
        """Return a bounded active installation log tail to StdCheck."""
        if self._active_log is None or not self._active_log.is_file():
            return "No environment command is running"
        with self._active_log.open("rb") as stream:
            stream.seek(max(0, self._active_log.stat().st_size - 16384))
            return "\n".join(stream.read().decode(errors="replace").splitlines()[-max(1, min(int(lines), 100)):])

    def do_check(self, is_complete=False, action="", timeout=1800, **kwargs):
        """Accept only measured preparation, preserving unavailable capabilities as explicit limitations."""
        try:
            if kwargs or action not in {"", "probe", "prepare"} or (is_complete and action):
                raise ValueError("Use Check with action probe or prepare; Complete validates without action")
            if type(timeout) is not int or not 1 <= timeout <= 14400:
                raise ValueError("timeout must be an integer in 1..14400 seconds")
            directory = safe_path(Path(self.workspace).resolve(), self.environment_dir)
            directory.mkdir(parents=True, exist_ok=True)
            if self.stage_manager is None:
                raise ValueError("Run preparation from a workflow with an active stage manager")
            self._cancelled = False
            if action == "probe" or (action == "prepare" and not self.smanager_get_value(state_key(directory) + ":host", None)):
                results = {}
                for name, command in HOST_PROBES.items():
                    log = directory / f"host-{name}.log"
                    result = execute(command, directory, log, 10, self._track)
                    results[name] = {**result, "log": log.name, "sha256": sha256(log)}
                write_json(directory / "host.json", results)
                self.smanager_set_value(state_key(directory) + ":host", sha256(directory / "host.json"))
                if action == "probe":
                    return False, {"error_code": "act4_environment_plan_required", "error": "Host probes recorded; workflow-specific version preparation remains",
                               "artifact": str(directory / "host.json"), "next_action": "Read host.json and dependency manifests/CI installation instructions only; create plan.yaml using Guide_Doc/ACT4_Environment_Guide.md, then Check(stage_args={\"action\":\"prepare\"})."}
            if action == "prepare":
                if sha256(directory / "host.json") != self.smanager_get_value(state_key(directory) + ":host", None):
                    raise ValueError('Host probes changed; Check(stage_args={"action":"probe"}) before preparation')
                plan = read_plan(directory)
                host = json.loads((directory / "host.json").read_text(encoding="utf-8"))
                for result in host.values():
                    if sha256(safe_path(directory, result["log"])) != result["sha256"]:
                        raise ValueError(f"Host probe log changed: {result['log']}; probe again before installation")
                self.smanager_set_value(state_key(directory), None)
                receipt = prepare(directory, plan, timeout, self._track)
                self.smanager_set_value(state_key(directory), sha256(directory / "receipt.json"))
            else:
                if not self.smanager_get_value(state_key(directory), None):
                    raise ValueError('Call Check(stage_args={"action":"probe"}), create plan.yaml, then Check(stage_args={"action":"prepare"})')
                receipt = json.loads((directory / "receipt.json").read_text())
            prepared_environment(directory, self.smanager_get_value)
            pending = [name for name, tool in receipt["tools"].items() if tool["status"] == "needs_install"]
            if pending:
                raise ValueError(f"Missing tools need installation recipes: {pending}; supply install argv and prepare again")
            limitations = {name: tool["reason"] for name, tool in receipt["tools"].items() if tool["status"] == "unavailable"}
            return True, {"status": "prepared_with_limitations" if limitations else "prepared", "limitations": limitations,
                          "summary": str(directory / "summary.md"), "activation": str(directory / "activate.sh"),
                          "next_action": "Call Complete without action. Use activate.sh for shell commands; retain unavailable capabilities in the final report. Preparation does not prove tests passed."}
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, InterruptedError) as error:
            return False, {"error_code": "act4_environment_preparation", "error": str(error),
                           "artifact": self.environment_dir,
                           "next_action": 'Correct plan.yaml or the reported environment problem, then Check(stage_args={"action":"prepare"}); inspect logs with StdCheck during installation.'}
