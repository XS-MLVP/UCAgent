"""Verify literal console arguments, public parameter binding and validation before tool calls."""

from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field
import pytest

import ucagent.verify_pdb as module
from ucagent.stage.vmanager import ToolDoCheck, ToolSetCurrentStageJournal
from ucagent.verify_pdb import VerifyPDB


@pytest.fixture
def console(monkeypatch):
    """Exercise the command entry without initializing PDB or modifying command history."""
    pdb = VerifyPDB.__new__(VerifyPDB)
    pdb.agent = SimpleNamespace(test_tools=[])
    output = []
    monkeypatch.setattr(module, "echo", output.append)
    monkeypatch.setattr(module, "echo_r", output.append)
    monkeypatch.setattr(module, "echo_y", output.append)
    return SimpleNamespace(pdb=pdb, output=output)


@pytest.mark.parametrize("arguments,expected", [
    ("journal='A,  B; x=y'", "A,  B; x=y"),
    ("'A=B;  C, D',mode='append'", "A=B;  C, D"),
    (r'''journal="A\tB, \"quoted\";  C"''', 'A\tB, "quoted";  C'),
])
def test_tool_invoke_preserves_string_data(console, arguments, expected):
    """Pass quoted punctuation, escapes and consecutive whitespace to a real public tool."""
    calls = []
    tool = ToolSetCurrentStageJournal().set_function(lambda journal, mode: calls.append((journal, mode)))
    console.pdb.agent.test_tools = [tool]

    console.pdb.do_tool_invoke(f"SetCurrentStageJournal {arguments}")

    assert calls == [(expected, "append" if "mode=" in arguments else "replace")]


def test_tool_invoke_validates_nested_literals_with_real_schema(console):
    """Retain nested values and named arguments through the Check tool's actual schema."""
    calls = []
    console.pdb.agent.test_tools = [ToolDoCheck().set_function(
        lambda timeout, stage_args: calls.append((timeout, stage_args)))]

    console.pdb.do_tool_invoke(
        'Check stage_args={"nested": {"ids": [1, 2], "enabled": True}, '
        '"note": "x=y;  z", "empty": None},timeout=15')

    assert calls == [(15, {"nested": {"ids": [1, 2], "enabled": True},
                          "note": "x=y;  z", "empty": None})]


def test_tool_invoke_without_arguments_uses_schema_defaults(console):
    """Keep zero-argument calls available for tools whose public fields have defaults."""
    calls = []
    console.pdb.agent.test_tools = [ToolDoCheck().set_function(
        lambda timeout, stage_args: calls.append(stage_args))]

    console.pdb.do_tool_invoke("Check")

    assert calls == [{}]


@pytest.mark.parametrize("arguments", [
    "journal=unknown_name",
    "journal=str(1)",
    "journal=f'{1}'",
    "journal=1+2",
    "journal=[set()]",
    "*['summary']",
    "**{'journal': 'summary'}",
    "journal='first',journal='second'",
    "journal='summary','append'",
    "journal='unclosed",
    "journal={'items': [1, 2}",
    "'summary') # discard wrapper",
])
def test_tool_invoke_rejects_invalid_input_before_invocation(console, arguments):
    """Reject syntax errors, expressions, unpacking and duplicate keywords without tool work."""
    calls = []
    console.pdb.agent.test_tools = [ToolSetCurrentStageJournal().set_function(
        lambda journal, mode: calls.append(journal))]

    console.pdb.do_tool_invoke(f"SetCurrentStageJournal {arguments}")

    assert calls == []
    assert console.output and console.output[-1].startswith("Error parsing arguments:")


@pytest.mark.parametrize("arguments,diagnostic", [
    ("'summary','append','extra'", "at most 2 positional arguments"),
    ("'first',journal='second'", "Duplicate argument 'journal'"),
    ("journal='summary',run_manager=None", "Unknown arguments: run_manager"),
    ("journal='summary',typo=True", "tool_list SetCurrentStageJournal"),
    ("mode='append'", "journal"),
    ("journal=['not a string']", "valid string"),
])
def test_tool_invoke_rejects_binding_and_schema_errors(console, arguments, diagnostic):
    """Reject excess, duplicate, private, unknown, missing and mistyped public arguments."""
    calls = []
    console.pdb.agent.test_tools = [ToolSetCurrentStageJournal().set_function(
        lambda journal, mode: calls.append(journal))]

    console.pdb.do_tool_invoke(f"SetCurrentStageJournal {arguments}")

    assert calls == []
    assert diagnostic in console.output[-1]


def test_tool_invoke_respects_schema_allowing_extra_fields(console):
    """Preserve an explicit extra-field contract instead of globally forbidding tool inputs."""
    class PublicArguments(BaseModel):
        """Declare a tool that accepts additional named input."""
        model_config = ConfigDict(extra="allow")
        text: str

    def run(text):
        """Expose one explicit positional field for the synthetic tool."""
        return text

    calls = []
    console.pdb.agent.test_tools = [SimpleNamespace(
        name="Capture", _run=run, tool_call_schema=PublicArguments,
        invoke=lambda values: calls.append(values))]

    console.pdb.do_tool_invoke("Capture 'summary',extra={'items': [1, 2]}")

    assert calls == [{"text": "summary", "extra": {"items": [1, 2]}}]


def test_tool_invoke_does_not_execute_argument_expressions(console, tmp_path):
    """Prove argument parsing cannot execute a supplied file-writing expression."""
    calls = []
    target = tmp_path / "must-not-exist"
    console.pdb.agent.test_tools = [ToolSetCurrentStageJournal().set_function(
        lambda journal, mode: calls.append(journal))]

    console.pdb.do_tool_invoke(
        f"SetCurrentStageJournal journal=__import__('pathlib').Path({str(target)!r}).write_text('bad')")

    assert not target.exists() and calls == []
    assert "Python literal" in console.output[-1]


@pytest.mark.parametrize("arguments,accepted", [
    ("message='A,  B; C'", True),
    ("'A,  B; C'", True),
    ("'first',message='second'", False),
])
def test_tool_invoke_accepts_public_schema_alias(console, arguments, accepted):
    """Recognize the argument name published by the schema before validating its value."""
    class PublicArguments(BaseModel):
        """Expose a public alias while retaining the method's internal field name."""
        text: str = Field(alias="message")

    def run(text):
        """Expose the field used by the synthetic tool method."""
        return text

    calls = []
    console.pdb.agent.test_tools = [SimpleNamespace(
        name="Capture", _run=run, tool_call_schema=PublicArguments,
        invoke=lambda values: calls.append(values))]

    console.pdb.do_tool_invoke(f"Capture {arguments}")

    assert calls == ([{"text": "A,  B; C"}] if accepted else [])
    if not accepted:
        assert "Duplicate argument 'text'" in console.output[-1]
