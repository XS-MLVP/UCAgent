"""Rebuild UCAgent's pinned Surfer bundle with native collapsed bit-vector rows."""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


SURFER_REVISION = "3ab79e7220f937cb3fadf1117f15d344e5f7e990"
BINDGEN_VERSION = "0.2.113"
SOURCE_SHA256 = "3bb51ce1310ae955a688ffb134e5be69023aa0c408a5a541f70c2f68d62c9a69"
PATCHED_SHA256 = "95ec5a20ff96d9c46bf8ce955e1a63ec4f87070b0068c27e40b88b1ea27b3051"
LOCK_SHA256 = "c5ced9f5f40448b8980608201e8fb14d9b24d82ca0003185cb7b1cc5ff236441"
VIEW_SHA256 = "dbedaaeb5e8d2a6384cf332aae7ee427ec415997abed8ca5a685344a591d115d"
PATCHED_VIEW_SHA256 = "0026a885c0fcb0c248cedb15a373d214de416b5f2832e9a8d3029602128a8a13"


def main() -> None:
    """Validate pinned sources, apply the local patch and publish matched web assets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="Surfer checkout at the pinned revision with initialized submodules")
    parser.add_argument("--wasm-bindgen", default="wasm-bindgen",
                        help="Path to wasm-bindgen CLI version " + BINDGEN_VERSION)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[2] / "server/static/surfer",
                        help="Existing bundle directory containing UCAgent's index.html")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    resources = Path(__file__).resolve().parent
    translation = source / "libsurfer/src/translation/mod.rs"
    if hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest() != LOCK_SHA256:
        parser.error("Use Surfer revision " + SURFER_REVISION + " with its unmodified Cargo.lock")
    source_hash = hashlib.sha256(translation.read_bytes()).hexdigest()
    if source_hash not in {SOURCE_SHA256, PATCHED_SHA256}:
        parser.error("Translation sources differ from the pinned revision/local patch")
    view_hash = hashlib.sha256((source / "libsurfer/src/view.rs").read_bytes()).hexdigest()
    if (source_hash, view_hash) not in {
        (SOURCE_SHA256, VIEW_SHA256), (PATCHED_SHA256, PATCHED_VIEW_SHA256),
    }:
        parser.error("Use a clean pinned checkout or one with the complete local patch")
    version = subprocess.check_output([args.wasm_bindgen, "--version"], text=True).strip()
    if version != "wasm-bindgen " + BINDGEN_VERSION:
        parser.error("Install wasm-bindgen-cli version " + BINDGEN_VERSION)
    index = output / "index.html"
    html = index.read_text(encoding="utf-8")
    for name in ("surfer.js", "surfer_bg.wasm"):
        if len(re.findall(r'href="\./' + re.escape(name) + r'"[^>]*integrity="sha384-[^"]+"', html)) != 1:
            parser.error("index.html must contain exactly one integrity preload for " + name)
    if source_hash == SOURCE_SHA256:
        subprocess.run(["patch", "--batch", "-p1", "-i", str(resources / "bit_expansion.patch")],
                       cwd=source, check=True)
    shutil.copyfile(resources / "bit_expansion.rs", translation.with_name("bit_expansion.rs"))
    env = dict(os.environ, VERGEN_GIT_SHA=SURFER_REVISION,
               VERGEN_GIT_DESCRIBE="v0.6.0-14-g3ab79e7-ucagent-bits")
    subprocess.run(["cargo", "build", "--release", "--locked", "--target",
                    "wasm32-unknown-unknown", "-p", "surfer", "--no-default-features",
                    "--features", "performance_plot,accesskit"], cwd=source, env=env, check=True)
    target = Path(env.get("CARGO_TARGET_DIR", "target"))
    if not target.is_absolute():
        target = source / target
    with tempfile.TemporaryDirectory(prefix="ucagent-surfer-web-") as directory:
        staging = Path(directory)
        subprocess.run([args.wasm_bindgen, "--target", "web", "--out-name", "surfer",
                        "--out-dir", str(staging),
                        str(target / "wasm32-unknown-unknown/release/surfer.wasm")], check=True)
        for name in ("surfer.js", "surfer_bg.wasm"):
            digest = base64.b64encode(hashlib.sha384((staging / name).read_bytes()).digest()).decode("ascii")
            html = re.sub(r'(href="\./' + re.escape(name) + r'"[^>]*integrity=")sha384-[^"]+',
                          lambda match: match[1] + "sha384-" + digest, html)
        # Publish only after both matching assets and their integrity hashes are ready.
        for name in ("surfer.js", "surfer_bg.wasm"):
            shutil.copyfile(staging / name, output / name)
        index.write_text(html, encoding="utf-8")
    print("Rebuilt Surfer " + SURFER_REVISION + " with collapsed bit-vector expansion")


if __name__ == "__main__":
    main()
