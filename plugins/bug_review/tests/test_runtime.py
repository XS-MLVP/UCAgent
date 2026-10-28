"""Exercise resolved options, native stage skips, optional Skills, and MCP schemas."""

import json
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import pytest
import yaml

from bug_review.plugin import get_plugin, configure_workflow, create_tools
from bug_review.core.records import Review, Case
from bug_review.core.layout import resolved_options
from bug_review.checkers.analysis import BugReviewStageChecker
from bug_review.tools.intake import ClaimsArgs
from bug_review.tools.analysis import DecisionArgs, AnalysisArgs
from conftest import context_payload
from ucagent.util.config import Config, UCAgentConfigLoader, load_yaml_with_env_vars
from ucagent.plugins import validate_plugin
from ucagent.stage.vstage import parse_vstage
from ucagent.tools.uctool import to_fastmcp


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('skills', [False, True])
def test_real_stage_parser_and_tool_visibility(tmp_path, monkeypatch, enabled, skills):
    """The same resolved switch controls native skip, tools and optional Skill gates."""
    monkeypatch.setenv('BUG_REVIEW_WAVEFORM_ENABLED', str(not enabled).lower())
    workflow = validate_plugin(get_plugin()).workflows[0]
    value = load_yaml_with_env_vars(workflow.config_file)
    value['runtime_options']['bug_review_waveform_enabled'] = enabled
    value['skill']['use_skill'] = skills
    if skills:
        shutil.copytree(workflow.config_file.parent.parent / 'skills', tmp_path / '.ucagent/skills/ext/bug_review')
    for guide in workflow.guide_doc_paths:
        destination = tmp_path / 'Guide_Doc' / guide.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(guide, destination)
    cfg = Config(value)
    configure_workflow(cfg, {'OUT': 'results', 'DUT': 'demo'})
    assert cfg.stage[3].skip is (not enabled)
    cfg.update_template({'OUT': 'results', 'DUT': 'demo'})
    cfg.un_freeze()
    cfg._temp_cfg = {'OUT': 'results', 'DUT': 'demo'}
    for item in cfg.stage:
        for checker in item.checker:
            checker.extra_args = Config({})
    stages = parse_vstage(cfg, cfg.stage, str(tmp_path), None, checker_registry={'BugReviewStageChecker': BugReviewStageChecker})
    assert len(stages) == 6
    assert stages[3].is_skipped() is (not enabled)
    for stage in stages:
        assert stage.checker[0].stage_id == stage.name
        assert stage._check_forced_skill_usage(is_complete=True) is None
    assert (tmp_path / '.ucagent/skills').exists() is skills
    context = SimpleNamespace(workspace=tmp_path, output_dir='results', cfg=cfg)
    tools = create_tools(context)
    names = {tool.name for tool in tools}
    assert ('ApplyReceiptToCase' in names) == enabled
    assert ('WaveInfo' in cfg.tools.ignore_tools) == (not enabled)
    assert len(names) == len(tools)
    for tool in tools:
        converted = to_fastmcp(tool)
        assert converted.name == tool.name
        assert converted.parameters.get('additionalProperties') is False
    prompts = '\n'.join(cfg.stage[2].task)
    assert '不分析波形' in prompts or '不调用波形' in prompts
    assert 'next_group' in prompts and 'shared' in prompts
    assert '逐 Case 阅读' not in prompts


@pytest.mark.parametrize('value', ['false', 0, 1, None, []])
def test_runtime_boolean_types_are_strict(value):
    """Do not treat truthy strings or numbers as feature policy."""
    cfg = Config({'runtime_options': {'bug_review_waveform_enabled': value}})
    with pytest.raises(ValueError, match='must be boolean'):
        resolved_options(cfg)


def test_guides_have_complete_current_examples_and_heading_spacing():
    """Validate whole canonical records independently of optional Skills."""
    guides = validate_plugin(get_plugin()).workflows[0].guide_doc_paths
    schemas = []
    for path in guides:
        text = path.read_text()
        for match in re.finditer(r'^#{1,6} ', text, re.M):
            assert text[:match.start()].endswith('\n\n') or text[:match.start()] == '\n'
        for block in re.findall(r'```json\n(.*?)\n```', text, re.S):
            data = json.loads(block)
            if 'schema_version' in data:
                Review.model_validate(data); schemas.append('review')
            elif 'analysis' in data:
                Case.model_validate(data); schemas.append('case')
            elif 'shared' in data and 'cases' in data:
                AnalysisArgs.model_validate(data); schemas.append('group_update')
            elif 'decisions' in data:
                DecisionArgs.model_validate(data); schemas.append('decisions')
    assert set(schemas) == {'review', 'decisions', 'group_update'}


