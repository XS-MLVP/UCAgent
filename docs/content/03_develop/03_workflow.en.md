
# Workflow Configuration

A workflow consists of a set of stages executed in sequence. Each stage describes tasks, reference files, expected outputs, and a Checker; the Agent can call `Check` to view feedback, then use `Complete` to perform final acceptance and proceed. If a stage fails, it should first be fixed according to the Checker's diagnosis before retrying.

## 1. Default Workflow

The default Chinese configuration is located at `ucagent/lang/zh/config/default.yaml`, which currently has 20 top-level stages; indented entries are sub-stages. The runtime Stage Manager flattens parent and child stages, therefore indices used by `--skip`, `hmcheck_set`, and `GoToStage` must be based on the current `status` or `hmcheck_list` in the active run.

| Top Index | Stage | Default Status |
| ---: | --- | --- |
| 0 | `requirement_analysis_and_planning` | Executing |
| 1 | `dut_function_understanding` | Executing |
| 2 | `functional_specification_analysis`: FG, FC, CK, line-by-line mapping sub-stages | Executing |
| 3 | `functional_specification_refine` | Executing |
| 4 | `static_bug_analysis` | Executing |
| 5 | `dut_wrapper_implementation`: DUT creation, pytest fixture | Executing |
| 6 | `coverage_model_implementation`: coverage groups, coverage points, batch implementation | Executing |
| 7 | `test_environment_implementation`: env, Bundle, Mock, and fixture | Partially human-checked, default skip |
| 8 | `basic_api_implementation` | Executing |
| 9 | `reference_model_implementation` | Executing when `NEED_REF_MODEL=true` |
| 10 | `reference_model_fixture_imp` | Executing when `NEED_REF_MODEL=true` |
| 11 | `basic_api_functional_test` | Executing |
| 12 | `create_test_case_templates` | Executing |
| 13 | `comprehensive_verification_and_bug_analysis`: batch implementation of test cases | Executing |
| 14 | `refine_test_cases_based_on_functional_points` | Executing |
| 15 | `static_bug_validation` | Executing |
| 16 | `line_coverage_analysis_and_improvement` | Default skip |
| 17 | `generate_random_test_cases` | Executing |
| 18 | `verification_review_and_summary` | Executing |
| 19 | `record_and_report_bugs` | Executing |

In the default configuration, `human_check_env_specification`, `human_check_env_implementation`, and `line_coverage_analysis_and_improvement` use `skip: true`; whether they actually execute is also subject to environment variables and project override configurations. Formal, Vibe, and Increment are independent configurations with different stage counts and names, and cannot be applied using the table above.

## 2. Stage Fields

The minimum stage structure is as follows:

```yaml
stage:
  - name: analyze_project
    desc: "Analyze project and generate report"
    task:
      - "Read {DUT}/README.md"
      - "Write results to {OUT}/{DUT}_analysis.md"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{DUT}_analysis.md"
    checker:
      - name: markdown_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{DUT}_analysis.md"
          no_line_break: true
    skill_list: []
    force_use_skill: false
    skip: false
```

- `name`: Stable stage identifier. LLMs recommend using it for filtering, history, and logs.
- `desc`: Stage title; may contain template variables provided by the Checker.
- `task`: Task list for the Agent. Clearly specify input, actions, output format, and completion criteria.
- `reference_files`: Relative paths or globs in the workspace that the stage needs to read. If required reference files are missing at runtime, fix the configuration or input.
- `output_files`: Paths or globs that must exist as outputs of the stage; each pattern must match a path; content correctness is still verified by the Checker.
- `checker`: Verification gates executed in sequence. `Complete` can only proceed after all gates pass.
- `stage`: List of sub-stages. A parent stage only enters parent stage acceptance after its sub-stages are completed.
- `skip`: Whether to default skip; suitable only for stages clearly not applicable.
- `need_human_check`: Wait for human review after passing the Checker.
- `skill_list`: Specialized skills for the current stage. When a skill is enabled and the list is non-empty, a real list/read/use evidence is required by default; `force_use_skill: false` makes it optional.

## 3. Configuration Loading and Template Variables

Configuration is loaded in the following order, with later layers overriding earlier ones:

1. `ucagent/setting.yaml`
2. `~/.ucagent/setting.yaml`
3. `ucagent/lang/<lang>/config/default.yaml`
4. Workspace `./.ucagent/setting.yaml`
5. File specified by `--config` (defaults to `config.yaml` if not specified)
6. CLI arguments and `--override`

When selecting a plugin workflow, its configuration baseline is inserted after the language default configuration and before the workspace configuration; see [Plugin Development and Release](09_plugins.md). The project configuration search scope includes the current startup directory, `~/.ucagent/`, and the language configuration directory; relative `--config` paths are not default relative to the workspace.

