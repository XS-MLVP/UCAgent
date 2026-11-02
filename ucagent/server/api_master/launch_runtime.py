"""Process and cluster launch runtimes, availability checks, and log collection."""

from __future__ import annotations

import json
import os
import re
import shutil
import shlex
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from ucagent.util.log import warning

from .common import (
    _LOCAL_HOSTS,
    _CONTAINER_LAUNCH_MODES,
    _LAUNCH_MODE_LABELS,
    _MASTER_SOURCE_CONTAINER_PATH,
    _SWARM_SERVICE_EXITED_STATES,
    _SWARM_SERVICE_PREFIX,
    _SWARM_SERVICE_RETENTION_SECONDS,
    _SWARM_SERVICE_RUNNING_STATES,
    _normalize_cluster_master_ip_config,
    _normalize_launch_mode,
    _normalize_launch_mode_list,
    _now,
    _parse_docker_relative_age,
    _parse_docker_timestamp,
    _plain_config_value,
    _resolve_launch_env_references,
    _swarm_task_id_from_service_name,
    _valid_env_name,
)


class LaunchRuntimeMixin:
    """Process and cluster launch runtimes, availability checks, and log collection."""

    def _start_task_process(self, task: Dict[str, Any], env: Dict[str, str]) -> subprocess.Popen:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            task["resolved_command"],
            cwd=task["workspace_dir"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        runtime = {
            "process": proc,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stdout, stdout_log, "stdout"),
                daemon=True,
                name=f"task-{task['task_id']}-stdout",
            ),
            "stderr_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stderr, stderr_log, "stderr"),
                daemon=True,
                name=f"task-{task['task_id']}-stderr",
            ),
        }
        self._task_runtime[task["task_id"]] = runtime
        runtime["stdout_thread"].start()
        runtime["stderr_thread"].start()
        return proc

    def _run_control_command(self, cmd: List[str], timeout: float = 10.0) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return 124, stdout, stderr or f"Command timed out after {timeout}s"
        except OSError as exc:
            return 127, "", str(exc)

    def _docker_cli_available(self) -> bool:
        return shutil.which("docker") is not None

    def _docker_sdk_client(self) -> Any:
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError("docker CLI was not found and Docker SDK for Python is not installed") from exc
        try:
            return docker.from_env()
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Docker SDK client: {exc}") from exc

    def _docker_sdk_network_attachment(self, network: str) -> Any:
        try:
            from docker.types import NetworkAttachmentConfig
        except ImportError:
            return network
        return NetworkAttachmentConfig(target=network)

    def _docker_swarm_local_state(self) -> str:
        if self._docker_cli_available():
            code, stdout, _stderr = self._run_control_command(
                ["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"],
                timeout=3.0,
            )
            return stdout.strip().lower() if code == 0 else ""
        try:
            info = self._docker_sdk_client().info()
            return str(((info.get("Swarm") or {}).get("LocalNodeState")) or "").strip().lower()
        except Exception:
            return ""

    def _docker_network_inspect_data(self, network: str) -> Tuple[Dict[str, Any], str]:
        network = str(network or "").strip()
        if not network:
            return {}, "network name is empty"
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "network", "inspect", network],
                timeout=5.0,
            )
            if code != 0:
                return {}, (stderr or stdout or f"Docker network '{network}' was not found").strip()
            try:
                data = json.loads(stdout)
                if isinstance(data, list) and data:
                    return data[0], ""
                if isinstance(data, dict):
                    return data, ""
            except json.JSONDecodeError as exc:
                return {}, f"failed to parse docker network inspect output for '{network}': {exc}"
            return {}, f"docker network inspect returned no data for '{network}'"
        try:
            network_obj = self._docker_sdk_client().networks.get(network)
            return dict(network_obj.attrs or {}), ""
        except Exception as exc:
            return {}, str(exc)

    def _ensure_docker_task_network(self, mode: str, network: str) -> Dict[str, Any]:
        network = str(network or "").strip()
        if not network:
            return {}
        info, error = self._docker_network_inspect_data(network)
        if not info:
            create_overlay = mode == "docker_swarm" or self._docker_swarm_local_state() == "active"
            if self._docker_cli_available():
                cmd = ["docker", "network", "create"]
                if create_overlay:
                    cmd.extend(["--driver", "overlay", "--attachable"])
                cmd.append(network)
                code, stdout, stderr = self._run_control_command(cmd, timeout=15.0)
                if code != 0:
                    raise ValueError(f"failed to create Docker network '{network}': {(stderr or stdout).strip() or error}")
            else:
                try:
                    kwargs = {"driver": "overlay", "attachable": True} if create_overlay else {"driver": "bridge"}
                    self._docker_sdk_client().networks.create(network, **kwargs)
                except Exception as exc:
                    raise ValueError(f"failed to create Docker network '{network}' via Docker SDK: {exc}") from exc
            info, error = self._docker_network_inspect_data(network)
            if not info:
                raise ValueError(f"Docker network '{network}' is unavailable after create: {error}")
        if mode == "docker_swarm":
            driver = str(info.get("Driver") or "").lower()
            scope = str(info.get("Scope") or "").lower()
            if driver != "overlay" or scope != "swarm":
                raise ValueError(
                    f"Docker network '{network}' is {driver or 'unknown'}/{scope or 'unknown'}, "
                    "expected overlay/swarm for Docker Swarm launch mode"
                )
        return info

    def _docker_inspect_container_id(self, candidate: str) -> str:
        candidate = str(candidate or "").strip().lstrip("/")
        if not candidate:
            return ""
        if self._docker_cli_available():
            code, stdout, _stderr = self._run_control_command(
                ["docker", "inspect", "--type", "container", "-f", "{{.Id}}", candidate],
                timeout=3.0,
            )
            return stdout.strip() if code == 0 else ""
        try:
            container = self._docker_sdk_client().containers.get(candidate)
            return str(container.id or (container.attrs or {}).get("Id") or "").strip()
        except Exception:
            return ""

    def _running_inside_container(self) -> bool:
        if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
            return True
        for path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if re.search(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", text):
                return True
            if any(marker in text for marker in ("/docker/", "/kubepods/", "/containerd/")):
                return True
        return False

    def _current_docker_container_id(self) -> str:
        explicit = [
            os.environ.get("UCAGENT_MASTER_CONTAINER_ID", ""),
            os.environ.get("UCAGENT_MASTER_CONTAINER", ""),
        ]
        candidates: List[str] = [str(item).strip() for item in explicit if str(item or "").strip()]
        cgroup_candidates: List[str] = []
        for path in ("/proc/self/cgroup", "/proc/self/mountinfo"):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            cgroup_candidates.extend(re.findall(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", text))
        if self._running_inside_container():
            candidates.extend(cgroup_candidates)
            candidates.append(os.environ.get("HOSTNAME", ""))
            try:
                with open("/etc/hostname", "r", encoding="utf-8", errors="replace") as fh:
                    candidates.append(fh.read().strip())
            except OSError:
                pass
        seen = set()
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            container_id = self._docker_inspect_container_id(candidate)
            if container_id:
                return container_id
        return ""

    def _docker_container_networks(self, container_id: str) -> Tuple[Dict[str, Any], str]:
        container_id = str(container_id or "").strip()
        if not container_id:
            return {}, "container id is empty"
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", container_id],
                timeout=5.0,
            )
            if code != 0:
                return {}, (stderr or stdout or f"failed to inspect Docker container '{container_id}'").strip()
            try:
                data = json.loads(stdout or "{}")
                return data if isinstance(data, dict) else {}, ""
            except json.JSONDecodeError as exc:
                return {}, f"failed to parse Docker container network data: {exc}"
        try:
            container = self._docker_sdk_client().containers.get(container_id)
            networks = (((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {})
            return dict(networks), ""
        except Exception as exc:
            return {}, str(exc)

    def _docker_network_aliases_for_master(self, mode: str) -> List[str]:
        aliases: List[str] = ["ucagent_master"]
        host = self._cluster_master_ip(mode).strip()
        host_l = host.lower()
        if (
            host
            and host_l not in {"host.docker.internal", "localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
            and not re.match(r"^\d+(?:\.\d+){3}$", host)
            and re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", host)
        ):
            aliases.insert(0, host)
        deduped: List[str] = []
        for alias in aliases:
            if alias not in deduped:
                deduped.append(alias)
        return deduped

    def _docker_master_network_host(self, mode: str, container_id: str, network_data: Dict[str, Any]) -> str:
        aliases = [
            str(item).strip()
            for item in (network_data.get("Aliases") or [])
            if str(item or "").strip()
        ]
        preferred = self._docker_network_aliases_for_master(mode)
        for alias in preferred:
            if alias in aliases:
                return alias
        container_id = str(container_id or "").strip()
        short_id = container_id[:12]
        for alias in aliases:
            if alias and alias not in {container_id, short_id}:
                return alias
        return aliases[0] if aliases else short_id

    def _ensure_master_on_docker_network(self, mode: str, network: str, task: Optional[Dict[str, Any]] = None) -> str:
        network = str(network or "").strip()
        if not network:
            return ""
        container_id = self._current_docker_container_id()
        if not container_id:
            if self._running_inside_container():
                raise ValueError(
                    "master appears to be running inside a container, but its Docker container id could not be resolved. "
                    "Set UCAGENT_MASTER_CONTAINER_ID or run the master container with Docker socket access so task "
                    f"containers can join the same Docker network '{network}'."
                )
            if task is not None:
                self._append_task_log(
                    task["stdout_log_path"],
                    f"Master is not running inside a Docker container; task will use configured master address {self._cluster_master_ip(mode)}.",
                )
            return ""
        networks, error = self._docker_container_networks(container_id)
        if network in networks:
            aliases = set(str(item) for item in ((networks.get(network) or {}).get("Aliases") or []))
            missing_aliases = [alias for alias in self._docker_network_aliases_for_master(mode) if alias not in aliases]
            if missing_aliases and task is not None:
                self._append_task_log(
                    task["stdout_log_path"],
                    f"Master container is already on Docker network '{network}' but is missing preferred aliases: {', '.join(missing_aliases)}.",
                )
            return self._docker_master_network_host(mode, container_id, networks.get(network) or {})
        aliases = self._docker_network_aliases_for_master(mode)
        if self._docker_cli_available():
            cmd = ["docker", "network", "connect"]
            for alias in aliases:
                cmd.extend(["--alias", alias])
            cmd.extend([network, container_id])
            code, stdout, stderr = self._run_control_command(cmd, timeout=15.0)
            if code != 0:
                raise ValueError(
                    f"failed to connect master container to Docker network '{network}': "
                    f"{(stderr or stdout).strip() or error}"
                )
        else:
            try:
                network_obj = self._docker_sdk_client().networks.get(network)
                network_obj.connect(container_id, aliases=aliases)
            except Exception as exc:
                raise ValueError(f"failed to connect master container to Docker network '{network}' via Docker SDK: {exc}") from exc
        if task is not None:
            self._append_task_log(
                task["stdout_log_path"],
                f"Connected master container to Docker network '{network}' with aliases: {', '.join(aliases)}.",
            )
        return aliases[0] if aliases else container_id[:12]

    def _prepare_docker_task_network(self, mode: str, network: str, task: Optional[Dict[str, Any]] = None) -> str:
        network = str(network or "").strip()
        if not network:
            return ""
        self._ensure_docker_task_network(mode, network)
        return self._ensure_master_on_docker_network(mode, network, task)

    def _k8s_cli_available(self) -> bool:
        return shutil.which("kubectl") is not None

    def _k8s_sdk_clients(self) -> Tuple[Any, Any]:
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config
        except ImportError as exc:
            raise RuntimeError("kubectl CLI was not found and Kubernetes Python client is not installed") from exc
        try:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            return k8s_client, k8s_client.CoreV1Api()
        except Exception as exc:
            raise RuntimeError(f"failed to initialize Kubernetes Python client: {exc}") from exc

    def _append_task_log(self, path: str, message: str) -> None:
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(message)
                if message and not message.endswith("\n"):
                    fh.write("\n")
        except OSError as exc:
            warning(f"Failed to append task log '{path}': {exc}")

    def _launch_cluster_config(self) -> Dict[str, Any]:
        cfg = _plain_config_value(self.cfg.get_value("launch.cluster", {}) or {})
        if not isinstance(cfg, dict):
            cfg = {}
        return {
            "image": str(cfg.get("image") or os.environ.get("UCAGENT_LAUNCH_IMAGE") or "ucagent:latest"),
            "container_command": cfg.get("container_command") or "ucagent",
            "master_ip": _normalize_cluster_master_ip_config(cfg.get("master_ip")),
            "docker_network": str(cfg.get("docker_network") or ""),
            "docker_extra_args": cfg.get("docker_extra_args") if isinstance(cfg.get("docker_extra_args"), list) else [],
            "swarm_extra_args": cfg.get("swarm_extra_args") if isinstance(cfg.get("swarm_extra_args"), list) else [],
            "k8s_namespace": str(cfg.get("k8s_namespace") or "default"),
            "k8s_image_pull_policy": str(cfg.get("k8s_image_pull_policy") or "IfNotPresent"),
            "k8s_service_account": str(cfg.get("k8s_service_account") or ""),
            "k8s_node_selector": cfg.get("k8s_node_selector") if isinstance(cfg.get("k8s_node_selector"), dict) else {},
            "k8s_tolerations": cfg.get("k8s_tolerations") if isinstance(cfg.get("k8s_tolerations"), list) else [],
            "k8s_resources": cfg.get("k8s_resources") if isinstance(cfg.get("k8s_resources"), dict) else {},
            "extra_mounts": cfg.get("extra_mounts") if isinstance(cfg.get("extra_mounts"), list) else [],
        }

    def _docker_available(self) -> Tuple[bool, str]:
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(["docker", "info"], timeout=3.0)
            if code != 0:
                return False, (stderr or stdout or "docker daemon is not reachable").strip()
            return True, "Docker daemon is reachable via docker CLI"
        try:
            client = self._docker_sdk_client()
            client.ping()
            return True, "Docker daemon is reachable via Docker SDK"
        except Exception as exc:
            return False, str(exc)

    def _docker_swarm_available(self) -> Tuple[bool, str]:
        docker_ok, docker_msg = self._docker_available()
        if not docker_ok:
            return False, docker_msg
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"],
                timeout=3.0,
            )
            if code != 0:
                return False, (stderr or stdout or "failed to inspect Docker Swarm state").strip()
            state = stdout.strip().lower()
        else:
            try:
                info = self._docker_sdk_client().info()
                state = str(((info.get("Swarm") or {}).get("LocalNodeState")) or "").strip().lower()
            except Exception as exc:
                return False, f"failed to inspect Docker Swarm state via Docker SDK: {exc}"
        if state != "active":
            return False, f"Docker Swarm is not active (state: {state or 'unknown'})"
        return True, "Docker Swarm is active"

    def _k8s_available(self) -> Tuple[bool, str]:
        if self._k8s_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["kubectl", "cluster-info", "--request-timeout=3s"],
                timeout=5.0,
            )
            if code != 0:
                return False, (stderr or stdout or "Kubernetes cluster is not reachable").strip()
            return True, "Kubernetes cluster is reachable via kubectl"
        try:
            _k8s_client, core = self._k8s_sdk_clients()
            core.list_namespace(limit=1)
            return True, "Kubernetes cluster is reachable via Kubernetes Python client"
        except Exception as exc:
            return False, str(exc)

    def _launch_mode_options(self) -> List[Dict[str, Any]]:
        docker_ok, docker_msg = self._docker_available()
        swarm_ok, swarm_msg = self._docker_swarm_available() if docker_ok else (False, docker_msg)
        k8s_ok, k8s_msg = self._k8s_available()
        raw_options = [
            {"value": "process", "name": _LAUNCH_MODE_LABELS["process"], "enabled": True, "reason": "Always available"},
            {"value": "docker", "name": _LAUNCH_MODE_LABELS["docker"], "enabled": docker_ok, "reason": docker_msg},
            {"value": "docker_swarm", "name": _LAUNCH_MODE_LABELS["docker_swarm"], "enabled": swarm_ok, "reason": swarm_msg},
            {"value": "k8s", "name": _LAUNCH_MODE_LABELS["k8s"], "enabled": k8s_ok, "reason": k8s_msg},
        ]
        enabled_modes = self._enabled_launch_modes()
        enabled_set = set(enabled_modes)
        options_by_value = {item["value"]: item for item in raw_options}
        ordered_values = [mode for mode in enabled_modes if mode in options_by_value]
        ordered_values.extend([item["value"] for item in raw_options if item["value"] not in ordered_values])
        options = []
        for value in ordered_values:
            item = dict(options_by_value[value])
            item["configured"] = value in enabled_set
            if not item["configured"]:
                item["enabled"] = False
                item["reason"] = "Not enabled by launch.default_args.launch_mode"
            options.append(item)
        return options

    def _enabled_launch_modes(self) -> List[str]:
        default_args = _plain_config_value(self.cfg.get_value("launch.default_args", {}) or {})
        raw_modes: Any = ["process"]
        if isinstance(default_args, dict):
            raw_modes = default_args.get("launch_mode", ["process"])
        return _normalize_launch_mode_list(raw_modes)

    def _ensure_launch_mode_supported(self, launch_mode: str) -> None:
        if launch_mode == "process":
            return
        for item in self._launch_mode_options():
            if item["value"] == launch_mode:
                if item["enabled"]:
                    return
                raise ValueError(f"Launch mode '{launch_mode}' is not available: {item['reason']}")
        raise ValueError(f"Launch mode '{launch_mode}' is not configured")

    def _cluster_master_ip(self, launch_mode: str) -> str:
        master_ip = self._launch_cluster_config().get("master_ip") or "127.0.0.1"
        if isinstance(master_ip, dict):
            mode = _normalize_launch_mode(launch_mode)
            master_ip = master_ip.get(mode) or master_ip.get("process") or "127.0.0.1"
        if str(master_ip).strip().lower() in {"0.0.0.0", "::", "[::]"}:
            return "127.0.0.1"
        return str(master_ip).strip() or "127.0.0.1"

    def _launch_bind_host(self, launch_mode: str, host: str) -> str:
        raw = str(host or "").strip() or "127.0.0.1"
        if launch_mode in _CONTAINER_LAUNCH_MODES and raw.lower() in _LOCAL_HOSTS:
            return "0.0.0.0"
        return raw

    def _service_base_url(self, launch_mode: str, bind_host: str, port: int) -> str:
        host = bind_host
        if str(host).strip().lower() in {"0.0.0.0", "::", "[::]", ""}:
            host = "127.0.0.1"
        return f"http://{host}:{port}"

    def _master_source_host_path(self) -> str:
        raw = str(os.environ.get("UCAGENT_MASTER_SOURCE", "") or "").strip()
        if not raw:
            return ""
        return os.path.abspath(raw)

    def _master_source_cli_path(self) -> str:
        source_host_path = self._master_source_host_path()
        if not source_host_path:
            return ""
        return os.path.join(source_host_path, "ucagent", "cli.py")

    def _master_source_container_cli_path(self) -> str:
        return os.path.join(_MASTER_SOURCE_CONTAINER_PATH, "ucagent", "cli.py")

    def _container_command(self, resolved_command: List[str]) -> List[str]:
        cfg = self._launch_cluster_config()
        configured = cfg.get("container_command") or "ucagent"
        if self._master_source_host_path():
            configured = ["python3", self._master_source_container_cli_path()]
        if isinstance(configured, list):
            prefix = [str(item) for item in configured if str(item).strip()]
        else:
            prefix = shlex.split(str(configured)) if str(configured).strip() else ["ucagent"]
        if len(resolved_command) >= 2:
            return prefix + [str(item) for item in resolved_command[2:]]
        return prefix + [str(item) for item in resolved_command]

    def _cluster_mounts(self, prepared: Dict[str, Any]) -> List[Tuple[str, str]]:
        cfg = self._launch_cluster_config()
        mounts: List[Tuple[str, str]] = []
        seen = set()

        def add_mount(source: Any, target: Any = None, *, require_exists: bool = True) -> None:
            src = os.path.abspath(str(source or "").strip())
            dst = str(target or source or "").strip()
            if not src or not dst:
                return
            if require_exists and not os.path.exists(src):
                return
            key = (src, dst)
            if key in seen:
                return
            seen.add(key)
            mounts.append((src, dst))

        if not (prepared.get("use_zip_workspace") is True):
            add_mount(prepared.get("workspace_dir"))
        source_host_path = self._master_source_host_path()
        if source_host_path:
            add_mount(source_host_path, _MASTER_SOURCE_CONTAINER_PATH, require_exists=False)
        for item in cfg.get("extra_mounts") or []:
            if isinstance(item, dict):
                add_mount(item.get("source") or item.get("src"), item.get("target") or item.get("dst"))
            elif isinstance(item, str) and ":" in item:
                source, target = item.split(":", 1)
                add_mount(source, target)
        return mounts

    def _cluster_launch_context(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        cfg = self._launch_cluster_config()
        use_zip_workspace = prepared.get("use_zip_workspace") is True
        context = {
            "cfg": cfg,
            "name": f"ucagent-{task['task_id']}",
            "env": self._cluster_env(env, task.get("env") or {}),
            "mounts": self._cluster_mounts(prepared),
            "network": str(cfg.get("docker_network") or "").strip() if mode in {"docker", "docker_swarm"} else "",
            "picker_workspace": "/tmp" if use_zip_workspace else (prepared.get("picker_workspace") or prepared["workspace_dir"]),
            "command": self._container_command(task["resolved_command"]),
        }
        self._append_cluster_launch_debug(
            task,
            mode,
            context["name"],
            cfg["image"],
            context["command"],
            context["mounts"],
            context["network"],
        )
        return context

    def _set_cluster_record(
        self,
        task: Dict[str, Any],
        mode: str,
        kind: str,
        name: str,
        image: Any,
        cluster_id: str = "",
        **extra: Any,
    ) -> Dict[str, Any]:
        cluster = {
            "mode": mode,
            "kind": kind,
            "name": name,
            "image": image,
        }
        if cluster_id:
            cluster["id"] = cluster_id
        cluster.update(extra)
        task["cluster"] = cluster
        return cluster

    def _cluster_ports(
        self,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        ports = []
        seen = set()

        def add(name: str, svc: Dict[str, Any]) -> None:
            if not svc.get("enabled"):
                return
            try:
                port = int(svc.get("port"))
            except (TypeError, ValueError):
                return
            if port in seen:
                return
            seen.add(port)
            ports.append({"name": name, "host_port": port, "container_port": port})

        add("cmd-api", cmd_api)
        add("terminal-api", terminal_api)
        add("web-console", web_console)
        return ports

    def _published_ports(
        self,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
        launch_mode: str = "docker",
        master_host_for_task: str = "",
    ) -> List[Dict[str, Any]]:
        if launch_mode != "docker":
            return []
        if master_host_for_task:
            return []
        return self._cluster_ports(cmd_api, terminal_api, web_console)

    def _docker_extra_args(self, cfg: Dict[str, Any]) -> List[str]:
        args = [str(item) for item in cfg.get("docker_extra_args") or [] if str(item).strip()]
        if self._cluster_master_ip("docker") == "host.docker.internal":
            has_host_mapping = any(
                arg == "--add-host=host.docker.internal:host-gateway"
                or (
                    arg == "--add-host"
                    and index + 1 < len(args)
                    and args[index + 1] == "host.docker.internal:host-gateway"
                )
                for index, arg in enumerate(args)
            )
            if not has_host_mapping:
                args.insert(0, "--add-host=host.docker.internal:host-gateway")
        return args

    def _write_docker_env_file(self, task: Dict[str, Any], env: Dict[str, str]) -> str:
        path = os.path.join(self._logs_dir, f"{task['task_id']}.docker.env")
        lines = []
        for key, value in sorted((env or {}).items()):
            key = str(key)
            if not _valid_env_name(key):
                continue
            escaped = str(value).replace("\\", "\\\\").replace("\n", "\\n")
            lines.append(f"{key}={escaped}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def _cluster_env(self, env: Dict[str, str], requested_env: Dict[str, Any]) -> Dict[str, str]:
        selected: Dict[str, str] = {}
        configured = self.cfg.get_value("launch.default_env", []) or []
        if hasattr(configured, "as_dict"):
            configured = configured.as_dict()
        for entry in configured if isinstance(configured, list) else []:
            if hasattr(entry, "as_dict"):
                entry = entry.as_dict()
            if isinstance(entry, str):
                key = entry.strip()
            elif isinstance(entry, dict) and len(entry) == 1:
                key = str(next(iter(entry.keys()))).strip()
            else:
                continue
            if key and key in env:
                selected[key] = str(env[key])
        for key, value in (requested_env or {}).items():
            selected[str(key)] = str(value)
        selected = _resolve_launch_env_references(selected, env)
        selected.setdefault("PYTHONUNBUFFERED", "1")
        return selected

    def _start_external_log_capture(self, task: Dict[str, Any], cmd: List[str]) -> None:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self._append_task_log(task["stderr_log_path"], f"Failed to start log capture: {exc}")
            try:
                stdout_log.close()
                stderr_log.close()
            except OSError:
                pass
            return
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        runtime.update({
            "log_process": proc,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stdout, stdout_log, "stdout"),
                daemon=True,
                name=f"task-{task['task_id']}-external-stdout",
            ),
            "stderr_thread": threading.Thread(
                target=self._pipe_task_log,
                args=(task["task_id"], proc.stderr, stderr_log, "stderr"),
                daemon=True,
                name=f"task-{task['task_id']}-external-stderr",
            ),
        })
        runtime["stdout_thread"].start()
        runtime["stderr_thread"].start()

    def _start_stream_log_capture(self, task: Dict[str, Any], stream_factory: Any, label: str) -> None:
        stdout_log = open(task["stdout_log_path"], "a", encoding="utf-8", buffering=1)
        stderr_log = open(task["stderr_log_path"], "a", encoding="utf-8", buffering=1)
        stop_event = threading.Event()

        def run() -> None:
            try:
                for chunk in stream_factory():
                    if stop_event.is_set():
                        break
                    if chunk is None:
                        continue
                    if isinstance(chunk, bytes):
                        text = chunk.decode("utf-8", errors="replace")
                    else:
                        text = str(chunk)
                    stdout_log.write(text)
                    if text and not text.endswith("\n"):
                        stdout_log.write("\n")
            except Exception as exc:
                stderr_log.write(f"{label} log capture failed: {exc}\n")
            finally:
                try:
                    stdout_log.flush()
                    stderr_log.flush()
                except Exception:
                    pass

        thread = threading.Thread(
            target=run,
            daemon=True,
            name=f"task-{task['task_id']}-{label}-logs",
        )
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        runtime.update({
            "log_stop_event": stop_event,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "stdout_thread": thread,
        })
        thread.start()

    def _docker_sdk_log_capture(self, task: Dict[str, Any], kind: str, name: str) -> None:
        def stream_factory() -> Any:
            client = self._docker_sdk_client()
            if kind == "container":
                return client.containers.get(name).logs(stream=True, follow=True, stdout=True, stderr=True)
            return client.api.service_logs(name, follow=True, stdout=True, stderr=True)

        self._start_stream_log_capture(task, stream_factory, f"docker-{kind}")

    def _k8s_sdk_log_capture(self, task: Dict[str, Any], namespace: str, pod_name: str) -> None:
        def stream_factory() -> Any:
            _k8s_client, core = self._k8s_sdk_clients()
            name = pod_name
            deadline = time.time() + 60.0
            while not name and time.time() < deadline:
                name = self._k8s_pod_name_for_job(namespace, str((task.get("cluster") or {}).get("name") or ""))
                if not name:
                    time.sleep(1.0)
            if not name:
                raise RuntimeError("Kubernetes job did not create a pod within 60s")
            return core.read_namespaced_pod_log(
                name=name,
                namespace=namespace,
                follow=True,
                _preload_content=False,
            ).stream()

        self._start_stream_log_capture(task, stream_factory, "k8s")

    def _k8s_pod_name_for_job(self, namespace: str, job_name: str) -> str:
        _k8s_client, core = self._k8s_sdk_clients()
        pods = core.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        items = pods.items or []
        if not items:
            return ""
        return str(items[0].metadata.name or "")

    def _append_cluster_launch_debug(
        self,
        task: Dict[str, Any],
        mode: str,
        name: str,
        image: Any,
        command: List[str],
        mounts: List[Tuple[str, str]],
        network: str = "",
    ) -> None:
        self._append_task_log(
            task["stdout_log_path"],
            (
                f"Cluster launch debug: mode={mode} name={name} image={image}\n"
                f"  command={shlex.join([str(item) for item in command])}\n"
                f"  mounts={json.dumps([{'source': s, 'target': t} for s, t in mounts], ensure_ascii=False)}\n"
                f"  network={network or '<none>'}"
            ),
        )

    def _append_docker_connectivity_debug(
        self,
        task: Dict[str, Any],
        launch_mode: str,
        master_host_for_task: str,
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> None:
        published = self._published_ports(cmd_api, terminal_api, web_console, launch_mode, master_host_for_task)
        self._append_task_log(
            task["stdout_log_path"],
            (
                "Docker connectivity debug: "
                f"master_host_for_task={master_host_for_task or self._cluster_master_ip(launch_mode)} "
                f"published_ports={json.dumps(published, ensure_ascii=False)}"
            ),
        )

    def _docker_swarm_task_detail(self, name: str) -> str:
        if not name:
            return ""
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                [
                    "docker", "service", "ps", name, "--no-trunc",
                    "--format", "ID={{.ID}} Name={{.Name}} Node={{.Node}} Desired={{.DesiredState}} Current={{.CurrentState}} Error={{.Error}} Image={{.Image}}",
                ],
                timeout=5.0,
            )
            return (stdout or stderr).strip() if code == 0 else (stderr or stdout).strip()
        try:
            service = self._docker_sdk_client().services.get(name)
            lines = []
            for item in service.tasks():
                status = item.get("Status") or {}
                spec = item.get("Spec") or {}
                container = spec.get("ContainerSpec") or {}
                lines.append(
                    "ID={id} Node={node} Desired={desired} State={state} Message={message} Error={error} Image={image}".format(
                        id=item.get("ID", ""),
                        node=item.get("NodeID", ""),
                        desired=item.get("DesiredState", ""),
                        state=status.get("State", ""),
                        message=status.get("Message", ""),
                        error=status.get("Err", ""),
                        image=container.get("Image", ""),
                    )
                )
            return "\n".join(lines)
        except Exception as exc:
            return str(exc)

    def _docker_swarm_service_state(self, name: str) -> Dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            return {"exists": False, "active": False, "exited": False, "detail": "missing service name"}
        if self._docker_cli_available():
            code, inspect_out, inspect_err = self._run_control_command(
                ["docker", "service", "inspect", name, "--format", "{{json .}}"],
                timeout=5.0,
            )
            if code != 0:
                return {
                    "exists": False,
                    "active": False,
                    "exited": False,
                    "detail": (inspect_err or inspect_out).strip(),
                }
            service_data: Dict[str, Any] = {}
            try:
                parsed = json.loads(inspect_out)
                service_data = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                service_data = {}
            code, stdout, stderr = self._run_control_command(
                ["docker", "service", "ps", name, "--no-trunc", "--format", "{{json .}}"],
                timeout=5.0,
            )
            if code != 0:
                return {
                    "exists": True,
                    "active": False,
                    "exited": False,
                    "detail": (stderr or stdout).strip(),
                    "created_at": _parse_docker_timestamp(service_data.get("CreatedAt")),
                    "updated_at": _parse_docker_timestamp(service_data.get("UpdatedAt")),
                }
            states: List[str] = []
            current_states: List[str] = []
            last_status_at = 0.0
            now = _now()
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    item = {"CurrentState": line}
                current = str(item.get("CurrentState") or "").strip()
                current_states.append(current)
                state = current.split(None, 1)[0].lower() if current else ""
                if state:
                    states.append(state)
                age = _parse_docker_relative_age(current)
                if age >= 0:
                    last_status_at = max(last_status_at, now - age)
            active = any(state in _SWARM_SERVICE_RUNNING_STATES for state in states)
            exited = bool(states) and not active and all(state in _SWARM_SERVICE_EXITED_STATES for state in states)
            return {
                "exists": True,
                "active": active,
                "exited": exited,
                "states": states,
                "current_states": current_states,
                "detail": "\n".join(current_states) or stdout.strip(),
                "created_at": _parse_docker_timestamp(service_data.get("CreatedAt")),
                "updated_at": _parse_docker_timestamp(service_data.get("UpdatedAt")),
                "last_status_at": last_status_at,
            }
        try:
            service = self._docker_sdk_client().services.get(name)
            attrs = service.attrs or {}
            states: List[str] = []
            messages: List[str] = []
            last_status_at = 0.0
            for item in service.tasks():
                status = item.get("Status") or {}
                state = str(status.get("State") or "").strip().lower()
                if state:
                    states.append(state)
                message = str(status.get("Message") or "").strip()
                error = str(status.get("Err") or "").strip()
                if state or message or error:
                    messages.append(" ".join(part for part in (state, message, error) if part))
                last_status_at = max(last_status_at, _parse_docker_timestamp(status.get("Timestamp")))
            active = any(state in _SWARM_SERVICE_RUNNING_STATES for state in states)
            exited = bool(states) and not active and all(state in _SWARM_SERVICE_EXITED_STATES for state in states)
            return {
                "exists": True,
                "active": active,
                "exited": exited,
                "states": states,
                "current_states": messages,
                "detail": "\n".join(messages),
                "created_at": _parse_docker_timestamp(attrs.get("CreatedAt")),
                "updated_at": _parse_docker_timestamp(attrs.get("UpdatedAt")),
                "last_status_at": last_status_at,
            }
        except Exception as exc:
            return {"exists": False, "active": False, "exited": False, "detail": str(exc)}

    def _remove_docker_swarm_service(self, name: str, task: Optional[Dict[str, Any]] = None, reason: str = "") -> bool:
        name = str(name or "").strip()
        if not name:
            return False
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(["docker", "service", "rm", name], timeout=15.0)
            if code != 0:
                if task is not None:
                    self._append_task_log(
                        task["stderr_log_path"],
                        f"Failed to remove Docker Swarm service {name}: {(stderr or stdout).strip()}",
                    )
                return False
        else:
            try:
                self._docker_sdk_client().services.get(name).remove()
            except Exception as exc:
                if task is not None:
                    self._append_task_log(
                        task["stderr_log_path"],
                        f"Failed to remove Docker Swarm service {name} via SDK: {exc}",
                    )
                return False
        if task is not None:
            suffix = f" ({reason})" if reason else ""
            self._append_task_log(task["stdout_log_path"], f"Removed Docker Swarm service {name}{suffix}")
        return True

    def _remove_exited_swarm_service_before_launch(self, task: Dict[str, Any], name: str) -> None:
        state = self._docker_swarm_service_state(name)
        if not state.get("exists"):
            return
        detail = str(state.get("detail") or "").strip()
        if state.get("exited"):
            removed = self._remove_docker_swarm_service(name, task, reason="exited service before relaunch")
            if not removed:
                raise ValueError(f"Docker Swarm service {name} already exists and could not be removed: {detail}")
            return
        if state.get("active"):
            raise ValueError(f"Docker Swarm service {name} already exists and is still active: {detail}")
        raise ValueError(f"Docker Swarm service {name} already exists and its state is unknown: {detail}")

    def _list_ucagent_swarm_services(self) -> List[Dict[str, Any]]:
        if self._docker_cli_available():
            code, stdout, stderr = self._run_control_command(
                ["docker", "service", "ls", "--format", "{{json .}}"],
                timeout=8.0,
            )
            if code != 0:
                warning(f"Failed to list Docker Swarm services: {(stderr or stdout).strip()}")
                return []
            services: List[Dict[str, Any]] = []
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = str(item.get("Name") or item.get("name") or "").strip()
                if name.startswith(_SWARM_SERVICE_PREFIX):
                    services.append({"name": name, "raw": item})
            return services
        try:
            services = []
            for service in self._docker_sdk_client().services.list():
                name = str((service.attrs or {}).get("Spec", {}).get("Name") or service.name or "").strip()
                if name.startswith(_SWARM_SERVICE_PREFIX):
                    services.append({"name": name, "raw": service.attrs or {}})
            return services
        except Exception as exc:
            warning(f"Failed to list Docker Swarm services via SDK: {exc}")
            return []

    def _swarm_service_finished_at(self, task: Optional[Dict[str, Any]], state: Dict[str, Any]) -> float:
        if task is not None:
            try:
                value = float(task.get("finished_at") or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        for key in ("last_status_at", "updated_at", "created_at"):
            try:
                value = float(state.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
        return 0.0

    def _cleanup_stale_swarm_services(self) -> int:
        if self._docker_swarm_local_state() != "active":
            return 0
        services = self._list_ucagent_swarm_services()
        if not services:
            return 0
        now = _now()
        with self._tasks_lock:
            tasks_snapshot = {task_id: dict(task) for task_id, task in self._tasks.items()}
        cleaned = 0
        for service in services:
            name = str(service.get("name") or "").strip()
            if not name.startswith(_SWARM_SERVICE_PREFIX):
                continue
            state = self._docker_swarm_service_state(name)
            if not state.get("exists") or not state.get("exited") or state.get("active"):
                continue
            task_id = _swarm_task_id_from_service_name(name)
            task = tasks_snapshot.get(task_id)
            if task is not None:
                finished_at = self._swarm_service_finished_at(task, state)
                if not finished_at or now - finished_at <= _SWARM_SERVICE_RETENTION_SECONDS:
                    continue
            if self._remove_docker_swarm_service(name):
                cleaned += 1
        return cleaned

    def _cluster_job_status(self, active: int, succeeded: int, failed: int) -> Tuple[bool, Optional[int], str]:
        detail = f"active={active} succeeded={succeeded} failed={failed}"
        if active > 0:
            return True, None, detail
        if succeeded > 0:
            return False, 0, detail
        if failed > 0:
            return False, 1, detail
        return True, None, detail

    def _int_or_zero(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _start_task_docker(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
        master_host_for_task: str = "",
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "docker")
        cfg = context["cfg"]
        name = context["name"]
        if not self._docker_cli_available():
            client = self._docker_sdk_client()
            network = str(cfg.get("docker_network") or "").strip() or None
            volumes = {
                source: {"bind": target, "mode": "rw"}
                for source, target in context["mounts"]
            }
            ports = {
                f"{port['container_port']}/tcp": port["host_port"]
                for port in self._published_ports(cmd_api, terminal_api, web_console, "docker", master_host_for_task)
            } or None
            container = client.containers.run(
                image=str(cfg["image"]),
                command=context["command"],
                name=name,
                detach=True,
                environment=context["env"],
                network=network,
                volumes=volumes,
                working_dir=context["picker_workspace"],
                ports=ports,
                remove="--rm" in self._docker_extra_args(cfg),
            )
            self._set_cluster_record(task, "docker", "container", name, cfg["image"], cluster_id=container.id)
            self._append_task_log(task["stdout_log_path"], f"Started Docker container {name} {container.id}")
            self._docker_sdk_log_capture(task, "container", name)
            return task["cluster"]

        env_file = self._write_docker_env_file(task, context["env"])
        cmd = ["docker", "run", "-d", "--name", name, "--env-file", env_file]
        network = str(cfg.get("docker_network") or "").strip()
        if network:
            cmd.extend(["--network", network])
        for source, target in context["mounts"]:
            cmd.extend(["-v", f"{source}:{target}"])
        cmd.extend(["--workdir", context["picker_workspace"]])
        for port in self._published_ports(cmd_api, terminal_api, web_console, "docker", master_host_for_task):
            cmd.extend(["-p", f"{port['host_port']}:{port['container_port']}"])
        cmd.extend(self._docker_extra_args(cfg))
        cmd.append(str(cfg["image"]))
        cmd.extend(context["command"])
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"docker run failed: {(stderr or stdout).strip()}")
        container_id = stdout.strip()
        self._set_cluster_record(task, "docker", "container", name, cfg["image"], cluster_id=container_id)
        self._append_task_log(task["stdout_log_path"], f"Started Docker container {name} {container_id}")
        self._start_external_log_capture(task, ["docker", "logs", "-f", name])
        return task["cluster"]

    def _start_task_docker_swarm(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "docker_swarm")
        cfg = context["cfg"]
        name = context["name"]
        self._remove_exited_swarm_service_before_launch(task, name)
        if not self._docker_cli_available():
            client = self._docker_sdk_client()
            mounts = [
                {"Type": "bind", "Source": source, "Target": target}
                for source, target in context["mounts"]
            ]
            task_template = {
                "ContainerSpec": {
                    "Image": str(cfg["image"]),
                    "Command": context["command"],
                    "Env": [
                        f"{key}={value}"
                        for key, value in sorted(context["env"].items())
                        if _valid_env_name(str(key))
                    ],
                    "Mounts": mounts,
                    "Dir": context["picker_workspace"],
                },
                "RestartPolicy": {"Condition": "none"},
            }
            network = context["network"]
            if network:
                task_template["Networks"] = [self._docker_sdk_network_attachment(network)]
            service_data = client.api.create_service(
                task_template=task_template,
                name=name,
                mode={"ReplicatedJob": {"TotalCompletions": 1, "MaxConcurrent": 1}},
            )
            service_id = str(service_data.get("ID") or "")
            if network:
                inspect_data = client.api.inspect_service(service_id)
                attached_networks = [
                    str(item.get("Target") or item.get("NetworkID") or "")
                    for item in ((inspect_data.get("Spec") or {}).get("TaskTemplate") or {}).get("Networks", [])
                ]
                if not attached_networks:
                    raise ValueError(f"Docker Swarm service {name} was created without configured network '{network}'")
            self._set_cluster_record(task, "docker_swarm", "job", name, cfg["image"], cluster_id=service_id)
            self._append_task_log(task["stdout_log_path"], f"Started Docker Swarm service {name} {service_id}")
            self._docker_sdk_log_capture(task, "service", name)
            return task["cluster"]

        cmd = [
            "docker", "service", "create",
            "--name", name,
            "--detach=true",
            "--mode", "replicated-job",
            "--replicas", "1",
            "--restart-condition", "none",
        ]
        network = context["network"]
        if network:
            cmd.extend(["--network", network])
        for source, target in context["mounts"]:
            cmd.extend(["--mount", f"type=bind,source={source},target={target}"])
        cmd.extend(["--workdir", context["picker_workspace"]])
        for key, value in sorted(context["env"].items()):
            key = str(key)
            if _valid_env_name(key):
                cmd.extend(["--env", f"{key}={value}"])
        cmd.extend([str(item) for item in cfg.get("swarm_extra_args") or [] if str(item).strip()])
        cmd.append(str(cfg["image"]))
        cmd.extend(context["command"])
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"docker service create failed: {(stderr or stdout).strip()}")
        service_id = stdout.strip()
        self._set_cluster_record(task, "docker_swarm", "job", name, cfg["image"], cluster_id=service_id)
        self._append_task_log(task["stdout_log_path"], f"Started Docker Swarm service {name} {service_id}")
        self._start_external_log_capture(task, ["docker", "service", "logs", "-f", "--raw", name])
        return task["cluster"]

    def _k8s_manifest(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._cluster_launch_context(task, env, prepared, "k8s")
        cfg = context["cfg"]
        name = context["name"]
        command = context["command"]
        ports = [
            {"name": item["name"][:15], "containerPort": item["container_port"]}
            for item in self._published_ports(cmd_api, terminal_api, web_console, "k8s")
        ]
        volume_mounts = []
        volumes = []
        for index, (source, target) in enumerate(context["mounts"], start=1):
            vol_name = f"workspace-{index}"
            volumes.append({"name": vol_name, "hostPath": {"path": source, "type": "Directory"}})
            volume_mounts.append({"name": vol_name, "mountPath": target})
        container = {
            "name": "ucagent",
            "image": cfg["image"],
            "imagePullPolicy": cfg["k8s_image_pull_policy"],
            "command": command[:1],
            "args": command[1:],
            "env": [
                {"name": str(key), "value": str(value)}
                for key, value in sorted(context["env"].items())
                if _valid_env_name(str(key))
            ],
            "volumeMounts": volume_mounts,
        }
        if ports:
            container["ports"] = ports
        if cfg.get("k8s_resources"):
            container["resources"] = cfg["k8s_resources"]
        pod_spec: Dict[str, Any] = {
            "restartPolicy": "Never",
            "containers": [container],
        }
        if volumes:
            pod_spec["volumes"] = volumes
        if cfg.get("k8s_service_account"):
            pod_spec["serviceAccountName"] = cfg["k8s_service_account"]
        if cfg.get("k8s_node_selector"):
            pod_spec["nodeSelector"] = cfg["k8s_node_selector"]
        if cfg.get("k8s_tolerations"):
            pod_spec["tolerations"] = cfg["k8s_tolerations"]
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": name,
                "labels": {
                    "app": "ucagent",
                    "ucagent-task-id": task["task_id"],
                },
            },
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "metadata": {
                        "labels": {
                            "app": "ucagent",
                            "ucagent-task-id": task["task_id"],
                        },
                    },
                    "spec": pod_spec,
                },
            },
        }

    def _start_k8s_port_forwards(self, task: Dict[str, Any]) -> None:
        cluster = task.get("cluster") or {}
        if task.get("launch_mode") != "k8s" or not cluster.get("name"):
            return
        if not self._k8s_cli_available():
            self._append_task_log(
                task["stderr_log_path"],
                "kubectl was not found; Kubernetes Python client fallback does not start local port-forward processes.",
            )
            return
        runtime = self._task_runtime.setdefault(task["task_id"], {})
        existing = runtime.get("port_forward_processes") or []
        if existing and any(proc.poll() is None for proc in existing):
            return
        cfg = self._launch_cluster_config()
        namespace = cluster.get("namespace") or cfg["k8s_namespace"]
        name = str(cluster.get("name") or "").strip()
        pod_ref = f"pod/{name}"
        if cluster.get("kind") == "job":
            code, stdout, stderr = self._run_control_command(
                ["kubectl", "get", "pods", "-n", namespace, "-l", f"job-name={name}", "-o", "jsonpath={.items[0].metadata.name}"],
                timeout=4.0,
            )
            if code != 0 or not stdout.strip():
                self._append_task_log(task["stderr_log_path"], f"Failed to find pod for Kubernetes job {namespace}/{name}: {(stderr or stdout).strip()}")
                return
            pod_ref = f"pod/{stdout.strip()}"
        processes = []
        for port in cluster.get("ports") or []:
            host_port = int(port["host_port"])
            container_port = int(port["container_port"])
            cmd = [
                "kubectl", "port-forward",
                "-n", namespace,
                pod_ref,
                f"{host_port}:{container_port}",
                "--address", "127.0.0.1",
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                processes.append(proc)
            except OSError as exc:
                self._append_task_log(task["stderr_log_path"], f"Failed to start kubectl port-forward: {exc}")
        runtime["port_forward_processes"] = processes

    def _start_task_k8s(
        self,
        task: Dict[str, Any],
        env: Dict[str, str],
        prepared: Dict[str, Any],
        cmd_api: Dict[str, Any],
        terminal_api: Dict[str, Any],
        web_console: Dict[str, Any],
    ) -> Dict[str, Any]:
        cfg = self._launch_cluster_config()
        manifest = self._k8s_manifest(task, env, prepared, cmd_api, terminal_api, web_console)
        manifest_path = os.path.join(self._logs_dir, f"{task['task_id']}.k8s-job.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        namespace = cfg["k8s_namespace"]
        if not self._k8s_cli_available():
            _k8s_client, _core = self._k8s_sdk_clients()
            batch = _k8s_client.BatchV1Api()
            try:
                batch.create_namespaced_job(namespace=namespace, body=manifest)
            except Exception as exc:
                raise ValueError(f"Kubernetes Python client job create failed: {exc}") from exc
            name = manifest["metadata"]["name"]
            self._set_cluster_record(
                task,
                "k8s",
                "job",
                name,
                cfg["image"],
                namespace=namespace,
                manifest_path=manifest_path,
                ports=self._published_ports(cmd_api, terminal_api, web_console, "k8s"),
            )
            self._append_task_log(task["stdout_log_path"], f"Started Kubernetes job {namespace}/{name}")
            self._k8s_sdk_log_capture(task, namespace, "")
            return task["cluster"]

        cmd = ["kubectl", "apply", "-n", namespace, "-f", manifest_path]
        code, stdout, stderr = self._run_control_command(cmd, timeout=30.0)
        if code != 0:
            raise ValueError(f"kubectl apply failed: {(stderr or stdout).strip()}")
        name = manifest["metadata"]["name"]
        self._set_cluster_record(
            task,
            "k8s",
            "job",
            name,
            cfg["image"],
            namespace=namespace,
            manifest_path=manifest_path,
            ports=self._published_ports(cmd_api, terminal_api, web_console, "k8s"),
        )
        self._append_task_log(task["stdout_log_path"], f"Started Kubernetes job {namespace}/{name}")
        self._start_k8s_port_forwards(task)
        self._start_external_log_capture(task, [
            "kubectl", "logs", "-f", "-n", namespace, f"job/{name}", "--all-containers=true"
        ])
        return task["cluster"]
