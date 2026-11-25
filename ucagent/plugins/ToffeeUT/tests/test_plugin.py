"""Exercise real UCAgent configuration, resources, tools and skill-independent stage gates."""

from pathlib import Path
import re
import json
import site
import tomllib

import pytest
import yaml

from toffee_ut.audit import summarize
from toffee_ut.plugin import get_plugin
from toffee_ut.tools import BuildToffeeDUT, CoverageInfo, RunToffee, UTProject
from toffee_ut.waveform import WaveInfo
from toffee_ut.sources import capture_source_documents, record_source_documents
from ucagent import VerifyAgent
from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.core.plugins import LoadedPlugin, load_plugin, validate_plugin
from ucagent.core.tools.skill import _scan_skills
from ucagent.core.tools.uctool import to_mcp_tool
from ucagent.runtime.host import RuntimeHost
from ucagent.util.config import Config


ROOT = Path(__file__).resolve().parents[1]


def test_descriptor_manifest_packaging_and_mcp_contracts(tmp_path):
    """Local/installed discovery use one public descriptor and Pydantic tool schemas."""
    plugin = validate_plugin(get_plugin())
    assert load_plugin(str(ROOT)).plugin.name == plugin.name == "toffee-ut"
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = tomllib.loads((ROOT / "ucagent-plugin.toml").read_text())
    assert metadata["entry-points"]["ucagent.plugins"][plugin.name] == manifest["entry"]
    assert metadata["version"] == plugin.version
    cfg = Config({"runtime_options": {}, "write_dirs": ["ut_project"], "un_write_dirs": []})
    for cls in (UTProject, BuildToffeeDUT, WaveInfo, CoverageInfo):
        tool = cls(workspace=str(tmp_path), project="ut_project", dut="Block", cfg=cfg)
        schema = to_mcp_tool(tool).parameters
        assert schema["additionalProperties"] is False
    assert to_mcp_tool(RunToffee()).parameters["additionalProperties"] is False
    assert not any("unit_test" in str(value) for value in plugin.python_requirements)


@pytest.mark.parametrize("documents", [True, False])
@pytest.mark.parametrize("skills", [True, False])
def test_document_route_and_skill_toggle_render_one_common_workflow(tmp_path, monkeypatch, documents, skills):
    """Both input modes retain every original top-level stage and separate substage."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    if documents:
        path = tmp_path / "Block_Doc/spec.md"
        path.parent.mkdir()
        path.write_text("Independent supplied contract\n")
    loaded = LoadedPlugin(get_plugin(), "toffee-ut", "test")
    result = resolve_task_configuration(str(tmp_path), "Block", plugins=[loaded], plugin_workflow="toffee-ut:ut",
                                        cfg_override=[{"skill.use_skill": skills}])
    stages = {stage.name: stage for stage in result.cfg.stage}
    available = {f"ext/toffee-ut/{path.parent.name}" for path in (ROOT / "src/toffee_ut/skills").rglob("SKILL.md")}
    assert set(result.cfg.skill.general_skill_list) == available
    original = [
        "requirement_analysis_and_planning", "dut_function_understanding",
        "functional_specification_analysis", "functional_specification_refine",
        "static_bug_analysis", "dut_wrapper_implementation",
        "coverage_model_implementation", "test_environment_implementation",
        "basic_api_implementation", "reference_model_implementation",
        "reference_model_fixture_imp", "basic_api_functional_test",
        "create_test_case_templates", "comprehensive_verification_and_bug_analysis",
        "refine_test_cases_based_on_functional_points", "static_bug_validation",
        "line_coverage_analysis_and_improvement", "generate_random_test_cases",
        "verification_review_and_summary", "record_and_report_bugs",
    ]
    assert list(stages) == original
    from ucagent.util.config import load_yaml_with_env_vars
    old_workflow = load_yaml_with_env_vars(str(ROOT.parent / "UnitTest/src/unit_test/workflows/unittest.yaml"))
    def stage_names(items):
        """Yield every nested name to detect missing or silently merged stages."""
        for item in items:
            yield item.name
            yield from stage_names(item.get_value("stage", []))
    def old_names(items):
        """Yield original stage IDs without checking legacy tools or implementation."""
        for item in items:
            yield item["name"]
            yield from old_names(item.get("stage", []))
    assert list(stage_names(result.cfg.stage)) == list(old_names(old_workflow["stage"]))
    assert result.cfg.get_value("runtime_options.ut_document_mode") == ("provided" if documents else "derive")
    assert result.template_context["DESIGN_SPEC"] == "ut_project/docs/spec/design/Block.md"
    assert result.cfg.manager_tools == ["RunToffee"]
    assert result.cfg.runtime_options.ut_line_coverage is True
    assert not stages["line_coverage_analysis_and_improvement"].skip
    prompt = result.cfg.mission.prompt.system
    assert "新增、删除、修改及受影响依赖" in prompt
    assert "应变项、不得退化项、仍未知项" in prompt
    assert "定向结果只证明受影响子集" in prompt
    assert "同一证据引用同一原件" in prompt
    assert "不逐轮另存副本" in prompt
    assert "失败证据和已交付报告不可覆盖或删除" in prompt
    assert "保留旧报告和旧审阅的历史副本" not in prompt
    def all_stages(items):
        """Yield all configured stage nodes for scoped Skill and checker assertions."""
        for item in items:
            yield item
            yield from all_stages(item.get_value("stage", []))
    from toffee_ut.stage_audit import RESTORED_PHASES
    for stage in all_stages(result.cfg.stage):
        checkers = stage.checker if stage.has_attr("checker") else []
        assert all(row.clss in {"ToffeeUTChecker", "ToffeeUTBatchChecker", "HumanChecker"} for row in checkers)
        assert all(row.args.phase in RESTORED_PHASES | {"inputs", "design", "plan", "environment", "tests", "triage", "final"} for row in checkers if row.clss != "HumanChecker")
        if stage.has_attr("skill_list"):
            assert stage.force_use_skill is False
            assert set(stage.skill_list) <= available
    assert not (tmp_path / "ut_project").exists()


@pytest.mark.parametrize("key,value", [("ut_workers", False), ("ut_timeout", 0), ("ut_timeout", 3601), ("ut_documents", "spec.md"),
                                      ("ut_rtl_dirs", [1]), ("ut_document_mode", "guess"), ("ut_dut_package", 1)])
def test_invalid_runtime_options_fail_before_agent_construction(tmp_path, monkeypatch, key, value):
    """Bad positive-int/path/routing options fail at the workflow boundary, not mid-run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    loaded = LoadedPlugin(get_plugin(), "toffee-ut", "test")
    # Core template validation rejects non-string list members before the
    # workflow factory runs; other invalid options reach the plugin's gate.
    with pytest.raises((ValueError, AssertionError)):
        resolve_task_configuration(str(tmp_path), "Block", plugins=[loaded], plugin_workflow="toffee-ut:ut",
                                   cfg_override=[{f"runtime_options.{key}": value}])


