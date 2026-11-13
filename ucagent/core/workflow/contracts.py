"""Validate workflow selection and explicit file inputs without activating candidates."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
import copy
import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ucagent.core.plugins import load_plugins, validate_workflow_dependencies


class Contract(BaseModel):
    """Reject unknown fields and coercions at the trusted handoff boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DecisionLimits(Contract):
    """Bound cumulative decisions for one source run, including failed starts."""

    backend_turns: int = Field(default=4, gt=0, le=100)
    tool_calls: int = Field(default=20, gt=0, le=1000)
    timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)


class HandoffSettings(Contract):
    """Keep candidate policy under operator ownership for the whole execution chain."""

    plugin_selectors: list[str] = Field(default_factory=list)
    allowed_workflows: list[str] = Field(min_length=1)
    allowed_next: dict[str, list[str]]
    target_configs: dict[str, str] = Field(default_factory=dict)
    goal: str = Field(default="", max_length=32000)
    chain_root: str | None = Field(default=None, min_length=1)
    resume_chain: str | None = Field(default=None, min_length=1)
    max_runs: int = Field(default=4, gt=0, le=1000)
    max_start_attempts: int = Field(default=2, gt=0, le=20)
    ready_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    decision_limits: DecisionLimits = Field(default_factory=DecisionLimits)
    allow_revisit: bool = False

    @model_validator(mode="after")
    def valid_references(self):
        """Require explicit edges for every trusted workflow and reject unknown targets."""
        allowed = set(self.allowed_workflows)
        if len(allowed) != len(self.allowed_workflows) or set(self.allowed_next) != allowed:
            raise ValueError("allowed_next must describe every distinct allowed workflow")
        if set(self.target_configs) - allowed or any(set(v) - allowed for v in self.allowed_next.values()):
            raise ValueError("Workflow policy contains an unknown target")
        if any(not ref or ref.count(":") != 1 for ref in allowed):
            raise ValueError("Workflow references must be plugin:workflow")
        return self


class NextWorkflow(Contract):
    """A model selects declared inputs; it cannot provide executable configuration."""

    workflow_ref: str = Field(min_length=1, description="Exact reference returned by ListWorkflows.")
    reason: str = Field(min_length=1, max_length=4000, description="Why this workflow advances the original goal.")
    summary: str = Field(min_length=1, max_length=16000, description="Verified results, limitations and useful input context.")
    inputs: dict[str, str] = Field(description="Target declared input path to current workspace source file.")
    transition_token: str = Field(min_length=1, description="CurrentTips handoff.transition_token for this Super turn.")

    @field_validator("inputs")
    @classmethod
    def valid_paths(cls, values):
        """Reject traversals, reserved resources and noncanonical file mappings."""
        for target, source in values.items():
            canonical_file(target, inputs_only=True)
            canonical_file(source)
        return values


class EndChain(Contract):
    """Record an explicit terminal decision from the current handoff turn."""

    reason: str = Field(min_length=1, max_length=4000, description="Explain how the accepted artifacts satisfy the goal.")
    summary: str = Field(min_length=1, max_length=16000, description="Final deliverables and remaining limitations.")
    transition_token: str = Field(min_length=1, description="CurrentTips handoff.transition_token.")


def canonical_file(value, *, inputs_only=False):
    """Return a canonical relative file path, excluding credentials and framework resources."""
    path = PurePosixPath(value)
    if (not value or "\\" in value or path.is_absolute() or path.as_posix() != value
            or ".." in path.parts or not path.parts or any(p.startswith(".") for p in path.parts)
            or path.parts[0] == "Guide_Doc" or (inputs_only and (len(path.parts) < 2 or path.parts[0] != "inputs"))):
        raise ValueError("Use canonical relative data files; target files must be under inputs/")
    return path


def source_file(workspace, relative):
    """Resolve a regular source file without following symlinks outside its run."""
    canonical_file(relative)
    root = Path(workspace).resolve()
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
        raise ValueError("Symlink handoff inputs are not allowed")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"Handoff input is not an existing regular file: {relative}")
    return path