List fields (especially `stage`, `checker`, `reference_files`) are replaced as a whole, not merged item by item by project name. When modifying default stages, copy the complete list and edit.

Common template variables:

| Variable | Meaning |
| --- | --- |
| `{DUT}` | DUT subdirectory name |
| `{OUT}` | Output directory under the workspace, default `unity_test` |
| `{WORKSPACE}` | Absolute path of the current workspace |
| `{GUIDE_DOC}` | Runtime `Guide_Doc` path in the workspace |
| `{DOC_GEN_LANG}` | Document language, from template configuration |

`{OUT}` is determined by `--output` (default `unity_test`) during the first configuration render. To change the output path, use this option; do not just modify `template_overwrite.OUT`.

Environment variable substitution occurs during YAML loading, e.g., `$(NEED_REF_MODEL: false)`; template variables like `{DUT}` and `{OUT}` are rendered after configuration parsing. Do not re-read raw environment variables at runtime to infer the already-parsed configuration.

## 4. Skip, Rollback, and Human Review

Temporarily skip a stage:

```bash
ucagent <workspace> <DUT> --skip <runtime_stage_index>
ucagent <workspace> <DUT> --unskip <runtime_stage_index>
```

Used during runtime:

```text
skip_stage <runtime_stage_index>
unskip_stage <runtime_stage_index>
tool_invoke GoToStage index=<runtime_stage_index>
hmcheck_set <runtime_stage_index> true
```

The index is the flattened runtime index; do not continue using old numbers after modifying the workflow. `GoToStage` can only go back to stages already reached. Skipping a stage does not generate the files it should have produced; subsequent Checkers may fail as a result; only skip if the stage is confirmed not applicable.

## 5. Checker Configuration

Checker classes are specified via `clss`, short names are imported from `ucagent.checkers`, and full paths can point to custom modules:

```yaml
checker:
  - name: word_count
    clss: "my_workflow.checkers.WordCountChecker"
    args:
      file_path: "{OUT}/{DUT}_analysis.md"
      word_min: 200
      need_human_check: false
```

`args` are passed to the constructor and `cfg` is automatically injected; `extra_args` are set via `set_extra` after instantiation, cannot override existing attributes, and cannot replace constructor parameters or dedicated setters. Whether `need_human_check` takes effect depends on whether the Checker's constructor handles it; alternatively, set `need_human_check: true` directly on the stage.

See [Custom Checker](07_checkers.md) for full implementation, lifecycle, and structured diagnosis of custom Checkers.

## 6. Batch Stages

Stages for feature coverage, test templates, test cases, and line mapping use `UnityChipBatchTask` to manage progress. When configuring batch tasks:

- Set `batch_size` before constructing `UnityChipBatchTask`;
- Use the current source document and test files as the source of truth; checkpoints are only for recovery;
- Resynchronize source/generated tasks after source file changes, delete or mark expired tasks;
- Complete the current batch with `Check` and expose the next batch; `Complete` is used only after all batches pass;
- Failure diagnosis returns only a bounded missing range and the next step; do not dump the entire source or logs into the prompt.

The functional line mapping stage has additional constraints: `file_list` is the authoritative input; do not treat `Guide_Doc` as a mapping target; every non-empty physical line must have FG/FC/CK or a justified `IGNORE`; an interval can have at most 100 lines. See `Guide_Doc/dut_line_func_map.md` and `functional_line_mapping_gap_analysis` in the default configuration.

## 7. Custom Workflows

Do not modify `default.yaml` directly within the package. Instead, copy the complete `stage` list that needs modification in the project configuration, or use `--override` for targeted temporary overrides:

```bash
ucagent <workspace> <DUT> \
  --config config.yaml \
  --override 'runtime_options.need_ref_model=True'
```

When adding a new stage, provide the task, reference document, output, and Checker simultaneously; if the stage requires skills, ensure that the same goal can still be achieved using standard tools and Checker when skills are disabled. Stage-specific skills, Guide_Doc, templates, and scripts collectively form the runtime contract, and any change at any layer should be tested synchronously.

## 8. Runtime Snapshot

After configuration parsing, UCAgent writes `.ucagent/runtime_config.json` to the workspace. It contains only parsed, non-sensitive fields, such as `DUT`, `OUT`, `runtime_options`, `current_test_report`, and `ucagent_python_path`. Skill scripts should read this snapshot; do not guess the source code path from the script location or re-interpret environment variables. The `ucagent_python_path` in the snapshot must be an absolute path containing the current `ucagent/__init__.py`.

Next: Run the [Mini Example](08_mini_example.md) first, then learn [Custom Tools](05_customize.md), [Template Files](04_template.md), and [Plugins](09_plugins.md) as needed.
