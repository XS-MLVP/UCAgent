"""Run the six-stage Bug Review analysis against immutable DUT inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.parse import unquote

from ucagent.tools.waveform import WaveInfo

from bug_review.analysis_core.task_manifest import atomic_write_json
from .review_claims import report_claim_blocks
from .inputs import discover_input_workspaces, resolve_run_specs
from .json_io import read_object


ANALYSIS = ("full_replay", "case_triage", "dut_evidence", "report_reconcile",
            "root_correlation", "publish")
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
    value = re.sub(r"^results/tests/", "", value)
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
    blocks = report_claim_blocks(source, name)
    analysis_lines = analysis.read_text(encoding="utf-8", errors="replace").splitlines() if analysis.is_file() else []
    bugs = []
    for row in table:
        aggregate = []
        for start, end in row["analysis_ranges"]:
            for line in analysis_lines[max(0, start - 1):end]:
                aggregate.extend(re.findall(r"<TC-([^>]+)>", line))
        bugs.append({**row, "origin": "reported", "claims": [], "tests": [],
                     "aggregate_tests": sorted(set(aggregate)),
                     "aggregate_refs": [f"unity_test/{analysis.name}:{start}-{end}"
                                        for start, end in row["analysis_ranges"]],
                     "root_refs": []})
    for block in blocks:
        identity = re.sub(r"-\d+$", "", block["source_label"].removeprefix("BG-"))
        if any(item["bug_id"] == identity for item in bugs):
            continue
        confidence = re.search(r"-(\d+)$", block["source_label"])
        reported_confidence = (int(confidence.group(1)) / 100 if confidence
                               and int(confidence.group(1)) <= 100 else None)
        bugs.append({"bug_id": identity, "origin": "reported", "summary": "",
                     "summary_item_present": False, "severity": "",
                     "reported_confidence": reported_confidence, "ck": [], "rtl_refs": [],
                     "source": {"path": str(analysis), "line": int(block["ref"].split(":")[-1].split("-")[0])},
                     "analysis_ranges": [], "claims": [], "tests": [],
                     "aggregate_tests": [], "aggregate_refs": [], "root_refs": []})
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
    """Prepare one module in a fresh, private UCAgent execution workspace."""
    if kind != "analysis":
        raise ValueError("Bug Review supports analysis only")
    root = Path(workspace).resolve()
    source_runs = [(safe_name(label), Path(path).resolve()) for label, path in options.get("runs", [])]
    if len(source_runs) != 1:
        raise ValueError("prepare exactly one workspace per execution")
    for label, source in source_runs:
        if (source.name != label or not label.startswith("workspace_") or not source.is_dir()
                or not (source / "unity_test/tests").is_dir()):
            raise ValueError(f"expected a UnityTest inputs/workspace_* directory: {source}")
        if root == source or root.is_relative_to(source) or source.is_relative_to(root):
            raise ValueError("output root and input workspaces must be separate")

    config_path = root / "review_job.json"
    frozen_source = [source_runs[0][0], str(source_runs[0][1])]
    if config_path.exists():
        existing = read_object(config_path)
        if (existing.get("schema") != "bug_review_job.v7"
                or existing.get("source_run") != frozen_source):
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
        text_suffixes = {".md", ".py", ".v", ".vh", ".sv", ".svh", ".vhd", ".vhdl", ".f"}
        ignored_parts = {".git", ".ucagent", "__pycache__", ".pytest_cache", ".venv", "venv",
                         "node_modules", "build", "dist", "output", "results", "coverage",
                         "Guide_Doc", "uc_test_report"}
        for path in source.rglob("*"):
            if (not path.is_file() or path.is_symlink()
                    or any(part in ignored_parts or part.startswith("toffee_tmp_") for part in path.relative_to(source).parts)):
                continue
            relative = path.relative_to(source)
            if path.suffix.lower() not in text_suffixes and path.name.lower() != "filelist.txt" and not (
                    relative.parts[:2] == ("unity_test", "line_map") and path.suffix.lower() == ".txt"):
                continue
            target = inputs / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        test_runs.append([label, str(destination.resolve())])

    config = {"schema": "bug_review_job.v7", "kind": kind, "stages": list(ANALYSIS),
              "source_run": frozen_source, "test_run": test_runs[0],
              "prepared_at": datetime.now(timezone.utc).isoformat(),
              "output_dir": "results", "batch_size": int(options.get("batch_size", 1)),
              "timeout": int(options.get("timeout", 300))}
    if config["batch_size"] < 1 or config["timeout"] < 1:
        raise ValueError("batch_size and timeout must be positive")
    atomic_write_json(config_path, config)
    return root


class Workflow:
    """Validate one module's current indexed stage artifacts."""

    def __init__(self, workspace):
        """Load the private run configuration and signed waveform scope."""
        self.root = Path(workspace).resolve()
        self.config = read_object(self.root / "review_job.json")
        if self.config.get("schema") != "bug_review_job.v7" or self.config.get("stages") != list(ANALYSIS):
            raise ValueError("workspace requires a fresh V7 analysis preparation")
        self.out = self.root / self.config["output_dir"]
        self.waveinfo = WaveInfo(workspace=str(self.root), test_dir=str(self.out / "tests"), dut_name="BugReview")

    def status(self):
        """Return the first stage whose indexed artifacts do not pass Check."""
        completed = []
        for stage in ANALYSIS:
            try:
                valid, _ = self.check(stage)
            except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError):
                valid = False
            if not valid:
                break
            if stage == "publish":
                from .review_store import load_record

                index = load_record(self.out, "review_index.json", "index")
                if index.stage_status.get("publish") != "complete":
                    break
            completed.append(stage)
        current = next((stage for stage in ANALYSIS if stage not in completed), "")
        return {"kind": "analysis", "current_stage": current,
                "completed": completed, "complete": not current}

    def check(self, stage):
        """Validate every artifact required through the requested V3 stage."""
        from .review_store import load_record, source_lines, within_output
        from .review_validation import ReviewIssues, case_issues, review_incomplete, validate_correlation

        if stage not in ANALYSIS:
            raise ValueError(f"unknown Bug Review stage: {stage}")
        name, source_text = self.config["source_run"]
        source = Path(source_text)
        index_path = self.out / "review_index.json"
        if not index_path.is_file():
            raise ValueError("results/review_index.json is missing; create full replay records")
        index = load_record(self.out, "review_index.json", "index")
        if (index.workspace.get("name") != name
                or index.workspace.get("source_path") != str(source)
                or index.workspace.get("execution_workspace") != str(self.root)
                or index.workspace.get("started_at") != self.config.get("prepared_at")):
            raise ValueError("review_index.json workspace identity differs from review_job.json")
        required_stages = ANALYSIS[:ANALYSIS.index(stage) + (stage != "publish")]
        for required in required_stages:
            if index.stage_status.get(required) != "complete":
                raise ValueError(f"stage_status.{required} must be complete")
        if len(index.bug_order) != len(set(index.bug_order)) or set(index.bug_order) != set(index.bugs):
            raise ValueError("review_index.json bug_order and bugs identities differ")
        original, _ = _inventory(source, name)
        expected_ids = {bug["bug_id"] for bug in original["bugs"]}
        if not expected_ids.issubset(index.bugs):
            raise ValueError(f"original Bug identities missing: {sorted(expected_ids - set(index.bugs))[:10]}")
        source_root = self.out / "inputs" / name
        original_issues = []
        for reported in original["bugs"]:
            bug_id = reported["bug_id"]
            entry = index.bugs[bug_id]
            location = reported["source"]
            path = Path(location["path"])
            if path.is_absolute():
                path = path.resolve().relative_to(source)
            start = location.get("line", location.get("line_start"))
            end = location.get("line_end", start)
            summary_ref = f"{path.as_posix()}:{start}" + (f"-{end}" if end != start else "")
            expected_fields = {
                "origin": "reported", "summary_ref": summary_ref,
                "reported_confidence": reported["reported_confidence"],
                "check_points": set(reported["ck"]),
                "aggregate_case_ids": {_workspace_node(node) for node in reported["aggregate_tests"]},
                "aggregate_refs": set(reported["aggregate_refs"]),
            }
            for field, expected in expected_fields.items():
                actual = getattr(entry, field)
                actual_set = set(actual) if isinstance(expected, set) else actual
                invalid = (not expected.issubset(actual_set) if field == "check_points"
                           else actual_set != expected)
                if invalid:
                    original_issues.append({"bug_id": bug_id, "field": field,
                                            "expected": sorted(expected) if isinstance(expected, set) else expected,
                                            "actual": sorted(actual_set) if isinstance(expected, set) else actual,
                                            "missing": sorted(expected - actual_set) if isinstance(expected, set) else [],
                                            "extra": sorted(actual_set - expected) if isinstance(expected, set) else [],
                                            "next_action": "Restore the original summary fact; reviewed associations belong in the attribution draft"})
        if original_issues:
            raise ReviewIssues(original_issues)
        if ANALYSIS.index(stage) >= ANALYSIS.index("report_reconcile"):
            from .review_attribution import claim_mapping_issues
            from .review_store import AttributionDraft

            if not index.claim_mapping_path:
                raise ValueError("claim_mapping_path is missing; commit the reviewed attribution draft")
            mapping = AttributionDraft.model_validate(read_object(within_output(self.out, index.claim_mapping_path)))
            mapping_issues = claim_mapping_issues(source, name, index, mapping.bugs)
            for item in mapping.bugs:
                if item.bug_id not in index.bugs:
                    continue
                entry = index.bugs[item.bug_id]
                for field, expected in (("analysis_refs", item.claim_refs), ("case_ids", item.case_ids),
                                        ("bg_ids", item.bg_ids), ("fg_ids", item.fg_ids),
                                        ("fc_ids", item.fc_ids), ("ck_ids", item.ck_ids),
                                        ("source_labels", item.source_labels),
                                        ("attribution_rationale", item.rationale),
                                        ("spec_candidates", item.spec_candidates),
                                        ("rtl_candidates", item.rtl_candidates)):
                    if getattr(entry, field) != expected:
                        mapping_issues.append({"bug_id": item.bug_id, "field": field,
                                               "expected": expected, "actual": getattr(entry, field),
                                               "next_action": "Restore the committed claim mapping"})
            if mapping_issues:
                raise ReviewIssues(mapping_issues)
        for bug_id, entry in index.bugs.items():
            if any(case_id not in index.cases for case_id in entry.case_ids):
                raise ValueError(f"{bug_id} refers to an unindexed case")
            for ref in [entry.summary_ref, *entry.analysis_refs]:
                if ref:
                    source_lines(source_root, ref, 1)
        coverage = load_record(self.out, index.coverage_path, "coverage")
        if not {"line", "functional"}.issubset(coverage.metrics):
            raise ValueError("coverage.json needs line and functional metrics")
        for metric in coverage.metrics.values():
            if metric.status == "unavailable" and not metric.reason.strip():
                raise ValueError("unavailable coverage needs a reason")
            if metric.status == "available":
                if not metric.source_ref or not metric.basis or metric.run_scope == "unknown":
                    raise ValueError("available coverage needs source_ref, basis and run_scope")
                source_lines(source_root, metric.source_ref, 1)
        manifest = load_record(self.out, index.manifest_path, "manifest")
        if not manifest.collected and not manifest.collection_errors:
            raise ValueError("test_manifest.json has no collected tests or collection error")
        if len(set(manifest.collected)) != len(manifest.collected):
            raise ValueError("test_manifest.json contains duplicate node IDs")
        if manifest.collection_exit_code != 0 and not manifest.collection_errors:
            raise ValueError("collection failure needs recorded diagnostics")
        if not set(manifest.collected).issubset(index.cases):
            raise ValueError("review_index.json omits collected test nodes")
        if len({entry.record_path for entry in index.cases.values()}) != len(index.cases):
            raise ValueError("multiple cases share one record path")
        summary = load_record(self.out, index.replay_summary_path, "replay_summary")
        if summary.baseline_id != manifest.baseline_id:
            raise ValueError("replay_summary.json baseline differs from test_manifest.json")
        if set(summary.outcomes) != set(manifest.collected):
            missing = sorted(set(manifest.collected) - set(summary.outcomes))[:10]
            extra = sorted(set(summary.outcomes) - set(manifest.collected))[:10]
            raise ValueError(f"replay_summary.json does not account for collected nodes: missing={missing}, extra={extra}")
        if manifest.collected and (not summary.commands or not summary.report_ref):
            raise ValueError("replay_summary.json needs baseline commands and saved report references")
        if summary.report_ref and not within_output(self.out, summary.report_ref).is_file():
            raise ValueError("replay_summary.json report_ref does not locate a saved report")
        from .review_replay import report_outcomes
        observed = {}
        for position, reference in enumerate(summary.batch_refs):
            batch = read_object(within_output(self.out, reference))
            context = batch.get("context", {})
            if context.get("source") != "RunTestCases" or context.get("stage_name") != "full_replay":
                raise ValueError(f"{reference} is not a full_replay RunTestCases report")
            if position >= len(summary.commands) or summary.commands[position] != [
                    "RunTestCases", str(context.get("pytest_ex_args", ""))]:
                raise ValueError(f"{reference} command differs from the saved RunTestCases context")
            for case_id, finding in report_outcomes(batch["report"], set(manifest.collected)).items():
                if case_id in observed:
                    raise ValueError(f"{case_id} appears in more than one baseline batch")
                observed[case_id] = finding
        if manifest.collected and (not summary.batch_refs or summary.report_ref not in summary.batch_refs
                                   or len(summary.commands) != len(summary.batch_refs)):
            raise ValueError("replay_summary.json needs saved baseline batch references")
        cases = {}
        issues = []
        for case_id, entry in index.cases.items():
            case = load_record(self.out, entry.record_path, "case")
            if case.case_id != case_id or set(case.bug_ids) != {
                    bug_id for bug_id, bug in index.bugs.items() if case_id in bug.case_ids}:
                raise ValueError(f"{case_id} case identity or Bug links differ from index")
            cases[case_id] = case
            target = (self.out / "tests" / entry.replay_target.split("::", 1)[0]).resolve()
            if not target.is_relative_to((self.out / "tests").resolve()):
                raise ValueError(f"{case_id} replay_target escapes the prepared test root")
            if case_id in manifest.collected and not target.is_file():
                raise ValueError(f"{case_id} collected replay_target file is missing")
            if case_id not in manifest.collected and not case.replay.not_run_reason.strip():
                raise ValueError(f"{case_id} is report-only and needs a not_run reason")
            if case_id in manifest.collected:
                if case.replay.status != summary.outcomes[case_id]:
                    raise ValueError(f"{case_id} replay status differs from baseline summary")
                finding = observed.get(case_id)
                if case.replay.status != "not_run" and (finding is None or finding[0] != case.replay.status):
                    raise ValueError(f"{case_id} replay status has no matching RunTestCases report outcome")
                if case.replay.status == "not_run" and finding is not None:
                    raise ValueError(f"{case_id} was reported by RunTestCases but marked not_run")
                if case.replay.status != "not_run" and case.replay.baseline_id != manifest.baseline_id:
                    raise ValueError(f"{case_id} replay baseline_id differs from manifest")
                if finding and finding[1] and entry.waveform_test_case_name != finding[1]:
                    raise ValueError(f"{case_id} waveform identity differs from saved report")
            elif case.replay.status != "not_run":
                raise ValueError(f"{case_id} was absent from collection but marked executed")
            issues.extend(case_issues(index, case, self.waveinfo,
                                      require_replay=case_id in manifest.collected,
                                      require_triage=ANALYSIS.index(stage) >= 1,
                                      require_wave=ANALYSIS.index(stage) >= 2,
                                      source_root=source_root))
        if issues:
            raise ReviewIssues(issues)
        if ANALYSIS.index(stage) >= 1:
            environment = load_record(self.out, index.environment_path, "environment")
            if any(not getattr(environment, field).strip() for field in (
                    "collection_review", "execution_review", "fixture_reset_review",
                    "driver_sampling_review", "reference_model_review",
                    "seed_reproducibility_review")):
                raise ValueError("environment_review.json needs all six quality reviews or explicit gaps")
            for position, finding in enumerate(environment.findings):
                if not finding.observation.strip() or not finding.impact.strip():
                    raise ValueError(f"environment finding {position} needs observation and impact")
                if any(case_id not in index.cases for case_id in finding.case_ids):
                    raise ValueError(f"environment finding {position} refers to an unindexed case")
                if finding.source_ref:
                    source_lines(source_root, finding.source_ref, 1)
            for case_id, case in cases.items():
                if case.replay.status in {"failed", "error", "xpassed"}:
                    if case.failure_analysis.category == "unreviewed":
                        raise ValueError(f"{case_id} failed without independent failure_analysis")
        if ANALYSIS.index(stage) >= 3:
            reconcile = load_record(self.out, index.reconciliation_path, "reconciliation")
            if set(reconcile.original_bug_ids) != expected_ids:
                raise ValueError("report_reconciliation.json does not list all original Bugs")
            discovered = {bug_id for bug_id, entry in index.bugs.items() if entry.origin == "discovered"}
            if set(reconcile.discovered_bug_ids) != discovered:
                raise ValueError("report_reconciliation.json discovered Bugs differ from index")
            uncovered = {case_id for case_id in manifest.collected
                         if cases[case_id].replay.status in {"failed", "error", "xpassed"}
                         and not cases[case_id].bug_ids}
            if set(reconcile.unreported_failed_cases) != uncovered:
                raise ValueError("report_reconciliation.json must list all failures without a Bug association")
            reported_now_passed = {case_id for bug_id in expected_ids
                                   for case_id in index.bugs[bug_id].case_ids
                                   if case_id in cases and cases[case_id].replay.status == "passed"}
            previous_failures = set(reconcile.previously_failed_now_passed)
            if (not previous_failures.issubset(reported_now_passed)
                    or set(reconcile.original_failure_refs) != previous_failures):
                raise ValueError("previously_failed_now_passed needs a prior failure ref for each currently passing case")
            for reference in reconcile.original_failure_refs.values():
                source_lines(source_root, reference, 1)
            if not reconcile.statistics_review.strip():
                raise ValueError("report_reconciliation.json needs the source/current statistics comparison")
            for bug_id in discovered:
                if not any(cases[case_id].failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                           for case_id in index.bugs[bug_id].case_ids):
                    raise ValueError(f"{bug_id} discovered Bug has no independently suspected DUT case")
            for case_id in manifest.collected:
                case = cases[case_id]
                if (case.replay.status in {"failed", "error", "xpassed"}
                        and case.failure_analysis.category in {"suspected_dut", "confirmed_dut"}
                        and case.waveform.receipt_id and not case.bug_ids):
                    raise ValueError(f"{case_id} has DUT evidence but no reported or discovered Bug")
        if ANALYSIS.index(stage) >= 4:
            if not index.root_path:
                raise ValueError("review_index.json has no active root record")
            revision = Path(index.root_path).parent
            if revision.parts[:1] != ("reviews",) or len(revision.parts) != 2:
                raise ValueError("root record must be under one reviews/<revision> directory")
            roots = load_record(self.out, index.root_path, "roots")
            bugs = {}
            for bug_id, entry in index.bugs.items():
                if not entry.review_path or Path(entry.review_path).parent != revision / "bugs":
                    raise ValueError(f"{bug_id} has no active Bug review in the root revision")
                bugs[bug_id] = load_record(self.out, entry.review_path, "bug")
            validate_correlation(index, cases, bugs, roots, source_root, self.waveinfo)
        if stage == "publish":
            from .reporting import verify_pages
            verify_pages(self.out, index, cases, bugs, roots)
        environment = load_record(self.out, index.environment_path, "environment")
        incomplete = review_incomplete(manifest, cases, environment)
        return True, {"stage": stage, "validated_workspaces": [name],
                      "review_status": "incomplete" if incomplete else "complete"}


