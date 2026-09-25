"""Run existing verification tests with UCAgent in an isolated workspace."""
from pathlib import Path
import shutil

from .analysis_core.task_manifest import atomic_write_json, stable_hash
from .tasks import read_object


def execute_suite(manifest, directory, timeout=300):
    """Run one complete UnityTest suite in a fresh isolated source copy."""
    from ucagent.tools.testops import RunUnityChipTest

    directory = Path(directory).resolve()
    result_path = directory / "execution.json"
    source = Path(manifest.get("workspace_root") or "")
    tests = Path(manifest.get("tests_root") or "")
    if not manifest.get("tests_root") or not tests.is_dir() or not tests.is_relative_to(source):
        raise ValueError(f"replay tests_root unavailable for {manifest['dut']}; cannot claim zero failures")
    if result_path.exists():
        result = read_object(result_path)
        if result["manifest_hash"] != stable_hash(manifest):
            raise ValueError("pytest source changed; prepare a new workspace")
        if result["execution"].get("invocation_success") and result["execution"].get("report_has_tests"):
            return result
    runtime = directory / "workspace"
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(source, runtime, ignore=shutil.ignore_patterns(
        ".git", ".ucagent", "__pycache__", "toffee_tmp_*"))
    snapshot = source / ".ucagent/runtime_config.json"
    if snapshot.is_file():
        destination = runtime / ".ucagent/runtime_config.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot, destination)
    relative_tests = tests.relative_to(source)
    runner = RunUnityChipTest(workspace=str(runtime))
    report, stdout, stderr = runner.do(
        test_dir_or_file=str(relative_tests.parent), pytest_ex_args=relative_tests.name,
        return_stdout=True, return_stderr=True, timeout=timeout,
        pytest_ex_env={"UC_IS_IMP_TEMPLATE": "false", "UCAGENT_WORKSPACE": str(runtime), "UCA_PYTEST_ARGS": ""})
    result = {"manifest_hash": stable_hash(manifest), "execution": report["execution"],
              "stdout": stdout, "stderr": stderr,
              "report_path": str(runtime / "uc_test_report/toffee_report.json"),
              "replay_workspace": {"replay_workspace_root": str(runtime),
                                   "replay_tests_root": str(runtime / relative_tests)}}
    atomic_write_json(result_path, result)
    if not result["execution"].get("invocation_success") or not result["execution"].get("report_has_tests"):
        raise ValueError(f"pytest replay blocked: {result['execution'].get('diagnostic_code')}; see {result_path}")
    return result
