
# Mini Example

The `examples/MiniWorkflow/` directory is a runnable two-stage workflow: the first stage analyzes the Calculator's README, and the second stage generates project documentation. It demonstrates the minimal combination of configuration, external tools, Guide_Doc, and custom Checkers.

## 1. Directory and Inputs

```text
examples/MiniWorkflow/
├── Calculator/README.md
├── Guide_Doc/
│   ├── project_analysis_guide.md
│   └── documentation_template.md
├── mini.yaml
├── my_tools.py
├── my_checkers.py
└── Makefile
```

The `mini.yaml` file uses the current workflow fields: `ex_tools`, `template_overwrite`, `mission`, `stage`, `reference_files`, `output_files`, and `checker`. The startup command uses `output/` as the workspace; since `--output` is not passed, the stage artifacts are actually located at `examples/MiniWorkflow/output/unity_test/`. When changing the output directory, pass `--output <name>` and verify the path using the current stage information.

## 2. Running

First, complete the [source installation](../01_start/00_installation.md#12-installing-the-ucagent-main-package), activate the virtual environment, and then follow the [direct usage](../02_usage/01_direct.md#1-configure-the-model) to configure the model. Execute from the repository root:

```bash
cd examples/MiniWorkflow
make test
make run ARGS="--loop"
```

`make test` only checks if custom tools and Checkers can be imported. `make run` will clean and create `output/`, copy Calculator, and then start UCAgent:

```bash
PYTHONPATH=. ucagent ./output/ Calculator \
  --config ./mini.yaml \
  --guid-doc-path ./Guide_Doc/ \
  -s -hm --tui --loop
```

The `--loop` flag enables immediate execution in normal mode; running only `make run` will pause at the TUI, requiring input of `loop` to begin. `PYTHONPATH=.` is used to import `my_tools` and `my_checkers` from the current directory, which the Makefile sets automatically.

When an external Code Agent is required, use:

```bash
make run ARGS="--mcp-server --backend=codex"
```

This command does not automatically enter the model loop. In another terminal, enter `examples/MiniWorkflow/output/` first, then follow [MCP Access](../01_start/03_mcp_mode.md#33-manual-dual-terminal-integration-using-codex-as-an-example) to configure and start Codex. The Mini task requires using `EditTextFile`, so full MCP file tools are enabled here.

You can also copy the entire `MiniWorkflow/` directory to another directory and run it; the installed UCAgent will start via the `ucagent` command, while custom tools and Checkers are imported from the current example directory.

The example workflow does not require embedded tools by default; the current CLI's `--no-embed-tools` is already set to `true` by default, so there is no need to add this parameter again.

## 3. What the Workflow Does

Stage `analyze_project`:

1. Reads `Calculator/README.md` and `Guide_Doc/project_analysis_guide.md`;
2. Generates `unity_test/Calculator_analysis.md` (relative to workspace);
3. Uses `CountWords` to provide statistics;
4. Accepts using a word count and Markdown format Checker.

Stage `generate_documentation`:

1. Reads the analysis document and `Guide_Doc/documentation_template.md`;
2. Generates `unity_test/Calculator_documentation.md` (relative to workspace);
3. Uses `ExtractSections` to check sections;
4. Accepts using word count, required sections, and Markdown format Checkers.

All stages must pass through `Check`/`Complete`. If a Checker fails, fix it according to the returned file and field, then retry.

## 4. Viewing Results

```bash
cat output/unity_test/Calculator_analysis.md
cat output/unity_test/Calculator_documentation.md
```

The actual word count and content are determined by the model output; do not treat the word count ranges in the example as universal requirements for all workflows.

## 5. Modifying the Example

### Adding a Stage

Append a complete stage to the `stage` list in `mini.yaml`:

```yaml
- name: generate_api_docs
  desc: "Generate API documentation"
  task:
    - "Read existing analysis and template, generate {OUT}/{PROJECT}_api.md"
  output_files:
    - "{OUT}/{PROJECT}_api.md"
```

Add a Checker for this stage if reliable acceptance is required.

### Adding a Tool

Define a class inheriting `UCTool` in `my_tools.py`, describe parameters using Pydantic `args_schema`, and then register the full import path in `ex_tools` within `mini.yaml`. Tools must only access paths allowed within the workspace.

### Adding a Checker

In `my_checkers.py`, inherit `Checker`; in the constructor, call `super().__init__()` first, and in `do_check` return `(bool, result)`. Failure results should include a stable `error_code`, specific `error`, and `next_action`.

## 6. Further Learning

- [Custom Development Intro](01_quick_start.md): Build configuration, tools, and Checkers from scratch.
- [Workflow Configuration](03_workflow.md): Stages, template variables, batching, and stage indexing.
- [Custom Tools](05_customize.md): Local tools and MCP schema.
- [Checkers](07_checkers.md): Lifecycle, diagnostics, and batching conventions.
- [Plugin Development and Release](09_plugins.md): Package workflow resources as installable plugins.