def publish_run(workspace, output_root):
    """Promote one checked private report and rebuild the module portal."""
    run = Path(workspace).resolve()
    root = Path(output_root).resolve()
    job = read_object(run / "review_job.json")
    name, _ = job["source_run"]
    module = root / name
    if run.parent != module / "runs":
        raise ValueError(f"execution workspace is outside its module area: {run}")
    if job.get("schema") == "bug_review_job.v7":
        workflow = Workflow(run)
        workflow.check("publish")
        report = workflow.out / "report"
    elif job.get("schema") == "bug_review_job.v6":
        report = recover_legacy_report(run, name)
    else:
        raise ValueError("unsupported completed Bug Review job schema")
    manifest_path = report / "report_manifest.json"
    manifest = read_object(manifest_path)
    if manifest.get("workspace") != name or not (report / "index.html").is_file():
        raise ValueError("verified module report or manifest is missing")
    for filename in manifest.get("pages", []):
        target = (report / filename).resolve()
        if not target.is_relative_to(report.resolve()) or not target.is_file():
            raise ValueError(f"report manifest page is missing: {filename}")
    published = module / "report"
    if published.exists() and not published.is_symlink():
        raise ValueError(f"module report must be a managed link: {published}")
    previous = os.readlink(published) if published.is_symlink() else None
    link = module / f".report-{secrets.token_hex(4)}"
    try:
        link.symlink_to(report.relative_to(module), target_is_directory=True)
        os.replace(link, published)
        portal = rebuild_portal(root)
        if job.get("schema") == "bug_review_job.v7":
            from .review_store import load_record

            index = load_record(workflow.out, "review_index.json", "index")
            if index.stage_status.get("publish") != "complete":
                index.stage_status["publish"] = "complete"
                atomic_write_json(workflow.out / "review_index.json",
                                  index.model_dump(mode="json", by_alias=True))
        return portal
    except Exception as error:
        if previous is not None:
            rollback = module / f".report-{secrets.token_hex(4)}"
            rollback.symlink_to(previous, target_is_directory=True)
            os.replace(rollback, published)
        if isinstance(error, PermissionError):
            raise PermissionError(
                f"Bug Review cannot write output path {error.filename or module}; "
                "choose a writable OUTPUT_ROOT or fix its owner/permissions"
            ) from error
        raise
    finally:
        link.unlink(missing_ok=True)


