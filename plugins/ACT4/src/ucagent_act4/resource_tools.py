"""Expose configured shared inputs without widening UCAgent's workspace file permissions."""

import json
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ucagent.plugins import PluginContext
from ucagent.tools.fileops import is_file_writeable
from ucagent.tools.uctool import UCTool

from .resources import REPOSITORIES, copy_on_write, input_path, resource_locations
from .xiangshan_bundle import safe_path, sha256


class ResourceArgs(BaseModel):
    """Select bounded read access or a stable per-run reference snapshot."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["status", "list", "read", "snapshot"] = Field(description="Inspect prepared inputs, list a directory, read text, or retain one ISA source for workspace-relative citations.")
    resource: Literal["act4", "manual", "xiangshan", "input"] = Field(default="manual", description="One of the prepared read-only inputs.")
    path: str = Field(default="", description="Exact path relative to the selected input; empty only for a root listing.")
    start_line: int = Field(default=1, ge=1, description="First physical text line to read.")
    limit: int = Field(default=100, ge=1, le=200, description="Maximum returned lines or directory entries.")


class ACT4Resources(UCTool):
    """Read registered inputs and retain selected references without arbitrary external file access."""

    name: str = "ACT4Resources"
    description: str = "Read prepared inputs without copying whole repositories. Use list/read for exploration and snapshot for ISA citations. Never modify shared inputs. During generation this tool exposes ISA sources only; after independent planning and source import, read selected assets from riscv-arch-test with file tools."
    args_schema: type[BaseModel] = ResourceArgs
    workspace: str
    resource_dir: str
    inputs: dict[str, str]
    cache_root: str = ""
    refs: dict[str, str] = Field(default_factory=dict)
    write_dirs: list[str] = Field(default_factory=list)
    un_write_dirs: list[str] = Field(default_factory=list)
    generation: bool = False

    def _run(self, action: str, resource: str = "manual", path: str = "", start_line: int = 1, limit: int = 100) -> dict:
        """Restrict all reads to configured sources and all snapshots to this run's reference area."""
        try:
            workspace = Path(self.workspace).resolve()
            directory = safe_path(workspace, self.resource_dir)
            data = json.loads(safe_path(directory, "receipt.json").read_text(encoding="utf-8"))
            if action == "status":
                return {"ok": True, "resources": data["resources"]}
            if action not in {"list", "read", "snapshot"} or resource not in self.inputs:
                raise ValueError("Select a prepared resource and list/read/snapshot")
            if self.generation and resource != "manual":
                raise ValueError("During generation use this tool for ISA sources only. Complete independent ISA planning and source import, then read selected assets in riscv-arch-test; never read excluded regenerated designs")
            if type(limit) is not int or not 1 <= limit <= 200 or type(start_line) is not int or start_line < 1:
                raise ValueError("Use start_line >= 1 and limit in 1..200")
            record = data["resources"][resource]
            configured = input_path(workspace, self.inputs[resource])
            root = Path(record["path"])
            permitted = {configured.absolute()}
            identifier = "act4" if resource == "input" and configured == input_path(workspace, self.inputs["act4"]) else resource
            if identifier in REPOSITORIES and configured == workspace / REPOSITORIES[identifier][0]:
                name, url, default_ref = REPOSITORIES[identifier]
                ref = self.refs.get(identifier, default_ref)
                key = name + "-" + hashlib.sha256(f"{url}\n{ref}".encode()).hexdigest()[:20]
                cache, _ = resource_locations(workspace, self.cache_root)
                permitted.add(safe_path(cache, "repositories/" + key + "/source"))
            if root not in permitted or root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
                raise ValueError("Prepared source is outside the configured resource roots; prepare sources again")
            selected = safe_path(root, path) if path else root
            if action == "list":
                entries = sorted(selected.iterdir(), key=lambda item: item.name)
                entries = [item for item in entries if item.name != ".git" and not item.is_symlink()]
                return {"ok": True, "resource": resource, "path": path, "entries": [item.name + ("/" if item.is_dir() else "") for item in entries[:limit]],
                        "total": len(entries), "truncated": len(entries) > limit}
            if not path or not selected.is_file() or selected.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Select one text source file of at most 2 MiB")
            content = selected.read_text(encoding="utf-8")
            if action == "snapshot":
                if resource != "manual":
                    raise ValueError("snapshot retains ISA references only; asset execution copies are prepared by Check")
                destination = safe_path(directory, "references/manual/" + path)
                relative = str(destination.relative_to(workspace))
                allowed, reason = is_file_writeable(relative, self.un_write_dirs, self.write_dirs)
                if not allowed:
                    raise ValueError(reason)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    copy_on_write(selected, destination)
                if sha256(destination) != sha256(selected):
                    raise ValueError("Retained ISA reference differs from its source; do not overwrite evidence, start a new run")
                return {"ok": True, "path": relative, "sha256": sha256(destination),
                        "next_action": "Use this workspace-relative path in reference_files; select exact reviewed line ranges."}
            lines = content.splitlines()
            return {"ok": True, "resource": resource, "path": path, "sha256": sha256(selected), "total_lines": len(lines),
                    "start_line": start_line, "lines": lines[start_line - 1:start_line - 1 + limit]}
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {"ok": False, "error_code": "act4_resource_access", "error": str(error),
                    "next_action": "Complete prepare_resources, call ACT4Resources(action='status'), then list a prepared resource and choose an exact path."}


def create_resource_tools(context: PluginContext) -> list[UCTool]:
    """Build resource readers from resolved stage configuration, not environment variables."""
    stages = [stage.as_dict() for stage in context.cfg.get_value("stage", [])]
    for stage in stages:
        for checker in stage.get("checker", []):
            if checker.get("clss") == "ACT4ResourceChecker":
                args = checker["args"]
                return [ACT4Resources(workspace=str(context.workspace), resource_dir=args["resource_dir"],
                                      inputs=dict(args["inputs"]), cache_root=args.get("cache_root", ""),
                                      refs=dict(args.get("refs", {})), write_dirs=list(context.write_dirs),
                                      un_write_dirs=list(context.un_write_dirs), generation=args.get("materialize") is False)]
    return []
