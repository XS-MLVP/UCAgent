
# Getting Started with Custom Development

Creating a workflow typically requires four types of resources:

- **Workflow Configuration**: Defines stage order, tasks, reference files, outputs, and Checkers;
- **Tools**: Enable the Agent to read, compute, test, or invoke domain services;
- **Guide_Doc/Templates**: Specify output structure, tags, and evidence formats;
- **Checker**: Accept stage artifacts using deterministic rules.

It is recommended to first run the [Mini Example](08_mini_example.md), then replace the Calculator in the example with your own input.

## 1. Minimum Directory Structure

```text
MyWorkflow/
├── Guide_Doc/
├── mini.yaml
├── my_tools.py
├── my_checkers.py
├── __init__.py
└── README.md
```

The `Makefile` is optional and is responsible only for preparing the workspace and constructing the startup command.

## 2. Workflow Configuration

Below is the minimal structure consistent with the current parser:

```yaml
ex_tools:
  - "my_tools.CountWords"

template_overwrite:
  PROJECT: "Calculator"

mission:
  name: "{PROJECT} Document Generation"
  prompt:
    system: "You are a technical documentation engineer."

stage:
  - name: analyze_project
    desc: "Analyze project"
    task:
      - "Read {PROJECT}/README.md"
      - "Write {OUT}/{PROJECT}_analysis.md"
    reference_files:
      - "Guide_Doc/project_analysis_guide.md"
    output_files:
      - "{OUT}/{PROJECT}_analysis.md"
    checker:
      - name: markdown_check
        clss: "UnityChipCheckerMarkdownFileFormat"
        args:
          markdown_file_list: "{OUT}/{PROJECT}_analysis.md"
          no_line_break: true
    skill_list: []
    force_use_skill: false
```

Field descriptions:

- `ex_tools` registers the full import path of external tool classes;
- `template_overwrite` provides custom template values such as `{PROJECT}`; the output directory is specified via the CLI option `--output`;
- `mission.prompt.system` is the global system prompt;
- `stage` is a list of stages executed in order; stages can nest `stage` sub-stages;
- `reference_files` and `output_files` use relative paths within the workspace;
- `checker[].args` are passed to the Checker constructor, while `extra_args` are used to add new attributes after instantiation and cannot override existing attributes;
- `skill_list` enters the stage skill gatekeeper only if skills are enabled and the list is non-empty. Skills are forced by default; set `force_use_skill: false` to make them optional.

Configuration loading and list replacement rules are documented in [Workflow Configuration](03_workflow.md).

## 3. Providing Tools

The `my_tools.CountWords` in the example configuration must be an importable, zero-argument instantiable tool class. It is recommended to inherit from `UCTool`, define parameters using Pydantic `BaseModel`, and implement the real `_run` behavior.

First, refer to the complete implementation in [Customize Tools](05_customize.md) to verify local invocation and MCP schema conversion, then register it in `ex_tools`. If only tasks and documentation specifications need adjustment, existing tools can be used without creating new tool classes.

## 4. Defining Acceptance

The above Markdown Checker validates format; if tasks also require word count, specific sections, or business rules, corresponding Checkers must be added. The Mini Example provides `WordCountChecker` and `RequiredSectionsChecker`.

Custom Checkers must validate real artifacts and clearly indicate location, expected conditions, and remediation actions upon failure. A complete, usable file existence check example is available in [Custom Checker](07_checkers.md); do not use placeholder implementations that unconditionally return `True` to accept a stage.

## 5. Writing Guide_Doc and Skills

Guide_Doc should describe the complete format and examples that the Agent must produce at the current stage, using runtime relative paths, such as `Guide_Doc/project_analysis_guide.md`. If skills are used:

- The first line of `SKILL.md` must be `---`, and the frontmatter must contain at least `name` and `description`;
- Scripts are placed in `scripts/` and executed via `RunSkillScript`;
- `RunSkillScript` loads `ucagent_python_path` from the runtime snapshot to prepare import paths for Python scripts; scripts read the already-parsed runtime configuration;
- If a skill is disabled or its directory does not exist, the stage must still be completable using ordinary tools and Checkers.

## 6. Launching Custom Workflow

Taking `examples/MiniWorkflow` as an example, the startup commands are:

```bash
cd examples/MiniWorkflow
make test
make run ARGS="--loop"
```

Equivalent core command:

```bash
PYTHONPATH=. ucagent ./output/ Calculator \
  --config ./mini.yaml \
  --guid-doc-path ./Guide_Doc/ \
  -s -hm --tui --loop
```

First, configure the model according to [Direct Usage](../02_usage/01_direct.md#1-configure-the-model). `PYTHONPATH=.` makes `my_tools` and `my_checkers` in the current directory importable; `--guid-doc-path` specifies the custom Guide_Doc. The Makefile cleans and prepares `output/`; before manually executing the core command, `Calculator/` must also be copied into the workspace.

When execution requires an external Code Agent, use `make run ARGS="--mcp-server --backend=codex"`, then connect according to [MCP Access](../01_start/03_mcp_mode.md#33-manual-dual-terminal-integration-using-codex-as-an-example). Here, full file tools are enabled to satisfy the `EditTextFile` requirement in the Mini task.

After launch, use `status`, `current_tips`, and `tool_list` to check the task; stages must pass `Check`/`Complete` upon completion. For more complete configurations, see [Mini Example](08_mini_example.md).
