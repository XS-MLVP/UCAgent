# -*- coding: utf-8 -*-
"""The workflow config, not framework hardwiring, decides the waveform/test tools."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unity_test.checkers import UnityChipCheckerTestFree
from ucagent.stage.vmanager import StageManager
from ucagent.plugins import PluginContext
from ucagent.util.config import Config
from unity_test.test_runner import (
    RunTestCasesManagerTool,
    resolve_free_runner_clss,
)
from unity_test.plugin import create_waveform_tools


def _plugin_context(cfg, tmp_path):
    return PluginContext(
        workspace=Path(tmp_path),
        output_dir="output",
        write_dirs=tuple(cfg.write_dirs),
        un_write_dirs=tuple(cfg.un_write_dirs),
        cfg=cfg,
        plugin_root=Path(tmp_path),
        dut_name="Adder",
    )


def _agent_stub():
    return SimpleNamespace(cfg=Config({"skill": {"use_skill": False}}))


def test_waveform_tool_stack_built_when_workflow_declares_test_dir(tmp_path):
    cfg = Config(
        {
            "tools": {"RunTestCases": {"test_dir": "tests"}},
            "runtime_options": {
                "waveform_analysis_format_priority": ["fst", "vcd"]
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    tools = create_waveform_tools(_plugin_context(cfg, tmp_path))
    assert [tool.name for tool in tools] == [
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "ReviewWaveInfoEvidenceBatch",
    ]


def test_waveform_tool_stack_normalizes_config_wrapped_backend_priority(tmp_path):
    cfg = Config(
        {
            "tools": {"RunTestCases": {"test_dir": "tests"}},
            "runtime_options": {
                "waveform_analysis_backend_priority": {"vcd": ["wavekit"]}
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    tools = create_waveform_tools(_plugin_context(cfg, tmp_path))
    assert [tool.name for tool in tools] == [
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "ReviewWaveInfoEvidenceBatch",
    ]
    assert tools[0].backend_priority == {
        "fst": ["pywellen", "wavekit"],
        "vcd": ["wavekit"],
        "fsdb": ["wavekit"],
    }


def test_waveform_tool_stack_skipped_without_test_dir(tmp_path):
    cfg = Config(
        {
            "runtime_options": {
                "waveform_analysis_format_priority": ["fst", "vcd"]
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    assert create_waveform_tools(_plugin_context(cfg, tmp_path)) == []


def test_waveform_tool_stack_defaults_format_priority_without_runtime_options(
    tmp_path,
):
    cfg = Config(
        {
            "tools": {"RunTestCases": {"test_dir": "tests"}},
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    tools = create_waveform_tools(_plugin_context(cfg, tmp_path))
    assert len(tools) == 3


def _manager(tmp_path, cfg, checker_registry=None, manager_tool_registry=None):
    return StageManager(
        workspace=str(tmp_path),
        cfg=cfg,
        agent=_agent_stub(),
        tool_read_text=None,
        ucagent_info={},
        checker_registry=checker_registry,
        manager_tool_registry=manager_tool_registry,
    )


_RUN_TEST_CASES_REGISTRY = {"RunTestCases": RunTestCasesManagerTool}


def test_stage_manager_without_manager_tools_declares_no_test_tool(tmp_path):
    cfg = Config(
        {
            "tools": {"RunTestCases": {"test_dir": "tests"}},
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    manager = _manager(
        tmp_path, cfg, manager_tool_registry=_RUN_TEST_CASES_REGISTRY
    )
    assert manager.plugin_manager_tools == []
    assert "RunTestCases" not in [tool.name for tool in manager.new_tools()]


class _RegistryRunner:
    """Sentinel runner that must win over a same-named dotted fallback."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.test_dir = args[1] if len(args) > 1 else ""
        self.run_test = SimpleNamespace(
            set_extra_python_paths=lambda paths: None
        )

    def set_workspace(self, workspace):
        self.workspace = workspace
        return self


def test_declared_manager_tool_binds_the_free_runner(tmp_path):
    cfg = Config(
        {
            "manager_tools": ["RunTestCases"],
            "tools": {
                "RunTestCases": {
                    "test_dir": "tests",
                    "free_runner_clss": "UnityChipCheckerTestFree",
                }
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    manager = _manager(
        tmp_path,
        cfg,
        checker_registry={"UnityChipCheckerTestFree": UnityChipCheckerTestFree},
        manager_tool_registry=_RUN_TEST_CASES_REGISTRY,
    )
    [tool] = manager.plugin_manager_tools
    assert isinstance(tool, RunTestCasesManagerTool)
    assert isinstance(tool.free_pytest_run, UnityChipCheckerTestFree)
    assert tool.manager is manager
    assert "RunTestCases" in [tool.name for tool in manager.new_tools()]


def test_declared_manager_tool_prefers_checker_registry_runner(tmp_path):
    cfg = Config(
        {
            "manager_tools": ["RunTestCases"],
            "tools": {
                "RunTestCases": {
                    "test_dir": "tests",
                    "free_runner_clss": "UnityChipCheckerTestFree",
                }
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    manager = _manager(
        tmp_path,
        cfg,
        checker_registry={"UnityChipCheckerTestFree": _RegistryRunner},
        manager_tool_registry=_RUN_TEST_CASES_REGISTRY,
    )
    [tool] = manager.plugin_manager_tools
    assert isinstance(tool.free_pytest_run, _RegistryRunner)
    assert tool.manager is manager


def test_declared_manager_tool_resolves_dotted_runner_without_registry(
    tmp_path,
):
    cfg = Config(
        {
            "manager_tools": ["RunTestCases"],
            "tools": {
                "RunTestCases": {
                    "test_dir": "tests",
                    "free_runner_clss": (
                        "unity_test.checkers.UnityChipCheckerTestFree"
                    ),
                }
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    manager = _manager(
        tmp_path, cfg, manager_tool_registry=_RUN_TEST_CASES_REGISTRY
    )
    [tool] = manager.plugin_manager_tools
    assert isinstance(tool.free_pytest_run, UnityChipCheckerTestFree)


def test_unresolvable_free_runner_clss_raises_at_startup(tmp_path):
    cfg = Config(
        {
            "manager_tools": ["RunTestCases"],
            "tools": {
                "RunTestCases": {
                    "test_dir": "tests",
                    "free_runner_clss": "NoSuchFreeRunner",
                }
            },
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    with pytest.raises(ValueError, match="free_runner_clss"):
        _manager(tmp_path, cfg, manager_tool_registry=_RUN_TEST_CASES_REGISTRY)


def test_declared_manager_tool_without_run_config_raises(tmp_path):
    cfg = Config(
        {
            "manager_tools": ["RunTestCases"],
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    with pytest.raises(ValueError, match="tools.RunTestCases"):
        _manager(tmp_path, cfg, manager_tool_registry=_RUN_TEST_CASES_REGISTRY)


def test_unknown_manager_tool_name_raises(tmp_path):
    cfg = Config(
        {
            "manager_tools": ["NoSuchTool"],
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    with pytest.raises(ValueError, match="Unknown manager tool"):
        _manager(tmp_path, cfg, manager_tool_registry=_RUN_TEST_CASES_REGISTRY)


def test_free_runner_clss_short_name_requires_registry_or_raises():
    with pytest.raises(ValueError, match="free_runner_clss"):
        resolve_free_runner_clss("UnityChipCheckerTestFree")


def test_free_runner_clss_resolves_plugin_qualified_name():
    assert (
        resolve_free_runner_clss(
            "unity_test.checkers.UnityChipCheckerTestFree"
        )
        is UnityChipCheckerTestFree
    )
