"""Read generation status without launching processes, creating files or replaying evidence."""

import argparse
import fcntl
import json
from pathlib import Path
import re

import yaml

from .finding_acceptance import finding_outcome
from .xiangshan_bundle import safe_path, sha256


def read_status(workspace: Path) -> dict:
    """Distinguish launcher liveness, official validation decisions and scoped evidence."""
    workspace = workspace.resolve(strict=True)
    runtime = safe_path(workspace, ".ucagent")
    config = yaml.safe_load(safe_path(runtime, "act4-run.yaml").read_bytes())["act4_run"]
    if Path(config["workspace"]).resolve() != workspace:
        raise ValueError("Run snapshot does not belong to this workspace")
    lock = safe_path(runtime, "act4-run.lock")
    process = "unknown"
    if lock.is_file():
        with lock.open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                process = "stopped"
            except BlockingIOError:
                process = "running"
    checkpoint = safe_path(runtime, "ucagent_info.json")
    info = json.loads(checkpoint.read_bytes()) if checkpoint.is_file() else {}
    stages = info.get("stages_info", {})
    index = info.get("stage_index")
    stage = stages.get(str(index), {})
    event_path = safe_path(runtime, "last_validation.json")
    event = json.loads(event_path.read_bytes()) if event_path.is_file() else None
    result = {"suite": config["suite"], "process": process, "all_completed": info.get("all_completed", False),
              "completed": sum(item["is_completed"] for item in stages.values()), "total": len(stages),
              "stage": stage.get("task", {}).get("title"), "last_validation": event,
              "current_blocker": (event.get("diagnostic") if event and event.get("stage_index") == index and not event.get("passed") else None),
              "configs": {}}
    reports = safe_path(workspace, f"{config['output']}/intermediate/{config['suite']}/reports")
    data = info.get("stage_data", {})
    review_dir = f"{config['output']}/intermediate/{config['suite']}/review"
    review = safe_path(workspace, f"{review_dir}/final-accepted.json")
    result["finding_outcome"] = None
    trusted = data.get(f"act4_review:{review_dir}:{config['suite']}", {}).get("final_snapshot")
    if trusted and review.is_file() and sha256(review) == trusted:
        result["finding_outcome"] = finding_outcome(json.loads(review.read_bytes())["findings"])
    paths = [safe_path(reports, f"{directory}/test-assets.json") for directory in ("native-selection", "act4_test_asset_check", "contribution-test-assets")]
    for path in sorted((path for path in paths if path.is_file()), key=lambda path: path.stat().st_mtime_ns):
        report = json.loads(path.read_bytes())
        for name, item in report.get("configs", {}).items():
            checks = item["checks"]
            selection = checks.get("source_selection") or {}
            entry = result["configs"].setdefault(name, {})
            entry.update(last_gate=path.parent.name, gate_status=item["status"], xlen=selection.get("xlen"),
                         selected=len(selection["selected_sources"]) if selection else None, complete_signature_chains=checks.get("complete_reference_runs"))
            entry["runner_pass_summaries"] = None
            if selection:
                build = Path(selection["build_root"]).relative_to(workspace / "riscv-arch-test" / f"work_itgen_{config['suite']}")
                summary = safe_path(workspace, f"riscv-arch-test/work_itgen_{config['suite']}/{build}/summary.log")
                if summary.is_file():
                    lines = {line.strip() for line in summary.read_text(errors="replace").splitlines()}
                    entries = {tuple(line.split(maxsplit=1)) for line in lines}
                    entry["runner_pass_summaries"] = sum((f"priv/{config['suite']}/{Path(source).stem}.log", f'RVCP-SUMMARY: TEST PASSED - Test File "{Path(source).name}"') in entries for source in selection["selected_sources"])
    validation = safe_path(reports, f"{config['suite']}_validation_state.yaml")
    native = safe_path(reports.parent, "native-validation")
    receipt = safe_path(native, "receipt.json")
    if receipt.is_file() and data.get(f"act4_native_validation:{native}") == sha256(receipt):
        jobs = {job["name"]: job for job in json.loads(receipt.read_bytes())["results"]}
        for name, job in jobs.items():
            if not name.startswith("build_") or job["status"] != "passed":
                continue
            target = next((arg.split("=", 1)[1] for arg in job["argv"] if arg.startswith("CONFIG_FILES=")), None)
            run = jobs.get(name.replace("build_", "run_", 1), {})
            if target and run.get("status") == "passed":
                log = safe_path(native, run["log"])
                if log.is_file() and sha256(log) == run["sha256"]:
                    counts = re.findall(r"(?m)^\s*RESULT: All ([1-9][0-9]*) tests? passed\.\s*$", log.read_text(errors="replace"))
                    if len(counts) == 1:
                        result["configs"].setdefault(target, {})["native_tests_passed"] = int(counts[0])
    reported = yaml.safe_load(validation.read_bytes()) if validation.is_file() else {}
    result["reported_sail_coverage"] = (reported or {}).get("sail_coverage", {}).get("passed")
    return result


def main(argv=None) -> int:
    """Print machine-readable status; missing or malformed snapshots are not successful runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(read_status(args.workspace), ensure_ascii=False, indent=2))
    except (OSError, TypeError, KeyError, ValueError, AttributeError, yaml.YAMLError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
