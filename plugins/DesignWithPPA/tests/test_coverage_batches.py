"""Focused DesignWithPPA workflow tests: coverage batches."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from pathlib import Path
from types import ModuleType, SimpleNamespace
import pytest
from design_with_ppa.checkers import (  # noqa: E402
    DesignAllPassBatchTestsChecker,
    DesignArchitectureChecker,
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignDutApiChecker,
    DesignLabelStructureChecker,
    DesignLineMapReferenceChecker,
    DesignMarkdownFileFormatChecker,
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    DesignRandomTestCasesChecker,
    DesignRefineTestCasesChecker,
    DesignLabelStructureRefineChecker,
    DesignSpecLineMapBatchChecker,
    DesignTestTemplateChecker,
    DesignPythonAllPassChecker,
    PPABaseCharacterizationChecker,
    PPABestVersionChecker,
    PPACandidateOptimizationChecker,
    PPAIterationChecker,
    PPAResultArtifactsChecker,
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    RTLSourceEvidenceChecker,
    _api_assertion_quality_violations,
    _actionable_checker_failure,
    _bounded_checker_value,
    _cleanup_transient_coverage_data,
    _coverage_fixture_lifecycle_violations,
    _hash_rows,
    _ppa_selection_score,
    _public_pytest_failure,
    _pytest_evidence,
    _rtl_regression_failure_evidence,
    _run_pytest,
    _run_workflow_ppa,
    select_best_accepted_record,
)
from ucagent.checkers.unity_test import (  # noqa: E402
    BaseUnityChipCheckerTestCase,
    UnityChipCheckerTestCase,
    UnityChipCheckerTestCaseWithLineCoverage,
)




def _write_coverage_fixture(
    root: Path,
    first_predicate: str,
    second_predicate: str,
) -> list[str]:
    """Write one two-CK coverage contract and return its canonical paths."""

    (root / "functions.md").write_text(
        "\n# Functions\n\n"
        "## Arithmetic\n\n"
        "<FG-ARITH>\n\n"
        "### Add\n\n"
        "<FC-ADD>\n\n"
        "#### First\n\n"
        "<CK-FIRST>\n\n"
        "First behavior.\n\n"
        "#### Second\n\n"
        "<CK-SECOND>\n\n"
        "Second behavior.\n",
        encoding="utf-8",
    )
    (root / "coverage.py").write_text(
        '"""Focused coverage fixture."""\n\n'
        "from toffee.funcov import CovGroup\n\n\n"
        "def get_coverage_groups(env):\n"
        '    """Return the fixture coverage model."""\n\n'
        '    group = CovGroup("FG-ARITH")\n'
        "    group.add_watch_point(\n"
        "        env,\n"
        "        {\n"
        f'            "CK-FIRST": {first_predicate},\n'
        f'            "CK-SECOND": {second_predicate},\n'
        "        },\n"
        '        name="FC-ADD",\n'
        "    )\n"
        "    return [group]\n",
        encoding="utf-8",
    )
    return [
        "FG-ARITH/FC-ADD/CK-FIRST",
        "FG-ARITH/FC-ADD/CK-SECOND",
    ]




def _coverage_batch_checker(
    root: Path,
    checkpoints: list[str],
) -> DesignCoverageGroupBatchChecker:
    """Create an initialized two-item predicate batch Checker."""

    class Stage:
        """Provide the batch lifecycle used by the focused Checker fixture."""

        name = "functional_coverage_checkpoints"

        def title(self) -> str:
            """Return the persisted checkpoint title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept a successful focused batch transition."""

    stage = Stage()
    manager = SimpleNamespace(data={"DESIGN_CK_LIST": checkpoints})
    manager.get_data = lambda key, default=None: manager.data.get(key, default)
    manager.set_data = lambda key, value: manager.data.__setitem__(key, value)
    manager.get_current_stage = lambda: stage
    checker = DesignCoverageGroupBatchChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        batch_size=1,
        data_key="DESIGN_CK_LIST",
    )
    checker.set_workspace(str(root)).set_stage(stage).set_stage_manager(manager)
    checker.on_init()
    return checker




def test_design_coverage_structure_requires_false_predicate_placeholders(
    tmp_path: Path,
) -> None:
    """The structure stage must not silently implement future CK predicates."""

    _write_coverage_fixture(
        tmp_path,
        "lambda _env: False",
        "lambda _env: False",
    )
    checker = DesignCoverageStructureChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        check_types=["FG", "FC"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    (tmp_path / "coverage.py").write_text(
        (tmp_path / "coverage.py")
        .read_text(encoding="utf-8")
        .replace("lambda _env: False", "lambda model: model.valid.value == 1", 1),
        encoding="utf-8",
    )
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "design_coverage_predicate_implemented_early"




def test_design_coverage_factory_requires_backend_neutral_env(tmp_path: Path) -> None:
    """DesignWithPPA coverage must not expose a backend-specific DUT target."""

    _write_coverage_fixture(tmp_path, "lambda _env: False", "lambda _env: False")
    coverage_file = tmp_path / "coverage.py"
    coverage_file.write_text(
        coverage_file.read_text(encoding="utf-8")
        .replace("get_coverage_groups(env)", "get_coverage_groups(dut)")
        .replace("        env,\n", "        dut,\n"),
        encoding="utf-8",
    )
    checker = DesignCoverageStructureChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        check_types=["FG", "FC"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert "one argument named env" in result["error"]




def test_design_coverage_rejects_private_dut_and_event_injection(tmp_path: Path) -> None:
    """Coverage predicates may read public event evidence but cannot manufacture it."""

    for predicate, expected_reason in (
        ("lambda env: env._dut.valid_o.value == 1", "private_dut_access"),
        ("lambda env: env._record_event('accepted')", "private_event_injection"),
        (
            "lambda env: env._record_transaction_observation(1, 2)",
            "private_event_injection",
        ),
        (
            "lambda env: len(env._active_transactions) == 1",
            "private_transaction_evidence_access",
        ),
    ):
        _write_coverage_fixture(tmp_path, predicate, "lambda _env: False")
        checker = DesignCoverageStructureChecker(
            test_dir=".",
            cov_file="coverage.py",
            doc_file="functions.md",
            check_types=["FG", "FC"],
        ).set_workspace(str(tmp_path))

        passed, result = checker.do_check()

        assert passed is False
        assert result["error_code"] == "design_coverage_structure_invalid"
        assert expected_reason in result["error"]




def test_design_coverage_predicate_batches_count_future_and_reject_constants(
    tmp_path: Path,
) -> None:
    """Valid future predicates count while fabricated constants still fail."""

    checkpoints = _write_coverage_fixture(
        tmp_path,
        "lambda _env: False",
        "lambda model: model.valid.value == 1",
    )
    checker = _coverage_batch_checker(tmp_path, checkpoints)

    passed, result = checker.do_check()

    assert passed is False
    assert "1/2" in result["error"]
    assert checker.batch_task.gen_task_list == [checkpoints[1]]
    assert checker.batch_task.tbd_task_list == [checkpoints[0]]

    _write_coverage_fixture(
        tmp_path,
        "lambda model: model.valid.value == 1",
        "lambda _env: False",
    )
    passed, result = checker.do_check()
    assert passed is False
    assert "1/2" in result["success"]
    assert checker.batch_task.gen_task_list == [checkpoints[0]]
    assert checker.batch_task.tbd_task_list == [checkpoints[1]]

    for constant in ("True", "1", "None"):
        _write_coverage_fixture(
            tmp_path,
            "lambda model: model.valid.value == 1",
            f"lambda _env: {constant}",
        )
        passed, result = checker.do_check()
        assert passed is False
        assert result["error_code"] == "design_coverage_constant_predicate"

    _write_coverage_fixture(
        tmp_path,
        "lambda model: model.valid.value == 1",
        "lambda model: model.ready.value == 1",
    )
    passed, result = checker.do_check()
    assert passed is True, result
    assert checker.batch_task.gen_task_list == checkpoints




def test_design_label_refinement_counts_valid_future_ck(tmp_path: Path) -> None:
    """A canonical CK review outside CurrentTips updates the real remaining batch."""

    (tmp_path / "functions.md").write_text(
        "<FG-A>\n\n<FC-A>\n\n<CK-A>\n\n<CK-B>\n",
        encoding="utf-8",
    )

    class Stage:
        """Provide batch persistence identity for the focused Checker."""

        name = "design_function_contract_refinement"

        def title(self) -> str:
            """Return the stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept one successful batch transition."""

    stage = Stage()
    checkpoints = ["FG-A/FC-A/CK-A", "FG-A/FC-A/CK-B"]
    manager = SimpleNamespace(data={"DESIGN_CK_LIST": checkpoints})
    manager.get_data = lambda key, default=None: manager.data.get(key, default)
    manager.set_data = lambda key, value: manager.data.__setitem__(key, value)
    manager.get_current_stage = lambda: stage
    checker = DesignLabelStructureRefineChecker(
        doc_file="functions.md",
        leaf_node="CK",
        data_key="DESIGN_CK_LIST",
        must_have_prefix="",
        batch_size=1,
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage).set_stage_manager(manager)
    checker.on_init()

    passed, result = checker.do_check(refined={checkpoints[1]: "reviewed"})

    assert passed is False, result
    assert checker.batch_task.gen_task_list == [checkpoints[1]]
    assert checker.batch_task.tbd_task_list == [checkpoints[0]]




def test_design_test_refinement_counts_valid_future_ck(tmp_path: Path) -> None:
    """A valid later test-review record is retained while the current CK remains."""

    (tmp_path / "functions.md").write_text(
        "<FG-A>\n\n<FC-A>\n\n<CK-A>\n\n<CK-B>\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    class Stage:
        """Provide batch persistence identity for the focused Checker."""

        name = "shared_test_refinement"

        def title(self) -> str:
            """Return the stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept one successful batch transition."""

    stage = Stage()
    manager = SimpleNamespace(data={})
    manager.get_data = lambda key, default=None: manager.data.get(key, default)
    manager.set_data = lambda key, value: manager.data.__setitem__(key, value)
    manager.save_stage_info = lambda: None
    manager.get_current_stage = lambda: stage
    checker = DesignRefineTestCasesChecker(
        doc_func_check="functions.md",
        test_dir="tests",
        batch_size=1,
        data_key="DESIGN_TEST_REFINEMENT",
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage).set_stage_manager(manager)
    checker.on_init()
    checkpoints = ["FG-A/FC-A/CK-A", "FG-A/FC-A/CK-B"]

    passed, result = checker.do_check(refined={checkpoints[1]: "reviewed"})

    assert passed is False, result
    assert checker.batch_task.gen_task_list == [checkpoints[1]]
    assert checker.batch_task.tbd_task_list == [checkpoints[0]]




def test_design_random_batch_counts_valid_future_ck(tmp_path: Path) -> None:
    """A later random-test decision is counted after the complete test gate passes."""

    (tmp_path / "functions.md").write_text(
        "<FG-A>\n\n<FC-A>\n\n<CK-A>\n\n<CK-B>\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()

    class Stage:
        """Provide batch persistence identity for the focused Checker."""

        name = "deterministic_random_tests"

        def title(self) -> str:
            """Return the stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept one successful batch transition."""

    stage = Stage()
    manager = SimpleNamespace(data={})
    manager.get_data = lambda key, default=None: manager.data.get(key, default)
    manager.set_data = lambda key, value: manager.data.__setitem__(key, value)
    manager.save_stage_info = lambda: None
    manager.get_current_stage = lambda: stage
    checker = DesignRandomTestCasesChecker(
        target_test_file="tests/test_random_*.py",
        doc_func_check="functions.md",
        test_dir="tests",
        batch_size=1,
        data_key="DESIGN_RANDOM_TEST_REPORT",
        args_check=False,
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage).set_stage_manager(manager)
    checker.on_init()
    checker._run_random_tests = lambda timeout=0, **kwargs: (True, "pass")
    checkpoints = ["FG-A/FC-A/CK-A", "FG-A/FC-A/CK-B"]

    passed, result = checker.do_check(
        generated={checkpoints[1]: "No useful randomized dimension."}
    )

    assert passed is False, result
    assert checker.batch_task.gen_task_list == [checkpoints[1]]
    assert checker.batch_task.tbd_task_list == [checkpoints[0]]




def test_design_template_batch_counts_valid_future_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The template gate validates and counts a canonical later CK association."""

    first = "FG-A/FC-A/CK-A"
    second = "FG-A/FC-A/CK-B"
    (tmp_path / "functions.md").write_text(
        "<FG-A>\n\n<FC-A>\n\n<CK-A>\n\n<CK-B>\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_source = (
        "def test_a(env):\n"
        "    env.fc_cover['FG-A'].mark_function('FC-A', test_a, ['CK-A'])\n"
        '    assert False, "Not implemented"\n\n\n'
        "def test_b(env):\n"
        "    env.fc_cover['FG-A'].mark_function('FC-A', test_b, ['CK-B'])\n"
        '    assert False, "Not implemented"\n'
    )
    (tests_dir / "test_demo.py").write_text(test_source, encoding="utf-8")
    nodes = [
        "tests/test_demo.py:1-3::test_a",
        "tests/test_demo.py:6-8::test_b",
    ]
    report = {
        "run_test_success": True,
        "tests": {
            "total": 2,
            "fails": 2,
            "test_cases": {node: "FAILED" for node in nodes},
            "test_case_details": {
                node: {
                    "phase": "call",
                    "exception_type": "AssertionError",
                    "exception": "AssertionError: Not implemented",
                }
                for node in nodes
            },
        },
        "total_funct_point": 1,
        "total_check_point": 2,
        "all_check_point_list": [first, second],
        "unhit_check_point_list": [first, second],
        "unmarked_check_points": 0,
        "unmarked_check_point_list": [],
        "test_function_with_no_check_point_mark": 0,
    }
    monkeypatch.setattr(
        BaseUnityChipCheckerTestCase,
        "do_check",
        lambda _self, **_kwargs: (report, "", ""),
    )

    class Stage:
        """Provide batch persistence identity for the focused Checker."""

        name = "shared_test_templates"

        def title(self) -> str:
            """Return the stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept one successful batch transition."""

    checker = DesignTestTemplateChecker(
        doc_func_check="functions.md",
        test_dir="tests",
        batch_size=1,
    ).set_workspace(str(tmp_path)).set_stage(Stage())
    checker.on_init()

    passed, result = checker.do_check()

    assert passed is True, result
    assert checker.batch_task.gen_task_list == [first, second]
    assert checker.batch_task.tbd_task_list == []




