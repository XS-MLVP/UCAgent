"""Declare the independent relay sink workflow and its exact file contracts."""

from pathlib import Path
from ucagent.core.plugins import Plugin, PluginWorkflow
from .checker import RelaySinkChecker


def get_plugin():
    """Expose one small workflow without activating any other plugin."""
    root = Path(__file__).resolve().parent
    return Plugin(name="relay-sink", version="1.0.0", description='Increment a validated integer payload and return the input digest.', root=root,
        checkers=(RelaySinkChecker,), workflows=(PluginWorkflow(
            name="consume", config_file=root / "workflows/consume.yaml",
            guide_doc_paths=(root / "Guide_Doc",), purpose='Increment a validated integer payload and return the input digest.',
            inputs={"inputs/payload.json": "Integer value and operation=increment"},
            outputs={"result_b/result.json": "Validated result"}),))
