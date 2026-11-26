"""Validate nine contribution categories against pinned sources and fresh executable evidence."""

from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

import yaml

from .act4_environment_checker import ACT4EnvironmentChecker
from ..environment import prepared_environment
from ..generation_inputs import load_rules, read_generation_inputs
from ..resources import clone_local, git_text
from ..generation_run import clone_source_snapshot, import_receipt
from ..run_config import run_settings
from ..xiangshan_bundle import execute, safe_path, sha256, write_json


CATEGORIES = {
    "norm_rules": ("Norm Rules", {"extract", "schema", "semantic"}),
    "udb_params": ("UDB/Params", {"schema", "query", "semantic"}),
    "rvvi": ("RVVI", {"producer", "consumer", "roundtrip"}),
    "rvmodel_macros": ("RVMODEL Macros", {"compile", "runtime"}),
    "testplan": ("Testplan", {"schema", "traceability", "semantic"}),
    "ctp": ("CTP", {"render", "includes"}),
    "coverpoints": ("Coverpoints", {"structure", "traceability", "semantic"}),
    "sail": ("Sail", {"build", "semantic"}),
    "tests": ("Tests", {"generate", "build", "self_check"}),
}
CORE = {"testplan", "ctp", "coverpoints", "tests"}
MODIFY = {"generate", "repair"}


def source_state(root: Path) -> dict:
    """Bind tracked and nonignored source content, deletions, modes and the pinned Git revision."""
    files = {}
    names = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.split("\0")
    for name in sorted(set(names) - {""}):
        path = root / name
        if path.is_symlink():
            files[name] = {"link": path.readlink().as_posix()}
        elif path.is_file():
            files[name] = {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode)}
        elif path.is_dir():
            files[name] = {"submodule": git_text(path, "rev-parse", "HEAD"),
                           "dirty": git_text(path, "status", "--porcelain"), "state": source_state(path)}
    return {"head": git_text(root, "rev-parse", "HEAD"), "files": files}


