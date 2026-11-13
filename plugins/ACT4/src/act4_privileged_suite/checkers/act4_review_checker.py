"""Audit existing ACT4 assets and validate evidence-driven repairs and final reports."""

from __future__ import annotations

import difflib
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any

import yaml

from ucagent.checkers.base import Checker, UnityChipBatchTask
from ucagent.util.log import warning
from ..environment import prepared_environment

from .act4_asset_checker import ACT4AssetChecker
from .act4_asset_consistency import scan_systemverilog
from .act4_testcase_reachability import inspect_source


TOPICS = {
    "act4_compliance", "omissions", "redundancy", "coverpoint_quality",
    "test_coverage", "ci", "reproducibility", "contribution_quality",
}
SEMANTIC_QUESTIONS = {
    "act4_compliance": "Compare the declared assets and API usage with this commit's ACT4 requirements; adjudicate scanner diagnostics without discarding them.",
    "omissions": "Compare specification obligations with plans, mappings, generators and target configurations; identify missing exceptions and boundary cases.",
    "redundancy": "Compare test obligations, privilege, XLEN, configuration, setup and outcomes before recommending removal of tests or bins.",
    "coverpoint_quality": "Review sampling, guards, value domains, bins, ignore/illegal bins and cross dimensions against the specification.",
    "test_coverage": "Review stimulus and expected outcomes for each obligation; distinguish source linkage, compilation, execution and measured bin hits.",
    "ci": "Compare the selected jobs with the upstream CI matrix and explain applicability, exclusions and unexecuted checks.",
    "reproducibility": "Review specification provenance, tool versions, dependencies, seeds and commands for reproducibility.",
    "contribution_quality": "Review maintainability, native integration, generator independence and the provenance of generated assets.",
}
ASSET_KINDS = {"test_plans", "coverage", "generators", "test_cases", "mappings"}
PURPOSES = {"environment", "generation", "build", "reference_model", "coverage", "lint"}
DIAGNOSTIC_FILE_LIMIT = 50
DIAGNOSTIC_BYTE_LIMIT = 256 * 1024
OPTIONAL_SIMULATORS = {
    "questa": ("vlib", "vlog", "vsim"),
    "vcs": ("vcs",),
    "xcelium": ("xrun",),
}


def is_text(value: Any) -> bool:
    """Require a nonempty textual explanation or identity without scalar coercion."""
    return isinstance(value, str) and bool(value.strip())


def is_text_list(value: Any, allow_empty: bool = False) -> bool:
    """Validate lists of textual identities and evidence without accepting YAML scalars."""
    return isinstance(value, list) and (allow_empty or bool(value)) and all(is_text(item) for item in value)


def digest(value: Any) -> str:
    """Hash a canonical JSON projection without type coercion."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def evidence_fingerprint(tree: Path, scope: dict[str, Any]) -> str:
    """Bind native evidence to executable inputs while allowing scope commentary edits."""
    return digest({"tree": tree_state(tree), "assets": scope["assets"],
                   "targets": scope["targets"], "jobs": scope["jobs"],
                   "shared_assets": scope["shared_assets"],
                   "context_files": scope["context_files"],
                   "reference_scope": scope["reference_scope"],
                   "reference_files": scope["reference_files"]})


def safe_path(root: Path, value: str) -> Path:
    """Resolve an exact relative path, rejecting traversal and symlink escapes."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Paths must be nonempty relative strings")
    parts = PurePosixPath(value).parts
    if value.startswith("/") or ".." in parts or ".git" in parts or "\\" in value or any(char in value for char in "\n\r\t\"*?["):
        raise ValueError(f"Unsafe relative path: {value}")
    path = root / value
    if path.resolve() == root.resolve() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes its artifact directory: {value}")
    return path


def validate_references(workspace: Path, output: Path, files: Any, selections: Any) -> dict[str, list[str]]:
    """Validate source-only reference selections and return their physical text lines."""
    if not is_text_list(files, allow_empty=True) or len(set(files)) != len(files):
        raise ValueError("reference_files must list unique workspace-relative inputs; use [] and report missing sources")
    if not isinstance(selections, dict) or set(selections) != set(files):
        raise ValueError("reference_scope must select reviewed_lines and excluded_reason for every reference_files path")
    contents = {}
    for name in files:
        path = safe_path(workspace, name)
        if path.resolve().is_relative_to(output.resolve()) or not path.is_file() or path.is_symlink():
            raise ValueError(f"Reference inputs must be existing files outside the review output: {name}")
        physical = path.read_text(encoding="utf-8").splitlines()
        selection = selections[name]
        if not isinstance(selection, dict) or set(selection) != {"reviewed_lines", "excluded_reason"}:
            raise ValueError(f"reference_scope.{name} requires reviewed_lines and excluded_reason")
        ranges = selection["reviewed_lines"]
        if not isinstance(ranges, list) or not ranges:
            raise ValueError(f"reference_scope.{name}.reviewed_lines must select relevant nonempty line ranges")
        previous, selected = 0, 0
        for bounds in ranges:
            if not isinstance(bounds, list) or len(bounds) != 2 or any(type(number) is not int for number in bounds) or not previous < bounds[0] <= bounds[1] <= len(physical):
                raise ValueError(f"reference_scope.{name}: ranges must be ordered, nonoverlapping existing physical lines")
            previous = bounds[1]
            selected += bounds[1] - bounds[0] + 1
        if not isinstance(selection["excluded_reason"], str) or (selected < len(physical) and not is_text(selection["excluded_reason"])):
            raise ValueError(f"reference_scope.{name}: explain why the unselected sections are outside this review")
        contents[name] = physical
    return contents


def tree_state(root: Path, paths: list[str] | None = None) -> dict[str, Any]:
    """Fingerprint source bytes, executable modes, and safe relative symlinks."""
    if paths is None:
        paths = [str(path.relative_to(root)) for path in root.rglob("*")
                 if ".git" not in path.relative_to(root).parts and (path.is_symlink() or not path.is_dir())]
    result = {}
    for name in sorted(set(paths)):
        path = safe_path(root, name)
        if not path.exists() and not path.is_symlink():
            continue
        mode = path.lstat().st_mode
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute():
                raise ValueError(f"Absolute source symlink is not portable: {name}")
            content = target.encode()
            kind = "symlink"
        elif stat.S_ISREG(mode):
            content = path.read_bytes()
            kind = "file"
        else:
            raise ValueError(f"Unsupported source object: {name}")
        result[name] = {"sha256": hashlib.sha256(content).hexdigest(),
                        "mode": stat.S_IMODE(mode), "kind": kind}
    return result


