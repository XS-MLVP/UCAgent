#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=${RTL2SPEC_WORKSPACE:-"$PWD"}
PYTHON=${RTL2SPEC_PYTHON:-python3}
XS_ROOT=${XIANGSHAN_ROOT:-"$ROOT/third_party/XiangShan"}
CACHE_ROOT=${RTL2SPEC_CACHE:-"$ROOT/.cache"}
MODULE=
CONFIG=DefaultConfig
RESULT=
ESPRESSO_COMMIT=${ESPRESSO_COMMIT:-85265139e9598852f9388d293658a1977a829a01}

usage() {
  cat <<'EOF'
Usage: generate_rtl.sh --module NAME --config CONFIG --result FILE

Generate split RTL or reuse a verified tool cache. Write generation details to FILE.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --module) MODULE=${2:?missing module}; shift 2 ;;
    --config) CONFIG=${2:?missing config}; shift 2 ;;
    --result) RESULT=${2:?missing result path}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'error: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$MODULE" && -n "$RESULT" ]] || { usage >&2; exit 2; }
invocation="xiangshan.runMain top.TopMain --config $CONFIG"

bash "$SCRIPT_DIR/preflight.sh" --module "$MODULE" --config "$CONFIG"

commit=$(git -C "$XS_ROOT" rev-parse HEAD)
mill_version=$(tr -d '[:space:]' < "$XS_ROOT/.mill-version")
java_home=$(bash "$SCRIPT_DIR/bootstrap_jdk.sh")
java_version=$("$java_home/bin/java" -version 2>&1 | head -n 1)
flags='--issue E.b --num-cores 1 --target systemverilog --split-verilog --dump-fir --fpga-platform --reset-gen --ignore-read-enable-mem'
wrapper_hash=$("$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$SCRIPT_DIR/generate_rtl.sh")
fingerprint=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$commit" "$CONFIG" "$mill_version" "$java_version" "$flags" "$(uname -s)" "$(uname -m)" "$ESPRESSO_COMMIT" "$wrapper_hash" | "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest()[:20])')
cache_dir="$CACHE_ROOT/rtl/$fingerprint"
target_dir="$cache_dir/split"
cache_rtl="$target_dir/$MODULE.sv"
tool_versions="$cache_dir/tool_versions.json"

cache_reused=0
if [[ -s "$cache_rtl" ]] && "$PYTHON" -m rtl2spec.runtime cache-check \
    --module "$MODULE" --config "$CONFIG" --rtl "$cache_rtl" >/dev/null 2>&1; then
  cache_reused=1
  printf 'Using cached RTL: %s\n' "$cache_rtl"
else
  rm -rf "$target_dir"
  mkdir -p "$cache_dir" "$target_dir"
  mill=$(bash "$SCRIPT_DIR/bootstrap_mill.sh")
  espresso=$(bash "$SCRIPT_DIR/prepare_espresso.sh")
  bundled="$XS_ROOT/src/main/resources/espresso"
  if [[ "$espresso" == "$bundled" ]]; then
    espresso_desc="XiangShan bundled binary"
  else
    espresso_desc="native build $ESPRESSO_COMMIT for $(uname -s)/$(uname -m)"
  fi
  backup="$cache_dir/espresso.original"
  original_hash=$(git -C "$XS_ROOT" hash-object "src/main/resources/espresso")
  cp "$bundled" "$backup"
  restore() {
    cp "$backup" "$bundled"
    restored_hash=$(git -C "$XS_ROOT" hash-object "src/main/resources/espresso")
    if [[ "$restored_hash" != "$original_hash" ]]; then
      printf 'fatal: failed to restore XiangShan Espresso resource\n' >&2
      exit 1
    fi
  }
  trap restore EXIT INT TERM
  if [[ "$espresso" != "$bundled" ]]; then cp "$espresso" "$bundled"; fi

  set +e
  (
    cd "$XS_ROOT"
    JAVA_HOME="$java_home" PATH="$java_home/bin:$PATH" NOOP_HOME="$XS_ROOT" "$mill" -i -Djvm-xmx=40G -Djvm-xss=256m xiangshan.runMain top.TopMain \
      --target-dir "$target_dir" --config "$CONFIG" --issue E.b --num-cores 1 \
      --target systemverilog \
      --firtool-opt "-O=release --disable-annotation-unknown --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none" \
      --split-verilog --dump-fir --fpga-platform --reset-gen \
      --firtool-opt --ignore-read-enable-mem
  ) 2>&1 | tee "$cache_dir/generation.log"
  generation_rc=${PIPESTATUS[0]}
  set -e

  restore
  trap - EXIT INT TERM
  if [[ ! -s "$cache_rtl" ]]; then
    printf 'error: generation returned %d and did not produce %s.sv\n' "$generation_rc" "$MODULE" >&2
    exit 1
  fi
  "$PYTHON" - "$tool_versions" "$mill_version" "$java_version" "$cache_rtl" "$espresso_desc" "$(uname -s)" "$(uname -m)" <<'PY'
import json, sys
path, mill_version, java_version, rtl_path, espresso, host_os, host_arch = sys.argv[1:]
firtool = "unknown"
try:
    first = open(rtl_path, encoding="utf-8").readline().strip()
    if "firtool-" in first:
        firtool = first.split("firtool-", 1)[1]
except OSError:
    pass
json.dump({"java": java_version, "mill": mill_version, "firtool": firtool, "espresso": espresso, "host_os": host_os, "host_arch": host_arch}, open(path, "w", encoding="utf-8"), indent=2, sort_keys=True)
open(path, "a", encoding="utf-8").write("\n")
PY
  printf '%s\n' "$generation_rc" > "$cache_dir/generation.exit-code"
fi

status=success
if [[ -f "$cache_dir/generation.exit-code" && "$(cat "$cache_dir/generation.exit-code")" != "0" ]]; then status=partial; fi

"$PYTHON" - "$RESULT" "$cache_rtl" "$status" "$invocation" "$flags" "$tool_versions" "$cache_reused" <<'PYRESULT'
import json, sys
output, rtl, status, command, flags, versions, reused = sys.argv[1:]
with open(output, "w", encoding="utf-8") as handle:
    json.dump({"rtl": rtl, "generation_status": status, "command": command,
               "generator_flags": flags, "tool_versions": json.load(open(versions)), "cache_reused": reused == "1"}, handle)
PYRESULT
printf 'RTL: %s\n' "$cache_rtl"
