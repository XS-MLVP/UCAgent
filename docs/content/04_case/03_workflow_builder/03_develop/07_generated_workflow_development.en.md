
# Secondary Development Guide for Generated Workflow Artifacts

This guide targets two types of developers: those who need to enhance a specific business sub-workflow after generation in Workflow Builder, and those who need to determine whether a change should be reflected back into the parent workflow in Workflow Builder. In this document, "Artifact Root" refers to the `workflow/` directory under the business build workspace, and "Parent Root" refers to `examples/workflow_builder/`.

Generated workflows are deliverables that can be used, checked, and migrated independently; they are not immutable black boxes. However, when performing secondary development on them, you must maintain consistency across input/output contracts, Tool/Checker registration, GuideDoc guidance, Make targets, and evaluation/incremental capabilities. Modifying only a single Python file without updating its spec, tests, and documentation may make the manual run succeed this time, but subsequent incremental maintenance will become incomprehensible.

## Secondary Development Goals

The goal of artifact secondary development is to add or adjust capabilities for a specific business that has already been generated, while preserving runnability, checkability, evaluability, rollback capability, and migratability. Typical tasks include adding new business Tools, adding formats or algorithms to existing Tools, adding new stages or adjusting stage input/output, adding Checkers that can prove new requirements, expanding the business knowledge base, GuideDoc, or user documentation, and configuring external dependencies for the new system.

Tasks that do not belong to artifact secondary development include: modifying the UCAgent core to bypass a business config error; manually forging reports to make a Checker pass; directly overwriting structured `eval/*.json` files; scattering temporary scripts in `wfgen/`, the artifact root, or the source directory; and writing all business-specific edge cases back into the parent generator.

## Parent Workflow Modification Entry Points

If errors in the artifacts recur across multiple unrelated businesses, or if the root cause lies in the Workflow Builder's generic templates, schemas, path rules, generation state, evaluation control, or stage guidance, you should modify the Parent Root. The corresponding entry points are `tools/workflow_builder/core.py`, `tools/workflow_tool_generator/core.py`, `tools/workflow_checker_generator/core.py`, `tools/workflow_config_generator/core.py`, `tools/workflow_guidedoc_generator/core.py`, `tools/workflow_evaluation_control/`, and `Guide_Doc/`.

If changes belong only to a business's algorithms, fields, knowledge, style, website visual rules, audio processing strategies, or dedicated external tools, they should remain in the Artifact Root. To enable reuse of similar businesses in the future, prioritize expressing generic capabilities as templates/specs that the parent workflow spec can accept, only moving the implementation up to the parent template once the protocols and algorithms of multiple businesses are stable.

## Component Ownership and Data Ownership in Artifact Root

Different businesses can add directories, but standard artifacts typically include the following responsibility areas. Read the artifact README and `docs/02输入输出.md` before secondary development, as specific sub-workflows can further subdivide `input/<TARGET>/` into requirements, source data, domain knowledge, and optional resources.

