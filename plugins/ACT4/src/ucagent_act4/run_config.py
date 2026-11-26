"""Resolve one reusable, strict configuration for either ACT generation workflow."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess

import yaml
from ucagent.plugins import PluginError

from .suite_catalog import validate_suite_target
from .xiangshan_bundle import safe_path


ASSET_TYPES = ("norm_rules", "udb_params", "rvvi", "rvmodel_macros", "testplan", "ctp", "coverpoints", "sail", "tests")
SHARED_INPUTS = frozenset({"norm_rules", "udb_params", "rvvi", "rvmodel_macros", "sail"})
WORKFLOWS = ("privileged-suite-generation", "unprivileged-suite-generation")


class RunConfigLoader(yaml.SafeLoader):
    """Reject duplicate mapping fields instead of silently changing a run policy."""

    def construct_mapping(self, node, deep=False):
        """Require unique scalar keys throughout the configuration document."""
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError(f"Configuration keys must be unique strings: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def resolve_run_config(data: dict, base: Path) -> dict:
    """Validate user choices and expand defaults and paths without accessing asset contents."""
    fields = {"schema_version", "suite", "workflow", "workspace", "output", "target_context", "upstream", "defaults", "assets", "limits", "runtime", "accepted_partial_findings"}
    if not isinstance(data, dict) or set(data) - fields or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError(f"Use schema_version: 1 and only these run fields: {sorted(fields)}")
    if data.get("workflow") not in WORKFLOWS:
        raise ValueError(f"workflow must be one of {WORKFLOWS}")
    validate_suite_target(data.get("suite"), announce=False)
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError("workspace must name a dedicated run directory")
    workspace = Path(workspace).expanduser()
    workspace = (workspace if workspace.is_absolute() else base / workspace).absolute()
    if ".." in workspace.parts:
        if any(path.is_symlink() for path in [workspace, *workspace.parents]):
            raise ValueError("workspace must not contain symlink components")
        workspace = workspace.resolve()
    if workspace == base or workspace == Path("/") or any(path.is_symlink() for path in [workspace, *workspace.parents]):
        raise ValueError("Use a dedicated workspace without symlink components")
    output = data.get("output", "act4_assets")
    destination = safe_path(workspace, output)
    for name in ("riscv-arch-test", "act4-inputs", "act4-inputs-dependencies", "capabilities", ".ucagent", "riscv-isa-manual"):
        reserved = workspace / name
        if destination.is_relative_to(reserved) or reserved.is_relative_to(destination):
            raise ValueError(f"output overlaps reserved run directory {name}")
    context = data.get("target_context", "Architectural behavior within the selected Test Suite; enumerate XLEN and target assumptions explicitly.")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("target_context must describe the requested target and assumptions")
    upstream = {"act4_root": "riscv-arch-test", "act4_ref": "act4", "manual_root": "riscv-isa-manual", "manual_ref": "HEAD", "cache_root": ""}
    provided = data.get("upstream", {})
    if not isinstance(provided, dict) or set(provided) - upstream.keys():
        raise ValueError(f"upstream permits only {sorted(upstream)}")
    upstream.update(provided)
    for name, value in upstream.items():
        if not isinstance(value, str) or (name != "cache_root" and not value.strip()):
            raise ValueError(f"Invalid upstream.{name}")
        if name.endswith("_root") and value and value != {"act4_root": "riscv-arch-test", "manual_root": "riscv-isa-manual"}.get(name):
            path = Path(value).expanduser()
            path = (path if path.is_absolute() else base / path).absolute()
            if path.is_relative_to(workspace) or workspace.is_relative_to(path):
                raise ValueError(f"Explicit upstream.{name} must be outside the run workspace")
            if any(part.is_symlink() for part in [path, *path.parents]):
                raise ValueError(f"upstream.{name} must not contain symlinks")
            path = path.resolve()
            if path.is_relative_to(workspace) or workspace.is_relative_to(path):
                raise ValueError(f"Explicit upstream.{name} must be outside the run workspace")
            upstream[name] = str(path)
    defaults = {"mode": "improve", "source": "upstream", "on_missing": "generate"}
    raw_defaults = data.get("defaults", {})
    overrides = data.get("assets", {})
    if (not isinstance(raw_defaults, dict) or set(raw_defaults) - defaults.keys()
            or not isinstance(overrides, dict) or set(overrides) - set(ASSET_TYPES)):
        raise ValueError("defaults permits mode/source/on_missing; assets must use the nine canonical category names")
    defaults.update(raw_defaults)
    if defaults["mode"] not in {"improve", "regenerate"} or defaults["on_missing"] not in {"generate", "error"}:
        raise ValueError("Suite defaults require mode improve/regenerate and on_missing generate/error")
    if defaults["source"] != "upstream":
        raise ValueError("Set local sources explicitly per asset, not as an ambiguous global default")
    assets = {}
    for category in ASSET_TYPES:
        supplied = overrides.get(category, {})
        if not isinstance(supplied, dict) or set(supplied) - {"mode", "source", "path", "on_missing"}:
            raise ValueError(f"Invalid asset policy: {category}")
        item = {**defaults, **supplied}
        if category in SHARED_INPUTS:
            item["mode"] = supplied.get("mode", "repair_only")
            item["on_missing"] = supplied.get("on_missing", "error" if item["source"] == "local" else "report")
            if item["mode"] != "repair_only" or item["on_missing"] not in {"error", "report"}:
                raise ValueError(f"{category}: shared inputs require mode repair_only and on_missing report/error; do not regenerate missing dependencies")
        elif item["mode"] not in {"improve", "regenerate"} or item["on_missing"] not in {"generate", "error"}:
            raise ValueError(f"{category}: mode is improve/regenerate; on_missing is generate/error")
        if item["mode"] == "regenerate":
            if "source" in supplied or "path" in supplied or "on_missing" in supplied:
                raise ValueError(f"{category}: regenerate takes no existing source, path or fallback")
            assets[category] = {"mode": "regenerate", "source": None, "path": None, "on_missing": "generate"}
            continue
        if item["source"] not in {"upstream", "local"}:
            raise ValueError(f"{category}: source is upstream/local")
        if item["source"] == "local":
            if not isinstance(item.get("path"), str) or not item["path"].strip():
                raise ValueError(f"{category}: local sources require path")
            path = Path(item["path"]).expanduser()
            path = (path if path.is_absolute() else base / path).absolute()
            if path.is_relative_to(workspace) or workspace.is_relative_to(path):
                raise ValueError(f"{category}: local source must be separate from the workspace")
            if not path.is_dir() or any(part.is_symlink() for part in [path, *path.parents]):
                raise ValueError(f"{category}: local source must be an existing non-symlink directory")
            path = path.resolve()
            if path.is_relative_to(workspace) or workspace.is_relative_to(path):
                raise ValueError(f"{category}: local source must be separate from the workspace")
            item["path"] = str(path)
            item["on_missing"] = supplied.get("on_missing", "error")
        elif "path" in supplied:
            raise ValueError(f"{category}: upstream sources do not take a local path")
        else:
            item["path"] = None
        assets[category] = item
    limits = {"stalled_rounds": 3, "experiments": 6, "experiment_seconds": 1800}
    supplied_limits = data.get("limits", {})
    if not isinstance(supplied_limits, dict) or set(supplied_limits) - limits.keys():
        raise ValueError(f"limits permits only {sorted(limits)}")
    limits.update(supplied_limits)
    for name, maximum in (("stalled_rounds", 100), ("experiments", 50), ("experiment_seconds", 3600)):
        if type(limits[name]) is not int or not 1 <= limits[name] <= maximum:
            raise ValueError(f"limits.{name} must be an integer in 1..{maximum}")
    runtime = {"use_skill": False, "mcp_port": -1}
    supplied_runtime = data.get("runtime", {})
    if not isinstance(supplied_runtime, dict) or set(supplied_runtime) - runtime.keys():
        raise ValueError("runtime permits only use_skill and mcp_port")
    runtime.update(supplied_runtime)
    if type(runtime["use_skill"]) is not bool or type(runtime["mcp_port"]) is not int or not (runtime["mcp_port"] == -1 or 1 <= runtime["mcp_port"] <= 65535):
        raise ValueError("runtime requires boolean use_skill and mcp_port=-1 or 1..65535")
    accepted = data.get("accepted_partial_findings", [])
    if not isinstance(accepted, list) or not all(isinstance(value, str) and re.fullmatch(r"F[0-9]+", value) for value in accepted) or len(set(accepted)) != len(accepted):
        raise ValueError("accepted_partial_findings must list distinct finding IDs explicitly accepted by the operator")
    return {"schema_version": 1, "suite": data["suite"], "workflow": data["workflow"], "workspace": str(workspace), "accepted_partial_findings": accepted,
            "output": output, "target_context": context, "upstream": upstream, "assets": assets, "limits": limits, "runtime": runtime}


def run_settings(cfg) -> dict | None:
    """Read the resolved generation contract, never reinterpret environment defaults."""
    value = cfg.get_value("act4_run", None) if hasattr(cfg, "get_value") else (cfg or {}).get("act4_run")
    return value.as_dict() if hasattr(value, "as_dict") else value


def ucagent_config(settings: dict) -> dict:
    """Project resolved run choices into the native UCAgent configuration layer."""
    return {"act4_run": settings, "loop_settings": {"max_stalled_rounds": settings["limits"]["stalled_rounds"]},
            "skill": {"use_skill": settings["runtime"]["use_skill"]}}


def main(argv=None) -> int:
    """Launch UCAgent with all generation choices taken from one reusable YAML file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--print-command", action="store_true", help="Validate configuration and show the command without starting UCAgent")
    args = parser.parse_args(argv)
    try:
        source = args.config.expanduser().resolve()
        settings = resolve_run_config(yaml.load(source.read_text(encoding="utf-8"), Loader=RunConfigLoader), source.parent)
        workspace = Path(settings["workspace"])
        native = workspace / ".ucagent" / "act4-run.yaml"
        if native.is_symlink() or native.parent.is_symlink():
            raise ValueError("Run configuration must not be written through symlinks")
        if not native.exists() and any((native.parent / name).exists() for name in ("ucagent_info.json", "runtime_config.json")):
            raise ValueError("Workspace contains a run without this generation configuration; use a new workspace")
        command = ["ucagent", str(workspace), settings["suite"], "--plugin", "act4", "--plugin-workflow", "act4:" + settings["workflow"],
                   "--config", str(native), "--output", settings["output"], "--backend", "codex",
                   "--mcp-server-no-file-tools", "--mcp-server-port", str(settings["runtime"]["mcp_port"]), "--loop", "--exit-on-completion"]
        print(json.dumps({"configuration": settings, "command": command, "input_file": str(source)}, ensure_ascii=False, indent=2), flush=True)
        if args.print_command:
            return 0
        native.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.safe_dump(ucagent_config(settings), sort_keys=False)
        lock = safe_path(workspace, ".ucagent/act4-run.lock")
        with lock.open("a+") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("A generation run already owns this workspace; use act4-status") from error
            if native.exists() and native.read_text(encoding="utf-8") != content:
                raise ValueError("Run configuration changed in an existing workspace; choose a new workspace")
            native.write_text(content, encoding="utf-8")
            return subprocess.call(command, env={**os.environ, "ACT4_ANNOUNCED_CONFIG": str(native)}, pass_fds=(stream.fileno(),))
    except (OSError, ValueError, TypeError, PluginError, yaml.YAMLError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
