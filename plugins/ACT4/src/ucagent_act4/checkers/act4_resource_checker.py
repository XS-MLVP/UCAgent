"""Prepare and validate shared ACT4 inputs before any workflow consumes their contents."""

import json
from pathlib import Path
import subprocess

from .act4_environment_checker import ACT4EnvironmentChecker
from ..resources import prepare_sources, repository_identity, resource_locations, verify_reference_snapshots
from ..xiangshan_bundle import safe_path, sha256


class ACT4ResourceChecker(ACT4EnvironmentChecker):
    """Reuse read-only sources while making a private checkout for the generation workflow."""

    def __init__(self, resource_dir: str, workflow: str, inputs: dict, cache_root: str = "",
                 refs: dict | None = None, cfg=None, **kwargs):
        """Store resolved input settings; defer discovery and downloading to Check."""
        super().__init__(resource_dir, cfg=cfg, **kwargs)
        if workflow not in {"generation", "review", "handoff"} or not isinstance(inputs, dict):
            raise ValueError("Use a known ACT4 workflow and its configured input mapping")
        if set(inputs) - {"act4", "manual", "xiangshan", "input"} or not {"act4", "manual"} <= inputs.keys():
            raise ValueError("Source preparation requires act4/manual and optional xiangshan/input")
        if any(not isinstance(value, str) or not value.strip() for value in inputs.values()):
            raise ValueError("Resource paths must be nonempty strings")
        if not isinstance(cache_root, str) or (refs is not None and (not isinstance(refs, dict) or set(refs) - {"act4", "manual", "xiangshan"}
                or any(not isinstance(value, str) or not value.strip() for value in refs.values()))):
            raise ValueError("Use a cache path string and a mapping of named repository refs")
        self.workflow, self.inputs, self.cache_root, self.refs = workflow, inputs, cache_root, refs or {}

    def do_check(self, is_complete=False, action="", timeout=1800, **kwargs):
        """Prepare on explicit request; Complete verifies pins and the recorded input locations only."""
        try:
            if kwargs or action not in {"", "prepare"} or (is_complete and action):
                raise ValueError('Use Check(stage_args={"action":"prepare"}); Complete takes no action')
            if type(timeout) is not int or not 1 <= timeout <= 14400:
                raise ValueError("timeout must be an integer in 1..14400 seconds")
            if self.stage_manager is None:
                raise ValueError("Start source preparation within an active workflow")
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.environment_dir)
            cache, search = resource_locations(workspace, self.cache_root)
            run_output = directory.parents[2]
            if cache.is_relative_to(run_output) or run_output.is_relative_to(cache):
                raise ValueError("Shared resources must be separate from this run's evidence directory")
            key = f"act4_resources:{directory.resolve()}"
            receipt = directory / "receipt.json"
            self._cancelled = False
            if action == "prepare" and not self.smanager_get_value(key, None):
                prepare_sources(workspace, directory, cache, search, self.inputs, self.refs, self.workflow,
                                timeout, self._track)
                self.smanager_set_value(key, sha256(receipt))
            if not receipt.is_file() or self.smanager_get_value(key, None) != sha256(receipt):
                raise ValueError('Prepare source inputs with Check(stage_args={"action":"prepare"}); do not edit receipt.json')
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if set(data["resources"]) != set(self.inputs):
                raise ValueError("Input configuration changed; start a new run")
            for name, record in data["resources"].items():
                path = Path(record["path"])
                if not path.is_dir() or path.is_symlink() or record["configured"] != self.inputs[name]:
                    raise ValueError(f"Prepared input disappeared or changed: {name}; restore it or start a new run")
                if "identity" in record and record["origin"] != "writable_copy":
                    if repository_identity(path, clean=record["origin"] != "provided", require_submodules=record["require_submodules"]) != record["identity"]:
                        raise ValueError(f"Pinned source changed: {name}; restore it or start a new run")
            verify_reference_snapshots(directory, data)
            return True, {"resources": data["resources"], "receipt": str(receipt),
                          "next_action": "Call Complete. Use ACT4Resources to read shared inputs; snapshot only ISA files needed for citations. Never edit shared sources."}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, InterruptedError) as error:
            return False, {"error_code": "act4_resource_preparation", "error": str(error),
                           "artifact": self.environment_dir,
                           "next_action": 'Correct the selected input or restore its pinned source, then Check(stage_args={"action":"prepare"}). Use StdCheck for download logs.'}
