
# Master Mode

Master is used to create, launch, and monitor multiple verification tasks. The browser panel is responsible for creating workspaces, uploading and compiling RTL, dispatching tasks, and viewing logs.

## 4.1 Starting Master

In the source code repository:

```bash

# Temporary Master workspace

make as_master

# Specify or use the default persistent workspace (default /tmp/ucagent_master)

make as_master_persist
```

Without using the Makefile:

```bash
ucagent --as-master --export-cmd-api
ucagent --as-master-persist --as-master
```

`--as-master-persist` must be used together with `--as-master`. The default Master address comes from the `master_api` configuration, typically `http://127.0.0.1:8800`; add `--as-master-password <password>` to protect the panel, and add `--as-master-key <key>` to restrict client registration.

## 4.2 Creating and Compiling Tasks

1. Open the Master address in a browser and navigate to **Launch**.
2. Create a workspace and upload RTL, README, or other requirement files.
3. Mark one **Main RTL** (you may also provide a filelist) and mark the verification requirement file as **Verification Needs**.
4. Select the top-level module and click **Compile**. Compilation is performed by the picker; syntax or parameter errors must be fixed based on the Compile Console.

Labels and page fields may vary by version; refer to the current page's required field prompts and command preview. A successful compilation only indicates that the DUT package was generated successfully; it does not imply that verification is complete.

## 4.3 Launching Sub-Agents

Select the following in **Launch Settings**:

- **Config Path**: Typically select `UT`, which corresponds to the default unit test workflow; you may also select Formal, Vibe, or Increment if provided in the configuration.
- **Backend**: Defaults to `launch.default_args.backend`, currently `opencode`; you may also select configured backends such as `langchain` or `codex`.
- **Launch Mode**: Defaults to `process`; Docker, Docker Swarm, and Kubernetes are also supported (requiring the corresponding environments).
- **CLI Flags**: Enable TUI, streaming output, or exit-after-completion as needed.

Fill in model-related environment variables in **Environment Variables**. See the [Web Master User Guide](../02_usage/07_web_master.md) for sub-Agent configuration details. After clicking **Launch Task**, Master starts the sub-Agent and waits for it to register via `--master`.

## 4.4 Monitoring and Review

- **Dashboard**: View Agent online status, progress, and offline tasks.
- **Task**: View launch commands, stdout/stderr, and task status; stop or delete managed tasks.
- **Agent**: View phases, files, and Diffs; batch switch between HM, Skip, LFail, and LPass.
- **Web Terminal**: Access the sub-Agent's terminal; whether it can run in parallel with the local terminal depends on the sub-Agent's launch parameters.

Whether there are bugs, waveforms, or coverage reports ultimately depends on the workflow, test results, and configuration. Rely on the actual artifacts in the workspace, Checker return values, and `uc_test_report/`; do not treat the completion status displayed on the page as proof of DUT correctness.

For more page capabilities, agents, and access control, see the [Web Master User Guide](../02_usage/07_web_master.md).
