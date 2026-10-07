"""Verify directly rendered public report pages."""
from ...core.reporting import verify_pages


def check(workflow, ctx):
    """Verify report pages, manifest, source links and waveform previews."""
    verify_pages(workflow.out, ctx["index"], ctx["cases"], ctx["bugs"], ctx["roots"])
