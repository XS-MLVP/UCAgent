"""Focused DesignWithPPA workflow tests: plugin packaging."""

from __future__ import annotations

import helpers  # noqa: F401  (runs the plugin sys.path bootstrap first)

from helpers import (
    PLUGIN_SOURCE,
    REPOSITORY_ROOT,
    _config,
    _template_context,
)

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import pytest
from design_with_ppa.consistency import (  # noqa: E402
    RunDesignConsistency,
    RunDesignConsistencyArgs,
)
from design_with_ppa.plugin import get_plugin
from ucagent.util.config import (  # noqa: E402
    Config,
    build_runtime_config,
    get_config,
    load_yaml_with_env_vars,
    save_runtime_config,
)
from ucagent.util.markdown import markdown_heading_spacing_errors
from ucagent.util.functions import render_template_dir




def test_plugin_metadata_requires_dynamic_template_context_release() -> None:
    """Package and runtime metadata must reject older incompatible UCAgent builds."""

    plugin = get_plugin()
    project = tomllib.loads(
        (PLUGIN_SOURCE.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert plugin.requires_ucagent == ">=26.9.2.dev26"
    assert "UCAgent>=26.9.2.dev26" in project["project"]["dependencies"]
    assert plugin.version == "0.4.7"
    assert project["project"]["version"] == "0.4.7"
    excluded = project["tool"]["setuptools"]["exclude-package-data"]["*"]
    assert "**/__pycache__/*" in excluded
    assert "**/*.pyc" in excluded
    manifest = (PLUGIN_SOURCE.parent / "MANIFEST.in").read_text(encoding="utf-8")
    assert "global-exclude *.py[cod]" in manifest
    assert "global-exclude __pycache__" in manifest




def test_make_targets_prefer_ucagent_source_from_makefile_location(
    tmp_path: Path,
) -> None:
    """Make targets must select this checkout even when invoked from elsewhere."""

    makefile = PLUGIN_SOURCE.parent / "Makefile"
    result = subprocess.run(
        [
            "make",
            "-n",
            "-f",
            str(makefile),
            "validate",
            f"PYTHON={sys.executable}",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f"{sys.executable} {REPOSITORY_ROOT / 'ucagent.py'}" in result.stdout
    assert "ucagent --validate-plugin" not in result.stdout




def test_make_targets_fall_back_to_installed_ucagent_without_source(
    tmp_path: Path,
) -> None:
    """A standalone plugin tree must use the installed console command."""

    plugin_root = tmp_path / "standalone" / "DesignWithPPA"
    plugin_root.mkdir(parents=True)
    makefile = plugin_root / "Makefile"
    shutil.copy2(PLUGIN_SOURCE.parent / "Makefile", makefile)
    result = subprocess.run(
        ["make", "-n", "-f", str(makefile), "validate"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ucagent --validate-plugin" in result.stdout
    assert "ucagent.py --validate-plugin" not in result.stdout




def test_make_clean_removes_only_declared_plugin_artifacts(tmp_path: Path) -> None:
    """The Makefile clean target is Git-independent and bounded to known artifacts."""

    project_root = tmp_path / "DesignWithPPA"
    project_root.mkdir()
    shutil.copy2(PLUGIN_SOURCE.parent / "Makefile", project_root / "Makefile")
    shutil.copy2(PLUGIN_SOURCE.parent / "ucagent-plugin.toml", project_root / "ucagent-plugin.toml")
    for relative in (
        "output/workspace/design",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "src/example.egg-info",
        "src/pkg/__pycache__",
    ):
        (project_root / relative).mkdir(parents=True)
    for relative in (
        "src/pkg/__pycache__/module.pyc",
        "src/pkg/module.pyo",
        ".coverage",
        ".coverage.worker",
    ):
        (project_root / relative).touch()
    sentinel = project_root / "notes.txt"
    sentinel.write_text("keep", encoding="utf-8")
    external_workspace = tmp_path / "external-workspace"
    external_workspace.mkdir()
    external_sentinel = external_workspace / "keep.txt"
    external_sentinel.write_text("keep external", encoding="utf-8")

    result = subprocess.run(
        [
            "make",
            "-s",
            "clean",
            f"WORKSPACE_ROOT={external_workspace}",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert external_sentinel.read_text(encoding="utf-8") == "keep external"
    for relative in (
        "output",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "src/example.egg-info",
        "src/pkg/__pycache__",
        "src/pkg/module.pyo",
        ".coverage",
        ".coverage.worker",
    ):
        assert not (project_root / relative).exists(), relative
    makefile = (project_root / "Makefile").read_text(encoding="utf-8")
    clean_recipe = makefile.split("\nclean:\n", maxsplit=1)[1]
    assert "git" not in clean_recipe.lower()




def test_run_design_consistency_has_zero_argument_defaults(tmp_path: Path) -> None:
    """The consistency Tool can be invoked without paths in a resolved workflow."""

    schema = RunDesignConsistencyArgs.model_json_schema()
    properties = schema["properties"]
    assert properties["test_dir"]["default"] == "{OUT}/tests"
    assert properties["test_glob"]["default"] == "{OUT}/tests/test_{DUT}_*.py"
    assert properties["architecture_file"]["default"] == "{OUT}/{DUT}_architecture.md"
    assert properties["performance_manifest_file"]["default"] == (
        "{OUT}/performance/performance_manifest.json"
    )
    assert properties["run_ppa"]["default"] is True
    assert RunDesignConsistency(workspace=str(tmp_path), cfg=_config()).name == (
        "RunDesignConsistency"
    )




def test_fp_matrix_example_contains_only_readme_and_specs() -> None:
    """The maintained FP4/FP8 case must contain inputs and no generated artifacts."""

    case_root = Path(__file__).resolve().parent.parent / "cases" / "LowPrecisionMatMul2x2"
    files = sorted(
        path.relative_to(case_root).as_posix()
        for path in case_root.rglob("*")
        if path.is_file()
    )
    assert files == [
        "README.md",
        "spec/01_numeric_formats.md",
        "spec/02_interface_and_timing.md",
        "spec/03_functional_verification.md",
        "spec/04_performance_and_optimization.md",
    ]
    content = "\n".join(
        (case_root / relative).read_text(encoding="utf-8") for relative in files
    )
    for metric_id in (
        "fp4_latency_cycles",
        "fp4_throughput_matrices_per_cycle",
        "fp8_latency_cycles",
        "fp8_throughput_matrices_per_cycle",
    ):
        assert metric_id in content
    assert "LowPrecisionMatMul2x2_performance_curve.json" in content
    assert "LowPrecisionMatMul2x2_ppa_dashboard.html" in content
    for hidden_or_stale_term in (
        "AnalyzePPA",
        "report IDs",
        "optimization ledger",
        "restored to",
        "SVG curve",
        "Verilog RTL",
    ):
        assert hidden_or_stale_term not in content




def test_fp_matrix_example_is_declared_for_wheel_installation() -> None:
    """The distributable wheel must install every maintained example input."""

    project = tomllib.loads(
        (PLUGIN_SOURCE.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    data_files = project["tool"]["setuptools"]["data-files"]
    installed_files = {
        source
        for sources in data_files.values()
        for source in sources
    }

    assert installed_files == {
        "cases/LowPrecisionMatMul2x2/README.md",
        "cases/LowPrecisionMatMul2x2/spec/*.md",
    }




def test_plugin_guide_docs_keep_required_heading_spacing() -> None:
    """Every normative DesignWithPPA Guide_Doc follows the runtime Markdown contract."""

    guide_root = PLUGIN_SOURCE / "design_with_ppa" / "Guide_Doc"
    failures = {
        path.relative_to(guide_root).as_posix(): markdown_heading_spacing_errors(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(guide_root.glob("*.md"))
        if markdown_heading_spacing_errors(path.read_text(encoding="utf-8"))
    }
    assert failures == {}




def test_rtl_line_coverage_guide_separates_raw_and_analysis_contracts() -> None:
    """The line-coverage guide must provide complete, distinct canonical artifacts."""

    guide_path = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "Guide_Doc"
        / "rtl_line_coverage.md"
    )
    content = guide_path.read_text(encoding="utf-8")
    workflow = load_yaml_with_env_vars(
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "workflows"
        / "unit-design-tdd.yaml"
    )

    assert "```text\n# Constant default branch" in content
    assert "*/Adder.v:84-86" in content
    assert "```markdown\n\n# Adder RTL 行覆盖分析" in content
    assert "<LINE_IGNORE>*/Adder.v:84-86</LINE_IGNORE>:" in content
    assert "proof=parameter_unreachable" in content
    assert "evidence=design/Adder_architecture.md:12-14" in content
    assert "不能把 Markdown 标签" in content
    assert "## 覆盖率排障流程" in content
    assert "get_coverage_groups(env)" in content
    assert "adapter.bind_coverage(groups)" in content
    assert "adapter.configure_test_artifacts(...)" in content
    assert "set_func_coverage(request, groups)" in content
    assert "adapter.finish()" in content
    assert "set_line_coverage(request, coverage_path, ignore=...)" in content
    assert "toffee_report.json:coverages.line.error" in content
    assert "line_dat/code_coverage.json" in content
    assert "merged.info" in content
    assert "{RTL_SOURCE_VALIDATION_GUIDE_FILE}" in workflow["guide_doc"][
        "plugin_copy_policy"
    ]["retain"]




@pytest.mark.parametrize("output", ["output", "output/dut"])
def test_design_dashboard_renders_as_a_relative_read_only_application(
    tmp_path: Path, output: str
) -> None:
    """The rendered dashboard must load reports relatively without network code."""

    template = PLUGIN_SOURCE / "design_with_ppa" / "templates" / "unit_design"
    rendered = render_template_dir(
        str(tmp_path),
        str(template),
        _template_context(output, str(tmp_path)),
        target_dir=output,
    )
    dashboard_relative = f"{output}/dut_ppa_dashboard.html"
    assert dashboard_relative in rendered
    dashboard = (tmp_path / dashboard_relative).read_text(encoding="utf-8")
    rtl_scaffold = (tmp_path / output / "rtl" / "dut.v").read_text(
        encoding="utf-8"
    )
    conftest = (tmp_path / output / "tests" / "conftest.py").read_text(
        encoding="utf-8"
    )

    assert "{{DUT}}" not in dashboard
    assert "{{OUT}}" not in dashboard
    assert "module dut (" in rtl_scaffold
    assert "def pytest_configure(config):" in conftest
    assert "register_managed_test_options(parser)" in conftest
    assert "managed_test_implementation(request.config)" in conftest
    assert "--design-backend" not in conftest
    assert '"performance: deterministic simulation performance case' in conftest
    assert "RTL_SOURCE_TEMPLATE_BODY" not in rtl_scaffold
    for required in (
        "// Module: dut",
        "// Purpose:",
        "// Interface:",
        "// Parameters:",
        "// Timing/reset:",
        "// Numeric behavior:",
        "// Core datapath:",
        "// input_i",
        "// output_o",
    ):
        assert required in rtl_scaffold
    assert f'const OUTPUT_PATH = "{output}"' in dashboard
    assert 'const WORKSPACE_PREFIX = "../".repeat(OUTPUT_DEPTH)' in dashboard
    assert 'data-dashboard-contract="design-with-ppa/v2"' in dashboard
    assert 'id="design-with-ppa-snapshot"' in dashboard
    assert "const EMBEDDED_SNAPSHOT" in dashboard
    assert "EMBEDDED_SNAPSHOT[source.snapshotKey]" in dashboard
    assert ".ucagent/runtime_config.json" in dashboard
    assert ".ucagent/design_with_ppa/state.json" in dashboard
    assert ".ucagent/current_test_report.json" in dashboard
    assert "file.text()" in dashboard
    assert "webkitdirectory" in dashboard
    assert 'getContext("2d")' in dashboard
    assert '<html lang="en">' in dashboard
    assert "--page: #0f1117" in dashboard
    assert 'class="app-shell"' in dashboard
    assert 'class="sidebar"' in dashboard
    assert 'class="workspace"' in dashboard
    assert "Run Status" in dashboard
    assert "Version History" in dashboard
    assert 'id="dashboard-theme-toggle"' in dashboard
    assert 'data-theme-option="dark"' in dashboard
    assert 'data-theme-option="light"' in dashboard
    assert 'data-theme-option="graphite"' in dashboard
    assert "const applyTheme = (name, persist = true)" in dashboard
    assert "const PREFERENCES_KEY = `design-with-ppa.dashboard.v2.preferences:${DUT}:${OUTPUT_PATH}`" in dashboard
    assert "window.localStorage.getItem(PREFERENCES_KEY)" in dashboard
    assert "window.localStorage.setItem(PREFERENCES_KEY, serialized)" in dashboard
    assert 'window.location.hash.startsWith("#dwp=")' in dashboard
    assert 'window.history.replaceState(null, "", fragment)' in dashboard
    assert "iteration_page_size: iterationPageSize" in dashboard
    assert "metrics: Object.fromEntries(displayFilters.metrics)" in dashboard
    assert "--page: #f4f7fb" in dashboard
    assert "--page: #151a20" in dashboard
    assert re.search(r"[\u4e00-\u9fff]", dashboard) is None
    assert 'id="ppa-score-chart"' in dashboard
    assert 'id="ppa-score-value"' in dashboard
    assert "PPA score" in dashboard
    assert 'id="iteration-limits"' in dashboard
    assert 'setText("iteration-progress", `${count} / ${minimum}`)' in dashboard
    assert '`${count >= minimum ? "minimum met"' in dashboard
    assert "white-space: nowrap" in dashboard
    assert "createElementNS" not in dashboard
    assert "const REFRESH_INTERVAL_MS = 15000" in dashboard
    assert (
        "refreshTimer = window.setInterval(refreshDashboard, REFRESH_INTERVAL_MS);"
        in dashboard
    )
    assert "tr.rejected-row" in dashboard
    assert 'if (iteration.accepted !== true) row.className = "rejected-row"' in dashboard
    assert (
        'chip.dataset.state = iteration.accepted ? "accepted" : "rejected"'
        in dashboard
    )
    assert (
        "segmentAccepted = previous.accepted === true && point.accepted === true"
        in dashboard
    )
    assert "context.setLineDash(segmentAccepted ? [] : [4, 4])" in dashboard
    assert "context.strokeStyle = point.accepted ? color : muted" in dashboard
    assert "hollow grey points are rejected" in dashboard
    assert "Strict Pareto regression" in dashboard
    assert "metric.previous_value" in dashboard
    assert "metric.current_value" in dashboard
    assert "rejection.test_summary" in dashboard
    assert "Sources and reports" in dashboard
    assert "artifacts.rtl_sources" in dashboard
    assert 'appendArtifactLink("Snapshot manifest", artifacts.snapshot_manifest)' in dashboard
    assert 'appendArtifactLink("Iteration report", artifacts.iteration_report)' in dashboard
    assert 'id="filter-accepted"' in dashboard
    assert 'id="filter-rejected"' in dashboard
    assert 'id="metric-filters"' in dashboard
    assert "const displayFilters = { accepted: true, rejected: true, metrics: new Map() }" in dashboard
    assert "const visibleSeries = (series)" in dashboard
    assert "const metricId = item && item.metric_id;" in dashboard
    assert "item && item.series && item.series.metric_id" not in dashboard
    assert "displayFilters.metrics.get(metricId) !== false" in dashboard
    assert "Local files / read-only auto-refresh" in dashboard
    assert "dut_performance_curve.json" in dashboard
    assert "performance_curve.svg" not in dashboard
    assert "Workflow Progress" not in dashboard
    assert "Report Preview" not in dashboard
    assert "Architecture Design" not in dashboard
    assert "localStorage.removeItem" not in dashboard
    assert "localStorage.clear" not in dashboard
    assert "sessionStorage" not in dashboard
    assert dashboard.count("history.replaceState(") == 1
    assert ".innerHTML" not in dashboard
    assert not re.search(
        r'(?:href|src)="(?:https?:)?//', dashboard, flags=re.IGNORECASE
    )
    assert not re.search(
        r"fetch\([^\n]+method\s*:\s*[\"'](?:POST|PUT|PATCH|DELETE)",
        dashboard,
        flags=re.IGNORECASE,
    )

    scripts = re.findall(r"<script>(.*?)</script>", dashboard, flags=re.DOTALL)
    assert len(scripts) == 1
    script_path = tmp_path / "dashboard.js"
    script_path.write_text(scripts[0], encoding="utf-8")
    node = shutil.which("node")
    if node is not None:
        result = subprocess.run(
            [node, "--check", str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr




def test_design_dashboard_derives_toffee_html_from_current_report() -> None:
    """The dashboard must link to the actual Toffee directory with a safe fallback."""

    dashboard = (
        PLUGIN_SOURCE
        / "design_with_ppa"
        / "templates"
        / "unit_design"
        / "{{DUT}}_ppa_dashboard.html"
    ).read_text(encoding="utf-8")

    assert 'context.result_path' in dashboard
    assert 'parts[parts.length - 1] = "index.html"' in dashboard
    assert 'return "uc_test_report/index.html"' in dashboard
    assert 'link.href = `${WORKSPACE_PREFIX}${path}`' in dashboard




def test_design_dashboard_is_a_packaged_workflow_template() -> None:
    """The plugin workflow and package metadata must include the dashboard template."""

    plugin = get_plugin()
    workflow = plugin.workflows[0]
    dashboard = workflow.template_dir / "{{DUT}}_ppa_dashboard.html"
    assert dashboard.is_file()
    project = tomllib.loads(
        (PLUGIN_SOURCE.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "templates/**/*" in project["tool"]["setuptools"]["package-data"][
        "design_with_ppa"
    ]
    manifest = (PLUGIN_SOURCE.parent / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include src/design_with_ppa/templates *" in manifest
