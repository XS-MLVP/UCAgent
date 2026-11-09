"""Verify isolated environment preparation, early launch diagnostics and full-evidence separation."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from act4_privileged_suite.checkers import act4_review_checker as module
from test_act4_review_checker import ReviewHarness


@pytest.mark.parametrize("phase", ["inventory", "audit"])
def test_preparation_runs_only_environment_probes(tmp_path: Path, monkeypatch, phase: str) -> None:
    """Prepare baseline execution without running native lanes or manufacturing their evidence."""
    harness = ReviewHarness(tmp_path)
    if phase == "audit":
        assert harness.checker("inventory").do_check()[0]
    commands = []
    execute = module.execute_command

    def environment_only(argv, cwd, env, log, timeout, append=False):
        """Reject accidental native commands in preparation-only mode."""
        commands.append(argv)
        assert "check.py" not in argv
        return execute(argv, cwd, env, log, timeout, append)

    monkeypatch.setattr(module, "execute_command", environment_only)
    passed, result = harness.checker(phase).do_check(prepare_environment=True)
    assert passed, result
    assert result["preparation_only"] and result["native_jobs_run"] is False
    assert result["environment_jobs"] == 1 and len(commands) == 1
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["ready"] and report["kind"] == "execution_preparation"
    assert report["started_at"] and report["duration_seconds"] >= 0
    assert all(job["status"] == "not_run" for job in report["jobs"] if job["purpose"] != "environment")
    assert not (harness.output / "evidence-before.json").exists()
    assert not (harness.output / "candidate").exists()
    assert not (harness.source / "result.txt").exists()
    passed, result = harness.checker("audit").do_check()
    assert not passed and "run_commands" in result["error"]


@pytest.mark.parametrize("options,phase", [
    ({"prepare_environment": True, "is_complete": True}, "inventory"),
    ({"prepare_environment": True, "run_commands": True}, "audit"),
    ({"prepare_environment": True}, "authorize"),
    ({"prepare_environment": True}, "repair"),
    ({"prepare_environment": True}, "final"),
    ({"prepare_environment": "true"}, "inventory"),
    ({"prepare_environment": 1}, "inventory"),
])
def test_preparation_rejects_invalid_controls(tmp_path: Path, monkeypatch, options: dict, phase: str) -> None:
    """Preparation is a typed baseline Check operation and cannot replace Complete or authorization."""
    harness = ReviewHarness(tmp_path)

    def unexpected_execution(*args, **kwargs):
        """Fail if invalid stage controls reach subprocess execution."""
        pytest.fail("Invalid preparation controls must not run commands")

    monkeypatch.setattr(module, "execute_command", unexpected_execution)
    passed, result = harness.checker(phase).do_check(**options)
    assert not passed and "prepare_environment" in result["error"]
    assert not (harness.output / "execution-preparation.json").exists()


def test_preparation_collects_independent_environment_failures(tmp_path: Path) -> None:
    """Report failed probes together and mark dependent checks blocked without launching them."""
    harness = ReviewHarness(tmp_path)
    environment = harness.scope["jobs"][-1]
    environment.update(cwd="missing-directory")
    other = {**deepcopy(environment), "id": "other-env", "cwd": ".", "probe": ["absent-act4-preparation-tool"]}
    dependent = {**deepcopy(other), "id": "dependent-env", "needs": ["other-env"]}
    harness.scope["jobs"].extend([other, dependent])
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert not passed and result["error_code"] == "act4_execution_not_ready"
    assert {item["id"] for item in result["failed_jobs"]} == {"environment", "other-env", "dependent-env"}
    jobs = json.loads((harness.output / "execution-preparation.json").read_text())["jobs"]
    records = {job["id"]: job for job in jobs}
    assert records["environment"]["attempts"][0]["diagnostic"]["error_code"] == "act4_execution_cwd"
    assert records["other-env"]["attempts"][0]["diagnostic"]["error_code"] == "act4_execution_entry"
    assert records["dependent-env"]["status"] == "blocked"
    assert not (harness.output / "prepare-before-dependent-env.log").exists()
    assert all(job["status"] == "not_run" for job in jobs if job["purpose"] != "environment")


@pytest.mark.parametrize("version_ok", [True, False])
@pytest.mark.parametrize("origin_ok", [True, False])
def test_preparation_checks_real_python_version_and_import_origin(tmp_path: Path, monkeypatch, version_ok: bool, origin_ok: bool) -> None:
    """Use the declared interpreter probe to validate its version and exact checkout import root."""
    harness = ReviewHarness(tmp_path)
    module_root = harness.source if origin_ok else tmp_path / "external-package"
    module_root.mkdir(exist_ok=True)
    (module_root / "fixture_module.py").write_text("VALUE = 1\n")
    if not origin_ok:
        monkeypatch.setenv("PYTHONPATH", str(module_root))
    expected = sys.version_info.major if version_ok else 99
    harness.scope["jobs"][-1].update(probe=[sys.executable, "-c",
        "import fixture_module, sys; from pathlib import Path; "
        f"assert sys.version_info.major == {expected}; "
        "assert Path(fixture_module.__file__).resolve().is_relative_to(Path.cwd()); "
        "print(sys.executable); print(sys.version); print(fixture_module.__file__)"], expected_output="fixture_module.py")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert passed is (version_ok and origin_ok), result
    assert not (harness.source / "__pycache__").exists()


@pytest.mark.parametrize("chained", [False, True])
def test_full_execution_probes_all_environments_before_native_jobs(tmp_path: Path, monkeypatch, chained: bool) -> None:
    """A later independent or chained environment must precede an already-ready generation job."""
    harness = ReviewHarness(tmp_path)
    second = {**deepcopy(harness.scope["jobs"][-1]), "id": "second-env"}
    if chained:
        second["needs"] = ["environment"]
    harness.scope["jobs"].append(second)
    harness.write("scope.yaml", harness.scope)
    order = []
    execute = module.execute_command

    def observed_execution(argv, cwd, env, log, timeout, append=False):
        """Record the real scheduler order while retaining actual fixture execution."""
        order.append(log.stem)
        return execute(argv, cwd, env, log, timeout, append)

    monkeypatch.setattr(module, "execute_command", observed_execution)
    harness.audit()
    assert order[:2] == ["before-environment", "before-second-env"]
    assert order[2] == "before-generation"


def test_preparation_cannot_depend_on_native_generation(tmp_path: Path) -> None:
    """Reject a preparation dependency that would require native work during the environment pass."""
    harness = ReviewHarness(tmp_path)
    dependent = {**deepcopy(harness.scope["jobs"][-1]), "id": "late-env", "needs": ["generation"]}
    harness.scope["jobs"].append(dependent)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert not passed and "only on other environment jobs" in result["error"]
    assert not (harness.output / "execution-preparation.json").exists()


def test_preparation_keeps_existing_native_evidence_valid(tmp_path: Path) -> None:
    """Preparation uses separate logs and cannot overwrite or replace a completed native audit."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    paths = [harness.output / name for name in ["evidence-before.json", "review.yaml", "review.md", "authorization.json"]]
    paths.extend(harness.output / job["log"] for job in evidence["jobs"])
    hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    state = deepcopy(harness.data)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed, result
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == hashes
    assert harness.data == state
    assert harness.checker("audit").do_check()[0]


