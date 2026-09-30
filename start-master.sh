#!/usr/bin/env bash
# Start the persistent UCAgent Master with the OpenAI-compatible backend settings.

set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$script_dir"

if [[ $# -gt 0 ]]; then
    printf 'Usage: OPENAI_API_KEY=... %s\n' "$(basename "$0")" >&2
    exit 2
fi

: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"

# Keep the endpoint and model used by the Master in one local, reviewable place.
OPENAI_API_BASE="http://172.28.11.121:18084/v1"
OPENAI_MODEL="gpt-6-sol"

export OPENAI_API_KEY OPENAI_API_BASE OPENAI_MODEL

exec make as_master_persist ARGS="--as-master 172.19.20.20:8800"
