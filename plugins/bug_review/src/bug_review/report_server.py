"""Serve published Bug Review pages and waveform snapshots on localhost."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit


class ReportHandler(SimpleHTTPRequestHandler):
    """Expose only the portal and published module reports with Wasm isolation headers."""

    def end_headers(self) -> None:
        """Enable the browser isolation required by bundled Surfer resources."""
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        """Resolve a public report path without exposing private run records."""
        root = Path(self.directory).resolve()
        value = unquote(urlsplit(path).path)
        parts = Path(value.lstrip("/")).parts
        if value in {"/", "/index.html", "/guide.md"}:
            return str(root / ("guide.md" if value == "/guide.md" else "index.html"))
        if (len(parts) < 2 or not parts[0].startswith("workspace_")
                or parts[1] != "report" or any(part in {".", ".."} for part in parts)):
            return str(root / "__report_path_not_found__")
        report = (root / parts[0] / "report").resolve()
        target = (root.joinpath(*parts)).resolve()
        if not report.is_dir() or not target.is_relative_to(report):
            return str(root / "__report_path_not_found__")
        return str(target)


def main() -> None:
    """Start a local static server for published Bug Review HTML and Surfer."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path,
                        default=Path(__file__).resolve().parent)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = args.output_root.resolve()
    if not (root / "index.html").is_file():
        parser.error(f"published portal is missing: {root / 'index.html'}")
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/plain; charset=utf-8", ".md")
    handler = partial(ReportHandler, directory=str(root))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"http://127.0.0.1:{server.server_port}/index.html", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
