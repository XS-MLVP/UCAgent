"""Focused DesignWithPPA workflow tests: rtl backend."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    _chisel_config,
    _config,
    _rtl_rows,
    _write_json,
    _write_workspace_python_dut,
    _write_yaml,
)

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import pytest
from design_with_ppa.checkers import (  # noqa: E402
    DesignAllPassBatchTestsChecker,
    DesignArchitectureChecker,
    DesignCoverageGroupBatchChecker,
    DesignCoverageStructureChecker,
    DesignDocumentationSyncChecker,
    DesignFinalDeliveryChecker,
    DesignFunctionalContractChecker,
    DesignInputContractChecker,
    DesignDutApiChecker,
    DesignLabelStructureChecker,
    DesignLineMapReferenceChecker,
    DesignMarkdownFileFormatChecker,
    DesignObservationContractChecker,
    DesignObservationInstrumentationChecker,
    DesignRandomTestCasesChecker,
    DesignRefineTestCasesChecker,
    DesignLabelStructureRefineChecker,
    DesignSpecLineMapBatchChecker,
    DesignTestTemplateChecker,
    DesignPythonAllPassChecker,
    PPABaseCharacterizationChecker,
    PPABestVersionChecker,
    PPACandidateOptimizationChecker,
    PPAIterationChecker,
    PPAResultArtifactsChecker,
    PerformanceArtifactChecker,
    PerformanceContractChecker,
    PerformanceTestContractChecker,
    PythonAdapterContractChecker,
    PythonEnvFixtureContractChecker,
    PythonExecutableSpecChecker,
    PythonReferenceContractChecker,
    PythonReferenceRegressionChecker,
    RTLAllPassRegressionChecker,
    RTLBackendBuildChecker,
    RTLLineCoverageChecker,
    RTLSourceEvidenceChecker,
    _api_assertion_quality_violations,
    _actionable_checker_failure,
    _bounded_checker_value,
    _cleanup_transient_coverage_data,
    _coverage_fixture_lifecycle_violations,
    _hash_rows,
    _ppa_selection_score,
    _public_pytest_failure,
    _pytest_evidence,
    _rtl_regression_failure_evidence,
    _run_pytest,
    _run_workflow_ppa,
    select_best_accepted_record,
)
from design_with_ppa.contracts import sha256_file
from design_with_ppa.rtl import (  # noqa: E402
    CHISEL_MILL_VERSION,
    CHISEL_SCALA_VERSION,
    CHISEL_VERSION,
    ChiselLanguageBackend,
    PreparedRTL,
    RTLLanguageBackend,
    RTLLanguageError,
    RTLPreparationRequest,
    RTLSourceTemplate,
    RTLSourceValidation,
    available_rtl_languages,
    build_rtl_template_context,
    discover_rtl_libraries,
    discover_rtl_sources,
    _workspace_python_dut_root,
    register_rtl_language,
    resolve_rtl_config,
    unregister_rtl_language,
)
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)




def test_rtl_backend_checker_reports_synthesis_smoke_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backend builder must not run when synthesis rejects RTL or hierarchy."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module broken;\n", encoding="ascii")
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="syntax error"
        ),
    )
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "rtl_synthesis_failed"
    assert "syntax error" in result["observed"]["stderr_tail"]




def test_rtl_backend_synthesis_diagnostic_locates_simulation_only_verilog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Verilog parser failure identifies the authored non-synthesizable construct."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "`default_nettype none\nmodule dut;\n  real value;\nendmodule\n",
        encoding="ascii",
    )
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="unexpected TOK_REAL"
        ),
    )

    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_synthesis_failed"
    assert result["location"] == "output/rtl/dut.v:3"
    assert result["observed"]["tests_not_run"].startswith("RTL regression")
    assert result["observed"]["coverage_pipeline"][0]["step"] == "synthesis"
    assert result["observed"]["coverage_pipeline"][0]["status"] == "blocked"
    assert all(
        step["status"] == "not_run"
        for step in result["observed"]["coverage_pipeline"][1:]
    )
    assert result["observed"]["synthesis_hazards"] == [
        {
            "path": "output/rtl/dut.v",
            "line": 3,
            "construct": "real/realtime/time declaration",
            "guidance": (
                "Replace real-valued state or arithmetic with fixed-width integer datapaths, "
                "explicit scaling, and lookup/case thresholds derived from the architecture contract."
            ),
        }
    ]
    assert "fixed-width" in result["next_action"]




def test_rtl_backend_rejects_authored_literal_width_truncation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic constant truncation must be fixed before RTL regression."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut;\n  wire [17:0] value = 18'd262144;\nendmodule\n",
        encoding="ascii",
    )
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="",
            stderr=(
                f"{rtl}:2: Warning: Literal has a width of 18 bit, but value requires 19 bit."
            ),
        ),
    )

    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_synthesis_width_warning"
    assert result["location"] == "output/rtl/dut.v:2"
    assert result["observed"]["width_warnings"][0]["literal_width"] == 18
    assert result["observed"]["width_warnings"][0]["required_width"] == 19
    assert "signedness" in result["next_action"]




def test_rtl_backend_checker_redacts_builder_name_from_fallback_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected builder errors must preserve diagnostics without naming the tool."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)
    calls = 0

    def fail_builder(command, **kwargs):
        """Pass synthesis, then raise an error containing the private executable name."""

        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise OSError("picker executable disappeared")

    monkeypatch.setattr("design_with_ppa.checkers.runtime.subprocess.run", fail_builder)
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_validation_prepare_invalid"
    assert "picker" not in result["error"].lower()
    assert "RTL validation" in result["error"]




def test_rtl_backend_rejects_incomplete_export_without_leaking_private_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero exit status cannot turn an incomplete generated tree into success."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)
    private_paths: list[Path] = []

    def incomplete_export(command, **kwargs):
        """Return success while creating only the builder's nested source tree."""

        del kwargs
        if command[0] == "yosys":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["picker", "--version"]:
            return subprocess.CompletedProcess(command, 0, "builder 1.0", "")
        assert command[:2] == ["picker", "export"]
        target = Path(command[-1])
        private_paths.append(target)
        nested = target / "python"
        nested.mkdir(parents=True)
        (nested / "dut.py").write_text(
            "class DUTdut:\n    pass\n", encoding="ascii"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime.subprocess.run", incomplete_export
    )
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_validation_prepare_invalid"
    serialized = json.dumps(result)
    assert "python/dut.py" not in serialized
    assert "Python-DUT" not in serialized
    assert "picker" not in serialized.lower()
    assert all(str(path) not in serialized for path in private_paths)




