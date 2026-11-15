
# Dynamic task workbench handoff

## Scope and branch

The user intends this layout to replace the **Master task detail page**, not the Master task list and not a separate report-only application. Preserve Workflow, workspace files, Agent Status, tools, Output and existing task operations. Simplify their presentation without deleting capabilities.

Branch: `codex/formal-workflow-polish`, based on `codex/formal-dashboard` at `e06f9ce4`. Earlier commits:

- `8e91a084`: compact Formal review replies, evidence-integrity projection, preflight/coverage diagnostics, local review drafts, and plain-language reporting guidance.
- `a851e295`: actual dynamic workbench layout, unified Formal report, suggestion prototype, quote comments and the shared Chat composer.
- The following commit includes the current FG/FC navigation, default-open checkpoint results, consistent visual styling and secondary-action menus, plus this handoff.

No DUT, historical proof output or RunSkillScript framework was changed for the UI. No model is required to preview an archived task. Do not infer verified design correctness from a finished task or evidence hashes.

## User-approved information layout

```text
Header: task identity / runtime status / existing task actions
Left column                  Right column
Workflow                     Verification report / File content
                             Report navigation: FG -> FC only
                             Selected FC: all CK cards + SVA + results
Workspace + Agent Status     Output                     Tools
```

Defaults: Workflow roughly 46% / Workspace 54% of the sidebar; lower-right Output+Tools roughly 34% of right-column height; Tools roughly 30% of lower-row width (bounded). User-dragged sizes are retained. Reset UI removes the new sizing preferences as well. On narrow screens, Workflow/Workspace is reachable through a toggle and Output/Tools share tabs; functionality is not removed.

## Canonical source files

All paths below are repository-relative.

| File | Responsibility |
| --- | --- |
| `ucagent/interfaces/server/templates/agent.html` | Actual shared dynamic task template, markup, existing API requests, Master workspace context, report wiring, console/Chat bridge and splitters. |
| `ucagent/interfaces/server/static/share/task-workbench.js` / `.css` | Repositions original components; docks the existing file viewer; content tabs; Tools search and resizing; narrow-screen access. |
| `ucagent/interfaces/server/static/share/formal-report.js` / `.css` | Formal-only FG/FC navigation, search/filter, selected FC checkpoint cards, previous/next FC, report split and selection/disclosure state. |
| `ucagent/interfaces/server/static/share/formal-view.js` | Proof-state styling, exact-scope actions and unified checkpoint analysis/evidence/trace/attempt rendering. Also used by the retained shared map integration. |
| `ucagent/interfaces/server/static/share/workbench-polish.js` / `.css` | Consistent typography/spacing/control sizes and secondary-action menus. Moves original controls rather than cloning handlers. |
| `ucagent/interfaces/server/static/share/task-suggestions.js` / `.css` | Browser-local suggestion review prototype; explicit accept/reject/pending decisions, per-item notes, handoff into the original Chat input. |
| `ucagent/interfaces/server/static/share/task-suggestion-examples.js` | Curated BIU audit examples, explicitly not actual new messages from a running LLM. Generic examples are available for other DUTs. |
| `ucagent/interfaces/server/static/share/quote-comments.js` / `.css` | Native text-selection comments anchored to exact FG/FC/CK, source revision and proof batch; local history; explicit Chat handoff. |
| `ucagent/interfaces/server/static/share/chat-composer.js` / `.css` | One original Chat input, auto-height and expanded editing using Output space, restoration of log layout. |
| `ucagent/interfaces/server/static/share/formal-review.js` / `.css` | Earlier local whole-node comments/change proposals. Distinct from quote comments; currently retained rather than silently removing existing drafts. |

The main template statically includes these assets. `formal-view.js`, `formal-report.js` and its CSS currently have versioned URLs (`fc-cards-3`) because browser caching previously made old CK navigation appear after updates. Template changes require restarting the actual UCAgent page-serving process; a second static server does not update an existing Master instance.

## Report interaction contract

