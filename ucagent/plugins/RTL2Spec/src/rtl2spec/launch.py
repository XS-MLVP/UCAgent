"""Launch the existing UCAgent workflow from one user-owned YAML configuration."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .evidence import output_root


class LaunchSettings(BaseModel):
    """Define only startup arguments; all other YAML sections belong to UCAgent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    workspace: str = Field(min_length=1)
    module: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    workflow: Literal["generic-design-document", "xiangshan-design-document"]
    output: str = Field(default="outputs", min_length=1)


def build_command(config_file: Path) -> list[str]:
    """Resolve startup paths relative to the YAML and preserve UCAgent's config loader."""
    config_file = config_file.expanduser().resolve(strict=True)
    data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rtl2spec" not in data:
        raise ValueError("Expected a YAML mapping with an rtl2spec section; create one with --init")
    settings = LaunchSettings.model_validate(data["rtl2spec"])
    workspace = Path(settings.workspace).expanduser()
    if not workspace.is_absolute():
        workspace = config_file.parent / workspace
    workspace = workspace.resolve()
    output_root(workspace, settings.output)
    return [
        sys.executable, "-P", "-m", "ucagent.cli", str(workspace), settings.module,
        "--plugin", "rtl2spec",
        "--plugin-workflow", f"rtl2spec:{settings.workflow}",
        "--config", str(config_file), "--output", settings.output,
        "--no-history", "--mcp-server-no-file-tools",
    ]


def main(argv: list[str] | None = None) -> int:
    """Create a template or start UCAgent from a configuration file."""
    parser = argparse.ArgumentParser(description=__doc__, prog="rtl2spec")
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
        command = build_command(args.config)
        os.execv(sys.executable, command)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(2, f"rtl2spec: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
