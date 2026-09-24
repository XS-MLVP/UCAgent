"""Run existing verification tests with UCAgent in an isolated workspace."""
import copy
from dataclasses import asdict
from pathlib import Path
import shutil

from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash
from bug_review.benchmark_workflow.toffee_parser import parse_test_executions
from bug_review.benchmark_workflow.test_source_parser import analyze_tests
from .tasks import read_object
from .case_analysis import FAILED, canonical_node, failure_inventory, source_evidence
from bug_review.benchmark_workflow.report_inventory import validate_report_inventory


def execute_suite(manifest, directory):
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
    shutil.copytree(source, runtime, ignore=shutil.ignore_patterns(".git", ".ucagent", "__pycache__"))
    relative_tests = tests.relative_to(source)
    for old in (runtime / relative_tests / "data").glob("toffee_tmp_*"):
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
    runner = RunUnityChipTest(workspace=str(runtime))
    report, stdout, stderr = runner.do(
        test_dir_or_file=str(relative_tests.parent), pytest_ex_args=relative_tests.name,
        return_stdout=True, return_stderr=True, timeout=300,
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


def prepare_replay_inputs(item, root):
    path = Path(root) / "replay/input.json"
    if path.exists():
        return read_object(path)
    replayed = copy.deepcopy(item)
    executions = {}
    for graph in replayed["run_graphs"]:
        manifest = graph["manifest"]
        result = execute_suite(manifest, Path(root) / "replay/runs" / manifest["run_key"])
        generated = [asdict(row) for row in parse_test_executions(read_object(result["report_path"]))]
        if not generated:
            raise ValueError("pytest report contains no test executions; cannot complete replay")
        runtime = result["replay_workspace"]
        tests = runtime["replay_tests_root"]
        nodeids = [row["nodeid"] for row in generated]
        graph.setdefault("test_sources", {}).update({key: asdict(value) for key, value in
            analyze_tests(tests, nodeids, str(Path(tests) / "data")).items()})
        graph["tests"] = graph.get("tests", []) + generated
        executions[manifest["run_key"]] = {**result, "tests": generated}
    replayed["failure_cases"] = failure_inventory(replayed)
    for case in replayed["failure_cases"]:
        case["sources"] = source_evidence(case)
        execution = executions[case["run_key"]]
        observed = [row for row in execution["tests"] if canonical_node(row["nodeid"]) == case["nodeid"]]
        failed = any(row["outcome"] in FAILED or any(phase["outcome"] in FAILED for phase in row["phases"])
                     for row in observed)
        status = "reproduced" if failed else "not_reproduced_same_snapshot" if observed else "testcase_not_collected"
        case["suite_replay"] = {"status": status, "observed_tests": observed,
                                **{key: execution[key] for key in ("execution", "stdout", "stderr", "report_path", "replay_workspace")}}
    replayed["suite_executions"] = executions
    replayed["reported_replay_validation"] = {
        manifest["run_key"]: validate_report_inventory(
            graph.get("reported_bug_inventory", {}), executions[manifest["run_key"]]["tests"]
        )
        for graph in replayed["run_graphs"]
        for manifest in [graph["manifest"]]
    }
    atomic_write_json(path, replayed)
    return replayed
