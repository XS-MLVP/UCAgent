
# Incremental Repair and Version Management

The incremental process organizes "approved findings, candidate modifications, formal deployment, regression evidence, and historical versions" into a single, identity-bound execution. It addresses controlled maintenance of generated workflows without replacing the regeneration of all business files.

## Current Round Inputs

At startup, freeze the current approved findings and suggestions; `eval-suggest` creates suggestions only, which still require approval via `eval-approve` or the console. Each item requires a stable ID, approval status, description, and determinable target. The incremental Agent first reads the workflow structure summary, tools and Checker index, relevant GuideDoc, and user docs directory, then reads the source code targeted by the round's objectives. A preliminary understanding does not require reading all files in full.

## Candidate Plan

The candidate plan records: run ID, approved items, estimated files, purpose of each modification, risk, check commands, and deployment order. The plan is located in the round's `tmp/inc_runs/<id>/` directory, not in `wfgen/workflow_implementation_plan.md`. The latter belongs to the initial cross-stage design constructed at the beginning; the console should display them separately.

## Modification and Verification

Formal files first enter the candidate directory via a controlled copy tool. After the Agent modifies the candidate, it runs syntax, structure, fixture, and affected Make targets. Deployment proceeds only if checks pass; the deployer saves old files and performs atomic replacement. After deployment, checks must be run again on the formal directory, as candidate and formal paths may have different reference relationships.

## Historical Versions

Each deployed file is saved with its content and structured index in `tmp/change_history/`. The index includes original path, backup, hash, run ID, timestamp, and action. The console allows viewing, restoring, and explicit deletion.

Upon restoration, a version is first created for the current formal file, then the selected old version is atomically written back, followed by running the corresponding checks. Deletion operations must simultaneously handle the index and backup files with no other references; immutable audit defaults cannot prevent users from explicitly cleaning version records.

## Regression Failure Handling

If `make check` fails after deployment, the formal state is unacceptable. The incremental process should immediately attempt to fix based on the failure, redeploy, and verify, or rollback. In this case, there is no need to wait for the user to re-approve the same fix. If the new fix would exceed the original approval scope, rollback and report the blockage rather than leaving erroneous formal files and spinning.

## Completion Checklist

- Each approved item corresponds to at least one actual change or explicit evidence of "no modification needed".
- `applied_changes.json` is consistent with file hashes.
- Old versions are locatable and restorable.
- Relevant tools/Checker tests and `make check` pass.
- No unregistered modifications, temporary files outside the workspace, or arbitrary shell operations.
- Incremental reports do not incorrectly write pending re-evaluation as confirmed by assessment.

## Minimum Fields for Candidate Plan

The candidate plan records run/batch/attempt, approved ID, target file, estimated operation, reason, risk, candidate check, and formal check. A file may cover multiple approvals, and an approval may require multiple files; the plan must maintain a bidirectional mapping.

The plan is not a deployment record. After actual deployment, the deployer records source/target hashes, backup, timestamp, and result; the Agent cannot pre-write plan items as applied.

## Candidate Modification Rules

First, use a controlled stager to copy the formal file and record the source hash, then edit the candidate. New files are also created under the current attempt's candidates directory. Debug logs and transformation intermediates remain in `evidence/tmp`, not placed in `wfgen/` or the formal workflow root.

Candidate tests should be minimal and fast; after deployment, run full relevant checks on the formal directory. If candidate tests depend on relative workflow paths, use an isolated projection and do not preemptively overwrite formal files for convenience.

## History and Failure Exit

Restoration first backs up the current formal version, so restoration can be undone. Deletion is an explicit user cleanup, not automatically executed when the Agent completes a task. Although history resides in `tmp`, `clean` must also be preserved.

When the approval scope is insufficient, rollback and report the need for new authorization; when dependencies are missing, save the candidate and evidence and mark as blocked; candidate check failure prevents deployment; rollback failure must be escalated to a critical status requiring human recovery. Reports must include run ID, target file, and final exit code.
