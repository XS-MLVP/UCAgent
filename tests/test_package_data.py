"""Guard the installed-wheel runtime resource contract."""

from pathlib import Path
import tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_package_data_declares_every_runtime_resource_type() -> None:
    """The wheel must retain files consumed after Python package installation."""

    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = set(
        pyproject["tool"]["setuptools"]["package-data"]["ucagent"]
    )
    required_patterns = {
        "**/*.json",  # Locale contracts, MCP configs, and web manifests.
        "**/*.yaml",  # Workflow configuration and Skill metadata.
        "**/*.md",  # Runtime Guide_Doc and Skill instructions.
        "**/*.j2",  # Formal workflow templates.
        "**/*.toml",  # MCP and FST converter configuration.
        "**/*.tcss",  # Installed TUI styling.
        "**/*.wasm",  # Installed waveform viewer runtime.
    }

    assert required_patterns <= patterns
