"""Common workspace binding and bounded errors for review tools."""

from typing import Any
import subprocess
from pydantic import Field
from ucagent.tools.uctool import UCTool

from ..core.layout import Layout
from ..core.records import Options, Record
from ..core.validation import ReviewIssues


class EmptyArgs(Record):
    """Use the current run without caller-selected paths."""


class ReviewTool(UCTool):
    """Bind plugin actions to OUT and return concise actionable diagnostics."""

    workspace: str = Field(exclude=True)
    output_dir: str = Field(exclude=True)
    module: str = Field(default='', exclude=True)
    options: Options = Field(default_factory=Options, exclude=True)
    waveinfo: Any = Field(default=None, exclude=True)

    @property
    def layout(self):
        """Resolve paths lazily; construction does not inspect runtime artifacts."""
        return Layout(self.workspace, self.output_dir)

    def _run(self, **kwargs):
        """Validate arguments on both direct and MCP invocation paths."""
        try:
            args = self.args_schema.model_validate(kwargs)
            return {'success': True, **self.perform(**args.model_dump())}
        except ReviewIssues as error:
            return {'success': False, **error.result()}
        except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            return {'success': False, 'error_code': 'REVIEW_ACTION_FAILED', 'error': str(error)[:1600],
                    'next_action': 'Correct the named input; use ReviewContext and Guide_Doc/analysis.md'}

    def perform(self, **kwargs):
        """Implement the schema-validated action in a concrete tool."""
        raise NotImplementedError
