# MessagesPanel: Replace RichLog with Custom ScrollView for Inline Append

## TL;DR

> **Quick Summary**: Rewrite `MessagesPanel` from `RichLog` subclass to custom `ScrollView` subclass, enabling inline text appending (行内追加) for LLM streaming output while preserving all existing functionality.
> 
> **Deliverables**:
> - Rewritten `MessagesPanel` in `ucagent/tui/widgets/messages_panel.py` (ScrollView-based)
> - Fixed `app.py:message_echo` (restore from debug hardcode)
> - Basic pytest tests for the new widget
> - Cleanup of leftover files from previous failed attempt
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → F1-F4

---

## Context

### Original Request
MessagesPanel 基于 RichLog，而 RichLog.write() 每次调用必定追加新行（Strip），无法实现行内追加。当 LLM streaming 输出 token（`message_echo(token, end="")`）时，每个 token 会变成独立一行而非追加到当前行尾。需要替换为自定义 ScrollView 来解决。

### Interview Summary
**Key Discussions**:
- **方案选择**: 用户选择方案D — 完全替换 RichLog，改用自定义 ScrollView（最灵活）
- **显示效果**: 实时逐 token 显示（打字机效果，受 0.2s batch 间隔限制）
- **ANSI 样式**: 需要保留（消息包含 ANSI 颜色码）
- **接口**: 保持 `append_message(msg: str)` 不变，`msg+end` 由调用方拼接后传入
- **Soft-wrap**: 保留自定义 `_soft_wrap_text`（CJK 字符宽度支持）
- **测试**: 写基本 pytest 测试

**Research Findings**:
- RichLog 源码（`_rich_log.py`）: write() 渲染 → Segment.split_lines → 追加到 self.lines，无修改已有行的 API
- 旧 urwid UI（`verify_ui.py:288-304`）通过 `set_text(current_text + line)` 实现行内追加
- `verify_agent.py:message_echo()` 传递 `(msg, end)` 参数，`end=""` 表示行内追加
- 存在之前失败的 `MessagesScrollView` 实现（已从代码中移除，残留 3 个未提交文件）

### Metis Review
**Identified Gaps** (addressed):
- **Previous failed attempt**: 存在 `IMPLEMENTATION_SUMMARY.md`, `demo_messages_scroll.py`, `test_multiline.py` 残留文件，需清理并从中吸取教训
- **auto_scroll 属性**: ScrollView 不继承此属性，AutoScrollMixin 依赖它 → 必须在新类中显式定义
- **render_line 坐标系**: ScrollView 的 render_line(y) 接收 widget-relative y，需加 scroll_offset.y → 文档化到计划中
- **ANSI 码跨 batch 分裂**: streaming token 可能在 batch 边界处切断 ANSI 转义序列 → 对未完成行存储原始字符串，渲染时才调用 Text.from_ansi()
- **线程安全**: append_message() 从 worker 线程调用 → 保持 SimpleQueue 模式，所有行变更仅在 _flush_batch() 中执行
- **deferred rendering**: Widget 尺寸未知时的渲染处理 → 参考 RichLog 的 `_size_known` 模式
- **缓存失效**: 修改最后一行（未完成行）时需要使缓存失效

---

## Work Objectives

### Core Objective
将 MessagesPanel 的基类从 RichLog 替换为 ScrollView，实现行内文本追加能力，支持 LLM streaming 输出的实时逐 token 显示。

### Concrete Deliverables
- `ucagent/tui/widgets/messages_panel.py` — 重写 MessagesPanel 为 ScrollView 子类
- `ucagent/tui/app.py` — 恢复 message_echo 正常逻辑（去掉 debug hardcode）
- `tests/test_messages_panel.py` — 基本 pytest 测试
- 清理残留文件: `IMPLEMENTATION_SUMMARY.md`, `demo_messages_scroll.py`, `test_multiline.py`

### Definition of Done
- [ ] `python -c "from ucagent.tui.widgets import MessagesPanel; print('OK')"` 输出 OK
- [ ] `python -m pytest tests/test_messages_panel.py -v` 全部通过
- [ ] MessagesPanel 支持行内追加（多次 append 无 `\n` 的文本显示在同一行）
- [ ] ANSI 颜色正确渲染
- [ ] 手动/自动滚动行为不变
- [ ] 窗口 resize 时 reflow 正常

### Must Have
- 行内追加能力（core feature）
- ANSI 颜色渲染（Text.from_ansi）
- 0.2s batch flush 机制（线程安全）
- AutoScrollMixin 集成（手动/自动滚动切换）
- 自定义 soft-wrap（CJK 字符宽度）
- 渲染历史 + resize reflow
- 行缓存（性能）
- max_lines 限制

