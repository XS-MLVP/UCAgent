"""Run the five-stage Bug Review analysis against immutable DUT inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from ucagent.tools.waveform import WaveInfo

from bug_review.analysis_core.report_inventory import build_report_inventory
from bug_review.analysis_core.task_manifest import atomic_write_json
from .inputs import discover_input_workspaces, resolve_run_specs
from .json_io import read_object


ANALYSIS = ("inventory", "replay", "waveform", "correlate", "publish")
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def safe_name(value):
    """Validate a workspace label before using it as an output path component."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError(f"invalid workspace name: {value!r}")
    return value


def _canonical_node(node):
    """Drop report line annotations while preserving the exact pytest node ID."""
    return re.sub(r"(?<=\.py):\d+(?:-\d+)?(?=::|$)", "", str(node))


def _workspace_node(node):
    """Normalize a RunTestCases node ID to the copied DUT workspace layout."""
    value = _canonical_node(node)
    value = re.sub(r"^workspace_[A-Za-z0-9_.-]+/", "", value)
    if value.startswith("tests/"):
        return "unity_test/" + value
    if value.startswith("unity_test/"):
        return value
    if value.endswith(".py") or ".py::" in value:
        return "unity_test/tests/" + value
    return value


def _parse_summary(path):
    """Read the summary table while retaining its source row and analysis links."""
    if not path.is_file():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in {"Name", "---"}:
            continue
        name = cells[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            continue
        ranges = [(int(a), int(b)) for a, b in re.findall(
            r"bug_analysis\.md:(\d+)-(\d+)", cells[7])]
        rows.append({"bug_id": name, "summary": cells[4], "severity": cells[1],
                     "raw": line, "summary_item_present": True,
                     "reported_confidence": float(cells[6]) if re.fullmatch(r"0(?:\.\d+)?|1(?:\.0+)?", cells[6]) else None,
                     "ck": re.findall(r"FG-[^< ]+/FC-[^< ]+/CK-[^< ]+", cells[3]),
                     "rtl_refs": re.findall(r"[A-Za-z0-9_./-]+\.(?:sv|v):\d+(?:-\d+)?", cells[5]),
                     "source": {"path": str(path), "line": line_number},
                     "analysis_ranges": ranges})
    ids = [row["bug_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate Bug name in {path}")
    return rows


def _inventory(source, name):
    """Build one reported-Bug inventory and a readable outline."""
    dut = source.name.removeprefix("workspace_")
    summary = source / "unity_test" / f"{dut}_bug_summary.md"
    analysis = source / "unity_test" / f"{dut}_bug_analysis.md"
    table = _parse_summary(summary)
    claims = build_report_inventory(analysis, run_key=name, model="reported", dut=dut)["bugs"] if analysis.is_file() else []
    assigned = set()
    bugs = []
    for row in table:
        related = [claim for claim in claims if any(
            start <= int(claim["source"]["line_start"]) <= end for start, end in row["analysis_ranges"])]
        assigned.update(claim["claim_id"] for claim in related)
        bugs.append({**row, "origin": "reported", "claims": related,
                     "tests": sorted({test for claim in related for test in claim["referenced_tests"]}),
                     "root_refs": sorted({ref for claim in related for ref in claim["root_refs"]})})
    for claim in claims:
        if claim["claim_id"] in assigned:
            continue
        identity = claim["bug_id"]
        row = next((item for item in bugs if item["bug_id"] == identity), None)
        if row is None:
            row = {"bug_id": identity, "origin": "reported", "summary": claim["summary"],
                   "summary_item_present": False,
                   "severity": "", "reported_confidence": (
                       claim["confidence_percent"] / 100 if claim["confidence_percent"] is not None else None),
                   "ck": ["/".join(part for part in (claim["fg"], claim["fc"], claim["ck"]) if part)],
                   "rtl_refs": [], "source": claim["source"],
                   "analysis_ranges": [], "claims": [], "tests": [], "root_refs": []}
            bugs.append(row)
        row["claims"].append(claim)
        row["tests"] = sorted(set(row["tests"] + claim["referenced_tests"]))
        row["root_refs"] = sorted(set(row["root_refs"] + claim["root_refs"]))
    line_maps = source / "unity_test/line_map"
    spec_files = {path.relative_to(source).as_posix().replace("/", "_").replace(".", "_"): path
                  for path in source.rglob("*.md") if "Guide_Doc" not in path.parts}
    for bug in bugs:
        refs = []
        for mapping in sorted(line_maps.glob("*_line_func_map.txt")):
            key = mapping.name.removesuffix("_line_func_map.txt")
            spec = spec_files.get(key)
            if spec is None:
                continue
            for line in mapping.read_text(encoding="utf-8", errors="replace").splitlines():
                for ck in bug["ck"]:
                    match = re.match(rf"^{re.escape(ck)}:\s*(\d+)-(\d+)", line)
                    if match:
                        refs.append(f"{spec.relative_to(source)}:{match.group(1)}-{match.group(2)}")
        bug["spec_refs"] = sorted(set(refs))[:32]
    if not summary.is_file() and not analysis.is_file():
        raise ValueError(f"Bug reports missing for {name}: {summary}, {analysis}")
    lines = ["", f"# {dut} Bug 复核骨架", "", f"输入工作区：{source}", ""]
    if not bugs:
        lines.extend(["## 原报告 Bug", "", "原报告没有 Bug 条目。", ""])
    for row in bugs:
        lines.extend([f"## {row['bug_id']}", "", row["summary"] or "待核对原报告声明", "",
                      f"- 关联测试：{', '.join(row['tests']) or '待查'}",
                      f"- CK：{', '.join(row['ck']) or '待查'}",
                      f"- Spec 候选：{', '.join(row['spec_refs']) or '待查'}",
                      f"- RTL 候选：{', '.join(row['rtl_refs']) or '待查'}",
                      f"- ROOT 候选：{', '.join(row['root_refs']) or '待查'}",
                      "- 待核实：测试正确性、规格预期、重跑结果、波形有效窗口和 RTL 因果链", ""])
    return {"schema": "bug_review_inventory.v2", "name": name, "dut": dut,
            "source_workspace": str(source), "summary_path": str(summary) if summary.is_file() else "",
            "analysis_path": str(analysis) if analysis.is_file() else "",
            "diagnostics": [f"missing {path}" for path in (summary, analysis) if not path.is_file()],
            "bugs": bugs}, "\n".join(lines)


def prepare(workspace, kind="analysis", **options):
    """Prepare report sources and test runtime files without copying whole inputs."""
    if kind != "analysis":
        raise ValueError("Bug Review supports analysis only")
    root = Path(workspace).resolve()
    source_runs = [(safe_name(label), Path(path).resolve()) for label, path in options.get("runs", [])]
    if not source_runs or len({label for label, _ in source_runs}) != len(source_runs):
        raise ValueError("provide at least one uniquely labeled workspace")
    for label, source in source_runs:
        if (source.name != label or not label.startswith("workspace_") or not source.is_dir()
                or not (source / "unity_test/tests").is_dir()):
            raise ValueError(f"expected a UnityTest inputs/workspace_* directory: {source}")
        if root == source or root.is_relative_to(source) or source.is_relative_to(root):
            raise ValueError("output root and input workspaces must be separate")

    config_path = root / "review_job.json"
    frozen_sources = [[label, str(path)] for label, path in source_runs]
    if config_path.exists():
        existing = read_object(config_path)
        if (existing.get("schema") != "bug_review_job.v4"
                or existing.get("source_runs") != frozen_sources):
            raise ValueError("output root has an older or different Bug Review preparation; select a new output root")
        for label, _ in source_runs:
            if not (root / "results" / "tests" / label / "unity_test/tests").is_dir():
                raise ValueError(f"prepared test cases are missing: results/tests/{label}")
        return root

    test_runs = []
    for label, source in source_runs:
        destination = root / "results" / "tests" / label
        if destination.exists():
            raise ValueError(f"test runtime copy already exists without review_job.json: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        (destination / "unity_test").mkdir(parents=True)
        shutil.copytree(source / "unity_test" / "tests", destination / "unity_test" / "tests",
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "toffee_tmp_*"))
        pytest_config = source / "unity_test" / ".pytest.ini"
        if pytest_config.is_file():
            shutil.copy2(pytest_config, destination / "unity_test" / ".pytest.ini")
        dut = source.name.removeprefix("workspace_")
        runtime_package = source / dut
        if runtime_package.is_dir():
            shutil.copytree(runtime_package, destination / "unity_test" / "tests" / dut,
                            ignore=shutil.ignore_patterns(
                "__pycache__", ".pytest_cache", "toffee_tmp_*"))
        inputs = root / "results" / "inputs" / label
        text_suffixes = {".md", ".v", ".vh", ".sv", ".svh", ".vhd", ".vhdl"}
        ignored_parts = {".git", ".ucagent", "__pycache__", ".pytest_cache", ".venv", "venv",
                         "node_modules", "build", "dist", "output", "results", "coverage",
                         "Guide_Doc", "uc_test_report"}
        for path in source.rglob("*"):
            if (not path.is_file() or path.is_symlink()
                    or any(part in ignored_parts or part.startswith("toffee_tmp_") for part in path.relative_to(source).parts)):
                continue
            relative = path.relative_to(source)
            if path.suffix.lower() not in text_suffixes and not (
                    relative.parts[:2] == ("unity_test", "line_map") and path.suffix.lower() == ".txt"):
                continue
            target = inputs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        test_runs.append([label, str(destination.resolve())])

    config = {"schema": "bug_review_job.v4", "kind": kind, "stages": list(ANALYSIS),
              "source_runs": frozen_sources, "test_runs": test_runs,
              "output_dir": "results", "batch_size": int(options.get("batch_size", 1)),
              "timeout": int(options.get("timeout", 300))}
    if config["batch_size"] < 1 or config["timeout"] < 1:
        raise ValueError("batch_size and timeout must be positive")
    atomic_write_json(config_path, config)
    return root


class Workflow:
    """Load prepared test inputs and validate updates to the canonical JSON."""

    def __init__(self, workspace):
        """Load the V4 job configuration from the agent workspace."""
        self.root = Path(workspace).resolve()
        self.config = read_object(self.root / "review_job.json")
        if self.config.get("schema") != "bug_review_job.v4" or self.config.get("stages") != list(ANALYSIS):
            raise ValueError("workspace requires a fresh V4 analysis preparation; select a new output root")
        self.out = self.root / self.config["output_dir"]
        self.waveinfo = WaveInfo(workspace=str(self.root), test_dir=str(self.out / "tests"), dut_name="BugReview")

    def _workspaces(self):
        """Return frozen workspace names and original read-only source paths."""
        return [(name, Path(path)) for name, path in self.config["source_runs"]]

    def _review_path(self, name):
        """Return the sole canonical review artifact for one input workspace."""
        return self.out / "workspaces" / name / "bug_review.json"

    def status(self):
        """Return progress only for stages whose artifacts pass their current checks."""
        completed = []
        for stage in ANALYSIS:
            try:
                valid, _ = self.check(stage)
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError):
                valid = False
            if not valid:
                break
            completed.append(stage)
        current = next((stage for stage in ANALYSIS if stage not in completed), "")
        return {"kind": "analysis", "current_stage": current,
                "completed": completed, "complete": not current}

    def check(self, stage):
        """Validate current-stage fields and links in each canonical review JSON."""
        names = [name for name, _ in self._workspaces()]
        required = [self._review_path(name) for name in names]
        if stage == "publish":
            required.append(self.out / "index.html")
        missing = [str(path.relative_to(self.root)) for path in required if not path.is_file()]
        if missing:
            return False, {"error_code": "STAGE_OUTPUT_MISSING", "error": f"missing outputs: {missing}",
                           "next_action": "Create or update bug_review.json with the current Skill, then run Check again."}
        for name, source in self._workspaces():
            target = self.out / "workspaces" / name
            document = read_object(self._review_path(name))
            bugs = document["suspected_bugs"]
            bug_ids = [bug["bug_id"] for bug in bugs]
            if (document.get("schema") != "bug_review.v3"
                    or document.get("workspace", {}).get("name") != name
                    or document.get("workspace", {}).get("source_path") != str(source)
                    or len(bug_ids) != len(set(bug_ids))):
                raise ValueError(f"{name}/bug_review.json has an invalid schema or workspace identity")
            if document.get("stage_status", {}).get(stage) != "complete":
                raise ValueError(f"{name}/bug_review.json does not mark {stage} complete after its work")
            if stage == "inventory":
                original, _ = _inventory(source, name)
                expected_ids = {bug["bug_id"] for bug in original["bugs"]}
                reported_ids = {bug["bug_id"] for bug in bugs if bug.get("origin") == "reported"}
                if not expected_ids.issubset(reported_ids):
                    raise ValueError(f"{name}/bug_review.json dropped an original Bug declaration")
                for bug in bugs:
                    if not isinstance(bug.get("bug_summary"), dict) or not isinstance(bug.get("evidence"), dict):
                        raise ValueError(f"{name}/{bug['bug_id']} lacks its summary or nested evidence structure")
            elif stage == "replay":
                cases = document["cases"]
                selected = [case for case in cases.values() if case.get("replay", {}).get("status") in
                            {"reproduced", "passed", "not_collected", "execution_error"}]
                if cases and not selected:
                    raise ValueError(f"{name}/bug_review.json has no selected case replay results")
                for case in selected:
                    replay = case["replay"]
                    if replay.get("invocation_success") is not True or replay.get("test_count", 0) < 1:
                        raise ValueError(f"{name}/{case.get('nodeid')} has no successful RunTestCases report")
                    relative_target = str(case["replay_target"]).split("::", 1)[0]
                    test_root = (self.out / "tests").resolve()
                    test_file = (test_root / relative_target).resolve()
                    if not test_file.is_relative_to(test_root) or not test_file.is_file():
                        raise ValueError(f"{name}/{case.get('nodeid')} has no prepared test file at replay_target")
            elif stage == "waveform":
                for case in document["cases"].values():
                    if (case.get("replay", {}).get("status") != "reproduced"
                            or case.get("test_review", {}).get("classification") != "suspected_dut_bug"):
                        continue
                    wave = case.get("waveform", {})
                    conclusion = wave.get("conclusion")
                    if conclusion not in {"dut_bug", "not_dut_bug", "inconclusive"}:
                        raise ValueError(f"{name}/{case.get('nodeid')} has an invalid WaveInfo conclusion")
                    if conclusion == "inconclusive" and not wave.get("result"):
                        raise ValueError(f"{name}/{case.get('nodeid')} lacks the inconclusive WaveInfo result")
                    if conclusion != "inconclusive" and not wave.get("receipt_id"):
                        raise ValueError(f"{name}/{case.get('nodeid')} lacks a signed WaveInfo receipt for its conclusion")
                for case in document["cases"].values():
                    wave = case.get("waveform", {})
                    receipt_id = wave.get("receipt_id")
                    if not receipt_id:
                        continue
                    receipt = self.waveinfo.get_analysis_receipt(receipt_id)
                    if receipt is None:
                        raise ValueError(f"{name}/{case.get('nodeid')} references no signed WaveInfo receipt")
                    if receipt.get("arguments", {}).get("test_case_name") != case.get("waveform_test_case_name"):
                        raise ValueError(f"{name}/{case.get('nodeid')} WaveInfo receipt is for another test case")
                    if wave.get("conclusion") == "dut_bug":
                        verified = self.waveinfo.get_bug_document_evidence(receipt_id)
                        if verified.get("success") is not True:
                            raise ValueError(f"{name}/{case.get('nodeid')} WaveInfo receipt lacks complete signal groups/viewer")
            elif stage == "correlate":
                roots = {root["root_id"]: root for root in document["root_causes"]}
                if len(roots) != len(document["root_causes"]):
                    raise ValueError(f"{name}/bug_review.json has duplicate root cause IDs")
                root_signatures = [tuple(root.get(field) for field in
                                         ("rtl_ref", "first_error", "causal_chain"))
                                   for root in roots.values()]
                if len(root_signatures) != len(set(root_signatures)):
                    raise ValueError(f"{name}/bug_review.json splits one root cause across multiple groups")
                members = [bug_id for root in roots.values() for bug_id in root["bug_ids"]]
                if len(members) != len(set(members)):
                    raise ValueError(f"{name}/bug_review.json assigns a Bug to multiple root causes")
                by_id = {bug["bug_id"]: bug for bug in bugs}
                root_members = {bug_id: root_id for root_id, root in roots.items() for bug_id in root["bug_ids"]}
                original, _ = _inventory(source, name)
                reported_nodes = {_workspace_node(node) for bug in original["bugs"] for node in bug["tests"]}
                for case in document["cases"].values():
                    case_id = _workspace_node(case["nodeid"])
                    if any(bug_id not in by_id for bug_id in case.get("bug_ids", [])):
                        raise ValueError(f"{name}/{case_id} references an unknown Bug")
                    if (case.get("replay", {}).get("status") == "reproduced"
                            and case_id not in reported_nodes
                            and not any(by_id[bug_id].get("origin") == "discovered"
                                        for bug_id in case.get("bug_ids", []))):
                        raise ValueError(f"{name}/bug_review.json omits a discovered Bug for {case_id}")
                for bug in bugs:
                    decision = bug["decision"]
                    verdict, confidence = decision["verdict"], decision["review_confidence"]
                    if verdict not in {"confirmed", "refuted", "inconclusive"}:
                        raise ValueError(f"{name}/{bug['bug_id']} has an invalid verdict")
                    if verdict == "refuted" and (type(confidence) not in {int, float} or confidence != 0) or verdict == "inconclusive" and confidence is not None:
                        raise ValueError(f"{name}/{bug['bug_id']} has an invalid review confidence")
                    if verdict == "confirmed" and (type(confidence) not in {int, float} or not 0 < confidence <= 1):
                        raise ValueError(f"{name}/{bug['bug_id']} has an invalid confirmed confidence")
                    if verdict == "confirmed" and decision.get("root_id") not in roots:
                        raise ValueError(f"{name}/{bug['bug_id']} has no root cause group")
                    if verdict == "confirmed" and root_members.get(bug["bug_id"]) != decision.get("root_id"):
                        raise ValueError(f"{name}/{bug['bug_id']} root membership is not bidirectional")
                    if verdict == "confirmed":
                        if not all(decision.get(field) for field in ("spec_ref", "rtl_ref", "first_error", "causal_chain")):
                            raise ValueError(f"{name}/{bug['bug_id']} lacks confirmed Spec/RTL causal evidence")
                        for field in ("spec_ref", "rtl_ref"):
                            match = re.fullmatch(r"(.+):(\d+)(?:-(\d+))?", decision[field])
                            source_relative = Path(match.group(1)) if match else Path("..")
                            source_root = (self.out / "inputs" / name).resolve()
                            source_file = (source_root / source_relative).resolve()
                            if (not match or source_relative.is_absolute() or ".." in source_relative.parts
                                    or not source_file.is_relative_to(source_root) or not source_file.is_file()):
                                raise ValueError(f"{name}/{bug['bug_id']} has a missing or non-local {field}")
                            with source_file.open(encoding="utf-8", errors="replace") as handle:
                                line_total = sum(1 for _ in handle)
                            start_line = int(match.group(2))
                            end_line = int(match.group(3) or match.group(2))
                            if start_line < 1 or end_line < start_line or end_line > line_total:
                                raise ValueError(f"{name}/{bug['bug_id']} has an invalid {field} line range")
                        root = roots[decision["root_id"]]
                        if any(root.get(field) != decision.get(field)
                               for field in ("rtl_ref", "first_error", "causal_chain")):
                            raise ValueError(f"{name}/{bug['bug_id']} differs from its shared root-cause evidence")
                        associated = [document["cases"].get(case_id)
                                      for case_id in bug.get("evidence", {}).get("case_ids", [])]
                        if not any(case and bug["bug_id"] in case.get("bug_ids", [])
                                   and case.get("replay", {}).get("status") == "reproduced"
                                   and case.get("test_review", {}).get("correctness_confirmed") is True
                                   and case.get("waveform", {}).get("conclusion") == "dut_bug"
                                   and case.get("waveform", {}).get("receipt_id")
                                   for case in associated):
                            raise ValueError(f"{name}/{bug['bug_id']} lacks a linked correct replay and signed DUT Bug waveform")
                    if verdict != "confirmed" and decision.get("root_id") is not None:
                        raise ValueError(f"{name}/{bug['bug_id']} has a root cause despite not being confirmed")
                if any(bug_id not in by_id for bug_id in members):
                    raise ValueError(f"{name}/bug_review.json root cause names an unknown Bug")
                if any(by_id[bug_id]["decision"]["verdict"] != "confirmed" for bug_id in members):
                    raise ValueError(f"{name}/bug_review.json root cause includes a non-confirmed Bug")
                if any(not all(root.get(field) for field in ("rtl_ref", "first_error", "causal_chain"))
                       for root in roots.values()):
                    raise ValueError(f"{name}/bug_review.json has an incomplete root-cause group")
            elif stage == "publish":
                workspace_index = (target / "index.html").read_text(encoding="utf-8")
                for index, bug in enumerate(bugs, 1):
                    filename = f"bug_{index:04d}.html"
                    if not (target / filename).is_file() or filename not in workspace_index:
                        raise ValueError(f"{name}/index.html is missing detail page for {bug['bug_id']}")
        if stage == "publish":
            index_text = (self.out / "index.html").read_text(encoding="utf-8")
            if any(f"workspaces/{name}/index.html" not in index_text for name in names):
                raise ValueError("index.html omits a selected workspace")
        return True, {"stage": stage, "validated_workspaces": names}

def main(argv=None):
    """Prepare, inspect or launch one five-stage analysis workspace."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analysis = sub.add_parser("prepare-analysis")
    analysis.add_argument("--input-root", default=str(PLUGIN_ROOT / "inputs"))
    analysis.add_argument("--output-root", default=str(PLUGIN_ROOT / "output"))
    analysis.add_argument("--run", action="append", default=[])
    analysis.add_argument("--batch-size", type=int, default=1)
    analysis.add_argument("--timeout", type=int, default=300)
    launch = sub.add_parser("launch")
    launch.add_argument("--workspace", default=str(PLUGIN_ROOT / "output"))
    launch.add_argument("--python", default=sys.executable)
    launch.add_argument("--ucagent-root")
    status = sub.add_parser("status")
    status.add_argument("--workspace", default=str(PLUGIN_ROOT / "output"))
    args, extra = parser.parse_known_args(argv)
    if args.command != "launch" and extra:
        parser.error("unexpected arguments: " + " ".join(extra))
    if args.command == "prepare-analysis":
        values = args.run or [f"{Path(path).name}={path}" for _, path in discover_input_workspaces(args.input_root)]
        runs = resolve_run_specs(values)
        root = prepare(args.output_root, runs=runs, batch_size=args.batch_size, timeout=args.timeout)
        print(json.dumps({"workspace": str(root), "next": "launch --workspace " + str(root)}))
    elif args.command == "status":
        print(json.dumps(Workflow(args.workspace).status(), ensure_ascii=False, indent=2))
    else:
        wf = Workflow(args.workspace)
        if args.ucagent_root:
            entry = Path(args.ucagent_root).resolve() / "ucagent.py"
            if not entry.is_file():
                raise ValueError(f"UCAgent entry missing: {entry}")
            command = [args.python, str(entry)]
        else:
            command = [args.python, "-m", "ucagent.cli"]
        command.extend([str(wf.root), "BugReview", "--plugin", str(PLUGIN_ROOT),
                        "--plugin-workflow", "bug_review:analysis", "--output", "results"])
        command.extend(extra[1:] if extra[:1] == ["--"] else extra)
        raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
