#!/usr/bin/env bash
set -euo pipefail

ROOT=${SPEC_GENERATOR_WORKSPACE:-"$PWD"}
PYTHON=${SPEC_GENERATOR_PYTHON:-python3}
CACHE_ROOT=${SPEC_GENERATOR_CACHE:-"$ROOT/.cache"}

if [[ -n "${JAVA_HOME:-}" && -x "$JAVA_HOME/bin/java" ]] && "$JAVA_HOME/bin/java" -version >/dev/null 2>&1; then
  printf '%s\n' "$JAVA_HOME"
  exit 0
fi

if command -v java >/dev/null 2>&1; then
  java_bin=$(command -v java)
  if command -v python3 >/dev/null 2>&1; then
    java_bin=$("$PYTHON" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$java_bin")
  fi
  java_home=$(cd "$(dirname "$java_bin")/.." 2>/dev/null && pwd || true)
  if [[ -x "$java_home/bin/java" ]] && "$java_home/bin/java" -version >/dev/null 2>&1; then
    printf '%s\n' "$java_home"
    exit 0
  fi
fi

command -v curl >/dev/null 2>&1 || { printf 'error: curl is required to bootstrap JDK\n' >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { printf 'error: tar is required to bootstrap JDK\n' >&2; exit 1; }

case "$(uname -s)" in
  Darwin) api_os=mac ;;
  Linux) api_os=linux ;;
  *) printf 'error: unsupported OS for JDK bootstrap: %s\n' "$(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) api_arch=aarch64 ;;
  x86_64|amd64) api_arch=x64 ;;
  *) printf 'error: unsupported architecture for JDK bootstrap: %s\n' "$(uname -m)" >&2; exit 1 ;;
esac

install_dir="$CACHE_ROOT/tools/jdk/temurin-17-$api_os-$api_arch"
marker="$install_dir/.complete"
if [[ ! -f "$marker" ]]; then
  archive="$install_dir.tar.gz"
  rm -rf "$install_dir"
  mkdir -p "$install_dir"
  url="https://api.adoptium.net/v3/binary/latest/17/ga/$api_os/$api_arch/jdk/hotspot/normal/eclipse"
  printf 'Bootstrapping Temurin JDK 17 for %s/%s\n' "$api_os" "$api_arch" >&2
  curl --fail --location --retry 3 "$url" --output "$archive"
  tar -xzf "$archive" -C "$install_dir" --strip-components=1
  rm -f "$archive"
  touch "$marker"
fi

if [[ -x "$install_dir/bin/java" ]]; then
  java_home="$install_dir"
elif [[ -x "$install_dir/Contents/Home/bin/java" ]]; then
  java_home="$install_dir/Contents/Home"
else
  printf 'error: bootstrapped JDK has no java executable: %s\n' "$install_dir" >&2
  exit 1
fi

printf '%s\n' "$java_home"
