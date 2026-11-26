"""Turn missing generation capabilities into verified implementation work, not suite exclusions."""

import json
from pathlib import Path
import re
import time

import yaml

from .act4_environment_checker import ACT4EnvironmentChecker
from ..environment import COMMERCIAL, prepared_environment
from ..finding_acceptance import check_finding_closure, check_finding_plan
from ..generation_inputs import read_generation_inputs
from ..xiangshan_bundle import execute, safe_path, sha256, write_json


AREAS = {"specification", "testplan", "coverage", "norm_mapping", "parameters", "ctp", "generator",
         "build", "reference_model", "stimulus", "observation"}


class ACT4GenerationCompletionChecker(ACT4EnvironmentChecker):
    """Require a source-led completion plan and real validation of its reusable or generated artifacts."""

    def __init__(self, suite: str, plan_file: str, input_dir: str, output_dir: str, environment_dir: str,
                 phase: str = "plan", final_report: str | None = None, review_dir: str | None = None, cfg=None):
        """Store stage-local inputs; defer source checks and command execution to explicit Check."""
        super().__init__(environment_dir, cfg=cfg)
        if phase not in {"plan", "verify", "generated"} or (phase == "generated" and not review_dir):
            raise ValueError("Completion phase must be plan, generated (with accepted review) or verify")
        self.suite, self.plan_file, self.input_dir = suite, plan_file, input_dir
        self.output_dir, self.phase, self.final_report = output_dir, phase, final_report
        self.review_dir = review_dir

    def do_check(self, is_complete=False, action="", timeout=3600, **kwargs):
        """Validate the scope plan or execute and authenticate its artifact-specific validation commands."""
        try:
            if (kwargs or action not in {"", "validate"} or (action and (is_complete or self.phase != "verify" or self.final_report))
                    or type(timeout) is not int or not 1 <= timeout <= 86400 or self.stage_manager is None):
                raise ValueError('Use Check(stage_args={"action":"validate","timeout":3600}) only in completion verification; Complete takes no action')
            workspace = Path(self.workspace).resolve()
            inputs = safe_path(workspace, self.input_dir)
            prepared = read_generation_inputs(inputs, self.smanager_get_value)
            if prepared["suite"] != self.suite:
                raise ValueError("Completion scope must use this run's prepared suite")
            plan_path = safe_path(workspace, self.plan_file)
            plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
            if (not isinstance(plan, dict) or plan.get("schema_version") != 1 or plan.get("suite") != self.suite
                    or not isinstance(plan.get("requested_scope"), str) or not plan["requested_scope"].strip()
                    or not isinstance(plan.get("items"), list) or not plan["items"]):
                raise ValueError("completion_plan.yaml requires schema_version=1, suite, requested_scope and nonempty items")
            areas, identities, artifacts, limitations, commands = set(), set(), {}, [], []
            if self.phase == "generated":
                witnesses, unmet = check_finding_plan(self, plan, self.review_dir, verify=True, freeze=False)
                return True, {"witness_sources": sorted(witnesses), "missing_witnesses": unmet, "measured_coverage": "not assessed"}
            for item in plan["items"]:
                if not isinstance(item, dict):
                    raise ValueError("Each completion item must be an object")
                identity = item.get("id")
                if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", identity) or identity in identities:
                    raise ValueError("Completion items require distinct stable IDs")
                identities.add(identity)
                if item.get("area") not in AREAS or item.get("action") not in {"reuse", "generate", "not_applicable", "commercial_optional", "external_input"}:
                    raise ValueError(f"{identity}: specify a completion area and reuse/generate/not_applicable/commercial_optional/external_input")
                areas.add(item["area"])
                for field in ("rationale", "scope"):
                    if not isinstance(item.get(field), str) or not item[field].strip():
                        raise ValueError(f"{identity}: explain {field}, including the exact affected behavior")
                paths, checks = item.get("artifacts"), item.get("checks")
                if (not isinstance(paths, list) or any(not isinstance(path, str) for path in paths)
                        or len(set(paths)) != len(paths) or not isinstance(checks, list)):
                    raise ValueError(f"{identity}: artifacts and checks must be lists of explicit paths and command objects")
                operation = item["action"]
                if operation in {"reuse", "generate"} and (not paths or not checks):
                    raise ValueError(f"{identity}: reusable and missing assets both need artifacts and executable checks")
                if operation == "not_applicable" and (paths or checks):
                    raise ValueError(f"{identity}: not_applicable requires empty artifacts/checks and a specification-based rationale")
                if operation == "commercial_optional":
                    if item.get("tool") not in COMMERCIAL or checks:
                        raise ValueError(f"{identity}: only licensed commercial simulators may be skipped as commercial_optional")
                    limitations.append({"id": identity, "reason": "commercial_license", "scope": item["scope"], "help": item["rationale"]})
                if operation == "external_input":
                    if (item.get("reason_code") not in {"target_information", "specification_ambiguity", "permission", "physical_device", "upstream_coordination"}
                            or (item["reason_code"] == "upstream_coordination" and item["area"] not in {"specification", "parameters", "reference_model", "stimulus", "observation"})
                            or not isinstance(item.get("request"), str) or not item["request"].strip() or not paths):
                        raise ValueError(f"{identity}: identify the external input or shared dependency that needs upstream coordination, include investigation evidence and a precise request; generate suite-local assets")
                    limitations.append({"id": identity, "reason": item["reason_code"], "scope": item["scope"], "help": item["request"]})
                for name in paths:
                    path = safe_path(workspace, name)
                    if self.phase == "verify":
                        if not path.is_file() or not path.stat().st_size:
                            raise ValueError(f"{identity}: missing or empty artifact {name}; implement the missing asset, not an exclusion")
                        artifacts[name] = sha256(path)
                for index, check in enumerate(checks):
                    if not isinstance(check, dict) or set(check) != {"argv", "cwd", "inputs"}:
                        raise ValueError(f"{identity}: each check requires argv, cwd and explicit workspace-relative inputs")
                    if not isinstance(check["argv"], list) or not check["argv"] or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in check["argv"]):
                        raise ValueError(f"{identity}: argv must contain nonempty command arguments")
                    cwd = workspace if check["cwd"] == "." else safe_path(workspace, check["cwd"])
                    dependencies = check["inputs"]
                    if (not isinstance(dependencies, list) or any(not isinstance(name, str) for name in dependencies)
                            or len(set(dependencies)) != len(dependencies)):
                        raise ValueError(f"{identity}: inputs must list distinct validation scripts, fixtures and configuration files")
                    for name in dependencies:
                        path = safe_path(workspace, name)
                        if self.phase == "verify":
                            artifacts[name] = sha256(path)
                    if self.phase == "verify":
                        script_suffixes = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".rb", ".pl", ".ps1", ".tcl", ".lua"}
                        for argument in check["argv"]:
                            script_argument = argument.partition("=")[2] if "=" in argument else argument
                            if Path(script_argument).suffix.lower() not in script_suffixes:
                                continue
                            script_path = Path(script_argument)
                            if not script_path.is_absolute():
                                script_path = cwd / script_path
                            try:
                                relative = script_path.resolve().relative_to(workspace).as_posix()
                            except ValueError:
                                continue
                            path = safe_path(workspace, relative)
                            if path.is_file():
                                artifacts[relative] = sha256(path)
                    commands.append((f"{identity}-{index}", check["argv"], cwd))
            if AREAS - areas:
                raise ValueError(f"Plan missing generation areas: {sorted(AREAS - areas)}")
            substantive = {item["area"] for item in plan["items"] if item["action"] in {"reuse", "generate", "external_input"}}
            if AREAS - {"parameters"} - substantive:
                raise ValueError("Core generation areas require implementation, reuse or a concrete external input; not_applicable/commercial_optional cannot replace source assets")
            summary = {"requested_scope": plan["requested_scope"], "items": len(identities),
                       "scope_complete": not any(item["reason"] != "commercial_license" for item in limitations),
                       "limitations": limitations}
            if self.review_dir:
                witnesses, unmet = check_finding_plan(self, plan, self.review_dir, self.phase == "verify", is_complete and self.phase == "plan")
                artifacts.update(witnesses)
                if unmet:
                    summary["scope_complete"] = False
                    summary["missing_witnesses"] = sorted(unmet)
                    if self.final_report:
                        review = safe_path(workspace, self.review_dir)
                        accepted = safe_path(review, "final-accepted.json")
                        state = self.smanager_get_value(f"act4_review:{self.review_dir}:{self.suite}", {})
                        if not accepted.is_file() or sha256(accepted) != state.get("final_snapshot"):
                            raise ValueError("Use accepted final dispositions before reporting missing witnesses")
                        check_finding_closure(json.loads(accepted.read_bytes())["findings"], unmet)
            if self.phase == "plan":
                return True, {**summary, "next_action": "Implement every generate item, including missing open-source tools, adapters and models. Preserve independent validation; do not label absent assets unsupported."}
            environment_dir = safe_path(workspace, self.environment_dir)
            environment = prepared_environment(environment_dir, self.smanager_get_value)
            basis = {"plan": sha256(plan_path), "inputs": sha256(inputs / "receipt.json"), "artifacts": artifacts,
                     "environment": sha256(environment_dir / "receipt.json")}
            directory = safe_path(workspace, self.output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            receipt = directory / "receipt.json"
            key = f"act4_generation_completion:{directory}"
            if action:
                self.smanager_set_value(key, None)
                self._cancelled = False
                deadline, results = time.monotonic() + timeout, []
                for name, argv, cwd in commands:
                    if self._cancelled or time.monotonic() >= deadline:
                        raise ValueError(f"Completion validation stopped before {name}; inspect logs and retry")
                    log = directory / f"{name}.log"
                    result = execute(argv, cwd, log, max(1, int(deadline - time.monotonic())), self._track, environment)
                    results.append({"name": name, **result, "log": log.name, "sha256": sha256(log)})
                current = {name: sha256(safe_path(workspace, name)) for name in artifacts}
                if current != artifacts or sha256(plan_path) != basis["plan"]:
                    raise ValueError("Validation changed completion sources; reconcile generated artifacts and rerun checks on the final inputs")
                write_json(receipt, {"basis": basis, "summary": summary, "results": results})
                self.smanager_set_value(key, sha256(receipt))
            if not receipt.is_file() or self.smanager_get_value(key, None) != sha256(receipt):
                raise ValueError('Run Check(stage_args={"action":"validate"}); prose is not execution evidence')
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if data["basis"] != basis:
                raise ValueError("Completion sources changed; rerun validation for the current artifacts")
            for result in data["results"]:
                if sha256(safe_path(directory, result["log"])) != result["sha256"]:
                    raise ValueError(f"Completion evidence changed: {result['name']}")
            failures = [result["name"] for result in data["results"] if result["status"] != "passed"]
            if failures:
                raise ValueError(f"Completion checks failed or unavailable: {failures}; repair/install the noncommercial dependency and retry")
            if self.final_report:
                text = safe_path(workspace, self.final_report).read_text(encoding="utf-8")
                blocks = [yaml.safe_load(block) for block in re.findall(r"(?ms)^```yaml\s*\n(.*?)^```\s*$", text)]
                reports = [block["scope_completion"] for block in blocks if isinstance(block, dict) and "scope_completion" in block]
                if reports != [summary]:
                    raise ValueError(f"Final report requires one scope_completion YAML block matching this evidence: {summary}")
            return True, {**summary, "receipt": str(receipt), "validated_commands": len(data["results"]),
                          "source_limitations": prepared["limitations"]}
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
            return False, {"error_code": "act4_generation_completion", "error": str(error)[:2500],
                           "artifact": self.plan_file, "next_action": "Read Guide_Doc/ACT4_Checker_Guide/ACT4GenerationCompletionChecker.md, repair the named item and rerun Check. Missing plans, generators, interfaces and free tools are generation work; only concrete external inputs or commercial licenses justify a scoped limitation."}
