"""Launch the existing UCAgent workflow from one user-owned YAML configuration."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .fmagent_workflow import FMAgentSettings
from .evidence import output_root


class LaunchSettings(BaseModel):
    """Define only startup arguments; all other YAML sections belong to UCAgent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    workspace: str = Field(min_length=1)
    module: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    workflow: Literal["generic-design-document", "xiangshan-design-document"]
    output: str = Field(default="outputs", min_length=1)
    mode: Literal["run", "reuse"] = "run"
    source: str | None = Field(default=None, min_length=1)


class UnityTestSettings(BaseModel):
    """Select an independent default verification mission."""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    workspace: str = Field(default="verification", min_length=1)


def read_settings(config_file: Path) -> tuple[dict, LaunchSettings, UnityTestSettings]:
    """Validate launch switches without resolving optional FM-Agent execution settings."""
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rtl2spec" not in data:
        raise ValueError("Expected a YAML mapping with an rtl2spec section; create one with --init")
    settings = LaunchSettings.model_validate(data["rtl2spec"])
    unitytest = UnityTestSettings.model_validate(data.get("unitytest", {}))
    if settings.mode == "reuse" and (not settings.source or not unitytest.enabled):
        raise ValueError("rtl2spec.mode reuse requires source and unitytest.enabled")
    return data, settings, unitytest


def build_command(config_file: Path) -> list[str]:
    """Resolve startup paths relative to the YAML and preserve UCAgent's config loader."""
    config_file = config_file.expanduser().resolve(strict=True)
    data, settings, _ = read_settings(config_file)
    fmagent = FMAgentSettings.model_validate(data.get("fmagent", {}))
    workflow = settings.workflow + ("-fmagent" if fmagent.enabled else "")
    workspace = Path(settings.workspace).expanduser()
    if not workspace.is_absolute():
        workspace = config_file.parent / workspace
    workspace = workspace.resolve()
    output_root(workspace, settings.output)
    return [
        sys.executable, "-P", "-m", "ucagent.cli", str(workspace), settings.module,
        "--plugin", "rtl2spec",
        "--plugin-workflow", f"rtl2spec:{workflow}",
        "--config", str(config_file), "--output", settings.output,
        "--no-history", "--mcp-server-no-file-tools",
    ]


def main(argv: list[str] | None = None) -> int:
    """Create a template or start UCAgent from a configuration file."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["fmagent"]:
        from .fmagent import main as fmagent_main
        return fmagent_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__, prog="rtl2spec", epilog="FM-Agent management: rtl2spec fmagent {fetch,install,bind,status} --help")
    parser.add_argument("--config", type=Path, default=Path("rtl2spec.yaml"), help="Run configuration (default: rtl2spec.yaml)")
    parser.add_argument("--init", choices=("generic", "xiangshan"), help="Write a bundled configuration template without overwriting files")
    args = parser.parse_args(argv)
    try:
        if args.init:
            template = Path(__file__).parent / "launch_configs" / f"{args.init}.yaml"
            content = template.read_text(encoding="utf-8")
            target = args.config.expanduser()
            with target.open("x", encoding="utf-8") as stream:
                stream.write(content)
            print(f"Created {target}. Edit its workspace/module, prepare the input, then run rtl2spec --config {shlex.quote(str(target))}.")
            return 0
        config_file = args.config.expanduser().resolve(strict=True)
        _, settings, unitytest = read_settings(config_file)
        if unitytest.enabled:
            from .unitytest import continue_to_unitytest

            return continue_to_unitytest(config_file, settings, unitytest)
        command = build_command(config_file)
        os.execv(sys.executable, command)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        parser.exit(2, f"rtl2spec: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
