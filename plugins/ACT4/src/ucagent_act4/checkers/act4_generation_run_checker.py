"""Gate source policy, selective local imports, regeneration isolation and final provenance."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time

import yaml

from .act4_environment_checker import ACT4EnvironmentChecker
from .act4_asset_checklist_checker import source_state
from ..generation_run import accepted_design, clone_source_snapshot, import_receipt, source_inventory
from ..finding_acceptance import finding_outcome
from ..resources import clone_local, git_text, resolve_source
from ..run_config import ASSET_TYPES, run_settings
from ..xiangshan_bundle import safe_path, sha256, write_json


class ACT4GenerationRunChecker(ACT4EnvironmentChecker):
    """Prepare private mixed-source inputs after independent design and check their final disposition."""

    def __init__(self, suite: str, output: str, phase: str = "inputs", cfg=None):
        """Store scope and phase without reading or writing the workspace."""
        super().__init__(f"{output}/intermediate/{suite}/asset-inputs", cfg=cfg)
        if phase not in {"inputs", "final"}:
            raise ValueError("phase must be inputs or final")
        self.suite, self.output, self.phase = suite, output, phase
        self.cfg = cfg

    def do_check(self, is_complete=False, action="", timeout=1800, run_commands=False, **kwargs):
        """Discover sources, import a reviewed selection once, or verify the canonical final source table."""
        try:
            actions = {"", "discover", "import"} if self.phase == "inputs" else {"", "validate"}
            if kwargs or action not in actions or (is_complete and action):
                raise ValueError("Use Check with action=discover/import in the input stage; Complete takes no action")
            if type(run_commands) is not bool or (run_commands and self.phase != "final"):
                raise ValueError("run_commands is only shared with the final stage's native validation gates")
            if type(timeout) is not int or not 1 <= timeout <= 14400:
                raise ValueError("timeout must be in 1..14400 seconds")
            settings = run_settings(self.cfg)
            if not settings or (settings["suite"], settings["output"]) != (self.suite, self.output):
                raise ValueError("Start this generation workflow with act4-run and its run YAML")
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.environment_dir)
            directory.mkdir(parents=True, exist_ok=True)
            design = accepted_design(workspace, self.output, self.suite, self.smanager_get_value)
            resources = directory.parent / "resources"
            upstream = resolve_source(workspace, settings["upstream"]["act4_root"], resources, self.smanager_get_value)
            if action == "discover":
                candidates = {"upstream": {"root": str(upstream), "files": source_inventory(upstream)}}
                for category, policy in settings["assets"].items():
                    if policy["source"] == "local":
                        root = Path(policy["path"])
                        candidates[category] = {"root": str(root), "files": source_inventory(root)}
                write_json(directory / "inventory.json", candidates)
                return True, {"inventory": str(directory / "inventory.json"), "policies": settings["assets"],
                              "next_action": "Create selection.yaml using exact native paths and source candidates. Never read excluded regenerated assets; ambiguous or missing local sources need an explicit resolution."}
            key = f"act4_generation_run:{directory}"
            if action == "import":
                if self.smanager_get_value(key, None):
                    raise ValueError("Inputs are already frozen; check without action or use a new workspace")
                selection_path = directory / "selection.yaml"
                selection_bytes = selection_path.read_bytes()
                selection_digest = hashlib.sha256(selection_bytes).hexdigest()
                selection = yaml.safe_load(selection_bytes.decode("utf-8"))
                if (not isinstance(selection, dict) or set(selection) != {"schema_version", "suite", "repositories", "assets"}
                        or selection["schema_version"] != 1 or selection["suite"] != self.suite
                        or not isinstance(selection["repositories"], dict) or "act4" in selection["repositories"]
                        or not isinstance(selection["assets"], dict) or set(selection["assets"]) != set(ASSET_TYPES)):
                    raise ValueError("selection.yaml requires schema_version=1, suite, extra repositories and all nine assets")
                roots = {"act4": upstream}
                if git_text(upstream, "status", "--porcelain", "--untracked-files=all"):
                    raise ValueError("Upstream input must be clean; select local category sources explicitly to import uncommitted assets")
                for name, relative in selection["repositories"].items():
                    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                        raise ValueError("Dependency repository IDs must match [a-z][a-z0-9_-]*")
                    source = safe_path(workspace, relative)
                    if not source.is_relative_to(directory.parent / "dependency-sources"):
                        raise ValueError("Prepare additional pinned Git sources under intermediate/<Suite>/dependency-sources/")
                    if git_text(source, "status", "--porcelain"):
                        raise ValueError(f"Dependency source must be clean before import: {name}")
                    roots[name] = source
                owners, imports, removals, local_inputs, patches = {}, {}, {}, {}, {}
                requirements = {item["id"] for item in design["plan"]["requirements"]}
                for category, entry in selection["assets"].items():
                    if (not isinstance(entry, dict) or set(entry) != {"files", "reason", "requirements"}
                            or not isinstance(entry["files"], list) or not isinstance(entry["reason"], str) or not entry["reason"].strip()
                            or not isinstance(entry["requirements"], list) or (entry["files"] and requirements and not entry["requirements"])
                            or not set(entry["requirements"]) <= requirements):
                        raise ValueError(f"{category}: declare files, a source-based reason and accepted ISA requirement IDs")
                    policy = settings["assets"][category]
                    if not entry["files"] and policy["on_missing"] == "error":
                        raise ValueError(f"{category}: requested source is missing; no silent upstream fallback is allowed")
                    for item in entry["files"]:
                        if (not isinstance(item, dict) or not {"repository", "path", "local_path"} <= item.keys()
                                or set(item) - {"repository", "path", "local_path", "patch_base"} or item["repository"] not in roots):
                            raise ValueError(f"{category}: each file needs repository, native path and local_path (or null)")
                        name, native = item["repository"], item["path"]
                        safe_path(roots[name], native)
                        identity = f"{name}:{native}"
                        if identity in owners:
                            previous_category = owners[identity][0]
                            previous_policy = settings["assets"][previous_category]
                            previous = next(record for record in selection["assets"][previous_category]["files"]
                                            if (record["repository"], record["path"]) == (name, native))
                            if (category in owners[identity] or item != previous
                                    or any(policy[field] != previous_policy[field] for field in ("source", "path"))
                                    or (policy["mode"] == "regenerate") != (previous_policy["mode"] == "regenerate")):
                                raise ValueError(f"Conflicting category ownership for {identity}; shared sources need the same origin and compatible policies")
                            owners[identity].append(category)
                            continue
                        owners[identity] = [category]
                        if "patch_base" in item and (policy["source"] != "local" or not str(item["local_path"]).endswith(".patch")):
                            raise ValueError("patch_base applies only to an explicitly selected local .patch")
                        if policy["mode"] == "regenerate":
                            if item["local_path"] is not None:
                                raise ValueError("Regeneration cannot import an old local asset")
                            if not safe_path(roots[name], native).is_file():
                                raise ValueError(f"Regeneration selection names an absent old source: {identity}; use files=[] when none exists")
                            removals.setdefault(name, []).append(native)
                        elif policy["source"] == "local":
                            source = safe_path(Path(policy["path"]), item["local_path"])
                            if source.suffix in {".elf", ".bin"} or not source.is_file():
                                raise ValueError("Select editable source files or an exact-base patch; ELF/binary-only inputs cannot be incrementally edited")
                            if source.suffix == ".patch":
                                base = item.get("patch_base")
                                if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base) or base != git_text(roots[name], "rev-parse", "HEAD"):
                                    raise ValueError("Local patches require patch_base equal to the exact pinned 40-hex repository HEAD; select that upstream revision in run YAML")
                                patches.setdefault(name, []).append((native, source))
                            else:
                                imports.setdefault(name, []).append((native, source))
                            local_inputs[str(source)] = {"sha256": sha256(source), "mode": stat.S_IMODE(source.stat().st_mode)}
                        elif item["local_path"] is not None or not safe_path(roots[name], native).is_file():
                            raise ValueError(f"{category}: upstream source not found; declare files=[] and the actual scope if on_missing is generate or report")
                deadline = time.monotonic() + timeout
                records = {}
                with tempfile.TemporaryDirectory(prefix=".asset-import-", dir=workspace) as temporary:
                    staging = Path(temporary)
                    for name, root in roots.items():
                        target_relative = "riscv-arch-test" if name == "act4" else f"capabilities/{name}"
                        baseline_relative = "act4-inputs" if name == "act4" else f"act4-inputs-dependencies/{name}"
                        for relative in (target_relative, baseline_relative):
                            if safe_path(workspace, relative).exists():
                                raise ValueError(f"Input destination already exists: {relative}; start a dedicated run workspace")
                        baseline = staging / f"baseline-{name}"
                        clone_local(root, baseline, directory, deadline, self._track)
                        reconstructed = {}
                        for native, patch in patches.get(name, []):
                            if patch not in reconstructed:
                                checkout = staging / f"patch-{name}-{len(reconstructed)}"
                                clone_local(root, checkout, directory, deadline, self._track)
                                for extra in (["--check"], []):
                                    result = subprocess.run(["git", "-C", str(checkout), "apply", *extra, str(patch)],
                                                            capture_output=True, text=True, timeout=max(1, deadline - time.monotonic()))
                                    if result.returncode:
                                        raise ValueError(f"Cannot reconstruct {patch.name} at its declared base: {result.stderr[:1200]}")
                                reconstructed[patch] = checkout
                            restored = safe_path(reconstructed[patch], native)
                            original = safe_path(root, native)
                            if (not restored.exists() and not original.is_file()) or (restored.is_file() and original.is_file() and sha256(restored) == sha256(original) and restored.stat().st_mode == original.stat().st_mode):
                                raise ValueError(f"Selected local patch does not change {name}:{native}; select its actual editable source instead")
                            destination = safe_path(baseline, native)
                            if restored.is_file():
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(restored, destination)
                            else:
                                destination.unlink(missing_ok=True)
                        for native, source in imports.get(name, []):
                            destination = safe_path(baseline, native)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, destination)
                        target = staging / f"working-{name}"
                        clone_source_snapshot(baseline, target, directory, deadline, self._track)
                        for native in removals.get(name, []):
                            safe_path(target, native).unlink(missing_ok=True)
                        records[name] = {"baseline": baseline_relative, "working": target_relative, "upstream_head": git_text(root, "rev-parse", "HEAD"),
                                         "baseline_state": source_state(baseline), "working_initial": source_state(target), "removed": removals.get(name, [])}
                    if sha256(selection_path) != selection_digest:
                        raise ValueError("selection.yaml changed during import; no source selection was published")
                    for name, record in records.items():
                        for prefix, key_name in (("baseline", "baseline"), ("working", "working")):
                            destination = safe_path(workspace, record[key_name])
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            (staging / f"{prefix}-{name}").rename(destination)
                if any(sha256(Path(path)) != facts["sha256"] or stat.S_IMODE(Path(path).stat().st_mode) != facts["mode"] for path, facts in local_inputs.items()):
                    raise ValueError("Local assets changed during import; start a new run with stable inputs")
                data = {"schema_version": 1, "settings": settings, "selection": selection, "local_inputs": local_inputs,
                        "repositories": records, "owners": owners, "selection_sha256": selection_digest}
                write_json(directory / "receipt.json", data)
                self.smanager_set_value(key, sha256(directory / "receipt.json"))
            data = import_receipt(workspace, settings, self.smanager_get_value)
            if self.phase == "final":
                checklist = yaml.safe_load((directory.parent / "asset_checklist.yaml").read_text(encoding="utf-8"))
                rows = ["", "## Asset input policies", "", "| Asset | Policy | Source | Result |", "| --- | --- | --- | --- |"]
                for category, policy in settings["assets"].items():
                    selected = [item for item in checklist["items"] if item["category"] == category]
                    if policy["mode"] == "regenerate" and any(item["action"] == "reuse" for item in selected):
                        raise ValueError(f"{category}: regeneration cannot be reported as reuse")
                    source = (policy["path"] or policy["source"] or "Independent ISA design").replace("|", "\\|")
                    rows.append(f"| {category} | {policy['mode']} | {source} | {', '.join(sorted({item['action'] for item in selected}))} |")
                baseline = data["repositories"]["act4"]
                rows.extend(["", f"Patch base: `{baseline['baseline']}` (upstream `{baseline['upstream_head']}` plus the selected local inputs).",
                             f"Reconstruct that input using [source selection](intermediate/{self.suite}/asset-inputs/selection.yaml) and "
                             f"[provenance](intermediate/{self.suite}/asset-inputs/receipt.json) before applying `changes.patch`; it contains only this run's changes."])
                review_path = safe_path(directory.parent, "review/final-accepted.json")
                state = self.smanager_get_value(f"act4_review:{self.output}/intermediate/{self.suite}/review:{self.suite}", {})
                content = review_path.read_bytes()
                if state.get("final_snapshot") != hashlib.sha256(content).hexdigest():
                    raise ValueError("Complete post-generation review before final delivery")
                review = json.loads(content)
                outcome = finding_outcome(review["findings"])
                rows.extend(["", f"Finding scope: {outcome['finding_scope']}; fixed: {outcome['fixed']}; "
                             f"local pending: {len(outcome['local_pending'])}; external pending: {len(outcome['external_pending'])}."])
                table = "\n".join(rows) + "\n"
                (directory / "policies.md").write_text(table, encoding="utf-8")
                report = safe_path(workspace, self.output + "/final.md").read_text(encoding="utf-8")
                visible = re.sub(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", report)
                visible = re.sub(r"(?s)<!--.*?-->", "", visible)
                if visible.count(table.strip()) != 1 or report.count(table.strip()) != 1 or len(re.findall(r"(?m)^## Asset input policies$", visible)) != 1:
                    raise ValueError(f"Include the exact Asset input policies table from {self.environment_dir}/policies.md once in final.md")
                from .act4_review_checker import tree_state
                from ..generation_run import git_source_files

                working = safe_path(workspace, data["repositories"]["act4"]["working"])
                if tree_state(working, git_source_files(working)) != state.get("generation_snapshot"):
                    raise ValueError("Sources changed after post-generation review; collect fresh after evidence")
                if review["summary"] not in report:
                    raise ValueError("Include the accepted review summary, including unresolved findings, in final.md")
                review_report = directory.parent / "review-results/final.md"
                if "intermediate/" + self.suite + "/review-results/final.md" not in visible or not review_report.is_file():
                    raise ValueError("Link the detailed post-generation review from final.md so every unresolved finding and next action can be inspected")
                if sha256(review_report) != review["report_sha256"]:
                    raise ValueError("Accepted post-generation review report changed; regenerate it through post-generation review")
                patch = directory.parent / "review-results/changes.patch"
                if sha256(patch) != review["patch_sha256"]:
                    raise ValueError("Accepted review patch changed; regenerate it through post-generation review")
                shutil.copy2(patch, safe_path(workspace, self.output + "/changes.patch"))
            return True, {"sources": {name: value["working"] for name, value in data["repositories"].items()},
                          "policies": settings["assets"], "next_action": "Preserve imported baselines. Improve selected sources or generate missing assets, then validate and publish the source-policy table."}
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as error:
            return False, {"error_code": "act4_generation_sources", "error": str(error), "artifact": self.environment_dir,
                           "next_action": "Read Guide_Doc/ACT4_Run_Guide.md, resolve the named source or policy conflict and retry without modifying provenance evidence."}
