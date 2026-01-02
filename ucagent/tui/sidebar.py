from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Placeholder, Static


class Sidebar(Vertical):
    """SideBar to display `Status` and `Mission` panel"""

    def compose(self) -> ComposeResult:
        # Mocks 
        # yield Placeholder("Stages", classes="mission")
        # yield Placeholder("Status", classes="status")
        
        pass
