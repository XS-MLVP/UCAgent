# AGENTS.md

This file contains repository-level instructions for coding agents working on
UCAgent. It applies to the entire repository unless a more specific AGENTS.md is
added below a subdirectory.

## Project Goal

UCAgent is a Python 3.11+ AI agent for hardware verification. It combines:

- configuration-driven verification workflows;
- stages and stage lifecycle management;
- deterministic checkers that gate stage completion;
- local and MCP-exposed tools;
- runtime Guide_Doc files, output templates, and optional skills;
- UnityChip/toffee tests, coverage, Bug analysis, and waveform evidence.

The main engineering objective is not merely to make an LLM produce output. The
system must prevent incomplete DUT specifications, invalid verification results,
and fabricated evidence from being accepted.

## Repository Map

- `ucagent/verify_agent.py`: top-level agent assembly and runtime initialization.
- `ucagent/cli.py`, `ucagent.py`: installed and source-tree CLI entry points.
- `ucagent/setting.yaml`: global defaults, backends, tools, launch settings, and
  environment-backed defaults.
- `ucagent/util/config.py`: layered config loading, overrides, template handling,
  and the shared `.ucagent/runtime_config.json` snapshot.
- `ucagent/stage/`: `VerifyStage`, `StageManager`, Check/Complete lifecycle, stage
  history, and stage tools.
- `ucagent/checkers/`: deterministic validation and batch-task implementations.
- `ucagent/tools/`: LLM tools, file/test operations, MCP conversion, skills, and
  waveform analysis.
- `ucagent/abackend/`: LangChain and command-line backend adapters.
- `ucagent/server/`, `ucagent/tui/`: master APIs, terminals, web UI, and TUI.
- `ucagent/lang/zh/config/default.yaml`: the main UnityTest workflow, system
  prompts, stage tasks, checker wiring, and stage-local skills.
- `ucagent/lang/zh/doc/Guide_Doc/`: runtime guidance copied into a DUT workspace.
- `ucagent/lang/zh/template/`: files rendered into a DUT workspace.
- `ucagent/lang/zh/skills/`: skills copied to `<workspace>/.ucagent/skills` when
  skill support is enabled.
- `docs/content/`: developer/user documentation for the MkDocs site. This is not
  the same as runtime `Guide_Doc`.
- `tests/`: unit and focused regression tests.
- `examples/`: example DUT inputs and, in some cases, generated verification
  artifacts. Do not treat generated example outputs as canonical source.

## Working Tree Discipline

- Assume the worktree may already contain important user changes. Inspect
  `git status --short` and the relevant diff before editing.
- Never revert, normalize, or reformat unrelated changes. Some files use CRLF and
  some use LF; preserve the existing file's line endings.
- Keep patches scoped by feature. Do not combine prompt rewrites, checker changes,
  server refactors, and unrelated cleanup unless the task requires all of them.
- Do not edit generated `output/`, DUT workspaces, waveform files, `.ucagent`
  checkpoints, or stage-history repositories unless the task explicitly targets
  generated/runtime state.
- Do not run broad destructive Make targets such as `make clean`, `reset_%`, or
  `clean_%` in a shared worktree without explicit authorization. They remove
  outputs, waveforms, checkpoints, and generated workspaces.
- Do not create a commit unless explicitly requested. When requested, group
  commits by coherent feature and use clear English commit messages.

## Configuration Contract

Configuration is loaded in this order:

1. `ucagent/setting.yaml`
2. `~/.ucagent/setting.yaml`
3. `ucagent/lang/<lang>/config/default.yaml`
4. workspace `.ucagent/setting.yaml`
5. the explicitly selected config file, usually `config.yaml`
6. CLI/config overrides

Important rules:

- `$(NAME: default)` is resolved while YAML is loaded. Negated boolean scalars
  such as `not $(IGNORE_X: true)` use `UCAgentConfigLoader`.
- Config lists are replaced as lists; they are not merged item-by-item. A custom
  `stage:` override generally needs the complete intended stage list.
- `{DUT}`, `{OUT}`, `{WORKSPACE}`, and other template values are rendered after
  config loading. Do not confuse template substitution with environment
  substitution.
- Runtime code must consume resolved `agent.cfg`, not re-read an environment
  variable that originally supplied a config default.
- After template resolution, `VerifyAgent` writes the non-secret shared snapshot
  `<workspace>/.ucagent/runtime_config.json`. External scripts and other runtime
  consumers should use `load_runtime_config(workspace)`.
- Keep secrets out of runtime snapshots, prompts, logs, checker results, and test
  fixtures. Never dump the full config because it can contain API keys/tokens.
- When adding a runtime option, define a positive, unambiguous field under
  `runtime_options`, validate its type, persist only if safe, document it, and
  test both enabled and disabled configurations.
