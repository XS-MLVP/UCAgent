
# Understanding Tasks, Workspaces, and Workflows

After completing the onboarding process, you can understand UCAgent through four concepts: input materials, workspace, workflow, and acceptance. These determine what the Agent does, where files are located, and when it can proceed to the next stage.

## Input Materials

The default ToffeeUT workflow uses RTL and independent requirement documents, then simulates through a Picker-exported DUT Python package. Make or Master Launch can compile it beforehand, or the workflow can use `BuildToffeeDUT`. Starting `ucagent` alone does not mean compilation or verification has completed.

`<workspace>/<DUT>/README.md` should describe the interfaces, timing, functionality, and verification goals. If the requirements are incomplete, the materials should be supplemented first to avoid letting the Agent guess the design behavior. Custom documentation workflows can use other types of inputs and do not necessarily require a DUT package.

## Workspace and Output Directory

`workspace` is the permitted project directory; `--output` overrides the workflow's artifact directory. The default ToffeeUT workflow uses `ut_project`. For example:

```text
output/                     # workspace passed at startup
├── Adder/                  # DUT package, source code, and requirements
├── Guide_Doc/              # Runtime guidance documents
├── ut_project/             # Current verification project
│   ├── docs/               # Specifications, reviews, and delivery reports
│   ├── testbenches/        # Verification environment and tests
│   └── results/            # Actual execution reports and receipts
└── .ucagent/               # Runtime configuration and task status
```

Specific artifacts depend on the workflow, enabled stages, and test results. The waveform format and storage location are determined by the DUT and test configuration; launching the task itself does not guarantee the generation of waveforms or complete reports. See [Result Analysis and Workflow Summary](06_summary.md) for how to read the results.

## Workflow and Acceptance

A workflow is a sequence of ordered stages. Each stage specifies the task, reference files, expected output, and Checker. The Agent uses tools to complete the task, then calls `Check` to view the acceptance results; only after calling `Complete` and passing the final checks and applicable gates can it proceed to the next stage.

Framework prompts and selection defaults live in `ucagent/core/locales/zh.yaml`. Its `workflow` selector points to `ucagent/plugins/ToffeeUT/src/toffee_ut/workflows/ut.yaml` (`toffee-ut:ut`). The framework bundles ToffeeUT and UnitTest resources; UnitTest requires explicit selection and a separate legacy environment. Install other plugins such as Formal separately or load them from source with `--plugin` and `--plugin-workflow`. Use `--config <file>` for configuration overrides. See [Workflow Configuration](../03_develop/03_workflow.md).

## Configuration and Launch Entry Points

- `ucagent/setting.yaml` provides global default settings for the backend, tools, and launch.
- Language configurations provide workflows and task prompts for the corresponding language.
- User configuration, workspace configuration, project `--config`, and CLI overrides collectively determine the configuration for the current run; see [Workflow Configuration](../03_develop/03_workflow.md#3-configuration-loading-and-template-variables) for the loading order.
- The `Makefile` in the source repository encapsulates workspace preparation and CLI commands; after installation via pip, the `ucagent` command can be used directly.

The TUI and Web pages are the operational entry points, the backend handles model interaction, and the workflow definition verifies the tasks. Selecting an interface does not automatically change the acceptance criteria. If you need to extend the framework, read [Architecture and Working Principles](../03_develop/02_architecture.md).
