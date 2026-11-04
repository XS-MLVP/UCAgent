"""Regress source/RTL evidence, flexible writing, packaged execution and stage lifecycle."""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import RTL, draft, complete_review
from rtl2spec.checkers import RTL2SpecArtifactsChecker, RTL2SpecGenericArtifactsChecker
from rtl2spec.evidence import read_json
from rtl2spec.documents import METADATA_RE, artifact_paths
from rtl2spec.tools import RTL2SpecCommand
from rtl2spec.validation import validate


def prepare_related_source(artifacts, command):
    """Commit a fixture helper module and regenerate evidence at that source baseline."""
    source = artifacts / "third_party/XiangShan/src/main/scala/Helper.scala"
    source.write_text("class Helper\n")
    subprocess.run(
        ["git", "-C", str(artifacts / "third_party/XiangShan"), "add", "src/main/scala/Helper.scala"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git", "-C", str(artifacts / "third_party/XiangShan"),
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-qm", "Add related helper",
        ],
        check=True,
        capture_output=True,
    )
    archive = artifacts / "related-archive"
    archive.mkdir()
    (artifacts / "outputs").rename(archive / "outputs")
    assert command._run("evidence", "Sbuffer")["ok"]
    draft(artifacts)
    assert command._run("metadata", "Sbuffer")["ok"]
    return source


def test_checker_reports_non_utf8_manifest_without_crashing(tmp_path):
    """A damaged manifest must become a structured checker failure during init."""
    evidence = tmp_path / "outputs/evidence"
    evidence.mkdir(parents=True)
    (evidence / "manifest.json").write_bytes(b"{\xff")
    checker = RTL2SpecArtifactsChecker(
        module="Block", config="Generic", phase="review", output_dir="outputs"
    )
    checker.stage = None
    checker.set_workspace(str(tmp_path)).on_init()
    ok, result = checker.do_check()
    assert not ok
    assert result["error_code"] == "SPEC_ARTIFACT_INVALID"
    assert "manifest.json" in result["artifact"]


@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("damage", ["encoding", "json", "related_path", "manifest_link", "output_link"])
def test_checker_recovers_after_input_repair(artifacts, tmp_path, generic, damage):
    """The same checker must reject current damage and accept restored signed artifacts."""
    root = artifacts
    checker_type = RTL2SpecArtifactsChecker
    if generic:
        from rtl2spec.generic_evidence import generate_generic
        from rtl2spec.documents import update_metadata

        root = tmp_path / "generic"
        source = root / "inputs/Sbuffer"
        source.mkdir(parents=True)
        (source / "Sbuffer.sv").write_text(RTL)
        generate_generic(root, "Sbuffer", "DefaultConfig")
        draft(root)
        update_metadata(root, "Sbuffer", "DefaultConfig", generic=True)
        complete_review(root, generic=True)
        checker_type = RTL2SpecGenericArtifactsChecker
    manifest = root / "outputs/evidence/manifest.json"
    original = manifest.read_bytes()
    if damage == "encoding":
        manifest.write_bytes(b"{\xff")
    elif damage == "json":
        manifest.write_text("{")
    elif damage == "related_path":
        value = json.loads(original)
        value["related_sources"] = [{"path": "../../outside.sv"}]
        manifest.write_text(json.dumps(value))
    elif damage == "manifest_link":
        external = tmp_path / "external.json"
        external.write_bytes(original)
        manifest.unlink()
        manifest.symlink_to(external)
    else:
        (root / "outputs").rename(tmp_path / "saved-outputs")
        (root / "outputs").symlink_to(tmp_path / "saved-outputs", target_is_directory=True)
    checker = checker_type(module="Sbuffer", phase="review")
    checker.set_workspace(str(root)).on_init()
    ok, result = checker.do_check()
    assert not ok and result["error_code"] == "SPEC_ARTIFACT_INVALID", result
    if damage == "manifest_link":
        manifest.unlink()
    elif damage == "output_link":
        (root / "outputs").unlink()
        (tmp_path / "saved-outputs").rename(root / "outputs")
    manifest.write_bytes(original)
    before = {p: p.read_bytes() for p in (root / "outputs").rglob("*") if p.is_file()}
    for complete in (False, True):
        ok, result = checker.do_check(is_complete=complete)
        assert ok, result
    assert {p: p.read_bytes() for p in before} == before


