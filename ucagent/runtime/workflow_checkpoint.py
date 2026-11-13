"""Exclusive atomic workflow-chain checkpoints and conservative restart validation."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading

from ucagent.core.workflow.contracts import workflow_fingerprint


class WorkflowCheckpoint:
    """Keep one process as chain writer and require reconciled resource ownership on restart."""

    def __init__(self, root):
        """Acquire ownership before reading or replacing any chain state."""
        self.root = Path(root).absolute()
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError("Chain root must not contain symlinks")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "chain.json"
        self._lock = threading.RLock()
        self._file = os.fdopen(os.open(self.root / ".owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise RuntimeError("Workflow chain already has an active owner") from None

    def save(self, state):
        """Fsync an atomic replacement so a crash cannot leave a partial checkpoint."""
        with self._lock:
            temporary = self.root / "chain.json.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def load(self, catalog, execution_fingerprint):
        """Reject changed policy/configuration and unresolved orphan processes before recovery."""
        if self.path.is_symlink():
            raise ValueError("Chain checkpoint must not be a symlink")
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if state.get("schema") != 1 or not state.get("runs"):
            raise ValueError("Invalid workflow chain checkpoint")
        if not state.get("quiescent"):
            raise RuntimeError("Unreconciled chain shutdown: inspect and stop prior external sessions before recovery")
        if state.get("policy_fingerprint") != policy_fingerprint(catalog.settings):
            raise ValueError("Workflow chain policy changed; refusing checkpoint recovery")
        if state.get("execution_fingerprint") != execution_fingerprint:
            raise ValueError("Workflow execution configuration changed; refusing checkpoint recovery")
        for run in state["runs"]:
            entry = catalog.entries.get(run["workflow_ref"])
            if entry is None or workflow_fingerprint(entry, catalog.settings.target_configs.get(entry.ref)) != run["fingerprint"]:
                raise ValueError("Workflow source/configuration changed; refusing checkpoint recovery")
        return state

    def close(self):
        """Release chain ownership only after all instance resources are reconciled."""
        self._file.close()


def policy_fingerprint(settings):
    """Exclude storage/reattachment paths while retaining all authorization and budget policy."""
    value = settings.model_dump(exclude={"chain_root", "resume_chain"})
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
