"""Per-test replay and evidence reviews owned by the analysis plugin."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

from bug_review.benchmark_workflow.durable_task_store import DurableTaskFiles
from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash
from .tasks import read_object


CLASSIFICATIONS = ("suspected_dut_bug", "spec_misunderstanding", "testbench_issue",
                   "environment_issue", "inconclusive")
CONCLUSIONS = ("dut_bug", "spec_misunderstanding", "testbench_issue",
               "environment_issue", "inconclusive")
NON_DUT = {"spec_misunderstanding", "testbench_issue", "environment_issue"}
FAILED = {"failed", "error", "fail"}
CASE_CANDIDATE_FIELDS = (
    "candidate_id", "property_text", "trigger", "expected", "observed", "root_cause",
    "source_excerpt", "source_excerpt_location", "confidence_percent", "signal_names",
    "waveform_focus_signals", "related_tests", "functional_contexts", "spec_matches",
    "validation_status", "validation_details", "bug_identity", "identity_type", "bg_name",
)


def canonical_node(node):
    # Source line ranges are report annotations, not part of a pytest node ID.
    return re.sub(r"(?<=\.py):\d+(?:-\d+)?(?=::|$)", "", str(node))


def _case_candidate(candidate):
    summary = {
        key: copy.deepcopy(candidate[key])
        for key in CASE_CANDIDATE_FIELDS
        if key in candidate
    }
    regions = list(candidate.get("rtl_regions", []))
    regions.sort(key=lambda row: (
        0 if row.get("evidence_source") in {"declared_dynamic", "static_link"} else 1,
        int(row.get("dependency_depth", 0) or 0),
        str(row.get("path", "")),
        int(row.get("line_start", 0) or 0),
    ))
    summary["rtl_regions"] = copy.deepcopy(regions[:12])
    return summary


def failure_inventory(item):
    """Include unclaimed failures and failed setup/teardown, without name matching."""
    cases = {}
    for graph in item.get("run_graphs", []):
        manifest = graph["manifest"]
        for execution in graph.get("tests", []):
            if (str(execution.get("outcome", "")).lower() not in FAILED
                    and not any(str(p.get("outcome", "")).lower() in FAILED
                                for p in execution.get("phases", []))):
                continue
            node = canonical_node(execution.get("nodeid", ""))
            if not node:
                raise ValueError("failed execution has no node ID")
            identity = {"dut": item["dut"], "model": manifest["model"],
                        "run_key": manifest["run_key"], "nodeid": node}
            key = "case-" + stable_hash(identity)[:24]
            if key in cases:
                cases[key]["original_executions"].append(copy.deepcopy(execution))
                continue
            function = node.split("[", 1)[0]
            candidates = [c for c in graph.get("candidate_bugs", [])
                          if any(canonical_node(n) in {node, function}
                                 for n in c.get("related_tests", []))]
            sources = graph.get("test_sources", {})
            source = sources.get(node) or sources.get(function) or {}
            cases[key] = {**identity, "case_id": key, "original_executions": [copy.deepcopy(execution)],
                          "source": copy.deepcopy(source), "manifest": copy.deepcopy(manifest),
                          "spec_properties": copy.deepcopy(graph.get("spec_properties", [])),
                          "candidates": [_case_candidate(candidate) for candidate in candidates],
                          "reported_candidate_ids": [c["candidate_id"] for c in candidates]}
    return list(cases.values())


def source_evidence(case):
    """Snapshot source text so reviews do not depend on mutable external files."""
    paths = {case["source"].get("source_file", "")}
    paths.update(h.get("path", "") for h in case["source"].get("helper_calls", []))
    manifest = case["manifest"]
    for path in manifest.get("found_files", {}).values():
        if isinstance(path, str) and Path(path).suffix.lower() in {".md", ".py", ".v", ".sv"}:
            paths.add(path)
    tests = Path(manifest["tests_root"]) if manifest.get("tests_root") else None
    if tests and tests.is_dir():
        # Driver, fixture and oracle definitions are essential to classify a Fail.
        paths.update(str(p) for p in tests.glob("*.py") if not p.name.startswith("test_"))
        file_part = case["nodeid"].split("::", 1)[0]
        paths.add(str(tests.parent / file_part))
        if manifest.get("workspace_root"):
            paths.add(str(Path(manifest["workspace_root"]) / file_part))
        paths.add(str(tests.parent / "conftest.py"))
    rows = {}
    for name in sorted(p for p in paths if p):
        path = Path(name)
        if not path.is_absolute() and manifest.get("workspace_root"):
            path = Path(manifest["workspace_root"]) / path
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            rows["source-" + stable_hash(str(path))[:16]] = {
                "path": str(path), "sha256": stable_hash(content), "content": content}
    for candidate in case["candidates"]:
        for region in candidate.get("rtl_regions", []):
            excerpt = str(region.get("excerpt") or "")
            if not excerpt:
                continue
            identity = {
                "path": region.get("path"),
                "line_start": region.get("line_start"),
                "line_end": region.get("line_end"),
                "sha256": region.get("sha256"),
            }
            rows["rtl-region-" + stable_hash(identity)[:16]] = {
                **identity,
                "kind": "rtl_region",
                "content": excerpt,
            }
    return rows


def replay_case(case, directory, config):
    from bug_review.benchmark_workflow.replay_execution import run_benchmark_replay_execution
    from bug_review.benchmark_workflow.replay_harness import build_replay_manifest, build_replay_runner_contract

    directory = Path(directory)
    path = directory / "execution.json"
    if path.exists():
        saved = read_object(path)
        if saved["case_hash"] != stable_hash(case):
            raise ValueError(f"replay input changed: {case['case_id']}")
        return saved
    if config.get("enabled"):
        metadata = {**case["source"], "nodeid": case["nodeid"], "outcome": "failed",
                    "direct_candidate_source": True}
        candidate = {**case, "candidate_id": case["case_id"], "related_tests": [case["nodeid"]],
                     "preferred_test": case["nodeid"], "replay_test_metadata": [metadata]}
        contract = build_replay_runner_contract(build_replay_manifest(case["manifest"], candidate), {})
        contract["input"]["fresh_waveforms"] = True
        contracts_path = directory / "contracts.json"
        atomic_write_json(contracts_path, {"replay_runner_contracts": [contract]})
        profile = read_object(config["runtime_profile"]) if config.get("runtime_profile") else None
        output = run_benchmark_replay_execution(
            contracts=[contract], contracts_path=str(contracts_path), output_dir=str(directory),
            runtime_root=config.get("runtime_root", ""), runtime_profile=profile,
            execution_mode=config.get("execution_mode", "auto"))
        rows = output.get("results", [])
        if len(rows) != 1 or rows[0].get("candidate_id") != case["case_id"]:
            raise ValueError(f"replay result does not match failed test: {case['case_id']}")
        result = rows[0]["result"]
        for row in [result, *result.get("case_results", [])]:
            diagnostics = row.get("diagnostics", {})
            for stream in ("stdout", "stderr"):
                log = diagnostics.get(stream + "_path")
                if log and Path(log).is_file():
                    diagnostics[stream] = Path(log).read_text(encoding="utf-8", errors="replace")
    else:
        result = {"status": "disabled_by_configuration", "reason": "Replay disabled; review original evidence."}
    saved = {"case_hash": stable_hash(case), "result": result}
    atomic_write_json(path, saved)
    return saved


def review_messages(stage, evidence):
    if stage == "replay":
        instruction = (
            "逐个分析失败测试，不预设责任方。独立从规格推导 specification_expected，核对实际输入、"
            "test_expected、dut_actual、driver/fixture/参考模型、复位、握手、采样边沿和响应延迟。"
            "不要修改原始测试，不要把回放失败或未复现直接当成 DUT Bug 或环境问题。"
            "只有测试正确性已确认且实际行为违反规格时才能选 suspected_dut_bug；"
            "证据不足选 inconclusive。所有结论引用 evidence 中的真实字段路径，"
            "路径以 / 分隔，例如 /case/original_executions/0 或 /sources/source-ID。"
        )
        response = {"classification": list(CLASSIFICATIONS), "correctness_confirmed": "boolean",
                    "exact_input": "string", "specification_expected": "string", "test_expected": "string",
                    "dut_actual": "string", "driver_timing_review": "string",
                    "rationale": "string", "evidence_refs": ["/case/original_executions/0"]}
    else:
        instruction = (
            "除非 replay 证据明确显示 setup、teardown 或 collection 环境失败，否则每个失败用例都必须调用 "
            "BugReviewWaveInfo(task_id=当前任务) 查看波形目录和信号，再提交带完整 signal_groups "
            "及时间窗口或时钟对齐的取证请求。根据规格和 driver 核对请求接受、响应有效、"
            "latency、Step 顺序和事务归属；单点 data mismatch 不证明 Bug。"
            "提交 conclusion、波形工具返回的 evidence_id、alignment_evidence、observed_behavior、"
            "source_correlation、rationale 和 evidence_refs。dut_bug 必须有可用签名波形证据；"
            "无法取证时仍须调用工具留下具体失败证据，并选 inconclusive。"
            "发现测试或理解错误时修正分类。不要补写原模型 bug 声明。"
        )
        response = {"conclusion": list(CONCLUSIONS), "evidence_id": "tool-generated ID",
                    "alignment_evidence": "string", "observed_behavior": "string",
                    "source_correlation": "string", "rationale": "string",
                    "evidence_refs": ["/case/original_executions/0"]}
    return [{"role": "system", "content": instruction + "\nJSON response: " + json.dumps(response)},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}]


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_response(stage, evidence, response, task_dir):
    if not isinstance(response, dict) or not _nonempty(response.get("rationale")):
        raise ValueError("response requires a nonempty rationale")
    refs = response.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("evidence_refs must cite supplied evidence paths")
    for ref in refs:
        if not isinstance(ref, str) or not ref.startswith("/") or ref == "/":
            raise ValueError(f"invalid evidence reference: {ref!r}")
        value = evidence
        try:
            for key in ref[1:].split("/"):
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, ValueError, TypeError):
            raise ValueError(f"evidence reference not found: {ref}") from None
        if value is None or value == "" or value == [] or value == {}:
            raise ValueError(f"evidence reference is empty: {ref}")
    if stage == "replay":
        if response.get("classification") not in CLASSIFICATIONS:
            raise ValueError("invalid failure classification")
        if type(response.get("correctness_confirmed")) is not bool:
            raise ValueError("correctness_confirmed must be a boolean")
        for key in ("exact_input", "specification_expected", "test_expected", "dut_actual", "driver_timing_review"):
            if not _nonempty(response.get(key)):
                raise ValueError(f"missing {key}; explicitly explain unavailable evidence")
        if response["classification"] == "suspected_dut_bug" and not response["correctness_confirmed"]:
            raise ValueError("suspected_dut_bug requires confirmed test correctness")
        if response["classification"] == "environment_issue":
            executions = [*evidence["case"].get("original_executions", []),
                          *evidence.get("replay", {}).get("observed_tests", [])]
            if not any(
                phase.get("name") in {"setup", "teardown", "collect"}
                and str(phase.get("outcome", "")).lower() in FAILED
                and (phase.get("call_raw") or phase.get("report_raw"))
                for execution in executions for phase in execution.get("phases", [])
            ):
                raise ValueError("environment_issue requires a failed setup/teardown/collection phase with a diagnostic; otherwise review the waveform")
    else:
        if response.get("conclusion") not in CONCLUSIONS:
            raise ValueError("invalid waveform conclusion")
        observation = load_observation(task_dir, response.get("evidence_id", ""))
        if observation.get("task_id") != Path(task_dir).name:
            raise ValueError("waveform observation belongs to another task")
        if not observation.get("verified_evidence", {}).get("success"):
            result = observation.get("result") or {}
            error_code = result.get("error_code") or result.get("status")
            if response["conclusion"] != "inconclusive" or result.get("success") is not False or not error_code:
                raise ValueError("waveform review requires final signed evidence, or an explicit WaveInfo error and inconclusive conclusion")
        for key in ("alignment_evidence", "observed_behavior", "source_correlation"):
            if not _nonempty(response.get(key)):
                raise ValueError(f"missing {key}")


def load_observation(task_dir, identity):
    if not re.fullmatch(r"wave-[a-f0-9]{64}", str(identity)):
        raise ValueError("evidence_id must be returned by BugReviewWaveInfo for this task")
    observation = read_object(Path(task_dir) / "waveforms" / f"{identity}.json")
    if "wave-" + stable_hash(observation) != identity:
        raise ValueError("waveform observation integrity failure")
    return observation


class CaseReviews:
    """Frozen, complete case lists backed by the existing durable task storage."""

    def __init__(self, root, stage):
        self.root = Path(root)
        self.stage = stage
        self.files = DurableTaskFiles(self.root, "benchmark_case_review.v1")

    def prepare(self, evidence_rows):
        tasks = []
        for evidence in evidence_rows:
            messages = review_messages(self.stage, evidence)
            identity = {"stage": self.stage, "evidence": evidence, "messages": messages}
            task = {**identity, "task_id": self.stage + "-" + stable_hash(identity)[:24]}
            self.files.prepare(task)
            tasks.append({"task_id": task["task_id"], "input_hash": stable_hash(task)})
        path = self.root / "index.json"
        index = {"stage": self.stage, "tasks": tasks}
        if path.exists() and read_object(path) != index:
            raise ValueError("case review inventory changed; prepare a new workspace")
        atomic_write_json(path, index)

    def tasks(self):
        path = self.root / "index.json"
        if not path.exists():
            return []
        tasks = []
        for row in read_object(path)["tasks"]:
            task = read_object(self.root / "tasks" / row["task_id"] / "input.json")
            if stable_hash(task) != row["input_hash"]:
                raise ValueError(f"case review input changed: {row['task_id']}")
            tasks.append(task)
        return tasks

    def output(self, task):
        output = self.files.load_succeeded_output(task)
        state = read_object(self.files.task_dir(task) / "state.json")
        if state["status"] == "succeeded":
            if output is None:
                raise ValueError(f"case review output changed: {task['task_id']}")
            validate_response(self.stage, task["evidence"], output, self.files.task_dir(task))
        return output

    def requests(self, limit):
        tasks, requests, completed = self.tasks(), [], 0
        for task in tasks:
            if self.output(task) is not None:
                completed += 1
            elif len(requests) < limit:
                requests.append({"task_id": task["task_id"], "task_type": self.stage + "_review",
                                 "dut": task["evidence"]["case"]["dut"], "round": 0,
                                 "input_hash": stable_hash(task), "request_hash": stable_hash(task["messages"]),
                                 "messages": task["messages"]})
        return {"total": len(tasks), "completed": completed, "pending": len(tasks) - completed,
                "requests": requests, "not_applicable": not tasks}

    def submit(self, task_id, input_hash, round_index, request_hash, response):
        task = next((t for t in self.tasks() if t["task_id"] == task_id), None)
        if task is None:
            raise ValueError("task is not in the current case review stage")
        if input_hash != stable_hash(task) or request_hash != stable_hash(task["messages"]) or round_index != 0:
            raise ValueError("stale case review identity; fetch BugReviewTasks again")
        prior = self.output(task)
        if prior is not None:
            if prior != response:
                raise ValueError("completed review cannot be replaced")
            return {"status": "succeeded", "reused": True}
        validate_response(self.stage, task["evidence"], response, self.files.task_dir(task))
        self.files.save_output(task, response)
        return {"status": "succeeded", "task_id": task_id}

    def results(self):
        rows = []
        for task in self.tasks():
            output = self.output(task)
            if output is None:
                raise ValueError(f"case review incomplete: {task['task_id']}")
            row = {"case": task["evidence"]["case"], "sources": task["evidence"].get("sources", {}), "review": output,
                   "replay": task["evidence"]["replay"]}
            if self.stage == "waveform":
                row["waveform"] = load_observation(self.files.task_dir(task), output["evidence_id"])
            rows.append(row)
        return rows

    def artifacts(self):
        return [self.root / "index.json"] + sorted(self.root.glob("tasks/*/*.json")) + sorted(
            self.root.glob("tasks/*/waveforms/*.json"))


def reviewed_comparison(item, failures, waveforms):
    """Feed reviewed evidence into existing candidates without inventing claims."""
    result = copy.deepcopy(item)
    waves = {r["case"]["case_id"]: r for r in waveforms}
    by_candidate = {}
    for row in failures:
        wave = waves.get(row["case"]["case_id"])
        final = wave["review"]["conclusion"] if wave else row["review"]["classification"]
        summary = {"case_id": row["case"]["case_id"], "nodeid": row["case"]["nodeid"],
                   "classification": final, "review": row["review"], "replay": row["replay"],
                   "waveform_review": wave["review"] if wave else None,
                   "waveform": wave["waveform"] if wave else None}
        for identity in row["case"]["reported_candidate_ids"]:
            by_candidate.setdefault(identity, []).append(summary)
    candidates = result.get("flat_candidates", []) + [c for g in result.get("run_graphs", [])
                                                       for c in g.get("candidate_bugs", [])]
    for candidate in candidates:
        reviews = by_candidate.get(candidate["candidate_id"], [])
        if not reviews:
            continue
        candidate.setdefault("test_evidence", []).extend({"failure_review": r} for r in reviews)
        details = candidate.setdefault("validation_details", {})
        details["failure_reviews"] = reviews
        candidate["replay_results"] = [r["replay"] for r in reviews]
        statuses = [r["replay"]["status"] for r in reviews]
        if any(s in {"infrastructure_incomplete", "infrastructure_error", "blocked_environment", "invalid_contract"}
               for s in statuses):
            status = "infrastructure_incomplete"
        elif "reproduced" in statuses:
            status = "reproduced"
        elif all(s == statuses[0] for s in statuses):
            status = statuses[0]
        else:
            status = "not_reproduced_snapshot_changed"
        details["replay_result"] = {
            "status": status, "reason": "Per-test replay results; see failure_reviews for causal attribution.",
            "phase": "execute", "case_results": candidate["replay_results"],
            "all_cases_reproduced": all(s == "reproduced" for s in statuses),
            "replay_completeness": "complete" if all(s in {
                "reproduced", "not_reproduced_same_snapshot", "not_reproduced_snapshot_changed"} for s in statuses) else "partial",
        }
        if all(r["classification"] in NON_DUT for r in reviews):
            candidate["validation_status"] = "excluded_declared_candidate"
            details["candidate_disposition"] = "excluded_declared_candidate"
            details["exclusion_reason"] = "All reviewed failing tests have non-DUT causes."
    return result