- Navigation shows **FG -> FC**, never all CK entries under FC in the middle panel. Expand an FG, select an FC.
- The selected FC shows **every CK and its SVA inline**, even when a result/search filter located that FC. A notice explains this; do not hide remaining CK and suggest the FC contains only matched goals.
- Each CK has a heading, ID and a single result badge. Its result/analysis is open by default. Original logs, waveform query, execution attempts and long recorded Bug interpretations remain disclosures.
- The checkpoint SVA and result are not duplicated inside its open analysis. `(-)` and similar placeholder reasons are suppressed. `RTL_BUG` is labeled as an **author classification**.
- Exact CK selection APIs remain usable for scoped review/evidence actions; default navigation selects FC.
- Identical polling should not rebuild active forms or erase user state. Task/workspace changes must invalidate retained controls and late replies.
- Evidence `verified/unverified/invalid`, input freshness and human Bug interpretation are separate dimensions. Archived/historical or unverified successful claims do not get current verified green styling. Top Bug count is labeled recorded observations, not independently confirmed Bugs.
- UnitTest's shared function map, test cases and waveform entries remain separate. Do not replace them with Formal-specific assumptions.

## Suggestion review and Chat: implemented versus not implemented

**Implemented:** page interaction only. The result/filter bar includes “LLM 建议”. Suggestions can be selected, accepted/rejected/left pending, and given individual human notes. “带入 Chat” puts explicit decisions into the **single existing Chat composer**. Users add general comments there; there is no second general-advice box or standalone feedback-draft panel. Repeated insertion updates the generated decision block when still recognizable and preserves appended user text; manually rewritten blocks are not blindly overwritten.

**Not implemented:** an LLM-facing suggestion submission tool, server-side suggestion inbox, durable multi-user review decisions or automatic consumption/resumption by a running verification task. The displayed BIU cases are curated review examples. Loading examples requires an explicit button or `suggestions=examples` URL. Example text is marked and sending is blocked before `/api/cmd`; no simulation should accidentally send a demo instruction.

Local decisions use `task-suggestions-v2` and are scoped by workspace, DUT, records revision, fingerprint, scope and run ID. Do not add compatibility fallbacks to the older prototype schema. Unknown or malformed data must not invent accepted decisions. Changing task/version clears task-bound composer content.

Ordinary Chat retains the existing runtime submission path and busy/TUI restrictions. It is a multiline textarea: Shift+Enter inserts a newline; Enter retains the existing explicit submission behavior. Busy state or a nonempty runtime-command input must not silently become Chat. A long suggestion/comment expands the same composer; “收起输入” restores Output height/logs without deleting text. The expanded editor is not a second draft.

## Quote comments

Drag-select text and release inside a report FG/FC/CK annotation container: the modal opens automatically. A plain click does not form a text selection and should not open a modal. Keyboard Shift-selection is also handled. “批注记录” opens saved history, not a mode that makes a subsequent plain click select text.

The quote anchor includes full node path, kind, source revision, fingerprint, batch scope/ID, exact quote, rendered-text offsets and surrounding text. Offsets are explicitly **not source-file line numbers**. Empty, overlong and cross-container selections are rejected rather than guessed/clipped. Data is rendered as text, not executable markup. Existing annotations remain historical if task inputs change.

Comments are browser-local (50 bounded entries / 500KB), not collaborative server records. “带入 Chat” appends the quote + location + human intent. Current live annotations may use ordinary Chat after explicit Send; archives/historical input remain non-sending previews. No LLM run was used to validate actual annotation-driven source modification: end-to-end model editing/verification remains future work. A human comment itself is not source application or proof acceptance.

## Existing APIs and controls to preserve

Keep the existing `apiFetch` / `_withSubWorkspaceParam` path handling. Master-mounted `/task/.../cmd` and `/agent/.../cmd` prefixes, command session identity, archive restrictions and stale-response guards must remain intact. Do not hardcode preview ports into product assets.

Workspace uses the original file API and file manager, not a newly implemented complete tree component. The existing modal viewer is docked into File content so Markdown/code/diff/download/wave behavior is reused. File actions and Recent changes remain available under “更多”. Tools is the original tool-call audit list (name/count/hot), with search; it is **not** a newly implemented callable tool palette. Agent Status is real backend state; Output retains Activity/System/Raw, Clear view, auto-scroll, runtime commands, Chat and interruption.