| Artifact Component | Ownership and Role | Primary Coupling on Modification |
| --- | --- | --- |
| `config.yaml` | Main execution stages, tasks, reference/output, Tool, Checker, and GuideDoc registration | Stage order, file accessibility, parameter signatures, GuideDoc, Make run/check and flow evaluation. |
| `config/inc.yaml` or equivalent incremental config | Business content extension/update process, not the Workflow Builder's outer `inc.yaml` | Business state, version, input contract, Checker, and user documentation. |
| `tools/` | Business Tools, parameter models, shared runtime libraries, and MCP adapters | Tool spec, config `ex_tools`, fixtures/tests, requirements, GuideDoc, and `docs/04开发者文档-tools.md`. |
| Checker source directory | Business invariants, output integrity, and stage acceptance | Checker spec, config `checkers`, args, fixtures/tests, GuideDoc, and `docs/05开发者文档-checkers.md`. |
| `.workflow/` | Generator spec, fixtures, generation state, and deterministic test support; belongs to maintainable metadata | Sync central spec and state strategy when modifying real source code to avoid generator overwriting or skipping next run. |
| `Guide_Doc/` | Sub-agent stage operation guidance, business constraints, and failure recovery | Config guide_docs, real Tool/Checker signatures, input/output and business knowledge indexing. |
| `docs/` | Documentation for human users and subsequent developers | README directory, quick start, input/output, stage checks, and real source code analysis for Tools/Checkers. |
| `knowledge_base/` or business knowledge directory | General business knowledge delivered by the workflow, readable by Agent via index | Index, source/license, version, GuideDoc read strategy, and related Checkers; do not inject the full database into every stage. |
| `Makefile`, `setup.py`, `ucagent_setup.sh`, `requirements.txt` | Runtime entry, cross-system configuration, controlled environment updates, and dependency installation | Environment schema, variable precedence, Make help/check/test/migration, non-Python installation notes, and eval_env. |
| `input/<TARGET>/` | Data, requirements, and optional domain knowledge provided by business users for each run | Input schema, quick start examples, missing file errors, and path boundaries; Tools must not overwrite user input. |
| `output/` | Business run results and structured intermediate artifacts | Output contract, atomic writes, hash/parsable verification, Checker, and cleanup strategy. |
| `tmp/` | The only allowed root for storing debug info, browser profiles, download caches, candidate cases, and temporary outputs | Cleanup at run start/end, concurrency lock fault tolerance, and version history to retain; do not clear profiles in use. |

## Code Analysis of Builder Generation Boundaries

The parent workflow's `tools/workflow_builder/core.py` uses `BuildReport` to record materialized operations and restricts artifact targets via safe path functions. Secondary developers should not copy these internal parent classes into sub-workflows, but must understand why generation state distinguishes created/skipped/warnings:

```python
@dataclass
class BuildReport:
    workflow_name: str = ""
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

An artifact already modified by the user is marked as skipped, typically indicating that the preserve strategy is protecting it, not that the generator failed. To make spec updates take effect, use the generator's supported replace or incremental candidate deployment, saving the old version first and running regression tests. Do not delete the entire `.workflow/` to force generation, as this will also lose specs, fixtures, and drift evidence.

## Tool Artifact Extension Steps

Before modifying a tool, locate it in `.workflow/tool_specs/` or the artifact's actual central spec directory. If a spec exists, it should be the single source of truth for name, description, inputs, outputs, errors, implementation, registration, and tests; modify the spec first, then update the real source code via the generator in the artifact or the Workflow Builder incremental process. If the artifact does not retain a replayable spec, explicitly mark the modified file as manually maintained in the modification record to prevent future generator overwrites.

Each Tool's stable return should allow subsequent stages to avoid parsing terminal text:

```python
return {
    "ok": True,
    "data": {"artifact": "output/result.json", "records": record_count},
    "errors": [],
    "warnings": warnings,
    "meta": {"tool": self.__class__.__name__, "schema_version": 1},
}
```

When adding parameters, sync Args/Pydantic models, Tool signatures, spec input schemas, config registration, GuideDoc call examples, and positive/negative fixtures. When adding outputs, sync output schemas, subsequent references, Checkers, and documentation. When introducing third-party libraries, sync `requirements.txt`. When introducing non-Python tools like Verilator, FFmpeg, or LibreOffice, document Linux/macOS installation commands, version verification, and failure/degradation behavior in the requirements comments.

Tool writes must be restricted to explicit `output/state/tmp` roots, with paths normalized using `resolve()` and ownership checked before writing. When involving network resource acquisition, place domain whitelists, protocols, response sizes, MIME types, redirects, license records, and caches in the checkable contract; do not implement "searchable online" as an arbitrary URL downloader.

## Checker Artifact Extension Steps

New Checkers must answer a verifiable proposition, such as "the output JSON is parseable, all required records have stable IDs, and the total error count matches the summary," rather than just "checking the output." Class docstrings should describe the check object and pass conditions; method docstrings should describe calls and returns. Construct parameters should only accept workflow-relative paths and structured thresholds; config args must exactly match signatures.

Check methods are recommended to return `(passed, evidence)`, where evidence includes error codes, target paths, failed fields/rules, and limited context. File not found, unparsable, structural errors, business semantic errors, and Checker self-exceptions should be distinguishable. Each rule must have at least one positive fixture and one negative fixture that breaks only that rule. Placeholder implementations using unconditional `return True` must not pass all tests.

After modifying a Checker, also verify the artifact timing of the stage it resides in. A file generated in subsequent stages cannot be used as a required input by the current Checker. Path comparisons must be completed after normalization; do not misjudge due to string differences between `.//workflow/a` and `workflow/a`. In reference/output, list specific files; directories can only be passed if the Checker explicitly supports directory traversal in its construction parameters, which does not change the stage file contract.

