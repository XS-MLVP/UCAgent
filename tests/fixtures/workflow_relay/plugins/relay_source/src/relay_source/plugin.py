"""Declare the independent relay source workflow and its exact file contracts."""

from pathlib import Path
from ucagent.core.plugins import Plugin, PluginWorkflow
from .checker import RelaySourceChecker


def get_plugin():
    """Expose one small workflow without activating any other plugin."""
    root = Path(__file__).resolve().parent
    return Plugin(name="relay-source", version="1.0.0", description='Produce a validated payload preserving the requested integer and operation.', root=root,
        checkers=(RelaySourceChecker,), workflows=(PluginWorkflow(
            name="produce", config_file=root / "workflows/produce.yaml",
            guide_doc_paths=(root / "Guide_Doc",), purpose='Produce a validated payload preserving the requested integer and operation.',
            inputs={"inputs/request.json": "Integer value and operation=increment"},
            outputs={"result_a/payload.json": "Validated payload"}),))
