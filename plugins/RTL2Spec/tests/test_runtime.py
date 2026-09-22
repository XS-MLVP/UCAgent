"""Regress source/RTL evidence, flexible writing, packaged execution and stage lifecycle."""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import draft
from rtl2spec.checkers import RTL2SpecArtifactsChecker
from rtl2spec.evidence import read_json
from rtl2spec.documents import METADATA_RE, artifact_paths
from rtl2spec.tools import RTL2SpecCommand
from rtl2spec.validation import validate


def test_new_generation_requires_clean_output_directories(artifacts, command):
    """A second generation run stops before touching existing documents or evidence."""
    assert not (artifacts / "src").exists()
    assert not (artifacts / "Makefile").exists()
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    before = (artifacts / "evidence/Sbuffer/manifest.json").read_bytes()
    result = command._run("evidence", "Sbuffer")
    assert result["error_code"] == "OUTPUT_DIRECTORY_NOT_CLEAN", result
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    assert (artifacts / "evidence/Sbuffer/manifest.json").read_bytes() == before


def test_user_archival_allows_regeneration_with_verified_cache(artifacts, command):
    """After user archival, reuse attested RTL but regenerate any corrupted cache."""
    archive = artifacts / "archive"
    archive.mkdir()
    for directory in ("outputs", "reports", "evidence"):
        (artifacts / directory / "Sbuffer").rename(archive / directory)
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    draft(artifacts)
    for action in ("metadata", "lint"):
        result = command._run(action, "Sbuffer")
        assert result["ok"], result
    for directory in ("outputs", "reports", "evidence"):
        (artifacts / directory / "Sbuffer").rename(archive / f"second-{directory}")
    cached_rtl = next((artifacts / ".cache/rtl").glob("*/split/Sbuffer.sv"))
    cached_rtl.write_text(cached_rtl.read_text() + "\n// Unattested change\n")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "2"
    assert (archive / "outputs/Sbuffer_design_document_zh.md").is_file()


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
        "unclosed_mermaid",
    ],
)
def test_invalid_artifacts_fail_with_diagnostics(artifacts, target):
    """Material contradictions and missing evidence cannot be hidden by consistent prose."""
    root = artifacts
    design = artifact_paths(root, "Sbuffer")[0]
    evidence = root / "evidence/Sbuffer"
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
        (root / ".ucagent/.rtl2spec_receipt_key").unlink()
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
    elif target == "unclosed_mermaid":
        design.write_text(
            design.read_text() + "\n```mermaid\nflowchart LR\n A --> B\n"
        )
    result = validate(root, "Sbuffer", config)
    assert not result["ok"], result
    assert result["artifact"] and result["next_action"] and result["observed"]


def test_fabricated_documents_without_tool_evidence_fail(tmp_path):
    """Mutually consistent fabricated documents cannot replace actual tool evidence."""
    folder = tmp_path / "evidence/Sbuffer"
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
    assert not validate(tmp_path, "Sbuffer", "DefaultConfig")["ok"]


def test_content_remains_flexible_within_template(artifacts, command):
    """Table row counts, cell formatting, prose and Mermaid source are not fixed by the template."""
    design = artifact_paths(artifacts, "Sbuffer")[0]
    design.write_text(
        design.read_text()
        .replace(
            "| 直连实例 | 1 | 转发 8 位数据 |",
            "| 直连实例 | 1 | 转发 8 位数据 |\n| 未启用实例 | 0 | 不适用 |",
        )
        .replace("#### `P-FORWARD`：组合转发", "#### P-FORWARD：更新后的行为名称")
    )
    result = validate(artifacts, "Sbuffer", "DefaultConfig")
    assert result["ok"], result


def test_metadata_updates_only_current_documents(artifacts, command):
    """Repeat metadata synchronization preserves author content without document versions."""
    design, report = artifact_paths(artifacts, "Sbuffer")
    before = [path.read_bytes() for path in (design, report)]
    result = command._run("metadata", "Sbuffer")
    assert result["ok"], result
    assert not (artifacts / "outputs/Sbuffer/VERSION_HISTORY.md").exists()
    assert [path.read_bytes() for path in (design, report)] == before
    for path in (design, report):
        metadata = json.loads(METADATA_RE.findall(path.read_text())[0])
        assert set(metadata) == {
            "module", "config", "xiangshan_commit", "rtl_sha256",
            "generation_status", "template_version", "date",
        }