## config and Stage Extension Steps

Before adding a new stage, map out input files, output files, called tools, passed Checkers, guidance documents, and failure recovery. Descriptive content in tasks should be in Chinese; class names, fields, commands, and file paths must remain in their original form. New stages should not just be "run cognition again," "write another spec," or "check again"; if it does not produce new state, new artifacts, or independent acceptance evidence, merge it into an existing stage.

Perform closure audits on stage references: reference files must come from user input or be explicitly output by previous stages; outputs must be specific files, not directories representing unknown results; Tool and Checker registration classes must be importable with consistent args; GuideDoc files must exist and inject only necessary documentation; any `{NAME}` placeholders must have clear definitions, defaults, or startup parameter sources.

After modifying config, complete YAML parsing, unknown placeholder checks, reference accessibility, directory file contracts, Tool/Checker imports, and Make dry-run checks. Then execute the relevant stage with a minimal business input, rather than waiting to discover the first missing reference after running the full long process for dozens of minutes.

## GuideDoc, docs, and Knowledge Base Extension Steps

GuideDoc is for Agents executing sub-workflows and should specify the phase objectives, specific inputs and outputs, tool parameters, verification conditions, minimum passing structures, common complete examples, and failure recovery. User docs are for humans and should cover quick start, inputs and outputs, each phase, and the Checker. Developer docs should reference real business source code for every Tool and Checker, explaining parameters, core algorithms, writes, errors, registration, and testing.

The Knowledge Base stores general professional knowledge required by sub-workflows itself. Project-specific knowledge added by users each time should remain in inputs or agreed-upon resources directories. The Knowledge Base must have an index, annotating topics, scope, source, license, version, and related files. The Agent first queries the index, then reads direct entries according to the current task; do not read the entire knowledge base at the start of each stage, otherwise long workflows may repeat reading after compression and spin uselessly.

## Environment, Makefile, and setup Extension Steps

The generated workflow's `setup.py` should read its own environment schema, interactively define or update local values, then controlled update markers in the Makefile or `ucagent_setup.sh`. Default users should be able to run it, but secrets, tokens, and agent credentials should not fall into commit-able files. Make variable priority is typically command line highest, local configuration second, and `?=` code default last; modify include order only after confirming with dry-run.

When adding external commands, synchronize environment schema, setup prompts and verification, requirements comments, Make variables/targets, Tool whitelist, Checker installation probe, QuickStart, and eval_env. External commands must be executed with parameter arrays, setting cwd, timeout, and output limits, never concatenating user input into a shell. When a business needs to generate multiple independent products in parallel, disjoint write sets can be executed in parallel; config, registration, shared state, and aggregated reports must be submitted serially.

## Compatibility of Evaluation and Incremental Delivery

