
# Secondary Development of the Parent Workflow Checker Generation Subsystem

This document explains how to modify the parent workflow Checker planning, generation, templates, fixtures, and registration system to ensure that subsequently generated business workflows possess the correct Checker. The target audience is developers maintaining `tools/workflow_checker_generator/`, the Builder center spec, and the parent stage acceptance, not the sub-Agent being checked by the Checker.

The Checker determines whether the parent stage or the generated business stage satisfies the contract. Secondary development must distinguish between two categories: parent Checkers registered in the root config verify `wfgen/` and build progress; business Checkers planned in `workflow_build.yaml` are materialized into `workflow/`. Both categories inherit the UCAgent Checker protocol, but differ in source and delivery location.

## Secondary Development Goals

Typical tasks include adding generic rule types, enhancing AST/docstring validation, modifying automatic fixtures, fixing registration parameters, adding path normalization, or improving Checker direct runner execution. Business-specific judgments should primarily be expressed by inlining sources within the center spec; only when multiple businesses share a rule and it is stable should it enter the public template.

## Parent Workflow Modification Entry Points

- `tools/workflow_checker_generator/core.py`: spec, source code, fixtures, registration, and reporting.
- `tools/workflow_checker_generator/templates.py`: generic rule renderer.
- `tools/workflow_builder/core.py`: materializes business Checkers directly from the center workflow spec.
- Root `config.yaml` and parent Checker modules: self-acceptance of the parent stage.
- `Guide_Doc/stage_check_guide.md` and stage GuideDoc: failure explanations and repair directions.
- `regression/run_checker_description_regression.py` and delivery contract: protocol regression.

## Real Generation Pipeline

The center planning for Checkers is located in the workflow spec within `workflow_build.yaml`. The build stage should directly generate Checker source code, fixtures, and registration from this design, avoiding the need to guess what each stage requires later. Related implementations are primarily located in `tools/workflow_checker_generator/`, `tools/workflow_builder/core.py`, and `tools/workflow_evaluation_control/uc_checkers.py`.

```bash
rg -n "Checker|checker_spec|workflow_spec" workflow_builder workflow_checker_generator regression
```

## Docstring and Construction Parameters

UCAgent reads the Checker description; therefore, Checker classes must provide non-empty, specific docstrings. Descriptions like `"Check output"` do not explain the check object. The docstring should specify which files or fields are read, the core pass conditions, and the meaning of failure.

Parameter names, required status, and default values in the configuration registration must match the Python constructor exactly. Adding an extra parameter will cause instantiation to fail, while missing required parameters will prevent the stage from running. Directory parameters are only reasonable when the Checker design explicitly supports directory traversal; workflow stage `reference_files` must remain specific files.

## Judgment Semantics

Checkers should distinguish between:
- Files that do not exist or cannot be parsed.
- Missing or incorrectly typed structural fields.
- Correct structure but unsatisfied business semantics.
- Dependency conditions not yet met, such as future chapters or optional outputs that do not exist.
- Exceptions encountered by the Checker itself.

Optional inputs should not be treated as mandatory files in early stages. Version or progress checks must be based on the current stage's true semantics, such as "version must match when the latest snapshot chapter equals the current chapter"; using globally unresolvable equalities will create false positives.

## Key Business Code Analysis Requirements

The generated `docs/05开发者文档-checkers.md` must provide real source code and analysis for each Checker:

1. Class definition, constructor, and `check`/entry call points.
2. Input paths, fields, and normalization rules.
3. Major conditional branches and error code mappings.
4. Why these conditions prove user requirements rather than merely proving format existence.
5. Positive fixtures, single-error negative fixtures, and boundary fixtures.
6. Registration fragments in config and parameter mappings.
7. Stages and tests that must be synchronized when modifying thresholds, fields, or dependencies.

Fragments must come from the final generated real files, annotated with relative paths and symbols near key lines. Analysis should point out the source of business rules; if requirements do not specify, it must state this is a design decision supplemented by the first-stage plan.

## Preventing False Positives and Negatives

The minimum fixture changes only one condition, making the failure reason locatable. A single negative fixture breaking five fields makes it impossible for developers to know if the Checker validates the target rule. Checkers must not rely on unstable time, random order, or absolute paths. Path comparisons should be normalized before comparison; `.//workflow/x` and `workflow/x` should not be incorrectly judged as different due to string differences.

