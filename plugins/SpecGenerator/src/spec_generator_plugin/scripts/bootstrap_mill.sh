#!/usr/bin/env bash
set -euo pipefail

ROOT=${SPEC_GENERATOR_WORKSPACE:-"$PWD"}
XS_ROOT=${XIANGSHAN_ROOT:-"$ROOT/third_party/XiangShan"}
CACHE_ROOT=${SPEC_GENERATOR_CACHE:-"$ROOT/.cache"}

if [[ ! -f "$XS_ROOT/.mill-version" ]]; then
  printf 'error: missing %s/.mill-version\n' "$XS_ROOT" >&2
  exit 1
fi

version=$(tr -d '[:space:]' < "$XS_ROOT/.mill-version")
install_dir="$CACHE_ROOT/tools/mill/$version"
launcher="$install_dir/mill"

if [[ ! -x "$launcher" ]]; then
  command -v curl >/dev/null 2>&1 || {
    printf 'error: curl is required to bootstrap Mill\n' >&2
    exit 1
  }
  mkdir -p "$install_dir"
  url="https://raw.githubusercontent.com/com-lihaoyi/mill/$version/mill"
  printf 'Bootstrapping Mill %s from %s\n' "$version" "$url" >&2
  curl --fail --location --retry 3 "$url" --output "$launcher"
  chmod +x "$launcher"
fi

printf '%s\n' "$launcher"
