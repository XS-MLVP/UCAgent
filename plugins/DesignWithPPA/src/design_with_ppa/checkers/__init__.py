"""Deterministic stage gates for the DesignWithPPA TDD workflow."""

from .common import (
    _DEFAULT_FUNCTIONAL_CK_EXCLUDE_PREFIXES,
    _DESIGN_LABEL_IDENTIFIER_RE,
    _PLACEHOLDER,
    _PLUGIN_PYTHON_IMPORT_ROOT,
    _PROCESS_ONLY_CK_TERM_RE,
    _PYTHON_IDENTIFIER_RE,
    _TOFFEE_NODE_RE,
    _VERILOG_IDENTIFIER_RE,
    _actionable_checker_failure,
    _bounded_checker_value,
    _cfg_dut,
    _checkpoint_prefixes,
    _contains_non_default_literal,
    _contract_identity,
    _exception_contract_diagnostic,
    _failure_text,
    _functional_checkpoints,
    _hash_rows,
    _is_batch_progress,
    _line_ranges_text,
    _rows_sha256,
    _test_source_rows,
    _validated_file_rows,
    _validated_input_identity,
)

from .test_quality import (
    _api_assertion_quality_violations,
    _environment_contract_violations,
)

from .observation import (
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    _OBSERVATION_CAPTURES,
    _OBSERVATION_CYCLE_ATTRIBUTE,
    _OBSERVATION_SOURCES,
    _load_observation_contract,
    _validate_observation_source_refs,
)

from .coverage_model import (
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    _DesignCoverageEnvironmentMixin,
    _cleanup_transient_coverage_data,
    _coverage_artifact_state,
    _coverage_fixture_lifecycle_violations,
    _coverage_pipeline_status,
    _coverage_predicate_inventory,
    _coverage_public_attributes,
)

from .runtime import (
    _normalize_final_test_node,
    _parse_collected_final_nodes,
    _parse_pytest_pass_count,
    _probe_python_dut_subprocess,
    _run_pytest,
    _validate_python_dut_tree,
    _validate_workspace_python_dut,
)

from .evidence import (
    _VERILOG_SYNTHESIS_HAZARDS,
    _extract_final_toffee_cases,
    _load_final_toffee_report,
    _public_evidence_error,
    _public_pytest_failure,
    _pytest_evidence,
    _redact_backend_output,
    _rtl_regression_failure_evidence,
    _toffee_status,
    _verilog_synthesis_hazard_evidence,
    _write_toffee_snapshot,
    _yosys_width_warning_evidence,
)

from .design_contract import (
    DesignDutApiChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignLabelStructureChecker,
    DesignMarkdownFileFormatChecker,
    DesignPythonAllPassChecker,
)

from .architecture import (
    DesignArchitectureChecker,
)

from .line_map import (
    DesignLineMapReferenceChecker,
    DesignSpecLineMapBatchChecker,
)

from .refinement import (
    DesignLabelStructureRefineChecker,
    DesignRefineTestCasesChecker,
    DesignTestTemplateBatchChecker,
    _expand_declared_batch,
    _normalize_declared_batch,
)

from .test_batches import (
    DesignAllPassBatchTestsChecker,
    DesignRandomTestCasesChecker,
    DesignTestTemplateChecker,
)

from .python_contracts import (
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
)

from .regression import (
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    _BackendRegressionChecker,
)

from .rtl_validation import (
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    RTLSourceEvidenceChecker,
)

from .performance_checkers import (
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    _AGGREGATIONS,
    _METRIC_KINDS,
    _TIME_UNITS,
    _require_manifest_spec_sources,
    _validate_performance_contract,
)

from .ppa_iteration import (
    PPABaseCharacterizationChecker,
    PPACandidateOptimizationChecker,
    PPAIterationChecker,
    _DASHBOARD_SNAPSHOT_END,
    _DASHBOARD_SNAPSHOT_START,
    _PPA_SCORE_ID,
    _aggregate_contract_metrics,
    _copy_rtl_snapshot,
    _embed_dashboard_snapshot,
    _load_bound_ledger,
    _load_cached_ppa,
    _load_candidate_hypothesis,
    _metric_assessment,
    _ppa_primary_metrics,
    _ppa_selection_score,
    _primary_metric_changes,
    _public_ppa_summary,
    _resolved_workflow_ppa_config,
    _restore_rtl_snapshot,
    _run_workflow_ppa,
    select_best_accepted_record,
)

from .final_delivery import (
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    PPABestVersionChecker,
    PPAResultArtifactsChecker,
    _FINAL_RTL_SYNC_BLOCK_RE,
    _render_final_rtl_sync_block,
    _replace_final_rtl_sync_block,
)
