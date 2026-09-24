"""Replay execution for the Bug Review workflow."""
import json
import os
import platform
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .cross_arch_replay import inspect_contracts, run_cross_arch_replay
from .replay_harness import run_replay_runner_contracts
from .utils import get_logger
from .resource_pools import replay_resource_isolated


CrossArchRunner = Callable[..., Dict[str, Any]]
LegacyRunner = Callable[..., Dict[str, Any]]
logger = get_logger(__name__)
from .paths import repository_root

REPO_ROOT = str(repository_root())


def _normalize_replay_execution_mode(mode: str) -> str:
    value = (mode or "").strip().lower()
    if value in {"", "auto"}:
        return "auto"
    if value in {"cross_arch", "cross-arch", "crossarch"}:
        return "cross_arch"
    if value in {"legacy", "direct"}:
        return "legacy"
    raise ValueError(f"unsupported replay execution mode: {mode}")


def _load_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _arch_aliases(arch: str) -> List[str]:
    value = (arch or "").strip().lower()
    aliases = [value] if value else []
    if value == "x86_64":
        aliases.append("amd64")
    elif value == "amd64":
        aliases.append("x86_64")
    elif value == "aarch64":
        aliases.append("arm64")
    elif value == "arm64":
        aliases.append("aarch64")
    deduped: List[str] = []
    for item in aliases:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _repo_local_runtime_for_arch(arch: str) -> Tuple[str, str]:
    """Find a compatible repo-local UCAgent root and Python executable."""
    runtime_root = ""
    selected_alias = ""
    for alias in _arch_aliases(arch):
        candidate = os.path.join(REPO_ROOT, "external", "runtime-shims", f"ucagent-{alias}-root")
        if os.path.isdir(candidate):
            runtime_root = candidate
            selected_alias = alias
            break
    if not runtime_root:
        return "", ""

    required_version = ""
    pyvenv_cfg = os.path.join(runtime_root, ".venv", "pyvenv.cfg")
    if os.path.isfile(pyvenv_cfg):
        try:
            with open(pyvenv_cfg, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip().lower().startswith("version") and "=" in line:
                        version = line.split("=", 1)[1].strip().split(".")
                        if len(version) >= 2:
                            required_version = ".".join(version[:2])
                        break
        except OSError:
            pass

    aliases = [selected_alias] + [item for item in _arch_aliases(arch) if item != selected_alias]
    for alias in aliases:
        bin_dir = os.path.join(REPO_ROOT, "external", f"runtime-{alias}", "bin")
        if not os.path.isdir(bin_dir):
            continue
        prefix = f"python{required_version}" if required_version else "python"
        for name in sorted(os.listdir(bin_dir)):
            candidate = os.path.join(bin_dir, name)
            if name.startswith(prefix) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return runtime_root, candidate
    return runtime_root, ""


def _runtime_settings_for_arch(
    *,
    runtime_root: str,
    runtime_profile: Optional[Dict[str, object]],
    arch: str,
) -> Tuple[str, Dict[str, object]]:
    base_profile = dict(runtime_profile or {})
    per_arch = base_profile.get("per_arch", {})
    arch_profile: Dict[str, object] = {}
    if isinstance(per_arch, dict):
        for alias in _arch_aliases(arch):
            candidate = per_arch.get(alias)
            if isinstance(candidate, dict):
                arch_profile = dict(candidate)
                break
    if "per_arch" in base_profile:
        base_profile.pop("per_arch", None)
    merged_profile = dict(base_profile)
    merged_profile.update(arch_profile)
    resolved_runtime_root = str(
        arch_profile.get("runtime_root")
        or merged_profile.get("runtime_root")
        or runtime_root
        or ""
    ).strip()
    discovered_runtime_root = ""
    discovered_python = ""
    missing_python = not str(merged_profile.get("python_executable") or "").strip()
    if not resolved_runtime_root or missing_python:
        discovered_runtime_root, discovered_python = _repo_local_runtime_for_arch(arch)
    if not resolved_runtime_root and discovered_runtime_root:
        resolved_runtime_root = discovered_runtime_root
        logger.info(
            "auto replay discovered repo-local runtime: arch=%s runtime_root=%s",
            arch,
            resolved_runtime_root,
        )
    runtime_matches_discovery = bool(
        resolved_runtime_root
        and discovered_runtime_root
        and os.path.realpath(resolved_runtime_root) == os.path.realpath(discovered_runtime_root)
    )
    if discovered_python and missing_python and runtime_matches_discovery:
        merged_profile["python_executable"] = discovered_python
        logger.info(
            "auto replay paired repo-local Python: arch=%s python_executable=%s",
            arch,
            discovered_python,
        )
    if resolved_runtime_root:
        merged_profile["runtime_root"] = resolved_runtime_root
    return resolved_runtime_root, merged_profile


def _run_cross_arch_and_load_results(
    *,
    contracts_path: str,
    output_dir: str,
    runtime_root: str,
    target_arch: str,
    qemu_binary: str,
    target_python: str,
    sysroot: str,
    path: Optional[Sequence[str]],
    ld_library_path: Optional[Sequence[str]],
    pythonpath: Optional[Sequence[str]],
    extra_env: Optional[Dict[str, str]],
    cross_arch_runner: CrossArchRunner,
) -> Dict[str, object]:
    summary = cross_arch_runner(
        contracts_path=contracts_path,
        output_dir=output_dir,
        runtime_root=runtime_root,
        target_arch=target_arch,
        qemu_binary=qemu_binary,
        target_python=target_python,
        sysroot=sysroot,
        path=path,
        ld_library_path=ld_library_path,
        pythonpath=pythonpath,
        extra_env=extra_env,
    )
    results_path = os.path.join(output_dir, "replay_results.json")
    if isinstance(summary, dict):
        candidate_path = str(summary.get("results_path") or "").strip()
        if candidate_path:
            results_path = candidate_path
    if not os.path.isfile(results_path):
        raise FileNotFoundError(results_path)
    return _load_json(results_path)


def _host_arch() -> str:
    machine = platform.machine().strip().lower()
    if machine in {"amd64"}:
        return "x86_64"
    if machine in {"arm64"}:
        return "aarch64"
    return machine or "unknown"


def _contract_arch_groups(contracts: Sequence[Dict[str, object]]) -> Tuple[str, Dict[str, List[Dict[str, object]]]]:
    inspection = inspect_contracts(contracts)
    host_arch = str(inspection.get("host_arch") or _host_arch()).lower()
    groups: Dict[str, List[Dict[str, object]]] = {}
    rows_by_candidate = {
        str(row.get("candidate_id") or ""): row
        for row in inspection.get("contracts", [])
        if isinstance(row, dict)
    }
    for contract in contracts:
        contract_input = contract.get("input", {}) if isinstance(contract, dict) else {}
        candidate_id = str(contract_input.get("candidate_id") or "")
        row = rows_by_candidate.get(candidate_id, {})
        machines = {
            str(item.get("machine") or "").lower()
            for item in row.get("binaries", [])
            if isinstance(item, dict) and item.get("machine")
        }
        if len(machines) == 1:
            arch = next(iter(machines))
        elif host_arch in machines:
            arch = host_arch
        elif machines:
            arch = sorted(machines)[0]
        else:
            arch = "unknown"
        groups.setdefault(arch, []).append(contract)
    return host_arch, groups


def _all_contracts_native_or_unknown(host_arch: str, arch_groups: Dict[str, List[Dict[str, object]]]) -> bool:
    return all(arch in {"unknown", host_arch} for arch in arch_groups)


def _merge_replay_payloads(payloads: Sequence[Dict[str, object]]) -> Dict[str, object]:
    results: List[Dict[str, object]] = []
    status_counts: Dict[str, int] = {}
    runtime_roots: List[str] = []
    input_contract_count = 0
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        input_contract_count += int(summary.get("input_contract_count", len(payload.get("results", [])) or 0))
        runtime_root = str(summary.get("runtime_root") or "").strip()
        if runtime_root and runtime_root not in runtime_roots:
            runtime_roots.append(runtime_root)
        for item in payload.get("results", []):
            if isinstance(item, dict):
                results.append(item)
                result = item.get("result", {})
                status = str(result.get("status") or "")
                if status:
                    status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "results": results,
        "summary": {
            "input_contract_count": input_contract_count,
            "result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "runtime_root": ",".join(runtime_roots),
        },
    }


