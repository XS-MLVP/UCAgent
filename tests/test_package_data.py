"""Guard the installed-wheel runtime resource contract."""

from pathlib import Path
import tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_package_data_declares_every_runtime_resource_type() -> None:
    """The wheel must retain files consumed after Python package installation."""

    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = pyproject["tool"]["setuptools"]["package-data"]
    root = REPOSITORY_ROOT / "ucagent"
    included = {path.relative_to(root).as_posix() for pattern in patterns["ucagent"]
                for path in root.glob(pattern) if path.is_file()}
    assert not any(path.startswith("plugins/") for path in included)
    assert {
        "setting.yaml", "SKILL.md", "core/locales/zh.yaml", "core/multi_agent/global_agent/workflow.yaml",
        "core/backends/assets/mcp_opencode.json", "core/backends/assets/mcp_codex.toml",
        "core/backends/assets/cli_codex_args.json.j2", "interfaces/terminal/tui/styles/default.tcss",
        "interfaces/server/static/surfer/surfer_bg.wasm", "interfaces/server/templates/master.html",
    } <= included
    assert set(patterns["ucagent.plugins"]) == {
        "ToffeeUT/ucagent-plugin.toml", "ToffeeUT/src/**/*",
        "UnitTest/ucagent-plugin.toml", "UnitTest/src/**/*",
    }
