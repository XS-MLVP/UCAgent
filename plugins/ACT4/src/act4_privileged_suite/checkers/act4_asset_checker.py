"""UCAgent adapter for the shared ACT4 asset consistency checker.

The implementation follows UCAgent's custom checker contract: configuration is
accepted by ``__init__`` and ``do_check`` returns ``(bool, structured_data)``.
The deterministic rules live beside this adapter in the plugin package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


from . import act4_asset_consistency as core


from ucagent.checkers.base import Checker
from ucagent.util.log import info as _info


class ACT4AssetChecker(Checker):
    """Check arbitrary declared assets and ACT4 suite relationships.

    The constructor intentionally mirrors the keyword-oriented style used by
    UCAgent's YAML checker configuration.  ``manifest`` may declare additional
    assets and schema/hash contracts; the ACT4 arguments are optional so the
    same checker can be used for a manifest-only stage.
    """

    def __init__(
        self,
        suite: str = "",
        act4_root: str = ".",
        mapping: str | None = None,
        sheet_csv: str | None = None,
        normative_metadata: str | None = None,
        coverage_files: Any = None,
        coverage_patterns: Any = None,
        generator_files: Any = None,
        generator_patterns: Any = None,
        ctp_files: Any = None,
        assets: Any = None,
        manifest: Any = None,
        inventory: str | None = None,
        asset_plan: str | None = None,
        completeness: str = "source",
        checker_type: str = "all",
        check_format: bool = True,
        check_consistency: bool = True,
        require_norm_metadata: bool = False,
        require_ctp: bool = False,
        exact_sheet_coverpoints: bool = False,
        exact_sheet_rules: bool = False,
        coverage_symbol_kinds: Any = None,
        coverage_comparison_mode: str = "all",
        compare_source_mapping: bool = True,
        strict_ownership: bool = False,
        require_suite_group: bool = False,
        require_ctp_norm_table: bool = False,
        allow_cross_suite_groups: Any = None,
        fail_on_warning: bool = False,
        require_generator_mapping_coverage: bool = False,
        generator_scope_contract: str | None = None,
        require_scoped_generator_targets: bool = False,
        require_priv_testchunk_api: bool = False,
        require_generator_auto_split: bool = False,
        require_standalone_generator: bool = False,
        require_priv_coverage_semantics: bool = False,
        coverage_intent_contract: str | None = None,
        output_dir: str | None = None,
        need_human_check: bool = False,
        cfg: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if kwargs:
            raise TypeError(
                f"unsupported ACT4AssetChecker arguments: {sorted(kwargs)}"
            )
        self.suite = suite
        self.act4_root = act4_root
        self.mapping = mapping
        self.sheet_csv = sheet_csv
        self.normative_metadata = normative_metadata
        self.coverage_files = coverage_files or []
        self.coverage_patterns = coverage_patterns or []
        self.generator_files = generator_files or []
        self.generator_patterns = generator_patterns or []
        self.ctp_files = ctp_files or []
        self.assets = assets or []
        self.manifest = manifest
        self.inventory = inventory
        self.asset_plan = asset_plan
        self.completeness = completeness
        self.checker_type = checker_type
        self.check_format = bool(check_format)
        self.check_consistency = bool(check_consistency)
        self.require_norm_metadata = bool(require_norm_metadata)
        self.require_ctp = bool(require_ctp)
        self.exact_sheet_coverpoints = bool(exact_sheet_coverpoints)
        self.exact_sheet_rules = bool(exact_sheet_rules)
        self.coverage_symbol_kinds = coverage_symbol_kinds or []
        self.coverage_comparison_mode = coverage_comparison_mode
        self.compare_source_mapping = bool(compare_source_mapping)
        self.strict_ownership = bool(strict_ownership)
        self.require_suite_group = bool(require_suite_group)
        self.require_ctp_norm_table = bool(require_ctp_norm_table)
        self.allow_cross_suite_groups = allow_cross_suite_groups or []
        self.fail_on_warning = bool(fail_on_warning)
        self.require_generator_mapping_coverage = bool(require_generator_mapping_coverage)
        self.generator_scope_contract = generator_scope_contract
        self.require_scoped_generator_targets = bool(
            require_scoped_generator_targets
        )
        self.require_priv_testchunk_api = bool(require_priv_testchunk_api)
        self.require_generator_auto_split = bool(require_generator_auto_split)
        self.require_standalone_generator = bool(require_standalone_generator)
        self.require_priv_coverage_semantics = bool(require_priv_coverage_semantics)
        self.coverage_intent_contract = coverage_intent_contract
        self.output_dir = output_dir
        self._last_report: dict[str, Any] = {}
        if hasattr(self, "set_human_check_needed"):
            self.set_human_check_needed(need_human_check)

    def on_init(self):
        _info(
            "ACT4AssetChecker initialised - "
            f"suite: {self.suite!r}, root: {self.act4_root!r}"
        )
        return super().on_init()

    def get_template_data(self) -> dict[str, str]:
        summary = self._last_report.get("summary", {})
        checks = self._last_report.get("checks", {})
        return {
            "ASSET_CHECK_STATUS": str(self._last_report.get("status", "not_run")),
            "ASSET_CHECK_TYPE": str(self._last_report.get("checker_type", self.checker_type)),
            "ASSET_CHECK_ERRORS": str(summary.get("errors", 0)),
            "ASSET_CHECK_WARNINGS": str(summary.get("warnings", 0)),
            "ASSET_CHECK_FILES": str(checks.get("generic_assets", 0)),
            "ASSET_CHECK_SUMMARY": (
                f"{self._last_report.get('status', 'not_run')}: "
                f"{summary.get('errors', 0)} errors, {summary.get('warnings', 0)} warnings"
            ),
        }

    def _workspace_root(self) -> Path:
        workspace = getattr(self, "workspace", None)
        root = Path(workspace or os.getcwd()).resolve()
        configured = Path(str(self.act4_root or ".")).expanduser()
        return configured.resolve() if configured.is_absolute() else (root / configured).resolve()

    def _resolve_config_path(self, value: Any, root: Path) -> Any:
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, (list, tuple)):
            return [self._resolve_config_path(item, root) for item in value]
        text = str(value)
        if not text or os.path.isabs(text):
            return value
        workspace = Path(getattr(self, "workspace", None) or os.getcwd()).resolve()
        root_candidate = (root / text).resolve()
        workspace_candidate = (workspace / text).resolve()
        if root_candidate.exists():
            return str(root_candidate)
        if workspace_candidate.exists():
            return str(workspace_candidate)
        return value

    def do_check(self, timeout=0, is_complete=False, **kwargs: Any) -> tuple[bool, object]:
        """Check configured assets and ACT4 cross-asset consistency."""
        try:
            root = self._workspace_root()
            manifest = self.manifest
            if isinstance(manifest, str) and not os.path.isabs(manifest):
                manifest = str((Path(getattr(self, "workspace", None) or os.getcwd()).resolve() / manifest).resolve())
            report = core.run_asset_checks(
                suite=self.suite,
                act4_root=root,
                mapping=self._resolve_config_path(self.mapping, root),
                sheet_csv=self._resolve_config_path(self.sheet_csv, root),
                normative_metadata=self._resolve_config_path(
                    self.normative_metadata, root
                ),
                coverage_files=self._resolve_config_path(self.coverage_files, root),
                coverage_patterns=self.coverage_patterns,
                generator_files=self._resolve_config_path(self.generator_files, root),
                generator_patterns=self.generator_patterns,
                ctp_files=self._resolve_config_path(self.ctp_files, root),
                assets=self.assets,
                manifest=manifest,
                inventory=self._resolve_config_path(self.inventory, root),
                asset_plan=self._resolve_config_path(self.asset_plan, root),
                completeness=self.completeness if self.asset_plan else "none",
                checker_type=self.checker_type,
                check_format=self.check_format,
                check_consistency=self.check_consistency,
                require_norm_metadata=self.require_norm_metadata,
                require_ctp=self.require_ctp,
                exact_sheet_coverpoints=self.exact_sheet_coverpoints,
                exact_sheet_rules=self.exact_sheet_rules,
                coverage_symbol_kinds=self.coverage_symbol_kinds,
                coverage_comparison_mode=self.coverage_comparison_mode,
                compare_source_mapping=self.compare_source_mapping,
                strict_ownership=self.strict_ownership,
                require_suite_group=self.require_suite_group,
                require_ctp_norm_table=self.require_ctp_norm_table,
                allow_cross_suite_groups=self.allow_cross_suite_groups,
                fail_on_warning=self.fail_on_warning,
                require_generator_mapping_coverage=self.require_generator_mapping_coverage,
                generator_scope_contract=self._resolve_config_path(
                    self.generator_scope_contract, root
                ),
                require_scoped_generator_targets=self.require_scoped_generator_targets,
                require_priv_testchunk_api=self.require_priv_testchunk_api,
                require_generator_auto_split=self.require_generator_auto_split,
                require_standalone_generator=self.require_standalone_generator,
                require_priv_coverage_semantics=self.require_priv_coverage_semantics,
                coverage_intent_contract=self._resolve_config_path(
                    self.coverage_intent_contract, root
                ),
            )
        except Exception as exc:
            return False, {"error": f"ACT4 asset checker failed to initialise: {exc}"}
        self._last_report = report
        report_paths: dict[str, str] = {}
        if self.output_dir:
            workspace = Path(getattr(self, "workspace", None) or os.getcwd()).resolve()
            configured = Path(self.output_dir).expanduser()
            output_dir = configured.resolve() if configured.is_absolute() else (workspace / configured).resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            basename = self.suite or "manifest"
            json_path = output_dir / f"{basename}.asset-consistency.json"
            md_path = output_dir / f"{basename}.asset-consistency.md"
            json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            md_path.write_text(core._format_report_markdown(report), encoding="utf-8")
            report_paths = {"json": str(json_path), "markdown": str(md_path)}
        summary = report.get("summary", {})
        errors = int(summary.get("errors", 0))
        warnings = int(summary.get("warnings", 0))
        passed = errors == 0 and (not self.fail_on_warning or warnings == 0)
        if passed:
            return True, {
                "message": "ACT4 asset consistency check passed",
                "summary": report.get("summary", {}),
                "checks": report.get("checks", {}),
                "report_paths": report_paths,
                "report": report,
            }
        error_lines = [
            f"{item.get('check')}: {item.get('message')}"
            for item in report.get("findings", [])
            if item.get("severity") == "error" or self.fail_on_warning
        ]
        return False, {
            "error": error_lines[:100],
            "summary": report.get("summary", {}),
            "checks": report.get("checks", {}),
            "report_paths": report_paths,
            "report": report,
        }


__all__ = ["ACT4AssetChecker"]
