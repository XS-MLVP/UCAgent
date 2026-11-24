"""Task adoption and explicit stage selection without constructing or running a DUT."""

from copy import deepcopy
from pathlib import Path
import re

import pytest

from toffee_ut.adoption import ToffeeUTAdoptionChecker, stage_catalog
from toffee_ut.audit import read_spec
from toffee_ut.plugin import get_plugin
from toffee_ut.tools import require_writable
from ucagent import VerifyAgent
from ucagent.core.agent.configuration import resolve_task_configuration
from ucagent.core.plugins import LoadedPlugin
from ucagent.core.stage.vstage import get_root_stage
from ucagent.core.tools.fileops import ReadTextFile
from ucagent.core.workspace.assets import prepare_resources
from ucagent.runtime.host import RuntimeHost
from ucagent.util.config import Config
from ucagent.util.functions import save_ucagent_info


def prepare(tmp_path, monkeypatch, workflow="ut", **options):
    """Resolve an isolated workflow with no dependency on the operator's configuration."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return resolve_task_configuration(
        str(tmp_path), "Block", plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")],
        plugin_workflow=f"toffee-ut:{workflow}", cfg_override=[options])


@pytest.mark.parametrize("skills", [False, True])
def test_adoption_accepts_unregistered_project_and_has_no_execution_tools(tmp_path, monkeypatch, skills):
    """Adoption reads relevant files without demanding a schema2 suite or a full baseline."""
    root = tmp_path / "ut_project"
    root.mkdir()
    original = root / "monitor.py"
    original.write_text("# Existing partial implementation, not a native test.\n")
    result = prepare(tmp_path, monkeypatch, workflow="adopt", **{"skill.use_skill": skills})
    assert result.cfg.manager_tools == [] and result.template_dir is None
    assert {"UTProject", "BuildToffeeDUT", "RunToffee", "RunBashCommand"} <= set(result.cfg.tools.ignore_tools)
    assert len(result.cfg.stage) == 3 and not (root / "workspace.json").exists()
    assert not (root / "docs").exists() and original.read_text().startswith("# Existing")
    assert result.template_context["ADOPTION_REPORT"] == "ut_project/docs/reviews/Block-adoption.md"
    assert len(stage_catalog()) == 39
    require_writable(str(tmp_path), result.cfg, [root / "docs/reviews/Block-adoption.md"])
    with pytest.raises(ValueError):
        require_writable(str(tmp_path), result.cfg, [original])
    registry = {checker.__name__: checker for checker in get_plugin().checkers}
    stages = get_root_stage(result.cfg, str(tmp_path), ReadTextFile(str(tmp_path)), registry).get_substages()
    assert len(stages) == 3 and stages[-1].is_hmcheck_needed()
    assert all(not stage.skill_list for stage in stages)
    save_ucagent_info(str(tmp_path), {"stage_index": 10})
    agent = VerifyAgent(workspace=str(tmp_path), dut_name="Block", output="ut_project",
        plugins=[LoadedPlugin(get_plugin(), "toffee-ut", "test")], plugin_workflow="toffee-ut:adopt",
        cfg_override=[{"backend.key_name": "blank", "langfuse.enable": False, "skill.use_skill": skills}],
        no_embed_tools=True, no_history=True)
    try:
        assert agent.stage_manager.get_current_stage().name == "adoption_task_scope"
        assert not agent.stage_manager.plugin_manager_tools
        for name in ("UTProject", "BuildToffeeDUT", "RunToffee", "RunBashCommand", "WaveInfo", "CoverageInfo"):
            assert agent.get_tool_by_name(name) is None
        assert (tmp_path / "Guide_Doc/ut-adoption.md").is_file()
        if not skills:
            assert not (tmp_path / ".ucagent/skills").exists()
        assert original.read_text().startswith("# Existing")
        assert not (root / "results").exists()
    finally:
        host = RuntimeHost(agent)
        host.start()
        host.request_shutdown()
        assert host.wait(5)["instance"] == "closed"


@pytest.mark.parametrize("skills", [False, True])
@pytest.mark.parametrize("chosen,phases", [
    (["env_fixture_implementation", "evaluate_env_fixture"], ["environment_impl", "env_selftest"]),
    (["implemente_function_checks_in_batch"], ["coverage_checks"]),
])
def test_explicit_child_selection_does_not_run_parent_acceptance_or_siblings(tmp_path, monkeypatch, skills, chosen, phases):
    """Any task-selected child remains independent; omitted stages are skipped, not completed."""
    result = prepare(tmp_path, monkeypatch, **{
        "skill.use_skill": skills, "runtime_options.ut_task": "Repair monitor sampling",
        "runtime_options.ut_task_stages": list(reversed(chosen))})
    assert len(result.cfg.stage) == 20
    assert len(stage_catalog([row.as_dict() for row in result.cfg.stage])) == 39
    resources = prepare_resources(result)
    try:
        registry = {checker.__name__: checker for checker in get_plugin().checkers}
        stages = get_root_stage(result.cfg, str(tmp_path), ReadTextFile(str(tmp_path)), registry).get_substages()
        active = [stage for stage in stages if not stage.is_skipped()]
        assert [stage.name for stage in active] == chosen
        assert [stage.checker[0].phase for stage in active] == phases
        assert all(not stage.is_completed() for stage in stages)
        assert "Repair monitor sampling" in result.cfg.mission.prompt.system
        if not skills:
            assert not (tmp_path / ".ucagent/skills").exists()
    finally:
        resources.permissions.restore()


def test_task_can_select_late_stage_without_a_skip_whitelist(tmp_path, monkeypatch):
    """Selection is user scope, not certification that all omitted work is satisfied."""
    result = prepare(tmp_path, monkeypatch, **{
        "runtime_options.ut_task": "Review an existing delivery",
        "runtime_options.ut_task_stages": ["record_and_report_bugs"]})
    assert not result.cfg.stage[-1].skip
    assert result.cfg.stage[-1].checker[0].args.phase == "final"
    assert all(row.skip for row in result.cfg.stage[:-1])


def test_parent_selection_respects_disabled_optional_children(tmp_path, monkeypatch):
    """Selecting a parent is not permission to activate Mock or human review branches."""
    result = prepare(tmp_path, monkeypatch, **{
        "runtime_options.ut_task": "Review the environment",
        "runtime_options.ut_task_stages": ["test_environment_implementation"]})
    parent = next(row for row in result.cfg.stage if row.name == "test_environment_implementation")
    active = [row.name for row in parent.stage if not row.skip]
    assert active == ["bundle_wrapper_design", "env_fixture_implementation", "evaluate_env_fixture"]


@pytest.mark.parametrize("options", [
    {"runtime_options.ut_task_stages": ["dut_function_understanding"]},
    {"runtime_options.ut_task_stages": []},
    {"runtime_options.ut_task_stages": "dut_function_understanding"},
    {"runtime_options.ut_task_stages": [1]},
    {"runtime_options.ut_task_stages": ["not_a_stage"]},
    {"runtime_options.ut_task_stages": ["static_bug_analysis", "static_bug_analysis"]},
    {"runtime_options.ut_task_stages": ["reference_model_implementation"]},
    {"runtime_options.ut_task": True},
])
def test_ambiguous_unknown_or_disabled_selection_is_rejected(tmp_path, monkeypatch, options):
    """Fail before execution instead of silently choosing a wider or empty scope."""
    overrides = {"runtime_options.ut_task": "Investigate current issue", **options}
    if options == {"runtime_options.ut_task_stages": ["dut_function_understanding"]}:
        overrides["runtime_options.ut_task"] = ""
    with pytest.raises((ValueError, AssertionError)):
        prepare(tmp_path, monkeypatch, **overrides)


def test_handoff_checks_only_task_scope_and_relevant_local_assets(tmp_path, contract_writer):
    """Missing suite results are not a blocker to a truthful task handoff."""
    root = tmp_path / "ut_project"
    root.mkdir()
    (root / "monitor.py").write_text("# Existing code under investigation.\n")
    path = root / "docs/reviews/Block-adoption.md"
    data = {"kind": "task_adoption", "dut": "Block", "project": "ut_project",
            "task": "Repair monitor", "acceptance": ["Relevant controls detect dropped events"],
            "out_of_scope": ["Full DUT acceptance"],
            "assets": [{"path": "ut_project/monitor.py", "use": "repair", "note": "No execution claim"}],
            "dependencies": [], "selected_stages": ["env_fixture_implementation", "evaluate_env_fixture"],
            "revalidation": ["Run affected controls after the implementation changes"]}
    contract_writer(path, data)
    for phase in ("task", "inventory", "handoff"):
        checker = ToffeeUTAdoptionChecker(phase, dut="Block").set_workspace(str(tmp_path))
        passed, result = checker.do_check(is_complete=True)
        assert passed and "not stage completion" in result["note"]
    for change in ({"selected_stages": ["missing"]}, {"acceptance": []}, {"project": "another"},
                   {"assets": [{"path": "../outside.py", "use": "reuse", "note": "Unsafe"}]}):
        contract_writer(path, {**deepcopy(data), **change})
        passed, result = checker.do_check(is_complete=True)
        assert not passed and result["error_code"] == "UT_ADOPTION_INVALID"
    contract_writer(path, {**data, "assets": [], "dependencies": ["Need the user's monitor source"]})
    assert checker.do_check()[0]
    contract_writer(path, data)
    checker.cfg = Config({"runtime_options": {"ut_task": data["task"],
                                              "ut_task_stages": data["selected_stages"]}})
    assert checker.do_check()[0]
    for change in ({"task": "A different task"}, {"selected_stages": ["static_bug_analysis"]}):
        contract_writer(path, {**data, **change})
        passed, result = checker.do_check()
        assert not passed and "differ" in result["error"]
    assert not (root / "results").exists() and not (root / "workspace.json").exists()


def test_complete_adoption_guide_example_matches_the_parser(tmp_path):
    """The canonical example is a valid complete handoff, not a fragment to invent around."""
    package = Path(__file__).resolve().parents[1] / "src/toffee_ut"
    text = (package / "Guide_Doc/ut-adoption.md").read_text()
    example = re.search(r"````markdown\n(.*?)^````$", text, re.M | re.S)[1]
    path = tmp_path / "ut_project/docs/reviews/Queue-adoption.md"
    path.parent.mkdir(parents=True)
    path.write_text(example)
    value = read_spec(path, "task_adoption", "Queue")
    for asset in value["assets"]:
        source = tmp_path / asset["path"]
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# Canonical handoff asset, not a real DUT.\n")
    checker = ToffeeUTAdoptionChecker("handoff", dut="Queue").set_workspace(str(tmp_path))
    assert checker.do_check()[0]
