"""Regress source/RTL evidence, flexible writing, packaged execution and stage lifecycle."""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import draft
from spec_generator_plugin.checkers import SpecGeneratorArtifactsChecker
from spec_generator_plugin.evidence import read_json
from spec_generator_plugin.documents import artifact_paths
from spec_generator_plugin.tools import SpecGeneratorCommand
from spec_generator_plugin.validation import validate


def test_full_pipeline_and_cache(artifacts, command):
    """Packaged scripts work without workspace implementations and reuse only signed RTL."""
    assert not (artifacts / "src").exists()
    assert not (artifacts / "Makefile").exists()
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    for version in ("v1.0.0", "v1.0.1"):
        result = command._run("evidence", "Sbuffer", version=version)
        assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    rtl = next((artifacts / ".cache/rtl").glob("*/split/Sbuffer.sv"))
    rtl.write_text(rtl.read_text().replace("[7:0]", "[6:0]"))
    result = command._run("evidence", "Sbuffer", version="v1.0.2")
    assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "2"
    assert "[7:0]" in (artifacts / "evidence/Sbuffer/v1.0.2/Sbuffer.sv").read_text()


@pytest.mark.parametrize(
    "target",
    [
        "manifest",
        "ports",
        "rtl",
        "source",
        "config",
        "receipt",
        "template",
        "empty",
        "reference",
        "link",
        "width",
        "diagram",
    ],
)
def test_invalid_artifacts_fail_with_diagnostics(artifacts, target):
    """Material contradictions and missing evidence cannot be hidden by consistent prose."""
    root = artifacts
    design = artifact_paths(root, "Sbuffer", "v1.0.0")[0]
    evidence = root / "evidence/Sbuffer/v1.0.0"
    config = "DefaultConfig"
    if target == "manifest":
        (evidence / "manifest.json").write_text("{}")
    elif target == "ports":
        (evidence / "ports.csv").write_text(
            (evidence / "ports.csv").read_text().replace("io_data", "io_fake")
        )
    elif target == "rtl":
        (evidence / "Sbuffer.sv").unlink()
    elif target == "source":
        (root / "third_party/XiangShan/src/main/scala/Sbuffer.scala").write_text(
            "changed source"
        )
    elif target == "config":
        config = "TestConfig"
    elif target == "receipt":
        (root / ".ucagent/.spec_generator_receipt_key").unlink()
    elif target == "template":
        design.write_text(
            design.read_text().replace(
                "| 文档范围 | 合成直连夹具 |", "| 使用模板版本 | v2.0.0 |"
            )
        )
    elif target == "empty":
        design.write_text("\n# Empty\n\n<!-- no content -->\n")
    elif target == "reference":
        design.write_text(design.read_text() + "\nRelated rule `P-UNKNOWN`.\n")
    elif target == "link":
        design.write_text(design.read_text() + "\n[RTL](missing.sv)\n")
    elif target == "width":
        design.write_text(
            design.read_text().replace("| `io_data` | I/8 |", "| `io_data` | I/32 |")
        )
    else:
        design.write_text(
            design.read_text() + "\n```mermaid\nflowchart LR\n A --> B\n```\n"
        )
    result = validate(root, "Sbuffer", "v1.0.0", config)
    assert not result["ok"], result
    assert result["artifact"] and result["next_action"] and result["observed"]


def test_fabricated_documents_without_tool_evidence_fail(tmp_path):
    """Mutually consistent fabricated documents cannot replace actual tool evidence."""
    folder = tmp_path / "evidence/Sbuffer/v1.0.0"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "module": "Sbuffer",
                "config": "DefaultConfig",
                "rtl_sha256": "a" * 64,
            }
        )
    )
    draft(tmp_path)
    assert not validate(tmp_path, "Sbuffer", "v1.0.0", "DefaultConfig")["ok"]


def test_content_remains_flexible_within_template(artifacts, command):
    """Table row counts, cell formatting, prose and diagrams are not fixed by the template."""
    design = artifact_paths(artifacts, "Sbuffer", "v1.0.0")[0]
    design.write_text(
        design.read_text()
        .replace(
            "| 直连实例 | 1 | 转发 8 位数据 |",
            "| 直连实例 | 1 | 转发 8 位数据 |\n| 未启用实例 | 0 | 不适用 |",
        )
        .replace("#### `P-FORWARD`：组合转发", "#### P-FORWARD：更新后的行为名称")
    )
    result = validate(artifacts, "Sbuffer", "v1.0.0", "DefaultConfig")
    assert result["ok"], result
    assert (
        read_json(artifacts / "evidence/Sbuffer/v1.0.0/diagrams/manifest.json")[
            "diagram_count"
        ]
        == 0
    )


