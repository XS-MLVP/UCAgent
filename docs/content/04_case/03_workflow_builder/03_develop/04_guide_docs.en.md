
# GuideDoc and Document Generation Secondary Development for Parent Workflows

This guide is for developers maintaining the parent workflow `Guide_Doc/` and `tools/workflow_guidedoc_generator/`, explaining how to modify stage guidance contracts, common FAQs, user document generation, and registration logic. The actual readers of GuideDoc are the Agents executing the stage, but the purpose of this guide is not to teach Agents how to perform tasks, but to instruct developers on how to design and implement this guidance system.

## Secondary Development Goals

Typical tasks include adding new parent stage GuideDocs, adjusting semantic chapter contracts, adding user document types, fixing detail algorithms, controlling reference document read volumes, updating common FAQs, or changing `guide_docs` registration. After modifications, it must be proven that the parent Agent reads the correct guidance, and that user documents generated for the workflow are not erroneously injected into each stage.

## Parent Workflow Modification Entry Points

- Root `Guide_Doc/`: Public and stage guidance actually loaded by the parent workflow.
- Root `config.yaml`, evaluation/incremental YAML: GuideDoc registration and stage references.
- `tools/workflow_guidedoc_generator/contract.py`: Stable chapter semantics and compatible headings.
- `tools/workflow_guidedoc_generator/core.py`: Spec validation, rendering, writing, and registration.
- `tools/workflow_builder/core.py`: Fixed user document templates.
- `regression/`: GuideDoc, delivery document, and detail regression.

## Directory Structure and Generation Methods

Parent workflow public guidance is located in the root `Guide_Doc/`. Stage-specific documents are typically located in `Guide_Doc/stages/`, while common issues are located in the same public directory and referenced by each stage. The implementation for generating business GuideDocs is located in `tools/workflow_guidedoc_generator/`, with registration information entering the business configuration.

## What a Stage Document Should Contain

- Stage objectives and content not handled in this stage.
- Specific reference files that must be read and their read order.
- Tool names, parameter sources, outputs, and failure handling.
- Specific files that need to be generated or updated.
- Checker names, parameters, and the meaning of each check.
- Minimum passing version, using stable placeholders rather than specific business filenames.
- A realistic common example.
- Common failures, confirmation methods, and fix order.
- The format for appending records in this stage within the implementation plan.

The purpose of the minimum example is to eliminate ambiguities in YAML, JSON, Markdown markers, or registration formats; it does not represent an encouragement for Agents to generate only minimal content. When there are requirements for body text length, it should be explicitly stated after the example that "this snippet only demonstrates structure, and formal content must meet detail requirements."

## FAQ Positioning

Stage FAQs are stable experiences summarized after predecessors run, placed in the public `Guide_Doc/` along with the Workflow Builder, and are not automatically rewritten on every business run. Only update the FAQ after confirming the issue is general, with causes and fix methods verified.

FAQ entries should include symptoms, true causes, incorrect practices, correct handling, and applicable stages. Business-specific filenames should only be placed in the "example" field and should not become universal mandatory artifacts. For example, if a business generates `diag_checker.py` once, it should not be required in general rules for all workflows to create it.

## Read Cost Control

Stage tasks should directly reference short documents of this stage; do not stuff hundreds of lines of public contracts into each config stage. Agents should first read directories, summaries, and minimum examples, then direct-read FAQs or development documents when encountering specific problems. Evaluation and incremental cognitive stages also adopt budgeted reading; establishing a preliminary understanding does not mean scanning all docs in full.

## Modification Methods

1. First confirm the problem stems from missing guidance, not Checker implementation errors.
2. Update public source documents and corresponding stage references.
3. If format contracts change, synchronize updates to minimum examples, schemas, and Checkers.
4. Check that text contains no business coupling, future file references, or contradictory steps.
5. Run GuideDoc generation regression and configuration reference checks.

## Document Quality Checks

Detail does not mean repeatedly saying "must be detailed." High-quality guidance provides fields, data flows, tool parameters, judgment conditions, and failure recovery. Stage descriptions should at least allow an Agent not involved in this conversation to execute, without guessing filenames, template names, or output locations.

