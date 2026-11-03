
# Console and Port Issues

## `Address already in use`

**Symptom**: When starting `eval-ui`, the error `127.0.0.1:8765` is already in use is displayed.

**Cause**: The same port is already being listened to by the console or another program. An HTTP service cannot bind to the same address and port multiple times.

**Verification**:

```bash

# Linux

ss -ltnp | grep ':8765'

# macOS

lsof -nP -iTCP:8765 -sTCP:LISTEN
```

If a correctly functioning workspace console already exists, open it directly. If parallel consoles are required, set `EVAL_UI_PORT=8766`. Do not allow the Makefile to automatically kill unknown processes.

## How to release the port after approval

Return to the terminal where `make ... eval-ui` was started and press `Ctrl+C`. After the service exits, verify again using `ss` or `lsof`. If the terminal is lost, first confirm the process is indeed this project's console based on the PID, then send a normal termination signal.

## Missing Plan or Report

The console uses the `WS` passed at startup as the root, reading `wfgen/workflow_implementation_plan.md`, three YAML manifests, `eval/incremental_report.json`, and `eval/applied_changes.json`. Do not search for these design files in the Workflow Builder source directory or within the generated workflow.

## Incorrectly Structured Design Page Layout

Fixed-format YAML/JSON uses structural parsing; Markdown plans are parsed by phase markers and headings; files without fixed formats display full text. If parsing fails, display the error and raw text instead of rendering an empty page. Navigation belongs to the current document and should appear below the fixed basic information, with the main body scrolling independently.

## Version History Deletion Prompt Invariant

Version history is by default immutable and cannot be silently modified by the Agent, but explicit deletion requests initiated by the user in the version management interface should be allowed. The backend must validate user actions, record IDs, and reference relationships, deleting indexes and any unreferenced backups. Changing only the frontend to hide errors does not alter the backend's immutability policy.

## How Structured Editing Takes Effect

Page editing creates drafts for allowed fields; these are only sent upon clicking Save. The backend re-validates types, body length, references, computed fields, and concurrent versions before atomic write. Leaving the page without saving should prompt a warning; the original file cannot be arbitrarily rewritten via the generic text interface.

## Blank Page or Data from Wrong Workspace

First, request `/api/meta` and verify the returned workspace against the startup command. Old browser tabs may still be connected to another port; the console name being the same does not imply the workspace is the same. Also check `/api/state` and the background HTTP status. Do not mask backend root path errors by modifying the frontend title.

## revision conflict

After a user opens a design file, the background Agent may update the same file. When saving, if the revision/hash is inconsistent, the operation should be rejected and a reload with merge required. Directly overwriting will lose the Agent's new phase records. When confirming a conflict, save the current draft to a user-visible area, but do not bypass validation to write the original file.

## Filtering and Batch Operations

Filtering only affects display and does not change state. Batch approval must use the ID explicitly selected by the user after applying the current filter; hidden records cannot be submitted together. Approve, defer, reject, and unapproved are mutually exclusive view dimensions; "approved" is a higher-level collection. Refresh after operation and verify each source ID.

## Background Process Management

Pressing `Ctrl+C` in the startup terminal is the preferred way to exit. If the terminal is lost, use `ss` to find the PID, then verify the command line and workspace before sending TERM. Do not use broad `pkill python`. After the service exits, confirm the port is released and check for no lingering browser verification processes.