### Must NOT Have (Guardrails)
- ❌ typewriter 动画（`append_with_typewriter`）— 明确排除
- ❌ 修改 AutoScrollMixin — 新 widget 适配其现有接口
- ❌ 修改 ConsoleWidget / verify_agent.py / 任何 message_echo 调用方
- ❌ 修改 CSS 选择器 — 使用 `id="messages-panel"` 匹配现有规则
- ❌ 过度抽象或过度注释（AI slop）
- ❌ 添加新的公开 API（除原有的 `append_message` 外）
- ❌ 在 `append_message()` 中直接修改 `_lines` 或 `_current_line_buffer`（线程不安全）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, `tests/` directory)
- **Automated tests**: Tests-after (not TDD — 已有明确的行为目标)
- **Framework**: pytest

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Widget logic**: Use Bash (python) — Import, instantiate, call methods, compare output
- **Integration**: Use Bash (pytest) — Run test suite

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — cleanup + research):
├── Task 1: Review previous attempt & cleanup leftover files [quick]
├── Task 2: Research ScrollView render_line pattern from Textual source [quick]

Wave 2 (After Wave 1 — core implementation, SEQUENTIAL):
├── Task 3: Rewrite MessagesPanel as ScrollView (depends: 1, 2) [deep]
├── Task 4: Fix app.py message_echo + integration (depends: 3) [quick]

Wave 3 (After Wave 2 — tests):
├── Task 5: Write pytest tests for MessagesPanel (depends: 3, 4) [unspecified-high]

Wave FINAL (After ALL tasks — review):
├── Task F1: Plan compliance audit [oracle]
├── Task F2: Code quality review [unspecified-high]
├── Task F3: Real manual QA [unspecified-high]
├── Task F4: Scope fidelity check [deep]

