#!/usr/bin/env python3
"""Regression checks for split evaluation workflows and JSON state contracts."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

import yaml

from examples.workflow_builder.tools.workflow_builder.core import generate_workflow_spec
from examples.workflow_builder.tools.workflow_child_supervisor.core import _run_dir, _validate_runtime_target
from examples.workflow_builder.tools.workflow_evaluation_control.incremental import (
    delete_incremental_backup,
    IncrementalDeploymentError,
    deploy_incremental_changes as _deploy_incremental_changes,
    restore_incremental_backup,
    verify_incremental_application,
)
from examples.workflow_builder.tools.workflow_evaluation_control.incremental_runs import (
    IncrementalRunError,
    current_incremental_run,
    incremental_attempt_paths,
    stage_incremental_candidates,
    start_incremental_run,
)
from examples.workflow_builder.tools.workflow_evaluation_control.approvals import (
    create_suggestion,
    decide_item,
    decide_repair,
    review_items,
)
from examples.workflow_builder.tools.workflow_evaluation_control.rules import (
    REQUIRED_CHECK_IDS,
    expected_report_status,
)
from examples.workflow_builder.tools.workflow_evaluation_control.static_audit import run_static_audit
from examples.workflow_builder.tools.workflow_evaluation_control.uc_checkers import (
    EvaluationJsonReportChecker,
    IncrementalApprovalChecker,
    IncrementalAuditCoverageChecker,
    IncrementalContextReportChecker,
    IncrementalRegressionChecker,
    StaticAuditCoverageChecker,
)
from examples.workflow_builder.tools.workflow_evaluation_control.uc_tools import (
    IncrementalChangeDeployerArgs,
    IncrementalCandidateStagerArgs,
    IncrementalContextInventory,
    EvaluationCommandRunner,
)
from examples.workflow_builder.tools.workflow_config_generator.core import (
    ConfigGenerationError,
    validate_config_spec,
)
from examples.workflow_builder.tools.workflow_evaluation_control.json_store import (
    JsonStoreError,
    aggregate_summary,
    initialize_workspace,
    load_document,
    mutate_document,
    update_run_request,
    validate_workspace,
)


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def deploy_incremental_changes(
    workspace: Path,
    workflow_root: str,
    mappings: list[dict],
    approval_ids: list[str],
    change_id: str,
    manifest_path: str = "eval/applied_changes.json",
):
    """Stage legacy test fixtures in a real isolated attempt before deployment."""
    try:
        run = current_incremental_run(workspace)
    except IncrementalRunError:
        run = start_incremental_run(workspace)
    batch_id = f"batch-{change_id}"
    attempt_id = "attempt-001"
    paths = incremental_attempt_paths(workspace, run["run_id"], batch_id, attempt_id)
    staged = []
    for index, mapping in enumerate(mappings):
        updated = dict(mapping)
        source = (workspace / str(mapping.get("source", ""))).resolve()
        target_name = str(mapping.get("target", "")) or f"mapping-{index}"
        candidate = paths["candidate"] / target_name
        if source.is_file():
            candidate.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, candidate)
            updated["source"] = candidate.relative_to(workspace).as_posix()
        staged.append(updated)
    return _deploy_incremental_changes(
        workspace,
        workflow_root,
        staged,
        approval_ids,
        change_id,
        manifest_path,
        run["run_id"],
        batch_id,
        attempt_id,
    )


def check_configs() -> None:
    schema = IncrementalChangeDeployerArgs.model_json_schema()
    require(
        {"mappings", "run_id", "batch_id", "attempt_id"}.issubset(schema.get("properties", {})),
        "incremental deployer schema is incomplete",
    )
    staging_schema = IncrementalCandidateStagerArgs.model_json_schema()
    require(
        {"files", "run_id", "batch_id", "attempt_id"}.issubset(staging_schema.get("properties", {})),
        "incremental candidate stager schema is incomplete",
    )
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    require(
        'rm -rf "$(WFB_WORKSPACE)/tmp/ui_validation"' in makefile,
        "incremental startup must remove stale browser profiles before workspace scanning",
    )
    require(
        "start-inc-run" in makefile and "UCAGENT_INC_RUN_ID" in makefile,
        "incremental startup must create and export an isolated run id",
    )
    require(
        "! -name inc_runs ! -name change_history" in makefile,
        "normal clean must preserve incremental version history",
    )
    static = ("tools", "checkers", "flow", "env")
    for name in (*static, "run"):
        path = ROOT / f"eval_{name}.yaml"
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        tools = value.get("ex_tools", [])
        has_child = any("ChildWorkflowSupervisor" in item for item in tools)
        require(has_child == (name == "run"), f"{path.name} child supervisor boundary is wrong")
        require(
            any("StaticEvaluationAudit" in item for item in tools),
            f"{path.name} does not register the deterministic static audit",
        )
        require(value.get("write_dirs") == ["tmp"], f"{path.name} must expose only tmp to file tools")
        for stage in value.get("stage", []):
            for field in ("reference_files", "output_files"):
                for item in stage.get(field, []):
                    require(Path(item).suffix != "", f"{path.name} {field} contains directory-shaped path: {item}")
    inc = yaml.safe_load((ROOT / "inc.yaml").read_text(encoding="utf-8"))
    require(
        not any("ChildWorkflowSupervisor" in item for item in inc.get("ex_tools", [])),
        "incremental workflow must not run child workflows",
    )
    require(
        any("StaticEvaluationAudit" in item for item in inc.get("ex_tools", [])),
        "incremental workflow does not register the deterministic static audit",
    )
    require(
        any("IncrementalCandidateStager" in item for item in inc.get("ex_tools", [])),
        "incremental workflow does not register the controlled candidate stager",
    )
    require(
        inc.get("write_dirs") == ["tmp"],
        "incremental ordinary file tools must not write the generated workflow directly",
    )
    stages = inc.get("stage", [])
    require(
        stages and stages[0].get("name") == "understand_generated_workflow",
        "incremental workflow must establish a minimal architecture context before planning",
    )
    context_report = "tmp/inc_runs/current.json"
    require(
        all(
            context_report in stage.get("reference_files", [])
            for stage in stages[1:]
        ),
        "every incremental repair stage must consume the checked context report",
    )
    verify_stage = next(
        (stage for stage in stages if stage.get("name") == "verify_and_report_increment"),
        None,
    )
    require(verify_stage is not None, "incremental workflow lacks its final verification stage")
    verify_checkers = verify_stage.get("checker", [])
    require(
        any(
            item.get("clss", "").endswith(".IncrementalRegressionChecker")
            and item.get("args", {}).get("workflow_root") == "workflow"
            and item.get("args", {}).get("manifest_path") == "eval/applied_changes.json"
            for item in verify_checkers
        ),
        "incremental final stage must verify make check evidence against the deployed workflow",
    )
    verify_task = "\n".join(str(item) for item in verify_stage.get("task", []))
    for marker in (
        "EvaluationCommandRunner(workflow_root='workflow', command='make_check')",
        "returncode",
        "必须严格等于零",
        "禁止使用 passed_with_findings",
    ):
        require(marker in verify_task, f"incremental verification contract lacks marker: {marker}")
    discovery_references = set(stages[0].get("reference_files", []))
    for path in (
        "workflow/config.yaml",
        "workflow/config/inc.yaml",
        "workflow/.workflow/workflow_spec.yaml",
        "workflow/docs/04开发者文档-tools.md",
        "workflow/docs/05开发者文档-checkers.md",
        "res/common.json",
    ):
        require(
            path in discovery_references,
            f"incremental discovery does not track required architecture baseline {path}",
        )
    require(
        not any("**" in path for path in discovery_references),
        "incremental discovery must not recursively read every generated document or resource",
    )
    guides = (
        "evaluation_contract.md",
        "eval_tools.md",
        "eval_checkers.md",
        "eval_flow.md",
        "eval_env.md",
        "eval_run.md",
        "incremental_evaluation.md",
    )
    for name in guides:
        lines = [line for line in (ROOT / "Guide_Doc" / name).read_text(encoding="utf-8").splitlines() if line.strip()]
        require(len(lines) >= 300, f"{name} must contain at least 300 effective lines")


def check_incremental_candidate_stager() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        workflow = workspace / "workflow"
        (workflow / "config").mkdir(parents=True)
        formal = workflow / "config/inc.yaml"
        original = b"stage:\n  - name: exact-copy\n# preserve formatting\n"
        formal.write_bytes(original)
        (workflow / "outside-link.yaml").symlink_to(formal)
        run = start_incremental_run(workspace)

        result = stage_incremental_candidates(
            workspace,
            "workflow",
            run["run_id"],
            "batch-flow",
            "attempt-001",
            ["config/inc.yaml"],
        )
        candidate = workspace / result["files"][0]["candidate"]
        require(candidate.read_bytes() == original, "candidate stager did not preserve exact bytes")
        require((workspace / result["receipt_path"]).is_file(), "candidate staging receipt is missing")

        repeated = stage_incremental_candidates(
            workspace,
            "workflow",
            run["run_id"],
            "batch-flow",
            "attempt-001",
            ["config/inc.yaml"],
        )
        require(
            repeated["files"][0]["sha256"] == result["files"][0]["sha256"],
            "identical candidate staging is not idempotent",
        )
        candidate.write_text("changed candidate\n", encoding="utf-8")
        try:
            stage_incremental_candidates(
                workspace, "workflow", run["run_id"], "batch-flow", "attempt-001", ["config/inc.yaml"]
            )
        except IncrementalRunError as exc:
            require("overwrite=true" in str(exc), "candidate overwrite rejection lacks actionable guidance")
        else:
            raise AssertionError("candidate stager implicitly overwrote a modified candidate")
        stage_incremental_candidates(
            workspace,
            "workflow",
            run["run_id"],
            "batch-flow",
            "attempt-001",
            ["config/inc.yaml"],
            overwrite=True,
        )
        require(candidate.read_bytes() == original, "explicit candidate restaging did not restore formal bytes")

        for unsafe in ("../config.yaml", "/tmp/config.yaml", "./config/inc.yaml", "outside-link.yaml"):
            try:
                stage_incremental_candidates(
                    workspace, "workflow", run["run_id"], "batch-flow", "attempt-002", [unsafe]
                )
            except IncrementalRunError:
                pass
            else:
                raise AssertionError(f"candidate stager accepted unsafe path: {unsafe}")

        newer = start_incremental_run(workspace)
        try:
            stage_incremental_candidates(
                workspace, "workflow", run["run_id"], "batch-flow", "attempt-003", ["config/inc.yaml"]
            )
        except IncrementalRunError as exc:
            require("active incremental run" in str(exc), "stale run rejection is unclear")
        else:
            raise AssertionError(f"candidate stager accepted stale run after {newer['run_id']}")


def check_incremental_context_report() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        workflow = workspace / "workflow"
        (workflow / "tools").mkdir(parents=True)
        (workflow / "docs").mkdir()
        (workspace / "res").mkdir()
        (workspace / "tmp").mkdir()
        files = {
            workflow / "tools/example.py": "def run():\n    return {'ok': True}\n",
            workflow / "docs/README.md": "# User workflow\n\nRun the generated workflow.\n",
            workflow / "config.yaml": "stage: []\n",
            workspace / "res/common.json": '{"notes": [{"title": "domain rule"}]}\n',
        }
        for path, text in files.items():
            path.write_text(text, encoding="utf-8")
        report_path = workspace / "tmp/incremental_context_report.json"
        inventory = IncrementalContextInventory()
        previous_workspace = os.environ.get("UCAGENT_WORKSPACE")
        os.environ["UCAGENT_WORKSPACE"] = str(workspace)
        result = json.loads(inventory._run(action="initialize", overwrite=True))
        require(
            result["file_count"] == len(files) - 1,
            "context inventory must cover core config/docs/resources without requiring tool source",
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        updates = []
        for record in report["files"]:
            name = Path(record["path"]).name
            updates.append(
                {
                    "path": record["path"],
                    "purpose": f"{name} defines its specific part of the generated workflow fixture.",
                    "contract": f"The runtime component associated with {name} consumes this exact content.",
                    "synchronizes_with": [],
                }
            )
        updated = json.loads(
            inventory._run(
                action="update",
                architecture="The fixture connects configuration, one tool, user documentation, and domain resources.",
                runtime_flow="Configuration selects the tool, the tool returns a result, and documentation describes its use.",
                approved_change_impact="Any approved tool change must consider its configuration, behavior, and documentation.",
                cross_file_risks="A source-only change can leave configuration and documentation inconsistent with runtime behavior.",
                file_updates=updates,
            )
        )
        require(
            updated["updated_file_count"] == len(updates),
            "context inventory did not atomically merge all file analyses",
        )
        validated = json.loads(inventory._run(action="validate"))
        require(validated["valid"], f"context tool rejected its completed report: {validated}")
        if previous_workspace is None:
            os.environ.pop("UCAGENT_WORKSPACE", None)
        else:
            os.environ["UCAGENT_WORKSPACE"] = previous_workspace
        checker = IncrementalContextReportChecker()
        checker.workspace = str(workspace)
        passed, details = checker.do_check()
        require(passed, f"complete incremental context report failed: {details}")
        files[workflow / "docs/README.md"] = "# Changed documentation\n"
        (workflow / "docs/README.md").write_text(files[workflow / "docs/README.md"], encoding="utf-8")
        passed, _ = checker.do_check()
        require(not passed, "stale context report hash was accepted")


def check_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        result = initialize_workspace(workspace)
        require(len(result["created"]) == 18, "unexpected initialized document count")
        validate_workspace(workspace)
        suggestion = {
            "id": "suggestion-1",
            "title": "Preserve history",
            "description": "Do not overwrite prior report runs.",
            "status": "open",
        }
        mutate_document(workspace, "create", "eval/user_suggestions.json", record=suggestion)
        eval_dir = workspace / "eval"
        eval_dir.chmod(eval_dir.stat().st_mode & ~stat.S_IWUSR)
        mutate_document(
            workspace,
            "create",
            "eval/approvals.json",
            record={"id": "permission-test", "decision": "rejected"},
        )
        require(not (eval_dir.stat().st_mode & stat.S_IWUSR), "JSON store did not restore eval directory mode")
        eval_dir.chmod(eval_dir.stat().st_mode | stat.S_IWUSR)
        try:
            mutate_document(
                workspace,
                "update",
                "eval/user_suggestions.json",
                record=suggestion,
                expected_revision=0,
            )
        except JsonStoreError:
            pass
        else:
            raise AssertionError("stale revision was accepted")
        update_run_request(workspace, "inc", "workflow", "example", 60, 120)
        request = load_document(workspace, "eval/run_request.json")
        require(request["mode"] == "inc", "runtime mode was not persisted")
        summary = aggregate_summary(workspace)
        require(summary["totals"]["reports"] == 0, "empty reports should aggregate as not_run")
        existing = workspace / "res/common.json"
        direct = json.loads(existing.read_text(encoding="utf-8"))
        direct["notes"].append({"title": "user-owned"})
        existing.write_text(json.dumps(direct), encoding="utf-8")
        initialize_workspace(workspace)
        require(load_document(workspace, "res/common.json")["notes"], "initialize overwrote user resource data")
        created = create_suggestion(workspace, "Review retry policy", "Bound repeated failures.", "high")
        require(created["record_id"].startswith("suggestion-"), "suggestion id was not generated")
        items = review_items(workspace)
        require(any(item["title"] == "Review retry policy" for item in items), "suggestion is not reviewable")


def check_runtime_contract_delivery() -> None:
    data = {
        "workflow": {"name": "sample", "description": "sample", "version": "1"},
        "runtime_contract": {
            "example_target": "example",
            "required_input": [{"path": "rtl", "type": "directory"}, {"path": "requirements.md", "type": "file"}],
        },
        "workflow_spec": {"inputs": [], "outputs": [], "checkers": [], "stages": []},
    }
    spec = yaml.safe_load(generate_workflow_spec(data))
    require(spec["runtime_contract"] == data["runtime_contract"], "workflow spec omitted runtime_contract")
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        root = workspace / "workflow"
        (root / ".workflow").mkdir(parents=True)
        (root / "input/example/rtl").mkdir(parents=True)
        (root / "input/example/requirements.md").write_text("verify counter", encoding="utf-8")
        (root / ".workflow/workflow_spec.yaml").write_text(
            yaml.safe_dump(spec, sort_keys=False), encoding="utf-8"
        )
        _validate_runtime_target(root, "example")
        require(
            _run_dir(workspace, "run-1") == workspace / "tmp/eval_runs/run-1",
            "child run evidence is not rooted in outer tmp",
        )


def check_approved_deployment() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        (workspace / "workflow").mkdir()
        candidate = workspace / "tmp/inc_candidates/run-1/README.md"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("approved update\n", encoding="utf-8")
        finding = {
            "id": "finding-1",
            "fingerprint": "fingerprint-1",
            "severity": "high",
            "category": "contract",
            "component": "config.yaml",
            "title": "Invalid stage contract",
            "description": "The stage cannot resolve a required runtime value.",
            "expected": "Every runtime value is declared.",
            "actual": "One runtime value is not declared.",
            "severity_reason": "The stage necessarily fails before producing its output.",
            "confidence": "confirmed",
            "requirement_refs": ["FLOW-PLACEHOLDERS"],
            "evidence": [{"kind": "source", "path": "config.yaml", "location": "stage[0]"}],
            "impact": "The workflow cannot complete.",
            "recommendation": "Declare or replace the value.",
            "repro": ["Run the static audit."],
            "status": "open",
        }
        mutate_document(
            workspace,
            "create",
            "eval/flow_report.json",
            record={
                "run_id": "flow-1",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:01+00:00",
                "checks": [{"id": "FLOW-PLACEHOLDERS", "status": "failed", "summary": "unknown symbol", "evidence": ["config.yaml"]}],
                "findings": [finding],
            },
        )
        decision = decide_item(workspace, "finding-1", "approved", "Apply the bounded placeholder fix.")
        approval_id = decision["record_id"]
        deploy_incremental_changes(
            workspace,
            "workflow",
            [{
                "source": "tmp/inc_candidates/run-1/README.md",
                "target": "README.md",
                "approval_ids": [approval_id],
                "rationale": "Apply the explicitly approved documentation correction.",
            }],
            [approval_id],
            "change-1",
        )
        passed, details = verify_incremental_application(workspace, "workflow")
        require(passed, f"approved deployment did not verify: {details}")
        uncited = workspace / "tmp/inc_candidates/run-2/README.md"
        uncited.parent.mkdir(parents=True)
        uncited.write_text("unscoped update\n", encoding="utf-8")
        try:
            deploy_incremental_changes(
                workspace,
                "workflow",
                [{
                    "source": "tmp/inc_candidates/run-2/README.md",
                    "target": "README.md",
                    "approval_ids": [],
                    "rationale": "This change has no item-level authorization.",
                }],
                [approval_id],
                "change-2",
            )
        except IncrementalDeploymentError as exc:
            require("approval_ids" in str(exc), "uncited mapping failed for an unrelated reason")
        else:
            raise AssertionError("deployment accepted a file without item-level approval")
        reviewed_candidate = workspace / "tmp/inc_candidates/run-2/reviewed-README.md"
        reviewed_candidate.write_text("reworked approved update\n", encoding="utf-8")
        reviewed_mapping = [{
            "source": "tmp/inc_candidates/run-2/reviewed-README.md",
            "target": "README.md",
            "approval_ids": [approval_id],
            "rationale": "Rework the same approved documentation correction after user review.",
        }]
        deploy_incremental_changes(
            workspace, "workflow", reviewed_mapping, [approval_id], "change-review-reworked"
        )
        require(
            (workspace / "workflow/README.md").read_text(encoding="utf-8") == "reworked approved update\n",
            "a pending deployment incorrectly blocked a same-scope repair attempt",
        )
        decide_repair(
            workspace,
            "change-review-reworked::README.md",
            "approved",
            "Keep this legacy acceptance metadata for compatibility testing.",
        )
        passed, details = verify_incremental_application(workspace, "workflow")
        require(passed, f"latest reworked deployment did not supersede historical hashes: {details}")
        same_approval_candidate = workspace / "tmp/inc_candidates/run-2/repeat-README.md"
        same_approval_candidate.write_text("repeat old authorization\n", encoding="utf-8")
        deploy_incremental_changes(
            workspace,
            "workflow",
            [{
                "source": "tmp/inc_candidates/run-2/repeat-README.md",
                "target": "README.md",
                "approval_ids": [approval_id],
                "rationale": "Reuse the same current approval for the next repair attempt.",
            }],
            [approval_id],
            "change-repeat-approval",
        )
        require(
            (workspace / "workflow/README.md").read_text(encoding="utf-8") == "repeat old authorization\n",
            "legacy accepted review metadata incorrectly blocked a successor attempt",
        )

        next_finding = dict(finding)
        next_finding.update(
            id="finding-2",
            fingerprint="fingerprint-2",
            title="Documentation omits the new runtime contract",
            description="The accepted document needs an additional independently approved contract update.",
            actual="The additional runtime contract is absent.",
            recommendation="Add the newly approved runtime contract.",
        )
        mutate_document(
            workspace,
            "create",
            "eval/flow_report.json",
            record={
                "run_id": "flow-2",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-02T00:00:00+00:00",
                "finished_at": "2026-01-02T00:00:01+00:00",
                "checks": [{
                    "id": "FLOW-DOCUMENTATION",
                    "status": "failed",
                    "summary": "new documentation contract is missing",
                    "evidence": ["README.md"],
                }],
                "findings": [next_finding],
            },
        )
        next_approval_id = decide_item(
            workspace,
            "finding-2",
            "approved",
            "Apply the newly identified and independently reviewed documentation contract.",
        )["record_id"]
        checker = IncrementalApprovalChecker()
        checker.workspace = str(workspace)
        passed, details = checker.do_check()
        require(
            passed,
            f"evaluation rerun invalidated historical deployment authorization: {details}",
        )
        strict_checker = IncrementalApprovalChecker(require_all_current=True)
        strict_checker.workspace = str(workspace)
        passed, details = strict_checker.do_check()
        require(
            not passed and next_approval_id in details.get("current_approved_ids", []),
            f"strict approval coverage did not report the newly approved but undeployed item: {details}",
        )
        successor = workspace / "tmp/inc_candidates/run-2/successor-README.md"
        successor.write_text("approved successor update\n", encoding="utf-8")
        deploy_incremental_changes(
            workspace,
            "workflow",
            [{
                "source": "tmp/inc_candidates/run-2/successor-README.md",
                "target": "README.md",
                "approval_ids": [next_approval_id],
                "rationale": "Apply the independently approved successor documentation contract.",
            }],
            [next_approval_id],
            "change-approved-successor",
        )
        successor_entry = next(
            item
            for item in load_document(workspace, "eval/applied_changes.json")["entries"]
            if item["id"] == "change-approved-successor"
        )
        successor_change = successor_entry["applied_changes"][0]
        require(
            successor_change["supersedes"]["repair_id"]
            == "change-repeat-approval::README.md",
            "successor deployment did not record its prior repair",
        )
        passed, details = strict_checker.do_check()
        require(
            passed,
            f"strict approval coverage did not accept complete current approval deployment: {details}",
        )
        require(
            {item["id"] for item in successor_entry["approval_provenance"]}
            == {next_approval_id},
            "successor deployment did not freeze approval provenance",
        )
        passed, details = checker.do_check()
        require(passed, f"new deployment approval snapshot failed validation: {details}")
        approval_id = next_approval_id
        malformed = workspace / "tmp/inc_candidates/run-3/config.yaml"
        malformed.parent.mkdir(parents=True)
        malformed.write_text("stage:\n  - name: broken\n     task: invalid\n", encoding="utf-8")
        original_target = workspace / "workflow/config.yaml"
        original_target.write_text("stage: []\n", encoding="utf-8")
        try:
            deploy_incremental_changes(
                workspace,
                "workflow",
                [{
                    "source": "tmp/inc_candidates/run-3/config.yaml",
                    "target": "config.yaml",
                    "approval_ids": [approval_id],
                    "rationale": "Apply the explicitly approved configuration correction.",
                }],
                [approval_id],
                "change-3",
            )
        except IncrementalDeploymentError as exc:
            require("structurally valid" in str(exc), "malformed YAML failed for an unrelated reason")
        else:
            raise AssertionError("deployment accepted malformed YAML")
        require(
            original_target.read_text(encoding="utf-8") == "stage: []\n",
            "malformed candidate changed the target before validation completed",
        )
        readonly = workspace / "tmp/inc_candidates/run-4/config.yaml"
        readonly.parent.mkdir(parents=True)
        readonly.write_text("stage:\n  - name: approved\n", encoding="utf-8")
        original_target.chmod(0o444)
        deploy_incremental_changes(
            workspace,
            "workflow",
            [{
                "source": "tmp/inc_candidates/run-4/config.yaml",
                "target": "config.yaml",
                "approval_ids": [approval_id],
                "rationale": "Apply the approved configuration to a runtime-protected target.",
            }],
            [approval_id],
            "change-4",
        )
        manifest = load_document(workspace, "eval/applied_changes.json")
        config_change = next(
            item
            for entry in manifest["entries"]
            if entry["id"] == "change-4"
            for item in entry["applied_changes"]
        )
        backup = config_change["backup"]
        require(backup["existed"], "deployment did not archive the old target")
        require(
            (workspace / backup["path"]).read_text(encoding="utf-8") == "stage: []\n",
            "archived target content is incorrect",
        )
        require(
            original_target.read_text(encoding="utf-8") == "stage:\n  - name: approved\n",
            "deployment could not atomically replace a read-only target",
        )
        restored = restore_incremental_backup(
            workspace,
            "change-4::config.yaml",
            "The deployed configuration must be rolled back for deterministic verification.",
        )
        require(
            original_target.read_text(encoding="utf-8") == "stage: []\n",
            "historical configuration was not restored",
        )
        restore_entry = next(
            item
            for item in load_document(workspace, "eval/applied_changes.json")["entries"]
            if item["id"] == restored["id"]
        )
        require(
            restore_entry["applied_changes"][0]["backup"]["existed"],
            "restore did not preserve the displaced current version",
        )
        deleted = delete_incremental_backup(
            workspace,
            "change-4::config.yaml",
            "The original archived version has already been restored and is no longer needed.",
        )
        require(not (workspace / deleted["deleted_path"]).exists(), "history deletion left the file behind")
        deleted_change = next(
            item
            for entry in load_document(workspace, "eval/applied_changes.json")["entries"]
            if entry["id"] == "change-4"
            for item in entry["applied_changes"]
        )
        require(deleted_change["backup"].get("deleted_at"), "history deletion lacks audit metadata")
        passed, details = verify_incremental_application(workspace, "workflow")
        require(passed, f"deleted historical source broke current deployment verification: {details}")


def check_static_audit_and_status_gate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        root = workspace / "workflow"
        root.mkdir()
        (root / "config.yaml").write_text(
            """
