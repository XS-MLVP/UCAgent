"""Import an actual RunTestCases report into the full replay baseline."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import hashlib
import shutil

from ucagent.util.config import load_current_test_report

from .json_io import atomic_write_json
from .layout import TEST_REPORT_ROOT, test_report_root, unity_test_root, workspace_node
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
            observed[children[0]] = (status, parent)
            continue
        failed_children = {workspace_node(item["node_id"])
                           for item in instances.get(raw_node, [])
                           if isinstance(item, dict) and item.get("status") == "FAILED"}
        for child in children:
            if status == "passed":
                observed[child] = ("passed", "")
            elif child in failed_children and status == "failed":
                observed[child] = ("failed", child)
            elif failed_children and status == "failed":
                observed[child] = ("passed", "")
    return observed


_WAVE_SESSION_RE = re.compile(r"^toffee_tmp_(\d{14})_(\d{3,6})$")
_WAVE_SESSION_SUFFIXES = (".fst", ".vcd", ".dat")
# Only an imported normal terminal outcome permits pruning. Missing or pending
# outcomes may belong to a failed/interrupted batch whose evidence is not sealed.
_PRUNABLE_WAVE_OUTCOMES = frozenset({"passed", "skipped"})


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


def _sessions(data_dir: Path) -> list[Path]:
    """List the toffee_tmp sessions below one data root, newest first."""
    return sorted(
        (path for path in data_dir.rglob("toffee_tmp_*")
         if path.is_dir() and _WAVE_SESSION_RE.fullmatch(path.name)),
        key=_wave_session_key, reverse=True)


def _free_session_target(data_root: Path, name: str) -> Path:
    """Return the next free session name when two runs share one timestamp."""
    match = _WAVE_SESSION_RE.fullmatch(name)
    stamp, fraction = match.groups() if match else (name, "")
    width = len(fraction) or 3
    base = int(fraction) if fraction else 0
    for candidate in range(base + 1, 10 ** width):
        target = data_root / f"toffee_tmp_{stamp}_{candidate:0{width}d}"
        if not target.exists():
            return target
    raise OSError(f"no free toffee session name below {data_root}")


def harvest_run_sessions(workspace: Path) -> dict:
    """Move every fresh toffee session into its own canonical per-run directory.

    A pytest run writes waveform dumps into a new ``toffee_tmp_*`` session
    below the helper-anchored ``unity_test/tests/data`` directory, and toffee
    deletes all older sessions there before the next run starts. Moving each
    finished session whole into ``unity_test/data`` (the root WaveInfo
    searches) right after its run keeps one directory per run, so a later
    run can never overwrite or delete earlier evidence and no case ever needs
    rerunning just because its dumps were lost. Same-filesystem moves are
    renames; a same-second name collision takes the next free fractional
    suffix instead of touching the existing directory.
    """
    unity_root = unity_test_root(workspace)
    data_root = unity_root / "data"
    legacy_root = unity_root / "tests" / "data"
    harvested = 0
    if legacy_root.is_dir():
        data_root.mkdir(parents=True, exist_ok=True)
        for session in _sessions(legacy_root):
            target = data_root / session.name
            if target.exists():
                target = _free_session_target(data_root, session.name)
            try:
                shutil.move(str(session), str(target))
            except (OSError, shutil.Error):
                continue
            harvested += 1
    return {"sessions_harvested": harvested}


def install_run_session_harvest(manager, workspace: Path) -> None:
    """Harvest each run's session immediately after every RunTestCases call.

    Registering on the stage manager (keyed, so repeated stage
    initializations stay idempotent) protects targeted dut_evidence reruns
    too, which never pass through the full_replay report import.
    """
    manager.add_post_test_case_run_callback(
        "bug_review_harvest_wave_sessions",
        lambda: harvest_run_sessions(Path(workspace)))


def prune_baseline_waveforms(workspace: Path, output: Path) -> dict:
    """Delete baseline waveform dumps that no evidence path can consume.

    Every run's harvested session stays as its own directory below
    ``unity_test/data``. Inside each session, files whose function stem
    belongs only to imported passed or skipped cases are removed; failed,
    pending and unattributable files stay for
    dut_evidence evidence collection.
    """
    harvest = harvest_run_sessions(workspace)
    index = load_record(output, "review_index.json", "index")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    keep, delete = set(), set()
    for case_id, entry in index.cases.items():
        stem = _wave_function_stem(entry.waveform_test_case_name or case_id)
        if not stem or "/" in stem or "\\" in stem:
            continue
        if summary.outcomes.get(case_id) in _PRUNABLE_WAVE_OUTCOMES:
            delete.add(stem.casefold())
        else:
            keep.add(stem.casefold())
    delete -= keep

    files_removed = bytes_removed = 0
    for session in _sessions(unity_test_root(workspace) / "data"):
        for path in sorted(session.rglob("*")):
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
    return {"sessions_harvested": harvest["sessions_harvested"],
            "files_removed": files_removed, "bytes_removed": bytes_removed}


def capture_baseline_coverage(workspace: Path, output: Path, report_roots=None) -> dict:
    """Freeze verified full-set coverage, combining only identical source scopes."""
    index = load_record(output, "review_index.json", "index")
    coverage = load_record(output, index.coverage_path, "coverage")
    roots = list(report_roots or [test_report_root(workspace)])
    snapshot = test_report_root(workspace) / "baseline-coverage" / secrets.token_hex(6)
    snapshot.mkdir(parents=True, exist_ok=False)
    recorded, missing = [], []
    observations = {"line": [], "functional": []}
    identities = []
    for number, root in enumerate(roots):
        manifest = root / "invocation.json"
        identities.append(json.loads(manifest.read_text())["context"].get("source_sha256")
                          if manifest.is_file() else None)
        for key, relative in [("line", "coverage_data/code_coverage.json"),
                              ("functional", "toffee_report.json")]:
            artifact = root / relative
            if not artifact.is_file() or artifact.is_symlink():
                continue
            try:
                value = json.loads(artifact.read_text())
            except (ValueError, OSError):
                continue
            frozen = snapshot / f"batch-{number}" / relative
            frozen.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact, frozen)
            observations[key].append(value)
    same_source = len(roots) == 1 or (all(identities) and len(set(identities)) == 1)
    for key in ("line", "functional"):
        metric = coverage.metrics[key]
        values = observations[key]
        try:
            if len(values) != len(roots) or not same_source:
                raise ValueError("All baseline invocations need matching input identities and coverage artifacts")
            if key == "line":
                totals = [int(item["overview"]["total"]["line"]) for item in values]
                if len(set(totals)) != 1 or totals[0] <= 0:
                    raise ValueError("Line coverage denominators differ or are empty")
                denominator = totals[0]
                if len(values) == 1:
                    missed = int(values[0]["overview"]["miss"]["line"])
                else:
                    missing_sets, universes = [], []
                    for item in values:
                        lines, universe = set(), {}
                        for path, file in item["uncovered"]["data"].items():
                            for module, data in file["modules"].items():
                                universe[(path, module)] = int(data["total"]["line"])
                                for interval in data["line"]:
                                    limits = [int(v) for v in str(interval).split("-")]
                                    if len(limits) not in (1, 2) or limits[-1] - limits[0] > denominator:
                                        raise ValueError("Invalid uncovered line interval")
                                    lines.update((path, module, line) for line in range(limits[0], limits[-1] + 1))
                        if len(lines) != int(item["overview"]["miss"]["line"]):
                            raise ValueError("Uncovered line identities do not match the summary")
                        missing_sets.append(lines)
                        universes.append(universe)
                    if any(universe != universes[0] for universe in universes):
                        raise ValueError("Instrumented source scopes differ")
                    missed = len(set.intersection(*missing_sets))
                if not 0 <= missed <= denominator:
                    raise ValueError("Invalid line coverage counts")
                numerator = denominator - missed
            else:
                sets, hits = [], set()
                for item in values:
                    bins = set()
                    groups = item["coverages"]["functional"]["groups"]
                    for group in groups:
                        for point in group["points"]:
                            if point.get("dynamic_bin"):
                                raise ValueError("Dynamic bins need an explicit aggregate universe")
                            for bin in point["bins"]:
                                identity = (group["name"], point["name"], bin["name"])
                                if identity in bins:
                                    raise ValueError("Duplicate functional checkpoint identity")
                                bins.add(identity)
                                if int(bin["hints"]) > 0:
                                    hits.add(identity)
                    if not bins:
                        raise ValueError("Functional checkpoint universe is empty")
                    sets.append(bins)
                if any(bins != sets[0] for bins in sets):
                    raise ValueError("Functional checkpoint definitions differ")
                denominator, numerator = len(sets[0]), len(hits)
            result = {"metric": key, "numerator": numerator, "denominator": denominator,
                      "source_sha256": identities, "invocation_count": len(roots)}
            target = snapshot / f"{key}.json"
            atomic_write_json(target, result)
            metric.status = "available"
            metric.source_ref = f"{target.relative_to(workspace)}:1-{len(target.read_text().splitlines())}"
            metric.run_scope = "review_full_run"
            metric.numerator, metric.denominator = numerator, denominator
            metric.value = f"{numerator / denominator:.1%}"
            metric.reason = ""
            if not metric.basis.strip():
                metric.basis = "Union of sampled checkpoints or covered lines across frozen full-replay invocations"
            recorded.append(key)
        except (ValueError, KeyError, TypeError) as error:
            metric.status = "unavailable"
            metric.value = ""
            metric.numerator = metric.denominator = None
            metric.source_ref = ""
            metric.reason = str(error)
            missing.append(key)
    for artifact in sorted(snapshot.rglob("*"), reverse=True):
        artifact.chmod(0o555 if artifact.is_dir() else 0o444)
    snapshot.chmod(0o555)
    atomic_write_json(output / index.coverage_path, coverage.model_dump(mode="json", by_alias=True))
    return {"recorded": recorded, "missing_evidence": missing}


def verify_invocation_snapshot(workspace: Path, payload: dict) -> None:
    """Compare imported baseline facts with the protected tool-generated snapshot."""
    archived = payload.get("context", {}).get("report_snapshot_path")
    if not archived:
        raise ValueError("RunTestCases invocation snapshot is required for baseline evidence")
    root = (workspace / archived).resolve()
    root.relative_to(test_report_root(workspace) / "invocations")
    manifest_file = root / "invocation.json"
    saved = json.loads(manifest_file.read_text())
    report_entry = next((entry for entry in saved["files"] if entry["path"] == "report.json"), None)
    if saved["invocation_id"] != payload["context"].get("invocation_id") or not report_entry:
        raise ValueError("Invocation manifest identity does not match the report")
    frozen = root / "report.json"
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != report_entry["sha256"]:
        raise ValueError("Invocation report differs from its archived hash")
    if json.loads(frozen.read_text()) != payload:
        raise ValueError("Current report differs from its immutable invocation snapshot")


def import_current_report(workspace: Path, output: Path, invocation_id: str = "") -> dict:
    """Snapshot one genuine report and update matching collected case records."""
    index = load_record(output, "review_index.json", "index")
    manifest = load_record(output, index.manifest_path, "manifest")
    summary = load_record(output, index.replay_summary_path, "replay_summary")
    if invocation_id:
        if not re.fullmatch(r"[a-f0-9]{32}", invocation_id):
            raise ValueError("invocation_id must be the exact ID returned by RunTestCases")
        snapshot = test_report_root(workspace) / "invocations" / invocation_id / "report.json"
        if snapshot.is_symlink() or snapshot.resolve().is_relative_to(workspace) is False:
            raise ValueError("Invocation snapshot must remain in the workspace")
        payload = json.loads(snapshot.read_text())
    else:
        payload = load_current_test_report(str(workspace))
    verify_invocation_snapshot(workspace, payload)
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
    if not report.get("run_test_success"):
        from .records import EnvironmentFinding
        environment = load_record(output, index.environment_path, "environment")
        environment.findings.append(EnvironmentFinding(category="other", case_ids=list(observed),
            source_ref=f"verification_review/analysis/{relative}:1-{len((output / relative).read_text().splitlines())}",
            observation="Test invocation ended abnormally; reported completed case outcomes are retained",
            impact="Review the exit diagnostic and recover remaining nodes before accepting full execution",
            status="unresolved"))
        atomic_write_json(output / index.environment_path, environment.model_dump(mode="json", by_alias=True))
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
        case.replay.invocation_id = context.get("invocation_id", "")
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
    # Seal the observed outcomes before cleanup reopens the durable summary.
    # A cleanup failure must preserve these facts and never prune using stale data.
    atomic_write_json(output / index.replay_summary_path, summary.model_dump(mode="json", by_alias=True))
    atomic_write_json(output / "review_index.json", index.model_dump(mode="json", by_alias=True))
    # Waveform hygiene runs after every batch: the run's session is already
    # harvested into its own canonical directory, and dumps of finished
    # passed cases are pruned immediately instead of waiting for the final
    # batch. Coverage evidence still describes only a baseline that accounts
    # for every collected node.
    coverage: dict = {"recorded": [], "missing_evidence": [], "deferred": True}
    waveforms: dict = {}
    try:
        waveforms = prune_baseline_waveforms(workspace, output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        summary.diagnostics.append(f"waveform pruning failed: {error}")
        waveforms = {"error": str(error)}
    if not set(manifest.collected) - set(summary.outcomes):
        coverage["deferred"] = False
        try:
            roots = []
            for batch in summary.batch_refs:
                saved = json.loads((output / batch).read_text())
                archived = saved.get("context", {}).get("report_snapshot_path")
                if not archived:
                    raise ValueError("Baseline report needs the invocation snapshot returned by RunTestCases")
                candidate = (workspace / archived).resolve()
                candidate.relative_to(test_report_root(workspace) / "invocations")
                roots.append(candidate)
            coverage = capture_baseline_coverage(workspace, output, roots)
        except (OSError, ValueError, KeyError, TypeError) as error:
            summary.diagnostics.append(f"coverage capture failed: {error}")
            coverage["error"] = str(error)
    atomic_write_json(output / index.replay_summary_path, summary.model_dump(mode="json", by_alias=True))
    atomic_write_json(output / "review_index.json", index.model_dump(mode="json", by_alias=True))
    return {"imported": len(observed), "remaining": len(collected - set(summary.outcomes)),
            "report_ref": relative, "baseline_id": manifest.baseline_id, **coverage, "waveforms": waveforms,
            "failure_evidence": {"run_log": run_log, "aligned": len(digests), "ambiguous": len(ambiguous),
                                 "prefilled_cases": len(prefilled_cases),
                                 "prefilled_fields": prefilled_fields}}