Critical Path: Task 1 → Task 3 → Task 4 → Task 5 → F1-F4
Parallel Speedup: Wave 1 tasks run in parallel (~30% faster)
Max Concurrent: 2 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | — | 3 |
| 2 | — | 3 |
| 3 | 1, 2 | 4, 5 |
| 4 | 3 | 5 |
| 5 | 3, 4 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T1 → `quick`, T2 → `quick`
- **Wave 2**: 2 tasks — T3 → `deep`, T4 → `quick`
- **Wave 3**: 1 task — T5 → `unspecified-high`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. Review previous failed attempt & cleanup leftover files

  **What to do**:
  - Read the 3 leftover files from a previous failed `MessagesScrollView` implementation:
    - `/home/wangjunyue/Workbench/UCAgent/IMPLEMENTATION_SUMMARY.md`
    - `/home/wangjunyue/Workbench/UCAgent/demo_messages_scroll.py`
    - `/home/wangjunyue/Workbench/UCAgent/test_multiline.py`
  - Note useful patterns (API design, internal data structures like `_lines`, `_text_history`) and pitfalls that may have caused the revert
  - Delete all 3 files (`rm IMPLEMENTATION_SUMMARY.md demo_messages_scroll.py test_multiline.py`)
  - Verify deletion

  **Must NOT do**:
  - Do NOT reuse the previous implementation code directly — it was reverted for a reason
  - Do NOT modify any other files

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple file review and deletion, no coding required
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `git-master`: Not needed — these are untracked files, not git operations

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: [Task 3]
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `IMPLEMENTATION_SUMMARY.md` — Describes the previous `MessagesScrollView` API: `append_text(text, newline=False)`, `append_with_typewriter()`, internal `_lines`, `_text_history`
  - `demo_messages_scroll.py` — Demo showing same-line append with `newline=False` parameter
  - `test_multiline.py` — Basic test showing `_lines` and `_text_history` internal structure

  **WHY Each Reference Matters**:
  - These files reveal the previous approach's API design decisions. The previous impl used `append_text(text, newline=False)` which is different from our chosen `append_message(msg)` approach. Understanding what was tried helps avoid repeating mistakes.

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Leftover files are deleted
    Tool: Bash
    Preconditions: Files exist at repo root
    Steps:
      1. Run: test ! -f IMPLEMENTATION_SUMMARY.md && test ! -f demo_messages_scroll.py && test ! -f test_multiline.py && echo "CLEAN"
    Expected Result: Output is "CLEAN"
    Failure Indicators: Any file still exists
    Evidence: .sisyphus/evidence/task-1-cleanup.txt
  ```

  **Commit**: YES
  - Message: `chore: cleanup leftover files from previous MessagesScrollView attempt`
  - Files: `IMPLEMENTATION_SUMMARY.md`, `demo_messages_scroll.py`, `test_multiline.py` (deleted)
  - Pre-commit: None

- [ ] 2. Research ScrollView render_line pattern from Textual source

  **What to do**:
  - Read the Textual source for ScrollView: find `render_line()` signature and behavior
  - Read RichLog source at `.venv/lib/python3.12/site-packages/textual/widgets/_rich_log.py` — specifically:
    - `render_line()` method (L301-307): how it compensates scroll offset and crops
    - `_render_line()` method (L309-319): how it reads from `self.lines`, uses cache, and crop_extends
    - `write()` method (L175-284): how it converts Rich renderables → Segments → Strips
    - `clear()` method (L286-299): state reset pattern
  - Read ScrollView base class at `.venv/lib/python3.12/site-packages/textual/scroll_view.py` to understand:
    - What `render_line(y)` receives (widget-relative y)
    - What methods/attributes ScrollView provides vs what must be implemented
    - How `virtual_size` affects scrollbar behavior
  - Document findings as a brief internal note (NOT a file — just capture in your working context)

  **Must NOT do**:
  - Do NOT modify any files
  - Do NOT create documentation files

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Pure research task — reading existing source files, no implementation
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: [Task 3]
  - **Blocked By**: None

  **References**:

  **Pattern References**:
  - `.venv/lib/python3.12/site-packages/textual/widgets/_rich_log.py:301-319` — RichLog's render_line → _render_line pattern: `y + scroll_offset.y` for content index, `strip.crop_extend(scroll_x, scroll_x + width, self.rich_style)` for horizontal cropping, LRU cache with key `(y + _start_line, scroll_x, width, _widest_line_width)`
  - `.venv/lib/python3.12/site-packages/textual/widgets/_rich_log.py:175-284` — write() pattern: `console.render(renderable, render_options) → Segment.split_lines(segments) → Strip.from_lines(lines)`
  - `.venv/lib/python3.12/site-packages/textual/scroll_view.py` — ScrollView base class, `render_line()` contract

  **WHY Each Reference Matters**:
  - The new MessagesPanel must implement `render_line()` exactly like RichLog does — same scroll offset compensation, same cropping, same caching strategy. These files are the authoritative source for that pattern.

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: ScrollView source exists and is readable
    Tool: Bash
    Preconditions: Textual package installed in .venv
    Steps:
      1. Run: python -c "from textual.scroll_view import ScrollView; print(hasattr(ScrollView, 'render_line'))"
    Expected Result: Output is "True"
    Failure Indicators: Import error or "False"
    Evidence: .sisyphus/evidence/task-2-scrollview-check.txt
  ```

  **Commit**: NO (pure research, no file changes)

