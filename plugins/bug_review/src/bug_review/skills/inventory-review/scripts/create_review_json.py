"""Create the editable canonical Bug Review JSON for one input workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ucagent.util.config import load_runtime_config

from bug_review.json_io import read_object
from bug_review.workflow import _inventory, _workspace_node, safe_name


def main() -> None:
    """Scaffold all source Bug and test identities without making conclusions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", help="Selected workspace label, for example workspace_raid_dec_top")
    args = parser.parse_args()
    name = safe_name(args.workspace)
    root = Path.cwd().resolve()
    runtime = load_runtime_config(root)
    output = (root / runtime["OUT"]).resolve()
    if not output.is_relative_to(root) or output == root:
        raise ValueError("Resolved OUT must be a child of the current workspace")
    job = read_object(root / "review_job.json")
    if job.get("schema") != "bug_review_job.v4":
        raise ValueError("review_job.json must use bug_review_job.v4; prepare a fresh output root")
    sources = {label: Path(path) for label, path in job["source_runs"]}
    source = sources.get(name)
    if source is None:
        raise ValueError(f"Workspace is not selected in review_job.json: {name}")
    inventory, _ = _inventory(source, name)
    dut = inventory["dut"]
    bugs = []
    cases = {}
    for item in inventory["bugs"]:
        bug_id = item["bug_id"]
        summary_source = dict(item["source"])
        summary_source["path"] = Path(summary_source["path"]).resolve().relative_to(source).as_posix()
        claims = []
        for claim in item["claims"]:
            claim = dict(claim)
            claim_source = dict(claim.get("source", {}))
            claim_path = Path(claim_source.get("path", ""))
            if claim_path.is_absolute():
                claim_source["path"] = claim_path.resolve().relative_to(source).as_posix()
            claim["source"] = claim_source
            claims.append(claim)
        case_ids = []
        for node in item["tests"]:
            case_id = _workspace_node(node)
            case_ids.append(case_id)
            test_path = case_id.removeprefix("unity_test/tests/").removeprefix("tests/")
            cases.setdefault(case_id, {
                "nodeid": case_id,
                "bug_ids": [],
                "source_nodeid": case_id,
                "replay_target": f"{name}/unity_test/tests/{test_path}",
                "waveform_test_case_name": "",
                "replay": {"status": "not_selected", "invocation_success": False, "test_count": 0},
                "test_review": {"classification": "inconclusive", "correctness_confirmed": False},
                "waveform": {"conclusion": "inconclusive", "receipt_id": "", "result": None},
            })
            if bug_id not in cases[case_id]["bug_ids"]:
                cases[case_id]["bug_ids"].append(bug_id)
        bugs.append({
            "bug_id": bug_id,
            "origin": "reported",
            "bug_summary": {"summary_item_present": item.get("summary_item_present", True),
                            "raw": item.get("raw", ""), "text": item["summary"],
                            "severity": item["severity"], "check_points": item["ck"],
                            "rtl_candidates": item["rtl_refs"], "source": summary_source},
            "reported_confidence": item["reported_confidence"],
            "analysis_claims": claims,
            "evidence": {
                "test_points": [], "check_points": item["ck"], "case_ids": case_ids,
                "spec": [{"ref": ref, "status": "candidate"} for ref in item["spec_refs"]],
                "rtl": [{"ref": ref, "status": "candidate"} for ref in item["rtl_refs"]],
                "root_candidates": item["root_refs"],
            },
            "decision": {"verdict": "inconclusive", "review_confidence": None,
                          "rationale": "Pending evidence review", "root_id": None},
        })
    document = {
        "schema": "bug_review.v3",
        "workspace": {"name": name, "dut": dut, "source_path": str(source)},
        "source_files": {
            "bug_summary": str(source / "unity_test" / f"{dut}_bug_summary.md"),
            "bug_analysis": str(source / "unity_test" / f"{dut}_bug_analysis.md"),
        },
        "stage_status": {stage: "pending" for stage in ("inventory", "replay", "waveform", "correlate", "publish")},
        "suspected_bugs": bugs,
        "cases": cases,
        "root_causes": [],
    }
    target = output / "workspaces" / name / "bug_review.json"
    if target.exists():
        raise FileExistsError(f"Refusing to replace an existing review artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(target.relative_to(root)))


if __name__ == "__main__":
    main()