@pytest.mark.parametrize("target_inside_workspace", [False, True])
def test_rtl_backend_rejects_runtime_symlink_ancestors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_inside_workspace: bool,
) -> None:
    """Generated Python must never traverse a symlink, regardless of its target."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n"
        "  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    real_target = (
        tmp_path / "inside-cache"
        if target_inside_workspace
        else tmp_path.parent / f"{tmp_path.name}-outside-cache"
    )
    real_target.mkdir()
    linked_root = tmp_path / "linked-runtime"
    linked_root.symlink_to(real_target, target_is_directory=True)
    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime._workspace_python_dut_root",
        lambda workspace: linked_root / "python-dut",
    )
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is False
    assert result["error_code"] == "rtl_validation_prepare_invalid"
    assert "symbolic links" in result["error"]




def test_chisel_backend_contract_template_and_advisory_guide() -> None:
    """Chisel must expose only its pinned authored-language source contract."""

    cfg = _chisel_config()
    resolved, backend = resolve_rtl_config(cfg)
    context = build_rtl_template_context(
        cfg, {"DUT": "dut", "OUT": "output", "WORKSPACE": "/workspace"}
    )
    guide = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "Guide_Doc"
        / "coding_standard_chisel.md"
    ).read_text(encoding="utf-8")

    assert isinstance(backend, ChiselLanguageBackend)
    assert resolved.language_options == {
        "chisel_version": "7.15.0",
        "scala_version": "2.13.18",
        "mill_version": "0.4.2",
    }
    assert available_rtl_languages() == ("chisel", "verilog")
    assert context["RTL_SOURCE_FILE"] == "dut.scala"
    assert context["RTL_SOURCE_GLOB"] == "output/rtl/*.scala"
    assert context["RTL_SOURCE_TEMPLATE"] == "chisel-7"
    assert context["RTL_CODING_GUIDE"] == (
        "Guide_Doc/coding_standard_chisel.md"
    )
    assert context["RTL_SOURCE_VALIDATION_CHECKER"] == (
        "RTLSourceEvidenceChecker"
    )
    assert context["RTL_SOURCE_VALIDATION_REPORT"] == (
        "output/dut_chisel_source_validation.md"
    )
    assert context["RTL_SOURCE_VALIDATION_GUIDE"] == (
        "Guide_Doc/source_validation_chisel.md"
    )
    assert context["RTL_SOURCE_VALIDATION_GUIDE_FILE"] == (
        "source_validation_chisel.md"
    )
    assert "class dut extends RawModule" in context["RTL_SOURCE_TEMPLATE_BODY"]
    assert "module dut" not in context["RTL_SOURCE_TEMPLATE_BODY"]
    for required in (
        "Module: dut",
        "Purpose:",
        "Interface:",
        "Parameters:",
        "Timing/reset:",
        "Numeric behavior:",
        "Core datapath:",
        "input_i",
        "output_o",
    ):
        assert required in context["RTL_SOURCE_TEMPLATE_BODY"]
    for required in (
        "Chisel `7.15.0`",
        "Scala `2.13.18`",
        "MuxLookup(key, default)(Seq(...))",
        "RawModule",
        "RegInit",
        "Ready/Valid",
        "BlackBox",
        "RTL-GUIDE-DEVIATION",
        "完整规范 Chisel 示例",
        "## 注释结构（建议）",
        "Module: Example",
        "Interface: describe every IO",
        "Core datapath: explain",
    ):
        assert required in guide
    assert "建议规范" in guide
    assert "Picker" not in guide
    assert "生成后的 Verilog" not in guide
    assert "Module: StreamAdd" in guide
    assert "Core handshake datapath" in guide




@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chisel_version", "7.14.0"),
        ("scala_version", "2.13.16"),
        ("mill_version", "0.4.1"),
    ],
)
def test_chisel_backend_rejects_unpinned_versions(field: str, value: str) -> None:
    """Every Chisel dependency version must match the tested tuple exactly."""

    cfg = _chisel_config()
    cfg.un_freeze()
    options = cfg.get_value("design_with_ppa.rtl.language_options").as_dict()
    options[field] = value
    cfg.set_value("design_with_ppa.rtl.language_options", options)

    with pytest.raises(RTLLanguageError, match=field):
        resolve_rtl_config(cfg)




def test_chisel_dependency_is_checked_only_during_chisel_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default Verilog remains usable when the Chisel-only toolchain is absent."""

    verilog, verilog_backend = resolve_rtl_config(_config())
    assert verilog.language == "verilog"
    assert verilog_backend.prepare(
        RTLPreparationRequest(
            workspace=tmp_path,
            language="verilog",
            top_module="dut",
            source_files=(),
            library_files=(),
            build_dir=tmp_path / "unused",
            language_options=verilog.language_options,
            python_dut_options={},
            timeout=10,
        )
    ).metadata["translation"] == "identity"

    monkeypatch.setattr(
        "design_with_ppa.rtl.shutil.which", lambda command: None
    )
    chisel_backend = ChiselLanguageBackend()
    build_dir = tmp_path / "private"
    build_dir.mkdir()
    with pytest.raises(RTLLanguageError, match="Mill 0.4.2"):
        chisel_backend.prepare(
            RTLPreparationRequest(
                workspace=tmp_path,
                language="chisel",
                top_module="dut",
                source_files=(),
                library_files=(),
                build_dir=build_dir,
                language_options=chisel_backend.normalize_options({}),
                python_dut_options={},
                timeout=10,
            )
        )




