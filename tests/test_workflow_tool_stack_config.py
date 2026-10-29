# -*- coding: utf-8 -*-
"""The workflow config, not framework hardwiring, decides the waveform/test tools."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/unitytest/src"))

from unitytest_plugin.checkers import UnityChipCheckerTestFree
from ucagent.stage.vmanager import StageManager, resolve_free_runner_clss
from ucagent.plugins import PluginContext
from ucagent.util.config import Config
from unitytest_plugin.plugin import create_waveform_tools


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
        }
    )
    tools = create_waveform_tools(_plugin_context(cfg, tmp_path))
    assert len(tools) == 3


def test_stage_manager_without_test_dir_omits_run_test_cases(tmp_path):
    cfg = Config({"write_dirs": ["tests"], "un_write_dirs": []})
    manager = StageManager(
        workspace=str(tmp_path),
        cfg=cfg,
        agent=_agent_stub(),
        tool_read_text=None,
        ucagent_info={},
    )
    assert manager.free_pytest_run is None
    assert "RunTestCases" not in [tool.name for tool in manager.new_tools()]


class _RegistryRunner:
    """Sentinel runner that must win over the same-named core checker."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.test_dir = args[1] if len(args) > 1 else ""
        self.run_test = SimpleNamespace(
            set_extra_python_paths=lambda paths: None
        )

    def set_workspace(self, workspace):
        self.workspace = workspace
        return self


def test_stage_manager_with_test_dir_registers_run_test_cases(tmp_path):
    cfg = Config(
        {
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
    manager = StageManager(
        workspace=str(tmp_path),
        cfg=cfg,
        agent=_agent_stub(),
        tool_read_text=None,
        ucagent_info={},
        checker_registry={"UnityChipCheckerTestFree": UnityChipCheckerTestFree},
    )
    assert isinstance(manager.free_pytest_run, UnityChipCheckerTestFree)
    assert "RunTestCases" in [tool.name for tool in manager.new_tools()]


def test_stage_manager_without_runner_clss_omits_run_test_cases(tmp_path):
    cfg = Config(
        {
            "tools": {"RunTestCases": {"test_dir": "tests"}},
            "write_dirs": ["tests"],
            "un_write_dirs": [],
        }
    )
    manager = StageManager(
        workspace=str(tmp_path),
        cfg=cfg,
        agent=_agent_stub(),
        tool_read_text=None,
        ucagent_info={},
    )
    assert manager.free_pytest_run is None
    assert "RunTestCases" not in [tool.name for tool in manager.new_tools()]


def test_stage_manager_resolves_free_runner_from_checker_registry(tmp_path):
    cfg = Config(
        {
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
    manager = StageManager(
        workspace=str(tmp_path),
        cfg=cfg,
        agent=_agent_stub(),
        tool_read_text=None,
        ucagent_info={},
        checker_registry={"UnityChipCheckerTestFree": _RegistryRunner},
    )
    assert isinstance(manager.free_pytest_run, _RegistryRunner)
    assert "RunTestCases" in [tool.name for tool in manager.new_tools()]


def test_unresolvable_free_runner_clss_raises_at_startup(tmp_path):
    cfg = Config(
        {
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
        StageManager(
            workspace=str(tmp_path),
            cfg=cfg,
            agent=_agent_stub(),
            tool_read_text=None,
            ucagent_info={},
        )


def test_free_runner_clss_short_name_falls_back_to_core_package():
    assert (
        resolve_free_runner_clss("UnityChipCheckerTestFree")
        is UnityChipCheckerTestFree
    )


def test_free_runner_clss_resolves_fully_qualified_name():
    assert (
        resolve_free_runner_clss("ucagent.checkers.UnityChipCheckerTestFree")
        is UnityChipCheckerTestFree
    )