Severity is not a decoration arbitrarily decided by the Checker. Issues that block UCAgent startup, cause infinite retries, corrupt formal files, or falsely claim completion are most dangerous; document wording, non-critical hints, and optional optimizations should not be upgraded to blocking stage issues.

## Modification Checklist

- Synchronize updates to the center checker spec, generation templates, registration, and stage parameters.
- Ensure docstrings explain the actual check content.
- Add instantiation tests and parameter registration consistency tests.
- Provide positive and negative evidence for each business rule.
- Verify that Checker self-exceptions do not masquerade as business failures.
- Run Checkers to generate regression and related full-process checks.

## Central Role of Checker Spec

The Checker spec is the common source for judgment implementation, fixtures, tests, and stage registration. Each Checker in `workflow_build.yaml` should fully carry name, description, entry, rules or source code, fixtures, tests, and registration. The Builder first writes the center definition to `.workflow/checker_specs/<name>.yaml`, then calls the checker generator for materialization, avoiding the situation where stage config, Python files, and tests are each written by different steps.

Checker descriptions must explain "what evidence proves what business condition." For example, a "Check report" has no object, fields, or failure meaning; only "read `validation_report.json`'s `status`, `missing_assets`, and `output_sha256`, confirming DOCX is parseable and no required assets are missing" is sufficient to guide the Agent and evaluator.

## AST and Docstring Validation Code Analysis

Source location: `tools/workflow_checker_generator/core.py`, symbol `_validate_spec()`.

This function first confirms the top-level mapping, name, detailed description, and entry, then validates rule type, register, fixtures, and tests. Paths must pass `_safe_resolve()`, test parameters must be mappings, and `expected_pass` must be a boolean. Duplicate or missing fields should fail before source generation to prevent leaving half-finished Checkers.

If the spec provides `source`, the validator cannot skip structural checks just because "the user has written code." Source and entry must still align, tests are still required, and registration parameters still need validation. Rule templates and inline source are just two ways to produce implementation and do not represent different quality standards.

## AST and Docstring Validation

Source location: `tools/workflow_checker_generator/core.py`, symbol `_validate_inline_source()`.

The following is pseudo-code omitting implementation details; the full implementation is in the source above.

```text
tree = ast.parse(source)
class_node = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == entry["class_name"]
)
if not any(base.id == "Checker" ... for base in class_node.bases):
    raise CheckerGenerationError(...)
method = next(node for node in class_node.body if node.name == entry["method"])
if method is None or not ast.get_docstring(method):
    raise CheckerGenerationError(...)
```

AST validation is more reliable than text search: class names in comments are not mistaken for implementation, aliases or base class attributes can be explicitly handled, and method docstrings can be obtained from the syntax tree. It still does not run tests, cannot prove import dependencies exist, construction parameters match, or check logic is correct, so a static checker and direct runner are still needed afterwards.

Current validation requirements check that methods have docstrings because UCAgent and diagnostic tools need explanations. Class-level `description` and method docstring responsibilities differ: `description` explains business checks to the stage and user, while method docstring explains calls and returns to maintainers. Neither can be empty.

## Automatic Fixture Generation Analysis

Source location: `tools/workflow_checker_generator/core.py`, symbol `_materialize_auto_tests()`.

The following is pseudo-code omitting implementation details; the full implementation is in the source above.

```text
if rule_type == "json_required_keys":
    fixtures[valid_path] = json.dumps({key: 0 for key in keys})
    fixtures[invalid_path] = json.dumps({key: 0 for key in keys[:-1]})
    tests = [
        {"expected_pass": True, ...},
        {"expected_pass": False, ...},
    ]
```

Automatic tests establish minimal positive and negative examples for generic rules. The negative example for required keys deletes only the last key, resulting in a single failure reason; the negative value for numeric ranges exceeds only the upper bound; `file exists` creates a file and ensures another path does not exist; `command exit code` uses an allowed command to produce 0 and non-0.

Automatic fixtures are suitable for proving basic template behavior but cannot replace business fixtures. A "field exists" Checker might still need to validate semantic relationships between fields; in such cases, an explicit fixture or inline Checker should be provided. Do not continuously add business-specific examples to generic templates, as this makes templates difficult to understand and imposes additional complexity on all workflows.

## Template Code Analysis: JSON Required Fields

Source location: `tools/workflow_checker_generator/templates.py`, symbol `_render_json_required_keys()`.

```python
target = self._resolve()
if not target.is_file():
    return False, {"error": "CHECKER-DATA-001: JSON result file not found"}
data = json.loads(target.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    return False, {"error": "CHECKER-DATA-002: JSON top-level must be mapping"}
missing = [key for key in self.required_keys if key not in data]
```

