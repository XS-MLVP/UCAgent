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
from ..native_ctp import missing_ctp_rules, validate_ctp_scope
from ..resources import clone_local, git_text
from ..generation_run import clone_source_snapshot, import_receipt
from ..run_config import run_settings
from .act4_asset_checklist_checker import source_state, udb_parameter_names
from ..xiangshan_bundle import execute, safe_path, sha256, write_json


class ACT4NativeValidationChecker(ACT4EnvironmentChecker):
    """Prove regeneration, native CTP consumption, lint, and selected DUT-config execution."""

    def __init__(self, suite: str, kind: str, input_dir: str, contract_file: str, manifest_file: str,
                 output_dir: str, environment_dir: str, act4_root: str = "riscv-arch-test",
                 final_report: str | None = None, cfg=None):
        """Keep preparation settings lightweight and defer all subprocesses until explicit Check."""
        super().__init__(environment_dir, cfg=cfg)
        self.cfg = cfg
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
            settings = run_settings(getattr(self, "cfg", None))
            imported = import_receipt(workspace, settings, self.smanager_get_value) if settings else None
            input_baseline = safe_path(workspace, imported["repositories"]["act4"]["baseline"]) if imported else None
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
            if (not isinstance(contribution, list) or (not contribution and not imported) or any(not isinstance(name, str) for name in contribution)
                    or len(contribution) != len(set(contribution))):
                raise ValueError("Provide a nonempty, unique contribution_set in the file manifest")
            sources = {}
            for name in contribution:
                source = safe_path(workspace, name)
                relative = source.relative_to(root).as_posix()
                frozen_source = safe_path(input_baseline, relative) if input_baseline else None
                allow_missing = not source.exists() and frozen_source is not None and frozen_source.is_file()
                if not source.exists() and not allow_missing:
                    original = subprocess.run(["git", "-C", str(root), "cat-file", "-e",
                                               f"{prepared['act4']['head']}:{relative}"],
                                              capture_output=True, timeout=30)
                    allow_missing = original.returncode == 0
                if not contribution_path_allowed(root, relative, allow_missing=allow_missing):
                    raise ValueError(f"Not an upstream-trackable source contribution: {name}")
                if self.kind == "unprivileged" and relative not in assets["required_sources"] and not (imported and relative in imported["repositories"]["act4"]["removed"]):
                    if not re.fullmatch(rf"tests/rv(?:32|64)[ie]/{re.escape(self.suite)}/[^/]+\.S", relative):
                        raise ValueError(f"Outside declared instruction assets: {relative}; do not modify framework internals")
                sources[relative] = sha256(source) if source.is_file() else None
                if sources[relative] is None and not allow_missing:
                    raise ValueError(f"A deleted contribution needs its frozen original source: {relative}")
            if imported:
                original = imported["repositories"]["act4"]["baseline_state"]["files"]
                current = source_state(root)["files"]
                changed = {name for name in original.keys() | current.keys() if original.get(name) != current.get(name)}
            else:
                changed = set(git_text(root, "diff", prepared["act4"]["head"], "--name-only").splitlines())
            if changed - sources.keys():
                raise ValueError(f"Tracked changes outside the contribution set: {sorted(changed - sources.keys())[:40]}; include legitimate assets or resolve unintended writes")
            baseline_sources = {}
            for name in (set(assets["required_sources"]) | set(assets["ctp_dependencies"])) - sources.keys():
                if input_baseline:
                    original_path = safe_path(input_baseline, name)
                    if not original_path.is_file() or sha256(original_path) != sha256(safe_path(root, name)):
                        raise ValueError(f"Contribution set omits a new or modified native asset: {name}")
                    baseline_sources[name] = sha256(original_path)
                    continue
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
                    if input_baseline:
                        original_path = safe_path(input_baseline, dependency)
                        if original_path.is_file():
                            if sha256(original_path) != sha256(safe_path(root, dependency)):
                                raise ValueError(f"Keep selected input config unchanged; generate a distinct native configuration: {dependency}")
                        elif dependency not in sources:
                            raise ValueError(f"New native config dependency must be declared and contributed: {dependency}")
                        config_sources[dependency] = sha256(safe_path(root, dependency))
                        continue
                    previous = subprocess.run(["git", "-C", str(root), "show", f"{prepared['act4']['head']}:{dependency}"],
                                              capture_output=True, timeout=30)
                    if previous.returncode:
                        if dependency not in sources:
                            raise ValueError(f"New native config dependency must be declared and contributed: {dependency}")
                    elif hashlib.sha256(previous.stdout).hexdigest() != sha256(safe_path(root, dependency)):
                        raise ValueError(f"Keep pinned config unchanged; generate a distinct native configuration: {dependency}")
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
                     "source_modes": {name: stat.S_IMODE(safe_path(root, name).stat().st_mode) if value is not None else None for name, value in sources.items()}}
            if action == "validate":
                self.smanager_set_value(key, None)
                self._cancelled = False
                results = []
                data = {"schema_version": 2, "basis": basis, "results": results, "validation_complete": False,
                        "asset_completeness": "complete", "source_limitations": list(prepared["limitations"]),
                        "submission_requirements": ["Real maintainer review", "SPDX/licensing review", "Contributor DCO sign-off and cryptographic commit signature"],
                        "non_claims": ["No DUT certification or 100% coverage claim", "Selected native configs only; not all upstream CI jobs"]}
                write_json(receipt, {**data, "results": [{"name": "validation_attempt", "status": "incomplete",
                                                         "reason": "No completed receipt for this validation attempt"}]})
                deadline = time.monotonic() + timeout
                with tempfile.TemporaryDirectory(prefix="act4-native-") as temporary:
                    checkout = Path(temporary) / "act4"

                    def clone_baseline(target):
                        """Recreate the same pinned input, including its authenticated source overlay."""
                        if input_baseline:
                            clone_source_snapshot(input_baseline, target, directory, deadline, self._track)
                        else:
                            clone_local(root, target, directory, deadline, self._track)
                            git_text(target, "checkout", "--detach", basis["head"])

                    clone_baseline(checkout)
                    for name in sources:
                        target = safe_path(checkout, name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if sources[name] is None:
                            target.unlink(missing_ok=True)
                        else:
                            shutil.copy2(safe_path(root, name), target)
                    git_text(checkout, "add", "--all")
                    clean_env = {name: value for name, value in environment.items()
                                 if name not in {"PYTHONPATH", "VIRTUAL_ENV"} and not name.startswith(("ITGEN", "UCAGENT"))}
                    clean_env["PATH"] = ":".join(part for part in clean_env.get("PATH", "").split(":")
                                                if not Path(part).is_relative_to(root))
                    clean_env["MISE_TRUSTED_CONFIG_PATHS"] = str(checkout)
                    clean_env["MISE_CEILING_PATHS"] = str(checkout.parent)
                    commands = [
                        ("regeneration", ["make", "tests", f"EXTENSIONS={','.join(assets['native_suites'])}", "EXCLUDE_EXTENSIONS=", "WORKDIR=work_native"], checkout),
                    ]
                    hook_sources = [name for name, value in sources.items() if value is not None] or assets["required_sources"]
                    commands.append(("source_hooks", ["mise", "exec", "--", "prek", "run", "--files", *hook_sources], checkout))
                    if assets["parameters"]["status"] == "required":
                        commands.append(("udb_parameters", ["bundle", "exec", "udb", "list", "parameters", "-f", "json"],
                                         safe_path(checkout, "framework/src/act/data")))
                    published = inputs / 'published-norm-rules.json'
                    rules_arg = f"NORM_RULES_URL={published.as_uri()}"
                    commands.append(("ctp", ["make", "-C", "docs/ctp", rules_arg], checkout))
                    for index, config in enumerate(configs):
                        commands.append((f"build_{index}", ["make", "elfs", f"CONFIG_FILES={config}", f"EXTENSIONS={','.join(assets['native_suites'])}",
                                                            "EXCLUDE_EXTENSIONS=", "WORKDIR=work_native", "DEBUG=True"], checkout))
                        run_command = safe_path(checkout, str(Path(config).parent / "run_cmd.txt"))
                        if not run_command.is_file() or not run_command.read_text().strip():
                            raise ValueError(f"Selected config has no native run_cmd.txt: {config}")
                        elf_dir = f"work_native/{Path(config).parent.name}/elfs"
                        commands.append((f"run_{index}", [sys.executable, "run_tests.py", run_command.read_text().strip(), elf_dir], checkout))
                    def run(name, argv, cwd):
                        """Execute within the shared time budget, binding both output streams when required."""
                        log = safe_path(directory, f"{name}.log")
                        stderr = safe_path(directory, "udb_parameters.stderr.log") if name == "udb_parameters" else None
                        build = next((result for result in results if result["name"] == name.replace("run_", "build_")), None)
                        if time.monotonic() >= deadline or self._cancelled:
                            result = {"status": "timeout", "reason": "Native validation deadline exceeded or execution cancelled"}
                            log.write_text(result["reason"], encoding="utf-8")
                            if stderr:
                                stderr.write_bytes(b"")
                        elif name.startswith("run_") and build and build["status"] != "passed":
                            result = {"status": "unavailable" if build["status"] == "unavailable" else "failed",
                                      "reason": f"No run after {build['name']}={build['status']}"}
                            log.write_text(result["reason"], encoding="utf-8")
                        elif name.startswith("run_") and not list(safe_path(checkout, argv[-1]).rglob("*.elf")):
                            result = {"status": "failed", "reason": "Zero final ELFs selected; a vacuous run is not a pass"}
                            log.write_text(result["reason"], encoding="utf-8")
                        else:
                            env = {**clean_env, "MISE_TRUSTED_CONFIG_PATHS": str(cwd)} if name == "ctp_baseline" else clean_env
                            result = execute(argv, cwd, log, max(1, int(deadline - time.monotonic())), self._track, env=env,
                                             **({"stderr_log": stderr} if stderr else {}))
                        if stderr:
                            result.update(stderr_log=stderr.name, stderr_sha256=sha256(stderr))
                        return {"name": name, **result, "log": log.name, "sha256": sha256(log)}

                    for name, argv, cwd in commands:
                        result = run(name, argv, cwd)
                        results.append(result)
                        if result["status"] == "passed" and name == "regeneration":
                            changed = git_text(checkout, "diff", "--name-only", "--", "tests", "coverpoints")
                            untracked = git_text(checkout, "ls-files", "--others", "--exclude-standard", "--", "tests", "coverpoints")
                            if changed or untracked:
                                result.update(status="failed", reason="Commit native regenerated files with their generators",
                                              changed=changed.splitlines()[:40], untracked=untracked.splitlines()[:40])
                        if result["status"] == "passed" and name == "udb_parameters":
                            try:
                                unknown = set(assets["parameters"]["names"]) - udb_parameter_names(directory / result["log"])
                                if unknown:
                                    raise ValueError(f"Unknown UDB parameters: {sorted(unknown)}")
                            except ValueError as error:
                                result.update(status="failed", reason=f"Invalid UDB query output: {error}")
                        if name == "ctp" and result["status"] == "failed":
                            missing = missing_ctp_rules(directory / result["log"], checkout)
                            if missing:
                                result["missing_rules"] = missing
                            affected = {f"coverpoints/norm/{filename}" for filename in missing}
                            suite_names = {self.suite, *assets["native_suites"], *(Path(plan).stem for plan in assets["native_plans"])}
                            if (missing and not any(Path(name).stem in suite_names or Path(name).stem.startswith(self.suite + "_") for name in missing)
                                    and affected.isdisjoint(sources) and affected.isdisjoint(assets["required_sources"])
                                    and all(path in assets["required_sources"] or path.startswith("tests/") for path in sources)
                                    and not any(path.startswith(("docs/", "generators/ctp/")) for path in sources)):
                                baseline = Path(temporary) / "baseline"
                                try:
                                    clone_baseline(baseline)
                                    validate_ctp_scope(checkout, baseline, self.suite, assets, contract["ctp_sources"], published,
                                                       directory, run, results)
                                except (ValueError, OSError, subprocess.SubprocessError) as error:
                                    result["reason"] = f"Could not verify suite CTP scope: {error}"
                    modified = git_text(checkout, "diff", "--name-only").splitlines()
                    if modified:
                        results.append({"name": "source_integrity", "status": "failed", "reason": "Native hooks changed submitted sources",
                                        "files": modified[:40]})
                data["validation_complete"] = all(item["status"] in {"passed", "baseline_limited"} for item in results)
                data["source_limitations"].extend(item["reason"] for item in results if item["status"] == "baseline_limited")
                write_json(receipt, data)
                self.smanager_set_value(key, sha256(receipt))
            if not receipt.is_file() or self.smanager_get_value(key, None) != sha256(receipt):
                raise ValueError('Run Check(stage_args={"action":"validate"}); hand-written success markers are not evidence')
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if data.get("schema_version") != 2:
                raise ValueError('Run Check(stage_args={"action":"validate"}) to record current native command and output evidence')
            if data["basis"] != basis:
                raise ValueError("Contribution/configuration changed; validate the current contribution set again")
            for result in data["results"]:
                if "log" in result and sha256(safe_path(directory, result["log"])) != result["sha256"]:
                    raise ValueError(f"Native execution log changed: {result['name']}")
                if "stderr_log" in result and sha256(safe_path(directory, result["stderr_log"])) != result["stderr_sha256"]:
                    raise ValueError(f"Native stderr log changed: {result['stderr_log']}")
                for filename, digest in result.get("outputs", {}).items():
                    if sha256(safe_path(directory, filename)) != digest:
                        raise ValueError(f"Scoped CTP render changed: {filename}")
            failures = [result for result in data["results"] if result["status"] not in {"passed", "baseline_limited"}]
            if failures:
                details = [{key: str(item[key])[:500] for key in ("name", "status", "reason", "log", "stderr_log", "missing_rules") if key in item}
                           for item in failures[:8]]
                repair = failures[0]
                if repair["name"] == "ctp":
                    repair = next((item for item in failures if item["name"].startswith("ctp_")), repair)
                log = (repair.get("stderr_log") if repair.get("exit_code") != 0 else None) or repair.get("log", "receipt.json")
                advice = ("Compare with the frozen input; do not remove rule references to force a full CTP pass."
                          if repair["name"] == "ctp" else "Repair the named native input or tool, not the frozen baseline.")
                return False, {"error_code": "act4_native_validation", "error": f"Native validation failed: {', '.join(item['name'] for item in failures)}",
                               "artifact": f"{self.output_dir}/{log}", "observed": details, "failure_key": f"{repair['name']}:{repair['status']}",
                               "next_action": f'Read {log}. {advice} Then Check(stage_args={{"action":"validate"}}).'}
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
