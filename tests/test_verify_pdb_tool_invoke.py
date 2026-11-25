"""Controller tool invocation validates structured JSON arguments before calls."""

from types import SimpleNamespace

import pytest

from ucagent.core.stage.vmanager import ToolSetCurrentStageJournal
from ucagent.runtime.control.controller import ControlError, Controller


@pytest.fixture
def controller():
    calls = []
    tool = ToolSetCurrentStageJournal().set_function(
        lambda journal, mode: calls.append((journal, mode))
    )
    result = Controller.__new__(Controller)
    result.agent = SimpleNamespace(get_tool_by_name=lambda name: tool if name == tool.name else None)
    result.calls = calls
    return result


def test_tool_invoke_preserves_punctuation_and_whitespace(controller):
    controller.tool_invoke("SetCurrentStageJournal", {"journal": "A,  B; x=y", "mode": "append"})
    assert controller.calls == [("A,  B; x=y", "append")]


def test_tool_invoke_applies_schema_defaults(controller):
    controller.tool_invoke("SetCurrentStageJournal", {"journal": "  keep spacing  "})
    assert controller.calls == [("  keep spacing  ", "replace")]


def test_tool_invoke_rejects_invalid_or_unknown_arguments_before_call(controller):
    with pytest.raises(ControlError, match="required"):
        controller.tool_invoke("SetCurrentStageJournal", {})
    with pytest.raises(ControlError, match="JSON object"):
        controller.tool_invoke("SetCurrentStageJournal", [])
    assert controller.calls == []
