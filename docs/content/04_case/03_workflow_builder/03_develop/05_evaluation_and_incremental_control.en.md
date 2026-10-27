
# Parent Workflow Evaluation, Incremental, and Console Secondary Development

This guide instructs users on secondary development of the parent workflow evaluation suite, incremental state machine, controlled deployment, and the "Workflow Build and Evaluation Console". Modifications focus on `tools/workflow_evaluation_control/` and root evaluation/incremental configurations, not on individual evaluation reports or sub-workflow source code.

## Secondary Development Goals

Typical tasks include adding report types or check IDs, adjusting severity rules, adding approval actions, modifying incremental run/batch/attempt, extending candidate stagers/deployers, changing backup recovery policies, or adding console pages or structured edit files. All extensions must maintain backward JSON readability, traceable approval sources, rollable formal documents, and restricted API paths.

## Parent Workflow Modification Entry Points

- `eval_*.yaml`, `inc.yaml`, and corresponding GuideDocs: Agent phase and task boundaries.
- `tools/workflow_evaluation_control/json_store.py`: structured file schema, CRUD, and atomic persistence.
- `approvals.py`: finding/suggestion decision and fingerprint.
- `incremental.py`, `incremental_runs.py`: candidates, deployment, history, and run identity.
- `review_server.py`, `design_editor.py`, and frontend resources: console API and UI.
- `uc_tools.py`, `uc_checkers.py`: expose controlled operations and acceptance to the parent Agent.
- evaluation split, review UI, write boundary regression: behavior protection.

## Report Model

Evaluation components write check results and findings to `eval/`. User approvals and suggestions possess stable IDs, status, reasons, timestamps, and sources. Aggregated reports retain history across different runs; old findings cannot represent modified new evaluation results.

Structured files must be created, updated, read, or deleted via the storage interface. When extending fields, provide default values and migration reads to prevent console crashes due to missing fields in old workspaces. Deleting entries is an explicit API; versioned deletions must also synchronize management of corresponding historical files and references.

## Incremental Run Identity

Each `run_inc` invocation first calls `start-inc-run`, generating a unique ID and `tmp/inc_runs/<id>/`. All approvals snapshots, candidate files, check records, deployment lists, and final states for this round are associated with this ID. The Agent can only read candidates from the current run and cannot treat previous round residues as approved modifications.

## Candidates and Deployment

The parent workflow should provide controlled tools to copy formal files to the current candidate directory. Modifications occur in the candidate replica; subsequent runs perform syntax, fixture, and related Make checks. The deployer creates temporary files in the same filesystem, saves old versions, and atomically replaces formal files, even if the original file is not writable in-place.

Old versions are saved to `tmp/change_history/`, with index records containing original paths, backup paths, hashes, timestamps, run IDs, and recovery status. Recovery is also a controlled atomic deployment; deleting history records must be explicitly triggered by the user.

## State Machine Termination Conditions

- No approved targets: normal quick termination.
- Candidate check failure: continue fixing candidates; do not deploy.
- Deployed but `make check` failure: immediately continue fixing or rollback; do not wait for new approvals.
- All approved targets have changes and evidence, regression passed: complete.
- Unable to fix within approved scope: report blocking reasons and incomplete mappings, then fail exit.

Repeated execution of the same failed command with unchanged state, files, and evidence constitutes a spin loop; the cycle should stop and enter an explicit fix or block branch.

## Console Extensions

The backend entry point is located at `tools/workflow_evaluation_control/review_server.py`, with structured design edit logic in `design_editor.py`. When adding new page fields, extend the server-side schema and validation first, then implement frontend presentation. File paths must be resolved from an allowlist and workspace root; arbitrary absolute paths passed by the browser are prohibited.

## Testing Priorities

- Concurrent report writes do not lose data.
- Old format files are readable and migratable.
- Unapproved entries cannot enter incremental snapshots.
- Two incremental runs do not share candidates.
- Old versions are saved before deployment; hashes match after recovery.
- Deleting version entries maintains files and indices.
- Illegal paths, symlinks, and out-of-bounds targets are rejected.
- Failed post-deployment regressions do not remain pending.

## Structured File Model

Evaluation control uses a fixed allowlist to manage `eval/` and `res/`. Each document possesses a format version, revision, and specific collection: evaluation reports use `runs`, approvals and suggestions use `items`, deployment records use `entries`, and audits use `events`. When the Agent calls tools, pass individual records, not entire JSON documents, to avoid overwriting all history with a single error.

Report runs contain run ID, contract version, status, timestamp, target revision, checks, findings, and metrics. Findings include stable ID/fingerprint, severity, evidence, impact, and suggestions. Approvals are bound to the source report, run ID, source ID, and fingerprint; if the source finding content changes, old approvals are no longer current.

