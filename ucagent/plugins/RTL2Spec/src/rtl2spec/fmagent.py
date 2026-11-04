"""Manage FM-Agent source and native installation, independently of document workflows."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .fmagent_config import DEFAULT_BRANCH, DEFAULT_COMMIT, DEFAULT_REPO, FMAgentPaths, bind_paths, plugin_source_root, resolve_paths


SOURCE_FILES = ("main.py", "config.py", "install.sh", "pyproject.toml")
PROBE = '''import importlib.util, sys
if sys.version_info < (3, 12):
    sys.exit(10)
for name in ("openai", "dotenv", "pydantic_settings", "rich", "zstandard", "tree_sitter"):
    if importlib.util.find_spec(name) is None:
        sys.exit(11)
try:
    import config
except (Exception, SystemExit):
    sys.exit(12)
'''


def isolated_environment() -> dict[str, str]:
    """Drop parent interpreter/Git/uv selection but retain native model configuration."""
    environment = dict(os.environ)
    excluded_bins = {str(Path(value) / "bin") for key in ("VIRTUAL_ENV", "CONDA_PREFIX")
                     if (value := environment.get(key))}
    if sys.prefix != sys.base_prefix:
        excluded_bins.add(str(Path(sys.prefix) / "bin"))
    excluded_bins = {str(Path(value).resolve()) for value in excluded_bins}
    environment = {key: value for key, value in environment.items()
                   if not key.startswith(("PYTHON", "GIT_", "UV_", "CONDA_"))
                   and key not in {"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "__PYVENV_LAUNCHER__"}}
    environment["PATH"] = os.pathsep.join(part for part in environment.get("PATH", "").split(os.pathsep)
                                          if part and str(Path(part).expanduser().resolve()) not in excluded_bins)
    environment.update(PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
    return environment


def source_present(root: Path) -> bool:
    """Require the native source entry points, not merely a directory with the right name."""
    return all((root / name).is_file() for name in SOURCE_FILES)


def fetch(paths: FMAgentPaths, repo: str | None = None, branch: str | None = None) -> None:
    """Clone once or reuse a valid checkout without updating, installing, or binding it."""
    root = paths.root
    environment = isolated_environment()
    pinned_commit = DEFAULT_COMMIT if branch is None and (repo is None or repo.removesuffix(".git") == DEFAULT_REPO.removesuffix(".git")) else None
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        if not source_present(root) or not (root / ".git").exists():
            raise ValueError(f"Refusing non-FM-Agent checkout: {root}; select an absent/empty directory or a valid FM-Agent checkout")
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                env=environment, capture_output=True, text=True, timeout=10)
        if result.returncode or Path(result.stdout.strip()).resolve() != root:
            raise ValueError(f"Invalid FM-Agent Git checkout: {root}; existing contents were preserved")
        is_default = root == (plugin_source_root() / "third_party/FM-Agent").resolve()
        for requested, arguments, label in (
            (repo or (DEFAULT_REPO if is_default else None), ["remote", "get-url", "origin"], "origin"),
            ((pinned_commit if is_default else None), ["rev-parse", "HEAD"], "commit"),
            (branch or (DEFAULT_BRANCH if is_default and not pinned_commit else None), ["symbolic-ref", "--short", "-q", "HEAD"], "branch"),
        ):
            if requested is not None:
                actual = subprocess.run(["git", "-C", str(root), *arguments], env=environment,
                                        capture_output=True, text=True, timeout=10)
                if actual.returncode or actual.stdout.strip().removesuffix(".git") != requested.removesuffix(".git"):
                    print(f"Warning: reused {root} has a different {label}; no update or checkout performed", file=sys.stderr)
        print(f"Reusing FM-Agent source: {root} (unchanged)")
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone", "--branch", branch or DEFAULT_BRANCH, "--", repo or DEFAULT_REPO, str(root)]
    result = subprocess.run(command, env=environment)
    if result.returncode:
        raise ValueError(f"FM-Agent fetch failed (exit {result.returncode}); no retry performed; inspect {root} before retrying")
    if pinned_commit:
        result = subprocess.run(["git", "-C", str(root), "checkout", "--detach", pinned_commit], env=environment)
        if result.returncode:
            raise ValueError(f"FM-Agent checkout failed for {pinned_commit} (exit {result.returncode}); no retry, installation or binding performed; inspect {root}")
    if not source_present(root):
        raise ValueError(f"Cloned source lacks FM-Agent entry points: {root}; no installation or binding performed")
    print(f"Fetched FM-Agent source: {root}")


def install(paths: FMAgentPaths, options: list[str]) -> None:
    """Delegate only dependency/tool provisioning to the existing native installer."""
    if not source_present(paths.root):
        raise ValueError(f"FM-Agent source missing at {paths.root}; run rtl2spec fmagent fetch --fmagent-root {shlex.quote(str(paths.root))} first")
    result = subprocess.run(["bash", str(paths.root / "install.sh"), *options], cwd=paths.root,
                            env=isolated_environment())
    if result.returncode:
        raise ValueError(f"FM-Agent native install failed (exit {result.returncode}); no retry or binding performed")
    print(f"Native installation completed: {paths.root / '.venv'}; configure models separately using FM-Agent documentation")


def local_status(paths: FMAgentPaths) -> tuple[str, str]:
    """Check source, interpreter, imports and native config without provisioning/model work."""
    if not source_present(paths.root):
        return "source-missing", f"FM-Agent source missing/incomplete at {paths.root}"
    if not paths.python.is_file() or not os.access(paths.python, os.X_OK):
        return "python-missing", f"Interpreter missing or not executable: {paths.python}"
    environment = isolated_environment()
    environment.update(PYTHONPATH=str(paths.root), PWD=str(paths.root))
    try:
        result = subprocess.run([str(paths.python), "-B", "-c", PROBE], cwd=paths.root, env=environment,
                                capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return "check-failed", "Local check could not finish; inspect the selected interpreter and native configuration"
    states = {
        0: ("ready", "Local Python imports and native configuration are available (model credentials/tools are not checked)"),
        10: ("dependencies-missing", "FM-Agent requires Python >=3.12"),
        11: ("dependencies-missing", "Python dependencies are incomplete; run fmagent install or bind a prepared interpreter"),
        12: ("configuration-invalid", "Native configuration cannot be loaded; inspect FM-Agent configuration/.env locally"),
    }
    return states.get(result.returncode, ("check-failed", "Local check failed; inspect the selected interpreter/native configuration"))


def report_status(paths: FMAgentPaths) -> str:
    """Print safe path provenance and a bounded local readiness summary."""
    print(f"root: {paths.root} [{paths.root_source}]\npython: {paths.python} [{paths.python_source}]\nlocal config: {paths.local_config}")
    state, detail = local_status(paths)
    print(f"status: {state}\n{detail}")
    return state


def confirm_action(action: str, paths: FMAgentPaths, yes: bool) -> None:
    """Ask before fetching source or running the native installer."""
    if action == "fetch":
        print(f"Fetch or reuse FM-Agent source at {paths.root}.")
    else:
        print(f"Run FM-Agent install.sh at {paths.root}; this may download dependencies and update user tools/configuration.")
    if yes:
        return
    if not sys.stdin.isatty():
        raise ValueError("Confirmation required; rerun with -y or --yes in a non-interactive terminal")
    try:
        answer = input("Continue? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in {"y", "yes"}:
        raise ValueError("Operation cancelled")


def main(argv: list[str] | None = None) -> int:
    """Dispatch standalone source, installation, binding and local inspection actions."""
    parser = argparse.ArgumentParser(prog="rtl2spec fmagent", description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("fetch", "install", "bind", "status"):
        child = actions.add_parser(action)
        child.add_argument("--fmagent-root", help="FM-Agent source directory")
        if action != "fetch":
            child.add_argument("--fmagent-python", help="Existing interpreter (install always prepares root/.venv)")
        if action in {"fetch", "install"}:
            child.add_argument("-y", "--yes", action="store_true", help="Confirm without prompting")
        if action == "fetch":
            child.add_argument("--repo", help=f"Clone source (default: {DEFAULT_REPO})")
            child.add_argument("--branch", help=f"Clone branch instead of default pinned commit {DEFAULT_COMMIT}")
        if action == "install":
            for option in ("--with-dsh", "--with-erlang", "--with-chisel"):
                child.add_argument(option, action="store_true", help="Pass this native toolchain option to install.sh")
    args = parser.parse_args(argv)
    if args.action == "install" and args.fmagent_python:
        parser.error("install prepares root/.venv; use bind --fmagent-python to select an existing interpreter")
    try:
        paths = resolve_paths(args.fmagent_root, getattr(args, "fmagent_python", None),
                              use_environment=args.action != "bind")
        if args.action in {"fetch", "install"}:
            confirm_action(args.action, paths, args.yes)
        if args.action == "fetch":
            fetch(paths, args.repo, args.branch)
        elif args.action == "install":
            install(paths, [option for option in ("--with-dsh", "--with-erlang", "--with-chisel")
                            if getattr(args, option[2:].replace("-", "_"))])
        elif args.action == "bind":
            if not source_present(paths.root):
                raise ValueError(f"FM-Agent source missing/incomplete at {paths.root}; fetch source before binding")
            bind_paths(paths)
            print(f"Saved FM-Agent paths to {paths.local_config}\nroot: {paths.root}\npython: {paths.python}")
            if any(os.environ.get(name, "").strip() for name in ("RTL2SPEC_FMAGENT_ROOT", "RTL2SPEC_FMAGENT_PYTHON")):
                print("Warning: process RTL2SPEC_FMAGENT_* values can override this binding", file=sys.stderr)
            state, detail = local_status(paths)
            if state != "ready":
                print(f"Warning: {state}: {detail}", file=sys.stderr)
        else:
            return 0 if report_status(paths) == "ready" else 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"rtl2spec fmagent: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
