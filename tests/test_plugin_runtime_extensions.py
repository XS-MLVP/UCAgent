#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plugin manager tools, runtime snapshot hooks, and framework neutrality."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ucagent.core.plugins import (
    LoadedPlugin,
    Plugin,
    PluginError,
    create_plugin_manager_tools_registry,
    create_plugin_runtime_hooks,
    plugin_summary,
)
from ucagent.core.stage.vmanager import ManagerTool
from ucagent.util.config import (
    Config,
    build_runtime_config,
    load_runtime_config,
    save_runtime_config,
    validate_runtime_config,
)
from unit_test.report_store import (
    CURRENT_TEST_REPORT_RELATIVE_PATH,
    TestProtocolRuntimeHook,
)
from unit_test.test_runner import RunTestCasesManagerTool


def _loaded(name: str, **fields) -> LoadedPlugin:
    """Build one selected plugin contributing the given fields."""

    plugin = Plugin(
        name=name,
        version="1.0.0",
        description="test plugin",
        root=Path("."),
        **fields,
    )
    return LoadedPlugin(plugin=plugin, selector=name, source="test")


class _SilentManagerTool(ManagerTool):
    """Minimal manager tool used only for registry collision tests."""

    name: str = "RunTestCases"
    description: str = "Collision probe."

    def _run(self) -> str:
        """Return the probe result."""

        return "probe"


class _ReservedKeyHook:
    """Contribute a framework-reserved snapshot key to prove rejection."""

    def snapshot_sections(self, cfg):
        """Return a section colliding with the framework namespace."""

        return {"runtime_options": {"injected": True}}


class _BadSectionHook:
    """Contribute a non-mapping snapshot section."""

    def snapshot_sections(self, cfg):
        """Return an invalid section shape."""

        return ["not", "a", "mapping"]


class _UnsafeValueHook:
    """Contribute a value the JSON snapshot cannot round-trip."""

    def snapshot_sections(self, cfg):
        """Return a section holding a non-JSON-safe set."""

        return {"probe_section": {"tags": {"a", "b"}}}


class _ProbeSectionHook:
    """Contribute one plain section for duplicate-key probing."""

    def snapshot_sections(self, cfg):
        """Return a JSON-safe probe section."""

        return {"probe_section": "value"}


def test_manager_tool_registry_dedupes_the_same_class():
    registry = create_plugin_manager_tools_registry(
        [
            _loaded("one", manager_tools=(RunTestCasesManagerTool,)),
            _loaded("two", manager_tools=(RunTestCasesManagerTool,)),
        ]
    )
    assert registry == {"RunTestCases": RunTestCasesManagerTool}


def test_manager_tool_registry_rejects_name_collision():
    with pytest.raises(PluginError, match="Duplicate plugin manager tool name"):
        create_plugin_manager_tools_registry(
            [
                _loaded("one", manager_tools=(RunTestCasesManagerTool,)),
                _loaded("two", manager_tools=(_SilentManagerTool,)),
            ]
        )


def test_manager_tool_registry_rejects_non_class_contribution():
    with pytest.raises(PluginError, match="manager_tools must be classes"):
        create_plugin_manager_tools_registry(
            [_loaded("one", manager_tools=(RunTestCasesManagerTool(),))]
        )


def test_runtime_hooks_instantiate_once_per_class():
    hooks = create_plugin_runtime_hooks(
        [
            _loaded("one", runtime_hooks=(TestProtocolRuntimeHook,)),
            _loaded("two", runtime_hooks=(TestProtocolRuntimeHook,)),
        ]
    )
    assert [type(hook) for hook in hooks] == [TestProtocolRuntimeHook]


def test_runtime_hooks_reject_same_name_different_class():
    first = type("SameHookName", (), {})
    second = type("SameHookName", (), {})
    with pytest.raises(PluginError, match="Duplicate plugin runtime hook name"):
        create_plugin_runtime_hooks(
            [
                _loaded("one", runtime_hooks=(first,)),
                _loaded("two", runtime_hooks=(second,)),
            ]
        )


def test_plugin_summary_lists_manager_tools_and_hooks():
    summary = plugin_summary(
        _loaded(
            "one",
            manager_tools=(RunTestCasesManagerTool,),
            runtime_hooks=(TestProtocolRuntimeHook,),
        )
    )
    assert summary["manager_tools"] == ["RunTestCases"]
    assert summary["runtime_hooks"] == ["TestProtocolRuntimeHook"]