def test_new_generation_requires_clean_output_directories(artifacts, command):
    """A second generation run stops before touching existing documents or evidence."""
    assert not (artifacts / "src").exists()
    assert not (artifacts / "Makefile").exists()
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    before = (artifacts / "outputs/evidence/manifest.json").read_bytes()
    result = command._run("evidence", "Sbuffer")
    assert result["error_code"] == "OUTPUT_DIRECTORY_NOT_CLEAN", result
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    assert (artifacts / "outputs/evidence/manifest.json").read_bytes() == before


def test_user_archival_allows_regeneration_with_verified_cache(artifacts, command):
    """After user archival, reuse attested RTL but regenerate any corrupted cache."""
    archive = artifacts / "archive"
    archive.mkdir()
    (artifacts / "outputs").rename(archive / "outputs")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"
    draft(artifacts)
    for action in ("metadata", "validate"):
        result = command._run(action, "Sbuffer")
        assert result["ok"], result
    (artifacts / "outputs").rename(archive / "second-outputs")
    cached_rtl = next((artifacts / ".cache/rtl").glob("*/split/Sbuffer.sv"))
    cached_rtl.write_text(cached_rtl.read_text() + "\n// Unattested change\n")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    assert (artifacts / ".cache/compiler-calls").read_text() == "2"
    assert (archive / "outputs/Sbuffer_design_document_zh.md").is_file()


def test_new_output_directory_preserves_previous_run(artifacts, command):
    """Evidence, related sources and metadata use the selected run without touching the old one."""
    original = {
        path: path.read_bytes()
        for path in (artifacts / "outputs").rglob("*") if path.is_file()
    }
    output_dir = "runs/second output"
    command.output_dir = output_dir
    command.write_dirs.append(output_dir)
    assert command._run("evidence", "Sbuffer")["ok"]
    result = command._run("related_sources", "Sbuffer", related_modules=["TestConfig"])
    assert result["ok"], result
    draft(artifacts, output_dir)
    for action in ("metadata", "validate"):
        result = command._run(action, "Sbuffer")
        assert result["ok"], result
    manifest = read_json(artifacts / output_dir / "evidence/manifest.json")
    assert manifest["related_sources"][0]["module"] == "TestConfig"
    assert all(path.read_bytes() == data for path, data in original.items())
    command.un_write_dirs.append(f"{output_dir}/evidence/manifest.json")
    result = command._run("related_sources", "Sbuffer", related_modules=["TestConfig"])
    assert result["error_code"] == "WRITE_POLICY_DENIED"


def test_related_sources_are_signed_and_reported(artifacts, command):
    """Related Scala source is recorded with a stable location/hash and surfaced in the report."""
    source = prepare_related_source(artifacts, command)
    result = command._run(
        "related_sources", "Sbuffer", related_modules=["Helper"]
    )
    assert result["ok"], result
    manifest = read_json(artifacts / "outputs/evidence/manifest.json")
    record = manifest["related_sources"][0]
    assert record["evidence_id"] == "E-REL-HELPER"
    assert record["path"] == "third_party/XiangShan/src/main/scala/Helper.scala"
    assert record["line"] == 1
    assert len(record["sha256"]) == 64
    assert command._run("metadata", "Sbuffer")["ok"]
    report = (artifacts / "outputs/Sbuffer_document_quality_review.md").read_text()
    assert "E-REL-HELPER" in report and "Helper.scala:1" in report


def test_related_source_change_invalidates_evidence(artifacts, command):
    """A recorded related source cannot silently change after evidence capture."""
    source = prepare_related_source(artifacts, command)
    assert command._run("related_sources", "Sbuffer", related_modules=["Helper"])["ok"]
    source.write_text("class Helper\n// changed\n")
    result = command._run("lint", "Sbuffer")
    assert not result["ok"], result
    output = result["stderr"] + result["stdout"]
    assert "source identity changed" in output or "related source" in output


