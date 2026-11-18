"""Run native ACT consumers in an isolated contribution-only checkout with verified receipts."""

import json
import hashlib
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import re

import yaml
from jsonschema import SchemaError, ValidationError

from .act4_environment_checker import ACT4EnvironmentChecker
from ..environment import prepared_environment
from ..generation_assets import contribution_path_allowed, validate_native_assets
from ..generation_inputs import native_plan_path, read_generation_inputs
from ..resources import clone_local, git_text
from ..xiangshan_bundle import execute, safe_path, sha256, write_json


class ACT4NativeValidationChecker(ACT4EnvironmentChecker):
    """Prove regeneration, native CTP consumption, lint, and selected DUT-config execution."""

    def __init__(self, suite: str, kind: str, input_dir: str, contract_file: str, manifest_file: str,
                 output_dir: str, environment_dir: str, act4_root: str = "riscv-arch-test",
                 final_report: str | None = None, cfg=None):
        """Keep preparation settings lightweight and defer all subprocesses until explicit Check."""
        super().__init__(environment_dir, cfg=cfg)
        native_plan_path(suite, kind)
        self.suite, self.kind, self.input_dir = suite, kind, input_dir
        self.contract_file, self.manifest_file, self.output_dir = contract_file, manifest_file, output_dir
        self.act4_root = act4_root
        self.final_report = final_report

    def do_check(self, is_complete=False, action="", timeout=3600, **kwargs):
        """Validate on explicit request; ordinary Check/Complete verifies current, tool-created evidence."""
        try:
            if kwargs or action not in {"", "validate"} or (is_complete and action) or (self.final_report and action):
                raise ValueError('Use Check(stage_args={"action":"validate"}); Complete only verifies receipts')
            if type(timeout) is not int or not 1 <= timeout <= 86400 or self.stage_manager is None:
                raise ValueError("Use an active stage and an integer timeout in 1..86400")
            workspace = Path(self.workspace).resolve()
            root = safe_path(workspace, self.act4_root)
            inputs = safe_path(workspace, self.input_dir)
            prepared = read_generation_inputs(inputs, self.smanager_get_value)
            if (prepared["suite"], prepared["kind"], prepared["act4"]["path"]) != (self.suite, self.kind, str(root)):
                raise ValueError("Validate the same suite, generation kind and checkout as the prepared inputs")
            contract_file = safe_path(workspace, self.contract_file)
            contract = yaml.safe_load(contract_file.read_text(encoding="utf-8"))
            assets = validate_native_assets(root, inputs, self.suite, self.kind, contract_file, "assets")
            manifest_path = safe_path(workspace, self.manifest_file)
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict) or manifest.get("baseline", {}).get("git_head") != prepared["act4"]["head"]:
                raise ValueError("The contribution manifest must use the prepared ACT Git baseline")
            contribution = manifest.get("contribution_set")
            if (not isinstance(contribution, list) or not contribution or any(not isinstance(name, str) for name in contribution)
                    or len(contribution) != len(set(contribution))):
                raise ValueError("Provide a nonempty, unique contribution_set in the file manifest")
            sources = {}
            for name in contribution:
                source = safe_path(workspace, name)
                relative = source.relative_to(root).as_posix()
                if not contribution_path_allowed(root, relative):
                    raise ValueError(f"Not an upstream-trackable source contribution: {name}")
                if self.kind == "unprivileged" and relative not in assets["required_sources"]:
                    if not re.fullmatch(rf"tests/rv(?:32|64)/{re.escape(self.suite)}/[^/]+\.S", relative):
                        raise ValueError(f"Outside declared instruction assets: {relative}; do not modify framework internals")
                sources[relative] = sha256(source)
            changed = set(git_text(root, "diff", prepared["act4"]["head"], "--name-only").splitlines())
            if changed - sources.keys():
                raise ValueError(f"Tracked changes outside the contribution set: {sorted(changed - sources.keys())[:40]}; include legitimate assets or resolve unintended writes")
            baseline_sources = {}
            for name in (set(assets["required_sources"]) | set(assets["ctp_dependencies"])) - sources.keys():
                previous = subprocess.run(["git", "-C", str(root), "show", f"{prepared['act4']['head']}:{name}"],
                                          capture_output=True, timeout=30)
                if previous.returncode or hashlib.sha256(previous.stdout).hexdigest() != sha256(safe_path(root, name)):
                    raise ValueError(f"Contribution set omits a new or modified native asset: {name}")
                baseline_sources[name] = sha256(safe_path(root, name))
            configs = contract.get("validation_configs")
            if (not isinstance(configs, list) or not configs or any(not isinstance(name, str) for name in configs)
                    or len(set(configs)) != len(configs)):
                raise ValueError("Declare distinct native validation_configs; include relevant CI compiler/XLEN combinations")
            config_sources = {}
            for name in configs:
                if not name.startswith("config/") or not name.endswith("/test_config.yaml"):
                    raise ValueError(f"Select an existing native test_config.yaml, not a private adapter: {name}")
                for dependency in (name, str(Path(name).parent / "run_cmd.txt")):
                    previous = subprocess.run(["git", "-C", str(root), "show", f"{prepared['act4']['head']}:{dependency}"],
                                              capture_output=True, timeout=30)
                    if previous.returncode or hashlib.sha256(previous.stdout).hexdigest() != sha256(safe_path(root, dependency)):
                        raise ValueError(f"Use an unchanged pinned native config: {dependency}")
                    config_sources[dependency] = sha256(safe_path(root, dependency))
            directory = safe_path(workspace, self.output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            key = f"act4_native_validation:{directory}"
            receipt = directory / "receipt.json"
            environment_dir = safe_path(workspace, self.environment_dir)
            environment = prepared_environment(environment_dir, self.smanager_get_value)
            basis = {"sources": sources, "contract_sha256": sha256(contract_file),
                     "input_receipt": sha256(inputs / "receipt.json"), "head": prepared["act4"]["head"],
                     "baseline_sources": baseline_sources, "configs": config_sources,
                     "environment_receipt": sha256(environment_dir / "receipt.json"),
                     "source_modes": {name: stat.S_IMODE(safe_path(root, name).stat().st_mode) for name in sources}}
            if action == "validate":
                self.smanager_set_value(key, None)
                self._cancelled = False
                results = []
                deadline = time.monotonic() + timeout
                with tempfile.TemporaryDirectory(prefix="act4-native-") as temporary:
                    checkout = Path(temporary) / "act4"
                    clone_local(root, checkout, directory, deadline, self._track)
                    git_text(checkout, "checkout", "--detach", basis["head"])
                    for name in sources:
                        target = safe_path(checkout, name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(safe_path(root, name), target)
                    git_text(checkout, "add", "--", *sources)
                    clean_env = {name: value for name, value in environment.items()
                                 if name not in {"PYTHONPATH", "VIRTUAL_ENV"} and not name.startswith(("ITGEN", "UCAGENT"))}
                    clean_env["PATH"] = ":".join(part for part in clean_env.get("PATH", "").split(":")
                                                if not Path(part).is_relative_to(root))
                    clean_env["MISE_TRUSTED_CONFIG_PATHS"] = str(checkout)
                    clean_env["MISE_CEILING_PATHS"] = str(checkout.parent)
                    commands = [
                        ("regeneration", ["make", "tests", f"EXTENSIONS={self.suite}", "EXCLUDE_EXTENSIONS=", "WORKDIR=work_native"], checkout),
                        ("source_hooks", ["mise", "exec", "--", "prek", "run", "--files", *sources], checkout),
                    ]
                    if assets["parameters"]["status"] == "required":
                        commands.append(("udb_parameters", ["bundle", "exec", "udb", "list", "parameters", "-f", "json"],
                                         safe_path(checkout, "framework/src/act/data")))
                    commands.append(("ctp", ["make", "-C", "docs/ctp",
                                               f"NORM_RULES_URL={(inputs / 'published-norm-rules.json').as_uri()}"], checkout))
                    for index, config in enumerate(configs):
                        commands.append((f"build_{index}", ["make", "elfs", f"CONFIG_FILES={config}", f"EXTENSIONS={self.suite}",
                                                            "EXCLUDE_EXTENSIONS=", "WORKDIR=work_native", "DEBUG=True"], checkout))
                        run_command = safe_path(checkout, str(Path(config).parent / "run_cmd.txt"))
                        if not run_command.is_file() or not run_command.read_text().strip():
                            raise ValueError(f"Selected config has no native run_cmd.txt: {config}")
                        elf_dir = f"work_native/{Path(config).parent.name}/elfs"
                        commands.append((f"run_{index}", [sys.executable, "run_tests.py", run_command.read_text().strip(), elf_dir], checkout))
                    for name, argv, cwd in commands:
                        log = directory / f"{name}.log"
                        build = next((result for result in results if result["name"] == name.replace("run_", "build_")), None)
                        if time.monotonic() >= deadline or self._cancelled:
                            result = {"status": "timeout", "reason": "Native validation deadline exceeded or execution cancelled"}
                            log.write_text(result["reason"], encoding="utf-8")
                        elif name.startswith("run_") and build and build["status"] != "passed":
                            result = {"status": "unavailable" if build["status"] == "unavailable" else "failed",
                                      "reason": f"No run after {build['name']}={build['status']}"}
                            log.write_text(result["reason"], encoding="utf-8")
                        elif name.startswith("run_") and not list(safe_path(checkout, argv[-1]).rglob("*.elf")):
                            result = {"status": "failed", "reason": "Zero final ELFs selected; a vacuous run is not a pass"}
                            log.write_text(result["reason"], encoding="utf-8")
                        else:
                            result = execute(argv, cwd, log, max(1, int(deadline - time.monotonic())), self._track, env=clean_env)
                        if result["status"] == "passed" and name == "regeneration":
                            changed = git_text(checkout, "diff", "--name-only", "--", "tests", "coverpoints")
                            untracked = git_text(checkout, "ls-files", "--others", "--exclude-standard", "--", "tests", "coverpoints")
                            if changed or untracked:
                                result.update(status="failed", reason="Commit native regenerated files with their generators",
                                              changed=changed.splitlines()[:40], untracked=untracked.splitlines()[:40])
                        if result["status"] == "passed" and name == "udb_parameters":
                            catalog = json.loads(log.read_text(encoding="utf-8"))
                            known = {entry["name"] for entry in catalog}
                            unknown = set(assets["parameters"]["names"]) - known
                            if unknown:
                                result.update(status="failed", reason=f"Unknown UDB parameters: {sorted(unknown)}")
                        results.append({"name": name, **result, "log": log.name, "sha256": sha256(log)})
                    modified = git_text(checkout, "diff", "--name-only").splitlines()
                    if modified:
                        results.append({"name": "source_integrity", "status": "failed", "reason": "Native hooks changed submitted sources",
                                        "files": modified[:40]})
                data = {"schema_version": 1, "basis": basis, "results": results,
                        "asset_completeness": "complete", "validation_complete": all(record["status"] == "passed" for record in results),
                        "source_limitations": prepared["limitations"],
                        "submission_requirements": ["Real maintainer review", "SPDX/licensing review", "Contributor DCO sign-off and cryptographic commit signature"],
                        "non_claims": ["No DUT certification or 100% coverage claim", "Selected native configs only; not all upstream CI jobs"]}
                write_json(receipt, data)
                self.smanager_set_value(key, sha256(receipt))
            if not receipt.is_file() or self.smanager_get_value(key, None) != sha256(receipt):
                raise ValueError('Run Check(stage_args={"action":"validate"}); hand-written success markers are not evidence')
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if data["basis"] != basis:
                raise ValueError("Contribution/configuration changed; validate the current contribution set again")
            for result in data["results"]:
                if "log" in result and sha256(safe_path(directory, result["log"])) != result["sha256"]:
                    raise ValueError(f"Native execution log changed: {result['name']}")
            failures = [result for result in data["results"] if result["status"] not in {"passed", "unavailable"}]
            if failures:
                raise ValueError(f"Native validation failed: {[result['name'] for result in failures]}; fix the first failing source/configuration and revalidate")
            if self.final_report:
                text = safe_path(workspace, self.final_report).read_text(encoding="utf-8")
                summaries = []
                for block in re.findall(r"(?ms)^```yaml\s*\n(.*?)^```\s*$", text):
                    candidate = yaml.safe_load(block)
                    if isinstance(candidate, dict) and "generation_result" in candidate:
                        summaries.append(candidate["generation_result"])
                expected = {"asset_completeness": data["asset_completeness"], "validation_complete": data["validation_complete"],
                            "limitations": [result["name"] for result in data["results"] if result["status"] != "passed"],
                            "source_limitations": data["source_limitations"],
                            "submission_requirements": data["submission_requirements"]}
                if summaries != [expected]:
                    raise ValueError(f"Final report must contain one generation_result YAML block matching actual evidence: {expected}")
            return True, {"asset_completeness": data["asset_completeness"], "validation_complete": data["validation_complete"],
                          "limitations": [result for result in data["results"] if result["status"] != "passed"],
                          "source_limitations": data["source_limitations"],
                          "submission_requirements": data["submission_requirements"], "receipt": str(receipt)}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, yaml.YAMLError, SchemaError, ValidationError) as error:
            return False, {"error_code": "act4_native_validation", "error": str(error)[:2000], "artifact": self.output_dir,
                           "next_action": 'Read the named native log, repair contribution sources or prepare the missing tool, then Check(stage_args={"action":"validate"}). Keep missing tools and human submission requirements separate from asset completeness.'}