- Always parse modified YAML in representative environment combinations. This is
  especially important for booleans, nested stages, Markdown fences, and strings
  containing `{}`.

Current test-fixture contract:

- `runtime_options.need_ref_model: false` -> ordinary DUT tests use `env`.
- `runtime_options.need_ref_model: true` -> ordinary DUT tests use
  `env, ref_model` in that order.
- `runtime_options.mock_components_enabled: true` does not change ordinary DUT
  test signatures.
- independent Mock tests use only `mock_dut` and the
  `test_api_{DUT}_mock_*` naming convention.

## Stage and Checker Lifecycle

`VerifyStage` constructs a checker, injects `cfg`, then calls
`set_workspace(...).set_stage(...)`. `StageManager` is attached later, and the
active stage eventually calls each checker's `on_init()`.

Follow these rules when implementing checkers:

- Keep `__init__` limited to validating/storing constructor parameters and
  creating lightweight helper objects. Do not scan workspace files or derive
  live task state in the constructor.
- Perform real workspace/stage-dependent initialization in `on_init()`. Call
  `super().on_init()` after the subclass has prepared its cached state.
- Do not assume `stage_manager` exists during construction or the initial
  `set_stage` callback.
- `get_template_data()` is a read-only projection of cached state. It must not
  scan files, update lists, advance a batch, write checkpoints, or otherwise
  change behavior. It may be called repeatedly while rendering descriptions.
- `do_check(is_complete=False, **kwargs)` performs live validation and returns
  `(bool, str|dict|list)`. Prefer structured, concise, actionable diagnostics.
- Every overridden `do_check` must have a meaningful docstring. `Checker.__str__`
  asserts that this description exists during stage-info generation.
- A failed checker must explain the exact failing artifact, the relevant current
  batch/item, and the next corrective action. Do not return only an internal
  boolean or a generic "checker failed" message.
- Do not trust LLM-authored progress markers by themselves. Cross-check markers
  against source files, generated artifacts, current configuration, and any
  signed/persisted tool evidence.
- Keep Check and Complete semantics distinct: Check may finish one batch and
  expose the next; Complete succeeds only when all work and final validation are
  complete.
- Export a new checker from `ucagent/checkers/__init__.py` when its short class
  name is referenced by `clss` in YAML.

## Batch Checker Rules

Use `UnityChipBatchTask` for staged batch work rather than implementing a second
checkpoint/progress engine.

- Set `checker.batch_size` before constructing `UnityChipBatchTask`.
- Preserve and reconcile `source_task_list`, `gen_task_list`, `tbd_task_list`,
  and `cmp_task_list`.
- Treat the current source files/documents as ground truth. Checkpoints support
  resume; they do not override changed source data.
- Re-derive source/generated completion state in `on_init()` or `do_check()` as
  appropriate, then use `sync_source_task()` and `sync_gen_task()`.
- Remove or invalidate stale tasks after source changes. Unknown, duplicate, or
  forged progress must fail rather than silently skip work.
- Use `UnityChipBatchTask.do_complete()` for batch transitions and completion
  semantics. It also resets the stage's consecutive-failure counter after a
  successful batch.
- Fail clearly when the source task list is empty because of an invalid path or
  configuration. Do not silently report completion.
- Keep LLM output compact. Summarize missing ranges/items by block and include
  only bounded excerpts; advise reading the source file when the excerpt is
  incomplete.

For functional line mapping specifically:

- `file_list` is the authoritative file set; do not infer or duplicate a parent
  stage's references at runtime.
- Do not pass `Guide_Doc` files into the line-map checker.
- Cover every nonblank physical source line with an FG/FC/CK mapping or a
  reasoned `IGNORE` mapping.
- Use file/line blocks no larger than 100 physical lines and validate progress
  against the actual mapping files.

## Tool and MCP Rules

- Prefer `UCTool` for new LLM-callable tools.
- Give every tool a unique `name`, a precise `description`, and a Pydantic
  `BaseModel` `args_schema` with useful `Field` descriptions.
- MCP conversion requires a `BaseModel` schema and does not support LangChain
  injected arguments. Test local invocation and MCP-schema conversion.
- Export a new built-in tool from `ucagent/tools/__init__.py` if configs should
  refer to it by short name.
- Resolve workspace-relative paths safely. Do not let tool arguments escape the
  configured workspace or bypass read/write directory restrictions.
- Return structured data when the LLM must reuse fields. Include detailed
  diagnostics for lookup failures: searched paths, available candidates,
  likely naming mismatches, prerequisites, and a concrete next call.
- For long calls, use UCTool progress/heartbeat support rather than appearing
  hung. Respect timeout and re-entry behavior.
- If a checker must prove that a tool was really called, persist a verifiable
  receipt or equivalent evidence and validate/replay it. Never accept document
  text as proof of invocation.
