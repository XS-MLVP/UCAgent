"""Exercise GenSpec resources and checkers through the real agent lifecycle."""

from pathlib import Path

import pytest

from gen_spec.plugin import get_plugin
from ucagent.plugins import LoadedPlugin, validate_plugin
from ucagent.verify_agent import VerifyAgent


@pytest.mark.parametrize("use_skill", [False, True])
@pytest.mark.parametrize("compare_reference", [False, True])
def test_workflow_initializes_and_checks_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    use_skill: bool, compare_reference: bool,
) -> None:
    """Both skill settings must load packaged guides and enforce document checks."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GENSPEC_COMPARE_REFERENCE", str(compare_reference).lower())
    plugin = validate_plugin(get_plugin())
    workflow = plugin.workflows[0]
    dut = tmp_path / "Adder"
    dut.mkdir()
    (dut / "Adder.v").write_text(
        "module Adder(input a, b, output y); assign y = a ^ b; endmodule\n",
        encoding="utf-8",
    )
    (dut / "Adder.md").write_text("\n# Adder\n\nFixture inputs.\n", encoding="utf-8")
    agent = VerifyAgent(
        workspace=str(tmp_path), dut_name="Adder", output="spec",
        workflow_config_file=str(workflow.config_file),
        plugin_workflow="gen-spec:generate-spec",
        plugins=[LoadedPlugin(plugin, "gen-spec", "test")],
        plugin_guide_doc_paths=[str(path) for path in workflow.guide_doc_paths],
        cfg_override=[
            {"backend.key_name": "blank"}, {"langfuse.enable": False},
            {"skill.use_skill": use_skill},
        ],
        no_embed_tools=True, no_history=True,
    )
    try:
        guides = tmp_path / "Guide_Doc"
        assert {path.name for path in guides.glob("*.md")} == {
            "dut_spec_template.md", "dut_functions_and_checks.md", "dut_line_func_map.md",
        }
        assert not list((tmp_path / "spec").glob("*.py"))
        if not use_skill:
            assert not (tmp_path / ".ucagent" / "skills").exists()
        stages = {stage.name: stage for stage in agent.stage_manager.stages}
        assert stages["ref_function_line_map_generation"].is_skipped() is not compare_reference
        assert all(not stage.skill_list for stage in stages.values())
        agent.stage_manager.get_current_tips()

        main = stages["draft_main_spec"].checker[0]
        assert main.do_check()[0] is False
        guide = (guides / "dut_spec_template.md").read_text(encoding="utf-8")
        headings = [line for line in guide.splitlines() if line.startswith("## ")]
        document = "\n# Adder\n\n" + "\n\n".join(
            f"{heading}\n\nSee <ref_file>Adder/Adder.v:1-1</ref_file>."
            for heading in headings
        ) + "\n"
        target = tmp_path / "spec" / "Adder_spec.md"
        target.parent.mkdir()
        target.write_text(document, encoding="utf-8")
        passed, result = main.do_check()
        assert passed, result
        target.write_text(document.replace(headings[0], "## Missing section"), encoding="utf-8")
        assert main.do_check()[0] is False
        target.write_text(document.replace("Adder/Adder.v", "Adder/missing.v"), encoding="utf-8")
        assert main.do_check()[0] is False
        target.write_text(document, encoding="utf-8")

        # No independent components is valid; a declared empty component must fail.
        components = stages["draft_component_spec"].checker[0]
        components.on_init()
        passed, result = components.do_check(is_complete=True)
        assert passed, result
        component = tmp_path / "spec" / "Adder_spec_Core.md"
        component.write_text("", encoding="utf-8")
        components.on_init()
        assert components.do_check()[0] is False
        component.write_text(document, encoding="utf-8")
        passed, result = components.do_check()
        assert passed, result

        source = stages["augment_with_code"].checker[0]
        source.on_init()
        assert source.get_template_data()["CURRENT_FILE_NAME"] == "Adder/Adder.v"
        assert source.do_check()[0] is False
        agent.stage_manager.tool_read_text._run(path="Adder/Adder.v")
        passed, result = source.do_check()
        assert passed, result
        assert stages["human_check"].need_human_check
    finally:
        agent.exit()


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("false", False)])
def test_human_checkpoint_setting(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool,
) -> None:
    """The optional checkpoint review setting must retain boolean YAML semantics."""
    from ucagent.util.config import load_yaml_with_env_vars

    if value is None:
        monkeypatch.delenv("HUMAN_CHECK_CK", raising=False)
    else:
        monkeypatch.setenv("HUMAN_CHECK_CK", value)
    cfg = load_yaml_with_env_vars(str(get_plugin().workflows[0].config_file))
    review = cfg["stage"][5]["stage"][2]["checker"][0]["args"]["need_human_check"]
    assert review is expected