def recover_legacy_report(run: Path, name: str) -> Path:
    """Republish completed V2.1 HTML without exposing private review records."""
    source = run / "results"
    index = read_object(source / "review_index.json")
    if index.get("workspace", {}).get("name") != name or any(
            index.get("stage_status", {}).get(stage) != "complete"
            for stage in ("inventory", "replay", "waveform", "correlate", "publish")):
        raise ValueError("legacy module review is not complete")
    old_manifest = read_object(source / "report_manifest.json")
    if old_manifest.get("workspace") != name:
        raise ValueError("legacy report manifest identity differs from module")
    report = source / "report"
    report.mkdir(parents=True, exist_ok=True)
    for filename in old_manifest.get("pages", []):
        original = (source / filename).resolve()
        if not original.is_relative_to(source.resolve()) or not original.is_file():
            raise ValueError(f"legacy report page is missing: {filename}")
        content = original.read_text(encoding="utf-8")
        (report / filename).write_text(content, encoding="utf-8")
        for href in re.findall(r"href='([^']+)'", content):
            path = unquote(html.unescape(href))
            if not path.startswith("inputs/"):
                continue
            asset = (source / path).resolve()
            if not asset.is_relative_to(source.resolve()) or not asset.is_file():
                raise ValueError(f"legacy source link is missing: {path}")
            target = report / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset, target)
    manifest = {"schema": "bug_review_report.v2", "workspace": name,
                "review_status": "legacy V2.1", "pages": old_manifest["pages"],
                "bugs": old_manifest.get("bugs", []), "cases": [], "collected": "unavailable"}
    atomic_write_json(report / "report_manifest.json", manifest)
    return report


