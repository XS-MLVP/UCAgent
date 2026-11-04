"""Public backend extension contract for normalized, reproducible PPA measurements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
import json
import math
import subprocess
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import PPAConfig, ResolvedPDK
from .models import AnalyzePPAArgs


@dataclass(frozen=True)
class PPARequest:
    """Confined analysis inputs; all paths are resolved before backend execution."""

    arguments: AnalyzePPAArgs
    rtl_files: tuple[Path, ...]
    waveform_files: tuple[Path, ...]
    waveform_provenance: tuple[dict[str, Any], ...]
    sdc_file: Path | None
    pdk: ResolvedPDK
    systemverilog: bool
    options: dict[str, Any]


@dataclass(frozen=True)
class PPAContext:
    """Disposable working directory, shared deadline, process runner, and progress."""

    run_dir: Path
    deadline: float
    run_process: Callable[[list[str], Path, float], subprocess.CompletedProcess[str]]
    progress: Callable[[str], Any]

    def check_deadline(self) -> None:
        """Stop in-process backend work when the overall budget has expired."""

        if time.monotonic() >= self.deadline:
            raise TimeoutError("PPA analysis deadline expired")


class PPAResult(BaseModel):
    """Backend-owned report sections; publication and final status stay with the tool.

    Timing uses ns/Hz and power uses watts. Missing measurements are null and
    produce a partial report. Nonfinite numbers and malformed primary metrics
    are rejected before publication.
    """

    model_config = ConfigDict(extra="forbid")
    summary: dict[str, Any] = Field(default_factory=lambda: {
        "design_type": "unknown", "area": None, "timing": None, "power": None,
    })
    details: dict[str, Any] = Field(default_factory=lambda: {
        "classification": None, "area_by_cell_type": {}, "timing_paths": [], "power_groups": [],
    })
    hotspots: dict[str, Any] = Field(default_factory=lambda: {
        "timing_paths": [], "power_instances": [], "findings": [],
    })
    waveform_aggregation: dict[str, Any] = Field(default_factory=lambda: {
        "method": "duration_weighted_independent_tc_activity",
        "formula": {
            "density_hz": "sum(tc_transition_count) / sum(tc_duration_seconds)",
            "duty_cycle": "sum(tc_high_duration_seconds) / sum(tc_duration_seconds)",
        },
        "reliable": False, "test_cases": [], "merged_input_bits": [],
    })
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    tools: dict[str, Any] = Field(default_factory=dict)
    waveform_scope: str | None = None

    @model_validator(mode="after")
    def validate_measurements(self):
        """Validate canonical primary metric types and evidence container shapes."""

        json.dumps(self.model_dump(), allow_nan=False)
        if set(self.summary) != {"design_type", "area", "timing", "power"}:
            raise ValueError("summary requires design_type, area, timing, and power")
        if self.summary["design_type"] not in {"unknown", "combinational", "sequential"}:
            raise ValueError("design_type must be unknown, combinational, or sequential")
        for group, keys in (("area", ("total",)), ("timing", ("critical_path_delay_ns", "maximum_frequency_hz")), ("power", ("total_w",))):
            row = self.summary[group]
            if row is None:
                continue
            if not isinstance(row, dict):
                raise ValueError(f"summary.{group} must be a metric mapping or null")
            for key in keys:
                value = row.get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                    raise ValueError(f"summary.{group}.{key} must be a finite nonnegative number or null")
            if group == "area" and (not isinstance(row.get("unit"), str) or not row["unit"]):
                raise ValueError("summary.area.unit must identify the area unit")
            if group == "timing" and not isinstance(row.get("metric_kind"), str):
                raise ValueError("summary.timing.metric_kind must identify the timing metric")
            if group == "timing" and row["metric_kind"] not in {"critical_path_delay", "minimum_clock_period"}:
                raise ValueError("timing.metric_kind must be critical_path_delay or minimum_clock_period")
        for key in ("test_cases", "merged_input_bits"):
            if not isinstance(self.waveform_aggregation.get(key), list):
                raise ValueError(f"waveform_aggregation.{key} must be a list")
        if type(self.waveform_aggregation.get("reliable")) is not bool:
            raise ValueError("waveform_aggregation.reliable must be a boolean")
        if self.waveform_aggregation["reliable"] and (
            not self.waveform_aggregation["test_cases"] or not self.waveform_aggregation["merged_input_bits"]
        ):
            raise ValueError("reliable activity requires test cases and merged input bits")
        return self

    @property
    def complete(self) -> bool:
        """Require all primary measurements, classification, and reliable activity."""

        area, timing, power = (self.summary[key] or {} for key in ("area", "timing", "power"))
        timing_value = timing.get("maximum_frequency_hz") if timing.get("metric_kind") == "minimum_clock_period" else timing.get("critical_path_delay_ns")
        return (area.get("total") is not None and power.get("total_w") is not None
                and bool(timing_value)
                and self.summary["design_type"] != "unknown" and self.waveform_aggregation["reliable"])


class PPABackend(ABC):
    """Implement one independently selectable analysis toolchain.

    Implementations must declare a stable name and version, use the supplied
    process runner for cancellation/deadlines, and return normalized results.
    """

    name: str
    version: str

    @abstractmethod
    def analyze(self, request: PPARequest, context: PPAContext) -> PPAResult:
        """Measure the supplied design and return available metrics and evidence."""


def load_backend(selection: str) -> PPABackend:
    """Instantiate the built-in backend or an explicitly configured module:class."""

    if selection == "yosys_opensta":
        from .backends.yosys_opensta import YosysOpenSTABackend
        cls = YosysOpenSTABackend
    else:
        module, separator, name = selection.partition(":")
        if not separator or not module or not name or ":" in name:
            raise ValueError("ppa.backend must be yosys_opensta or an importable module:Class")
        try:
            cls = getattr(import_module(module), name)
        except (ImportError, AttributeError) as exc:
            raise ValueError(
                f"Cannot load PPA backend {selection!r}; install its package in the UCAgent environment and set ppa.backend to module:Class"
            ) from exc
    if not isinstance(cls, type) or not issubclass(cls, PPABackend):
        raise ValueError("configured PPA backend must subclass PPABackend")
    try:
        backend = cls()
    except Exception as exc:
        raise ValueError(f"Cannot initialize PPA backend {selection!r}: {exc}") from exc
    if not isinstance(getattr(backend, "name", None), str) or not backend.name or not isinstance(getattr(backend, "version", None), str) or not backend.version:
        raise ValueError("PPA backend must declare nonempty name and version strings")
    return backend


def backend_identity(backend: PPABackend, config: PPAConfig) -> dict[str, Any]:
    """Bind selection, implementation version, and options into report comparison."""

    return {"selection": config.backend, "name": backend.name, "version": backend.version,
            "options": config.model_dump()["backend_options"]}
