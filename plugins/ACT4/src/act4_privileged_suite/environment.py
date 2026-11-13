"""Prepare reusable ACT4 tools and consume their measured environment without global mutation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
import time

import yaml

from .xiangshan_bundle import execute, safe_path, sha256, write_json


TOOL_IDS = {"python", "bash", "git", "curl", "make", "uv", "compiler", "reference", "lint"}
HOST_PROBES = {
    "python": [sys.executable, "--version"], "bash": ["bash", "--version"],
    "git": ["git", "--version"], "curl": ["curl", "--version"],
    "make": ["make", "--version"], "uv": ["uv", "--version"],
    "compiler": ["riscv64-unknown-elf-gcc", "--version"],
    "reference": ["sail_riscv_sim", "--version"], "lint": ["ruff", "--version"],
    "questa": ["vsim", "-version"], "vcs": ["vcs", "-ID"], "xcelium": ["xrun", "-version"],
}
COMMERCIAL = {"questa", "vcs", "xcelium"}
INSTALL_COMMANDS = {"curl", "tar", "git", "pip", "pip3", "python", "python3", "{PYTHON}", "cp", "mkdir", "chmod"}
PROBE_FLAGS = {"--version", "-version", "-V", "--help", "-h"}


def state_key(directory: Path) -> str:
    """Identify the preparation receipt independently of the consuming workflow phase."""
    return f"act4_environment:{directory.resolve()}"


def _validate_prefix_path(value: str, identifier: str) -> None:
    """Require installer destinations to remain below the isolated tool prefix."""
    prefix = "{PREFIX}/"
    relative = value[len(prefix):] if value.startswith(prefix) else ""
    if not relative or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError(f"{identifier} installer paths must remain below {{PREFIX}}")


def read_plan(directory: Path) -> dict:
    """Validate explicit version probes, installation recipes, and private installation paths."""
    plan = yaml.safe_load(safe_path(directory, "plan.yaml").read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1 or set(plan) != {"schema_version", "tools"}:
        raise ValueError("plan.yaml requires schema_version: 1 and tools")
    if not isinstance(plan["tools"], list) or not plan["tools"]:
        raise ValueError("plan.yaml tools must be a nonempty list")
    found = set()
    for tool in plan["tools"]:
        if not isinstance(tool, dict):
            raise ValueError("Each tool must be a mapping")
        required = {"id", "version", "basis", "probe", "expected_output", "install", "bin_dirs", "storage"}
        if required - tool.keys() or tool.keys() - required - {"unavailable_reason"}:
            raise ValueError(f"Tool requires {sorted(required)}; only unavailable_reason is optional")
        identifier = tool["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", identifier) or identifier in found or identifier in COMMERCIAL:
            raise ValueError("Use unique tool IDs; commercial simulators are probe-only")
        found.add(identifier)
        for field in ("version", "basis", "expected_output"):
            if not isinstance(tool[field], str) or not tool[field].strip():
                raise ValueError(f"{identifier}.{field} must be nonempty")
        re.compile(tool["expected_output"])
        if not isinstance(tool["storage"], str) or tool["storage"] not in {"persistent", "temporary"}:
            raise ValueError(f"{identifier}.storage must be persistent or temporary")
        if not isinstance(tool["install"], list):
            raise ValueError(f"{identifier}.install must be an ordered list of argv lists")
        for argv in [tool["probe"], *tool["install"]]:
            if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
                raise ValueError(f"{identifier} commands must be nonempty argv lists")
        probe = tool["probe"]
        if (probe[0] != "{PYTHON}" and (Path(probe[0]).name != probe[0] or "/" in probe[0] or "\\" in probe[0])) or len(probe) != 2 or probe[1] not in PROBE_FLAGS:
            raise ValueError(f"{identifier} probes must call a PATH executable with one version/help flag")
        for argv in tool["install"]:
            command = argv[0]
            if command not in INSTALL_COMMANDS:
                raise ValueError(f"{identifier} installer executable is not allowed: {argv[0]}")
            arguments = argv[1:]
            if command in {"python", "python3", "{PYTHON}"} and not (len(arguments) >= 5 and arguments[:2] == ["-m", "pip"] and "install" in arguments and any(arguments[index:index + 2] == ["--prefix", "{PREFIX}"] for index in range(len(arguments) - 1))):
                raise ValueError(f"{identifier} Python installers may only run pip install --prefix {{PREFIX}}; scripts are not allowed")
            if command in {"pip", "pip3"} and not ("install" in arguments and any(arguments[index:index + 2] == ["--prefix", "{PREFIX}"] for index in range(len(arguments) - 1))):
                raise ValueError(f"{identifier} pip installers require install --prefix {{PREFIX}}")
            if command == "curl":
                outputs = [arguments[index + 1] for index in range(len(arguments) - 1) if arguments[index] in {"-o", "--output"}]
                if len(outputs) != 1 or not any(argument.startswith("https://") for argument in arguments):
                    raise ValueError(f"{identifier} downloads must write directly under {{PREFIX}}")
                _validate_prefix_path(outputs[0], identifier)
            if command == "tar":
                destinations = [arguments[index + 1] for index in range(len(arguments) - 1) if arguments[index] == "-C"]
                if len(destinations) != 1:
                    raise ValueError(f"{identifier} archives must extract under {{PREFIX}}")
                _validate_prefix_path(destinations[0], identifier)
            if command == "git":
                if "clone" not in arguments:
                    raise ValueError(f"{identifier} Git installers must clone under {{PREFIX}}")
                _validate_prefix_path(arguments[-1], identifier)
            if command == "cp":
                _validate_prefix_path(arguments[-1], identifier)
            if command == "mkdir" and not all(argument.startswith("-") or argument.startswith("{PREFIX}/") for argument in arguments):
                raise ValueError(f"{identifier} directories must be created under {{PREFIX}}")
            if command == "mkdir":
                for argument in arguments:
                    if not argument.startswith("-"):
                        _validate_prefix_path(argument, identifier)
            if command == "chmod":
                if len(arguments) != 2:
                    raise ValueError(f"{identifier} chmod requires one mode and one prefix-scoped target")
                _validate_prefix_path(arguments[-1], identifier)
        if not isinstance(tool["bin_dirs"], list) or not tool["bin_dirs"]:
            raise ValueError(f"{identifier}.bin_dirs must be a nonempty list")
        for name in tool["bin_dirs"]:
            safe_path(directory, name)
        if "unavailable_reason" in tool and (not isinstance(tool["unavailable_reason"], str) or not tool["unavailable_reason"].strip()):
            raise ValueError(f"{identifier}.unavailable_reason must explain the unavailable installation route")
    if TOOL_IDS - found:
        raise ValueError(f"Plan missing tools: {sorted(TOOL_IDS - found)}")
    return plan


def prepared_environment(directory: Path, get_value=None) -> dict[str, str]:
    """Load verified tool paths for subprocesses, preserving the caller's other environment values."""
    environment = dict(os.environ)
    receipt_path = safe_path(directory, "receipt.json")
    if not receipt_path.exists():
        if get_value is not None and get_value(state_key(directory), None):
            raise ValueError("Environment receipt is missing; return to prepare_environment and prepare again")
        return environment
    if get_value is not None and get_value(state_key(directory), None) != sha256(receipt_path):
        raise ValueError("Environment receipt changed; return to prepare_environment and prepare again")
    receipt = json.loads(receipt_path.read_text())
    environment["PATH"] = os.pathsep.join([*receipt["path"], environment.get("PATH", "")])
    for name, expected in receipt["files"].items():
        if sha256(safe_path(directory, name)) != expected:
            raise ValueError(f"Environment evidence changed: {name}; prepare again")
    for tool in receipt["tools"].values():
        if tool["status"] == "ready":
            executable = Path(tool["executable"])
            if not executable.is_file() or not os.access(executable, os.X_OK) or sha256(executable) != tool["executable_sha256"]:
                raise ValueError(f"Prepared tool changed or disappeared: {executable}; prepare again")
            if shutil.which(tool["command"], path=environment["PATH"]) != str(executable):
                raise ValueError(f"Prepared tool is shadowed on PATH: {executable}; correct bin_dirs and prepare again")
    return environment


