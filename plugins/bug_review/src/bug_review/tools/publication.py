"""Publish validated current review records."""

from typing import Type
from pydantic import BaseModel, Field
from .base import ReviewTool
from ..core.records import Record
from ..core.validation import validate
from ..core.reporting import render_report


class RenderArgs(Record):
    """Choose deterministic rendering or read-only report verification."""

    verify_only: bool = Field(default=False, description='Validate existing report pages without rewriting them.')


class RenderBugReviewReport(ReviewTool):
    """Render only after final claim decisions pass the same completion gate."""

    name: str = 'RenderBugReviewReport'
    description: str = 'Validate decisions and render or verify report/index.html and portable source/waveform assets. No waveform required when disabled.'
    args_schema: Type[BaseModel] = RenderArgs
    call_time_out: int = 120
    is_alive_loop: bool = True

    def perform(self, verify_only):
        """Never publish a merely declared or partially investigated result."""
        validate(self.layout, 'decisions', self.waveinfo)
        return render_report(self.layout, verify_only)
