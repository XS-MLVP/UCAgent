"""Import an actual RunTestCases report into the full replay baseline."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import shutil

from ucagent.util.config import load_current_test_report

from .json_io import atomic_write_json
from .layout import TEST_REPORT_ROOT, canonical_node, test_report_root, unity_test_root, workspace_node
from .records import load_record
from .failures import match_failure_digests, prefill_failure_analysis


def save_run_log(output: Path, batch_relative: str, stdout: str) -> str:
    """Persist one RunTestCases stdout as an evidence log the scripts can parse."""
    if not stdout.strip():
        return ""
    logs = output / "diagnostics" / "run_logs"
    logs.mkdir(parents=True, exist_ok=True)
    name = Path(batch_relative).stem + ".txt"
    (logs / name).write_text(f"STDOUT: {json.dumps(stdout)}\n", encoding="utf-8")
    return f"diagnostics/run_logs/{name}"


STATUSES = {"PASSED": "passed", "FAILED": "failed", "ERROR": "error",
            "SKIPPED": "skipped", "XFAILED": "xfailed", "XPASSED": "xpassed"}


def report_outcomes(report: dict, collected: set[str]) -> dict[str, tuple[str, str]]:
    """Extract only exact collected nodes from a saved RunTestCases report."""
    tests = report.get("tests") or {}
    if not isinstance(tests, dict):
        raise ValueError("RunTestCases tests must be an object")
    result_map = tests.get("test_cases") or {}
    if not isinstance(result_map, dict):
        raise ValueError("RunTestCases test_cases must be an object")
    observed: dict[str, tuple[str, str]] = {}
    instances = tests.get("test_case_instances") or {}
    for raw_node, raw_status in result_map.items():
        parent = workspace_node(raw_node)
        status = STATUSES.get(str(raw_status).upper())
        if status is None:
            raise ValueError(f"unknown report status for {raw_node}: {raw_status}")
        children = [case_id for case_id in collected
                    if case_id == parent or case_id.startswith(parent + "[")]
        if not children:
            continue
        if len(children) == 1:
            observed[children[0]] = (status, canonical_node(raw_node))
            continue
        failed_nodes = {workspace_node(item["node_id"]): canonical_node(item["node_id"])
                        for item in instances.get(raw_node, [])
                        if isinstance(item, dict) and item.get("status") == "FAILED"}
        for child in children:
            if status == "passed":
                observed[child] = ("passed", "")
            elif child in failed_nodes:
                observed[child] = ("failed", failed_nodes[child])
            elif failed_nodes and status == "failed":
                observed[child] = ("passed", "")
    return observed


_WAVE_SESSION_RE = re.compile(r"^toffee_tmp_(\d{14})_(\d{3,6})$")
_WAVE_SESSION_SUFFIXES = (".fst", ".vcd", ".dat")
# Only anomalous outcomes can ever need waveform evidence; passed, skipped and
# not_run cases have no consumer for their dumps.
_KEEP_WAVE_OUTCOMES = frozenset({"failed", "error", "xfailed", "xpassed"})


def _wave_function_stem(identity: str) -> str:
    """Return the pytest function stem WaveInfo matches dump files against."""
    stem = identity.strip().split("::")[-1]
    lowered = stem.lower()
    for suffix in _WAVE_SESSION_SUFFIXES:
        if lowered.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return re.sub(r"\[.*$", "", stem).strip()


def _wave_session_key(path: Path) -> tuple[float, float, str]:
    """Order toffee sessions exactly like WaveInfo's newest-session choice."""
    match = _WAVE_SESSION_RE.fullmatch(path.name)
    if match is None:
        return (float("-inf"), path.stat().st_mtime, str(path))
    stamp, fraction = match.groups()
    parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S").timestamp()
    return (parsed + int(fraction) / (10 ** len(fraction)), path.stat().st_mtime, str(path))


def _tree_stats(root: Path) -> tuple[int, int]:
    """Count regular files and their total bytes below one directory."""
    count = total = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            count += 1
            total += path.stat().st_size
    return count, total


