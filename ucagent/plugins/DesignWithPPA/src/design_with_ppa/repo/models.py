"""Canonical task, candidate, pin, workload, and module build schemas."""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts import load_yaml
from .common import inside, relative_path


class StrictModel(BaseModel):
    """Reject unknown fields and implicit scalar conversions in task artifacts."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ResultField(StrictModel):
    """Describe one interface-independent logical result field."""

    width: int = Field(ge=1)
    signed: bool = False


class TaskContract(StrictModel):
    """Freeze required behavior and measurement conditions, not an implementation."""

    objective: str = Field(min_length=1)
    target_paths: list[str] = Field(min_length=1)
    allowed_changes: list[str] = Field(min_length=1)
    dependencies: list[str]
    caller_impact: str = Field(min_length=1)
    requirements: dict[str, str] = Field(min_length=1)
    result_fields: dict[str, ResultField] = Field(min_length=1)
    clock_period_ns: float = Field(gt=0)
    max_latency_cycles: int = Field(ge=1)
    min_throughput_per_cycle: float = Field(gt=0)
    max_cycles: int = Field(ge=1)
    max_area: float | None = Field(default=None, gt=0)
    max_power_w: float | None = Field(default=None, gt=0)
    max_effective_period_ns: float | None = Field(default=None, gt=0)
    ordering: Literal["in_order", "tagged"] = "in_order"

    @model_validator(mode="after")
    def validate_paths(self):
        """Keep all declared scope paths repository-relative and requirement text nonempty."""

        for name in self.target_paths + self.allowed_changes + self.dependencies:
            relative_path(name)
        if any(not key or not value.strip() for key, value in self.requirements.items()):
            raise ValueError("requirements must contain nonempty IDs and descriptions")
        if any(not any(fnmatch.fnmatchcase(p, g) for g in self.allowed_changes)
               for p in self.target_paths):
            raise ValueError("target_paths must be included in allowed_changes")
        return self


class Change(StrictModel):
    """Declare an explicit repository source operation, including executable mode."""

    path: str
    action: Literal["add", "replace", "delete"]
    executable: bool = False

    @field_validator("path")
    @classmethod
    def validate_path(cls, value):
        """Reject traversal before a change reaches materialization or delivery."""

        return relative_path(value)


class Candidate(StrictModel):
    """Identify one complete experiment and its source modifications."""

    variant_id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    hypothesis: str = Field(min_length=1)
    changes: list[Change]


class Pin(StrictModel):
    """Specify every public pin's exact packed representation and purpose."""

    direction: Literal["input", "output"]
    width: int = Field(ge=1)
    signed: bool = False
    purpose: str = Field(min_length=1)


class Interface(StrictModel):
    """Version the complete top-level public pin and transaction protocol contract."""

    version: str = Field(min_length=1)
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    pins: dict[str, Pin] = Field(min_length=1)
    clock: str | None
    reset: str | None
    reset_active: int = Field(ge=0, le=1)
    reset_cycles: int = Field(ge=1)
    request_when: dict[str, int]
    response_when: dict[str, int]
    protocol: str = Field(min_length=1)
    parameters: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pins(self):
        """Check signal names, control pins, and handshake predicates against public pins."""

        if self.clock is not None and self.clock == self.reset:
            raise ValueError("clock and reset must be distinct input pins")
        for name in [*self.pins, *self.parameters]:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"Invalid RTL identifier: {name}")
        for name in (self.clock, self.reset):
            if name is None:
                continue
            pin = self.pins.get(name)
            if pin is None or pin.direction != "input" or pin.width != 1:
                raise ValueError(f"Control pin must be a one-bit input: {name}")
        for name, value in {**self.request_when, **self.response_when}.items():
            if name not in self.pins or not 0 <= value < (1 << self.pins[name].width):
                raise ValueError(f"Invalid public handshake predicate: {name}")
        return self


class Command(StrictModel):
    """Describe one module-local process, never a complete-system build."""

    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout: int = Field(default=600, ge=1, le=7200)