Secondary actions use native `<details>` menus with original DOM elements, not duplicate IDs or copied event handlers. Menus close outside/on Escape and after explicit button actions. Scope-sensitive hidden states remain authoritative.

## Tests and verification

Focused frontend regression command:

```bash
node --test tests/test_workbench_polish.js tests/test_formal_report.js tests/test_formal_review_ui.js tests/test_task_workbench.js tests/test_task_suggestions.js tests/test_suggestion_chat.js tests/test_chat_composer.js tests/test_quote_comments.js tests/test_agent_sidebar.js tests/test_console_view.js tests/test_dashboard_stage_view.js tests/test_agent_modal_resize.js tests/test_agent_markdown_yaml_collapse.js tests/test_function_map_results.js
git diff --check
```

New tests cover local-only decisions, literal text, exact quote/version anchors, stale workspace controls, trace/review scope, pending-not-consent, demo send guard, multiline composer, menu retention, proportional sizes and reset. Do not restore old CK-in-middle navigation to satisfy superseded test expectations.

Earlier interface validation (17 tests) used:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy -u NO_PROXY -u no_proxy python -m pytest -q tests/test_control_api_runtime.py tests/test_console_master_proxy.py
```

The test environment's inherited IPv6 NO_PROXY entry caused httpx URL parsing failure; removing environment proxies fixed it without product code changes. Previously 357 Formal/plugin/config tests and 87 stage/API regressions passed before frontend-only changes; they were not all rerun after each style tweak.

Actual Firefox headless BiDi tests exercised file docking/report return, workspace BIU->Adder isolation, Tools keyboard resize, menus and click hit-testing, 1440x1000 / 1280x720 / 800x600 / 390x844 document bounds, one Chat draft, archive send blocking, true mouse-drag quote selection, automatic quote modal, FG/FC navigation and default-open CK analysis. Browser image inspection was unavailable to the agent model: geometry/DOM/interactions were verified, but final aesthetics still require human review.

## Runtime preview and old prototypes

The most recent native preview is `http://172.38.8.191:8907/?sub_workspace=BIU-polish-20261112`, serving this source from a UCAgent Master process. Adder archive uses `sub_workspace=Adder-polish-20261112`. `&suggestions=examples` explicitly loads the suggestion interaction examples. These paths/workspaces and port availability are local machine facts, not product configuration, and may not exist elsewhere.

Older 8900/8904/8906 static/GET-proxy pages were exploratory prototypes outside the repository. They are not the implementation to maintain and several were stopped. Do not copy their hardcoded BIU labels, ports or audit conclusions into the generic page. The 8907 backend is a preview with saved workspace copies, not the verification run itself; archives may have no saved execution transcript/tool-call stream.

## Remaining review priorities

1. Human visual review of density, long Chinese labels and menu placement. The user explicitly wants uniform sizes and fewer buttons while retaining every workbench region.
2. Full live-task browser acceptance (permissions, runtime busy states and actual model handoff), beyond archived preview and isolated API tests.
3. Generic long-text annotations outside Formal reports if requested; currently select only mapped Formal FG/FC/CK text.
4. Consolidate the older whole-node local draft dialog and quote history if the user chooses one review model; do not silently discard browser-local drafts.
5. Add a real versioned suggestion/review backend only in a separately scoped change. Preserve proof gates and do not turn acceptance into automatic RTL changes or assumption weakening.
6. Source files often use compact formatting inherited from the prototype. Keep future edits scoped; avoid mixing wholesale formatting/refactors with layout changes.

## BIU report semantic warning

The displayed old BIU artifact is original model output. Independent review confirmed two conditional specification conflicts (disabled peripheral addresses route to MEM; all-target-disabled requests remain buffered without response), but rejected the claimed FIFO-reset “phantom occupancy” explanation. The IFU response-chain group is not confirmed under a clean environment. UI evidence-integrity labels must not present these original human interpretations as independently proven root causes. Do not rewrite historical reports just to improve the preview.
