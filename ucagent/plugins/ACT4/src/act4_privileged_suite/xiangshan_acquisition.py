"""Discover upstream ACT assets and run bounded, isolated gap-generation workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

import yaml
import ucagent

from . import xiangshan_bundle as bundle
from .xiangshan_trace import citation, records_by_id, require_text


REPOSITORIES = {
    "upstream": ("https://github.com/riscv/riscv-arch-test.git", "act4"),
    "xiangshan": ("https://github.com/OpenXiangShan/XiangShan.git", "kunminghu-v3"),
    "manual": ("https://github.com/riscv/riscv-isa-manual.git", None),
}
ASSET_DIRS = ("tests", "testplans", "coverpoints", "generators")


def upstream_files(root: Path, searchable: bool = True) -> dict:
    """Inventory regular ACT assets, optionally restricting discovery to searchable text files."""
    files = {}
    for directory in ASSET_DIRS:
        for current, children, names in os.walk(root / directory, followlinks=False):
            children[:] = [name for name in children if name not in bundle.SOURCE_IGNORE_DIRS]
            for name in children:
                bundle.safe_path(root, str((Path(current) / name).relative_to(root)))
            for name in names:
                if name == ".git" or name.endswith(".pyc"):
                    continue
                if searchable and Path(name).suffix not in {".S", ".h", ".sv", ".svh", ".yaml", ".yml", ".csv", ".py", ".md", ".adoc"}:
                    continue
                relative = str((Path(current) / name).relative_to(root))
                files[relative] = bundle.identity(bundle.safe_path(root, relative))
                if len(files) > 50000:
                    raise ValueError("ACT discovery exceeds 50000 files; exclude generated build/cache trees from the input")
    return files


class XiangShanAcquisition:
    """Bind semantic module selection to real upstream searches and child-workflow receipts."""

    def __init__(self, output: Path, roots: dict, state: dict, environment: dict, process_started):
        """Store the current check's paths and receipts without doing discovery or launching tools."""
        self.output, self.roots, self.state = output, roots, state
        self.environment, self.process_started = environment, process_started

    def fetch(self, timeout: int) -> None:
        """Fetch missing public repositories only into owned output; never update user checkouts."""
        deadline = time.monotonic() + timeout
        for origin in ("upstream", "xiangshan", "manual"):
            destination = self.roots[origin]
            if destination.is_dir():
                continue
            if not destination.is_relative_to(self.output / "repositories"):
                raise ValueError(f"Missing user-specified {origin} checkout: {destination}")
            url, branch = REPOSITORIES[origin]
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f"{destination.name}-{uuid.uuid4().hex}")
            argv = ["git", "clone"] + (["--branch", branch] if branch else [])
            if origin == "upstream":
                argv.append("--recurse-submodules")
            remaining = int(deadline - time.monotonic())
            if remaining < 1:
                raise ValueError("Repository preparation budget exhausted; completed checkouts are retained for retry")
            result = bundle.execute([*argv, url, str(temporary)], self.output,
                                    self.output / f"fetch-{origin}.log", remaining, self.process_started, self.environment)
            if result["status"] != "passed":
                raise ValueError(f"Cannot fetch {origin}; inspect fetch-{origin}.log or supply a complete pinned local checkout")
            temporary.rename(destination)

    def discover(self, queries: list[str]) -> dict:
        """Persist complete candidate lists and source fingerprints for explicit search terms."""
        if not isinstance(queries, list) or not 1 <= len(queries) <= 30 or any(not isinstance(term, str) or not term.strip() for term in queries):
            raise ValueError("discover requires 1..30 nonempty queries based on the requested XiangShan function and ISA")
        root = self.roots["upstream"]
        if not root.is_dir():
            raise ValueError("Fetch or provide riscv-arch-test before searching for reusable assets")
        files, matches = upstream_files(root), {query: [] for query in queries}
        for relative in files:
            text = bundle.safe_path(root, relative).read_text(encoding="utf-8").casefold()
            for query in queries:
                if query.casefold() in relative.casefold() or query.casefold() in text:
                    matches[query].append(relative)
        if not files:
            raise ValueError("No ACT assets found; provide a matching complete riscv-arch-test checkout")
        result = {"schema_version": 1, "queries": matches, "files": files}
        path = self.output / "discovery.json"
        bundle.write_json(path, result)
        self.state["discovery"] = bundle.sha256(path)
        return {"catalog": "discovery.json", "counts": {query: len(paths) for query, paths in matches.items()},
                "next_action": "Read the candidate files, then write scope.yaml mapping XiangShan functions to reusable ACT suites/parts and precise gaps."}

    def validate(self, module: str) -> dict:
        """Validate scope evidence and upstream-first acquisition decisions without inventing ISA matches."""
        path = self.output / "discovery.json"
        if not path.is_file() or self.state.get("discovery") != bundle.sha256(path):
            raise ValueError("Call Check(action=discover, queries=[ISA/function terms]) before selecting or generating assets")
        discovery = json.loads(path.read_text(encoding="utf-8"))
        if upstream_files(self.roots["upstream"]) != discovery["files"]:
            raise ValueError("Upstream discovery inputs changed; repeat discover before freezing scope, or start a fresh handoff after scope was frozen")
        scope = yaml.safe_load((self.output / "scope.yaml").read_text(encoding="utf-8"))
        if not isinstance(scope, dict) or scope.get("schema_version") != 1 or scope.get("module") != module:
            raise ValueError("scope.yaml requires schema_version: 1 and the requested XiangShan module")
        require_text(scope, "request")
        features = records_by_id(scope.get("features"), "requested functions")
        jobs = scope.get("generation_jobs")
        if not isinstance(jobs, list):
            raise ValueError("scope.yaml requires generation_jobs, using [] when upstream/local assets suffice")
        indexed_jobs = records_by_id(jobs, "generation jobs") if jobs else {}
        evidence_files = {}
        for feature in features.values():
            require_text(feature, "description", "assessment")
            evidence = citation(self.roots["xiangshan"], feature.get("xiangshan"))
            evidence_files[f"xiangshan:{evidence['path']}"] = evidence["sha256"]
            queries = feature.get("queries")
            if not isinstance(queries, list) or not queries or any(query not in discovery["queries"] for query in queries):
                raise ValueError(f"Feature {feature['id']} must reference actual discovery queries")
            suites = feature.get("act4_suites")
            if not isinstance(suites, list) or any(not isinstance(suite, str) or not re.fullmatch(r"[A-Za-z][\w]*", suite) for suite in suites):
                raise ValueError("act4_suites must list exact discovered ACT identifiers, or [] for unsupported functions")
            inspected = feature.get("inspected")
            if not isinstance(inspected, list):
                raise ValueError("Every function needs inspected upstream evidence, even when only partial assets exist")
            candidates = {name for query in queries for name in discovery["queries"][query]}
            if candidates and not inspected:
                raise ValueError(f"Inspect upstream candidates before declaring a gap: {feature['id']}")
            for reference in inspected:
                evidence = citation(self.roots["upstream"], reference)
                if evidence["path"] not in candidates:
                    raise ValueError(f"Inspected asset was not in the recorded search: {evidence['path']}")
            if feature.get("upstream_status") not in {"complete", "partial", "absent"}:
                raise ValueError("upstream_status must be complete, partial or absent")
            if feature.get("resolution") not in {"reuse", "local", "generate", "unavailable"}:
                raise ValueError("resolution must be reuse, local, generate or unavailable")
            if feature["upstream_status"] == "complete" and feature["resolution"] != "reuse":
                raise ValueError(f"Reuse sufficient upstream assets instead of regenerating {feature['id']}")
            if feature["upstream_status"] != "complete":
                require_text(feature, "gap")
            if feature["resolution"] in {"generate", "unavailable"}:
                require_text(feature, "next_action")
            if feature["resolution"] == "generate" and feature.get("generation_job") not in indexed_jobs:
                raise ValueError(f"Declare a generation job for {feature['id']}")
        for identity, job in indexed_jobs.items():
            if not re.fullmatch(r"[A-Za-z][\w-]*", identity) or not re.fullmatch(r"[A-Za-z][\w]*", job.get("suite", "")):
                raise ValueError("Generation IDs and suites must be safe identifiers")
            require_text(job, "rationale", "eligibility")
            linked = [feature for feature in features.values() if feature.get("generation_job") == identity and feature["resolution"] == "generate"]
            if not linked:
                raise ValueError(f"Generation job {identity} is not linked to a confirmed upstream gap")
            generator = self.roots["upstream"] / f"generators/testgen/src/testgen/priv/extensions/{job['suite']}.py"
            if generator.exists():
                raise ValueError(f"Generation workflow only creates new privileged suites; do not overwrite existing {job['suite']}. Reuse it or document the remaining unsupported gap")
        fingerprint = {"scope": bundle.sha256(self.output / "scope.yaml"), "discovery": self.state["discovery"], "evidence": evidence_files}
        if self.state.get("scope") and self.state["scope"] != fingerprint:
            raise ValueError("Frozen scope changed; start a new handoff to preserve acquisition and generation evidence")
        self.state["scope"] = fingerprint
        return scope

    def synthesize(self, scope: dict, identifier: str, backend: str, timeout: int) -> None:
        """Run the existing generation workflow in a private clone and bind actual completion evidence."""
        jobs = records_by_id(scope["generation_jobs"], "generation jobs")
        if identifier not in jobs:
            raise ValueError("synthesize requires generation_id from scope.yaml")
        if not backend or backend == "blank" or not re.fullmatch(r"[A-Za-z][\w-]*", backend):
            raise ValueError("Select a configured model backend to run gap generation; blank cannot generate assets")
        job = jobs[identifier]
        deadline = time.monotonic() + timeout
        receipts = self.state.setdefault("synthesis", {})
        if identifier in receipts:
            raise ValueError("Generation already completed; reuse its recorded outputs instead of rerunning")
        manual = self.roots["manual"]
        if not manual.is_dir():
            raise ValueError("Provide ACT4_MANUAL_ROOT with ISA sources and normative_rule_defs before gap generation")
        attempt = self.output / "generation" / identifier / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        checkout = attempt / "riscv-arch-test"
        cloned = bundle.execute(["git", "clone", "--no-hardlinks", "--recurse-submodules", str(self.roots["upstream"]), str(checkout)],
                                attempt, attempt / "clone.log", timeout, self.process_started, self.environment)
        if cloned["status"] != "passed":
            raise ValueError(f"Cannot prepare isolated generation clone; inspect {attempt / 'clone.log'}")
        for relative, expected in json.loads((self.output / "discovery.json").read_text(encoding="utf-8"))["files"].items():
            path = bundle.safe_path(checkout, relative)
            if not path.is_file() or bundle.identity(path) != expected:
                raise ValueError(f"Generation clone differs from the inspected upstream source at {relative}; use a clean pinned input instead of discarding local changes")
        request = {"module": scope["module"], "request": scope["request"], "job": job,
                   "features": [feature for feature in scope["features"] if feature.get("generation_job") == identifier]}
        bundle.write_json(attempt / "handoff-request.json", request)
        argv = [sys.executable, "-m", "ucagent.cli", str(attempt), job["suite"],
                "--plugin", "act4-privileged-suite", "--plugin-workflow", "act4-privileged-suite:privileged-suite-generation",
                "--output", "act4_assets", "--backend", backend, "--loop", "--exit-on-completion",
                "--loop-msg", "Read handoff-request.json. Generate only the declared missing privileged suite using the normal workflow and all its checks. Do not modify unrelated suites."]
        import_roots = [str(Path(ucagent.__file__).resolve().parent.parent), str(Path(__file__).resolve().parent.parent)]
        import_roots += [path for path in self.environment.get("PYTHONPATH", "").split(os.pathsep) if path and path not in import_roots]
        environment = {**self.environment, "ACT4_MANUAL_ROOT": str(manual), "PYTHONPATH": os.pathsep.join(import_roots)}
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            raise ValueError("Gap generation budget exhausted while preparing its isolated clone")
        result = bundle.execute(argv, attempt, attempt / "workflow.log", remaining, self.process_started, environment)
        bundle.write_json(attempt / "execution.json", result)
        info_path = attempt / ".ucagent/ucagent_info.json"
        if result["status"] != "passed" or not info_path.is_file():
            raise ValueError(f"Gap generation did not finish; preserve {attempt / 'workflow.log'} and report this gap, not a successful source")
        info = json.loads(info_path.read_text(encoding="utf-8"))
        workflow = yaml.safe_load((Path(__file__).parent / "workflows/privileged-suite-generation.yaml").read_text(encoding="utf-8"))
        stages = [stage for _, stage in sorted(info.get("stages_info", {}).items(), key=lambda item: int(item[0]))]
        if (info.get("all_completed") is not True or info.get("DUT") != job["suite"]
                or info.get("plugin_workflow") != "act4-privileged-suite:privileged-suite-generation"
                or len(stages) != len(workflow["stage"])
                or any(not stage.get("task", {}).get("title", "").startswith(f"{index + 1}-{expected['name']}-")
                       for index, (stage, expected) in enumerate(zip(stages, workflow["stage"])))
                or any(stage.get("is_completed") is not True or stage.get("check_pass") is not True or stage.get("is_skipped") for stage in stages)):
            raise ValueError("Generation process exited without completing all required stages; do not import its unfinished assets")
        files = upstream_files(checkout, searchable=False)
        required = [f"generators/testgen/src/testgen/priv/extensions/{job['suite']}.py", f"coverpoints/priv/{job['suite']}_coverage.svh",
                    f"coverpoints/norm/{job['suite']}.yaml"]
        if any(name not in files for name in required) or not any(name.startswith("tests/") and name.endswith(".S") and job["suite"] in name for name in files):
            raise ValueError("Generation completion lacks the actual new suite generator, coverage, norm mapping or assembly; do not import incomplete outputs")
        report_root = attempt / "act4_assets" / job["suite"] / "reports"
        reports = {}
        for name in (f"{job['suite']}_final_summary_report.md", f"{job['suite']}_validation_state.yaml", f"{job['suite']}_file_manifest.yaml"):
            path = bundle.safe_path(report_root, name)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f"Generation is missing its authoritative report: {name}")
            reports[str(path.relative_to(self.output))] = bundle.identity(path)
        receipts[identifier] = {"root": str(checkout.relative_to(self.output)), "files": files,
                                "reports": reports,
                                "completion": str(info_path.relative_to(self.output)), "completion_sha256": bundle.sha256(info_path),
                                "execution": str((attempt / "execution.json").relative_to(self.output)),
                                "execution_sha256": bundle.sha256(attempt / "execution.json"),
                                "log": str((attempt / "workflow.log").relative_to(self.output)), "log_sha256": bundle.sha256(attempt / "workflow.log")}

    def import_roots(self, scope: dict) -> dict:
        """Expose only finished generated sources alongside existing immutable upstream/local inputs."""
        roots = {key: self.roots[key] for key in ("upstream", "local", "manual")}
        for job in scope["generation_jobs"]:
            receipt = self.state.get("synthesis", {}).get(job["id"])
            if not receipt:
                raise ValueError(f"Run Check(action=synthesize, generation_id={job['id']}) before importing the missing suite")
            for field in ("completion", "execution", "log"):
                if bundle.sha256(bundle.safe_path(self.output, receipt[field])) != receipt[field + "_sha256"]:
                    raise ValueError(f"Generation evidence changed for {job['id']}")
            root = bundle.safe_path(self.output, receipt["root"])
            if upstream_files(root, searchable=False) != receipt["files"]:
                raise ValueError(f"Generated asset inventory changed for {job['id']}")
            bundle.verify_files(self.output, receipt["reports"])
            roots[f"generated:{job['id']}"] = root
        return roots