## GuideDoc Spec and Document Types

The GuideDoc generator handles both stage operation guidance and final user documents, but the two document types use different contracts. Stage GuideDocs emphasize purpose, inputs, outputs, usage, execution, checks, and failure recovery; user documents emphasize effective body text length, commands, input/output, and development/maintenance information. When developers add new document types, they should first determine if it is executed by the Agent or read by humans; the same set of headers should not mechanically validate all documents.

The spec should clearly define target path, document type, chapter id, heading, content, and registration stage. The `id` is stable semantics, while `heading` can be localized or adjusted in wording. Relying solely on heading text would incorrectly treat "input", "Inputs", and "input/output" as different contracts, so the current implementation retains compatible mappings.

## Semantic Chapter Contract Code Analysis

Source location: `tools/workflow_guidedoc_generator/contract.py`, symbols `REQUIRED_SECTION_IDS`, `LEGACY_HEADING_IDS`, and `section_id()`.

```python
REQUIRED_SECTION_IDS = (
    "purpose", "inputs", "outputs", "usage",
    "execution", "checks", "failure_recovery",
)

def section_id(section):
    value = section.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return LEGACY_HEADING_IDS.get(section.get("heading"), "")
```

Explicit `id` takes priority, ensuring Chinese heading changes do not affect validation. Only when the old spec lacks an `id` is it mapped by `heading`, providing backward compatibility. Adding new required chapters affects all existing GuideDocs, therefore requiring schema versions, default migrations, or sufficient regression; one cannot simply add a value to the tuple and expect the old workspace to pass automatically.

`REQUIRED_OPERATION_MARKERS` further checks if key chapters truly describe `input/<TARGET>/`, `output/`, `make check_example`, and `make run`. It addresses the issue of "complete headings but vague content." However, markers are just minimum evidence and should not evolve into all business documents pasting the same command block.

## Spec Validation Code Analysis

Source location: `tools/workflow_guidedoc_generator/core.py`, symbol `validate_guidedoc_specs()`.

The validator first limits specs and output paths via `_safe()`, then loads the YAML mapping, distinguishing user documents from GuideDocs. For operation guidance, it builds a section id set, checks for missing or duplicate entries, content types, and markers; for user documents, it calls `_effective_prose_length()` to calculate body text after excluding code fences, headings, and formatting noise.

This order is critical: path safety must fail before reading or writing; do not continue building Markdown if the structure is illegal; length checks should be based on actual descriptions, not YAML serialization length. If a new "source analysis" document requirement is added, check real source paths, code fences, and analysis chapters, rather than counting code characters to meet length.

The validation function returns a normalized spec list for the generation stage. Developers should not read a set of unnormalized fields from the original YAML again after validation, otherwise validation and generation will diverge.

## Document Generation and Registration Code Analysis

Source location: `tools/workflow_guidedoc_generator/core.py`, symbol `generate_guidedocs()`.

The following is pseudo-code omitting implementation details; see the source above for the full implementation.

```text
specs = validate_guidedoc_specs(workflow_root, spec_paths)
for spec in specs:
    target = _safe(root, spec["path"])
    content = render_sections(spec["sections"])
    _write_text(root, target, content)
    ... update config guide_docs registration ...
```

The generator should use atomic writes to avoid UCAgent reading a long document halfway written. Registration applies only to GuideDocs the Agent needs to load; ordinary user documents should not all be stuffed into `guide_docs`, otherwise each stage context would meaninglessly increase. Registration records must use workflow-relative file paths and be consistent with stage references.

When multiple GuideDocs are batch-generated, it is best to validate all first before starting writes. This ensures that if the seventh spec has a format error, the first six new files and old config do not end up in a mixed state. If the current implementation cannot be transactional, the report must at least accurately list written files for failure recovery cleanup.

## Minimum Passable Structure for Stage Guidance

The following structure only demonstrates semantics and does not represent that formal content can be this abbreviated:

```yaml
path: Guide_Doc/stages/prepare.md
document_type: guidedoc
sections:
  - id: purpose
    heading: Purpose
    content: Describe this stage's responsibility and explicitly excluded work.
  - id: inputs
    heading: Inputs
    content: List the files and fields available before execution and their source stages.
  - id: execution
    heading: Execution Steps
    content: Specify the tools, arguments, outputs, and plan update locations in order.
```

