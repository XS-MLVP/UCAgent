
# Second-Development Testing and Regression for Parent Workflows

This guide directs second-developers to write, select, and run tests for the current Workflow Builder parent workflow. Since the model processes in Workflow Builder are time-consuming, parent code modifications should first be identified by deterministic regression tests for protocol errors, followed by a small number of real business runs to verify parent Agent behavior and generated artifacts. Complete generation should not be treated as the most basic unit test.

## Second-Development Goals

Developers should be able to select the minimum regression based on the modified responsibility domain, establish fixtures that fail first then pass for defects, integrate new scripts into the regression Makefile, and record existing failures outside the scope. The testing focus is to prove the parent module's inputs, outputs, boundaries, and compatibility, not to achieve a green return code by manually fixing the test workspace.

## Parent Workflow Modification Entry Points

The test entry points are the root `make regression` and `regression/Makefile`. Scripts directly invoke the parent generator or evaluation control core, checking artifacts within a temporary workspace. Tests involving UCAgent import must use the project venv; real process validation requires creating an independent business root to observe via supervision strategy whether the parent workflow can generate correct results autonomously.

## Regression Entry

```bash
cd ~/work/UCAgent/examples/workflow_builder
make regression
```

Scripts in `regression/` cover design construction, delivery contracts, boundary writing, evaluation splitting, incremental control, console, and generator behavior. Developers should run the most relevant scripts first based on the modification scope, then run the total entry point.

## Layered Testing

1. **Syntax Tests**: Python compilation, YAML/JSON parsing, Makefile dry run.
2. **Unit Tests**: Pure functions, schema validation, path handling, state transitions, and serialization.
3. **Component Regression**: Run a specific generator with fixed test_data and check artifacts.
4. **Protocol Regression**: Consistency between tools, Checker, GuideDoc, config, and environment facilities.
5. **Real Workspace Validation**: Select a small business to run key stages, observing retries, latency, and final artifacts.

## Test Data Principles

Fixtures should be small, stable, and contain a single error. Do not rely on network, model random output, current username, or absolute paths. Negative samples should break the target rule only once. When external commands are required, use a whitelist and detectable skip conditions, distinguishing "not installed" from "test failure" in reports.

## Documentation Regression

Documentation checks should verify the existence of required files, Markdown relative links and images, necessary titles and commands. It cannot merely count words, nor count repeated code block content as proof of detail. Make targets in QuickStart must exist in the current Makefile.

## Minimum Test Set After Modifications

| Modified Area | Minimum Validation |
| --- | --- |
| Makefile or setup.py | Config dry-run, check, variable coverage, Make help |
| Tool Generator | Tool component regression, registration test, total regression |
| Checker Generator | Instantiation, positive/negative fixtures, stage registration, total regression |
| GuideDoc/config | YAML parsing, reference existence, stage check regression |
| Evaluation Control | Report CRUD, aggregation, approval status, permission boundaries |
| Incremental Deployment | Run isolation, candidate copy, backup, atomic replacement, recovery |
| Console | API test, structure edit, filter, delete, port conflict |

## Real-Run Acceptance

During real-time execution, record the start/end of each stage, failure count, Checker messages, and artifact changes. If a stage is slow, first confirm if it is still generating valid tool calls; only modify rules if a parent workflow issue is confirmed. The supervision Agent should not directly write sub-workflow artifacts, otherwise the run result loses its verification value.

After completion, check `git diff` to ensure workspace artifacts, `.ucagent` history, `tmp/`, local configurations, or browser profiles are not committed to the parent repository.

## Regression Makefile Code Analysis and Structure

The `regression/Makefile` defines independent targets for each type of protocol test, which are then aggregated by `all`. The root Makefile's `regression` target explicitly passes the UCAgent virtual environment Python, avoiding inconsistencies between system Python versions and dependencies and the project.

```make
all: contract stability checker_descriptions requirement_templates \
     living_plan write_boundaries evaluation_split review_ui \
     documentation environment_setup

contract:
	cd $(ROOT) && PYTHONPATH="..." $(PYTHON) regression/run_delivery_contract_regression.py
```

Each target runs from the Workflow Builder root, ensuring relative test_data and module paths are consistent. New regression scripts must be added to `.PHONY` and `all`; otherwise, developers running only `make regression` will not execute them. Scripts depending on UCAgent modules must use the passed venv Python; pure documentation scripts can use the same interpreter for consistency.

## Delivery Contract Regression

