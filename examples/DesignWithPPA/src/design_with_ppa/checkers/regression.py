"""Dual-backend regression gates with source-bound receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any
from ucagent.checkers.base import Checker
from ..contracts import (
    atomic_json,
    atomic_text,
    diagnostic,
    load_json,
    resolve_workspace_path,
)
from ..rtl import (
    discover_rtl_libraries,
    discover_rtl_sources,
    resolve_rtl_config,
)

from .common import (
    _PLACEHOLDER,
    _cfg_dut,
    _contract_identity,
    _exception_contract_diagnostic,
    _hash_rows,
    _validated_input_identity,
    excluded_test_paths,
)
from .evidence import (
    _public_pytest_failure,
    _redact_backend_output,
)
from .rtl_validation import (
    RTLBackendBuildChecker,
)
from .runtime import (
    _normalize_final_test_node,
    _parse_collected_final_nodes,
    _parse_pytest_pass_count,
)
from .test_quality import (
    _api_assertion_quality_violations,
    _environment_contract_violations,
)
from . import runtime  # qualified so tests patch one runtime module


class _BackendRegressionChecker(Checker):
    """Run one backend mode and persist a source-bound all-pass receipt."""

    accepted_stage_args = ("test_target",)


    backend = ""

    def __init__(
        self,
        test_dir: str,
        test_glob: str,
        summary_file: str,
        markdown_summary_file: str | None,
        timeout: int,
        cfg: Any,
        pytest_args: list[str] | None = None,
        ret_std_out: bool = True,
        ret_std_error: bool = True,
        exclude_test_globs: list[str] | None = None,
        input_manifest_file: str | None = None,
        contract_files: list[str] | None = None,
        rtl_architecture_file: str | None = None,
        rtl_manifest_file: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Validate lightweight regression settings without reading live files."""

        super().__init__()
        del kwargs
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("timeout must be a positive integer")
        if pytest_args is not None and (
            not isinstance(pytest_args, list)
            or any(not isinstance(value, str) for value in pytest_args)
        ):
            raise ValueError("pytest_args must be a list of strings")
        for field, value in (("ret_std_out", ret_std_out), ("ret_std_error", ret_std_error)):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be a bool")
        if exclude_test_globs is not None and (
            not isinstance(exclude_test_globs, list)
            or any(not isinstance(value, str) or not value for value in exclude_test_globs)
        ):
            raise ValueError("exclude_test_globs must be a list of non-empty strings")
        if contract_files is not None and (
            not isinstance(contract_files, list)
            or any(not isinstance(value, str) or not value for value in contract_files)
        ):
            raise ValueError("contract_files must be a list of non-empty strings")
        self.cfg = cfg
        self.test_dir = test_dir
        self.test_glob = test_glob
        self.summary_file = summary_file
        self.markdown_summary_file = markdown_summary_file
        self.timeout = timeout
        self.pytest_args = list(pytest_args or [])
        self.ret_std_out = ret_std_out
        self.ret_std_error = ret_std_error
        self.exclude_test_globs = list(exclude_test_globs or [])
        self.input_manifest_file = input_manifest_file
        self.contract_files = list(contract_files or [])
        self.rtl_architecture_file = rtl_architecture_file
        self.rtl_manifest_file = rtl_manifest_file
        self._passed_tests = 0
        self._total_tests = 0

    def do_check(self, is_complete: bool = False, **kwargs: Any):
        """Run the configured backend pytest suite and reject every functional failure."""

        test_target = kwargs.pop("test_target", None)
        del kwargs
        if test_target is not None and self.backend != "rtl":
            return False, diagnostic(
                "test_target_unsupported",
                "A targeted dual-implementation Check is available only in the RTL shared-regression stage.",
                "Use RunTestCases for a targeted Python-reference test, or call the RTL stage Check with stage_args.test_target.",
                artifact=self.test_dir,
                location=self.test_dir,
                observed=test_target,
                expected="No test_target for this stage.",
            )
        if test_target is not None and (
            not isinstance(test_target, str) or not test_target.strip()
        ):
            return False, diagnostic(
                "rtl_test_target_invalid",
                "test_target must be one non-empty pytest node relative to the configured test directory.",
                "Call Check with stage_args.test_target='test_file.py::test_function', or omit test_target for the full regression.",
                artifact=self.test_dir,
                location=self.test_dir,
                observed=test_target,
                expected="One exact test_file.py::test_function node.",
            )
        if is_complete and test_target is not None:
            return False, diagnostic(
                "rtl_targeted_complete_forbidden",
                "Complete cannot use a targeted regression selection.",
                "Call Complete without stage_args.test_target so every shared functional TC is revalidated.",
                artifact=self.test_dir,
                location=self.test_dir,
                observed=test_target,
                expected="A full Python-reference and RTL regression during Complete.",
            )
        self._passed_tests = 0
        self._total_tests = 0
        run_test_count = 0
        pytest_targets: list[str] | None = None
        workspace = Path(self.workspace).resolve()
        try:
            if self.backend == "rtl":
                if not self.rtl_architecture_file or not self.rtl_manifest_file:
                    raise ValueError(
                        "RTL regression requires architecture and backend manifest paths"
                    )
                build_checker = RTLBackendBuildChecker(
                    architecture_file=self.rtl_architecture_file,
                    manifest_file=self.rtl_manifest_file,
                    timeout=self.timeout,
                    cfg=self.cfg,
                    input_manifest_file=self.input_manifest_file,
                    contract_files=self.contract_files,
                ).set_workspace(self.workspace)
                build_passed, build_result = build_checker.do_check()
                if not build_passed:
                    return False, build_result
                rtl_manifest = load_json(
                    resolve_workspace_path(
                        workspace, self.rtl_manifest_file, must_exist=True
                    )
                )
                rtl_dut_identity = runtime._validate_workspace_python_dut(
                    workspace, rtl_manifest
                )
            else:
                rtl_dut_identity = None
            test_dir = resolve_workspace_path(workspace, self.test_dir, must_exist=True)
            excluded_paths = excluded_test_paths(workspace, self.exclude_test_globs)
            test_files = sorted(
                path.resolve()
                for path in workspace.glob(self.test_glob)
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.resolve() not in excluded_paths
                )
            )
            if not test_files:
                raise ValueError(f"no test files matched {self.test_glob}")
            violations = [
                {
                    "file": path.relative_to(workspace).as_posix(),
                    **violation,
                }
                for path in test_files
                for violation in _environment_contract_violations(path)
            ]
            if violations:
                return False, diagnostic(
                    f"{self.backend}_environment_bypass",
                    "One or more tests access forbidden private state or manipulate observation evidence.",
                    "Remove the private DUT access, private event/transaction helper call, active transaction state access, or event evidence assignment identified in observed.violations, then call Check.",
                    artifact=self.test_glob,
                    location=f"{violations[0]['file']}:{violations[0].get('line', 1)}",
                    observed={
                        "violations": violations[:20],
                        "truncated": len(violations) > 20,
                    },
                    expected="Tests do not access private DUT/transaction state or manipulate normalized event evidence.",
                )
            assertion_violations = [
                {
                    "file": path.relative_to(workspace).as_posix(),
                    **violation,
                }
                for path in test_files
                for violation in _api_assertion_quality_violations(
                    path, _cfg_dut(self.cfg)
                )
            ]
            if assertion_violations:
                return False, diagnostic(
                    f"{self.backend}_weak_api_assertion",
                    "One or more tests contain weak assertions for a public API result.",
                    "Compare every value returned by an imported api_{DUT}_* function with an independently derived exact expected value using ==. Do not use self-comparison, != 0, truthiness, or None checks as functional proof, then call Check.",
                    artifact=self.test_glob,
                    location=f"{assertion_violations[0]['file']}:{assertion_violations[0].get('line', 1)}",
                    observed={
                        "violations": assertion_violations[:20],
                        "truncated": len(assertion_violations) > 20,
                    },
                    expected="Every non-error api_{DUT}_* value result has an independent exact equality assertion.",
                )
            placeholders = [
                path.relative_to(workspace).as_posix()
                for path in test_files
                if _PLACEHOLDER in path.read_text(encoding="utf-8")
            ]
            if placeholders:
                return False, diagnostic(
                    f"{self.backend}_test_placeholder",
                    "One or more tests still contain the required unimplemented placeholder.",
                    "Open every file in observed.files, replace the Not implemented placeholder with requirements-derived stimulus and exact assertions, run the affected nodes with RunTestCases, then call Check.",
                    artifact=self.test_glob,
                    location=placeholders[0],
                    observed={"files": placeholders[:20], "truncated": len(placeholders) > 20},
                    expected="No selected shared test contains the Not implemented placeholder.",
                )
            if self.backend == "rtl":
                collected = runtime._run_pytest(
                    workspace,
                    test_dir,
                    self.backend,
                    self.timeout,
                    [*self.pytest_args, "--collect-only"],
                    test_files=test_files,
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
                        "rtl_test_collection_failed",
                        "The target RTL regression tests could not be collected.",
                        "Start with the first failed node or assertion diagnostic in observed. Repair that test/API/fixture import or syntax error without changing the selected functional TC set, then call Check again.",
                        artifact=self.test_glob,
                        location=(failure.get("failed_nodes") or [self.test_glob])[0],
                        observed=failure,
                        expected="The complete selected functional TC set is collected without import, fixture, or syntax errors.",
                    )
                collected_nodes = _parse_collected_final_nodes(
                    f"{collected.stdout}\n{collected.stderr}",
                    workspace,
                    test_files,
                )
                if not collected_nodes:
                    return False, diagnostic(
                        "rtl_test_collection_empty",
                        "The target RTL regression did not collect any test cases.",
                        "Add discoverable shared functional test cases to the selected files, then call Check.",
                        artifact=self.test_glob,
                        location=self.test_glob,
                        observed={"collected_test_count": 0},
                        expected="At least one collected shared functional pytest node.",
                    )
                self._total_tests = len(collected_nodes)
                if test_target is not None:
                    path_text, separator, node_text = test_target.strip().partition(
                        "::"
                    )
                    target_path = Path(path_text)
                    if (
                        not separator
                        or not node_text
                        or target_path.is_absolute()
                        or ".." in target_path.parts
                        or not path_text.endswith(".py")
                    ):
                        return False, diagnostic(
                            "rtl_test_target_invalid",
                            "test_target is not one exact pytest node relative to the configured test directory.",
                            "Use test_file.py::test_function from the current target test set, then call Check again.",
                            artifact=self.test_dir,
                            location=self.test_dir,
                            observed=test_target,
                            expected="One exact test_file.py::test_function node.",
                        )
                    target_node = (
                        test_dir.relative_to(workspace) / target_path
                    ).as_posix() + f"::{node_text}"
                    if target_node not in collected_nodes:
                        available = [
                            node.removeprefix(
                                test_dir.relative_to(workspace).as_posix() + "/"
                            )
                            for node in sorted(collected_nodes)
                        ]
                        return False, diagnostic(
                            "rtl_test_target_unknown",
                            "test_target is not part of the current shared functional regression.",
                            "Choose one exact node from available_targets and call Check again.",
                            artifact=self.test_dir,
                            location=self.test_dir,
                            observed={
                                "test_target": test_target,
                                "available_targets": available[:20],
                                "truncated": len(available) > 20,
                            },
                            expected="A collected non-performance functional pytest node.",
                        )
                    pytest_targets = [target_node]
                    run_test_count = 1
                else:
                    run_test_count = self._total_tests
                reference_completed = runtime._run_pytest(
                    workspace,
                    test_dir,
                    "python",
                    self.timeout,
                    self.pytest_args,
                    test_files=test_files,
                    pytest_targets=pytest_targets,
                )
                reference_passed = min(
                    run_test_count,
                    _parse_pytest_pass_count(
                        f"{reference_completed.stdout}\n{reference_completed.stderr}"
                    ),
                )
                if (
                    reference_completed.returncode != 0
                    or reference_passed != run_test_count
                ):
                    if runtime.backend_option_usage_failure(reference_completed):
                        return False, diagnostic(
                            "rtl_shared_backend_option_unregistered",
                            (
                                "pytest rejected --design-backend before running the "
                                "shared suite because the workspace conftest no "
                                "longer registers the workflow-owned backend "
                                "selector."
                            ),
                            (
                                "Restore the template-managed selector in the shared "
                                "conftest: import register_managed_test_options and "
                                "managed_test_implementation from design_with_ppa, "
                                "call register_managed_test_options(parser) inside "
                                "exactly one pytest_addoption(parser), and select the "
                                "env backend through "
                                "managed_test_implementation(request.config); do not "
                                "hand-write parser.addoption for --design-backend. "
                                "The conftest is workflow-managed read-only; a "
                                "drifted copy must be restored from the rendered "
                                "plugin template, not edited in place. Rerun the "
                                "same target with RunTestCases, then call Check."
                            ),
                            artifact=self.test_dir,
                            location=self.test_dir,
                            observed={
                                "returncode": reference_completed.returncode,
                                "stderr_tail": _redact_backend_output(
                                    reference_completed.stderr, 2000, (workspace,)
                                ),
                            },
                            expected=(
                                "The shared conftest registers the managed backend "
                                "selector so the suite executes instead of failing "
                                "pytest argument parsing."
                            ),
                        )
                    failure = _public_pytest_failure(reference_completed)
                    failure["progress"] = {
                        "passed": reference_passed,
                        "selected": run_test_count,
                        "total": self._total_tests,
                    }
                    if self.ret_std_out:
                        failure["stdout_tail"] = _redact_backend_output(
                            reference_completed.stdout, 4000, (workspace,)
                        )
                    if self.ret_std_error:
                        failure["stderr_tail"] = _redact_backend_output(
                            reference_completed.stderr, 4000, (workspace,)
                        )
                    return False, diagnostic(
                        "rtl_shared_python_regression_failed",
                        "The current shared tests do not pass against the Python executable specification.",
                        (
                            "Compare the first failure with README, Spec, architecture, and its "
                            "FG/FC/CK contract. The Python reference is not frozen: repair its "
                            "function, state, reset, timing, invalid-input, or boundary behavior "
                            "when it contradicts those sources, and synchronize affected shared "
                            "tests, API, adapter, fixture, coverage, and independently derived "
                            "expected values. Do not edit the reference or expected merely to "
                            "match a failing output. Rerun the same Python target and call Check; "
                            "RTL comparison starts only after the current Python run passes."
                        ),
                        artifact=self.test_glob,
                        location=(failure.get("failed_nodes") or [self.test_glob])[0],
                        observed=failure,
                        expected="The exact target TC set passes against the current Python executable specification before RTL comparison.",
                    )
            completed = runtime._run_pytest(
                workspace,
                test_dir,
                self.backend,
                self.timeout,
                self.pytest_args,
                test_files=test_files,
                rtl_dut_identity=rtl_dut_identity,
                pytest_targets=pytest_targets,
            )
            if self.backend == "rtl":
                self._passed_tests = min(
                    run_test_count,
                    _parse_pytest_pass_count(
                        f"{completed.stdout}\n{completed.stderr}"
                    ),
                )
        except subprocess.TimeoutExpired as exc:
            if self.backend == "rtl" and self._total_tests:
                captured = "\n".join(
                    value.decode(errors="replace")
                    if isinstance(value, bytes)
                    else value
                    for value in (exc.stdout or "", exc.stderr or "")
                )
                self._passed_tests = min(
                    run_test_count,
                    _parse_pytest_pass_count(captured),
                )
            return False, diagnostic(
                f"{self.backend}_regression_timeout",
                f"The {self.backend} regression exceeded {self.timeout} seconds.",
                (
                    "Run the selected tests one node at a time to identify the first "
                    "nonterminating transaction. Bound waits with max_cycles and repair "
                    "the responsible reference/API/adapter/fixture or selected RTL behavior; "
                    "then call Check again. Increase the configured timeout only after each "
                    "individual node terminates normally."
                ),
                artifact=self.test_glob,
                location=test_target or self.test_glob,
                observed={
                    "timeout": str(exc),
                    **(
                        {
                            "progress": {
                                "passed": self._passed_tests,
                                "total": self._total_tests,
                            }
                        }
                        if self.backend == "rtl"
                        else {}
                    ),
                },
                expected=f"Every selected {self.backend} test terminates within {self.timeout} seconds.",
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code=f"{self.backend}_regression_invalid",
                error=f"The {self.backend} regression source set or managed runtime is invalid.",
                exc=exc,
                artifact=self.test_dir,
                guide="Guide_Doc/python_dut_interface.md",
                expected=(
                    "A non-empty workspace-local shared test set, valid normalized env "
                    f"runtime, and current {self.backend} implementation evidence."
                ),
            )
        if (
            completed.returncode != 0
            or (
                self.backend == "rtl"
                and self._passed_tests != run_test_count
            )
        ):
            if self.backend == "rtl" and runtime.pytest_died_before_summary(completed):
                return False, diagnostic(
                    "rtl_regression_aborted_before_summary",
                    (
                        "The RTL pytest run was aborted by the native runtime "
                        "before printing any test summary, so no functional "
                        "diagnostic exists."
                    ),
                    (
                        "1. Read observed.stdout_tail: pytest emitted only progress "
                        "marks and died silently. The RTL native layer aborts the "
                        "whole process when it cannot write an artifact file, most "
                        "commonly a coverage path whose directory does not exist.\n"
                        "2. Inspect every configure_test_artifacts call in the "
                        "shared conftest and adapter: coverage and waveform paths "
                        "must be absolute with existing parent directories. Route "
                        "them through prepare_native_artifact_path from "
                        "design_with_ppa, which resolves the path and creates "
                        "missing parent directories on the Python side; a "
                        "relative path such as coverage/<test>.dat aborts at "
                        "adapter.finish() and swallows every remaining test "
                        "diagnostic.\n"
                        "3. Repair the artifact binding, rerun one node with "
                        "Check stage_args.test_target to confirm the summary "
                        "prints again, then run the full regression."
                    ),
                    artifact=self.test_dir,
                    location=test_target if isinstance(test_target, str) else self.test_dir,
                    observed={
                        "returncode": completed.returncode,
                        "stdout_tail": _redact_backend_output(
                            completed.stdout, 2000, (workspace,)
                        ),
                        "stderr_tail": _redact_backend_output(
                            completed.stderr, 2000, (workspace,)
                        ),
                    },
                    expected=(
                        "pytest prints a run summary; every native artifact path "
                        "resolves to an absolute path with an existing parent "
                        "directory."
                    ),
                )
            failure = _public_pytest_failure(completed)
            debug_target = test_target.strip() if isinstance(test_target, str) else None
            if self.backend == "rtl":
                if debug_target is None:
                    for raw_line in (
                        f"{completed.stdout}\n{completed.stderr}"
                    ).splitlines():
                        line = raw_line.strip()
                        if not line.startswith("FAILED ") or ".py::" not in line:
                            continue
                        raw_node = line[len("FAILED ") :].partition(" - ")[0]
                        try:
                            normalized_node = _normalize_final_test_node(
                                raw_node, workspace, test_files
                            )
                        except ValueError:
                            continue
                        if normalized_node not in collected_nodes:
                            continue
                        test_prefix = test_dir.relative_to(workspace).as_posix() + "/"
                        debug_target = normalized_node.removeprefix(test_prefix)
                        break
                failure["progress"] = {
                    "passed": self._passed_tests,
                    "selected": run_test_count,
                    "total": self._total_tests,
                }
                failure["backend_comparison"] = {
                    "python_reference": "pass",
                    "rtl": "fail",
                    "same_target_tests": run_test_count,
                    "full_target_tests": self._total_tests,
                }
                if debug_target is not None:
                    data_dir = test_dir / "data"
                    retained_waveform = any(
                        path.is_file()
                        and not path.is_symlink()
                        and path.suffix.lower() in {".vcd", ".fst"}
                        for session in data_dir.glob("toffee_tmp_*")
                        if session.is_dir() and not session.is_symlink()
                        for path in session.rglob("*")
                    )
                    failure["rtl_debug"] = {
                        "test_target": debug_target,
                        "targeted_check": {
                            "stage_args": {"test_target": debug_target}
                        },
                        "waveform_test_case_name": debug_target,
                        "waveform_retained": retained_waveform,
                    }
            if self.ret_std_out:
                failure["stdout_tail"] = _redact_backend_output(
                    completed.stdout, 4000, (workspace,)
                )
            if self.ret_std_error:
                failure["stderr_tail"] = _redact_backend_output(
                    completed.stderr, 4000, (workspace,)
                )
            return False, diagnostic(
                f"{self.backend}_regression_failed",
                f"The {self.backend} functional regression did not pass.",
                (
                    "The same current tests pass against the Python executable specification but fail against RTL. "
                    "Do not assume this is an RTL-only defect until the failing vector has been reconciled across "
                    "the README/Spec, the shared test, the Python reference, and the selected RTL implementation. "
                    "For packed arrays or matrix arithmetic, first write the byte-to-element table and the exact "
                    "operand mapping for every output (for a 2x2 multiply, A[i][0]*B[0][j] + A[i][1]*B[1][j]); "
                    "then trace the first failing vector through decode, product, accumulate, encode, and output "
                    "byte order. Check that every intermediate and saturation comparison has enough signed width "
                    "to represent the largest pre-conversion value, not only the final encoded value. "
                    "If comments, stimulus, reference, and Spec disagree, the Spec is authoritative: repair the "
                    "reference/shared test when it contradicts the Spec, rerun the Python gate, and only then compare RTL. "
                    "Otherwise keep requirements-derived expectations unchanged and fix the selected RTL implementation. "
                    "Also check reset/clock RefreshComb/Step ordering, latency, handshake, and boundary behavior required by the architecture. "
                    + (
                        f"Recheck only the first failure with Check stage_args.test_target={json.dumps(debug_target)}, "
                        f"and inspect its retained waveform with WaveInfo test_case_name={json.dumps(debug_target)} when waveform_retained is true. "
                        if debug_target is not None
                        else "Call Check again after the focused RTL repair. "
                    )
                    + "RunTestCases validates Python only and cannot validate this RTL stage."
                    if self.backend == "rtl"
                    else (
                        "Compare the failure with README, Spec, architecture, and FG/FC/CK. "
                        "Repair the executable reference when it contradicts those sources, "
                        "otherwise repair the shared test infrastructure; never preserve the "
                        "failure or change expected behavior merely to match it."
                    )
                ),
                artifact=self.test_glob,
                location=(failure.get("failed_nodes") or [self.test_glob])[0],
                observed=failure,
                expected=(
                    "The exact selected TC set passes with identical requirements-derived "
                    f"expectations against the {self.backend} implementation."
                ),
            )
        if self.backend == "rtl":
            self._passed_tests = run_test_count
        if self.backend == "rtl" and test_target is not None:
            return True, {
                "message": "The targeted shared test passed against both implementations.",
                "test_target": test_target,
                "passed": self._passed_tests,
                "total": self._total_tests,
                "next_action": "Fix another failing target with Check, or call Complete without test_target for the full regression.",
            }
        source_files = sorted(
            path.resolve()
            for path in test_dir.rglob("*.py")
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and path.resolve() not in excluded_paths
            )
        )
        if self.backend == "rtl":
            rtl_config, rtl_language_backend = resolve_rtl_config(self.cfg)
            source_files.extend(
                discover_rtl_sources(
                    workspace, rtl_config, rtl_language_backend
                )
            )
            source_files = sorted(set(source_files), key=lambda path: path.as_posix())
            _, rtl_libraries = discover_rtl_libraries(
                workspace, rtl_config, rtl_language_backend
            )
        summary = {
            "schema_version": "1.0",
            "backend": self.backend,
            "status": "pass",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "sources": _hash_rows(workspace, source_files),
            "command": ["pytest", self.test_dir, f"--design-backend={self.backend}"],
        }
        if self.backend == "rtl":
            summary["target_test_count"] = self._total_tests
            summary["python_reference_regression"] = "pass"
        if self.ret_std_out:
            summary["stdout_tail"] = _redact_backend_output(
                completed.stdout, 4000, (workspace,)
            )
        if self.ret_std_error:
            summary["stderr_tail"] = _redact_backend_output(
                completed.stderr, 4000, (workspace,)
            )
        if self.backend == "rtl":
            summary["rtl_libraries"] = list(rtl_libraries)
        try:
            if self.input_manifest_file is not None:
                summary["design_inputs"] = _validated_input_identity(
                    workspace, self.input_manifest_file
                )
            if self.contract_files:
                summary["contracts"] = _contract_identity(
                    workspace, self.contract_files
                )
        except (OSError, ValueError, FileNotFoundError) as exc:
            artifact = self.input_manifest_file or self.test_dir
            return False, _exception_contract_diagnostic(
                error_code=f"{self.backend}_regression_provenance_invalid",
                error=f"The passing {self.backend} regression cannot be bound to the current requirements and contracts.",
                exc=exc,
                artifact=artifact,
                guide="Guide_Doc/design_input_and_architecture.md",
                expected=(
                    "Current README/Spec hashes, architecture, functional contract, shared "
                    "test sources, and regression receipt all describe the same design revision."
                ),
            )
        summary_path = resolve_workspace_path(workspace, self.summary_file)
        atomic_json(summary_path, summary)
        result = {
            "message": f"{self.backend} regression passed.",
            "summary": summary_path.relative_to(workspace).as_posix(),
            "source_files": len(source_files),
        }
        if self.markdown_summary_file is not None:
            markdown_path = resolve_workspace_path(
                workspace, self.markdown_summary_file
            )
            dut = _cfg_dut(self.cfg)
            atomic_text(
                markdown_path,
                (
                    f"\n# {dut} {self.backend.upper()} Test Summary\n\n"
                    "## Result\n\n"
                    f"- Backend: `{self.backend}`\n"
                    "- Functional regression: `Pass`\n"
                    f"- Bound source files: `{len(source_files)}`\n\n"
                    "## Machine Receipt\n\n"
                    "```json\n"
                    + json.dumps(summary, indent=2, ensure_ascii=True)
                    + "\n```\n"
                ),
            )
            result["markdown_summary"] = markdown_path.relative_to(
                workspace
            ).as_posix()
        return True, result


class PythonReferenceRegressionChecker(_BackendRegressionChecker):
    """Require the shared UT suite to pass against the Python executable specification."""

    backend = "python"


class RTLAllPassRegressionChecker(_BackendRegressionChecker):
    """Require the shared UT suite to pass in isolated RTL test mode."""

    backend = "rtl"

    def get_template_data(self) -> dict[str, int]:
        """Expose pass progress from the most recent target regression run."""

        return {
            "RTL_TESTS_PASSED": self._passed_tests,
            "RTL_TESTS_TOTAL": self._total_tests,
        }