def test_related_source_can_be_context_only(artifacts, command):
    """A read related source may remain report-only when no final claim depends on it."""
    prepare_related_source(artifacts, command)
    assert command._run("related_sources", "Sbuffer", related_modules=["Helper"])["ok"]
    assert command._run("metadata", "Sbuffer")["ok"]
    complete_review(artifacts)
    result = command._run("lint", "Sbuffer")
    assert result["ok"], result


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
        "comments",
        "unclosed_mermaid",
    ],
)
def test_invalid_artifacts_fail_with_diagnostics(artifacts, target):
    """Material contradictions and missing evidence cannot be hidden by consistent prose."""
    root = artifacts
    design = artifact_paths(root, "Sbuffer")[0]
    evidence = root / "outputs/evidence"
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
                    "| 使用模板版本 | v6.0.0 |", "| 使用模板版本 | v2.0.0 |"
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
            design.read_text().replace(
                "| `IO-INPUT-01` | `input.data` | 数据 | `outputs/evidence/Sbuffer.sv:5` | `I/8` |",
                "| `IO-INPUT-01` | `input.data` | 数据 | `outputs/evidence/Sbuffer.sv:5` | `I/32` |",
            )
        )
    elif target == "comments":
        design.write_text(design.read_text() + "\n<!-- generator note -->\n")
    elif target == "unclosed_mermaid":
        design.write_text(
            design.read_text() + "\n```mermaid\nflowchart LR\n A --> B\n"
        )
    result = validate(root, "Sbuffer", config)
    assert not result["ok"], result
    assert result["artifact"] and result["next_action"] and result["observed"]


def test_fabricated_documents_without_tool_evidence_fail(tmp_path):
    """Mutually consistent fabricated documents cannot replace actual tool evidence."""
    folder = tmp_path / "outputs/evidence"
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
    assert not (artifacts / "outputs/VERSION_HISTORY.md").exists()
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
    command.un_write_dirs.append("outputs/evidence/manifest.json")
    assert (
        command._run("evidence", "Sbuffer")["error_code"]
        == "WRITE_POLICY_DENIED"
    )
    command.un_write_dirs.pop()
    folder = workspace / "outputs/evidence"
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
    assert not (workspace / "outputs/evidence/manifest.json").exists()


def test_checker_reads_current_state(artifacts):
    """Check and Complete share current validation and never regenerate missing artifacts."""
    checker = RTL2SpecArtifactsChecker("Sbuffer").set_workspace(
        str(artifacts)
    )
    assert checker.do_check()[0]
    (artifacts / "outputs/evidence/ports.csv").write_text("")
    assert not checker.do_check(is_complete=True)[0]
    assert (artifacts / ".cache/compiler-calls").read_text() == "1"


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("workflow", ["xiangshan", "generic"])
@pytest.mark.parametrize("output_dir", ["outputs", "unity_test", "runs/custom output"])
def test_fresh_agent_stages(workspace, monkeypatch, enabled, workflow, output_dir):
    """Both workflows complete in the selected directory with Skills enabled or absent."""
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
    workflow_id = f"rtl2spec:{workflow}-design-document"
    selected = resolve_plugin_workflow([loaded], workflow_id)
    docs, skills = collect_plugin_resources([loaded], selected)
    monkeypatch.setenv("XIANGSHAN_CONFIG", "TestConfig")
    monkeypatch.setenv("RTL2SPEC_CONFIG", "TestConfig")
    if workflow == "generic":
        inputs = workspace / "inputs/Sbuffer"
        inputs.mkdir(parents=True)
        (inputs / "Sbuffer.sv").write_text(RTL)
    action_prefix = "generic_" if workflow == "generic" else ""
    agent = VerifyAgent(
        workspace=str(workspace),
        dut_name="Sbuffer",
        output=output_dir,
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
        plugin_workflow=workflow_id,
        template_context_factory=selected[1].template_context_factory,
    )
    try:
        command = next(tool for tool in agent.test_tools if tool.name == "RTL2SpecCommand")
        assert command.output_dir == output_dir
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
            assert stage.reference_files
            assert len(agent.stage_manager.stages) == 4
            stage.need_pass_llm_suggestion = False
            if index == 1:
                assert f"{output_dir}/evidence/manifest.json" in stage.reference_files
                assert f"{output_dir}/evidence/ports.md" in stage.reference_files
            for name in stage.reference_files:
                agent.tool_read_text.invoke({"path": name})
            if index == 0:
                assert not stage.do_check(is_complete=True)[0]
                result = command._run(
                    f"{action_prefix}evidence", "Sbuffer", config="TestConfig"
                )
                assert result["ok"], result
                assert command._run(f"{action_prefix}ports", "Sbuffer", config="TestConfig")["ok"]
            elif index == 1:
                assert any(name.endswith("ports.md") for name in stage.reference_files)
                assert any(name.endswith("manifest.json") for name in stage.reference_files)
                for path in artifact_paths(workspace, "Sbuffer", output_dir):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                assert not stage.do_check(is_complete=True)[0]
                draft(workspace, output_dir)
                assert command._run(
                    f"{action_prefix}metadata", "Sbuffer", config="TestConfig"
                )["ok"]
            elif index == 2:
                assert any(name.endswith("Sbuffer_design_document_zh.md") for name in stage.reference_files)
                assert not stage.do_check(is_complete=True)[0]
                complete_review(workspace, "Sbuffer", "TestConfig", generic=workflow == "generic", output_dir=output_dir)
            else:
                assert not stage.do_check(is_complete=True)[0]
                result = command._run(f"{action_prefix}finalize", "Sbuffer", config="TestConfig")
                assert result["ok"], result
            passed, result = stage.do_check(is_complete=True)
            assert passed, result
            stage.meta_set_journal(
                "Verified synthetic fixture artifacts for this test stage."
            )
            result = agent.stage_manager.complete(timeout=30)
            assert result["complete"], result
        assert agent.stage_manager.all_completed
        timings = [json.loads(line) for line in (workspace / output_dir / "logs/stages.jsonl").read_text().splitlines()]
        assert [item["phase"] for item in timings] == ["evidence", "draft", "review", "final"]
        assert all(item["elapsed_seconds"] >= 0 and item["completed_at"] >= item["started_at"] for item in timings)
        for path in artifact_paths(workspace, "Sbuffer", output_dir):
            assert path.is_file()
        assert (workspace / output_dir / "evidence/manifest.json").is_file()
        assert not (workspace / "reports").exists()
        assert not (workspace / "evidence").exists()
        if output_dir != "outputs":
            assert not (workspace / "outputs").exists()
    finally:
        agent.exit()


