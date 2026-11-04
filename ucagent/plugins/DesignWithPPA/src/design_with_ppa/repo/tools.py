"""Workflow-local tools for reproducible repository-module unit validation and delivery."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ucagent.tools.uctool import UCTool

from ..contracts import diagnostic
from .common import RepoPaths
from .delivery import deliver, restore_best
from .validation import validate_unit


class RunRepoValidationArgs(BaseModel):
    """Select measurement, complete best-version restoration, or delivery of a unit."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["validate", "restore_best", "deliver"] = Field(
        default="validate", description="Validate the current unit, restore all best-version files, or rebuild and package delivery.")
    baseline: bool = Field(default=False, description="Establish the permanent original baseline before measuring candidates.")
    migration_script: bool = Field(default=False, description="Include an optional dry-run-by-default apply.py in the delivery bundle.")


class RunRepoValidation(UCTool):
    """Execute module-only build, pin-based tests, PPA, and verified delivery operations."""

    name: str = "RunRepoValidation"
    description: str = (
        "Validate the current repo/candidate against frozen logical unit workloads and its public pins. "
        "Build only the selected module and source dependencies in an independent copy; never build "
        "the entire system or write SOURCE_PATH. Use baseline=true once, then new variant_id values "
        "for candidates. restore_best restores complete versioned inputs; deliver reruns validation "
        "and verifies a source/RTL/patch bundle in a fresh copy."
    )
    args_schema: type[BaseModel] = RunRepoValidationArgs
    call_time_out: int = 36000
    _workspace: str = PrivateAttr()
    _cfg: object = PrivateAttr()

    def __init__(self, workspace: str, cfg, **kwargs):
        """Store resolved context without reading source repositories during tool creation."""

        super().__init__(**kwargs)
        self._workspace, self._cfg = workspace, cfg

    def _run(self, action="validate", baseline=False, migration_script=False, **kwargs) -> dict:
        """Run the selected managed operation and return bounded actionable diagnostics."""

        from ucagent.util.log import info

        try:
            args = RunRepoValidationArgs(action=action, baseline=baseline, migration_script=migration_script)
            paths = RepoPaths(self._workspace, self._cfg)
            info(f"[RunRepoValidation] {args.action}: preparing isolated module validation")
            if action == "deliver":
                result = deliver(paths, migration_script=migration_script)
                return {k: v for k, v in result.items() if k != "bundle_files"}
            record = restore_best(paths) if action == "restore_best" else validate_unit(paths, baseline=baseline)
            return {"status": "pass", "variant_id": record["variant_id"], "accepted": record["accepted"],
                    "verification_scope": "unit_only", "system_integration": "not_run",
                    "ppa_metrics": record["ppa_metrics"], "performance_metrics": record["performance_metrics"],
                    "report": f"{paths.output.relative_to(paths.workspace)}/repo/reports/{record['variant_id']}.json"}
        except Exception as exc:
            return diagnostic("repo_validation_failed", str(exc)[-6000:],
                              "Repair the named unit artifact or dependency using Guide_Doc/repo_module.md, then call RunRepoValidation again.",
                              artifact="repo/candidate")