def test_chisel_prepare_builds_privately_and_redacts_source_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter must keep project details private and map errors to authored Scala."""

    workspace = tmp_path / "workspace"
    source = workspace / "output" / "rtl" / "dut.scala"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import chisel3._\nclass dut extends RawModule { val y = IO(Output(Bool())); y := false.B }\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "private"
    build_dir.mkdir()
    java_home = tmp_path / "jdk"
    (java_home / "bin").mkdir(parents=True)
    backend = ChiselLanguageBackend()
    monkeypatch.setattr(
        "design_with_ppa.rtl.shutil.which", lambda name: f"/tools/{name}"
    )
    monkeypatch.setattr(
        backend, "_resolve_java_home", lambda timeout: (java_home, 17)
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        """Return the pinned version, then emulate one deterministic elaboration."""

        calls.append(command)
        if command[-1] == "version":
            return subprocess.CompletedProcess(command, 0, "0.4.2\n", "")
        assert (build_dir / "build.sc").is_file()
        build_text = (build_dir / "build.sc").read_text(encoding="utf-8")
        assert "org.chipsalliance::chisel:7.15.0" in build_text
        assert "org.chipsalliance:::chisel-plugin:7.15.0" in build_text
        assert (
            build_dir / "design" / "src" / "authored" / "00000-dut.scala"
        ).is_file()
        generated = Path(command[-1])
        generated.write_text(
            "module dut(output y); assign y = 1'b0; endmodule\n",
            encoding="ascii",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("design_with_ppa.rtl.subprocess.run", fake_run)
    request = RTLPreparationRequest(
        workspace=workspace,
        language="chisel",
        top_module="dut",
        source_files=(source.resolve(),),
        library_files=(),
        build_dir=build_dir,
        language_options=backend.normalize_options({}),
        python_dut_options={},
        timeout=30,
    )
    prepared = backend.prepare(request)

    assert prepared.analysis_verilog_files == (build_dir / "dut.v",)
    assert prepared.python_dut_files == prepared.analysis_verilog_files
    assert prepared.metadata["chisel_version"] == "7.15.0"
    assert calls[0][-2:] == ["-i", "version"]
    assert calls[1][2:5] == [
        "-i",
        "design.runMain",
        "ucagent.internal.UCAgentElaborate",
    ]
    assert not list(workspace.rglob("build.sc"))
    assert not list(workspace.rglob("*.v"))

    failing_dir = tmp_path / "private-failure"
    failing_dir.mkdir()
    private_source = (
        failing_dir / "design" / "src" / "authored" / "00000-dut.scala"
    )

    def fail_run(command, **kwargs):
        """Return a compiler error containing a private copied-source path."""

        if command[-1] == "version":
            return subprocess.CompletedProcess(command, 0, "0.4.2\n", "")
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            f"{private_source}:7: error: not found: value broken\n",
        )

    monkeypatch.setattr("design_with_ppa.rtl.subprocess.run", fail_run)
    failed_request = RTLPreparationRequest(
        workspace=workspace,
        language="chisel",
        top_module="dut",
        source_files=(source.resolve(),),
        library_files=(),
        build_dir=failing_dir,
        language_options=backend.normalize_options({}),
        python_dut_options={},
        timeout=30,
    )
    with pytest.raises(RTLLanguageError) as caught:
        backend.prepare(failed_request)
    message = str(caught.value)
    assert "output/rtl/dut.scala:7: error" in message
    assert str(failing_dir) not in message
    assert "build.sc" not in message
    assert "generated.v" not in message
    assert "design.runMain" not in message




@pytest.mark.skipif(
    shutil.which("mill") is None or shutil.which("yosys") is None,
    reason="Mill and Yosys are required for real Chisel elaboration",
)
def test_real_chisel_7_elaboration_with_mill_0_4(tmp_path: Path) -> None:
    """The pinned real toolchain must elaborate the canonical guide example."""

    workspace = tmp_path / "workspace"
    source = workspace / "output" / "rtl" / "StreamAdd.scala"
    source.parent.mkdir(parents=True)
    guide = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "Guide_Doc"
        / "coding_standard_chisel.md"
    ).read_text(encoding="utf-8")
    canonical = re.search(
        r"## 完整规范 Chisel 示例\n\n```scala\n(.*?)\n```", guide, re.DOTALL
    )
    assert canonical is not None
    source.write_text(
        "import shared.LibraryContract\n" + canonical.group(1) + "\n",
        encoding="utf-8",
    )
    library = tmp_path / "shared-library" / "LibraryContract.scala"
    library.parent.mkdir()
    library.write_text(
        "package shared\nobject LibraryContract { val revision = 1 }\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "private"
    build_dir.mkdir()
    backend = ChiselLanguageBackend()
    prepared = backend.prepare(
        RTLPreparationRequest(
            workspace=workspace,
            language="chisel",
            top_module="StreamAdd",
            source_files=(source.resolve(),),
            library_files=(library.resolve(),),
            build_dir=build_dir,
            language_options=backend.normalize_options({}),
            python_dut_options={},
            timeout=300,
        )
    )
    generated = prepared.analysis_verilog_files[0]
    completed = subprocess.run(
        [
            shutil.which("yosys"),
            "-q",
            "-p",
            f'read_verilog "{generated}"; hierarchy -check -top StreamAdd; proc; check',
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "module StreamAdd(" in generated.read_text(encoding="utf-8")
    metadata = dict(prepared.metadata)
    java_major_version = metadata.pop("java_major_version")
    assert metadata == {
        "translation": "chisel-elaboration",
        "chisel_version": "7.15.0",
        "scala_version": "2.13.18",
        "mill_version": "0.4.2",
        "library_source_count": 1,
    }
    assert java_major_version >= 17




@pytest.mark.skipif(
    any(shutil.which(command) is None for command in ("mill", "yosys", "picker")),
    reason="Mill, Yosys, and the RTL backend builder are required",
)
def test_real_chisel_rtl_backend_build_is_automatic_and_private(
    tmp_path: Path,
) -> None:
    """Check must turn current Chisel into a private runnable DUT without LLM work."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n"
        "  rtl_language: chisel\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    source = tmp_path / "output" / "rtl" / "dut.scala"
    source.parent.mkdir(parents=True)
    source.write_text(
        """/** Private backend integration smoke DUT. */
import chisel3._

class dut extends RawModule {
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  val y = IO(Output(Bool()))
  y := a ^ b
}
""",
        encoding="utf-8",
    )
    (tmp_path / "output" / "tests").mkdir(parents=True)
    manifest_relative = ".ucagent/design_with_ppa/rtl_backend_manifest.json"
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=manifest_relative,
        timeout=300,
        cfg=_chisel_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert result == {
        "message": "RTL validation is ready for the current source hashes.",
        "top_module": "dut",
        "rtl_language": "chisel",
        "source_files": ["output/rtl/dut.scala"],
        "library_source_count": 0,
    }
    assert not list((tmp_path / "output").rglob("*.v"))
    assert not list((tmp_path / "output").rglob("build.sc"))
    manifest_text = (tmp_path / manifest_relative).read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["rtl_sources"] == [
        {"path": "output/rtl/dut.scala", "sha256": sha256_file(source)}
    ]
    assert manifest["prepared_content"]["analysis"]["file_count"] == 1
    assert manifest["generated_content"]["file_count"] > 0
    assert "picker" not in manifest_text.lower()
    assert "generated.v" not in manifest_text
    assert (_workspace_python_dut_root(tmp_path) / "dut" / "__init__.py").is_file()

    passed, result = checker.do_check()
    assert passed is True, result
    assert "already matches" in result["message"]




