"""Interactive Global layout, persistent Agent pages and message identity routing."""
import asyncio
import json
from pathlib import Path
import pytest
from textual.widgets import Input, Tree, Static
from ucagent.interfaces.terminal.tui.global_app import GlobalApp, AttachApp, AgentScreen
from ucagent.interfaces.terminal.tui.agent_view import SuperAgentView, SubAgentView
from ucagent.interfaces.terminal.tui.widgets.messages_panel import MessagesPanel
from ucagent.interfaces.terminal.presentation import format_result, format_operation
from ucagent.runtime.session import RuntimeSession
from ucagent.runtime.agent_events import GlobalInbox, atomic_json
from test_runtime_host import make_host
from test_global_agent import runtime, start, prepare

@pytest.fixture
def global_session(runtime, tmp_path):
    host, _ = make_host(tmp_path / "global-host", mode="console")
    host.agent_sessions = runtime
    runtime.host = host
    runtime.inbox = GlobalInbox(host, runtime.root, runtime.events)
    seen = []
    host.agent.one_loop = lambda text=None: seen.append(text)
    frontend = RuntimeSession(host, result_formatter=format_result, operation_formatter=format_operation)
    host.start()
    yield frontend, runtime, seen
    host.request_shutdown(); host.wait(3)

def panel_text(panel):
    state = panel.export_state()
    return "\n".join(row.plain for row in state.render_history) + state.current_line_buffer


async def wait_for_agent_messages(pilot, agent_id, expected):
    """Wait for asynchronous page delivery instead of assuming a fixed render latency."""
    deadline = asyncio.get_running_loop().time() + 3
    observed = ""
    while asyncio.get_running_loop().time() < deadline:
        await pilot.pause(.02)
        page = pilot.app.screen
        if not isinstance(page, AgentScreen) or page.view.agent_id != agent_id:
            continue
        panels = list(page.query(MessagesPanel))
        if panels:
            observed = panel_text(panels[0])
            if expected in observed:
                return
    pytest.fail(f"Agent {agent_id} did not display {expected!r}; observed {observed!r}")


def saved_output(runtime, agent_id):
    run = runtime.runs[agent_id]
    root = Path(run["result_path"]).parent
    child = agent_id + "/attempt-1/plan/task"
    run["children"] = [{"agent_id": child, "parent_id": agent_id, "role": "sub", "task_id": "plan/task", "status": "running", "instruction": "Produce the verified task artifact"}]
    run["stages"] = [{"name": "prepare", "completed": False}]
    run["mission"] = {"mission_name": "Full workflow", "current_index": 0, "stages": [
        {"index": 0, "name": "prepare", "title": "prepare", "is_current": True},
        {"index": 1, "name": "later", "title": "later"}]}
    run["statistics"] = {"LLM": "super-model", "Tool Calls": 100}
    run["tools"] = [{"name": "SubAgentTool", "call_count": 4, "is_hot": False}]
    run["children"][0].update(attempt=1,
        mission={"mission_name": "Full workflow", "current_index": 0,
                 "stages": [run["mission"]["stages"][0]]},
        statistics={"LLM": "sub-model", "Tool Calls": 3},
        tools=[{"name": "ReadTextFile", "call_count": 3, "is_hot": False}],
        changed_files=[{"path": "out/sub.txt"}], backend="codex")
    atomic_json(root / "view_snapshot.json", run)
    (root / "view").mkdir(exist_ok=True)
    rows = [dict(seq=1, agent_id=agent_id, kind="message", payload={"text": "SUPER DETAILS\n"}),
            dict(seq=2, agent_id=child, kind="message", payload={"text": "SUB DETAILS\n"}),
            dict(seq=3, agent_id=agent_id, kind="console", payload={"text": "\x1b[32mSERVICE READY\x1b[0m\n"}),
            dict(seq=4, agent_id=child, kind="console", payload={"text": "SUB EXECUTION LOG\n", "worker_attempt": 1}),
            dict(seq=5, agent_id=child, kind="tool_detail", payload={"text": "Tool Result: ReadTextFile\nFILE BODY\n", "worker_attempt": 1}),
            dict(seq=6, agent_id=agent_id + "/attempt-1/plan/sibling", kind="console", payload={"text": "SIBLING LOG\n", "worker_attempt": 1})]
    (root / "view/events.jsonl").write_text("\n".join(json.dumps(x) for x in rows)+"\n")
    return child

