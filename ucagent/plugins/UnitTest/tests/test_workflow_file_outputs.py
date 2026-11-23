"""Workflow artifact declarations expose the actual files edited by API and fixture stages."""

from pathlib import Path

import pytest

from ucagent.core.plugins import create_plugin_checker_registry, load_plugin
from ucagent.core.stage.vstage import parse_vstage
from ucagent.util.config import get_config


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
API_WRITERS = {
    "UnityChipCheckerDutCreation", "UnityChipCheckerDutFixture", "UnityChipCheckerBundleWrapper",
    "UnityChipCheckerMockFixture", "UnityChipCheckerEnvFixture", "UnityChipCheckerDutApi",
}


@pytest.mark.parametrize("workflow", ["unittest", "incremental"])
@pytest.mark.parametrize("mock_enabled", [False, True])
@pytest.mark.parametrize("ref_enabled", [False, True])
def test_api_implementation_stages_declare_checker_targets_as_outputs(
        tmp_path, monkeypatch, workflow, mock_enabled, ref_enabled):
    """Real workflow loading and stage construction keep output metadata aligned with checkers."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "false" if mock_enabled else "true")
    monkeypatch.setenv("NEED_REF_MODEL", "true" if ref_enabled else "false")
    cfg = get_config(workflow_config_file=str(PLUGIN_ROOT / "src/unit_test/workflows" / (workflow + ".yaml")),
                     cfg_override={"skill.use_skill": False})
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "DUT", "OUT": "unit_test"}
    cfg.update_template({"DUT": "DUT", "OUT": "unit_test", "WORKSPACE": str(tmp_path)})
    pending, writers = list(cfg.stage), []
    while pending:
        current = pending.pop()
        if current.get_value("ignore", False):
            continue
        pending.extend(current.get_value("stage", []))
        targets = {checker.args.target_file for checker in current.get_value("checker", [])
                   if checker.clss in API_WRITERS}
        if targets:
            assert targets <= set(current.get_value("output_files", [])), current.name
            writers.append(current)
    assert writers
    registry = create_plugin_checker_registry([load_plugin(str(PLUGIN_ROOT))])
    stages = parse_vstage(cfg, writers, str(tmp_path), None, checker_registry=registry)
    assert len(stages) == len(writers)
    assert all("unit_test/tests/DUT_api.py" in stage.output_files for stage in stages)