`run_delivery_contract_regression.py` is the largest deterministic test. It constructs workflow build data, generates a complete workflow, and checks fixed deliverables, Make targets, config, environment, documentation, tools, Checker, and run contracts. It is suitable for discovering new templates that break the overall structure, but with many assertions; when failing, locate the specific contract rather than blindly updating expected strings.

Currently, this script has one existing assertion requiring the initial task to include "Prohibit calling non-existent ListFiles". If source rules have changed but the test is not synchronized, review separately whether it is an implementation regression or an outdated assertion. This round of documentation expansion only records it without modifying parent task semantics.

## Stability and Living Plan Regression

`run_builder_stability_regression.py` verifies repeated builds, existing file policies, and generation result stability. For tool generation states based on hashes, the first and second runs should produce interpretable created/skipped results, not unconditional rewrites every time.

`run_living_plan_regression.py` verifies implementation plan stage markers, append behavior, and protection of preceding content. New stage names or marker syntax must include corresponding fixtures to ensure subsequent stages cannot overwrite preceding stage "issues and handling".

## Checker and Requirements Regression

`run_checker_description_regression.py` generates a Checker, imports the class, and checks description/docstring, capable of discovering issues where "source exists but UCAgent reports No description". Running it must use the project virtual environment; otherwise, system Python may fail due to `typing.NotRequired` or dependency versions, which is a test environment error, not a Checker business failure.

`run_requirement_template_contract_regression.py` verifies that user requirement templates can express reusable templates, tools, Checkers, environments, and documentation requirements. When modifying guide templates or manifest schemas, add positive examples for new fields and negative examples for missing fields.

## Write Boundary and Evaluation Split Regression

`run_write_boundary_regression.py` checks workspace initialization, history permission recovery, tmp cleanup, and prohibition of out-of-bounds writes. When adding cleanup logic, prove it will not delete `eval/`, `res/`, `input/`, the current incremental run, or change history.

`run_evaluation_split_regression.py` verifies responsibilities of tools/checkers/flow/env, JSON store, approvals, incremental runs, candidate deployment, and report aggregation. It should not start expensive real model processes but use fixed workspaces and tools to directly invoke control logic.

## Console Regression Code Patterns

`run_review_ui_regression.py` starts a local service on a temporary port, checking meta, state, design files, structure editing, approvals, suggestions, history recovery, and deletion via HTTP requests. Tests also actively request symbolic links and `../` out-of-bounds paths, expecting a 400 response.

```python
response = request("GET", "/api/design-files/workflow%2F..%2Feval%2Fsummary.json")
assert response.status == 400
```

Console tests should close the server and browser profile upon exit. If a lock in tmp is deleted by browser concurrency, the cleaner must tolerate `FileNotFoundError`; however, if service threads are not stopped and ports are still listening, it must fail.

## How to Write Single-Variable Fixtures

First construct a minimal legal baseline, then copy and only change the target field. For example, when testing that reference cannot be a directory, the valid spec uses `reports/result.json`, and the invalid spec changes only it to `reports/`. Do not simultaneously delete stage names, change templates incorrectly, and add absolute paths, as failures may stem from any rule.

Each negative test must assert a stable error code or key field, not just assert "an exception was raised". Positive tests must also check actual file content, registration, or hashes, not just that the function did not raise an error.

Source code pattern: Scripts like `regression/run_write_boundary_regression.py` use temporary workspaces, explicit calls, and assertions.

```python
with tempfile.TemporaryDirectory() as temporary:
    workspace = Path(temporary) / "workspace"
    workspace.mkdir()
    result = operation(workspace)
    assert result["ok"] is True
    assert (workspace / "expected/file.json").is_file()
    assert not (Path(temporary) / "escaped.json").exists()
```

Temporary directories isolate machine state and clean up upon completion; tests assert both files that should be created and files that should not be created to prove write boundaries. If failure artifacts need to be retained for debugging, a directory can be retained via an explicit environment variable, but regression should not pollute the repository by default.

## Tool Test Design

Tools require at least spec validation, source compile/import, parameter models, normal calls, boundary calls, failure structures, path escape, and repeated runs. When involving external programs, use controllable small commands, timeouts, and temporary cwd. Network-acquired tools should separate the downloader from business parsing, testing with local response fixtures without relying on the public internet in regression.

For generator tests, also verify config registration and generation state. After modifying existing files, generate again, asserting that preserve/replace policies match the design. When multiple tools are batch-generated, check that registration does not lose items or have duplicates.