def test_metadata_summary_is_literal_and_history_preserved(artifacts, command):
    """Free text never enters a shell; existing semantic history is not rewritten."""
    _, _, history = artifact_paths(artifacts, "Sbuffer", "v1.0.0")
    history.write_text("\n# History\n\nAn existing introduction.\n")
    summary = 'check $(touch injected) `touch injected` "quoted"'
    result = command._run(
        "metadata", "Sbuffer", version="v1.0.0", change_type="Patch", summary=summary
    )
    assert result["ok"], result
    original = history.read_bytes()
    assert summary in original.decode()
    assert not (artifacts / "injected").exists()
    assert command._run("metadata", "Sbuffer", version="v1.0.0")["ok"]
    assert history.read_bytes() == original


def test_metadata_failure_does_not_partially_edit(artifacts, command):
    """Missing history details fail before factual document fields are changed."""
    paths = artifact_paths(artifacts, "Sbuffer", "v1.0.0")
    paths[2].write_text("\n# History\n\nNo current version yet.\n")
    before = [path.read_bytes() for path in paths]
    assert not command._run("metadata", "Sbuffer", version="v1.0.0")["ok"]
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize(
    "args",
    [
        dict(action="clean", module="Sbuffer"),
        dict(action="preflight", module="../x"),
        dict(action="preflight", module="Sbuffer", config="$(touch x)"),
        dict(action="evidence", module="Sbuffer"),
        dict(
            action="metadata", module="Sbuffer", version="v1.0.0", change_type="Patch"
        ),
    ],
)
def test_invalid_arguments_do_not_launch(command, monkeypatch, args):
    """Reject invalid public arguments before spawning any program."""

    def fail(*args, **kwargs):
        """Detect any accidental launch for invalid input."""
        pytest.fail("unexpected subprocess")

    monkeypatch.setattr(subprocess, "Popen", fail)
    assert command._run(**args)["error_code"] == "INVALID_ARGUMENTS"


def test_workspace_source_prerequisite(tmp_path):
    """An installed plugin diagnoses missing source, not missing workspace scripts."""
    result = SpecGeneratorCommand(workspace=str(tmp_path), write_dirs=[".cache"])._run(
        "preflight", "Sbuffer"
    )
    assert not result["ok"]
    assert "third_party/XiangShan" in result["stdout"]
    assert "Makefile" not in result["stdout"]


