"""Per-test replay and evidence reviews owned by the analysis plugin."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .analysis_core.durable_task_store import DurableTaskFiles
from .analysis_core.task_manifest import atomic_write_json, stable_hash
from .tasks import read_object


CLASSIFICATIONS = ("suspected_dut_bug", "spec_misunderstanding", "testbench_issue",
                   "environment_issue", "inconclusive")
CONCLUSIONS = ("dut_bug", "spec_misunderstanding", "testbench_issue",
               "environment_issue", "inconclusive")
FAILED = {"failed", "error", "fail"}


def canonical_node(node):
    """Drop report line annotations from an exact pytest node ID."""
    # Source line ranges are report annotations, not part of a pytest node ID.
    return re.sub(r"(?<=\.py):\d+(?:-\d+)?(?=::|$)", "", str(node))


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


def review_messages(stage, evidence):
    """Describe the current case judgment and its structured response."""
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
    """Check whether a required review explanation contains text."""
    return isinstance(value, str) and bool(value.strip())


def validate_response(stage, evidence, response, task_dir):
    """Validate cited replay or waveform evidence before accepting a review."""
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
    """Read one task-scoped WaveInfo observation by its verified identity."""
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
