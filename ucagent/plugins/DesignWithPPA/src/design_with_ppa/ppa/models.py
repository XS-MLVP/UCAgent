"""Public argument schema for workspace PPA measurements."""

from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, model_validator


_TOP_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SCOPE_RE = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$"
)
_RANGED_REFERENCE_RE = re.compile(
    r"^(?P<name>.+?)\[(?P<left>-?\d+)(?::(?P<right>-?\d+))?\]$"
)
_FST_VECTOR_SUFFIX_RE = re.compile(r"\s*\[[^\]]*\]$")
_STATE_CELL_RE = re.compile(r"(?:^|[_$])(dff|sdff|adff|dlatch|mem)(?:[_$]|$)", re.I)
_REPORT_ID_RE = re.compile(r"^ppa-[0-9a-f]{32}$")


class AnalyzePPAArgs(BaseModel):
    """Strict public arguments for :class:`AnalyzePPA`."""

    model_config = ConfigDict(extra="forbid")

    rtl_files: list[str] | None = Field(
        default=None,
        description=(
            "Workspace-relative Verilog .v source files for one design. "
            "Omit to derive from the current RTL backend manifest."
        ),
    )
    top_module: str | None = Field(
        default=None,
        description=(
            "Exact top-level Verilog module name to elaborate and analyze. "
            "Omit to derive from the current RTL backend manifest."
        ),
    )
    waveform_files: list[str] | None = Field(
        default=None,
        description=(
            "Ordered workspace-relative .vcd/.fst files from independent performance-test "
            "TC runs. Their activities are duration-weighted internally. "
            "Omit to derive from the current performance manifest."
        ),
    )
    waveform_scope: str | None = Field(
        default=None,
        description=(
            "Common dotted waveform hierarchy containing the DUT ports, for example "
            "testbench.dut. Omit to derive from the current performance manifest."
        ),
    )
    liberty_file: str | None = Field(
        default=None,
        description=(
            "Optional workspace-relative Liberty .lib file overriding the configured "
            "technology library. Omit to use the configured PDK."
        ),
    )
    sdc_file: str | None = Field(
        default=None,
        description="Optional workspace-relative SDC timing constraints file.",
    )
    clock_port: str | None = Field(
        default=None,
        description="Top-level clock port used with clock_period_ns when no SDC is supplied.",
    )
    clock_period_ns: float | None = Field(
        default=None,
        gt=0,
        description="Positive clock period in nanoseconds, paired with clock_port.",
    )
    report_path: str | None = Field(
        default=None,
        description=(
            "Optional writable workspace-relative .json destination. Defaults to "
            "{OUT}/{top_module}_ppa_report.json."
        ),
    )
    baseline_report_id: str | None = Field(
        default=None,
        description=(
            "Optional report_id from the internal PPA cache. The current report is "
            "compared against that baseline after analysis."
        ),
    )
    max_timing_paths: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum critical timing paths retained in the detailed report.",
    )
    max_power_instances: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum highest-power instances retained in the detailed report.",
    )
    timeout: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Overall PPA analysis deadline in seconds.",
    )

    @model_validator(mode="after")
    def validate_contract(self):
        """Reject ambiguous constraints and malformed design identifiers.

        The four workspace-derivable fields may arrive as ``None``; format
        validation is deferred until :meth:`AnalyzePPA._run` fills them from
        the manifests, so this validator only checks fields that are actually
        present.
        """

        if self.top_module is not None and not _TOP_MODULE_RE.fullmatch(self.top_module):
            raise ValueError("top_module must be an ordinary Verilog identifier")
        if self.waveform_scope is not None and not _SCOPE_RE.fullmatch(self.waveform_scope):
            raise ValueError("waveform_scope must be a dotted waveform hierarchy")
        explicit_clock = self.clock_port is not None or self.clock_period_ns is not None
        if explicit_clock and (self.clock_port is None or self.clock_period_ns is None):
            raise ValueError("clock_port and clock_period_ns must be provided together")
        if self.sdc_file is not None and explicit_clock:
            raise ValueError(
                "sdc_file and explicit clock_port/clock_period_ns are mutually exclusive"
            )
        if self.clock_port is not None and not _TOP_MODULE_RE.fullmatch(self.clock_port):
            raise ValueError("clock_port must be an ordinary Verilog identifier")
        if self.baseline_report_id is not None and not _REPORT_ID_RE.fullmatch(
            self.baseline_report_id
        ):
            raise ValueError("baseline_report_id must match ppa- followed by 32 lowercase hex characters")
        return self