def load_handoff_settings(cfg):
    """Disabled mode is inert; enabled handoff requires a managed non-blank Super."""
    enabled = cfg.get_value("runtime_options.workflow_handoff_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("runtime_options.workflow_handoff_enabled must be boolean")
    if not enabled:
        return None
    if not cfg.get_value("runtime_options.multi_agent_enabled", False) or cfg.get_value("backend.key_name") == "blank":
        raise ValueError("Workflow handoff requires managed multi mode with a non-blank Super")
    raw = cfg.get_value("workflow_handoff", {})
    return HandoffSettings.model_validate(raw.as_dict() if hasattr(raw, "as_dict") else raw)


@dataclass(frozen=True)
class CatalogEntry:
    """Describe an available workflow without instantiating its tools or resources."""

    ref: str
    owner: object
    workflow: object
    unavailable: str | None = None

    def describe(self):
        """Expose only task metadata and dependency diagnostics to the Super."""
        return {"workflow_ref": self.ref, "purpose": self.workflow.purpose,
                "inputs": dict(self.workflow.inputs), "outputs": dict(self.workflow.outputs),
                "unavailable": self.unavailable}


class WorkflowCatalog:
    """Discover trusted plugins independently from each Agent's active plugin registry."""

    def __init__(self, settings, plugins=()):
        """Load declarations, validate all references, and retain a fresh target factory input."""
        loaded = {p.plugin.name: p for p in plugins}
        for item in load_plugins(settings.plugin_selectors):
            if item.plugin.name in loaded and loaded[item.plugin.name].plugin.root != item.plugin.root:
                raise ValueError("Conflicting plugin sources in workflow catalog")
            loaded[item.plugin.name] = item
        self.entries = {}
        for item in loaded.values():
            for workflow in item.plugin.workflows:
                ref = f"{item.plugin.name}:{workflow.name}"
                if ref not in settings.allowed_workflows:
                    continue
                for name in workflow.inputs:
                    canonical_file(name, inputs_only=True)
                for name in workflow.outputs:
                    canonical_file(name)
                unavailable = None
                try:
                    validate_workflow_dependencies(item.plugin.name, workflow)
                except ValueError as exc:
                    unavailable = str(exc)
                self.entries[ref] = CatalogEntry(ref, item, workflow, unavailable)
        missing = set(settings.allowed_workflows) - self.entries.keys()
        if missing:
            raise ValueError(f"Unknown allowed workflows: {sorted(missing)}; provide trusted plugin_selectors")
        self.settings = settings

    def select(self, source, request, visited):
        """Validate an edge, revisit policy and exact declared input names before queuing."""
        if request.workflow_ref not in self.settings.allowed_next.get(source, []):
            raise ValueError("Target workflow is not an allowed successor")
        if not self.settings.allow_revisit and request.workflow_ref in visited:
            raise ValueError("Workflow revisits are disabled")
        entry = self.entries[request.workflow_ref]
        if entry.unavailable:
            raise ValueError(entry.unavailable)
        if set(request.inputs) != set(entry.workflow.inputs):
            raise ValueError(f"Target requires exactly these inputs: {sorted(entry.workflow.inputs)}")
        return entry


def execution_overrides(cfg):
    """Copy only connection/execution settings; never inherit source workflow policy or stages."""
    keys = ("backend", "model_type", "openai", "anthropic", "rate_limiter", "conversation_summary", "langfuse", "lang")
    return {key: copy.deepcopy(value.as_dict() if hasattr(value, "as_dict") else value)
            for key in keys if (value := cfg.get_value(key, None)) is not None}


def workflow_fingerprint(entry, config_file=None):
    """Hash trusted source bytes without persisting configuration contents or credentials."""
    digest = hashlib.sha256(entry.workflow.config_file.read_bytes())
    digest.update(entry.ref.encode())
    digest.update(entry.owner.plugin.version.encode())
    for path in sorted(entry.owner.plugin.root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml", ".toml"} and not path.is_symlink():
            digest.update(str(path.relative_to(entry.owner.plugin.root)).encode())
            digest.update(path.read_bytes())
    if config_file:
        digest.update(Path(config_file).read_bytes())
    return digest.hexdigest()


def configuration_fingerprint(cfg):
    """Bind recovery to effective settings without exposing secrets or incidental random seeds."""
    import json
    value = copy.deepcopy(cfg.as_dict())
    value.pop("seed", None)
    policy = value.get("workflow_handoff", {})
    policy.pop("resume_chain", None)
    policy.pop("chain_root", None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
