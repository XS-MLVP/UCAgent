"""Check executable documentation contracts without building a site or calling models."""

import ast
import importlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from ucagent.interfaces.server.api_mcp import _collect_mcp_tools
from ucagent.util.config import load_yaml_with_env_vars


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "docs/content"
STARTUP_PAGES = (
    "01_start/01_modes_overview",
    "01_start/03_mcp_mode",
    "02_usage/03_option",
)


@pytest.mark.parametrize("locale", ("", ".en"))
def test_documented_default_workflow_matches_locale_and_workflow_defaults(locale):
    """Authoritative architecture and lifecycle pages follow the actual default selector."""
    selector = load_yaml_with_env_vars(str(ROOT / "ucagent/core/locales/zh.yaml"))["workflow"]
    workflow = load_yaml_with_env_vars(str(ROOT / selector))
    assert selector == "ucagent/plugins/ToffeeUT/src/toffee_ut/workflows/ut.yaml"
    assert len(workflow["stage"]) == 20 and workflow["output"] == "ut_project"
    assert workflow["runtime_options"]["ut_line_coverage"] is True
    for page in ("01_start/05_architecture", "03_develop/03_workflow"):
        text = (CONTENT / f"{page}{locale}.md").read_text(encoding="utf-8")
        assert selector in text and "toffee-ut:ut" in text and "ut_project" in text
    text = (CONTENT / f"03_develop/03_workflow{locale}.md").read_text(encoding="utf-8")
    assert "runtime_options.ut_line_coverage=true" in text
    assert "NEED_REF_MODEL=true" not in text


@pytest.mark.parametrize("page", STARTUP_PAGES)
@pytest.mark.parametrize("locale", ("", ".en"))
def test_unittest_mcp_examples_keep_required_tools(page, locale, monkeypatch):
    """Copyable single-task examples satisfy the real business MCP preflight."""
    workflow = ROOT / "ucagent/plugins/UnitTest/src/unit_test/workflows/unittest.yaml"
    monkeypatch.setenv("NEED_REF_MODEL", "false")
    monkeypatch.setenv("IGNORE_MOCK_COMPONENT", "false")
    required = load_yaml_with_env_vars(str(workflow))["runtime_options"]["required_mcp_tools"]
    agent = SimpleNamespace(
        tool_list_base=[SimpleNamespace(name="ReadTextFile")],
        tool_list_task=[],
        tool_list_ext=[],
        tool_list_file=[SimpleNamespace(name=name) for name in required if name != "ReadTextFile"],
        cfg=SimpleNamespace(runtime_options={"required_mcp_tools": required}),
    )
    source = (CONTENT / f"{page}{locale}.md").read_text()
    checked = 0
    for block in re.findall(r"```bash\n(.*?)```", source, re.DOTALL):
        for line in block.replace("\\\n", " ").splitlines():
            tokens = shlex.split(line, comments=True)
            if not tokens or tokens[0] not in {"ucagent", "python3"}:
                continue
            if not {"--mcp-server", "--mcp-server-no-file-tools"}.intersection(tokens):
                continue
            tools = _collect_mcp_tools(agent, no_file_ops="--mcp-server-no-file-tools" in tokens)
            assert set(required) <= {tool.name for tool in tools}
            checked += 1
    assert checked, f"No MCP startup example checked in {page}{locale}"


@pytest.mark.skipif(shutil.which("make") is None, reason="GNU Make is required for dry runs")
@pytest.mark.parametrize("target", ("mcp_Adder", "mcp_with_master_Adder", "mcp_all_tools_Adder"))
def test_documented_make_mcp_targets_enable_file_tools(target):
    """Expand real recipes without preparing workspaces or launching any clients."""
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, "CMD=ucagent", "MASTER_IP=127.0.0.1"],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=20,
    )
    commands = [shlex.split(line) for line in result.stdout.splitlines() if line.startswith("ucagent ")]
    assert len(commands) == 1, result.stdout
    assert "--mcp-server" in commands[0]
    assert "--mcp-server-no-file-tools" not in commands[0]


@pytest.mark.parametrize("source", sorted(
    path for path in (CONTENT / "03_develop").glob("*.md") if not path.name.endswith(".en.md")
), ids=lambda path: path.stem)
def test_developer_translations_preserve_inline_api_identifiers(source):
    """Translations keep literal class/tool names in both directions, not just flags."""
    original = source.read_text()
    translated = source.with_suffix(".en.md").read_text()
    pattern = r"`([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`"
    original_names = set(re.findall(pattern, original))
    translated_names = set(re.findall(pattern, translated))
    missing = {name for name in original_names
               if not re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", translated)}
    extra = {name for name in translated_names
             if not re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", original)}
    assert not missing, f"Missing English identifiers: {missing}"
    assert not extra, f"Extra English identifiers: {extra}"


@pytest.mark.parametrize("page", ("05_customize", "07_checkers"))
@pytest.mark.parametrize("locale", ("", ".en"))
def test_documented_framework_imports_exist(page, locale):
    """Resolve framework imports from complete examples without executing their bodies."""
    source = (CONTENT / f"03_develop/{page}{locale}.md").read_text()
    checked = 0
    for block in re.findall(r"(?:```|~~~)python\n(.*?)(?:```|~~~)", source, re.DOTALL):
        for node in ast.walk(ast.parse(block)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module != "ucagent" and not node.module.startswith("ucagent."):
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(module, alias.name), f"{page}{locale}: {node.module}.{alias.name}"
                checked += 1
    assert checked


@pytest.mark.parametrize("page", ("03_workflow", "07_checkers"))
@pytest.mark.parametrize("locale", ("", ".en"))
def test_documented_batch_engine_uses_the_public_class(page, locale):
    """The shared helper remains importable and is not replaced by a translated name."""
    from ucagent import BatchTask
    from ucagent.core.checkers.base import BatchTask as CoreBatchTask

    source = (CONTENT / f"03_develop/{page}{locale}.md").read_text()
    assert BatchTask is CoreBatchTask
    assert "`BatchTask`" in source
    assert set(re.findall(r"`([A-Za-z_]*BatchTask)`", source)) == {BatchTask.__name__}