def udb_parameter_names(path: Path) -> set[str]:
    """Read unique parameter names from the native UDB query's JSON stdout."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(entries, list) or not entries
            or any(not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip() for entry in entries)
            or len({entry["name"] for entry in entries}) != len(entries)):
        raise ValueError(f"Require nonempty native UDB parameter records with unique names: {path.name}")
    return {entry["name"] for entry in entries}


def verify_output(path: Path, format_name: str) -> dict:
    """Reject empty, malformed or vacuous evidence and return its immutable digest."""
    if not path.is_file() or not path.stat().st_size:
        raise ValueError(f"Missing or empty validation output: {path}")
    if format_name == "junit":
        document = ET.parse(path).getroot()
        cases = document.findall(".//testcase")
        if (document.tag not in {"testsuite", "testsuites"} or not cases or document.findall(".//failure") or document.findall(".//error")
                or not any(case.find("skipped") is None for case in cases)):
            raise ValueError(f"Require nonzero passing, non-skipped testcases: {path}")
    elif format_name == "norm_rules":
        load_rules(path)
    elif format_name == "udb_parameters":
        udb_parameter_names(path)
    elif format_name == "json":
        if not json.loads(path.read_text(encoding="utf-8")):
            raise ValueError(f"Empty JSON result: {path}")
    elif format_name == "yaml":
        if not yaml.safe_load(path.read_text(encoding="utf-8")):
            raise ValueError(f"Empty YAML result: {path}")
    elif format_name == "elf":
        with path.open("rb") as stream:
            header = stream.read(20)
        if len(header) != 20 or header[:4] != b"\x7fELF" or header[18:20] != b"\xf3\x00":
            raise ValueError(f"Expected a RISC-V ELF: {path}")
    elif format_name != "text":
        raise ValueError(f"Unknown evidence format: {format_name}")
    return {"sha256": sha256(path), "format": format_name}


class ACT4AssetChecklistChecker(ACT4EnvironmentChecker):
    """Gate reuse, scoped reports and independently tested changes for all nine ACT asset categories."""

    def __init__(self, suite: str, plan_file: str, input_dir: str, environment_dir: str,
                 output_dir: str, patch_dir: str, phase: str = "plan", final_report: str | None = None, cfg=None):
        """Store paths and phase; source inspection and baseline capture happen only during Check."""
        super().__init__(environment_dir, cfg=cfg)
        self.cfg = cfg
        if phase not in {"plan", "verify"}:
            raise ValueError("phase must be plan or verify")
        self.suite, self.plan_file, self.input_dir = suite, plan_file, input_dir
        self.environment_dir, self.output_dir, self.patch_dir = environment_dir, output_dir, patch_dir
        self.phase, self.final_report = phase, final_report

    def do_check(self, is_complete=False, action="", timeout=3600, **kwargs):
        """Freeze clean repositories, validate typed change evidence, and reconcile the final checklist."""
        location = self.plan_file
        try:
            if (kwargs or action not in {"", "validate"} or type(timeout) is not int or not 1 <= timeout <= 86400
                    or (action and (self.phase != "verify" or is_complete or self.final_report))):
                raise ValueError('Use Check(stage_args={"action":"validate"}) during verification; Complete takes no action')
            workspace = Path(self.workspace).resolve()
            settings = run_settings(getattr(self, "cfg", None))
            imported = import_receipt(workspace, settings, self.smanager_get_value) if settings else None
            plan_path = safe_path(workspace, self.plan_file)
            plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
            if (not isinstance(plan, dict) or set(plan) != {"schema_version", "suite", "repositories", "items"}
                    or plan["schema_version"] != 1 or plan["suite"] != self.suite
                    or not isinstance(plan["repositories"], dict) or "act4" not in plan["repositories"]
                    or not isinstance(plan["items"], list) or not plan["items"]):
                raise ValueError("Require schema_version=1, suite, repositories including act4, and nonempty items")
            if imported:
                for item in plan["items"]:
                    category = item.get("category") if isinstance(item, dict) else None
                    policy = imported["settings"]["assets"].get(category, {})
                    selected = imported["selection"]["assets"].get(category, {})
                    if (policy.get("source") == "local" and policy.get("on_missing") == "report" and not selected.get("files")
                            and item.get("action") not in {"report", "not_applicable"}):
                        raise ValueError(f"{category}: requested local shared input is absent; report the gap or explain non-applicability, do not substitute an upstream source")
                    if (policy.get("source") == "local" and policy.get("on_missing") == "generate"
                            and not selected.get("files") and item.get("action") != "generate"
                            and not (item.get("required") is False and item.get("action") in {"not_applicable", "report"})):
                        raise ValueError(f"{category}: the selected local source was missing; generate a new asset instead of reusing or excluding the upstream source")
            inputs = safe_path(workspace, self.input_dir)
            prepared = read_generation_inputs(inputs, self.smanager_get_value)
            if prepared["suite"] != self.suite:
                raise ValueError("Checklist suite differs from frozen inputs")
            directory = safe_path(workspace, self.output_dir)
            patch_dir = safe_path(workspace, self.patch_dir)
            roots, states = {}, {}
            if imported and not set(imported["repositories"]) <= plan["repositories"].keys():
                raise ValueError("Declare every imported dependency repository in the nine-asset checklist")
            for name, relative in plan["repositories"].items():
                if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                    raise ValueError("Repository IDs must be lowercase identifiers")
                root = safe_path(workspace, relative)
                if ".ucagent" in root.parts or any(root == path or root.is_relative_to(path) or path.is_relative_to(root)
                                                  for path in [directory, patch_dir, *roots.values()]):
                    raise ValueError(f"Repository paths must be separate from evidence and other repositories: {relative}")
                if Path(git_text(root, "rev-parse", "--show-toplevel")).resolve() != root:
                    raise ValueError(f"Require a separate Git checkout: {relative}")
                roots[name], states[name] = root, source_state(root)
            if states["act4"]["head"] != prepared["act4"]["head"]:
                raise ValueError("ACT repository revision differs from frozen input")
            key = f"act4_asset_checklist:{directory}"
            baseline = self.smanager_get_value(key + ":baseline")
            if baseline is None:
                if self.phase != "plan" or is_complete:
                    raise ValueError("Run the planning Check before changing any source; no baseline exists")
                for name, root in roots.items():
                    imported_root = imported["repositories"].get(name) if imported else None
                    if imported_root:
                        if imported_root["working"] != plan["repositories"][name] or imported_root["working_initial"] != states[name]:
                            raise ValueError(f"Imported sources changed before baseline capture: {name}")
                    elif git_text(root, "status", "--porcelain", "--untracked-files=all"):
                        raise ValueError(f"First Check requires a clean checkout, not a post-edit baseline: {name}")
                baseline = {"repositories": plan["repositories"], "states": states}
            if baseline["repositories"] != plan["repositories"]:
                raise ValueError("Repository scope changed after baseline capture; restart input planning before edits")
            changes = {}
            for name, state in states.items():
                previous = baseline["states"][name]
                if state["head"] != previous["head"]:
                    raise ValueError(f"Pinned repository HEAD changed: {name}")
                changes[name] = {path for path in state["files"].keys() | previous["files"].keys()
                                 if state["files"].get(path) != previous["files"].get(path)}
                if imported and name in imported["repositories"]:
                    changes[name].update(imported["repositories"][name]["removed"])
            identities, categories, covered, snapshots, operations = set(), set(), {}, {}, []
            oracles, baseline_checks = {}, {}
            for item in plan["items"]:
                fields = {"id", "category", "action", "required", "scope", "reason", "repository", "artifacts", "checks", "report", "oracle"}
                if not isinstance(item, dict) or set(item) != fields:
                    raise ValueError(f"Each checklist item requires exactly {sorted(fields)}")
                identity, category, decision = item["id"], item["category"], item["action"]
                location = f"{self.plan_file}#{identity}"
                if (not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", identity) or identity in identities
                        or category not in CATEGORIES or decision not in {*MODIFY, "reuse", "reference", "report", "not_applicable"}
                        or type(item["required"]) is not bool):
                    raise ValueError("Require unique item IDs, one of nine categories, a supported action and boolean required")
                identities.add(identity)
                categories.add(category)
                protected = bool(settings and settings["assets"][category]["mode"] == "repair_only")
                if protected and decision == "generate":
                    raise ValueError(f"{category}: repair_only does not generate missing shared inputs; reference an unchanged input or report the gap")
                if decision == "reference" and (not protected or item["required"] or item["checks"]):
                    raise ValueError(f"{identity}: reference is for optional unchanged shared inputs, without executable checks; use reuse for a verification claim")
                if settings and settings["assets"][category]["mode"] == "regenerate" and decision == "reuse":
                    raise ValueError(f"{category}: the selected regeneration policy forbids reuse")
                if any(not isinstance(item[field], str) or not item[field].strip() for field in ("scope", "reason")):
                    raise ValueError("Describe the exact target/platform scope and the source-based decision")
                if not isinstance(item["artifacts"], list) or not isinstance(item["checks"], list):
                    raise ValueError("artifacts and checks must be lists")
                repository = item["repository"]
                if repository is not None and repository not in roots:
                    raise ValueError(f"Unknown repository: {repository}")
                if decision in MODIFY and repository is None:
                    raise ValueError("Modified assets need a pinned, independently writable repository")
                if decision in MODIFY:
                    oracle = item["oracle"]
                    oracle_fields = {"method", "sources", "explanation"} | ({"baseline_failure"} if protected else set())
                    if (not isinstance(oracle, dict) or set(oracle) != oracle_fields
                            or oracle["method"] not in {"manual_examples", "independent_model", "upstream_tests"}
                            or not isinstance(oracle["sources"], list) or not oracle["sources"]
                            or not isinstance(oracle["explanation"], str) or not oracle["explanation"].strip()):
                        raise ValueError(f"{identity}: changes require an independent oracle with {sorted(oracle_fields)}")
                    for relative in oracle["sources"]:
                        path = safe_path(workspace, relative)
                        if (relative in item["artifacts"] or ".ucagent" in path.parts
                                or path.is_relative_to(directory) or path.is_relative_to(patch_dir)):
                            raise ValueError("A changed asset or generated evidence cannot be its own oracle")
                        for name, root in roots.items():
                            if path.is_relative_to(root) and path.relative_to(root).as_posix() in changes[name]:
                                raise ValueError("Oracle source was modified by this run; use independent fixed inputs")
                        snapshots[relative] = {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode)}
                        oracles[relative] = snapshots[relative]
                elif item["oracle"] is not None:
                    raise ValueError("Only changed assets declare an oracle")
                if decision == "not_applicable":
                    if item["required"] or item["artifacts"] or item["checks"] or item["report"] is not None:
                        raise ValueError("Only genuinely inapplicable optional scopes may have no artifacts or checks")
                    continue
                if not item["artifacts"] or len(set(item["artifacts"])) != len(item["artifacts"]):
                    raise ValueError("Declare distinct source artifacts or investigation evidence")
                if decision == "report":
                    report = item["report"]
                    if (not isinstance(report, dict) or set(report) != {"reason_code", "impact", "next_action"}
                            or report["reason_code"] not in {"outside_scope", "external_input", "commercial_license", "upstream_coordination"}
                            or any(not isinstance(report[field], str) or not report[field].strip() for field in report)
                            or item["checks"] or (item["required"] and report["reason_code"] == "outside_scope")):
                        raise ValueError("Reports need reason_code, impact and next_action; required work cannot be outside_scope")
                elif item["report"] is not None:
                    raise ValueError("Only report actions contain report details")
                changed = []
                for relative in item["artifacts"]:
                    path = safe_path(workspace, relative)
                    if ".ucagent" in path.parts or path.is_relative_to(directory) or path.is_relative_to(patch_dir):
                        raise ValueError("Source artifacts cannot be managed state or checklist outputs")
                    owning = [name for name, root in roots.items() if path.is_relative_to(root)]
                    if owning:
                        name = owning[0]
                        native = path.relative_to(roots[name]).as_posix()
                        if native in changes[name]:
                            if decision not in MODIFY or repository != name:
                                raise ValueError(f"Changed source cannot be classified as {decision}: {relative}")
                            changed.append(native)
                            covered.setdefault(name, set()).add(native)
                        if repository is not None and name != repository:
                            raise ValueError(f"Asset belongs to a different repository: {relative}")
                        owners = imported["owners"].get(f"{name}:{native}", []) if imported else []
                        if protected and decision in {"repair", "reference"} and category not in owners:
                            raise ValueError(f"{identity}: {relative} must be a frozen input selected for {category}")
                        if settings and decision in MODIFY and not protected and name != "act4" and category not in owners:
                            raise ValueError(f"{identity}: do not classify shared dependency repository changes as suite generation: {relative}")
                    elif decision in MODIFY:
                        raise ValueError(f"Modified source is outside its declared repository: {relative}")
                    elif decision == "reference" and not (category == "norm_rules" and path == inputs / "norm-rules.json" and "norm-rules.json" in prepared["files"]):
                        raise ValueError(f"{identity}: reference needs a selected source or the frozen normative rule index: {relative}")
                    if self.phase == "verify" or decision in {"reuse", "reference", "report"}:
                        original_files = imported["repositories"][repository]["baseline_state"]["files"] if imported and repository in imported["repositories"] else {}
                        if not path.exists() and changed and (native in baseline["states"][repository]["files"] or native in original_files):
                            snapshots[relative] = None
                        else:
                            snapshots[relative] = {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode)}
                if self.phase == "verify" and decision in MODIFY:
                    if not changed:
                        raise ValueError("generate/repair must own a real source change, not only a claim")
                    before = baseline["states"][repository]["files"]
                    if decision == "generate" and not any(name not in before and name in states[repository]["files"] for name in changed):
                        raise ValueError("generate requires a newly added source; use repair for existing-source edits")
                    original_files = imported["repositories"][repository]["baseline_state"]["files"] if imported and repository in imported["repositories"] else {}
                    if decision == "repair" and not any(name in before or name in original_files for name in changed):
                        raise ValueError("repair requires an existing-source change; use generate for new assets")
                roles = set()
                for index, check in enumerate(item["checks"]):
                    if not isinstance(check, dict) or set(check) != {"kind", "argv", "cwd", "inputs", "outputs", "exit_code", "diagnostic"}:
                        raise ValueError("Checks require kind, argv, cwd, inputs, outputs, exit_code and diagnostic")
                    role = check["kind"]
                    if role not in CATEGORIES[category][1] | {"inspect", "negative", "regression"}:
                        raise ValueError(f"Unsupported validation role for {category}: {role}")
                    roles.add(role)
                    argv = check["argv"]
                    if (not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
                            or Path(argv[0]).name in {"echo", "true", "false", "touch", "printf"} or "-c" in argv):
                        raise ValueError("Use executable validators/native commands, not inline or placeholder commands")
                    if any(str(workspace) in argument for argument in argv):
                        raise ValueError("Use isolated workspace-relative inputs, not absolute paths into the original workspace")
                    if check["cwd"] != ".":
                        safe_path(workspace, check["cwd"])
                    if not isinstance(check["inputs"], list) or not check["inputs"]:
                        raise ValueError("Declare validator, fixture and source dependencies")
                    for relative in check["inputs"]:
                        path = safe_path(workspace, relative)
                        if ".ucagent" in path.parts or path.is_relative_to(directory) or path.is_relative_to(patch_dir):
                            raise ValueError("Validation inputs cannot be managed state or checklist evidence")
                        if self.phase == "verify":
                            snapshots[relative] = {"sha256": sha256(path), "mode": stat.S_IMODE(path.stat().st_mode)}
                    if type(check["exit_code"]) is not int or (role != "negative" and check["exit_code"] != 0):
                        raise ValueError("Successful validators require exit_code=0")
                    if role == "negative":
                        if not 1 <= check["exit_code"] <= 125 or not isinstance(check["diagnostic"], str) or not check["diagnostic"].strip():
                            raise ValueError("Negative checks require a deliberate failing fixture and specific diagnostic")
                        re.compile(check["diagnostic"])
                    elif check["diagnostic"] is not None:
                        raise ValueError("diagnostic is reserved for negative checks")
                    outputs = check["outputs"]
                    if not isinstance(outputs, dict) or (not outputs and role != "negative"):
                        raise ValueError("Successful checks require fresh nonempty output artifacts")
                    if role in {"semantic", "regression", "roundtrip", "self_check", "runtime"} and "junit" not in outputs.values():
                        raise ValueError(f"{role} requires a nonzero passing JUnit test report")
                    if category == "norm_rules" and role == "extract" and "norm_rules" not in outputs.values():
                        raise ValueError("Rule extraction requires a native norm_rules output, not a generic success report")
                    if category == "udb_params" and role == "query" and "udb_parameters" not in outputs.values():
                        raise ValueError("UDB queries require native udb_parameters output")
                    for relative, format_name in outputs.items():
                        path = safe_path(workspace, relative)
                        if (".ucagent" in path.parts or any(path.is_relative_to(root) for root in roots.values())
                                or path.is_relative_to(directory) or path.is_relative_to(patch_dir)
                                or relative in snapshots or format_name not in {"junit", "json", "yaml", "elf", "text", "norm_rules", "udb_parameters"}):
                            raise ValueError("Outputs must be separate fresh evidence paths, not source files")
                    operations.append((f"{identity}-{index}", check))
                if protected and decision == "repair":
                    defect = item["oracle"]["baseline_failure"]
                    if (not isinstance(defect, dict) or set(defect) != {"check_index", "exit_code", "message"}
                            or type(defect["check_index"]) is not int or not 0 <= defect["check_index"] < len(item["checks"])
                            or type(defect["exit_code"]) is not int or not 1 <= defect["exit_code"] <= 125
                            or not isinstance(defect["message"], str) or not defect["message"].strip()):
                        raise ValueError(f"{identity}: baseline_failure needs a zero-based check_index, expected nonzero exit_code and the specific literal defect message")
                    check = item["checks"][defect["check_index"]]
                    if (check["kind"] not in CATEGORIES[category][1] or not set(item["artifacts"] + item["oracle"]["sources"]) <= set(check["inputs"])):
                        raise ValueError(f"{identity}: reproduce the defect with a positive {category} check consuming the selected sources and independent oracle")
                    unchanged = {name: sha256(safe_path(workspace, name)) for name in set(check["inputs"]) - set(item["artifacts"])}
                    for name, digest in unchanged.items():
                        snapshots[name] = {"sha256": digest, "mode": stat.S_IMODE(safe_path(workspace, name).stat().st_mode)}
                    baseline_checks[f"{identity}-{defect['check_index']}"] = {"failure": defect, "check": check, "artifacts": sorted(item["artifacts"]), "inputs": unchanged}
                if decision in MODIFY and (CATEGORIES[category][1] | {"negative", "regression"}) - roles:
                    raise ValueError(f"Missing validation roles: {sorted((CATEGORIES[category][1] | {'negative', 'regression'}) - roles)}")
                if decision in MODIFY:
                    positive = [check for check in item["checks"] if check["kind"] != "negative"]
                    dependencies = {name for check in positive for name in check["inputs"]}
                    semantic_inputs = {name for check in positive
                                       if check["kind"] in {"semantic", "roundtrip", "runtime", "self_check", "regression"}
                                       for name in check["inputs"]}
                    if set(item["oracle"]["sources"]) - semantic_inputs:
                        raise ValueError("Semantic/regression checks must declare the fixed independent oracle sources as inputs")
                    if self.phase == "verify" and {name for name in item["artifacts"] if snapshots[name] is not None} - dependencies:
                        raise ValueError("Positive checks must declare the actual changed sources as inputs")
                    for check in item["checks"]:
                        if check["kind"] == "negative":
                            prefix = 2 if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|bash|sh|perl|ruby|node", Path(check["argv"][0]).name) else 1
                            if prefix == 2 and check["argv"][1:2] == ["-m"]:
                                prefix = 3
                            if (not set(check["inputs"]) - dependencies
                                    or not any(check["argv"][:prefix] == valid["argv"][:prefix] for valid in positive)
                                    or re.search(check["diagnostic"], "") or not re.search(r"\w{2,}", check["diagnostic"])):
                                raise ValueError("Negative validation must exercise the same validator with a distinct bad input and specific diagnostic")
                if decision == "reuse" and not roles - {"negative"}:
                    raise ValueError("Reused assets require an executable compatibility check")
            if categories != set(CATEGORIES):
                raise ValueError(f"Checklist must cover all nine categories; missing {sorted(set(CATEGORIES) - categories)}")
            if imported:
                for identity, owners in imported["owners"].items():
                    repository, native = identity.split(":", 1)
                    required_path = imported["repositories"][repository]["working"] + "/" + native
                    for category in owners:
                        if not any(item["category"] == category and required_path in item["artifacts"] for item in plan["items"]):
                            raise ValueError(f"Selected input is missing from its category checklist: {required_path} ({category})")
            for category in CORE:
                if not any(item["category"] == category and item["required"] for item in plan["items"]):
                    raise ValueError(f"Core category must include required work: {category}")
            for identity, check in operations:
                if set(check["outputs"]) & snapshots.keys():
                    raise ValueError(f"{identity}: validation outputs overlap source inputs")
            if "oracles" in baseline and baseline["oracles"] != oracles:
                raise ValueError("Independent oracle sources changed after planning; restore their frozen content")
            planning = self.phase == "plan"
            if "defects" in baseline and baseline["defects"] != baseline_checks and not (planning and states == baseline["states"]):
                raise ValueError("Shared repair scope or reproduction changed after planning; review the baseline before editing")
            baseline = {**baseline, "oracles": oracles, "defects": baseline_checks}
            environment_path = safe_path(workspace, self.environment_dir)
            proof = self.smanager_get_value(key + ":reproduction", {}) if baseline_checks else {}
            current_proof = (bool(proof) and baseline_checks == proof["defects"] and proof["environment"] == sha256(environment_path / "receipt.json")
                             and all(safe_path(workspace, name).is_file() and sha256(safe_path(workspace, name)) == facts["sha256"] for name, facts in proof["evidence"].items()))
            if planning and (not baseline_checks or current_proof):
                self.smanager_set_value(key + ":baseline", baseline)
                return True, {"categories": 9, "items": len(identities), "next_action": "Implement generate/repair items; preserve reports and validate all changed sources."}
            if planning and (is_complete or states != baseline["states"]):
                raise ValueError("Run a planning Check on the original unmodified sources to reproduce the shared defect before editing")
            for name, paths in changes.items():
                missing = paths - covered.get(name, set())
                if not planning and missing:
                    raise ValueError(f"Unclassified source changes in {name}: {sorted(missing)[:20]}")
            directory.mkdir(parents=True, exist_ok=True)
            receipt = directory / "receipt.json"
            environment = prepared_environment(environment_path, self.smanager_get_value)
            environment = {name: value for name, value in environment.items()
                           if name not in {"PYTHONPATH", "VIRTUAL_ENV"} and not name.startswith(("UCAGENT", "ITGEN"))}
            environment["PATH"] = os.pathsep.join(part for part in environment.get("PATH", "").split(os.pathsep)
                                                  if part and not Path(part).resolve().is_relative_to(workspace))
            basis = {"plan": sha256(plan_path), "inputs": sha256(inputs / "receipt.json"), "states": states,
                     "sources": snapshots, "environment": sha256(environment_path / "receipt.json")}
            if action:
                self.smanager_set_value(key + ":receipt", None)
                owned_patches = self.smanager_get_value(key + ":patches", {})
                for relative, digest in owned_patches.items():
                    target = safe_path(workspace, relative)
                    if target.exists() and (not target.is_file() or sha256(target) != digest):
                        raise ValueError(f"Previously generated patch was edited; preserve it elsewhere before revalidation: {relative}")
                for relative in owned_patches:
                    safe_path(workspace, relative).unlink(missing_ok=True)
                self.smanager_set_value(key + ":patches", {})
            if planning or action:
                self._cancelled = False
                deadline = time.monotonic() + timeout
                results, evidence, patches = (list(proof["results"]), dict(proof["evidence"]), {}) if current_proof else ([], {}, {})
                with tempfile.TemporaryDirectory(prefix="act4-checklist-") as temporary:
                    passes = (True,) if planning else (True, False) if baseline_checks and not current_proof else (False,)
                    for reproducing in passes:
                        isolated = Path(temporary) / ("baseline" if reproducing else "candidate")
                        isolated.mkdir()
                        for name, root in roots.items():
                            target = safe_path(isolated, plan["repositories"][name])
                            target.parent.mkdir(parents=True, exist_ok=True)
                            patch_base = "HEAD"
                            if imported and name in imported["repositories"]:
                                baseline_root = safe_path(workspace, imported["repositories"][name]["baseline"])
                                clone_source_snapshot(baseline_root, target, directory, deadline, self._track)
                                git_text(target, "add", "--all")
                                patch_base = git_text(target, "write-tree")
                                for native in imported["repositories"][name]["removed"]:
                                    safe_path(target, native).unlink(missing_ok=True)
                            else:
                                clone_local(root, target, directory, deadline, self._track, require_submodules=name == "act4")
                            for native in (() if reproducing else changes[name]):
                                source, destination = safe_path(root, native), safe_path(target, native)
                                if source.exists():
                                    destination.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(source, destination)
                                elif destination.exists():
                                    destination.unlink()
                            if not reproducing and changes[name] and name != "act4":
                                git_text(target, "add", "--all")
                                patch = subprocess.run(
                                    ["git", "-C", str(target), "diff", "--cached", "--binary", "--full-index", patch_base],
                                    check=True, capture_output=True, timeout=30,
                                ).stdout
                                if not patch.strip() and not imported:
                                    raise ValueError(f"Empty dependency patch: {name}")
                                if patch.strip():
                                    patches[name] = patch
                        for relative in snapshots:
                            source = safe_path(workspace, relative)
                            if snapshots[relative] is not None and not any(source.is_relative_to(root) for root in roots.values()):
                                target = safe_path(isolated, relative)
                                target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(source, target)
                        environment["MISE_TRUSTED_CONFIG_PATHS"] = str(isolated)
                        environment["MISE_CEILING_PATHS"] = str(isolated.parent)
                        isolated_sources = {name: source_state(safe_path(isolated, plan["repositories"][name])) for name in roots}
                        for identity, check in operations:
                            if reproducing and identity not in baseline_checks:
                                continue
                            if self._cancelled or time.monotonic() >= deadline:
                                raise ValueError(f"Validation stopped before {identity}; inspect logs and retry")
                            location = f"{self.plan_file}#{identity}"
                            for relative in check["outputs"]:
                                target = safe_path(isolated, relative)
                                if target.exists():
                                    target.unlink()
                                target.parent.mkdir(parents=True, exist_ok=True)
                            log = (directory / "baseline" if reproducing else directory) / f"{identity}.log"
                            cwd = isolated if check["cwd"] == "." else safe_path(isolated, check["cwd"])
                            result = execute(check["argv"], cwd, log, max(1, int(deadline - time.monotonic())), self._track, environment)
                            results.append({"id": identity, "phase": "baseline" if reproducing else "candidate", **result})
                            evidence[log.relative_to(workspace).as_posix()] = {"sha256": sha256(log), "format": "text"}
                            if reproducing:
                                expected = baseline_checks[identity]["failure"]
                                if result["status"] != "failed" or result.get("exit_code") != expected["exit_code"] or expected["message"] not in log.read_text(errors="replace"):
                                    return False, {"error_code": "act4_shared_defect_not_reproduced", "error": f"{identity}: frozen baseline did not reproduce the declared defect", "artifact": str(log), "location": location,
                                                   "expected": {"exit_code": expected["exit_code"], "message": expected["message"][:240]},
                                                   "observed": {"status": result["status"], "exit_code": result.get("exit_code")},
                                                   "next_action": "Leave the shared input unchanged. Reference/reuse a sound source; report unresolved suspicions. Retry a repair only with an independent, reproducible defect."}
                                continue
                            if result.get("exit_code") != check["exit_code"] or result["status"] not in {"passed", "failed"}:
                                raise ValueError(f"{identity}: expected exit {check['exit_code']}, observed {result}; inspect {log}")
                            if check["kind"] == "negative" and not re.search(check["diagnostic"], log.read_text(errors="replace")):
                                raise ValueError(f"{identity}: failure did not match the intended negative diagnostic")
                            for relative, format_name in check["outputs"].items():
                                source = safe_path(isolated, relative)
                                facts = verify_output(source, format_name)
                                target = directory / "outputs" / identity / relative
                                target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(source, target)
                                evidence[target.relative_to(workspace).as_posix()] = facts
                        for name in roots:
                            if source_state(safe_path(isolated, plan["repositories"][name])) != isolated_sources[name]:
                                raise ValueError(f"Validators changed source files in {name}; fix sources before rerunning")
                if ({name: source_state(root) for name, root in roots.items()} != states or sha256(plan_path) != basis["plan"]
                        or sha256(inputs / "receipt.json") != basis["inputs"]
                        or sha256(environment_path / "receipt.json") != basis["environment"]
                        or any(sha256(safe_path(workspace, name)) != facts["sha256"] for name, facts in snapshots.items() if facts)):
                    raise ValueError("Sources changed during validation; reconcile changes and rerun")
                if planning:
                    self.smanager_set_value(key + ":reproduction", {"defects": baseline_checks, "environment": basis["environment"], "results": results, "evidence": evidence})
                    self.smanager_set_value(key + ":baseline", baseline)
                    return True, {"categories": 9, "items": len(identities), "reproduced": sorted(baseline_checks), "next_action": "Repair only the reproduced shared defects and run the same checks on the candidate."}
                for name in patches:
                    target = safe_path(patch_dir, f"{name}.patch")
                    if target.exists():
                        raise ValueError(f"Refusing to overwrite an unowned dependency patch: {target}; preserve it elsewhere and retry")
                owned_patches = {}
                for name, patch in patches.items():
                    patch_dir.mkdir(parents=True, exist_ok=True)
                    target = safe_path(patch_dir, f"{name}.patch")
                    target.write_bytes(patch)
                    relative = target.relative_to(workspace).as_posix()
                    owned_patches[relative] = sha256(target)
                    self.smanager_set_value(key + ":patches", dict(owned_patches))
                    evidence[relative] = {"sha256": owned_patches[relative], "format": "text"}
                write_json(receipt, {"basis": basis, "results": results, "evidence": evidence})
                self.smanager_set_value(key + ":receipt", sha256(receipt))
            if not receipt.is_file() or self.smanager_get_value(key + ":receipt") != sha256(receipt):
                raise ValueError('Run Check(stage_args={"action":"validate"}); no current authenticated evidence exists')
            data = json.loads(receipt.read_text(encoding="utf-8"))
            if data["basis"] != basis:
                raise ValueError("Source, plan or environment changed; rerun checklist validation")
            for relative, facts in data["evidence"].items():
                path = safe_path(workspace, relative)
                if path.is_relative_to(directory / "outputs"):
                    verify_output(path, facts["format"])
                if sha256(path) != facts["sha256"]:
                    raise ValueError(f"Validation evidence changed: {relative}")
            rows = ["", "## Asset checklist", "", "| Asset | Actions | Verification | Scope / follow-up | Evidence / patches |",
                    "| --- | --- | --- | --- | --- |"]
            unresolved = []
            for category, (label, _) in CATEGORIES.items():
                items = [item for item in plan["items"] if item["category"] == category]
                counts = Counter(item["action"] for item in items)
                labels = {"reuse": "reused", "reference": "referenced (identity only)", "generate": "generated", "repair": "repaired", "report": "reported", "not_applicable": "not applicable"}
                decisions = ", ".join(f"{labels[name]}: {count}" for name, count in sorted(counts.items()))
                active = sum(item["action"] in {*MODIFY, "reuse"} for item in items)
                reports = [item for item in items if item["action"] == "report"]
                unresolved.extend(item["id"] for item in reports if item["required"])
                notes = "; ".join(f"{item['id']}: {item['scope']} — {item['reason']}"
                                  + (f"; impact: {item['report']['impact']}; next: {item['report']['next_action']}" if item["report"] else "")
                                  for item in items)
                notes = " ".join(notes.split()).replace("|", "\\|")
                links = [f"[validation]({os.path.relpath(receipt, patch_dir.parent)})"]
                for name in sorted({item["repository"] for item in items if item["action"] in MODIFY} - {"act4", None}):
                    base = imported["repositories"][name]["baseline"] if imported and name in imported["repositories"] else states[name]["head"]
                    relative = (patch_dir / (name + ".patch")).relative_to(workspace).as_posix()
                    if relative in data["evidence"]:
                        links.append(f"[{name}.patch]({os.path.relpath(patch_dir / (name + '.patch'), patch_dir.parent)}) (base {base})")
                    else:
                        links.append(f"{name}: no content/mode difference from {base}; no patch needed")
                rows.append(f"| {label} | {decisions} | {active} checked; {len(reports)} reported, not verified | {notes} | {'; '.join(links)} |")
            table = "\n".join(rows) + "\n"
            if self.final_report:
                text = safe_path(workspace, self.final_report).read_text(encoding="utf-8")
                visible = re.sub(r"(?ms)^```[^\n]*\n.*?^```[^\n]*$", "", text)
                if visible.count(table.strip()) != 1 or len(re.findall(r"(?m)^## Asset checklist$", visible)) != 1:
                    raise ValueError(f"Include the exact current Asset checklist from {self.output_dir}/checklist.md once in the final report")
                for block in re.findall(r"(?ms)^```yaml\s*\n(.*?)^```\s*$", text):
                    summary = yaml.safe_load(block)
                    if (unresolved and isinstance(summary, dict) and isinstance(summary.get("scope_completion"), dict)
                            and summary["scope_completion"].get("scope_complete") is True):
                        raise ValueError("Required reported items remain unresolved; scope_completion cannot claim completeness")
            else:
                (directory / "checklist.md").write_text(table, encoding="utf-8")
            return True, {"categories": 9, "items": len(identities), "unresolved_required": unresolved,
                          "scope_complete": not unresolved, "receipt": str(receipt),
                          "next_action": "Copy checklist.md into final.md; checked means these recorded checks passed, not upstream approval or full coverage."}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError, yaml.YAMLError, ET.ParseError, re.error) as error:
            return False, {"error_code": "act4_asset_checklist", "error": str(error)[:2400], "artifact": location,
                           "next_action": "Read Guide_Doc/ACT4_Checker_Guide/ACT4AssetChecklistChecker.md; repair the named item and rerun Check. Do not change receipts or downgrade modified sources to reuse/report."}