Formal specs must also include `outputs`, `usage`, `checks`, `failure_recovery`, and provide sufficient detail for each tool and Checker. The minimum example should be placed immediately after the reminder that "body text must meet detail requirements" to prevent Agents from copying the example verbatim as the final document.

## FAQ Maintenance Linkage

After stage failures are evidenced, first record the business scene in this stage's "Issues and Handling" in the implementation plan. After the process completes, categorize: if it is a business-specific constraint, keep it in the business plan or business GuideDoc; if it is a generator defect, modify the code and regress; if it is a cross-business stable misconception, then write it to the public FAQ.

FAQ entries must provide symptoms, impact, confirmation steps, root cause, correct fix, and incorrect practices. For example, the universal root cause of "Checker reports unread `.//workflow/x`" is that the path is not normalized; `.//` should not be treated as the correct format that future Agents must mimic. After FAQ updates, check which stages need to reference them, ensuring not all stages default to reading all FAQs.

## Reading Budget and Context Design

The goal of GuideDoc is to reduce Agent decision costs, not add reading rituals. A stage should directly reference short, complete documents of this stage; shared long contracts should be consulted on-demand via indexes and rule ids. Evaluation and incremental processes should first read directories, manifest summaries, and target object indexes, then read source code by finding.

Instructions like "fully understand the entire process" in task descriptions can lead to full scans of tools, checkers, docs, and reports, which then compress and repeat reading. More reliable instructions specify which indexes to read in the first round, what cognitive summary to output, and which direct dependencies are allowed to be appended when processing a specific object.

## Secondary Development Case: Adding Stage Guidance to Parent Workflow

Assume the addition of a "Material License Audit" stage. The developer first declares in the central workflow spec that the input is a specific material list file, the output is a license report, the Tool is the license metadata parser, and the Checker is the license status checker. The stage GuideDoc explains the source whitelist, unknown license behavior, network failure recovery, and report evidence.

Adding only the GuideDoc without the central stage and Checker means the document will not be executed; adding only the config stage without a GuideDoc means the Agent will guess tool parameters; registering the entire `docs/` directory causes stage context explosion. The correct approach modifies and covers the spec, tool, Checker, GuideDoc registration, minimal fixture, and regression simultaneously.

## Extension Points and Testing

Testing explicit IDs, old heading mappings, missing sections, duplicate sections, and unknown IDs when adding new chapter semantics. Testing code blocks, tables, links, Chinese and English body text when modifying the length algorithm. Testing that user documents are not injected into the Agent, GuideDocs are readable, paths do not escape, and repeated generation is idempotent when modifying registration.

Real-world business acceptance requires reading the generated documents, not just checking the checker return code. A structure that is correct but inconsistent with the actual tool signatures in the steps remains a serious document defect.

## Cross-Cutting Complete GuideDoc Index

All files in the table below are located in the parent workflow `Guide_Doc/`. They represent the execution contract of the parent Agent, not the content of the developer's documents. Before modifying, query referenced stages in YAML to avoid unintentionally injecting a long document into all stage contexts.

