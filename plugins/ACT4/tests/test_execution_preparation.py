"""Validate review launch preparation without weakening evidence or optional-tool contracts."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from ucagent_act4.checkers import act4_review_checker as module
from ucagent_act4 import environment
from test_act4_environment import plan_for
from test_act4_review_checker import ReviewHarness
from test_act4_review_checker import isolate_optional_simulators as isolate_optional_simulators


@pytest.mark.parametrize("local_input", [False, True])
def test_preparation_runs_only_environment_jobs(tmp_path: Path, monkeypatch, local_input: bool) -> None:
    """Use either source kind without native execution, source mutation or formal evidence."""
    harness = ReviewHarness(tmp_path)
    if local_input:
        (harness.source / ".git").rename(tmp_path / "saved-git")
        harness.source.rename(tmp_path / "local-module")
        harness.source = tmp_path / "local-module"
    source_state = module.tree_state(harness.source)
    commands = []
    execute = module.execute_command

    def environment_only(argv, *args, **kwargs):
        """Reject native validation commands during preparation."""
        commands.append(argv)
        assert "check.py" not in argv
        return execute(argv, *args, **kwargs)

    monkeypatch.setattr(module, "execute_command", environment_only)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed, result
    assert len(commands) == result["environment_jobs"] == 1
    assert result["preparation_only"] and result["ready"] and not result["native_jobs_run"]
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["started_at"] and report["duration_seconds"] >= 0
    assert all(job["status"] == "not_run" for job in report["jobs"] if job["purpose"] != "environment")
    assert not (harness.output / "evidence-before.json").exists()
    assert not (harness.output / "candidate").exists()
    assert module.tree_state(harness.source) == source_state
    passed, result = harness.checker("audit").do_check(is_complete=True)
    assert not passed and "run_commands" in result["error"]


@pytest.mark.parametrize("options,phase", [
    ({"prepare_environment": True, "is_complete": True}, "audit"),
    ({"prepare_environment": True, "run_commands": True}, "audit"),
    ({"prepare_environment": True, "refresh_tools": True}, "audit"),
    ({"prepare_environment": True, "experiment": {"action": "prepare", "id": "E1"}}, "audit"),
    ({"prepare_environment": True}, "plan"),
    ({"prepare_environment": True}, "repair"),
    ({"prepare_environment": True}, "final"),
    ({"prepare_environment": "true"}, "audit"),
    ({"prepare_environment": 1}, "audit"),
    ({"prepare_environment": None}, "audit"),
])
def test_preparation_rejects_invalid_controls(tmp_path: Path, monkeypatch, options: dict, phase: str) -> None:
    """Reject invalid stage controls before running even an environment probe."""
    harness = ReviewHarness(tmp_path, accept_plan=False)

    def unexpected_execution(*args, **kwargs):
        """Fail when invalid controls reach any command execution."""
        pytest.fail("Invalid preparation controls must not execute commands")

    monkeypatch.setattr(module, "execute_command", unexpected_execution)
    passed, result = harness.checker(phase).do_check(**options)
    assert not passed and "prepare_environment" in result["error"]
    assert not (harness.output / "execution-preparation.json").exists()


@pytest.mark.parametrize("missing", ["plan", "scope"])
def test_preparation_requires_independent_plan_and_scope(tmp_path: Path, monkeypatch, missing: str) -> None:
    """Do not read assets or freeze a baseline before accepting the independent ISA plan."""
    harness = ReviewHarness(tmp_path, accept_plan=missing != "plan")
    if missing == "scope":
        (harness.output / "scope.yaml").unlink()

    def unexpected_execution(*args, **kwargs):
        """Reject entry into the asset executor before its inputs exist."""
        pytest.fail("Preparation cannot bypass the ISA plan or scope")

    monkeypatch.setattr(module.ACT4ReviewChecker, "_execute_jobs", unexpected_execution)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed and ("isa-plan" if missing == "plan" else "scope.yaml") in result["error"]
    assert not (harness.output / "baseline").exists()


@pytest.mark.parametrize("simulator", ["questa", "vcs", "xcelium"])
def test_optional_environment_failure_is_a_limitation(tmp_path: Path, simulator: str) -> None:
    """Keep preparation and required validation usable when a commercial simulator is absent."""
    harness = ReviewHarness(tmp_path)
    optional = deepcopy(harness.scope["jobs"][-1])
    optional.update(id="optional-simulator", optional_tool=simulator, probe=["absent-review-simulator"])
    harness.scope["jobs"].append(optional)
    harness.scope["jobs"][3].update(optional_tool=simulator, needs=["environment", "build", "optional-simulator"])
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed and result["ready"], result
    assert not result["failed_jobs"] and result["limitation_count"] == 2
    assert not (harness.output / "prepare-before-optional-simulator.log").exists()
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert all(job["status"] == "passed" for job in evidence["jobs"] if not job["optional"])
    assert all(job["status"] == "unavailable" for job in evidence["jobs"] if job["optional"])


def test_declared_unavailable_native_lane_is_a_limitation(tmp_path: Path) -> None:
    """Respect a documented missing validation route without inventing a launch failure."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][4].update(disposition="unavailable", reason="Local input has no runnable lint entry")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed and result["limitation_count"] == 1, result
    assert result["limitations"][0]["id"] == "lint"