- [ ] 3. Rewrite MessagesPanel as custom ScrollView

  **What to do**:
  In `ucagent/tui/widgets/messages_panel.py`, replace the entire `MessagesPanel` class. Change base from `RichLog` to `ScrollView`. Preserve the class name `MessagesPanel` and the public API `append_message(msg: str)`.

  **Step-by-step implementation**:

  1. **Change imports and base class**:
     - Remove: `from textual.widgets import RichLog`
     - Add: `from textual.scroll_view import ScrollView`
     - Add: `from rich.console import Console` (for rendering)
     - Add: `from rich.segment import Segment`
     - Add: `from textual.strip import Strip`
     - Add: `from textual.geometry import Size`
     - Add: `from textual.cache import LRUCache`
     - Keep: `from rich.text import Text`, `from textual import events`, `from textual.binding import Binding`
     - Class declaration: `class MessagesPanel(AutoScrollMixin, ScrollView, can_focus=True):`

  2. **Define class attributes and `__init__`**:
     - `auto_scroll: bool = True` — required by AutoScrollMixin (ScrollView does NOT provide this)
     - `max_messages: int = 1000` — same as before
     - `BINDINGS` — same key bindings as before
     - In `__init__`:
       - `self.border_title = "Messages"`
       - `self._lines: list[Strip] = []` — rendered display lines
       - `self._line_cache: LRUCache = LRUCache(1024)` — render cache
       - `self._render_history: deque[Text] = deque(maxlen=self.max_messages)` — for reflow
       - `self._batch_queue: queue.SimpleQueue[str] = queue.SimpleQueue()` — thread-safe ingestion
       - `self._current_line_buffer: str = ""` — accumulator for incomplete line (raw string, NOT Text)
       - `self._last_wrap_width: int = 0`
       - `self._widest_line_width: int = 0`
       - `self._start_line: int = 0` — offset for max_lines pruning
       - `self._size_known: bool = False` — deferred rendering guard
       - `self._deferred_payloads: list[str] = []` — payloads received before size known

  3. **Implement `render_line(y: int) -> Strip`** (core ScrollView contract):
     ```
     def render_line(self, y: int) -> Strip:
         scroll_x, scroll_y = self.scroll_offset
         content_y = scroll_y + y
         if content_y >= len(self._lines):
             return Strip.blank(self.scrollable_content_region.width, self.rich_style)
         key = (content_y + self._start_line, scroll_x, self.scrollable_content_region.width, self._widest_line_width)
         if key in self._line_cache:
             return self._line_cache[key].apply_style(self.rich_style)
         line = self._lines[content_y]
         cropped = line.crop_extend(scroll_x, scroll_x + self.scrollable_content_region.width, self.rich_style)
         self._line_cache[key] = cropped
         return cropped.apply_style(self.rich_style)
     ```

  4. **Implement `_render_text_to_strips(text: Text) -> list[Strip]`** (convert Rich Text → Strips):
     - Use `self.app.console` to get render options
     - If not wrap: `render_options.update(overflow="ignore", no_wrap=True)`
     - `segments = self.app.console.render(text, render_options)`
     - `lines = list(Segment.split_lines(segments))`
     - `strips = Strip.from_lines(lines)`
     - Handle width: adjust each strip to render_width
     - Return strips (or `[Strip.blank(width)]` if empty)

  5. **Implement inline append logic in `_flush_batch()`**:
     This is the CORE new logic. Adapted from `verify_ui.py:288-304`:
     ```
     def _flush_batch(self) -> None:
         # 1. Drain queue → concatenate
         messages = []
         try:
             while True:
                 messages.append(self._batch_queue.get_nowait())
         except queue.Empty:
             pass
         if not messages:
             return
         payload = "".join(messages)
         if not payload:
             return

         # 2. Handle deferred rendering
         if not self._size_known:
             self._deferred_payloads.append(payload)
             return

         # 3. Split by \n and process segments
         self._process_payload(payload)
     ```

  6. **Implement `_process_payload(payload: str)`**:
     ```
     def _process_payload(self, payload: str) -> None:
         segments = payload.split("\n")
         for i, segment in enumerate(segments):
             if i == 0:
                 # First segment: append to current incomplete line
                 self._current_line_buffer += segment
             else:
                 # Subsequent segments: finalize current line, start new
                 self._finalize_current_line()
                 self._current_line_buffer = segment

         # Re-render the current incomplete line (if non-empty)
         self._update_pending_line()

         # Update virtual size and scroll
         total_lines = len(self._lines) + (1 if self._current_line_buffer else 0)
         self.virtual_size = Size(self._widest_line_width, total_lines)
         if self.auto_scroll:
             self.scroll_end(animate=False)
         self.refresh()
     ```

  7. **Implement `_finalize_current_line()`**:
     - If `self._current_line_buffer` is empty: add a blank Strip to `self._lines`
     - Else: `text = Text.from_ansi(self._current_line_buffer)` → store in `_render_history` → soft-wrap → render to Strips → extend `self._lines`
     - Reset `self._current_line_buffer = ""`
     - Handle `max_messages` pruning (trim `self._lines` if exceeds limit)
     - Clear affected cache entries

  8. **Implement `_update_pending_line()`**:
     - This renders the "current incomplete line" as a temporary visual line
     - If buffer is empty, nothing to show
     - If buffer is non-empty: render `Text.from_ansi(self._current_line_buffer)` to Strip(s)
     - These pending strips are stored separately (e.g., `self._pending_strips: list[Strip]`) and included in `render_line()` at the end of `self._lines`
     - When the line is finalized (newline received), the pending strips are replaced by finalized strips
     - Invalidate cache for the pending line positions

  9. **Port existing methods verbatim**:
     - `_soft_wrap_text(text, width) -> list[Text]` — static method, no RichLog dependency
     - `_char_display_width(ch) -> int` — static method, no RichLog dependency
     - `_reflow_history()` — clear all lines, re-render from `_render_history`, preserve manual scroll
     - `on_resize()` — detect width change, trigger reflow
     - `on_mount()` — `set_interval(0.2, self._flush_batch)`, set `_size_known = True`, flush deferred payloads
     - `on_unmount()` — `self._flush_batch()`
     - `_get_scrollable() → self`
     - `move_focus(delta)`, `action_scroll_messages_up/down`, `action_cancel_scroll`
     - `on_mouse_scroll_up/down` — from current implementation
     - `_update_title()`, `_enter_manual_scroll_with_focus()`, `_exit_manual_scroll()`
     - `_on_manual_scroll_changed(manual: bool)`

  10. **Implement `clear()`**:
      - `self._lines.clear()`
      - `self._line_cache.clear()`
      - `self._current_line_buffer = ""`
      - `self._pending_strips = []`
      - `self._start_line = 0`
      - `self._widest_line_width = 0`
      - `self.virtual_size = Size(0, 0)`
      - `self.refresh()`

  11. **Handle `_size_known` lifecycle**:
      - In `on_resize`: if first resize with non-zero width, set `_size_known = True` and flush all deferred payloads
      - Alternatively, set in `on_mount` (widgets have known size by then)

  **Must NOT do**:
  - Do NOT add `append_with_typewriter()` or any animation features
  - Do NOT change the class name from `MessagesPanel`
  - Do NOT add new public methods beyond what exists
  - Do NOT modify `AutoScrollMixin`
  - Do NOT modify `__init__.py` exports (class name stays same)
  - Do NOT mutate `_lines` or `_current_line_buffer` from `append_message()` (thread safety!)
  - Do NOT call `Text.from_ansi()` during batch queue ingestion — only during `_flush_batch` on UI thread

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex implementation requiring understanding of Textual internals, threading model, rendering pipeline. Must get scroll offset, cache invalidation, and lifecycle correct.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `playwright`: Not needed — this is a backend widget rewrite, not browser work
    - `frontend-ui-ux`: Not needed — no visual design decisions, purely functional

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (sequential)
  - **Blocks**: [Task 4, Task 5]
  - **Blocked By**: [Task 1, Task 2]

  **References**:

  **Pattern References** (existing code to follow):
  - `ucagent/tui/widgets/messages_panel.py` (ENTIRE FILE) — Current implementation to replace. Preserve all AutoScrollMixin integration, BINDINGS, batch queue, soft-wrap, reflow logic. The executor must understand what's being replaced.
  - `ucagent/tui/mixins/auto_scroll.py` (ENTIRE FILE) — AutoScrollMixin interface: requires `.auto_scroll` attribute, `.scroll_end()`, `.scroll_offset.y`, `.max_scroll_y`, `.scroll_up()/.scroll_down()/.scroll_relative()`. The new widget must conform.
  - `ucagent/verify_ui.py:265-304` — Old urwid UI's `_update_ui_impl` method: shows the line buffer split logic `(msg + end).split("\n")` where segment[0] appends to last line, subsequent segments become new lines. THIS IS THE REFERENCE ALGORITHM for inline append.

  **API/Type References**:
  - `.venv/lib/python3.12/site-packages/textual/widgets/_rich_log.py:301-319` — `render_line()` and `_render_line()`: exact pattern for scroll offset compensation (`scroll_y + y`), horizontal cropping (`crop_extend`), and LRU caching
  - `.venv/lib/python3.12/site-packages/textual/widgets/_rich_log.py:175-284` — `write()` method: rendering pipeline from Rich objects to Strips: `console.render(renderable, render_options) → Segment.split_lines() → Strip.from_lines()`
  - `.venv/lib/python3.12/site-packages/textual/scroll_view.py` — ScrollView base class: `render_line(y)` contract, what attributes are inherited
  - `.venv/lib/python3.12/site-packages/textual/strip.py` — Strip class: `.from_lines()`, `.blank()`, `.crop_extend()`, `.adjust_cell_length()`, `.cell_length`

  **External References**:
  - Rich library `Text.from_ansi()` — Converts ANSI escape sequences to styled Text objects
  - Rich library `Segment.split_lines()` — Splits rendered Segments into per-line groups

  **WHY Each Reference Matters**:
  - `messages_panel.py`: The executor MUST understand every method being replaced to preserve behavior
  - `auto_scroll.py`: Without conforming to this interface, scroll behavior breaks
  - `verify_ui.py:265-304`: The inline append algorithm reference — don't reinvent, adapt this proven pattern
  - `_rich_log.py`: The rendering pipeline is non-trivial; must follow the same Segment→Strip conversion
  - `scroll_view.py`: Understanding the base class contract is essential for correct `render_line()` implementation

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Import and basic instantiation
    Tool: Bash
    Preconditions: Code changes applied
    Steps:
      1. Run: python -c "from ucagent.tui.widgets.messages_panel import MessagesPanel; print('OK')"
    Expected Result: Output "OK", no import errors
    Failure Indicators: ImportError, AttributeError
    Evidence: .sisyphus/evidence/task-3-import.txt

  Scenario: Class has required attributes
    Tool: Bash
    Preconditions: Code changes applied
    Steps:
      1. Run: python -c "
         from ucagent.tui.widgets.messages_panel import MessagesPanel
         from textual.scroll_view import ScrollView
         assert issubclass(MessagesPanel, ScrollView), 'Must subclass ScrollView'
         assert hasattr(MessagesPanel, 'append_message')
         assert hasattr(MessagesPanel, 'render_line')
         assert hasattr(MessagesPanel, '_flush_batch')
         assert hasattr(MessagesPanel, '_soft_wrap_text')
         assert hasattr(MessagesPanel, '_char_display_width')
         assert hasattr(MessagesPanel, '_reflow_history')
         print('All checks passed')
         "
    Expected Result: Output "All checks passed"
    Failure Indicators: AssertionError with specific message
    Evidence: .sisyphus/evidence/task-3-attributes.txt

  Scenario: Not a RichLog subclass
    Tool: Bash
    Preconditions: Code changes applied
    Steps:
      1. Run: python -c "
         from ucagent.tui.widgets.messages_panel import MessagesPanel
         from textual.widgets import RichLog
         assert not issubclass(MessagesPanel, RichLog), 'Must NOT subclass RichLog'
         print('Correct: not RichLog')
         "
    Expected Result: Output "Correct: not RichLog"
    Failure Indicators: AssertionError — still inheriting RichLog
    Evidence: .sisyphus/evidence/task-3-not-richlog.txt
  ```

  **Commit**: YES (groups with Task 4)
  - Message: `refactor(tui): replace RichLog with custom ScrollView in MessagesPanel for inline append`
  - Files: `ucagent/tui/widgets/messages_panel.py`
  - Pre-commit: `python -c "from ucagent.tui.widgets import MessagesPanel; print('OK')"`

- [ ] 4. Fix app.py message_echo + integration verification

  **What to do**:
  - In `ucagent/tui/app.py`, restore the `message_echo` method to its proper implementation:
    - Remove the debug hardcode line: `messages_panel.append_message("-")`
    - Remove the debug print: `print("Calling append")`
    - Uncomment and use: `messages_panel.append_message(f"{msg}{end}")`
  - Verify that the import of `MessagesPanel` in `app.py` still works (class name unchanged)
  - Verify that `compose()` yields `MessagesPanel(id="messages-panel")` — should be unchanged

  **Exact change in `app.py:164-173`**:
  ```python
  # FROM:
  def message_echo(self, msg: str, end: str = "\n") -> None:
      messages_panel = self.query_one("#messages-panel", MessagesPanel)
      # messages_panel.append_message(f"{msg}{end}")
      messages_panel.append_message("-")
      print("Calling append")

  # TO:
  def message_echo(self, msg: str, end: str = "\n") -> None:
      messages_panel = self.query_one("#messages-panel", MessagesPanel)
      messages_panel.append_message(f"{msg}{end}")
  ```

  **Must NOT do**:
  - Do NOT change the method signature of `message_echo`
  - Do NOT change any other method in app.py
  - Do NOT add new imports

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Tiny 3-line change in a single file
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (after Task 3)
  - **Blocks**: [Task 5]
  - **Blocked By**: [Task 3]

  **References**:

  **Pattern References**:
  - `ucagent/tui/app.py:164-173` — The exact lines to modify. Current state has commented-out correct code and debug hardcode.
  - `ucagent/verify_agent.py:531-541` — `message_echo(msg, end)` implementation showing how `handler(msg, end)` is called — confirms the (msg, end) parameter contract

  **WHY Each Reference Matters**:
  - `app.py:164-173`: Exact location of the bug/debug code to fix
  - `verify_agent.py:531-541`: Confirms the handler is called with (msg, end) — the fix must handle both params correctly

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: No debug code remains
    Tool: Bash
    Preconditions: Code changes applied
    Steps:
      1. Run: python -c "
         import ast, sys
         with open('ucagent/tui/app.py') as f:
             source = f.read()
         assert 'append_message(\"-\")' not in source, 'Debug hardcode still present'
         assert 'print(\"Calling append\")' not in source, 'Debug print still present'
         assert '# messages_panel.append_message' not in source, 'Commented-out code still present'
         assert 'append_message(f\"{msg}{end}\")' in source, 'Proper implementation missing'
         print('Clean')
         "
    Expected Result: Output "Clean"
    Failure Indicators: AssertionError with specific message
    Evidence: .sisyphus/evidence/task-4-no-debug.txt

  Scenario: message_echo exists with correct signature
    Tool: Bash
    Preconditions: Code changes applied
    Steps:
      1. Run: python -c "
         import inspect
         from ucagent.tui.app import VerifyApp
         sig = inspect.signature(VerifyApp.message_echo)
         params = list(sig.parameters.keys())
         assert 'msg' in params, 'Missing msg param'
         assert 'end' in params, 'Missing end param'
         print('Signature OK')
         "
    Expected Result: Output "Signature OK"
    Failure Indicators: ImportError or AssertionError
    Evidence: .sisyphus/evidence/task-4-signature.txt
  ```

  **Commit**: YES (groups with Task 3)
  - Message: `refactor(tui): replace RichLog with custom ScrollView in MessagesPanel for inline append`
  - Files: `ucagent/tui/app.py`
  - Pre-commit: `python -c "from ucagent.tui.app import VerifyApp; print('OK')"`