@pytest.mark.asyncio
async def test_global_is_idle_and_accepts_natural_language(global_session):
    frontend, runtime, seen = global_session
    app = GlobalApp(frontend)
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause(.25)
        assert seen == [] and runtime.runs == {}
        assert frontend.host.agent.suppress_tool_result_messages is True
        field = app.query_one("#global-input", Input)
        field.value = "Use the producer workflow"
        await pilot.press("enter")
        prepare(runtime)
        await pilot.pause(.15)
        assert seen == ["Use the producer workflow"]
        assert panel_text(app.query_one("#global-conversation", MessagesPanel)).count("Use the producer workflow") == 1
        assert frontend.host.snapshot()["instance"] == "ready"
    assert frontend.host.snapshot()["instance"] == "ready"
    assert frontend.host.agent.suppress_tool_result_messages is False
    assert frontend.host.agent.suppress_human_message_echo is False

@pytest.mark.asyncio
async def test_independent_super_sub_pages_and_draft(global_session):
    frontend, runtime, _ = global_session
    a = start(runtime, "a"); b = start(runtime, "b")
    prepare(runtime)
    child = saved_output(runtime, a); saved_output(runtime, b)
    runtime.events.append("global", "message", text="GLOBAL CHAT\n")
    runtime.events.append(a, "message", text="CHILD NOISE\n")
    app = GlobalApp(frontend)
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause(.3)
        text = panel_text(app.query_one("#global-conversation", MessagesPanel))
        assert "GLOBAL CHAT" in text and "CHILD NOISE" not in text
        node = app.query_one("#agent-tree", Tree).root.children[0]
        assert "running" in node.label.plain and "produce" in node.label.plain
        assert "\n" not in node.label.plain
        assert node.children[0].label.plain == "running · task"
        app.open_agent(a)
        await wait_for_agent_messages(pilot, a, "SUPER DETAILS")
        assert isinstance(app.screen, AgentScreen)
        assert "SUPER DETAILS" in panel_text(app.screen.query_one("#messages-panel", MessagesPanel))
        from xml.etree import ElementTree
        ElementTree.fromstring(app.export_screenshot())  # ANSI logs cannot leak invalid control bytes.
        app.screen.query_one("#console-input", Input).value = "saved draft"
        app.screen.action_back()
        await pilot.pause(.1)
        app.open_agent(b)
        await wait_for_agent_messages(pilot, b, "SUPER DETAILS")
        assert app.screen.query_one("#console-input", Input).value == ""
        app.screen.action_back()
        app.open_agent(a)
        await wait_for_agent_messages(pilot, a, "SUPER DETAILS")
        assert app.screen.query_one("#console-input", Input).value == "saved draft"
        app.open_view(SubAgentView(SuperAgentView(runtime.agent_status, a), child))
        await wait_for_agent_messages(pilot, child, "SUB DETAILS")
        text = panel_text(app.screen.query_one("#messages-panel", MessagesPanel))
        assert "SUB DETAILS" in text and "SUPER DETAILS" not in text
        assert "Produce the verified task artifact" not in str(app.screen.query_one("#task-detail", Static).render())
        assert len(runtime.launcher.starts) == 2

@pytest.mark.asyncio
async def test_attach_only_opens_an_existing_view(global_session):
    _, runtime, _ = global_session
    agent_id = start(runtime); prepare(runtime); saved_output(runtime, agent_id)
    app = AttachApp(SuperAgentView(runtime.agent_status, agent_id))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(.3)
        assert "SUPER DETAILS" in panel_text(app.screen.query_one("#messages-panel", MessagesPanel))
        assert len(runtime.launcher.starts) == 1
        await pilot.press("escape")
    assert runtime.agent_status(agent_id)["status"] == "running"


@pytest.mark.asyncio
async def test_interrupt_targets_the_visible_agent(global_session):
    """Ctrl-C from a Super page never interrupts Global's separate conversation."""
    frontend, runtime, _ = global_session
    agent_id = start(runtime); prepare(runtime); saved_output(runtime, agent_id)
    calls = []
    class View(SuperAgentView):
        def cancel_operation(self):
            calls.append(self.agent_id)
            return {"state": "paused"}
    app = GlobalApp(frontend)
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause(.2)
        app.open_view(View(runtime.agent_status, agent_id))
        await pilot.pause(.2)
        await pilot.press("ctrl+c")
        await pilot.pause(.2)
        assert calls == [agent_id]
        assert frontend.host.snapshot()["instance"] == "ready"
        assert runtime.agent_status(agent_id)["status"] == "running"