def copy_sources(source: Path, target: Path, state: dict[str, Any]) -> None:
    """Copy only fingerprinted sources without Git metadata or shared hardlinks."""
    target.mkdir(parents=True, exist_ok=True)
    for name, identity in state.items():
        original = safe_path(source, name)
        destination = safe_path(target, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if identity["kind"] == "symlink":
            destination.symlink_to(os.readlink(original))
        else:
            shutil.copy2(original, destination)


def artifact_paths(root: Path, artifact: dict[str, Any]) -> list[Path]:
    """Resolve exact files or bounded relative patterns inside the execution checkout."""
    path = safe_path(root, artifact["path"])
    pattern = artifact.get("pattern")
    if pattern is None:
        return [path] if path.is_file() else []
    if not is_text(pattern) or Path(pattern).is_absolute() or any(
        part in {"..", ".git"} for part in PurePosixPath(pattern).parts
    ) or "\\" in pattern:
        raise ValueError("Artifact pattern must stay inside its relative directory")
    return sorted(safe_path(root, str(item.relative_to(root))) for item in path.glob(pattern) if item.is_file())


def execute_command(argv: list[str], cwd: Path, env: dict[str, str], log: Path,
                    timeout: int, append: bool = False, deadline: float | None = None) -> dict[str, Any]:
    """Run a real command with a bounded lifetime and preserve startup and timeout failures."""
    started = time.monotonic()
    result: dict[str, Any] = {"argv": argv, "started_at": datetime.now(timezone.utc).isoformat()}
    with log.open("ab" if append else "wb") as stream:
        if deadline is not None:
            timeout = min(timeout, max(0, deadline - time.monotonic()))
            if timeout <= 0:
                stream.write(b"Experiment time budget exhausted before command startup\n")
                return {**result, "status": "budget_exhausted", "reason": "Experiment time budget exhausted", "duration_seconds": 0}
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
                result.update(exit_code=code, status="passed" if code == 0 else "failed")
                if code:
                    result["reason"] = f"Command exited with status {code}; inspect the command log"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                result.update(status="timeout", reason="Command exceeded its declared timeout")
        except OSError as exc:
            stream.write(str(exc).encode())
            result.update(status="unavailable", reason=str(exc))
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def record_validation_failure(record: dict[str, Any], message: str) -> None:
    """Keep the native command failure primary and bound secondary artifact diagnostics."""
    if record["status"] == "passed":
        record["status"] = "failed"
    record.setdefault("reason", message)
    record["validation_error_count"] = record.get("validation_error_count", 0) + 1
    errors = record.setdefault("validation_errors", [])
    if len(errors) < 20:
        errors.append(message)


def resolve_validation_plan(tree: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Compare scoped jobs with frozen native target policy without claiming a full CI matrix."""
    plan: dict[str, Any] = {"targets": {}, "jobs": {}, "errors": [], "full_matrix": False,
                           "limitation": "Target policy and command alignment do not prove dynamic matrix selection or cross-suite coverage."}
    for target in scope["targets"]:
        safe_path(tree, target)
        matches = sorted(path for path in (tree / "config").glob("*/*/test_config.yaml") if path.parent.name == target)
        target_plan: dict[str, Any] = {"status": "unverified", "sources": {}, "reason": "No unique native target config was found"}
        plan["targets"][target] = target_plan
        if len(matches) != 1:
            continue
        config = matches[0]
        policy_path = safe_path(tree, str(config.parent.parent.relative_to(tree) / "ci.yaml"))
        runner_path = safe_path(tree, str(config.parent.relative_to(tree) / "run_cmd.txt"))
        if not policy_path.is_file() or not runner_path.is_file():
            target_plan["reason"] = "Target lacks ci.yaml or run_cmd.txt; execution is not established as native CI"
            continue
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if not isinstance(policy, dict) or type(policy.get("ci_enabled", True)) is not bool or any(
            not is_text_list(policy.get(field, []), allow_empty=True) for field in ("exclude_configs", "exclude_extensions")
        ):
            raise ValueError(f"Unsupported native CI policy: {policy_path.relative_to(tree)}; inspect its current schema before running")
        command = runner_path.read_text(encoding="utf-8").strip()
        if not command:
            raise ValueError(f"Empty native run command: {runner_path.relative_to(tree)}")
        for source in (config, policy_path, runner_path, tree / ".github/scripts/ci_config.py"):
            if source.is_file():
                name = str(source.relative_to(tree))
                target_plan["sources"][name] = hashlib.sha256(safe_path(tree, name).read_bytes()).hexdigest()
        enabled = policy.get("ci_enabled", True) and target not in policy.get("exclude_configs", [])
        target_plan.update(status="enabled" if enabled else "excluded", config=str(config.relative_to(tree)),
                           run_command=command, exclude_extensions=policy.get("exclude_extensions", []),
                           reason="Native target policy permits selection" if enabled else "Native CI disables this simulator or excludes this target")
    for job in scope["jobs"]:
        target_plan = plan["targets"][job["target"]]
        alignment = {"kind": "unverified", "reason": target_plan["reason"], "issues": []}
        plan["jobs"][job["id"]] = alignment
        argv = job.get("argv", [])
        if job["purpose"] == "environment":
            alignment.update(kind="environment", reason="Tool probe; not a CI correctness result")
        elif job["purpose"] == "lint":
            source_text = safe_path(tree, job["source"]).read_text(encoding="utf-8")
            command = shlex.join(argv)
            if argv and job["source"].startswith(".github/workflows/") and command in source_text:
                alignment.update(kind="native_subset", reason="Lint command occurs in the declared native workflow")
            else:
                alignment.update(kind="local_only", reason="Local lint is not evidence of the complete upstream lint workflow")
        elif target_plan["status"] != "unverified":
            extensions = {name for arg in argv if arg.startswith("EXTENSIONS=") for name in arg.split("=", 1)[1].split(",")}
            extensions = extensions or {scope["suite"]}
            if target_plan["status"] == "excluded":
                alignment["issues"].append("Target is excluded from native CI")
            if extensions & set(target_plan["exclude_extensions"]):
                alignment["issues"].append("Selected extensions include native CI exclusions")
            configs = [arg.split("=", 1)[1] for arg in argv if arg.startswith("CONFIG_FILES=")]
            if configs and configs != [target_plan["config"]]:
                alignment["issues"].append("Build configuration differs from the selected target")
            if job["purpose"] == "reference_model" and job["disposition"] == "run":
                positions = [index for index, arg in enumerate(argv) if Path(arg).name == "run_tests.py"]
                expected = shlex.split(re.sub(r"\{debug:[^{}]*\}", "", target_plan["run_command"]))
                if len(positions) != 1 or positions[0] + 1 >= len(argv) or shlex.split(re.sub(r"\{debug:[^{}]*\}", "", argv[positions[0] + 1])) != expected:
                    alignment["issues"].append("Final ELF runner differs from run_cmd.txt; ref_model_exe for signature generation is not the final runner")
                else:
                    alignment.update(kind="native_subset", reason="Final ELF runner matches the selected target's native command")
            elif job["purpose"] in {"generation", "build", "coverage"}:
                alignment["reason"] = "Target policy checked; command and dynamic selection still require source-grounded review"
        diagnostic = job.get("diagnostic_reason")
        if diagnostic is not None and not is_text(diagnostic):
            raise ValueError(f"Job {job['id']} diagnostic_reason must explain the intentional deviation")
        if diagnostic:
            alignment.update(kind="diagnostic", reason=diagnostic)
        elif alignment["issues"] and job["disposition"] == "run":
            plan["errors"].append({"job": job["id"], "issues": alignment["issues"],
                                   "next_action": "Use the native target/runner or explicitly declare diagnostic_reason; do not attribute this experiment to upstream CI"})
    return plan


def experiment_sources(root: Path, receipts: dict[str, str], index_digest: str | None = None) -> dict[str, str]:
    """Replay retained experiment identities before admitting their logs or source quotations."""
    allowed = {"experiments.json": index_digest} if index_digest else {}
    for name, identity in receipts.items():
        path = safe_path(root, name)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != identity:
            raise ValueError(f"Experiment evidence changed: {name}; run a new declared experiment")
        evidence = json.loads(content)
        allowed[name] = identity
        allowed.update(evidence["source_files"])
        for job in evidence["jobs"]:
            for field in ("log", "probe_log"):
                if field in job:
                    allowed[job[field]] = job[f"{field}_sha256"]
            allowed.update({item["path"]: item["sha256"] for item in job.get("artifacts", []) + job.get("diagnostics", [])})
    for name, identity in allowed.items():
        if hashlib.sha256(safe_path(root, name).read_bytes()).hexdigest() != identity:
            raise ValueError(f"Experiment source or artifact changed: {name}; preserve completed experiments and create a new ID")
    return allowed


class ACT4ReviewChecker(Checker):
    """Validate review and repair completeness while preserving unresolved findings."""

    accepted_stage_args = ("run_commands", "refresh_tools", "experiment")

    def __init__(self, phase: str, suite: str, review_dir: str,
                 act4_root: str = "riscv-arch-test", batch_size: int = 12,
                 max_stalled_checks: int = 8, max_experiments: int = 6,
                 max_experiment_seconds: int = 1800, **kwargs: Any) -> None:
        """Store stage configuration without inspecting the live workspace."""
        super().__init__()
        kwargs.pop("cfg", None)
        if kwargs or phase not in {"plan", "audit", "repair", "final"}:
            raise ValueError("Invalid ACT4 review phase or checker arguments")
        self.phase, self.suite = phase, suite
        self.review_dir, self.act4_root = review_dir, act4_root
        if type(batch_size) is not int or not 1 <= batch_size <= 50:
            raise ValueError("Review batch_size must be an integer from 1 to 50")
        if type(max_stalled_checks) is not int or max_stalled_checks < 1:
            raise ValueError("Review max_stalled_checks must be a positive integer")
        self.batch_size = batch_size
        self.max_stalled_checks = max_stalled_checks
        if type(max_experiments) is not int or not 1 <= max_experiments <= 50 or type(max_experiment_seconds) is not int or not 1 <= max_experiment_seconds <= 3600:
            raise ValueError("Review experiment limits require max_experiments in 1..50 and max_experiment_seconds in 1..3600")
        self.max_experiments, self.max_experiment_seconds = max_experiments, max_experiment_seconds
        self._stalled_checks = 0
        self._last_stall_signature = None
        self.batch = UnityChipBatchTask(f"act4_review_{phase}", self)
        self._review_tasks: dict[str, Any] = {}
        self._review_completed: set[str] = set()

    def get_template_data(self) -> dict[str, Any]:
        """Expose only the cached, source-validated review batch progress."""
        return self.batch.get_template_data("REVIEW_TOTAL", "REVIEW_COMPLETED", "REVIEW_CURRENT")

    def _state(self) -> dict[str, Any]:
        """Access persisted baseline, evidence fingerprints, and candidate preparation state."""
        if self.stage_manager is None:
            raise ValueError("Review requires an active stage manager; restart this workflow")
        key = f"act4_review:{self.review_dir}:{self.suite}"
        state = self.stage_manager.get_data(key)
        if state is None:
            state = {}
            self.stage_manager.set_data(key, state)
        return state

    def _write(self, name: str, data: Any) -> None:
        """Atomically publish a checker-owned JSON evidence artifact."""
        target = safe_path(self.output, name)
        descriptor, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self, name: str) -> dict[str, Any]:
        """Read a canonical YAML/JSON mapping with actionable schema failures."""
        path = safe_path(self.output, name)
        if not path.is_file():
            raise ValueError(f"Create {path} using Guide_Doc/ACT4_Extension_Review_Guide.md")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError(f"{path}: expected a schema_version: 1 mapping")
        return data

    def _isa_plan(self, state: dict[str, Any], is_complete: bool) -> dict[str, Any]:
        """Freeze an ISA-only test design before asset review and preserve its original identity."""
        self._validation_section, self._validation_location = "isa_plan", "isa-plan.yaml"
        plan_path = safe_path(self.output, "isa-plan.yaml")
        if plan_path.is_symlink():
            raise ValueError("isa-plan.yaml must be a regular file")
        plan = self._load("isa-plan.yaml")
        if plan.get("suite") != self.suite or not is_text(plan.get("target_context")):
            raise ValueError("isa-plan.yaml needs this suite and target_context from the user, not existing tests or CI")
        workspace = Path(self.workspace)
        if is_text_list(plan.get("reference_files"), allow_empty=True):
            for name in plan["reference_files"]:
                if safe_path(workspace, name).resolve().is_relative_to(self.source.resolve()):
                    raise ValueError("ISA-only planning cannot cite the asset input directory; supply ISA originals in a separate reference directory")
        contents = validate_references(workspace, self.output, plan.get("reference_files"), plan.get("reference_scope"))
        references = tree_state(workspace, plan["reference_files"])
        frozen = self.output / "isa-references"
        identity = {"references": references, "reference_scope": plan["reference_scope"], "target_context": plan["target_context"]}
        if frozen.is_symlink():
            raise ValueError("ISA reference snapshot must not be a symlink")
        if "isa_inputs" not in state:
            if self.phase != "plan" or frozen.exists():
                raise ValueError("Complete review_plan before inspecting assets or validating execution plans; use a fresh output for a new ISA scope")
            copy_sources(workspace, frozen, references)
            state["isa_inputs"] = identity
        if state["isa_inputs"] != identity or tree_state(frozen) != references:
            raise ValueError("ISA scope or frozen sources changed; start a new review output rather than rewriting the independent baseline")
        allowed = {f"isa-references/{name}": item["sha256"] for name, item in references.items()}
        sources = {}
        for name, physical in contents.items():
            selected = plan["reference_scope"][name]["reviewed_lines"]
            for first, end in selected:
                for start in range(first, end + 1, 80):
                    last = min(start + 79, end)
                    sources[f"isa:{name}:{start}-{last}"] = {"path": f"isa-references/{name}", "lines": [start, last], "excluded": False}
            previous = 0
            for first, end in selected + [[len(physical) + 1, len(physical) + 1]]:
                if first > previous + 1:
                    sources[f"excluded:{name}:{previous + 1}-{first - 1}"] = {
                        "path": f"isa-references/{name}", "lines": [previous + 1, first - 1], "excluded": True}
                previous = end
        context = {"schema_version": 1, "source_files": allowed, "sources": sources}
        if "isa_context" not in state:
            self._write("isa-plan-context.json", context)
            state["isa_context"] = digest(context)
        if digest(self._load("isa-plan-context.json")) != state["isa_context"] or digest(context) != state["isa_context"]:
            raise ValueError("isa-plan-context.json changed; restore the original ISA context")
        if not is_text_list(plan.get("limitations"), allow_empty=True) or (not references and not plan["limitations"]):
            raise ValueError("ISA plan limitations must explain missing ISA sources; never claim completeness without sources")
        requirements = plan.get("requirements")
        if not isinstance(requirements, list):
            raise ValueError("Write ISA-derived requirements after reading isa-plan-context.json; each needs I<number>, applicability, stimulus, observation and basis")
        if not requirements and not plan["limitations"]:
            raise ValueError("An empty ISA design requires limitations explaining missing sources or the absence of applicable requirements")
        indexed, source_lines = {}, {}
        for item in requirements:
            if not isinstance(item, dict) or not is_text(item.get("id")) or not re.fullmatch(r"I[0-9]+", item["id"]) or item["id"] in indexed:
                raise ValueError("ISA requirements need unique I<number> IDs")
            if not all(is_text(item.get(field)) for field in ("requirement", "applicability", "stimulus", "observation")):
                raise ValueError(f"ISA requirement {item['id']} needs requirement, applicability, stimulus and observation")
            self._citations(item.get("basis"), allowed, source_lines)
            for citation in item["basis"]:
                if not any(not block["excluded"] and block["path"] == citation["path"] and
                           max(block["lines"][0], citation["lines"][0]) <= min(block["lines"][1], citation["lines"][1]) for block in sources.values()):
                    raise ValueError(f"ISA requirement {item['id']} must cite selected ISA lines, not an excluded section")
            indexed[item["id"]] = item
        reviews = plan.get("source_reviews")
        if not isinstance(reviews, list):
            raise ValueError("source_reviews must assess every selected and excluded ISA source block")
        reviewed, linked = set(), set()
        for item in reviews:
            if not isinstance(item, dict) or not is_text(item.get("source")) or item["source"] not in sources or item["source"] in reviewed:
                raise ValueError("source_reviews must reference each isa-plan-context.json source ID exactly once")
            block = sources[item["source"]]
            if not is_text_list(item.get("requirements"), allow_empty=True) or not set(item["requirements"]) <= indexed.keys() or not is_text(item.get("reason")):
                raise ValueError("Each ISA source review needs known requirement IDs, or an empty list with a source-grounded exclusion reason")
            self._citations(item.get("basis"), allowed, source_lines)
            if not any(citation["path"] == block["path"] and block["lines"][0] <= citation["lines"][0] <= citation["lines"][1] <= block["lines"][1] for citation in item["basis"]):
                raise ValueError(f"ISA source review must quote its own source block: {item['source']}")
            if block["excluded"] and item["requirements"]:
                raise ValueError("An excluded ISA section cannot introduce requirements; correct the scope in a new review")
            for name in item["requirements"]:
                if not any(citation["path"] == block["path"] and max(citation["lines"][0], block["lines"][0]) <= min(citation["lines"][1], block["lines"][1]) for citation in indexed[name]["basis"]):
                    raise ValueError(f"ISA requirement {name} has no basis in its linked source block")
            reviewed.add(item["source"])
            linked.update(item["requirements"])
        if reviewed != sources.keys() or linked != indexed.keys():
            raise ValueError(f"Complete ISA source_reviews and link all requirements; missing sources: {sorted(sources.keys() - reviewed)[:12]}, requirements: {sorted(indexed.keys() - linked)[:12]}")
        snapshot = {"schema_version": 1, "plan": plan, "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "inputs": identity}
        if "isa_plan" in state:
            if digest(snapshot) != state["isa_plan"] or self._load("isa-plan-accepted.json") != snapshot:
                raise ValueError("Accepted ISA plan changed; retain its original requirements and record later corrections in review obligations")
        elif self.phase == "plan" and is_complete:
            if any((self.output / name).exists() for name in ("baseline.json", "validation-plan.json", "evidence-before.json")):
                raise ValueError("ISA planning must finish before asset validation; restart with a fresh output")
            self._write("isa-plan-accepted.json", snapshot)
            state["isa_plan"] = digest(snapshot)
        elif self.phase != "plan":
            raise ValueError("Complete review_plan to accept the independent ISA design before reviewing assets")
        self._validation_section, self._validation_location = "scope", "scope.yaml"
        return plan

    def _baseline(self, state: dict[str, Any], scope: dict[str, Any]) -> None:
        """Freeze actual dirty or clean source state and reject subsequent input drift."""
        if self.source.is_symlink() or not self.source.is_dir():
            raise ValueError("Review input must be an existing workspace-relative directory, not a symlink")
        git_input = (self.source / ".git").exists()
        if git_input and not (self.source / ".git").is_dir():
            raise ValueError("Git review input must be an independent clone, not a shared worktree")
        repositories = [self.source] if git_input else []
        paths = {name for values in scope["assets"].values() for name in values} | set(scope["context_files"])
        submodules = []
        for repository in repositories:
            index = subprocess.check_output(
                ["git", "-C", str(repository), "ls-files", "--stage", "-z"],
                env=self.environment,
            ).decode().split("\0")
            for entry in filter(None, index):
                metadata, name = entry.split("\t", 1)
                mode, _, stage = metadata.split()
                if stage != "0":
                    raise ValueError(f"Resolve the input merge conflict before reviewing: {name}")
                if mode == "160000" and not (safe_path(repository, name) / ".git").exists():
                    raise ValueError(f"Initialize the ACT4 submodule before reviewing: {name}")
            entries = subprocess.check_output(
                ["git", "-C", str(repository), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                env=self.environment,
            ).decode().split("\0")
            for name in filter(None, entries):
                path = safe_path(repository, name)
                if path.is_dir() and not path.is_symlink():
                    if not (path / ".git").exists():
                        raise ValueError(f"Initialize the ACT4 submodule before reviewing: {path}")
                    repositories.append(path)
                    submodules.append(str(path.relative_to(self.source)))
                else:
                    paths.add(str(path.relative_to(self.source)))
        current = tree_state(self.source, sorted(paths) if git_input else None)
        head = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True, env=self.environment).strip() if git_input else None
        module_heads = {name: subprocess.check_output(["git", "-C", str(self.source / name), "rev-parse", "HEAD"], text=True, env=self.environment).strip()
                        for name in submodules}
        references = tree_state(Path(self.workspace), scope["reference_files"])
        identity = {"input": {"root": self.act4_root, "kind": "git" if git_input else "directory"},
                    "head": head, "submodules": module_heads, "files": current,
                    "references": references}
        baseline = self.output / "baseline"
        reference_root = self.output / "references"
        if baseline.is_symlink() or reference_root.is_symlink():
            raise ValueError("Frozen input directories must not be symlinks")
        if "baseline" not in state:
            if self.phase != "audit" or baseline.exists():
                raise ValueError("Baseline trust state is missing; start a new review output in review_audit")
            copy_sources(self.source, baseline, current)
            copy_sources(Path(self.workspace), reference_root, references)
            state["baseline"] = identity
            self._write("baseline.json", {"schema_version": 1, **identity})
        if identity != state["baseline"] or tree_state(baseline) != current:
            raise ValueError("Input checkout or frozen baseline changed; restore it or start a new review")
        if tree_state(reference_root) != references:
            raise ValueError("Frozen reference inputs changed; restore them or start a new review")
        if self._load("baseline.json") != {"schema_version": 1, **identity}:
            raise ValueError("baseline.json changed; restore the original checker-generated baseline report")

    def _scope(self) -> dict[str, Any]:
        """Validate exact existing assets and a documented, target-specific CI matrix."""
        scope = self._load("scope.yaml")
        if scope.get("suite") != self.suite or not isinstance(scope.get("assets"), dict):
            raise ValueError("scope.yaml must identify this suite and its assets")
        assets = scope["assets"]
        if set(assets) != ASSET_KINDS:
            raise ValueError(f"scope.assets requires exactly {sorted(ASSET_KINDS)}")
        for kind, paths in assets.items():
            if not is_text_list(paths, allow_empty=True) or len(set(paths)) != len(paths):
                raise ValueError(f"scope.assets.{kind} must list unique exact paths")
            for name in paths:
                if not safe_path(self.source, name).is_file():
                    raise ValueError(f"Missing review asset: {name}; use [] and report an omission")
        if not any(assets.values()):
            raise ValueError("Review requires existing test assets; use the generation workflow for a new suite")
        context = scope.get("context_files")
        if not is_text_list(context, allow_empty=True) or len(context) != len(set(context)):
            raise ValueError("scope.context_files must list unique ACT4-relative reference-only files; use [] when none")
        if set(context).intersection(name for paths in assets.values() for name in paths):
            raise ValueError("A path cannot be both a reviewed asset and a reference-only context file")
        for name in context:
            if not safe_path(self.source, name).is_file():
                raise ValueError(f"Missing context file: {name}; locate the actual shared definition")
        shared = scope.get("shared_assets")
        if not isinstance(shared, list):
            raise ValueError("scope.shared_assets must list shared paths, consumer suites and their review boundary; use [] when none")
        seen_shared = set()
        for item in shared:
            if not isinstance(item, dict) or not is_text(item.get("path")) or item["path"] in seen_shared:
                raise ValueError("shared_assets requires unique path mappings")
            seen_shared.add(item["path"])
            if not safe_path(self.source, item["path"]).is_file() or not (item["path"] in context or any(item["path"] in paths for paths in assets.values())):
                raise ValueError("Shared assets must be existing declared assets or context_files")
            if not is_text_list(item.get("consumers")) or not is_text(item.get("boundary")):
                raise ValueError("Shared assets require consumers and boundary explaining reviewed and excluded suites")
        if set(context) - seen_shared:
            raise ValueError(f"Declare the review boundary for context_files in shared_assets: {sorted(set(context) - seen_shared)}")
        for field in ("targets", "references", "discovery"):
            if not is_text_list(scope.get(field)):
                raise ValueError(f"scope.{field} must document the complete review boundary as nonempty strings")
        validate_references(Path(self.workspace), self.output, scope.get("reference_files"), scope.get("reference_scope"))
        plan = self._load("isa-plan-accepted.json")["plan"]
        for name in plan["reference_files"]:
            if scope["reference_scope"].get(name) != plan["reference_scope"][name]:
                raise ValueError(f"scope must retain the independent ISA selection: {name}; add further references without narrowing the original plan")
        jobs = scope.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            raise ValueError("scope.jobs must cover native CI or explicitly document why it is unavailable")
        names = set()
        matrix = set()
        for job in jobs:
            if not isinstance(job, dict) or not is_text(job.get("id")) or not re.fullmatch(r"[A-Za-z0-9_-]+", job["id"]):
                raise ValueError("Each CI job needs a unique safe id")
            if job["id"] in names:
                raise ValueError(f"Duplicate CI job: {job['id']}")
            names.add(job["id"])
            for field in ("target", "source", "purpose"):
                if not isinstance(job.get(field), str) or not job[field].strip():
                    raise ValueError(f"CI job {job['id']} needs {field}")
            if not safe_path(self.source, job["source"]).is_file():
                raise ValueError(f"CI job {job['id']} source must name an existing CI/documentation file")
            if job["target"] not in scope["targets"]:
                raise ValueError(f"CI job {job['id']} has an undeclared target")
            if job["purpose"] not in PURPOSES:
                raise ValueError(f"CI purpose must be one of {sorted(PURPOSES)}")
            matrix.add((job["target"], job["purpose"]))
            if not is_text_list(job.get("needs", []), allow_empty=True) or len(set(job.get("needs", []))) != len(job.get("needs", [])):
                raise ValueError(f"CI job {job['id']} needs must list unique prerequisite job IDs")
            if job.get("disposition") not in {"run", "not_applicable", "unavailable"}:
                raise ValueError("CI disposition must be run, not_applicable, or unavailable")
            if "optional_tool" in job:
                if job["optional_tool"] not in OPTIONAL_SIMULATORS or job["purpose"] not in {"coverage", "environment"}:
                    raise ValueError("optional_tool must identify questa/vcs/xcelium for a coverage or simulator environment job")
                if job["disposition"] != "run" or "install" in job:
                    raise ValueError("Optional simulator jobs must use disposition: run without install; availability comes from environment.json")
            if job["purpose"] == "environment" and job["disposition"] != "run":
                raise ValueError("Environment jobs must run a real probe before reporting unavailable tools")
            if job["disposition"] != "run":
                if not isinstance(job.get("reason"), str) or not job["reason"].strip():
                    raise ValueError("Unexecuted CI jobs need a concrete reason and impact")
                continue
            commands = [job.get("probe")] if job["purpose"] == "environment" else [job.get("argv")]
            if "install" in job:
                if job["purpose"] != "environment":
                    raise ValueError("Only environment jobs may declare install")
                commands.append(job["install"])
            elif job["purpose"] == "environment" and not is_text(job.get("reason")):
                raise ValueError("An environment without an installer needs the concrete missing media/license and recovery action")
            for argv in commands:
                if not is_text_list(argv):
                    raise ValueError("CI commands must be nonempty argument lists, not shell strings")
                if Path(argv[0]).name in {"true", "false", "echo", "printf"}:
                    raise ValueError("CI commands must run the actual native checks, not placeholder commands")
            if "expected_output" in job:
                if job["purpose"] != "environment" or not is_text(job["expected_output"]):
                    raise ValueError("expected_output is a nonempty environment probe regex")
                re.compile(job["expected_output"])
            if type(job.get("timeout_seconds")) is not int or not 1 <= job["timeout_seconds"] <= 3600:
                raise ValueError("CI timeout_seconds must be an integer in 1..3600")
            if job.get("cwd", ".") != ".":
                safe_path(self.source, job["cwd"])
            diagnostics = job.get("diagnostics", [])
            if not isinstance(diagnostics, list):
                raise ValueError(f"CI job {job['id']} diagnostics must list relative path/pattern mappings")
            for diagnostic in diagnostics:
                if not isinstance(diagnostic, dict) or set(diagnostic) - {"path", "pattern"}:
                    raise ValueError("Diagnostic selectors accept only path and optional pattern")
                safe_path(self.source, diagnostic.get("path"))
                artifact_paths(self.source, diagnostic)
            artifacts = job.get("artifacts", [])
            if not isinstance(artifacts, list):
                raise ValueError("CI artifacts must list exact paths and kinds")
            for artifact in artifacts:
                if not isinstance(artifact, dict) or artifact.get("kind") not in {"coverage", "elf", "signature", "results", "generated", "other"}:
                    raise ValueError("Each CI artifact needs a path and kind")
                safe_path(self.source, artifact.get("path"))
                artifact_paths(self.source, artifact)
                if type(artifact.get("min_count", 1)) is not int or not 1 <= artifact.get("min_count", 1) <= 100000:
                    raise ValueError("Artifact min_count must be an integer in 1..100000")
                for field in ("pass_pattern", "fail_pattern"):
                    if field in artifact:
                        if artifact["kind"] != "results" or not is_text(artifact[field]):
                            raise ValueError(f"{field} requires a nonempty results regex")
                        expression = re.compile(artifact[field])
                        if expression.search(""):
                            raise ValueError("Result patterns must not match empty text")
            if job["purpose"] == "build" and not any(item["kind"] == "elf" for item in artifacts):
                raise ValueError(f"Build {job['id']} must declare nonempty ELF artifacts")
            if job["purpose"] in {"reference_model", "coverage"}:
                if not is_text_list(job.get("elf_inputs")):
                    raise ValueError(f"Execution {job['id']} must declare elf_inputs from prerequisite build jobs")
                kind = "results" if job["purpose"] == "reference_model" else "coverage"
                required = [item for item in artifacts if item["kind"] == kind]
                if not required or (kind == "results" and any(
                    not all(field in item for field in ("pass_pattern", "fail_pattern")) for item in required
                )):
                    raise ValueError(f"Execution {job['id']} must declare {kind} evidence; results need pass_pattern and fail_pattern")
        expected = {(target, purpose) for target in scope["targets"]
                    for purpose in PURPOSES}
        if matrix != expected:
            raise ValueError(f"Declare every CI lane or explain its unavailability: {sorted(expected - matrix)}")
        ordered = []
        remaining = list(jobs)
        ancestors: dict[str, set[str]] = {}
        while remaining:
            ready = [job for job in remaining if set(job.get("needs", [])) <= set(ancestors)]
            if not ready:
                raise ValueError("CI needs contains a cycle, self reference, or unknown job ID")
            for job in ready:
                parents = set(job.get("needs", []))
                ancestors[job["id"]] = parents | {parent for name in parents for parent in ancestors[name]}
                ordered.append(job)
                remaining.remove(job)
        indexed = {job["id"]: job for job in jobs}
        for job in ordered:
            if "optional_tool" not in job and any("optional_tool" in indexed[name] for name in ancestors[job["id"]]):
                raise ValueError(f"Required job {job['id']} must not depend on an optional simulator; keep generation/build/model/lint independent")
            if job["disposition"] != "run" or job["purpose"] == "environment":
                continue
            prerequisites = [indexed[name] for name in ancestors[job["id"]]]
            for purpose in ({"environment", "generation"} if job["purpose"] == "build" else {"environment"}):
                if not any(item["purpose"] == purpose and item["target"] == job["target"] for item in prerequisites):
                    raise ValueError(f"CI job {job['id']} must depend on its target's {purpose} jobs")
            for name in job.get("elf_inputs", []):
                provider = indexed.get(name, {})
                if name not in ancestors[job["id"]] or provider.get("purpose") != "build" or provider.get("target") != job["target"]:
                    raise ValueError(f"ELF provider {name} must be a prerequisite build for {job['target']}")
        plan = resolve_validation_plan(self.source, scope)
        self._write("validation-plan.json", plan)
        if plan["errors"]:
            raise ValueError(f"Validation plan conflicts with native CI: {plan['errors']}; inspect validation-plan.json before executing")
        return scope

    def _environment(self, state: dict[str, Any], refresh: bool) -> dict[str, Any]:
        """Probe optional simulators before scope authoring and retain tamper-evident smoke results."""
        if state.get("environment") and not refresh:
            data = self._load("environment.json")
            if digest(data) != state["environment"]:
                raise ValueError("environment.json changed; use Check(stage_args={\"refresh_tools\": true}) in review_audit")
            for tool in data["tools"].values():
                for attempt in tool["attempts"]:
                    if hashlib.sha256(safe_path(self.output, attempt["log"]).read_bytes()).hexdigest() != attempt["sha256"]:
                        raise ValueError("Optional simulator probe log changed; refresh_tools in review_audit")
            return data
        if self.phase not in {"plan", "audit"}:
            raise ValueError("Start in review_plan to probe optional tools before reviewing assets")
        environment = dict(self.environment)
        environment["PATH"] = str(self.output / "tools/bin") + os.pathsep + environment.get("PATH", "")
        data = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "tools": {}}
        smoke = ('module review_smoke;\nint value;\n'
                 'covergroup sample_cg; cp: coverpoint value { bins one = {1}; } endgroup\n'
                 'sample_cg coverage_sample;\ninitial begin coverage_sample = new; value = 1; '
                 'coverage_sample.sample(); $display("ACT4_REVIEW_SMOKE_PASS"); $finish; end\nendmodule\n')
        for tool, binaries in OPTIONAL_SIMULATORS.items():
            resolved = {name: shutil.which(name, path=environment["PATH"]) for name in binaries}
            record = {"executables": resolved, "attempts": [], "status": "not_found",
                      "impact": "Measured coverage using this simulator is unavailable; source review and independent jobs continue."}
            data["tools"][tool] = record
            missing = [name for name, location in resolved.items() if location is None]
            if missing:
                record["reason"] = "Executables not on PATH: " + ", ".join(missing)
                continue
            with tempfile.TemporaryDirectory(prefix=f"probe-{tool}-", dir=self.output) as temporary:
                directory = Path(temporary)
                (directory / "smoke.sv").write_text(smoke, encoding="utf-8")
                if tool == "questa":
                    commands = [[resolved["vlib"], "work"], [resolved["vlog"], "-sv", "smoke.sv"],
                                [resolved["vsim"], "-c", "-coverage", "work.review_smoke", "-do", "run -all; quit -f"]]
                elif tool == "vcs":
                    commands = [[resolved["vcs"], "-full64", "-sverilog", "smoke.sv", "-o", "smoke"], [str(directory / "smoke")]]
                else:
                    commands = [[resolved["xrun"], "-64bit", "-sv", "-coverage", "all", "smoke.sv"]]
                for index, argv in enumerate(commands):
                    log_name = f"environment-{tool}-{index}.log"
                    log = safe_path(self.output, log_name)
                    attempt = execute_command(argv, directory, environment, log, 20)
                    attempt.update(log=log_name, sha256=hashlib.sha256(log.read_bytes()).hexdigest())
                    record["attempts"].append(attempt)
                    if attempt["status"] != "passed":
                        break
                success = len(record["attempts"]) == len(commands) and all(item["status"] == "passed" for item in record["attempts"])
                success = success and "ACT4_REVIEW_SMOKE_PASS" in log.read_text(errors="replace")
                record["status"] = "available" if success else "unusable"
                record["reason"] = ("SystemVerilog covergroup compile and simulation smoke passed; native ACT4 coverage still requires its own job."
                                    if success else "Compilation or simulation smoke failed/timed out or did not finish; inspect probe logs for license/tool configuration errors.")
        self._write("environment.json", data)
        state["environment"] = digest(data)
        return data

    def _evidence(self, state: dict[str, Any], scope: dict[str, Any], tree: Path,
                  label: str, run_commands: bool, deadline: float | None = None) -> dict[str, Any]:
        """Reuse asset checks and record real isolated command results bound to input bytes."""
        fingerprint = digest({"sources": evidence_fingerprint(tree, scope),
                              "references": state["baseline"]["references"], "environment": state["environment"],
                              "isa_plan": state["isa_plan"]})
        evidence_path = safe_path(self.output, f"evidence-{label}.json")
        cached = state.get(f"evidence-{label}")
        if not run_commands:
            if not cached or not evidence_path.exists() or digest(json.loads(evidence_path.read_text())) != cached:
                raise ValueError(f"Run Check(stage_args={{\"run_commands\": true}}) to collect {label} evidence")
            evidence = json.loads(evidence_path.read_text())
            if evidence["fingerprint"] != fingerprint:
                raise ValueError(f"{label} evidence is stale; rerun the declared commands")
            for job in evidence["jobs"]:
                if "log" in job and hashlib.sha256(safe_path(self.output, job["log"]).read_bytes()).hexdigest() != job["log_sha256"]:
                    raise ValueError(f"Command log changed: {job['log']}; rerun validation")
                if "probe_log" in job and hashlib.sha256(safe_path(self.output, job["probe_log"]).read_bytes()).hexdigest() != job["probe_log_sha256"]:
                    raise ValueError(f"Environment probe log changed: {job['probe_log']}; rerun validation")
                for artifact in job.get("artifacts", []) + job.get("diagnostics", []):
                    if hashlib.sha256(safe_path(self.output, artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
                        raise ValueError(f"Command artifact changed: {artifact['path']}; rerun validation")
            return evidence
        validation_plan = resolve_validation_plan(tree, scope)
        if validation_plan["errors"]:
            raise ValueError(f"Candidate validation plan conflicts with native CI: {validation_plan['errors']}")
        results = []
        missing = sorted({name for names in scope["assets"].values() for name in names
                          if not safe_path(tree, name).is_file()})
        passed = not missing
        for mapping in scope["assets"]["mappings"] or [None]:
            checker = ACT4AssetChecker(
                suite=self.suite, act4_root=str(tree),
                coverage_files=[str(tree / name) for name in scope["assets"]["coverage"]],
                coverage_context_files=[str(tree / name) for name in scope["context_files"] if Path(name).suffix.lower() in {".sv", ".svh"}],
                discover_coverage=False,
                generator_files=[str(tree / name) for name in scope["assets"]["generators"]],
                mapping=str(tree / mapping) if mapping else None,
                compare_source_mapping=False,
                assets=[{"path": str(tree / name)} for name in sorted({
                    name for names in scope["assets"].values() for name in names})],
                require_standalone_generator=True,
                require_priv_coverage_semantics=True,
            ).set_workspace(str(self.workspace))
            check_passed, result = checker.do_check()
            passed = passed and check_passed
            results.append(result)
        findings: list[dict[str, Any]] = []
        coverage = scan_systemverilog([tree / name for name in scope["assets"]["coverage"] if (tree / name).is_file()], findings)
        points = sorted(f"{group}/{cp}" for group, data in coverage["groups"].items() for cp in data["coverpoints"])
        reachability = {}
        duplicates: dict[str, list[str]] = {}
        for name in {name for paths in scope["assets"].values() for name in paths}:
            path = tree / name
            if path.is_file():
                duplicates.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), []).append(name)
        evidence = {"schema_version": 1, "fingerprint": fingerprint,
                    "act4_head": state["baseline"]["head"],
                    "input": state["baseline"]["input"],
                    "environment": self._load("environment.json"), "targets": scope["targets"],
                    "static_passed": passed, "static": results, "missing_assets": missing, "coverpoints": points,
                    "reachability": reachability, "validation_plan": validation_plan,
                    "duplicate_assets": [sorted(names) for names in duplicates.values() if len(names) > 1], "jobs": []}
        with tempfile.TemporaryDirectory(prefix=f"run-{label}-", dir=self.output) as temporary:
            execution = Path(temporary) / "checkout"
            if state["baseline"]["input"]["kind"] == "git":
                subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(self.source), str(execution)], check=True, capture_output=True, env=self.environment)
                subprocess.run(["git", "-C", str(execution), "read-tree", state["baseline"]["head"]], check=True, capture_output=True, env=self.environment)
                subprocess.run(["git", "-C", str(execution), "update-ref", "--no-deref", "HEAD", state["baseline"]["head"]], check=True, capture_output=True, env=self.environment)
            for name, head in state["baseline"]["submodules"].items():
                module = safe_path(execution, name)
                subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(self.source / name), str(module)], check=True, capture_output=True, env=self.environment)
                subprocess.run(["git", "-C", str(module), "read-tree", head], check=True, capture_output=True, env=self.environment)
                subprocess.run(["git", "-C", str(module), "update-ref", "--no-deref", "HEAD", head], check=True, capture_output=True, env=self.environment)
            copy_sources(tree, execution, tree_state(tree))
            repositories = [execution, *(execution / name for name in state["baseline"]["submodules"])] if state["baseline"]["input"]["kind"] == "git" else []
            for repository in reversed(repositories):
                subprocess.run(["git", "-C", str(repository), "add", "--force", "--all"], check=True, capture_output=True, env=self.environment)
            tools = safe_path(self.output, "tools")
            (tools / "bin").mkdir(parents=True, exist_ok=True)
            environment = {**self.environment, "PATH": str(tools / "bin") + os.pathsep + self.environment.get("PATH", "")}
            records: dict[str, dict[str, Any]] = {}
            pending = list(scope["jobs"])
            while pending:
                job = next(item for item in pending if all(name in records for name in item.get("needs", [])))
                pending.remove(job)
                record = {"id": job["id"], "target": job["target"],
                          "purpose": job["purpose"], "status": job["disposition"],
                          "optional": "optional_tool" in job, "ci_alignment": validation_plan["jobs"][job["id"]]}
                optional = evidence["environment"]["tools"].get(job.get("optional_tool"))
                if optional is not None:
                    record["optional_tool"] = job["optional_tool"]
                records[job["id"]] = record
                blocked = [name for name in job.get("needs", []) if records[name]["status"] != "passed"]
                if job["disposition"] != "run":
                    record["reason"] = job["reason"]
                elif optional is not None and optional["status"] != "available":
                    record.update(status="unavailable", reason=optional["reason"], evidence="environment.json")
                elif blocked:
                    record.update(status="blocked", blocked_by=blocked,
                                  reason="Prepare or repair prerequisite jobs, then rerun validation")
                else:
                    log_name = f"{label}-{job['id']}.log"
                    log = safe_path(self.output, log_name)
                    record.update(cwd=job.get("cwd", "."), log=log_name)
                    cwd = execution if job.get("cwd", ".") == "." else safe_path(execution, job["cwd"])
                    inputs = {item["source_path"] for name in job.get("elf_inputs", [])
                              for item in records[name].get("artifacts", []) if item["kind"] == "elf"}
                    for name in inputs:
                        source = safe_path(execution, name)
                        saved = next(item for provider in job["elf_inputs"] for item in records[provider]["artifacts"] if item["source_path"] == name)
                        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != saved["sha256"]:
                            raise ValueError(f"ELF input changed after build: {name}; rerun the native build")
                    for artifact in job.get("artifacts", []) + job.get("diagnostics", []):
                        for output in artifact_paths(execution, artifact):
                            if str(output.relative_to(execution)) in inputs:
                                raise ValueError("Execution output must not overwrite its ELF inputs")
                            output.unlink()
                    if job["purpose"] == "environment":
                        probe = [arg.replace("{TOOLS}", str(tools)) for arg in job["probe"]]
                        attempts = [execute_command(probe, cwd, environment, log, job["timeout_seconds"], deadline=deadline)]
                        pattern = job.get("expected_output")
                        matched = attempts[-1]["status"] == "passed" and (
                            pattern is None or re.search(pattern, log.read_text(errors="replace")) is not None)
                        if not matched and "install" in job:
                            install = [arg.replace("{TOOLS}", str(tools)) for arg in job["install"]]
                            attempts.append(execute_command(install, cwd, environment, log, job["timeout_seconds"], append=True, deadline=deadline))
                            if attempts[-1]["status"] == "passed":
                                probe_log = safe_path(self.output, f"{label}-{job['id']}-probe.log")
                                attempts.append(execute_command(probe, cwd, environment, probe_log, job["timeout_seconds"], deadline=deadline))
                                matched = attempts[-1]["status"] == "passed" and (
                                    pattern is None or re.search(pattern, probe_log.read_text(errors="replace")) is not None)
                                record.update(probe_log=str(probe_log.relative_to(self.output)),
                                              probe_log_sha256=hashlib.sha256(probe_log.read_bytes()).hexdigest())
                        record.update(status="passed" if matched else "unavailable", attempts=attempts,
                                      installed=len(attempts) == 3 and matched)
                        if not matched:
                            record["reason"] = job.get("reason", "Tool preparation failed; inspect the installation/probe log, provide the required tool version and rerun")
                    else:
                        record.update(execute_command(job["argv"], cwd, environment, log, job["timeout_seconds"], deadline=deadline))
                        if job.get("elf_inputs"):
                            record["elf_count"] = len(inputs)
                            if not inputs:
                                record_validation_failure(record, "No ELF inputs; generate tests and build ELFs before execution")
                    record["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
                    record["artifacts"] = []
                    executed = 0
                    for artifact in job.get("artifacts", []):
                        outputs = artifact_paths(execution, artifact)
                        if len(outputs) < artifact.get("min_count", 1):
                            record_validation_failure(record, f"Expected artifact missing or insufficient: {artifact['path']}")
                        for source in outputs:
                            content = source.read_bytes()
                            if not content or (artifact["kind"] == "elf" and not content.startswith(b"\x7fELF")):
                                record_validation_failure(record, f"Empty or invalid {artifact['kind']} artifact: {source.relative_to(execution)}")
                            if artifact["kind"] == "results" and "pass_pattern" in artifact:
                                text = content.decode("utf-8", errors="replace")
                                executed += len(re.findall(artifact["pass_pattern"], text))
                                if re.search(artifact["fail_pattern"], text):
                                    record_validation_failure(record, "Native test results contain failures or signature-only runs")
                            relative = str(source.relative_to(execution))
                            name = f"artifacts-{label}/{job['id']}/{relative}"
                            target = safe_path(self.output, name)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                            record["artifacts"].append({"path": name, "source_path": relative, "kind": artifact["kind"],
                                                        "sha256": hashlib.sha256(content).hexdigest()})
                    if job["purpose"] == "reference_model":
                        record["executed_tests"] = executed
                        if executed == 0 or executed != record.get("elf_count"):
                            record_validation_failure(record, "Native passing test count must equal the nonzero input ELF count")
                    log_text = log.read_text(errors="replace")
                    diagnostic_paths = {path for selector in job.get("diagnostics", [])
                                        for path in artifact_paths(execution, selector)}
                    selected = sorted(diagnostic_paths, key=lambda path: (
                        str(path.relative_to(execution)) not in log_text, str(path)))[:DIAGNOSTIC_FILE_LIMIT]
                    record["diagnostics"] = []
                    for source in selected:
                        relative = str(source.relative_to(execution))
                        size = source.stat().st_size
                        with source.open("rb") as stream:
                            stream.seek(max(0, size - DIAGNOSTIC_BYTE_LIMIT))
                            content = stream.read(DIAGNOSTIC_BYTE_LIMIT)
                        name = f"diagnostics-{label}/{job['id']}/{relative}"
                        target = safe_path(self.output, name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                        record["diagnostics"].append({"path": name, "source_path": relative,
                            "source_size": size, "truncated": size > len(content),
                            "sha256": hashlib.sha256(content).hexdigest()})
                    record["diagnostic_summary"] = {
                        "matched_files": len(diagnostic_paths), "saved_files": len(selected),
                        "omitted_files": len(diagnostic_paths) - len(selected),
                        "truncated_files": sum(item["truncated"] for item in record["diagnostics"])}
            evidence["jobs"] = [records[job["id"]] for job in scope["jobs"]]
        source_prefix = str(tree.relative_to(self.output))
        evidence["source_files"] = {
            f"{source_prefix}/{name}": identity["sha256"]
            for name, identity in tree_state(tree).items() if identity["kind"] == "file"}
        evidence["source_files"].update({
            f"references/{name}": identity["sha256"]
            for name, identity in state["baseline"]["references"].items() if identity["kind"] == "file"})
        independent = self._load("isa-plan-accepted.json")
        evidence["source_files"]["isa-plan.yaml"] = independent["sha256"]
        evidence["source_files"].update(self._load("isa-plan-context.json")["source_files"])
        evidence["isa_requirements"] = {item["id"]: item for item in independent["plan"]["requirements"]}
        evidence["isa_plan_limitations"] = independent["plan"]["limitations"]
        evidence["implementation_sources"] = sorted({f"{source_prefix}/{name}"
            for kind in ("generators", "test_cases") for name in scope["assets"][kind] if (tree / name).is_file()})
        assembly = {f"{source_prefix}/{name}": name for name in scope["assets"]["test_cases"]
                    if Path(name).suffix.lower() == ".s" and (tree / name).is_file()}
        for job in evidence["jobs"]:
            for artifact in job.get("artifacts", []):
                if artifact["kind"] == "generated" and Path(artifact["path"]).suffix.lower() == ".s":
                    assembly[artifact["path"]] = artifact["source_path"]
        evidence["testcase_links"] = {}
        for retained, original in sorted(assembly.items()):
            text = safe_path(self.output, retained).read_text(encoding="utf-8", errors="replace")
            result = inspect_source(text)
            reachability[retained] = result
            excluded = {item["testcase"] for item in result["impossible"]} | set(result["conditional_unverified_labels"])
            descriptors = re.sub(
                r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*',
                lambda match: match.group() if match.group().startswith('"') else " " + "\n" * match.group().count("\n"),
                text, flags=re.DOTALL,
            )
            for match in re.finditer(
                r'^\s*([A-Za-z_][\w$]*)_str:\s*\.string[^\n]*?\bcg:\s*([\w$]+);\s*cp:\s*([\w$]+);',
                descriptors, re.MULTILINE,
            ):
                testcase, group, point = match.groups()
                if testcase in result["linked_labels"] and testcase not in excluded and not result["parse_issues"]:
                    evidence["testcase_links"].setdefault(f"{group}/{point}", []).append({
                        "testcase": f"{original}::{testcase}", "path": retained,
                        "line": descriptors.count("\n", 0, match.start(1)) + 1})
        tasks = {f"topic:{topic}": {"topic": topic, "question": question}
                 for topic, question in sorted(SEMANTIC_QUESTIONS.items())}
        evidence["obligation_sources"] = {}
        inputs = [(f"{source_prefix}/{name}", "plan", name) for name in scope["assets"]["test_plans"] if (tree / name).is_file()]
        plan_inputs = {safe_path(self.source, name).resolve() for name in scope["assets"]["test_plans"]}
        inputs.extend((f"references/{name}", "specification", name) for name in scope["reference_files"]
                      if safe_path(Path(self.workspace), name).resolve() not in plan_inputs)
        for path, kind, name in inputs:
            content = safe_path(self.output, path).read_bytes()
            try:
                lines = content.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                lines = []
            selected = scope["reference_scope"][name]["reviewed_lines"] if kind == "specification" else [[1, len(lines)]]
            blocks = [(start + 1, min(start + 80, end)) for first, end in selected for start in range(first - 1, end, 80)
                      if any(line.strip() for line in lines[start:min(start + 80, end)])]
            if kind == "specification":
                excluded, previous = [], 0
                for first, end in selected + [[len(lines) + 1, len(lines) + 1]]:
                    if first > previous + 1:
                        excluded.append([previous + 1, first - 1])
                    previous = end
                if excluded:
                    tasks[f"boundary:{name}"] = {"topic": "omissions", "path": path,
                        "reviewed_lines": selected, "excluded_lines": excluded,
                        "reason": scope["reference_scope"][name]["excluded_reason"],
                        "question": "Verify the declared exclusion against the source and suite dependencies. Cite an excluded section; use not_applicable only with confirmed justification, otherwise report issues or unverified."}
            for start, end in blocks or [(0, 0)]:
                identity = f"source:{kind}:{name}:{start}-{end}"
                task = {"topic": "omissions", "path": path, "lines": [start, end], "kind": kind,
                        "question": "Extract all applicable obligations from this source block, including ones absent from both coverage and testgen; map each obligation or justify exclusion. Read adjacent blocks for context."}
                evidence["obligation_sources"][identity] = task
                tasks[identity] = task
        if label == "after":
            before_sources = self._load("evidence-before.json")["obligation_sources"]
            for identity, task in before_sources.items():
                if identity not in evidence["obligation_sources"]:
                    evidence["obligation_sources"][identity] = task
                    tasks[identity] = task
                    evidence["source_files"][task["path"]] = hashlib.sha256(safe_path(self.output, task["path"]).read_bytes()).hexdigest()
        for item in scope["shared_assets"]:
            path = f"{source_prefix}/{item['path']}" if (tree / item["path"]).is_file() else f"baseline/{item['path']}"
            evidence["source_files"][path] = hashlib.sha256(safe_path(self.output, path).read_bytes()).hexdigest()
            tasks[f"shared:{item['path']}"] = {"topic": "contribution_quality", "path": path,
                "consumers": item["consumers"], "boundary": item["boundary"],
                "question": "Review shared dependencies and cross-suite impact. Distinguish missing external scope from real defects; propose validation for affected consumers."}
        for group, data in coverage["groups"].items():
            for point, detail in data["coverpoint_details"].items():
                identity = f"{group}/{point}"
                tasks[f"point:{identity}"] = {
                    "topic": "coverpoint_quality", "question": SEMANTIC_QUESTIONS["coverpoint_quality"] + " " + SEMANTIC_QUESTIONS["test_coverage"],
                    "path": f"{source_prefix}/{Path(detail['file']).relative_to(tree)}",
                    "line": detail["line"], "expression": detail["expression"],
                    "kind": detail["kind"], "cross_members": detail["cross_members"],
                    "conditions": detail["condition"], "bins": data["bins"].get(point, [])}
        for report_number, result in enumerate(results):
            if "error" in result and not result.get("report", {}).get("findings"):
                tasks[f"diagnostic:{report_number}:failure"] = {
                    "topic": "act4_compliance", "question": "Diagnose the failed asset check using its retained error and the frozen inputs; do not assume an unavailable analysis passed.",
                    "error": result["error"]}
            for finding_number, finding in enumerate(result.get("report", {}).get("findings", [])):
                if finding.get("severity") in {"error", "warning"}:
                    signature = {key: finding.get(key) for key in ("check", "severity", "message", "file", "line")}
                    if isinstance(signature["file"], str) and Path(signature["file"]).resolve().is_relative_to(tree.resolve()):
                        signature["file"] = str(Path(signature["file"]).resolve().relative_to(tree.resolve()))
                    identity = digest(signature)[:16]
                    task = tasks.setdefault(f"diagnostic:{identity}", {
                        "topic": "act4_compliance", "question": "Determine whether this diagnostic is an asset defect, scanner limitation, scope mismatch or unresolved issue; cite the relevant source.",
                        "check": finding["check"], "severity": finding["severity"],
                        "message": finding["message"], "occurrences": []})
                    task["occurrences"].append({"report": report_number, "finding": finding_number,
                        **{key: finding[key] for key in ("target", "rule_names", "coverpoint") if key in finding}})
                    if isinstance(finding.get("file"), str):
                        path = Path(finding["file"])
                        if path.is_file() and path.resolve().is_relative_to(tree.resolve()):
                            task["path"] = f"{source_prefix}/{path.resolve().relative_to(tree.resolve())}"
                            if type(finding.get("line")) is int and finding["line"] > 0:
                                task["line"] = finding["line"]
        for name, result in sorted(reachability.items()):
            if any(result[key] for key in ("unresolved_descriptors", "conditional_unverified_labels", "impossible", "parse_issues")):
                tasks[f"reachability:{name}"] = {
                    "topic": "test_coverage", "question": "Explain the descriptor/label and conditional-compilation findings using the target configuration; unknown macros are not proof of unreachable tests.",
                    "source": name, "path": name}
        evidence["duplicate_assets"].sort()
        for index, names in enumerate(evidence["duplicate_assets"]):
            tasks[f"duplicate:{index}"] = {"topic": "redundancy", "paths": names,
                "sources": [f"{source_prefix}/{name}" for name in names],
                "question": SEMANTIC_QUESTIONS["redundancy"]}
        evidence["review_tasks"] = tasks
        evidence["review_digest"] = digest(evidence)
        self._isa_plan(state, is_complete=False)
        if digest({"sources": evidence_fingerprint(tree, scope),
                   "references": state["baseline"]["references"], "environment": state["environment"],
                   "isa_plan": state["isa_plan"]}) != fingerprint:
            raise ValueError("Source changed during validation; discard results and retry")
        self._write(f"evidence-{label}.json", evidence)
        state[f"evidence-{label}"] = digest(evidence)
        return evidence

    def _review(self, scope: dict[str, Any], evidence: dict[str, Any], partial: bool = False) -> dict[str, Any]:
        """Require full review topics, traceability, findings, and exact proposed changes."""
        review = self._load("review.yaml")
        if review.get("suite") != self.suite or not is_text(review.get("summary")):
            raise ValueError("review.yaml needs the suite and a nonempty summary")
        checks = review.get("checks")
        if not isinstance(checks, dict) or set(checks) != TOPICS:
            raise ValueError(f"review.checks requires exactly {sorted(TOPICS)}")
        for name, check in checks.items():
            if not isinstance(check, dict) or check.get("status") not in {"passed", "issues", "unverified", "not_applicable"}:
                raise ValueError(f"Invalid review status for {name}")
            if not is_text_list(check.get("evidence")) or not is_text(check.get("conclusion")):
                raise ValueError(f"Review topic {name} needs a nonempty evidence string list and textual conclusion/limitation")
        findings = review.get("findings")
        changes = review.get("changes")
        if not isinstance(findings, list) or not isinstance(changes, list):
            raise ValueError("review.findings and changes must be lists; [] is valid for a clean audit")
        ids = set()
        for item in findings:
            if not isinstance(item, dict) or not is_text(item.get("id")) or not re.fullmatch(r"F[0-9]+", item["id"]) or item["id"] in ids:
                raise ValueError("Findings require unique F<number> identities")
            ids.add(item["id"])
            if item.get("topic") not in TOPICS or item.get("severity") not in {"high", "medium", "low", "info"}:
                raise ValueError("Each finding needs a valid topic and severity")
            if not is_text_list(item.get("evidence")) or any(not is_text(item.get(field)) for field in ("location", "problem", "recommendation")):
                raise ValueError(f"Finding {item['id']} needs textual location/problem/recommendation and a nonempty evidence string list")
            if "root_cause_key" in item and (not is_text(item["root_cause_key"]) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", item["root_cause_key"])):
                raise ValueError("root_cause_key must be a stable 1..120 character rule/source identity; do not merge per-module evidence")
        for change in changes:
            if not isinstance(change, dict) or not is_text_list(change.get("findings")) or not set(change["findings"]) <= ids:
                raise ValueError("Each change must reference existing finding ids")
            if not is_text_list(change.get("paths")) or not is_text(change.get("action")) or not is_text(change.get("risk")):
                raise ValueError("Each change needs exact paths, action, and risk")
            if not is_text_list(change.get("validation_jobs")) or not set(change["validation_jobs"]) <= {job["id"] for job in scope["jobs"]}:
                raise ValueError("Each change needs declared validation_jobs")
            if any(item.get("classification") != "confirmed_defect" or item.get("diagnosis") != "repair_ready"
                   for item in findings if item["id"] in change["findings"]):
                raise ValueError("Propose repairs only for confirmed_defect findings with diagnosis: repair_ready; investigate other findings first")
            for name in change["paths"]:
                path = safe_path(self.source, name)
                if path.is_symlink():
                    raise ValueError(f"Repair proposals must target regular source files: {name}")
        experiments = review.get("experiments", [])
        if not isinstance(experiments, list):
            raise ValueError("review.experiments must be a list of bounded experimental plans")
        experiment_ids = set()
        for experiment in experiments:
            if not isinstance(experiment, dict) or not isinstance(experiment.get("id"), str) or not re.fullmatch(r"E[0-9]+", experiment["id"]) or experiment["id"] in experiment_ids:
                raise ValueError("Experiments require unique E<number> IDs")
            experiment_ids.add(experiment["id"])
            if not is_text_list(experiment.get("findings")) or not set(experiment["findings"]) <= ids or not all(is_text(experiment.get(field)) for field in ("question", "success_criterion")):
                raise ValueError("Experiments need finding IDs, a concrete question and success_criterion, not an assumed verdict")
            if not is_text_list(experiment.get("paths")) or not is_text_list(experiment.get("jobs")) or not set(experiment["jobs"]) <= {job["id"] for job in scope["jobs"]}:
                raise ValueError("Experiments need exact editable paths and selected scope job IDs")
            for name in experiment["paths"]:
                path = safe_path(self.source, name)
                if path.is_symlink() or name.startswith(("framework/", "tests/env/", ".github/")) or name in {"Makefile", "run_tests.py", "pyproject.toml", "uv.lock", ".mise.toml"} or name.startswith("tests/") and name.endswith(".S"):
                    raise ValueError(f"Experiment cannot modify protected infrastructure or generated assembly: {name}")
                reviewed = {item for paths in scope["assets"].values() for item in paths} | set(scope["context_files"])
                if path.exists() and name not in reviewed and not name.startswith("config/"):
                    raise ValueError(f"Declare the existing experiment dependency in assets/context_files before editing: {name}")
            assets = experiment.get("assets")
            if not isinstance(assets, dict) or set(assets) != ASSET_KINDS or any(not is_text_list(paths, allow_empty=True) for paths in assets.values()):
                raise ValueError("Experiment assets must explicitly list all five asset categories")
            for paths in assets.values():
                for name in paths:
                    safe_path(self.source, name)
            original_assets = {name for paths in scope["assets"].values() for name in paths}
            proposed_assets = {name for paths in assets.values() for name in paths}
            if (original_assets ^ proposed_assets) - set(experiment["paths"]):
                raise ValueError("Experimental asset additions/removals must be declared editable paths")
        post_assets = review.get("post_assets")
        if not isinstance(post_assets, dict) or set(post_assets) != ASSET_KINDS:
            raise ValueError(f"review.post_assets must declare all repaired asset categories: {sorted(ASSET_KINDS)}")
        allowed = {name for change in changes for name in change["paths"]}
        for kind, names in post_assets.items():
            if not is_text_list(names, allow_empty=True) or len(set(names)) != len(names):
                raise ValueError(f"review.post_assets.{kind} must list unique exact paths")
            for name in names:
                safe_path(self.source, name)
            if (set(names) ^ set(scope["assets"][kind])) - allowed:
                raise ValueError("Changed post-review asset membership must be within declared repair paths")
        self._traceability(review.get("traceability"), evidence, partial=partial)
        self._validation_section, self._validation_location = "conclusion", "review.yaml/checks"
        if checks["ci"]["status"] == "passed" and (not any(job["status"] == "passed" for job in evidence["jobs"]) or any(job["status"] not in {"passed", "not_applicable"} for job in evidence["jobs"])):
            raise ValueError("CI cannot be passed with failed, unavailable, or unexecuted jobs")
        if checks["act4_compliance"]["status"] == "passed" and not evidence["static_passed"]:
            raise ValueError("ACT4 compliance cannot pass while deterministic checks report errors")
        if checks["test_coverage"]["status"] == "passed" and (not review["traceability"] or any(item["coverage"] != "measured" for item in review["traceability"])):
            raise ValueError("Test coverage cannot pass while coverpoints have gaps or only static/unverified evidence")
        self._semantic_review(review, evidence, partial=partial)
        return review

    def _semantic_review(self, document: dict[str, Any], evidence: dict[str, Any],
                         review: dict[str, Any] | None = None, changed: list[str] | None = None,
                         partial: bool = False) -> None:
        """Require source-grounded AI judgments for every unresolved semantic obligation."""
        self._validation_section, self._validation_location = "semantic", "semantic_review"
        semantic = document.get("semantic_review")
        if not isinstance(semantic, dict) or semantic.get("reviewer") != "ai":
            raise ValueError("Write semantic_review with reviewer: ai using Guide_Doc/ACT4_Extension_Review_Guide.md")
        if semantic.get("evidence_digest") != evidence["review_digest"]:
            raise ValueError(f"Review the current evidence and set semantic_review.evidence_digest to {evidence['review_digest']}")
        tasks = dict(evidence["review_tasks"])
        tasks.update({f"finding:{item['id']}": {"topic": item.get("topic", "contribution_quality")} for item in document["findings"]})
        if review is not None:
            tasks.update({f"finding:{item['id']}": {"topic": item["topic"]} for item in review["findings"]})
            tasks.update({f"change:{name}": {"topic": "contribution_quality"} for name in changed or []})
        allowed = dict(evidence["source_files"])
        evidence_name = "evidence-before.json" if review is None else "evidence-after.json"
        allowed[evidence_name] = hashlib.sha256((json.dumps(evidence, indent=2) + "\n").encode()).hexdigest()
        if review is not None:
            before = self._load("evidence-before.json")
            allowed.update(before["source_files"])
            allowed["evidence-before.json"] = hashlib.sha256((json.dumps(before, indent=2) + "\n").encode()).hexdigest()
        for run in ([before, evidence] if review is not None else [evidence]):
            for job in run["jobs"]:
                for field in ("log", "probe_log"):
                    if field in job:
                        allowed[job[field]] = job[f"{field}_sha256"]
                allowed.update({item["path"]: item["sha256"]
                                for item in job.get("artifacts", []) + job.get("diagnostics", [])})
        allowed["environment.json"] = hashlib.sha256((json.dumps(evidence["environment"], indent=2) + "\n").encode()).hexdigest()
        allowed.update(experiment_sources(self.output, self._state().get("experiment_receipts", {}), self._state().get("experiment_index")))
        for tool in evidence["environment"]["tools"].values():
            allowed.update({attempt["log"]: attempt["sha256"] for attempt in tool["attempts"]})
        source_lines = {}
        for finding in document["findings"]:
            self._validation_section = "finding"
            self._validation_location = f"findings/{finding['id']}"
            if finding.get("classification") not in {"confirmed_defect", "suspected_defect", "validation_gap", "not_a_defect"}:
                raise ValueError(f"Finding {finding['id']} needs classification separating defects from suspicion and validation gaps")
            if finding.get("diagnosis") not in {"symptoms_only", "cause_identified", "repair_ready"}:
                raise ValueError(f"Finding {finding['id']} needs diagnosis: symptoms_only/cause_identified/repair_ready")
            if finding["classification"] == "confirmed_defect":
                plan = finding.get("repair_plan")
                if not isinstance(plan, dict) or not all(is_text(plan.get(field)) for field in (
                    "expected_behavior", "stimulus", "observation", "resources", "restoration", "next_action"
                )):
                    raise ValueError(f"Finding {finding['id']} needs repair_plan: expected_behavior, stimulus, observation, resources, restoration and next_action; design the missing test instead of treating its absence as a blocker")
                for field in ("paths", "validation_jobs"):
                    if not is_text_list(plan.get(field), allow_empty=finding["diagnosis"] != "repair_ready"):
                        raise ValueError(f"Finding {finding['id']} repair_plan.{field} must list exact identities; repair_ready requires nonempty lists")
                for name in plan["paths"]:
                    safe_path(self.source, name)
                if not set(plan["validation_jobs"]) <= {job["id"] for job in evidence["jobs"]}:
                    raise ValueError(f"Finding {finding['id']} repair_plan names unknown validation_jobs")
                self._citations(plan.get("basis"), allowed, source_lines)
            attempts = finding.get("investigation")
            if not isinstance(attempts, list) or not attempts:
                raise ValueError(f"Finding {finding['id']} needs investigation entries documenting work actually attempted, results and quoted evidence")
            for attempt in attempts:
                if not isinstance(attempt, dict) or not all(is_text(attempt.get(field)) for field in ("action", "result")):
                    raise ValueError("Each investigation requires action, result and basis; a generic request for more evidence is insufficient")
                self._citations(attempt.get("basis"), allowed, source_lines)
            if review is not None and finding["status"] in {"deferred", "not_fixed"}:
                blocker = finding.get("blocker")
                if not isinstance(blocker, dict) or blocker.get("kind") not in {"specification", "configuration", "reproduction", "tooling", "implementation"}:
                    raise ValueError(f"Finding {finding['id']} needs a precise blocker kind; use implementation when behavior is known but the test is missing")
                if not all(is_text(blocker.get(field)) for field in ("detail", "impact", "why_not_resolved")) or blocker.get("owner") not in {"agent", "user", "upstream"}:
                    raise ValueError("Unresolved findings require blocker detail, impact, why_not_resolved and owner: agent/user/upstream")
                if blocker["owner"] == "user" and not all(is_text(blocker.get(field)) for field in ("request", "reason_user_needed")):
                    raise ValueError("User assistance needs a concrete request and reason_user_needed; ordinary investigation remains agent work")
                stop = blocker.get("stop_reason")
                if stop not in {"external_dependency", "unfinished_work", "budget_exhausted"}:
                    raise ValueError(f"Finding {finding['id']} blocker.stop_reason must distinguish external_dependency, unfinished_work and budget_exhausted")
                alternatives = blocker.get("alternatives")
                if not isinstance(alternatives, list):
                    raise ValueError("blocker.alternatives must list evaluated repair routes; use [] only for unfinished work or budget stops")
                routes = set()
                for alternative in alternatives:
                    if not isinstance(alternative, dict) or alternative.get("route") not in {"suite_local", "positive_subset", "native_entrypoint", "validation_only"} or alternative["route"] in routes:
                        raise ValueError("Blocker alternatives require unique suite_local/positive_subset/native_entrypoint/validation_only routes")
                    routes.add(alternative["route"])
                    if alternative.get("status") not in {"tried", "ruled_out", "pending"} or not is_text(alternative.get("result")):
                        raise ValueError("Each alternative needs tried/ruled_out/pending and a specific result")
                    self._citations(alternative.get("basis"), allowed, source_lines)
                    if alternative["status"] == "tried":
                        identity = alternative.get("experiment_id")
                        attempted = self._state().get("experiments", {}).get(identity, {}) if isinstance(identity, str) else {}
                        declared = next((plan for plan in review.get("experiments", []) if plan["id"] == identity and finding["id"] in plan["findings"]), None)
                        if declared is None or attempted.get("status") != "completed" or not any(item["path"] == f"evidence-experiment-{identity}.json" or item["path"].startswith((f"artifacts-experiment-{identity}/", f"diagnostics-experiment-{identity}/", f"experiment-{identity}-")) for item in alternative["basis"]):
                            raise ValueError("A tried alternative must name its completed experiment_id and quote its retained result; source-only exclusions use ruled_out")
                if stop == "external_dependency":
                    if blocker["owner"] == "agent" or routes != {"suite_local", "positive_subset", "native_entrypoint", "validation_only"} or any(item["status"] == "pending" for item in alternatives):
                        raise ValueError("External blockers require an external owner and evidence for all four alternatives; unattempted agent work is unfinished_work, not impossibility")
                elif blocker["owner"] != "agent":
                    raise ValueError("Unfinished work and budget stops remain agent-owned; do not request external help for ordinary implementation")
                if stop == "unfinished_work" and finding["classification"] == "confirmed_defect" and not any(item["status"] in {"tried", "ruled_out"} for item in alternatives):
                    raise ValueError("Confirmed defects need a real minimal experiment or a source-grounded excluded route before stopping as unfinished_work; a plan alone is not an attempt")
                if stop == "budget_exhausted":
                    budget = blocker.get("budget")
                    if not isinstance(budget, dict) or budget.get("resource") not in {"seconds", "tokens", "experiments"} or type(budget.get("limit")) is not int or budget["limit"] < 1 or type(budget.get("consumed")) is not int or budget["consumed"] < budget["limit"]:
                        raise ValueError("Budget stops require resource seconds/tokens/experiments, positive limit and consumed >= limit, plus quoted usage evidence")
                    self._citations(budget.get("basis"), allowed, source_lines)
                    if budget["resource"] == "experiments":
                        attempts = self._state().get("experiments", {})
                        used = sum(item["status"] != "prepared" for item in attempts.values())
                        if budget["limit"] != self.max_experiments or budget["consumed"] != used or not any(item["path"] == "experiments.json" for item in budget["basis"]):
                            raise ValueError("Experiment budget claims must match the configured limit and actual attempts in experiments.json")
            if review is not None and finding["status"] == "fixed" and (finding["classification"] != "confirmed_defect" or finding["diagnosis"] != "repair_ready"):
                raise ValueError("Only a confirmed_defect with repair_ready diagnosis and an actual validated source change can be fixed")
            if review is not None and finding["status"] == "dismissed" and finding["classification"] != "not_a_defect":
                raise ValueError("A dismissed finding requires classification: not_a_defect and a source-grounded reassessment")
        self._validation_section, self._validation_location = "obligation", "obligations"
        obligations = document.get("obligations")
        if not isinstance(obligations, list):
            raise ValueError("obligations must map every evidence.obligation_sources block to requirements or explicit exclusions")
        source_ids = set(evidence["obligation_sources"])
        covered_sources, obligation_ids, compared_plan = set(), set(), set()
        for item in obligations:
            self._validation_section = "obligation"
            self._validation_location = f"obligations/{item.get('id', 'unknown')}" if isinstance(item, dict) else "obligations"
            if not isinstance(item, dict) or not is_text(item.get("id")) or not re.fullmatch(r"O[0-9]+", item["id"]) or item["id"] in obligation_ids:
                raise ValueError("Obligations require unique O<number> identities")
            obligation_ids.add(item["id"])
            if not is_text_list(item.get("plan_items"), allow_empty=True) or len(item["plan_items"]) != len(set(item["plan_items"])) or not set(item["plan_items"]) <= evidence["isa_requirements"].keys():
                raise ValueError(f"Obligation {item['id']} needs unique plan_items from the accepted ISA plan; use [] only for additional discoveries")
            compared_plan.update(item["plan_items"])
            if not is_text_list(item.get("sources")) or not set(item["sources"]) <= source_ids:
                raise ValueError(f"Obligation {item['id']} must cite current obligation_sources IDs")
            covered_sources.update(item["sources"])
            if not all(is_text(item.get(field)) for field in ("requirement", "reason")) or item.get("status") not in {"implemented", "gap", "unverified", "not_applicable"}:
                raise ValueError("Each obligation needs requirement, reason and implemented/gap/unverified/not_applicable status")
            if not is_text_list(item.get("targets")) or not set(item["targets"]) <= set(evidence["targets"]):
                raise ValueError("Obligation targets must identify selected configurations")
            for field, available in (("coverpoints", evidence["coverpoints"]), ("implementation", evidence["implementation_sources"]),
                                     ("findings", [finding["id"] for finding in document["findings"]])):
                if not is_text_list(item.get(field), allow_empty=True) or not set(item[field]) <= set(available):
                    raise ValueError(f"Obligation {item['id']} has unknown {field} links")
            if item["status"] == "gap" and not item["findings"]:
                raise ValueError("Missing obligations must link to findings even if coverage and generator both lack them")
            if item["status"] == "implemented" and (not item["coverpoints"] or not item["implementation"]):
                raise ValueError("Implemented obligations require both coverpoints and implementation source links; otherwise record a gap or unverified")
            tasks[f"obligation:{item['id']}"] = {"topic": "omissions",
                "sources": sorted({evidence["obligation_sources"][name]["path"] for name in item["sources"]} | set(item["implementation"]) |
                                  {tasks[f"point:{point}"]["path"] for point in item["coverpoints"]} |
                                  ({"isa-plan.yaml"} if item["plan_items"] else set()) |
                                  {citation["path"] for name in item["plan_items"] for citation in evidence["isa_requirements"][name]["basis"]}),
                "obligation_status": item["status"], "findings": item["findings"], "coverpoints": item["coverpoints"]}
        if not partial and covered_sources != source_ids:
            raise ValueError(f"Obligation inventory omits source blocks: {sorted(source_ids - covered_sources)[:12]}")
        if not partial and compared_plan != evidence["isa_requirements"].keys():
            raise ValueError(f"Compare every independent ISA requirement with current assets, including gaps or justified exclusions: {sorted(evidence['isa_requirements'].keys() - compared_plan)[:12]}")
        if review is not None and not {item["id"] for item in review["obligations"]} <= obligation_ids:
            raise ValueError("Final obligations must retain every original obligation ID; explain exclusions instead of dropping gaps")
        self._validation_section, self._validation_location = "judgment", "semantic_review/judgments"
        judgments = semantic.get("judgments")
        if isinstance(judgments, list) and any(isinstance(item, dict) and "reused_from" in item for item in judgments):
            raise ValueError("Do not author reused_from provenance; use semantic_review.reused_tasks to reference eligible unchanged judgments")
        requested_reuse = semantic.get("reused_tasks", [])
        if not is_text_list(requested_reuse, allow_empty=True) or len(set(requested_reuse)) != len(requested_reuse) or requested_reuse and review is None:
            raise ValueError("semantic_review.reused_tasks must list unique eligible final task IDs; audit judgments cannot be reused")
        if review is not None:
            reusable = {}
            reason = "No accepted audit snapshot is available"
            snapshot_id = self._state().get("audit_snapshot")
            if snapshot_id:
                content = safe_path(self.output, "review-accepted.json").read_bytes()
                if hashlib.sha256(content).hexdigest() != snapshot_id:
                    raise ValueError("Accepted audit snapshot changed; restore it before requesting final reuse")
                snapshot = json.loads(content)
                previous = snapshot["review"]
                reason = "An executable input, configuration, reference, validation outcome or artifact changed; unknown dependencies require full re-review"
                signatures = []
                for run in (before, evidence):
                    signatures.append([{key: job.get(key) for key in ("id", "target", "purpose", "status", "optional", "elf_count", "executed_tests", "ci_alignment")} |
                        {"artifacts": [{key: artifact.get(key) for key in ("source_path", "sha256", "kind")} for artifact in job.get("artifacts", [])]}
                        for job in run["jobs"]])
                current_classes = {item["id"]: item["classification"] for item in document["findings"]}
                previous_classes = {item["id"]: item["classification"] for item in previous["findings"]}
                if snapshot["evidence_digest"] == before["review_digest"] and before["fingerprint"] == evidence["fingerprint"] and signatures[0] == signatures[1] and current_classes == previous_classes:
                    reason = "Only judgments with identical dependency inputs, task definitions and quoted sources are eligible; findings and changes always require fresh review"
                    for original in previous["semantic_review"]["judgments"]:
                        for subject in original["tasks"]:
                            current_subject = subject.replace("baseline/", "candidate/")
                            if subject not in before["review_tasks"] or current_subject not in tasks:
                                continue
                            expected_task = json.loads(json.dumps(before["review_tasks"][subject]).replace("baseline/", "candidate/"))
                            if expected_task != tasks[current_subject]:
                                continue
                            if any(item["id"] in original["findings"] and item.get("status") in {"fixed", "dismissed"} for item in document["findings"]):
                                continue
                            if subject.startswith("topic:") and any(
                                json.dumps(previous.get(field), sort_keys=True).replace("baseline/", "candidate/") != json.dumps(document.get(field), sort_keys=True)
                                for field in ("obligations", "traceability")
                            ):
                                continue
                            retained = copy.deepcopy(original)
                            retained["tasks"] = [current_subject]
                            retained["diagnostics"] = {current_subject: original["diagnostics"][subject]} if subject.startswith("diagnostic:") else {}
                            valid = True
                            for citation in retained["basis"]:
                                old_path = citation["path"]
                                new_path = old_path.replace("baseline/", "candidate/").replace("artifacts-before/", "artifacts-after/").replace("diagnostics-before/", "diagnostics-after/")
                                if old_path == "evidence-before.json":
                                    valid = False
                                    break
                                if old_path not in allowed or new_path not in allowed or allowed[old_path] != allowed[new_path]:
                                    valid = False
                                    break
                                citation["path"] = new_path
                            if valid:
                                retained["reused_from"] = {"artifact": "review-accepted.json", "sha256": snapshot_id,
                                    "task": subject, "dependency_fingerprint": evidence["fingerprint"]}
                                reusable[current_subject] = retained
            self._write("reuse-final.json", {"schema_version": 1, "evidence_digest": evidence["review_digest"],
                        "reason": reason, "judgments": reusable})
            if set(requested_reuse) - reusable.keys():
                raise ValueError(f"Requested final reuse is stale or ineligible: {sorted(set(requested_reuse) - reusable.keys())[:12]}; inspect reuse-final.json and review changed dependencies")
            if isinstance(judgments, list):
                judgments = judgments + [reusable[identity] for identity in requested_reuse]
                semantic["judgments"] = judgments
        if not isinstance(judgments, list) or (not partial and not judgments):
            raise ValueError("semantic_review.judgments must assess every evidence review_task; an empty or missing AI review cannot pass")
        observed = set()
        finding_ids = {item["id"] for item in document["findings"]}
        for index, judgment in enumerate(judgments):
            self._validation_section = "judgment"
            self._validation_location = f"semantic_review/judgments/{index}"
            if not isinstance(judgment, dict) or not is_text_list(judgment.get("tasks")):
                raise ValueError("Each AI judgment needs nonempty task IDs from evidence.review_tasks")
            subjects = judgment["tasks"]
            if len(set(subjects)) != len(subjects) or set(subjects) - tasks.keys() or observed.intersection(subjects):
                raise ValueError("AI review task IDs must exist and be assessed exactly once")
            observed.update(subjects)
            status, confidence = judgment.get("status"), judgment.get("confidence")
            if not is_text(status) or status not in {"passed", "issues", "unverified", "not_applicable"} or not is_text(confidence) or confidence not in {"confirmed", "inferred", "unverified"}:
                raise ValueError("AI judgments need status passed/issues/unverified/not_applicable and confidence confirmed/inferred/unverified")
            if not all(is_text(judgment.get(field)) for field in ("reasoning", "conclusion")):
                raise ValueError("Each AI judgment needs reasoning comparing the cited facts with the obligation, and a conclusion")
            if (status in {"unverified", "not_applicable"} or confidence != "confirmed") and not is_text(judgment.get("limitation")):
                raise ValueError("Unverified, inferred or inapplicable AI judgments require a concrete limitation")
            if status in {"issues", "unverified"} and not is_text(judgment.get("next_action")):
                raise ValueError("Issues and unverified AI judgments need the exact next action")
            if status == "passed" and confidence != "confirmed":
                raise ValueError("An inferred or unverified AI judgment cannot be passed")
            if status == "passed":
                if "topic:act4_compliance" in subjects and not evidence["static_passed"]:
                    raise ValueError("AI compliance cannot pass while deterministic checks report errors")
                if "topic:ci" in subjects and (not any(job["status"] == "passed" for job in evidence["jobs"]) or any(
                    job["status"] not in {"passed", "not_applicable"} for job in evidence["jobs"]
                )):
                    raise ValueError("AI CI review cannot pass with failed, unavailable or unexecuted jobs")
                if "topic:test_coverage" in subjects and (not document["traceability"] or any(
                    item["coverage"] != "measured" for item in document["traceability"]
                )):
                    raise ValueError("AI test coverage cannot pass without complete measured traceability")
            linked = judgment.get("findings")
            if not is_text_list(linked, allow_empty=True) or not set(linked) <= finding_ids or (status == "issues" and not linked):
                raise ValueError("AI judgment findings must name existing finding IDs; issues must be recorded as findings")
            basis = judgment.get("basis")
            self._citations(basis, allowed, source_lines)
            self._validation_section = "judgment"
            self._validation_location = f"semantic_review/judgments/{index}"
            diagnostics = {subject for subject in subjects if subject.startswith("diagnostic:")}
            dispositions = judgment.get("diagnostics", {})
            if not isinstance(dispositions, dict) or set(dispositions) != diagnostics or any(
                value not in {"asset_defect", "scanner_limitation", "scope_mismatch", "unresolved"} for value in dispositions.values()
            ):
                raise ValueError("Each diagnostic task needs a diagnostics entry: asset_defect/scanner_limitation/scope_mismatch/unresolved")
            if "asset_defect" in dispositions.values() and (status != "issues" or not linked):
                raise ValueError("An asset_defect diagnostic must be issues and link to a finding")
            if "unresolved" in dispositions.values() and status == "passed":
                raise ValueError("An unresolved diagnostic cannot be passed")
            if status == "passed" and any(task in {"topic:omissions", "topic:coverpoint_quality"} for task in subjects) and not any(item["path"].startswith("references/") for item in basis):
                raise ValueError("Passing specification-completeness or coverpoint-quality review needs a frozen reference citation; declare scope.reference_files or report unverified")
            for subject in subjects:
                task = tasks[subject]
                self._validation_location = subject
                if subject.startswith("boundary:"):
                    if status == "passed" or (status == "not_applicable" and confidence != "confirmed"):
                        raise ValueError(f"Excluded source boundary {subject} needs confirmed not_applicable, or issues/unverified")
                    if not any(item["path"] == task["path"] and any(first <= item["lines"][0] <= item["lines"][1] <= last
                               for first, last in task["excluded_lines"]) for item in basis):
                        raise ValueError(f"Boundary {subject} must cite an excluded source section to justify its exclusion")
                if subject.startswith("source:") and task["lines"][0] and not any(
                    item["path"] == task["path"] and task["lines"][0] <= item["lines"][0] <= item["lines"][1] <= task["lines"][1]
                    for item in basis
                ):
                    raise ValueError(f"Source task {subject} must cite its own source block")
                if subject.startswith("obligation:"):
                    expected_status = {"implemented": "passed", "gap": "issues", "unverified": "unverified", "not_applicable": "not_applicable"}[task["obligation_status"]]
                    if status != expected_status:
                        raise ValueError(f"Judgment for {subject} must match its obligation status: {expected_status}")
                    if not set(task["findings"]) <= set(linked):
                        raise ValueError(f"Judgment for {subject} must link its obligation findings")
                    if status == "passed":
                        for point in task["coverpoints"]:
                            definition = tasks[f"point:{point}"]
                            if not any(item["path"] == definition["path"] and item["lines"][0] <= definition["line"] <= item["lines"][1] for item in basis):
                                raise ValueError(f"Implemented obligation {subject} must cite its coverpoint definition: {point}")
                required_sources = task.get("sources", [task["path"]] if "path" in task else [])
                cited = {item["path"] for item in basis}
                if not subject.startswith("point:"):
                    for name in set(required_sources) - cited:
                        content = safe_path(self.output, name).read_bytes()
                        if name not in allowed or hashlib.sha256(content).hexdigest() != allowed[name]:
                            raise ValueError(f"AI task source changed: {name}; recollect evidence")
                        try:
                            quotable = bool(content.decode("utf-8").strip())
                        except UnicodeDecodeError:
                            quotable = False
                        if quotable or evidence_name not in cited:
                            raise ValueError(f"AI judgment for {subject} must cite its task sources: {required_sources}; cite {evidence_name} for empty or binary inputs")
                if subject.startswith("point:") and not any(
                    item["path"] == task["path"] and item["lines"][0] <= task["line"] <= item["lines"][1]
                    for item in basis
                ):
                    raise ValueError(f"AI judgment for {subject} must cite its defining source line: {task['path']}:{task['line']}")
                if subject.startswith("change:"):
                    name = subject.removeprefix("change:")
                    expected = f"candidate/{name}" if f"candidate/{name}" in evidence["source_files"] else f"baseline/{name}"
                    if not any(item["path"] == expected for item in basis):
                        raise ValueError(f"AI judgment for {subject} must cite the changed source: {expected}")
                if subject.startswith("finding:"):
                    finding = next(item for item in document["findings"] if subject == f"finding:{item['id']}")
                    if finding["classification"] == "confirmed_defect" and finding.get("status") != "fixed" and (status != "issues" or confidence != "confirmed" or finding["id"] not in linked):
                        raise ValueError(f"Confirmed defect {finding['id']} needs an issues/confirmed judgment linked to the finding, even when repair is deferred")
                    if finding["classification"] == "not_a_defect" and (status not in {"passed", "not_applicable"} or confidence != "confirmed"):
                        raise ValueError(f"Ruling out finding {finding['id']} requires a confirmed passed/not_applicable judgment")
                    if finding.get("status") == "fixed" and status != "passed":
                        raise ValueError(f"Finding {finding['id']} cannot be fixed while its AI reassessment is {status}")
                    if finding.get("status") == "fixed":
                        paths = {name for change in review["changes"] if finding["id"] in change["findings"]
                                 for name in change["paths"] if name in (changed or [])}
                        sources = {f"candidate/{name}" if f"candidate/{name}" in evidence["source_files"] else f"baseline/{name}"
                                   for name in paths}
                        if not sources.intersection(item["path"] for item in basis):
                            raise ValueError(f"AI reassessment of fixed finding {finding['id']} must cite its changed source")
                    if finding.get("status") == "dismissed" and (status not in {"passed", "not_applicable"} or confidence != "confirmed"):
                        raise ValueError("Dismissed findings need a confirmed reassessment explaining why no source repair is needed")
            if review is None and status in {"issues", "unverified"}:
                for subject in subjects:
                    topic = tasks[subject]["topic"]
                    if document["checks"][topic]["status"] == "passed":
                        raise ValueError(f"Topic {topic} cannot pass with an issues/unverified AI judgment")
        if not partial and observed != tasks.keys():
            missing = sorted(tasks.keys() - observed)
            raise ValueError(f"AI review is incomplete: {len(missing)} tasks missing; first tasks: {missing[:12]}; read the complete evidence.review_tasks")
        traced = {item["coverpoint"] for item in document["traceability"]}
        completed = observed - (source_ids - covered_sources) - {f"point:{point}" for point in evidence["coverpoints"] if point not in traced}
        self._review_tasks, self._review_completed = tasks, completed

    def _citations(self, basis: Any, allowed: dict[str, str], source_lines: dict[str, list[str]]) -> None:
        """Verify exact quotations for semantic judgments and documented investigation attempts."""
        if not isinstance(basis, list) or not basis:
            raise ValueError("Source evidence requires path, lines, exact quote and observation")
        for citation in basis:
            self._validation_section = "citation_source"
            self._validation_location = f"{citation.get('path')}:{citation.get('lines')}" if isinstance(citation, dict) else "basis"
            if not isinstance(citation, dict) or not is_text(citation.get("path")) or citation["path"] not in allowed:
                raise ValueError("AI basis.path must name a frozen source/reference, current evidence JSON or retained command log/artifact; report text is not evidence")
            name = citation["path"]
            if name not in source_lines:
                content = safe_path(self.output, name).read_bytes()
                if hashlib.sha256(content).hexdigest() != allowed[name]:
                    raise ValueError(f"AI basis source changed: {name}; recollect evidence")
                try:
                    source_lines[name] = content.decode("utf-8").splitlines()
                except UnicodeDecodeError as exc:
                    raise ValueError(f"AI basis requires UTF-8 text: {name}; cite a retained textual report for binary artifacts") from exc
            self._validation_section = "citation_lines"
            lines, physical = citation.get("lines"), source_lines[name]
            if not isinstance(lines, list) or len(lines) != 2 or any(type(number) is not int for number in lines) or not 1 <= lines[0] <= lines[1] <= len(physical) or lines[1] - lines[0] >= 100:
                raise ValueError(f"AI basis.lines must select 1..100 existing physical lines: {name}")
            self._validation_section = "citation_quote"
            if not is_text(citation.get("quote")) or citation["quote"] != "\n".join(physical[lines[0] - 1:lines[1]]):
                raise ValueError(f"AI basis.quote must exactly match the selected source lines: {name}")
            self._validation_section = "citation_observation"
            if not is_text(citation.get("observation")):
                raise ValueError("AI basis.observation must explain what the quoted source establishes")

    def _traceability(self, trace: Any, evidence: dict[str, Any], partial: bool = False) -> None:
        """Check complete coverpoint accounting without treating static presence as hits."""
        self._validation_section, self._validation_location = "traceability", "traceability"
        if not isinstance(trace, list):
            raise ValueError("review.traceability must enumerate all defined coverpoints")
        observed = set()
        for item in trace:
            self._validation_section = "traceability"
            self._validation_location = item.get("coverpoint", "traceability") if isinstance(item, dict) else "traceability"
            if not isinstance(item, dict) or not is_text(item.get("coverpoint")) or item["coverpoint"] in observed:
                raise ValueError("Coverpoint traceability entries must be unique mappings")
            observed.add(item.get("coverpoint"))
            if item.get("coverage") not in {"measured", "static", "gap", "unverified"}:
                raise ValueError("Coverpoint coverage must distinguish measured/static/gap/unverified")
            if not is_text(item.get("obligation")) or not is_text_list(item.get("evidence")) or not is_text_list(item.get("testcases"), allow_empty=True):
                raise ValueError("Each coverpoint needs a textual obligation, testcase string list, and nonempty evidence string list")
            if item["coverage"] in {"measured", "static"} and not item["testcases"]:
                raise ValueError("Covered points require exact testcase identities")
            if item["coverage"] == "static":
                links = evidence["testcase_links"].get(item["coverpoint"], [])
                if not set(item["testcases"]) <= {link["testcase"] for link in links} or not {link["path"] for link in links}.intersection(item["evidence"]):
                    raise ValueError(f"Static traceability requires recorded descriptor/label links and their retained source paths: {item['coverpoint']}; otherwise report unverified")
            if item["coverage"] == "measured":
                artifacts = {artifact["path"] for job in evidence["jobs"] if job["status"] == "passed" and job["purpose"] == "coverage"
                             for artifact in job.get("artifacts", []) if artifact["kind"] == "coverage"}
                if not artifacts.intersection(item["evidence"]):
                    raise ValueError("Measured coverpoints must reference retained coverage artifacts from passing commands")
        if observed - set(evidence["coverpoints"]) or (not partial and observed != set(evidence["coverpoints"])):
            raise ValueError("Traceability must list every scanned group/coverpoint exactly once")

    def _review_batch(self, is_complete: bool) -> tuple[bool, dict[str, Any]]:
        """Revalidate live records and expose one bounded batch plus the full missing-work index."""
        tasks, completed = self._review_tasks, self._review_completed
        previous = set(self.batch.gen_task_list)
        self.batch.sync_source_task(sorted(tasks), [], "Review requirements changed")
        self.batch.sync_gen_task(sorted(completed), [], "Validated review records changed")
        self.batch.cmp_task_list = [task for task in self.batch.cmp_task_list if task in completed]
        passed, result = self.batch.do_complete([], is_complete, "missing source-grounded review",
                                               "unknown review task", "Read the current review batch; do not rerun native commands for document edits.")
        missing = sorted(set(tasks) - completed)
        current = list(self.batch.tbd_task_list)
        current_inputs = {identity: dict(tasks[identity]) for identity in current}
        for task in current_inputs.values():
            if "occurrences" in task:
                task["occurrence_count"] = len(task["occurrences"])
                task["occurrences"] = task["occurrences"][:8]
                task["full_evidence"] = "evidence-before.json" if self.phase == "audit" else "evidence-after.json"
        progress = {"schema_version": 1, "phase": self.phase, "total": len(tasks), "completed": len(completed),
                    "remaining": len(missing), "current_batch": current, "missing_tasks": missing,
                    "tasks": current_inputs,
                    "requirements": {"source": "Provide both extracted obligations (or a justified exclusion) and a source judgment.",
                                     "point": "Provide both traceability and a definition-grounded judgment.",
                                     "other": "Provide a source-grounded judgment; use ACT4ReviewDocument for exact quotations and structured updates."}}
        self._write(f"progress-{self.phase}.json", progress)
        if self.batch.checkpoint_error:
            return False, result
        if passed and not missing:
            return True, {"completed": len(completed), "total": len(tasks)}
        diagnostic = {"error_code": "act4_review_batch_pending", "error": f"{len(missing)} review tasks remain; complete the current batch of {len(current)}.",
                      "location": f"{self.phase}/batch/{digest([identity for identity in current if identity not in completed])[:16]}", "artifact": f"{self.review_dir}/progress-{self.phase}.json",
                      "observed": {"completed": len(completed), "total": len(tasks)}, "current_batch": current,
                      "next_action": "Read progress for task-specific inputs, update obligations/traceability/judgments for this batch, then Check. Complete requires every batch and the final report."}
        response = diagnostic
        if completed - previous:
            response["progress_summary"] = {"newly_validated": len(completed - previous), "completed": len(completed), "remaining": len(missing)}
        return False, response

    def _checked_result(self, passed: bool, result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Pause repeated failed Checks even inside one model turn without affecting other workflows."""
        diagnostic = result.get("diagnostic", result)
        if passed:
            self._stalled_checks = 0
            self._last_stall_signature = None
        else:
            signature = digest({key: diagnostic.get(key) for key in ("error_code", "error", "location", "observed")})
            diagnostic["failure_key"] = signature
            self._stalled_checks = self._stalled_checks + 1 if signature == self._last_stall_signature else 1
            self._last_stall_signature = signature
            diagnostic["stalled_checks"] = self._stalled_checks
            if self._stalled_checks >= self.max_stalled_checks:
                diagnostic["execution_paused"] = True
                diagnostic["next_action"] = (
                    f"Review paused after {self._stalled_checks} unchanged failed Checks. "
                    "Inspect the reported artifact and current batch; resolve the blocker or ask the operator for the specific missing input before resuming. "
                    "Do not rerun native commands merely to repair document fields."
                )
                agent = getattr(self.stage_manager, "agent", None)
                if agent is not None:
                    agent.set_break(True)
                warning(f"ACT4 review paused: {self.review_dir}, {self.phase}, {diagnostic.get('location')}")
        return passed, result

    def _changes(self, state: dict[str, Any], review: dict[str, Any]) -> list[str]:
        """Reject candidate changes outside declared repair paths, including modes and deletions."""
        before, after = state["baseline"]["files"], tree_state(self.output / "candidate")
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        allowed = {name for item in review["changes"] for name in item["paths"]}
        if set(changed) - allowed:
            raise ValueError(f"Candidate changes outside review.changes paths: {sorted(set(changed) - allowed)[:20]}")
        return changed

    def _markdown(self, name: str, title: str, data: dict[str, Any],
                  runs: list[tuple[str, dict[str, Any]]]) -> None:
        """Lead with outcomes, unresolved causes and useful requests before technical evidence."""
        text = f"\n# {title}\n\n{data.get('summary', '')}\n\n"
        environment_summary = self.output.parent / "environment" / "summary.md"
        if environment_summary.is_file():
            receipt = json.loads((environment_summary.parent / "receipt.json").read_text(encoding="utf-8"))
            ready = sum(tool["status"] == "ready" for tool in receipt["tools"].values())
            total = len(receipt["tools"])
            text += f"Environment preparation: **{ready}/{total} declared tools ready**. See [environment summary](../environment/summary.md) for unavailable tools and effects; these results do not replace asset validation.\n\n"
        structured = "final.yaml" if name == "final.md" else "review.yaml"
        originals = {item["id"]: item for item in data.get("original_review", data)["findings"]}
        findings = [{**originals[item["id"]], **item} for item in data["findings"]]
        classes = {kind: sum(item["classification"] == kind for item in findings)
                   for kind in ("confirmed_defect", "suspected_defect", "validation_gap", "not_a_defect")}
        outcomes = {status: sum(item.get("status") == status for item in findings)
                    for status in ("fixed", "deferred", "not_fixed", "dismissed")}
        text += (f"Confirmed defects: **{classes['confirmed_defect']}**; suspected defects: **{classes['suspected_defect']}**; "
                 f"validation gaps: **{classes['validation_gap']}**; ruled out: **{classes['not_a_defect']}**.\n\n")
        if name == "final.md":
            text += (f"Fixed: **{outcomes['fixed']}**; deferred: **{outcomes['deferred']}**; not fixed: **{outcomes['not_fixed']}**; "
                     f"dismissed without a patch: **{outcomes['dismissed']}**. "
                     f"Source files changed: **{len(data['changed_paths'])}**. [Patch](changes.patch).\n\n")
        latest = runs[-1][1]
        source = latest["input"]
        text += f"Input: `{source['root']}` ({source['kind']}); patch paths are relative to this input root. "
        if source["kind"] == "directory":
            text += "Local source snapshot; no upstream commit identity or full upstream CI certification is implied. "
        text += "\n\n"
        required = [job for job in latest["jobs"] if not job["optional"]]
        required_passed = any(job["status"] == "passed" for job in required) and all(job["status"] in {"passed", "not_applicable"} for job in required)
        optional_gaps = [job["id"] for job in latest["jobs"] if job["optional"] and job["status"] not in {"passed", "not_applicable"}]
        text += f"Required declared validation: **{'passed' if required_passed else 'incomplete or failed'}**. "
        if optional_gaps:
            text += f"Optional validation not completed: {', '.join(optional_gaps)}. "
        text += "Report completion does not certify every asset or establish measured coverage.\n"
        if latest["isa_plan_limitations"]:
            text += "\nISA-first planning limitations: " + "; ".join(latest["isa_plan_limitations"]) + "\n"
        progress_labels = {"not_started": "Implementation not started", "designing": "Design/investigation in progress",
                           "implemented": "Candidate implementation exists", "validated": "Repair validated", "not_applicable": "No repair required"}
        stop_labels = {"external_dependency": "External dependency", "unfinished_work": "Agent work unfinished", "budget_exhausted": "Budget exhausted"}
        if name == "final.md":
            text += "\n## Repair summary\n\nModule-local findings are counted separately; shared root keys do not merge their evidence.\n\n"
            text += "| Finding | Disposition | Repair progress | Why stopped | Owner / next action |\n| --- | --- | --- | --- | --- |\n"
            for item in findings:
                blocker = item.get("blocker", {})
                action = item.get("next_action", "No remaining repair action")
                cells = [item["id"], item["status"], progress_labels[item["repair_progress"]],
                         stop_labels.get(blocker.get("stop_reason"), "Not stopped"), f"{blocker.get('owner', 'agent')}: {action[:160]}{'…' if len(action) > 160 else ''}"]
                text += "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |\n"
            roots: dict[str, list[str]] = {}
            for item in findings:
                if item.get("root_cause_key"):
                    roots.setdefault(item["root_cause_key"], []).append(item["id"])
            if roots:
                text += "\nShared issue identities (for correlation, not additional defects):\n"
                for key, identities in sorted(roots.items()):
                    text += f"\n- `{key}`: {', '.join(identities)}\n"
        text += "\n## Help requested from the user\n\n"
        requests = [item for item in findings if item.get("blocker", {}).get("owner") == "user"]
        if not requests:
            text += "No user input is currently required. Agent-owned unfinished work remains open; it is not a claim that repair is impossible.\n"
        for item in requests:
            blocker = item["blocker"]
            text += f"- **{item['id']}**: {blocker['request']} Why user help is needed: {blocker['reason_user_needed']}\n"
        text += "\n## Validation achieved\n\n"
        text += f"Scope-wide static checks: **{'passed' if latest['static_passed'] else 'issues remain'}**. Upstream full CI: **not certified**.\n\n"
        text += "| Target | Generation | ELF build | Self-check execution | Coverage job | Lint | CI alignment |\n| --- | --- | --- | --- | --- | --- | --- |\n"
        for target in latest["targets"]:
            jobs = [job for job in latest["jobs"] if job["target"] == target]
            cells = [target]
            for purpose in ("generation", "build", "reference_model", "coverage", "lint"):
                states = sorted({job["status"] + (" (optional)" if job["optional"] else "") for job in jobs if job["purpose"] == purpose})
                cells.append(", ".join(states) or "not run")
            cells.append(", ".join(sorted({job["ci_alignment"]["kind"] for job in jobs if job["purpose"] != "environment"})))
            text += "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |\n"
        text += "\nThese are scoped execution results, not proof that every finding is covered. Successful generation/build is not self-check success; a coverage job is not proof of complete bin hits. Local-only lint and diagnostic experiments are not upstream CI.\n"
        text += "\n## Findings and outcomes\n\n"
        if not findings:
            text += "No findings were recorded within the reviewed scope. The validation limits below still apply.\n"
        for item in findings:
            classification = {"confirmed_defect": "Confirmed defect", "suspected_defect": "Suspected defect",
                              "validation_gap": "Validation limitation", "not_a_defect": "Not a defect"}[item["classification"]]
            diagnosis = {"symptoms_only": "Symptoms observed; cause not yet established",
                         "cause_identified": "Cause identified", "repair_ready": "Evidence supports a concrete repair"}[item["diagnosis"]]
            text += (f"\n### {item['id']} — {item['problem']}\n\n"
                     f"**{classification} / {item.get('status', 'reviewed')}** · {item['severity']} · {item['location']}\n\n"
                     f"{item.get('reason', item['recommendation'])}\n\n"
                     f"Diagnosis: {diagnosis}.\n")
            if item.get("repair_plan"):
                text += f"\nExpected behavior: {item['repair_plan']['expected_behavior']}\n\nDistinguishing observation: {item['repair_plan']['observation']}\n"
            blocker = item.get("blocker")
            if blocker:
                text += (f"\nStop reason: {stop_labels[blocker['stop_reason']]}.\n\nStill missing or unfinished: {blocker['detail']}\n\n"
                         f"Why it remains open: {blocker['why_not_resolved']}\n\n"
                         f"Impact: {blocker['impact']}\n\n"
                         f"Next action ({blocker['owner']}): {item['next_action']}\n")
            for attempt in item["investigation"]:
                text += f"\n- Investigated: {attempt['action']} Result: {attempt['result']}\n"
        text += "\n## Validation limits and evidence\n\n"
        for risk in data.get("remaining_risks", []):
            text += f"- {risk}\n"
        disposition_counts: dict[str, int] = {}
        for judgment in data["semantic_review"]["judgments"]:
            for disposition in judgment.get("diagnostics", {}).values():
                disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        if disposition_counts:
            text += "\nScanner diagnostics (not defect counts): " + "; ".join(f"{kind}: {count}" for kind, count in sorted(disposition_counts.items())) + ". Raw failures remain in the evidence.\n\n"
        text += (f"Full report data: [{structured}]({structured}); [scope.yaml](scope.yaml); "
                 "[baseline.json](baseline.json); [optional tool probes](environment.json).\n")
        if name == "final.md":
            text += "Original review: [review.md](review.md), [review.yaml](review.yaml).\n"
        for tool, record in latest["environment"]["tools"].items():
            text += f"\n- {tool}: **{record['status']}**. {record['reason']}\n"
        for label, evidence in runs:
            source_identity = f"ACT4 HEAD: `{evidence['act4_head']}`" if evidence["act4_head"] else "Local directory snapshot (no Git HEAD)"
            text += (f"\n<details>\n<summary>Native validation ({label})</summary>\n\n"
                     f"\n### Native validation ({label})\n\n{source_identity}. "
                     f"Full evidence: [evidence-{label}.json](evidence-{label}.json).\n\n"
                     "Build task counts are not executed test counts. Only validated model results "
                     "populate the model-test column; blocked jobs have no execution result.\n\n"
                     "| Job | Target | Purpose | Status | ELF files / inputs | Passing model tests | Log |\n"
                     "| --- | --- | --- | --- | --- | --- | --- |\n")
            for job in evidence["jobs"]:
                elf_count = job.get("elf_count", "—")
                if job["purpose"] == "build" and "artifacts" in job:
                    elf_count = sum(item["kind"] == "elf" for item in job["artifacts"])
                cells = [job["id"], job["target"], job["purpose"], job["status"],
                         str(elf_count), str(job.get("executed_tests", "—")),
                         f"[log]({job['log']})" if "log" in job else "—"]
                text += "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |\n"
            for job in evidence["jobs"]:
                if job["status"] in {"passed", "not_applicable"}:
                    continue
                text += f"\n### {job['id']}\n\n{job.get('reason', job['status'])}\n"
                if job.get("blocked_by"):
                    text += f"\nBlocked by: {', '.join(job['blocked_by'])}.\n"
                argv = job.get("argv") or (job.get("attempts") or [{}])[-1].get("argv")
                if argv:
                    text += f"\nCheckout-relative cwd: `{job.get('cwd', '.')}`. Command:\n\n```bash\n{shlex.join(argv)}\n```\n"
                for item in job.get("diagnostics", []):
                    note = " (tail excerpt)" if item["truncated"] else ""
                    text += f"\n- [{item['source_path']}]({item['path']}){note}\n"
                if job.get("diagnostic_summary", {}).get("omitted_files"):
                    text += f"\nDiagnostic file limit reached; inspect evidence-{label}.json and narrow scope.jobs diagnostics before rerunning.\n"
            text += "\n</details>\n"
        judgments = data["semantic_review"]["judgments"]
        counts = {status: sum(len(item["tasks"]) for item in judgments if item["status"] == status)
                  for status in ("passed", "issues", "unverified", "not_applicable")}
        text += "\n## AI semantic review\n\n" + "; ".join(f"{status}: {count}" for status, count in counts.items()) + ".\n\n"
        if name == "final.md":
            reused = sum(len(item["tasks"]) for item in judgments if "reused_from" in item)
            text += f"Reused unchanged judgments: **{reused}**; freshly assessed: **{sum(counts.values()) - reused}**. [Reuse provenance](reuse-final.json).\n\n"
            if self._state().get("experiments"):
                text += "[Experimental attempts and budgets](experiments.json) are separate from formal repair validation.\n\n"
        text += f"Every judgment's reasoning, confidence, source quotations and limitations are in [{structured}]({structured}).\n"
        trace = data.get("traceability", [])
        counts = {status: sum(item["coverage"] == status for item in trace)
                  for status in ("measured", "static", "gap", "unverified")}
        if latest["isa_requirements"]:
            text += "\n## Independent ISA plan comparison\n\n"
            text += "[ISA-first design](isa-plan.yaml) is a review baseline, not proof of completeness. Later corrections retain the original requirement IDs.\n\n"
            text += "| ISA requirement | Review obligations | Asset status | Findings |\n| --- | --- | --- | --- |\n"
            for identity in latest["isa_requirements"]:
                matches = [item for item in data["obligations"] if identity in item["plan_items"]]
                cells = [identity, ", ".join(item["id"] for item in matches) or "Not compared",
                         ", ".join(sorted({item["status"] for item in matches})),
                         ", ".join(sorted({finding for item in matches for finding in item["findings"]})) or "None"]
                text += "| " + " | ".join(cells) + " |\n"
        text += "\n## Coverpoint traceability\n\n" + "; ".join(f"{status}: {count}" for status, count in counts.items()) + ".\n\n"
        text += f"Every point's obligation, testcases and evidence are in [{structured}]({structured}).\n"
        text += f"\nSource-derived obligations: **{len(data['obligations'])}** across **{len(latest['obligation_sources'])}** source blocks; forward mappings and exclusions are in [{structured}]({structured}).\n"
        if not data.get("changes", data.get("changed_paths", [])):
            text += "\nNo source changes are included. Unresolved findings remain documented with reasons and follow-up actions.\n"
        safe_path(self.output, name).write_text(text, encoding="utf-8")

    def _final(self, review: dict[str, Any],
               evidence: dict[str, Any], changed: list[str], publish: bool = True) -> dict[str, Any]:
        """Validate all dispositions and generate a portable text-source patch and final report."""
        final = self._load("final.yaml")
        if final.get("suite") != self.suite or not is_text(final.get("summary")):
            raise ValueError("final.yaml requires this suite and a summary")
        results = final.get("findings")
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise ValueError("final.findings must list each reviewed finding exactly once")
        ids = [item.get("id") for item in results]
        if not is_text_list(ids, allow_empty=True) or len(set(ids)) != len(ids) or set(ids) != {item["id"] for item in review["findings"]}:
            raise ValueError("Final dispositions must cover all original findings exactly once")
        for item in results:
            if item.get("status") not in {"fixed", "deferred", "not_fixed", "dismissed"} or not is_text_list(item.get("evidence")) or not is_text(item.get("reason")):
                raise ValueError("Final findings need fixed/deferred/not_fixed/dismissed, a nonempty evidence string list, and textual reason")
            if item["status"] in {"deferred", "not_fixed"} and not is_text(item.get("next_action")):
                raise ValueError(f"Finding {item['id']} needs next_action describing the missing information or follow-up required for repair")
            progress = item.get("repair_progress")
            expected = {"fixed": {"validated"}, "dismissed": {"not_applicable"},
                        "deferred": {"not_started", "designing", "implemented"}, "not_fixed": {"not_started", "designing", "implemented"}}[item["status"]]
            if progress not in expected:
                raise ValueError(f"Finding {item['id']} repair_progress must be one of {sorted(expected)} for disposition {item['status']}")
            if progress == "implemented":
                formal = any(set(change["paths"]) & set(changed) for change in review["changes"] if item["id"] in change["findings"])
                experimental = any(self._state().get("experiments", {}).get(plan["id"], {}).get("changed_paths") and
                    self._state()["experiments"][plan["id"]]["status"] == "completed"
                    for plan in review.get("experiments", []) if item["id"] in plan["findings"])
                if not formal and not experimental:
                    raise ValueError(f"Finding {item['id']} cannot claim implemented without a declared source change or retained experimental implementation")
            original = next(finding for finding in review["findings"] if finding["id"] == item["id"])
            if "root_cause_key" in item and item["root_cause_key"] != original.get("root_cause_key"):
                raise ValueError("Update root_cause_key in the reviewed finding before using it for final correlation")
            if item["status"] == "fixed":
                proposals = [change for change in review["changes"] if item["id"] in change["findings"]]
                if not any(set(change["paths"]) & set(changed) for change in proposals):
                    raise ValueError(f"Finding {item['id']} claims a fix without a declared source change")
                required = {job for change in proposals for job in change["validation_jobs"]}
                if any(job["status"] != "passed" for job in evidence["jobs"] if job["id"] in required):
                    raise ValueError(f"Finding {item['id']} cannot be fixed without passing its validation jobs")
        self._traceability(final.get("traceability"), evidence, partial=not publish)
        self._semantic_review(final, evidence, review=review, changed=changed, partial=not publish)
        self._validation_section, self._validation_location = "conclusion", "final.yaml"
        before_evidence = self._load("evidence-before.json")
        coverage_delta = set(before_evidence["coverpoints"]) ^ set(evidence["coverpoints"])
        ci_passed = any(job["status"] == "passed" for job in evidence["jobs"]) and all(job["status"] in {"passed", "not_applicable"} for job in evidence["jobs"])
        if type(final.get("ci_passed")) is not bool or final["ci_passed"] != ci_passed:
            raise ValueError("final.ci_passed must exactly match recorded command results")
        for field in ("remaining_risks", "coverage_changes"):
            if not isinstance(final.get(field), list):
                raise ValueError(f"final.{field} must be a list")
        if not is_text_list(final["remaining_risks"], allow_empty=True):
            raise ValueError("final.remaining_risks must list nonempty textual limitations")
        described = set()
        for item in final["coverage_changes"]:
            if not isinstance(item, dict) or not is_text(item.get("coverpoint")) or not is_text(item.get("reason")):
                raise ValueError("coverage_changes entries need coverpoint and reason")
            described.add(item["coverpoint"])
        if coverage_delta - described:
            raise ValueError(f"Describe every added or removed coverpoint: {sorted(coverage_delta - described)}")
        semantic_risks = any(item["status"] in {"issues", "unverified"} or item["confidence"] != "confirmed"
                             for item in final["semantic_review"]["judgments"])
        if (not ci_passed or not evidence["static_passed"] or semantic_risks or any(item["status"] != "fixed" for item in results)) and not final["remaining_risks"]:
            raise ValueError("Unresolved findings, AI judgments or CI limitations must appear in remaining_risks")
        if not publish:
            return final
        patch = []
        for name in changed:
            before, after = self.output / "baseline" / name, self.output / "candidate" / name
            if before.is_symlink() or after.is_symlink():
                raise ValueError(f"Do not change symlink source assets: {name}")
            old = before.read_bytes().decode("utf-8").splitlines(keepends=True) if before.exists() else []
            new = after.read_bytes().decode("utf-8").splitlines(keepends=True) if after.exists() else []
            if any("\x00" in line for line in old + new):
                raise ValueError(f"Review patches support UTF-8 text source changes only: {name}")
            patch.append(f"diff --git a/{name} b/{name}\n")
            if not before.exists():
                patch.append(f"new file mode {stat.S_IFREG | stat.S_IMODE(after.stat().st_mode):o}\n")
            elif not after.exists():
                patch.append(f"deleted file mode {stat.S_IFREG | stat.S_IMODE(before.stat().st_mode):o}\n")
            elif before.stat().st_mode != after.stat().st_mode:
                patch.extend([f"old mode {stat.S_IFREG | stat.S_IMODE(before.stat().st_mode):o}\n",
                              f"new mode {stat.S_IFREG | stat.S_IMODE(after.stat().st_mode):o}\n"])
            for line in difflib.unified_diff(old, new, fromfile=f"a/{name}" if before.exists() else "/dev/null",
                                             tofile=f"b/{name}" if after.exists() else "/dev/null"):
                patch.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        safe_path(self.output, "changes.patch").write_bytes("".join(patch).encode("utf-8"))
        final.update(changed_paths=changed,
                     asset_checks_passed=evidence["static_passed"],
                     original_review=review, before=before_evidence, after=evidence,
                     patch="changes.patch", input_checkout_modified=False)
        self._markdown("final.md", "ACT4 Extension Review and Repair Report", final,
                       [("before", before_evidence), ("after", evidence)])
        return final

    def do_check(self, is_complete: bool = False, run_commands: bool = False, refresh_tools: bool = False,
                 experiment: dict[str, Any] | None = None,
                 **kwargs: Any) -> tuple[bool, dict[str, Any]]:
        """Validate current review evidence, scoped candidate repairs, and final dispositions."""
        self._validation_section, self._validation_location = "scope", "scope.yaml"
        try:
            if type(run_commands) is not bool or type(refresh_tools) is not bool:
                raise ValueError("run_commands and refresh_tools must be booleans")
            if experiment is not None and (not isinstance(experiment, dict) or set(experiment) != {"action", "id"} or experiment.get("action") not in {"prepare", "run", "status"} or is_complete or run_commands or refresh_tools):
                raise ValueError("Use Check(stage_args={experiment: {action: prepare/run/status, id: E<number>}}) in audit/repair, without Complete or other execution arguments")
            if self.phase == "plan" and (run_commands or experiment is not None):
                raise ValueError("review_plan reads ISA sources only; finish the independent design before asset commands or experiments")
            if refresh_tools and self.phase not in {"plan", "audit"}:
                raise ValueError("Refresh optional tools in review_plan or review_audit, then recollect before and after evidence")
            workspace = Path(self.workspace).resolve()
            self.source = safe_path(workspace, self.act4_root)
            self.output = safe_path(workspace, self.review_dir)
            self.environment = prepared_environment(self.output.parent / "environment", self.smanager_get_value if self.stage_manager else None)
            if self.output.resolve().is_relative_to(self.source.resolve()) or self.source.resolve().is_relative_to(self.output.resolve()):
                raise ValueError("Review artifacts and input checkout must be separate")
            self.output.mkdir(parents=True, exist_ok=True)
            state = self._state()
            if experiment is not None and self.phase == "final":
                if experiment["id"] not in state.get("experiments", {}):
                    raise ValueError("Prepare the experiment with the repair checker before inspecting final-stage status")
                return self._checked_result(True, {"experiment": experiment["id"], "final_review": "not_checked",
                    "next_action": "The experiment does not validate final.yaml; run ordinary Check and Complete after formal repair validation"})
            environment = self._environment(state, refresh_tools)
            if self.phase == "plan" and not (self.output / "isa-plan.yaml").exists() and not is_complete:
                return self._checked_result(True, {"environment": "environment.json",
                    "next_action": "Create isa-plan.yaml from user scope and ISA only, then Check to obtain isa-plan-context.json. Do not read existing CTP, coverage, generators, mappings or CI yet."})
            plan = self._isa_plan(state, is_complete)
            if self.phase == "plan":
                return self._checked_result(True, {"plan": "isa-plan.yaml", "requirements": len(plan["requirements"]),
                    "accepted": "isa_plan" in state,
                    "next_action": "Continue to review_audit and compare every ISA requirement with assets." if is_complete else "Call Complete to freeze the ISA-first design before reviewing assets."})
            if self.phase == "audit" and not (self.output / "scope.yaml").exists() and not is_complete:
                return self._checked_result(True, {"environment": "environment.json", "optional_tools": {name: item["status"] for name, item in environment["tools"].items()},
                              "next_action": "Create scope.yaml using the detected capabilities; optional simulators must not be prerequisites of generation/build/model/lint."})
            scope = self._scope()
            self._validation_section, self._validation_location = "baseline", "baseline.json"
            self._baseline(state, scope)
            candidate = self.output / "candidate"
            if candidate.is_symlink():
                raise ValueError("Repair candidate must not be a symlink")
            if candidate.exists() and state.get("candidate_prepared") is not True:
                raise ValueError("Candidate was not prepared from the frozen baseline by Check; use a fresh review output")
            if self.phase == "audit" and not run_commands and not is_complete and not state.get("evidence-before"):
                return self._checked_result(True, {"baseline": "baseline.json", "scope": "scope.yaml",
                              "next_action": 'Run Check(stage_args={"run_commands": true}), then write review.yaml using evidence-before.json'})
            self._validation_section, self._validation_location = "evidence", "evidence-before.json"
            before = self._evidence(state, scope, self.output / "baseline", "before",
                                    run_commands and self.phase == "audit")
            self._validation_section, self._validation_location = "document", "review.yaml"
            review = self._review(scope, before, partial=self.phase == "audit")
            if experiment is not None:
                self._validation_section, self._validation_location = "experiment", str(experiment["id"])
                plan = next((item for item in review.get("experiments", []) if item["id"] == experiment["id"]), None)
                if plan is None:
                    raise ValueError("Declare this experiment in review.yaml before preparing or running it")
                directory = safe_path(self.output, f"experiments/{plan['id']}/candidate")
                experiments = state.setdefault("experiments", {})
                prepared = experiments.get(plan["id"])
                if experiment["action"] == "status":
                    status = {key: value for key, value in (prepared or {"status": "not_prepared"}).items() if key != "inputs"}
                    return self._checked_result(True, {"experiment": plan["id"], "state": status, "acceptance": "Experiment status does not complete the review"})
                if experiment["action"] == "prepare":
                    if prepared is not None or directory.exists():
                        raise ValueError("Experiment already prepared; use status/run, or declare a new ID for a different attempt")
                    base = candidate if candidate.exists() else self.output / "baseline"
                    if candidate.exists():
                        self._changes(state, review)
                    inputs = tree_state(base)
                    copy_sources(base, directory, inputs)
                    experiments[plan["id"]] = {"plan": digest(plan), "inputs": inputs, "status": "prepared"}
                    return self._checked_result(True, {"experiment": plan["id"], "candidate": str(directory.relative_to(self.output)), "editable_paths": plan["paths"],
                        "next_action": "Implement only the declared experimental paths, then Check with experiment action run; do not edit the formal candidate"})
                if prepared is None or prepared["plan"] != digest(plan) or prepared["status"] != "prepared":
                    raise ValueError("Experiment must be prepared, unchanged in declaration and not previously run; use a new ID after a completed or interrupted attempt")
                current = tree_state(directory)
                changed = {name for name in current.keys() | prepared["inputs"].keys() if current.get(name) != prepared["inputs"].get(name)}
                if changed - set(plan["paths"]):
                    raise ValueError(f"Experiment changed undeclared paths: {sorted(changed - set(plan['paths']))}")
                used = sum(item["status"] != "prepared" for item in experiments.values())
                elapsed = sum(item.get("seconds", self.max_experiment_seconds if item["status"] == "running" else 0) for item in experiments.values())
                if used >= self.max_experiments or elapsed >= self.max_experiment_seconds:
                    raise ValueError("Experiment budget exhausted; preserve partial results and report budget_exhausted with the next continuation action")
                selected = set(plan["jobs"])
                while True:
                    expanded = selected | {name for job in scope["jobs"] if job["id"] in selected for name in job.get("needs", [])}
                    if expanded == selected:
                        break
                    selected = expanded
                experiment_scope = {**scope, "assets": plan["assets"], "jobs": [copy.deepcopy(job) for job in scope["jobs"] if job["id"] in selected]}
                prepared["status"] = "running"
                prepared["changed_paths"] = sorted(changed)
                started = time.monotonic()
                label = f"experiment-{plan['id']}"
                try:
                    receipt = self._evidence(state, experiment_scope, directory, label, True,
                                             deadline=started + self.max_experiment_seconds - elapsed)
                    prepared.update(status="completed", jobs={job["id"]: job["status"] for job in receipt["jobs"]})
                    name = f"evidence-{label}.json"
                    state.setdefault("experiment_receipts", {})[name] = hashlib.sha256(safe_path(self.output, name).read_bytes()).hexdigest()
                finally:
                    prepared["seconds"] = time.monotonic() - started
                    if prepared["status"] == "running":
                        prepared["status"] = "interrupted"
                    self._write("experiments.json", {"schema_version": 1, "receipts": state.get("experiment_receipts", {}),
                        "attempts": {identity: {key: value for key, value in item.items() if key != "inputs"} for identity, item in experiments.items()},
                        "budget": {"max_experiments": self.max_experiments, "max_seconds": self.max_experiment_seconds}})
                    state["experiment_index"] = hashlib.sha256(safe_path(self.output, "experiments.json").read_bytes()).hexdigest()
                self._baseline(state, scope)
                return self._checked_result(True, {"experiment": plan["id"], "evidence": name, "jobs": prepared["jobs"],
                    "next_action": "Inspect generated sources, signatures and logs against success_criterion; update investigation before promoting a repair. This is not formal validation or stage completion."})
            if self.phase == "audit":
                passed, result = self._review_batch(is_complete)
                if not passed:
                    return self._checked_result(passed, result)
                self._review(scope, before)
            self._markdown("review.md", "ACT4 Extension Review", review, [("before", before)])
            if self.phase == "audit":
                self._write("review-accepted.json", {"schema_version": 1, "review": review, "evidence_digest": before["review_digest"]})
                state["audit_snapshot"] = hashlib.sha256(safe_path(self.output, "review-accepted.json").read_bytes()).hexdigest()
                return self._checked_result(True, {"report": "review.md", "asset_health": before["static_passed"]})
            if not candidate.exists():
                if self.phase != "repair":
                    raise ValueError("Candidate missing; run Check in review_repair to prepare it")
                copy_sources(self.output / "baseline", candidate, state["baseline"]["files"])
                state["candidate_prepared"] = True
            changed = self._changes(state, review)
            if self.phase == "repair" and not run_commands and not is_complete:
                return self._checked_result(True, {"candidate": str(candidate), "changed_paths": changed,
                              "next_action": 'Repair evidence-supported review.changes paths; document unresolved findings, then Check(stage_args={"run_commands": true}) and create final.yaml'})
            for kind in ASSET_KINDS:
                for name in set(scope["assets"][kind]) - set(review["post_assets"][kind]):
                    if safe_path(candidate, name).exists():
                        raise ValueError(f"post_assets must not hide an existing reviewed asset: {name}")
            post_scope = {**scope, "assets": review["post_assets"]}
            self._validation_section, self._validation_location = "evidence", "evidence-after.json"
            after = self._evidence(state, post_scope, candidate, "after", run_commands and self.phase == "repair")
            if self.phase == "final":
                self._validation_section, self._validation_location = "document", "final.yaml"
                self._final(review, after, changed, publish=False)
                passed, result = self._review_batch(is_complete)
                if not passed:
                    return self._checked_result(passed, result)
                self._final(review, after, changed)
            self._baseline(state, scope)
            return self._checked_result(True, {"report": "final.md" if self.phase == "final" else "evidence-after.json",
                          "changed_paths": changed, "ci": [{key: value for key, value in job.items()
                              if key in {"id", "status", "purpose", "log", "reason", "elf_count", "executed_tests"}}
                              for job in after["jobs"]]})
        except (ValueError, TypeError, KeyError, OSError, re.error, yaml.YAMLError, subprocess.SubprocessError) as exc:
            if isinstance(exc, yaml.YAMLError) and getattr(exc, "problem_mark", None):
                self._validation_section = "yaml"
                self._validation_location += f":{exc.problem_mark.line + 1}:{exc.problem_mark.column + 1}"
            return self._checked_result(False, {"error_code": f"act4_review_{self._validation_section}", "error": str(exc),
                           "location": self._validation_location,
                           "artifact": self.review_dir, "phase": self.phase,
                           "next_action": "Correct the named review artifact and rerun Check; follow Guide_Doc/ACT4_Extension_Review_Guide.md"})
