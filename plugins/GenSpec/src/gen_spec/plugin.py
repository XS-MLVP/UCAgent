"""Expose the GenSpec workflow and its runtime document guide."""

from pathlib import Path

from ucagent.plugins import Plugin, PluginWorkflow

from . import __version__


def get_plugin() -> Plugin:
    """Return the workflow-only plugin using UCAgent's built-in checkers."""
    root = Path(__file__).resolve().parent
    return Plugin(
        name="gen-spec",
        version=__version__,
        description=(
            "Deprecated specification generation plugin; "
            "use SpecGenerator (xiangshan-spec-generator) instead."
        ),
        root=root,
        requires_ucagent=">=26.9.2.dev14",
        workflows=(
            PluginWorkflow(
                name="generate-spec",
                config_file=root / "workflows" / "generate-spec.yaml",
                guide_doc_paths=(root / "Guide_Doc",),
            ),
        ),
    )
