#!/usr/bin/env python3
"""Regression checks for the local evaluation review HTTP interface."""

from __future__ import annotations

import json
import hashlib
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from examples.workflow_builder.tools.workflow_evaluation_control.json_store import load_document, mutate_document
from examples.workflow_builder.tools.workflow_evaluation_control import design_monitor
from examples.workflow_builder.tools.workflow_evaluation_control.review_server import (
    ReviewHandler,
    ThreadingHTTPServer,
    initialize_workspace,
    serve,
)


def request_json(base_url: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        initialize_workspace(workspace)
        target = workspace / "workflow/config.yaml"
        target.parent.mkdir()
        target.write_text("stage: []\n", encoding="utf-8")
        (workspace / "workflow/tools").mkdir()
        (workspace / "workflow/tools/example.py").write_text("print('ok')\n", encoding="utf-8")
        (workspace / "workflow/output").mkdir()
        (workspace / "workflow/output/result.bin").write_bytes(b"\x00\x01\x02")
        (workspace / "workflow/large.log").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        (workspace / "workflow/config-link.yaml").symlink_to("config.yaml")
        ucagent = workspace / ".ucagent"
        ucagent.mkdir()
        (ucagent / "ucagent_info.json").write_text(json.dumps({
            "version": "test",
            "stage_index": 1,
            "all_completed": False,
            "time_begin": 100.0,
            "time_end": None,
            "is_agent_exit": False,
            "stages_info": {
                "0": {"task": {"title": "Stage zero"}, "is_completed": True, "check_pass": True, "fail_count": 0, "time_cost": 4},
                "1": {"task": {"title": "Stage one"}, "is_completed": False, "check_pass": False, "fail_count": 2, "time_cost": 8, "meta_data": {"journal": "Investigating fixtures."}},
            },
        }), encoding="utf-8")
        wfgen = workspace / "wfgen"
        wfgen.mkdir()
        (wfgen / "workflow_implementation_plan.md").write_text(
            "# 工作流实施计划\n\n用于回归测试的最小计划。\n", encoding="utf-8"
        )
        (wfgen / "requirements_manifest.yaml").write_text(
            "required_stages:\n  - name: validate\nrequired_tools:\n  - name: ExampleTool\n",
            encoding="utf-8",
        )
        (wfgen / "input_example_manifest.yaml").write_text(
            "source_dir: input/test_input\ntarget_dir: input/example\ncopy_mode: copy_tree\n"
            "required_input:\n  - {path: guide.md, type: file}\nresource_paths: []\n",
            encoding="utf-8",
        )
        minimal_build = (
            "workflow: {name: demo, description: Demo workflow, version: 0.1.0}\n"
            "root: {path: workflow, overwrite: false}\n"
            "runtime_contract: {required_input: [{path: guide.md, type: file}], modes: {}}\n"
            "directories: {public: [tmp], internal: [.workflow]}\n"
            "files: {public: [], internal: []}\nmakefile: {targets: [check]}\nconfig: {}\n"
            "workflow_spec:\n"
            "  checkers:\n"
            "    - name: DemoChecker\n      description: Demo\n"
            "      entry: {file: checkers/demo.py, class_name: DemoChecker, method: do_check}\n"
            "      source: 'class DemoChecker: pass'\n      fixtures: []\n      tests: []\n"
            "  stages:\n"
            "    - {name: validate, description: Validate, reference_files: [], output_files: [], checker: []}\n"
            "acceptance: {required_public_files: [], required_public_dirs: []}\n"
        )
        (wfgen / "workflow_build.yaml").write_text(minimal_build, encoding="utf-8")
        (wfgen / "workflow_build_schema.yaml").write_text(minimal_build, encoding="utf-8")
        (wfgen / "guidedoc_spec_schema.yaml").write_text(
            "title: Stage guide\ndocument_type: guide_doc\noperation_contract: true\n"
            "output: Guide_Doc/stage.md\nsections:\n"
            "  - {id: purpose, heading: 目的, content: 说明阶段目的}\n",
            encoding="utf-8",
        )
        (wfgen / "smoke_tool_selection.yaml").write_text(
            "name: ExampleTool\nspec_path: .workflow/tool_specs/ExampleTool.yaml\n"
            "fixture_paths: [.workflow/tool_tests/cases/ExampleTool/pass.json]\n",
            encoding="utf-8",
        )
        (wfgen / "mcp_baseline_evidence.yaml").write_text(
            "stage: verify_generated_tools_through_mcp\nstatus: passed\n"
            "generated_at: '2026-08-03T00:00:00Z'\nconfigured_generated_tools: []\n"
            "mcp_result: {}\nservice_lifecycle: {}\npost_mcp_static_check: {}\n"
            "failure_summary: []\n",
            encoding="utf-8",
        )
        (wfgen / "operator_notes.yaml").write_text(
            "notes:\n  - This file has no fixed WFB contract.\n", encoding="utf-8"
        )
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        backup = workspace / "tmp/change_history/deploy-config/before/config.yaml"
        backup.parent.mkdir(parents=True)
        backup.write_text("stage:\n  - name: previous\n", encoding="utf-8")
        backup_digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        mutate_document(
            workspace,
            "create",
            "eval/applied_changes.json",
            record={
                "id": "deploy-config",
                "status": "applied",
                "workflow_root": "workflow",
                "approval_ids": ["decision-flow-1"],
                "applied_at": "2026-07-29T00:00:00+00:00",
                "applied_changes": [{
                    "source": "tmp/inc_candidates/current/config.yaml",
                    "target": "config.yaml",
                    "sha256": digest,
                    "approval_ids": ["decision-flow-1"],
                    "rationale": "Apply the approved configuration contract correction.",
                    "backup": {
                        "existed": True,
                        "path": "tmp/change_history/deploy-config/before/config.yaml",
                        "sha256": backup_digest,
                        "created_at": "2026-07-29T00:00:00+00:00",
                    },
                }],
            },
        )
        mutate_document(
            workspace,
            "create",
            "eval/incremental_report.json",
            record={
                "run_id": "incremental-1",
                "contract_version": 2,
                "status": "passed",
                "started_at": "2026-07-29T00:00:00+00:00",
                "finished_at": "2026-07-29T00:01:00+00:00",
                "target": {"workflow_root": "workflow", "revision": "current"},
                "checks": [{
                    "id": "INC-DEPLOYMENT",
                    "status": "passed",
                    "summary": "Deployment hashes were recorded.",
                    "evidence": [{"kind": "source", "path": "eval/applied_changes.json"}],
                }],
                "findings": [],
            },
        )
        mutate_document(
            workspace,
            "create",
            "eval/tools_report.json",
            record={
                "run_id": "tools-1",
                "contract_version": 2,
                "status": "passed_with_findings",
                "started_at": "2026-07-29T00:00:00+00:00",
                "finished_at": "2026-07-29T00:01:00+00:00",
                "target": {"workflow_root": "workflow", "revision": "current"},
                "checks": [{
                    "id": "TOOLS-CHECK",
                    "status": "passed",
                    "summary": "Tool registration was inspected.",
                    "evidence": [{"kind": "source", "path": "workflow/config.yaml"}],
                }],
                "findings": [{
                    "id": "tool-finding-1",
                    "fingerprint": "tool-finding-fingerprint",
                    "severity": "info",
                    "category": "contract",
                    "component": "workflow/tools/example.py",
                    "title": "Tool documentation is incomplete",
                    "description": "The generated tool lacks a complete developer explanation.",
                    "expected": "Developer documentation explains the tool contract.",
                    "actual": "The explanation is incomplete.",
                    "severity_reason": "This affects maintainability but not execution.",
                    "confidence": "confirmed",
                    "requirement_refs": ["guide/tool-docs"],
                    "evidence": [{"kind": "source", "path": "workflow/tools/example.py"}],
                    "impact": "Future changes may be unsafe.",
                    "recommendation": "Add source-backed analysis.",
                    "repro": ["Read the developer document."],
                    "status": "open",
                }],
            },
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)
        server.workspace = workspace
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base_url, timeout=5) as response:
                page = response.read().decode("utf-8")
            assert '工作流构建与评估控制台' in page and 'id="reportStatus"' in page
            assert 'id="reviewTab"' in page and 'id="designTab"' in page
            assert 'class="console-main"' in page and 'role="tabpanel"' in page
            assert 'id="workflowTreeNav"' in page and 'id="ucagentProgress"' in page
            assert 'id="documentOutlinePanel"' not in page and 'id="incrementalFileNav"' in page
            assert 'id="openIncrementalPlanButton"' not in page and 'id="openWorkflowPlanButton"' not in page
            assert 'value="info" checked' in page
            metadata = request_json(base_url, "/api/meta")
            assert metadata["result"]["workspace"] == str(workspace.resolve())
            serve(workspace, "127.0.0.1", server.server_port)
            with urlopen(f"{base_url}/app.js", timeout=5) as response:
                script = response.read().decode("utf-8")
            assert "/api/decisions" in script and "/api/repairs/decisions" not in script
            assert "增量版本管理" in script and "验收修复" not in script
            assert 'item.source_kind === "repair"' in script
            assert "/api/repairs/delete" in script and "删除版本记录" in script
            assert "designPathFromView" in script and "loadDesignSnapshot" in script
            assert "renderUcagentProgress" in script and "renderDocumentOutline" in script
            assert "planningReaderScroll" in script and "documentOutlineBar" in script
            assert '"critical", "high", "medium", "low", "info", "user"' in script
            state = request_json(base_url, "/api/state")
            assert state["ok"] and len(state["result"]["reports"]) == 5
            finding_review_id = next(
                item["review_id"] for item in state["result"]["items"]
                if item["source_id"] == "tool-finding-1"
            )
            assert state["result"]["incremental"]["latest_run_id"] == "incremental-1"
            assert state["result"]["repairs"][0]["integrity"] == "verified"
            assert state["result"]["repairs"][0]["run_id"] == "legacy"
            workflow_plan = request_json(base_url, "/api/workflow-plan")["result"]
            assert workflow_plan["exists"] and "工作流实施计划" in workflow_plan["content"]
            artifacts = request_json(base_url, "/api/wfgen-artifacts")["result"]
            assert {item["path"] for item in artifacts["files"]} == {
                "input_example_manifest.yaml", "workflow_build.yaml",
                "requirements_manifest.yaml", "workflow_implementation_plan.md",
            }
            assert all(item.get("modified_at") for item in artifacts["files"])
            design = request_json(base_url, "/api/design")["result"]
            assert [item["path"] for item in design["monitored_files"]] == [
                "wfgen/input_example_manifest.yaml",
                "wfgen/workflow_build.yaml",
                "wfgen/requirements_manifest.yaml",
                "wfgen/workflow_implementation_plan.md",
                "eval/applied_changes.json",
                "eval/incremental_report.json",
            ]
            assert design["workflow_tree"]["counts"] == {"files": 4, "directories": 2, "symlinks": 1}
            assert any(item["path"] == "workflow/output" and item["runtime"] for item in design["workflow_tree"]["nodes"])
            assert design["ucagent"]["state"] == "running"
            assert design["ucagent"]["stage_title"] == "Stage one"
            assert design["ucagent"]["stage_fail_count"] == 2
            input_editor = request_json(
                base_url, "/api/design-edit/wfgen%2Finput_example_manifest.yaml"
            )["result"]
            assert input_editor["schema"]["kind"] == "input_example"
            assert input_editor["save_allowed"] is False
            assert "content" not in input_editor and input_editor["draft"]["source_dir"] == "input/test_input"
            manifest = request_json(base_url, "/api/wfgen-artifacts/requirements_manifest.yaml")["result"]
            assert manifest["parsed"]["required_stages"][0]["name"] == "validate"
            assert manifest["size"] > 0 and manifest["modified_at"]
            expected_kinds = {
                "requirements_manifest.yaml": "requirements_manifest",
                "input_example_manifest.yaml": "input_example_manifest",
                "workflow_build.yaml": "workflow_build",
                "workflow_implementation_plan.md": "workflow_implementation_plan",
            }
            for artifact_path, expected_kind in expected_kinds.items():
                artifact = request_json(base_url, f"/api/wfgen-artifacts/{artifact_path}")["result"]
                assert artifact["artifact_kind"] == expected_kind
                assert artifact["specialized_view"] is True
                assert isinstance(artifact["structure_issues"], list)
                assert isinstance(artifact["view_model"], dict)
            applied_view = request_json(base_url, "/api/design-files/eval%2Fapplied_changes.json")["result"]
            assert applied_view["artifact_kind"] == "applied_changes"
            assert applied_view["view_model"]["change_count"] == 1
            incremental_view = request_json(base_url, "/api/design-files/eval%2Fincremental_report.json")["result"]
            assert incremental_view["artifact_kind"] == "incremental_report"
            assert incremental_view["view_model"]["latest_run_id"] == "incremental-1"
            source_view = request_json(base_url, "/api/design-files/workflow%2Ftools%2Fexample.py")["result"]
            assert source_view["previewable"] is True and "print('ok')" in source_view["content"]
            binary_view = request_json(base_url, "/api/design-files/workflow%2Foutput%2Fresult.bin")["result"]
            assert binary_view["previewable"] is False and "二进制" in binary_view["reason"]
            large_view = request_json(base_url, "/api/design-files/workflow%2Flarge.log")["result"]
            assert large_view["previewable"] is False and "预览上限" in large_view["reason"]
            for unsafe_path in ("workflow%2Fconfig-link.yaml", "workflow%2F..%2Feval%2Fsummary.json"):
                try:
                    request_json(base_url, f"/api/design-files/{unsafe_path}")
                except HTTPError as exc:
                    assert exc.code == 400
                else:
                    raise AssertionError(f"unsafe preview unexpectedly passed: {unsafe_path}")
            try:
                request_json(base_url, "/api/wfgen-artifacts/operator_notes.yaml")
            except HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("non-monitored wfgen artifact unexpectedly passed")
            original_limit = design_monitor.MAX_TREE_NODES
            design_monitor.MAX_TREE_NODES = 3
            try:
                bounded = request_json(base_url, "/api/design")["result"]["workflow_tree"]
                assert bounded["truncated"] is True and len(bounded["nodes"]) == 3
            finally:
                design_monitor.MAX_TREE_NODES = original_limit
            (ucagent / "ucagent_info.json").write_text("{", encoding="utf-8")
            invalid_progress = request_json(base_url, "/api/design")["result"]["ucagent"]
            assert invalid_progress["state"] == "invalid" and invalid_progress["error"]
            (ucagent / "ucagent_info.json").write_text(json.dumps({
                "stage_index": 2,
                "all_completed": True,
                "time_begin": 100.0,
                "time_end": 110.0,
                "is_agent_exit": True,
                "stages_info": {
                    "0": {"task": {"title": "First"}, "is_completed": True, "check_pass": True},
                    "1": {"task": {"title": "Final"}, "is_completed": True, "check_pass": True},
                },
            }), encoding="utf-8")
            completed_progress = request_json(base_url, "/api/design")["result"]["ucagent"]
            assert completed_progress["state"] == "completed"
            assert completed_progress["stage_title"] == "Final" and completed_progress["completed_stages"] == 2
            completed_editor = request_json(
                base_url, "/api/design-edit/wfgen%2Finput_example_manifest.yaml"
            )["result"]
            assert completed_editor["save_allowed"] is True
            invalid_draft = request_json(
                base_url,
                "/api/design-edit/validate",
                {"edits": [{
                    "path": completed_editor["path"],
                    "fingerprint": completed_editor["fingerprint"],
                    "draft": completed_editor["draft"],
                }]},
            )["result"]
            assert invalid_draft["valid"] is False and invalid_draft["errors"]
            (wfgen / "workflow_build.yaml").write_text("workflow: [\n", encoding="utf-8")
            broken_build = request_json(base_url, "/api/design-files/wfgen%2Fworkflow_build.yaml")["result"]
            assert broken_build["parse_error"] and broken_build["content"] == "workflow: [\n"
            assert broken_build["structure_issues"][0]["code"] == "parse_error"
            repair_id = state["result"]["repairs"][0]["repair_id"]
            repair_state = request_json(base_url, "/api/state")["result"]["repairs"][0]
            assert repair_state["backup_status"] == "available"
            try:
                request_json(base_url, "/api/review-items/delete", {"ids": [repair_id]})
            except HTTPError as exc:
                assert exc.code == 400
            else:
                raise AssertionError("immutable deployment version record was deleted through review API")
            restored = request_json(
                base_url,
                "/api/repairs/history/restore",
                {
                    "id": repair_id,
                    "reason": "Restore the prior configuration while retaining the current file.",
                },
            )
            restore_id = restored["result"]["id"]
            assert target.read_text(encoding="utf-8") == "stage:\n  - name: previous\n"
            restored_state = request_json(base_url, "/api/state")["result"]
            restored_repair = next(
                item for item in restored_state["repairs"] if item["entry_id"] == restore_id
            )
            assert restored_repair["backup_status"] == "available"
            original_backup = workspace / repair_state["backup"]["path"]
            assert original_backup.is_file()
            formal_before_console_delete = target.read_bytes()
            request_json(
                base_url,
                "/api/repairs/history/delete",
                {
                    "id": restored_repair["repair_id"],
                    "reason": "Delete the displaced test version after validating restore auditing.",
                },
            )
            deleted_state = request_json(base_url, "/api/state")["result"]
            deleted_repair = next(
                item for item in deleted_state["repairs"] if item["entry_id"] == restore_id
            )
            assert deleted_repair["backup_status"] == "deleted"
            console_deletion = request_json(
                base_url,
                "/api/repairs/delete",
                {
                    "ids": [repair_id, restored_repair["repair_id"]],
                    "reason": "Remove superseded records from the console regression view.",
                },
            )["result"]
            assert len(console_deletion["deleted"]) == 2
            assert console_deletion["formal_files_changed"] is False
            assert console_deletion["backup_files_changed"] is False
            assert target.read_bytes() == formal_before_console_delete
            assert original_backup.is_file()
            after_console_delete = request_json(base_url, "/api/state")["result"]
            assert not after_console_delete["repairs"]
            manifest_after_delete = load_document(workspace, "eval/applied_changes.json")
            original_entry_id, _, original_target = repair_id.partition("::")
            original_entry = next(
                item for item in manifest_after_delete["entries"] if item["id"] == original_entry_id
            )
            original_change = next(
                item for item in original_entry["applied_changes"] if item["target"] == original_target
            )
            assert original_change["console_deleted_at"]
            created = request_json(
                base_url,
                "/api/suggestions",
                {
                    "title": "Review timeout handling",
                    "description": "Make timeout evidence visible in the evaluation report.",
                    "priority": "high",
                    "entry_kind": "issue",
                },
            )
            suggestion_id = created["result"]["record_id"]
            refreshed = request_json(base_url, "/api/state")["result"]
            review_id = next(
                item["review_id"]
                for item in refreshed["items"]
                if item["source_id"] == suggestion_id
            )
            second = request_json(
                base_url,
                "/api/suggestions",
                {
                    "title": "Document simulator selection",
                    "description": "Describe when Verilator is selected for compilation.",
                    "priority": "medium",
                    "entry_kind": "suggestion",
                },
            )
            second_id = second["result"]["record_id"]
            second_review_id = next(
                item["review_id"]
                for item in request_json(base_url, "/api/state")["result"]["items"]
                if item["source_id"] == second_id
            )
            bulk_result = request_json(
                base_url,
                "/api/decisions/bulk",
                {
                    "ids": [review_id, second_review_id],
                    "decision": "approved",
                    "reason": "The change is scoped and has a clear acceptance criterion.",
                },
            )
            assert len(bulk_result["result"]) == 2
            request_json(base_url, f"/api/suggestions/{suggestion_id}/withdraw", {})
            suggestions = load_document(workspace, "eval/user_suggestions.json")
            assert suggestions["items"][0]["status"] == "withdrawn"
            approvals = load_document(workspace, "eval/approvals.json")
            assert len(approvals["items"]) == 2
            assert all(item["decision"] == "approved" for item in approvals["items"])
            deletion = request_json(
                base_url,
                "/api/review-items/delete",
                {"ids": [second_review_id]},
            )["result"]
            assert deletion["approvals_deleted"] == 1
            assert all(item.get("id") != second_id for item in load_document(workspace, "eval/user_suggestions.json")["items"])
            assert all(item.get("source_id") != second_id for item in load_document(workspace, "eval/approvals.json")["items"])
            request_json(
                base_url,
                "/api/decisions",
                {"id": finding_review_id, "decision": "approved", "reason": "Approve this exact finding before deletion."},
            )
            finding_deletion = request_json(
                base_url, "/api/review-items/delete", {"ids": [finding_review_id]}
            )["result"]
            assert finding_deletion["approvals_deleted"] == 1
            tools_report = load_document(workspace, "eval/tools_report.json")
            assert tools_report["runs"][0]["findings"] == []
            audit = load_document(workspace, "eval/audit.json")
            review_deletions = [event for event in audit["events"] if event.get("action") == "delete_review_item"]
            assert len(review_deletions) >= 2
            version_deletions = [
                event for event in audit["events"]
                if event.get("action") == "delete_deployment_version_from_console"
            ]
            assert len(version_deletions) == 2
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("review UI regression: PASS")


if __name__ == "__main__":
    main()