This code separates errors for missing files, parsing/type issues, and missing fields, allowing the Agent to take different remediation actions. `_resolve()` restricts the path to within the workspace, preventing the Checker from reading arbitrary system files via stage parameters. The return value is `(passed, evidence)`, where the evidence retains the path and missing keys rather than simply returning `False`.

Note that "key exists" does not verify value type or meaning. If business logic requires `status == completed` or a non-empty hash, a more suitable rule should be selected or a business-specific Checker written. Stuffing all conditions into the description of `required_keys` creates inconsistency between documentation and implementation.

## Template Code Analysis: Numeric Range and Commands

The `numeric range` template explicitly excludes `bool` because `bool` is a subclass of `int` in Python. The upper and lower bounds are closed intervals; changing them to open intervals would alter business semantics and requires synchronizing the spec and fixture. Fields that do not exist and non-numeric values currently share the same error branch; if the Agent's fix requires distinguishing these, a new error code and a single negative case can be added.

The `command exit code` template only allows `self.command[0]` to appear in `allowed_commands`, using an array parameter to call `subprocess.run()`, setting `cwd`, `capture`, `text`, and `timeout`. It does not concatenate via shell, so user parameters do not become pipes or redirects. `stdout`/`stderr` are truncated to the tail to avoid the Checker returning massive context.

Command whitelists need to be precise to executable programs, but verifying only the program name may still allow dangerous parameters. This is suitable for `python -m py_compile`, specific `make check`, etc., where control is assured; handling user-controlled arbitrary parameters requires adding parameter mode, working directory, and output path restrictions.

## Registration Code Analysis

Source location: `tools/workflow_checker_generator/core.py`, symbol `_register_checker()`.

```python
expected = {
    "name": spec["name"],
    "clss": f"{module_path}.{spec['entry']['class_name']}",
    "args": args if isinstance(args, dict) else {},
}
existing = next(item for item in checker_list if item.get("name") == spec["name"])
```

UCAgent configuration fields use `clss` instead of the usual spelling `class`. The generator is responsible for removing `.py` from file paths, converting slashes to dots, and then concatenating the class name. Manual registration easily misses this detail. Existing items with the same name are updated rather than appended repeatedly, ensuring stable stage invocation order.

The target stage is looked up before registration; if the stage does not exist, it must fail and cannot revert to the first stage. `args` must align with the Checker's `__init__`. The evaluation process should import the class, check the signature, and attempt instantiation to discover if the config passes or misses parameters.

## Checker Materialization Main Chain

Source location: `tools/workflow_checker_generator/core.py`, symbol `generate_checkers_from_specs()`.

The main chain parses each spec sequentially, performs structural validation, generates automated tests, writes explicit fixtures, selects inline source or template renderer, writes Checker source code, and optionally registers. Each action updates the `CheckerGenerationReport`. Any failure should point to the current spec to avoid ambiguity during batch generation regarding which item failed.

When `Builder` is invoked, `update_config=False` is typically used because the central stage contract injects configuration uniformly via the config generator; independent tools can register. Developers modifying the semantics of this switch must check for duplicate or missing registrations.

## Secondary Development Case: Extending Business Checker Generation Capabilities

The `DocumentIntegrityChecker` for DOCX workflows needs to prove the output is not merely an empty shell with a `.docx` suffix. Construction parameters include the workflow-relative document path, a list of required chapters, and a minimum image count. The check method uses `zipfile` or `python-docx` to parse the file, verifying ZIP integrity, body paragraphs, headings, relationship files, and image references, returning evidence for each.

Positive fixtures represent the minimal valid DOCX; negative fixtures separately cover damaged ZIPs, missing chapters, lost image relationships, and document path escape. The spec is registered to the stage after document generation, with the reference pointing to the specific DOCX and structured report. Developer documentation cites the actual parsing code, explaining why checking only file existence and size is insufficient.

If "page header must contain version" is added later, the requirement reference, Checker construction parameters, rules, fixtures, stage tasks, development documentation, and `eval_checkers` business coverage must all be updated. Adding a sentence in the description without changing the code is not sufficient.

## False Positive Diagnosis Methods

When encountering consecutive stage failures, first reproduce the Checker registration parameters in an independent direct runner. Then check sequentially: whether the input is already generated in the current stage; whether paths normalize to the same value; whether optional files are forced; whether the fixture represents the current schema; whether the Checker itself catches import/parsing exceptions; and whether the failure evidence corresponds to the actual branch.

