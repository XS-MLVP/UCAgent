"""Prepare Make and interactive task workspaces through the same plugin contract."""
from pathlib import Path
import tempfile
from uuid import uuid4

from ucagent import load_plugin
from ucagent import PreparationJob


def prepare_workflow_workspace(*, plugin, workflow, source, workspace, dut, options=None, timeout=900):
    """Prepare in a temporary sibling, then publish with reversible backups of replaced assets."""
    loaded = load_plugin(plugin)
    selected = next((w for w in loaded.plugin.workflows if w.name == workflow), None)
    if selected is None or selected.prepare_workspace is None:
        raise ValueError("Selected workflow has no workspace preparation hook")
    source, target = Path(source).resolve(), Path(workspace).resolve()
    if not source.is_dir() or target == source or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Source and destination must be separate existing-source trees")
    if not (target / ".ucagent").resolve().is_relative_to(target):
        raise ValueError("Destination runtime directory must stay inside the workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ucagent-prepare-", dir=target.parent) as temporary:
        prepared = Path(temporary) / "workspace"
        job = PreparationJob(selected, source, prepared, dut, options or {},
                             timeout=timeout, progress=print, cache=target)
        job.thread.start()
        try:
            while not job.done.wait(.2):
                pass
        except KeyboardInterrupt:
            job.cancelled.set()
            job.thread.join()
            raise
        if job.error:
            target.mkdir(parents=True, exist_ok=True)
            if job.log_path.exists():
                log = target / ".ucagent/preparation-failed.log"
                log.parent.mkdir(exist_ok=True)
                log.write_bytes(job.log_path.read_bytes())
            raise RuntimeError(f"{job.error}; retained command log: {target / '.ucagent/preparation-failed.log'}")
        target.mkdir(parents=True, exist_ok=True)
        backup = target / ".ucagent/preparation-backups" / uuid4().hex
        published, saved = [], []
        try:
            for path in sorted(prepared.iterdir()):
                members = list(path.iterdir()) if path.name == ".ucagent" else [path]
                for member in members:
                    relative = member.relative_to(prepared)
                    destination = target / relative
                    if not destination.resolve().is_relative_to(target):
                        raise ValueError("Preparation destination escapes workspace")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists() or destination.is_symlink():
                        previous = backup / relative
                        previous.parent.mkdir(parents=True, exist_ok=True)
                        destination.rename(previous)
                        saved.append((previous, destination))
                    member.rename(destination)
                    published.append((destination, member))
        except Exception:
            for destination, original in reversed(published):
                destination.rename(original)
            for previous, destination in reversed(saved):
                previous.rename(destination)
            raise
        if job.log_path.exists():
            log = target / ".ucagent/preparation.log"
            log.parent.mkdir(exist_ok=True)
            log.write_bytes(job.log_path.read_bytes())
    return target