def test_preparation_reports_native_entry_problems_without_running_them(tmp_path: Path) -> None:
    """Catch independently checkable generation and lint launch errors in one preparation pass."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][0]["argv"] = ["missing-generation-entry"]
    harness.scope["jobs"][4]["cwd"] = "missing-lint-directory"
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert not passed and {item["id"] for item in result["failed_jobs"]} == {"generation", "lint"}
    assert result["native_jobs_run"] is False
    assert not (harness.output / "before-generation.log").exists()


def test_preparation_defers_paths_created_by_native_prerequisites(tmp_path: Path) -> None:
    """Do not reject a build directory that its generation prerequisite may legitimately create."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][1]["cwd"] = "generated-build-directory"
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert passed, result
    jobs = json.loads((harness.output / "execution-preparation.json").read_text())["jobs"]
    build = next(job for job in jobs if job["id"] == "build")
    assert build["status"] == "not_run" and build["preparation"]["status"] == "deferred"
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    build = next(job for job in evidence["jobs"] if job["id"] == "build")
    assert build["status"] == "unavailable"
    assert build["diagnostic"]["error_code"] == "act4_execution_cwd"


def test_preparation_timeout_blocks_dependents(tmp_path: Path) -> None:
    """Bound real probe execution and preserve the timeout without running dependent native jobs."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][-1].update(
        probe=[sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=1)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert not passed and result["native_jobs_run"] is False
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["jobs"][-1]["attempts"][0]["status"] == "timeout"
    assert report["jobs"][0]["preparation"]["status"] == "blocked"
    assert not (harness.output / "before-generation.log").exists()


def test_preparation_reprobes_persistently_installed_tools(tmp_path: Path) -> None:
    """Keep tools between isolated runs but probe again, including before full native evidence."""
    harness = ReviewHarness(tmp_path)
    tool = harness.output / "tools/bin/preparation-fixture"
    script = f"#!{sys.executable}\nprint('fixture-ready')\n"
    harness.scope["jobs"][-1].update(probe=["preparation-fixture"], expected_output="fixture-ready",
        install=[sys.executable, "-c",
            f"from pathlib import Path; p=Path('{{TOOLS}}/bin/preparation-fixture'); p.write_text({script!r}); p.chmod(0o755)"])
    harness.write("scope.yaml", harness.scope)
    assert harness.checker("inventory").do_check(prepare_environment=True)[0]
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert tool.is_file() and report["jobs"][-1]["installed"]
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    environment = evidence["jobs"][-1]
    assert environment["status"] == "passed" and not environment["installed"]
    assert len(environment["attempts"]) == 1
    tool.write_text(f"#!{sys.executable}\nraise SystemExit(7)\n")
    harness.scope["jobs"][-1].pop("install")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed, result
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["jobs"][-1]["attempts"][0]["exit_code"] == 7


def test_preparation_bounds_independent_failures(tmp_path: Path) -> None:
    """Retain all failures on disk while keeping the task-facing result bounded."""
    harness = ReviewHarness(tmp_path)
    environment = harness.scope["jobs"][-1]
    for number in range(25):
        harness.scope["jobs"].append({**deepcopy(environment), "id": f"failed-env-{number}",
                                      "probe": ["absent-preparation-fixture"]})
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("inventory").do_check(prepare_environment=True)
    assert not passed and len(result["failed_jobs"]) == 20
    assert result["failed_job_count"] == 25 and result["omitted_jobs"] == 5
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert sum(job["status"] == "unavailable" for job in report["jobs"]) == 25


@pytest.mark.parametrize("defect", ["cwd", "entry", "executable"])
def test_launch_precheck_rejects_invalid_paths_without_spawning(tmp_path: Path, monkeypatch, defect: str) -> None:
    """Produce a precise actionable diagnostic before attempting an invalid launch."""
    cwd = tmp_path
    argv = [sys.executable, "--version"]
    if defect == "cwd":
        cwd = tmp_path / "missing"
    elif defect == "entry":
        argv = ["missing-act4-entry"]
    else:
        entry = tmp_path / "not-executable"
        entry.write_text("exit 0\n")
        argv = [str(entry)]

    def unexpected_spawn(*args, **kwargs):
        """Fail if a known invalid command reaches process creation."""
        pytest.fail("Invalid launch must not spawn a process")

    monkeypatch.setattr(module.subprocess, "Popen", unexpected_spawn)
    result = module.execute_command(argv, cwd, {}, tmp_path / "command.log", 10)
    assert result["status"] == "unavailable" and result["diagnostic"]["next_action"]
    assert result["diagnostic"]["error_code"] == ("act4_execution_cwd" if defect == "cwd" else "act4_execution_entry")


@pytest.mark.parametrize("program,path", [("probe", "bin"), ("bin/probe", ""), ("probe", "bin:")])
def test_launch_precheck_resolves_paths_from_child_cwd(tmp_path: Path, monkeypatch, program: str, path: str) -> None:
    """Relative PATH and argv entries must resolve as the child process will resolve them."""
    cwd = tmp_path / "child"
    (cwd / "bin").mkdir(parents=True)
    entry = cwd / "bin/probe"
    entry.write_text("#!/bin/sh\nprintf 'ready\\n'\n")
    entry.chmod(0o755)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = module.execute_command([program], cwd, {"PATH": path}, tmp_path / "command.log", 10)
    assert result["status"] == "passed", result