| File | Role | Secondary Development Linkage |
| --- | --- | --- |
| `workflow_build_guide.md` | Central design principles for construction, explaining the transition of requirements to sub-workflows | requirements manifest, implementation plan, Builder skeleton, and requirement coverage Checker. |
| `workflow_build_yaml_guide.md` | Fixed structure of `wfgen/workflow_build.yaml`, minimum passing version, common examples, and reference closure | config/checker/tool/guidedoc generator reading the central spec and `WorkflowBuildConfigChecker`. |
| `tool_generation_guide.md` | tool spec, actual implementation, generation status, batch generation, and testing strategy | `tools/workflow_tool_generator/`, Tool generation Checker, `eval_tools`, and sub-workflow `docs/04`. |
| `checker_generation_guide.md` | checker spec, docstring, positive/negative fixtures, args registration, and false positive prevention | `tools/workflow_checker_generator/`, Checker generation Checker, `eval_checkers`, and sub-workflow `docs/05`. |
| `config_generation_guide.md` | config/inc stage structure, specific file reference/output, word count requirements, and self-review | `tools/workflow_config_generator/`, runtime audit, `eval_flow`, and all generation stage contracts. |
| `guidedoc_generation_guide.md` | GuideDoc/user docs spec, section ID, detail level, source code analysis, and registration boundary | `tools/workflow_guidedoc_generator/`, GuideDoc spec/generated/user docs Checker. |
| `stage_check_guide.md` | One-time check before stage end, failure evidence, and repair order | Check command for stage tasks and living plan "Issues and Handling"; avoid re-running the entire check group for every generated file. |
| `makefile_architecture_guide.md` | Parent Makefile variable precedence, run/eval/inc/UI targets, loop/TUI/history, and workspace preparation | Root Makefile, `setup.py`, QuickStart/Usage commands, and environment regression. |
| `evaluation_contract.md` | Shared report schema for the evaluation suite, severity, evidence, write, and contract not to modify evaluated objects | JSON store, Evaluation Checker, report UI, and aggregate. |
| `evaluation_execution.md` | Static evaluation reading budget, deterministic commands, report writing, and anti-loopback steps | EvaluationCommandRunner, StaticEvaluationAudit, and all `eval_*.yaml`. |
| `eval_tools.md` | Tool existence, UCTool protocol, registration, callability, and static evaluation checklist for user requirement coverage | `eval_tools.yaml`, tool audit rule ID, `eval/tools_report.json`. |
| `eval_checkers.md` | Checker existence, protocol/docstring, args registration, positive/negative work, and business sufficiency | `eval_checkers.yaml`, checker audit rule ID, `eval/checkers_report.json`. |
| `eval_flow.md` | config/inc semantics, stage handover, reference reachability, Checker realizability, and GuideDoc rationality | `eval_flow.yaml`, flow audit rule ID, `eval/flow_report.json`. |
| `eval_env.md` | Makefile, setup.py, `ucagent_setup.sh`, requirements, portability, permissions, and ports | `eval_env.yaml`, environment audit rule ID, `eval/env_report.json`. |
| `eval_run.md` | High-cost evaluation for the only runnable sub-workflow, explaining runtime target, timeout, stuck evidence, and termination | `eval_run.yaml`, ChildWorkflowSupervisor, runtime report, and execution assessment gate. |
| `incremental_workflow_discovery.md` | Preliminary cognition of inc first stage, index priority, and reading budget | `IncrementalContextInventory`, context report Checker; avoid full-text scanning to prevent continuous compression. |
| `incremental_execution.md` | inc run/batch/attempt, candidate copy, modification, check, deploy, regression, and termination state machine | `inc.yaml`, stager/deployer, incremental report, applied changes, and history. |
| `incremental_evaluation.md` | Approving freshness, fixing scope, acceptance evidence for each suggestion, and closure | approvals/suggestions, IncrementalApproval/Application/Regression Checker. |

## 24 Stage GuideDoc Complete Index

`Guide_Doc/stages/README.md` is the stage document directory and shared structure description. The following files correspond one-to-one with the 24 stages in the main `config.yaml`; the numbers and stage names in the filenames must remain synchronized.