template_overwrite:
  INPUT_ROOT: input/{DUT}
stage:
  - name: analyze
    task: ["Read {UNDECLARED_INPUT} and write a report."]
    reference_files: ["{UNDECLARED_INPUT}/design.sv"]
    output_files: ["{OUT}/{DUT}/report.json"]
""".strip(),
            encoding="utf-8",
        )
        audit = run_static_audit(workspace)
        placeholder_findings = [
            item for item in audit["findings"] if item["rule_id"] == "FLOW-PLACEHOLDERS"
        ]
        require(placeholder_findings, "generic unknown placeholder was not detected")
        require(
            any("UNDECLARED_INPUT" in item["actual"] for item in placeholder_findings),
            "audit appears tied to one example placeholder instead of collecting symbols",
        )
        initialize_workspace(workspace)
        audit_path = workspace / "tmp/eval_static_audit/flow.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        mutate_document(
            workspace,
            "create",
            "eval/flow_report.json",
            record={
                "run_id": "flow-omission",
                "contract_version": 2,
                "status": "passed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:01+00:00",
                "checks": [
                    {"id": item, "status": "passed", "summary": item, "evidence": ["fixture"]}
                    for item in REQUIRED_CHECK_IDS["flow"]
                ],
                "findings": [],
            },
        )
        coverage = StaticAuditCoverageChecker()
        coverage.workspace = str(workspace)
        covered, details = coverage.do_check()
        require(not covered, f"flow report was allowed to omit deterministic high-risk evidence: {details}")
        audit_finding = next(
            item
            for item in audit["findings"]
            if item.get("severity") in {"critical", "high"}
        )
        mutate_document(
            workspace,
            "create",
            "eval/flow_report.json",
            record={
                "run_id": "flow-direct-audit-identity",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-01T00:00:02+00:00",
                "finished_at": "2026-01-01T00:00:03+00:00",
                "checks": [
                    {"id": item, "status": "passed", "summary": item, "evidence": ["fixture"]}
                    for item in REQUIRED_CHECK_IDS["flow"]
                ],
                "findings": [{
                    "id": "finding-direct-audit-identity",
                    "rule_id": audit_finding["rule_id"],
                    "fingerprint": "direct-audit-identity",
                    "severity": audit_finding["severity"],
                    "category": "configuration",
                    "component": audit_finding["path"],
                    "path": audit_finding["path"],
                    "title": "Deterministic audit finding",
                    "description": "The deterministic audit finding is preserved by identity.",
                    "expected": audit_finding.get("expected", "valid configuration"),
                    "actual": audit_finding.get("actual", "invalid configuration"),
                    "severity_reason": "The deterministic audit classified this finding as high risk.",
                    "confidence": "confirmed",
                    "requirement_refs": ["FLOW-CONFIG-001"],
                    "evidence": [{
                        "kind": "source",
                        "path": audit_finding["path"],
                        "location": audit_finding.get("location", ""),
                        "observation": "The report copies audit identity without overloading requirement_refs.",
                    }],
                    "impact": "The generated workflow contract is invalid.",
                    "recommendation": "Correct the audited configuration.",
                    "repro": ["Run StaticEvaluationAudit."],
                    "status": "open",
                }],
            },
        )
        covered, details = coverage.do_check()
        require(
            covered,
            f"direct finding.rule_id/path audit identity was rejected: {details}",
        )
        (root / "config.yaml").write_text(
            """
