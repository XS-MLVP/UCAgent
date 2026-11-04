"""Performance contract, TC, and RTL artifact gates."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from ucagent.checkers.base import Checker
from ..contracts import (
    atomic_json,
    canonical_json_sha256,
    diagnostic,
    finite_number,
    load_fenced_yaml,
    load_json,
    load_yaml,
    performance_stimulus_identity,
    resolve_workspace_path,
    resolved_output,
    sha256_file,
)
from ..performance import (
    build_performance_manifest,
)

from .common import (
    _inline_reason,
    _PLACEHOLDER,
    _VERILOG_IDENTIFIER_RE,
    _cfg_dut,
    _contract_identity,
    _exception_contract_diagnostic,
    _validated_input_identity,
)
from .evidence import (
    _public_pytest_failure,
    _redact_backend_output,
)
from .test_quality import (
    _environment_contract_violations,
)
from . import runtime  # qualified so tests patch one runtime module


_METRIC_KINDS = {"latency", "throughput", "frequency", "area", "power", "custom"}


_AGGREGATIONS = {"max", "min", "mean", "p95", "sum"}


_TIME_UNITS = {"s", "ms", "us", "ns", "ps", "fs", "cycle", "cycles"}


def _validate_performance_contract(
    workspace: Path, contract_path: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate the canonical performance contract and return metrics by ID."""

    contract = load_yaml(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ValueError("schema_version must be '1.0'")
    dut = contract.get("dut")
    top_module = contract.get("top_module")
    if not isinstance(dut, str) or not dut.strip():
        raise ValueError("dut must be a non-empty string")
    if not isinstance(top_module, str) or not _VERILOG_IDENTIFIER_RE.fullmatch(top_module):
        raise ValueError("top_module must be a portable RTL identifier")
    metrics = contract.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("metrics must be a non-empty list")
    by_id: dict[str, dict[str, Any]] = {}
    for index, metric in enumerate(metrics):
        field = f"metrics[{index}]"
        if not isinstance(metric, dict):
            raise ValueError(f"{field} must be a mapping")
        metric_id = metric.get("id")
        if not isinstance(metric_id, str) or not metric_id.strip():
            raise ValueError(f"{field}.id must be non-empty")
        if metric_id in by_id:
            raise ValueError(f"duplicate metric id: {metric_id}")
        if metric.get("kind") not in _METRIC_KINDS:
            raise ValueError(f"{field}.kind is invalid")
        if metric.get("direction") not in {"min", "max"}:
            raise ValueError(f"{field}.direction must be min or max")
        if metric.get("aggregation") not in _AGGREGATIONS:
            raise ValueError(f"{field}.aggregation is invalid")
        unit = metric.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"{field}.unit must be non-empty")
        source = metric.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"{field}.source must be a mapping")
        source_path = source.get("path")
        source_line = source.get("line")
        if not isinstance(source_path, str) or not source_path.strip():
            raise ValueError(f"{field}.source.path must be non-empty")
        spec_file = resolve_workspace_path(workspace, source_path, must_exist=True)
        if spec_file.suffix.lower() != ".md":
            raise ValueError(f"{field}.source.path must reference a Markdown Spec")
        if isinstance(source_line, bool) or not isinstance(source_line, int) or source_line < 1:
            raise ValueError(f"{field}.source.line must be a positive integer")
        line_count = len(spec_file.read_text(encoding="utf-8").splitlines())
        if source_line > line_count:
            raise ValueError(f"{field}.source.line exceeds the Spec file")
        target = metric.get("target")
        hard = metric.get("hard_requirement")
        if type(hard) is not bool:
            raise ValueError(f"{field}.hard_requirement must be boolean")
        if target is None:
            if hard:
                raise ValueError(f"{field} cannot be hard without a numeric target")
        else:
            finite_number(target, f"{field}.target")
        measurement_test = metric.get("measurement_test")
        if not isinstance(measurement_test, str) or "::" not in measurement_test:
            raise ValueError(f"{field}.measurement_test must be an exact pytest node ID")
        time_base = metric.get("clock_or_time_base")
        if not isinstance(time_base, str) or not time_base.strip():
            raise ValueError(f"{field}.clock_or_time_base must be non-empty")
        by_id[metric_id] = metric
    return contract, by_id


