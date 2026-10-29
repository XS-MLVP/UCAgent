"""Audit existing ACT4 assets, bind human approval, and validate scoped repairs."""

from __future__ import annotations

import difflib
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

from ucagent.checkers.base import CB_KEY_ON_INIT, Checker

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
                    timeout: int, append: bool = False) -> dict[str, Any]:
    """Run a real command with a bounded lifetime and preserve startup and timeout failures."""
    started = time.monotonic()
    result: dict[str, Any] = {"argv": argv, "started_at": datetime.now(timezone.utc).isoformat()}
    with log.open("ab" if append else "wb") as stream:
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


class ACT4ReviewChecker(Checker):
    """Gate review completeness separately from asset health and human permission."""

    accepted_stage_args = ("run_commands",)

    def __init__(self, phase: str, suite: str, review_dir: str,
                 act4_root: str = "riscv-arch-test", **kwargs: Any) -> None:
        """Store stage configuration without inspecting the live workspace."""
        super().__init__()
        kwargs.pop("cfg", None)
        if kwargs or phase not in {"inventory", "audit", "authorize", "repair", "final"}:
            raise ValueError("Invalid ACT4 review phase or checker arguments")
        self.phase, self.suite = phase, suite
        self.review_dir, self.act4_root = review_dir, act4_root
        self._approval_callback_installed = False
        if phase == "authorize":
            self.add_cb(CB_KEY_ON_INIT, self._install_approval_callback)

    def _install_approval_callback(self, checker: Any) -> None:
        """Attach the completion hook after the stage has finished construction."""
        if not self._approval_callback_installed:
            self.stage.append_on_complete_callback(self._capture_approval)
            self._approval_callback_installed = True

    def _capture_approval(self, stage: Any) -> None:
        """Persist approval only after the real human-gated stage actually completes."""
        state = self._state()
        passed, message = stage.get_hmcheck_state()
        if passed is True and message.strip() == state.get("pending_digest"):
            state["approved_digest"] = message.strip()
            self.stage_manager.save_stage_info()

    def _state(self) -> dict[str, Any]:
        """Access persisted controller-owned state, never an agent-authored approval file."""
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

    def _baseline(self, state: dict[str, Any], scope: dict[str, Any]) -> None:
        """Freeze actual dirty or clean source state and reject subsequent input drift."""
        if self.source.is_symlink() or not (self.source / ".git").is_dir():
            raise ValueError("riscv-arch-test must be an independent Git clone, not a worktree")
        repositories = [self.source]
        paths = {name for values in scope["assets"].values() for name in values}
        submodules = []
        for repository in repositories:
            index = subprocess.check_output(
                ["git", "-C", str(repository), "ls-files", "--stage", "-z"],
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
        current = tree_state(self.source, sorted(paths))
        head = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True).strip()
        module_heads = {name: subprocess.check_output(["git", "-C", str(self.source / name), "rev-parse", "HEAD"], text=True).strip()
                        for name in submodules}
        references = tree_state(Path(self.workspace), scope["reference_files"])
        identity = {"head": head, "submodules": module_heads, "files": current,
                    "references": references}
        baseline = self.output / "baseline"
        reference_root = self.output / "references"
        if baseline.is_symlink() or reference_root.is_symlink():
            raise ValueError("Frozen input directories must not be symlinks")
        if "baseline" not in state:
            if self.phase != "inventory" or baseline.exists():
                raise ValueError("Baseline trust state is missing; start a new review output and obtain new approval")
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
        for field in ("targets", "references", "discovery"):
            if not is_text_list(scope.get(field)):
                raise ValueError(f"scope.{field} must document the complete review boundary as nonempty strings")
        reference_files = scope.get("reference_files")
        if not is_text_list(reference_files, allow_empty=True) or len(set(reference_files)) != len(reference_files):
            raise ValueError("scope.reference_files must list unique workspace-relative specification inputs; use [] and report missing sources")
        for name in reference_files:
            path = safe_path(Path(self.workspace), name)
            if path.resolve().is_relative_to(self.output.resolve()) or not path.is_file() or path.is_symlink():
                raise ValueError(f"Reference inputs must be existing files outside the review output: {name}")
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
        return scope

    def _evidence(self, state: dict[str, Any], scope: dict[str, Any], tree: Path,
                  label: str, run_commands: bool) -> dict[str, Any]:
        """Reuse asset checks and record real isolated command results bound to input bytes."""
        fingerprint = digest({"sources": evidence_fingerprint(tree, scope),
                              "references": state["baseline"]["references"]})
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
        results = []
        missing = sorted({name for names in scope["assets"].values() for name in names
                          if not safe_path(tree, name).is_file()})
        passed = not missing
        for mapping in scope["assets"]["mappings"] or [None]:
            checker = ACT4AssetChecker(
                suite=self.suite, act4_root=str(tree),
                coverage_files=[str(tree / name) for name in scope["assets"]["coverage"]],
                discover_coverage=False,
                generator_files=[str(tree / name) for name in scope["assets"]["generators"]],
                mapping=str(tree / mapping) if mapping else None,
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
                    "static_passed": passed, "static": results, "missing_assets": missing, "coverpoints": points,
                    "reachability": reachability,
                    "duplicate_assets": [sorted(names) for names in duplicates.values() if len(names) > 1], "jobs": []}
        with tempfile.TemporaryDirectory(prefix=f"run-{label}-", dir=self.output) as temporary:
            execution = Path(temporary) / "checkout"
            subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(self.source), str(execution)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(execution), "read-tree", state["baseline"]["head"]], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(execution), "update-ref", "--no-deref", "HEAD", state["baseline"]["head"]], check=True, capture_output=True)
            for name, head in state["baseline"]["submodules"].items():
                module = safe_path(execution, name)
                subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(self.source / name), str(module)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(module), "read-tree", head], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(module), "update-ref", "--no-deref", "HEAD", head], check=True, capture_output=True)
            copy_sources(tree, execution, tree_state(tree))
            for repository in reversed([execution, *(execution / name for name in state["baseline"]["submodules"])]):
                subprocess.run(["git", "-C", str(repository), "add", "--force", "--all"], check=True, capture_output=True)
            tools = safe_path(self.output, "tools")
            (tools / "bin").mkdir(parents=True, exist_ok=True)
            environment = {**os.environ, "PATH": str(tools / "bin") + os.pathsep + os.environ.get("PATH", "")}
            records: dict[str, dict[str, Any]] = {}
            pending = list(scope["jobs"])
            while pending:
                job = next(item for item in pending if all(name in records for name in item.get("needs", [])))
                pending.remove(job)
                record = {"id": job["id"], "target": job["target"],
                          "purpose": job["purpose"], "status": job["disposition"]}
                records[job["id"]] = record
                blocked = [name for name in job.get("needs", []) if records[name]["status"] != "passed"]
                if job["disposition"] != "run":
                    record["reason"] = job["reason"]
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
                        attempts = [execute_command(probe, cwd, environment, log, job["timeout_seconds"])]
                        pattern = job.get("expected_output")
                        matched = attempts[-1]["status"] == "passed" and (
                            pattern is None or re.search(pattern, log.read_text(errors="replace")) is not None)
                        if not matched and "install" in job:
                            install = [arg.replace("{TOOLS}", str(tools)) for arg in job["install"]]
                            attempts.append(execute_command(install, cwd, environment, log, job["timeout_seconds"], append=True))
                            if attempts[-1]["status"] == "passed":
                                probe_log = safe_path(self.output, f"{label}-{job['id']}-probe.log")
                                attempts.append(execute_command(probe, cwd, environment, probe_log, job["timeout_seconds"]))
                                matched = attempts[-1]["status"] == "passed" and (
                                    pattern is None or re.search(pattern, probe_log.read_text(errors="replace")) is not None)
                                record.update(probe_log=str(probe_log.relative_to(self.output)),
                                              probe_log_sha256=hashlib.sha256(probe_log.read_bytes()).hexdigest())
                        record.update(status="passed" if matched else "unavailable", attempts=attempts,
                                      installed=len(attempts) == 3 and matched)
                        if not matched:
                            record["reason"] = job.get("reason", "Tool preparation failed; inspect the installation/probe log, provide the required tool version and rerun")
                    else:
                        record.update(execute_command(job["argv"], cwd, environment, log, job["timeout_seconds"]))
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
        source_prefix = "baseline" if label == "before" else "candidate"
        evidence["source_files"] = {
            f"{source_prefix}/{name}": identity["sha256"]
            for name, identity in tree_state(tree).items() if identity["kind"] == "file"}
        evidence["source_files"].update({
            f"references/{name}": identity["sha256"]
            for name, identity in state["baseline"]["references"].items() if identity["kind"] == "file"})
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
                    tasks[f"diagnostic:{report_number}:{finding_number}"] = {
                        "topic": "act4_compliance", "question": "Determine whether this diagnostic is an asset defect, scanner limitation, scope mismatch or unresolved issue; cite the relevant source.",
                        "check": finding["check"], "severity": finding["severity"],
                        "message": finding["message"]}
                    if isinstance(finding.get("file"), str):
                        path = Path(finding["file"])
                        if path.is_file() and path.resolve().is_relative_to(tree.resolve()):
                            task = tasks[f"diagnostic:{report_number}:{finding_number}"]
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
        if digest({"sources": evidence_fingerprint(tree, scope),
                   "references": state["baseline"]["references"]}) != fingerprint:
            raise ValueError("Source changed during validation; discard results and retry")
        self._write(f"evidence-{label}.json", evidence)
        state[f"evidence-{label}"] = digest(evidence)
        return evidence

    def _review(self, scope: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
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
        for change in changes:
            if not isinstance(change, dict) or not is_text_list(change.get("findings")) or not set(change["findings"]) <= ids:
                raise ValueError("Each change must reference existing finding ids")
            if not is_text_list(change.get("paths")) or not is_text(change.get("action")) or not is_text(change.get("risk")):
                raise ValueError("Each change needs exact paths, action, and risk")
            if not is_text_list(change.get("validation_jobs")) or not set(change["validation_jobs"]) <= {job["id"] for job in scope["jobs"]}:
                raise ValueError("Each change needs declared validation_jobs")
            for name in change["paths"]:
                path = safe_path(self.source, name)
                if path.is_symlink():
                    raise ValueError(f"Repair proposals must target regular source files: {name}")
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
                raise ValueError("Changed post-review asset membership must be within approved source paths")
        self._traceability(review.get("traceability"), evidence)
        if checks["ci"]["status"] == "passed" and (not any(job["status"] == "passed" for job in evidence["jobs"]) or any(job["status"] not in {"passed", "not_applicable"} for job in evidence["jobs"])):
            raise ValueError("CI cannot be passed with failed, unavailable, or unexecuted jobs")
        if checks["act4_compliance"]["status"] == "passed" and not evidence["static_passed"]:
            raise ValueError("ACT4 compliance cannot pass while deterministic checks report errors")
        if checks["test_coverage"]["status"] == "passed" and (not review["traceability"] or any(item["coverage"] != "measured" for item in review["traceability"])):
            raise ValueError("Test coverage cannot pass while coverpoints have gaps or only static/unverified evidence")
        self._semantic_review(review, evidence)
        return review

    def _semantic_review(self, document: dict[str, Any], evidence: dict[str, Any],
                         review: dict[str, Any] | None = None, changed: list[str] | None = None) -> None:
        """Require source-grounded AI judgments for every unresolved semantic obligation."""
        semantic = document.get("semantic_review")
        if not isinstance(semantic, dict) or semantic.get("reviewer") != "ai":
            raise ValueError("Write semantic_review with reviewer: ai using Guide_Doc/ACT4_Extension_Review_Guide.md")
        if semantic.get("evidence_digest") != evidence["review_digest"]:
            raise ValueError(f"Review the current evidence and set semantic_review.evidence_digest to {evidence['review_digest']}")
        tasks = dict(evidence["review_tasks"])
        if review is not None:
            tasks.update({f"finding:{item['id']}": {"topic": item["topic"]} for item in review["findings"]})
            tasks.update({f"change:{name}": {"topic": "contribution_quality"} for name in changed or []})
        allowed = dict(evidence["source_files"])
        evidence_name = "evidence-before.json" if review is None else "evidence-after.json"
        allowed[evidence_name] = hashlib.sha256((json.dumps(evidence, indent=2) + "\n").encode()).hexdigest()
        if review is not None:
            allowed.update(self._load("evidence-before.json")["source_files"])
        for job in evidence["jobs"]:
            for field in ("log", "probe_log"):
                if field in job:
                    allowed[job[field]] = job[f"{field}_sha256"]
            allowed.update({item["path"]: item["sha256"]
                            for item in job.get("artifacts", []) + job.get("diagnostics", [])})
        judgments = semantic.get("judgments")
        if not isinstance(judgments, list) or not judgments:
            raise ValueError("semantic_review.judgments must assess every evidence review_task; an empty or missing AI review cannot pass")
        observed = set()
        finding_ids = {item["id"] for item in document["findings"]}
        source_lines = {}
        for judgment in judgments:
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
            if not isinstance(basis, list) or not basis:
                raise ValueError("AI judgments require source evidence with path, lines, exact quote and observation")
            for citation in basis:
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
                lines = citation.get("lines")
                physical = source_lines[name]
                if not isinstance(lines, list) or len(lines) != 2 or any(type(number) is not int for number in lines) or not 1 <= lines[0] <= lines[1] <= len(physical) or lines[1] - lines[0] >= 100:
                    raise ValueError(f"AI basis.lines must select 1..100 existing physical lines: {citation['path']}")
                if not is_text(citation.get("quote")) or citation["quote"] != "\n".join(physical[lines[0] - 1:lines[1]]):
                    raise ValueError(f"AI basis.quote must exactly match the selected source lines: {citation['path']}")
                if not is_text(citation.get("observation")):
                    raise ValueError("AI basis.observation must explain what the quoted source establishes")
            if status == "passed" and any(task in {"topic:omissions", "topic:coverpoint_quality"} for task in subjects) and not any(item["path"].startswith("references/") for item in basis):
                raise ValueError("Passing specification-completeness or coverpoint-quality review needs a frozen reference citation; declare scope.reference_files or report unverified")
            for subject in subjects:
                task = tasks[subject]
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
                if review is not None and subject.startswith("finding:"):
                    finding = next(item for item in document["findings"] if subject == f"finding:{item['id']}")
                    if finding["status"] == "fixed" and status != "passed":
                        raise ValueError(f"Finding {finding['id']} cannot be fixed while its AI reassessment is {status}")
                    if finding["status"] == "fixed":
                        paths = {name for change in review["changes"] if finding["id"] in change["findings"]
                                 for name in change["paths"] if name in (changed or [])}
                        sources = {f"candidate/{name}" if f"candidate/{name}" in evidence["source_files"] else f"baseline/{name}"
                                   for name in paths}
                        if not sources.intersection(item["path"] for item in basis):
                            raise ValueError(f"AI reassessment of fixed finding {finding['id']} must cite its approved changed source")
            if review is None and status in {"issues", "unverified"}:
                for subject in subjects:
                    topic = tasks[subject]["topic"]
                    if document["checks"][topic]["status"] == "passed":
                        raise ValueError(f"Topic {topic} cannot pass with an issues/unverified AI judgment")
        if observed != tasks.keys():
            missing = sorted(tasks.keys() - observed)
            raise ValueError(f"AI review is incomplete: {len(missing)} tasks missing; first tasks: {missing[:12]}; read the complete evidence.review_tasks")

    def _traceability(self, trace: Any, evidence: dict[str, Any]) -> None:
        """Check complete coverpoint accounting without treating static presence as hits."""
        if not isinstance(trace, list):
            raise ValueError("review.traceability must enumerate all defined coverpoints")
        observed = set()
        for item in trace:
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
        if observed != set(evidence["coverpoints"]):
            raise ValueError("Traceability must list every scanned group/coverpoint exactly once")

    def _authorization(self, state: dict[str, Any], scope: dict[str, Any],
                       review: dict[str, Any]) -> str:
        """Bind operator approval to baseline, proposal, matrix, and original evidence."""
        approval = digest({"baseline": state["baseline"], "scope": scope,
                           "review": review, "evidence": state["evidence-before"]})
        paths = sorted({path for item in review["changes"] for path in item["paths"]})
        self._write("authorization.json", {"schema_version": 1, "digest": approval,
                    "paths": paths, "mode": "repair" if paths else "report_only",
                    "findings_without_changes": sorted({item["id"] for item in review["findings"]}
                        - {name for item in review["changes"] for name in item["findings"]}),
                    "operator_command": f"hmcheck_pass {approval}"})
        return approval

    def _require_approval(self, state: dict[str, Any], approval: str) -> None:
        """Accept only a receipt produced from the real stage human gate."""
        if state.get("approved_digest") != approval:
            raise ValueError("No matching human authorization; return to review_authorization and request approval")
        gate = next((stage for stage in self.stage_manager.stages if stage.name == "review_authorization"), None)
        if gate is None or not gate.is_completed() or not gate.is_hmcheck_needed() or gate.is_skipped():
            raise ValueError("The human authorization stage is required")
        passed, message = gate.get_hmcheck_state()
        if passed is False or (passed is True and message.strip() != approval):
            raise ValueError("Human authorization was rejected or does not match the current proposal")

    def _changes(self, state: dict[str, Any], review: dict[str, Any]) -> list[str]:
        """Reject candidate changes outside approved exact paths, including modes and deletions."""
        before, after = state["baseline"]["files"], tree_state(self.output / "candidate")
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        allowed = {name for item in review["changes"] for name in item["paths"]}
        if set(changed) - allowed:
            raise ValueError(f"Unauthorized candidate changes: {sorted(set(changed) - allowed)[:20]}")
        return changed

    def _markdown(self, name: str, title: str, data: dict[str, Any],
                  runs: list[tuple[str, dict[str, Any]]]) -> None:
        """Render decisions and native outcomes with links to complete machine evidence."""
        text = f"\n# {title}\n\n{data.get('summary', '')}\n\n"
        structured = "final.yaml" if name == "final.md" else "review.yaml"
        text += (f"Full report data: [{structured}]({structured}); [scope.yaml](scope.yaml); "
                 "[baseline.json](baseline.json); [authorization.json](authorization.json).\n")
        if name == "final.md":
            text += "Original review: [review.md](review.md), [review.yaml](review.yaml).\n"
        for label, evidence in runs:
            text += (f"\n## Native validation ({label})\n\nACT4 HEAD: `{evidence['act4_head']}`. "
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
        for field, value in data.items():
            if field in {"schema_version", "suite", "summary", "post_assets", "traceability", "semantic_review",
                         "original_review", "before", "after"}:
                continue
            text += f"\n## {field.replace('_', ' ').title()}\n\n```yaml\n{yaml.safe_dump(value, sort_keys=False, allow_unicode=True)}```\n"
        judgments = data["semantic_review"]["judgments"]
        counts = {status: sum(len(item["tasks"]) for item in judgments if item["status"] == status)
                  for status in ("passed", "issues", "unverified", "not_applicable")}
        text += f"\n## AI semantic review\n\n```yaml\n{yaml.safe_dump(counts, sort_keys=False)}```\n\n"
        text += f"Every judgment's reasoning, confidence, source quotations and limitations are in [{structured}]({structured}).\n"
        trace = data.get("traceability", [])
        counts = {status: sum(item["coverage"] == status for item in trace)
                  for status in ("measured", "static", "gap", "unverified")}
        text += f"\n## Coverpoint traceability\n\n```yaml\n{yaml.safe_dump(counts, sort_keys=False)}```\n\n"
        text += f"Every point's obligation, testcases and evidence are in [{structured}]({structured}).\n"
        if not data.get("changes", data.get("changed_paths", [])):
            text += "\nNo source changes are included. Approval of an empty path list authorizes no source edits.\n"
        safe_path(self.output, name).write_text(text, encoding="utf-8")

    def _final(self, state: dict[str, Any], review: dict[str, Any],
               evidence: dict[str, Any], changed: list[str]) -> dict[str, Any]:
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
            if item.get("status") not in {"fixed", "deferred", "not_fixed"} or not is_text_list(item.get("evidence")) or not is_text(item.get("reason")):
                raise ValueError("Final findings need fixed/deferred/not_fixed, a nonempty evidence string list, and textual reason")
            if item["status"] == "fixed":
                proposals = [change for change in review["changes"] if item["id"] in change["findings"]]
                if not any(set(change["paths"]) & set(changed) for change in proposals):
                    raise ValueError(f"Finding {item['id']} claims a fix without an approved source change")
                required = {job for change in proposals for job in change["validation_jobs"]}
                if any(job["status"] != "passed" for job in evidence["jobs"] if job["id"] in required):
                    raise ValueError(f"Finding {item['id']} cannot be fixed without passing its validation jobs")
        self._traceability(final.get("traceability"), evidence)
        self._semantic_review(final, evidence, review=review, changed=changed)
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
        final.update(authorization=state["approved_digest"], changed_paths=changed,
                     asset_checks_passed=evidence["static_passed"],
                     original_review=review, before=before_evidence, after=evidence,
                     patch="changes.patch", input_checkout_modified=False)
        self._markdown("final.md", "ACT4 Extension Review and Repair Report", final,
                       [("before", before_evidence), ("after", evidence)])
        return final

    def do_check(self, is_complete: bool = False, run_commands: bool = False,
                 **kwargs: Any) -> tuple[bool, dict[str, Any]]:
        """Validate the review phase, real evidence, human authorization, and repair scope."""
        try:
            if type(run_commands) is not bool:
                raise ValueError("run_commands must be a boolean")
            workspace = Path(self.workspace).resolve()
            self.source = safe_path(workspace, self.act4_root)
            self.output = safe_path(workspace, self.review_dir)
            if self.output.resolve().is_relative_to(self.source.resolve()) or self.source.resolve().is_relative_to(self.output.resolve()):
                raise ValueError("Review artifacts and input checkout must be separate")
            self.output.mkdir(parents=True, exist_ok=True)
            state = self._state()
            scope = self._scope()
            self._baseline(state, scope)
            candidate = self.output / "candidate"
            if candidate.is_symlink():
                raise ValueError("Repair candidate must not be a symlink")
            if self.phase in {"inventory", "audit", "authorize"} and candidate.exists() and state.get("candidate_prepared") is not True:
                raise ValueError("A repair candidate must not exist before authorization; use a fresh review output")
            if self.phase == "inventory":
                return True, {"baseline": "baseline.json", "scope": "scope.yaml"}
            before = self._evidence(state, scope, self.output / "baseline", "before",
                                    run_commands and self.phase == "audit")
            review = self._review(scope, before)
            approval = self._authorization(state, scope, review)
            self._markdown("review.md", "ACT4 Extension Review", review, [("before", before)])
            if self.phase == "audit":
                return True, {"report": "review.md", "digest": approval, "asset_health": before["static_passed"]}
            if self.phase == "authorize":
                if self.stage is None or not self.stage.is_hmcheck_needed():
                    raise ValueError("Human authorization cannot be disabled for this stage")
                passed, message = self.stage.get_hmcheck_state()
                if passed is False or (passed is True and message.strip() != approval):
                    raise ValueError(f"Request human approval of the current report: hmcheck_pass {approval}")
                if is_complete and passed is True:
                    state["pending_digest"] = approval
                return True, {"digest": approval, "next_action": f"Wait for the operator: hmcheck_pass {approval}"}
            self._require_approval(state, approval)
            if not candidate.exists():
                if self.phase != "repair":
                    raise ValueError("Candidate missing; return to the authorized repair stage")
                copy_sources(self.output / "baseline", candidate, state["baseline"]["files"])
                state["candidate_prepared"] = True
            elif state.get("candidate_prepared") is not True:
                raise ValueError("Candidate was not prepared by an authorized Check; use a fresh review output")
            changed = self._changes(state, review)
            if self.phase == "repair" and not run_commands and not is_complete:
                return True, {"candidate": str(candidate), "changed_paths": changed,
                              "next_action": "Repair approved paths, then Check(stage_args={\"run_commands\": true})"}
            for kind in ASSET_KINDS:
                for name in set(scope["assets"][kind]) - set(review["post_assets"][kind]):
                    if safe_path(candidate, name).exists():
                        raise ValueError(f"post_assets must not hide an existing reviewed asset: {name}")
            post_scope = {**scope, "assets": review["post_assets"]}
            after = self._evidence(state, post_scope, candidate, "after", run_commands and self.phase == "repair")
            if self.phase == "final":
                self._final(state, review, after, changed)
            self._baseline(state, scope)
            return True, {"report": "final.md" if self.phase == "final" else "evidence-after.json",
                          "changed_paths": changed, "ci": [{key: value for key, value in job.items()
                              if key in {"id", "status", "purpose", "log", "reason", "elf_count", "executed_tests"}}
                              for job in after["jobs"]]}
        except (ValueError, TypeError, KeyError, OSError, re.error, yaml.YAMLError, subprocess.SubprocessError) as exc:
            return False, {"error_code": "act4_review_contract", "error": str(exc),
                           "artifact": self.review_dir, "phase": self.phase,
                           "next_action": "Correct the named review artifact or request operator action; follow Guide_Doc/ACT4_Extension_Review_Guide.md"}
