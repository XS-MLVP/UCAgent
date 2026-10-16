"""Check runtime guidance, current schemas and the packaged navigation contract."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import yaml

import pytest

from bug_review.core.records import RECORD_MODELS
from bug_review.plugin import get_plugin
from bug_review.checkers.analysis import BugReviewStageChecker
from ucagent.plugins import validate_plugin
from ucagent.util.config import Config, UCAgentConfigLoader
from ucagent.stage.vmanager import ToolRunTestCases
from ucagent.stage.vstage import parse_vstage


def test_all_registered_guide_examples_match_current_models():
    """Registered documents include complete typed examples, independent of optional skills."""
    plugin = get_plugin()
    validated = validate_plugin(plugin)
    guides = validated.workflows[0].guide_doc_paths
    assert len(guides) == 7
    for path in guides:
        text = path.read_text()
        for match in re.finditer(r'^#{1,6} ', text, re.M):
            prefix = text[:match.start()]
            assert prefix == '\n' or prefix.endswith('\n\n'), path
        for block in re.findall(r'```json\n(.*?)\n```', text, re.S):
            value = json.loads(block)
            if 'record_type' in value:
                RECORD_MODELS[value['record_type']].model_validate(value)


@pytest.mark.parametrize('enabled', [True, False])
def test_workflow_references_and_checkers_do_not_depend_on_skill_files(tmp_path, enabled):
    """Actual stage prompts and evidence checkers remain available without any copied skills."""
    workflow = get_plugin().workflows[0]
    value = yaml.load(workflow.config_file.read_text(), Loader=UCAgentConfigLoader)
    value['skill']['use_skill'] = enabled
    cfg = Config(value)
    cfg._temp_cfg = {'DUT': 'demo', 'OUT': 'verification_review/analysis'}
    if enabled:
        source = workflow.config_file.parent.parent / 'skills'
        shutil.copytree(source, tmp_path / '.ucagent/skills/ext/bug_review')
    else:
        assert not (tmp_path / '.ucagent/skills').exists()
    for guide in validate_plugin(get_plugin()).workflows[0].guide_doc_paths:
        target = tmp_path / 'Guide_Doc' / guide.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(guide, target)
    for stage_cfg in cfg.stage:
        for checker in stage_cfg.checker:
            checker.extra_args = Config({})
    stages = parse_vstage(cfg, cfg.stage, str(tmp_path), None,
                         checker_registry={'BugReviewStageChecker': BugReviewStageChecker})
    for stage in stages:
        if stage.name != 'full_replay':
            assert 'Guide_Doc/bug_review_writing.md' in stage.reference_files
            assert 'Guide_Doc/bug_review_investigation.md' in stage.reference_files
            assert 'Guide_Doc/bug_review_example_ptw.md' in stage.reference_files
        assert stage.checker[0].stage_id == stage.name
        assert stage._check_forced_skill_usage(is_complete=False) is None
        if enabled:
            assert stage.skill_list
            assert not stage._check_forced_skill_usage(is_complete=True)[0]
        else:
            assert stage.skill_list == {}
            assert 'skill_list' not in stage.task_info()
            assert stage._check_forced_skill_usage(is_complete=True) is None
    prompts = {stage.name: '\n'.join(stage.task()) for stage in stages}
    assert 'dut_context' in prompts['case_triage']
    assert all(field in prompts['root_correlation'] for field in
               ['affected_behavior', 'causal_steps', 'signal_explanations', 'investigation', 'first_evidence_id', 'alternatives'])
    assert 'primary_evidence_id' in prompts['root_correlation']


def test_report_bridge_navigation():
    """Execute navigation with the actual JS protocol rather than inspecting strings."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the bundled bridge check')
    result = subprocess.run([node, str(Path(__file__).with_name('test_report_navigation.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_replay_instructions_use_public_tool_arguments():
    """Documented test selection must reach the public MCP schema without ignored keys."""
    workflow = get_plugin().workflows[0]
    paths = [workflow.config_file, workflow.guide_doc_paths[0]]
    allowed = set(ToolRunTestCases().args_schema.model_fields)
    for path in paths:
        calls = re.findall(r'RunTestCases\(([^)]*)\)', path.read_text())
        assert calls
        for call in calls:
            keys = re.findall(r'(\w+)\s*=', call)
            assert set(keys).issubset(allowed), (path, keys)