def test_metadata_missing_report_preserves_design(artifacts, command):
    """A missing report must fail before any design metadata is rewritten."""
    design, report = artifact_paths(artifacts, "Sbuffer")
    report.unlink()
    design.write_text(design.read_text().replace('"module": "Sbuffer"', '"module": "wrong"'))
    before = design.read_bytes()
    result = command._run("metadata", "Sbuffer")
    assert not result["ok"], result
    assert design.read_bytes() == before


@pytest.mark.parametrize(
    "args",
    [
        dict(action="clean", module="Sbuffer"),
        dict(action="render", module="Sbuffer"),
        dict(action="preflight", module="../x"),
        dict(action="preflight", module="Sbuffer", config="$(touch x)"),
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
    result = RTL2SpecCommand(workspace=str(tmp_path), write_dirs=[".cache"])._run(
        "preflight", "Sbuffer"
    )
    assert not result["ok"]
    assert "third_party/XiangShan" in result["stdout"]
    assert "Makefile" not in result["stdout"]


@pytest.mark.parametrize("dirty", [False, True])
def test_preflight_requires_a_clean_source(workspace, dirty):
    """The packaged preflight enforces clean source without an optional strict mode."""
    from rtl2spec.plugin import get_plugin

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
    command.un_write_dirs.append("evidence/Sbuffer/manifest.json")
    assert (
        command._run("evidence", "Sbuffer")["error_code"]
        == "WRITE_POLICY_DENIED"
    )
    command.un_write_dirs.pop()
    folder = workspace / "evidence/Sbuffer"
    folder.mkdir(parents=True)
    (folder / "manifest.json").symlink_to(tmp_path / "external.json")
    assert (
        command._run("evidence", "Sbuffer")["error_code"]
        == "PATH_OUTSIDE_WORKSPACE"
    )
    assert not (tmp_path / "external.json").exists()


def test_timeout_and_no_rtl_failure(command, workspace, monkeypatch):
    """Missing compiler output and process-tree timeouts cannot create valid evidence."""
    monkeypatch.setenv("RTL2SPEC_TEST_NO_RTL", "1")
    result = command._run("evidence", "Sbuffer")
    assert not result["ok"], result
    assert "did not produce Sbuffer.sv" in result["stderr"]
    monkeypatch.delenv("RTL2SPEC_TEST_NO_RTL")
    monkeypatch.setenv("RTL2SPEC_TEST_DELAY", "15")
    command.command_timeout = 2
    assert (
        command._run("evidence", "Sbuffer")["error_code"]
        == "COMMAND_TIMEOUT"
    )
    assert not (workspace / "evidence/Sbuffer/manifest.json").exists()


def test_checker_reads_current_state(artifacts):
    """Check and Complete share current validation and never regenerate missing artifacts."""
    checker = RTL2SpecArtifactsChecker("Sbuffer").set_workspace(
        str(artifacts)
    )
    assert checker.do_check()[0]
    (artifacts / "evidence/Sbuffer/ports.csv").write_text("")
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

    from rtl2spec.plugin import get_plugin

    project = Path(__file__).resolve().parents[1]
    if get_plugin().root == project / "src/rtl2spec":
        if enabled:
            # Exercise source discovery as it works before the distribution is installed.
            monkeypatch.setattr("ucagent.plugins._entry_points", lambda: [])
            loaded = load_plugin("rtl2spec", search_paths=[project])
        else:
            loaded = load_plugin(str(project))
    else:
        loaded = load_plugin("rtl2spec")
    selected = resolve_plugin_workflow(
        [loaded], "rtl2spec:design-document"
    )
    docs, skills = collect_plugin_resources([loaded], selected)
    monkeypatch.setenv("XIANGSHAN_CONFIG", "TestConfig")
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="Sbuffer",
        output="outputs/Sbuffer" if enabled else "rendered",
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
        plugin_workflow="rtl2spec:design-document",
        template_context_factory=selected[1].template_context_factory,
    )
    try:
        assert skills == []
        tool_names = {tool.name for tool in agent.test_tools}
        assert tool_names == set(agent.cfg.tools.selected_tools)
        assert {"RTL2SpecCommand", "Check", "Complete", "ReadTextFile"} <= tool_names
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
                    "evidence", "Sbuffer", config="TestConfig"
                )
                assert result["ok"], result
            elif index == 1:
                assert any(name.endswith("ports.csv") for name in stage.reference_files)
                for path in artifact_paths(workspace, "Sbuffer"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                assert not stage.do_check(is_complete=True)[0]
                draft(workspace)
                assert command._run(
                    "metadata", "Sbuffer", config="TestConfig"
                )["ok"]
            else:
                assert any(
                    name.endswith("Sbuffer_design_document_zh.md")
                    for name in stage.reference_files
                )
                assert command._run(
                    "lint", "Sbuffer", config="TestConfig"
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
    monkeypatch.setenv("RTL2SPEC_TEST_RC", "7")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    result = validate(workspace, "Sbuffer", "DefaultConfig", "evidence")
    assert result["ok"] and any("partial" in message for message in result["warnings"])


def test_cached_rtl_is_not_required_for_check(artifacts):
    """Deleting disposable RTL cache does not invalidate the persistent evidence copy."""
    import shutil

    shutil.rmtree(artifacts / ".cache/rtl")
    assert validate(artifacts, "Sbuffer", "DefaultConfig")["ok"]


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
    from rtl2spec.evidence import parse_ports

    if valid:
        assert parse_ports(text, "X")[0]["width"] == 8
    else:
        with pytest.raises(ValueError):
            parse_ports(text, "X")


def test_markdown_fences_are_checked_without_fixed_layout():
    """Alternative Markdown fence delimiters work; unfinished blocks fail."""
    from rtl2spec.documents import mermaid_sources

    assert mermaid_sources("~~~mermaid\nflowchart LR\n A --> B\n~~~\n") == [
        "flowchart LR\n A --> B\n"
    ]
    with pytest.raises(ValueError, match="unclosed"):
        mermaid_sources("```mermaid\nflowchart LR\n")


@pytest.mark.parametrize("config", ["DefaultConfig", "TestConfig"])
def test_resolved_workflow_parameters(monkeypatch, config):
    """The workflow resolves configuration without a document version field."""
    from rtl2spec.plugin import get_plugin
    from ucagent.util.config import load_yaml_with_env_vars

    monkeypatch.setenv("XIANGSHAN_CONFIG", config)
    cfg = load_yaml_with_env_vars(str(get_plugin().workflows[0].config_file))
    assert cfg["template"] is None
    assert cfg["template_overwrite"] == {"XS_CONFIG": config}
    for stage in cfg["stage"]:
        assert stage["checker"][0]["args"]["config"] == "{XS_CONFIG}"


def test_cached_status_cannot_be_upgraded_by_editing_logs(
    command, workspace, monkeypatch
):
    """Unsigned ancillary cache files cannot turn partial generation into success."""
    monkeypatch.setenv("RTL2SPEC_TEST_RC", "7")
    assert command._run("evidence", "Sbuffer")["ok"]
    folder = next((workspace / ".cache/rtl").iterdir())
    (folder / "generation.exit-code").write_text("0\n")
    (folder / "tool_versions.json").write_text('{"java": "fabricated"}')
    (workspace / "evidence/Sbuffer").rename(workspace / "archived-evidence")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    manifest = read_json(workspace / "evidence/Sbuffer/manifest.json")
    assert manifest["generation_status"] == "partial"
    assert manifest["tool_versions"]["java"] != "fabricated"
    assert (workspace / ".cache/compiler-calls").read_text() == "1"


@pytest.mark.parametrize("phase", ["draft", "final"])
@pytest.mark.parametrize("defect", ["heading", "table"])
def test_stage_gates_template_structure(artifacts, phase, defect):
    """Real stage Check/Complete rejects structure errors even when evidence and metadata match."""
    path = artifact_paths(artifacts, "Sbuffer")[0]
    text = path.read_text(encoding="utf-8")
    if defect == "heading":
        text = text.replace("### 文档摘要", "### 自定义标题")
    else:
        text = text.replace(
            "| 参数 | 取值 |\n| --- | --- |\n| 数据宽度 | 8 位，无可配置参数 |", ""
        )
    path.write_text(text, encoding="utf-8")
    checker = RTL2SpecArtifactsChecker(
        "Sbuffer", phase=phase
    ).set_workspace(str(artifacts))
    for complete in (False, True):
        passed, result = checker.do_check(is_complete=complete)
        assert not passed, result
        assert result["artifact"].endswith("_design_document_zh.md")
        assert "Guide_Doc/chip_design_document_template_zh.md" in result["next_action"]