## JSON Load and Validation Code Analysis

Source location: `tools/workflow_evaluation_control/json_store.py`, symbols `load_document()` and `validate_document()`.

```python
value = json.loads(path.read_text(encoding="utf-8"))
return validate_document(relative, value)
```

This seemingly simple load function separates reporting "file not found", "JSON format error", and "invalid schema". `validate_document()` selects the corresponding structural rule based on the relative path, rejecting Agent-created unknown eval files. Developers adding new document types must simultaneously update the allowlist, base document, validation, collection name, record ID, template, CLI, and console.

Validation at load time means historical file corruption is immediately exposed upon reading, rather than silently overwriting during the next mutation. Error messages retain line and column numbers to facilitate user repair of manually corrupted files, but the normal flow should still write through structured tools.

## Atomic Write and Permission Code Analysis

Source location: `tools/workflow_evaluation_control/json_store.py`, symbol `_atomic_write()`.

```python
tmp_root = workspace / "tmp/json_store"
fd, temporary = tempfile.mkstemp(dir=tmp_root)
json.dump(value, stream, indent=2, ensure_ascii=False)
stream.flush()
os.fsync(stream.fileno())
os.replace(temporary, path)
```

Temporary files are uniformly placed in the root `tmp/`, flushed and fsynced after writing, then atomically replaced with `os.replace()`. The function temporarily restores parent directory and target user write permissions, then restores parent directory mode and removes group/other write bits on eval files after completion. This prevents half-written JSON and explains why direct editors might see files as read-only.

Read-only is not "permanently locked": controlled storage and deployers can update via directory-level atomic replacement. Developers cannot globally `chmod -R 777` for convenience, as this would break audit boundaries. Exception branches must clean up temporary files and restore permissions.

## CRUD and Concurrency Code Analysis

Source location: `tools/workflow_evaluation_control/json_store.py`, symbol `mutate_document()`.

`expected_revision` implements optimistic concurrency control. After the console reads the revision and submits edits, if the evaluation Agent has updated the document in the meantime, the server rejects the old draft, preventing post-write overwriting pre-write. Create rejects duplicate IDs; update/delete require record existence; upsert explicitly allows both.

Each successful mutation increments the revision, performs atomic write, and appends audit. List/get returns deep copies to prevent callers from modifying in-memory objects and bypassing persistence. When adding batch operations, they must still complete under a single lock and single revision; looping single API calls can lead to partial success.

## Approval Freshness Analysis

Source location: `tools/workflow_evaluation_control/approvals.py`, symbols `_fingerprint()`, `decide_item()`, and `approval_is_current()`.

The fingerprint is calculated based on the stable business content of findings/suggestions, not just the ID. Approval records store the source run and fingerprint; during incremental deployment, the current source object is re-read and compared. If the evaluation regenerates the same ID but the problem content changes, the user must re-approve.

Approve, reject, and defer are user decisions; the Agent cannot approve its own findings. Default responses reduce input, but the console must allow user modification. Batch approvals apply only to user-selected records, saving sources for each item, avoiding an untraceable "big approval" for specific issues.

## Incremental Candidates and Run Identity

Each `start-inc-run` generates a run ID, below which batches and attempts are established. Candidate stagers only allow copying explicitly targeted files from `workflow/` to the current attempt's candidate directory, recording source hashes. The Agent modifies candidates, not formal files, ensuring check failures do not pollute the public workflow.

Run ID resolves issues with old candidate mixing; batch represents a group of related approvals; attempt represents retry fixes within the same batch. Reports, candidates, evidence, and history must carry these identities. A single long-lived `tmp/candidate/` directory covering all rounds cannot be used.

## Deployer Code Analysis

Source location: `tools/workflow_evaluation_control/incremental.py`, symbol `deploy_incremental_changes()`.

The deployer first validates `workflow_root`, mapping, change ID, fixed manifest path, current run, and current approvals. Each mapping must include source, target, approval IDs, and rationale, with all approvals within the current authorization set. It then executes projected semantics, preventing candidates from introducing new deterministic high-risk findings.

```python
approved = {
    item["id"]: item for item in approvals["items"]
    if approval_is_current(workspace, item)
}
if any(item not in approved for item in approval_ids):
    raise IncrementalDeploymentError(...)
```

This check prevents old approvals, forged IDs, or changed findings from being deployed. Mappings must also reference covering approvals, allowing applied changes to answer "why this file is allowed to be modified".

## Backup, Atomic Replacement, and Rollback

