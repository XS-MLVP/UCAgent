from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import Vertical, Container
from textual.widgets import Header, Placeholder, Footer

from ucagent.tui.body_panel import BodyPanel
from ucagent.tui.sidebar import Sidebar


class VerifyUI(App[None]):
    """ Verify UI """

    CSS_PATH = "style.css"

    BINDINGS = []

    def compose(self)-> ComposeResult:
        yield Header()
        with Container():
            yield Sidebar(id="sidebar")
            yield BodyPanel(id="body")
        yield Footer()

if __name__ == '__main__':
    app = VerifyUI()
    app.run()