| Stage GuideDoc | Primary Purpose of This Stage |
| --- | --- |
| `stages/00_extract_requirements_and_plan.md` | Read user guide and examples, generate requirements manifest, input manifest, and detailed implementation plan, clarifying that Tools/Chekers/docs must be more specific than the user's original wording. |
| `stages/01_design_workflow_build_config.md` | Convert requirements to central `workflow_build.yaml`, planning stages, Tools, Checkers, references, GuideDocs, and tests in advance. |
| `stages/02_build_initial_template.md` | Invoke Builder to generate a checkable initial skeleton, not overstepping to replace subsequent business implementation. |
| `stages/03_verify_tool_generation_loop.md` | Prove that the tool generator itself can safely generate from spec, retain/replace, and return evidence. |
| `stages/04_design_smoke_business_tool_spec.md` | Select a representative business Tool from requirements, write a complete spec, real source code scheme, and positive/negative tests. |
| `stages/05_implement_smoke_business_tool.md` | Verify actual implementation and registration through generated materialized smoke Tool, not manually supplemented by the supervisor. |
| `stages/06_strengthen_smoke_business_tool_tests.md` | Add boundary, failure, path, and repeated run fixtures to prevent relying only on lucky positive examples. |
| `stages/07_initialize_smoke_workflow.md` | Assemble the minimum runnable sub-workflow using initial config/Make/GuideDoc for the smoke Tool. |
| `stages/08_verify_generated_tools_through_mcp.md` | Load and call tools from UCAgent/MCP paths, proving it is not limited to direct import. |
| `stages/09_freeze_smoke_baseline.md` | Save the smoke baseline spec, tests, and evidence as a comparable standard for subsequent batch generation. |
| `stages/10_design_complete_runtime_configs.md` | Design full config/inc stage contracts, self-reviewing reference/output reachability, placeholders, and Tool/Checker closure. |
| `stages/11_generate_complete_runtime_configs.md` | Generate full configuration using the config generator, running syntax, path, registration, and execution contract audits. |
| `stages/12_design_all_business_tool_specs.md` | Design tool specs for all requirement capabilities, clarifying real algorithms, dependencies, outputs, and test mappings. |
| `stages/13_generate_all_business_tools.md` | Batch generate tool source code and registration, allowing independent products to prepare in parallel and shared configs to submit serially. |
| `stages/14_run_full_tool_test_suite.md` | Run syntax, direct, MCP, positive/negative fixtures, and requirement coverage in one go, fixing and re-running. |
| `stages/15_design_all_document_specs.md` | Plan GuideDoc, README, 01–05, requirements, etc., document types, sections, detail levels, and source code analysis evidence. |
| `stages/16_generate_all_documentation_and_dependencies.md` | Materialize documents and dependencies in batch, running the document group check for the last time to avoid repeated per-file checks. |
| `stages/17_generate_all_reusable_templates.md` | Generate templates and cases only for truly reusable business patterns, not forcing all businesses to establish meaningless templates. |
| `stages/18_complete_readme_and_makefile.md` | Complete sub-workflow README, Make targets, environment entry, and user command consistency. |
| `stages/19_mark_feature_complete.md` | Align manifest capability markers with real product evidence, prohibiting marking "complete" without evidence. |
| `stages/20_verify_final_requirement_coverage.md` | Reverse-check from user original requirements whether tools, Checkers, stages, documents, and environments truly cover. |
| `stages/21_clean_release_candidate.md` | Clean non-delivery temporary files, ensuring temporary data exists only in `tmp/`, without deleting user inputs, reports, and required history. |
| `stages/22_prepare_and_verify_migration_packages.md` | Generate migration lists/packages, verifying relative paths, dependencies, environment descriptions, and package integrity. |
| `stages/23_verify_migrated_release.md` | Unpack, configure, and run checks in the new temporary root, confirming no dependency on absolute build machine paths. |

## Standard Process for Adding or Modifying GuideDoc

1. Identify whether this is a cross-cutting contract, an evaluation/incremental contract, or a main phase operation guide, and query the current YAML reference scope.
2. Write steps using specific files, fields, Tool parameters, Checker judgments, and failure evidence; descriptive content should be in Chinese, while class names, fields, commands, and identifiers must remain in their original form.
3. Include a minimal passing structure and a common complete example immediately followed by a reminder: "The minimal example does not meet the depth/length of the main text," to prevent the Agent from copying a brief example verbatim.
4. Write stable, generic failures into the corresponding FAQ, retaining only symptoms, root cause, verification, correct fix, and incorrect practices; do not automatically modify the parent FAQ during every business run.
5. Synchronize stage task, guide_docs registration, corresponding Checker, document generation rules, and document regression, then verify whether a new business observation Agent can execute independently.

## Continue Reading

Beyond evaluation and incremental GuideDoc, there are JSON state, approval freshness, candidate deployment, and rollback contracts. Please continue reading [Evaluation and Incremental Control](05_evaluation_and_incremental_control.md), and do not leave an inconsistent state machine by modifying only natural language guidance.