def _report_cfg(test_dir=None):
    tools = {"RunTestCases": {}} if test_dir is None else {
        "RunTestCases": {"test_dir": test_dir}
    }
    cfg = Config({"tools": tools})
    cfg._temp_cfg = {"DUT": "Adder", "OUT": "unit_test"}
    return cfg


def test_test_protocol_hook_contributes_snapshot_sections():
    sections = TestProtocolRuntimeHook().snapshot_sections(
        _report_cfg("custom_tests")
    )
    assert sections == {
        "test_output_dir": "custom_tests",
        "current_test_report": CURRENT_TEST_REPORT_RELATIVE_PATH,
    }


def test_test_protocol_hook_contributes_nothing_without_test_dir():
    assert TestProtocolRuntimeHook().snapshot_sections(_report_cfg()) == {}


def test_test_protocol_hook_validates_report_pointer_contract():
    hook = TestProtocolRuntimeHook()
    valid = {
        "test_output_dir": "tests",
        "current_test_report": CURRENT_TEST_REPORT_RELATIVE_PATH,
    }
    assert hook.validate_runtime_snapshot(valid) is None

    with pytest.raises(ValueError, match="requires 'test_output_dir'"):
        hook.validate_runtime_snapshot(
            {"current_test_report": CURRENT_TEST_REPORT_RELATIVE_PATH}
        )
    with pytest.raises(ValueError, match="test_output_dir.*non-empty string"):
        hook.validate_runtime_snapshot(
            {
                "test_output_dir": "   ",
                "current_test_report": CURRENT_TEST_REPORT_RELATIVE_PATH,
            }
        )


def test_test_protocol_hook_clears_report_on_stage_start(tmp_path):
    report = tmp_path / CURRENT_TEST_REPORT_RELATIVE_PATH
    report.parent.mkdir(parents=True)
    report.write_text('{"stale": true}', encoding="utf-8")

    TestProtocolRuntimeHook().on_stage_start(str(tmp_path))

    assert not report.exists()


def test_runtime_config_merges_hook_sections(tmp_path):
    snapshot = build_runtime_config(
        _report_cfg("custom_tests"), snapshot_hooks=[TestProtocolRuntimeHook()]
    )
    assert snapshot["test_output_dir"] == "custom_tests"
    assert snapshot["current_test_report"] == CURRENT_TEST_REPORT_RELATIVE_PATH

    validate_runtime_config(snapshot, snapshot_hooks=[TestProtocolRuntimeHook()])
    path = save_runtime_config(
        str(tmp_path),
        _report_cfg("custom_tests"),
        snapshot_hooks=[TestProtocolRuntimeHook()],
    )
    assert load_runtime_config(str(tmp_path)) == json.loads(
        path.read_text(encoding="utf-8")
    )


def test_runtime_config_rejects_hook_reserved_key():
    with pytest.raises(ValueError, match="reserved or duplicate key"):
        build_runtime_config(
            _report_cfg(), snapshot_hooks=[_ReservedKeyHook()]
        )


def test_runtime_config_rejects_hook_duplicate_section_key():
    with pytest.raises(ValueError, match="reserved or duplicate key"):
        build_runtime_config(
            _report_cfg(),
            snapshot_hooks=[_ProbeSectionHook(), _ProbeSectionHook()],
        )


def test_runtime_config_rejects_hook_bad_section_shape():
    with pytest.raises(ValueError, match="non-empty string keys"):
        build_runtime_config(_report_cfg(), snapshot_hooks=[_BadSectionHook()])


def test_runtime_config_rejects_hook_non_json_safe_value():
    with pytest.raises(ValueError, match="non-JSON-safe"):
        build_runtime_config(_report_cfg(), snapshot_hooks=[_UnsafeValueHook()])


def test_framework_core_stays_test_domain_neutral():
    """No pytest/test-report protocol token may re-enter the framework core."""

    forbidden = (
        "runtestcases",
        "runpytest",
        "classify_pytest_execution",
        "current_test_report",
        "test_output_dir",
    )
    offenders = []
    # Bundled workflow trees under ucagent/plugins/ legitimately own the
    # pytest protocol; this guard covers the framework core only.
    bundled = REPO_ROOT / "ucagent" / "plugins"
    for path in sorted((REPO_ROOT / "ucagent").rglob("*.py")):
        if path.is_relative_to(bundled):
            continue
        text = path.read_text(encoding="utf-8").lower()
        offenders.extend(
            f"{path.relative_to(REPO_ROOT)}:{token}"
            for token in forbidden
            if token in text
        )
        if "pytest" in text:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:pytest")
    assert offenders == []
