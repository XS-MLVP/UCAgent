"""Isolate existing ACT assets and gate reproducible Kunminghu V3 handoff packages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

import yaml

from ucagent.checkers.base import Checker

from .. import xiangshan_bundle as bundle
from .. import xiangshan_delivery
from ..environment import prepared_environment, read_plan
from ..xiangshan_acquisition import XiangShanAcquisition
from ..xiangshan_trace import testcase_inventory, validate_trace


TARGET_TOPICS = {"configuration", "isa", "memory", "boot", "termination", "console", "timer", "interrupts"}


def source_files(root: Path, names: list[str]) -> dict:
    """Expand declared source trees without copying caches, symlinks, or special files."""
    result = {}
    for name in names:
        selected = bundle.safe_path(root, name)
        if not selected.exists():
            raise ValueError(f"Missing source: {root / name}")
        paths = [selected]
        if selected.is_dir():
            paths = []
            for directory, children, files in os.walk(selected, followlinks=False):
                for child in children:
                    if (Path(directory) / child).is_symlink():
                        raise ValueError(f"Source symlink must be materialized before handoff: {Path(directory) / child}")
                children[:] = [child for child in children if child not in bundle.SOURCE_IGNORE_DIRS]
                paths.extend(Path(directory) / filename for filename in files if filename != ".git" and not filename.endswith(".pyc"))
        for path in paths:
            relative = str(path.relative_to(root))
            result[relative] = bundle.identity(bundle.safe_path(root, relative))
    if not result or len(result) > 50000:
        raise ValueError("Select 1..50000 source files; omit build outputs and tool installations")
    return result


def git_output(root: Path, *args: str, env=None) -> str:
    """Read bounded Git provenance without changing the supplied checkout."""
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=30, check=True, env=env)
    return result.stdout.decode().strip()


class ACT4XiangShanChecker(Checker):
    """Gate input isolation, V3 evidence, native compilation, and portable delivery separately."""

    accepted_stage_args = ("action", "timeout", "jobs", "emulator", "cycles", "queries", "generation_id")

    def __init__(self, phase: str, suite: str, handoff_dir: str, input_root: str,
                 framework_root: str, xiangshan_root: str, manual_root: str = "riscv-isa-manual", cfg=None, **kwargs):
        """Store stage parameters without reading workspace or deriving live state."""
        super().__init__()
        if phase not in {"scope", "inputs", "target", "build", "delivery"} or kwargs:
            raise ValueError("Unknown XiangShan handoff phase or arguments")
        self.phase, self.suite, self.handoff_dir = phase, suite, handoff_dir
        self.input_root, self.framework_root, self.xiangshan_root = input_root, framework_root, xiangshan_root
        self.manual_root = manual_root
        self.cfg = cfg
        self._cancelled = False
        self._active_log = None

    def _track_process(self, process, timeout, log):
        """Expose the active command to KillCheck and stop subsequent jobs after cancellation."""
        self.set_check_process(process, timeout)
        self._active_log = log
        if self._cancelled:
            raise ValueError("Handoff action was cancelled; inspect the last log before retrying")

    def kill(self):
        """Cancel the current native process group without leaving compiler or simulator children."""
        self._cancelled = True
        if self._process is None or self._process.poll() is not None:
            return "No active handoff command; cancellation recorded"
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return "Handoff command group cancelled; wait for Check to return before retrying"

    def check_std(self, lines):
        """Expose a bounded tail of the real active command log to StdCheck."""
        if self._active_log is None or not self._active_log.is_file():
            return "No handoff command log is available yet"
        with self._active_log.open("rb") as stream:
            stream.seek(max(0, self._active_log.stat().st_size - 16384))
            output = stream.read().decode(errors="replace").splitlines()
        return "\n".join(output[-max(1, min(int(lines), 100)):])

    def _load(self, name: str) -> dict:
        """Read a versioned task document with a concrete recovery instruction."""
        path = bundle.safe_path(self.output, name)
        if not path.is_file():
            raise ValueError(f"Create {name} using Guide_Doc/ACT4_XiangShan_Handoff_Guide.md")
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError(f"{name} requires schema_version: 1")
        return data

    def _inputs(self, state: dict, action: str, timeout: int) -> None:
        """Snapshot explicit framework and local asset imports before native generation."""
        plan = self._load("input.yaml")
        if plan.get("suite") != self.suite or not isinstance(plan.get("framework_paths"), list) or not plan["framework_paths"]:
            raise ValueError("input.yaml requires the current suite and nonempty framework_paths")
        imports = plan.get("imports")
        generation = plan.get("generation", [])
        if not isinstance(imports, list) or not imports or not isinstance(generation, list):
            raise ValueError("input.yaml requires nonempty imports and a generation command list")
        framework = source_files(self.framework, plan["framework_paths"])
        exclusions = plan.get("framework_exclude", [])
        if not isinstance(exclusions, list) or any(not isinstance(name, str) for name in exclusions) or len(exclusions) != len(set(exclusions)):
            raise ValueError("framework_exclude must list unique exact paths replaced by local module imports")
        replaced = {}
        for name in exclusions:
            if name not in framework or not name.startswith("generators/testgen/"):
                raise ValueError(f"Only selected test-generator files may be replaced by explicit local imports: {name}")
            replaced[name] = framework.pop(name)
        for required in ("README.md", "pyproject.toml", "uv.lock", "framework/src/act/act.py", "tests/env/rvtest_macros.h"):
            if required not in framework:
                raise ValueError(f"framework_paths must include {required} from the matching ACT checkout")
        if any(name.startswith("tests/") and not name.startswith("tests/env/") for name in framework):
            raise ValueError("Select only tests/env from framework_paths; import module tests and support files explicitly")
        assets, destinations, import_files = {}, {}, {}
        features = {feature["id"]: feature for feature in self.scope["features"]}
        covered_features = set()
        for entry in imports:
            if not isinstance(entry, dict) or set(entry) != {"origin", "source", "destination", "features"}:
                raise ValueError("Each import requires origin, source, destination and features")
            origin = entry["origin"]
            if origin not in self.import_roots:
                raise ValueError(f"Unknown or unfinished asset origin: {origin}")
            selected_features = entry["features"]
            if not isinstance(selected_features, list) or not selected_features or any(name not in features for name in selected_features):
                raise ValueError("Import features must reference the requested XiangShan functions in scope.yaml")
            for name in selected_features:
                feature = features[name]
                if feature["resolution"] == "unavailable":
                    raise ValueError(f"Do not import tests for an unavailable function: {name}")
                if origin == "local" and feature["resolution"] != "local":
                    raise ValueError("Local supplementation requires an explicitly assessed upstream gap")
                if origin.startswith("generated:") and (feature["resolution"] != "generate" or origin != f"generated:{feature['generation_job']}"):
                    raise ValueError("Generated imports must belong to that function's declared gap-generation job")
            source_root = self.import_roots[origin]
            source = bundle.safe_path(source_root, entry["source"])
            destination = bundle.safe_path(self.package / "act4", entry["destination"])
            if not entry["destination"].startswith(("tests/", "testplans/", "generators/testgen/", "coverpoints/", "references/")):
                raise ValueError("Import destinations must be module tests, plans, test generators or coverpoints")
            selected = source_files(source_root, [entry["source"]])
            if origin.startswith("generated:") and any(name not in state["synthesis"][origin.split(":", 1)[1]]["files"] for name in selected):
                raise ValueError("Generated imports must come from the completed workflow's recorded asset inventory")
            for name, identity in selected.items():
                target = destination / Path(name).relative_to(entry["source"]) if source.is_dir() else destination
                target_name = str(target.relative_to(self.package / "act4"))
                if target_name.endswith((".elf", ".sig", ".results", ".log")):
                    raise ValueError(f"Import source assets only, not earlier build outputs: {target_name}")
                if target_name in destinations or target_name in framework:
                    raise ValueError(f"Duplicate or framework-overwriting import: {target_name}")
                destinations[target_name] = {"origin": origin, "source": name, "features": selected_features}
                assets[f"{origin}:{name}"] = identity
                import_files[target_name] = bundle.safe_path(source_root, name)
                if target_name.startswith(("tests/", "testplans/", "generators/testgen/")):
                    covered_features.update(selected_features)
        required_features = {name for name, feature in features.items() if feature["resolution"] != "unavailable"}
        if required_features != covered_features:
            raise ValueError(f"Every available function needs actual test/plan/generator assets: {sorted(required_features - covered_features)}")
        for command in generation:
            if not isinstance(command, list) or not command or any(not isinstance(word, str) or not word or "\x00" in word for word in command):
                raise ValueError("generation entries must be nonempty argv lists, without shell expansion")
            if command[0] not in {"uv", "python3", "make"}:
                raise ValueError("Use a reviewed native uv, python3 or make generation entry point")
        if not set(replaced) <= set(destinations):
            raise ValueError("Every framework_exclude entry must have an explicit local import to the same destination")
        fingerprint = {"input_yaml": bundle.sha256(self.output / "input.yaml"), "scope": state["scope"], "framework": framework,
                       "framework_replaced": replaced, "assets": assets, "destinations": destinations}
        if "inputs" in state and state["inputs"] != fingerprint:
            if action != "prepare":
                raise ValueError("Selected inputs changed; return to handoff_inputs and explicitly prepare a new snapshot")
            previous = bundle.safe_path(self.output, f"previous-inputs/{uuid.uuid4().hex}")
            previous.mkdir(parents=True)
            self.package.rename(previous / "bundle")
            bundle.write_json(previous / "receipts.json", state)
            for name in ("inputs", "snapshot", "generation", "generated", "source_provenance", "target", "build_plan", "build", "run", "delivery"):
                state.pop(name, None)
        if "inputs" not in state:
            if action != "prepare":
                raise ValueError("Call Check(stage_args={\"action\":\"prepare\"}) to snapshot the selected inputs")
            if (self.package / "act4").exists():
                raise ValueError("Unowned bundle/act4 already exists; use a fresh handoff output directory")
            for name, source in {**{name: bundle.safe_path(self.framework, name) for name in framework}, **import_files}.items():
                target = bundle.safe_path(self.package / "act4", name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            state["inputs"] = fingerprint
            state["snapshot"] = source_files(self.package / "act4", list(framework) + list(destinations))
            provenance = {}
            for label, root in {"framework": self.framework, **{origin: self.import_roots[origin] for origin in {entry['origin'] for entry in imports}}}.items():
                try:
                    repository = Path(git_output(root, "rev-parse", "--show-toplevel", env=self.environment))
                    head = git_output(repository, "rev-parse", "HEAD", env=self.environment)
                    provenance[label] = {"kind": "git", "commit": head, "subdirectory": str(root.relative_to(repository)),
                                         "dirty": bool(git_output(root, "status", "--porcelain", "--", ".", env=self.environment))}
                except subprocess.SubprocessError:
                    provenance[label] = {"kind": "directory", "commit": None}
            state["source_provenance"] = provenance
        bundle.verify_files(self.package / "act4", state["snapshot"])
        if generation and not state.get("generation"):
            if action != "generate":
                raise ValueError("Call Check(stage_args={\"action\":\"generate\"}) to run the declared native generation")
            records = []
            deadline = time.monotonic() + timeout
            for index, command in enumerate(generation):
                remaining = int(deadline - time.monotonic())
                if remaining < 1:
                    raise ValueError("Generation budget exhausted; inspect completed logs and retry with a larger timeout")
                record = bundle.execute(command, self.package / "act4", self.output / f"generation-{index}.log", remaining, self._track_process, env=self.environment)
                records.append(record)
                if record["status"] != "passed":
                    bundle.write_json(self.output / "generation-result.json", {"schema_version": 1, "commands": records})
                    raise ValueError(f"Generation failed; inspect generation-{index}.log and repair its dependency before retrying")
            bundle.verify_files(self.package / "act4", state["snapshot"])
            bundle.write_json(self.output / "generation-result.json", {"schema_version": 1, "commands": records})
            state["generation"] = {"result": bundle.sha256(self.output / "generation-result.json"),
                                   "logs": {f"generation-{index}.log": bundle.identity(self.output / f"generation-{index}.log") for index in range(len(records))}}
        if generation:
            if bundle.sha256(self.output / "generation-result.json") != state["generation"]["result"]:
                raise ValueError("Native generation receipt changed")
            bundle.verify_files(self.output, state["generation"]["logs"])
        current = source_files(self.package / "act4", ["tests"])
        assembly = [name for name in current if name.endswith(".S") and not name.startswith("tests/env/")]
        if not assembly:
            raise ValueError("No module .S files exist; import generated assembly or declare its native generation command")
        if "generated" in state and current != state["generated"]:
            raise ValueError("Generated tests changed; do not manually edit the test body or expected results")
        state["generated"] = current
        bundle.write_json(self.output / "input-inventory.json", {"schema_version": 1, "suite": self.suite,
                          "framework": framework, "imports": destinations, "assembly": assembly})

    def _target(self, state: dict, action: str) -> None:
        """Require actual V3 source citations and account for every imported assembly file."""
        target = self._load("target.yaml")
        selection = self._load("selection.yaml")
        head = git_output(self.xiangshan, "rev-parse", "HEAD", env=self.environment)
        if target.get("family") != "kunminghu-v3" or target.get("commit") != head or target.get("top") != "SimTop":
            raise ValueError("target.yaml must identify kunminghu-v3, SimTop and the exact XiangShan HEAD")
        branch = git_output(self.xiangshan, "branch", "--show-current", env=self.environment)
        if branch != "kunminghu-v3":
            git_output(self.xiangshan, "merge-base", "--is-ancestor", head, "refs/remotes/origin/kunminghu-v3", env=self.environment)
        configuration = target.get("configuration")
        if not isinstance(configuration, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", configuration):
            raise ValueError("target.yaml requires the actual Scala configuration class")
        memory = target.get("memory")
        if not isinstance(memory, dict) or set(memory) != {"base", "size"} or any(type(value) is not int or value <= 0 for value in memory.values()) or sum(memory.values()) > 2 ** 64:
            raise ValueError("memory requires positive integer base and size within RV64")
        if type(target.get("allow_source_only")) is not bool or not isinstance(target.get("limitations"), list) or any(not isinstance(item, str) or not item.strip() for item in target["limitations"]):
            raise ValueError("target.yaml requires allow_source_only and an explicit limitations list")
        decisions = target.get("decisions")
        if not isinstance(decisions, dict) or set(decisions) != TARGET_TOPICS:
            raise ValueError(f"target decisions must cover {sorted(TARGET_TOPICS)}")
        citations = []
        for topic, decision in decisions.items():
            if not isinstance(decision, dict) or not isinstance(decision.get("reason"), str) or not decision["reason"].strip() or not isinstance(decision.get("references"), list) or not decision["references"]:
                raise ValueError(f"Target decision {topic} requires reasoning and V3 source references")
            for reference in decision["references"]:
                if not isinstance(reference, dict) or set(reference) != {"path", "lines", "quote"}:
                    raise ValueError(f"Target decision {topic} references require path, lines and quote")
                path = bundle.safe_path(self.xiangshan, reference["path"])
                bounds = reference["lines"]
                text = path.read_text(encoding="utf-8")
                lines = text.splitlines()
                if not isinstance(bounds, list) or len(bounds) != 2 or any(type(number) is not int for number in bounds) or not 1 <= bounds[0] <= bounds[1] <= len(lines) or bounds[1] - bounds[0] >= 100:
                    raise ValueError(f"Invalid 1..100-line source citation: {reference['path']}")
                quote = "\n".join(lines[bounds[0] - 1:bounds[1]])
                if reference.get("quote") != quote:
                    raise ValueError(f"Citation disagrees with {reference['path']}:{bounds}")
                repository = Path(git_output(path.parent, "rev-parse", "--show-toplevel", env=self.environment))
                revision = git_output(repository, "rev-parse", "HEAD", env=self.environment)
                committed = subprocess.run(["git", "-C", str(repository), "show", f"HEAD:{path.relative_to(repository)}"], capture_output=True, check=True, timeout=30, env=self.environment).stdout
                if hashlib.sha256(committed).hexdigest() != bundle.sha256(path):
                    raise ValueError(f"Cited source differs from its pinned commit: {reference['path']}")
                citations.append({"topic": topic, "path": reference["path"], "lines": bounds, "quote": quote,
                                  "sha256": bundle.sha256(path), "commit": revision})
        if not any(re.search(rf"\bclass\s+{re.escape(configuration)}\b", item["quote"]) for item in citations if item["topic"] == "configuration"):
            raise ValueError("Configuration evidence must include the selected Scala class declaration")
        config_root = bundle.safe_path(self.output, "config")
        config_files = source_files(config_root, ["test_config.yaml", "udb.yaml", "sail.json", "link.ld", "rvmodel_macros.h"])
        config = yaml.safe_load((config_root / "test_config.yaml").read_text())
        required = {"name": "xiangshan-kmhv3", "udb_config": "udb.yaml", "linker_script": "link.ld", "dut_include_dir": "."}
        if not isinstance(config, dict) or any(config.get(key) != value for key, value in required.items()):
            raise ValueError(f"test_config.yaml requires {required}")
        for field in ("compiler_exe", "ref_model_exe", "objdump_exe"):
            value = config.get(field)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+", value):
                raise ValueError(f"{field} must be a portable executable name resolved on PATH")
        if not config["objdump_exe"].endswith("objdump"):
            raise ValueError("objdump_exe must name a matching binutils objdump; objcopy uses the same tool prefix")
        if "sail" not in config["ref_model_exe"].lower():
            raise ValueError("ref_model_exe must remain Sail; supply emu only to the run action")
        if type(config.get("harts", 1)) is not int or config.get("harts", 1) != 1:
            raise ValueError("This handoff targets a single hart; set harts: 1")
        if not isinstance(yaml.safe_load((config_root / "udb.yaml").read_text()), dict):
            raise ValueError("udb.yaml must describe the V3 target")
        records = selection.get("tests")
        if not isinstance(records, list) or not records:
            raise ValueError("selection.yaml requires a nonempty tests list")
        expected = {name.removeprefix("tests/") for name in state["generated"] if name.endswith(".S") and not name.startswith("tests/env/")}
        included, seen = [], set()
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Each selection entry requires path, disposition and reason")
            name = item["path"]
            if name in seen or name not in expected or item.get("disposition") not in {"include", "exclude", "support"} or not isinstance(item.get("reason"), str) or not item["reason"].strip():
                raise ValueError(f"Invalid, duplicate or unexplained selection: {name}")
            seen.add(name)
            if item["disposition"] == "support" and Path(name).parent.name != "env":
                raise ValueError(f"Native ACT scans {name} as a test; support .S must already be in an env directory. Preserve native include layout")
            if item["disposition"] == "include":
                if Path(name).parent.name == "env":
                    raise ValueError(f"Native ACT excludes env support files from test selection: {name}")
                content = bundle.safe_path(self.package / "act4/tests", name).read_text()
                match = re.search(r"START_TEST_CONFIG[^\n]*\n(.*?)^[^\n]*END_TEST_CONFIG", content, re.MULTILINE | re.DOTALL)
                if not match:
                    raise ValueError(f"{name} requires the native START_TEST_CONFIG / END_TEST_CONFIG header; regenerate using its matching framework")
                header = "\n".join(re.sub(r"^\s*(?:#|//|\*)", "", line, count=1) for line in match.group(1).splitlines())
                metadata = yaml.safe_load(header)
                if not isinstance(metadata, dict) or type(metadata.get("NEEDS_SIGNATURE", True)) is not bool:
                    raise ValueError(f"Invalid ACT test metadata in {name}")
                signature = metadata.get("NEEDS_SIGNATURE", True)
                included.append({"path": name, "needs_signature": signature})
        if seen != expected or not included:
            raise ValueError(f"Account for all .S files and include at least one; missing={sorted(expected - seen)[:20]}")
        signature = {"target": bundle.sha256(self.output / "target.yaml"), "selection": bundle.sha256(self.output / "selection.yaml"),
                     "traceability": bundle.sha256(self.output / "traceability.yaml"), "config": config_files, "citations": citations,
                     "delivery_contract": {name: bundle.sha256(Path(bundle.__file__).parent / name) for name in
                        ("xiangshan_bundle.py", "xiangshan_recipient.py", "xiangshan_delivery.py", "xiangshan_trace.py", "handoff/README.md", "handoff/Makefile")}}
        if state.get("target") == signature:
            bundle.load_plan(self.package)
            return
        if action != "adapt":
            raise ValueError("Call Check(stage_args={\"action\":\"adapt\"}) to validate and freeze the target and selection")
        trace = validate_trace(self.package / "act4", self._load("traceability.yaml"), [test["path"] for test in included])
        described = {test["path"]: test for test in trace["tests"]}
        for test in included:
            test["description"] = bundle.test_description(trace, described[test["path"]])
        excluded = {item["path"] for item in records if item["disposition"] == "exclude"}
        include_roots = [self.package / "act4", self.package / "act4/tests/env", config_root]
        selected_sources = [(self.package / "act4" / name, name) for name in state["generated"] if name.removeprefix("tests/") not in excluded]
        selected_sources += [(config_root / name, f"config/{name}") for name in config_files]
        for path, name in selected_sources:
            if path.suffix not in {".S", ".h", ".ld"}:
                continue
            text = path.read_text(encoding="utf-8")
            references = re.findall(r'(?m)^\s*(?:#\s*include\s*|\.include\s+|\.incbin\s+|INCLUDE\s+)"([^"\n]+)"', text)
            references += re.findall(r"(?m)^\s*INCLUDE\s+([^\s\";]+)", text)
            for reference in references:
                if Path(reference).is_absolute():
                    raise ValueError(f"Nonportable absolute include in {name}: {reference}")
                if reference in {"rvtest_config.h", "rvtest_config.svh", "rvmodel_macros.svh"}:
                    continue
                candidates = [(directory / reference).resolve() for directory in [path.parent, *include_roots]]
                if not any((candidate.is_relative_to(self.package.resolve()) and candidate.is_file()) or (candidate.parent == config_root.resolve() and candidate.name in config_files) for candidate in candidates):
                    raise ValueError(f"Missing packaged include/data dependency in {name}: {reference}; import it and prepare a new input snapshot")
        if state.get("target"):
            old_plan = bundle.load_plan(self.package)
            for name in old_plan["files"]:
                if name.startswith("act4/selected-tests/"):
                    bundle.safe_path(self.package, name).unlink()
        for name in config_files:
            destination = bundle.safe_path(self.package / "act4/config/xiangshan-kmhv3", name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_root / name, destination)
        for name in state["generated"]:
            relative = name.removeprefix("tests/")
            if relative not in excluded:
                destination = bundle.safe_path(self.package / "act4/selected-tests", relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                original = self.package / "act4" / name
                if relative in described:
                    description = bundle.test_description(trace, described[relative])
                    destination.write_bytes(bundle.annotate_source(original.read_bytes(), described[relative], description))
                else:
                    shutil.copy2(original, destination)
        shutil.copy2(Path(bundle.__file__), self.package / "act4_driver.py")
        bundle.write_json(self.package / "target-evidence.json", {"schema_version": 1, "target": target, "sources": citations})
        shutil.copy2(self.output / "selection.yaml", self.package / "selection.yaml")
        shutil.copy2(self.output / "input.yaml", self.package / "input.yaml")
        shutil.copy2(self.output / "scope.yaml", self.package / "scope.yaml")
        shutil.copy2(self.output / "discovery.json", self.package / "discovery.json")
        bundle.write_json(self.package / "traceability.json", trace)
        bundle.write_json(self.package / "provenance.json", {"schema_version": 1, "suite": self.suite, "inputs": state["inputs"],
                          "repositories": state["source_provenance"]})
        names = ["act4", "act4_driver.py", "target-evidence.json", "selection.yaml", "provenance.json", "input.yaml", "scope.yaml", "discovery.json", "traceability.json"]
        for receipt in state.get("synthesis", {}).values():
            for name in [receipt[field] for field in ("completion", "execution", "log")] + list(receipt["reports"]):
                relative = f"acquisition/{name}"
                destination = bundle.safe_path(self.package, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bundle.safe_path(self.output, name), destination)
                names.append(relative)
        if state.get("generation"):
            for name in ["generation-result.json", *state["generation"]["logs"]]:
                destination = bundle.safe_path(self.package, f"generation/{name}")
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(self.output / name, destination)
            names.append("generation")
        files = source_files(self.package, names)
        if any(name.endswith((".elf", ".sig", ".results")) for name in files):
            raise ValueError("Source snapshot contains previous compiled/signature outputs; prepare inputs containing source assets only")
        bundle.write_json(self.package / "build-plan.json", {"schema_version": 1, "suite": self.suite, "tests": included,
                          "memory": memory, "target": {key: target[key] for key in ("family", "commit", "configuration", "top")}, "files": files,
                          "tools": {"uv": "uv", "compiler": config["compiler_exe"], "sail": config["ref_model_exe"],
                                    "objdump": config["objdump_exe"], "objcopy": config["objdump_exe"].removesuffix("objdump") + "objcopy"}})
        state["target"] = signature
        state["build_plan"] = bundle.sha256(self.package / "build-plan.json")
        for name in ("build", "run", "delivery"):
            state.pop(name, None)

    def _deliver(self, state: dict, action: str) -> dict:
        """Publish a compact recipient directory; keep every audit and execution log in plugin output."""
        result = json.loads((self.package / "build-result.json").read_text())
        if bundle.sha256(self.package / "build-result.json") != state.get("build"):
            raise ValueError("Missing or changed native build receipt; call the build action")
        target = self._load("target.yaml")
        plan = bundle.load_plan(self.package)
        status = "built_not_run" if result["status"] == "passed" else "source_only"
        if status == "source_only" and not target["allow_source_only"]:
            raise ValueError("ELF build did not pass; resolve the recorded failure before delivery")
        bundle.verify_files(self.package, result["artifacts"])
        if result["status"] == "passed":
            bundle.validate_build(self.package, result)
        run = None
        if state.get("run"):
            if bundle.sha256(self.package / "run-result.json") != state["run"]:
                raise ValueError("Emulator execution receipt changed; rerun the current ELFs")
            run = json.loads((self.package / "run-result.json").read_text())
            if run["build_sha256"] != state["build"] or sorted(item["source"] for item in run["tests"]) != sorted(item["path"] for item in plan["tests"]):
                raise ValueError("Emulator receipt does not cover this build")
            bundle.verify_files(self.package, run["artifacts"])
            status = "emulator_passed" if run["status"] == "passed" else "emulator_failed"
        summary = {
            "source_only": "Source only; NOT ready to run. Repair build dependencies and rebuild before execution.",
            "built_not_run": "Final selfchecking ELFs, binaries and disassembly were built. They have NOT been run on XiangShan.",
            "emulator_passed": "All selected programs passed ACT selfchecks and GOOD TRAP on the supplied emulator; its hardware revision was not independently verified.",
            "emulator_failed": "One or more programs failed or timed out on the supplied emulator. See per-program results; do not attribute failures to RTL without diagnosis.",
        }[status]
        trace = json.loads((self.package / "traceability.json").read_text())
        report = {"schema_version": 1, "suite": self.suite, "status": status, "summary": summary,
                  "target": plan["target"], "tests": len(plan["tests"]), "limitations": target["limitations"],
                  "build": {key: result[key] for key in ("status", "errors", "log")},
                  "failed_tests": [test for test in run["tests"] if test["status"] != "passed"] if run else [],
                  "requested_module": self.scope["request"], "functions": self.scope["features"],
                  "traceability": {"report": "delivery/TESTS.md", "data": "bundle/traceability.json",
                                   "testcases": sum(len(test["cases"]) for test in trace["tests"]),
                                   "coverpoints": len(trace["coverpoints"]), "norm_rules": len(trace["rules"]),
                                   "evidence_level": trace["evidence_level"]}}
        delivery = bundle.safe_path(self.output, "delivery")
        archive_path = bundle.safe_path(self.output, f"{self.suite}-kunminghu-v3.tar.gz")
        if action == "package":
            environment = read_plan(self.output.parent / "environment")["tools"]
            with tempfile.TemporaryDirectory(dir=self.output) as temporary:
                staged = Path(temporary) / "delivery"
                manifest = xiangshan_delivery.publish(staged, self.package, plan, result, trace, self.scope,
                                                     target, status, summary, environment, run)
                archive_temp = Path(temporary) / "delivery.tar.gz"
                with tarfile.open(archive_temp, "w:gz") as archive:
                    for name in sorted([*manifest["files"], "manifest.json"]):
                        archive.add(bundle.safe_path(staged, name), arcname=f"{self.suite}-kunminghu-v3/{name}", recursive=False)
                relocated = Path(temporary) / "received"
                with tarfile.open(archive_temp) as archive:
                    for member in archive.getmembers():
                        prefix = f"{self.suite}-kunminghu-v3/"
                        if not member.isfile() or not member.name.startswith(prefix):
                            raise ValueError("Archive contains a non-file or unexpected package root")
                        destination = bundle.safe_path(relocated, member.name.removeprefix(prefix))
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as source, destination.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        destination.chmod(0o755 if member.mode & 0o111 else 0o644)
                checked = subprocess.run([sys.executable, "-B", str(relocated / "handoff.py"), "verify"], cwd=temporary,
                                         capture_output=True, text=True, timeout=60)
                if checked.returncode:
                    raise ValueError(f"Relocated package verification failed: {checked.stderr[-1000:]}")
                if delivery.exists():
                    if not (delivery / "manifest.json").is_file():
                        raise ValueError("Unowned delivery directory exists; use a fresh handoff output")
                    previous = bundle.safe_path(self.output, f"previous-deliveries/{uuid.uuid4().hex}")
                    previous.parent.mkdir(exist_ok=True)
                    delivery.rename(previous)
                staged.rename(delivery)
                archive_temp.replace(archive_path)
            state["delivery"] = {"manifest": bundle.sha256(delivery / "manifest.json"), "archive": bundle.sha256(archive_path)}
            bundle.write_json(self.output / "handoff-report.json", report)
            (self.output / "handoff-report.md").write_text(
                f"\n# {self.suite} handoff\n\n{summary}\n\n"
                + "Recipient guide: delivery/README.md. ACT index: delivery/TESTS.md.\n\n"
                + "Producer evidence: bundle/build-result.json, optional bundle/run-result.json, traceability.yaml and target.yaml.\n",
                encoding="utf-8")
        if not state.get("delivery"):
            raise ValueError('Call Check(stage_args={"action":"package"}) to create and verify the recipient package')
        if state["delivery"]["manifest"] != bundle.sha256(delivery / "manifest.json") or state["delivery"]["archive"] != bundle.sha256(archive_path):
            raise ValueError("Delivery changed; package the current evidence again")
        sealed = json.loads((delivery / "manifest.json").read_text())
        bundle.verify_files(delivery, sealed["files"])
        actual = {str(path.relative_to(delivery)) for path in delivery.rglob("*") if path.is_file()}
        if actual != set(sealed["files"]) | {"manifest.json"} or sealed["status"] != status:
            raise ValueError("Delivery contains unrecorded files or stale status; package it again")
        return report

    def do_check(self, is_complete=False, action="", timeout=1800, jobs=1, emulator="", cycles=20000000,
                 queries=None, generation_id="", **kwargs):
        """Validate current handoff evidence; execute native jobs only on explicit Check actions."""
        try:
            if kwargs or (is_complete and action):
                raise ValueError("Complete validates only; run explicit actions with Check first")
            if type(timeout) is not int or not 1 <= timeout <= 86400:
                raise ValueError("timeout must be in 1..86400 seconds")
            self._cancelled = False
            if not re.fullmatch(r"[^\W\d][\w-]{0,79}", self.suite):
                raise ValueError("Use a single XiangShan module identifier, such as Vector or LSU, without path separators")
            workspace = Path(self.workspace).resolve()
            self.output = bundle.safe_path(workspace, self.handoff_dir)
            self.environment = prepared_environment(self.output.parent / "environment", self.smanager_get_value if self.stage_manager else None)
            self.source = bundle.safe_path(workspace, self.input_root)
            self.framework = bundle.safe_path(workspace, self.framework_root)
            self.xiangshan = bundle.safe_path(workspace, self.xiangshan_root)
            manual = bundle.safe_path(workspace, self.manual_root)
            if any(self.output.is_relative_to(root) or root.is_relative_to(self.output) for root in (self.source, self.framework, self.xiangshan, manual)):
                raise ValueError("Handoff output must not overlap read-only inputs")
            self.package = bundle.safe_path(self.output, "bundle")
            self.output.mkdir(parents=True, exist_ok=True)
            if self.stage_manager is None:
                raise ValueError("Restart the handoff workflow with an active stage manager")
            key = f"act4_xiangshan:{self.handoff_dir}:{self.suite}"
            state = self.smanager_get_value(key, {})
            roots = {"upstream": self.framework, "local": self.source, "xiangshan": self.xiangshan, "manual": manual}
            defaults = {"upstream": (self.framework_root, "riscv-arch-test"), "xiangshan": (self.xiangshan_root, "XiangShan"), "manual": (self.manual_root, "riscv-isa-manual")}
            for origin, (configured, default) in defaults.items():
                if not roots[origin].exists() and configured == default:
                    roots[origin] = bundle.safe_path(self.output, f"repositories/{default}")
            self.framework, self.xiangshan = roots["upstream"], roots["xiangshan"]
            acquisition = XiangShanAcquisition(self.output, roots, state, self.environment, self._track_process)
            allowed = {"scope": {"", "fetch", "discover"}, "inputs": {"", "prepare", "generate", "synthesize"}, "target": {"", "inventory", "adapt"}, "build": {"", "adapt", "build", "run"}, "delivery": {"", "package"}}
            if action not in allowed[self.phase]:
                raise ValueError(f"Actions for this stage: {sorted(allowed[self.phase])}")
            try:
                bundle.write_json(self.output / "acquisition-paths.json", {key: str(path.relative_to(workspace)) for key, path in roots.items()})
                if action == "fetch":
                    acquisition.fetch(timeout)
                    return True, {"next_action": "Read acquisition-paths.json and the requested XiangShan module; discover matching ACT suites and specific subfeatures."}
                if action == "discover":
                    return True, acquisition.discover(queries)
                self.scope = acquisition.validate(self.suite)
                if self.phase == "scope":
                    return True, {"module": self.suite, "features": len(self.scope["features"]), "next_action": "Complete scope selection, prepare the environment, then acquire only missing assets."}
                if action == "synthesize":
                    backend = self.cfg.get_value("backend.key_name", "") if self.cfg is not None else ""
                    acquisition.synthesize(self.scope, generation_id, backend, timeout)
                    return True, {"next_action": "Inspect the completed generation assets and import only the missing parts through input.yaml."}
                self.import_roots = acquisition.import_roots(self.scope)
                self._inputs(state, action, timeout)
                if action == "inventory":
                    selected = [item["path"] for item in self._load("selection.yaml")["tests"] if item["disposition"] == "include"]
                    bundle.write_json(self.output / "trace-inventory.json", testcase_inventory(self.package / "act4", selected))
                    return True, {"inventory": "trace-inventory.json", "next_action": "Describe every testcase and its coverpoint/norm evidence in traceability.yaml before adapt."}
                if self.phase != "inputs":
                    self._target(state, action)
                if self.phase in {"build", "delivery"}:
                    if bundle.sha256(self.package / "build-plan.json") != state.get("build_plan"):
                        raise ValueError("Frozen build plan changed; start a fresh handoff")
                    if action == "adapt":
                        return False, {"error_code": "act4_xiangshan_rebuild", "error": "Target changed; previous build and simulation evidence were invalidated",
                                       "next_action": "Call Check(stage_args={\"action\":\"build\"}) for the updated target."}
                    if action == "build":
                        state.pop("build", None)
                        state.pop("run", None)
                        state.pop("delivery", None)
                        result = bundle.build(self.package, "build-result.json", timeout, jobs, self._track_process, env=self.environment)
                        state["build"] = bundle.sha256(self.package / "build-result.json")
                    if not state.get("build") or bundle.sha256(self.package / "build-result.json") != state["build"]:
                        raise ValueError("Call Check(stage_args={\"action\":\"build\"}) to record a real native build attempt")
                    result = json.loads((self.package / "build-result.json").read_text())
                    if result["status"] != "passed" and not self._load("target.yaml")["allow_source_only"]:
                        raise ValueError(f"Build status is {result['status']}; inspect {result['log']} and its errors before retrying")
                    if action == "run":
                        executable = bundle.safe_path(workspace, emulator)
                        state.pop("run", None)
                        state.pop("delivery", None)
                        bundle.run(self.package, "build-result.json", str(executable), timeout, cycles, "run-result.json", self._track_process, env=self.environment)
                        state["run"] = bundle.sha256(self.package / "run-result.json")
                    if result["status"] == "passed":
                        bundle.validate_build(self.package, result)
                if self.phase == "delivery":
                    return True, self._deliver(state, action)
                return True, {"phase": self.phase, "suite": self.suite, "build_recorded": bool(state.get("build")),
                              "emulator_run_recorded": bool(state.get("run")), "next_action": "Review the artifacts and call Complete without action to advance."}
            finally:
                self.smanager_set_value(key, state, persist=True)
        except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError, subprocess.SubprocessError) as error:
            return False, {"error_code": "act4_xiangshan_handoff", "error": str(error), "artifact": self.handoff_dir,
                           "next_action": "Correct the named input or dependency using Guide_Doc/ACT4_XiangShan_Handoff_Guide.md, then repeat the indicated Check action. Do not edit receipts."}