def test_design_spec_line_map_counts_valid_later_block(tmp_path: Path) -> None:
    """Canonical mappings determine progress even when a later block is done first."""

    lines = [f"requirement {index}" for index in range(1, 151)]
    (tmp_path / "spec.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "functions.md").write_text(
        "<FG-A>\n\n<FC-A>\n\n<CK-A>\n",
        encoding="utf-8",
    )
    map_dir = tmp_path / "line_map"
    map_dir.mkdir()
    (map_dir / "spec_md_line_func_map.txt").write_text(
        "FG-A/FC-A/CK-A: 101-150\n",
        encoding="utf-8",
    )

    class Stage:
        """Provide batch persistence identity for the focused Checker."""

        name = "design_spec_line_mapping"

        def title(self) -> str:
            """Return the stage title."""

            return self.name

        def reset_continue_fail_count_with_batch_pass(self) -> None:
            """Accept one successful batch transition."""

    stage = Stage()
    checker = DesignSpecLineMapBatchChecker(
        name="design_spec_lines",
        file_list=["spec.md"],
        func_check_file="functions.md",
        map_location="line_map",
        batch_size=1,
        max_block_lines=100,
    )
    checker.set_workspace(str(tmp_path)).set_stage(stage)
    checker.on_init()

    progress = checker.get_template_data()

    assert progress["LINE_MAP_PROGRESS"] == "1/2"
    assert progress["CURRENT_LINE_BLOCKS"] == "spec.md:1-100"




