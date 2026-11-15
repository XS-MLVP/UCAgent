# Formal task workbench handoff

The FlowCanvas workbench opens on the existing Formal task detail page, both through Master and through a direct command-service URL. The shared workbench continues to serve other task types. This change follows `c0679304` on `codex/formal-workflow-polish`, which introduced the FG/FC report navigation and checkpoint results layout.

## Page layout and interactions

- **Left** — 验证模板 opens first. Expand a function group (FG), then select a function point (FC) to see its checkpoints (CK). The navigation keeps counts at the end of each row and reveals coverage actions on hover or keyboard focus, with an explicit action menu on touch devices. The other rail buttons open 阶段审阅 and the Worktree.
- **Center** — The selected FC shows its goal, detailed description, and each CK in one default-open block with the inline SVA and available evidence or analysis. The source and Pause buttons sit at the bottom of the report preview. In a file preview, Pause sits in the file toolbar. Chat sits below it in a single composer. The splitter resizes sent-message history.
- **Right** — 工作流 shows the stage progress, current runtime status and stage controls such as HM and Skip where available. 输出 contains LLM, Activity, System logs and Raw output tabs. 覆盖率 shows the proof overview. The tools dock lists one tool per row with aligned counts and run actions; category tabs and search share a row. Narrow screens use a collapsible right pane.
- 阶段审阅 shows the selected stage's recorded LLM suggestions, Check results and human feedback. For a live task awaiting human review, the decision form in 工作流 submits against the current control revision.
- FG/FC/CK target actions open a small form for the selected scope. Explicit submission sends the request through the task's Chat command. Once accepted, the request appears as a task card in Chat history and the model's response goes to 输出. Selecting text in a preview or in Output offers “添加到对话”, which opens an optional comment field. Each confirmed excerpt adds its own removable card above the composer. Sending from Chat includes all attached excerpts, their comments and any text in the composer. The accepted message appears in sent history.

## Source and integration

Paths are relative to the repository. The app packages the browser assets and Apache 2.0 attribution with the Formal plugin.

| File | Responsibility |
| --- | --- |
| `ucagent/plugins/Formal/src/formal/web/workbench.html` | Three-pane shell and target-action form. |
| `ucagent/plugins/Formal/src/formal/web/flowcanvas-ui.{css,js}` | Navigation, header controls, tab styling and keyboard behavior, composer styling, and task card rendering extracted from [FlowCanvas 5bb2cda](https://github.com/Miical/UCAgent/tree/5bb2cda5f9f4758953108ffdc0d0664398c0f313/plugins/FlowCanvas). |
| `ucagent/plugins/Formal/src/formal/web/flowcanvas-coverage-actions.{css,js}` | Target action buttons and popup. The adapter provides target context, action text and submission. |
| `ucagent/plugins/Formal/src/formal/web/formal-workbench.{css,js}` | Layout, host control mounting and restore, Formal stage review, tool invocation and Chat history. |
| `ucagent/plugins/Formal/src/formal/web/formal-report.{css,js}` and `formal-view.js` | FG/FC selection and order, CK presentation, proof state, evidence and run controls. |
| `ucagent/plugins/Formal/src/formal/web/workbench-entry.js` | Loads versioned CSS and modules through the task origin. Component styles load before the Formal overrides. |
| `ucagent/interfaces/server/templates/agent.html` and `static/share/task-workbench.js` under the same server directory | Resolve the Formal view and load the optional plugin on demand. The existing controls supply workspace, command session, file viewing and runtime state. |
| `ucagent/interfaces/server/api_cmd/formal_routes.py` | Serves plugin assets at `/static/formal/` using the installed or source-tree plugin. |

Use the pinned FlowCanvas revision when refreshing component extracts and put Formal-specific behavior in the adapter. Preserve the task's API mount and workspace scoping for direct access and Master proxy paths. Tool runs use the existing `tool_invoke` runtime command, and parameterized tools take a JSON object. Scope checks keep tool execution and approval controls confined to the live task. A change to route registration requires restarting the command service.

## FC review metadata

New Formal specification stages require a one-line `title` of at most 60 characters, a detailed `description`, and a group-local positive, unique `review_order`. The Formal dashboard and generated Markdown use that sequence. Legacy records with absent metadata remain readable. Titles and review order stay out of the proof input fingerprint. Historical batches use their archived specification metadata when the snapshot matches the frozen semantic inputs.

The dashboard displays all checkpoints for the selected FC, even when a filter was used to find it. Evidence integrity, proof input freshness and recorded Bug interpretations remain independent. Historical or unverified success is shown without the current verified pass indicator. Exact CK paths and run IDs stay attached to evidence queries and proof actions.

## Verification

Run from the repository root with the project dependencies installed.

```bash
node --test tests/*.js
PYTHONPATH="$PWD:$PWD/ucagent/plugins/Formal/src" python -m pytest -q \
  ucagent/plugins/Formal/tests tests/test_control_api_runtime.py \
  tests/test_console_master_proxy.py tests/test_config_loader.py
git diff --check
```

The process recovery tests `test_recorded_descendant_is_cleaned_after_group_leader_exits` and `test_controller_crash_cleans_owned_workers` use Linux `/proc`. The macOS regression omitted those two tests.

For browser review, open an active Formal task in Master and at the direct command address. Check the header menu, right pane and tool alignment at desktop and narrow widths, and navigate Workflow/Output/Coverage with the arrow keys. Select an FC to verify that all of its CKs show inline SVA. Use an archived task to verify that live actions are unavailable. The Adder preview exercised the current layout from 320 to 1920 px. The browser Chat test used simulated command acknowledgements; live model response and a new FormalMC run were outside that check.

## Earlier BIU artifact

The BIU review examples are curated excerpts of the earlier report. Independent review confirmed two conditional specification conflicts involving disabled targets, rejected the proposed FIFO-reset explanation, and left the IFU response-chain claim unconfirmed. Keep those interpretations distinct from current proof evidence. The handoff at `c0679304` records the earlier prototype and preview checks.
