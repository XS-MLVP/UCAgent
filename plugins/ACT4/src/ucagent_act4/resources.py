"""Reuse pinned source repositories and isolate writable ACT4 work without hardlinks."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from .xiangshan_bundle import execute, safe_path, sha256, write_json


REPOSITORIES = {
    "act4": ("riscv-arch-test", "https://github.com/riscv/riscv-arch-test.git", "act4"),
    "manual": ("riscv-isa-manual", "https://github.com/riscv/riscv-isa-manual.git", "HEAD"),
    "xiangshan": ("XiangShan", "https://github.com/OpenXiangShan/XiangShan.git", "kunminghu-v3"),
}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "baseline", "candidate", "bundle",
             "delivery", "experiments", "references", "isa-references", "work", "build", "elf", "bin", "disass", ".ucagent"}


def copy_on_write(source: Path, destination: Path) -> None:
    """Copy one file using filesystem reflinks when available, never writable hardlinks."""
    with source.open("rb") as reader, destination.open("xb") as writer:
        try:
            fcntl.ioctl(writer.fileno(), 0x40049409, reader.fileno())
        except OSError as error:
            if error.errno not in {errno.EOPNOTSUPP, errno.EXDEV, errno.EINVAL, errno.ENOTTY, errno.ENOSYS}:
                raise
            shutil.copyfileobj(reader, writer)
    shutil.copystat(source, destination)


def resource_locations(workspace: Path, setting: str = "") -> tuple[Path, Path]:
    """Choose a shared output-level cache, or an explicitly configured absolute cache root."""
    search = next((path for path in (workspace, *workspace.parents) if path.name == "output"), workspace.parent)
    cache = Path(setting).expanduser() if setting else search / ".act4-cache"
    if not cache.is_absolute():
        cache = workspace / cache
    if cache.is_symlink() or any(parent.is_symlink() for parent in cache.parents):
        raise ValueError("ACT4_RESOURCE_ROOT must not contain symlinks")
    return cache.absolute(), search


def discover_resources(search: Path, names: set[str], max_depth: int = 6) -> list[Path]:
    """Find bounded existing resource directories without walking source, build, or cache trees."""
    found, pending, visited = [], [(search, 0)], 0
    while pending and visited < 10000:
        directory, depth = pending.pop()
        visited += 1
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for path in entries:
            if path.is_symlink() or not path.is_dir():
                continue
            if path.name in names:
                found.append(path)
            elif depth < max_depth and not path.name.startswith((".", "work_")) and path.name not in SKIP_DIRS | {item[0] for item in REPOSITORIES.values()}:
                pending.append((path, depth + 1))
    return sorted(found)


def git_text(root: Path, *arguments: str) -> str:
    """Read bounded Git metadata without modifying the source checkout or optional index locks."""
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *arguments], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def input_path(workspace: Path, configured: str) -> Path:
    """Resolve an explicitly configured read-only root, including external absolute inputs."""
    if not isinstance(configured, str) or not configured.strip() or ".." in Path(configured).parts:
        raise ValueError("Input roots must be explicit nonempty paths without parent traversal")
    path = Path(configured).expanduser()
    if not path.is_absolute():
        return safe_path(workspace, configured)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Read-only input roots must not contain symlinks")
    return path


def repository_identity(root: Path, *, clean: bool, require_submodules: bool = True) -> dict:
    """Identify a checkout and recursive submodule pins, rejecting incomplete reusable sources."""
    if root.is_symlink() or not root.is_dir() or not (root / ".git").exists():
        raise ValueError(f"Not a regular Git checkout: {root}")
    head = git_text(root, "rev-parse", "HEAD")
    modules = git_text(root, "submodule", "status", "--recursive")
    if any(line[:1] in ({"-", "+", "U"} if require_submodules else {"+", "U"}) for line in modules.splitlines()):
        raise ValueError(f"Incomplete or changed submodules: {root}")
    if clean and git_text(root, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none"):
        raise ValueError(f"Shared checkout has local changes; do not overwrite it: {root}")
    return {"head": head, "submodules": modules}


def clone_local(source: Path, target: Path, log_dir: Path, deadline: float, process_started=None, *, require_submodules: bool = True) -> None:
    """Clone pinned local repositories and their submodules without network or shared writable files."""
    pending = [(source, target)]
    while pending:
        original, destination = pending.pop()
        remaining = int(deadline - time.monotonic())
        if remaining < 1:
            raise ValueError("Resource preparation timed out; retry preparation")
        index = hashlib.sha256(str(destination).encode()).hexdigest()[:16]
        result = execute(["git", "clone", "--no-hardlinks", "--dissociate", "--no-checkout", str(original), str(destination)],
                         log_dir, log_dir / f"clone-{index}.log", remaining, process_started)
        if result["status"] != "passed":
            raise ValueError(f"Cannot clone local source; inspect clone-{index}.log")
        head = git_text(original, "rev-parse", "HEAD")
        result = execute(["git", "-C", str(destination), "checkout", "--detach", head], log_dir,
                         log_dir / f"checkout-{index}.log", max(1, int(deadline - time.monotonic())), process_started)
        if result["status"] != "passed":
            raise ValueError(f"Cannot check out pinned source; inspect checkout-{index}.log")
        try:
            remote = git_text(original, "remote", "get-url", "origin")
        except subprocess.CalledProcessError:
            remote = str(original)
        git_text(destination, "remote", "set-url", "origin", remote)
        if (original / ".gitmodules").is_file():
            modules = git_text(original, "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$")
            for entry in modules.splitlines():
                key, relative = entry.split(" ", 1)
                old = safe_path(original, relative)
                new = safe_path(destination, relative)
                if not (old / ".git").exists():
                    if require_submodules:
                        raise ValueError(f"Initialize required ACT submodule before reuse: {old}")
                    continue
                if new.is_dir() and not any(new.iterdir()):
                    new.rmdir()
                git_text(destination, "config", key.removesuffix(".path") + ".url", str(old))
                pending.append((old, new))


def prepare_sources(workspace: Path, directory: Path, cache: Path, search: Path, inputs: dict,
                    refs: dict, workflow: str, timeout: int, process_started=None, *, materialize: bool = True) -> dict:
    """Prepare missing inputs once, import clean historical checkouts, and record exact provenance."""
    directory.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    if cache.stat().st_uid != os.getuid():
        raise ValueError("The shared resource directory must belong to the current user")
    deadline = time.monotonic() + timeout
    records = {}
    with safe_path(cache, ".resources.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another run is preparing shared sources; retry after it finishes") from None
        for identifier in sorted(inputs, key=lambda name: name == "input"):
            configured = inputs[identifier]
            if identifier == "input" and input_path(workspace, configured) == input_path(workspace, inputs["act4"]):
                records[identifier] = {**records["act4"], "configured": configured}
                continue
            original = input_path(workspace, configured)
            if original.is_dir():
                records[identifier] = {"configured": configured, "path": str(original.resolve()), "origin": "provided"}
                if (original / ".git").exists():
                    identity = repository_identity(original, clean=False, require_submodules=identifier == "act4")
                    if identifier in REPOSITORIES:
                        ref = refs.get(identifier, REPOSITORIES[identifier][2])
                        if (not isinstance(ref, str) or not ref.strip() or ref.startswith("-")
                                or any(char.isspace() for char in ref)):
                            raise ValueError(f"Invalid resource revision for {identifier}")
                        try:
                            requested_head = git_text(original, "rev-parse", ref + "^{commit}")
                        except (OSError, subprocess.SubprocessError) as error:
                            raise ValueError(f"Cannot resolve requested {identifier} revision {ref!r} in {original}") from error
                        if identity["head"] != requested_head:
                            raise ValueError(f"Provided {identifier} checkout is at {identity['head']}, not requested {ref} ({requested_head})")
                    records[identifier]["identity"] = identity
                    records[identifier]["require_submodules"] = identifier == "act4"
                continue
            if identifier not in REPOSITORIES or configured != REPOSITORIES[identifier][0]:
                raise ValueError(f"Missing explicitly selected {identifier} input: {configured}")
            name, url, default_ref = REPOSITORIES[identifier]
            ref = refs.get(identifier, default_ref)
            if not isinstance(ref, str) or not ref.strip() or ref.startswith("-") or any(char.isspace() for char in ref):
                raise ValueError(f"Invalid resource revision for {identifier}")
            key = name + "-" + hashlib.sha256(f"{url}\n{ref}".encode()).hexdigest()[:20]
            entry = safe_path(cache, "repositories/" + key)
            destination = safe_path(entry, "source")
            metadata = safe_path(entry, "receipt.json")
            origin = "shared_cache"
            if entry.exists():
                saved = json.loads(metadata.read_text(encoding="utf-8"))
                if saved["url"] != url or saved["ref"] != ref or saved["identity"] != repository_identity(destination, clean=True, require_submodules=identifier == "act4"):
                    raise ValueError(f"Shared source changed: {destination}; choose a new cache or restore the recorded source")
            else:
                entry.parent.mkdir(parents=True, exist_ok=True)
                rejected, selected = [], None
                for candidate in discover_resources(search, {name}):
                    if time.monotonic() >= deadline:
                        raise ValueError("Resource discovery timed out; narrow the shared search root or provide an input")
                    try:
                        identity = repository_identity(candidate, clean=True, require_submodules=identifier == "act4")
                        remote = git_text(candidate, "remote", "get-url", "origin").removesuffix(".git").rstrip("/")
                        if remote != url.removesuffix(".git"):
                            continue
                        if ref != "HEAD" and git_text(candidate, "rev-parse", ref + "^{commit}") != identity["head"]:
                            continue
                        selected = candidate
                        break
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        rejected.append({"path": str(candidate), "reason": str(error)[:300]})
                with tempfile.TemporaryDirectory(prefix=".prepare-", dir=entry.parent) as temporary:
                    staging = Path(temporary) / "source"
                    if selected is not None:
                        clone_local(selected, staging, directory, deadline, process_started, require_submodules=identifier == "act4")
                        if repository_identity(selected, clean=True, require_submodules=identifier == "act4") != repository_identity(staging, clean=True, require_submodules=identifier == "act4"):
                            raise ValueError("Local source changed during import; retry with a stable checkout")
                        origin = "existing_output"
                    else:
                        pinned_commit = re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", ref) is not None
                        argv = ["git", "clone"]
                        if pinned_commit:
                            argv += ["--no-checkout"]
                        elif ref != "HEAD":
                            argv += ["--branch", ref]
                        remaining = int(deadline - time.monotonic())
                        if remaining < 1:
                            raise ValueError("Resource preparation timed out; retry preparation")
                        result = execute([*argv, url, str(staging)], directory, directory / f"fetch-{identifier}.log",
                                         remaining, process_started)
                        if result["status"] != "passed":
                            raise ValueError(f"Cannot obtain {identifier}; inspect fetch-{identifier}.log or provide a pinned local input")
                        commands = []
                        if pinned_commit:
                            available = subprocess.run(["git", "-C", str(staging), "cat-file", "-e", ref + "^{commit}"],
                                                       capture_output=True, timeout=30)
                            if available.returncode:
                                commands.append(("pin-fetch", ["git", "fetch", "origin", ref]))
                            commands.append(("pin-checkout", ["git", "checkout", "--detach", ref]))
                        if identifier == "act4":
                            commands.append(("submodules", ["git", "submodule", "update", "--init", "--recursive"]))
                        for step, command in commands:
                            remaining = int(deadline - time.monotonic())
                            if remaining < 1:
                                raise ValueError("Resource preparation timed out; retry preparation")
                            result = execute(command, staging, directory / f"{step}-{identifier}.log", remaining, process_started)
                            if result["status"] != "passed":
                                raise ValueError(f"Cannot obtain {identifier}; inspect {step}-{identifier}.log or provide a pinned local input")
                        if pinned_commit and git_text(staging, "rev-parse", "HEAD").lower() != ref.lower():
                            raise ValueError(f"Downloaded {identifier} does not match the requested commit {ref}")
                        origin = "download"
                    saved = {"url": url, "ref": ref, "identity": repository_identity(staging, clean=True, require_submodules=identifier == "act4"),
                             "imported_from": str(selected) if selected else url, "rejected": rejected[:30]}
                    write_json(Path(temporary) / "receipt.json", saved)
                    Path(temporary).rename(entry)
            records[identifier] = {"configured": configured, "path": str(destination), "origin": origin,
                                   "identity": saved["identity"], "url": url, "ref": ref, "require_submodules": identifier == "act4"}
            if workflow == "generation" and identifier == "act4" and materialize:
                with tempfile.TemporaryDirectory(prefix=".act4-copy-", dir=workspace) as temporary:
                    staging = Path(temporary) / name
                    clone_local(destination, staging, directory, deadline, process_started)
                    staging.rename(original)
                records[identifier].update(path=str(original), origin="writable_copy", shared_source=str(destination))
    result = {"schema_version": 1, "cache_root": str(cache), "search_root": str(search), "resources": records}
    write_json(directory / "receipt.json", result)
    return result


def verify_reference_snapshots(directory: Path, data: dict) -> None:
    """Require retained ISA files to remain exact copies of the registered read-only manual."""
    references = safe_path(directory, "references")
    if not references.exists():
        return
    manual = input_path(directory, data["resources"]["manual"]["path"])
    for current, children, names in os.walk(references, followlinks=False):
        for name in children:
            safe_path(references, str((Path(current) / name).relative_to(references)))
        for name in names:
            relative = str((Path(current) / name).relative_to(references))
            snapshot = safe_path(references, relative)
            if not relative.startswith("manual/") or not snapshot.is_file():
                raise ValueError(f"Unexpected ISA reference snapshot: {relative}")
            source = safe_path(manual, relative.removeprefix("manual/"))
            if not source.is_file() or sha256(snapshot) != sha256(source):
                raise ValueError(f"ISA reference differs from its registered source: {relative}; do not edit retained evidence")


def resolve_source(workspace: Path, configured: str, directory: Path, get_value=None) -> Path:
    """Resolve only a configured input or its prepared shared replacement, never an output path."""
    receipt = directory / "receipt.json"
    if receipt.is_file():
        if get_value is not None and get_value(f"act4_resources:{directory.resolve()}", None) != sha256(receipt):
            raise ValueError("Source preparation evidence changed; return to prepare_resources")
        data = json.loads(receipt.read_text(encoding="utf-8"))
        verify_reference_snapshots(directory, data)
        for record in data["resources"].values():
            if record["configured"] == configured:
                source = input_path(workspace, record["path"])
                if source.is_symlink() or not source.is_dir():
                    raise ValueError("Prepared source disappeared or became a symlink; return to prepare_resources")
                if "identity" in record and record["origin"] != "writable_copy":
                    if repository_identity(source, clean=record["origin"] != "provided", require_submodules=record["require_submodules"]) != record["identity"]:
                        raise ValueError("Prepared source changed; restore the recorded pin or start a new run")
                return source
    return input_path(workspace, configured)
