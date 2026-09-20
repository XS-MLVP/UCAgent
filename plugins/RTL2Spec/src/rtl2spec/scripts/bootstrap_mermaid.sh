#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=${RTL2SPEC_WORKSPACE:-"$PWD"}
CACHE_ROOT=${RTL2SPEC_CACHE:-"$ROOT/.cache"}
MERMAID_CLI_VERSION=${MERMAID_CLI_VERSION:-11.16.0}
install_dir="$CACHE_ROOT/tools/mermaid-cli/$MERMAID_CLI_VERSION"
mmdc="$install_dir/node_modules/.bin/mmdc"

node_home=$(bash "$SCRIPT_DIR/bootstrap_node.sh")

if [[ ! -x "$mmdc" ]]; then
  mkdir -p "$install_dir"
  PATH="$node_home/bin:$PATH" "$node_home/bin/npm" install --ignore-scripts --prefix "$install_dir" "@mermaid-js/mermaid-cli@$MERMAID_CLI_VERSION" >&2
fi

printf '%s\n' "$mmdc"
