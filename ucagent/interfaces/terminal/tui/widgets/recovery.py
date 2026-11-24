"""Compact interruption presentation and explicit operator recovery forms."""

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input


REASONS = {
    "repairable": "Repairable failure", "capability": "Capability unavailable", "environment": "Missing prerequisite",
    "input": "Decision needed", "review": "Review required", "budget": "Budget exhausted",
    "operator": "Paused by operator", "execution": "Repeated execution failure",
}
BUDGET_LABELS = {
    "planning_revisions": "Additional planning revisions", "supervisor_backend_turns": "Super backend turns",
    "supervisor_model_rounds": "Super model calls", "supervisor_tool_calls": "Super tool calls",
    "supervisor_timeout_seconds": "Super seconds per turn", "worker_backend_turns": "Sub backend turns",
    "worker_model_rounds": "Sub model calls", "worker_tool_calls": "Sub tool calls",
    "worker_timeout_seconds": "Sub execution seconds", "task_max_attempts": "Sub attempts",
}


def reason_label(issue):
    """Name the policy category without guessing from a provider error."""
    return REASONS.get((issue or {}).get("kind"), "Needs attention")



class RecoveryPanel(Vertical):
    """One stable status strip expands only when an agent needs attention."""

    DEFAULT_CSS = """
    RecoveryPanel { height: auto; padding: 0 1; border-bottom: solid $primary; }
    RecoveryPanel.attention { border: round $warning; margin: 0 1; }
    RecoveryPanel Static { height: auto; }
    RecoveryPanel #recovery-summary { max-height: 4; }
    RecoveryPanel #recovery-actions { height: auto; grid-size: 2; grid-columns: 1fr 1fr; grid-rows: 3; }
    RecoveryPanel Button { min-width: 10; width: auto; margin: 0 1 0 0; }
    """

    def compose(self):
        """Keep the compact status strip and applicable controls in one place."""
        yield Static(id="recovery-title", markup=False)
        yield Static(id="recovery-summary", markup=False)
        with Horizontal(id="recovery-actions"):
            yield Button("Resume", id="recovery-resume", variant="primary")
            yield Button("Reply", id="recovery-reply", variant="primary")
            yield Button("Add budget", id="recovery-grant", variant="warning")
            yield Button("Review", id="recovery-review", variant="primary")
            yield Button("Details", id="recovery-details")
            yield Button("Open Super", id="recovery-parent")

    def update_snapshot(self, snapshot):
        """Render authoritative state while keeping Sub controls with its parent."""
        sub = snapshot.get("role") == "sub"
        recovery = snapshot.get("recovery") or {}
        issue = recovery.get("issue") or snapshot.get("issue")
        parent_issue = (snapshot.get("parent_recovery") or {}).get("issue")
        if sub and not issue and snapshot.get("status") == "needs_attention":
            issue = parent_issue
        state = snapshot.get("status", "unknown")
        self.set_class(bool(issue), "attention")
        if issue:
            title = "⏸ " + reason_label(issue)
            if sub:
                title += " · Attempt ended; Super owns recovery"
            elif snapshot.get("readonly"):
                title += " · Process ended; retry from Global"
            summary = issue.get("summary", "")[:240] + "\nNext: " + issue.get("next_action", "")[:180]
        else:
            title = {"running": "● Running", "verified": "✓ Task verified", "succeeded": "✓ Completed",
                     "completed": "✓ Completed", "waiting_dependency": "◷ Waiting for dependency", "queued": "◷ Queued",
                     "failed": "✕ Terminated", "cancelled": "Cancelled"}.get(state, state)
            summary = ""
        planning = recovery.get("planning", {})
        if planning and not sub:
            title += f" · Planning {planning['used']}/{planning['limit']}"
        color = "yellow" if issue else "cyan" if state == "running" else "green" if state in {"verified", "completed", "succeeded"} else "red" if state == "failed" else ""
        self.query_one("#recovery-title", Static).update(Text(title, style=color))
        self.query_one("#recovery-summary", Static).update(Text(summary))
        actions = recovery.get("actions", []) if not sub and not snapshot.get("readonly") else []
        for action in ("resume", "reply", "grant", "review"):
            self.query_one("#recovery-" + action, Button).display = action in actions
        self.query_one("#recovery-details", Button).display = bool(issue)
        self.query_one("#recovery-parent", Button).display = sub
        self.query_one("#recovery-actions").display = bool(issue or sub)

    def on_resize(self, event):
        """Wrap actions on narrow terminals without hiding the message panel."""
        if self.is_mounted:
            self.query_one("#recovery-actions").styles.layout = "grid" if event.size.width < 54 else "horizontal"