@replay_resource_isolated
def run_benchmark_replay_execution(
    *,
    contracts: Sequence[Dict[str, object]],
    contracts_path: str,
    output_dir: str,
    runtime_root: str = "",
    runtime_profile: Optional[Dict[str, object]] = None,
    execution_mode: str = "auto",
    target_arch: str = "auto",
    qemu_binary: str = "",
    target_python: str = "",
    sysroot: str = "",
    path: Optional[Sequence[str]] = None,
    ld_library_path: Optional[Sequence[str]] = None,
    pythonpath: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
    cross_arch_runner: CrossArchRunner = run_cross_arch_replay,
    legacy_runner: LegacyRunner = run_replay_runner_contracts,
) -> Dict[str, object]:
    mode = _normalize_replay_execution_mode(execution_mode)
    if not contracts:
        return {"results": [], "summary": {"input_contract_count": 0, "result_count": 0, "status_counts": {}}}
    logger.info(
        "auto replay dispatch: mode=%s contracts=%d output_dir=%s",
        mode,
        len(contracts),
        output_dir,
    )

    if mode == "legacy":
        resolved_runtime_root, resolved_runtime_profile = _runtime_settings_for_arch(
            runtime_root=runtime_root,
            runtime_profile=runtime_profile,
            arch=target_arch if target_arch != "auto" else _host_arch(),
        )
        logger.info(
            "auto replay using legacy runner: target_arch=%s runtime_root=%s",
            target_arch if target_arch != "auto" else _host_arch(),
            resolved_runtime_root or "<empty>",
        )
        return legacy_runner(
            list(contracts),
            runtime_root=resolved_runtime_root,
            runtime_profile=resolved_runtime_profile,
        )

    if not contracts_path:
        if mode == "cross_arch":
            raise ValueError("contracts_path is required for cross_arch replay execution")
        resolved_runtime_root, resolved_runtime_profile = _runtime_settings_for_arch(
            runtime_root=runtime_root,
            runtime_profile=runtime_profile,
            arch=target_arch if target_arch != "auto" else _host_arch(),
        )
        return legacy_runner(
            list(contracts),
            runtime_root=resolved_runtime_root,
            runtime_profile=resolved_runtime_profile,
        )

    if mode == "auto":
        host_arch, arch_groups = _contract_arch_groups(contracts)
        non_unknown_arches = {arch for arch in arch_groups if arch != "unknown"}
        logger.info(
            "auto replay arch inspection: host=%s groups=%s",
            host_arch,
            ", ".join(f"{arch}:{len(items)}" for arch, items in sorted(arch_groups.items())) or "<none>",
        )
        if _all_contracts_native_or_unknown(host_arch, arch_groups):
            resolved_runtime_root, resolved_runtime_profile = _runtime_settings_for_arch(
                runtime_root=runtime_root,
                runtime_profile=runtime_profile,
                arch=host_arch,
            )
            logger.info(
                "auto replay using native runner: host_arch=%s contracts=%d runtime_root=%s",
                host_arch,
                len(contracts),
                resolved_runtime_root or "<empty>",
            )
            return legacy_runner(
                list(contracts),
                runtime_root=resolved_runtime_root,
                runtime_profile=resolved_runtime_profile,
            )
        if len(non_unknown_arches) > 1 or (non_unknown_arches and host_arch in non_unknown_arches and len(arch_groups) > 1):
            group_payloads: List[Dict[str, object]] = []
            for arch, group_contracts in arch_groups.items():
                if not group_contracts:
                    continue
                group_runtime_root, group_runtime_profile = _runtime_settings_for_arch(
                    runtime_root=runtime_root,
                    runtime_profile=runtime_profile,
                    arch=arch,
                )
                if arch in {"unknown", host_arch}:
                    logger.info(
                        "auto replay group start: arch=%s mode=legacy contracts=%d runtime_root=%s",
                        arch,
                        len(group_contracts),
                        group_runtime_root or "<empty>",
                    )
                    group_payloads.append(
                        legacy_runner(
                            list(group_contracts),
                            runtime_root=group_runtime_root,
                            runtime_profile=group_runtime_profile,
                        )
                    )
                    logger.info(
                        "auto replay group done: arch=%s mode=legacy contracts=%d",
                        arch,
                        len(group_contracts),
                    )
                    continue
                group_dir = os.path.join(output_dir, f"replay_group_{arch}")
                os.makedirs(group_dir, exist_ok=True)
                group_contracts_path = os.path.join(group_dir, "replay_runner_contracts.json")
                with open(group_contracts_path, "w", encoding="utf-8") as handle:
                    json.dump({"replay_runner_contracts": list(group_contracts)}, handle, ensure_ascii=False, indent=2)
                logger.info(
                    "auto replay group start: arch=%s mode=cross_arch contracts=%d output_dir=%s runtime_root=%s",
                    arch,
                    len(group_contracts),
                    group_dir,
                    group_runtime_root or "<empty>",
                )
                group_payloads.append(
                    _run_cross_arch_and_load_results(
                        contracts_path=group_contracts_path,
                        output_dir=group_dir,
                        runtime_root=group_runtime_root,
                        target_arch=arch,
                        qemu_binary=qemu_binary,
                        target_python=target_python,
                        sysroot=sysroot,
                        path=group_runtime_profile.get("path") if group_runtime_profile.get("path") is not None else path,
                        ld_library_path=group_runtime_profile.get("ld_library_path") if group_runtime_profile.get("ld_library_path") is not None else ld_library_path,
                        pythonpath=group_runtime_profile.get("pythonpath") if group_runtime_profile.get("pythonpath") is not None else pythonpath,
                        extra_env=group_runtime_profile.get("env") if group_runtime_profile.get("env") is not None else extra_env,
                        cross_arch_runner=cross_arch_runner,
                    )
                )
                logger.info(
                    "auto replay group done: arch=%s mode=cross_arch contracts=%d",
                    arch,
                    len(group_contracts),
                )
            merged = _merge_replay_payloads(group_payloads)
            with open(os.path.join(output_dir, "replay_results.json"), "w", encoding="utf-8") as handle:
                json.dump(merged, handle, ensure_ascii=False, indent=2)
            logger.info(
                "auto replay merged group results: result_count=%d statuses=%s",
                len(merged.get("results", [])),
                merged.get("summary", {}).get("status_counts", {}),
            )
            return merged

    try:
        resolved_runtime_root, resolved_runtime_profile = _runtime_settings_for_arch(
            runtime_root=runtime_root,
            runtime_profile=runtime_profile,
            arch=target_arch if target_arch != "auto" else _host_arch(),
        )
        logger.info(
            "auto replay using cross-arch runner: target_arch=%s output_dir=%s runtime_root=%s",
            target_arch,
            output_dir,
            resolved_runtime_root or "<empty>",
        )
        return _run_cross_arch_and_load_results(
            contracts_path=contracts_path,
            output_dir=output_dir,
            runtime_root=resolved_runtime_root,
            target_arch=target_arch,
            qemu_binary=qemu_binary,
            target_python=target_python,
            sysroot=sysroot,
            path=resolved_runtime_profile.get("path") if resolved_runtime_profile.get("path") is not None else path,
            ld_library_path=resolved_runtime_profile.get("ld_library_path") if resolved_runtime_profile.get("ld_library_path") is not None else ld_library_path,
            pythonpath=resolved_runtime_profile.get("pythonpath") if resolved_runtime_profile.get("pythonpath") is not None else pythonpath,
            extra_env=resolved_runtime_profile.get("env") if resolved_runtime_profile.get("env") is not None else extra_env,
            cross_arch_runner=cross_arch_runner,
        )
    except (FileNotFoundError, SystemExit, ValueError):
        existing_results_path = os.path.join(output_dir, "replay_results.json")
        if os.path.isfile(existing_results_path):
            loaded = _load_json(existing_results_path)
            if loaded:
                logger.warning(
                    "auto replay cross-arch runner exited early but wrote results: output_dir=%s statuses=%s",
                    output_dir,
                    loaded.get("summary", {}).get("status_counts", {}),
                )
                return loaded
        if mode != "auto":
            raise
        logger.warning(
            "auto replay cross-arch runner unavailable, falling back to legacy runner: output_dir=%s",
            output_dir,
        )
        resolved_runtime_root, resolved_runtime_profile = _runtime_settings_for_arch(
            runtime_root=runtime_root,
            runtime_profile=runtime_profile,
            arch=target_arch if target_arch != "auto" else _host_arch(),
        )
        return legacy_runner(
            list(contracts),
            runtime_root=resolved_runtime_root,
            runtime_profile=resolved_runtime_profile,
        )
