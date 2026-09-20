# Workflow Evaluation Control

This package owns the fixed `eval/*.json` and `res/*.json` contracts used by the
split evaluation workflows. `StructuredJsonStore` provides initialization,
validation, record CRUD, optimistic revisions, atomic writes under
`tmp/json_store/`, mutation auditing, runtime request selection, and summary
aggregation. Agents must use the tool. Users can use the review CLI instead of
hand-writing `eval/user_suggestions.json` or `eval/approvals.json`.

`IncrementalCandidateStager` seeds an attempt by copying selected regular files
byte-for-byte from the generated workflow. It rejects directories, symlinks,
path traversal, inactive runs, and implicit overwrites. `IncrementalChangeDeployer`
accepts candidates only from the current
`tmp/inc_runs/<run_id>/batches/<batch_id>/attempts/<attempt_id>/candidate/`, requires current provenance-bound approved ids from
`eval/approvals.json`, and requires every file mapping to cite its authorizing
approval ids and a concrete rationale. It deploys paths relative to the
generated workflow and appends per-file approval links and hashes to
`eval/applied_changes.json`. A deployed finding remains
`fix_applied_pending_recheck` until its evaluator runs again.

The legacy YAML control classes remain import-compatible for old configurations,
but the current `eval_*.yaml` and `inc.yaml` workflows use JSON reports.

CLI examples:

```bash
python -m examples.workflow_builder.tools.workflow_evaluation_control.cli --workspace "$WS" initialize
python -m examples.workflow_builder.tools.workflow_evaluation_control.cli --workspace "$WS" validate
make eval-list WS="$WS"
make eval-review WS="$WS"
make eval-approve WS="$WS" ID=flow/finding-id REASON="accept this bounded change"
make eval-reject WS="$WS" ID=flow/finding-id REASON="the cited behavior is intentional"
make eval-defer WS="$WS" ID=flow/finding-id REASON="needs domain-owner review"
make eval-suggest WS="$WS" TITLE="Tighten timeout" \
  DESCRIPTION="Detect logs without stage progress." PRIORITY=high
make eval-ui WS="$WS"
```

The graphical console is available at `http://127.0.0.1:8765` by default. It
shows each evaluator's latest status and open findings, supports report,
severity, and text filters, exposes evidence and remediation fields, and records
individual or bulk decisions. Users can create typed issue descriptions,
improvement suggestions, and supplemental context without editing JSON. All
approve, reject, defer, create, and withdraw actions use the same structured
store as the CLI. Set `EVAL_UI_HOST` or `EVAL_UI_PORT` on
the make command when a different bind address or port is required. The default
loopback bind intentionally avoids exposing evaluation decisions to the network.

The review list also supports individual and bulk physical deletion. Deleting a
finding or suggestion removes its provenance-bound approval. Deployment version
records are retained as deployment evidence. Users may remove selected records
from the console list without changing formal or backup files; this action is
soft-deleted in the manifest and remains available to the audit log. Users
may explicitly delete only the archived bytes while retaining their path, hash,
time, and reason in `eval/applied_changes.json`. Every JSON mutation is recorded
in `eval/audit.json`.

The console also has a separate three-column build-design monitor. Open
`http://127.0.0.1:8765/?tab=design` to inspect the four fixed planning files in
`wfgen/`, `eval/applied_changes.json`, `eval/incremental_report.json`, the full
generated `workflow/` tree, and root `.ucagent/ucagent_info.json` progress.
The left outline selects files and parsed document sections, the center uses
contract-specific views, and the right rail summarizes the root
UCAgent stage and Checker state. Refresh is manual; the browser marks files
added, changed, or deleted since its previous in-session snapshot. Workflow
text previews are confined below `workflow/`, do not follow symlinks, and are
limited to 2 MiB. Structure banners are navigation hints rather than evaluator
or Checker verdicts. Use `design=file:<workspace-relative-path>&format=source`
to link to a specific raw file view.

The four fixed planning files expose a controlled structured editor. Raw source,
Builder infrastructure, Checker source, plan markers, and historical plan stages
remain read-only. Edits stay in browser memory across file navigation and are
written only by the top-level Save action. The server validates all drafts as
one set, checks their original SHA256 fingerprints, recalculates derived
`copy_mode` and `minimum_counts`, and rejects writes while root UCAgent is
running or its state is invalid. Validation and replacement temporary files are
confined to the workspace `tmp/` directory.

Open `http://127.0.0.1:8765/?view=repairs` to enter incremental version management directly.
This view combines the latest `eval/incremental_report.json` checks with every
file deployment in `eval/applied_changes.json`. It compares the recorded and
current SHA256, distinguishes verified, drifted, missing, and superseded
targets, and presents the run, batch, attempt, approval provenance, and version chain.
Deployment review is not an overwrite gate: while the originating finding approval
remains current, the incremental workflow may create successive attempts until
`make check` succeeds.

Before each new deployment, the deployer archives the displaced target under
`tmp/inc_runs/<run_id>/history/<change_id>/before/` and stores its path and SHA256 beside
the applied file record. The repair view can restore or delete that archive.
Restore first archives the current target and appends a new `operation=restore`
entry, so rollback does not destroy the version being displaced. Delete removes
only the archived file and retains its hash, deletion time, and user reason.
Deployments created before this history feature correctly show no prior version;
their old bytes cannot be reconstructed from a SHA256. Normal `make clean` and
later incremental runs preserve `tmp/inc_runs/` and legacy `tmp/change_history/`;
recoverable versions are removed only through an explicit version-management action.

New report runs use `contract_version=2`. Their evaluator-specific mandatory
check ids, finding evidence fields, severity, and terminal status are enforced
by `EvaluationJsonReportChecker`. `StaticEvaluationAudit` supplies deterministic
configuration and source evidence without importing generated code.
