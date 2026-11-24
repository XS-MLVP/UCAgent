"""Strict contracts for long-lived Global sessions and on-demand Supers."""
from __future__ import annotations

from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ucagent.core.workflow.contracts import canonical_file

ID_PATTERN = r"^[A-Za-z0-9_-]{1,80}$"
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
PROTECTED_OVERRIDES = frozenset({
    "workflow", "runtime_options", "runtime_options.agent_mode", "agent_run", "agent_run.role",
    "runtime_options.workflow_handoff_enabled", "agent_run.id", "agent_run.attempt",
    "agent_run.result_path", "agent_run.session_dir",
})

class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class AgentArtifactRef(StrictContract):
    agent_id: str = Field(pattern=ID_PATTERN)
    attempt: int = Field(ge=1)
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def check_path(cls, value):
        canonical_file(value)
        return value

class SuperRequest(StrictContract):
    workflow_ref: str = Field(pattern=r"^[^:]+:[^:]+$")
    instruction: str = Field(min_length=1, max_length=32000)
    launch_profile: str = Field(default="standard", min_length=1)
    source_workspace: str | None = Field(default=None, description="Exact DUT source from ListDUTs, or a project-relative directory.")
    dut_name: str | None = Field(default=None, min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_$-]*$", description="Concrete DUT module name; required when the source contains multiple DUTs.")
    preparation: dict[str, Any] = Field(default_factory=dict, description="Workflow preparation options from ListWorkflows; omit to use defaults.")
    inputs: dict[str, AgentArtifactRef] = Field(default_factory=dict)

    @field_validator("inputs")
    @classmethod
    def check_inputs(cls, value):
        for path in value:
            canonical_file(path, inputs_only=True)
        return value

class SuperSpec(SuperRequest):
    plugin_selector: str = Field(min_length=1)
    agent_id: str = Field(pattern=ID_PATTERN)

class SuperProfile(StrictContract):
    backend: str = Field(default="langchain", min_length=1)
    max_subagents: int = Field(default=2, ge=1, le=128)
    max_attempts: int = Field(default=2, ge=1, le=10)
    preparation_timeout: int = Field(default=900, ge=1, le=86400)
    config_ref: str | None = None
    no_embed_tools: bool = False
    resources: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def validate_profile(self):
        if not self.backend.strip() or self.backend == "blank":
            raise ValueError("A Super requires a model backend")
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("Profile resources must be unique")
        if PROTECTED_OVERRIDES & self.overrides.keys():
            raise ValueError("Profile overrides protected Agent session settings")
        return self

    def describe(self):
        return {"backend": self.backend, "max_subagents": self.max_subagents,
                "max_attempts": self.max_attempts, "preparation_timeout": self.preparation_timeout, "resources": list(self.resources)}

class GlobalSettings(StrictContract):
    plugin_selectors: list[str] = Field(default_factory=list)
    allowed_workflows: list[str] = Field(default_factory=list)
    target_configs: dict[str, str] = Field(default_factory=dict)
    launch_profiles: dict[str, SuperProfile] = Field(min_length=1)
    resources: dict[str, int] = Field(default_factory=dict)
    workspace_roots: list[str] = Field(default_factory=list)
    root: str | None = None
    project_root: str | None = None
    max_parallel_supers: int = Field(default=2, ge=1, le=32)
    max_runs_per_request: int = Field(default=12, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_policy(self):
        allowed = set(self.allowed_workflows)
        if len(allowed) != len(self.allowed_workflows) or any(x.count(":") != 1 for x in allowed):
            raise ValueError("allowed_workflows must contain unique plugin:workflow references")
        if allowed and set(self.target_configs) - allowed:
            raise ValueError("target_configs references an unknown workflow")
        if any(not k.strip() or type(v) is not int or v < 1 for k, v in self.resources.items()):
            raise ValueError("resources must have positive integer capacities")
        for name, profile in self.launch_profiles.items():
            if not name.strip() or set(profile.resources) - self.resources.keys():
                raise ValueError("Invalid profile name or unknown profile resource")
        return self

class AgentSnapshot(StrictContract):
    agent_id: str
    parent_id: str | None = None
    role: Literal["global", "super", "sub"]
    attempt: int = Field(default=1, ge=1)
    status: str
    workflow_ref: str | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_index: int = 0
    children: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

class AgentEvent(StrictContract):
    seq: int = Field(ge=1)
    agent_id: str
    parent_id: str | None = None
    attempt: int = Field(ge=1)
    kind: str
    timestamp: float
    payload: dict[str, Any] = Field(default_factory=dict)

class AgentView(Protocol):
    def snapshot(self) -> dict: ...
    def events_since(self, cursor: int = 0) -> dict: ...
    def submit_input(self, text: str, *, command: bool = False) -> dict: ...
    def cancel_operation(self) -> dict: ...

def load_global_settings(cfg):
    """Resolve Global policy only for the root of a multi session."""
    from ucagent.core.multi_agent.mode import agent_role
    if agent_role(cfg) != "global":
        return None
    if cfg.get_value("runtime_options.workflow_handoff_enabled", False):
        raise ValueError("Multi workflow chaining belongs to Global; disable workflow_handoff_enabled")
    import copy
    raw = cfg.get_value("global_agent", {})
    raw = copy.deepcopy(raw.as_dict() if hasattr(raw, "as_dict") else raw)
    for profile in raw.get("launch_profiles", {}).values():
        if profile.get("backend") is None:
            profile["backend"] = cfg.get_value("backend.key_name", "langchain")
    return GlobalSettings.model_validate(raw)