- [ ] 5. Write pytest tests for MessagesPanel

  **What to do**:
  Create `tests/test_messages_panel.py` with pytest tests covering the core behaviors of the rewritten MessagesPanel. Tests should exercise the widget logic **without** launching a full Textual app where possible (unit-level), plus a minimal Textual app test for integration.

  **Test cases to implement**:

  1. **Inline append (core behavior)**:
     - Call `_process_payload("hello")` then `_process_payload(" world")` — `_current_line_buffer` should be `"hello world"`, no finalized lines yet
     - Call `_process_payload("hello\n")` — should finalize one line, buffer empty
     - Call `_process_payload("a\nb\nc")` — should finalize "a" and "b", buffer has "c"

  2. **Newline handling**:
     - `_process_payload("\n")` — finalizes current buffer (even if empty), starts fresh
     - `_process_payload("line1\nline2\nline3\n")` — 3 finalized lines, buffer empty
     - `_process_payload("")` — no-op (no change to buffer or lines)

  3. **ANSI rendering preservation**:
     - `_process_payload("\033[31mred\033[0m text\n")` — finalized line should contain styled text (verify `_render_history[-1]` has style spans)
     - Verify `Text.from_ansi()` is used during finalization (check `_render_history` entries are Rich `Text` objects)

  4. **Empty and edge cases**:
     - Empty message: `_process_payload("")` should not add lines
     - Only newlines: `_process_payload("\n\n\n")` should produce 3 finalized lines (blank)
     - Rapid sequential appends: multiple `_process_payload` calls without `\n` should accumulate in buffer

  5. **Soft-wrap static methods**:
     - `_char_display_width('A')` → 1 (ASCII)
     - `_char_display_width('中')` → 2 (CJK)
     - `_soft_wrap_text(Text("hello world"), 5)` → wraps into multiple Text objects at width 5
     - `_soft_wrap_text(Text("中文测试"), 5)` → correctly handles CJK width (中文 = 4 chars display width, 测 pushes past 5)

  6. **Batch queue thread safety**:
     - `append_message("test")` should put into `_batch_queue` without touching `_lines`
     - After `append_message`, `_lines` should be unchanged (not modified until flush)

  7. **Integration test (Textual app)**:
     - Use `textual.testing` or `App.run_test()` to mount a minimal app with MessagesPanel
     - Call `append_message("hello\n")`, advance timers by 0.2s, verify content is rendered
     - This tests the full lifecycle: mount → queue → flush → render

  **Test structure**:
  ```python
  import pytest
  from rich.text import Text

  class TestMessagesPanelPayloadProcessing:
      """Tests for inline append logic via _process_payload"""

  class TestSoftWrap:
      """Tests for _soft_wrap_text and _char_display_width static methods"""

  class TestBatchQueue:
      """Tests for thread-safe append_message → queue behavior"""

  class TestIntegration:
      """Tests requiring a running Textual app"""
  ```

  **Implementation note**: For unit tests of `_process_payload`, you'll need to instantiate MessagesPanel within a minimal Textual app context (since ScrollView needs a compositor). Use a test fixture that creates a minimal app, mounts the widget, and gives you access to the instance. Check existing tests in the repo for patterns.

  **Must NOT do**:
  - Do NOT test internal Textual/ScrollView rendering (not our code)
  - Do NOT test AutoScrollMixin behavior (separate concern)
  - Do NOT add test infrastructure (pytest is already set up)
  - Do NOT over-test — focus on the NEW behaviors (inline append, payload processing)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Test writing requires understanding the widget internals and Textual testing patterns. Not trivial but well-scoped.
  - **Skills**: []
  - **Skills Evaluated but Omitted**:
    - `playwright`: Not needed — these are pytest unit/integration tests, not browser tests

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after Task 3, 4)
  - **Blocks**: [F1-F4]
  - **Blocked By**: [Task 3, Task 4]

  **References**:

  **Pattern References**:
  - `ucagent/tui/widgets/messages_panel.py` — The implementation being tested. Executor must read Task 3's implementation to understand internal methods (`_process_payload`, `_finalize_current_line`, `_current_line_buffer`, `_lines`, `_render_history`)
  - `tests/` directory — Check for existing test patterns, fixtures, conftest.py

  **API/Type References**:
  - `rich.text.Text` — `Text.from_ansi()` for ANSI parsing, `Text.plain` for extracting unstyled text, `.spans` for checking style info
  - Textual testing: `App.run_test()` async context manager for integration tests

  **External References**:
  - Textual testing guide: https://textual.textualize.io/guide/testing/ — How to use `run_test()` for widget tests
  - pytest-asyncio for async test support (if needed for `App.run_test()`)

  **WHY Each Reference Matters**:
  - `messages_panel.py`: The tests must exercise the actual methods — need to know their signatures and behavior
  - `tests/` directory: Must follow existing test conventions (if any)
  - Textual testing guide: Integration tests need the correct async pattern to mount widgets

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: All tests pass
    Tool: Bash
    Preconditions: Task 3 and Task 4 complete
    Steps:
      1. Run: python -m pytest tests/test_messages_panel.py -v
    Expected Result: All tests pass (0 failures), at least 10 test cases
    Failure Indicators: Any test failure, or fewer than 10 tests collected
    Evidence: .sisyphus/evidence/task-5-pytest.txt

  Scenario: Test file covers key behaviors
    Tool: Bash
    Preconditions: Test file created
    Steps:
      1. Run: python -m pytest tests/test_messages_panel.py --collect-only -q
    Expected Result: At least 10 tests collected, covering: inline append, newline handling, ANSI, empty cases, soft-wrap, batch queue
    Failure Indicators: Collection errors or fewer than 10 items
    Evidence: .sisyphus/evidence/task-5-collect.txt

  Scenario: No import errors in test file
    Tool: Bash
    Preconditions: Test file created
    Steps:
      1. Run: python -c "import tests.test_messages_panel; print('OK')"
    Expected Result: Output "OK"
    Failure Indicators: ImportError, SyntaxError
    Evidence: .sisyphus/evidence/task-5-import.txt
  ```

  **Commit**: YES
  - Message: `test(tui): add pytest tests for MessagesPanel ScrollView`
  - Files: `tests/test_messages_panel.py`
  - Pre-commit: `python -m pytest tests/test_messages_panel.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Rejection → fix → re-run.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run linter + `python -m pytest tests/test_messages_panel.py -v`. Review all changed files for: `as any`/`# type: ignore`, empty catches, print() in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | VERDICT`

---

## Commit Strategy

- **After Task 1**: `chore: cleanup leftover files from previous MessagesScrollView attempt`
- **After Task 4**: `refactor(tui): replace RichLog with custom ScrollView in MessagesPanel for inline append`
- **After Task 5**: `test(tui): add pytest tests for MessagesPanel ScrollView`

---

## Success Criteria

### Verification Commands
```bash
# Import check
python -c "from ucagent.tui.widgets import MessagesPanel; print('OK')"
# Expected: OK

# Attribute check
python -c "
from ucagent.tui.widgets.messages_panel import MessagesPanel
assert hasattr(MessagesPanel, 'append_message')
assert hasattr(MessagesPanel, 'render_line')
assert hasattr(MessagesPanel, '_flush_batch')
assert hasattr(MessagesPanel, '_soft_wrap_text')
assert hasattr(MessagesPanel, '_reflow_history')
assert hasattr(MessagesPanel, 'auto_scroll')
print('All attributes present')
"
# Expected: All attributes present

# Tests
python -m pytest tests/test_messages_panel.py -v
# Expected: All tests pass

# Leftover files cleaned
test ! -f IMPLEMENTATION_SUMMARY.md && test ! -f demo_messages_scroll.py && test ! -f test_multiline.py && echo "Clean"
# Expected: Clean
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] No leftover debug code (print statements, hardcoded "-")
