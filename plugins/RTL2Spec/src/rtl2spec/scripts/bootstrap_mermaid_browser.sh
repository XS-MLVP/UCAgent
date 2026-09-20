#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PYTHON=${RTL2SPEC_PYTHON:-python3}

if [[ -n "${MERMAID_BROWSER_PATH:-}" && -x "$MERMAID_BROWSER_PATH" ]]; then
  printf '%s\n' "$MERMAID_BROWSER_PATH"
  exit 0
fi
if [[ -n "${PUPPETEER_EXECUTABLE_PATH:-}" && -x "$PUPPETEER_EXECUTABLE_PATH" ]]; then
  printf '%s\n' "$PUPPETEER_EXECUTABLE_PATH"
  exit 0
fi

for command in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge; do
  if path=$(command -v "$command" 2>/dev/null); then printf '%s\n' "$path"; exit 0; fi
done

if [[ "$(uname -s)" == "Darwin" ]]; then
  for path in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    if [[ -x "$path" ]]; then printf '%s\n' "$path"; exit 0; fi
  done
fi

mmdc=$(bash "$SCRIPT_DIR/bootstrap_mermaid.sh")
node_home=$(bash "$SCRIPT_DIR/bootstrap_node.sh")
install_dir=$(cd "$(dirname "$mmdc")/../.." && pwd)
puppeteer="$install_dir/node_modules/.bin/puppeteer"
browser_cache="$install_dir/browser-cache"
if [[ ! -x "$puppeteer" ]]; then
  printf 'error: Puppeteer CLI not found beside Mermaid CLI\n' >&2
  exit 1
fi

PATH="$node_home/bin:$PATH" PUPPETEER_CACHE_DIR="$browser_cache" "$puppeteer" browsers install chrome-headless-shell >&2
browser=$("$PYTHON" - "$browser_cache" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
names = {"chrome-headless-shell", "headless_shell", "chrome-headless-shell.exe"}
matches = sorted(path for path in root.rglob("*") if path.is_file() and path.name in names)
if matches:
    print(matches[-1])
PY
)
if [[ -z "$browser" || ! -x "$browser" ]]; then
  printf 'error: Puppeteer browser installation completed without an executable\n' >&2
  exit 1
fi
printf '%s\n' "$browser"