Issues like `.//workflow/x` vs `workflow/x` being incorrectly judged by string comparison have occurred; such problems should be normalized at the path generation and comparison layer, not by requiring the Agent to read a strange string. Issues like "latest snapshot version must always equal current version" causing false positives during batch updates within the same phase should be limited to the same chapter or same checkpoint semantics.

## Extension Points, Modification Impact, and Regression Matrix

| Modification | Sync Scope |
| --- | --- |
| New rule type | spec validation, renderer, auto fixture, documentation, and regression |
| Modified construction parameters | template, register args, config, instantiation test |
| Modified path rules | `_safe_resolve`, template `_resolve`, symbolic links, and out-of-bounds fixtures |
| Modified error codes | FAQ, stage fix hints, evaluation evidence, and negative tests |
| Modified `clss` registration | UCAgent loading, config generation, static import regression |
| Modified business semantics | user requirements, central spec, positive/negative fixtures, stages, and development documentation |

Checker regression must simultaneously prove that passing cases pass and failing cases fail. Running only positive examples will allow error implementations with unconditional `return True` to pass all tests.

## Parent Builder Checker Complete Index

The following class definitions are in `tools/workflow_builder/uc_checkers.py`. Most classes inherit `WorkflowBuildConfigChecker`, sharing workspace path normalization, YAML/JSON reading, and evidence structure, but each class has a different business proof object.

| Checker Class | Check Object | Primary Failure Meaning | Secondary Dev Note |
| --- | --- | --- | --- |
| `WorkflowBuildConfigChecker` | Basic structure, paths, and core contract of `workflow_build.yaml` | Central design unparseable or unable to drive subsequent generation | Yes, shared base class; modifying generic paths/reading behavior affects almost all parent Checkers. |
| `WorkflowInputExampleManifestChecker` | User sample list, file existence, and categorization in `input_example_manifest.yaml` | Input contract incomplete regarding real samples | New sample types must express unknown/optional classification; do not hardcode specific business extensions. |
| `WorkflowBuildOutputChecker` | Builder initial products, directories, and reports | Builder returns success but fixed deliverables are missing | New deliverables must sync BuildReport and delivery regression. |
| `WorkflowMinimalInitChecker` | Minimal runnable skeleton of smoke workflow | Cannot complete generation loop before full implementation | Minimal does not mean empty shell; check only files committed in this stage. |
| `WorkflowEnvironmentSetupChecker` | Generated Makefile, `ucagent_setup.sh`, `setup.py`, schema, and requirements | Sub-workflow not portable or config ineffective | Distinguish Python dependencies from non-Python installation notes; test dry-run and repeated execution. |
| `WorkflowMCPToolIntegrationChecker` | Tool source code, config registration, import, parameters, and direct/MCP calls | Tool file exists but UCAgent unavailable | New return structures or adapters must change both direct and MCP evidence. |
| `WorkflowGeneratedCheckerChecker` | Generated Checker source code, docstring, fixture, registration, and positive/negative runs | Checker cannot load, parameters wrong, or judgment invalid | Prevent unconditional pass while avoiding false positives from future products in current stages. |
| `WorkflowGeneratedConfigChecker` | Syntax, required fields, and basic registration of generated config/inc | Runtime configuration unloadable | New schema fields must define compatible defaults before modifying generator and this Checker. |
| `WorkflowRuntimeConfigAuditChecker` | Stage reference/output specific files, reachability, placeholders, Tool/Checker/GuideDoc closures | Config parses but hangs at runtime or cannot read files | Normalize path comparisons; reference/output directories prohibited; do not write exceptions for specific `{INPUT}` appearances. |
| `WorkflowGeneratedGuideDocChecker` | Semantic chapters, operation evidence, registration, and detail level of generated GuideDoc | Agent can read docs but cannot execute steps | Handle multi-language titles via stable section IDs; do not hardcode Chinese titles. |
| `WorkflowMigrationPackageChecker` | Migration package file list, relative paths, hashes, extractability, and post-migration checks | Success on dev machine but fails on new system delivery | Must verify in new temporary root; do not pass due to accidental absolute path existence. |
| `WorkflowToolGenerationChecker` | Tool spec, generation status, basic source/test structure | Generation loop not established | Base class for tool Checkers; generic rules should not include specific business filenames. |
| `WorkflowGeneratedToolChecker` | Single smoke business Tool source code, spec, fixture, and run result | Representative Tool unavailable, batch generation untrustworthy | Check parameters should be provided by current spec; do not assume accidental files like `diag_checker*.py`. |
| `WorkflowBusinessToolGenerationChecker` | Count, generation, registration, testing, and requirement coverage of all planned business Tools | Only smoke Tools; business capability delivery incomplete | Allow subsequent new Tools, but each must return to manifest/spec and test evidence. |
| `WorkflowGuideDocSpecChecker` | Document spec target path, type, section ID, detail level, and registration plan | Batch document generation without planning | Distinguish GuideDoc and human docs; word count rules cannot be bypassed by code block flooding. |
| `WorkflowRequirementCoverageChecker` | Traceable mapping from requirements in requirements manifest to Tool, Checker, config, GuideDoc, docs | Products complete in form but deviate from user needs | Same category used with multiple aliases at different times; thresholds should increase with stages, not require final products initially. |
| `WorkflowImplementationPlanChecker` | Initial implementation plan stages, Tools, Checkers, GuideDocs, products, and action descriptions | Parent Agent fails to establish executable blueprint | Class/method docstrings and plan body detail must be tested; minimum examples must indicate non-meeting of positive word count. |
| `WorkflowLivingPlanChecker` | Per-stage markers, appended content, and predecessors | Subsequent stages disconnected from or overwrite predecessor design | Sync appender, FAQ, UI parsing, and living-plan regression after marker modification. |
| `WorkflowUserDocsChecker` | README, 01–05 user/dev docs, directories, word count, and real source analysis | Generated workflow unusable by humans or further development | Format requirements must maintain content freedom; source snippets must come from actual generated files. |
| `WorkflowDependencyChecker` | Python dependencies in `requirements.txt`, non-Python tool comments, and installation methods | Users cannot restore runtime environment | Do not fabricate unverified versions; optional system tools must explain downgrade behavior. |