def test_preparation_reports_independent_failures_and_blocked_jobs(tmp_path: Path) -> None:
    """Collect launch errors without executing dependent native jobs."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][-1]["cwd"] = "missing-environment-directory"
    other = deepcopy(harness.scope["jobs"][-1])
    other.update(id="other-environment", cwd=".", probe=["absent-review-entry"])
    harness.scope["jobs"].append(other)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed and result["error_code"] == "act4_execution_not_ready"
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    jobs = {job["id"]: job for job in report["jobs"]}
    assert jobs["environment"]["attempts"][0]["diagnostic"]["error_code"] == "act4_execution_cwd"
    assert jobs["other-environment"]["attempts"][0]["diagnostic"]["error_code"] == "act4_execution_entry"
    assert jobs["generation"]["preparation"] == {"status": "blocked", "blocked_by": ["environment"]}
    assert not (harness.output / "before-generation.log").exists()


def test_preparation_finds_native_launch_errors(tmp_path: Path) -> None:
    """Find independent generation and lint entry errors before any native work."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][0]["argv"] = ["absent-generation-entry"]
    harness.scope["jobs"][4]["cwd"] = "missing-lint-directory"
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed and {job["id"] for job in result["failed_jobs"]} == {"generation", "lint"}
    assert not (harness.output / "before-generation.log").exists()


@pytest.mark.parametrize("create_directory", [False, True])
def test_deferred_paths_are_rechecked_during_execution(tmp_path: Path, create_directory: bool) -> None:
    """Allow generated directories provisionally but require them at actual command launch."""
    harness = ReviewHarness(tmp_path)
    if create_directory:
        script = harness.source / "check.py"
        script.write_text(script.read_text() + '\nPath("generated-build").mkdir(exist_ok=True)\n')
    harness.scope["jobs"][1].update(cwd="generated-build", argv=[sys.executable, "../check.py"],
        artifacts=[{"path": "generated-build/fixture.elf", "kind": "elf"}])
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed and result["deferred_job_count"] == 1, result
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    build = next(job for job in evidence["jobs"] if job["id"] == "build")
    assert build["status"] == ("passed" if create_directory else "unavailable")
    if not create_directory:
        assert build["diagnostic"]["error_code"] == "act4_execution_cwd"


@pytest.mark.parametrize("chained", [False, True])
def test_all_environments_precede_native_execution(tmp_path: Path, monkeypatch, chained: bool) -> None:
    """Prioritize independent and chained environments even when native work is already ready."""
    harness = ReviewHarness(tmp_path)
    extra = deepcopy(harness.scope["jobs"][-1])
    extra.update(id="late-environment", probe=[sys.executable, "-c", "print('Python 3 late probe')"])
    if chained:
        extra["needs"] = ["environment"]
    harness.scope["jobs"].append(extra)
    harness.write("scope.yaml", harness.scope)
    commands = []
    execute = module.execute_command

    def recording_execute(argv, *args, **kwargs):
        """Record real launch order while retaining normal execution behavior."""
        commands.append(argv)
        return execute(argv, *args, **kwargs)

    monkeypatch.setattr(module, "execute_command", recording_execute)
    harness.checker("audit").do_check(run_commands=True)
    assert commands[:2] == [harness.scope["jobs"][-2]["probe"], extra["probe"]]
    assert commands[2] == harness.scope["jobs"][0]["argv"]


