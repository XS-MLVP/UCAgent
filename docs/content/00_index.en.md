
<div class="uc-home-hero" markdown="1">

<div class="uc-home-eyebrow">UCAGENT / DOCUMENTATION</div>

# UCAgent Documentation

UCAgent is an AI verification agent for digital circuit unit testing. It reads the DUT and verification requirements, generates documents, tests, and coverage models in stages, runs tests, and retains reports that can be reviewed. Deterministic Checkers validate each stage. You can intervene manually or connect an external coding agent through MCP.

<div class="uc-home-actions" markdown="1">

[Get started](./01_start/00_installation.md){ .md-button .md-button--primary }
[Choose a run mode](./01_start/01_modes_overview.md){ .md-button }

</div>
</div>

## Complete Your First Run

If you are new to UCAgent, start with these pages:

<div class="uc-start-steps" markdown="1">

1. [Prerequisites and installation](./01_start/00_installation.md): install UCAgent, picker, and an optional coding agent.
2. [Run modes](./01_start/01_modes_overview.md): choose normal mode, MCP integration, or Master mode.
3. Follow either [normal mode](./01_start/02_normal_mode.md), which connects to a model through LangChain, or [MCP integration](./01_start/03_mcp_mode.md), which uses an external coding agent such as opencode.
4. [Results and workflow summary](./01_start/06_summary.md): understand the workspace and verification artifacts.

</div>

Read [Master mode](./01_start/04_master_mode.md) when you need to manage multiple tasks centrally.

## Responsibilities

- picker exports RTL as a Python DUT package; UCAgent manages verification workflows and their artifacts.
- UCAgent does not define the DUT specification for you. Prepare the README, RTL, and other references first. A failed test must be checked against the specification to distinguish a test problem from a DUT defect.
- Run modes share workflows and Checkers, but use different model connections, process arrangements, and interaction interfaces.

## Documentation Map

### Getting Started

1. **[Prerequisites and installation](./01_start/00_installation.md)**: environment setup and preparation for model configuration.
2. **[Run modes](./01_start/01_modes_overview.md)**: normal and Master modes, backends, and interaction interfaces.
3. **[Normal mode](./01_start/02_normal_mode.md)**: prepare a DUT, configure a model, and run verification in the terminal.
4. **[MCP integration](./01_start/03_mcp_mode.md)**: connect an external coding agent.
5. **[Master mode](./01_start/04_master_mode.md)**: manage multiple tasks through the web interface.
6. **[Tasks, workspaces, and workflows](./01_start/05_architecture.md)**: inputs, artifacts, and acceptance criteria.
7. **[Results and workflow summary](./01_start/06_summary.md)**: read results and review a completed run.

> Complete one task in normal or MCP mode before moving to Master, multiple instances, or batch execution. Replace example values such as `<workspace>` and `<DUT>` in commands. In configuration files, `{WORKSPACE}`, `{DUT}`, and `{OUT}` are UCAgent template variables; `{OUT}` defaults to `unity_test`.

### User Guide

- **[Direct use](./02_usage/01_direct.md)**: run locally with the LangChain backend.
- **[Human–agent collaboration](./02_usage/02_assit.md)**: pause, inspect, repair, and resume verification.
- **[CLI options](./02_usage/03_option.md)**: command-line arguments and environment variables.
- **[TUI](./02_usage/04_tui.md)**: terminal interface and shortcuts.
- **[FAQ](./02_usage/05_faq.md)**: common questions.
- **[LLM Check and Refinement](./02_usage/06_llm_check.md)**: optional stage reviews and repair suggestions.
- **[Web Master guide](./02_usage/07_web_master.md)**: web interface reference.
- **[Skills](./02_usage/08_skill.md)**: optional task guidance and scripts.
- **[Graphical applications with Xpra](./02_usage/09_web_xpra.md)**: graphical applications in the browser.

### Development

- **[Overview](./03_develop/00_index.md)**: development learning path.
- **[Development quick start](./03_develop/01_quick_start.md)**: create a custom workflow.
- **[Architecture](./03_develop/02_architecture.md)**: components and execution.
- **[Workflow configuration](./03_develop/03_workflow.md)**: stages, configuration layers, and template variables.
- **[Templates and generated artifacts](./03_develop/04_template.md)**: runtime guidance and output files.
- **[Custom tools](./03_develop/05_customize.md)**: implement and register tools.
- **[Tool reference](./03_develop/06_tool_list.md)**: built-in tools.
- **[Waveform formats and extensions](./03_develop/10_waveform_analysis.md)**: configure and extend waveform analysis.
- **[Checkers](./03_develop/07_checkers.md)**: implement deterministic acceptance rules.
- **[Mini example](./03_develop/08_mini_example.md)**: a complete runnable workflow.
- **[Plugin development and distribution](./03_develop/09_plugins.md)**: package and publish extensions.

### Examples

- **[RTL2Spec documentation generation](./04_case/00_rtl2spec.md)**: generate design documents from XiangShan source and RTL evidence.
- **[Concurrent instances](./04_case/01_multirun.md)**: verify multiple DUTs concurrently.
- **[Batch execution](./04_case/02_batchrun.md)**: run a series of verification tasks.
- **[Workflow Builder](./04_case/03_workflow_builder/00_index.md)**: build, evaluate, and iterate on custom workflows.