- When adding a dependency, update both `pyproject.toml` and `requirements.txt`
  with compatible constraints, then add focused tests for missing dependency,
  empty data, malformed data, and successful use.

## Runtime Docs, Templates, and Skills

These layers form one behavioral contract and often must change together:

1. `ucagent/lang/zh/config/default.yaml` task/system prompts
2. `ucagent/lang/zh/doc/Guide_Doc/*` runtime user guidance
3. `ucagent/lang/zh/template/*` generated-file skeletons
4. `ucagent/lang/zh/skills/*/SKILL.md` and skill scripts
5. checker/parser implementation
6. focused tests

Do not change only one layer when a format or mandatory behavior changes.

### LLM-Facing Content

LLM-facing content includes system/stage/task prompts, rendered stage
descriptions, checker diagnostics, tool descriptions and argument fields, tool
results, runtime `Guide_Doc`, templates, and skill instructions.

- Write from the perspective of the agent executing the current stage. State the
  objective, usable inputs and actions, required artifacts/formats/evidence,
  acceptance criteria, and the concrete next action.
- Do not expose UCAgent architecture or implementation details that do not
  change the LLM's valid next action. Avoid Python class/module names, object
  lifecycle and call order, checker internals, checkpoint/state storage,
  configuration assembly, backend/MCP/server wiring, private data structures,
  and enforcement rationale.
- Preserve public runtime interfaces the LLM must actually use, including tool
  names and arguments, workspace paths, tags and schemas, stage commands,
  constraints, and validation results. Present them as task contracts, not as
  explanations of how UCAgent implements or enforces them.
- Translate internal failures into task-oriented diagnostics: identify the
  affected artifact/input and location, the expected condition, the observed
  problem, and the exact corrective action or next tool call. Do not expose
  stack traces, internal booleans, or call chains unless the text is explicitly
  for developer debugging rather than the stage-running LLM.
- Keep LLM-facing text concise and stage-local. Remove background information
  that cannot influence the current stage's decisions, output, or completion.
- Describe only the current canonical contract. Do not mention superseded
  formats, migrations, backward compatibility, removed arguments, or what older
  releases accepted unless the current task explicitly requires migration work.
  When input has the wrong shape, state the required current structure and the
  exact repair action without teaching the LLM about historical alternatives.

### Shared Runtime Contract

- Tagged Markdown is a machine-readable interface. Treat FG/FC/CK, BG/TC,
  FILE/LINK-BUG, progress markers, and fenced evidence blocks like an API.
- Keep one canonical format instead of accepting several ambiguous variants.
- Keep examples syntactically valid, visually readable in Markdown, and exactly
  consistent with checker expectations.

### Optional Skill Contract

- Skill support is optional. Every workflow and stage must remain executable and
  checker-completable when skills are disabled and when `.ucagent/skills` is
  absent.
- Treat a skill as an acceleration or guidance path, never as the sole source of
  mandatory behavior. The stage prompt, runtime guidance, tool contracts, and
  templates available without skills must still expose every required objective,
  input, output format, evidence rule, and completion criterion.
- Make skill references in task prompts conditional and provide an actionable
  non-skill path using the normally available tools and source files. Do not
  unconditionally instruct the LLM to read a skill, call a skill-only tool, run
  a skill script, or stop because a skill is unavailable.
- Skill-enabled and skill-disabled paths must produce the same canonical
  artifacts and meet the same checker standards. Disabling skills must not skip
  work, weaken evidence, or relax validation.
- Any requirement to invoke a skill or validate skill-use evidence must be
  conditional on the resolved skill setting. It must not block Check or Complete
  when skills are disabled.
- Skill directories require `SKILL.md` with valid `name` and `description`
  frontmatter. Keep a skill concise and put deterministic repeated work in
  `scripts/`.
- Skill scripts execute with the DUT workspace as the current directory. Read
  resolved runtime configuration from `.ucagent/runtime_config.json`; do not
  reinterpret feature environment variables.
- A nonempty `scripts/__init__.py` can install `setup_vstage` hooks. Avoid hidden
  import-time side effects and make hooks idempotent.
- Skills are copied into a workspace at agent initialization. Source changes do
  not automatically update an already-running workspace; restart/recopy before
  diagnosing stale skill behavior.
- For every skill-related workflow change, test both enabled and disabled
  configurations. The disabled case must cover an absent skill directory and
  must verify that rendered prompts, available actions, checker behavior, and
  completion do not depend on skill-only content.

## Verification Domain Invariants

Preserve these established semantics unless the task explicitly changes them:

- Empty test templates intentionally end with
  `assert False, "Not implemented"`. Implemented tests must remove that
  placeholder and use real assertions.
- Validation infrastructure failures (test code, fixtures, API, reference model,
  Mock behavior, reset/timing, dependencies) must be fixed to Pass. They are not
  DUT Bugs.