def test_chisel_source_validation_uses_only_authored_and_regression_evidence(
    tmp_path: Path,
) -> None:
    """Chisel evidence must never expose private implementation line coverage."""

    cfg = _chisel_config()
    source = tmp_path / "output" / "rtl" / "dut.scala"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import chisel3._\nclass dut extends RawModule { val y = IO(Output(Bool())); y := false.B }\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "output" / "tests" / "test_dut_functional.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_contract():\n    assert True\n", encoding="utf-8")
    rtl_config, backend = resolve_rtl_config(cfg)
    rtl_rows = _hash_rows(tmp_path, [source.resolve()])
    generated_content = _write_workspace_python_dut(
        tmp_path, "class DUT:\n    pass\n"
    )
    manifest_path = (
        tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend_manifest.json"
    )
    _write_json(
        manifest_path,
        {
            "schema_version": "1.4",
            "rtl_language": "chisel",
            "rtl_config": rtl_config.identity(),
            "rtl_sources": rtl_rows,
            "rtl_libraries": [],
            "synthesis_smoke": "pass",
            "python_dut_import": {"module": "dut", "class": "DUTdut"},
            "python_dut_builder": {
                "coverage": True,
                "waveform_format": "vcd",
            },
            "generated_content": generated_content,
        },
    )
    regression_path = tmp_path / "output" / "reports" / "dut_rtl_regression.json"
    _write_json(
        regression_path,
        {
            "backend": "rtl",
            "status": "pass",
            "rtl_libraries": [],
            "sources": _hash_rows(
                tmp_path,
                sorted([source.resolve(), test_file.resolve()], key=lambda path: path.as_posix()),
            ),
        },
    )
    checker = RTLSourceEvidenceChecker(
        test_dir="output/tests",
        coverage_analysis="output/dut_chisel_source_validation.md",
        coverage_ignore="output/tests/dut.ignore",
        rtl_manifest_file=(
            ".ucagent/design_with_ppa/rtl_backend_manifest.json"
        ),
        rtl_regression_file="output/reports/dut_rtl_regression.json",
        cfg=cfg,
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    assert result["source_files"] == ["output/rtl/dut.scala"]
    report = (tmp_path / result["report"]).read_text(encoding="utf-8")
    assert "Authored language: `Chisel`" in report
    assert "Verilog" not in report
    assert "Picker" not in report
    assert (tmp_path / "output" / "tests" / "dut.ignore").read_text() == ""

    source.write_text(source.read_text() + "\n// current source changed\n", encoding="utf-8")
    passed, result = checker.do_check()
    assert passed is False
    assert result["error_code"] == "rtl_source_evidence_invalid"
    assert "build receipt" in result["error"]




def test_rtl_library_paths_append_environment_and_bind_verilog_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Config and environment directories must form one ordered hashed source set."""

    local_library = tmp_path / "libraries" / "local"
    shared_a = tmp_path / "shared-a"
    shared_b = tmp_path / "shared-b"
    for directory in (local_library, shared_a, shared_b):
        directory.mkdir(parents=True)
    (local_library / "Helper.v").write_text(
        "module Helper(input a, output y); assign y = ~a; endmodule\n",
        encoding="ascii",
    )
    (local_library / "ignored.scala").write_text("object ignored\n", encoding="ascii")
    (shared_a / "SharedA.v").write_text("module SharedA; endmodule\n", encoding="ascii")
    (shared_b / "nested").mkdir()
    (shared_b / "nested" / "SharedB.v").write_text(
        "module SharedB; endmodule\n", encoding="ascii"
    )
    explicit = tmp_path / "config.yaml"
    _write_yaml(
        explicit,
        {"design_with_ppa": {"rtl": {"library_paths": ["libraries/local"]}}},
    )
    monkeypatch.setenv(
        "DESIGN_WITH_PPA_RTL_LIBRARY_PATHS",
        os.pathsep.join((str(shared_a), str(shared_b), str(shared_a))),
    )
    workflow = (
        PLUGIN_SOURCE / "design_with_ppa" / "workflows" / "unit-design-tdd.yaml"
    )
    cfg = get_config(
        str(explicit), [], str(tmp_path), workflow_config_file=str(workflow)
    )
    cfg.un_freeze()
    cfg._temp_cfg = {"DUT": "dut", "OUT": "output", "WORKSPACE": str(tmp_path)}
    cfg.update_template(cfg._temp_cfg)
    resolved, backend = resolve_rtl_config(cfg)
    library_files, library_rows = discover_rtl_libraries(
        tmp_path, resolved, backend
    )

    assert resolved.library_paths == (
        "libraries/local",
        str(shared_a),
        str(shared_b),
    )
    assert [path.name for path in library_files] == [
        "Helper.v",
        "SharedA.v",
        "SharedB.v",
    ]
    assert [row["library_index"] for row in library_rows] == [0, 1, 2]
    assert [row["path"] for row in library_rows] == [
        "Helper.v",
        "SharedA.v",
        "nested/SharedB.v",
    ]
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in library_rows)
    context = build_rtl_template_context(
        cfg, {"DUT": "dut", "OUT": "output", "WORKSPACE": str(tmp_path)}
    )
    assert json.loads(context["RTL_LIBRARY_PATHS"]) == list(resolved.library_paths)

    top = tmp_path / "output" / "rtl" / "dut.v"
    top.parent.mkdir(parents=True)
    top.write_text(
        "module dut(input a, output y); Helper helper(.a(a), .y(y)); endmodule\n",
        encoding="ascii",
    )
    authored = discover_rtl_sources(tmp_path, resolved, backend)
    prepared = backend.prepare(
        RTLPreparationRequest(
            workspace=tmp_path,
            language="verilog",
            top_module="dut",
            source_files=authored,
            library_files=library_files,
            build_dir=tmp_path / "unused",
            language_options=resolved.language_options,
            python_dut_options={},
            timeout=30,
        )
    )
    assert prepared.library_files == library_files
    assert set(prepared.analysis_verilog_files) == {*library_files, *authored}
    helper_hash = library_rows[0]["sha256"]
    (local_library / "Helper.v").write_text(
        "module Helper(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    _, changed_rows = discover_rtl_libraries(tmp_path, resolved, backend)
    assert changed_rows[0]["sha256"] != helper_hash




def test_rtl_library_discovery_rejects_missing_empty_and_overlapping_directories(
    tmp_path: Path,
) -> None:
    """Invalid library roots must fail before a downstream tool sees partial input."""

    cfg = _config()
    cfg.un_freeze()
    cfg.set_value("design_with_ppa.rtl.library_paths", ["missing-library"])
    resolved, backend = resolve_rtl_config(cfg)
    with pytest.raises(RTLLanguageError, match="not a readable directory"):
        discover_rtl_libraries(tmp_path, resolved, backend)

    empty = tmp_path / "empty-library"
    empty.mkdir()
    cfg.set_value("design_with_ppa.rtl.library_paths", [str(empty)])
    resolved, backend = resolve_rtl_config(cfg)
    with pytest.raises(RTLLanguageError, match="contains no Verilog sources"):
        discover_rtl_libraries(tmp_path, resolved, backend)

    shared = tmp_path / "shared-library"
    nested = shared / "nested"
    nested.mkdir(parents=True)
    (nested / "Shared.v").write_text("module Shared; endmodule\n", encoding="ascii")
    cfg.set_value(
        "design_with_ppa.rtl.library_paths", [str(shared), str(nested)]
    )
    resolved, backend = resolve_rtl_config(cfg)
    with pytest.raises(RTLLanguageError, match="overlap"):
        discover_rtl_libraries(tmp_path, resolved, backend)




@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("language", "unknown", "not registered"),
        ("source_glob", "../private/*.v", "workspace-relative"),
        ("source_glob", "dut/*.v", "below the resolved OUT"),
        ("source_template", "systemverilog", "requires source_template"),
        ("library_paths", "libraries", "must be a list"),
        ("library_path_append", [], "path-separated string"),
        ("language_options", {"standard": "systemverilog"}, "verilog-2005"),
        ("python_dut.interface", "manual", "must be 'automatic'"),
        ("python_dut.options", {"unsafe": True}, "does not accept"),
    ],
)
def test_rtl_language_config_rejects_invalid_current_contract(
    field: str, value: object, message: str
) -> None:
    """Language selection, templates, paths, and conversion options are strict."""

    cfg = _config()
    cfg.un_freeze()
    cfg.set_value(f"design_with_ppa.rtl.{field}", value)
    with pytest.raises(RTLLanguageError, match=re.escape(message)):
        resolve_rtl_config(cfg)




@pytest.mark.parametrize("target_inside_workspace", [False, True])
def test_rtl_source_discovery_rejects_symlink_directory(
    tmp_path: Path, target_inside_workspace: bool
) -> None:
    """Authored source discovery must reject every symbolic-link directory."""

    output = tmp_path / "output"
    output.mkdir()
    real_source_dir = (
        output / "real-rtl"
        if target_inside_workspace
        else tmp_path.parent / f"{tmp_path.name}-rtl"
    )
    real_source_dir.mkdir()
    (real_source_dir / "dut.v").write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    (output / "rtl").symlink_to(real_source_dir, target_is_directory=True)
    config, backend = resolve_rtl_config(_config())

    with pytest.raises(RTLLanguageError, match="symbolic link"):
        discover_rtl_sources(tmp_path, config, backend)




def test_language_backend_keeps_generated_verilog_ephemeral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future source language may translate privately without leaking paths."""

    class FakeChiselBackend(RTLLanguageBackend):
        """Translate one Scala fixture into a private analysis-only Verilog file."""

        name = "test-chisel"
        display_name = "Test Chisel"
        source_extensions = (".scala",)
        source_template = "test-chisel-module"

        def default_source_glob(self, output_dir: str) -> str:
            """Return the test language source pattern."""

            return f"{output_dir}/rtl/*.scala"

        def source_template_bundle(self, module_name: str) -> RTLSourceTemplate:
            """Return a Scala scaffold without any generated Verilog content."""

            return RTLSourceTemplate(
                filename=f"{module_name}.scala",
                content=(
                    "import chisel3._\n\n"
                    f"class {module_name} extends Module {{\n"
                    "  val io = IO(new Bundle {})\n"
                    "}\n"
                ),
                coding_guide="Guide_Doc/coding_standard_test_chisel.md",
            )

        def source_validation_bundle(
            self, module_name: str
        ) -> RTLSourceValidation:
            """Return the reusable generated-language source evidence gate."""

            return RTLSourceValidation(
                checker="RTLSourceEvidenceChecker",
                description="Test authored-source evidence",
                task="Call Check to validate the current authored sources.",
                guide="Guide_Doc/rtl_backend.md",
                report_filename=f"{module_name}_source_validation.md",
            )

        def normalize_options(self, options):
            """Accept only a deterministic test compiler version."""

            if options != {"compiler": "test-1"}:
                raise RTLLanguageError("test compiler option is invalid")
            return dict(options)

        def prepare(self, request: RTLPreparationRequest) -> PreparedRTL:
            """Write deterministic Verilog only inside the trusted build directory."""

            generated = request.build_dir / "private-generated.v"
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text(
                "module dut(input a, output y); assign y = a; endmodule\n",
                encoding="ascii",
            )
            return PreparedRTL(
                language=self.name,
                source_files=request.source_files,
                library_files=request.library_files,
                analysis_verilog_files=(generated,),
                python_dut_files=(generated,),
                metadata={"compiler": request.language_options["compiler"]},
            )

    backend = FakeChiselBackend()
    register_rtl_language(backend)
    try:
        with pytest.raises(RTLLanguageError, match="already registered"):
            register_rtl_language(FakeChiselBackend())
        cfg = _config()
        cfg.un_freeze()
        cfg.set_value("design_with_ppa.rtl.language", backend.name)
        cfg.set_value("design_with_ppa.rtl.source_glob", "output/rtl/*.scala")
        cfg.set_value(
            "design_with_ppa.rtl.source_template", backend.source_template
        )
        cfg.set_value(
            "design_with_ppa.rtl.language_options", {"compiler": "test-1"}
        )
        template_context = build_rtl_template_context(
            cfg,
            {"DUT": "dut", "OUT": "output", "WORKSPACE": str(tmp_path)},
        )
        assert template_context["RTL_SOURCE_FILE"] == "dut.scala"
        assert "import chisel3._" in template_context["RTL_SOURCE_TEMPLATE_BODY"]
        assert "module dut(" not in template_context["RTL_SOURCE_TEMPLATE_BODY"]
        assert template_context["RTL_CODING_GUIDE"].endswith(
            "coding_standard_test_chisel.md"
        )
        source = tmp_path / "output" / "rtl" / "dut.scala"
        source.parent.mkdir(parents=True)
        source.write_text("object dut extends Module\n", encoding="ascii")
        architecture = tmp_path / "output" / "dut_architecture.md"
        architecture.write_text(
            "\n# Architecture\n\n```yaml\narchitecture:\n"
            "  rtl_language: test-chisel\n  top_module: dut\n```\n",
            encoding="utf-8",
        )
        private_paths: list[Path] = []
        reject_private_analysis = False
        monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)

        def fake_run(command, **kwargs):
            """Accept synthesis/build and record only the transient generated input."""

            if command[0] == sys.executable:
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[0] == "yosys":
                match = re.search(r'read_verilog "([^"]+)"', command[-1])
                assert match is not None
                private_paths.append(Path(match.group(1)))
                assert private_paths[-1].is_file()
                if reject_private_analysis:
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        "",
                        f"SystemVerilog parse failed in {private_paths[-1]}",
                    )
                return subprocess.CompletedProcess(command, 0, "", "")
            if command == ["picker", "--version"]:
                return subprocess.CompletedProcess(command, 0, "builder 1.0", "")
            assert command[:2] == ["picker", "export"]
            assert "--coverage" in command
            filelist = Path(command[command.index("--fs") + 1])
            assert filelist.is_file()
            private_paths.append(filelist)
            generated = Path(command[-1])
            generated.mkdir(parents=True)
            (generated / "__init__.py").write_text(
                "class DUTdut:\n    pass\n", encoding="ascii"
            )
            (generated / "_UT_dut.so").write_bytes(b"fixture-native-extension")
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr("design_with_ppa.checkers.runtime.subprocess.run", fake_run)
        checker = RTLBackendBuildChecker(
            architecture_file="output/dut_architecture.md",
            manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
            timeout=10,
            cfg=cfg,
        ).set_workspace(str(tmp_path))

        passed, result = checker.do_check()

        assert passed is True, result
        assert result["source_files"] == ["output/rtl/dut.scala"]
        manifest_path = (
            tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend.json"
        )
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        assert manifest["rtl_sources"][0]["path"] == "output/rtl/dut.scala"
        assert set(manifest["prepared_content"]) == {"analysis", "python_dut"}
        assert "private-generated.v" not in manifest_text
        assert "read_verilog" not in manifest_text
        assert "picker" not in manifest_text.lower()
        assert private_paths
        assert all(not path.exists() for path in private_paths)

        ppa_private_paths: list[Path] = []

        def fail_private_ppa(self, arguments, **kwargs):
            """Capture trusted analysis files and fail before report publication."""

            del self, arguments
            ppa_private_paths.extend(kwargs["trusted_rtl_files"])
            assert kwargs["rtl_provenance"] == manifest["rtl_sources"]
            assert all(path.is_file() for path in ppa_private_paths)
            assert all(not path.is_relative_to(tmp_path) for path in ppa_private_paths)
            raise RuntimeError("controlled PPA failure")

        monkeypatch.setattr(
            "design_with_ppa.checkers.ppa_iteration.AnalyzePPA.analyze", fail_private_ppa
        )
        with pytest.raises(RuntimeError, match="controlled PPA failure"):
            _run_workflow_ppa(
                workspace=tmp_path,
                cfg=cfg,
                architecture={"top_module": "dut"},
                rtl_config=resolve_rtl_config(cfg)[0],
                rtl_language_backend=backend,
                rtl_files=[source.resolve()],
                rtl_rows=manifest["rtl_sources"],
                rtl_library_files=(),
                rtl_library_rows=[],
                prepared_content=manifest["prepared_content"],
                performance_manifest={
                    "tests": [{"waveform": {"path": "output/waves/tc.vcd"}}]
                },
                report_file="output/reports/ppa/current.json",
                baseline_report_id=None,
                timeout=10,
            )
        assert ppa_private_paths
        assert all(not path.exists() for path in ppa_private_paths)
        assert backend.name in available_rtl_languages()

        reject_private_analysis = True
        source.write_text("object dutChanged extends Module\n", encoding="ascii")
        passed, result = checker.do_check()
        assert passed is False
        assert result["error_code"] == "rtl_synthesis_failed"
        assert result["artifact"] == "output/rtl/*.scala"
        assert result["observed"] == {"returncode": 1}
        assert "Verilog" not in json.dumps(result)
        assert all(str(path) not in json.dumps(result) for path in private_paths)
    finally:
        unregister_rtl_language(backend.name)
    assert backend.name not in available_rtl_languages()




