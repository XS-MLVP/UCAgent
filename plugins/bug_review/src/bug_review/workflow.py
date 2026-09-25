"""Run the five-stage Bug Review analysis against immutable DUT inputs."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from bug_review.analysis_core.report_inventory import build_report_inventory
from bug_review.analysis_core.task_manifest import atomic_write_json, stable_hash
from bug_review.analysis_core.toffee_parser import parse_test_executions
from .case_analysis import CaseReviews, FAILED, canonical_node, source_evidence
from .inputs import discover_input_workspaces, resolve_run_specs
from .tasks import read_object, task_lock
from .test_execution import execute_suite


ANALYSIS = ("inventory", "replay", "waveform", "correlate", "publish")
PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def file_hash(path):
    """Return a file's SHA-256 digest for input and output integrity checks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value):
    """Validate a workspace label before using it as an output path component."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in {".", ".."}:
        raise ValueError(f"invalid workspace name: {value!r}")
    return value


def _page(title, body):
    """Render one self-contained report page from escaped evidence fields."""
    return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width'>"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:6px 0}</style>"
            f"<h1>{html.escape(title)}</h1>{body}</html>")


def _write_text(path, value):
    """Write UTF-8 text after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _failed(row):
    """Recognize a failed test or failed setup, teardown, or collection phase."""
    return str(row.get("outcome", "")).lower() in FAILED or any(
        str(phase.get("outcome", "")).lower() in FAILED for phase in row.get("phases", [])
    )


def _workspace_node(node):
    """Express pytest's tests/ node IDs relative to the DUT workspace."""
    value = canonical_node(node)
    return "unity_test/" + value if value.startswith("tests/") else value


def _source_files(source):
    """Select immutable inputs without hashing historical waveforms or reports."""
    for path in sorted(source.rglob("*")):
        if not path.is_file() or any(part in {"data", "uc_test_report", "__pycache__", ".git"}
                                     for part in path.relative_to(source).parts):
            continue
        if path.suffix.lower() in {".py", ".md", ".v", ".sv", ".vh", ".svh",
                                   ".yaml", ".yml", ".toml", ".json", ".txt", ".f"} or (
            path.name == "runtime_config.json"
        ):
            yield path


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
    return {"schema": "bug_review_inventory.v1", "name": name, "dut": dut,
            "source_workspace": str(source), "summary_path": str(summary) if summary.is_file() else "",
            "analysis_path": str(analysis) if analysis.is_file() else "",
            "diagnostics": [f"missing {path}" for path in (summary, analysis) if not path.is_file()],
            "bugs": bugs}, "\n".join(lines)


def prepare(workspace, kind="analysis", **options):
    """Prepare a fresh V1 analysis workspace from explicit immutable inputs."""
    if kind != "analysis":
        raise ValueError("Bug Review supports analysis only")
    root = Path(workspace).resolve()
    runs = [(safe_name(label), Path(path).resolve()) for label, path in options.get("runs", [])]
    if not runs or len({label for label, _ in runs}) != len(runs):
        raise ValueError("provide at least one uniquely labeled workspace")
    for label, source in runs:
        if (source.name != label or not label.startswith("workspace_") or not source.is_dir()
                or not (source / "unity_test/tests").is_dir()):
            raise ValueError(f"expected a UnityTest inputs/workspace_* directory: {source}")
        if root == source or root.is_relative_to(source) or source.is_relative_to(root):
            raise ValueError("output root and input workspaces must be separate")
    config = {"schema": "bug_review_job.v1", "kind": kind, "stages": list(ANALYSIS),
              "runs": [[label, str(path)] for label, path in runs],
              "output_dir": "results", "batch_size": int(options.get("batch_size", 1)),
              "timeout": int(options.get("timeout", 300))}
    if config["batch_size"] < 1 or config["timeout"] < 1:
        raise ValueError("batch_size and timeout must be positive")
    path = root / "review_job.json"
    if path.exists() and read_object(path) != config:
        raise ValueError("output root belongs to another analysis; select a new output root")
    atomic_write_json(path, config)
    return root


