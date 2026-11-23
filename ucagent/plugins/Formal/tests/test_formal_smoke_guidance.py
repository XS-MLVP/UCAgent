"""Stage-local guidance separates disposable tool health from official verification work."""
from pathlib import Path

import pytest

from ucagent.util.config import get_config

SOURCE = Path(__file__).resolve().parents[1] / 'src/formal'


@pytest.mark.parametrize('enabled', [False, True])
def test_smoke_function_and_closure_guidance_without_skill_dependency(tmp_path, monkeypatch, enabled):
    """All three objectives and boundaries survive optional Skill removal."""
    monkeypatch.setenv('HOME', str(tmp_path))
    cfg = get_config(workflow_config_file=str(SOURCE / 'workflows/formal.yaml'),
                     cfg_override=[{'skill.use_skill': enabled}])
    configured = {s['name']: s for s in cfg.get_value('stage')}
    stages = {stage['name']: '\n'.join(stage.get_value('task', []))
              for parent in configured.values() for stage in parent.get_value('stage', [parent])}
    smoke = stages['script_generation']
    functions = stages['implement_formal_case_batches']
    closure = stages['coverage_analysis_and_optimization']
    assert 'RunFormal(action=preflight)' in smoke
    assert '临时' in smoke and '不参与正式 CK' in smoke and '不要实现正式 CK' in smoke
    assert '冻结基础' not in smoke
    assert not configured['script_generation'].get_value('reference_files', [])
    assert '正式环境 Assume' in functions and 'case_batch.run_call' in functions
    assert '不要求全部 Pass' in functions and '公共输入更新后' in functions
    assert 'review_fc' in functions and 'current_fc' in functions
    assert 'ENV_PENDING' in functions and '10 条' in functions
    assert '不跳回第 5 或第 6 阶段' in closure
    assert '完整' in closure and '覆盖缺口' in closure and '复用' in closure
    assert 'baseline: true' not in '\n'.join(stages.values())


def test_guides_keep_disposable_properties_out_of_official_acceptance():
    """Do not reintroduce the frozen-baseline Skill command in current normative guidance."""
    for relative in ['Guide_Doc/formal_execution.md', 'Guide_Doc/formal_data.md', 'skills/data/SKILL.md']:
        text = (SOURCE / relative).read_text()
        assert '冒烟' in text
        assert '--baseline' not in text
    assert '--assumptions' in (SOURCE / 'skills/data/SKILL.md').read_text()
