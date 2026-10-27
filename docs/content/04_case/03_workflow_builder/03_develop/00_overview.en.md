
# Workflow Builder Parent Workflow Secondary Development Overview

This set of documents is intended for users preparing to perform secondary development on the parent workflow located in `examples/workflow_builder/`. The goal is to assist developers in modifying the parent workflow stages, generators, evaluation control, incremental deployment, console, and delivery contracts, rather than guiding how a specific sub-workflow Agent should complete business tasks. The generated workflows, business Tools, business Checkers, and GuideDoc mentioned in this text are output objects of the parent workflow code, used to explain the impact of a single parent code modification.

## Secondary Development Goals

After reading this set of documents, developers should be able to locate the actual modification entry point within the parent workflow from a requirement or defect, understand module interfaces and call relationships, design backward-compatible data structures, supplement deterministic regression, and verify generation effects using independent business validation. A single business generation failure may originate from the requirement, parent stage description, GuideDoc, generator, Checker, UCAgent runtime, or external services; parent code should only be modified after confirming the responsibility domain. Modifying the UCAgent core or manually supplementing sub-artifacts to mask problems is not acceptable.

We do not repeat the daily startup steps found in Usage, nor do we treat stage prompts as developer tutorials. Developers are concerned with: which YAML defines the stage, which UCTool exposes the tool, how to write core functions to files, which schemas and regressions must be synchronized, and how to ensure any future business obtains the fix.

## Reading Order

1. [Workflow Introduction](01_workflow.md): Understand the data flow of construction, evaluation, incremental, and console.
2. [Tool Introduction](02_tools.md): Understand tool registration, invocation, return structures, and write boundaries.
3. [Checker Introduction](03_checkers.md): Understand stage acceptance, parameter injection, and evidence semantics.
4. [GuideDoc Introduction](04_guide_docs.md): Understand GuideDoc templates, stage FAQs, and minimal examples.
5. [Evaluation and Incremental Control](05_evaluation_and_incremental_control.md): Understand approval, candidates, deployment, and version history.
6. [Testing and Regression](06_testing.md): Determine which deterministic checks must run after modification.
7. [Secondary Development Guide for Workflow Artifacts](07_generated_workflow_development.md): Understand components, ownership, extension order, and criteria for judging whether to feed back to the parent generator.

## Parent Workflow Modification Entry Points

Secondary development typically begins with one of four entry points. Process behavior modifications involve `config.yaml`, `inc.yaml`, `eval_*.yaml`, and their `Guide_Doc/` directories; product generation capability modifications involve `tools/workflow_builder/` and the four generators; evaluation, approval, deployment, or UI modifications involve `tools/workflow_evaluation_control/`; and runtime and environment entry modifications involve the root Makefile and setup. After determining the entry point, read the corresponding source code analysis, do not edit a historical `workspace_x/workflow/` first.

## Primary Source Code Areas

| Area | Responsibility |
| --- | --- |
| `tools/workflow_builder/` | Read construction design, create skeleton, environment facilities, configuration, and inline Checkers |
| `tools/workflow_tool_generator/` | Generate and register tools according to tool spec |
| `tools/workflow_checker_generator/` | Generate Checker source code, fixtures, and registration information |
| `tools/workflow_config_generator/` | Generate main configuration and incremental configuration, inject stage contracts |
| `tools/workflow_guidedoc_generator/` | Generate and register GuideDoc |
| `tools/workflow_evaluation_control/` | Structured reports, approval, incremental run, deployment history, and console |
| `Guide_Doc/` | Parent workflow stage execution rules, FAQs, and evaluation rules |
| `regression/` | Model-independent protocols, boundaries, and regression tests |

## Development Boundaries

- Prioritize modifying the parent workflow within `examples/workflow_builder/`; do not modify the UCAgent core to mask generator issues.
- Business-specific filenames cannot be written to generic GuideDoc unless it is explicitly marked as an example.
- New tools or Checkers must synchronize updates to spec, registration, tests, configuration, and generated documentation.
- `reference_files` and `output_files` can only list files, not directories; referenced files must exist before execution in that stage.
- All temporary files enter the workspace `tmp/`; evaluation reports enter `eval/`; user expertise enters `res/`.
- Long documents should use indexing and on-demand reading strategies; do not require the Agent to read all materials in full every round just to "establish understanding."

## Problem Statement Before Modification