@pytest.mark.parametrize("skills", [True, False])
def test_model_free_agent_requires_real_stage_artifacts_with_or_without_skills(
        project, checked_evidence, monkeypatch, skills):
    """Stage traversal rejects synthetic PASS when behavior-group evidence is absent."""
    monkeypatch.chdir(project)
    # Isolate UCAgent config, not the interpreter's existing user installation.
    if site.ENABLE_USER_SITE and site.USER_BASE:
        monkeypatch.setenv("PYTHONUSERBASE", site.USER_BASE)
    monkeypatch.setenv("HOME", str(project / "home"))
    agent = VerifyAgent(workspace=str(project), dut_name="Block", output="ut_project",
        plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")], plugin_workflow="toffee-ut:ut",
        cfg_override=[{"backend.key_name": "blank"}, {"skill.use_skill": skills}, {"langfuse.enable": False},
                      {"runtime_options.ut_rtl_dirs": ["inputs/Block.sv"]},
                      {"runtime_options.ut_documents": ["inputs/interface.md"]},
                      {"vmanager.llm_suggestion.check_fail_refinement.enable": False},
                      {"vmanager.llm_suggestion.check_pass_refinement.enable": False}],
        no_embed_tools=True, no_history=True)
    try:
        stages = {stage.name: stage for stage in agent.stage_manager.stages}
        coverage_tasks = "\n".join(stages["line_coverage_analysis_and_improvement"].task_info()["description"])
        assert "同类缺口合批" in coverage_tasks
        assert "只复核变动和受影响的审阅条目" in coverage_tasks
        assert "{OUT}" not in coverage_tasks and "{DUT}" not in coverage_tasks
        full_tasks = "\n".join(stages["comprehensive_verification_and_bug_analysis"].task())
        assert "完整选择" in full_tasks and "已有当前有效完整签名" in full_tasks
        assert (project / "Guide_Doc/ut-contracts.md").is_file()
        assert (project / "Guide_Doc/ut-methods.md").is_file()
        skill_root = project / ".ucagent/skills"
        available = {f"ext/toffee-ut/{path.parent.name}" for path in (ROOT / "src/toffee_ut/skills").rglob("SKILL.md")}
        if skills:
            assert {entry["name"] for entry in _scan_skills(str(project))} == available
            source = ROOT / "src/toffee_ut/skills"
            for path in source.rglob("*"):
                if path.is_file():
                    assert (skill_root / "ext/toffee-ut" / path.relative_to(source)).read_bytes() == path.read_bytes()
        else:
            assert not skill_root.exists()
        assert [tool.name for tool in agent.stage_manager.plugin_manager_tools] == ["RunToffee"]
        inspected = agent.get_tool_by_name("UTProject")._run("inspect")
        assert inspected["ok"], inspected
        assert agent.get_tool_by_name("UTProject")._run("scaffold")["ok"]
        # This real tool call still runs pure Python only. Typed native audit
        # inputs above are separate and never become claimed simulation output.
        run = agent.get_tool_by_name("RunToffee")._run(seed=23)
        assert run["ok"] and run["tests"] == {"PASS": 1}, run
        summarize(project, "Block", "ut_project")
        completed = []
        for _ in range(2):
            stage = agent.stage_manager.get_current_stage()
            assert all("{DESIGN_SPEC}" not in task and "{TB}" not in task for task in stage.task())
            if not skills:
                assert "skill_list" not in stage.task_info()
                assert not skill_root.exists()
            else:
                listing = agent.get_tool_by_name("ListSkill")._run()
                listed = set(re.findall(r"Skill Name: ([^\s]+)", listing))
                assert listed == available
                assert "pending/" not in listing
            stage.set_reference_file_status({name: "Readed" for name in stage.reference_files})
            agent.stage_manager.set_current_stage_journal("Typed fixture contract gate verified; no hardware run claimed.")
            result = agent.stage_manager.complete(timeout=20)
            assert result.get("complete"), result
            completed.append(stage.name)
        assert completed == ["requirement_analysis_and_planning", "dut_function_understanding"]
        stage = agent.stage_manager.get_current_stage()
        assert stage.name == "dut_function_grouping"
        stage.set_reference_file_status({name: "Readed" for name in stage.reference_files})
        agent.stage_manager.set_current_stage_journal("Synthetic execution is not behavior group evidence.")
        failed = agent.stage_manager.complete(timeout=20)
        assert not failed.get("complete") and "behavior_groups" in str(failed)
    finally:
        host = RuntimeHost(agent)
        host.start()
        host.request_shutdown()
        assert host.wait(5)["instance"] == "closed"


