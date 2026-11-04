"""Run optional native specification preparation and preserve its original artifacts."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .evidence import output_root
from . import fmagent, fmagent_config


class FMAgentSettings(BaseModel):
    """Accept only the current task-level FM-Agent switches."""

    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    mode: Literal["run", "reuse"] = "run"
    resume: bool = False
    isolate: bool = False
    submodule: str = "."

    @model_validator(mode="after")
    def validate_options(self):
        """Reject escaping scope and meaningless reuse options."""
        scope = Path(self.submodule)
        if not self.submodule.strip() or scope.is_absolute() or ".." in scope.parts:
            raise ValueError("submodule must be a project-relative directory")
        if self.mode == "reuse" and (self.resume or self.isolate):
            raise ValueError("reuse cannot enable resume or isolate")
        return self


def settings_from_cfg(cfg) -> FMAgentSettings:
    """Read resolved runtime configuration without consulting task YAML or bindings."""
    value = cfg.get_value("fmagent", {}) if cfg is not None else {}
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    return FMAgentSettings.model_validate(value)


def workflow_paths(workspace: Path, module: str, output: str, kind: str) -> tuple[Path, Path, Path]:
    """Protect outputs against input-project and actual Git-root overlap."""
    workspace = workspace.resolve()
    project = workspace / (f"inputs/{module}" if kind == "generic" else "third_party/XiangShan")
    if project.is_symlink() or not project.is_dir():
        raise ValueError(f"Input project must be an existing ordinary directory: {project}")
    project = project.resolve()
    if not project.is_relative_to(workspace):
        raise ValueError(f"Input project escapes workspace: {project}")
    for raw in (workspace / output, workspace / (output + "-fmagent")):
        current = workspace
        for part in raw.relative_to(workspace).parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"Output path redirects through a symlink: {current}")
    folder = output_root(workspace, output)
    native = output_root(workspace, output + "-fmagent")
    result = subprocess.run(["git", "-C", str(project), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, timeout=10, env=fmagent.isolated_environment())
    input_root = Path(result.stdout.strip()).resolve() if result.returncode == 0 else project
    for target in (folder, native):
        if target.is_relative_to(input_root) or input_root.is_relative_to(target) or target.is_relative_to(project) or project.is_relative_to(target):
            raise ValueError(f"Output overlaps input project/repository: {target}; input: {input_root}")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise FileExistsError(f"Output must be absent or empty: {target}; preserve it and choose a new output")
    return project, folder, native


def validate_runtime_dirs(project: Path) -> None:
    """Reject redirected or Git-tracked runtime data before launching or moving it."""
    for name in ("fm_agent", ".codegraph"):
        source = project / name
        if source.is_symlink() or (source.exists() and not source.is_dir()):
            raise ValueError(f"Runtime path must be an ordinary directory: {source}")
        result = subprocess.run(["git", "-C", str(project), "ls-files", "-z", "--", name],
                                capture_output=True, timeout=10, env=fmagent.isolated_environment())
        if result.returncode == 0 and result.stdout:
            raise ValueError(f"Runtime path contains Git-tracked data: {source}; preserve it and select an untracked runtime directory")


def rename_no_replace(source: Path, target: Path) -> None:
    """Atomically move on the same filesystem without replacing even an empty directory."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = operation(os.fsencode(source), os.fsencode(target), 4)
    elif sys.platform.startswith("linux"):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = operation(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    else:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is unavailable", str(source))
    if result:
        error = ctypes.get_errno()
        raise OSError(error, f"Cannot move {source} to {target}: {os.strerror(error)}")


def move_runtime_dirs(project: Path, native: Path) -> None:
    """Preserve both actual directories, reporting every partial location on failure."""
    if native.is_symlink() or native.resolve() != native or not native.is_dir():
        raise ValueError(f"Native destination redirected or missing; preserve runtime data at {project}: {native}")
    validate_runtime_dirs(project)
    errors = []
    for name in ("fm_agent", ".codegraph"):
        source, target = project / name, native / name
        if source.exists():
            try:
                rename_no_replace(source, target)
            except OSError as exc:
                errors.append(str(exc))
    if errors:
        locations = {name: {"source": str(project / name), "source_exists": (project / name).exists(),
                            "destination": str(native / name), "destination_exists": (native / name).exists()}
                     for name in ("fm_agent", ".codegraph")}
        raise OSError(f"Runtime move failed: {errors}; preserved locations: {locations}")


def group_is_running(group: int) -> bool:
    """Exclude zombies when checking whether process-group writers remain alive."""
    result = subprocess.run(["ps", "-eo", "pgid=,stat="], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError("Cannot confirm FM-Agent process-group shutdown")
    return any(len(fields := line.split()) == 2 and fields[0] == str(group) and not fields[1].startswith("Z")
               for line in result.stdout.splitlines())


def stop_writers(process: subprocess.Popen) -> None:
    """Reap the native parent and stop all remaining same-group writers with bounded waits."""
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not group_is_running(process.pid):
            process.wait(timeout=2)
            return
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            process.poll()
            if not group_is_running(process.pid):
                process.wait(timeout=2)
                return
            time.sleep(0.05)
    raise RuntimeError(f"FM-Agent writers may still be active (group {process.pid}); runtime data not moved")


def prepare(workspace: Path, module: str, output: str, kind: str, settings: FMAgentSettings) -> dict:
    """Execute run/reuse once, stop writers and permanently preserve all actual runtime data."""
    project, folder, native = workflow_paths(workspace, module, output, kind)
    scope = project / settings.submodule
    if not scope.is_dir() or not scope.resolve().is_relative_to(project):
        raise ValueError(f"submodule must resolve to a directory within {project}: {scope}")
    validate_runtime_dirs(project)
    command = None
    paths = None
    if settings.mode == "reuse":
        if not (project / "fm_agent").is_dir():
            raise ValueError(f"reuse requires existing {project / 'fm_agent'}; restore a copy manually or choose run")
    else:
        paths = fmagent_config.resolve_paths()
        state, detail = fmagent.local_status(paths)
        if state != "ready":
            raise ValueError(f"FM-Agent environment unavailable: {detail}; use rtl2spec fmagent fetch/install/bind/status")
        command = [str(paths.python), str(paths.root / "main.py"), str(project), "--plugin", "chip", "--only-spec"]
        if settings.submodule != ".":
            command += ["--submodule", settings.submodule]
        if settings.resume:
            command.append("--resume")
        if settings.isolate:
            command.append("--isolate")
    native.mkdir(parents=True, exist_ok=True)
    process = None
    previous = {}
    permissions = []
    failure = None

    def cancel(signum, frame):
        """Turn a catchable termination into cancellation with local cleanup."""
        raise KeyboardInterrupt(f"FM-Agent preparation cancelled by signal {signum}")

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, cancel)
        entries = [project]
        for name in ("fm_agent", ".codegraph"):
            source = project / name
            if source.exists():
                entries.extend([source, *source.rglob("*")])
        for path in entries:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f"Runtime operation path must be a regular file or directory: {path}")
            if not mode & stat.S_IWUSR:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                permissions.append((descriptor, stat.S_IMODE(os.fstat(descriptor).st_mode), path))
                os.fchmod(descriptor, stat.S_IMODE(mode) | stat.S_IWUSR)
        if command:
            with (native / "pipeline.log").open("xb") as log:
                process = subprocess.Popen(command, cwd=paths.root, env=fmagent.isolated_environment(),
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                code = process.wait()
                if code:
                    raise RuntimeError(f"FM-Agent exited with status {code}; inspect {native / 'pipeline.log'}")
    except BaseException as exc:
        failure = exc
    finally:
        try:
            for signum in previous:
                signal.signal(signum, signal.SIG_IGN)
            try:
                if process is not None:
                    stop_writers(process)
            except BaseException as exc:
                if failure is None:
                    failure = exc
                else:
                    failure.add_note(str(exc))
            else:
                try:
                    move_runtime_dirs(project, native)
                except BaseException as exc:
                    if failure is None:
                        failure = exc
                    else:
                        failure.add_note(str(exc))
        finally:
            restoration_errors = []
            for descriptor, mode, original in reversed(permissions):
                try:
                    os.fchmod(descriptor, mode)
                except OSError as exc:
                    restoration_errors.append(f"{original}: {exc}")
                finally:
                    os.close(descriptor)
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            if restoration_errors:
                error = OSError(f"Cannot restore preserved runtime permissions: {restoration_errors}")
                if failure is None:
                    failure = error
                else:
                    failure.add_note(str(error))
    if failure is not None:
        raise failure
    extracted = native / "fm_agent/extracted_functions"
    references, specs = [], []
    if extracted.exists():
        if extracted.is_symlink() or not extracted.is_dir():
            raise ValueError(f"Artifact root must be an ordinary directory: {extracted}")
        for path in sorted(extracted.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Artifact paths must not redirect: {path}")
            if path.is_file() and (path.name.endswith("_spec.md") or path.name.endswith("_info.md")):
                references.append(path.relative_to(workspace).as_posix())
                if path.name.endswith("_spec.md"):
                    specs.append(path)
    return {"project": project, "output": folder, "native": native, "extracted": extracted,
            "specs": specs, "references": references}


def export_specs(prepared: dict) -> dict:
    """Copy the cached spec set byte-for-byte without overwriting any export directory."""
    target = prepared["output"] / "specs"
    if prepared["output"].resolve() != prepared["output"]:
        raise ValueError(f"Spec output parent redirects: {prepared['output']}")
    target.mkdir(parents=True, exist_ok=False)
    for source in prepared["specs"]:
        if source.is_symlink() or not source.resolve().is_relative_to(prepared["extracted"]):
            raise ValueError(f"Spec path redirects outside original artifacts: {source}")
        destination = target / source.relative_to(prepared["extracted"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
    return {"spec_count": len(prepared["specs"]), "output": str(target)}