It is recommended to clearly write observable symptoms, minimal reproduction commands, failed stages, Checker messages, related artifacts, and expected behavior. For performance issues, also record stage start time, actual tool invocations, whether artifact timestamps have changed, and whether context compression has occurred. This allows distinguishing real computation, model waiting, and stateless idle loops.

## Completion Definition

Development modification is only considered complete when all the following conditions are met: code implementation and documentation are consistent; target regressions pass; no other generators are broken; new fields have a compatibility strategy; generated artifacts can be accepted by `make check`; and during real workspace verification, no sub-workflow artifacts are hand-written by the parent Agent.

## Entry Map from Command to Source Code

Developers must first clarify which layer of entry they are running. The `run`, `run_eval_*`, and `run_inc` commands in the root Makefile all start UCAgent within the business construction workspace, but the loaded configurations come respectively from `config.yaml` in the Workflow Builder root directory, evaluation configuration, and `inc.yaml`. The Makefile is responsible for preparing the workspace, copying public inputs, selecting the output root, setting `PYTHONPATH`, starting the permission daemon, and passing TUI/loop parameters. UCAgent then invokes the UCTools registered in this directory according to the stages in the configuration; these tools then enter the various generators or evaluation control modules.

Key entry points can be located using the table below:

| User Action | Make Entry | Python Entry | Main Persistence Result |
| --- | --- | --- | --- |
| Generate business workflow | `run` | `workflow_builder.core.build_workflow` and respective UCTools | `wfgen/`, `workflow/` |
| Generate business Tool | Internal call during build stage | `workflow_tool_generator.core.generate_tools_from_specs` | `workflow/tools/`, tool registration |
| Generate business Checker | Internal call during build stage | `workflow_checker_generator.core.generate_checkers_from_specs` | Checker, fixture, stage registration |
| Generate configuration | Internal call during build stage | `workflow_config_generator.core.generate_config` | `workflow/config.yaml`, `config/inc.yaml` |
| Generate GuideDoc | Internal call during build stage | `workflow_guidedoc_generator.core.generate_guidedocs` | `workflow/Guide_Doc/`, registration |
| Write evaluation report | `run_eval_*` | `StructuredJsonStore`, `json_store.mutate_document` | `eval/*.json` |
| Incremental deployment | `run_inc` | `incremental.deploy_incremental_changes` | `workflow/`, `tmp/change_history/` |
| Console | `eval-ui` | `review_server.serve` | Update approval, suggestions, and structured design via API |

If the issue occurs in generated artifacts, still trace upward along this table: which template or spec generated the artifact file, which parent stage wrote the spec, which Checker should have intercepted earlier. Fixing a single line in the last generated file might pass the current workspace, but cannot improve the next business.

## Core Data Object Code Analysis

Source location: `tools/workflow_builder/core.py`, symbols `WorkflowBuildError` and `BuildReport`.

```python
class WorkflowBuildError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

@dataclass
class BuildReport:
    workflow_name: str = ""
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

These two types reflect the error and result boundaries of the generator. `WorkflowBuildError` uses stable error codes to distinguish issues like "configuration cannot be parsed", "path out of bounds", "Checker generation failure", etc., from ordinary Python stack traces. Callers can write the `code` into the UCTool's structured error, allowing stage tasks to obtain actionable reasons without parsing natural language. When adding new validation rules, choose an error code prefix consistent with the responsibility domain, and ensure one error code represents only one type of fix action.

`BuildReport` is not the final business report, but a change list of a materialized operation. `created_files` and `skipped_files` support determining if overwrite strategy is effective, and `warnings` are used to record non-blocking issues that need developer handling. New generation steps must append actual writes to the report; otherwise, although UCTool returns success, Agent and regression cannot confirm what was produced. Conversely, do not pre-register success before file write failure.

## Environment Configuration Invocation Analysis

The `setup.py` in the Workflow Builder root directory only generates `.workflow_builder/local.mk`. The Makefile optionally loads it before default variable definitions, so saved values can become local defaults, while the command-line `make WS=...` retains higher priority. This configuration is oriented towards "how to start the parent workflow", containing UCAgent source, virtual environment, default workspace, MCP/console port, and optional proxy.

The `workflow/setup.py` in generating business workflows comes from the `WORKFLOW_ENVIRONMENT_SETUP` template in `tools/workflow_builder/core.py`. It reads the business workflow's own `config/environment.schema.yaml`, saves `.workflow/local/environment.yaml`, and updates the controlled sections of the generated product Makefile and `ucagent_setup.sh`. While both share the same name, their state directories, schemas, and modification objects are completely different. Development documentation, tests, and error messages must use qualifiers like "Workflow Builder root setup" or "generated workflow setup".

The risk of environment configuration modifications focuses on three aspects: first, whether Make variable priority changes; second, whether sensitive values are written to commit-able files; third, whether half-controlled sections are left when configuration fails. Any modification should be tested for first write, repeated execution, dry-run, illegal input, command-line override, and atomic replacement.

Source location: root `Makefile`, local configuration load entry.

```make
WORKFLOW_BUILDER_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
LOCAL_CONFIG ?= $(WORKFLOW_BUILDER_DIR)/.workflow_builder/local.mk
-include $(LOCAL_CONFIG)

