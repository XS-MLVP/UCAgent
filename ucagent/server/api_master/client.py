"""Agent heartbeat client, record reporting, and workspace synchronization."""

from __future__ import annotations

import json
import os
import shutil
import socket
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from ucagent.util.log import warning
from ucagent.util.workspace_archive import create_workspace_archive

from .common import (
    _copy_jsonable,
    _local_ip,
    _master_log,
    _now,
    _safe_name,
    _workspace_sync_ignore_patterns_from_cfg,
)


class MasterClient:
    """
    Background thread that periodically sends a heartbeat + status snapshot
    to a MasterApiServer via HTTP.
    """

    def __init__(
        self,
        master_url: str,
        *,
        payload: Callable[[], dict],
        workspace: str,
        cfg: Any,
        agent_id: Optional[str] = None,
        interval: float = 5.0,
        reconnect_interval: float = 10.0,
        access_key: str = "",
    ) -> None:
        """Receive state and workspace dependencies without a debugger reference."""
        self.payload = payload
        self.workspace = workspace
        self.cfg = cfg
        self._lifecycle_lock = threading.RLock()
        self.master_url = master_url.rstrip("/")
        self.agent_id = agent_id or f"{socket.gethostname()}-{os.getpid()}"
        self.interval = interval
        self.reconnect_interval = reconnect_interval
        self.access_key = access_key

        self._running = False
        self._kicked = False
        self._auth_failed = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._force_next = False
        self._last_capabilities: Dict[str, Any] = {}

    def _headers(self) -> Dict[str, str]:
        return {"X-Access-Key": self.access_key} if self.access_key else {}

    @staticmethod
    def _response_detail(resp: Any) -> str:
        try:
            data = resp.json()
            detail = data.get("detail") or data.get("message") or data
            return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        except Exception:
            return (getattr(resp, "text", "") or "").strip()[:500]

    def _build_payload(self) -> dict:
        """Detach the injected status snapshot and apply this connection's identity."""
        return {**_copy_jsonable(self.payload()), "id": self.agent_id}

    def _heartbeat_loop(self) -> None:
        import requests

        register_url = f"{self.master_url}/api/register"
        connected = False
        headers = self._headers()
        while not self._stop_event.is_set():
            try:
                payload = self._build_payload()
                if self._force_next or not connected:
                    payload["force"] = True
                    self._force_next = False
                resp = requests.post(register_url, json=payload, timeout=10, headers=headers)
                if resp.ok:
                    data = resp.json()
                    if data.get("status") == "removed":
                        self._kicked = True
                        self._running = False
                        return
                    if isinstance(data.get("capabilities"), dict):
                        self._last_capabilities = data["capabilities"]
                    if not connected:
                        _master_log(f"[MasterClient] (Re)connected to master {self.master_url} as '{self.agent_id}'")
                    connected = True
                    self._connected = True
                else:
                    if resp.status_code == 403:
                        self._auth_failed = True
                        self._running = False
                        self._connected = False
                        return
                    connected = False
                    self._connected = False
                    self._stop_event.wait(self.reconnect_interval)
                    continue
            except Exception as exc:
                if connected:
                    _master_log(f"[MasterClient] Connection to {self.master_url} lost: {exc}. Retrying in {self.reconnect_interval}s …")
                connected = False
                self._connected = False
                self._stop_event.wait(self.reconnect_interval)
                continue
            self._stop_event.wait(self.interval)

    def send_exit_heartbeat(self, reason: str = "exit") -> Tuple[bool, str]:
        import requests

        self._stop_event.set()
        payload = self._build_payload()
        payload["client_exit"] = True
        payload["exited_at"] = _now()
        payload["exit_reason"] = str(reason or "exit")
        register_url = f"{self.master_url}/api/register"
        try:
            resp = requests.post(register_url, json=payload, timeout=10, headers=self._headers())
        except Exception as exc:
            self._connected = False
            return False, f"Failed to send exit heartbeat to master {self.master_url}: {exc}"
        if resp.ok:
            data = resp.json()
            if data.get("status") == "removed":
                self._kicked = True
                self._running = False
                self._connected = False
                return False, f"This agent was removed from master {self.master_url}."
            if isinstance(data.get("capabilities"), dict):
                self._last_capabilities = data["capabilities"]
            self._running = False
            self._connected = False
            return True, f"Exit heartbeat sent to master {self.master_url} as '{self.agent_id}'."
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)."
        self._connected = False
        return False, f"Exit heartbeat failed for master {self.master_url}: HTTP {resp.status_code} {self._response_detail(resp)}"

    def start(self) -> Tuple[bool, str]:
        """Start one heartbeat worker; reconnect waits remain interruptible."""
        with self._lifecycle_lock:
            if self.is_running:
                return False, f"Master client is already running or stopping: {self.master_url}"
            if self._kicked or self._auth_failed:
                return False, "Master rejected this connection; create a new connection with valid identity and credentials"
            self._stop_event.clear()
            self._force_next = True
            self._connected = False
            self._running = True
            self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="master-client")
            try:
                self._thread.start()
            except Exception:
                self._running = False
                raise
            return True, f"Master heartbeat started for {self.master_url} as '{self.agent_id}'"

    def stop(self, timeout=5) -> Tuple[bool, str]:
        """Retain a heartbeat thread blocked in HTTP until that request actually ends."""
        from ucagent.control.runtime.services import lifecycle_timeout

        timeout = lifecycle_timeout(timeout)
        with self._lifecycle_lock:
            self._stop_event.set()
            self._running = False
            self._connected = False
            thread = self._thread
            if thread is not None and thread.ident is not None and thread is not threading.current_thread():
                thread.join(timeout)
            if thread is not None and thread.is_alive():
                return False, f"Master client is still stopping: {self.master_url}"
            self._thread = None
            return True, f"Disconnected from master {self.master_url}"

    def report_records(self, report: Dict[str, Any]) -> Tuple[bool, str]:
        """Send one versioned, type-discriminated record envelope to the master."""
        if self._kicked:
            return False, f"This agent was removed from master {self.master_url}."
        if self._auth_failed:
            return False, f"Access key was rejected by master {self.master_url}."
        if not self._running:
            return False, f"Not connected to master {self.master_url}."
        if not isinstance(report, dict):
            return False, "Record report must be a dictionary."

        import requests

        try:
            payload = _copy_jsonable(report)
        except (TypeError, ValueError) as exc:
            return False, f"Record report must be JSON serializable: {exc}"
        payload["agent_id"] = self.agent_id
        payload.setdefault("schema_version", 1)
        url = f"{self.master_url}/api/records"
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=30,
                headers=self._headers(),
            )
        except Exception as exc:
            self._connected = False
            return False, f"Failed to report records to master {self.master_url}: {exc}"
        if response.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)."
        if not response.ok:
            return False, (
                f"Record report failed for master {self.master_url}: "
                f"HTTP {response.status_code} {self._response_detail(response)}"
            )
        self._connected = True
        return True, (
            f"Reported type '{payload.get('record_type')}' records to master "
            f"{self.master_url} as '{self.agent_id}'."
        )

    def workspace_sync_status(self) -> Tuple[bool, str, Dict[str, Any]]:
        if self._kicked:
            return False, f"This agent was removed from master {self.master_url}", {}
        if self._auth_failed:
            return False, f"Access key was rejected by master {self.master_url}", {}
        if not self._running:
            return False, "Not connected to master", {}
        import requests

        url = f"{self.master_url}/api/workspace-sync/status"
        try:
            resp = requests.get(
                url,
                params={"agent_id": self.agent_id},
                timeout=15,
                headers=self._headers(),
            )
        except Exception as exc:
            self._connected = False
            return False, f"Failed to query workspace sync-back status from {self.master_url}: {exc}", {}
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)", {}
        if not resp.ok:
            return False, f"Master returned HTTP {resp.status_code}: {self._response_detail(resp)}", {}
        try:
            data = resp.json()
        except Exception as exc:
            return False, f"Invalid workspace sync-back status response: {exc}", {}
        self._connected = True
        status = data.get("data") or {}
        if not isinstance(status, dict):
            return False, "Invalid workspace sync-back status payload", {}
        self._last_capabilities["workspace_sync_back"] = status
        if not status.get("enabled"):
            return False, str(status.get("reason") or "Workspace sync-back is not available"), status
        return True, str(status.get("reason") or "Workspace sync-back is available"), status

    def _sync_workspace_ignore_patterns(self) -> List[str]:
        return _workspace_sync_ignore_patterns_from_cfg(self.cfg)

    def sync_workspace_back(self, workspace_dir: str = "", reason: str = "manual") -> Tuple[bool, str]:
        ok, msg, status = self.workspace_sync_status()
        if not ok:
            if status and not status.get("enabled") and (reason == "exit" or reason.startswith("stage_complete:")):
                return True, f"Workspace sync-back skipped: {msg}"
            return False, msg
        workspace = os.path.abspath(workspace_dir or self.workspace)
        if not workspace or not os.path.isdir(workspace):
            return False, f"Workspace directory not found: {workspace or '<empty>'}"

        import requests

        archive_stem = _safe_name(str(status.get("task_id") or self.agent_id or "workspace"), "workspace")
        temp_dir = ""
        try:
            archive_path, filename, temp_dir = create_workspace_archive(
                workspace,
                archive_stem=archive_stem,
                root_name="workspace",
                ignore_patterns=self._sync_workspace_ignore_patterns(),
            )
            url = f"{self.master_url}/api/workspace-sync/back"
            with open(archive_path, "rb") as fh:
                resp = requests.post(
                    url,
                    data={"agent_id": self.agent_id, "reason": reason},
                    files={"archive": (filename, fh, "application/gzip")},
                    timeout=(15, 600),
                    headers=self._headers(),
                )
        except Exception as exc:
            return False, f"Failed to upload workspace archive to {self.master_url}: {exc}"
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
        if resp.status_code == 403:
            self._auth_failed = True
            self._running = False
            self._connected = False
            return False, f"Access key was rejected by master {self.master_url} (HTTP 403)"
        if not resp.ok:
            return False, f"Master returned HTTP {resp.status_code}: {self._response_detail(resp)}"
        try:
            data = resp.json()
        except Exception:
            data = {}
        sync = data.get("sync") if isinstance(data, dict) else {}
        if isinstance(sync, dict) and sync.get("workspace_id"):
            return (
                True,
                f"Workspace synced back to master {self.master_url} "
                f"(task={sync.get('task_id')}, workspace={sync.get('workspace_id')})",
            )
        return True, f"Workspace synced back to master {self.master_url}"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_connected(self) -> bool:
        return self._connected and self.is_running and not self._stop_event.is_set()

    @property
    def is_kicked(self) -> bool:
        return self._kicked

    @property
    def is_auth_failed(self) -> bool:
        return self._auth_failed