## Checker Test Design

Each business rule in Checker must have positive and single negative evidence. First test class importability, inheritance of Checker, non-empty description/docstring, and constructor parameter matching, then call `check`. Exceptional inputs should return `(False, evidence)` instead of causing the runner to crash.

Command Checker tests whitelist rejection, expected return codes, unexpected return codes, and timeouts. File Checker tests relative paths, absolute paths, `..`, symbolic links, and missing files. Structure Checker tests top-level types, field types, missing fields, and boundary values.

## GuideDoc and config Test Design

GuideDoc tests explicit section IDs, old title mappings, missing sections, duplicate sections, markers, valid content, and registration. Code blocks in user documentation should not be counted towards content length. After generation, read the Markdown to confirm commands and paths match the actual Makefile/config.

Config tests unknown placeholders, double braces, loop coverage, parent process path leakage, directory file contract, future references, unknown Checkers, parameter mismatches, and stage handoffs. YAML parsing is just the first layer; the final step must also execute static config checker.

## Incremental and Version Management Test Design

Initialize eval files and two formal files in a temporary workspace, create approval, start run, stage candidate, and deploy. Assert formal hash, backup hash, applied changes, run ID, and approval mapping. Then simulate a second file replacement failure, confirming the first rolls back. Finally, test recovery saves the current version, while deletion removes only the target record.

Post-deployment regression failure state machine tests must prove the process does not stall in pending or repeat the same command. Use fixed failure/success scripts and attempt counts to simulate two fixes.

## Complete Example from Defect to Regression

Problem: config generator allows `reference_files: [docs/]`. First write a minimal invalid spec and confirm old code passes the error; add specific file judgment in `_file_contract_errors()`; assert error includes field location; then add valid file paths to ensure no false positives. Subsequently run config component, delivery contract, evaluation split, and real generation workflow `make check`.

Documentation synchronization explains why directories cannot be references, how to list deterministically existing files, and why unknown future files cannot be referenced in advance. This protects the regression mechanism, guides the Agent, and evaluation rules can still discover historical artifacts.

## Performance and Authenticity

Deterministic regression should complete within seconds without invoking models. Real business tests are used to observe whether the Agent understands the task, whether it fails continuously, and product quality; the two cannot replace each other. To speed up real processes, batch generation followed by checks, limit reads, and parallel independent tools can be used, but results cannot be manually generated by the supervisor.

Test reports must record commands, interpreters, return codes, and known failures. If full regression stops early due to existing issues, run remaining targets separately and explicitly state which pass; do not vaguely write "regression failed" or "all passed".

## Regression Extension Rules

When adding new components, prioritize adding tests to existing responsibility targets; only create new targets when forming independent protocols, runtime costs, or dependency boundaries. New targets must enter `all`, use the passed interpreter, isolate workspaces, and be documented in README explaining the protected behavior. When deleting features, simultaneously delete assertions for lost objects; do not let outdated tests force implementations to retain meaningless text.

## Complete Directory of Existing Regression Scripts

The following table is based on actual files `regression/run_*regression.py`. Secondary developers should first place defects into the script with the closest responsibility; only create new scripts when attribution is impossible.

