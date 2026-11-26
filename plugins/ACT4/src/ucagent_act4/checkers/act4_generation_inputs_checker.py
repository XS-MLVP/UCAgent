"""Prepare native testplans and verifiable ISA inputs for either generation workflow."""

from pathlib import Path
import subprocess
import tempfile
from urllib.error import URLError

from ucagent.checkers.base import Checker

from ..generation_inputs import (bind_source_rules, discover_generation_inputs, load_rules, native_plan_path,
                                prepare_generation_inputs, read_generation_inputs)
from ..resources import resolve_source
from ..xiangshan_bundle import safe_path, sha256


class ACT4GenerationInputsChecker(Checker):
    """Capture inputs only on explicit preparation, then verify their immutable receipt."""

    accepted_stage_args = ("action", "manual_files", "plan_paths", "manual_exclusions", "rule_bindings", "timeout")

    def __init__(self, suite: str, kind: str, input_dir: str, manual_root: str,
                 act4_root: str = "riscv-arch-test", cfg=None):
        """Store resolved source locations without reading workspace state."""
        super().__init__()
        native_plan_path(suite, kind)
        self.suite, self.kind, self.input_dir = suite, kind, input_dir
        self.manual_root, self.act4_root = manual_root, act4_root

    def do_check(self, is_complete=False, action="", manual_files=None, plan_paths=None, manual_exclusions=None,
                 rule_bindings=None, timeout=300, **kwargs):
        """Freeze sources, bind pending rules to exact excerpts, and verify the evidence before completion."""
        try:
            if type(timeout) is not int or timeout <= 0:
                raise ValueError("timeout must be a positive integer in seconds")
            scope_arguments = any(value is not None for value in (manual_files, plan_paths, manual_exclusions))
            if (kwargs or action not in {"", "discover", "prepare", "extend", "bind_rules"}
                    or (is_complete and (action or scope_arguments or rule_bindings is not None))
                    or (scope_arguments and action not in {"discover", "prepare", "extend"})
                    or (manual_exclusions is not None and action == "discover")
                    or (rule_bindings is not None and action != "bind_rules")):
                raise ValueError("Use discover, prepare or extend with manual_files/plan_paths, or bind_rules with rule_bindings; Complete takes no action")
            if self.stage_manager is None:
                raise ValueError("Start input preparation in the generation workflow")
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.input_dir)
            key = f"act4_generation_inputs:{directory}"
            if action and action != "discover" and self.smanager_get_value(key + ":sealed", False):
                raise ValueError("Input stage is complete; start a new run to change its scope or rules")
            if action in {"discover", "prepare", "extend"}:
                manual = resolve_source(workspace, self.manual_root, directory.parent / "resources", self.smanager_get_value)
                root = safe_path(workspace, self.act4_root)
                if action == "discover":
                    return True, {**discover_generation_inputs(root, manual, self.suite, self.kind,
                                                               manual_files if manual_files is not None else [], plan_paths),
                                  "next_action": "Read candidate sources and all plan members. Prepare with manual_files and plan_paths; explain omitted candidates in manual_exclusions. Discovery does not complete input preparation."}
                previous = None
                if action == "extend":
                    previous = (directory, read_generation_inputs(directory, self.smanager_get_value))
                elif self.smanager_get_value(key, None):
                    raise ValueError("Inputs are prepared; use extend to add missing sources before Complete, or verify without action")
                directory.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".inputs-", dir=directory.parent) as temporary:
                    staging = Path(temporary) / "prepared"
                    prepare_generation_inputs(staging, root, manual, self.suite, self.kind,
                                              manual_files, plan_paths, manual_exclusions, previous)
                    backup = Path(temporary) / "previous"
                    if directory.exists():
                        directory.rename(backup)
                    try:
                        staging.rename(directory)
                    except OSError:
                        if backup.exists():
                            backup.rename(directory)
                        raise
                self.smanager_set_value(key, sha256(directory / "receipt.json"))
            data = read_generation_inputs(directory, self.smanager_get_value)
            if (data["suite"], data["kind"]) != (self.suite, self.kind):
                raise ValueError("Prepared suite/style differs from this workflow; start a matching run")
            if action == "bind_rules":
                data = bind_source_rules(directory, data, rule_bindings)
                self.smanager_set_value(key, sha256(directory / "receipt.json"))
            rules = load_rules(directory / "norm-rules.json", allow_empty=True)
            if is_complete and not rules:
                raise ValueError("Sources are frozen but have no mapped rules; use bind_rules with exact source excerpts and pending-tag tracking")
            if is_complete:
                self.smanager_set_value(key + ":sealed", True)
            return True, {"suite": self.suite, "kind": self.kind, "native_plans": data["native_plans"],
                          "source_plans": data["source_plans"], "manual_sources": sorted(data["manual_sources"]),
                          "manual_exclusions": data["manual_exclusions"],
                          "new_suite": data["new_suite"], "unpublished_tags": data["unpublished_tags"],
                          "pending_rules": data["pending_rules"], "rule_count": len(rules),
                          "companion_plans": data["companion_plans"],
                          "non_text_rules": data["non_text_rules"],
                          "limitations": data["limitations"], "receipt": str(directory / "receipt.json"),
                          "next_action": "Read all captured sources; bind missing rules with exact excerpts before Complete. Missing plans and assets are implementation tasks, not unsupported suites."}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, URLError) as error:
            return False, {"error_code": "act4_generation_inputs", "error": str(error), "artifact": self.input_dir,
                           "next_action": 'Use action="discover" to inspect all native plan members and specification candidates. Prepare reviewed sources, or extend the prepared scope before Complete. Use bind_rules with exact name/source/start_line/end_line/text/upstream for pending rules. Never edit receipts; completed input scope requires a new run.'}