## Complete Index of Evaluation and Incremental Checkers

The following class definitions are located in `tools/workflow_evaluation_control/uc_checkers.py`. They do not judge whether a business file is "good" or "bad," but rather verify whether evaluation/incremental reports collect evidence according to the contract, are bound by approval constraints, and are truly completed with deployment regression.

| Checker Class | Purpose | Secondary Development Focus |
| --- | --- | --- |
| `EvaluationJsonReportChecker` | Validates the schema, status, checks, findings, metrics, and run identity of a specified eval report | New fields must provide backward-compatible defaults for old runs; JSON parsing alone is insufficient. |
| `EvaluationGuideCoverageChecker` | Validates whether the eval/incremental GuideDoc covers required rules, severity levels, and execution constraints | New check IDs must synchronize with both the GuideDoc and the coverage list, but full long-form document reading per stage should not be required. |
| `StaticAuditCoverageChecker` | Confirms that static audit coverage includes all required rules within this evaluation domain | Must compare rule IDs against actual evidence; a single "audit success" boolean value is insufficient. |
| `IncrementalAuditCoverageChecker` | Confirms that the incremental phase has performed approval freshness, candidate, boundary, deployment, and regression audits | Audit rules must be synchronized after modifying the state machine to prevent scenarios where formal documents are replaced while awaiting re-approval. |
| `IncrementalContextReportChecker` | Validates the cognitive list, target approvals, index, and reading budget for the current inc run | "Preliminary understanding" should not be implemented as a full file read check-in; it must verify navigability rather than byte volume. |
| `IncrementalApprovalChecker` | Validates the source, run, fingerprint, decision, and current status of approvals/suggestions | Agents must not self-approve; old approvals must become invalid if the source finding changes. |
| `EvaluationStageGateChecker` | Checks whether the evaluation stage only executes allowed operations, writes reports correctly, and meets completion thresholds | When changing eval responsibility splitting, the gate must be synchronized to prevent `eval_tools` from exceeding boundaries or starting sub-processes in the evaluation environment. |
| `EvaluationEvidenceChecker` | Checks whether evidence for findings/checks points to specific files, symbols, commands, or results | Judgments without evidence cannot be used to deceive users into believing requirements are met; evidence paths must be traceable and non-invasive. |
| `IncrementalApplicationChecker` | Validates the mapping from approved targets to candidates, deployment records, hashes, backups, and incomplete item mappings | Generating a candidate plan is not equivalent to fixing; formal file results must be verified. |
| `IncrementalRegressionChecker` | Requires formal `make check` and related target success on top of application evidence | Regression failures must not be converted to pending solely due to deployment; they should continue to be fixed or rolled back within the original approval scope. |

