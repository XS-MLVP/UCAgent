"""Persistent Global conversation and independent Super/Sub execution pages."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Input, Static, Tree, Footer
from ucagent.interfaces.terminal.tui.widgets.messages_panel import MessagesPanel
from ucagent.interfaces.terminal.tui.agent_view import SuperAgentView, SubAgentView
from ucagent.core.multi_agent.global_agent.display import session_summary
from ucagent.interfaces.terminal.tui.agent_screen import AgentScreen

SESSION_CSS = """
Screen { background: $background; }
#global-body { height: 1fr; }
#global-conversation { width: 1fr; height: 1fr; border: solid $primary; }
#agent-tree { width: 38; border: solid $secondary; }
#global-input { height: 3; margin: 0 1; }
#session-status { height: auto; padding: 0 1; }
"""

class SessionApp(App):
    CSS = SESSION_CSS
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pages = {}
    def open_view(self, view):
        key = view.agent_id
        if key not in self.pages:
            page = AgentScreen(view)
            self.pages[key] = page
            self.install_screen(page, key)
        self.push_screen(key)

    def close_agent_page(self):
        if isinstance(self, AttachApp) and len(self.screen_stack) <= 2: self.exit()
        elif len(self.screen_stack) > 1: self.pop_screen()
        else: self.exit()

    def get_css_variables(self):
        variables = super().get_css_variables()
        key = "surface" if self.current_theme.name == "textual-light" else "surface-active"
        variables["console-input-focus"] = variables.get(key, variables.get("surface", "ansi_default"))
        return variables

class GlobalApp(SessionApp):
    TITLE = "UCAgent · Global"
    BINDINGS = [Binding("ctrl+c", "interrupt", "Interrupt Global", priority=True),
                Binding("ctrl+q", "detach", "Return to console", priority=True)]
    def __init__(self, session):
        super().__init__()
        self.frontend, self.host = session, session.host
        self.runtime = self.host.agent_sessions
        self.cursor = 0
        self.tree_state = None
        self.history = []
        self.history_index = 0
        self.refreshing = False
        self.capture = None
        self.session_output = ""
        self.previous_tool_suppression = False
        self.previous_human_suppression = False

    def compose(self):
        yield Static(f"Global | {self.runtime.workspace} | /help", id="session-status")
        with Horizontal(id="global-body"):
            yield MessagesPanel(id="global-conversation")
            yield Tree("Agents", id="agent-tree")
        yield Input(placeholder="Describe a task or ask about a running Agent...", id="global-input")
        yield Footer()

    def on_mount(self):
        self.conversation_panel = self.query_one("#global-conversation", MessagesPanel)
        self.agents_tree = self.query_one("#agent-tree", Tree)
        self.status_panel = self.query_one("#session-status", Static)
        self.previous_tool_suppression = getattr(self.host.agent, "suppress_tool_result_messages", False)
        self.host.agent.suppress_tool_result_messages = True
        self.previous_human_suppression = getattr(self.host.agent, "suppress_human_message_echo", False)
        self.host.agent.suppress_human_message_echo = True
        self.host.attach_control("global-tui", interrupt=self.action_interrupt, messages=True)
        self.capture = self.host.output.capture()
        self.capture.__enter__()
        self.query_one("#global-input", Input).focus()
        self.global_timer = self.set_interval(.2, self.refresh_global)
        self.host.startup.release()

    async def refresh_global(self):
        if self.refreshing or not self.is_mounted: return
        self.refreshing = True
        try:
            state = await asyncio.to_thread(self.runtime.list_agents)
            page = await asyncio.to_thread(self.runtime.events.read, self.cursor)
            if not self.conversation_panel.is_attached: return
            self.cursor = page["cursor"]
            panel = self.conversation_panel
            if page.get("gap"): panel.append_message("Earlier messages are available in the session archive.\n")
            for event in page["events"]:
                if event["agent_id"] == "global" and event["kind"] == "message":
                    panel.append_message(event["payload"].get("text", ""))
                elif event["agent_id"] == "global" and event["kind"] == "user_input":
                    panel.append_message(f"[You] {event['payload']['text']}\n")
                elif event["kind"] in {"queued", "started", "result", "waiting_input", "runtime_error"}:
                    data = event["payload"]
                    panel.append_message(f"[{event['agent_id']}] {data.get('status', event['kind'])}" +
                                         (f" · {data['error']}" if data.get("error") else "") + "\n")
            signature = [(a["agent_id"], a["status"], a["attempt"], a.get("stage_index"),
                          [(c["agent_id"], c.get("status")) for c in a.get("children", [])]) for a in state["agents"]]
            if signature != self.tree_state:
                self.tree_state = signature
                tree = self.agents_tree
                selected = tree.cursor_node.data if tree.cursor_node else None
                tree.clear()
                for agent in state["agents"]:
                    progress = f" {min(agent.get('stage_index', 0) + 1, len(agent['stages']))}/{len(agent['stages'])}" if agent.get("stages") else ""
                    node = tree.root.add(Text(f"{agent['status']}{progress} · {agent['workflow_ref'].rsplit(':', 1)[-1]} · {agent['agent_id'][-4:]}"), data=agent["agent_id"], expand=True)
                    if agent["agent_id"] == selected: tree.move_cursor(node)
                    for child in agent.get("children", []):
                        leaf = node.add_leaf(Text(f"{child.get('status', '')} · {child.get('task_id', '').rsplit('/', 1)[-1]}"), data=(agent["agent_id"], child["agent_id"]))
                        if leaf.data == selected: tree.move_cursor(leaf)
                tree.root.expand()
            pending = sum(x["state"] == "queued" for x in self.runtime.inbox.items)
            active = sum(a["status"] not in {"succeeded", "failed", "cancelled"} for a in state["agents"])
            self.status_panel.update(Text(f"Global | {active} active Supers | {pending} queued messages | /help"))
            if self.host.snapshot()["instance"] in {"closed", "failed"}: self.exit()
        finally: self.refreshing = False

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id != "global-input": return
        text = event.value.strip()
        if not text: return
        event.input.value = ""
        self.history.append(text); self.history_index = len(self.history)
        panel = self.query_one("#global-conversation", MessagesPanel)
        try:
            if text == "/help":
                panel.append_message("/agents · /open AGENT_ID · /cancel AGENT_ID · /retry AGENT_ID · /quit · Ctrl-Q: console\n")
            elif text == "/agents":
                panel.append_message(str(self.runtime.root) + "\n" + session_summary(await asyncio.to_thread(self.runtime.list_agents)) + "\n")
            elif text.startswith("/open "):
                self.open_agent(text.split(maxsplit=1)[1])
            elif text.startswith("/cancel "):
                result = await asyncio.to_thread(self.runtime.cancel_super, text.split(maxsplit=1)[1])
                panel.append_message(f"{result['agent_id']}: {result['status']}\n")
            elif text.startswith("/retry "):
                agent_id = text.split(maxsplit=1)[1]
                result = await asyncio.to_thread(self.runtime.retry_super, agent_id, self.runtime.agent_status(agent_id)["attempt"])
                panel.append_message(f"{agent_id}: attempt {result['attempt']} queued\n")
            elif text == "/quit": self.host.request_shutdown("operator_exit")
            elif text.startswith("/"): panel.append_message("Unknown interface command. Use /help.\n")
            else:
                await asyncio.to_thread(self.runtime.submit_input, text)
        except Exception as error: panel.append_message(f"Error: {error}\n")

    def open_agent(self, agent_id):
        self.runtime.agent_status(agent_id)
        self.open_view(SuperAgentView(self.runtime.agent_status, agent_id))

    def on_tree_node_selected(self, event: Tree.NodeSelected):
        if event.control.id != "agent-tree" or not event.node.data: return
        value = event.node.data
        if isinstance(value, tuple):
            parent, child = value
            self.open_view(SubAgentView(SuperAgentView(self.runtime.agent_status, parent), child))
        else: self.open_agent(value)

    def on_key(self, event):
        if len(self.screen_stack) != 1: return
        field = self.query_one("#global-input", Input)
        if field.has_focus and event.key in {"up", "down"}:
            self.history_index = max(0, min(len(self.history), self.history_index + (-1 if event.key == "up" else 1)))
            field.value = self.history[self.history_index] if self.history_index < len(self.history) else ""
            event.prevent_default(); event.stop()

    def action_interrupt(self):
        if isinstance(self.screen, AgentScreen):
            self.call_later(self.screen.action_interrupt)
            return
        item = self.runtime.inbox.active
        if item: self.host.operations.cancel(item["operation_id"])

    def action_detach(self):
        if isinstance(self.screen, AgentScreen): self.screen.action_back()
        else: self.exit()

    def on_unmount(self):
        self.global_timer.stop()
        self.host.detach_control("global-tui")
        self.host.agent.suppress_tool_result_messages = self.previous_tool_suppression
        self.host.agent.suppress_human_message_echo = self.previous_human_suppression

    def _release_capture(self):
        if self.capture is not None:
            self.capture.__exit__(None, None, None)
            self.capture = None
        if self.host.snapshot()["instance"] in {"closed", "failed"}:
            self.host.output.close()

    async def run_async(self, **kwargs):
        try: return await super().run_async(**kwargs)
        finally: self._release_capture()

    @asynccontextmanager
    async def run_test(self, **kwargs):
        try:
            async with super().run_test(**kwargs) as pilot: yield pilot
        finally: self._release_capture()

class AttachApp(SessionApp):
    def __init__(self, view):
        super().__init__()
        self.view = view
    def on_mount(self): self.open_view(self.view)