def test_global_input_echo_does_not_change_model_history():
    """The TUI echoes input on admission; model history still retains the real Human message."""
    from types import SimpleNamespace
    from langchain_core.messages import HumanMessage, AIMessage
    from ucagent.core.backends.langchain.agent import UCAgentLangChainBackend
    backend = UCAgentLangChainBackend.__new__(UCAgentLangChainBackend)
    backend.vagent = SimpleNamespace(suppress_human_message_echo=True)
    human = HumanMessage(content="one user request")
    assert backend.format_message(human) == "" and human.content == "one user request"
    assert "model reply" in backend.format_message(AIMessage(content="model reply"))
    backend.vagent.suppress_human_message_echo = False
    assert "one user request" in backend.format_message(human)


@pytest.mark.asyncio
async def test_inflight_refresh_can_finish_after_view_detaches(global_session, monkeypatch):
    """A transport response racing with TUI removal cannot query a destroyed screen."""
    import asyncio
    import threading
    frontend, runtime, _ = global_session
    app = GlobalApp(frontend)
    entered, release = threading.Event(), threading.Event()
    original = runtime.list_agents
    def slow_snapshot():
        entered.set()
        assert release.wait(3)
        return original()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(.3)
        app.global_timer.stop()
        monkeypatch.setattr(runtime, "list_agents", slow_snapshot)
        refresh = asyncio.create_task(app.refresh_global())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await app.conversation_panel.remove()
        finally:
            release.set()
        await refresh
        assert frontend.host.snapshot()["instance"] == "ready"


@pytest.mark.asyncio
async def test_execution_layout_splitters_and_global_remain_independent(global_session):
    """Both execution pages retain the established layout, with page-local resizing."""
    from ucagent.interfaces.terminal.tui.widgets import TaskPanel, ConsoleWidget, StatusBar
    frontend, runtime, _ = global_session
    agent_id = start(runtime); prepare(runtime); child = saved_output(runtime, agent_id)
    app = GlobalApp(frontend)
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.pause(.3)
        global_regions = {key: app.query_one(key).region for key in
                          ("#global-conversation", "#agent-tree", "#global-input")}
        app.open_agent(agent_id)
        await wait_for_agent_messages(pilot, agent_id, "SUPER DETAILS")
        parent = app.screen
        for selector, widget_type in (("#task-panel", TaskPanel), ("#messages-panel", MessagesPanel),
                                      ("#console", ConsoleWidget), ("#status-bar", StatusBar)):
            assert isinstance(parent.query_one(selector), widget_type)
        mission = parent.query_one(TaskPanel)
        messages = parent.query_one(MessagesPanel)
        console = parent.query_one(ConsoleWidget)
        assert mission.border_title == "Mission" and console.border_title == "Console"
        assert mission.region.width == 84
        assert messages.region.x > mission.region.right
        assert console.region.y > mission.region.bottom and console.region.width == 160
        assert parent.query_one(StatusBar).region.y == 47
        await pilot.press("ctrl+left", "ctrl+up")
        await pilot.pause()
        assert parent.task_width == 82 and parent.console_height == 26
        splitter = parent.query_one("#split-task").region
        await pilot.mouse_down(offset=(splitter.x, splitter.y + 2))
        await pilot.hover(offset=(splitter.x - 6, splitter.y + 2))
        await pilot.mouse_up(offset=(splitter.x - 6, splitter.y + 2))
        horizontal = parent.query_one("#split-console").region
        await pilot.mouse_down(offset=(10, horizontal.y))
        await pilot.hover(offset=(10, horizontal.y + 3))
        await pilot.mouse_up(offset=(10, horizontal.y + 3))
        await pilot.pause()
        assert mission.region.width == 76 and parent.console_height == 23
        app.open_view(SubAgentView(parent.view, child))
        await pilot.pause(.3)
        assert app.screen.task_width == 84 and app.screen.console_height == 24
        assert isinstance(app.screen.query_one(TaskPanel), TaskPanel)
        assert isinstance(app.screen.query_one(ConsoleWidget), ConsoleWidget)
        assert app.screen.query_one(StatusBar).region.y == 47
        await pilot.press("ctrl+right", "ctrl+down", "escape")
        assert app.screen is parent and parent.task_width == 76 and parent.console_height == 23
        await pilot.press("escape")
        assert all(app.query_one(key).region == region for key, region in global_regions.items())
        assert not app.screen.query("#task-panel")
        app.open_agent(agent_id)
        await pilot.pause()
        assert app.screen is parent and mission.region.width == 76


