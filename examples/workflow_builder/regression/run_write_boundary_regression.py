#!/usr/bin/env python3
"""Guard the main workflow's generated-workflow write boundary."""

import stat
import tempfile
from pathlib import Path

import yaml
from ucagent.tools.fileops import is_file_writeable
from workflow_builder.history_permissions import restore_owner_write


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
MAKEFILE = ROOT / "Makefile"


def main() -> int:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    template_overwrite = config.get("template_overwrite") or {}
    test_workflow_root = template_overwrite.get("TEST_WORKFLOW_ROOT")
    assert test_workflow_root == "workflow", (
        "TEST_WORKFLOW_ROOT must be the canonical workspace-relative path 'workflow'; "
        "template substitutions are single-pass, so nested placeholders are invalid"
    )
    assert "{" not in test_workflow_root and ".//" not in test_workflow_root
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "OUT ?= ." in makefile
    assert "NORMALIZED_OUT := $(patsubst %/,%,$(OUT))" in makefile
    assert "UCAGENT_OUTPUT=$(OUT)" not in makefile
    assert "--output $(OUT)" not in makefile
    assert makefile.count("UCAGENT_OUTPUT=$(NORMALIZED_OUT)") == 4
    assert makefile.count("--output $(NORMALIZED_OUT)") == 4
    assert makefile.count("UCAGENT_OUTPUT=$(EVAL_OUTPUT_ROOT)") == 4
    assert makefile.count("--output $(EVAL_OUTPUT_ROOT)") == 4
    assert 'RUN_LOOP_ARGS ?= --loop --loop-msg "$(RUN_LOOP_MSG)"' in makefile
    assert "--tui $(RUN_LOOP_ARGS) $(RUN_EXTRA)" in makefile
    assert "make run RUN_LOOP_ARGS=" in makefile
    assert 'chmod -R u+w "$(WFB_WORKSPACE)/.ucagent/history"' in makefile
    assert 'rm -rf "$(WFB_WORKSPACE)/.ucagent/history"' not in makefile
    assert "workflow_builder.history_permissions" in makefile
    assert "history_guard_pid" in makefile
    assert "GUIDE_DOC_SOURCE_DIR ?= $(WORKFLOW_BUILDER_HOME)/Guide_Doc" in makefile
    assert 'cp -a "$(GUIDE_DOC_SOURCE_DIR)/." "$(WORKSPACE_GUIDE_DOC_DIR)/"' in makefile
    write_dirs = config.get("write_dirs") or []
    assert "{TEST_WORKFLOW}" in write_dirs, (
        "config.yaml must explicitly allow {TEST_WORKFLOW}; {OUT} may resolve to "
        "'.' and fail prefix checks for paths written as workflow/..."
    )
    resolved_write_dirs = [
        path.replace("{OUT}", ".").replace("{TEST_WORKFLOW}", "workflow")
        for path in write_dirs
    ]
    for equivalent_path in ("workflow/.workflow/tool_tests/cases/example.txt",):
        allowed, message = is_file_writeable(
            equivalent_path,
            un_write_dirs=[],
            write_dirs=resolved_write_dirs,
        )
        assert allowed, f"{equivalent_path} must be writable: {message}"

    with tempfile.TemporaryDirectory(prefix="history_permissions_") as temp:
        history = Path(temp) / ".ucagent/history"
        snapshot = history / "workflow/config.yaml"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text("stage: []\n", encoding="utf-8")
        snapshot.chmod(snapshot.stat().st_mode & ~stat.S_IWUSR)
        assert not snapshot.stat().st_mode & stat.S_IWUSR
        assert restore_owner_write(history) == 1
        assert snapshot.stat().st_mode & stat.S_IWUSR

    stages = {stage["name"]: stage for stage in config.get("stage") or []}
    required_outputs = {
        "design_smoke_business_tool_spec": {
            "{WFGEN_DIR}/smoke_tool_selection.yaml",
        },
        "implement_smoke_business_tool": {
            "{TEST_WORKFLOW_ROOT}/config.yaml",
        },
        "strengthen_smoke_business_tool_tests": {
            "{WFGEN_DIR}/smoke_tool_selection.yaml",
            "{TEST_WORKFLOW_ROOT}/config.yaml",
        },
    }
    for stage_name, required in required_outputs.items():
        actual = set(stages[stage_name].get("output_files") or [])
        missing = required - actual
        assert not missing, f"{stage_name} is missing output declarations: {sorted(missing)}"

    extensionless_files = {
        "{DESC_FILE}",
        "{BUILD_CONFIG}",
        "{INC_REPORT}",
        "{EVAL_CONTROL}",
    }
    for stage in stages.values():
        for field in ("reference_files", "output_files"):
            for value in stage.get(field, []):
                basename = Path(str(value).rstrip("/")).name
                assert not str(value).endswith("/"), (stage["name"], field, value)
                assert (
                    Path(basename).suffix
                    or basename in {"Makefile", "Dockerfile", "requirements"}
                    or value in extensionless_files
                ), f"{stage['name']}.{field} contains a directory-shaped path: {value}"

    expected_mcp_outputs = {
        "verify_generated_tools_through_mcp": {
            "{WFGEN_DIR}/workflow_implementation_plan.md",
            "{WFGEN_DIR}/mcp_baseline_evidence.yaml",
        },
        "run_full_tool_test_suite": {
            "{WFGEN_DIR}/workflow_implementation_plan.md",
        },
    }
    for stage_name, expected_outputs in expected_mcp_outputs.items():
        outputs = set(stages[stage_name].get("output_files") or [])
        assert outputs == expected_outputs, (
            f"{stage_name} must declare only agent-written stable evidence, not "
            "checker-generated MCP logs because VerifyStage checks outputs before "
            "running the checker"
        )
        checker_classes = {
            item.get("clss")
            for item in stages[stage_name].get("checker") or []
            if isinstance(item, dict)
        }
        assert (
            "examples.workflow_builder.workflow_builder.uc_checkers."
            "WorkflowMCPToolIntegrationChecker"
        ) in checker_classes, f"{stage_name} must retain the MCP integration checker"

    print("[PASS] generated workflow write boundary regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