def prune_baseline_waveforms(workspace: Path, output: Path) -> dict:
    """Delete baseline waveform dumps that no evidence path can consume.

    All dumps live in one canonical location: the newest toffee_tmp session
    under ``unity_test/data`` — the same root pytest writes (RunTestCases
    cwd) and WaveInfo reads. Superseded sessions, and any legacy sessions
    still under the pre-unification ``unity_test/tests/data`` location, first
    hand their failed, error, xfailed and xpassed dumps to that target
    session (existing files win on a name collision) and are then removed
    whole. Inside the target session, files whose function stem belongs only
    to passed, skipped or not_run cases are removed; kept stems and any
    unattributable file stay.
    """
    index = load_record(output, "review_index.json", "index")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    keep, delete = set(), set()
    for case_id, entry in index.cases.items():
        stem = _wave_function_stem(entry.waveform_test_case_name or case_id)
        if not stem or "/" in stem or "\\" in stem:
            continue
        if summary.outcomes.get(case_id, "not_run") in _KEEP_WAVE_OUTCOMES:
            keep.add(stem.casefold())
        else:
            delete.add(stem.casefold())
    delete -= keep

    def _sessions(data_dir: Path) -> list[Path]:
        """List the toffee_tmp sessions below one data root, newest first."""
        return sorted(
            (path for path in data_dir.rglob("toffee_tmp_*")
             if path.is_dir() and _WAVE_SESSION_RE.fullmatch(path.name)),
            key=_wave_session_key, reverse=True)

    unity_root = unity_test_root(workspace)
    data_root = unity_root / "data"
    sessions_removed = files_removed = bytes_removed = 0

    primary = _sessions(data_root)
    legacy = _sessions(unity_root / "tests" / "data")
    target = primary[0] if primary else None
    if target is None and legacy:
        target = data_root / legacy[0].name
        try:
            shutil.move(str(legacy[0]), str(target))
        except (OSError, shutil.Error):
            target = None
        else:
            legacy = legacy[1:]

    for session in primary[1:] + legacy:
        # Superseded and legacy sessions may still hold dumps WaveInfo could
        # consume; relocate kept-stem files into the target session first.
        for path in sorted(session.rglob("*")):
            stem = path.name.rsplit(".", 1)[0].casefold() \
                if path.is_file() and not path.is_symlink() and "." in path.name else ""
            if not stem or target is None or not any(
                    re.fullmatch(re.escape(kept) + r"\d*", stem) for kept in keep):
                continue
            destination = target / path.relative_to(session)
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(path), str(destination))
            except (OSError, shutil.Error):
                continue
        count, total = _tree_stats(session)
        shutil.rmtree(session, ignore_errors=True)
        if not session.exists():
            sessions_removed += 1
            files_removed += count
            bytes_removed += total

    if target is not None:
        for path in sorted(target.rglob("*")):
            if not path.is_file() or path.is_symlink() or "." not in path.name:
                continue
            stem = path.name.rsplit(".", 1)[0].casefold()
            if any(re.fullmatch(re.escape(stem_del) + r"\d*", stem) for stem_del in delete) \
                    and not any(re.fullmatch(re.escape(stem_keep) + r"\d*", stem) for stem_keep in keep):
                size = path.stat().st_size
                try:
                    path.unlink()
                except OSError:
                    continue
                files_removed += 1
                bytes_removed += size
    return {"sessions_removed": sessions_removed, "files_removed": files_removed,
            "bytes_removed": bytes_removed}