UCAGENT_HOME ?= $(HOME)/FDocB/UCAgent
WS ?= $(WORKFLOW_BUILDER_HOME)/workspace
```

First calculate the Makefile's own directory rather than relying on the caller's cwd, so local configuration can still be found when starting from the business workspace using `make -f ...`. The `-include` allows the file to be missing on first use; ordinary assignments in the configuration override subsequent `?=` default values, while command-line variables remain at highest priority maintained by GNU Make. Modifying this order directly affects cross-workspace startup and must be verified via three dry-runs: no configuration, with configuration, and command-line override.

## Data Ownership and Write Boundaries

The `input/` directory is the source of user requirements; the parent Agent can only copy and read from it. The `wfgen/` directory is the central design, where components are appended by responsibility during the build phase. The `workflow/` directory contains public business workflows. The `eval/` directory can only be updated via structured storage. The `res/` directory holds user expertise. The `tmp/` directory stores temporary test cases, incremental candidates, and historical versions. The write boundary is not a documentation suggestion but a security contract preventing the evaluation Agent from modifying the object being evaluated, preventing incremental Agents from exceeding their approval scope, and preventing temporary files from polluting the formal delivery.

When developing new tools, first determine which ownership category it belongs to. A standard evaluation command executor cannot write to `workflow/`. A candidate stager can copy from formal files to the current run directory but cannot deploy in reverse. Only a deployer can replace formal files after verifying the approval source and candidate mapping. Merging these actions into a "universal file tool" renders approval, auditing, and rollback meaningless.

## Complete Localization Example for a Single Defect

Assume the generated `config.yaml` references a non-existent `{INPUT}` in the first phase. Do not simply change it to an absolute path. First, read `wfgen/workflow_build.yaml` in the generation workspace to confirm whether the variable is declared in the runtime contract or template coverage. Then, check if `workflow_config_generator.core._find_unknown_runtime_placeholders()` and `_inject_planned_stage_contracts()` should intercept the issue. Next, verify if the parent phase GuideDoc requires a self-review after generation. Finally, add a negative fixture to the config generator containing undefined placeholders.

The correct fix ensures that all unknown placeholders fail during the generation phase and provide the field location. The current workspace can obtain the new configuration by re-running the corresponding phase or incremental process. Acceptance is not just YAML parseability; it also includes config generator regression, delivery contract, actual `make check`, and new business builds. This process illustrates that developers fix the mechanism producing the error and the missing defense, not a string in a historical file.

## Compatibility and Change Review

When modifying public spec fields, answer whether the old workspace can continue to read them. New optional fields must have clear default values; required fields must appear simultaneously in the schema, minimal example, and migration notes. Renaming fields must provide compatible reading or a clear version gate; updating only the generator while leaving the console, Checker, and regression readers using the old name is insufficient.

During review, check at least: input schema, generated files, configuration registration, user documentation, development documentation, error codes, regression fixtures, and incremental compatibility. A small number of lines of code does not imply a small impact scope; for example, changing the path rule for `reference_files` affects config generation, UCAgent reference tracking, evaluation, and console parsing simultaneously.

## Extension Points Summary

This system prioritizes extension through the central schema, template renderer, UCTool wrapper, structured storage API, and console editor schema. New capabilities should choose the narrowest correct extension point: business rendering enters the corresponding generator, cross-component invariants enter central validation, manual approval enters evaluation control, and no logic should be dumped into `tools/workflow_builder/core.py` or arbitrary shells.
