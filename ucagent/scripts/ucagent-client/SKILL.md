---
name: ucagent-client
description: Control a running UCAgent CMD API server from an AI agent or shell. Use when the user wants to connect to UCAgent, run runtime commands, inspect status, console, mission, tasks, tools, workspace files, pause or cancel execution, or call raw CMD API endpoints.
---

# UCAgent Client

Use the bundled helper to communicate with a running UCAgent
`ControlApiServer`. The helper is dependency-free Python and can be used from
any agent runtime that can execute local shell commands.

## Helper Resolution

1. Resolve paths relative to this `SKILL.md`.
2. Prefer `scripts/ucagent_client.py`.
4. Run the helper as `python3 <helper> ...`.

Do not print password values. It is fine to report whether a password is set.

## Connection Behavior

- `init` without a URL probes default Unix sockets first, then
  `http://127.0.0.1:8765`.
- A saved connection target is tried first. If it is unavailable, the helper
  falls back to default targets automatically.
- Supported targets: `http://host:port`, `https://host:port`, `host:port`,
  `unix:///path/to.sock`, and `/absolute/path/to.sock`.
- Default state file: `.agents/ucagent-client.json` in the current workspace.
- Legacy state files `.uclient/ucagent-client.json` and `.uclient/ucagent.json` are
  still read for compatibility.
- Override state with `UCAGENT_CLIENT_STATE=/path/to/state.json`.
  `UCAGENT_UCLIENT_STATE` is accepted only as a legacy override.

## Command Mapping

Map user intent to helper subcommands:

- Connect/save target: `python3 <helper> init [url] [--passwd <key>]`
- Run one runtime command: `python3 <helper> cmd <cmd> [args...]`
- Run multiple commands: `python3 <helper> batch <cmd> [<cmd> ...]`
- Show status: `python3 <helper> status`
- Show help: `python3 <helper> help [cmd]`
- List runtime commands: `python3 <helper> cmds [prefix]`
- Show console output: `python3 <helper> console [--lines N]`
- Clear console output: `python3 <helper> clear-console`
- Show mission progress: `python3 <helper> mission`
- Show task list: `python3 <helper> tasks`
- Show one task: `python3 <helper> task <index>`
- Show tool usage counts: `python3 <helper> tools`
- Show recently changed files: `python3 <helper> changed-files [--count N]`
- List workspace files: `python3 <helper> files [path]`
- Read a workspace text file: `python3 <helper> file <path>`
- Pause UCAgent: `python3 <helper> pause`
- Query an operation: `python3 <helper> operation <id>`
- Cancel an operation: `python3 <helper> cancel <id>`
- Remove saved state: `python3 <helper> disconnect`
- Call an endpoint directly: `python3 <helper> raw <METHOD> <PATH> [JSON]`

For status-style commands, summarize the important fields instead of dumping
very large JSON unless the user asks for raw output.

Command submissions return `operation_id`; poll the operation until `succeeded`, `failed`, or `cancelled`. Acceptance alone is not completion.

Use `cmd --session <id> ...` to reuse the session returned by an earlier submission. Supply `--confirmed` only after the operator has approved a command that requires confirmation.