def capture_baseline_coverage(workspace: Path, output: Path) -> dict:
    """Record deterministic coverage evidence from this run's saved reports.

    Evidence references, run scope and measured line totals are tool-computed
    facts, so the reviewer never hand-writes them. Only an empty basis text is
    prefilled; a metric whose saved artifact is absent stays untouched for
    explicit reviewer recording.
    """
    index = load_record(output, "review_index.json", "index")
    coverage = load_record(output, index.coverage_path, "coverage")
    report_root = test_report_root(workspace)
    evidence = {"line": "coverage_data/code_coverage.json", "functional": "toffee_report.json"}
    recorded, missing = [], []
    for metric_key, relative in evidence.items():
        metric = coverage.metrics.get(metric_key)
        artifact = report_root / relative
        if metric is None or not artifact.is_file():
            missing.append(metric_key)
            continue
        text = artifact.read_text(encoding="utf-8", errors="replace")
        line_count = len(text.splitlines())
        if not line_count:
            missing.append(metric_key)
            continue
        metric.status = "available"
        metric.source_ref = f"{TEST_REPORT_ROOT.as_posix()}/{relative}:1-{line_count}"
        metric.run_scope = "review_full_run"
        if not metric.basis.strip():
            metric.basis = ("Evidence reference recorded by CaptureReplayReport from the saved full "
                            "replay report; refine the metric definition in this basis")
        if metric_key == "line":
            try:
                overview = json.loads(text)["overview"]
                total = int(overview["total"]["line"])
                missed = int(overview["miss"]["line"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                total, missed = None, None
            if total is not None and 0 <= missed <= total:
                metric.numerator = total - missed
                metric.denominator = total
                metric.value = f"{(total - missed) / total:.1%}"
        recorded.append(metric_key)
    if recorded:
        atomic_write_json(output / index.coverage_path, coverage.model_dump(mode="json", by_alias=True))
    return {"recorded": recorded, "missing_evidence": missing}


def import_current_report(workspace: Path, output: Path) -> dict:
    """Snapshot one genuine report and update matching collected case records."""
    index = load_record(output, "review_index.json", "index")
    manifest = load_record(output, index.manifest_path, "manifest")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    payload = load_current_test_report(str(workspace))
    report = payload["report"]
    context = payload.get("context", {})
    if context.get("source") != "RunTestCases" or context.get("stage_name") != "full_replay":
        raise ValueError("current report must come from RunTestCases in full_replay")
    collected = set(manifest.collected)
    observed = report_outcomes(report, collected)
    for case_id in observed:
        if case_id in summary.outcomes:
            raise ValueError(f"baseline outcome already recorded for {case_id}")
    relative = f"replay/batch-{secrets.token_hex(6)}.json"
    atomic_write_json(output / relative, payload)
    if not observed:
        summary.diagnostics.append(f"{relative}: no exact collected outcome matched")
    stdout = str(payload.get("pytest_stdout", "") or "")
    run_log = save_run_log(output, relative, stdout)
    digests, ambiguous = match_failure_digests(
        stdout, {case_id: status for case_id, (status, _) in observed.items()})
    prefilled_cases: list[str] = []
    prefilled_fields = 0
    for case_id, (status, report_node) in observed.items():
        entry = index.cases[case_id]
        case = load_record(output, entry.record_path, "case")
        case.replay.status = status
        case.replay.baseline_id = manifest.baseline_id
        case.replay.report_node_id = report_node or case_id
        case.replay.invocation_success = bool(report.get("run_test_success"))
        case.replay.result = f"{relative}: {status}"
        if report_node:
            entry.waveform_test_case_name = report_node
        digest = digests.get(case_id)
        if digest:
            filled = prefill_failure_analysis(case, digest, run_log)
            if filled:
                prefilled_cases.append(case_id)
                prefilled_fields += len(filled)
        summary.outcomes[case_id] = status
        atomic_write_json(output / entry.record_path, case.model_dump(mode="json", by_alias=True))
    summary.commands.append(["RunTestCases", str(context.get("pytest_ex_args", ""))])
    summary.report_ref = relative
    summary.batch_refs.append(relative)
    # Coverage evidence only describes a baseline that accounts for every
    # collected node; partial batches leave the metrics for the final batch.
    coverage: dict = {"recorded": [], "missing_evidence": [], "deferred": True}
    waveforms: dict = {}
    if not set(manifest.collected) - set(summary.outcomes):
        coverage["deferred"] = False
        try:
            coverage = capture_baseline_coverage(workspace, output)
        except (OSError, ValueError, KeyError, TypeError) as error:
            summary.diagnostics.append(f"coverage capture failed: {error}")
            coverage["error"] = str(error)
        try:
            waveforms = prune_baseline_waveforms(workspace, output)
        except (OSError, ValueError, KeyError, TypeError) as error:
            summary.diagnostics.append(f"waveform pruning failed: {error}")
            waveforms = {"error": str(error)}
    atomic_write_json(output / index.replay_summary_path, summary.model_dump(mode="json", by_alias=True))
    atomic_write_json(output / "review_index.json", index.model_dump(mode="json", by_alias=True))
    return {"imported": len(observed), "remaining": len(collected - set(summary.outcomes)),
            "report_ref": relative, "baseline_id": manifest.baseline_id, **coverage, "waveforms": waveforms,
            "failure_evidence": {"run_log": run_log, "aligned": len(digests), "ambiguous": len(ambiguous),
                                 "prefilled_cases": len(prefilled_cases),
                                 "prefilled_fields": prefilled_fields}}