## Configuration Alias and Implementation Class Mapping

The Checker `name` in the configuration is a stage semantic alias, while `clss` is the Python implementation. A single class can be used across multiple stages with different arguments and aliases. Developers adjusting class signatures must search for all mappings below and cannot rely on only the first search result.

| Implementation Class | Current Primary Configuration Alias |
| --- | --- |
| `WorkflowLivingPlanChecker` | `living_plan_update_check` |
| `WorkflowRequirementCoverageChecker` | `requirements_manifest_check`, `initial_build_requirement_coverage`, `initial_template_requirement_coverage`, `smoke_manifest_check`, `final_requirement_coverage` |
| `WorkflowImplementationPlanChecker` | `workflow_implementation_plan_check` |
| `WorkflowInputExampleManifestChecker` | `input_example_manifest_check` |
| `WorkflowBuildConfigChecker` | `workflow_build_config_check` |
| `WorkflowBuildOutputChecker` | `workflow_builder_output_check` |
| `WorkflowToolGenerationChecker` | `workflow_tool_generation_check` |
| `WorkflowGeneratedToolChecker` | `workflow_business_tool_spec_check`, `workflow_generated_tool_check`, `workflow_generated_tool_strengthened_check` |
| `WorkflowMinimalInitChecker` | `workflow_minimal_init_check` |
| `WorkflowEnvironmentSetupChecker` | `workflow_environment_setup_check` |
| `WorkflowMCPToolIntegrationChecker` | `workflow_mcp_tool_integration_check`, `full_mcp_tool_integration_check` |
| `WorkflowRuntimeConfigAuditChecker` | `runtime_config_reference_audit` |
| `WorkflowGuideDocSpecChecker` | `guidedoc_spec_check` |
| `WorkflowGeneratedGuideDocChecker` | `generated_guidedoc_check` |
| `WorkflowUserDocsChecker` | `generated_user_docs_check` |
| `WorkflowDependencyChecker` | `generated_dependency_check` |
| `WorkflowMigrationPackageChecker` | `generated_migration_package_check`, `final_migration_package_check` |

In `inc.yaml`, `generated_workflow_context_complete` maps to `IncrementalContextReportChecker`; `approved_changes_deployed` maps to `IncrementalApplicationChecker`; `applied_changes_have_approval` and `all_current_approvals_deployed` map to `IncrementalApprovalChecker`; `incremental_report_complete` maps to `EvaluationJsonReportChecker`; `incremental_guide_complete` maps to `EvaluationGuideCoverageChecker`; `incremental_static_audit_covered` maps to `IncrementalAuditCoverageChecker`; and `incremental_make_check_passed` maps to `IncrementalRegressionChecker`.

In each `eval_*.yaml`, report aliases `tools_report_complete`, `checkers_report_complete`, `flow_report_complete`, `env_report_complete`, and `run_report_complete` map to `EvaluationJsonReportChecker`; guide aliases `tools_guide_complete`, `checkers_guide_complete`, `flow_guide_complete`, `env_guide_complete`, `run_guide_complete`, and `evaluation_contract_complete` map to `EvaluationGuideCoverageChecker`; and `deterministic_audit_covered` maps to `StaticAuditCoverageChecker`. `EvaluationStageGateChecker` and `EvaluationEvidenceChecker` belong to composable gate capabilities; if newly registered in the configuration, they must supplement alias, args instantiation, and stage evidence regression.

## Standard Steps for Modifying Checkers

1. First, write a provable proposition stating "what exactly is proven when it passes," then determine whether this is a parent construction, an evaluation incremental, or a generated business Checker.
2. List all specific files and fields that currently exist in this stage; set future outputs as post-stage checks or explicitly optional, prohibiting the use of directories to replace reference files.
3. Implement stable docstrings, construct parameters, path normalization, branch error codes, and meaningful evidence; do not catch all exceptions and masquerade as business failures.
4. Search all YAML files for the corresponding `clss` and alias, verifying that argument names, types, requiredness, and default values match the signature.
5. Add minimal positive fixtures, negative fixtures destroying only one condition at a time, boundary fixtures, import/instantiation tests, and configuration integration tests.

## Continue Reading

Checkers tell the Agent "what constitutes completion," while GuideDocs tell the Agent "how to achieve it repeatably." Please continue reading [GuideDoc Introduction](04_guide_docs.md) to understand how stage guidance, FAQs, minimal examples, and Checker semantics remain consistent.
