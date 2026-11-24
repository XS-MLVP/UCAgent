"""Super/Sub pages using the established verification TUI widgets and stylesheet."""
from __future__ import annotations

import asyncio
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Static, Tree, HelpPanel, Button
from ucagent.interfaces.terminal.tui.widgets.recovery import RecoveryPanel, RecoveryDialog

from ucagent.interfaces.terminal.presentation import format_mission, format_status, format_data
from ucagent.interfaces.terminal.tui.agent_view import SubAgentView
from ucagent.interfaces.terminal.tui.screens import ThemePickerScreen
from ucagent.interfaces.terminal.tui.widgets import (
    TaskPanel, MessagesPanel, ConsoleWidget, ConsoleInput, StatusBar,
    VerticalSplitter, HorizontalSplitter,
)
from ucagent.interfaces.terminal.tui.widgets.splitter import _clamp_split_value


class AgentTaskPanel(TaskPanel):
    """Render the familiar Mission sections from detached session data."""

    def compose(self):
        yield Static(id="agent-title", classes="section-title", markup=False)
        yield Static(id="mission-title", classes="section-title", markup=False)
        yield Static(id="task-list", markup=False)
        yield Static(id="task-detail", markup=False)
        yield Tree("Sub agents", id="sub-tree")
        yield Static("Changed Files", classes="section-title")
        yield Static(id="changed-files", markup=False)
        yield Static("Tools Call", classes="section-title")
        yield Static(id="tool-status", markup=False)
        yield Static("Status", classes="section-title")
        yield Static(id="status-summary", markup=False)

    def on_mount(self, event):
        event.prevent_default()
        self.watch(self.screen, "task_width", self._apply_task_width)
        self._apply_task_width(self.screen.task_width)
        self.child_rows = None

    def update_snapshot(self, snapshot):
        """Keep stage colors, file timestamps, tool counts and task identity visible."""
        sub = snapshot.get("role") == "sub"
        mission = snapshot.get("mission")
        if mission:
            self.query_one("#mission-title", Static).update(mission["mission_name"])
            stages = Text.from_ansi("\n".join(format_mission(mission, use_skills=snapshot.get("use_skills", False))))
        else:
            self.query_one("#mission-title", Static).update(snapshot.get("workflow_ref", ""))
            stages = Text()
            for i, stage in enumerate(snapshot.get("stages", [])):
                completed = stage.get("is_completed", stage.get("completed", False))
                skipped = stage.get("is_skipped", False)
                current = i == snapshot.get("stage_index", 0)
                label = stage.get("title", stage.get("name", ""))
                stages.append(f"{i:2d} {label}" + (" (skipped)" if skipped else "") + "\n",
                              style="yellow" if skipped else "green" if completed else "red" if current else "")
        self.query_one("#task-list", Static).update(stages)
        detail = []
        for field, label in (("summary", "Result"), ("error", "Error")):
            if snapshot.get(field): detail.extend(["", label, str(snapshot[field])])
        if snapshot.get("artifacts"): detail.extend(["", "Artifacts", *snapshot["artifacts"].keys()])
        self.query_one("#task-detail", Static).update("\n".join(detail))
        tree = self.query_one("#sub-tree", Tree)
        tree.display = not sub and bool(snapshot.get("children"))
        rows = [(x["agent_id"], x.get("task_id", "").rsplit("/", 1)[-1], x.get("status", ""))
                for x in snapshot.get("children", [])]
        if rows != self.child_rows:
            selected = tree.cursor_node.data if tree.cursor_node else None
            tree.clear()
            for key, task, state in rows:
                node = tree.root.add_leaf(Text(f"{state} · {task}"), data=key)
                if selected == key: tree.move_cursor(node)
            tree.root.expand()
            self.child_rows = rows
        from ucagent.util.functions import fmt_time_stamp, fmt_time_deta
        changed = Text()
        for row in snapshot.get("changed_files", [])[:5]:
            age = row.get("age_seconds")
            when = fmt_time_stamp(row["mtime"]) if row.get("mtime") else ""
            if age is not None and age < 180: when += f" ({fmt_time_deta(age)})"
            path = row["path"] + (" (deleted)" if row.get("deleted") else "")
            changed.append(f"{when}: {path}\n" if when else path + "\n",
                           style="green" if age is not None and age < 180 else "")
        self.query_one("#changed-files", Static).update(changed)
        tools = Text()
        for tool in snapshot.get("tools", []):
            tools.append(f"{tool['name']}({tool['call_count']}) ", style="yellow" if tool["is_hot"] else "")
        self.query_one("#tool-status", Static).update(tools)
        state = f"{snapshot.get('status', 'unknown')} | attempt {snapshot.get('attempt', 1)}"
        if snapshot.get("readonly"): state += " | read-only"
        if snapshot.get("connected") is False: state += " | disconnected"
        if snapshot.get("statistics"): state += "\n" + format_status(snapshot["statistics"])
        self.query_one("#status-summary", Static).update(Text(state))