@pytest.mark.asyncio
async def test_execution_history_completion_and_console_are_page_local(global_session):
    """Commands target Super, Sub instructions route through it, and Global stays separate."""
    from ucagent.interfaces.terminal.tui.widgets import ConsoleWidget
    frontend, runtime, _ = global_session
    agent_id = start(runtime); prepare(runtime); child = saved_output(runtime, agent_id)
    calls = []
    class View(SuperAgentView):
        def snapshot(self):
            return {**super().snapshot(), "readonly": False,
                    "commands": [{"name": "status", "aliases": ["st"]}]}
        def submit_input(self, text, *, command=False):
            calls.append((text, command))
            return {"state": "queued"}
    app = GlobalApp(frontend)
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.pause(.3)
        app.open_view(View(runtime.agent_status, agent_id))
        await wait_for_agent_messages(pilot, agent_id, "SUPER DETAILS")
        parent = app.screen
        field = parent.query_one("#console-input", Input)
        assert "status" in parent.command_names() and app.focused is field
        field.value = "stat"
        await pilot.press("tab")
        assert field.value == "status"
        await pilot.press("enter")
        field.value = "consider the timing constraint"
        await pilot.press("enter", "up")
        assert field.value == "consider the timing constraint"
        await pilot.press("up")
        assert field.value == "status"
        await pilot.press("down", "down")
        assert field.value == ""
        assert calls == [("status", True), ("consider the timing constraint", False)]
        app.open_view(SubAgentView(parent.view, child))
        await wait_for_agent_messages(pilot, child, "FILE BODY")
        sub = app.screen
        sub_field = sub.query_one("#console-input", Input)
        await pilot.press("up")
        assert sub_field.value == ""
        sub_field.value = "add boundary cases"
        await pilot.press("enter", "up")
        assert sub_field.value == "add boundary cases"
        assert calls[-1] == (f"Regarding Sub {child}: add boundary cases", False)
        assert sub.history == ["add boundary cases"]
        assert parent.history == ["status", "consider the timing constraint"]
        assert "SERVICE READY" in "".join(x.payload for x in parent.query_one(ConsoleWidget).export_state().entries)
        assert "SERVICE READY" not in "".join(x.payload for x in sub.query_one(ConsoleWidget).export_state().entries)
        assert "consider the timing constraint" not in frontend.render_console_entries_since()
        await pilot.press("escape", "escape")
        assert not app.history
        assert "add boundary cases" not in panel_text(app.query_one("#global-conversation", MessagesPanel))


@pytest.mark.asyncio
async def test_execution_help_and_theme_preserve_the_page_and_draft(global_session):
    """The old help/theme controls remain usable on an attached Agent screen."""
    from ucagent.interfaces.terminal.tui.screens import ThemePickerScreen
    _, runtime, _ = global_session
    agent_id = start(runtime); prepare(runtime); saved_output(runtime, agent_id)
    app = AttachApp(SuperAgentView(runtime.agent_status, agent_id))
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.pause(.3)
        page = app.screen
        field = page.query_one("#console-input", Input)
        field.value = "unfinished instruction"
        await pilot.press("f1")
        assert page.query("#help-overlay")
        await pilot.press("escape")
        assert not page.query("#help-overlay") and app.screen is page
        assert field.value == "unfinished instruction"
        original_theme = app.theme
        await pilot.press("ctrl+t")
        assert isinstance(app.screen, ThemePickerScreen)
        modal = app.screen.query_one("#theme-picker")
        assert modal.region.width == 34 and modal.region.x == 63
        assert app.screen.styles.background.a == 0
        await pilot.press("down", "escape")
        assert app.theme == original_theme and app.screen is page
        assert field.value == "unfinished instruction"


