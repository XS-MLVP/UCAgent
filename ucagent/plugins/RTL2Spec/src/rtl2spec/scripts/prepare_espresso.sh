#!/usr/bin/env bash
set -euo pipefail

ROOT=${RTL2SPEC_WORKSPACE:-"$PWD"}
XS_ROOT=${XIANGSHAN_ROOT:-"$ROOT/third_party/XiangShan"}
CACHE_ROOT=${RTL2SPEC_CACHE:-"$ROOT/.cache"}
ESPRESSO_COMMIT=${ESPRESSO_COMMIT:-85265139e9598852f9388d293658a1977a829a01}
bundled="$XS_ROOT/src/main/resources/espresso"
os=$(uname -s)
arch=$(uname -m)

if [[ ! -f "$bundled" ]]; then
  printf 'error: XiangShan bundled Espresso not found: %s\n' "$bundled" >&2
  exit 1
fi

# The checked-in binary is Linux x86-64. Reuse it only on that host family.
if [[ "$os" == "Linux" && ( "$arch" == "x86_64" || "$arch" == "amd64" ) && -x "$bundled" ]]; then
  printf '%s\n' "$bundled"
  exit 0
fi

for tool in git make cc; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'error: %s is required to build native Espresso on %s/%s\n' "$tool" "$os" "$arch" >&2
    exit 1
  }
done

key=$(printf '%s-%s' "$os" "$arch" | tr '[:upper:]' '[:lower:]')
tool_dir="$CACHE_ROOT/tools/espresso/$key/$ESPRESSO_COMMIT"
source_dir="$tool_dir/source"
binary="$tool_dir/espresso"

if [[ ! -x "$binary" ]]; then
  mkdir -p "$tool_dir"
  if [[ ! -d "$source_dir/.git" ]]; then
    rm -rf "$source_dir"
    git clone --no-checkout https://github.com/classabbyamp/espresso-logic.git "$source_dir" >&2
  fi
  git -C "$source_dir" fetch --depth 1 origin "$ESPRESSO_COMMIT" >&2
  git -C "$source_dir" checkout --detach "$ESPRESSO_COMMIT" >&2
  make -C "$source_dir/espresso-src" >&2
  cp "$source_dir/bin/espresso" "$binary"
  chmod +x "$binary"
fi

printf '%s\n' "$binary"
