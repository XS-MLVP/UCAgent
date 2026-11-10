"""Resolve checkout-local FM-Agent paths without consulting shell configuration."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
import json
import os
from pathlib import Path
import tomllib
from urllib.parse import unquote, urlsplit


DEFAULT_REPO = "https://github.com/fmagent-project/FM-Agent"
DEFAULT_BRANCH = "main"


def plugin_source_root() -> Path:
    """Find the retained local source for source, editable, or directory installs."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "src/rtl2spec/fmagent_config.py").is_file():
        return candidate
    try:
        source = json.loads(metadata.distribution("ucagent-rtl2spec").read_text("direct_url.json") or "{}")
        url = urlsplit(source.get("url", ""))
        candidate = Path(unquote(url.path))
        if (url.scheme == "file" and url.netloc in {"", "localhost"} and "dir_info" in source
                and candidate.is_absolute() and (candidate / "src/rtl2spec/fmagent_config.py").is_file()):
            return candidate.resolve()
    except (metadata.PackageNotFoundError, ValueError, TypeError, AttributeError):
        pass
    raise ValueError("FM-Agent management requires retained RTL2Spec local source; install from a local directory (wheel-only installs are unsupported)")


@dataclass(frozen=True)
class FMAgentPaths:
    """Carry effective paths and their independently reported selection sources."""

    root: Path
    python: Path
    root_source: str
    python_source: str
    local_config: Path


def resolve_paths(root: str | None = None, python: str | None = None, *, use_environment: bool = True) -> FMAgentPaths:
    """Select paired paths; standalone binding excludes temporary process overrides."""
    source = plugin_source_root()
    config = source / "rtl2spec.local.toml"
    layers = [
        ("argument", {"root": root, "python": python}),
    ]
    if use_environment:
        layers.append(("environment", {"root": os.environ.get("RTL2SPEC_FMAGENT_ROOT"),
                                       "python": os.environ.get("RTL2SPEC_FMAGENT_PYTHON")}))
    local = {}
    if not (root and root.strip() and python and python.strip()) and config.exists():
        try:
            local = tomllib.loads(config.read_text(encoding="utf-8")).get("fmagent", {})
            if not isinstance(local, dict):
                raise ValueError("fmagent must be a table")
            for key in ("root", "python"):
                if key in local and not isinstance(local[key], str):
                    raise ValueError(f"fmagent.{key} must be a string")
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid local configuration {config}; fix its TOML/path fields or supply both --fmagent-root and --fmagent-python") from exc
    layers.append(("local TOML", local))
    root_index = len(layers)
    root_value = str(source / "third_party/FM-Agent")
    root_source = "default"
    for index, (label, values) in enumerate(layers):
        value = values.get("root")
        if value and value.strip():
            root_value, root_source, root_index = value, label, index
            break
    selected_root = Path(root_value).expanduser().absolute().resolve()
    selected_python = selected_root / ".venv/bin/python"
    python_source = "root default"
    for label, values in layers[:root_index + 1]:
        value = values.get("python")
        if value and value.strip():
            selected_python = Path(os.path.abspath(Path(value).expanduser()))
            python_source = label
            break
    return FMAgentPaths(selected_root, selected_python, root_source, python_source, config)


def bind_paths(paths: FMAgentPaths) -> None:
    """Update only the two path fields, retaining TOML comments and unrelated content."""
    try:
        from tomlkit import dumps, parse, table
        from tomlkit.exceptions import TOMLKitError
    except ImportError as exc:
        raise ValueError("Binding requires the declared tomlkit dependency; reinstall the local RTL2Spec package") from exc

    try:
        document = parse(paths.local_config.read_text(encoding="utf-8")) if paths.local_config.exists() else parse("")
        if "fmagent" not in document:
            document["fmagent"] = table()
        if not isinstance(document["fmagent"], dict):
            raise ValueError("fmagent must be a table")
        document["fmagent"]["root"] = str(paths.root)
        document["fmagent"]["python"] = str(paths.python)
        content = dumps(document)
    except (TOMLKitError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot update {paths.local_config}; repair its fmagent table first") from exc
    with paths.local_config.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)