Source location: `tools/workflow_evaluation_control/incremental.py`, symbols `_atomic_copy()`, `_archive_target()`, and `_rollback_targets()`.

`_atomic_copy()` creates a temporary file in the target parent directory, uses `copy2` to preserve metadata, and then `os.replace`. The original target can be a read-only file because it is not written in-place. `_archive_target()` saves the pre-replacement file to a relative path under the current `history/before` and computes the SHA-256 hash; the new file records `existed=False`.

When a batch deployment fails midway, rollback restores existing files in reverse order and deletes files added in the current run. Reverse order is critical because subsequent targets may depend on preceding directories or configurations. Rollback should also record failures; if rollback itself fails, the report must be escalated to a critical state and cannot return a standard deployment failure.

## Restore and Delete History

`restore_incremental_backup()` searches records, verifies backup paths are within the allowed history root, checks hashes, and saves the current formal version before restoration. This allows users to undo restoration after restoring an older version. `delete_incremental_backup()` only responds to explicit user actions, updates the index, and deletes unreferenced backups.

Version records are immutable by default for Agents to support auditing; user deletion in the console is an explicit, controlled management action. Frontend buttons, backend APIs, reference checks, and file deletion must all be implemented together; removing only the UI entry would leave orphaned files.

## Incremental State Machine and make check

If a candidate check fails, continue fixing the candidate; if `make check` fails on the formal version after successful deployment, continue fixing or rollback. At this point, do not wait for new approval, as the target is already authorized by the current approval and formal files have already changed. Only rollback and report a need for new decision if the fix requires going beyond the original approval scope.

Anti-loop conditions should compare state, candidate hash, check return code, and new evidence. If the same command is executed consecutively and none of these values change, the process should enter a fix or block state, no longer treating stage prompts as new requests for repeated verification.

## Console Backend and Structure Editing

`review_server.py` binds the workspace to the handler, exposing only fixed APIs. `design_editor.py` provides editor schemas, drafts, cross-file validation, and save functionality by file type. The browser can only edit allowed fields; the server re-reads the original revision, applies the draft, validates all candidates, and then atomically saves.

The workflow file tree reading API must also restrict paths, symbolic links, size, and binary types. Files without a fixed schema display raw text only; guessing fields for a pretty interface and writing back is not allowed. When adding monitored files, simultaneously update the whitelist, artifact parser, frontend renderer, and API regression tests.

## Fault Scenarios and Testing

Test coverage must include: corrupted JSON, revision conflicts, duplicate IDs, expired approvals, candidate out-of-bounds, target out-of-bounds, backup hash mismatch, second run using old candidate, batch deployment failure midway, rollback failure, read-only targets, history restore and delete, and post-deployment regression failure. Each test runs in a temporary workspace without touching real business data.

For the console, also test: two workspace port conflicts, existing service detection, invalid path 400, unsaved draft, structure validation failure, batch approval, and explicit deletion. HTTP 200 only proves API response; business state correctness must be re-asserted by re-reading JSON and target files.

## Five Evaluation Workflows Itemized Responsibilities

The evaluation suite uses five independent YAML files. Splitting them limits reading scope, report writing, and tool permissions, avoiding the need to start high-cost sub-workflows for any single static evaluation.

| Configuration & Stage | Input/Output | Must Check | Explicitly Prohibited |
| --- | --- | --- | --- |
| `eval_tools.yaml` / `evaluate_tool_contracts` | Read tool source, register, spec, fixture, requirements, and `res/`; write `eval/tools_report.json` | Verify all tools exist, comply with UCTool protocol, config correctly registered, source contains real business logic, fixtures/direct calls prove availability, requirements cover user needs | Do not start sub-workflows, do not modify `workflow/`, do not declare tools available just because files exist. |
| `eval_checkers.yaml` / `evaluate_checker_contracts` | Read Checker source, config args, fixture, stage product contracts, and `res/`; write `eval/checkers_report.json` | Checker exists, protocol/docstring, class import, constructor args match registration, positive examples pass and single-negative fails, determines if proof of requirement, does not reference future files or form unpassable thresholds | Do not lower business semantics to make existing products pass, do not directly modify Checkers. |
| `eval_flow.yaml` / `evaluate_flow_contracts` | Read config/inc, workflow spec, Tool/Checker/GuideDoc index, and requirements; write `eval/flow_report.json` | YAML parsing is just the start; also check placeholder declarations, reference/output specifics and timeliness, Tool/Checker/GuideDoc loadability, stage outputs support subsequent stages, documents match real signatures | Do not just search for `{INPUT}` patterns; check all undeclared variables and closure references; do not start sub-processes. |
| `eval_env.yaml` / `evaluate_environment_contracts` | Read Makefile, setup.py, `ucagent_setup.sh`, requirements, schema, and environment docs; write `eval/env_report.json` | Make targets and variable priorities, setup controlled updates, requirements distinguish Python/non-Python, paths portable, secrets not written to disk, port conflicts resolvable, permissions do not block atomic replacement | Do not treat local absolute paths as portable, do not modify user `res/checkers.json` without authorization. |
| `eval_run.yaml` / `evaluate_requested_runtime` | Read user-specified runtime target, inputs, and existing static evidence; write independent runtime report | Use `ChildWorkflowSupervisor` to start specified sub-process, record stage, duration, failure, product changes, stuck, and termination evidence | Do not start high-cost business flows by default with `run_eval`, do not wait indefinitely without timeout/termination policies. |

