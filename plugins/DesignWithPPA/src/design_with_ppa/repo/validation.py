"""Measured unit validation, immutable baselines, and complete candidate evidence."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
import shutil
import sys
import tempfile

import ucagent.util.functions as uc_functions

from ..checkers.ppa_iteration import (
    _metric_category, _ppa_primary_metrics, _ppa_selection_score,
    _primary_metric_changes, select_best_accepted_record,
)
from ..contracts import atomic_json, canonical_json_sha256, load_json, sha256_file
from ..ppa import AnalyzePPA, AnalyzePPAArgs
from .build import prepare_unit
from .common import RepoPaths, inside, run_command, selected_path, tree_identity
from .evidence import seal, unseal
from .models import Candidate, Interface, Recipe, TaskContract, Workload, read_model, validate_python
from .snapshot import materialize, snapshot_repository


def module_checkpoints(paths: RepoPaths) -> list[str]:
    """Read the canonical FG/FC/CK leaf set from the authored function document."""

    document = inside(paths.edit, "functions_and_checks.md", exists=True)
    return sorted(uc_functions.get_unity_chip_doc_marks(str(document), "CK", 1))


def checkpoint_coverage(contract: TaskContract, workload: Workload) -> dict:
    """Aggregate scenario and transaction coverage statistics per FG/FC/CK path."""

    rows = {key: {"scenarios": 0, "transactions": 0} for key in contract.requirements}
    for scenario in workload.scenarios:
        for key in scenario.covers:
            rows[key]["scenarios"] += 1
            rows[key]["transactions"] += len(scenario.transactions)
    return {"checkpoints": rows, "covered": len(rows), "total": len(rows),
            "coverage": 1.0 if rows else 0.0}


def read_contract(paths: RepoPaths) -> tuple[TaskContract, Workload, dict]:
    """Validate semantic coverage and capture the complete frozen task/reference identity."""

    contract = read_model(paths.edit, "contract.yaml", TaskContract)
    workload = read_model(paths.edit, "verification/workload.yaml", Workload)
    covered = {key for scenario in workload.scenarios for key in scenario.covers}
    if covered != set(contract.requirements):
        raise ValueError(f"Workload coverage must match requirements: missing={sorted(set(contract.requirements) - covered)}, unknown={sorted(covered - set(contract.requirements))}")
    for scenario in workload.scenarios:
        releases = [t.release_cycle for t in scenario.transactions]
        span = max(releases) - min(releases) + 1
        if len(releases) / span < contract.min_throughput_per_cycle:
            raise ValueError(
                f"Workload scenario '{scenario.name}' cannot reach min_throughput_per_cycle: "
                f"{len(releases)} transactions over a release span of {span} cycles cap throughput "
                f"at {len(releases) / span:.4g} < {contract.min_throughput_per_cycle}. Schedule the "
                "release_cycle values densely enough (remove idle gaps) and call Check again.")
    validate_python(inside(paths.edit, "verification/reference.py", exists=True), reference=True)
    dut = paths.cfg.get_value("_temp_cfg", {}).get("DUT")
    task_root = inside(paths.workspace, dut, exists=True)
    if not (task_root / "README.md").is_file():
        raise ValueError(f"Task input is missing: {dut}/README.md")
    identity = {"task_inputs": tree_identity(task_root), "contract": contract.model_dump(),
                "verification": tree_identity(paths.edit / "verification")}
    liberty = paths.cfg.get_value("design_with_ppa.ppa.liberty_file", None)
    sdc = paths.cfg.get_value("design_with_ppa.ppa.sdc_file", None)
    identity["ppa"] = {"liberty": sha256_file(inside(paths.workspace, liberty, exists=True)) if liberty else "bundled",
                       "sdc": sha256_file(inside(paths.workspace, sdc, exists=True)) if sdc else None,
                       "no_regression_metrics": paths.cfg.get_value("design_with_ppa.no_regression_metrics", "performance,timing"),
                       "score_weights": {k: paths.cfg.get_value(f"design_with_ppa.score_weights.{k}", 1.0) for k in ("timing", "area", "power")}}
    return contract, workload, identity


def child_environment() -> dict:
    """Use the exact currently loaded package roots for independent runner subprocesses."""

    import ucagent

    roots = [str(Path(__file__).resolve().parents[2]), str(Path(ucagent.__file__).resolve().parent.parent)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "SOURCE_PATH"}
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(roots + env.get("PYTHONPATH", "").split(os.pathsep)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    return env


def reference_check(paths: RepoPaths) -> dict:
    """Execute deterministic reference examples in a disposable copy without RTL."""

    contract, workload, identity = read_contract(paths)
    paths.run.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reference-", dir=paths.run) as name:
        root = Path(name)
        shutil.copy2(paths.edit / "contract.yaml", root / "contract.yaml")
        shutil.copytree(paths.edit / "verification", root / "verification")
        run_command([sys.executable, "-m", "design_with_ppa.repo.runner", "reference", str(root)], root, 120, env=child_environment())
        expected = load_json(root / "expected.json")
    statistics = checkpoint_coverage(contract, workload)
    atomic_json(paths.edit / "coverage.json", statistics)
    return {"identity": canonical_json_sha256(identity), "expected": expected,
            "coverage": statistics}


def current_identity(paths: RepoPaths) -> str:
    """Hash all authored variant and semantic inputs that invalidate validation evidence."""

    _, _, contract = read_contract(paths)
    return canonical_json_sha256({"settings": paths.identity(), "contract": contract,
                                  "candidate": tree_identity(paths.edit / "candidate")})


def validated_records(paths: RepoPaths) -> list[dict]:
    """Load authentic records and reject altered complete version snapshots."""

    records = []
    for artifact in sorted((paths.state / "records").glob("*.json")):
        record = unseal(paths, artifact)
        stored = inside(paths.state, record["snapshot"], exists=True)
        if tree_identity(stored) != record["snapshot_files"]:
            raise ValueError(f"Saved variant snapshot changed: {record['variant_id']}")
        records.append(record)
    return sorted(records, key=lambda record: record["iteration"])


def validate_unit(paths: RepoPaths, *, baseline: bool = False, persist: bool = True) -> dict:
    """Build and measure a module using frozen semantics and variant-specific public pins."""

    source = snapshot_repository(paths)
    contract, workload, semantic = read_contract(paths)
    for name in contract.dependencies + (contract.target_paths if paths.options["mode"] == "optimize" else []):
        if name not in source["files"]:
            raise ValueError(f"Declared source dependency or optimization target is absent from source_snapshot: {name}")
    candidate_root = paths.edit / "candidate"
    candidate = read_model(candidate_root, "candidate.yaml", Candidate)
    interface = read_model(candidate_root, "interface.yaml", Interface)
    recipe = read_model(candidate_root, paths.options["build_recipe"], Recipe)
    for command in recipe.build + recipe.tool_versions:
        if any(str(paths.source) in argument for argument in command.argv):
            raise ValueError("Module commands must use the independent copy, not an absolute SOURCE_PATH reference")
    for name in ("adapter.py", "protocol.py"):
        validate_python(inside(candidate_root, name, exists=True), protocol=name == "protocol.py")
    for change in candidate.changes:
        if not selected_path(change.path, paths.options["source_paths"]):
            raise ValueError(f"Change is outside imported source_paths: {change.path}; select its parent directory in a new workspace")
        if not any(fnmatch.fnmatchcase(change.path, pattern) for pattern in contract.allowed_changes):
            raise ValueError(f"Change is outside contract.allowed_changes: {change.path}")
    records = validated_records(paths)
    original = records[0] if records else None
    semantic_hash = canonical_json_sha256(semantic)
    if original and original["semantic_identity"] != semantic_hash:
        raise ValueError("Task/reference/workload/PPA contract changed; establish a fresh baseline in a new workspace")
    if not original and not baseline:
        raise ValueError("RunRepoValidation(baseline=true) is required before candidate measurements")
    if baseline and original:
        if original["input_identity"] == current_identity(paths):
            return original
        raise ValueError("The original baseline already exists and cannot be replaced")
    if not original and paths.options["mode"] == "optimize" and candidate.changes:
        raise ValueError("Optimization baseline must use the unmodified source: changes must be empty")
    if paths.options["mode"] == "add" and not any(c.action == "add" and c.path in contract.target_paths for c in candidate.changes):
        raise ValueError("add mode requires an added target_paths entry")
    if original:
        if paths.options["interface_policy"] == "preserve" and interface.model_dump() != original["interface"]:
            raise ValueError("interface_policy=preserve requires the baseline interface unchanged")
        for record in records:
            if record["interface"]["version"] == interface.version and record["interface"] != interface.model_dump():
                raise ValueError("Changed pins/protocol require a new interface.version")
    before = current_identity(paths)
    frozen_trees = {"source_snapshot": tree_identity(paths.snapshot),
                    "verification": tree_identity(paths.edit / "verification"),
                    "candidate": tree_identity(candidate_root)}
    candidate_files = tree_identity(candidate_root)
    candidate_files.pop("candidate.yaml", None)
    experiment = canonical_json_sha256({"files": candidate_files, "changes": [c.model_dump() for c in candidate.changes]})
    if persist:
        for record in records:
            if record["input_identity"] == before:
                return record
            if record["variant_id"] == candidate.variant_id:
                raise ValueError("A measured variant_id is immutable; select a new variant_id for changed files")
            if record["experiment_identity"] == experiment:
                raise ValueError("Only variant_id/hypothesis changed; implement a distinct unit experiment before measuring another round")
    paths.run.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix=candidate.variant_id + "-", dir=paths.run))
    repository, build = run_root / "repository", run_root / "validation"
    source_files = materialize(paths.snapshot, candidate_root, candidate.changes, repository)
    build_evidence = prepare_unit(repository, candidate_root, build, recipe, interface, cfg=paths.cfg)
    if not persist:
        measured = next((r for r in records if r["input_identity"] == before), None)
        if measured is None or measured["build"]["normalized_rtl_sha256"] != build_evidence["normalized_rtl_sha256"]:
            raise ValueError("Rebuilt RTL differs from the measured variant; inspect generator/toolchain changes before delivery")
    shutil.copy2(paths.edit / "contract.yaml", build / "contract.yaml")
    shutil.copytree(paths.edit / "verification", build / "verification")
    env = child_environment()
    reference_run = run_command([sys.executable, "-m", "design_with_ppa.repo.runner", "reference", str(build)], build, recipe.timeout, env=env)
    rtl_run = run_command([sys.executable, "-m", "design_with_ppa.repo.runner", "rtl", str(build)], build, recipe.timeout, env=env)
    results = load_json(build / "unit_results.json")
    latencies, throughputs = [], []
    for scenario in workload.scenarios:
        result = results["scenarios"][scenario.name]
        rows = result["results"]
        # User-visible latency includes waiting after a frozen release time; an adapter
        # cannot improve it by delaying accept() until hardware is ready.
        latencies += [max(1, rows[t.id]["completed_cycle"] - t.release_cycle) for t in scenario.transactions]
        duration = max(1, max(r["completed_cycle"] for r in rows.values()) - min(t.release_cycle for t in scenario.transactions) + 1)
        throughputs.append(len(rows) / duration)
    performance = {"unit.latency_cycles": {"value": max(latencies), "unit": "cycle", "direction": "min"},
                   "unit.throughput_per_cycle": {"value": min(throughputs), "unit": "transaction/cycle", "direction": "max"}}
    hard_pass = max(latencies) <= contract.max_latency_cycles and min(throughputs) >= contract.min_throughput_per_cycle
    sdc = paths.cfg.get_value("design_with_ppa.ppa.sdc_file", None)
    arguments = AnalyzePPAArgs(
        rtl_files=[(build / "design/rtl/unit.v").relative_to(paths.workspace).as_posix()],
        top_module=interface.top,
        waveform_files=[(build / result["waveform"]).relative_to(paths.workspace).as_posix() for result in results["scenarios"].values()],
        waveform_scope=f"TOP.{interface.top}",
        liberty_file=paths.cfg.get_value("design_with_ppa.ppa.liberty_file", None),
        sdc_file=sdc,
        clock_port=interface.clock if not sdc else None,
        clock_period_ns=contract.clock_period_ns if interface.clock and not sdc else None,
        max_timing_paths=paths.cfg.get_value("design_with_ppa.ppa.max_timing_paths", 10),
        max_power_instances=paths.cfg.get_value("design_with_ppa.ppa.max_power_instances", 10),
        report_path=(paths.output / "repo/reports" / (run_root.name + "-ppa.json")).relative_to(paths.workspace).as_posix(),
        timeout=recipe.timeout,
    )
    report = AnalyzePPA(workspace=str(paths.workspace), output_dir=paths.output.relative_to(paths.workspace).as_posix(),
                        write_dirs=[paths.output.relative_to(paths.workspace).as_posix()], un_write_dirs=[]).analyze(arguments)
    ppa_metrics = _ppa_primary_metrics(report)
    # A combinational unit may become sequential during interface exploration.
    # Keep a stable period metric while retaining the complete native STA report.
    timing_key = next(k for k in ppa_metrics if k.startswith("ppa.timing."))
    timing = ppa_metrics.pop(timing_key)
    period = 1e9 / timing["value"] if timing["unit"] == "Hz" else timing["value"]
    ppa_metrics["ppa.timing.effective_period_ns"] = {"value": period, "unit": "ns", "direction": "min"}
    hard_pass = hard_pass and all(limit is None or ppa_metrics[key]["value"] <= limit for key, limit in (
        ("ppa.area.total", contract.max_area), ("ppa.power.total_w", contract.max_power_w),
        ("ppa.timing.effective_period_ns", contract.max_effective_period_ns)))
    comparisons = {}
    accepted = hard_pass or not original
    categories = tuple(semantic["ppa"]["no_regression_metrics"].split(","))
    if any(c not in {"performance", "timing", "area", "power"} for c in categories):
        raise ValueError("no_regression_metrics must list performance,timing,area,power categories")
    # Existing metric selection classifies non-PPA names as functional performance.
    if original:
        previous = select_best_accepted_record(records, categories=categories)
        comparisons = _primary_metric_changes({**previous["ppa_metrics"], **previous["performance_metrics"]},
                                               {**ppa_metrics, **performance}, rel_tol=1e-6, abs_tol=1e-12)
        accepted = hard_pass and not any(c["assessment"] == "regressed" and _metric_category(k) in categories for k, c in comparisons.items())
    drifted = [name for name, tree in frozen_trees.items()
               if tree != tree_identity(paths.snapshot if name == "source_snapshot"
                                        else paths.edit / name)]
    if current_identity(paths) != before or drifted:
        raise ValueError(f"Authored inputs changed while the measurement was running: {drifted or ['task README, contract.yaml, or settings']}; "
                         "finish your edits first, then rerun the current variant")
    record = {"schema_version": 1, "variant_id": candidate.variant_id,
              "iteration": len(records), "baseline": not bool(original), "accepted": accepted,
              "hard_targets_pass": hard_pass, "input_identity": before,
              "experiment_identity": experiment,
              "semantic_identity": semantic_hash, "interface": interface.model_dump(),
              "source_identity": source["snapshot_identity"], "functional_regression": {"pass": True},
              "verification_scope": "unit_only", "system_integration": "not_run",
              "ppa_metrics": ppa_metrics, "performance_metrics": performance,
              "comparisons": comparisons, "ppa_report": report,
              "ppa_score": _ppa_selection_score(original["ppa_metrics"] if original else ppa_metrics, ppa_metrics,
                                                 weights=semantic["ppa"]["score_weights"]),
              "unit_results": results, "build": build_evidence,
              "reference_run": reference_run, "rtl_run": rtl_run,
              "materialized_sources": source_files,
              "run_directory": run_root.relative_to(paths.workspace).as_posix()}
    if persist:
        saved = paths.state / "versions" / candidate.variant_id
        if saved.exists():
            raise ValueError(f"Version snapshot already exists without valid record: {candidate.variant_id}")
        shutil.copytree(candidate_root, saved / "candidate")
        shutil.copytree(paths.edit / "verification", saved / "verification")
        shutil.copy2(paths.edit / "contract.yaml", saved / "contract.yaml")
        record["snapshot"] = saved.relative_to(paths.state).as_posix()
        record["snapshot_files"] = tree_identity(saved)
        atomic_json(paths.state / "records" / f"{len(records):06d}.json", seal(paths, record))
        atomic_json(paths.edit / "reports" / (candidate.variant_id + ".json"), record)
    return record
