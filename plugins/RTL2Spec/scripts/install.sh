#!/usr/bin/env bash
# Install this local plugin and compose its independent FM-Agent management actions.
set -euo pipefail

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_command=python3
fmagent_root=
fmagent_python=
repo=
branch=
skip_fetch=0
skip_install=0
skip_bind=0
yes=0

usage() {
    printf '%s\n' 'Usage: bash scripts/install.sh [--python PYTHON] [--fmagent-root ROOT]' \
        '       [--fmagent-python PYTHON --skip-install] [--repo URL] [--branch BRANCH]' \
        '       [--skip-fetch] [--skip-install] [--skip-bind] [-y|--yes]' \
        'Installs the local plugin, then fetches, natively installs and binds FM-Agent.' \
        'Native install may access the network and change user tools/configuration.'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python|--fmagent-root|--fmagent-python|--repo|--branch)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "Missing value for $1" >&2; exit 2; }
            case "$1" in
                --python) python_command="$2" ;;
                --fmagent-root) fmagent_root="$2" ;;
                --fmagent-python) fmagent_python="$2" ;;
                --repo) repo="$2" ;;
                --branch) branch="$2" ;;
            esac
            shift 2 ;;
        -y|--yes) yes=1; shift ;;
        --skip-fetch) skip_fetch=1; shift ;;
        --skip-install) skip_install=1; shift ;;
        --skip-bind) skip_bind=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -n "$fmagent_python" && "$skip_install" -ne 1 ]]; then
    echo '--fmagent-python requires --skip-install; native install always prepares root/.venv' >&2
    exit 2
fi
if ! command -v "$python_command" >/dev/null 2>&1; then
    echo "Python not found: $python_command" >&2
    exit 2
fi

stage=preflight
trap 'echo "Stopped during $stage; completed steps are retained, no rollback or retry performed." >&2' ERR
selection=$("$python_command" -I - "$plugin_root" "$fmagent_root" "$fmagent_python" "$skip_fetch" "$skip_install" "$skip_bind" <<'PY'
"""Validate steps and snapshot paired paths before any package or source changes."""
import shlex
import sys
sys.path.insert(0, sys.argv[1] + "/src")
from rtl2spec.fmagent import source_present
from rtl2spec.fmagent_config import resolve_paths
if sys.version_info < (3, 11):
    raise SystemExit("RTL2Spec requires Python >=3.11")
if sys.argv[4:] != ["1", "1", "1"]:
    paths = resolve_paths(sys.argv[2], sys.argv[3])
    if sys.argv[4] == "1" and (sys.argv[5] != "1" or sys.argv[6] != "1") and not source_present(paths.root):
        raise SystemExit(f"FM-Agent source missing at {paths.root}; fetch first or omit --skip-fetch")
    selected_python = paths.root / ".venv/bin/python" if sys.argv[5] != "1" else paths.python
    python_source = "native install target" if sys.argv[5] != "1" else paths.python_source
    print("fmagent_root=" + shlex.quote(str(paths.root)))
    print("fmagent_python=" + shlex.quote(str(selected_python)))
    print(f"Selected root: {paths.root} [{paths.root_source}]", file=sys.stderr)
    print(f"Selected python: {selected_python} [{python_source}]", file=sys.stderr)
    if sys.argv[6] != "1":
        print("Successful preparation will save these paths; use --skip-bind to leave the binding unchanged", file=sys.stderr)
PY
)
eval "$selection"

stage='plugin installation'
"$python_command" -I -m pip install "$plugin_root"
echo 'Completed: plugin installation'
root_args=()
yes_args=()
[[ "$yes" -ne 1 ]] || yes_args+=(--yes)
[[ -z "$fmagent_root" ]] || root_args+=(--fmagent-root "$fmagent_root")
if [[ "$skip_fetch" -ne 1 ]]; then
    stage=fetch
    fetch_args=()
    [[ -z "$repo" ]] || fetch_args+=(--repo "$repo")
    [[ -z "$branch" ]] || fetch_args+=(--branch "$branch")
    "$python_command" -I -m rtl2spec.fmagent fetch "${root_args[@]+"${root_args[@]}"}" "${fetch_args[@]+"${fetch_args[@]}"}" "${yes_args[@]+"${yes_args[@]}"}"
    echo 'Completed: fetch'
fi
if [[ "$skip_install" -ne 1 ]]; then
    stage='native installation'
    "$python_command" -I -m rtl2spec.fmagent install "${root_args[@]+"${root_args[@]}"}" "${yes_args[@]+"${yes_args[@]}"}"
    echo 'Completed: native installation'
fi
if [[ "$skip_bind" -ne 1 ]]; then
    stage=bind
    bind_args=()
    [[ -z "$fmagent_python" ]] || bind_args+=(--fmagent-python "$fmagent_python")
    "$python_command" -I -m rtl2spec.fmagent bind "${root_args[@]+"${root_args[@]}"}" "${bind_args[@]+"${bind_args[@]}"}"
    echo 'Completed: bind'
fi