def prepare(directory: Path, plan: dict, timeout: int, process_started=None) -> dict:
    """Probe first, install missing tools under versioned prefixes, then require successful re-probes."""
    deadline = time.monotonic() + timeout
    environment = dict(os.environ)
    records, paths, files = {}, [], {}
    files["plan.yaml"] = sha256(directory / "plan.yaml")
    for tool in plan["tools"]:
        identifier = tool["id"]
        recipe = json.dumps(tool, sort_keys=True).encode()
        key = f"{identifier}-{hashlib.sha256(recipe).hexdigest()[:20]}"
        base = (Path.home() / ".local/share/ucagent/act4/tools" if tool["storage"] == "persistent"
                else Path(tempfile.gettempdir()) / f"ucagent-act4-{os.getuid()}")
        if base.is_symlink() or (base.exists() and base.stat().st_uid != os.getuid()):
            raise ValueError(f"Installation directory must be owned by the current user and not a symlink: {base}")
        prefix = safe_path(base, key)
        bins = [str(safe_path(prefix, name)) for name in tool["bin_dirs"]]
        probe = [arg.replace("{PREFIX}", str(prefix)).replace("{PYTHON}", sys.executable) for arg in tool["probe"]]
        record = {"status": "needs_install", "prefix": str(prefix), "attempts": [], "version": tool["version"], "basis": tool["basis"]}
        records[identifier] = record
        candidates = [("host", environment), ("cache", {**environment, "PATH": os.pathsep.join([*bins, environment["PATH"]])})]
        try:
            for location, candidate in candidates:
                log = directory / f"{identifier}-{location}.log"
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise TimeoutError("Preparation time budget exhausted; retry preparation to finish remaining tools")
                result = execute(probe, directory, log, min(20, remaining), process_started, env=candidate)
                files[log.name] = sha256(log)
                record["attempts"].append({**result, "log": log.name})
                executable = shutil.which(probe[0], path=candidate["PATH"])
                output = log.read_text(errors="replace")
                if result["status"] == "passed" and executable and tool["version"] in output and re.search(tool["expected_output"], output):
                    selected = str(Path(executable).absolute())
                    record.update(status="ready", origin=location, command=probe[0], executable=selected, executable_sha256=sha256(Path(selected)))
                    additions = bins if location != "host" else [str(Path(selected).parent)]
                    paths = list(dict.fromkeys([*additions, *paths]))
                    environment["PATH"] = os.pathsep.join([*paths, os.environ.get("PATH", "")])
                    break
                if location == "host":
                    continue
                if location == "installed":
                    record.update(status="unavailable", reason="Installed tool failed its version/capability probe; inspect the probe log and correct the recipe")
                    break
                if not tool["install"]:
                    if tool.get("unavailable_reason"):
                        record.update(status="unavailable", reason=tool["unavailable_reason"])
                    else:
                        record["reason"] = "Provide install argv from the selected project's dependency instructions and prepare again"
                    break
                prefix.mkdir(parents=True, exist_ok=True)
                lock_path = safe_path(prefix, ".install.lock")
                with lock_path.open("a") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise ValueError(f"Another task is installing {identifier}; retry preparation after it finishes") from None
                    for index, argv in enumerate(tool["install"]):
                        remaining = int(deadline - time.monotonic())
                        if remaining <= 0:
                            raise TimeoutError("Preparation time budget exhausted")
                        command = [arg.replace("{PREFIX}", str(prefix)).replace("{PYTHON}", sys.executable) for arg in argv]
                        install_log = directory / f"{identifier}-install-{index}.log"
                        result = execute(command, prefix, install_log, remaining, process_started, env=candidate)
                        files[install_log.name] = sha256(install_log)
                        record["attempts"].append({**result, "log": install_log.name})
                        if result["status"] != "passed":
                            record.update(status="unavailable", reason=f"Installation failed; inspect {install_log.name}, resolve network/permission/dependency failure and retry")
                            break
                    else:
                        candidates.append(("installed", candidate))
                    if record["status"] == "unavailable":
                        break
        except InterruptedError:
            raise
        except (OSError, ValueError) as error:
            record.update(status="unavailable", reason=str(error))
    activation = directory / "activate.sh"
    activation.write_text('export PATH=' + shlex.quote(os.pathsep.join(paths)) + '${PATH:+:"$PATH"}\n', encoding="utf-8")
    files[activation.name] = sha256(activation)
    if (directory / "host.json").is_file():
        files["host.json"] = sha256(directory / "host.json")
        for record in json.loads((directory / "host.json").read_text()).values():
            log_sha256 = sha256(safe_path(directory, record["log"]))
            if log_sha256 != record["sha256"]:
                raise ValueError(f"Host probe log changed: {record['log']}; repeat host probes")
            files[record["log"]] = log_sha256
    unavailable = [f"- {name}: {tool.get('reason', tool['status'])}" for name, tool in records.items() if tool["status"] != "ready"]
    summary = (
        "\n# Environment preparation\n\n"
        + f"{len(records) - len(unavailable)}/{len(records)} tools are ready. "
        + ("Unavailable tools limit the corresponding validation; they are not test failures.\n\n" if unavailable else "All declared tools passed their probes.\n\n")
        + "\n".join(unavailable) + "\n\nSee receipt.json and the named logs. Native build/model results remain separate evidence.\n"
    )
    (directory / "summary.md").write_text(summary, encoding="utf-8")
    files["summary.md"] = sha256(directory / "summary.md")
    receipt = {"schema_version": 1, "tools": records, "path": paths, "files": files}
    write_json(directory / "receipt.json", receipt)
    return receipt