def rebuild_portal(output_root):
    """Build the top-level index only from published module reports."""
    from .reporting import LABELS

    root = Path(output_root).resolve()
    pages = {}
    for module in sorted(root.glob("workspace_*")):
        report = module / "report"
        manifest_path = report / "report_manifest.json"
        if not (report / "index.html").is_file() or not manifest_path.is_file():
            continue
        manifest = read_object(manifest_path)
        if manifest.get("workspace") != module.name:
            raise ValueError(f"published report identity mismatch: {module.name}")
        if (manifest.get("schema") == "bug_review_report.v3"
                and not isinstance(manifest.get("high_confidence_root_count"), int)):
            raise ValueError(f"published report has no high-confidence root count: {module.name}")
        for filename in manifest.get("pages", []):
            target = (report / filename).resolve()
            if not target.is_relative_to(report.resolve()) or not target.is_file():
                raise ValueError(f"published report has a broken page: {module.name}/{filename}")
        pages[module.name] = manifest
    rows = "".join(
        f"<tr><td><a href='{html.escape(name, quote=True)}/report/index.html'>{html.escape(name)}</a></td>"
        f"<td>{manifest.get('collected', '')}</td><td>{len(manifest.get('cases', []))}</td>"
        f"<td>{html.escape(str(manifest.get('high_confidence_root_count', '—')))}</td><td>complete</td></tr>"
        for name, manifest in pages.items())
    content = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
               "<title>Bug Review</title><h1>Bug Review</h1>"
               "<table><tr><th>Module</th><th>Collected</th><th>Failed</th>"
               f"<th>{html.escape(LABELS['high_confidence'])}</th><th>Review</th></tr>"
               + rows + "</table></html>")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".index-{secrets.token_hex(4)}.html"
    server_copy = root / f".serve-{secrets.token_hex(4)}.py"
    try:
        shutil.copy2(Path(__file__).with_name("report_server.py"), server_copy)
        os.replace(server_copy, root / "serve.py")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, root / "index.html")
    finally:
        server_copy.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
    return root / "index.html"


