#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "Usage: $0 <dut_dir> [-o output_dir | -r rerun_cwd] [make_args...]" >&2
  echo "   or: $0 -r rerun_cwd [make_args...]" >&2
}

infer_dut_from_workspace() {
  local workspace="$1"
  local path=""
  local dut=""
  local count=0

  while IFS= read -r -d '' path; do
    dut="$(basename -- "$path")"
    dut="${dut%_api.py}"
    count=$((count + 1))
  done < <(find "$workspace/unity_test/tests" -maxdepth 1 -type f -name '*_api.py' -print0 2>/dev/null)

  if [ "$count" -eq 1 ]; then
    printf '%s\n' "$dut"
    return 0
  fi

  count=0
  while IFS= read -r -d '' path; do
    case "$(basename -- "$path")" in
      .ucagent|Guide_Doc|tests|uc_test_report|unity_test)
        continue
        ;;
    esac
    dut="$(basename -- "$path")"
    count=$((count + 1))
  done < <(find "$workspace" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)

  if [ "$count" -eq 1 ]; then
    printf '%s\n' "$dut"
    return 0
  fi

  return 1
}

if [ "$#" -lt 1 ]; then
  usage
  exit 1
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
run_dir="$(pwd -P)"
rerun_dir=""
dut_dir=""
make_args=()
use_output_dir=false
use_rerun_dir=false

if [ "$1" != "-o" ] && [ "$1" != "-r" ]; then
  dut_dir="$1"
  shift
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    -o)
      if [ "$#" -lt 2 ]; then
        echo "Error: -o requires a directory path." >&2
        exit 1
      fi
      run_dir="$2"
      use_output_dir=true
      shift 2
      ;;
    -r)
      if [ "$#" -lt 2 ]; then
        echo "Error: -r requires a workspace path." >&2
        exit 1
      fi
      rerun_dir="$2"
      use_rerun_dir=true
      shift 2
      ;;
    *)
      make_args+=("$1")
      shift
      ;;
  esac
done

if [ "$use_output_dir" = true ] && [ "$use_rerun_dir" = true ]; then
  echo "Error: -o and -r cannot be used together." >&2
  exit 1
fi

if [ -n "$dut_dir" ]; then
  if [ ! -d "$dut_dir" ]; then
    echo "Error: DUT directory not found: $dut_dir" >&2
    exit 1
  fi
  src_dir="$(cd -- "$(dirname -- "$dut_dir")" && pwd -P)"
  dut="$(basename -- "$dut_dir")"
fi

if [ -n "$rerun_dir" ]; then
  if [ ! -d "$rerun_dir" ]; then
    echo "Error: rerun workspace not found: $rerun_dir" >&2
    exit 1
  fi
  cwd_dir="$(cd -- "$rerun_dir" && pwd -P)"
  if [ -z "$dut_dir" ]; then
    if ! dut="$(infer_dut_from_workspace "$cwd_dir")"; then
      echo "Error: unable to infer DUT name from rerun workspace: $cwd_dir" >&2
      exit 1
    fi
    src_dir="$cwd_dir"
  fi
else
  if [ -z "$dut_dir" ]; then
    echo "Error: DUT directory is required unless -r is provided." >&2
    usage
    exit 1
  fi
  mkdir -p "$run_dir"
  timestamp="$(date '+%Y-%m-%d-%H-%M-%S')"
  cwd_dir="$(cd -- "$run_dir" && pwd -P)/${dut}-${timestamp}"
  mkdir -p "$cwd_dir"
fi

exec make -C "$repo_root" "SRC=$src_dir" "CWD=$cwd_dir" "test_$dut" "${make_args[@]}"