@pytest.mark.parametrize("dirty", [False, True])
def test_preflight_requires_a_clean_source(workspace, dirty):
    """The packaged preflight enforces clean source without an optional strict mode."""
    from spec_generator_plugin.plugin import get_plugin

    if dirty:
        (workspace / "third_party/XiangShan/src/main/scala/Sbuffer.scala").write_text(
            "class Sbuffer // local edit\n"
        )
    result = subprocess.run(
        ["bash", str(get_plugin().root / "scripts/preflight.sh"), "--module", "Sbuffer"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) is (not dirty), result.stdout + result.stderr
    if dirty:
        assert "XiangShan worktree is dirty" in result.stderr


def test_write_policy_and_external_symlinks(command, workspace, tmp_path):
    """Protect explicit read-only descendants and reject writable symlink escapes."""
    command.un_write_dirs.append("evidence/Sbuffer/v1.0.0/manifest.json")
    assert (
        command._run("evidence", "Sbuffer", version="v1.0.0")["error_code"]
        == "WRITE_POLICY_DENIED"
    )
    command.un_write_dirs.pop()
    folder = workspace / "evidence/Sbuffer/v1.0.0"
    folder.mkdir(parents=True)
    (folder / "manifest.json").symlink_to(tmp_path / "external.json")
    assert (
        command._run("evidence", "Sbuffer", version="v1.0.0")["error_code"]
        == "PATH_OUTSIDE_WORKSPACE"
    )
    assert not (tmp_path / "external.json").exists()


def test_timeout_and_no_rtl_failure(command, workspace, monkeypatch):
    """Missing compiler output and process-tree timeouts cannot create valid evidence."""
    monkeypatch.setenv("SPEC_TEST_NO_RTL", "1")
    result = command._run("evidence", "Sbuffer", version="v1.0.0")
    assert not result["ok"], result
    assert "did not produce Sbuffer.sv" in result["stderr"]
    monkeypatch.delenv("SPEC_TEST_NO_RTL")
    monkeypatch.setenv("SPEC_TEST_DELAY", "15")
    command.command_timeout = 2
    assert (
        command._run("evidence", "Sbuffer", version="v1.0.0")["error_code"]
        == "COMMAND_TIMEOUT"
    )
    assert not (workspace / "evidence/Sbuffer/v1.0.0/manifest.json").exists()


def test_checker_reads_current_state(artifacts):
    """Check and Complete share current validation and never regenerate missing artifacts."""
    checker = SpecGeneratorArtifactsChecker("Sbuffer", "v1.0.0").set_workspace(
        str(artifacts)
    )
    assert checker.do_check()[0]
    (artifacts / "evidence/Sbuffer/v1.0.0/ports.csv").write_text("")
    assert not checker.do_check(is_complete=True)[0]
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"


@pytest.mark.parametrize("enabled", [False, True])
def test_fresh_agent_stages(workspace, command, monkeypatch, enabled):
    """Start without generated references; all stages gate content with Skills on and off."""
    from ucagent.verify_agent import VerifyAgent
    from ucagent.plugins import (
        collect_plugin_resources,
        load_plugin,
        resolve_plugin_workflow,
    )

    from spec_generator_plugin.plugin import get_plugin

    project = Path(__file__).resolve().parents[1]
    if get_plugin().root == project / "src/spec_generator_plugin":
        if enabled:
            # Exercise source discovery as it works before the distribution is installed.
            monkeypatch.setattr("ucagent.plugins._entry_points", lambda: [])
            loaded = load_plugin("xiangshan-spec-generator", search_paths=[project])
        else:
            loaded = load_plugin(str(project))
    else:
        loaded = load_plugin("xiangshan-spec-generator")
    selected = resolve_plugin_workflow(
        [loaded], "xiangshan-spec-generator:design-document"
    )
    docs, skills = collect_plugin_resources([loaded], selected)
    monkeypatch.setenv("SPEC_DOCUMENT_VERSION", "v1.0.0")
    monkeypatch.setenv("XIANGSHAN_CONFIG", "TestConfig")
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="Sbuffer",
        output="rendered",
        cfg_override=[
            {"backend.key_name": "blank"},
            {"langfuse.enable": False},
            {"skill.use_skill": enabled},
        ],
        no_embed_tools=True,
        no_history=True,
        plugins=[loaded],
        plugin_guide_doc_paths=[str(path) for path in docs],
        plugin_skill_paths=[],
        workflow_config_file=str(selected[1].config_file),
        plugin_workflow="xiangshan-spec-generator:design-document",
    )
    try:
        assert skills == []
        tool_names = {tool.name for tool in agent.test_tools}
        assert tool_names == set(agent.cfg.tools.selected_tools)
        assert {"SpecGeneratorCommand", "Check", "Complete", "ReadTextFile"} <= tool_names
        assert not {"RunBashCommand", "RunTestCases", "RunSkillScript"} & tool_names
        assert not (workspace / "rendered/chip_design_document_template_zh.md").exists()
        assert "ListSkill" not in agent.get_default_system_prompt()
        assert (workspace / ".ucagent/skills").exists() is enabled
        for index, stage in enumerate(agent.stage_manager.stages):
            assert agent.stage_manager.stage_index == index
            assert "Guide_Doc/generation-guide.md" in stage.reference_files
            assert "Guide_Doc/chip_design_document_template_zh.md" in stage.reference_files
            stage.need_pass_llm_suggestion = False
            for name in stage.reference_files:
                agent.tool_read_text.invoke({"path": name})
            if index == 0:
                assert not stage.do_check(is_complete=True)[0]
                result = command._run(
                    "evidence", "Sbuffer", config="TestConfig", version="v1.0.0"
                )
                assert result["ok"], result
            elif index == 1:
                assert any(name.endswith("ports.csv") for name in stage.reference_files)
                for path in artifact_paths(workspace, "Sbuffer", "v1.0.0"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                assert not stage.do_check(is_complete=True)[0]
                draft(workspace)
                assert command._run(
                    "metadata", "Sbuffer", config="TestConfig", version="v1.0.0"
                )["ok"]
            else:
                assert any(
                    name.endswith("_v1.0.0.md") for name in stage.reference_files
                )
                assert not stage.do_check(is_complete=True)[0]
                assert command._run(
                    "render", "Sbuffer", config="TestConfig", version="v1.0.0"
                )["ok"]
            passed, result = stage.do_check(is_complete=True)
            assert passed, result
            stage.meta_set_journal(
                "Verified synthetic fixture artifacts for this test stage."
            )
            result = agent.stage_manager.complete(timeout=30)
            assert result["complete"], result
        assert agent.stage_manager.all_completed
    finally:
        agent.exit()


def test_partial_generation_is_explicit(command, workspace, monkeypatch):
    """A target RTL file produced before downstream failure is accepted with a warning."""
    monkeypatch.setenv("SPEC_TEST_RC", "7")
    result = command._run("evidence", "Sbuffer", version="v1.0.0")
    assert result["ok"], result
    result = validate(workspace, "Sbuffer", "v1.0.0", "DefaultConfig", "evidence")
    assert result["ok"] and any("partial" in message for message in result["warnings"])


def test_cached_rtl_is_not_required_for_check(artifacts):
    """Deleting disposable RTL cache does not invalidate the persistent evidence copy."""
    import shutil

    shutil.rmtree(artifacts / ".cache/rtl")
    assert validate(artifacts, "Sbuffer", "v1.0.0", "DefaultConfig")["ok"]


@pytest.mark.parametrize(
    "text, valid",
    [
        ("module X(input [15:8] data, output result); endmodule", True),
        ("module X(input [WIDTH:0] data); endmodule", False),
        ("module X(input data, output data); endmodule", False),
    ],
)
def test_elaborated_port_parser(text, valid):
    """Accept literal widths and reject unresolved or duplicate elaborated ports."""
    from spec_generator_plugin.evidence import parse_ports

    if valid:
        assert parse_ports(text, "X")[0]["width"] == 8
    else:
        with pytest.raises(ValueError):
            parse_ports(text, "X")


def test_markdown_fences_are_checked_without_fixed_layout():
    """Alternative Markdown fence delimiters work; unfinished blocks fail."""
    from spec_generator_plugin.documents import mermaid_sources

    assert mermaid_sources("~~~mermaid\nflowchart LR\n A --> B\n~~~\n") == [
        "flowchart LR\n A --> B\n"
    ]
    with pytest.raises(ValueError, match="unclosed"):
        mermaid_sources("```mermaid\nflowchart LR\n")


@pytest.mark.parametrize(
    "version,config", [("v1.0.0", "DefaultConfig"), ("v3.1.2", "TestConfig")]
)
def test_resolved_workflow_parameters(monkeypatch, version, config):
    """All stage gates consume the selected config/version and disable generic templates."""
    from spec_generator_plugin.plugin import get_plugin
    from ucagent.util.config import load_yaml_with_env_vars

    monkeypatch.setenv("SPEC_DOCUMENT_VERSION", version)
    monkeypatch.setenv("XIANGSHAN_CONFIG", config)
    cfg = load_yaml_with_env_vars(str(get_plugin().workflows[0].config_file))
    assert cfg["template"] is None
    assert cfg["template_overwrite"] == {"VERSION": version, "XS_CONFIG": config}
    for stage in cfg["stage"]:
        assert stage["checker"][0]["args"]["config"] == "{XS_CONFIG}"


def test_cached_status_cannot_be_upgraded_by_editing_logs(
    command, workspace, monkeypatch
):
    """Unsigned ancillary cache files cannot turn partial generation into success."""
    monkeypatch.setenv("SPEC_TEST_RC", "7")
    assert command._run("evidence", "Sbuffer", version="v1.0.0")["ok"]
    folder = next((workspace / ".cache/rtl").iterdir())
    (folder / "generation.exit-code").write_text("0\n")
    (folder / "tool_versions.json").write_text('{"java": "fabricated"}')
    result = command._run("evidence", "Sbuffer", version="v1.0.1")
    assert result["ok"], result
    manifest = read_json(workspace / "evidence/Sbuffer/v1.0.1/manifest.json")
    assert manifest["generation_status"] == "partial"
    assert manifest["tool_versions"]["java"] != "fabricated"
    assert (workspace / ".cache/compiler-calls").read_text() == "1"


@pytest.mark.parametrize("phase", ["draft", "final"])
@pytest.mark.parametrize("defect", ["heading", "table"])
def test_stage_gates_template_structure(artifacts, phase, defect):
    """Real stage Check/Complete rejects structure errors even when evidence and metadata match."""
    path = artifact_paths(artifacts, "Sbuffer", "v1.0.0")[0]
    text = path.read_text(encoding="utf-8")
    if defect == "heading":
        text = text.replace("### 文档摘要", "### 自定义标题")
    else:
        text = text.replace(
            "| 参数 | 取值 |\n| --- | --- |\n| 数据宽度 | 8 位，无可配置参数 |", ""
        )
    path.write_text(text, encoding="utf-8")
    checker = SpecGeneratorArtifactsChecker(
        "Sbuffer", "v1.0.0", phase=phase
    ).set_workspace(str(artifacts))
    for complete in (False, True):
        passed, result = checker.do_check(is_complete=complete)
        assert not passed, result
        assert result["artifact"].endswith("_design_document_zh_v1.0.0.md")
        assert "Guide_Doc/chip_design_document_template_zh.md" in result["next_action"]