def main(argv=None):
    """Prepare, run, inspect, or publish selected module workspaces."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare-analysis", "run-analysis"):
        analysis = sub.add_parser(command)
        analysis.add_argument("--input-root", default=str(PLUGIN_ROOT / "inputs"))
        analysis.add_argument("--output-root", default=str(PLUGIN_ROOT / "output"))
        analysis.add_argument("--run", action="append", default=[])
        analysis.add_argument("--batch-size", type=int, default=1)
        analysis.add_argument("--timeout", type=int, default=300)
        if command == "run-analysis":
            analysis.add_argument("--python", default=sys.executable)
            analysis.add_argument("--ucagent-root")
    launch = sub.add_parser("launch")
    launch.add_argument("--workspace", required=True)
    launch.add_argument("--python", default=sys.executable)
    launch.add_argument("--ucagent-root")
    status = sub.add_parser("status")
    status.add_argument("--workspace", required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("--workspace", required=True)
    publish.add_argument("--output-root")
    args, extra = parser.parse_known_args(argv)
    if args.command not in {"launch", "run-analysis"} and extra:
        parser.error("unexpected arguments: " + " ".join(extra))
    if args.command in {"prepare-analysis", "run-analysis"}:
        values = args.run or [f"{Path(path).name}={path}" for _, path in discover_input_workspaces(args.input_root)]
        runs = resolve_run_specs(values)
        output_root = Path(args.output_root).resolve()
        for name, source in runs:
            safe_name(name)
            module = output_root / name
            try:
                module.mkdir(parents=True, exist_ok=True)
            except PermissionError as error:
                raise PermissionError(
                    f"Bug Review cannot create output path {error.filename or module}; "
                    "choose a writable OUTPUT_ROOT or fix its owner/permissions"
                ) from error
            run = module / "runs" / f"run-{secrets.token_hex(8)}"
            print(json.dumps({"module": name, "output_root": str(output_root),
                              "workspace": str(run)}, ensure_ascii=False), flush=True)
            prepare(run, runs=[(name, source)], batch_size=args.batch_size, timeout=args.timeout)
            if args.command == "prepare-analysis":
                continue
            if args.ucagent_root:
                entry = Path(args.ucagent_root).resolve() / "ucagent.py"
                if not entry.is_file():
                    raise ValueError(f"UCAgent entry missing: {entry}")
                command = [args.python, str(entry)]
            else:
                command = [args.python, "-m", "ucagent.cli"]
            command.extend([str(run), "BugReview", "--plugin", str(PLUGIN_ROOT),
                            "--plugin-workflow", "bug_review:analysis", "--output", "results"])
            command.extend(extra[1:] if extra[:1] == ["--"] else extra)
            result = subprocess.call(command)
            if result:
                raise SystemExit(result)
            print(json.dumps({"published_index": str(publish_run(run, output_root))}), flush=True)
    elif args.command == "status":
        print(json.dumps(Workflow(args.workspace).status(), ensure_ascii=False, indent=2))
    elif args.command == "publish":
        run = Path(args.workspace).resolve()
        output_root = Path(args.output_root).resolve() if args.output_root else run.parents[2]
        print(json.dumps({"published_index": str(publish_run(run, output_root))}))
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
        result = subprocess.call(command)
        if result == 0 and wf.root.parent.name == "runs":
            publish_run(wf.root, wf.root.parents[2])
        raise SystemExit(result)


if __name__ == "__main__":
    main()