def test_all_stage_configs_have_meaningful_checkers():
    """Every YAML checker constructor and do_check description remains valid."""
    value = load_yaml_with_env_vars(get_plugin().workflows[0].config_file)
    for stage in value['stage']:
        for spec in stage['checker']:
            checker = BugReviewStageChecker(**spec['args'])
            assert checker.stage_id == stage['name']
            assert checker.do_check.__doc__


@pytest.mark.parametrize('enabled', [False, True])
def test_real_agent_startup_uses_compact_workflow(tmp_path, enabled):
    """Start a model-free real Agent with runtime snapshot, tools and template policy."""
    from ucagent.verify_agent import VerifyAgent
    from ucagent.plugins import LoadedPlugin
    from ucagent.util.config import load_runtime_config
    plugin = validate_plugin(get_plugin())
    workflow = plugin.workflows[0]
    workspace = tmp_path / 'workspace'; workspace.mkdir()
    (workspace / 'unity_test').mkdir()
    (workspace / 'unity_test/report.md').write_text('No reported Bugs.')
    explicit = tmp_path / 'empty.yaml';explicit.write_text('{}\n')
    agent = VerifyAgent(workspace=str(workspace), dut_name='demo', output='results',
        config_file=str(explicit), workflow_config_file=str(workflow.config_file),
        template_context_factory=workflow.template_context_factory,
        plugin_guide_doc_paths=[str(p) for p in workflow.guide_doc_paths],
        plugin_skill_paths=[('bug_review', str(p)) for p in workflow.skill_paths],
        plugins=[LoadedPlugin(plugin, 'bug_review', 'test')],
        cfg_override=[{'backend.key_name': 'blank'}, {'langfuse.enable': False},
                      {'skill.use_skill': False}, {'runtime_options.bug_review_waveform_enabled': enabled},
                      {'vmanager.llm_suggestion.check_fail_refinement.enable': False},
                      {'vmanager.llm_suggestion.check_pass_refinement.enable': False}],
        no_embed_tools=True, no_history=True)
    try:
        assert agent.template is None
        assert len(agent.stage_manager.stages) == 6
        assert agent.stage_manager.stages[3].is_skipped() is (not enabled)
        names = {t.name for t in agent.test_tools}
        assert ('WaveInfo' in names) == enabled
        assert ('ApplyReceiptToCase' in names) == enabled
        snapshot = load_runtime_config(str(workspace))
        assert snapshot['OUT'] == 'results'
        assert snapshot['runtime_options']['bug_review_waveform_enabled'] is enabled
        assert snapshot['test_output_dir'] == 'results/runs/work'
        assert (workspace / 'unity_test/report.md').read_text() == 'No reported Bugs.'
        assert not (workspace / '.ucagent/skills').exists()
        intake = next(t for t in agent.test_tools if t.name == 'PrepareReviewInputs')
        assert intake._run()['success']
        assert agent.stage_manager.stages[0].checker[0].do_check()[0]
        by_name = {t.name: t for t in agent.test_tools}
        assert by_name['SubmitReviewClaims']._run(context={'description': 'No-Bug report input.', 'scope': 'Only source-accounted claims are reviewed.'}, claims=[], source_reviews=[{
            'path': 'inputs/report.md', 'disposition': 'no_claims',
            'reason': 'The source explicitly reports no Bugs.'}])['success']
        assert by_name['SubmitReviewDecisions']._run(decisions=[], roots=[])['success']
        assert by_name['RenderBugReviewReport']._run()['success']
        manager = agent.stage_manager
        for _ in range(6):
            if manager.all_completed:
                break
            stage = manager.stages[manager.stage_index]
            for path in stage.reference_files:
                manager.tool_read_text._run(path=path)
            manager.set_current_stage_journal('Verified no-claim source and generated the canonical empty review.')
            result = manager.complete(timeout=30)
            assert result.get('complete'), result
        assert manager.all_completed
        assert (tmp_path / 'index.html').is_file()
    finally:
        agent.exit()