| Script | Protected Parent Workflow Contract | Extended Methods |
| --- | --- | --- |
| `run_builder_runtime_directory_regression.py` | Sub-workflow runtime directories created by Builder, Python package/import skeleton, and basic path ownership | When adding fixed runtime directories or packages, build and import real generation classes in temporary workspace, not just check filenames. |
| `run_builder_stability_regression.py` | Command limits, plan appending, GuideDoc contract, Tool generation safety, and repeated build stability | For modifications to preserve/replace, hashes, paths, or detail algorithms, add first/second/file drift comparison groups. |
| `run_checker_description_regression.py` | Generated Checker class descriptions, method docstrings, imports, and basic runtime protocols | When adding new renderers/rule types, generate and import that type to prevent runtime failures like `No description provided`. |
| `run_delivery_contract_regression.py` | Broad delivery contracts from central design to complete sub-workflows: skeleton, config, Tool, Checker, GuideDoc, docs, Make, and migration | Only add true cross-component invariants; single-module details go into component scripts to avoid stale prompt strings becoming pseudo-contracts. |
| `run_documentation_regression.py` | This `docs/` information architecture, links/images, development documentation detail, source analysis, and dynamic component lists | New documents add REQUIRED; new stages/UCTool/Checker/GuideDoc/regression should pass dynamic inventory requirements corresponding to development document class or file names. |
| `run_environment_setup_regression.py` | Workflow Builder root `setup.py`, `.workflow_builder/local.mk`, interactive/non-interactive config, command line overrides, and secret boundaries | Test defaults, persistence, show/check, invalid values, and old config compatibility for each new environment field. |
| `run_evaluation_split_regression.py` | Five evaluation splits, JSON store, approval freshness, inc run isolation, candidate, deploy, backup recovery, and report aggregation | New JSON types, approval actions, state transitions, or deploy mappings go here first; must assert persisted results and file hashes. |
| `run_living_plan_regression.py` | `workflow_implementation_plan.md` stage markers, required sections, appending idempotency, and non-overlapping predecessors | New stages or plan sections must have normal appending, same-stage retries, missing markers, duplicate markers, and predecessor coverage negative examples. |
| `run_requirement_template_contract_regression.py` | Requirements manifest/input guide templates' expressiveness for Tool, Checker, environment, documentation, templates, and requirement tracking | New requirement categories add positive minimal mappings and single-field missing negative examples; do not treat a business name as a generic required item. |
| `run_review_ui_regression.py` | Console HTTP API, report filtering/approval/suggestions/deletion, design reading/editing, workflow tree, progress, history recovery/deletion, and path safety | Frontend changes cannot only test DOM; read JSON/YAML/target files after API requests, covering revision conflicts and out-of-bounds paths 400. |
| `run_write_boundary_regression.py` | Parent Agent, evaluation, incremental, history permission guardianship, and `tmp/` cleanup writable scope | New tools' writable roots or cleanup rules must add positive examples and negative examples for `..`, absolute paths, symbolic links, and unrelated directories. |

## Current Regression Makefile and Explicit Execution

The `all` target in `regression/Makefile` currently aggregates contracts, stability, checker descriptions, requirement templates, living plans, write boundaries, evaluation splits, review UI, documentation, and environment setup. During secondary development, do not assume scripts in the directory are executed by `make regression`; `run_builder_runtime_directory_regression.py` must confirm integration into the current Makefile. If not integrated, run explicitly:

```bash
PYTHONPATH="$(cd ../.. && pwd):${PYTHONPATH:-}" \
  python regression/run_builder_runtime_directory_regression.py
```

If a script is a mandatory delivery gate, correct modification is adding the target to `regression/Makefile` and including it in `all`, while updating this list; it should not rely solely on documentation telling users to manually run an extra command. For expensive, network/model-dependent, or hardware-specific tests, retain explicit targets and clearly annotate why they do not enter deterministic `all`.

## New Regression Code Pattern

Each script uses `tempfile.TemporaryDirectory()` or equivalent isolation, creates real artifacts via public core/UCTool, then reads back files to assert. The structure below is the minimal pattern; actual scripts should make specific assertions on error codes and persisted states:

```python
with tempfile.TemporaryDirectory() as temporary:
    workspace = Path(temporary)
    create_valid_baseline(workspace)
    report = call_public_core(workspace)
    assert report.ok
    assert (workspace / "expected/file.yaml").is_file()

    break_exactly_one_rule(workspace)
    with pytest.raises(ExpectedContractError, match="STABLE-CODE"):
        call_public_core(workspace)
```

If the project does not use pytest, maintain the existing script's pure `assert`/`main()` style; do not introduce a new test framework for a single case. Subprocesses must pass argument arrays, cwd, timeout, text/capture_output, assert return codes, and retain limited stdout/stderr in failure messages. Threads, HTTP servers, or browser processes must be closed in `finally`, leaving no ports or profile locks.

## Secondary Development Acceptance Order

1. First run `py_compile` and YAML/JSON parsing for the modified module to exclude low-cost syntax failures.
2. Run one to three closest responsibility regression scripts from the table above, confirming new negative examples fail old implementations and pass new ones.
3. Run `make regression`; if known failures cause `all` to terminate early, record precise assertions and run subsequent targets separately.
4. Generate a new, controlled-scale business workflow, using supervision strategy to observe failure counts, product timestamps, and context compression, without generating sub-products for the Agent.
5. Run `make check` on the generated sub-workflow, then select corresponding evaluation and incremental loops to confirm parent modifications do not merely pass static regressions.

## Continue Reading

After completing the parent workflow modification, developers also need to know "which components in the generated child workflows should be continued in development and how." Please continue reading the [Workflow Product Secondary Development Guide](07_generated_workflow_development.md).