def _require_manifest_spec_sources(
    metrics: dict[str, dict[str, Any]], input_identity: dict[str, Any]
) -> None:
    """Require every performance metric to reference a hashed input Spec file."""

    sources = input_identity.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        raise ValueError("design input identity has no Spec source set")
    spec_paths = {
        row.get("path")
        for row in sources[1:]
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    invalid = sorted(
        metric_id
        for metric_id, metric in metrics.items()
        if metric.get("source", {}).get("path") not in spec_paths
    )
    if invalid:
        raise ValueError(
            "performance metric source.path must reference a Markdown Spec from "
            f"the design input manifest: {invalid[:20]}"
        )


class PerformanceContractChecker(Checker):
    """Validate Spec-traceable metrics, directions, units, targets, and measurement tests."""

    def __init__(
        self,
        contract_file: str,
        cfg: Any,
        input_manifest_file: str | None = None,
        architecture_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the performance contract path for live validation."""

        super().__init__()
        del kwargs
        self.cfg = cfg
        self.contract_file = contract_file
        self.input_manifest_file = input_manifest_file
        self.architecture_file = architecture_file
        self._cached_metric_count = 0

    def get_template_data(self) -> dict[str, int]:
        """Expose the count from the latest successful contract validation."""

        return {"PERFORMANCE_METRIC_COUNT": self._cached_metric_count}

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require every performance metric to trace to a real Spec line and pytest node."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            input_identity = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            contract, metrics = _validate_performance_contract(
                workspace,
                resolve_workspace_path(
                    workspace, self.contract_file, must_exist=True
                ),
            )
            if input_identity is not None:
                _require_manifest_spec_sources(metrics, input_identity)
            if contract.get("dut") != _cfg_dut(self.cfg):
                raise ValueError("contract dut does not match the resolved DUT")
            if self.architecture_file is not None:
                architecture = load_fenced_yaml(
                    resolve_workspace_path(
                        workspace, self.architecture_file, must_exist=True
                    ),
                    "architecture",
                )
                if contract.get("top_module") != architecture.get("top_module"):
                    raise ValueError(
                        "contract top_module does not match the architecture contract"
                    )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="performance_contract_invalid",
                error="The performance contract is not complete, Spec-traceable, or architecture-consistent.",
                exc=exc,
                artifact=self.contract_file,
                guide="Guide_Doc/performance_contract.md",
                expected=(
                    "Schema 1.0 contains unique finite metrics whose kind/unit/direction, "
                    "Spec path and physical line, target policy, aggregation, exact pytest "
                    "node, time base, DUT, and top module are all valid."
                ),
            )
        self._cached_metric_count = len(metrics)
        return True, {
            "message": "Performance contract is complete.",
            "metrics": len(metrics),
            "hard_requirements": sum(
                1 for metric in metrics.values() if metric["hard_requirement"]
            ),
            "design_input_sha256": (
                input_identity["source_set_sha256"]
                if input_identity is not None
                else None
            ),
        }


class PerformanceTestContractChecker(Checker):
    """Validate dedicated performance pytest nodes without importing workspace code."""

    def __init__(
        self,
        test_glob: str,
        contract_file: str,
        cfg: Any,
        min_tests: int = 2,
        **kwargs: Any,
    ) -> None:
        """Store source patterns and validate the minimum performance test count."""

        super().__init__()
        del kwargs
        if isinstance(min_tests, bool) or not isinstance(min_tests, int) or min_tests < 2:
            raise ValueError("min_tests must be an integer greater than or equal to 2")
        self.cfg = cfg
        self.test_glob = test_glob
        self.contract_file = contract_file
        self.min_tests = min_tests
        self._cached_test_count = 0

    def get_template_data(self) -> dict[str, int]:
        """Expose the latest validated performance test count."""

        return {"PERFORMANCE_TEST_COUNT": self._cached_test_count}

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Require named, marked, sidecar-writing tests bound to every contract node."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        try:
            dut = _cfg_dut(self.cfg)
            pattern = Path(self.test_glob)
            if pattern.is_absolute() or ".." in pattern.parts:
                raise ValueError("test_glob must remain workspace-relative")
            test_files = sorted(
                path.resolve()
                for path in workspace.glob(self.test_glob)
                if path.is_file() and not path.is_symlink()
            )
            if not test_files:
                raise ValueError(f"no performance test files matched {self.test_glob}")
            prefix = f"test_{dut}_performance_"
            nodes: dict[str, Path] = {}
            invalid_functions: list[str] = []
            missing_sidecar_calls: list[str] = []
            for test_file in test_files:
                source = test_file.read_text(encoding="utf-8")
                if _PLACEHOLDER in source:
                    raise ValueError(
                        f"performance test still contains the unimplemented placeholder: "
                        f"{test_file.relative_to(workspace).as_posix()}"
                    )
                try:
                    tree = ast.parse(source, filename=str(test_file))
                except SyntaxError as exc:
                    raise ValueError(
                        f"performance test syntax is invalid at "
                        f"{test_file.relative_to(workspace).as_posix()}:{exc.lineno}"
                    ) from exc
                violations = _environment_contract_violations(test_file, tree)
                if violations:
                    raise ValueError(
                        "performance tests must not access private DUT/transaction state "
                        "or manipulate normalized event evidence: "
                        f"{test_file.relative_to(workspace).as_posix()} {violations}"
                    )
                for function in (
                    node
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")
                ):
                    marked = any(
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr == "performance"
                        and isinstance(decorator.value, ast.Attribute)
                        and decorator.value.attr == "mark"
                        and isinstance(decorator.value.value, ast.Name)
                        and decorator.value.value.id == "pytest"
                        for decorator in function.decorator_list
                    )
                    if not function.name.startswith(prefix) or not marked:
                        invalid_functions.append(
                            f"{test_file.relative_to(workspace).as_posix()}::{function.name}"
                        )
                        continue
                    arguments = [argument.arg for argument in function.args.args]
                    if not arguments or arguments[0] != "env" or "request" not in arguments:
                        invalid_functions.append(
                            f"{test_file.relative_to(workspace).as_posix()}::{function.name}"
                        )
                        continue
                    node_id = (
                        f"{test_file.relative_to(workspace).as_posix()}::{function.name}"
                    )
                    if node_id in nodes:
                        raise ValueError(f"duplicate performance test node: {node_id}")
                    nodes[node_id] = test_file
                    has_sidecar_call = any(
                        isinstance(call, ast.Call)
                        and (
                            isinstance(call.func, ast.Name)
                            and call.func.id == "write_performance_result"
                            or isinstance(call.func, ast.Attribute)
                            and call.func.attr == "write_performance_result"
                        )
                        for call in ast.walk(function)
                    )
                    if not has_sidecar_call:
                        missing_sidecar_calls.append(node_id)
            if invalid_functions:
                raise ValueError(
                    "performance pytest functions must use the exact prefix, marker, "
                    f"and env/request arguments: {invalid_functions[:20]}"
                )
            if len(nodes) < self.min_tests:
                raise ValueError(
                    f"at least {self.min_tests} performance pytest functions are required; "
                    f"found {len(nodes)}"
                )
            if missing_sidecar_calls:
                raise ValueError(
                    "each performance test must call write_performance_result in its RTL "
                    f"evidence branch: {missing_sidecar_calls[:20]}"
                )
            _, metrics = _validate_performance_contract(
                workspace,
                resolve_workspace_path(workspace, self.contract_file, must_exist=True),
            )
            contract_nodes = {
                metric["measurement_test"] for metric in metrics.values()
            }
            unknown = sorted(contract_nodes - set(nodes))
            unbound = sorted(set(nodes) - contract_nodes)
            if unknown or unbound:
                raise ValueError(
                    "performance contract/test node set mismatch: "
                    f"unknown_contract_nodes={unknown[:20]}, "
                    f"unbound_test_nodes={unbound[:20]}"
                )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="performance_test_contract_invalid",
                error="The dedicated performance TC set does not satisfy its naming, measurement, or contract binding.",
                exc=exc,
                artifact=self.test_glob,
                guide="Guide_Doc/performance_measurement.md",
                expected=(
                    f"At least {self.min_tests} tests use the exact test_<DUT>_performance_* "
                    "prefix, performance marker, env/request fixtures, one "
                    "write_performance_result call, and a one-to-one measurement_test binding."
                ),
            )
        self._cached_test_count = len(nodes)
        return True, {
            "message": "Dedicated performance test contract is complete.",
            "test_count": len(nodes),
            "test_nodes": sorted(nodes),
        }


class PerformanceArtifactChecker(Checker):
    """Run performance tests and validate waveform/sidecar/manifest identity."""

    def __init__(
        self,
        test_dir: str,
        results_glob: str,
        contract_file: str,
        manifest_file: str,
        timeout: int,
        cfg: Any,
        pytest_args: list[str] | None = None,
        ret_std_out: bool = True,
        ret_std_error: bool = True,
        input_manifest_file: str | None = None,
        contract_files: list[str] | None = None,
        rtl_manifest_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store performance test locations and validate lightweight settings."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        for field, value in (("ret_std_out", ret_std_out), ("ret_std_error", ret_std_error)):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
        self.cfg = cfg
        self.test_dir = test_dir
        self.results_glob = results_glob
        self.contract_file = contract_file
        self.manifest_file = manifest_file
        self.timeout = timeout
        self.pytest_args = list(pytest_args or ["-m", "performance"])
        self.ret_std_out = ret_std_out
        self.ret_std_error = ret_std_error
        if contract_files is not None and (
            not isinstance(contract_files, list)
            or any(not isinstance(value, str) or not value for value in contract_files)
        ):
            raise ValueError("contract_files must be a list of non-empty strings")
        self.input_manifest_file = input_manifest_file
        self.contract_files = list(contract_files or [])
        self.rtl_manifest_file = rtl_manifest_file

    def do_check(self, run_tests: bool = True, is_complete: bool = False, **kwargs: Any):
        """Require all performance pytest cases to pass and produce unique reliable artifacts."""

        del is_complete, kwargs
        workspace = Path(self.workspace).resolve()
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
            wave_root = resolve_workspace_path(
                workspace,
                Path(resolved_output(self.cfg)) / "performance" / "waves",
            )
            if wave_root.is_symlink() or (wave_root.exists() and not wave_root.is_dir()):
                raise ValueError("performance waveform root must be a regular directory")
            design_inputs = (
                _validated_input_identity(workspace, self.input_manifest_file)
                if self.input_manifest_file is not None
                else None
            )
            contracts = (
                _contract_identity(workspace, self.contract_files)
                if self.contract_files
                else None
            )
            pattern = Path(self.results_glob)
            if pattern.is_absolute() or ".." in pattern.parts:
                raise ValueError("results_glob must remain workspace-relative")
            _, contract_metrics = _validate_performance_contract(
                workspace,
                resolve_workspace_path(
                    workspace, self.contract_file, must_exist=True
                ),
            )
            if design_inputs is not None:
                _require_manifest_spec_sources(contract_metrics, design_inputs)
            collected_tests: set[str] | None = None
            if run_tests:
                if not self.rtl_manifest_file:
                    raise ValueError(
                        "RTL performance execution requires synchronized validation evidence"
                    )
                rtl_manifest = load_json(
                    resolve_workspace_path(
                        workspace, self.rtl_manifest_file, must_exist=True
                    )
                )
                rtl_dut_identity = runtime._validate_workspace_python_dut(
                    workspace, rtl_manifest
                )
                collected = runtime._run_pytest(
                    workspace,
                    test_dir,
                    "rtl",
                    self.timeout,
                    [*self.pytest_args, "--collect-only"],
                    rtl_dut_identity=rtl_dut_identity,
                )
                if collected.returncode != 0:
                    failure = _public_pytest_failure(collected)
                    if self.ret_std_out:
                        failure["stdout_tail"] = _redact_backend_output(
                            collected.stdout, 4000, (workspace,)
                        )
                    if self.ret_std_error:
                        failure["stderr_tail"] = _redact_backend_output(
                            collected.stderr, 4000, (workspace,)
                        )
                    return False, diagnostic(
                        "performance_test_collection_failed",
                        "The performance pytest selection could not be collected.",
                        (
                            "Start with the first failed node or assertion diagnostic in "
                            "observed. Repair that performance test/API/env import, marker "
                            "registration, fixture, or current RTL test-runtime error, then "
                            "call Check again without changing the TC selection."
                        ),
                        artifact=self.test_dir,
                        location=(failure.get("failed_nodes") or [self.test_dir])[0],
                        observed=failure,
                        expected="Every marked performance TC is collected with its shared env and request fixtures.",
                    )
                collected_tests = {
                    line.strip()
                    for line in collected.stdout.splitlines()
                    if "::" in line
                    and line.strip().split("::", 1)[0].endswith(".py")
                }
                if not collected_tests:
                    raise ValueError("no performance pytest test cases were collected")
                stale_results = sorted(workspace.glob(self.results_glob))
                if any(path.is_symlink() for path in stale_results):
                    raise ValueError("performance sidecar paths must not be symbolic links")
                for stale_result in stale_results:
                    if stale_result.is_file():
                        stale_result.unlink()
                wave_root.mkdir(parents=True, exist_ok=True)
                stale_waveforms = sorted(
                    path
                    for path in wave_root.iterdir()
                    if path.suffix.lower() in {".vcd", ".fst"}
                )
                if any(path.is_symlink() or not path.is_file() for path in stale_waveforms):
                    raise ValueError("performance waveform paths must be regular files")
                for stale_waveform in stale_waveforms:
                    stale_waveform.unlink()
                completed = runtime._run_pytest(
                    workspace,
                    test_dir,
                    "rtl",
                    self.timeout,
                    self.pytest_args,
                    rtl_dut_identity=rtl_dut_identity,
                )
                if completed.returncode != 0:
                    failure = _public_pytest_failure(completed)
                    if self.ret_std_out:
                        failure["stdout_tail"] = _redact_backend_output(
                            completed.stdout, 4000, (workspace,)
                        )
                    if self.ret_std_error:
                        failure["stderr_tail"] = _redact_backend_output(
                            completed.stderr, 4000, (workspace,)
                        )
                    return False, diagnostic(
                        "performance_tests_failed",
                        "The RTL performance pytest selection did not pass.",
                        (
                            "Start with the first failed node in observed. If it is a "
                            "collection/runtime error, repair that test, API, env fixture, or "
                            "current RTL runtime. If it is an assertion, keep the Spec-derived "
                            "stimulus and expected metric unchanged and repair the selected RTL. "
                            "Call Check again; it reruns the complete performance set and "
                            "regenerates waveforms and sidecars automatically."
                        ),
                        artifact=self.test_dir,
                        location=(failure.get("failed_nodes") or [self.test_dir])[0],
                        observed=failure,
                        expected="Every selected performance TC passes and emits one fresh waveform/sidecar pair.",
                    )
            result_files = sorted(
                path.resolve()
                for path in workspace.glob(self.results_glob)
                if path.is_file() and not path.is_symlink()
            )
            if not result_files:
                raise ValueError(f"no performance sidecars matched {self.results_glob}")
            observed_metrics: set[str] = set()
            observed_tests: set[str] = set()
            observed_waveforms: set[str] = set()
            for result_file in result_files:
                result = load_json(result_file)
                if result.get("schema_version") != "1.0":
                    raise ValueError(f"invalid sidecar schema: {result_file}")
                test_case = result.get("test_case")
                if not isinstance(test_case, str) or "::" not in test_case:
                    raise ValueError(f"sidecar has invalid test_case: {result_file}")
                if test_case in observed_tests:
                    raise ValueError(f"duplicate sidecar test_case: {test_case}")
                observed_tests.add(test_case)
                waveform = result.get("waveform")
                if not isinstance(waveform, dict):
                    raise ValueError(f"sidecar waveform must be a mapping: {result_file}")
                waveform_path_value = waveform.get("path")
                if not isinstance(waveform_path_value, str):
                    raise ValueError(f"sidecar waveform.path is invalid: {result_file}")
                waveform_path = resolve_workspace_path(
                    workspace, waveform_path_value, must_exist=True
                )
                if waveform_path.suffix.lower() not in {".vcd", ".fst"}:
                    raise ValueError(f"unsupported waveform suffix: {waveform_path_value}")
                if waveform.get("format") != waveform_path.suffix.lower().lstrip("."):
                    raise ValueError(f"waveform format mismatch: {waveform_path_value}")
                try:
                    waveform_path.relative_to(wave_root)
                except ValueError as exc:
                    raise ValueError(
                        f"performance waveform must be stored under {wave_root.relative_to(workspace).as_posix()}: "
                        f"{waveform_path_value}"
                    ) from exc
                if waveform_path_value in observed_waveforms:
                    raise ValueError(f"duplicate waveform assignment: {waveform_path_value}")
                observed_waveforms.add(waveform_path_value)
                if sha256_file(waveform_path) != waveform.get("sha256"):
                    raise ValueError(f"waveform hash mismatch: {waveform_path_value}")
                for hash_field in ("stimulus_sha256", "input_trace_sha256"):
                    value = result.get(hash_field)
                    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                        raise ValueError(f"sidecar {hash_field} is invalid: {result_file}")
                stimulus = result.get("stimulus")
                if not isinstance(stimulus, dict):
                    raise ValueError(f"sidecar stimulus must be a mapping: {result_file}")
                if type(stimulus.get("deterministic")) is not bool:
                    raise ValueError(
                        f"sidecar stimulus.deterministic is invalid: {result_file}"
                    )
                seed = stimulus.get("seed")
                if seed is not None and (
                    isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
                ):
                    raise ValueError(f"sidecar stimulus.seed is invalid: {result_file}")
                if seed is None and not stimulus["deterministic"]:
                    raise ValueError(
                        f"sidecar unseeded stimulus must be deterministic: {result_file}"
                    )
                if not isinstance(stimulus.get("parameters"), dict):
                    raise ValueError(
                        f"sidecar stimulus.parameters is invalid: {result_file}"
                    )
                input_trace = stimulus.get("input_trace")
                if input_trace in (None, [], {}):
                    raise ValueError(
                        f"sidecar stimulus.input_trace is empty: {result_file}"
                    )
                if canonical_json_sha256(
                    performance_stimulus_identity(stimulus)
                ) != result["stimulus_sha256"]:
                    raise ValueError(f"sidecar stimulus hash mismatch: {result_file}")
                if canonical_json_sha256(input_trace) != result["input_trace_sha256"]:
                    raise ValueError(f"sidecar input trace hash mismatch: {result_file}")
                rows = result.get("metrics")
                if not isinstance(rows, list) or not rows:
                    raise ValueError(f"sidecar metrics must be non-empty: {result_file}")
                sidecar_metric_ids: set[str] = set()
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError(f"sidecar metric must be a mapping: {result_file}")
                    metric_id = row.get("id")
                    if metric_id not in contract_metrics:
                        raise ValueError(f"unknown sidecar metric ID: {metric_id}")
                    if metric_id in sidecar_metric_ids or metric_id in observed_metrics:
                        raise ValueError(f"duplicate sidecar metric ID: {metric_id}")
                    sidecar_metric_ids.add(metric_id)
                    contract_metric = contract_metrics[metric_id]
                    if row.get("kind") != contract_metric["kind"]:
                        raise ValueError(f"kind mismatch for metric {metric_id}")
                    if row.get("unit") != contract_metric["unit"]:
                        raise ValueError(f"unit mismatch for metric {metric_id}")
                    if row.get("direction") != contract_metric["direction"]:
                        raise ValueError(f"direction mismatch for metric {metric_id}")
                    finite_number(row.get("value"), f"metric {metric_id}")
                    if test_case != contract_metric["measurement_test"]:
                        raise ValueError(f"test_case mismatch for metric {metric_id}")
                    observed_metrics.add(metric_id)
                measurement = result.get("measurement")
                if not isinstance(measurement, dict):
                    raise ValueError(f"sidecar measurement must be a mapping: {result_file}")
                start_time = finite_number(
                    measurement.get("start_time"), "measurement.start_time"
                )
                end_time = finite_number(
                    measurement.get("end_time"), "measurement.end_time"
                )
                duration = finite_number(
                    measurement.get("duration"), "measurement.duration"
                )
                if duration <= 0 or end_time - start_time != duration:
                    raise ValueError(f"sidecar duration is invalid: {result_file}")
                if measurement.get("time_unit") not in _TIME_UNITS:
                    raise ValueError(f"sidecar time_unit is invalid: {result_file}")
                transaction_count = measurement.get("transaction_count")
                if (
                    isinstance(transaction_count, bool)
                    or not isinstance(transaction_count, int)
                    or transaction_count < 0
                ):
                    raise ValueError(
                        f"sidecar transaction_count is invalid: {result_file}"
                    )
            missing = sorted(set(contract_metrics) - observed_metrics)
            if missing:
                raise ValueError(f"performance metrics lack sidecar evidence: {missing}")
            if collected_tests is not None and observed_tests != collected_tests:
                raise ValueError(
                    "performance pytest/sidecar set mismatch: "
                    f"missing_sidecars={sorted(collected_tests - observed_tests)[:20]}, "
                    f"unknown_sidecars={sorted(observed_tests - collected_tests)[:20]}"
                )
            waveform_files = {
                path.relative_to(workspace).as_posix()
                for path in wave_root.iterdir()
                if path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in {".vcd", ".fst"}
            }
            if waveform_files != observed_waveforms:
                raise ValueError(
                    "performance waveform/sidecar set mismatch: "
                    f"unreferenced_waveforms={sorted(waveform_files - observed_waveforms)[:20]}, "
                    f"missing_waveforms={sorted(observed_waveforms - waveform_files)[:20]}"
                )
            manifest_path = resolve_workspace_path(workspace, self.manifest_file)
            manifest = build_performance_manifest(
                workspace, result_files, manifest_path
            )
            manifest["design_inputs"] = design_inputs
            manifest["contracts"] = contracts
            atomic_json(manifest_path, manifest)
        except subprocess.TimeoutExpired as exc:
            return False, diagnostic(
                "performance_tests_timeout",
                f"Performance pytest exceeded {self.timeout} seconds.",
                (
                    "Run the performance nodes individually with RunTestCases to locate the "
                    "first nonterminating stimulus. Bound all protocol waits with max_cycles "
                    "and repair that test/API/env or selected RTL behavior, then call Check "
                    "again. Increase the configured timeout only after every individual node "
                    "terminates."
                ),
                artifact=self.test_dir,
                location=self.test_dir,
                observed={
                    "timeout_seconds": self.timeout,
                    "reason": str(exc),
                    "partial_stdout_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stdout), 2000, (workspace,)
                    ),
                    "partial_stderr_tail": _redact_backend_output(
                        runtime.timeout_stream_fragment(exc.stderr), 2000, (workspace,)
                    ),
                },
                expected=f"The complete marked performance TC set terminates within {self.timeout} seconds.",
            )
        except (OSError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            reason = _redact_backend_output(str(exc), 4000, (workspace,))
            if "contract" in reason.lower() or "design input" in reason.lower():
                next_action = (
                    "Return to the performance-contract stage and correct the exact "
                    "metric/source/test identity in observed.reason. Then call Check here "
                    "to rerun the complete performance set."
                )
            elif "rtl" in reason.lower() and (
                "evidence" in reason.lower() or "runtime" in reason.lower()
            ):
                next_action = (
                    "Call the RTL implementation-stage Check to rebuild and validate the "
                    "current RTL test runtime, then return here and call Check again."
                )
            else:
                next_action = (
                    "Use observed.reason to identify the exact TC, sidecar field, waveform, "
                    "metric, duration, seed, stimulus, or hash that failed. Repair the source "
                    "performance test when needed, then call Check to regenerate every "
                    "sidecar, waveform, and manifest. Do not hand-edit generated JSON, "
                    "waveforms, hashes, or the performance manifest."
                )
            return False, diagnostic(
                "performance_artifact_invalid",
                (
                    "The performance evidence set is missing, malformed, stale, or "
                    f"inconsistent. First problem: {_inline_reason(reason)}"
                ),
                next_action,
                artifact=self.results_glob,
                location=self.results_glob,
                observed={"reason": reason},
                expected=(
                    "Every collected performance TC has one unique schema-1.0 sidecar and "
                    "one current VCD/FST with finite metrics, positive duration, stable "
                    "stimulus/input identity and verified hashes; the manifest contains the "
                    "same ordered set."
                ),
            )
        result = {
            "message": "Performance tests and artifacts are complete.",
            "manifest": manifest_path.relative_to(workspace).as_posix(),
            "test_cases": len(manifest["tests"]),
            "waveform_files": [row["waveform"]["path"] for row in manifest["tests"]],
        }
        if completed is not None and self.ret_std_out:
            result["stdout_tail"] = _redact_backend_output(
                completed.stdout, 4000, (workspace,)
            )
        if completed is not None and self.ret_std_error:
            result["stderr_tail"] = _redact_backend_output(
                completed.stderr, 4000, (workspace,)
            )
        return True, result
