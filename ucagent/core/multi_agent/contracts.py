"""Validated multi-agent configuration and task contracts, independent of transport."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject ambiguous fields instead of silently weakening a task contract."""

    model_config = ConfigDict(extra="forbid")


class Limits(StrictModel):
    """Finite per-attempt and logical-task budgets enforced by the service."""

    supervisor_backend_turns: int = Field(default=8, gt=0, strict=True)
    worker_backend_turns: int = Field(default=80, gt=0, strict=True)
    supervisor_model_rounds: int = Field(default=8, gt=0, le=100, strict=True)
    supervisor_tool_calls: int = Field(default=40, gt=0, le=1000, strict=True)
    supervisor_timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    worker_model_rounds: int = Field(default=80, gt=0, strict=True)
    worker_tool_calls: int = Field(default=200, gt=0, strict=True)
    worker_timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    task_max_attempts: int = Field(default=2, gt=0, le=10, strict=True)
    planning_revisions: int = Field(default=3, gt=0, le=20, strict=True)


class Role(StrictModel):
    """A trusted role supplies a prompt, backend and business-tool allowlist."""

    description: str = ""
    backend: str | None = None
    system: str = ""
    system_file: str | None = None
    model_overrides: dict = Field(default_factory=dict, repr=False)
    allowed_tools: list[str] = Field(default_factory=lambda: [
        "ReadTextFile", "PathList", "SearchText", "FindFiles", "GetFileInfo",
        "EditTextFile", "ReplaceStringInFile", "DeleteTextLines", "CreateDirectory",
    ])
    command: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_prompt_and_backend(self):
        """Require one prompt source and an explicit command for external workers."""
        if bool(self.system.strip()) == bool(self.system_file):
            raise ValueError("A role requires exactly one of system or system_file")
        if self.backend == "command" and not self.command:
            raise ValueError("A command role requires a nonempty argv command")
        if self.backend != "command" and self.command:
            raise ValueError("command is only valid for backend=command")
        if set(self.model_overrides) - {"model_type", "openai", "anthropic", "rate_limiter", "conversation_summary"}:
            raise ValueError("model_overrides may only change model provider and context settings")
        if self.model_overrides and self.backend not in (None, "langchain"):
            raise ValueError("model_overrides is only valid for backend=langchain")
        return self


class ArtifactRule(StrictModel):
    """Workflow-authored validation for one exact task output."""

    path: str
    min_bytes: int = Field(default=1, ge=0, strict=True)
    contains: list[str] = Field(default_factory=list)
    json_keys: list[str] | None = None


class TaskContract(StrictModel):
    """Trusted split-task rules prevent a planner inventing its own acceptance gate."""

    rules: list[ArtifactRule] = Field(min_length=1)
    allowed_roles: list[str] = Field(default_factory=list)


class Settings(StrictModel):
    """Run-level concurrency and role settings; loaded only in multi mode."""

    max_workers: int = Field(default=1, gt=0, le=128, strict=True)
    default_role: str = "worker"
    delegation_scope: Literal["auto", "stage", "subtree"] = "auto"
    limits: Limits = Field(default_factory=Limits)
    roles: dict[str, Role]
    stage_roles: dict[str, str] = Field(default_factory=dict)
    task_contracts: dict[str, TaskContract] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_default(self):
        """Reject a fallback role that cannot be constructed."""
        if self.default_role not in self.roles:
            raise ValueError("multi_agent.default_role must name a configured role")
        if set(self.stage_roles.values()) - self.roles.keys():
            raise ValueError("stage_roles contains an unknown role")
        return self


class TaskSpec(StrictModel):
    """Planner-provided file ownership and dependencies; stage gates remain authoritative."""

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    instruction: str = Field(min_length=1, max_length=32000)
    role: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list, description=
        "Exact read-only input files; no globs or directories. Input producers must be explicit dependencies.")
    outputs: list[str] = Field(default_factory=list, description=
        "Exact output files; no globs or directories. Required for task scope; "
        "stage/auto may omit this list and rely on the stage Checker for dynamic outputs.")
    contract: str | None = None
    resources: list[str] = Field(default_factory=list)


class TaskPlan(StrictModel):
    """One stage or subtree plan, with optional independently validated split tasks."""

    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    planning_token: str | None = Field(default=None, description="CurrentTips planning_token for a managed MCP planning turn; omit for external manual plans.")
    scope: Literal["auto", "stage", "subtree", "task"] = Field(default="auto", description=
        "Use auto for an entire stage group in one worker session. stage limits work to the current step. "
        "task provides file-only workers without Check, stage journals or Skill tools.")
    scope_reason: str | None = Field(default=None, min_length=1, max_length=2000, description=
        "Required when narrowing the default subtree to stage/task: explain the single-step boundary "
        "or independent file split, and how required stage/Skill gates will be fulfilled.")
    tasks: list[TaskSpec] = Field(min_length=1, max_length=128)


def role_backend_config(cfg, role):
    """Resolve inherited model settings and the bounded legacy argv configuration once."""
    from ucagent.util.config import Config
    resolved = Config(cfg.as_dict())
    resolved.merge_from(Config(role.model_overrides))
    resolved.set_value("backend.key_name", role.backend)
    if role.command:
        resolved.set_value("backend.command", {"clss": "ucagent.core.backends.cmdline.SessionCommandBackend",
                                               "args": {"argv": role.command}})
    return resolved


def load_settings(cfg, workspace):
    """Validate the mode first; disabled mode never loads or reads role resources."""
    enabled = cfg.get_value("runtime_options.multi_agent_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("runtime_options.multi_agent_enabled must be boolean")
    if not enabled:
        if cfg.get_value("multi_agent_cli_limit", False):
            raise ValueError("--max-subagents requires runtime_options.multi_agent_enabled=true")
        return None
    raw = cfg.get_value("multi_agent", {})
    settings = Settings.model_validate(raw.as_dict() if hasattr(raw, "as_dict") else raw)
    root = Path(workspace).resolve()
    selected = cfg.get_value("backend.key_name", "langchain")
    for name, role in settings.roles.items():
        if selected == "blank":
            if role.backend is None:
                raise ValueError(f"Role {name}: blank has no worker backend; set an explicit registered backend")
        elif role.backend is not None and role.backend != selected:
            raise ValueError(f"Role {name}: backend {role.backend} conflicts with {selected}; remove the role backend override")
        role.backend = role.backend or selected
        if role.backend == "blank":
            raise ValueError(f"Role {name}: blank cannot execute a worker")
        if role.model_overrides and role.backend != "langchain":
            raise ValueError(f"Role {name}: model_overrides require the langchain backend")
        from ucagent.core.backends import get_backend_class
        resolved = role_backend_config(cfg, role)
        backend_class = get_backend_class(resolved)
        if not backend_class.capabilities.managed_sessions:
            raise ValueError(f"Backend {role.backend!r} does not implement managed Agent sessions")
        if not backend_class.capabilities.model_rounds and any(
            cfg.get_value(f"vmanager.llm_suggestion.{gate}.enable", False)
            for gate in ("check_fail_refinement", "check_pass_refinement")
        ):
            raise ValueError("Selected backend does not support the configured model-based stage reviewer; "
                             "configure a compatible reviewer before enabling managed CLI sessions")
        if role.system_file:
            source = Path(role.system_file)
            source = source if source.is_absolute() else root / source
            role.system = source.read_text(encoding="utf-8")
            if not role.system.strip():
                raise ValueError("Role system_file must not be empty")
    return settings