def test_rtl_backend_guide_requires_refresh_after_immediate_writes() -> None:
    """The shared adapter contract must separate port writes from evaluation."""

    guide = (
        PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc" / "rtl_backend.md"
    ).read_text(encoding="utf-8")

    assert "GetXPort().AsImmWrite()" in guide
    assert "但不会执行组合逻辑" in guide
    assert "必须先写完所有输入，再统一刷新" in guide
    assert "首次刷新前 `Step(1)`" in guide
    assert "纯组合设计" in guide
    assert "不能代替 `Step(1)`" in guide
    assert "每个时钟调用一次 `InitClock" in guide
    assert "last_event" in guide
    assert "api_validation_error" in guide
    assert "transaction_accepted" in guide
    assert "测试不得直接调用该方法、transaction helper" in guide
    example = guide[guide.index("class AdderAdapter:") :]
    assert example.index('self._dut.GetXPort().AsImmWrite()') < example.index(
        'self._dut.InitClock("clk_i")'
    )
    assert example.index('self._dut.InitClock("clk_i")') < example.index(
        "def configure_test_artifacts"
    )
    drive = example[example.index("    def _drive") : example.index("    def _step")]
    refresh_index = drive.index("self._dut.RefreshComb()")
    assert max(
        drive.index("self._dut.valid_i.value = valid_i"),
        drive.index("self._dut.a_i.value = a_i"),
        drive.index("self._dut.b_i.value = b_i"),
        drive.index("self._dut.rst_ni.value = rst_ni"),
    ) < refresh_index
    transact = example[
        example.index("    def add") : example.index("    def run_until_observation_end")
    ]
    assert transact.index("self.last_transaction_timing = None") < transact.index(
        "self._drive("
    )
    assert transact.index("self._drive(") < transact.index("self._step()")
    assert "accepted_at = self.sim_time_ns" in transact
    assert transact.index("self._step()") < transact.index(
        "self._record_transaction_accepted("
    )
    validation = transact[: transact.index("self.last_transaction_timing = None")]
    assert validation.index('self._record_event(\n                "api_validation_error"') < validation.index(
        'raise ValueError("max_cycles must be a positive integer")'
    )
    wait_loop = transact[transact.index("        for _ in range(max_cycles):") :]
    assert wait_loop.index("self._step()") < wait_loop.index(
        "if self._dut.valid_o.value"
    )
    assert "self.last_transaction_timing = (accepted_at, self.sim_time_ns)" in transact
    assert '"transaction_id": transaction_id' in example
    assert 'self._record_event("response_observed", **evidence)' in example
    assert "latency_cycles=self.sim_time_ns - accepted_at" in transact
    assert example.index("def _step") < example.index("self._dut.Step(1)")
    assert example.index("self._dut.Step(1)") < example.rindex(
        "self._dut.RefreshComb()"
    )