def test_runtime_markdown_heading_spacing_and_skill_metadata():
    """Guides, rendered template text and optional method files obey the maintained format."""
    package = ROOT / "src/toffee_ut"
    files = [*(package / "Guide_Doc").glob("*.md"), *(package / "skills").rglob("*.md"),
             *(package / "templates").rglob("*.md.j2")]
    for path in files:
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if re.match(r"^#{1,6} ", line):
                assert index and not lines[index - 1].strip(), (path, index + 1)
                assert index + 1 < len(lines) and not lines[index + 1].strip(), (path, index + 1)
        if path.name == "SKILL.md":
            meta = yaml.safe_load(path.read_text().split("---", 2)[1])
            assert meta["name"] == path.parent.name and meta["description"]


def test_root_project_can_be_scaffolded_without_a_root_template_target(tmp_path, monkeypatch):
    """Explicit --output . uses per-file automation and a bounded root write footprint."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    loaded = LoadedPlugin(get_plugin(), "toffee-ut", "test")
    prepared = resolve_task_configuration(str(tmp_path), "Block", output=".", plugins=[loaded],
                                          plugin_workflow="toffee-ut:ut")
    tool = UTProject(workspace=str(tmp_path), project=".", dut="Block", cfg=prepared.cfg)
    assert prepared.template_dir is None
    assert tool._run("scaffold")["ok"]
    assert (tmp_path / "conftest.py").is_file()
    assert not (tmp_path / "ut_project").exists()
    assert ".ucagent" not in prepared.cfg.write_dirs and "inputs" not in prepared.cfg.write_dirs


def test_guide_examples_obey_the_actual_contract_parser(tmp_path, checked_evidence, project):
    """Complete maintained guide examples are executable contract fixtures rather than fragments."""
    from toffee_ut.audit import audit_project, read_spec
    from toffee_ut.project import scaffold
    package = ROOT / "src/toffee_ut"
    guide = (package / "Guide_Doc/ut-contracts.md").read_text()
    examples = re.findall(r"````markdown\n(.*?)^````$", guide, re.M | re.S)
    assert len(examples) == 2
    workspace = tmp_path / "guide_workspace"
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "inputs/queue-interface.md").write_text("Independent interface contract input for example parsing.\n")
    scaffold(workspace, "Queue")
    (workspace / "ut_project/docs/spec/design/Queue.md").write_text(examples[0])
    (workspace / "ut_project/docs/spec/verification/Queue.md").write_text(examples[1])
    record_source_documents(workspace, "Queue", "ut_project", capture_source_documents(
        workspace, "Queue", "ut_project", ["inputs/queue-interface.md"]))
    assert audit_project(workspace, "Queue", phase="plan")["ok"]
    results = (package / "Guide_Doc/ut-results.md").read_text()
    issue, report = re.findall(r"````markdown\n(.*?)^````$", results, re.M | re.S)
    issue_file = workspace / "issue.md"
    issue_file.write_text(issue)
    assert read_spec(issue_file, "issue")["classification"] == "unconfirmed"
    fields = json.loads(re.search(r"```json\n(.*?)^```$", report, re.M | re.S)[1])
    assert set(fields) == set(summarize(project, "Block", "ut_project"))
