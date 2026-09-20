#!/usr/bin/env bash
set -euo pipefail

ROOT=${SPEC_GENERATOR_WORKSPACE:-"$PWD"}
PYTHON=${SPEC_GENERATOR_PYTHON:-python3}
CACHE_ROOT=${SPEC_GENERATOR_CACHE:-"$ROOT/.cache"}
NODE_VERSION=${NODE_VERSION:-22.23.2}

case "$(uname -s)" in
  Darwin) node_os=darwin ;;
  Linux) node_os=linux ;;
  *) printf 'error: unsupported OS for Node bootstrap: %s\n' "$(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) node_arch=arm64 ;;
  x86_64|amd64) node_arch=x64 ;;
  *) printf 'error: unsupported architecture for Node bootstrap: %s\n' "$(uname -m)" >&2; exit 1 ;;
esac

artifact="node-v$NODE_VERSION-$node_os-$node_arch.tar.gz"
case "$node_os-$node_arch" in
  darwin-arm64) expected=61130f394c1630d211dd50aecc4353d379480f36d3ac913cd85dbba1aed585c6 ;;
  darwin-x64) expected=58e99022c2ff89395576cc7fd4d98cea24bb68081475d5f88b801ee8729fb026 ;;
  linux-arm64) expected=013b59cfd2819703a6f4a14ab891fc46fc2a4e3f5bcd92de3fb4929b43e35b30 ;;
  linux-x64) expected=b294a556e639d64338823920e5866c21c02741742d2e1529ee1a225c1ec9252a ;;
esac

install_dir="$CACHE_ROOT/tools/node/$NODE_VERSION-$node_os-$node_arch"
if [[ ! -x "$install_dir/bin/node" ]]; then
  command -v curl >/dev/null 2>&1 || { printf 'error: curl is required to bootstrap Node.js\n' >&2; exit 1; }
  command -v tar >/dev/null 2>&1 || { printf 'error: tar is required to bootstrap Node.js\n' >&2; exit 1; }
  archive="$install_dir.tar.gz"
  rm -rf "$install_dir"
  mkdir -p "$install_dir"
  curl --fail --location --retry 3 "https://nodejs.org/dist/v$NODE_VERSION/$artifact" --output "$archive"
  actual=$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$archive")
  if [[ "$actual" != "$expected" ]]; then
    printf 'error: Node.js archive checksum mismatch: expected %s, got %s\n' "$expected" "$actual" >&2
    exit 1
  fi
  tar -xzf "$archive" -C "$install_dir" --strip-components=1
  rm -f "$archive"
fi

printf '%s\n' "$install_dir"
