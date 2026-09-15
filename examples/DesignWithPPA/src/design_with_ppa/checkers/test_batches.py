"""Template, all-pass, and deterministic-random test batch gates."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from ucagent.checkers.unity_test import (
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerCoverageGroup,
    UnityChipCheckerCoverageGroupBatchImplementation,
    UnityChipCheckerBatchTestsImplementation,
    UnityChipCheckerDutApi,
    UnityChipCheckerLabelStructureRefine,
    UnityChipCheckerLabelStructure,
    UnityChipCheckerMarkdownFileFormat,
    UnityChipCheckerRefineTestCases,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
    UnityChipCheckerTestTemplate,
    UnityChipCheckerTestMustPass,
)
from ucagent.checkers.unity_test_random import (
    RandomTestCasesChecker,
    _iter_test_function_defs,
)
import ucagent.util.functions as uc_functions
from ..contracts import (
    diagnostic,
    resolve_workspace_path,
)

from .common import (
    _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES,
    _PLACEHOLDER,
    _actionable_checker_failure,
    _cfg_dut,
    _checkpoint_prefixes,
    _exception_contract_diagnostic,
    _functional_checkpoints,
    _is_batch_progress,
)
from .refinement import (
    DesignTestTemplateBatchChecker,
    _expand_declared_batch,
    _normalize_declared_batch,
)
from .test_quality import (
    _api_assertion_quality_violations,
    _environment_contract_violations,
)




class DesignTestTemplateChecker(DesignTestTemplateBatchChecker):
    """Create templates for functional CKs without importing performance CKs."""

    def _load_checkpoint_scope(self):
        """Return one consistent functional subset for template report validation."""

        all_checkpoints, blocks = uc_functions.get_unity_chip_doc_marks(
            self.get_path(self.doc_func_check),
            leaf_node="CK",
            return_line_block=True,
        )
        ignored_prefixes = _checkpoint_prefixes(
            self.extra_kwargs.get(
                "ignore_ck_prefix", _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES
            )
        )
        target = _functional_checkpoints(all_checkpoints, ignored_prefixes)
        self.ignored_source_checkpoints = [
            checkpoint for checkpoint in all_checkpoints if checkpoint not in target
        ]
        target_blocks = {
            checkpoint: blocks[checkpoint]
            for checkpoint in target
            if checkpoint in blocks
        }
        # The inherited checker compares report bins with its first returned
        # list before batch filtering, so both views must use the same scope.
        return target, target, target_blocks




class DesignAllPassBatchTestsChecker(UnityChipCheckerBatchTestsImplementation):
    """Advance design-test batches only when every current test and CK passes."""

    def __init__(self, cfg: Any, **kwargs: Any) -> None:
        """Retain the resolved runtime config used by the public-API source gate."""

        super().__init__(cfg=cfg, **kwargs)
        if not callable(getattr(cfg, "get_value", None)):
            raise TypeError("cfg must be a resolved UCAgent configuration")
        self.cfg = cfg
        # Later-batch tests opportunistically validated by one Check; they must
        # stay outside the CurrentTips guidance scope of the canonical batch.
        self._opportunistic_test_cases: set[str] = set()

    def _cached_document_preflight(self, target_tests: str):
        """Skip verification-only Bug-document preflight for an all-Pass design batch."""

        del target_tests
        return None

    @staticmethod
    def _test_case_is_implemented(workspace: Path, test_case: str) -> bool:
        """Return whether a failed-template test has been replaced by real code."""

        source_name, _, qualified_name = str(test_case).partition("::")
        if not source_name or not qualified_name:
            return False
        source_path = workspace / source_name
        if not source_path.is_file():
            return False
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        definitions, parse_error = _iter_test_function_defs(str(source_path))
        if parse_error is not None:
            return False
        for definition in definitions:
            if definition.get("qualname") != qualified_name:
                continue
            try:
                tree = ast.parse(source_text, filename=str(source_path))
                node = next(
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == definition.get("name")
                    and node.lineno == definition.get("line")
                )
                segment = ast.get_source_segment(
                    source_text, node
                ) or ""
            except (OSError, UnicodeError, SyntaxError, StopIteration):
                return False
            return _PLACEHOLDER not in segment
        return False

    def _include_implemented_future_tests(self) -> None:
        """Add correctly authored later tests to this run for evidence and accounting."""

        current = set(self.current_test_cases)
        generated = set(self.batch_task.gen_task_list)
        future = [
            test_case
            for test_case in self.batch_task.source_task_list
            if test_case not in current
            and test_case not in generated
            and self._test_case_is_implemented(Path(self.workspace).resolve(), test_case)
        ]
        if future:
            # The extended run scope is Check-time evidence bookkeeping only;
            # CurrentTips guidance must stay scoped to the canonical batch.
            self._opportunistic_test_cases.update(future)
            self.batch_task.tbd_task_list.extend(future)
            self.current_test_cases = list(self.batch_task.tbd_task_list)

    def get_template_data(self) -> dict[str, object]:
        """Render CurrentTips guidance scoped to the canonical batch, not the run scope."""

        data = super().get_template_data()
        guidance = [
            test_case
            for test_case in self.batch_task.tbd_task_list
            if test_case not in self._opportunistic_test_cases
        ]
        if guidance and len(guidance) != len(self.batch_task.tbd_task_list):
            data["LIST_CURRENT_CASES"] = guidance
            data["TEST_BATCH_RUN_ARGS"] = self.get_run_args(
                self.test_dir, test_cases=guidance
            )[0]
        return data

    def do_check(self, timeout=0, is_complete=False, **kwargs):
        """Reject private access and evidence manipulation before batch execution."""

        # CurrentTips remains the priority scope.  A later test that has already
        # replaced its template is included opportunistically so pytest evidence
        # can prove it and the canonical batch statistics can absorb it.
        ready, message = self.check_data()
        if ready:
            self._include_implemented_future_tests()
        elif isinstance(message, dict):
            return False, _actionable_checker_failure(
                message,
                error_code="design_batch_source_invalid",
                error="The shared-test batch cannot be resolved from the current sources.",
                next_action=(
                    "Use observed.checker_result and observed.current_batch to repair the "
                    "first missing, duplicated, malformed, or stale test node in the "
                    f"configured test directory {self.test_dir}; preserve canonical CK "
                    "associations, then call Check again."
                ),
                artifact=self.test_dir,
                expected=(
                    "Every current batch node resolves to one readable shared pytest "
                    "function associated with an in-scope CK."
                ),
                current_batch=list(self.current_test_cases),
            )
        elif message and self.current_test_cases:
            return False, _actionable_checker_failure(
                message,
                error_code="design_batch_source_invalid",
                error="The shared-test batch cannot be resolved from the current sources.",
                next_action=(
                    "Use observed.checker_result and observed.current_batch to repair the "
                    "first missing or malformed test template, preserve its canonical CK "
                    "association, then call Check again."
                ),
                artifact=self.test_dir,
                expected="Every current batch node resolves to one readable shared pytest function.",
                current_batch=list(self.current_test_cases),
            )

        workspace = Path(self.workspace).resolve()
        violations: list[dict[str, Any]] = []
        assertion_violations: list[dict[str, Any]] = []
        try:
            for relative in sorted({
                test_case.split("::", 1)[0]
                for test_case in self.current_test_cases
            }):
                source = resolve_workspace_path(workspace, relative, must_exist=True)
                for violation in _environment_contract_violations(source):
                    violations.append({
                        "file": source.relative_to(workspace).as_posix(),
                        **violation,
                    })
                    if len(violations) >= 20:
                        break
                if len(violations) >= 20:
                    break
                for violation in _api_assertion_quality_violations(
                    source, _cfg_dut(self.cfg), self._ignored_test_prefixes()
                ):
                    assertion_violations.append({
                        "file": source.relative_to(workspace).as_posix(),
                        **violation,
                    })
                    if len(assertion_violations) >= 20:
                        break
                if len(assertion_violations) >= 20:
                    break
        except (OSError, SyntaxError, ValueError, FileNotFoundError) as exc:
            return False, _exception_contract_diagnostic(
                error_code="design_batch_environment_contract_invalid",
                error="A current shared-test source cannot be inspected for forbidden private access.",
                exc=exc,
                artifact=self.test_dir,
                guide="Guide_Doc/design_ut_contract.md",
                expected=(
                    "Every current test is readable Python and does not access private DUT "
                    "or transaction state, call private event helpers, or assign normalized "
                    "event evidence."
                ),
            )
        if violations:
            first_violation = violations[0]
            return False, diagnostic(
                "design_batch_environment_bypass",
                "Current tests access forbidden private state or manipulate observation evidence.",
                "Remove the private DUT access, private event/transaction helper call, active transaction state access, or event evidence assignment identified in observed.violations, then call Check.",
                artifact=self.test_dir,
                location=f"{first_violation['file']}:{first_violation.get('line', 1)}",
                observed={"violations": violations, "truncated": len(violations) >= 20},
                expected="Tests do not access private DUT/transaction state or manipulate normalized event evidence.",
            )
        if assertion_violations:
            first_assertion_violation = assertion_violations[0]
            return False, diagnostic(
                "design_batch_weak_api_assertion",
                "Current tests contain weak assertions for a public API result.",
                "At the first location in observed.violations, compare the value returned by the imported api_{DUT}_* call with an independently derived exact expected value using ==. Apply the same repair to the remaining listed violations, rerun those nodes with RunTestCases, then call Check.",
                artifact=self.test_dir,
                location=f"{first_assertion_violation['file']}:{first_assertion_violation.get('line', 1)}",
                observed={
                    "violations": assertion_violations,
                    "truncated": len(assertion_violations) >= 20,
                },
                expected=(
                    "Each current api_{DUT}_* value result is checked against exact "
                    "specified behavior."
                ),
            )
        passed, result = super().do_check(
            timeout=timeout,
            is_complete=is_complete,
            **kwargs,
        )
        if passed or _is_batch_progress(result):
            return passed, result
        return False, _actionable_checker_failure(
            result,
            error_code="design_batch_validation_failed",
            error="The current shared-test implementation batch did not pass its gate.",
            next_action=(
                "Start with the first exact node, CK, or source location in the returned "
                "diagnostic. Repair the requirements-conformant reference and affected "
                "shared artifacts when the reference is wrong; otherwise repair the test "
                "infrastructure or independent expected calculation. Rerun the current "
                "nodes with RunTestCases, then call Check again without skip, xfail, or "
                "weakened assertions."
            ),
            artifact=self.test_dir,
            expected=(
                "Every current shared test passes, has an exact assertion and CK "
                "association, and hits every associated checkpoint."
            ),
            current_batch=list(self.current_test_cases),
        )

    def _validate_current_batch_report(self, report: dict[str, Any]):
        """Require exact all-Pass tests, CK associations, coverage hits, and assertions."""

        artifact = self.test_dir
        tests = report.get("tests")
        test_cases = tests.get("test_cases") if isinstance(tests, dict) else None
        if not isinstance(test_cases, dict):
            return False, diagnostic(
                "design_batch_report_invalid",
                "The current batch report has no tests.test_cases mapping.",
                "Run the current batch nodes with RunTestCases, repair the first reported collection, fixture, API, reference, or assertion error, and call Check again; do not create or edit a report manually.",
                artifact=artifact,
                location=artifact,
                observed=type(test_cases).__name__,
                expected="A mapping of exact pytest node IDs to PASSED statuses.",
            ), "report_invalid"

        normalized_statuses: dict[str, str] = {}
        duplicate_nodes: list[str] = []
        for node_id, status in test_cases.items():
            normalized = self.rm_line_no(str(node_id))
            if normalized in normalized_statuses:
                duplicate_nodes.append(normalized)
            normalized_statuses[normalized] = status
        if duplicate_nodes:
            return False, diagnostic(
                "design_batch_node_identity_ambiguous",
                "Multiple report entries normalize to the same pytest node ID.",
                "Open the first node in observed, keep one uniquely named top-level test definition for that node, rename or remove the duplicate, rerun the current batch with RunTestCases, then call Check.",
                artifact=artifact,
                location=sorted(set(duplicate_nodes))[0],
                observed=sorted(set(duplicate_nodes))[:20],
                expected="Each current batch node ID appears exactly once.",
            ), "report_invalid"

        nonpassing = [
            {"test": test_case, "status": normalized_statuses.get(test_case, "MISSING")}
            for test_case in self.current_test_cases
            if normalized_statuses.get(test_case) != "PASSED"
        ]
        if nonpassing:
            return False, diagnostic(
                "design_batch_tests_not_all_pass",
                "One or more current design tests did not pass.",
                (
                    "Compare the first failure with README, Spec, architecture, and its "
                    "FG/FC/CK contract. If the Python reference implements that contract "
                    "incorrectly, repair the reference and every affected adapter, API, "
                    "fixture, coverage predicate, or independently derived expected value; "
                    "then rerun the current and all affected Python nodes. If the reference "
                    "already matches the contract, repair the test infrastructure or expected "
                    "calculation instead. Never change the reference or expected value merely "
                    "to match the observed failure, weaken an assertion, skip a node, or mark "
                    "it xfail; then call Check."
                ),
                artifact=artifact,
                location=nonpassing[0]["test"],
                observed={
                    "nonpassing_count": len(nonpassing),
                    "tests": nonpassing[:20],
                    "truncated": len(nonpassing) > 20,
                },
                expected="Every current batch test has status PASSED.",
            ), "tests_failed"

        coverage_error = uc_functions.get_missing_functional_coverage_message(report)
        if coverage_error:
            return False, diagnostic(
                "design_batch_coverage_missing",
                coverage_error,
                "Use observed to determine whether coverage groups, the env fixture reporting call, or current CK sampling is absent. Repair the matching function_coverage_def.py/conftest.py/test call, rerun exactly the current batch with RunTestCases, then call Check; do not edit the report.",
                artifact=artifact,
                location=artifact,
                observed={
                    "functional_points": report.get("total_funct_point"),
                    "checkpoints": report.get("total_check_point"),
                },
                expected="A non-empty functional coverage report for the shared test suite.",
            ), "coverage_failed"

        try:
            documented_checkpoints = uc_functions.get_unity_chip_doc_marks(
                self.get_path(self.doc_func_check),
                leaf_node="CK",
            )
        except (AssertionError, OSError, TypeError, ValueError) as exc:
            return False, diagnostic(
                "design_batch_function_contract_invalid",
                "The functions-and-checks document cannot be parsed as the current CK authority.",
                "Use observed.reason to repair the first missing, malformed, or duplicate FG/FC/CK entry in Guide_Doc/design_ut_contract.md format, then call Check again without changing valid CK behavior.",
                artifact=self.doc_func_check,
                location=self.doc_func_check,
                observed={"reason": str(exc)},
                expected="One parseable canonical FG/FC/CK hierarchy.",
            ), "coverage_failed"

        def in_scope(checkpoint: Any) -> bool:
            """Return whether one CK belongs to functional design testing."""

            return isinstance(checkpoint, str) and not any(
                checkpoint.startswith(prefix) for prefix in self.ignore_ck_prefix
            )

        documented = {ck for ck in documented_checkpoints if in_scope(ck)}
        reported = {
            ck for ck in report.get("all_check_point_list", []) if in_scope(ck)
        }
        missing_from_coverage = sorted(documented - reported)
        missing_from_document = sorted(reported - documented)
        if missing_from_coverage or missing_from_document:
            return False, diagnostic(
                "design_batch_coverage_contract_mismatch",
                "The functional coverage model and functions-and-checks document disagree.",
                "Use observed.missing_from_coverage and missing_from_document to repair the first exact CK: add every required CK once to function_coverage_def.py or remove only a coverage entry that has no requirement. Preserve canonical IDs, rerun the current batch, then call Check.",
                artifact=self.doc_func_check,
                location=self.doc_func_check,
                observed={
                    "missing_from_coverage": missing_from_coverage[:20],
                    "missing_from_document": missing_from_document[:20],
                    "truncated": (
                        len(missing_from_coverage) > 20
                        or len(missing_from_document) > 20
                    ),
                },
                expected="The in-scope CK sets in the document and coverage model are identical.",
            ), "coverage_failed"

        associations = report.get("test_case_with_check_point_list")
        if not isinstance(associations, dict):
            associations = {}
        normalized_associations: dict[str, list[str]] = {}
        duplicate_associations: list[str] = []
        for node_id, checkpoints in associations.items():
            normalized = self.rm_line_no(str(node_id))
            if normalized in normalized_associations:
                duplicate_associations.append(normalized)
            normalized_associations[normalized] = (
                [ck for ck in checkpoints if in_scope(ck)]
                if isinstance(checkpoints, list)
                else []
            )
        missing_associations = [
            test_case
            for test_case in self.current_test_cases
            if not normalized_associations.get(test_case)
        ]
        if duplicate_associations or missing_associations:
            return False, diagnostic(
                "design_batch_checkpoint_association_missing",
                "Current design tests do not have one unambiguous functional CK association.",
                "Keep each top-level test name unique and call mark_function for the CKs exercised by every current test, rerun the batch, then call Check.",
                artifact=artifact,
                location=(
                    missing_associations[0]
                    if missing_associations
                    else sorted(set(duplicate_associations))[0]
                ),
                observed={
                    "missing": missing_associations[:20],
                    "duplicate_nodes": sorted(set(duplicate_associations))[:20],
                    "truncated": (
                        len(missing_associations) > 20
                        or len(set(duplicate_associations)) > 20
                    ),
                },
                expected="Every current test has one report identity and at least one in-scope CK association.",
            ), "association_failed"

        unknown_associations = sorted({
            checkpoint
            for test_case in self.current_test_cases
            for checkpoint in normalized_associations[test_case]
            if checkpoint not in documented or checkpoint not in reported
        })
        if unknown_associations:
            return False, diagnostic(
                "design_batch_checkpoint_association_invalid",
                "Current design tests reference CKs outside the canonical coverage contract.",
                "Find the first CK in observed in the affected test mark_function call and replace it with the exact existing FG/FC/CK path required by that test, or restore the missing canonical CK in both contract and coverage model when the Spec requires it. Rerun the current batch, then call Check.",
                artifact=artifact,
                location=unknown_associations[0],
                observed=unknown_associations[:20],
                expected="Every associated CK exists in both the document and coverage model.",
            ), "association_failed"

        unhit_report_checkpoints = {
            ck for ck in report.get("unhit_check_point_list", []) if in_scope(ck)
        }
        current_checkpoints = {
            checkpoint
            for test_case in self.current_test_cases
            for checkpoint in normalized_associations[test_case]
        }
        unhit_checkpoints = sorted(current_checkpoints & unhit_report_checkpoints)
        if unhit_checkpoints:
            return False, diagnostic(
                "design_batch_checkpoint_not_hit",
                "One or more CKs associated with the current passing tests were not hit.",
                "Add the missing deterministic stimulus or coverage sampling for these CKs without weakening assertions, rerun exactly the current batch, then call Check.",
                artifact=artifact,
                location=unhit_checkpoints[0],
                observed={
                    "unhit_count": len(unhit_checkpoints),
                    "checkpoints": unhit_checkpoints[:20],
                    "truncated": len(unhit_checkpoints) > 20,
                },
                expected="Every CK associated with the current batch has at least one coverage hit.",
            ), "coverage_failed"

        assertions_passed, assertion_result = uc_functions.check_has_assert_in_tc(
            self.workspace,
            report,
        )
        if not assertions_passed:
            observed = (
                assertion_result.get("error")
                if isinstance(assertion_result, dict)
                else assertion_result
            )
            return False, diagnostic(
                "design_batch_assertion_missing",
                "One or more current design tests contain no observable assertion.",
                "Add meaningful assertions against independently derived expected behavior, rerun the current batch, then call Check.",
                artifact=artifact,
                location=artifact,
                observed=observed,
                expected="Every current test contains assert or pytest.raises evidence.",
            ), "assertion_failed"
        return True, "", "passed"




class DesignRandomTestCasesChecker(RandomTestCasesChecker):
    """Generate deterministic random coverage without a Bug-analysis document."""

    accepted_stage_args = ("generated",)


    def do_check(
        self,
        timeout: int = 0,
        is_complete: bool = False,
        generated: Any = None,
        **kwargs: Any,
    ):
        """Validate submitted canonical CK records even when authored ahead."""

        _expand_declared_batch(self.batch_task, generated)
        try:
            passed, result = super().do_check(
                timeout=timeout,
                is_complete=is_complete,
                generated=generated,
                **kwargs,
            )
            if passed or _is_batch_progress(result):
                return passed, result
            return False, _actionable_checker_failure(
                result,
                error_code="design_random_batch_invalid",
                error="The current deterministic-random CK batch is incomplete or invalid.",
                next_action=(
                    "Use observed.current_batch and the first nested diagnostic. Repair "
                    "the named random test with a fixed seed, valid input constraints, an "
                    "independently derived exact assertion, and mark_function only for "
                    "the CKs its sampling actually hits; rerun that test with "
                    "RunTestCases, then call Check again."
                ),
                artifact=self.target_test_file,
                expected=(
                    "Every current CK has deterministic random evidence with a fixed "
                    "seed, an exact assertion, and a hit coverage association, or a "
                    "recorded non-randomization reason without a random mark."
                ),
                current_batch=list(self.batch_task.tbd_task_list),
            )
        finally:
            _normalize_declared_batch(self.batch_task)

    def test_check(self, timeout: int = 0, **kw: Any):
        """Execute the random tests and reject false random coverage claims.

        Every random test must pass with executable assertions.  Additionally,
        a CK claimed by a random test's mark_function association must actually
        be hit in the same run; CKs unsuitable for randomization are
        dispositioned through stage_args.generated reasons and must not carry
        a random mark.
        """

        test_files = uc_functions.find_files_by_pattern(
            self.workspace, self.target_test_file
        )
        if len(test_files) < self.mini_file_count:
            return False, diagnostic(
                "design_random_tests_missing",
                "The configured random-test file set is missing or empty.",
                "Create at least one deterministic random test file matching the configured pattern, then call Check again.",
                artifact=self.target_test_file,
                location=self.target_test_file,
                observed={"files": test_files, "minimum_files": self.mini_file_count},
                expected="At least one random test file.",
            )
        naming_files = (
            self._stage_test_files() if self.test_func_rules else test_files
        )
        naming_issues = self._test_function_name_issues(naming_files)
        if naming_issues:
            return False, diagnostic(
                "design_random_test_naming_invalid",
                "Random test function names do not match the design workflow contract.",
                "Rename the reported functions to the configured random-test prefix and call Check again.",
                artifact=self.target_test_file,
                location=(
                    f"{naming_issues[0].get('file', self.target_test_file)}:"
                    f"{naming_issues[0].get('line', 1)}"
                    if isinstance(naming_issues[0], dict)
                    else self.target_test_file
                ),
                observed=naming_issues[:20],
                expected="Each random test uses the configured test_random_* naming contract.",
            )

        total_test_count = 0
        for test_file in test_files:
            source_path = Path(self.get_path(test_file))
            try:
                random_tests, parse_error = _iter_test_function_defs(source_path)
                source_text = source_path.read_text(encoding="utf-8")
                source_tree = ast.parse(source_text, filename=test_file)
            except (OSError, UnicodeError, SyntaxError) as exc:
                return False, diagnostic(
                    "design_random_test_source_invalid",
                    "A random test source cannot be parsed.",
                    "Fix the reported Python source or syntax error and call Check again.",
                    artifact=test_file,
                    location=(
                        f"{test_file}:{exc.lineno}"
                        if isinstance(exc, SyntaxError) and exc.lineno
                        else test_file
                    ),
                    observed=str(exc),
                    expected="Readable, valid Python random-test source.",
                )
            if parse_error is not None:
                return False, diagnostic(
                    "design_random_test_source_invalid",
                    "A random test function could not be inspected.",
                    "Fix the reported Python source structure and call Check again.",
                    artifact=test_file,
                    location=f"{test_file}:{random_tests[0]['line']}" if random_tests else test_file,
                    observed=str(parse_error),
                    expected="Inspectible test_random_* functions.",
                )
            total_test_count += len(random_tests)
            source_nodes = {
                node.lineno: node
                for node in ast.walk(source_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            }
            for random_test in random_tests:
                args = random_test["args"]
                if not args or args[0] != "env":
                    return False, diagnostic(
                        "design_random_test_fixture_invalid",
                        "A random test does not use env as its first argument.",
                        "Change the test signature to start with env and call Check again.",
                        artifact=test_file,
                        location=f"{test_file}:{random_test['line']}",
                        observed={"arguments": args},
                        expected="The first test argument is env.",
                    )
                function_node = source_nodes.get(random_test["line"])
                function_source = ast.get_source_segment(source_text, function_node) or ""
                for snippet, requirement in self.must_func_code_snippet.items():
                    present = (
                        uc_functions.has_executable_mark_function_call(function_source)
                        if snippet == ".mark_function"
                        else snippet in function_source
                    )
                    if not present:
                        return False, diagnostic(
                            "design_random_test_contract_invalid",
                            "A random test is missing a required deterministic coverage marker.",
                            "Add the required repeat-count and mark_function calls with a fixed seed, then call Check again.",
                            artifact=test_file,
                            location=f"{test_file}:{random_test['line']}",
                            observed={"missing": snippet},
                            expected=requirement,
                        )
        if total_test_count < self.min_test_count:
            return False, diagnostic(
                "design_random_tests_insufficient",
                "The random-test stage has too few test cases.",
                "Add meaningful deterministic random cases for the current CK batch and call Check again.",
                artifact=self.target_test_file,
                location=self.target_test_file,
                observed={"count": total_test_count, "minimum": self.min_test_count},
                expected=f"At least {self.min_test_count} random test case(s).",
            )
        self.total_random_test_count = total_test_count
        pytest_args = " ".join(Path(test_file).name for test_file in test_files)
        report, stdout, stderr = BaseUnityChipCheckerTestCase.do_check(
            self,
            pytest_args=pytest_args,
            timeout=timeout,
            **kw,
        )
        passed, message = uc_functions.is_run_report_pass(report, stdout, stderr)
        if not passed:
            return False, diagnostic(
                "design_random_test_run_failed",
                "The random-test execution did not complete successfully.",
                "Use observed to locate the first collection, fixture, API, reference, or assertion failure; repair that exact shared artifact, rerun the node with RunTestCases, then call Check. Do not record a design Bug.",
                artifact=self.target_test_file,
                location=self.target_test_file,
                observed=message,
                expected="run_test_success=true.",
            )
        tests = report.get("tests", {}).get("test_cases", {})
        if not isinstance(tests, dict) or not tests:
            return False, diagnostic(
                "design_random_test_report_invalid",
                "The random-test run produced no test-case mapping.",
                "Run the matching random test file with RunTestCases, repair the first collection/reporting error it returns, and call Check again.",
                artifact=self.target_test_file,
                location=self.target_test_file,
                observed={"test_case_mapping": "missing or empty"},
                expected="A non-empty tests.test_cases mapping.",
            )
        failed = sorted(
            str(node) for node, status in tests.items() if status != "PASSED"
        )
        if failed:
            return False, diagnostic(
                "design_random_test_failed",
                "A deterministic random test failed against the design.",
                (
                    "Compare the first deterministic failure with README, Spec, architecture, "
                    "and FG/FC/CK. Repair the Python reference and affected shared artifacts if "
                    "the reference contradicts that authority; otherwise repair the input "
                    "constraint, expected calculation, adapter, or RTL as identified by the "
                    "backend result. Do not change reference behavior to match a failure; rerun "
                    "the affected directed and random nodes, then call Check."
                ),
                artifact=self.target_test_file,
                location=failed[0],
                observed={"failed_test_cases": failed[:20], "truncated": len(failed) > 20},
                expected="Every random test case has status PASSED.",
            )
        assertion_pass, assertion_message = uc_functions.check_has_assert_in_tc(
            self.workspace, report
        )
        if not assertion_pass:
            return False, diagnostic(
                "design_random_test_assertion_missing",
                "A random test case has no executable assertion.",
                "Add an exact assertion to the named random test and call Check again.",
                artifact=self.target_test_file,
                location=self.target_test_file,
                observed=assertion_message,
                expected="Every random test contains assert or pytest.raises.",
            )
        # This gate deliberately runs only the random-test files, so directed
        # tests never execute here and directed-only CKs are expected to be
        # unhit in this report.  A CK is actionable only when a random test
        # claims it through mark_function yet the run never triggers it: that
        # is a false coverage claim, not a test failure.  CKs unsuitable for
        # randomization stay valid through the stage_args.generated reason
        # path and must not carry a random mark.
        associations = report.get("test_case_with_check_point_list", {})
        marked_by_random: dict[str, list[str]] = {}
        if isinstance(associations, dict):
            for node, checkpoints in associations.items():
                if not isinstance(checkpoints, list):
                    continue
                for checkpoint in checkpoints:
                    marked_by_random.setdefault(str(checkpoint), []).append(
                        str(node)
                    )
        claim_scope = set(self.batch_task.tbd_task_list) | set(self.random_result)
        unhit_marked = [
            checkpoint
            for checkpoint in report.get("unhit_check_point_list", [])
            if checkpoint in claim_scope and checkpoint in marked_by_random
        ]
        if unhit_marked:
            return False, diagnostic(
                "design_random_checkpoint_not_hit",
                "One or more in-scope CKs are marked by random tests but were never hit in this run.",
                (
                    "For the first CK in observed.unhit_marked_checkpoints choose one "
                    "path: (1) extend that random test's constrained sampling so the "
                    "CK's documented trigger inputs occur, or (2) remove the CK from "
                    "that test's mark_function association and record its directed-only "
                    "reason in stage_args.generated. Rerun the random tests with "
                    "RunTestCases, then call Check."
                ),
                artifact=self.target_test_file,
                location=str(unhit_marked[0]),
                observed={
                    "unhit_marked_checkpoints": [
                        {
                            "CK": checkpoint,
                            "marked_by": marked_by_random[checkpoint][:5],
                        }
                        for checkpoint in unhit_marked[:20]
                    ],
                    "truncated": len(unhit_marked) > 20,
                },
                expected=(
                    "Every CK marked by a random test is hit in the same run; CKs "
                    "unsuitable for randomization carry no random mark and are "
                    "dispositioned by a stage_args.generated reason."
                ),
            )
        return True, {
            "success": f"Random test cases ({total_test_count}) passed under the design contract.",
            "test_case_count": len(tests),
        }