def test_design_coverage_excludes_ppa_checkpoints_from_functional_scope(
    tmp_path: Path,
) -> None:
    """Performance process CKs must not become transaction coverage predicates."""

    checkpoints = _write_coverage_fixture(
        tmp_path,
        "lambda _env: False",
        "lambda _env: False",
    )
    with (tmp_path / "functions.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n## PPA\n\n<FG-PPA>\n\n"
            "### Iteration\n\n<FC-PPA-ITERATION>\n\n"
            "#### Curve\n\n<CK-PPA-CURVE>\n\nCurve evidence.\n"
        )
    checker = DesignCoverageStructureChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        check_types=["FG", "FC"],
        ignore_ck_prefix=["FG-PPA/", "FG-PPA-"],
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert result["checkpoint_count"] == 2
    assert result["performance_checkpoints_excluded"] == 1

    batch = _coverage_batch_checker(
        tmp_path, [*checkpoints, "FG-PPA/FC-PPA-ITERATION/CK-PPA-CURVE"]
    )
    assert batch.batch_task.source_task_list == checkpoints




def test_design_coverage_is_static_and_rejects_generic_predicates(
    tmp_path: Path,
) -> None:
    """Coverage gates must not execute workspace modules or accept generic evidence."""

    _write_coverage_fixture(
        tmp_path,
        "lambda _env: False",
        "lambda _env: False",
    )
    coverage_file = tmp_path / "coverage.py"
    coverage_file.write_text(
        "raise RuntimeError('must not execute')\n" + coverage_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    checker = DesignCoverageStructureChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        check_types=["FG", "FC"],
    ).set_workspace(str(tmp_path))
    passed, result = checker.do_check()
    assert passed is True, result

    _write_coverage_fixture(
        tmp_path,
        'lambda model: model.last_event == "response_observed"',
        "lambda _env: False",
    )
    passed, result = checker.do_check()
    assert passed is False
    assert "last_event_data" in result["error"]

    repeated = (
        'lambda model: model.last_event == "response_observed" '
        'and model.last_event_data.get("operation") == "add"'
    )
    _write_coverage_fixture(tmp_path, repeated, repeated)
    passed, result = checker.do_check()
    assert passed is False
    assert "duplicate predicates" in result["error"]

    batch = _coverage_batch_checker(
        tmp_path,
        ["FG-ARITH/FC-ADD/CK-FIRST", "FG-ARITH/FC-ADD/CK-SECOND"],
    )
    passed, result = batch.do_check()
    assert passed is False
    assert result["error_code"] == "design_coverage_source_invalid"
    assert result["artifact"] == "coverage.py"
    assert result["next_action"]

    (tmp_path / "architecture.md").write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n"
        "  ports:\n"
        "    - {name: valid, direction: input, width: 1, signed: false}\n"
        "```\n",
        encoding="utf-8",
    )
    (tmp_path / "adapter.py").write_text(
        '"""Public adapter surface."""\n\n'
        "class FixtureAdapter:\n"
        "    def __init__(self):\n"
        "        self.sim_time_ns = 0\n"
        "    @property\n"
        "    def last_event(self):\n"
        "        return 'initialized'\n"
        "    @property\n"
        "    def last_event_data(self):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    _write_coverage_fixture(
        tmp_path,
        "lambda model: model.unknown_state == 1",
        "lambda _env: False",
    )
    public_checker = DesignCoverageStructureChecker(
        test_dir=".",
        cov_file="coverage.py",
        doc_file="functions.md",
        architecture_file="architecture.md",
        adapter_file="adapter.py",
        check_types=["FG", "FC"],
    ).set_workspace(str(tmp_path))
    passed, result = public_checker.do_check()
    assert passed is False
    assert "undeclared public environment attributes" in result["error"]