class Recipe(StrictModel):
    """Export only the selected unit and its dependencies into synthesizable RTL."""

    scope: Literal["unit"]
    build: list[Command] = Field(default_factory=list)
    tool_versions: list[Command] = Field(default_factory=list)
    rtl_files: list[str] = Field(min_length=1)
    include_dirs: list[str] = Field(default_factory=list)
    defines: dict[str, str] = Field(default_factory=dict)
    systemverilog: bool = False
    timeout: int = Field(default=600, ge=1, le=7200)

    @model_validator(mode="after")
    def validate_build_inputs(self):
        """Require explicit ordered RTL files and safe preprocessor definitions."""

        if len(set(self.rtl_files)) != len(self.rtl_files):
            raise ValueError("rtl_files must not contain duplicates")
        if self.build and not self.tool_versions:
            raise ValueError("A native unit build requires tool_versions commands for its generator/toolchain")
        for path in self.rtl_files + self.include_dirs:
            relative_path(path)
        for command in self.build + self.tool_versions:
            relative_path(command.cwd)
        for name, value in self.defines.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not re.fullmatch(r"[A-Za-z0-9_'()+*/.:-]+", value):
                raise ValueError(f"Invalid preprocessor definition: {name}")
        return self


class Transaction(StrictModel):
    """Bind one logical request to its earliest allowed launch cycle."""

    id: str = Field(min_length=1)
    inputs: dict[str, int]
    release_cycle: int = Field(default=0, ge=0)


class Scenario(StrictModel):
    """Describe deterministic transactions and reference self-check examples."""

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    covers: list[str] = Field(min_length=1)
    transactions: list[Transaction] = Field(min_length=1)
    expected_examples: dict[str, dict[str, int]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transactions(self):
        """Require unique transaction identities and real self-check examples."""

        ids = [t.id for t in self.transactions]
        if len(ids) != len(set(ids)) or not set(self.expected_examples) <= set(ids):
            raise ValueError("Transaction IDs must be unique and cover expected_examples")
        return self


class Workload(StrictModel):
    """Freeze logical work independently from interface-specific physical input traces."""

    seed: int
    scenarios: list[Scenario] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scenarios(self):
        """Keep scenario identities unique across waveform and result artifacts."""

        names = [s.name for s in self.scenarios]
        if len(names) != len(set(names)):
            raise ValueError("Scenario names must be unique")
        return self


def read_model(root: Path, name: str, model: type[StrictModel]):
    """Load one canonical typed YAML artifact within its declared root."""

    return model.model_validate(load_yaml(inside(root, name, exists=True)))


def validate_python(path: Path, *, reference: bool = False, protocol: bool = False) -> None:
    """Constrain test programs to public pin operations and pure reference computations."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed_imports = {"math", "random", "itertools", "functools", "collections", "typing", "dataclasses", "fractions", "decimal"}
    banned_calls = {"eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "vars", "globals", "locals", "__import__", "breakpoint"}
    for node in ast.walk(tree):
        if not reference and isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Attribute) for target in targets):
                raise ValueError(f"{path.name}:{node.lineno}: test adapters must not replace public methods or object attributes")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(n.split(".")[0] not in allowed_imports for n in names):
                raise ValueError(f"{path.name}:{node.lineno}: use pure Python and the supplied public env; import is not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError(f"{path.name}:{node.lineno}: private state is not a test interface")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in banned_calls:
            raise ValueError(f"{path.name}:{node.lineno}: dynamic or external access is not allowed")
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    required = "evaluate" if reference else "run"
    if protocol:
        tests = [n for name, n in functions.items() if name.startswith("test_")]
        if not tests or any(not any(isinstance(n, ast.Assert) for n in ast.walk(test)) for test in tests):
            raise ValueError("protocol.py must contain test_* functions with real public-pin assertions")
        if any([a.arg for a in test.args.args] != ["env"] for test in tests):
            raise ValueError("Protocol test signatures must be test_*(env)")
    elif required not in functions:
        raise ValueError(f"{path.name} must define {required}")
