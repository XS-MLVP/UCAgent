"""Stage external UnityTest workspaces and execute their tests before analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

from bug_review.benchmark_workflow.task_manifest import atomic_write_json, stable_hash


PREPARATION_SCHEMA = "benchmark_prepared_inputs.v1"


def _is_unitytest_workspace(path: Path) -> bool:
    return (
        (path / ".ucagent/runtime_config.json").is_file()
        and (path / "unity_test/tests").is_dir()
        and any(child.is_dir() and child.name not in {"unity_test", "Guide_Doc", ".ucagent"}
                for child in path.iterdir())
    )


def _workspaces(source: Path) -> list[Path]:
    source = source.resolve()
    if _is_unitytest_workspace(source):
        return [source]
    return sorted(path for path in source.iterdir() if path.is_dir() and _is_unitytest_workspace(path))


def _source_identity(source: Path) -> str:
    rows = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or any(part in {"__pycache__", "uc_test_report"} for part in path.parts):
            continue
        stat = path.stat()
        rows.append((str(path.relative_to(source)), stat.st_size, stat.st_mtime_ns))
    return stable_hash(rows)


def _dut_name(source: Path) -> str:
    name = source.name
    return name.removeprefix("workspace_") if name.startswith("workspace_") else name


def _report_has_tests(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tests = value.get("tests", [])
    if isinstance(tests, list):
        return bool(tests)
    if isinstance(tests, dict):
        return int(tests.get("total", 0) or 0) > 0
    return False


def _run_tests(workspace: Path, timeout: int) -> dict[str, Any]:
    from ucagent.tools.testops import RunUnityChipTest

    runner = RunUnityChipTest(workspace=str(workspace))
    report, stdout, stderr = runner.do(
        test_dir_or_file="unity_test",
        pytest_ex_args="tests",
        return_stdout=True,
        return_stderr=True,
        timeout=timeout,
        pytest_ex_env={
            "UC_IS_IMP_TEMPLATE": "false",
            "UCAGENT_WORKSPACE": str(workspace),
            "UCA_PYTEST_ARGS": "",
        },
    )
    execution = report.get("execution", {})
    result = {
        "execution": execution,
        "report_path": str(workspace / "uc_test_report/toffee_report.json"),
        "stdout": stdout,
        "stderr": stderr,
    }
    if not execution.get("invocation_success") or not execution.get("report_has_tests"):
        code = execution.get("diagnostic_code", "UNKNOWN")
        raise RuntimeError(f"UnityTest preparation failed for {workspace.name}: {code}")
    return result


def stage_analysis_inputs(source: Path, destination: Path, *, model: str = "ucagent",
                          run_tests: bool = True, timeout: int = 300) -> dict[str, Any]:
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"input source is not a directory: {source}")
    if destination == source or destination.is_relative_to(source):
        raise ValueError("prepared input destination must be outside the source tree")
    workspaces = _workspaces(source)
    if not workspaces:
        raise ValueError(f"no runtime-config UnityTest workspaces found under {source}")
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    expected_names = {workspace.name for workspace in workspaces}
    for existing in destination.iterdir():
        if existing.is_dir() and existing.name not in expected_names:
            shutil.rmtree(existing)
    for workspace in workspaces:
        staged = destination / workspace.name
        identity = _source_identity(workspace)
        metadata_path = staged / ".benchmark_prepared.json"
        prior = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        report_path = staged / "uc_test_report/toffee_report.json"
        run_info_path = staged / "run_info.json"
        run_info = json.loads(run_info_path.read_text(encoding="utf-8")) if run_info_path.is_file() else {}
        adopted_report = (
            not prior
            and run_info.get("source_workspace") == str(workspace)
            and run_tests
            and _report_has_tests(report_path)
        )
        reusable = (
            not run_tests
            and ((prior.get("source_identity") == identity and _report_has_tests(report_path))
                 or adopted_report)
        )
        if not reusable:
            if staged.exists():
                shutil.rmtree(staged)
            shutil.copytree(
                workspace,
                staged,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "uc_test_report", "toffee_tmp_*"),
            )
            atomic_write_json(staged / "run_info.json", {
                "dut": _dut_name(workspace),
                "model": model,
                "all_completed": False,
                "source_workspace": str(workspace),
                "source_identity": identity,
                "prepared_by": PREPARATION_SCHEMA,
            })
            execution = _run_tests(staged, timeout) if run_tests else {}
            metadata = {
                "schema": PREPARATION_SCHEMA,
                "dut": _dut_name(workspace),
                "model": model,
                "source_workspace": str(workspace),
                "source_identity": identity,
                "tests_executed": run_tests,
                "execution": execution,
            }
            atomic_write_json(metadata_path, metadata)
        else:
            metadata = prior or {
                "schema": PREPARATION_SCHEMA,
                "dut": _dut_name(workspace),
                "model": model,
                "source_workspace": str(workspace),
                "source_identity": identity,
                "tests_executed": True,
                "execution": {
                    "adopted_existing_report": True,
                    "report_path": str(report_path),
                },
            }
            if not prior:
                atomic_write_json(run_info_path, {**run_info, "source_identity": identity})
                atomic_write_json(metadata_path, metadata)
        rows.append({
            "dut": metadata["dut"],
            "workspace": str(staged),
            "source_workspace": str(workspace),
            "source_identity": identity,
            "tests_executed": bool(metadata.get("tests_executed")),
            "report_path": str(report_path) if report_path.is_file() else "",
            "reused": reusable,
        })
    result = {"schema": PREPARATION_SCHEMA, "source": str(source),
              "destination": str(destination), "runs": rows}
    atomic_write_json(destination / "prepared_inputs.json", result)
    return result


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--model", default="ucagent")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--run-tests", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    result = stage_analysis_inputs(
        args.source, args.destination, model=args.model,
        run_tests=args.run_tests, timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
