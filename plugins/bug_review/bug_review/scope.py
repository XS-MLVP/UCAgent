"""Freeze the analysis scope from observed runs, independently of scoring targets."""
from dataclasses import asdict, replace
from pathlib import Path
import shutil

from bug_review.benchmark_workflow.discover import discover_all_runs
from bug_review.benchmark_workflow.task_manifest import stable_hash


def discover_scope(runs, workspace):
    manifests, rejected, seen = [], [], set()
    for model, name in runs:
        source = Path(name).resolve()
        for index, manifest in enumerate(discover_all_runs(str(source), model_label=model, native_ucagent=True)):
            root = Path(manifest.workspace_root).resolve()
            native_unitytest = (
                (root / ".ucagent/runtime_config.json").is_file()
                and (root / "unity_test/tests").is_dir()
                and bool(manifest.tests_root)
                and bool(manifest.rtl_root)
            )
            if native_unitytest and not root.is_relative_to(Path(workspace).resolve()):
                rejected.append({
                    "path": str(root),
                    "reason": (
                        "external UnityTest workspace must be staged inside the analysis workspace; "
                        "run make bug_review_<name> from the UCAgent checkout before starting the workflow"
                    ),
                })
                continue
            if not (manifest.found_files.get("run_info") or manifest.found_files.get("toffee_report")
                    or (root / ".ucagent/ucagent_info.json").is_file() or native_unitytest):
                rejected.append({"path": str(root), "reason": "no recognizable run metadata or test report"})
                continue
            identity = (model, str(root))
            if identity in seen:
                continue
            seen.add(identity)
            location = str(root.relative_to(source)) if source.is_dir() and root.is_relative_to(source) else index
            manifest = replace(manifest, run_key=stable_hash([manifest.run_key, model, str(source), location])[:16])
            # Archive extraction uses temporary directories. Persist their content
            # before freezing paths so later stages can resume independently.
            if not source.is_dir() or not root.is_relative_to(source):
                destination = Path(workspace) / "source_runs" / stable_hash(
                    [model, str(source), manifest.dut, manifest.run_key])[:24]
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(root, destination)
                def relocated(value):
                    if value and Path(value).is_relative_to(root):
                        return str(destination / Path(value).relative_to(root))
                    return value
                manifest = replace(
                    manifest, workspace_root=str(destination),
                    found_files={k: relocated(v) for k, v in manifest.found_files.items()},
                    **{key: relocated(getattr(manifest, key)) for key in (
                        "unity_test_root", "tests_root", "data_root", "guide_doc_root",
                        "rtl_root", "completion_evidence")})
            manifests.append(asdict(manifest))
    if not manifests:
        details = "; ".join(f"{row['path']}: {row['reason']}" for row in rejected)
        raise ValueError(
            "no recognizable analysis runs in inputs; expected prepared UCAgent workspace metadata or test reports"
            + (f" ({details})" if details else "")
        )
    return {"schema": "benchmark_analysis_scope.v1",
            "duts": sorted({m["dut"] for m in manifests}),
            "runs": manifests, "rejected": rejected,
            "policy": "all discovered runs; incomplete runs retained with missing-evidence diagnostics"}