After secondary development of sub-workflow outputs is complete, first run its own `make check`, `make test_tools`, and relevant business examples, then run corresponding `eval_tools`, `eval_checkers`, `eval_flow`, or `eval_env` from the outer Workflow Builder. Evaluation reports do not modify outputs; only after the user approves findings in the console or proposes suggestions does the outer `inc.yaml` modify, check, backup, and deploy in the current candidate directory. The atomic deployment entry for formal files is `IncrementalChangeDeployer`; ordinary file tools and evaluation Agents must not replace it in writing to `workflow/`.

If human secondary development bypasses the incremental deployer to directly modify outputs, subsequent incs can still work, but developers must treat the current file as a new baseline, check generator state and spec for drift, and provide their own Git or another version backup. Do not treat the outer `tmp/change_history/` as a permanent version library; it is used for incremental deployment recovery, and users should still manage long-term business source code with Git.

## Complete Order of Secondary Development on One Product

1. Run existing `make check` in the product root and record the baseline, read README, input/output docs, target stage GuideDoc, and related Tool/Checker development docs, avoiding blind full-library scans without objectives.
2. Clearly define requirement id, current behavior, expected behavior, inputs/outputs, invariants, affected components, minimal positive/negative examples, and acceptance commands.
3. Decide if the change belongs only to the current product or exposes a generic defect in the parent template/generator; if both are needed, fix the parent mechanism first with regression, then use incremental flow to fix historical products.
4. Fix the central spec/manifest first, then Tools, Checkers, config, GuideDoc, docs, and requirements. Temporary test data goes only to `tmp/`; formal fixtures go to test directories specified by the contract.
5. Verify in order: syntax, unit/fixture, Tool direct/MCP, Checker positive/negative, config closure, documentation, and `make check`; fix the layer if it fails at any point, without re-running the same long command without state changes.
6. Run corresponding evaluations and review reports; high-risk issues must have concrete evidence. When deploying via incremental flow, confirm each approval has change mapping, old version backup, new hash, and formal regression results.
7. Update the product's version, change notes, and migration package; execute configuration and checks in the new temporary root, confirming no dependencies on developer machine absolute paths.

## Failure, Rollback, and Regression Strategies

Syntax failures, Tool direct call failures, Checker negative example false passes, unreachable config references, and formal `make check` failures cannot be replaced by "known issues" in docs or reports. For candidates not yet deployed, continue fixing the candidate; if deployed and within the same approval scope, save a new version of old files before continuing fixes; if exceeding the approval scope, rollback or report needing new approval. Do not stop at pending when a deployed regression fails and infinitely repeat the same command.

Product-level regression must include: full Python source compilation; YAML/JSON parseable and schema-valid; each Tool's normal, boundary, failure, path, and repeated runs; each Checker's import, args, positive examples, and single-error negative examples; stage reference closure; GuideDoc with real signatures; Make dry-run/check; setup first, repeated, invalid values, and command-line override; minimum run after migrating to new root. External dependencies that do not exist must be clearly marked skip/unavailable, not disguised as business success.

## Completion Definition

Secondary development on a generated workflow is considered complete only when all the following conditions are met simultaneously: user requirements have stable ids and tracking mappings; spec/source code/config/GuideDoc/docs are consistent; Tools are truly callable and passable via UCAgent; Checker positive/negative evidence is valid; `make check` returns 0 for formal products; old versions are recoverable; evaluations have no unresolved blocking issues; migration to new directories does not depend on original absolute paths.

If a modification fixes a generic parent mechanism defect, also add deterministic regression in the Workflow Builder parent root, update corresponding `Guide_Doc/`, and update this group's developer docs. Only then will the fix automatically take effect in the next unrelated business, rather than existing only in the current historical workspace.

## Continue Reading

When needing to modify specific components in the parent workflow, locate the phase from [Workflow Introduction](01_workflow.md), then read [Tool Introduction](02_tools.md), [Checker Introduction](03_checkers.md), [GuideDoc Introduction](04_guide_docs.md), [Evaluation and Incremental Control](05_evaluation_and_incremental_control.md), and [Testing and Regression](06_testing.md).
