"""Run Toffee with the selected interpreter and bind validated artifacts to source bytes."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
from importlib import metadata
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4
from urllib.parse import urlsplit

from .paths import digest, local_path, source_identity, write_json
from .layout import project_layout
from .project import package_root
from .process import execute


def runtime_info():
    """Reject a mixed or incorrect Toffee installation in the selected interpreter."""
    try:
        import toffee
        version = metadata.version("uc-toffee")
    except (ImportError, metadata.PackageNotFoundError) as error:
        raise ValueError("The test runtime is unavailable; ask the operator to repair the ToffeeUT environment") from error
    for legacy in ("pytoffee", "toffee-test"):
        try:
            metadata.version(legacy)
        except metadata.PackageNotFoundError:
            continue
        raise ValueError("The test runtime contains conflicting packages; ask the operator to repair the ToffeeUT environment")
    if not all(hasattr(toffee, key) for key in ("Execution", "CoverGroupDef", "Scoreboard")):
        raise ValueError("The active test runtime is incompatible; ask the operator to repair the ToffeeUT environment")
    return {"python": sys.executable, "toffee_version": version, "toffee_module": toffee.__file__}


def _signature(workspace, payload, *, create=False):
    """Sign automation evidence; the private key never enters prompts or snapshots."""
    path = local_path(workspace, ".ucagent/toffee_ut.key")
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(os.urandom(32))
        except FileExistsError:
            pass
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hmac.new(path.read_bytes(), encoded, hashlib.sha256).hexdigest()


class RunSourceStale(ValueError):
    """The signed receipt describes a previous set of test inputs."""

    def __init__(self, message, changed=()):
        super().__init__(message)
        self.changed = tuple(changed)


def validate_run(workspace, project, record, *, current=True):
    """Verify a tool receipt, raw verdicts, hashes, source freshness and native build inputs."""
    record = dict(record)
    signature = record.pop("signature", "")
    if not hmac.compare_digest(signature, _signature(workspace, record)):
        raise ValueError("Run receipt is missing or changed; call RunToffee again")
    if type(record.get("line_coverage_required")) is not bool or not isinstance(record.get("waveforms"), dict):
        raise ValueError("Run receipt needs explicit coverage requirements and waveform identities; call RunToffee again")
    root = local_path(workspace, project, allow_root=True).resolve()
    run = local_path(root, record["run"])
    if not run.is_relative_to(root / "results"):
        raise ValueError("Run must be below results")
    for relative, expected in record["files"].items():
        path = local_path(run, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Run artifact changed or is missing: {relative}")
    if record["source_before"] != record["source_after"]:
        raise ValueError("Sources changed during the run; rerun after edits finish")
    if current:
        actual, signed = source_identity(root, workspace, record["extra_inputs"]), record["source_after"]
        if actual != signed:
            changed = sorted(name for name in actual.keys() | signed.keys() if actual.get(name) != signed.get(name))
            raise RunSourceStale("Run is stale for current sources", changed)
    cases = json.loads((run / "cases.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if cases["errors"] or cases["collect_only"] or not cases["cases"]:
        raise ValueError("Run has collection errors, incomplete evidence or no executed tests")
    if manifest.get("state") != "committed" or not manifest.get("coverage_complete"):
        raise ValueError("Toffee did not commit complete run artifacts")
    from toffee.outcomes import case_status
    counts = dict(Counter(case_status(row["phases"]) for row in cases["cases"].values()))
    if (set(cases["collection"]) != set(cases["cases"]) or len(cases["collection"]) != len(cases["cases"])
            or any(row["status"] != case_status(row["phases"]) for row in cases["cases"].values())
            or counts != cases["counts"] or counts != manifest.get("tests")):
        raise ValueError("RUN_EVIDENCE_MISMATCH: case outcomes differ from manifest")
    if record["returncode"] != cases["exitstatus"] or record["returncode"] != manifest.get("pytest_exitstatus"):
        raise ValueError("RUN_EVIDENCE_MISMATCH: process exit status differs")
    if "INCOMPLETE" in cases["counts"]:
        raise ValueError("At least one test has incomplete execution phases")
    for artifact in manifest.get("artifacts", []):
        path = Path(artifact["path"])
        if not path.resolve().is_relative_to(run.resolve()) or digest(path) != artifact["sha256"]:
            raise ValueError("Toffee artifact identity mismatch")
        for filename, expected in artifact.get("build", {}).get("files", {}).items():
            path = Path(filename)
            if not path.resolve().is_relative_to(Path(workspace).resolve()) or not path.is_file() or digest(path) != expected:
                raise ValueError(f"Native build input changed or is outside the workspace: {filename}")
    if not isinstance(record["full_selection"], bool) or record["full_selection"] and cases.get("deselected"):
        raise ValueError("Run selection omits collected cases")
    for case in cases["cases"].values():
        for wave in case.get("waveforms", []):
            path = local_path(root, wave["path"])
            if (not path.is_relative_to(run) or wave["path"] not in record["waveforms"]
                    or wave["native_dut"] not in case["native_duts"]):
                raise ValueError("Waveform is not bound to this run and case's actual native DUT")
            # A stored observation remains verifiable after optional waveform
            # cleanup; an existing but modified original is never accepted.
            if path.exists() and digest(path) != record["waveforms"][wave["path"]]:
                raise ValueError("Run waveform artifact changed")
    return {"record": {**record, "signature": signature}, "cases": cases, "manifest": manifest}


def current_run(workspace, project):
    """Read the current signed receipt without falling back to a historical run."""
    root = local_path(workspace, project, allow_root=True)
    return validate_run(workspace, project, json.loads((root / "results/latest.json").read_text()))


def archived_run(workspace, project, run, *, current=True):
    """Read an explicit signed run, requiring current sources unless used as a baseline."""
    if not isinstance(run, str) or not re.fullmatch(r"results/[a-zA-Z0-9][a-zA-Z0-9_.-]*", run):
        raise ValueError("Select one project-relative run: results/<run-id>")
    root = local_path(workspace, project, allow_root=True).resolve()
    folder = local_path(root, run)
    receipt = local_path(folder, "receipt.json")
    if folder.resolve() != folder or receipt.is_symlink():
        raise ValueError("Select a run and receipt by their original paths, not through links")
    record = json.loads(receipt.read_text())
    if not isinstance(record, dict) or record.get("run") != run:
        raise ValueError("Archive path does not match the signed run identity")
    return validate_run(workspace, project, record, current=current)


def default_targets(root, layout):
    """Resolve the full-selection paths shared by preflight and the runner."""
    defaults = list(layout["tests"])
    if (root / "testbenches/shared/tests").is_dir():
        defaults.append("testbenches/shared/tests")
    return defaults


def run_tests(workspace, dut, project="ut_project", targets=None, *, keyword="", markers="",
              workers=1, timeout=1200, seed=1, cancelled=lambda: False, progress=lambda message: None,
              python_paths=(), waveforms=True, line_coverage_required=True, expected_sources=None):
    """Execute selected real tests and retain partial logs on cancellation or timeout."""
    root = local_path(workspace, project, allow_root=True)
    results = local_path(workspace, (Path(project) / "results").as_posix())
    # Reject stale success even if this new launch fails before pytest starts.
    latest = local_path(workspace, (Path(project) / "results/latest.json").as_posix())
    if expected_sources is None:
        latest.unlink(missing_ok=True)
    layout = project_layout(workspace, dut, project)
    from .audit import contracts
    _, requirements = contracts(workspace, dut, project)
    extra_inputs = sorted({row["source"].split("#", 1)[0] for row in requirements.values()
                           if row["basis"] != "open" and not urlsplit(row["source"]).scheme})
    runtime = runtime_info()
    if type(waveforms) is not bool or type(line_coverage_required) is not bool:
        raise ValueError("waveforms and line_coverage_required must be booleans")
    if (type(workers) is not int or workers < 1 or type(timeout) is not int or timeout < 1
            or type(seed) is not int or not 1 <= seed <= 2**31 - 1):
        raise ValueError("workers/timeout must be positive integers and seed must be in [1, 2147483647]")
    if not (root / "pytest.ini").is_file():
        raise ValueError("Scaffold or adopt a project with pytest.ini before running tests")
    defaults = default_targets(root, layout)
    if targets is not None and not isinstance(targets, (list, tuple)):
        raise ValueError("targets must be a list of project-relative test paths")
    targets = list(dict.fromkeys(targets or defaults))
    for selector in targets:
        if not isinstance(selector, str) or selector.startswith("-"):
            raise ValueError("Use project-relative pytest paths, not command-line options")
        path = local_path(workspace, (Path(project) / selector.split("::", 1)[0]).as_posix())
        if not path.is_relative_to(root / "testbenches") or not path.exists():
            raise ValueError(f"Test target must exist below testbenches: {selector}")
    if expected_sources is not None:
        before = source_identity(root, workspace, extra_inputs)
        if before != expected_sources:
            return {"ok": False, "error_code": "UT_COVERAGE_PREFLIGHT", "error": "Inputs changed after targeted preflight",
                    "next_action": "Verify the current exact-node batch before requesting full execution."}
        latest.unlink(missing_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    destination = local_path(root, f"results/{run_id}")
    # Use Toffee's managed pytest backend directly, preserving the resolved
    # plugin import roots instead of the CLI prepending its installation root.
    command = [sys.executable, "-m", "pytest", "-p", "toffee._pytest_plugin",
               f"--toffee-output={destination}", "--toffee-export-coverage-json",
               "-p", "pytest_asyncio.plugin", "-p", "toffee_ut.pytest_plugin",
               f"--toffee-ut-cases={destination / 'cases.json'}",
               f"--toffee-ut-seed={seed}", f"--junitxml={destination / 'junit.xml'}",
                "-o", "addopts=", f"-k={keyword}", f"-m={markers}", *targets]
    if workers > 1:
        command.extend(["-p", "xdist", "-n", str(workers), "--dist=load", "--max-worker-restart=0"])
    if waveforms:
        command.append("--toffee-ut-waveforms")
    env = os.environ.copy()
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(key, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for path in python_paths:
        if not Path(path).is_absolute() or not Path(path).is_dir():
            raise ValueError("The runtime import paths are stale; ask the operator to restart UCAgent")
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys([
        *map(str, python_paths), str(Path(__file__).resolve().parents[1]), str(package_root(root)),
        str(Path(workspace).resolve()), *filter(None, env.get("PYTHONPATH", "").split(os.pathsep))]))
    if expected_sources is None:
        before = source_identity(root, workspace, extra_inputs)
    stdout_path, stderr_path = results / f".{run_id}.stdout", results / f".{run_id}.stderr"
    returncode, interrupted = execute(command, root, stdout_path, stderr_path, timeout, cancelled, progress, env)
    destination.mkdir(exist_ok=True)
    stdout_path.replace(destination / "stdout.log")
    stderr_path.replace(destination / "stderr.log")
    if interrupted:
        return {"ok": False, "error_code": interrupted.upper(), "run": f"results/{run_id}",
                "error": "Test execution did not finish.", "next_action": "Inspect run logs and rerun the same targets."}
    case_file = destination / "cases.json"
    case_data = json.loads(case_file.read_text()) if case_file.is_file() else {}
    wave_paths = {wave["path"] for case in case_data.get("cases", {}).values() for wave in case.get("waveforms", [])}
    waves = {relative: digest(local_path(root, relative)) for relative in wave_paths}
    files = {path.relative_to(destination).as_posix(): digest(path) for path in destination.rglob("*")
             if path.is_file() and path.relative_to(root).as_posix() not in waves}
    record = {"schema_version": 1, "run": f"results/{run_id}", "dut": dut,
              "selection": {"targets": targets, "keyword": keyword, "markers": markers},
              "full_selection": set(targets) == set(defaults) and not keyword and not markers and not case_data.get("deselected"),
               "runtime": runtime, "seed": seed, "returncode": returncode, "files": files,
               "line_coverage_required": line_coverage_required,
               "waveforms": waves,
              "extra_inputs": extra_inputs,
              "source_before": before, "source_after": source_identity(root, workspace, extra_inputs)}
    record["signature"] = _signature(workspace, record, create=True)
    write_json(destination / "receipt.json", record)
    try:
        checked = validate_run(workspace, project, record)
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as error:
        return {"ok": False, "error_code": "RUN_INCOMPLETE", "run": record["run"],
                "error": str(error), "next_action": "Inspect run logs, fix collection/runtime errors and rerun."}
    write_json(results / "latest.json", record)
    cases = checked["cases"]["cases"]
    failures = [{"nodeid": nodeid, "status": row["status"],
                 "phases": {key: value for key, value in row["phases"].items() if value.get("failure")}}
                for nodeid, row in cases.items() if row["status"] in {"FAIL", "ERROR", "XPASS", "INCOMPLETE"}]
    return {"ok": True, "run": record["run"], "tests": checked["cases"]["counts"],
            "full_selection": record["full_selection"], "failures": failures[:12],
            "failures_total": len(failures), "artifact_manifest": f"{record['run']}/manifest.json",
            "next_action": "Classify each failure and unresolved scenario; then call Check."}