class AgentStatusBar(StatusBar):
    """Use the original bottom bar without reaching into another Agent's objects."""

    def on_mount(self, event):
        event.prevent_default()
        self.query_one("#status-hint", Static).update("F1 shortcuts · Esc back")

    def update_snapshot(self, snapshot):
        stats = snapshot.get("statistics", {})
        parts = [f"{label}: {self._format_value(stats.get(key, '—'))}" for label, key in
                 (("Run Time", "Run Time"), ("Model", "LLM"), ("Speed", "Token Speed"), ("Idle", "Idle"))]
        parts.extend([f"Backend: {snapshot.get('backend', '—')}",
                      f"Stream: {stats.get('Stream', '—')}",
                      f"Mode: {stats.get('Interaction Mode', '—')}"])
        if snapshot.get("role") == "sub": parts.insert(0, f"Sub: {snapshot.get('status', 'unknown')}")
        self._raw_text = " | ".join(parts)
        self.query_one("#status-left", Static).update(Text(self._truncate_left(self._raw_text)))


class AgentScreen(Screen):
    """A persistent execution page with the same layout and controls as VerifyApp."""

    CSS_PATH = "styles/default.tcss"
    CSS = "#sub-tree { height: auto; max-height: 12; } #task-detail { height: auto; }"
    # Recovery controls must not take the initial command input focus.
    AUTO_FOCUS = "#console-input"

    BINDINGS = [Binding("escape", "back", "Back", priority=True),
                Binding("ctrl+c", "interrupt", "Cancel operation", priority=True),
                Binding("ctrl+q", "back", "Back", priority=True),
                Binding("f1", "toggle_help", "Help"),
                Binding("ctrl+t", "choose_theme", "Theme")]
    BINDINGS += [Binding(key, "split_" + direction, show=False, priority=True)
                 for key, direction in (("ctrl+left", "left"), ("ctrl+right", "right"),
                     ("ctrl+up", "up"), ("ctrl+down", "down"), ("ctrl+h", "left"),
                     ("ctrl+l", "right"), ("ctrl+k", "up"), ("ctrl+j", "down"))]
    task_width = reactive(84)
    console_height = reactive(13)

    def __init__(self, view, *, title=None):
        super().__init__()
        self.view = view
        self.title_text = title or view.agent_id
        self.cursor = 0
        self.stream_id = None
        self.history = []
        self.history_index = 0
        self.refreshing = False
        self.snapshot_data = {}
        self.key_handler = self

    def compose(self):
        with Vertical(id="app-container"):
            with Horizontal(id="main-container"):
                yield AgentTaskPanel(id="task-panel")
                yield VerticalSplitter("task_width", owner=self, id="split-task", classes="splitter vertical")
                with Vertical(id="right-container"):
                    yield RecoveryPanel(id="recovery-panel")
                    yield MessagesPanel(id="messages-panel")
            yield HorizontalSplitter("console_height", invert=True, owner=self,
                                     id="split-console", classes="splitter horizontal")
            with Vertical(id="console-container"):
                yield ConsoleWidget(id="console", prompt="(UnityChip) ", owner=self)
                yield AgentStatusBar(id="status-bar")

    def on_mount(self):
        self.messages_panel = self.query_one(MessagesPanel)
        self.console_panel = self.query_one(ConsoleWidget)
        self.title_panel = self.query_one("#agent-title", Static)
        self.task_panel = self.query_one(AgentTaskPanel)
        self.input_panel = self.query_one(ConsoleInput)
        self.status_bar = self.query_one(AgentStatusBar)
        self.task_width = min(self.task_width, max(26, self.app.size.width - 60))
        self.console_height = self.app.size.height // 2
        self.title_panel.update(Text(self.title_text))
        self.input_panel.focus_input()
        self.view_timer = self.set_interval(.25, self.refresh_view)
        self.call_after_refresh(self.refresh_view)

    async def refresh_view(self):
        if self.refreshing or not self.is_mounted: return
        self.refreshing = True
        try:
            snapshot = await asyncio.to_thread(self.view.snapshot)
            if not self.messages_panel.is_attached: return
            stream_id = snapshot.get("stream_id")
            if self.stream_id is not None and self.stream_id != stream_id:
                self.cursor = 0
                self.messages_panel.clear()
                self.console_panel.clear_output(sync_to_console=False)
            self.stream_id = stream_id
            page = await asyncio.to_thread(self.view.events_since, self.cursor)
            if not self.messages_panel.is_attached: return
            self.cursor = page["cursor"]
            self.snapshot_data = snapshot
            role = snapshot.get("role", "super").capitalize()
            self.title_panel.update(Text(f"{role} · {self.title_text}"))
            self.task_panel.update_snapshot(snapshot)
            self.query_one(RecoveryPanel).update_snapshot(snapshot)
            self.status_bar.update_snapshot(snapshot)
            self.input_panel.prompt = "(To Super) " if role == "Sub" else "(Guidance · /chat) "
            if snapshot.get("readonly"): self.input_panel.prompt = "(Read-only; Esc back) "
            self.input_panel.refresh_prompt()
            running = [r["command"] for r in snapshot.get("operations", []) if r["state"] not in {"succeeded", "failed", "cancelled"}] if role != "Sub" else []
            self.input_panel.set_busy(bool(running) and not snapshot.get("readonly"))
            self.input_panel.update_running_commands(running)
            if page.get("gap"): self.console_panel.append_output("Earlier output is in the session event archive.\n", sync_to_console=False)
            for event in page["events"]:
                if event["kind"] in {"message", "attention"} or (role == "Sub" and event["kind"] == "tool_detail"):
                    self.messages_panel.append_message(event["payload"].get("text", ""))
                elif event["kind"] == "console" and event["agent_id"] == self.view.agent_id:
                    self.console_panel.append_output(event["payload"].get("text", ""), sync_to_console=False)
        except Exception as error:
            if self.title_panel.is_attached: self.title_panel.update(Text(f"{self.title_text} | disconnected: {error}"))
        finally:
            self.refreshing = False

    def on_resize(self, event):
        """Keep the state card and messages usable on narrow terminals."""
        if self.is_mounted:
            self.task_width = min(self.task_width, max(26, event.size.width - 60))

    def on_unmount(self):
        self.view_timer.stop()

    def command_names(self):
        if self.snapshot_data.get("role") == "sub": return set()
        return {name for row in self.snapshot_data.get("commands", []) for name in (row["name"], *row["aliases"])}

    def complete_command(self, text):
        if " " in text: return []
        prefix = "/" if text.startswith("/") else ""
        names = self.command_names() | {"back", "help", "clear", "quit"}
        return sorted(prefix + name for name in names if (prefix + name).startswith(text))

    def get_history_item(self, direction):
        self.history_index = max(0, min(len(self.history), self.history_index + direction))
        return self.history[self.history_index] if self.history_index < len(self.history) else ""

    async def on_console_input_command_submitted(self, event):
        event.stop()
        text = event.command.strip()
        if not text: return
        self.history.append(text)
        self.history_index = len(self.history)
        command = text.removeprefix("/")
        if command in {"back", "global", "quit", "exit", "q"}: self.action_back(); return
        if command == "clear": self.console_panel.clear_output(sync_to_console=False); return
        self.console_panel.echo_command(text, sync_to_console=False)
        if command == "help":
            self.console_panel.append_output("Enter a registered command or supplemental instruction. Sub guidance goes to its Super.\nEsc/back: return · Ctrl-C: interrupt · Ctrl-arrows: resize · F1: shortcuts\n" + ", ".join(sorted(self.command_names())) + "\n", sync_to_console=False)
            return
        try:
            if snapshot := self.snapshot_data.get("recovery", {}).get("issue"):
                verb, _, message = command.partition(" ")
                if text.startswith("/") and verb in {"resume", "reply", "budget"}:
                    if verb == "budget":
                        await self.on_button_pressed(Button.Pressed(self.query_one("#recovery-grant", Button)))
                        return
                    result = await asyncio.to_thread(self.view.recover, {"issue_id": snapshot["id"],
                        "action": "reply" if verb == "reply" else "resume", "message": message})
                    self.console_panel.append_output("Action accepted.\n", sync_to_console=False)
                    return
            result = await asyncio.to_thread(self.view.submit_input, command if text.startswith("/") else text,
                                             command=text.startswith("/") or text.split()[0] in self.command_names())
            if self.console_panel.is_attached: self.console_panel.append_output(format_data(result) + "\n", sync_to_console=False)
        except Exception as error:
            if self.console_panel.is_attached: self.console_panel.append_output(str(error) + "\n", sync_to_console=False)

    async def on_button_pressed(self, event: Button.Pressed):
        """Open the action-specific form without changing the task on selection."""
        if not (event.button.id or "").startswith("recovery-"):
            return
        event.stop()
        action = event.button.id.removeprefix("recovery-")
        if action == "parent":
            self.app.open_view(self.view.parent)
            return
        snapshot = self.snapshot_data
        recovery = snapshot.get("recovery") or snapshot.get("parent_recovery") or {}
        if not recovery.get("issue") and snapshot.get("issue"):
            recovery = {"issue": snapshot["issue"]}
        if not recovery.get("issue"):
            return
        async def apply(request):
            """Submit the reviewed action off the UI thread and refresh its result."""
            if not request:
                return
            try:
                if request["action"] == "review":
                    result = await asyncio.to_thread(self.view.review, request["issue_id"],
                        snapshot["stage_index"], snapshot["control_revision"], request["message"])
                else:
                    result = await asyncio.to_thread(self.view.recover, request)
                self.console_panel.append_output("Action accepted.\n", sync_to_console=False)
                await self.refresh_view()
            except Exception as error:
                self.console_panel.append_output(str(error) + "\n", sync_to_console=False)
        self.app.push_screen(RecoveryDialog(recovery, action), apply)

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        if event.control.id == "sub-tree" and event.node.data:
            event.stop()
            self.app.open_view(SubAgentView(self.view, event.node.data))

    def action_back(self):
        if self.query("#help-overlay"):
            self.query("#help-overlay").remove()
        elif self.console_panel._manual_scroll:
            self.console_panel.action_exit_page_mode()
        elif self.input_panel.has_suggestions:
            self.input_panel.clear_suggestions()
        else:
            self.app.close_agent_page()

    async def action_interrupt(self):
        try:
            result = await asyncio.to_thread(self.view.cancel_operation)
            if self.console_panel.is_attached: self.console_panel.append_output(format_data(result) + "\n", sync_to_console=False)
        except Exception as error:
            if self.console_panel.is_attached: self.console_panel.append_output(str(error) + "\n", sync_to_console=False)

    def action_toggle_help(self):
        if self.query("#help-overlay"): self.query("#help-overlay").remove()
        else:
            help_panel = HelpPanel(id="help-overlay")
            help_panel.border_title = "Keys"
            self.mount(help_panel)

    def action_choose_theme(self):
        def apply(theme):
            if theme: self.app.theme = theme
        self.app.push_screen(ThemePickerScreen(sorted(self.app.available_themes), current=self.app.theme), apply)

    def watch_task_width(self, value):
        if self.is_mounted: self.query_one(AgentTaskPanel).styles.width = value

    def action_split_left(self): self.task_width = _clamp_split_value("task_width", self.task_width - 2)
    def action_split_right(self): self.task_width = _clamp_split_value("task_width", self.task_width + 2)
    def action_split_up(self): self.console_height = _clamp_split_value("console_height", self.console_height + 2)
    def action_split_down(self): self.console_height = _clamp_split_value("console_height", self.console_height - 2)
