
# Tool List

This page lists the primary tools by purpose. The actually available tools are determined by the workflow, plugin, skill switch, and tool filter configuration; names and parameters are subject to the schema of this run. Use `tool_list` in the console to view current tools; see [Customize Tools](05_customize.md) for custom implementations.

## Phases and Verification

| Tool | Purpose |
| --- | --- |
| `RoleInfo` | Retrieve role, system task, and constraints |
| `Status` / `CurrentTips` / `Detail` | View phase status, current task tips, and detailed information |
| `Check` | Check current phase; batch phases can advance to the next batch upon passing |
| `Complete` | Execute final checks and applicable gates; advance phase upon success |
| `GoToStage` | Return to a previously reached phase |
| `KillCheck` | Abort an ongoing check |
| `StageJournal` / `AllStageJournal` / `SetCurrentStageJournal` | Read or record phase logs |
| `StageDiff` / `StageCommit` | View or record phase artifact changes |
| `HumanHelp` | Request human assistance |
| `Exit` | Request exit according to current task rules |

`Check` and `Complete` are not success declarations: they read the current artifacts and execute the Checker. The `stage_args` parameter in arguments is used for additional inputs supported by the current Checker; `full_output: true` can request the raw check result. See [Workflow Configuration](03_workflow.md) for verification rules.

## Files and Text

All paths should be relative to the current workspace. Writes are subject to UCAgent's writable directory and no-write configuration constraints.

| Tool | Purpose and Key Parameters |
| --- | --- |
| `ReadTextFile` | Read text; `path`, `start` (1-based), `count`. Also serves as phase reference files and skill read records |
| `ReadBinFile` | Read byte range of binary files |
| `PathList` | List directory structure by depth |
| `FindFiles` | Find files by filename pattern |
| `SearchText` | Search text or regex, with optional file, hit count, and context range limits |
| `EditTextFile` | Create or overwrite full text; supports `append` and `expected_sha256` for concurrent modification checks |
| `ReplaceStringInFile` | Precisely replace unique non-empty text; supports `line_blocks` limit, SHA-256, and `dry_run` |
| `DeleteTextLines` | Delete single lines or closed intervals by physical line number from pre-deletion snapshot; supports SHA-256 |
| `CopyFile` / `MoveFile` | Copy or move files, with option to specify overwrite behavior |
| `DeleteFile` | Delete file; path and confirmation parameters provided by schema |
| `CreateDirectory` | Create directory |
| `GetFileInfo` | View file size, modification time, and other information |

Example for `DeleteTextLines.line_blocks`: `[1, [10, 20]]` deletes line 1 and lines 10–20; `[10, 20]` deletes only two single lines. All ranges reference the original file; any out-of-bounds access will reject the entire operation. For `ReplaceStringInFile`, search blocks use nested closed intervals, e.g., `[[10, 20]]`, requiring uniqueness across all specified blocks.

It is recommended to read files first and record SHA-256, then submit modifications; re-read and redo edits if concurrent conflicts occur.

## Testing, Commands, and Workspace

| Tool | Purpose |
| --- | --- |
| `RunPyTest` | Run Python tests, providing pytest parameters and timeout, and select stdout/stderr return |
| `RunUnityChipTest` | Run UnityChip/toffee tests and generate corresponding reports |
| `RunTestCases` | Run a set of test cases supported by the phase |
| `RunBashCommand` | Execute Bash commands in the workspace; ignored by default in tool filter configuration |
| `WorkDiff` / `WorkCommit` | View Git workspace differences or commit allowed files; ignored by default |

Do not register test infrastructure errors as DUT bugs. Failed test cases that truly expose DUT defects should retain assertions and record evidence according to the current workflow.

The `timeout` input for `RunPyTest` defaults to 15 seconds; UCAgent also sets the tool-level `call_time_out`, defaulting to 300 seconds. Long tasks must consider both tool and client timeouts; specific behavior follows actual call configuration.

## Waveform Evidence

| Tool | Purpose |
| --- | --- |
| `WaveInfo` | Find test waveforms, analyze signals and clock alignment, and generate verifiable evidence receipts |
| `ApplyWaveInfoEvidence` | Update central waveform records in bug documents using verified receipts |
| `ReviewWaveInfoEvidenceBatch` | Prepare a batch of waveform contexts for review and atomically apply results after full audit |

Waveform tools depend on the optional `wavekit`. Phases requiring waveform evidence must have dependencies and real test data. Exploratory queries cannot replace complete evidence; parameters, TC nodes, and bug document formats follow the current tool schema and runtime `Guide_Doc/dut_bug_analysis.md`.

By default, analysis files are selected in FST, VCD, FSDB order; `runtime_options.waveform_analysis_format_priority` can be configured. FSDB runtime dependencies, browser limitations, and readers for other formats are documented in [Waveform Analysis Formats and Extensions](10_waveform_analysis.md).

## Skills, Planning, and Retrieval

| Tool | Purpose |
| --- | --- |
| `ListSkill` / `RunSkillScript` / `SetSkillUsage` | List skills, execute scripts, and register current phase skill evidence; see [Skills](../02_usage/08_skill.md) |
| `CreateToDo` | Create or overwrite a plan, requiring 2–20 steps |
| `CompleteToDoSteps` / `UndoToDoSteps` | Complete or undo steps by index starting from 1 |
| `ResetToDo` / `GetToDoSummary` / `ToDoState` | Clear plan, read summary, or get status |
| `SemanticSearchInGuidDoc` | Perform semantic search on running guides and project reference materials |
| `MemoryPut` / `MemoryGet` | Write or retrieve memory by scope |

ToDo tools require corresponding options to be enabled. Retrieval and memory tools depend on embedded models; currently disabled by default in CLI, can be enabled with `--no-embed-tools false`. Planning, memory, and skill usage cannot replace Checker verification.

## Assembly and MCP Scope

The `--mcp-server-no-file-tools` option omits the file operation tool group, retaining basic `ReadTextFile`, phase tools, and registered extension tools. Therefore, this option does not prohibit all file writes: external clients and custom tools must each comply with workspace permissions.

The default `tools.ignore_tools` configuration includes `RunBashCommand`, `WorkDiff`, and `WorkCommit`. Filter rules are jointly determined by `tools.ignore_tools` and `tools.selected_tools`; adjustments should be confirmed via `tool_list` and MCP tool discovery results. CLI options are documented in [Parameter Description](../02_usage/03_option.md).
