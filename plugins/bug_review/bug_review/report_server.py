"""Serve generated reports together with UCAgent's bundled Surfer viewer."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import ucagent


REPO = Path(__file__).resolve().parent.parent
DEFAULT_SURFER_ROOT = Path(ucagent.__file__).resolve().parent / "server/static/surfer"


class ReportRequestHandler(SimpleHTTPRequestHandler):
    """Map /surfer to bundled assets and /workspace to repository files."""

    def __init__(self, *args, workspace_root: Path, surfer_root: Path, **kwargs):
        self.workspace_root = workspace_root.resolve()
        self.surfer_root = surfer_root.resolve()
        super().__init__(*args, directory=str(self.workspace_root), **kwargs)

    @staticmethod
    def _contained(root: Path, relative: str) -> Path:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return root / ".invalid-path"
        return candidate

    def translate_path(self, path: str) -> str:
        request_path = unquote(urlsplit(path).path)
        if request_path == "/surfer" or request_path == "/surfer/":
            return str(self.surfer_root / "index.html")
        if request_path.startswith("/surfer/"):
            return str(self._contained(self.surfer_root, request_path.removeprefix("/surfer/")))
        if request_path.startswith("/workspace/"):
            return str(self._contained(self.workspace_root, request_path.removeprefix("/workspace/")))
        return str(self._contained(self.workspace_root, request_path.lstrip("/")))

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        request_path = unquote(urlsplit(self.path).path)
        if request_path.startswith("/workspace/"):
            self.send_header(
                "X-UCAgent-Waveform-Path",
                request_path.removeprefix("/workspace/"),
            )
        if request_path.startswith("/surfer/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def build_server(root: Path, host: str, port: int, surfer_root: Path = DEFAULT_SURFER_ROOT) -> ThreadingHTTPServer:
    root = Path(root).resolve()
    surfer_root = Path(surfer_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"report root does not exist: {root}")
    if not (surfer_root / "surfer_bg.wasm").is_file():
        raise FileNotFoundError(f"Surfer assets are incomplete: {surfer_root}")
    handler = partial(
        ReportRequestHandler,
        workspace_root=root,
        surfer_root=surfer_root,
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO, help="workspace root exposed to reports and waveform links")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--surfer-root", type=Path, default=DEFAULT_SURFER_ROOT)
    args = parser.parse_args()
    server = build_server(args.root, args.host, args.port, args.surfer_root)
    print(f"LLPTW report server: http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
