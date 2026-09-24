"""Cross arch replay for the Bug Review workflow."""
import json
import os
import shutil
import platform
import signal
import time
from typing import Any, Dict, List, Optional, Sequence

from .replay_harness import run_replay_runner_contracts
from .utils import get_logger
from .paths import repository_root, resources_root


REPO_ROOT = str(repository_root())
logger = get_logger(__name__)


class ReplayInterruptedError(RuntimeError):
    pass


def _write_json(path: str, data: Dict[str, object]) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(os.path.abspath(path), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return os.path.abspath(path)


def _now_epoch() -> float:
    return time.time()


def _empty_results_payload(contract_count: int, runtime_root: str = "") -> Dict[str, object]:
    return {
        "results": [],
        "summary": {
            "input_contract_count": contract_count,
            "result_count": 0,
            "status_counts": {},
            "runtime_root": runtime_root,
        },
    }


def _status_payload(
    *,
    state: str,
    inspection: Dict[str, object],
    output_dir: str,
    profile_path: str = "",
    results_path: str = "",
    summary_path: str = "",
    contracts_path: str = "",
    contract_count: int = 0,
    completed_count: int = 0,
    current_candidate_id: str = "",
    last_candidate_id: str = "",
    status_counts: Optional[Dict[str, object]] = None,
    error: str = "",
) -> Dict[str, object]:
    return {
        "state": state,
        "inspection": inspection,
        "output_dir": os.path.abspath(output_dir),
        "profile_path": os.path.abspath(profile_path) if profile_path else "",
        "results_path": os.path.abspath(results_path) if results_path else "",
        "summary_path": os.path.abspath(summary_path) if summary_path else "",
        "contracts_path": os.path.abspath(contracts_path) if contracts_path else "",
        "contract_count": contract_count,
        "completed_count": completed_count,
        "current_candidate_id": current_candidate_id,
        "last_candidate_id": last_candidate_id,
        "status_counts": dict(status_counts or {}),
        "error": error,
        "updated_at_epoch": _now_epoch(),
    }


def _infrastructure_error_results(
    contracts: Sequence[Dict[str, object]],
    reason: str,
    runtime_root: str = "",
) -> Dict[str, object]:
    results = []
    status_counts: Dict[str, int] = {}
    for contract in contracts:
        contract_input = contract.get("input", {}) if isinstance(contract, dict) else {}
        candidate_id = str(contract_input.get("candidate_id") or "")
        result = {
            "status": "infrastructure_error",
            "source": "cross_arch_replay",
            "phase": "",
            "failure_type": "",
            "expected": str(contract_input.get("expected") or ""),
            "observed": str(contract_input.get("observed") or ""),
            "reason": reason,
            "returncode": None,
            "runtime_root": runtime_root,
            "artifacts": list(contract_input.get("evidence_artifacts", []) or []),
        }
        status_counts["infrastructure_error"] = status_counts.get("infrastructure_error", 0) + 1
        results.append(
            {
                "candidate_id": candidate_id,
                "result": result,
                "replay_runner_contract": contract,
            }
        )
    return {
        "results": results,
        "summary": {
            "input_contract_count": len(list(contracts)),
            "result_count": len(results),
            "status_counts": dict(sorted(status_counts.items())),
            "runtime_root": runtime_root,
        },
    }


def _existing_paths(candidates: Sequence[str]) -> List[str]:
    return [os.path.abspath(path) for path in candidates if path and os.path.exists(path)]


def _first_existing_file(candidates: Sequence[str]) -> str:
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    return ""


def _first_existing_dir(candidates: Sequence[str]) -> str:
    for path in candidates:
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    return ""


def _path_candidates_from_rootfs(rootfs_dir: str, relative_paths: Sequence[str]) -> List[str]:
    return [os.path.join(rootfs_dir, rel_path) for rel_path in relative_paths]


def _arch_aliases(target_arch: str) -> List[str]:
    value = (target_arch or "").strip().lower()
    aliases = [value] if value else []
    alias_map = {
        "aarch64": ["arm64"],
        "arm64": ["aarch64"],
        "x86_64": ["amd64"],
        "amd64": ["x86_64"],
    }
    aliases.extend(alias_map.get(value, []))
    deduped: List[str] = []
    for item in aliases:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _elf_machine(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as handle:
            header = handle.read(20)
    except OSError:
        return ""
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return ""
    endian = header[5]
    if endian == 1:
        machine_id = int.from_bytes(header[18:20], byteorder="little")
    elif endian == 2:
        machine_id = int.from_bytes(header[18:20], byteorder="big")
    else:
        return ""
    return {62: "x86_64", 183: "aarch64"}.get(machine_id, f"elf_machine_{machine_id}")


def _candidate_binary_paths_for_root(root: str) -> List[str]:
    paths: List[str] = []
    if not root or not os.path.isdir(root):
        return paths
    xspcomm_dir = os.path.join(root, "xspcomm")
    if os.path.isdir(xspcomm_dir):
        paths.extend(
            [
                os.path.join(xspcomm_dir, "_pyxspcomm.so.0.0.1"),
                os.path.join(xspcomm_dir, "_pyxspcomm.so"),
                os.path.join(xspcomm_dir, "libxspcomm.so.0.0.1"),
                os.path.join(xspcomm_dir, "libxspcomm.so"),
            ]
        )
    for entry in sorted(os.listdir(root)):
        if entry.startswith("_UT_") and entry.endswith(".so"):
            paths.append(os.path.join(root, entry))
    return paths


def _candidate_binary_paths(contract_input: Dict[str, object]) -> List[str]:
    roots: List[str] = []
    rtl_root = str(contract_input.get("rtl_root") or "")
    dut = str(contract_input.get("dut") or "")
    tests_root = str(contract_input.get("tests_root") or "")
    data_root = str(contract_input.get("data_root") or "")

    def add_root(path: str) -> None:
        path = os.path.abspath(path) if path else ""
        if path and path not in roots and os.path.isdir(path):
            roots.append(path)

    add_root(rtl_root)
    if rtl_root:
        rtl_parent = os.path.dirname(os.path.abspath(rtl_root))
        add_root(rtl_parent)
        if dut:
            add_root(os.path.join(rtl_parent, dut))
        for entry in sorted(os.listdir(rtl_parent)) if os.path.isdir(rtl_parent) else []:
            candidate = os.path.join(rtl_parent, entry)
            if candidate == os.path.abspath(rtl_root):
                continue
            if os.path.isdir(candidate) and (
                os.path.isdir(os.path.join(candidate, "xspcomm"))
                or any(name.startswith("_UT_") and name.endswith(".so") for name in os.listdir(candidate))
            ):
                add_root(candidate)
    if tests_root:
        add_root(os.path.dirname(os.path.abspath(tests_root)))
    if data_root:
        add_root(os.path.dirname(os.path.dirname(os.path.abspath(data_root))))

    paths: List[str] = []
    for root in roots:
        for path in _candidate_binary_paths_for_root(root):
            if path not in paths:
                paths.append(path)
    return paths


def inspect_contracts(contracts: Sequence[Dict[str, object]]) -> Dict[str, object]:
    host_arch = platform.machine().strip().lower() or "unknown"
    rows = []
    for contract in contracts:
        contract_input = contract.get("input", {}) if isinstance(contract, dict) else {}
        rtl_root = str(contract_input.get("rtl_root") or "")
        row = {
            "candidate_id": str(contract_input.get("candidate_id") or ""),
            "dut": str(contract_input.get("dut") or ""),
            "rtl_root": rtl_root,
            "binaries": [],
        }
        for path in _candidate_binary_paths(contract_input):
            machine = _elf_machine(path)
            if machine:
                row["binaries"].append(
                    {
                        "path": path,
                        "machine": machine,
                        "host_matches": machine == host_arch,
                    }
                )
        rows.append(row)
    all_machines = sorted({binary["machine"] for row in rows for binary in row["binaries"]})
    return {
        "host_arch": host_arch,
        "detected_target_arches": all_machines,
        "cross_arch_required": any(machine != host_arch for machine in all_machines),
        "contracts": rows,
    }


def resolve_target_arch(target_arch: str, inspection: Optional[Dict[str, object]] = None) -> str:
    requested = (target_arch or "").strip().lower()
    if requested and requested != "auto":
        return requested
    detected = list((inspection or {}).get("detected_target_arches", []) or [])
    if len(detected) == 1:
        return str(detected[0]).strip().lower()
    if len(detected) > 1:
        raise SystemExit(f"multiple target architectures detected: {detected}; pass --target-arch explicitly")
    return "aarch64"


def discover_repo_local_cross_arch_assets(target_arch: str = "aarch64") -> Dict[str, str]:
    target_arch = (target_arch or "").strip().lower()
    arch_aliases = _arch_aliases(target_arch)
    arch_rootfs_candidates = [
        os.environ.get("BENCHMARK_CROSS_ARCH_ROOTFS", ""),
    ]
    for alias in arch_aliases:
        arch_rootfs_candidates.extend(
            [
                os.path.join(REPO_ROOT, "external", "runtime-rootfs", f"{alias}-rootfs-noble"),
                os.path.join(REPO_ROOT, "external", "runtime-rootfs", f"{alias}-rootfs-lite"),
                os.path.join(REPO_ROOT, "external", "runtime-rootfs", f"{alias}-rootfs"),
            ]
        )
    rootfs = _first_existing_dir(arch_rootfs_candidates)

    overlay_candidates = [
        os.environ.get("BENCHMARK_CROSS_ARCH_OVERLAY", ""),
    ]
    for alias in arch_aliases:
        overlay_candidates.append(os.path.join(REPO_ROOT, "external", f"{alias}-overlay", "site-packages"))
    overlay = _first_existing_dir(overlay_candidates)

    qemu_candidates = [
        os.environ.get("BENCHMARK_QEMU_BINARY", ""),
    ]
    for alias in arch_aliases:
        qemu_candidates.append(shutil.which(f"qemu-{alias}-static") if alias else "")
        qemu_candidates.append(shutil.which(f"qemu-{alias}") if alias else "")
    qemu_binary = _first_existing_file(qemu_candidates)

    target_python_candidates: List[str] = []
    if rootfs:
        target_python_candidates.extend(
            _path_candidates_from_rootfs(
                rootfs,
                [
                    "usr/bin/python3",
                    "usr/bin/python3.12",
                    "usr/bin/python3.11",
                    "usr/bin/python3.10",
                    "usr/bin/python3.9",
                    "usr/bin/python3.8",
                ],
            )
        )
    target_python_candidates.append(os.environ.get("BENCHMARK_QEMU_TARGET_PYTHON", ""))
    target_python = _first_existing_file(target_python_candidates)

    sysroot_candidates = [
        os.environ.get("BENCHMARK_QEMU_SYSROOT", ""),
        rootfs,
    ]
    sysroot = _first_existing_dir(sysroot_candidates)

    runtime_root_candidates = [
        os.environ.get("BENCHMARK_UCAGENT_RUNTIME_ROOT", ""),
        os.path.join(REPO_ROOT, "external", "UCAgent"),
        os.path.join(REPO_ROOT, "external", "ucagent"),
        os.environ.get("UCAgent_DIR", ""),
    ]
    runtime_root = _first_existing_dir(runtime_root_candidates)

    return {
        "target_arch": target_arch,
        "runtime_root": runtime_root,
        "qemu_binary": qemu_binary,
        "target_python": target_python,
        "sysroot": sysroot,
        "overlay_pythonpath": overlay,
        "rootfs": rootfs,
    }


def build_repo_local_runtime_profile(
    *,
    runtime_root: str,
    target_arch: str = "aarch64",
    qemu_binary: str = "",
    target_python: str = "",
    sysroot: str = "",
    pythonpath: Optional[Sequence[str]] = None,
    path: Optional[Sequence[str]] = None,
    ld_library_path: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resolved_target_arch = resolve_target_arch(target_arch)
    assets = discover_repo_local_cross_arch_assets(target_arch=resolved_target_arch)
    resolved_runtime_root = os.path.abspath(runtime_root or assets["runtime_root"])
    resolved_qemu_binary = os.path.abspath(qemu_binary or assets["qemu_binary"])
    resolved_target_python = os.path.abspath(target_python or assets["target_python"])
    resolved_sysroot = os.path.abspath(sysroot or assets["sysroot"])
    default_pythonpaths = _existing_paths(
        [assets["overlay_pythonpath"]]
        + [
            os.path.join(REPO_ROOT, "external", "runtime-rootfs", f"{alias}-site-packages")
            for alias in _arch_aliases(resolved_target_arch)
        ]
    )
    if not resolved_runtime_root:
        raise SystemExit("runtime root not found; set BENCHMARK_UCAGENT_RUNTIME_ROOT or clone external/UCAgent")
    if not resolved_qemu_binary:
        raise SystemExit("qemu binary not found; set BENCHMARK_QEMU_BINARY or install qemu-user")
    if not resolved_target_python:
        raise SystemExit("target python not found; set BENCHMARK_QEMU_TARGET_PYTHON or provide a rootfs")
    if not resolved_sysroot:
        raise SystemExit("sysroot not found; set BENCHMARK_QEMU_SYSROOT or provide a rootfs")

    profile = {
        "runtime_root": resolved_runtime_root,
        "python_executable": str(resources_root() / "qemu_python_launcher.sh"),
        "path": [item for item in (path or []) if item],
        "ld_library_path": [item for item in (ld_library_path or []) if item],
        "pythonpath": default_pythonpaths + [item for item in (pythonpath or []) if item],
        "env": {
            "TOFFEE_MODE": "replay",
            "BENCHMARK_QEMU_BINARY": resolved_qemu_binary,
            "BENCHMARK_QEMU_TARGET_PYTHON": resolved_target_python,
        },
    }
    if resolved_sysroot:
        profile["env"]["BENCHMARK_QEMU_SYSROOT"] = resolved_sysroot
    if extra_env:
        profile["env"].update({str(key): str(value) for key, value in extra_env.items()})
    return profile


def write_profile(profile: Dict[str, Any], output_profile: str) -> str:
    return _write_json(output_profile, profile)


def run_cross_arch_replay(
    *,
    contracts_path: str,
    output_dir: str,
    runtime_root: str = "",
    target_arch: str = "aarch64",
    qemu_binary: str = "",
    target_python: str = "",
    sysroot: str = "",
    profile_output: str = "",
    summary_output: str = "",
    path: Optional[Sequence[str]] = None,
    ld_library_path: Optional[Sequence[str]] = None,
    pythonpath: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    profile_path = os.path.abspath(profile_output or os.path.join(output_dir, "replay_cross_arch_profile.json"))
    results_path = os.path.join(output_dir, "replay_results.json")
    replay_summary_path = os.path.join(output_dir, "replay_summary.json")
    status_path = os.path.join(output_dir, "cross_arch_replay_status.json")
    summary_path = summary_output or os.path.join(output_dir, "cross_arch_replay_summary.json")

    with open(os.path.abspath(contracts_path), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    contracts = payload.get("replay_runner_contracts", []) if isinstance(payload, dict) else []
    inspection = inspect_contracts(contracts)
    _write_json(
        results_path,
        _empty_results_payload(len(contracts)),
    )
    _write_json(replay_summary_path, _empty_results_payload(len(contracts)).get("summary", {}))
    _write_json(
        status_path,
        _status_payload(
            state="initializing",
            inspection=inspection,
            output_dir=output_dir,
            profile_path=profile_path,
            results_path=results_path,
            summary_path=replay_summary_path,
            contracts_path=contracts_path,
            contract_count=len(contracts),
            completed_count=0,
        ),
    )

    profile: Dict[str, Any] = {}
    results = _empty_results_payload(len(contracts))
    replay_returncode = 0
    error = ""
    previous_handlers: Dict[int, Any] = {}
    interrupted_signal = 0

    def _signal_handler(signum: int, frame: object) -> None:
        del frame
        nonlocal interrupted_signal
        interrupted_signal = signum
        raise ReplayInterruptedError(f"received signal {signal.Signals(signum).name}")
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _signal_handler)
        resolved_target_arch = resolve_target_arch(target_arch, inspection)
        assets = discover_repo_local_cross_arch_assets(target_arch=resolved_target_arch)
        profile = build_repo_local_runtime_profile(
            runtime_root=runtime_root or assets["runtime_root"],
            target_arch=resolved_target_arch,
            qemu_binary=qemu_binary or assets["qemu_binary"],
            target_python=target_python or assets["target_python"],
            sysroot=sysroot or assets["sysroot"],
            pythonpath=pythonpath,
            path=path,
            ld_library_path=ld_library_path,
            extra_env=extra_env,
        )
        profile_path = write_profile(profile, profile_path)
        _write_json(
            status_path,
            _status_payload(
                state="running",
                inspection=inspection,
                output_dir=output_dir,
                profile_path=profile_path,
                results_path=results_path,
                summary_path=replay_summary_path,
                contracts_path=contracts_path,
                contract_count=len(contracts),
                completed_count=0,
                status_counts={},
            ),
        )
        logger.info(
            "cross-arch replay start: target_arch=%s contracts=%d output_dir=%s runtime_root=%s",
            resolved_target_arch,
            len(contracts),
            output_dir,
            profile.get("runtime_root", "") or "<empty>",
        )

        def _persist_progress(event: Dict[str, object]) -> None:
            payload = event.get("payload", {})
            result_item = event.get("result", {})
            event_name = str(event.get("event") or "")
            _write_json(results_path, payload)
            _write_json(replay_summary_path, payload.get("summary", {}))
            _write_json(
                status_path,
                _status_payload(
                    state="running",
                    inspection=inspection,
                    output_dir=output_dir,
                    profile_path=profile_path,
                    results_path=results_path,
                    summary_path=replay_summary_path,
                    contracts_path=contracts_path,
                    contract_count=len(contracts),
                    completed_count=len(payload.get("results", [])),
                    current_candidate_id=str(event.get("candidate_id") or "") if event_name == "contract_started" else "",
                    last_candidate_id=str(result_item.get("candidate_id") or event.get("candidate_id") or ""),
                    status_counts=payload.get("summary", {}).get("status_counts", {}),
                ),
            )
            if event_name == "contract_started":
                logger.info(
                    "cross-arch replay progress: %s/%s started candidate_id=%s",
                    event.get("contract_index", 0),
                    event.get("contract_count", len(contracts)),
                    event.get("candidate_id", ""),
                )
            elif event_name == "contract_completed":
                result_payload = result_item.get("result", {}) if isinstance(result_item.get("result"), dict) else {}
                logger.info(
                    "cross-arch replay progress: %s/%s completed candidate_id=%s status=%s",
                    event.get("contract_index", 0),
                    event.get("contract_count", len(contracts)),
                    result_item.get("candidate_id", event.get("candidate_id", "")),
                    result_payload.get("status", ""),
                )

        results = run_replay_runner_contracts(
            contracts,
            runtime_root=profile["runtime_root"],
            runtime_profile=profile,
            progress_callback=_persist_progress,
        )
        _write_json(results_path, results)
        _write_json(replay_summary_path, results.get("summary", {}))
        _write_json(
            status_path,
            _status_payload(
                state="completed",
                inspection=inspection,
                output_dir=output_dir,
                profile_path=profile_path,
                results_path=results_path,
                summary_path=replay_summary_path,
                contracts_path=contracts_path,
                contract_count=len(contracts),
                completed_count=len(results.get("results", [])),
                last_candidate_id=str(results.get("results", [{}])[-1].get("candidate_id") or "") if results.get("results") else "",
                status_counts=results.get("summary", {}).get("status_counts", {}),
            ),
        )
        logger.info(
            "cross-arch replay completed: contracts=%d statuses=%s output_dir=%s",
            len(results.get("results", [])),
            results.get("summary", {}).get("status_counts", {}),
            output_dir,
        )
    except (ReplayInterruptedError, KeyboardInterrupt) as exc:
        replay_returncode = 130 if interrupted_signal == signal.SIGINT else 143 if interrupted_signal == signal.SIGTERM else 130
        error = f"{exc.__class__.__name__}: {exc}"
        runtime_root_value = str(profile.get("runtime_root") or runtime_root or "")
        partial_results = _load_partial_results(results_path)
        if partial_results.get("results"):
            results = partial_results
        else:
            results = _empty_results_payload(len(contracts), runtime_root=runtime_root_value)
        _write_json(results_path, results)
        _write_json(replay_summary_path, results.get("summary", {}))
        _write_json(
            status_path,
            _status_payload(
                state="interrupted",
                inspection=inspection,
                output_dir=output_dir,
                profile_path=profile_path,
                results_path=results_path,
                summary_path=replay_summary_path,
                contracts_path=contracts_path,
                contract_count=len(contracts),
                completed_count=len(results.get("results", [])),
                last_candidate_id=str(results.get("results", [{}])[-1].get("candidate_id") or "") if results.get("results") else "",
                status_counts=results.get("summary", {}).get("status_counts", {}),
                error=error,
            ),
        )
        logger.warning(
            "cross-arch replay interrupted: completed=%d/%d output_dir=%s error=%s",
            len(results.get("results", [])),
            len(contracts),
            output_dir,
            error,
        )
        raise KeyboardInterrupt() from exc
    except Exception as exc:
        replay_returncode = 1
        error = f"{exc.__class__.__name__}: {exc}"
        runtime_root_value = str(profile.get("runtime_root") or runtime_root or "")
        partial_results = _load_partial_results(results_path)
        if partial_results.get("results"):
            results = partial_results
        else:
            results = _infrastructure_error_results(contracts, error, runtime_root=runtime_root_value)
        _write_json(results_path, results)
        _write_json(replay_summary_path, results.get("summary", {}))
        _write_json(
            status_path,
            _status_payload(
                state="failed",
                inspection=inspection,
                output_dir=output_dir,
                profile_path=profile_path,
                results_path=results_path,
                summary_path=replay_summary_path,
                contracts_path=contracts_path,
                contract_count=len(contracts),
                completed_count=len(results.get("results", [])),
                last_candidate_id=str(results.get("results", [{}])[-1].get("candidate_id") or "") if results.get("results") else "",
                status_counts=results.get("summary", {}).get("status_counts", {}),
                error=error,
            ),
        )
        logger.exception(
            "cross-arch replay failed: completed=%d/%d output_dir=%s",
            len(results.get("results", [])),
            len(contracts),
            output_dir,
        )
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    summary = {
        "inspection": inspection,
        "profile_path": profile_path,
        "replay_output_dir": os.path.abspath(output_dir),
        "replay_returncode": replay_returncode,
        "replay_summary": results.get("summary", {}),
        "status_path": os.path.abspath(status_path),
        "results_path": os.path.abspath(results_path),
        "error": error,
    }
    _write_json(summary_path, summary)
    return summary


def _load_partial_results(path: str) -> Dict[str, object]:
    if not os.path.isfile(path):
        return {"results": [], "summary": {}}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {"results": [], "summary": {}}