- A correctly written test that reproducibly exposes a DUT defect must remain
  Fail and be recorded with the required Bug evidence. Do not weaken assertions
  to make it Pass.
- Static candidates use `BG-STATIC-*` only in
  `{DUT}_static_bug_analysis.md`. A dynamically reproduced Bug gets a separate
  non-static BG tag in `{DUT}_bug_analysis.md`.
- Dynamic Bug entries require real WaveInfo evidence for every associated TC.
  Each TC must be immediately followed by a canonical `<WAVEFORM-REF>` link to
  its unique record in the document-level `<WAVEFORM-EVIDENCE>` section. The
  record's fenced `yaml` block must have `waveform_analysis` as its sole
  top-level key, name every associated BG, and contain a verifiable receipt.
- A failed TC has exactly one central waveform record even when it is associated
  with multiple Bugs. The signed signal groups must cover the union of each
  associated BG's `required_signals`.
- A no-Bug result must remain valid without manufacturing waveform evidence.
- Test log cycle values and wavekit steps may differ by zero or several cycles.
  Align evidence by clock occurrence and transaction context; never assume they
  are identical indexes.
- Keep Bug-specific conclusions in the BG entry and the matching central
  `bug_evidence` item. Keep shared receipt, viewer, alignment, and signals only
  in the TC's central waveform record.

## Code Style and Scope

- Match nearby style; the repository is not uniformly autoformatted.
- Use UTF-8. Chinese is expected in runtime prompts and Guide_Doc files. Keep
  Python identifiers and implementation comments concise and conventional.
- Prefer standard parsers and structured data over ad hoc string replacement.
- Add comments only for non-obvious lifecycle, security, or parsing logic.
- Avoid broad abstractions for a single checker/tool unless they clearly reduce
  duplication or establish a reusable contract.
- Preserve public constructor arguments and defaults unless compatibility is
  explicitly out of scope.
- Keep user-facing checker/tool errors concise enough for an LLM context window.
  Do not emit every uncovered line when a merged range conveys the same result.

## Testing Strategy

Start with the smallest tests that cover the changed behavior, then broaden by
risk. Typical commands:

```bash
python3 -m py_compile path/to/changed.py tests/test_changed_area.py
pytest -q tests/test_changed_area.py
git diff --check
```

Useful focused suites:

- config/runtime prompts: `tests/test_config_loader.py`,
  `tests/test_waveform_prompt_config.py`,
  `tests/test_unitytest_skill_runtime_options.py`
- stages and batches: `tests/test_stage_manager.py`,
  `tests/test_file_linemap_batch_checker.py`, and the relevant
  `tests/test_unity_*_checker.py`
- tools/MCP/waveforms: `tests/test_waveform_tool.py`,
  `tests/test_mcp_waveinfo_visibility.py`, `tests/test_mcps.py`
- Bug formats/checkers: `tests/test_toffee_report_waveform_analysis.py`,
  `tests/test_toffee_report_mark_diagnostics.py`,
  `tests/test_dynamic_bug_record_scripts.py`, `tests/test_static_bug.py`
- server/TUI/backend changes: the matching `tests/test_api_*`,
  `tests/test_messages_panel*`, `tests/test_cmdline_backend.py`, or
  `tests/test_verify_pdb_runtime.py`

Testing caveats:

- Do not use bare `pytest` as the only completion gate. It also collects tests
  under `examples/` and unrendered template files, causing module-name collisions,
  missing generated DUT imports, and template syntax errors.
- Some historical tests depend on absent generated examples, optional packages,
  or older lifecycle/line-number behavior. Re-check the current baseline before
  treating a broad-suite failure as a regression.
- A baseline issue does not excuse failures in tests directly related to the
  files you changed. Report unrelated broad-suite failures explicitly rather
  than hiding or "fixing" them outside scope.
- Use `tmp_path`/temporary workspaces for tests. Do not rely on or mutate the
  repository's `output/` directory.
- For documentation changes, run `mkdocs build -f docs/mkdocs.yml --strict` when
  documentation dependencies are installed.
- For YAML workflow changes, load the file under every affected boolean/config
  combination and verify that checker classes instantiate with the supplied
  arguments.

## Definition of Done

Before handing off a change:

- confirm behavior against the actual surrounding implementation, not only docs;
- synchronize prompts, Guide_Doc, templates, skills, checkers, and tests where
  the contract crosses those layers;
- verify config values come from resolved cfg at runtime;
- run focused tests and proportionate regression tests;
- run Python compilation and `git diff --check`;
- inspect the final diff for unrelated churn, secrets, generated files, and
  accidental line-ending changes;
- state what passed and what could not be run, including exact residual risks;
- leave the worktree uncommitted unless the user explicitly requested commits.
