"""Preview or apply an explicit module delivery bundle with complete conflict preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def file_state(path: Path) -> dict | None:
    """Return the regular-file identity used by delivery preconditions."""

    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic-link target: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Target is not a regular file: {path}")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": "100755" if path.stat().st_mode & 0o111 else "100644"}


def apply_bundle(bundle: Path, target: Path, *, apply: bool = False, verify_revision: bool = True) -> dict:
    """Validate every path and source hash before optionally updating selected files."""

    bundle, target = bundle.resolve(), target.resolve()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if target.is_relative_to(bundle) or bundle.is_relative_to(target):
        raise ValueError("Bundle and target must be non-overlapping directories")
    if verify_revision and (target / ".git").exists():
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            revision = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"],
                                               env=env, text=True, stderr=subprocess.PIPE).strip()
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"Cannot read the target Git revision: {(exc.stderr or '')[-800:]}") from exc
        if revision != manifest["base_commit"]:
            raise ValueError("Target HEAD differs from the delivery base_commit")
    changes, seen = [], set()
    for change in manifest["changes"]:
        name = change["path"]
        relative = Path(name)
        if not name or relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts or name in seen:
            raise ValueError(f"Invalid or duplicate delivery path: {name}")
        seen.add(name)
        destination = target / relative
        source = bundle / "files" / relative
        for path, root in ((destination, target), (source, bundle)):
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Delivery path escapes its root: {name}")
            for parent in (path, *path.parents):
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ValueError(f"Delivery path traverses a symbolic link: {name}")
        if file_state(destination) != change["before"]:
            raise ValueError(f"Target content or executable mode conflicts: {name}")
        if change["action"] not in {"add", "replace", "delete"}:
            raise ValueError(f"Invalid change action: {name}")
        if change["action"] != "delete" and file_state(source) != change["after"]:
            raise ValueError(f"Bundle content changed: {name}")
        changes.append((change, source, destination))
    if not apply:
        return {"status": "preview", "changes": manifest["changes"]}
    # Preflight is complete before the first target mutation. Keep rollback copies
    # for ordinary I/O failures; interrupted application can be inspected manually.
    with tempfile.TemporaryDirectory(prefix="repo-module-apply-") as name:
        backup = Path(name)
        completed = []
        try:
            for index, (change, source, destination) in enumerate(changes):
                if destination.exists():
                    shutil.copy2(destination, backup / str(index))
                completed.append((index, change, destination))
                if change["action"] == "delete":
                    destination.unlink()
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        except Exception:
            for index, change, destination in reversed(completed):
                if change["before"] is None:
                    destination.unlink(missing_ok=True)
                elif (backup / str(index)).exists():
                    shutil.copy2(backup / str(index), destination)
            raise
    return {"status": "applied", "files": len(changes)}


def main() -> None:
    """Default to a preview; require --apply and an explicit target for writes."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply_bundle(Path(__file__).resolve().parent, args.target, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