class Workflow:
    """Advance the frozen V1 analysis through five checked stages."""

    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.config = read_object(self.root / "review_job.json")
        if self.config.get("schema") != "bug_review_job.v1" or self.config.get("stages") != list(ANALYSIS):
            raise ValueError("workspace requires a fresh V1 analysis preparation")
        self.out = self.root / self.config["output_dir"]

    def _state(self):
        """Read state and verify every completed stage's saved artifacts."""
        path = self.root / "workflow_state.json"
        state = read_object(path) if path.is_file() else {"config_hash": stable_hash(self.config), "completed": {}}
        if state["config_hash"] != stable_hash(self.config):
            raise ValueError("analysis configuration changed; prepare a new output root")
        for stage, files in state["completed"].items():
            for relative, digest in files.items():
                artifact = self.root / relative
                if not artifact.is_file() or file_hash(artifact) != digest:
                    raise ValueError(f"{stage} output changed or missing: {relative}")
        return state

    def status(self):
        """Return the current stage and previously sealed stage names."""
        completed = self._state()["completed"]
        current = next((stage for stage in ANALYSIS if stage not in completed), "")
        return {"kind": "analysis", "current_stage": current,
                "completed": list(completed), "complete": not current}

    def _workspaces(self):
        """Return frozen workspace names and their source paths."""
        return [(name, Path(path)) for name, path in self.config["runs"]]

    def _dut_roots(self):
        """Expose task roots to the shared WaveInfo wrapper."""
        return [(source.name.removeprefix("workspace_"), self.root / "tasks" / name)
                for name, source in self._workspaces()]

    def _review_store(self, name, stage):
        """Return the existing durable per-case review queue."""
        return CaseReviews(self.root / "tasks" / name / stage / "reviews", stage)

    def _decision_paths(self, name):
        """Locate the frozen correlation request and accepted answers."""
        base = self.root / "tasks" / name / "correlate"
        return base / "requests.json", base / "responses"

    def requests(self):
        """Expose bounded current-stage judgments and exact response identities."""
        stage = self.status()["current_stage"]
        limit = self.config["batch_size"]
        if stage in {"replay", "waveform"}:
            progress = {"total": 0, "completed": 0, "pending": 0, "requests": []}
            for name, _ in self._workspaces():
                part = self._review_store(name, stage).requests(limit)
                for key in ("total", "completed", "pending"):
                    progress[key] += part[key]
                progress["requests"].extend(part["requests"])
                limit -= len(part["requests"])
            return {**progress, "not_applicable": not progress["total"]}
        if stage == "correlate":
            progress = {"total": 0, "completed": 0, "pending": 0, "requests": []}
            for name, _ in self._workspaces():
                request_path, answers = self._decision_paths(name)
                if not request_path.is_file():
                    continue
                for task in read_object(request_path)["tasks"]:
                    progress["total"] += 1
                    output = answers / f"{task['task_id']}.json"
                    if output.is_file():
                        self._validate_decision(task, read_object(output), name)
                        progress["completed"] += 1
                    elif len(progress["requests"]) < limit:
                        progress["requests"].append({
                            "task_id": task["task_id"], "task_type": "bug_decision",
                            "dut": task["evidence"]["dut"], "round": 0,
                            "input_hash": stable_hash(task),
                            "request_hash": stable_hash(task["messages"]),
                            "messages": task["messages"]})
            progress["pending"] = progress["total"] - progress["completed"]
            return {**progress, "not_applicable": not progress["total"]}
        return {"total": 0, "completed": 0, "pending": 0, "requests": [], "not_applicable": True}

    def submit(self, **kwargs):
        """Validate and persist one review against the current frozen request."""
        with task_lock(self.root / "workflow.lock"):
            stage = self.status()["current_stage"]
            if stage in {"replay", "waveform"}:
                for name, _ in self._workspaces():
                    store = self._review_store(name, stage)
                    if any(task["task_id"] == kwargs["task_id"] for task in store.tasks()):
                        return store.submit(**kwargs)
                raise ValueError("review task is not in the current stage")
            if stage != "correlate":
                raise ValueError("current stage has no judgment task")
            for name, _ in self._workspaces():
                request_path, answers = self._decision_paths(name)
                if not request_path.is_file():
                    continue
                task = next((row for row in read_object(request_path)["tasks"]
                             if row["task_id"] == kwargs["task_id"]), None)
                if task is None:
                    continue
                if (kwargs["input_hash"] != stable_hash(task)
                        or kwargs["request_hash"] != stable_hash(task["messages"])
                        or kwargs["round_index"] != 0):
                    raise ValueError("stale decision request; call BugReviewTasks again")
                response = kwargs["response"]
                self._validate_decision(task, response, name)
                target = answers / f"{task['task_id']}.json"
                if target.exists() and read_object(target) != response:
                    raise ValueError("decision already accepted; prepare a new output root")
                atomic_write_json(target, response)
                return {"status": "succeeded", "task_id": task["task_id"]}
            raise ValueError("decision task is not in the current stage")

    def _validate_decision(self, task, response, name):
        """Require an evidence-based verdict with a consistent root identity."""
        if not isinstance(response, dict):
            raise ValueError("decision must be a JSON object")
        verdict = response.get("verdict")
        confidence = response.get("review_confidence")
        if verdict not in {"confirmed", "refuted", "inconclusive"}:
            raise ValueError("verdict must be confirmed, refuted, or inconclusive")
        if verdict == "refuted" and confidence != 0:
            raise ValueError("refuted Bug requires review_confidence 0")
        if verdict == "inconclusive" and confidence is not None:
            raise ValueError("inconclusive Bug requires null review_confidence")
        if verdict == "confirmed" and (type(confidence) not in {float, int} or not 0 < confidence <= 1):
            raise ValueError("confirmed Bug requires review_confidence in (0, 1]")
        if not isinstance(response.get("rationale"), str) or not response["rationale"].strip():
            raise ValueError("decision requires a nonempty rationale")
        if verdict == "confirmed" and not all(
            isinstance(response.get(key), str) and response[key].strip()
            for key in ("spec_ref", "rtl_ref", "first_error", "causal_chain")
        ):
            raise ValueError("confirmed Bug requires spec_ref, rtl_ref, first_error and causal_chain")
        refs = response.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("decision requires evidence_refs")
        evidence = task["evidence"]
        for ref in refs:
            value = evidence
            try:
                if not isinstance(ref, str) or not ref.startswith("/"):
                    raise ValueError
                for key in ref[1:].split("/"):
                    value = value[int(key)] if isinstance(value, list) else value[key]
            except (KeyError, IndexError, TypeError, ValueError):
                raise ValueError(f"evidence reference unavailable: {ref}") from None
            if value in (None, "", [], {}):
                raise ValueError(f"evidence reference empty: {ref}")
        if verdict == "confirmed":
            supported = any(
                row.get("review", {}).get("correctness_confirmed") is True
                and row.get("review", {}).get("classification") == "suspected_dut_bug"
                and row.get("waveform_review", {}).get("conclusion") == "dut_bug"
                and row.get("waveform", {}).get("verified_evidence", {}).get("success") is True
                and row.get("replay", {}).get("status") == "reproduced"
                for row in evidence["cases"])
            if not supported:
                raise ValueError("confirmed Bug needs a correct, reproduced case with signed waveform evidence")
            source = dict(self._workspaces())[name]
            for key in ("spec_ref", "rtl_ref"):
                match = re.fullmatch(r"(.+):(\d+)(?:-\d+)?", response[key])
                cited = (source / match.group(1)).resolve() if match else source
                if not match or not cited.is_relative_to(source) or not cited.is_file():
                    raise ValueError(f"{key} must cite an existing input file and line: {response[key]}")
                allowed = {".md", ".txt"} if key == "spec_ref" else {".v", ".sv", ".vh", ".svh"}
                if cited.suffix.lower() not in allowed:
                    raise ValueError(f"{key} cites the wrong source type: {response[key]}")
                line_count = sum(1 for _ in cited.open(encoding="utf-8", errors="replace"))
                if not 1 <= int(match.group(2)) <= line_count:
                    raise ValueError(f"{key} line is outside {cited}")

    def check(self, stage):
        """Gate completion on stage state and every input workspace artifact."""
        status = self.status()
        if stage in status["completed"]:
            files = self._state()["completed"][stage]
            expected = [self.out / "input_inventory.json"] if stage == "inventory" else []
            names = [name for name, _ in self._workspaces()]
            artifacts = {
                "inventory": ("bug_inventory.json", "bug_outline.md"),
                "replay": ("replay_results.json", "case_reviews.json"),
                "waveform": ("waveform_reviews.json", "waveform_evidence.json"),
                "correlate": ("bug_reviews.json", "root_groups.json"),
                "publish": ("report_data.json", "index.html"),
            }
            for name in names:
                expected.extend(self.out / "workspaces" / name / part for part in artifacts[stage])
            if stage == "publish":
                expected.append(self.out / "index.html")
            if any(not path.is_file() or str(path.relative_to(self.root)) not in files for path in expected):
                return False, {"error_code": "STAGE_OUTPUT_MISSING",
                               "error": f"{stage} output missing for a selected workspace",
                               "next_action": "Run BugReviewRunStage for this stage after restoring the missing output."}
            if stage == "inventory":
                overview = read_object(self.out / "input_inventory.json")
                if [row["name"] for row in overview["workspaces"]] != names:
                    raise ValueError("input_inventory.json workspace list differs from review_job.json")
            for name in names:
                target = self.out / "workspaces" / name
                if stage == "inventory":
                    inventory = read_object(target / "bug_inventory.json")
                    bugs = inventory["bugs"]
                    if (inventory["name"] != name or len(bugs) != next(
                            row["reported_bug_count"] for row in overview["workspaces"]
                            if row["name"] == name) or len({row["bug_id"] for row in bugs}) != len(bugs)):
                        raise ValueError(f"{name}/bug_inventory.json has incomplete or duplicate Bug identities")
                elif stage == "replay":
                    inventory = read_object(target / "bug_inventory.json")
                    replay = read_object(target / "replay_results.json")
                    reviews = read_object(target / "case_reviews.json")["cases"]
                    cases = {row["nodeid"]: row for row in replay["cases"]}
                    reported = {_workspace_node(node) for bug in inventory["bugs"] for node in bug["tests"]}
                    if replay["name"] != name or not reported.issubset(cases):
                        raise ValueError(f"{name}/replay_results.json omits a reported test")
                    reviewed = {row["case"]["nodeid"] for row in reviews}
                    if any(row["status"] == "reproduced" and node not in reviewed
                           for node, row in cases.items()):
                        raise ValueError(f"{name}/case_reviews.json omits a reproduced failure")
                elif stage == "waveform":
                    reviews = read_object(target / "case_reviews.json")["cases"]
                    waves = read_object(target / "waveform_reviews.json")["cases"]
                    evidence = read_object(target / "waveform_evidence.json")["by_case"]
                    expected_ids = {row["case"]["case_id"] for row in reviews
                                    if row["replay"]["status"] == "reproduced"
                                    and row["review"]["classification"] != "environment_issue"}
                    actual_ids = {row["case"]["case_id"] for row in waves}
                    if expected_ids != actual_ids or actual_ids != set(evidence):
                        raise ValueError(f"{name}/waveform_reviews.json does not cover all eligible failures")
                elif stage == "correlate":
                    inventory = read_object(target / "bug_inventory.json")
                    reviews = read_object(target / "bug_reviews.json")["bugs"]
                    roots = read_object(target / "root_groups.json")["groups"]
                    by_id = {row["bug_id"]: row for row in reviews}
                    if (len(by_id) != len(reviews) or not {
                            row["bug_id"] for row in inventory["bugs"]}.issubset(by_id)):
                        raise ValueError(f"{name}/bug_reviews.json dropped or duplicated an original Bug")
                    grouped = {member: group["root_id"] for group in roots
                               for member in group["member_bug_ids"]}
                    if any(row["root_id"] != grouped.get(row["bug_id"]) for row in reviews):
                        raise ValueError(f"{name}/root_groups.json disagrees with Bug members")
                elif stage == "publish":
                    report = read_object(target / "report_data.json")
                    reviews = read_object(target / "bug_reviews.json")["bugs"]
                    if ([row["bug_id"] for row in report["bugs"]] !=
                            [row["bug_id"] for row in reviews]):
                        raise ValueError(f"{name}/report_data.json differs from accepted Bug decisions")
                    for verdict in ("confirmed", "refuted", "inconclusive"):
                        if report["counts"][verdict] != sum(row["verdict"] == verdict for row in reviews):
                            raise ValueError(f"{name}/report_data.json has incorrect {verdict} count")
                    index_text = (target / "index.html").read_text(encoding="utf-8")
                    for bug in reviews:
                        filename = "bug_" + stable_hash(bug["bug_id"])[:16] + ".html"
                        if not (target / filename).is_file() or filename not in index_text:
                            raise ValueError(f"{name}/index.html omits Bug detail {bug['bug_id']}")
            if stage == "publish":
                index_text = (self.out / "index.html").read_text(encoding="utf-8")
                if any(f"workspaces/{name}/index.html" not in index_text for name in names):
                    raise ValueError("index.html omits a selected workspace")
            return True, status
        return False, {"error_code": "BUG_REVIEW_STAGE_PENDING", "stage": stage,
                       "progress": self.requests(),
                       "next_action": "Call BugReviewRunStage, finish BugReviewTasks, then Check."}

    def run(self, stage):
        """Run only the current stage and seal its completed outputs."""
        with task_lock(self.root / "workflow.lock"):
            state = self._state()
            if stage in state["completed"]:
                return {"status": "succeeded", "reused": True, "stage": stage}
            current = self.status()["current_stage"]
            if stage != current:
                raise ValueError(f"current stage is {current}; requested {stage}")
            if stage != "inventory":
                self._check_sources()
            outputs = getattr(self, f"_run_{stage}")()
            if outputs is None:
                return {"status": "awaiting_judgments", "progress": self.requests()}
            state["completed"][stage] = {str(path.relative_to(self.root)): file_hash(path)
                                         for path in outputs}
            atomic_write_json(self.root / "workflow_state.json", state)
            return {"status": "succeeded", "stage": stage, **self.status()}

    def _run_inventory(self):
        """Freeze source identity and publish a complete reported-Bug outline."""
        files = {}
        workspaces = []
        outputs = []
        for name, source in self._workspaces():
            for path in _source_files(source):
                files[str(path)] = file_hash(path)
            inventory, outline = _inventory(source, name)
            target = self.out / "workspaces" / name
            json_path = target / "bug_inventory.json"
            outline_path = target / "bug_outline.md"
            atomic_write_json(json_path, inventory)
            _write_text(outline_path, outline)
            workspaces.append({"name": name, "dut": inventory["dut"], "source": str(source),
                               "reported_bug_count": len(inventory["bugs"])})
            outputs.extend([json_path, outline_path])
        if not files:
            raise ValueError("no source files found in selected input workspaces")
        index = self.out / "input_inventory.json"
        atomic_write_json(index, {"schema": "bug_review_inputs.v1",
                                  "workspaces": workspaces, "files": files})
        return [index, *outputs]

    def _check_sources(self):
        """Reject changed input sources before another stage consumes them."""
        for path, digest in read_object(self.out / "input_inventory.json")["files"].items():
            if not Path(path).is_file() or file_hash(path) != digest:
                raise ValueError(f"input changed after inventory: {path}; prepare a new output root")

    def _run_replay(self):
        """Execute each existing test suite once and collect case judgments."""
        outputs = []
        pending = False
        for name, source in self._workspaces():
            inventory = read_object(self.out / "workspaces" / name / "bug_inventory.json")
            dut = inventory["dut"]
            manifest = {"dut": dut, "model": name, "run_key": name,
                        "workspace_root": str(source), "tests_root": str(source / "unity_test/tests"),
                        "found_files": {"summary": inventory["summary_path"],
                                        "analysis": inventory["analysis_path"]}}
            execution = execute_suite(manifest, self.root / "tasks" / name / "replay" / "runs" / name,
                                      timeout=self.config["timeout"])
            generated = [asdict(row) for row in parse_test_executions(read_object(execution["report_path"]))]
            if not generated:
                raise ValueError(f"replay report contains no tests: {name}")
            original_path = source / "uc_test_report/toffee_report.json"
            original = [asdict(row) for row in parse_test_executions(read_object(original_path))] if original_path.is_file() else []
            reported = {_workspace_node(test) for bug in inventory["bugs"] for test in bug["tests"]}
            nodes = {_workspace_node(row["nodeid"]) for row in generated if _failed(row)}
            nodes.update(_workspace_node(row["nodeid"]) for row in original if _failed(row))
            nodes.update(reported)
            case_rows = []
            review_rows = []
            for node in sorted(nodes):
                past = [row for row in original if _workspace_node(row["nodeid"]) == node]
                current = [row for row in generated if _workspace_node(row["nodeid"]) == node]
                failed = any(_failed(row) for row in current)
                status = "reproduced" if failed else "passed" if current else "not_collected"
                case_id = "case-" + stable_hash([name, node])[:24]
                case = {"dut": dut, "model": name, "run_key": name, "nodeid": node,
                        "case_id": case_id, "original_executions": past,
                        "manifest": manifest, "source": {"source_file": str(source / node.split("::")[0])},
                        "candidates": [], "reported_candidate_ids": [
                            bug["bug_id"] for bug in inventory["bugs"] if node in
                            {_workspace_node(test) for test in bug["tests"]}]}
                case_rows.append({"case_id": case_id, "nodeid": node, "status": status,
                                  "reported_bug_ids": case["reported_candidate_ids"],
                                  "observed_tests": current})
                if failed or any(_failed(row) for row in past):
                    review_rows.append({"case": case, "sources": source_evidence(case),
                                        "replay": {"status": status, "observed_tests": current,
                                                   "report_path": execution["report_path"],
                                                   "replay_workspace": execution["replay_workspace"],
                                                   "execution": execution["execution"]}})
            store = self._review_store(name, "replay")
            store.prepare(review_rows)
            if store.requests(1)["pending"]:
                pending = True
                continue
            target = self.out / "workspaces" / name
            replay_path = target / "replay_results.json"
            review_path = target / "case_reviews.json"
            atomic_write_json(replay_path, {"schema": "bug_review_replay.v1", "name": name,
                                           "execution": execution["execution"],
                                           "report_path": execution["report_path"],
                                           "original_report_path": str(original_path) if original_path.is_file() else None,
                                           "suite_test_count": len(generated),
                                           "suite_failed_count": sum(_failed(row) for row in generated),
                                           "cases": case_rows})
            atomic_write_json(review_path, {"cases": store.results()})
            outputs.extend([replay_path, review_path, self.root / "tasks" / name / "replay" / "runs" / name / "execution.json",
                            Path(execution["report_path"]), *store.artifacts()])
        return None if pending else outputs

    def _run_waveform(self):
        """Collect signed WaveInfo judgments for reproduced failed cases."""
        outputs = []
        pending = False
        for name, _ in self._workspaces():
            rows = []
            for review in read_object(self.out / "workspaces" / name / "case_reviews.json")["cases"]:
                if (review["replay"]["status"] == "reproduced"
                        and review["review"]["classification"] != "environment_issue"):
                    rows.append({"case": review["case"], "sources": review["sources"],
                                 "replay": review["replay"], "failure_review": review["review"]})
            store = self._review_store(name, "waveform")
            store.prepare(rows)
            if store.requests(1)["pending"]:
                pending = True
                continue
            results = store.results()
            target = self.out / "workspaces" / name
            review_path = target / "waveform_reviews.json"
            evidence_path = target / "waveform_evidence.json"
            atomic_write_json(review_path, {"cases": results})
            atomic_write_json(evidence_path, {"by_case": {
                row["case"]["case_id"]: row["waveform"] for row in results}})
            outputs.extend([review_path, evidence_path, *store.artifacts()])
        return None if pending else outputs

    def _run_correlate(self):
        """Prepare Bug decisions, then merge confirmed members by proven RTL root."""
        outputs = []
        pending = False
        for name, _ in self._workspaces():
            target = self.out / "workspaces" / name
            inventory = read_object(target / "bug_inventory.json")
            replay = read_object(target / "replay_results.json")
            reviews = read_object(target / "case_reviews.json")["cases"]
            waves = read_object(target / "waveform_reviews.json")["cases"]
            by_node = {row["case"]["nodeid"]: row for row in reviews}
            by_wave = {row["case"]["nodeid"]: row for row in waves}
            bugs = list(inventory["bugs"])
            reported_nodes = {_workspace_node(test) for bug in bugs for test in bug["tests"]}
            for case in replay["cases"]:
                if case["status"] == "reproduced" and case["nodeid"] not in reported_nodes:
                    bugs.append({"bug_id": "DISCOVERED-" + stable_hash([name, case["nodeid"]])[:12],
                                 "origin": "discovered", "summary": "New replay failure: " + case["nodeid"],
                                 "reported_confidence": None, "tests": [case["nodeid"]],
                                 "claims": [], "ck": [], "rtl_refs": [], "root_refs": []})
            tasks = []
            for bug in bugs:
                cases = []
                for node in {_workspace_node(test) for test in bug["tests"]}:
                    if node in by_node:
                        row = dict(by_node[node])
                        if node in by_wave:
                            row["waveform"] = by_wave[node]["waveform"]
                            row["waveform_review"] = by_wave[node]["review"]
                        cases.append(row)
                evidence = {"dut": inventory["dut"], "bug": bug, "cases": cases,
                            "replay_cases": [case for case in replay["cases"]
                                             if case["nodeid"] in {_workspace_node(test) for test in bug["tests"]}]}
                message = ("Judge this Bug from the supplied current test, waveform, Spec and RTL evidence. "
                           "Return verdict (confirmed/refuted/inconclusive), review_confidence (0 for refuted, "
                           "null for inconclusive, positive for confirmed), rationale, spec_ref, rtl_ref, "
                           "first_error, causal_chain, and evidence_refs. Preserve original claims. "
                           "Confirmed requires a correct reproduced test and signed waveform. "
                           "Use the same RTL root and first_error for Bugs sharing one cause.")
                task_id = "correlate-" + stable_hash([name, bug["bug_id"]])[:24]
                tasks.append({"task_id": task_id, "evidence": evidence,
                              "messages": [{"role": "system", "content": message},
                                           {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}]})
            requests_path, answers = self._decision_paths(name)
            if requests_path.exists() and read_object(requests_path) != {"tasks": tasks}:
                raise ValueError(f"correlation inputs changed for {name}; prepare a new output root")
            atomic_write_json(requests_path, {"tasks": tasks})
            if any(not (answers / f"{task['task_id']}.json").is_file() for task in tasks):
                pending = True
                continue
            rows = []
            groups = {}
            for task in tasks:
                response_path = answers / f"{task['task_id']}.json"
                response = read_object(response_path)
                self._validate_decision(task, response, name)
                bug = task["evidence"]["bug"]
                root_id = None
                if response["verdict"] == "confirmed":
                    root_id = "ROOT-" + stable_hash([
                        response["rtl_ref"], response["first_error"], response["causal_chain"]])[:16]
                    group = groups.setdefault(root_id, {"root_id": root_id,
                        "rtl_ref": response["rtl_ref"], "first_error": response["first_error"],
                        "member_bug_ids": [], "causal_chains": []})
                    group["member_bug_ids"].append(bug["bug_id"])
                    group["causal_chains"].append(response["causal_chain"])
                rows.append({**bug, "verdict": response["verdict"],
                             "review_confidence": response["review_confidence"],
                             "root_id": root_id, "decision": response,
                             "cases": task["evidence"]["cases"]})
                outputs.append(response_path)
            review_path = target / "bug_reviews.json"
            group_path = target / "root_groups.json"
            atomic_write_json(review_path, {"schema": "bug_review_decisions.v1", "bugs": rows})
            atomic_write_json(group_path, {"schema": "bug_review_roots.v1",
                                           "groups": list(groups.values())})
            outputs.extend([requests_path, review_path, group_path])
        return None if pending else outputs

    def _run_publish(self):
        """Render each reviewed Bug and one cross-workspace report index."""
        outputs = []
        links = []
        for name, _ in self._workspaces():
            target = self.out / "workspaces" / name
            reviews = read_object(target / "bug_reviews.json")
            roots = read_object(target / "root_groups.json")
            replay = read_object(target / "replay_results.json")
            bugs = reviews["bugs"]
            counts = {status: sum(row["verdict"] == status for row in bugs)
                      for status in ("confirmed", "refuted", "inconclusive")}
            report_path = target / "report_data.json"
            report = {"schema": "bug_review_report.v1", "name": name, "counts": counts,
                      "execution": replay["execution"], "replay_cases": replay["cases"],
                      "suite_test_count": replay["suite_test_count"],
                      "suite_failed_count": replay["suite_failed_count"],
                      "original_report_path": replay["original_report_path"],
                      "bugs": bugs, "root_groups": roots["groups"]}
            atomic_write_json(report_path, report)
            outputs.append(report_path)
            table_rows = []
            for bug in bugs:
                filename = "bug_" + stable_hash(bug["bug_id"])[:16] + ".html"
                page_path = target / filename
                decision = bug["decision"]
                detail = ("<p><a href='index.html'>返回工作区索引</a> · "
                          "<a href='report_data.json'>结构化证据</a></p>"
                          f"<p><strong>{html.escape(bug['verdict'])}</strong> · "
                          f"复核置信度 {html.escape(str(bug['review_confidence']))} · "
                          f"根因组 {html.escape(str(bug['root_id'] or '无'))}</p>"
                          f"<h2>原始声明</h2><p>{html.escape(bug['summary'])}</p>"
                          f"<p>来源 {html.escape(bug['origin'])} · 原置信度 "
                          f"{html.escape(str(bug.get('reported_confidence')))}</p>"
                          f"<h2>裁决与因果链</h2><p>{html.escape(decision['rationale'])}</p>"
                          f"<p>Spec: {html.escape(decision.get('spec_ref') or '未确认')} · "
                          f"RTL: {html.escape(decision.get('rtl_ref') or '未确认')}</p>"
                          f"<p>首次分歧：{html.escape(decision.get('first_error') or '未确认')}</p>"
                          f"<p>因果链：{html.escape(decision.get('causal_chain') or '未确认')}</p>"
                          "<h2>关联测试与波形</h2>")
                for case in bug["cases"]:
                    observation = case.get("waveform", {})
                    viewer = observation.get("result", {}).get("waveform_viewer", {})
                    url = viewer.get("url") if isinstance(viewer, dict) else None
                    wave_link = (f"<a href='{html.escape(url, quote=True)}'>打开波形</a>"
                                 if isinstance(url, str) and url.startswith(("https://", "http://"))
                                 else "无波形入口")
                    detail += (f"<h3>{html.escape(case['case']['nodeid'])}</h3>"
                               f"<p>复现：{html.escape(case['replay']['status'])} · "
                               f"测试归因：{html.escape(case['review']['classification'])} · "
                               f"波形结论：{html.escape(case.get('waveform_review', {}).get('conclusion', '未审查'))}</p>"
                               f"<p>证据 ID：{html.escape(case.get('waveform_review', {}).get('evidence_id', '无'))} · "
                               f"{wave_link}</p>")
                detail += ("<details><summary>完整声明与证据</summary><pre>"
                           + html.escape(json.dumps(bug, ensure_ascii=False, indent=2))
                           + "</pre></details>")
                _write_text(page_path, _page(f"{name}: {bug['bug_id']}", detail))
                outputs.append(page_path)
                table_rows.append(f"<tr><td><a href='{filename}'>{html.escape(bug['bug_id'])}</a></td>"
                                  f"<td>{html.escape(bug['origin'])}</td>"
                                  f"<td>{html.escape(bug['verdict'])}</td>"
                                  f"<td>{html.escape(str(bug['review_confidence']))}</td>"
                                  f"<td>{html.escape(str(bug['root_id'] or ''))}</td></tr>")
            body = ("<p><a href='../../index.html'>总索引</a> · "
                    "<a href='report_data.json'>结构化报告</a></p>"
                    f"<p>重跑用例：{replay['suite_test_count']} · "
                    f"本次失败：{replay['suite_failed_count']} · "
                    f"原始测试报告：{'有' if replay['original_report_path'] else '缺失'}</p>"
                    f"<p>确认 {counts['confirmed']} · 排除 {counts['refuted']} · "
                    f"未定 {counts['inconclusive']}</p>"
                    "<table><tr><th>Bug</th><th>来源</th><th>裁决</th><th>复核置信度</th>"
                    "<th>根因组</th></tr>" + "".join(table_rows) + "</table>")
            index = target / "index.html"
            _write_text(index, _page(f"{name} Bug Review", body))
            outputs.append(index)
            links.append(f"<li><a href='workspaces/{html.escape(name)}/index.html'>"
                         f"{html.escape(name)}</a>：确认 {counts['confirmed']}，排除 "
                         f"{counts['refuted']}，未定 {counts['inconclusive']}</li>")
        index = self.out / "index.html"
        _write_text(index, _page("Bug Review", "<ul>" + "".join(links) + "</ul>"))
        return [index, *outputs]


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
