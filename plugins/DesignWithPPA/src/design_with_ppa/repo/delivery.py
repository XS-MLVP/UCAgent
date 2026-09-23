"""Restore complete best variants and prove module delivery in a fresh repository copy."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ..checkers.ppa_iteration import _primary_metric_changes, select_best_accepted_record
from ..contracts import atomic_json, atomic_text
from . import apply_bundle as migration
from .build import prepare_unit
from .common import RepoPaths, inside, run_command, tree_identity
from .models import Candidate, Interface, Recipe, TaskContract, read_model
from .snapshot import snapshot_repository
from .validation import child_environment, current_identity, seal, validate_unit, validated_records


def best_record(paths: RepoPaths) -> dict:
    """Select the best complete measured version using the existing Pareto policy."""

    records = validated_records(paths)
    categories = tuple(paths.cfg.get_value("design_with_ppa.no_regression_metrics", "performance,timing").split(","))
    return select_best_accepted_record(records, categories=categories)


def restore_best(paths: RepoPaths) -> dict:
    """Restore all versioned inputs together, preserving the displaced draft for inspection."""

    best = best_record(paths)
    if current_identity(paths) == best["input_identity"]:
        return best
    source = inside(paths.state, best["snapshot"], exists=True)
    paths.run.mkdir(parents=True, exist_ok=True)
    draft = Path(tempfile.mkdtemp(prefix="displaced-draft-", dir=paths.run))
    for name in ("candidate", "verification", "contract.yaml"):
        current = paths.edit / name
        if current.exists():
            shutil.move(str(current), str(draft / name))
        saved = source / name
        if saved.is_dir():
            shutil.copytree(saved, current)
        else:
            shutil.copy2(saved, current)
    return best


def deliver(paths: RepoPaths, *, migration_script: bool = False) -> dict:
    """Revalidate the selected unit, check patch application, and publish a complete bundle."""

    source = snapshot_repository(paths)
    best = restore_best(paths)
    final = validate_unit(paths, persist=False)
    if not final["hard_targets_pass"] or not final["accepted"]:
        raise ValueError("Restored best variant no longer passes acceptance; inspect current measurement evidence")
    tests_dir = paths.edit / "tests"
    if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
        # Pin the TCs to the delivered variant: the Pareto best is not
        # necessarily the most recently measured record.
        env = child_environment()
        env["REPO_TC_RECORD"] = str(paths.state / "records" / f"{best['iteration']:06d}.json")
        run_command([sys.executable, "-m", "pytest", "-q", str(tests_dir)],
                    paths.workspace, 900, env=env)
    candidate = read_model(paths.edit / "candidate", "candidate.yaml", Candidate)
    destination = paths.output / "repo/delivery"
    temporary = Path(tempfile.mkdtemp(prefix="delivery-", dir=paths.run))
    try:
        bundle = temporary / "bundle"
        bundle.mkdir()
        changes = []
        for change in candidate.changes:
            before = source["files"].get(change.path)
            after = None
            if change.action != "delete":
                original = inside(paths.edit / "candidate/files", change.path, exists=True)
                target = inside(bundle / "files", change.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
                target.chmod(0o755 if change.executable else 0o644)
                after = migration.file_state(target)
            changes.append({"path": change.path, "action": change.action, "before": before, "after": after})
        manifest = {"schema_version": 1, "base_commit": source["commit"],
                    "snapshot_mode": source["snapshot_mode"], "source_identity": source["snapshot_identity"],
                    "submodules": source["submodules"], "variant_id": best["variant_id"],
                    "source_paths": source["selection"]["source_paths"],
                    "excluded_submodules": source["excluded_submodules"],
                    "verification_scope": "unit_only", "system_integration": "not_run", "changes": changes}
        atomic_json(bundle / "manifest.json", manifest)
        fresh = temporary / "applied"
        shutil.copytree(paths.snapshot, fresh, symlinks=True)
        migration.apply_bundle(bundle, fresh, apply=True)
        if tree_identity(fresh) != final["materialized_sources"]:
            raise ValueError("Delivery files do not reproduce the validated source tree")
        # Create a binary-capable Git patch against an independent index, including
        # additions and executable bits, without creating any commit or touching SOURCE_PATH.
        patch_tree = temporary / "patch"
        shutil.copytree(paths.snapshot, patch_tree, symlinks=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        run_command(["git", "init", "-q"], patch_tree, 120, env=env)
        atomic_text(patch_tree / ".git/info/attributes", "* -text -filter -ident\n")
        run_command(["git", "add", "-f", "."], patch_tree, 120, env=env)
        migration.apply_bundle(bundle, patch_tree, apply=True, verify_revision=False)
        for change in candidate.changes:
            if change.action == "add":
                run_command(["git", "add", "-N", "-f", "--", change.path], patch_tree, 120, env=env)
        patch = subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff", "--no-renames"], cwd=patch_tree, env=env)
        (bundle / "changes.patch").write_bytes(patch)
        patch_check = temporary / "patch-check"
        shutil.copytree(paths.snapshot, patch_check, symlinks=True)
        if patch:
            run_command(["git", "apply", "--binary", str(bundle / "changes.patch")], patch_check, 120, env=env)
        if tree_identity(patch_check) != final["materialized_sources"]:
            raise ValueError("Generated patch does not reproduce the validated unit source")
        # Build and test the actual delivery application, not only its candidate overlay.
        recipe = read_model(paths.edit / "candidate", paths.options["build_recipe"], Recipe)
        interface = read_model(paths.edit / "candidate", "interface.yaml", Interface)
        check_build = temporary / "rebuild"
        replay_build = prepare_unit(fresh, paths.edit / "candidate", check_build, recipe, interface, cfg=paths.cfg)
        if replay_build["normalized_rtl_sha256"] != final["build"]["normalized_rtl_sha256"]:
            raise ValueError("Applying the delivery did not reproduce the validated generated RTL")
        shutil.copy2(paths.edit / "contract.yaml", check_build / "contract.yaml")
        shutil.copytree(paths.edit / "verification", check_build / "verification")
        for operation in ("reference", "rtl"):
            run_command([sys.executable, "-m", "design_with_ppa.repo.runner", operation, str(check_build)], check_build, recipe.timeout, env=child_environment())
        shutil.copytree(paths.edit / "candidate", bundle / "candidate")
        shutil.copytree(paths.edit / "verification", bundle / "verification")
        shutil.copy2(paths.edit / "contract.yaml", bundle / "contract.yaml")
        shutil.copytree(check_build / "design/rtl", bundle / "rtl")
        records = validated_records(paths)
        changes = _primary_metric_changes(
            {**records[0]["ppa_metrics"], **records[0]["performance_metrics"]},
            {**best["ppa_metrics"], **best["performance_metrics"]}, rel_tol=1e-6, abs_tol=1e-12)
        improvement = any(row["assessment"] == "improved" for row in changes.values())
        atomic_json(bundle / "validation.json", final)
        atomic_json(bundle / "history.json", {"records": records})
        atomic_text(bundle / "interface_changes.md", "\n# Interface Changes\n\n"
                    + "Baseline interface: `" + records[0]["interface"]["version"] + "`.\n\n"
                    + "Delivered interface: `" + best["interface"]["version"] + "`.\n\n"
                    + "See candidate/interface.yaml for all public pins and protocol details. "
                    + "Only module unit tests and module PPA were run. The repository supplied source dependencies; "
                    + "the complete system was not built or tested.\n")
        atomic_json(bundle / "interfaces.json", {"baseline": records[0]["interface"], "delivered": best["interface"]})
        # The human-facing summary reports only sealed measurement records, so a
        # delivery can never narrate better numbers than it actually measured.
        contract = read_model(paths.edit, "contract.yaml", TaskContract)
        metric_rows = "\n".join(
            f"| {name} | {row['baseline']:.6g} {row['unit']} | {row['current']:.6g} {row['unit']} | "
            f"{row['delta']:+.6g} | "
            + ("n/a" if row["percent_change"] is None else f"{row['percent_change']:+.1f}%")
            + f" | {row['assessment']} |"
            for name, row in changes.items())
        atomic_text(bundle / "summary.md", "\n# Repository Module Delivery Summary\n\n"
                    + f"- Task: {contract.objective}\n"
                    + f"- Mode: {paths.options['mode']}; source commit `{source['commit']}` "
                    + f"({source['snapshot_mode']} snapshot).\n"
                    + f"- Baseline variant: `{records[0]['variant_id']}`; delivered variant: "
                    + f"`{best['variant_id']}` ({len(records) - 1} measured candidate rounds, "
                    + f"{sum(1 for r in records[1:] if r['accepted'])} accepted).\n"
                    + f"- Interface: `{records[0]['interface']['version']}` -> "
                    + f"`{best['interface']['version']}` (policy: {paths.options['interface_policy']}).\n"
                    + f"- Hard targets: {'pass' if final['hard_targets_pass'] else 'fail'}.\n\n"
                    + "## Measured Primary Metrics\n\n"
                    + "| metric | baseline | delivered | delta | change | assessment |\n"
                    + "| --- | --- | --- | --- | --- | --- |\n"
                    + metric_rows + "\n\n"
                    + "## Conclusion\n\n"
                    + ("At least one primary metric improved against the immutable baseline.\n" if improvement
                       else "No primary metric improved against the immutable baseline; "
                            "this delivery records that result without fabricating an optimization claim.\n")
                    + f"\nCaller impact: {contract.caller_impact}\n\n"
                    + "Verification scope: unit only (`verification_scope: unit_only`); "
                    + "the complete system was not built or tested.\n")
        if migration_script:
            shutil.copy2(Path(migration.__file__), bundle / "apply.py")
        if destination.exists():
            shutil.move(str(destination), str(temporary / "previous-delivery"))
        shutil.move(str(bundle), str(destination))
        receipt = {"variant_id": best["variant_id"], "input_identity": current_identity(paths),
                   "bundle_files": tree_identity(destination), "patch_rebuild_pass": True,
                   "improvement_found": improvement}
        atomic_json(paths.state / "delivery.json", seal(paths, receipt))
        return {"status": "pass", "delivery": destination.relative_to(paths.workspace).as_posix(), **receipt}
    finally:
        shutil.rmtree(temporary)