class RecoveryDialog(ModalScreen):
    """Show the exact reason and additions before sending one recovery request."""

    DEFAULT_CSS = """
    RecoveryDialog { align: center middle; background: $background 70%; }
    #recovery-dialog { width: 76; max-width: 95%; height: auto; max-height: 90%; padding: 1 2; border: round $primary; background: $surface; }
    #recovery-form { height: auto; max-height: 24; }
    #recovery-dialog.budget { height: 85%; max-height: 38; }
    #recovery-dialog.budget #recovery-form { height: 1fr; max-height: 100%; }
    #recovery-form Static { height: auto; }
    #recovery-form Input { margin-bottom: 1; }
    #recovery-dialog-actions { height: 3; min-height: 3; }
    #recovery-dialog-actions Button { margin-right: 1; }
    #recovery-error { color: $error; height: auto; }
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def action_close(self):
        """Dismiss without changing task state or adding budget."""
        self.dismiss(None)

    def __init__(self, recovery, action):
        """Bind the form to the exact interruption shown when it was opened."""
        super().__init__()
        self.recovery, self.action = recovery, action
        self.issue = recovery["issue"]

    def compose(self):
        """Show evidence and editable increments with fixed, reachable action buttons."""
        with Vertical(id="recovery-dialog", classes="budget" if self.action == "grant" else ""):
            with VerticalScroll(id="recovery-form"):
                issue = self.issue
                source = "Runtime observation" if issue.get("source") == "runtime" else "Agent report; checks below are runtime observations"
                lines = [reason_label(issue), issue.get("summary", ""), "", "Next: " + issue.get("next_action", ""), "", source]
                for check in issue.get("checks", []):
                    state = "Met" if check["satisfied"] is True else "Unmet" if check["satisfied"] is False else "Unverified"
                    lines.append(f"  {check['kind']} · {check['value']} · {state}")
                for item in issue.get("evidence", []):
                    lines.append(f"  {item['tool']} · {item['outcome']} · evidence {item['id'][:8]}")
                budget = issue.get("budget")
                if budget:
                    lines.append(f"Used: {BUDGET_LABELS.get(budget['dimension'], budget['dimension'])} {budget['used']}/{budget['limit']}")
                yield Static("\n".join(lines), markup=False)
                if self.action == "grant":
                    yield Static("Additional budget (usage is retained; 0 means no addition)")
                    for name, label in BUDGET_LABELS.items():
                        if name.startswith("worker_") or name == "task_max_attempts":
                            if not self.issue.get("task_id"):
                                continue
                        yield Static(label)
                        yield Input(str(self.recovery.get("suggested_grant", {}).get(name, 0)), type="number", id="grant-" + name)
                if self.action in {"reply", "resume", "grant", "review"}:
                    yield Static("Reply or guidance" if self.action != "review" else "Review notes (approve and resume)")
                    yield Input(placeholder="Describe the resolution or new guidance", id="recovery-message")
            yield Static(id="recovery-error", markup=False)
            with Horizontal(id="recovery-dialog-actions"):
                if self.action != "details":
                    yield Button("Approve and resume" if self.action == "review" else "Apply and resume", id="recovery-confirm", variant="primary")
                yield Button("Close", id="recovery-close")

    @on(Button.Pressed)
    def button_pressed(self, event):
        """Submit only explicit valid input; closing never changes execution state."""
        event.stop()
        if event.button.id == "recovery-close":
            self.dismiss(None)
            return
        message = self.query_one("#recovery-message", Input).value.strip()
        if self.action == "reply" and not message:
            self.query_one("#recovery-error", Static).update("Reply to the pending question first.")
            return
        grant = {}
        if self.action == "grant":
            try:
                grant = {field.id.removeprefix("grant-"): int(field.value) for field in self.query(Input) if field.id.startswith("grant-") and int(field.value)}
                if not grant or any(value < 0 for value in grant.values()):
                    raise ValueError()
            except ValueError:
                self.query_one("#recovery-error", Static).update("Use nonnegative integers and add at least one budget.")
                return
        self.dismiss({"issue_id": self.issue["id"], "action": self.action, "message": message, "grant": grant})
