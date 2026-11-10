
# Formal execution operations

The Formal plugin exposes `RunFormal` locally and over MCP. An agent implements
properties in the task YAML, calls `RunFormal(action="run")`, inspects `status`
and `Check`, and only supplies analysis when a property remains unresolved.
Queueing, timing, report collection, process cleanup, and evidence projection are
automatic. `status` waits up to 300 seconds by default for a new checkpoint or
completion, with normal UCTool heartbeat support; use `wait_s=0` for an immediate
query or configure the call argument up to 1200 seconds. Runtime task instructions are in
`src/formal/Guide_Doc/formal_execution.md`.

## Configuration

Override the resolved workflow configuration, for example:

```yaml
runtime_options:
  formal_execution:
    first_pass_budget_s: 300
    analysis_threshold_s: 1200
    max_active_workers: 2
    slow_queue_max_workers: 1
    setup_timeout_s: 120
    stop_grace_s: 10
    max_review_rounds: 3
    property_cumulative_budget_s: 3600
```

All fields are positive integers. The analysis threshold must exceed the first
turn, the cumulative budget must cover the analysis threshold, and slow workers
cannot exceed active workers. Configuration is read from resolved `cfg`, not
feature environment variables.

- **First turn:** each property is selected explicitly in an independent
  FormalMC process, retaining the original assumptions. Untouched properties
  take priority over slow retries. A long property cannot create a whole-batch
  barrier; even a one-worker setup rotates after the first turn.
- **Slow turn:** an unresolved property receives the remaining round budget,
  normally about 900 seconds after its first 300 seconds. Slow occupancy is
  limited while first-turn work is active. Once the initial queue is drained,
  slow work can borrow idle capacity. This is finite-batch first-turn priority,
  not a permanently reserved slow slot.
- **Reviewed retry:** `review` with `disposition="retry"` and a reason/next action
  grants one uninterrupted turn of up to the analysis threshold, constrained by
  the remaining cumulative budget. The initial round counts toward the round
  limit. Attempts and previous decisions are retained.
- **Deferral:** `defer` is allowed only for unresolved properties whose proof
  turns ended, not failed compilation or crashed workers. It records a gap and
  a reactivation condition; it never changes `UNPROVEN` to a proved result.

The controller emits batch-wall-clock snapshots at the configured 300/1200
second checkpoints, plus property-completion and final snapshots. A property
waiting in a queue is not timed out by a batch checkpoint. Solve duration is
measured at Tcl proof boundaries; preparation and waiting are separate. Tool
reported time is retained separately because it can represent CPU rather than
wall time. One-second engine timeout granularity, scheduling, and termination
can cause small budget overruns; actual durations are recorded rather than
clamped to the requested limit.

## FormalMC behavior and limits

The commands and table formats were checked against FormalMC 2025.12 using small
licensed designs. The implementation uses exact `set_opt -timeout`, explicit
`prove <property>`, typed `show_prop -only_assert`/`-only_cover`, and final
`show_prop -time -engine -reason` reports. `Undet` and `NotRun` are not success.
An error can be printed even when the process exits zero, so exit code alone is
not evidence of a completed proof.

Each turn starts a fresh process and re-reads frozen input files. It does **not**
resume a solver's internal search: 5+15 minutes of independent attempts is not a
continuous 20-minute proof. For a target needing a longer uninterrupted search,
review it and request a bounded retry. Although the tool provides background
proof and save/load session commands, no search-continuation guarantee is made.
Compilation is repeated, and concurrent processes consume additional memory and
may consume additional licenses. Start conservatively with one or two workers;
do not combine large process concurrency with unrestricted engine parallelism.

This implementation targets Linux, using process birth identities and isolated
process groups. Cancellation is asynchronous. Recovery after a controller crash
is performed on the next status/check request, using recorded owned process
identities. A hard kill in the tiny interval between spawning and recording a
child cannot be made fully atomic without an external process supervisor; an
operator should inspect remaining tool processes after an abrupt host failure.
No automatic re-execution is triggered by `Check` or `Complete`.

## Records and correctness gates

Each immutable-input run is kept under `{OUT}/formal_runs/<run_id>/`:

```text
state.json
report.md
controller.log
inputs/
inventory/
attempts/
snapshots/
```

The current pointer is `{OUT}/formal_runs/current.json`. The controller survives
a tool-call return; restarting an agent does not intentionally duplicate the
same run. Inputs, effective budgets, semantic YAML fields, and executable
identity contribute to the fingerprint. Changing analysis or summary prose does
not invalidate proof evidence. Changing RTL, generated sources, spec,
constraints, or configuration requires a new run. All results are conservatively
invalidated together; fine-grained dependency caching is not implemented.

`Check` cross-checks inventory, recorded property results, and report hashes.
Only current stopped results are projected into task analysis data. Coverage
must refer to the current run's inventory report; an old projected fanin report
cannot authorize coverage for a newer run. A deferred run can finish its review
stage, but the final summary must include the literal `UNPROVEN` and renders
machine proof counts and gaps separately from agent-authored conclusions.

Machine artifacts are not editable progress checklists. Raw evidence lives in
run-scoped attempt logs; the shared `tests/avis.log` is only an aggregate result
projection, not the original counterexample transcript. Use the run report and
attempt logs when analyzing a counterexample.

## Verification

Run focused tests without a license:

```bash
python3 -m pytest -q ucagent/plugins/Formal/tests
```

Enable the short real-tool smoke test when FormalMC and a license are available:

```bash
FORMALMC_INTEGRATION=1 python3 -m pytest -q ucagent/plugins/Formal/tests
```

The scheduler tests use accelerated one/two-second budgets. They cover a slow
property beside quick properties, single-slot rotation, typed covers, unknown
results, partial failure, review and retry limits, cancellation, crash recovery,
stale inputs, evidence tampering, MCP schemas, skill-independent generation, and
write-policy boundaries. They do not benchmark production-scale proof
convergence or exercise a real 20-minute workload.