@pytest.mark.parametrize("preparation", [False, True])
def test_environment_cannot_depend_on_native_work(tmp_path: Path, preparation: bool) -> None:
    """Reject an acyclic environment-to-native dependency before any execution."""
    harness = ReviewHarness(tmp_path)
    extra = deepcopy(harness.scope["jobs"][-1])
    extra.update(id="late-environment", needs=["generation"])
    harness.scope["jobs"].append(extra)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=preparation, run_commands=not preparation)
    assert not passed and "Environment jobs may depend only" in result["error"]
    assert result["errors"][0]["field"] == "scope.jobs[6].needs"
    assert not (harness.output / "baseline").exists()


def test_preparation_preserves_existing_evidence_and_review(tmp_path: Path) -> None:
    """Do not invalidate formal evidence or advance review tasks when only probing launch readiness."""
    harness = ReviewHarness(tmp_path)
    harness.audit()
    retained = {path: path.read_bytes() for path in harness.output.rglob("*") if path.is_file()}
    state = deepcopy(harness.data)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed, result
    assert all(path.read_bytes() == content for path, content in retained.items())
    assert harness.data == state
    assert harness.checker("audit").do_check(is_complete=True)[0]


def test_preparation_reuses_first_stage_tool_receipt(tmp_path: Path, monkeypatch) -> None:
    """Use receipt PATH entries even when the parent process cannot find the prepared tool."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    harness = ReviewHarness(tmp_path)
    directory = harness.output.parent / "environment"
    directory.mkdir()
    environment.prepare(directory, plan_for(directory), timeout=60)
    harness.data[environment.state_key(directory)] = environment.sha256(directory / "receipt.json")
    harness.scope["jobs"][-1].update(probe=["act4-fixture", "--version"], expected_output="act4-fixture 1.0")
    harness.write("scope.yaml", harness.scope)
    assert module.shutil.which("act4-fixture") is None
    assert harness.checker("audit").do_check(prepare_environment=True)[0]
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert evidence["jobs"][-1]["status"] == "passed"
    assert not evidence["jobs"][-1]["installed"]


def test_preparation_installs_and_reprobes_project_tool(tmp_path: Path) -> None:
    """Persist project-specific tools while requiring a fresh probe on later executions."""
    harness = ReviewHarness(tmp_path)
    script = f"#!{sys.executable}\nprint('project-ready')\n"
    harness.scope["jobs"][-1].update(probe=["review-project-tool"], expected_output="project-ready",
        install=[sys.executable, "-c", f"from pathlib import Path; tool = Path('{{TOOLS}}/bin/review-project-tool'); tool.write_text({script!r}); tool.chmod(0o755)"])
    harness.write("scope.yaml", harness.scope)
    assert harness.checker("audit").do_check(prepare_environment=True)[0]
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["jobs"][-1]["installed"] and len(report["jobs"][-1]["attempts"]) == 3
    harness.checker("audit").do_check(run_commands=True)
    evidence = json.loads((harness.output / "evidence-before.json").read_text())
    assert not evidence["jobs"][-1]["installed"] and len(evidence["jobs"][-1]["attempts"]) == 1
    (harness.output / "tools/bin/review-project-tool").write_text(f"#!{sys.executable}\nraise SystemExit(7)\n")
    harness.scope["jobs"][-1].pop("install")
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed, result


@pytest.mark.parametrize("version_ok", [False, True])
@pytest.mark.parametrize("origin_ok", [False, True])
def test_preparation_checks_declared_python_import_probe(tmp_path: Path, monkeypatch, version_ok: bool, origin_ok: bool) -> None:
    """Validate the declared interpreter version and import origin inside the isolated input."""
    harness = ReviewHarness(tmp_path)
    import_root = harness.source if origin_ok else tmp_path / "foreign-python"
    import_root.mkdir(exist_ok=True)
    (import_root / "review_fixture.py").write_text("VALUE = 1\n")
    if not origin_ok:
        monkeypatch.setenv("PYTHONPATH", str(import_root))
    expected = sys.version_info.major if version_ok else 99
    harness.scope["jobs"][-1].update(probe=[sys.executable, "-c",
        "import review_fixture, sys; from pathlib import Path; "
        f"assert sys.version_info.major == {expected}; "
        "assert Path(review_fixture.__file__).resolve().is_relative_to(Path.cwd()); print('Python 3')"])
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed is (version_ok and origin_ok), result
    assert not (harness.source / "__pycache__").exists()


def test_preparation_timeout_is_bounded(tmp_path: Path) -> None:
    """Kill a timed-out probe and report dependent native tasks without launching them."""
    harness = ReviewHarness(tmp_path)
    harness.scope["jobs"][-1].update(probe=[sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=1)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert not passed, result
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert report["jobs"][-1]["attempts"][0]["status"] == "timeout"
    assert report["jobs"][0]["preparation"]["status"] == "blocked"
    assert not (harness.output / "before-generation.log").exists()


@pytest.mark.parametrize("optional", [False, True])
def test_preparation_bounds_failure_and_limitation_summaries(tmp_path: Path, optional: bool) -> None:
    """Bound both failure and limitation output while retaining all job records on disk."""
    harness = ReviewHarness(tmp_path)
    for index in range(25):
        job = deepcopy(harness.scope["jobs"][-1])
        job.update(id=f"missing-{index}", probe=["absent-review-tool"])
        if optional:
            job["optional_tool"] = "questa"
        harness.scope["jobs"].append(job)
    harness.write("scope.yaml", harness.scope)
    passed, result = harness.checker("audit").do_check(prepare_environment=True)
    assert passed is optional, result
    entries, count, omitted = ("limitations", "limitation_count", "omitted_limitations") if optional else ("failed_jobs", "failed_job_count", "omitted_jobs")
    assert len(result[entries]) == 20 and result[count] == 25 and result[omitted] == 5
    report = json.loads((harness.output / "execution-preparation.json").read_text())
    assert len(report["jobs"]) == 31


@pytest.mark.parametrize("defect", ["cwd", "entry", "permission"])
def test_launch_precheck_rejects_unusable_paths(tmp_path: Path, monkeypatch, defect: str) -> None:
    """Explain a known launch failure without starting a subprocess."""
    cwd, argv = tmp_path, [sys.executable, "--version"]
    if defect == "cwd":
        cwd = tmp_path / "missing"
    elif defect == "entry":
        argv = ["absent-review-entry"]
    else:
        entry = tmp_path / "not-executable"
        entry.write_text("exit 0\n")
        argv = [str(entry)]

    def unexpected_spawn(*args, **kwargs):
        """Reject launching a command already known to be unavailable."""
        pytest.fail("Invalid launch must not spawn a process")

    monkeypatch.setattr(module.subprocess, "Popen", unexpected_spawn)
    result = module.execute_command(argv, cwd, {}, tmp_path / "command.log", 10)
    assert result["status"] == "unavailable"
    assert result["diagnostic"]["error_code"] == ("act4_execution_cwd" if defect == "cwd" else "act4_execution_entry")


@pytest.mark.parametrize("program,path", [("probe", "bin"), ("bin/probe", ""), ("probe", "bin:")])
def test_launch_precheck_resolves_child_relative_paths(tmp_path: Path, monkeypatch, program: str, path: str) -> None:
    """Resolve relative argv and PATH entries against the actual child directory."""
    cwd = tmp_path / "child"
    (cwd / "bin").mkdir(parents=True)
    entry = cwd / "bin/probe"
    entry.write_text("#!/bin/sh\nprintf 'ready\\n'\n")
    entry.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    result = module.execute_command([program], cwd, {"PATH": path}, tmp_path / "command.log", 10)
    assert result["status"] == "passed", result
