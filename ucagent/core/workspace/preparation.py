"""Workflow-owned preparation contracts and bounded workspace copying."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import shutil

from pydantic import BaseModel, ConfigDict


class PreparationOptions(BaseModel):
    """Reject undeclared workflow preparation options."""
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass
class WorkspacePreparation:
    """Give a workflow isolated paths and managed progress, cancellation and commands."""
    source: Path
    workspace: Path
    dut_name: str
    options: BaseModel
    progress: Callable[[str], None]
    check_cancelled: Callable[[], None]
    run_command: Callable
    cache: Path | None = None

    def copy(self, source, destination):
        """Copy inputs without following directory links or importing runtime state."""
        source, destination = Path(source), Path(destination)
        if not source.resolve().is_relative_to(self.source.resolve()):
            raise ValueError(f"Source symlink escapes workspace: {source.name}")
        if not destination.resolve().is_relative_to(self.workspace.resolve()):
            raise ValueError("Preparation destination escapes workspace")
        self.check_cancelled()
        if source.is_symlink() and source.is_dir():
            raise ValueError(f"Source directory symlink cannot be copied safely: {source.name}")
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Copy in bounded chunks so large model libraries remain cancellable.
            with source.open("rb") as src, destination.open("wb") as dst:
                while data := src.read(1024 * 1024):
                    self.check_cancelled()
                    dst.write(data)
            shutil.copystat(source, destination)
            return
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            if child.name in {".ucagent", ".git", "__pycache__", ".venv"} or child.name.endswith((".pyc", "_cache")):
                continue
            self.copy(child, destination / child.name)


def rtl_source(source, dut_name):
    """Locate a unique RTL root in a raw DUT or a prepared verification workspace."""
    source = Path(source)
    roots = [source / f"{dut_name}_RTL", source, source / dut_name]
    for root in roots:
        if any((root / f"{dut_name}{suffix}").is_file() for suffix in (".v", ".sv")):
            return root
    raise ValueError(f"No {dut_name}.v or {dut_name}.sv found; select a DUT source with ListDUTs or provide source_workspace.")
