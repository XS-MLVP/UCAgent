"""Accepted workflow results, independent of transport and orchestration."""
from typing import Literal
from pydantic import Field, field_validator, model_validator
from ucagent.core.workflow.contracts import canonical_file
from ucagent.core.multi_agent.global_agent.session_contracts import StrictContract

class ArtifactReceipt(StrictContract):
    """One runtime-produced artifact digest used by the parent verifier."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str):
        canonical_file(value)
        return value


class StageReceipt(StrictContract):
    """Compact evidence that a workflow stage reached completion."""

    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    completed: bool


class WorkflowRunResult(StrictContract):
    """Runtime-authored result of one Super workflow run."""

    agent_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    workflow_ref: str = Field(pattern=r"^[^:]+:[^:]+$")
    attempt: int = Field(ge=1)
    status: Literal["succeeded", "failed", "cancelled"]
    stages: list[StageReceipt] = Field(default_factory=list)
    artifacts: list[ArtifactReceipt] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def unique_artifacts(self):
        """Require one digest per relative artifact path."""
        paths = [item.path for item in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("Run result artifacts must have unique paths")
        return self