Severity ordering is: issues preventing UCAgent startup, infinite retries, destructive/out-of-bounds replacement of formal files, or inability to rollback are highest risk; products deviating from user semantics while claiming completion follow closely; deterministic check failures, missing critical evidence, and non-reproducible installs are high/medium risk; text not affecting results and optional improvements are low risk.

## Incremental Workflow Four Stages Itemized Explanation

| `inc.yaml` stage | Primary Input | Tools & Products | Checker & Pass Semantics |
| --- | --- | --- | --- |
| `understand_generated_workflow` | Current inc run ID, approved finding/suggestion snapshot, sub-workflow index, `res/` index, and direct dependencies | `IncrementalContextInventory` produces a budgeted context report, `StructuredJsonStore` records this run's state; read list and targets first, then source as needed | `generated_workflow_context_complete` only proves sufficient preliminary understanding to plan this fix, does not require reading all docs/tools/checkers in full. |
| `plan_approved_changes` | Current approval snapshot, context report, source file hashes, and related requirements | Build candidate plans for this run/batch/attempt, mapping each change to approval ID, source, target, reason, implementation, and acceptance commands; use stager to copy formal files | `applied_changes_have_approval` checks that plans and subsequent records only reference current approvals; unapproved suggestions cannot be mixed in. |
| `deploy_approved_changes` | Current attempt candidate, mapping, approval snapshot, candidate check evidence | Use generator or controlled editing to update candidates; after passing checks, `IncrementalChangeDeployer` backs up old versions and deploys atomically, writing `applied_changes.json` and history | `approved_changes_deployed`, `all_current_approvals_deployed` require a deployed/skipped/blocked mapping for each current approval; passing is not granted just by generating a plan. |
| `verify_and_report_increment` | Formal files, applied changes, history, this run's check commands, and all approval acceptance conditions | Run `make check` and related targets on formal sub-workflows; on failure, immediately return to candidate fix or rollback; on pass, write `incremental_report.json` with acceptance evidence | `incremental_make_check_passed`, `incremental_report_complete`, `incremental_guide_complete`, `incremental_static_audit_covered` jointly prove formal products pass, reports are complete, and no out-of-bounds changes occurred. |

Approval authorizes "the scope of fixes for the target issue," not "asking again for each file replacement." If formal files deployed after regression fail, iterative fixes within the same scope do not require new approvals, but each replacement must save versions and evidence. Changes to other unauthorized files require rollback or a report for new approval.

## Console Subsystem Secondary Development Map

The "Workflow Construction and Evaluation Console" has three types of data interfaces: evaluation and approval are structured JSON CRUD; construction design is field-level draft editing for YAML with fixed schemas, full-text read-only for unstructured Markdown; version management is restore and explicit delete for change history. These three cannot be merged into a single "turn any file into a JSON form" API.

`review_server.py` handles HTTP routing, workspace binding, error codes, and static resources; `json_store.py` and `approvals.py` manage evaluation data; `design_editor.py` manages editor schemas, drafts, and cross-validation for `wfgen/input_example_manifest.yaml`, `wfgen/workflow_build.yaml`, `wfgen/requirements_manifest.yaml`, and other allowed fields; artifact reader parses implementation plan markers, YAML outlines, JSON reports, and the `workflow/` file tree. The server must re-verify every save; it cannot trust that the browser has already performed word count and cross-file checks.

When adding new editable fields, synchronize allowed fields, value types, create/delete rules, word counts/statistical derived values, cross-file references, revision conflicts, and save regression tests. Do not open raw full-text coverage to bypass the structural view. When adding new read-only monitored files, update the allowed list, parser, navigation outline, file size limits, and illegal/symbolic link path regression tests.

## Continue Reading

Every invariant for evaluation and incremental control requires deterministic regression. Please continue reading [Testing and Regression](06_testing.md) to understand the responsibility boundaries protected by each existing regression script.