@pytest.mark.asyncio
async def test_super_and_sub_missions_console_and_details_are_scoped(global_session):
    """Execution pages retain the familiar sections and route telemetry by owner."""
    from ucagent.interfaces.terminal.tui.widgets import ConsoleWidget
    frontend, runtime, _ = global_session
    agent_id = start(runtime)
    prepare(runtime)
    child = saved_output(runtime, agent_id)
    app = GlobalApp(frontend)
    def rendered(page, selector):
        return str(page.query_one(selector, Static).render())
    def console(page):
        return "".join(row.payload for row in page.query_one(ConsoleWidget).export_state().entries)
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.pause(.2)
        app.open_agent(agent_id)
        await wait_for_agent_messages(pilot, agent_id, "SUPER DETAILS")
        parent = app.screen
        assert "later" in rendered(parent, "#task-list")
        assert not parent.query("#daemon-cmds")
        assert "Produce the verified task artifact" not in rendered(parent, "#task-detail")
        assert "SubAgentTool(4)" in rendered(parent, "#tool-status")
        assert "super-model" in rendered(parent, "#status-summary")
        messages = panel_text(parent.query_one(MessagesPanel))
        assert "SUPER DETAILS" in messages and "SUB DETAILS" in messages
        assert "FILE BODY" not in messages
        assert "SERVICE READY" in console(parent)
        assert "SUB EXECUTION LOG" not in console(parent) and "SIBLING LOG" not in console(parent)
        app.open_view(SubAgentView(parent.view, child))
        await wait_for_agent_messages(pilot, child, "FILE BODY")
        sub = app.screen
        assert "prepare" in rendered(sub, "#task-list") and "later" not in rendered(sub, "#task-list")
        assert not sub.query("#daemon-cmds")
        assert "Produce the verified task artifact" not in rendered(sub, "#task-detail")
        assert "ReadTextFile(3)" in rendered(sub, "#tool-status")
        assert "SubAgentTool" not in rendered(sub, "#tool-status")
        assert "sub-model" in rendered(sub, "#status-summary")
        assert "super-model" not in rendered(sub, "#status-summary")
        assert "out/sub.txt" in rendered(sub, "#changed-files")
        assert "FILE BODY" in panel_text(sub.query_one(MessagesPanel))
        assert "SUB EXECUTION LOG" in console(sub)
        assert "SERVICE READY" not in console(sub) and "SIBLING LOG" not in console(sub)


def test_sub_retry_changes_stream_and_filters_previous_attempt():
    """Retrying a logical task starts a clean display and does not replay prior logs."""
    from types import SimpleNamespace
    child = {"agent_id": "super/attempt-1/plan/task", "attempt": 1, "statistics": {"Tool Calls": 2}}
    events = [{"agent_id": child["agent_id"], "payload": {"worker_attempt": i}, "kind": "console"} for i in (1, 2)]
    parent = SimpleNamespace(agent_id="super", snapshot=lambda: {
        "children": [child], "statistics": {"Tool Calls": 999}, "readonly": False, "stream_id": "super/attempt-1"},
        events_since=lambda cursor: {"events": events, "cursor": 2})
    view = SubAgentView(parent, child["agent_id"])
    first = view.snapshot()
    assert len(view.events_since()["events"]) == 1
    child.update(attempt=2, statistics={"Tool Calls": 0})
    second = view.snapshot()
    assert first["stream_id"] != second["stream_id"]
    assert second["statistics"]["Tool Calls"] == 0
    assert view.events_since()["events"] == [events[1]]


@pytest.mark.asyncio
async def test_global_shows_preparation_without_changing_execution_layout(global_session):
    """Display DUT/workflow/progress before a Super process exists."""
    frontend, runtime, _ = global_session
    agent_id = start(runtime)
    runtime.runs[agent_id].update(status="preparing", preparation_progress="Exporting simulator interface")
    runtime.events.append(agent_id, "preparation", text="Exporting simulator interface")
    app = GlobalApp(frontend)
    async with app.run_test(size=(120, 38)) as pilot:
        await pilot.pause(.25)
        node = app.query_one("#agent-tree", Tree).root.children[0]
        assert "preparing" in node.label.plain and "dut / produce" in node.label.plain
        assert node.children[0].label.plain == "Exporting simulator interface"
        assert "Exporting simulator interface" in panel_text(app.query_one("#global-conversation", MessagesPanel))
