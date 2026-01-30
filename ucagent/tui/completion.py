"""Tab completion handler for UCAgent TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .handlers import KeyHandler


class CompletionSource(Protocol):
    """Protocol for completion data sources."""

    def complete_command(self, text: str) -> list[str]:
        """Return completion suggestions for the given text."""
        ...


class CompletionState:
    """Manages tab completion state."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.index: int = -1
        self.base: str = ""

    def reset(self) -> None:
        """Reset completion state."""
        self.items = []
        self.index = -1
        self.base = ""

    @property
    def has_items(self) -> bool:
        """Return True if there are completion items."""
        return bool(self.items)

    def cycle_next(self) -> str | None:
        """Cycle to next completion item and return it."""
        if not self.items:
            return None
        self.index = (self.index + 1) % len(self.items)
        return self.items[self.index]

    def current_item(self) -> str | None:
        """Return currently selected item."""
        if not self.items or self.index < 0:
            return None
        return self.items[self.index]


class CompletionHandler:
    """Handles tab completion logic for console input."""

    def __init__(self) -> None:
        self.state = CompletionState()

    def reset(self) -> None:
        """Reset completion state."""
        self.state.reset()

    def handle_tab(
            self,
            current_text: str,
            source: "KeyHandler",
            is_cycling: bool = False,
    ) -> tuple[str | None, list[str], int]:
        """Handle tab key press for completion.

        Args:
            current_text: Current input text.
            source: Completion source (KeyHandler).
            is_cycling: True if already showing suggestions.

        Returns:
            Tuple of (new_text, suggestions, selected_index).
            new_text is None if no change needed.
        """
        if is_cycling and self.state.has_items:
            selected = self.state.cycle_next()
            if selected:
                new_text = self.state.base + selected
                return new_text, self.state.items, self.state.index
            return None, [], -1

        completions = source.complete_command(current_text)

        if not completions:
            self.reset()
            return None, [], -1

        base = self._extract_base(current_text)

        if len(completions) == 1:
            self.reset()
            return base + completions[0], [], -1

        self.state.items = completions
        self.state.index = 0
        self.state.base = base
        return base + completions[0], completions, 0

    @staticmethod
    def _extract_base(text: str) -> str:
        """Extract the base prefix before the completion word."""
        if " " in text:
            return text[: text.rfind(" ") + 1]
        return ""
