
# Formal execution operations

The Formal plugin exposes `RunFormal` for managed proof execution and evidence.
Structured task authoring is the optional `ext/formal/data` Skill, not an
independent UCTool. It executes through the existing `RunSkillScript` interface;
no framework Skill execution behavior is changed.

The default stages declare no Skill requirements. When the data Skill is useful,
load it once using ListSkill and ReadTextFile, then call the existing command
triples, for example `commands:[["ext/formal/data","formal_data.py","inspect planning"]]`.
For a batch update, write a structured request file under the output directory,
then invoke `update --request-file formal_test/data_update.json`. Requests contain
`section`, `expected_sha256`, and exactly one of `data` or `bodies`; no inline
shell JSON or field-by-field set sequence is required.

`inspect` is read-only. `prepare analysis` / `prepare bugs` explicitly validates
current stopped proof evidence, coordinates exact queues, and returns a
`ready_update` request with original witness context. The Skill binds verified
references automatically. It does not prove the intended specification semantics
or justify a Bug classification without review.

With Skills disabled or absent, ordinary file tools maintain the same canonical
YAML, Check coordinates current analysis/Bug entries, and RunFormal evidence
supplies current exact references. The same acceptance gates apply. Neither a
missing Skill nor a disabled Skill directory is a reason to skip work.

Shared roots use an explicit root_cause_id; evidence remains property-specific.
Severe-Bug summaries derive from accepted observations and roots, not a separately
authored summary list. Stage journaling remains mandatory; Complete validates
and advances, while Check is used for actual diagnostics. See
`src/formal/Guide_Doc/formal_data.md` for full enabled/disabled examples.

Queueing, timing, report collection, and process cleanup are automatic.
`status` requests up to 300 seconds by default and is capped below the resolved
tool-call timeout with return headroom; use `wait_s=0` for an immediate query.
The execution and original-evidence contract is in
`src/formal/Guide_Doc/formal_execution.md`.

## Effective interface preflight

The Formal plugin requires pyslang 12.1.x for parser-backed interface preparation.
The parser and generated Tcl use the same deterministic direct DUT source order:
`.v` files followed by `.sv` files, each sorted. No BasicInfo prose is consumed as
an executable parameter default. The actual selected module's public scalar
integral parameter defaults are elaborated; `spec.parameters` supplies only
explicit public overrides. Derived defaults are recomputed after overrides,
and zero is a valid explicit value. Unknown/local/type/non-integral or unresolved
bindings are rejected rather than guessed.

The generated verification ports have concrete resolved dimensions and
signedness. The original DUT receives only explicit overrides, preserving its
own default dependency relationships; the checker receives effective constants
needed by SVA. Read-only `inspect spec` exposes effective interface data from the
same preflight. Missing bindings and unsupported compilation context must identify
the input and `spec.parameters`, not suggest editing descriptive `basic_info`.
Preflight does not modify the task's parameter map or source RTL.

The initial supported context is direct source files and scalar packed integral
ports. Preprocessor/include contexts or richer type/interface constructs that
cannot be matched safely are rejected explicitly; operators must provide a
supported consistent compilation context instead of relying on silent regex
fallbacks. This is not a full SystemVerilog project build system.

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
not evidence of a completed proof. `TrivF` is retained as `TRIVIALLY_FALSE`,
a distinct static/constant failure. `TrivT` reason metadata is retained for review;
a direct identity proof must not automatically be labeled overconstraint. Unknown
result spellings become property-specific `NEEDS_OPERATOR` diagnostics while
other independent work can finish; never rewrite a verification objective merely
to avoid a tool-result parser error.

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
machine proof counts and gaps separately from agent-authored conclusions. Severe-Bug summaries are derived from accepted Bug observations and shared roots; authors do not maintain a second severe_bugs structure.

Machine artifacts are not editable progress checklists. Raw evidence lives in
run-scoped attempt logs; the shared `tests/avis.log` is only an aggregate result
projection, not the original counterexample transcript. Use the run report and
attempt logs when analyzing a counterexample.

## Compact data review and original observations

The data Skill returns only missing required author fields by default. Full
planning/basic_info/summary schemas remain available with `inspect <section>
--schema`; optional render defaults are not prefilled into every request.
Clock applicability must be explicitly reviewed: an unknown count is null,
whereas zero means a confirmed clockless design.

`prepare` filters completed reviews and reports total/pending/completed counts.
Inspection remains read-only. Evidence metadata is attached by the shared data
backend. The Skill still runs exclusively through the unchanged RunSkillScript
framework; no additional data tool is registered.

RunFormal now hashes the original VCD alongside the tool report and generated
testbench. The existing wavekit VcdReader provides bounded top-scope samples at
the last recorded timestamp, preserving widths, X/Z masks, omitted signal counts,
and unavailable states. This sample is not necessarily a failure cycle or a
full replay. Bug trigger/actual fields are deterministic projections of this
original evidence and are not authored through the data Skill; raw YAML edits
are rejected at report delivery. Reference semantics, root-cause interpretation,
and any expected-value calculation still require independent review. No
DUT-specific arithmetic oracle is supplied.

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