template_overwrite:
  INPUT_ROOT: input
stage:
  - name: analyze
    task: ["Read {INPUT_ROOT}/{DUT}/design.sv and write a report."]
    reference_files: ["{INPUT_ROOT}/{DUT}/design.sv"]
    output_files: ["{OUT}/{DUT}/report.json"]
""".strip(),
            encoding="utf-8",
        )
        valid_audit = run_static_audit(workspace)
        require(
            not [item for item in valid_audit["findings"] if item["rule_id"] == "FLOW-PLACEHOLDERS"],
            "declared runtime placeholder was rejected",
        )
        (root / "config.yaml").write_text(
            """
template_overwrite:
  INPUT_ROOT: input/{DUT}
stage:
  - name: analyze
    task: ["Read {INPUT_ROOT}/{DUT}/design.sv and write a report."]
    reference_files: ["{INPUT_ROOT}/{DUT}/design.sv"]
    output_files: ["{OUT}/{DUT}/report.json"]
""".strip(),
            encoding="utf-8",
        )
        nested_audit = run_static_audit(workspace)
        nested_findings = [
            item
            for item in nested_audit["findings"]
            if item["rule_id"] == "FLOW-PLACEHOLDERS"
        ]
        require(
            any("expands the same built-in symbol" in item["message"] for item in nested_findings),
            "composed template path duplication was not rejected",
        )
        (root / ".workflow").mkdir()
        (root / ".workflow/workflow_spec.yaml").write_text(
            yaml.safe_dump(
                {
                    "stages": [
                        {
                            "name": "analyze",
                            "reference_files": ["input/{DUT}/design.sv"],
                            "output_files": ["{OUT}/{DUT}/report.json"],
                            "checker": [
                                {
                                    "name": "LintOutputChecker",
                                    "args": {"lint_path": "{OUT}/{DUT}/report.json"},
                                }
                            ],
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (root / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "stage": [
                        {
                            "name": "analyze",
                            "reference_files": ["input/{DUT}/design.sv"],
                            "output_files": ["{OUT}/{DUT}/report.json"],
                            "checker": [],
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        drift_audit = run_static_audit(workspace)
        require(
            any(
                item["rule_id"] == "FLOW-CONFIG-SYNC"
                and item["location"] == "stage[0].checker"
                for item in drift_audit["findings"]
            ),
            "workflow_spec/config checker drift was not detected",
        )
        matching_stage = {
            "name": "analyze",
            "reference_files": ["input/{DUT}/design.sv"],
            "output_files": ["{OUT}/{DUT}/report.json"],
            "checker": [
                {
                    "name": "LintOutputChecker",
                    "args": {"lint_path": "{OUT}/{DUT}/report.json"},
                }
            ],
        }
        (root / "config.yaml").write_text(
            yaml.safe_dump({"stage": [matching_stage]}, sort_keys=False),
            encoding="utf-8",
        )
        (root / "config/inc.yaml").parent.mkdir(parents=True)
        (root / "config/inc.yaml").write_text(
            yaml.safe_dump({"stage": [matching_stage]}, sort_keys=False),
            encoding="utf-8",
        )
        shared_stage_audit = run_static_audit(workspace)
        require(
            not [
                item
                for item in shared_stage_audit["findings"]
                if item["rule_id"] == "FLOW-CONFIG-SYNC"
                and "duplicated" in item["message"]
            ],
            "a valid stage shared by main and incremental configs was rejected",
        )
        (root / "config/inc.yaml").write_text(
            yaml.safe_dump({"stage": [matching_stage, matching_stage]}, sort_keys=False),
            encoding="utf-8",
        )
        duplicate_stage_audit = run_static_audit(workspace)
        require(
            any(
                item["rule_id"] == "FLOW-CONFIG-SYNC"
                and "within one generated configuration" in item["message"]
                for item in duplicate_stage_audit["findings"]
            ),
            "a duplicate stage inside one runtime config was not rejected",
        )
        workflow_spec = yaml.safe_load(
            (root / ".workflow/workflow_spec.yaml").read_text(encoding="utf-8")
        )
        workflow_spec["checkers"] = [{
            "name": "JsonFixtureChecker",
            "fixtures": [{
                "path": ".workflow/checker_tests/cases/JsonFixtureChecker/valid.json",
                "content": '{"outer": {"inner": {"value": true}}}',
            }],
        }]
        (root / ".workflow/workflow_spec.yaml").write_text(
            yaml.safe_dump(workflow_spec, sort_keys=False),
            encoding="utf-8",
        )
        (root / "config/inc.yaml").write_text(
            yaml.safe_dump({"stage": [matching_stage]}, sort_keys=False),
            encoding="utf-8",
        )
        nested_json_audit = run_static_audit(workspace)
        require(
            not [
                item
                for item in nested_json_audit["findings"]
                if item["rule_id"] == "FLOW-PLACEHOLDERS"
                and item["location"].endswith(".content")
            ],
            "nested JSON fixture braces were misclassified as template syntax",
        )
        double_brace_stage = dict(matching_stage)
        double_brace_stage["task"] = ["Read input/{{TARGET}}/design.sv."]
        (root / "config/inc.yaml").write_text(
            yaml.safe_dump({"stage": [double_brace_stage]}, sort_keys=False),
            encoding="utf-8",
        )
        double_brace_audit = run_static_audit(workspace)
        require(
            any(
                item["rule_id"] == "FLOW-PLACEHOLDERS"
                and "Double-brace syntax" in item["message"]
                for item in double_brace_audit["findings"]
            ),
            "a real double-brace runtime placeholder was not rejected",
        )
    checks = [{"id": check_id, "status": "passed"} for check_id in REQUIRED_CHECK_IDS["flow"]]
    require(
        expected_report_status(checks, [{"severity": "high", "status": "open"}]) == "failed",
        "high finding did not force failed status",
    )
    require(
        expected_report_status(checks, [{"severity": "medium", "status": "open"}]) == "passed_with_findings",
        "medium finding did not produce passed_with_findings",
    )
    config_spec = yaml.safe_load(
        (ROOT / "tools/workflow_config_generator/test_data/config_spec.yaml").read_text(encoding="utf-8")
    )
    config_spec["stages"][0]["task"].append("Read {ARBITRARY_UNKNOWN_SYMBOL}.")
    try:
        validate_config_spec(config_spec)
    except ConfigGenerationError as exc:
        require(
            "ARBITRARY_UNKNOWN_SYMBOL" in str(exc),
            "config generator rejected the spec for an unrelated reason",
        )
    else:
        raise AssertionError("config generator accepted an arbitrary unknown runtime symbol")


def check_projected_semantic_gate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        root = workspace / "workflow"
        root.mkdir()
        (root / "config.yaml").write_text(
            (
                "template_overwrite:\n"
                "  INPUT_ROOT: input\n"
                "stage:\n"
                "  - name: input\n"
                "    checker:\n"
                "      - name: InputContractChecker\n"
                "        clss: checkers.input_contract_checker.InputContractChecker\n"
                "        args:\n"
                "          path: '{INPUT_ROOT}/{DUT}'\n"
            ),
            encoding="utf-8",
        )
        finding = {
            "id": "finding-projection",
            "fingerprint": "fingerprint-projection",
            "severity": "high",
            "category": "contract",
            "component": "config.yaml",
            "title": "Repair the input path",
            "description": "The input path contract requires an approved correction.",
            "expected": "A concrete single-pass path.",
            "actual": "The old path is incorrect.",
            "severity_reason": "The input stage cannot start.",
            "confidence": "confirmed",
            "requirement_refs": ["FLOW-PLACEHOLDERS"],
            "evidence": [{"kind": "source", "path": "config.yaml", "location": "template_overwrite"}],
            "impact": "The workflow cannot start.",
            "recommendation": "Use a concrete template value.",
            "repro": ["Run static audit."],
            "status": "open",
        }
        mutate_document(
            workspace,
            "create",
            "eval/flow_report.json",
            record={
                "run_id": "flow-projection",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:01+00:00",
                "checks": [{"id": "FLOW-PLACEHOLDERS", "status": "failed", "summary": "path", "evidence": ["config.yaml"]}],
                "findings": [finding],
            },
        )
        approval_id = decide_item(
            workspace,
            "finding-projection",
            "approved",
            "Apply only a deterministic input-path correction.",
        )["record_id"]
        candidate = workspace / "tmp/inc_candidates/current/config.yaml"
        candidate.parent.mkdir(parents=True)
        candidate.write_text(
            (
                "template_overwrite:\n"
                "  INPUT_ROOT: input/{DUT}\n"
                "stage:\n"
                "  - name: input\n"
                "    checker:\n"
                "      - name: InputContractChecker\n"
                "        clss: checkers.input_contract_checker.InputContractChecker\n"
                "        args:\n"
                "          path: '{INPUT_ROOT}/{DUT}'\n"
            ),
            encoding="utf-8",
        )
        try:
            deploy_incremental_changes(
                workspace,
                "workflow",
                [{
                    "source": "tmp/inc_candidates/current/config.yaml",
                    "target": "config.yaml",
                    "approval_ids": [approval_id],
                    "rationale": "Apply the approved input path correction without unrelated changes.",
                }],
                [approval_id],
                "projection-rejected",
            )
        except IncrementalDeploymentError as exc:
            require(
                "projected deployment" in str(exc),
                "semantic projection failed for an unrelated reason",
            )
        else:
            raise AssertionError("deployment accepted a nested runtime placeholder")
        require(
            (root / "config.yaml").read_text(encoding="utf-8")
            == (
                "template_overwrite:\n"
                "  INPUT_ROOT: input\n"
                "stage:\n"
                "  - name: input\n"
                "    checker:\n"
                "      - name: InputContractChecker\n"
                "        clss: checkers.input_contract_checker.InputContractChecker\n"
                "        args:\n"
                "          path: '{INPUT_ROOT}/{DUT}'\n"
            ),
            "rejected semantic projection changed the formal target",
        )


def check_incremental_no_change_gate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        audit_path = workspace / "tmp/eval_static_audit/incremental.json"
        audit_path.parent.mkdir(parents=True)
        audit_path.write_text(
            json.dumps({"status": "passed", "findings": []}),
            encoding="utf-8",
        )
        checks = [
            {
                "id": check_id,
                "status": "passed",
                "summary": f"{check_id} revalidated",
                "evidence": [{"kind": "source", "path": "workflow/config.yaml", "observation": "verified"}],
            }
            for check_id in REQUIRED_CHECK_IDS["incremental"]
        ]
        mutate_document(
            workspace,
            "create",
            "eval/incremental_report.json",
            record={
                "run_id": "inc-no-change-clean",
                "contract_version": 2,
                "status": "passed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:00:01+00:00",
                "summary": {"verdict": "no_change"},
                "checks": checks,
                "findings": [],
            },
        )
        checker = IncrementalAuditCoverageChecker()
        checker.workspace = str(workspace)
        passed, details = checker.do_check()
        require(passed, f"clean revalidated no_change was rejected: {details}")
        skipped = [dict(item) for item in checks]
        skipped[0]["status"] = "skipped"
        mutate_document(
            workspace,
            "create",
            "eval/incremental_report.json",
            record={
                "run_id": "inc-no-change-skipped",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-01T00:00:02+00:00",
                "finished_at": "2026-01-01T00:00:03+00:00",
                "summary": {"verdict": "no_change"},
                "checks": skipped,
                "findings": [],
            },
        )
        passed, _ = checker.do_check()
        require(not passed, "no_change was allowed to skip deterministic revalidation")
        audit_path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "findings": [
                        {
                            "rule_id": "FLOW-CONFIG-SYNC",
                            "severity": "high",
                            "path": "config.yaml",
                            "location": "stage[0].checker",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        passed, details = checker.do_check()
        require(
            not passed and "omitted" in json.dumps(details),
            "incremental report was allowed to omit a deterministic high-risk finding",
        )
        failed_checks = [dict(item) for item in checks]
        next(item for item in failed_checks if item["id"] == "INC-SOURCE-SYNC")["status"] = "failed"
        mutate_document(
            workspace,
            "create",
            "eval/incremental_report.json",
            record={
                "run_id": "inc-reproducing-finding",
                "contract_version": 2,
                "status": "failed",
                "started_at": "2026-01-01T00:00:04+00:00",
                "finished_at": "2026-01-01T00:00:05+00:00",
                "summary": {"verdict": "changes_applied"},
                "checks": failed_checks,
                "findings": [{
                    "id": "finding-sync",
                    "rule_id": "FLOW-CONFIG-SYNC",
                    "fingerprint": "fingerprint-sync",
                    "severity": "high",
                    "category": "configuration",
                    "component": "config.yaml",
                    "title": "Stage checker drift",
                    "description": "The runtime checker binding differs from the central specification.",
                    "expected": "Matching checker bindings.",
                    "actual": "The binding still differs.",
                    "severity_reason": "The configured checker does not validate the planned output.",
                    "confidence": "confirmed",
                    "requirement_refs": ["FLOW-CONFIG-001"],
                    "evidence": [{
                        "kind": "source",
                        "path": "config.yaml",
                        "location": "stage[0].checker",
                        "observation": "The deterministic audit still reproduces the drift.",
                    }],
                    "impact": "The runtime validation contract is incomplete.",
                    "recommendation": "Synchronize the central specification and runtime configuration.",
                    "repro": ["Run StaticEvaluationAudit."],
                    "status": "fix_applied_pending_recheck",
                }],
            },
        )
        passed, details = checker.do_check()
        require(
            not passed and "must remain open" in json.dumps(details),
            "a still-reproducing deterministic finding was allowed to claim a fix",
        )


def check_incremental_receipt_gate() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        root = workspace / "workflow"
        root.mkdir()
        (root / "config.yaml").write_text("stage: []\n", encoding="utf-8")
        (root / "config").mkdir()
        (root / "config/inc.yaml").write_text("stage: []\n", encoding="utf-8")
        (root / "Makefile").write_text("check:\n\t@true\n", encoding="utf-8")
        candidate = workspace / "tmp/legacy/README.md"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("version one\n", encoding="utf-8")
        suggestion_id = create_suggestion(
            workspace,
            "Update readme",
            "Apply one bounded readme correction for receipt verification.",
            "high",
        )["record_id"]
        approval_id = decide_item(
            workspace,
            suggestion_id,
            "approved",
            "Authorize only the bounded readme correction.",
        )["record_id"]
        deploy_incremental_changes(
            workspace,
            "workflow",
            [{
                "source": candidate.relative_to(workspace).as_posix(),
                "target": "README.md",
                "approval_ids": [approval_id],
                "rationale": "Apply the approved readme correction for receipt validation.",
            }],
            [approval_id],
            "receipt-change",
        )
        run = current_incremental_run(workspace)
        prior = os.environ.get("UCAGENT_INC_RUN_ID")
        prior_workspace = os.environ.get("UCAGENT_WORKSPACE")
        os.environ["UCAGENT_INC_RUN_ID"] = run["run_id"]
        os.environ["UCAGENT_WORKSPACE"] = str(workspace)
        try:
            runner = EvaluationCommandRunner()
            result = json.loads(runner._run(workflow_root="workflow", command="make_check"))
            require(result["returncode"] == 0 and result.get("receipt_path"), "make check receipt was not recorded")
            checker = IncrementalRegressionChecker(workflow_root="workflow")
            checker.workspace = str(workspace)
            passed, details = checker.do_check()
            require(passed, f"fresh make check receipt was rejected: {details}")
            (root / "config.yaml").write_text("stage: []\n# unverified drift\n", encoding="utf-8")
            passed, details = checker.do_check()
            require(
                not passed and "changed after" in str(details.get("error", "")),
                "workflow drift did not invalidate the make check receipt",
            )
        finally:
            if prior is None:
                os.environ.pop("UCAGENT_INC_RUN_ID", None)
            else:
                os.environ["UCAGENT_INC_RUN_ID"] = prior
            if prior_workspace is None:
                os.environ.pop("UCAGENT_WORKSPACE", None)
            else:
                os.environ["UCAGENT_WORKSPACE"] = prior_workspace


def check_checker_reachability_gate() -> None:
    """Synthetic malformed fields cannot become blocking findings without a real writer path."""
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        checks = [
            {
                "id": check_id,
                "status": "passed",
                "summary": f"Validated {check_id}.",
                "evidence": [{
                    "kind": "source",
                    "path": "workflow/checkers/example.py",
                    "location": "do_check",
                    "observation": "Direct source inspection completed.",
                }],
            }
            for check_id in REQUIRED_CHECK_IDS["checkers"]
        ]
        positive = next(item for item in checks if item["id"] == "CHECKERS-POSITIVE")
        positive["evidence"].append({
            "kind": "producer_checker",
            "producer": "workflow/tools/ExampleProducer.py",
            "checker": "workflow/checkers/example.py",
            "artifact": "tmp/integration/example.json",
            "observation": "The real producer output was passed to the bound Checker.",
        })
        finding = {
            "id": "synthetic-shape",
            "fingerprint": "synthetic-shape-v1",
            "severity": "medium",
            "category": "robustness",
            "component": "workflow/checkers/example.py",
            "title": "Synthetic field shape throws",
            "description": "A manually mutated field causes an exception.",
            "expected": "The Checker rejects reachable invalid artifacts.",
            "actual": "A synthetic mutation throws.",
            "severity_reason": "The case has not been shown reachable.",
            "confidence": "confirmed",
            "requirement_refs": ["CHECKERS-CHALLENGE"],
            "evidence": [{
                "kind": "test",
                "path": "tmp/tests/test_synthetic.py",
                "location": "test_invalid_shape",
                "observation": "The handcrafted fixture throws.",
            }],
            "impact": "Unknown until reachability is proven.",
            "recommendation": "Trace the actual producer before filing a defect.",
            "repro": ["Run the synthetic fixture."],
            "status": "open",
        }
        run = {
            "run_id": "checkers-reachability",
            "contract_version": 2,
            "status": "passed_with_findings",
            "started_at": "2026-08-06T00:00:00+00:00",
            "finished_at": "2026-08-06T00:01:00+00:00",
            "target": {"workflow_root": "workflow", "revision": "test"},
            "checks": checks,
            "findings": [finding],
            "metrics": {},
        }
        mutate_document(workspace, "create", "eval/checkers_report.json", record=run)
        checker = EvaluationJsonReportChecker(
            report_path="eval/checkers_report.json",
            expected_report_type="checkers",
        )
        checker.workspace = str(workspace)
        passed, details = checker.do_check()
        require(
            not passed and "lacks reachability evidence" in json.dumps(details),
            "synthetic malformed finding passed without reachability evidence",
        )

        finding["severity"] = "info"
        finding["confidence"] = "suspected"
        finding["evidence"].append({
            "kind": "reachability",
            "producer": "workflow/tools/ExampleProducer.py",
            "artifact": "output/example.json:field",
            "reachable": False,
            "observation": "The registered producer always emits a list; no alternate writer exists.",
        })
        run["status"] = "passed"
        mutate_document(
            workspace,
            "update",
            "eval/checkers_report.json",
            record=run,
            record_id=run["run_id"],
        )
        passed, details = checker.do_check()
        require(passed, f"non-blocking unreachable observation was rejected: {details}")


def main() -> None:
    check_configs()
    check_incremental_candidate_stager()
    check_incremental_context_report()
    check_store()
    check_runtime_contract_delivery()
    check_approved_deployment()
    check_static_audit_and_status_gate()
    check_projected_semantic_gate()
    check_incremental_no_change_gate()
    check_incremental_receipt_gate()
    check_checker_reachability_gate()
    print("evaluation split regression: PASS")


if __name__ == "__main__":
    main()