def test_rtl_backend_build_replaces_old_tree_without_loading_generated_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful build atomically replaces files without importing workspace code."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, output y); assign y = a; endmodule\n",
        encoding="ascii",
    )
    target = _workspace_python_dut_root(tmp_path) / "dut"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    (target / "old.py").write_text("OLD = True\n", encoding="utf-8")
    import_marker = tmp_path / "generated_backend_was_imported"
    monkeypatch.setattr("design_with_ppa.checkers.rtl_validation.shutil.which", lambda name: name)

    def fake_subprocess_run(command, **kwargs):
        """Model synthesis, version, and generated-source creation."""

        if command[0] == sys.executable:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "yosys":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["picker", "--version"]:
            return subprocess.CompletedProcess(command, 0, "picker 1.0", "")
        assert command[:2] == ["picker", "export"]
        assert command[command.index("--wave_file_name") + 1] == "ucagent.vcd"
        generated = Path(command[-1])
        generated.mkdir(parents=True)
        (generated / "__init__.py").write_text(
            f"open({str(import_marker)!r}, 'w').write('imported')\n"
            "class DUTdut:\n    pass\n",
            encoding="utf-8",
        )
        (generated / "_UT_dut.so").write_bytes(b"fixture-native-extension")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "design_with_ppa.checkers.runtime.subprocess.run", fake_subprocess_run
    )
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=".ucagent/design_with_ppa/rtl_backend.json",
        timeout=10,
        cfg=_config(),
    ).set_workspace(str(tmp_path))
    passed, _ = checker.do_check()
    assert passed is True
    assert not (target / "old.py").exists()
    assert (target / "__init__.py").is_file()
    assert not import_marker.exists()
    assert not list(target.parent.glob(".build-*"))
    manifest = json.loads(
        (tmp_path / ".ucagent" / "design_with_ppa" / "rtl_backend.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["rtl_sources"] == _rtl_rows(tmp_path)
    assert manifest["schema_version"] == "1.4"
    assert manifest["python_dut_import"] == {
        "module": "dut",
        "class": "DUTdut",
    }
    assert manifest["python_dut_builder"]["coverage"] is True
    assert manifest["python_dut_builder"]["waveform_format"] == "vcd"
    assert manifest["generated_content"]["file_count"] == 2
    assert "generated_files" not in manifest
    assert str(target) not in json.dumps(manifest)
    passed, _ = checker.do_check()
    assert passed is True
    assert not import_marker.exists()




@pytest.mark.skipif(
    shutil.which("yosys") is None or shutil.which("picker") is None,
    reason="Yosys and the RTL backend builder are required for the real build test",
)
def test_real_rtl_backend_build_without_parent_import(tmp_path: Path) -> None:
    """The real internal builder must produce a source-bound backend package."""

    architecture = tmp_path / "output" / "dut_architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text(
        "\n# Architecture\n\n```yaml\narchitecture:\n  rtl_language: verilog\n  top_module: dut\n```\n",
        encoding="utf-8",
    )
    rtl = tmp_path / "output" / "rtl" / "dut.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text(
        "module dut(input a, input b, output y); assign y = a ^ b; endmodule\n",
        encoding="ascii",
    )
    (tmp_path / "output" / "tests").mkdir(parents=True)
    manifest_path = ".ucagent/design_with_ppa/rtl_backend.json"
    checker = RTLBackendBuildChecker(
        architecture_file="output/dut_architecture.md",
        manifest_file=manifest_path,
        timeout=120,
        cfg=_config(),
    ).set_workspace(str(tmp_path))

    passed, result = checker.do_check()

    assert passed is True, result
    manifest = json.loads((tmp_path / manifest_path).read_text(encoding="utf-8"))
    assert manifest["top_module"] == "dut"
    assert manifest["rtl_sources"] == _rtl_rows(tmp_path)
    assert manifest["generated_content"]["file_count"] > 0
    assert (_workspace_python_dut_root(tmp_path) / "dut" / "__init__.py").is_file()
    passed, result = checker.do_check()
    assert passed is True, result
    assert "already matches" in result["message"]


def test_python_dut_probe_failure_carries_child_output(tmp_path: Path) -> None:
    """The generated-runtime probe must surface the child's root cause."""

    import design_with_ppa.checkers.runtime as runtime_module

    def fake_run(command, **kwargs):
        """Simulate a generated runtime that crashes on import."""

        del command, kwargs
        return subprocess.CompletedProcess(
            [],
            1,
            "",
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named 'dut_shim'\n",
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)
    try:
        with pytest.raises(ValueError, match="dut_shim"):
            runtime_module._probe_python_dut_subprocess(
                tmp_path, "dut", "DUTdut", timeout=10
            )
    finally:
        monkeypatch.undo()


def test_tool_error_lines_extract_midstream_errors() -> None:
    """Decisive tool lines survive even when a long tail would cut them."""

    from design_with_ppa.checkers.evidence import tool_error_lines

    output = (
        "Info: elaborating\n"
        "%Error: dut.v:12: syntax error\n"
        + "Info: filler\n" * 2000
        + "Warning: tail warning\n"
    )
    lines = tool_error_lines(output)
    assert "%Error: dut.v:12: syntax error" in lines
    assert "Warning: tail warning" in lines
    assert tool_error_lines("clean run\n") == []
