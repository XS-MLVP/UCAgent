
# Performance, Context, and Stability Observations

## Is a 20-40 minute single-stage run normal?

Business complexity affects tool, Checker, and documentation generation times, but duration alone cannot determine normality. Effective long-running tasks continuously generate diverse tool invocations, file changes, or progressively shrink the failing set; ineffective long-running tasks typically repeatedly read the same large files, perform full checks, compress consecutively, or restate conclusions without state changes.

Recording the stage start time, the last five tool invocations, the target file mtime, failure count, and compression timestamp is more reliable than observing the TUI display.

## Continuous Context Compression

**Mechanism**: Compression only summarizes existing history. If compression triggers a task to immediately read large amounts of reports, contracts, docs, and source code, the new context will quickly exceed limits again, and the Agent may continuously build understanding without modification.

**Handling**: Convert assessments and incremental tasks to index-first, responsibility queues, single target per run, and evidence-to-disk. The compression summary saves the current ID, read index, pending items, and the next action, avoiding redundant full-text insertion. GuideDoc provides a short execution version, while detailed contracts are read directionally based on the issue.

**Prevention**: Limit single tool output, use line ranges and structured queries; do not interpret "fully understanding the process" as reading every file verbatim.

## `incomplete chunked read`

This exception indicates that the HTTP stream was closed by the peer before the complete response ended. It may involve the model service, proxy, network link, timeout, or connection stability under large requests. It is not a Python file write error directly caused by a business file being locked.

If the exception consistently occurs after reading a specific file, the file may simply be the last tool result of the next model request, not proving that the read action itself crashed. Compare request context size, whether it consistently occurs at the model node, whether short requests succeed, and different proxy paths and service logs. Editing too much content at once increases generation time and response body, which is a risk factor, but the stack trace alone cannot confirm it as the sole cause.

## `config.yaml` and `Makefile` appearing locked

UCAgent historical snapshots may alter permissions, or another process may be processing the same workspace. File locks/read-only and model stream interruptions operate at different layers. Check `stat`, processes, history permission daemons, and actual write errors. The `Makefile` is responsible for restoring history and writable workflow status; incremental deployments use atomic replacement and do not rely on in-place writing of the original file.

## Browser profile lock warning

When the UI automatically exits verification, the browser deletes the `lock` in the profile, and concurrent thread cleanup may result in `ENOENT`. If only the lock in `tmp` disappears and the verification return code is normal, this is a cleanup race warning. The cleanup routine should ignore non-existent paths and delete the entire `tmp/ui_validation/` directory after stopping UI verification.

## Performance Optimization Principles

- Generate independent files in batches, performing a comprehensive check on the final run.
- Share specs and register files for serial writes; independent business tools can prepare in parallel.
- After failure, only re-run affected checks, then perform a full check before stage completion.
- Read summaries, indexes, and related source code without re-reading full text.
- Stop repeating commands when state shows no change, entering repair or blocking branches.

## How to Distinguish Network, Request Size, and Business Errors

Model stream exception stacks typically stop at `httpx/openai streaming`; business errors usually return structured results from Tools or Checkers; local file permission errors appear as specific `PermissionError` or replace failures. Record the exception occurrence node, the size of the last tool result before the request, and behavior after automatic retry.

Stable short requests repeatedly experiencing stream interruption within the same stage while carrying large documents indicate that context or response scale are high-probability factors, but proxy and service limits must still be compared. Failure persists after switching networks, which can only partially rule out link issues and cannot prove a single root cause.

## Context Budget Practices

Read only the manifest, directory, and target index in the first round; read direct source code and one layer of dependencies for each issue; limit tool results to line counts; write evidence to structured reports promptly; save completed IDs and next actions in the compression summary. Do not embed 300 lines of assessment contracts within each stage prompt.

## Batch Check Strategy

When generating ten documents, complete this batch first, then run `make check_docs` once. After failure, only fix the failed files and run specific checks; perform a full check before stage completion. Tools and Checkers with independent source code can prepare in parallel, while shared configs/specs must be submitted serially. This reduces model rounds without sacrificing final evidence.

## Performance Recording Table

Record at least: stage, start time, last change time, invocation count, failure count, compression count, target file count, and final return code. Compare these metrics across business scenarios to determine if new rules truly improve speed, rather than relying solely on subjective experience.
