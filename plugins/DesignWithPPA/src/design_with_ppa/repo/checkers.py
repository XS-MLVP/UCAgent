"""Stage gates for repository snapshots, unit contracts, measured candidates, and delivery."""

from __future__ import annotations

import ast
import sys
import traceback

from ucagent.checkers.base import Checker, UnityChipBatchTask
from ucagent.util.log import error

from ..contracts import atomic_json, diagnostic, no_improvement_patience, optimization_limits
from .common import RepoPaths, inside, run_command, tree_identity
from .delivery import best_record, deliver
from .models import TaskContract, read_model
from .snapshot import snapshot_repository
from .validation import (child_environment, current_identity, module_checkpoints,
                         reference_check, seal, unseal, validate_unit, validated_records)




def _test_sources_tree(tests_dir):
    """Hash only authored test sources; pytest leaves caches and coverage data behind."""

    return {name: row for name, row in tree_identity(tests_dir).items()
            if name.endswith(".py") and "__pycache__" not in name}


class RepoModuleChecker(Checker):
    """Gate one isolated module workflow phase using actual source and execution evidence."""

    def __init__(self, phase: str, cfg=None, **kwargs):
        """Store phase only; resolve workspace and config when the stage actually runs."""

        super().__init__()
        self.cfg = cfg
        if phase not in {"snapshot", "contract", "reference", "baseline",
                         "test_cases", "candidates", "delivery"}:
            raise ValueError("Invalid repository-module phase")
        self.phase = phase
        self.batch_size = 1
        self.batch = UnityChipBatchTask("repo_variants", self) if phase == "candidates" else None

    def do_check(self, is_complete=False, **kwargs):
        """Validate the current phase; never count authored claims as measured completion."""

        try:
            paths = RepoPaths(self.workspace, self.cfg)
            source = snapshot_repository(paths)
            if self.phase == "snapshot":
                return True, {"commit": source["commit"], "source_files": len(source["files"]),
                              "source_paths": source["selection"]["source_paths"],
                              "excluded_submodules": source["excluded_submodules"],
                              "local_changes_excluded": source["local_changes_excluded"],
                              "next_action": "Read source_snapshot and write repo/contract.yaml for the target unit and dependency closure."}
            if self.phase == "contract":
                contract = read_model(paths.edit, "contract.yaml", TaskContract)
                if paths.options["mode"] == "optimize":
                    missing = [p for p in contract.target_paths if p not in source["files"]]
                    if missing:
                        raise ValueError(f"Optimization target_paths do not exist in source_snapshot: {missing}")
                for name in contract.dependencies:
                    if name not in source["files"]:
                        raise ValueError(f"Declared source dependency is absent: {name}")
                checkpoints = module_checkpoints(paths)
                if set(contract.requirements) != set(checkpoints):
                    raise ValueError(
                        f"contract.yaml requirements must be exactly the FG/FC/CK leaf paths of "
                        f"{paths.output.relative_to(paths.workspace)}/repo/functions_and_checks.md: "
                        f"missing={sorted(set(checkpoints) - set(contract.requirements))}, "
                        f"unknown={sorted(set(contract.requirements) - set(checkpoints))}")
                return True, {"requirements": list(contract.requirements),
                              "checkpoints": len(checkpoints), "verification_scope": "unit_only"}
            if self.phase == "reference":
                result = reference_check(paths)
                coverage = result["coverage"]
                return True, {"reference_pass": True, "scenarios": list(result["expected"]),
                              "coverage": {"covered": coverage["covered"], "total": coverage["total"]},
                              "coverage_report": f"{paths.output.relative_to(paths.workspace)}/repo/coverage.json"}
            if self.phase == "baseline":
                result = validate_unit(paths, baseline=True)
                return True, {"baseline": result["variant_id"], "ppa_metrics": result["ppa_metrics"],
                              "dashboard": f"{paths.output.relative_to(paths.workspace)}/design_with_ppa_dashboard.html"}
            records = validated_records(paths)
            if not records:
                raise ValueError("No measured baseline; complete the baseline stage first")
            if self.phase == "test_cases":
                checkpoints = module_checkpoints(paths)
                tests_dir = inside(paths.edit, "tests")
                test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
                if not test_files:
                    raise ValueError("No test cases found; write pytest files under repo/tests using the managed env fixture")
                mapping = {}
                for path in test_files:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                    covers = None
                    for node in tree.body:
                        targets = getattr(node, "targets", [])
                        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COVERS" for t in targets):
                            covers = [item.value for item in node.value.elts
                                      if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                    if covers is None or not covers:
                        raise ValueError(f"Test case needs a module-level back-annotation like "
                                         f"COVERS = [\"FG-.../FC-.../CK-...\"] listing its checkpoints: {path.name}")
                    unknown = [ck for ck in covers if ck not in checkpoints]
                    if unknown:
                        raise ValueError(f"Test case annotates unknown checkpoints {unknown}: {path.name}")
                    mapping[path.name] = covers
                uncovered = [ck for ck in checkpoints if not any(ck in covers for covers in mapping.values())]
                if uncovered:
                    raise ValueError(f"Test-case back-annotation leaves checkpoints uncovered: {uncovered}")
                run = run_command([sys.executable, "-m", "pytest", "-q", str(tests_dir)],
                                  paths.workspace, 900, env=child_environment())
                atomic_json(paths.state / "test_gate.json", seal(paths, {
                    "function_doc": tree_identity(inside(paths.edit, "functions_and_checks.md")),
                    "tests": _test_sources_tree(tests_dir)}))
                return True, {"test_cases": len(test_files), "checkpoints": len(checkpoints),
                              "tc_coverage": f"{len(checkpoints)}/{len(checkpoints)}",
                              "pytest": run["stdout"][-2000:]}
            if self.phase == "candidates":
                gate_path = paths.state / "test_gate.json"
                if gate_path.exists():
                    sealed = unseal(paths, gate_path)
                    current = {"function_doc": tree_identity(inside(paths.edit, "functions_and_checks.md")),
                               "tests": _test_sources_tree(inside(paths.edit, "tests"))}
                    changed = [name for name in sealed if sealed[name] != current[name]]
                    if changed:
                        raise ValueError(f"Frozen test-stage artifacts changed during candidate iteration: "
                                         f"{changed}; restore them exactly, or start a new workspace")
                if (paths.edit / "functions_and_checks.md").is_file() and \
                        set(read_model(paths.edit, "contract.yaml", TaskContract).requirements) != set(module_checkpoints(paths)):
                    raise ValueError("functions_and_checks.md no longer matches contract.yaml requirements; "
                                     "restore the frozen FG/FC/CK binding before measuring candidates")
                identity = current_identity(paths)
                if not any(r["input_identity"] == identity for r in records):
                    validate_unit(paths)
                    records = validated_records(paths)
                    tests_dir = paths.edit / "tests"
                    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
                        run_command([sys.executable, "-m", "pytest", "-q", str(tests_dir)],
                                    paths.workspace, 900, env=child_environment())
                minimum, maximum = optimization_limits(paths.cfg)
                patience = no_improvement_patience(paths.cfg)
                measured = len(records) - 1
                last_improved = max([0] + [r["iteration"] for r in records[1:] if r["accepted"] and any(c["assessment"] == "improved" for c in r["comparisons"].values())])
                finished = measured >= maximum or (measured >= minimum and measured - last_improved >= patience)
                count = max(minimum, measured if finished else measured + 1)
                if count <= 0:
                    return True, {"success": "No candidate rounds are required for this task."}
                tasks = [f"candidate-{i}" for i in range(1, count + 1)]
                generated = tasks[:measured]
                note: list[str] = []
                self.batch.sync_source_task(tasks, note, "Required distinct unit candidate rounds changed.")
                self.batch.sync_gen_task(generated, note, "Measured unit candidate rounds changed.")
                return self.batch.do_complete(note, is_complete,
                                              "required by the configured candidate round limits",
                                              "in the sealed RunRepoValidation measurement records",
                                              " Call RunRepoValidation with a new variant_id to measure the next distinct candidate.")
            # Final evidence is cheap to recheck once delivery has been rebuilt.
            receipt_path = paths.state / "delivery.json"
            if receipt_path.exists():
                receipt = unseal(paths, receipt_path)
                if (receipt["input_identity"] == current_identity(paths)
                        and receipt["variant_id"] == best_record(paths)["variant_id"]
                        and receipt["bundle_files"] == tree_identity(paths.edit / "delivery")):
                    return True, {"delivery": "repo/delivery", "verification_scope": "unit_only"}
            result = deliver(paths)
            return True, {**{k: v for k, v in result.items() if k != "bundle_files"},
                          "verification_scope": "unit_only", "system_integration": "not_run"}
        except Exception as exc:
            error(f"[RepoModuleChecker/{self.phase}] {traceback.format_exc()[-4000:]}")
            return False, diagnostic("repo_stage_failed", f"{type(exc).__name__}: {exc}"[-6000:],
                                     "Repair the named unit input or dependency according to Guide_Doc/repo_module.md, then call Check again.",
                                     artifact=f"repo/{self.phase}")
