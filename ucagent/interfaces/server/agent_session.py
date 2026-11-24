"""Authenticated loopback transport for existing Agent views; never constructs agents."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from ucagent.runtime.agent_events import atomic_json
from ucagent.runtime.control.controller import ControlError

class AgentSessionServer:
    def __init__(self, view, root):
        self.view, self.root = view, Path(root)
        self.token = secrets.token_urlsafe(32)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.dispatch()
            def do_POST(self): self.dispatch()
            def dispatch(self):
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + owner.token):
                    self.respond(401, {"error": "Unauthorized session client"}); return
                try:
                    url = urlparse(self.path)
                    if self.command == "GET" and url.path == "/snapshot": result = owner.view.snapshot()
                    elif self.command == "GET" and url.path == "/events":
                        result = owner.view.events_since(int(parse_qs(url.query).get("cursor", [0])[0]))
                    elif self.command == "POST":
                        size = int(self.headers.get("Content-Length", 0))
                        if not 0 <= size <= 131072: raise ValueError("Request too large")
                        data = json.loads(self.rfile.read(size) or b"{}")
                        if url.path == "/input":
                            if type(data.get("command", False)) is not bool: raise ValueError("command must be boolean")
                            result = owner.view.submit_input(data["text"], command=data.get("command", False))
                        elif url.path == "/cancel": result = owner.view.cancel_operation()
                        elif url.path == "/recover": result = owner.view.recover(data)
                        elif url.path == "/review": result = owner.view.review(**data)
                        else: self.respond(404, {"error": "Unknown session action"}); return
                    else: self.respond(404, {"error": "Unknown session action"}); return
                    self.respond(200, result)
                except (ValueError, KeyError, RuntimeError, TypeError, ControlError) as error:
                    self.respond(400, {"error": str(error)[:2000]})
            def respond(self, code, payload):
                body = json.dumps(payload, ensure_ascii=False, default=str).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="ucagent-session-http")

    def start(self):
        self.thread.start()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "connection.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"url": f"http://127.0.0.1:{self.server.server_port}", "token": self.token}, stream)
        return self

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        (self.root / "connection.json").unlink(missing_ok=True)

class RemoteAgentView:
    def __init__(self, root, *, timeout=1):
        self.root, self.timeout = Path(root), timeout

    def _call(self, path, payload=None, *, timeout=None):
        connection = json.loads((self.root / "connection.json").read_text())
        parsed = urlparse(connection["url"])
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Agent session endpoint must be loopback HTTP")
        request = Request(connection["url"] + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout if timeout is None else timeout) as response: return json.load(response)
        except HTTPError as error:
            raise ValueError(json.loads(error.read()).get("error", "Session request failed")) from error

    def snapshot(self): return self._call("/snapshot")
    def events_since(self, cursor=0): return self._call(f"/events?cursor={cursor}")
    def submit_input(self, text, *, command=False): return self._call("/input", {"text": text, "command": command})
    def cancel_operation(self): return self._call("/cancel", {})
    def recover(self, request):
        """Allow prerequisite rechecks to finish without slowing regular polling."""
        return self._call("/recover", request, timeout=30)
    def review(self, issue_id, index, expected_revision, message):
        """Approve the displayed stage revision through the authenticated session."""
        return self._call("/review", dict(issue_id=issue_id, index=index, expected_revision=expected_revision, message=message), timeout=30)

class SavedAgentView:
    """Read-only terminal history; loss of a process handle never restarts a workflow."""
    def __init__(self, root): self.root = Path(root)
    def snapshot(self):
        path = self.root / "view_snapshot.json"
        data = json.loads(path.read_text()) if path.is_file() else {"status": "unavailable", "stages": [], "children": []}
        return {**data, "readonly": True}
    def events_since(self, cursor=0):
        path = self.root / "view/events.jsonl"
        events = []
        if path.is_file():
            with path.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row["seq"] > cursor:
                        events.append(row)
                        if len(events) >= 200: break
        return {"events": events, "cursor": events[-1]["seq"] if events else cursor, "gap": False, "has_more": len(events) == 200}
    def submit_input(self, text, *, command=False): raise ValueError("Saved Agent view is read-only")
    def cancel_operation(self): raise ValueError("Saved Agent view is read-only")
    def recover(self, request):
        """Require a new Global attempt after the owning process has ended."""
        raise ValueError("Agent process has ended; use retry instead")
    def review(self, **kwargs):
        """Keep historical stage evidence read-only."""
        raise ValueError("Saved Agent view is read-only")
