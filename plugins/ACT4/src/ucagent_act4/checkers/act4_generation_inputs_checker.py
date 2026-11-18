"""Prepare native testplans and verifiable ISA inputs for either generation workflow."""

from pathlib import Path
import subprocess
from urllib.error import URLError

from ucagent.checkers.base import Checker

from ..generation_inputs import native_plan_path, prepare_generation_inputs, read_generation_inputs
from ..resources import resolve_source
from ..xiangshan_bundle import safe_path, sha256


class ACT4GenerationInputsChecker(Checker):
    """Capture inputs only on explicit preparation, then verify their immutable receipt."""

    def __init__(self, suite: str, kind: str, input_dir: str, manual_root: str,
                 act4_root: str = "riscv-arch-test", cfg=None):
        """Store resolved source locations without reading workspace state."""
        super().__init__()
        native_plan_path(suite, kind)
        self.suite, self.kind, self.input_dir = suite, kind, input_dir
        self.manual_root, self.act4_root = manual_root, act4_root

    def do_check(self, is_complete=False, action="", manual_files=None, **kwargs):
        """Freeze inputs with prepare/manual_files, or verify the existing capture before completion."""
        try:
            if (kwargs or action not in {"", "prepare"} or (is_complete and (action or manual_files))
                    or (manual_files is not None and action != "prepare")):
                raise ValueError("Use Check with action=prepare and manual_files; Complete takes no action")
            if self.stage_manager is None:
                raise ValueError("Start input preparation in the generation workflow")
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.input_dir)
            key = f"act4_generation_inputs:{directory}"
            if action == "prepare":
                if self.smanager_get_value(key, None):
                    raise ValueError("Inputs are already frozen; verify without action or start a new run to change scope")
                manual = resolve_source(workspace, self.manual_root, directory.parent / "resources", self.smanager_get_value)
                prepare_generation_inputs(directory, safe_path(workspace, self.act4_root), manual,
                                          self.suite, self.kind, manual_files)
                self.smanager_set_value(key, sha256(directory / "receipt.json"))
            data = read_generation_inputs(directory, self.smanager_get_value)
            if (data["suite"], data["kind"]) != (self.suite, self.kind):
                raise ValueError("Prepared suite/style differs from this workflow; start a matching run")
            return True, {"suite": self.suite, "kind": self.kind, "native_plan": data["native_plan"],
                          "new_suite": data["new_suite"], "unpublished_tags": data["unpublished_tags"],
                          "non_text_rules": data["non_text_rules"],
                          "limitations": data["limitations"], "receipt": str(directory / "receipt.json"),
                          "next_action": "Read the captured native plan and ISA sources, then Complete."}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, URLError) as error:
            return False, {"error_code": "act4_generation_inputs", "error": str(error), "artifact": self.input_dir,
                           "next_action": 'Use ACT4Resources to select all relevant src/*.adoc files, then call Check with action="prepare" and manual_files set to those actual paths. If inputs are already frozen, restore the named evidence or start a new run; never invent rules.'}