def test_partial_generation_is_explicit(command, workspace, monkeypatch):
    """A target RTL file produced before downstream failure is accepted with a warning."""
    monkeypatch.setenv("RTL2SPEC_TEST_RC", "7")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    result = validate(workspace, "Sbuffer", "DefaultConfig", "evidence")
    assert result["ok"] and any("partial" in message for message in result["warnings"])


@pytest.mark.parametrize("open_state", [None, "Closed", "Open", "Deferred"])
def test_partial_finalization_enforces_the_final_stage_contract(command, workspace, monkeypatch, open_state):
    """Finalize must enforce generation limitations before publishing a successful receipt."""
    from rtl2spec.contracts import contract_rows
    from rtl2spec.review import finalize

    monkeypatch.setenv("RTL2SPEC_TEST_RC", "7")
    assert command._run("evidence", "Sbuffer")["ok"]
    draft(workspace)
    design, report = artifact_paths(workspace, "Sbuffer")
    if open_state is not None:
        text = design.read_text()
        row = contract_rows(text)["open"][0]
        lines = text.splitlines()
        lines.insert(row["line"], f"| `OPEN-GENERATION-PARTIAL` | Downstream generation failed | Only captured target RTL is covered | Repair the downstream build and regenerate | {open_state} |")
        design.write_text("\n".join(lines) + "\n")
    report.write_text(report.read_text() + "\nDownstream generation failed; conclusions cover only the captured target RTL.\n")
    assert command._run("metadata", "Sbuffer")["ok"]
    complete_review(workspace)
    before = report.read_bytes()
    result = finalize(workspace, "Sbuffer", "DefaultConfig")
    if open_state in {"Open", "Deferred"}:
        assert result["ok"], result
        assert validate(workspace, "Sbuffer", "DefaultConfig", "final")["ok"]
    else:
        assert not result["ok"], result
        assert any(issue.get("rule") == "PARTIAL_SIGNOFF" for issue in result["observed"])
        assert not (workspace / "outputs/validation.json").exists()
        assert report.read_bytes() == before


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
    (workspace / "outputs").rename(workspace / "archived-output")
    result = command._run("evidence", "Sbuffer")
    assert result["ok"], result
    manifest = read_json(workspace / "outputs/evidence/manifest.json")
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
        text = text.replace("## 文档摘要", "## 自定义标题")
    else:
        text = text.replace(
            "| 参数 ID | 参数 / 派生常量 | 配置值 | 约束或裁剪 | 证据 |\n| --- | --- | --- | --- | --- |\n| `PARAM-01` | 数据宽度 | `8` | 声明常量，不是可覆盖参数 | `E-RTL-01` |", ""
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
