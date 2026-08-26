# -*- coding: utf-8 -*-
"""Waveform discovery, event analysis, and receipt-backed evidence tools."""

from __future__ import annotations

import ast
from bisect import bisect_left, bisect_right
from collections import OrderedDict
import copy
from dataclasses import dataclass
from datetime import datetime
from difflib import get_close_matches
import hashlib
import hmac
import json
from pathlib import Path
import os
import re
import secrets
import stat
import tempfile
import threading
import textwrap
import time
from typing import Any, ClassVar, Literal, Optional
import weakref

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field, model_validator
import yaml

from ucagent.util.functions import make_llm_tool_ret
from ucagent.util.bug_analysis_contract import (
    BUG_ANALYSIS_SECTION_MARKERS,
    BUG_ANALYSIS_SECTION_TITLES,
    WAVEFORM_BUG_ANALYSIS_FIELDS,
    BUG_TODO_MARKER,
    DOCUMENT_TAG_PATTERN,
    DYNAMIC_BUGS_END_MARKER,
    DYNAMIC_BUGS_MARKER,
    WAVEFORM_BLOCK_KEY,
    WAVEFORM_EVIDENCE_END_MARKER,
    WAVEFORM_EVIDENCE_MARKER,
    WAVEFORM_FENCE_CLOSE,
    WAVEFORM_FENCE_OPEN,
    WAVEFORM_LLM_ANALYSIS_FIELDS,
    WAVEFORM_REFERENCE_MARKER,
    WAVEFORM_SIGNAL_GROUP_FIELDS,
    normalize_display_title,
    normalize_test_case_tag,
    parse_dynamic_tag_heading,
    parse_waveform_record_heading,
    test_case_identity_relation,
    test_case_parent,
    waveform_anchor_id,
    waveform_record_heading,
    waveform_record_tag,
    waveform_reference,
)
from ucagent.util.log import warning
from ucagent.util.markdown import ensure_markdown_file_heading_spacing
from ucagent.util.waveform_viewer import (
    WaveformViewerProtocolError,
    build_waveform_viewer_markdown_link,
    build_waveform_viewer_url,
    normalize_waveform_viewer_payload,
)
from .uctool import UCTool


_DOCUMENT_WRITE_LOCK = threading.Lock()
_RECEIPT_STORE_LOCKS = weakref.WeakValueDictionary()
_RECEIPT_STORE_LOCKS_GUARD = threading.Lock()


WaveEvent = Literal["change", "rising", "falling", "equals", "unknown"]
ClockEdge = Literal["rising", "falling"]
WaveClockMode = Literal["", "clocked", "combinational"]


class WaveSignalPattern(BaseModel):
    """A safe waveform signal query and event selector."""

    signal: str = Field(
        ...,
        min_length=1,
        description=(
            "wavekit signal query: exact dotted path, *, **, /{regex}/, or brace "
            "alternatives/ranges"
        ),
    )
    event: WaveEvent = Field(
        default="change",
        description="Event to find: change, rising, falling, equals, or unknown.",
    )
    value: int | str | None = Field(
        default=None,
        description=(
            "Required only for equals. Accepts an integer, decimal, 0x/0b value, "
            "or a Verilog literal such as 8'hff."
        ),
    )

    @model_validator(mode="after")
    def validate_event_value(self):
        if self.event == "equals" and self.value is None:
            raise ValueError("event='equals' requires a value")
        if self.event != "equals" and self.value is not None:
            raise ValueError("value is only valid when event='equals'")
        self.signal = self.signal.strip()
        if not self.signal:
            raise ValueError("signal query must not be blank")
        return self


class WaveSignalGroups(BaseModel):
    """Exact waveform paths grouped by their role in final Bug evidence."""

    clock_mode: WaveClockMode = Field(
        default="",
        description=(
            "Use clocked when the DUT has a relevant clock, combinational when it does "
            "not, or leave empty when final Bug evidence is not being requested."
        ),
    )
    clocks: list[str] = Field(
        default_factory=list,
        description="Exact full paths of relevant DUT clock signals.",
    )
    inputs: list[str] = Field(
        default_factory=list,
        description=(
            "Exact full paths of relevant DUT data, selector, enable, request, and other inputs."
        ),
    )
    outputs: list[str] = Field(
        default_factory=list,
        description=(
            "Exact full paths of relevant DUT data, status, valid, and other outputs."
        ),
    )
    protocol: list[str] = Field(
        default_factory=list,
        description=(
            "Exact full paths of request/response acceptance and validity signals such as "
            "enable, ready, valid, busy, done, or the DUT's equivalent; empty only when "
            "the interface has no such protocol signals."
        ),
    )
    key_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Exact full paths of function-specific selectors, state, flags, or internal "
            "signals needed to explain selection and error propagation."
        ),
    )

    @model_validator(mode="after")
    def validate_groups(self):
        for field_name in WAVEFORM_SIGNAL_GROUP_FIELDS:
            normalized = []
            seen = set()
            for value in getattr(self, field_name):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"signal_groups.{field_name} entries must be non-empty strings"
                    )
                value = value.strip()
                if value not in seen:
                    seen.add(value)
                    normalized.append(value)
            setattr(self, field_name, normalized)

        has_signals = any(
            getattr(self, field) for field in WAVEFORM_SIGNAL_GROUP_FIELDS
        )
        if not self.clock_mode:
            if has_signals:
                raise ValueError(
                    "signal_groups.clock_mode is required when signal groups are provided"
                )
            return self
        if self.clock_mode == "clocked" and not self.clocks:
            raise ValueError("signal_groups.clocks must contain a DUT clock in clocked mode")
        if self.clock_mode == "combinational" and self.clocks:
            raise ValueError("signal_groups.clocks must be empty in combinational mode")
        for field_name in ("inputs", "outputs", "key_signals"):
            if not getattr(self, field_name):
                raise ValueError(
                    f"signal_groups.{field_name} must contain at least one relevant signal"
                )
        return self

    def is_empty(self) -> bool:
        return not self.clock_mode


class WaveInfoAnalysisArgs(BaseModel):
    """Canonical arguments used by :class:`WaveInfo` analysis and receipts."""

    test_case_name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Test function name or full pytest node ID. Omit it to list waveform "
            "files in the newest session. When provided, the final :: component is "
            "used as the exact waveform basename, including parameter IDs. For Bug "
            "evidence, use the complete target TC node ID with only the leading TC- "
            "removed; inventory basename hints are not source-test identities."
        ),
    )
    pattern: list[WaveSignalPattern] | None = Field(
        default=None,
        description=(
            "Structured signal/event queries. Omit this to inspect waveform metadata "
            "and the signal catalog."
        ),
    )
    signal_groups: WaveSignalGroups | None = Field(
        default=None,
        description=(
            "Required for final Bug-document evidence. Group exact full paths for the DUT "
            "clock (if any), relevant inputs, relevant outputs, protocol controls, and "
            "function-specific key signals. These signals are loaded for context and the "
            "online viewer but do not become event triggers."
        ),
    )
    logged_cycle: int | None = Field(
        default=None,
        ge=0,
        description="Cycle number printed by the failing test; it is not a wavekit timestamp.",
    )
    cycle_tolerance: int = Field(
        default=5,
        ge=0,
        le=100,
        description="Clock-edge tolerance around logged_cycle, in cycles.",
    )
    clock_signal: str | None = Field(
        default=None,
        description="Exact or wavekit query for the one-bit clock used to align logged_cycle.",
    )
    clock_edge: ClockEdge = Field(
        default="rising",
        description="Clock edge on which the test's cycle counter advances.",
    )
    cycle_origin: int = Field(
        default=0,
        ge=0,
        description=(
            "Global clock occurrence index corresponding to logged cycle 0. This is "
            "an alignment hypothesis and still requires signal-context confirmation."
        ),
    )
    start_step: int | None = Field(
        default=None,
        ge=0,
        description="Inclusive wavekit simulation timestamp for an explicit read window.",
    )
    end_step: int | None = Field(
        default=None,
        ge=0,
        description="Inclusive wavekit simulation timestamp for an explicit read window.",
    )
    context_steps: int = Field(
        default=1,
        ge=0,
        le=20,
        description=(
            "Surrounding event points to include. During cycle alignment it also "
            "extends signal loading by this many clock edges."
        ),
    )
    max_signals: int = Field(
        default=32,
        ge=1,
        le=64,
        description=(
            "Maximum combined event/context signals; analysis fails instead of truncating "
            "a requested signal set."
        ),
    )
    max_points: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of timestamps returned in the event timeline.",
    )
    max_files: int = Field(
        default=20,
        ge=1,
        le=1000,
        description=(
            "Maximum waveform files shown by the no-argument newest-session inventory."
        ),
    )
    file_offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based waveform-file offset used by inventory pagination.",
    )

    @model_validator(mode="after")
    def validate_window(self):
        if self.test_case_name is not None:
            self.test_case_name = self.test_case_name.strip()
            if not self.test_case_name:
                raise ValueError("test_case_name must not be blank")
        elif any(
            value is not None
            for value in (
                self.pattern,
                self.signal_groups,
                self.logged_cycle,
                self.clock_signal,
                self.start_step,
                self.end_step,
            )
        ):
            raise ValueError(
                "test_case_name is required when requesting signals, events, cycle "
                "alignment, or a wave-step window; omit all analysis arguments to list "
                "the newest session's waveform files"
            )
        if self.signal_groups is not None and self.signal_groups.is_empty():
            self.signal_groups = None
        if self.signal_groups is not None and not self.pattern:
            raise ValueError("signal_groups requires a non-empty event pattern")
        if self.clock_signal is not None:
            self.clock_signal = self.clock_signal.strip() or None
        if (
            self.signal_groups is not None
            and self.signal_groups.clock_mode == "combinational"
            and self.clock_signal is not None
        ):
            raise ValueError(
                "clock_signal is not valid when signal_groups.clock_mode is combinational"
            )
        if (
            self.start_step is not None
            and self.end_step is not None
            and self.start_step > self.end_step
        ):
            raise ValueError("start_step must be less than or equal to end_step")
        if (self.start_step is None) != (self.end_step is None):
            raise ValueError(
                "start_step and end_step must be provided together for an explicit window"
            )
        if self.logged_cycle is not None and self.start_step is not None:
            raise ValueError(
                "logged_cycle alignment and an explicit start_step/end_step window are "
                "separate evidence modes; use one mode per WaveInfo call"
            )
        return self


class WaveInfoToolPattern(BaseModel):
    """Non-nullable MCP representation of one waveform query."""

    signal: str = Field(
        ...,
        min_length=1,
        description=(
            "wavekit signal query: exact dotted path, *, **, /{regex}/, or brace "
            "alternatives/ranges"
        ),
    )
    event: WaveEvent = Field(
        default="change",
        description="Event to find: change, rising, falling, equals, or unknown.",
    )
    value: str = Field(
        default="",
        description=(
            "Required only for equals. Use a decimal, 0x/0b value, or a Verilog "
            "literal such as 8'hff; otherwise leave it empty."
        ),
    )

    @model_validator(mode="after")
    def validate_event_value(self):
        self.signal = self.signal.strip()
        self.value = self.value.strip()
        if not self.signal:
            raise ValueError("signal query must not be blank")
        if self.event == "equals" and not self.value:
            raise ValueError("event='equals' requires a non-empty value")
        if self.event != "equals" and self.value:
            raise ValueError("value is only valid when event='equals'")
        return self


class ArgWaveInfo(BaseModel):
    """Simple non-nullable arguments published through MCP."""

    test_case_name: str = Field(
        default="",
        description=(
            "Test function name or full pytest node ID. Leave empty only to list "
            "waveform files in the newest session. For Bug evidence, copy the complete "
            "target TC tag and remove only its leading TC-; do not remove or add path "
            "components. Inventory basename hints are discovery-only."
        ),
    )
    pattern: list[WaveInfoToolPattern] = Field(
        default=[],
        description=(
            "Structured signal/event queries. Leave empty to inspect waveform metadata "
            "and the signal catalog."
        ),
    )
    signal_groups: WaveSignalGroups = Field(
        default_factory=WaveSignalGroups,
        description=(
            "Required for final Bug-document evidence. Use exact full paths and classify "
            "the DUT clock mode, relevant inputs, outputs, protocol controls, and key signals."
        ),
    )
    logged_cycle: int = Field(
        default=-1,
        ge=-1,
        description=(
            "Cycle number printed by the failing test, or -1 when unavailable; it is "
            "not a wavekit timestamp."
        ),
    )
    cycle_tolerance: int = Field(
        default=5,
        ge=0,
        le=100,
        description="Clock-edge tolerance around logged_cycle, in cycles.",
    )
    clock_signal: str = Field(
        default="",
        description=(
            "Exact or wavekit query for the one-bit clock used to align logged_cycle; "
            "leave empty when cycle alignment is not requested."
        ),
    )
    clock_edge: ClockEdge = Field(
        default="rising",
        description="Clock edge on which the test's cycle counter advances.",
    )
    cycle_origin: int = Field(
        default=0,
        ge=0,
        description=(
            "Global clock occurrence index corresponding to logged cycle 0. This is "
            "an alignment hypothesis and still requires signal-context confirmation."
        ),
    )
    start_step: int = Field(
        default=-1,
        ge=-1,
        description=(
            "Inclusive wavekit simulation timestamp for an explicit read window, or -1."
        ),
    )
    end_step: int = Field(
        default=-1,
        ge=-1,
        description=(
            "Inclusive wavekit simulation timestamp for an explicit read window, or -1."
        ),
    )
    context_steps: int = Field(
        default=1,
        ge=0,
        le=20,
        description=(
            "Surrounding event points to include. During cycle alignment it also "
            "extends signal loading by this many clock edges."
        ),
    )
    max_signals: int = Field(
        default=32,
        ge=1,
        le=64,
        description=(
            "Maximum combined event/context signals; analysis fails instead of truncating "
            "a requested signal set."
        ),
    )
    max_points: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of timestamps returned in the event timeline.",
    )
    max_files: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Maximum waveform files shown on one inventory page.",
    )
    file_offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based waveform-file offset used by inventory pagination.",
    )

    @model_validator(mode="after")
    def validate_request(self):
        self.test_case_name = self.test_case_name.strip()
        self.clock_signal = self.clock_signal.strip()
        if not self.test_case_name and any(
            (
                self.pattern,
                not self.signal_groups.is_empty(),
                self.logged_cycle >= 0,
                bool(self.clock_signal),
                self.start_step >= 0,
                self.end_step >= 0,
            )
        ):
            raise ValueError(
                "test_case_name is required when requesting signals, events, cycle "
                "alignment, or a wave-step window"
            )
        if self.start_step >= 0 and self.end_step >= 0 and self.start_step > self.end_step:
            raise ValueError("start_step must be less than or equal to end_step")
        if (self.start_step >= 0) != (self.end_step >= 0):
            raise ValueError(
                "start_step and end_step must both be non-negative, or both use -1"
            )
        if self.logged_cycle >= 0 and self.start_step >= 0:
            raise ValueError(
                "logged_cycle alignment and an explicit start_step/end_step window are "
                "separate evidence modes; use one mode per WaveInfo call"
            )
        if not self.signal_groups.is_empty() and not self.pattern:
            raise ValueError("signal_groups requires a non-empty event pattern")
        if self.signal_groups.clock_mode == "combinational" and self.clock_signal:
            raise ValueError(
                "clock_signal is not valid when signal_groups.clock_mode is combinational"
            )
        return self

    def analysis_arguments(self) -> dict[str, Any]:
        """Convert MCP sentinel values into the canonical optional representation."""

        patterns = [entry.model_dump(mode="json") for entry in self.pattern]
        for entry in patterns:
            if entry["event"] != "equals":
                entry["value"] = None
        return {
            "test_case_name": self.test_case_name or None,
            "pattern": patterns or None,
            "signal_groups": (
                None
                if self.signal_groups.is_empty()
                else self.signal_groups.model_dump(mode="json")
            ),
            "logged_cycle": self.logged_cycle if self.logged_cycle >= 0 else None,
            "cycle_tolerance": self.cycle_tolerance,
            "clock_signal": self.clock_signal or None,
            "clock_edge": self.clock_edge,
            "cycle_origin": self.cycle_origin,
            "start_step": self.start_step if self.start_step >= 0 else None,
            "end_step": self.end_step if self.end_step >= 0 else None,
            "context_steps": self.context_steps,
            "max_signals": self.max_signals,
            "max_points": self.max_points,
            "max_files": self.max_files,
            "file_offset": self.file_offset,
        }


class ArgApplyWaveInfoEvidence(BaseModel):
    """Arguments for associating one signed WaveInfo receipt with one BG/TC pair."""

    target_file: str = Field(
        ...,
        min_length=1,
        description=(
            "Existing dynamic Bug-analysis Markdown file, relative to the workspace. "
            "The file must be inside an enabled write directory."
        ),
    )
    bug_tag: str = Field(
        ...,
        min_length=1,
        description=(
            "Exact non-static, non-zero-confidence dynamic Bug tag, for example "
            "BG-ADD-OVERFLOW-95. Angle brackets are optional. The BG path entry must already "
            "exist. The same Bug tag may repeat under different CK branches when one root "
            "cause affects tests associated with those CKs; pass checkpoint_path to select "
            "the exact occurrence. Within one CK branch, add sibling TCs to the existing BG "
            "occurrence. When one failing test exposes multiple independent Bugs, call the "
            "tool separately with each distinct bug_tag."
        ),
    )
    checkpoint_path: str = Field(
        default="",
        description=(
            "Exact FG/FC/CK path owning the target BG occurrence, for example "
            "FG-ARITHMETIC/FC-ADD/CK-OVERFLOW. Required when the same bug_tag/test_case_tag "
            "pair is ambiguous or when a missing TC must be inserted into a bug_tag that "
            "appears under multiple CK branches; otherwise it may be blank."
        ),
    )
    test_case_tag: str = Field(
        ...,
        min_length=1,
        description=(
            "Exact TC tag under bug_tag, copied from the current report node ID after "
            "removing only its file line range and adding TC-. Its file path must begin "
            "with the configured TC output directory shown by the current stage/Checker. "
            "Angle brackets are optional. If the TC is "
            "absent, the tool creates it under the unique BG. The same TC may be associated "
            "with multiple distinct Bugs while retaining one central waveform record. The "
            "operation preserves sibling TCs and records owned by other tests. The signed "
            "WaveInfo test_case_name must equal this value after removing TC-, or may be one "
            "parameterized child of the same exact workspace-relative file/class/function. "
            "Different paths, classes, and functions are never equivalent."
        ),
    )
    receipt_id: str = Field(
        default="",
        description=(
            "Receipt ID returned by the final evidence-producing WaveInfo call. Leave "
            "blank to select the newest signed final receipt matching test_case_tag."
        ),
    )
    replace_existing: bool = Field(
        default=False,
        description=(
            "Set true only when deliberately replacing a different real receipt already "
            "recorded for this TC. Scaffold placeholders and the same receipt do not require "
            "this flag. Adding another TC under the same BG also does not require it. A "
            "replacement must retain every signal required by all associated Bugs."
        ),
    )

    @model_validator(mode="after")
    def normalize_values(self):
        for field_name in ("target_file", "bug_tag", "test_case_tag"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be blank")
            setattr(self, field_name, value)
        self.receipt_id = self.receipt_id.strip()
        self.checkpoint_path = self.checkpoint_path.strip()
        return self


@dataclass(frozen=True)
class _WaveSelection:
    test_case_name: str
    expected_basename: str
    data_dir: Path
    session: Path
    waveform: Path
    suffix: int
    worker: str


@dataclass(frozen=True)
class _ValueState:
    wave_step: int
    value: int
    x_mask: int
    z_mask: int


@dataclass
class _SignalTrace:
    name: str
    width: int
    states: list[_ValueState]

    @property
    def wave_steps(self) -> list[int]:
        return [state.wave_step for state in self.states]

    def value_at(self, wave_step: int) -> _ValueState | None:
        index = bisect_right(self.wave_steps, wave_step) - 1
        return self.states[index] if index >= 0 else None


def _import_wavekit():
    """Import lazily so a missing optional runtime does not break UCAgent startup."""

    import wavekit  # type: ignore[import-not-found]

    return wavekit


class WaveInfo(UCTool):
    """Locate the newest test waveform and return structured event evidence."""

    name: str = "WaveInfo"
    description: str = (
        "List or inspect waveforms generated by UnityChip pytest cases. Call WaveInfo "
        "without arguments to list file metadata from the newest toffee_tmp_* session. "
        "Provide test_case_name to inspect one exact waveform and optionally analyze events. "
        "For Bug evidence, test_case_name must be the complete target TC pytest node ID "
        "with only the leading TC- removed. Inventory basenames locate waveform files but "
        "do not define or shorten the source-test identity. "
        "The tool searches only the newest toffee_tmp_* session, prefers FST, "
        "and never substitutes another test or a stale session. Signal queries use "
        "wavekit syntax and must be supplied as structured pattern entries. "
        "A pattern-only call is exploratory: final Bug evidence must use either a "
        "complete start_step/end_step window or logged_cycle with an exact clock_signal. "
        "Final Bug evidence also requires signal_groups with the DUT clock mode, relevant "
        "inputs, relevant outputs, actual protocol controls, and function-specific key "
        "signals. These context signals are shown in the timeline and online viewer without "
        "becoming event triggers. A target result signal alone is not complete evidence. "
        "logged_cycle is only a test-log hint: provide clock_signal so the tool can "
        "map clock occurrence indices to wavekit simulation timestamps. Always "
        "confirm a candidate with the interface specification, test-driver/API Step "
        "ordering, logged inputs, ready/valid or the DUT's equivalent acceptance and "
        "response conditions, backpressure/latency, state, transaction IDs, and relevant "
        "pins before using it as Bug evidence. One simulation Step does not by itself make "
        "a request accepted or an output valid; inspect whether the API already steps/waits "
        "and what edge, latency, response-valid, done, or busy condition permits sampling. "
        "WaveInfo finds reproducible events; it does not decide that a value is valid at "
        "an arbitrary timestamp or classify a DUT Bug."
    )
    args_schema: Optional[ArgsSchema] = ArgWaveInfo
    return_direct: bool = False
    call_lock_arguments: tuple[str, ...] = ("test_case_name",)

    workspace: str = Field(default=".", description="UCAgent workspace root.")
    test_dir: str = Field(default=".", description="Rendered UnityChip pytest directory.")
    dut_name: str = Field(default="", description="DUT name used in rerun suggestions.")
    analysis_receipts: list[dict[str, Any]] = Field(
        default_factory=list,
        exclude=True,
        repr=False,
        description=(
            "Signed receipts created only by actual WaveInfo calls and restored from the "
            "workspace checkpoint store."
        ),
    )

    _SESSION_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^toffee_tmp_(\d{14})_(\d{3,6})$"
    )
    _RECEIPT_STORE_VERSION: ClassVar[int] = 1
    _RECEIPT_LIMIT: ClassVar[int] = 4096
    _RECEIPT_STORE_RELATIVE: ClassVar[Path] = Path(
        ".ucagent/waveinfo_receipts.json"
    )
    _RECEIPT_KEY_RELATIVE: ClassVar[Path] = Path(
        ".ucagent/.waveinfo_receipt_key"
    )
    _ANALYSIS_CONTEXT_SUFFIXES: ClassVar[frozenset[str]] = frozenset(
        {".py", ".v", ".vh", ".sv", ".svh", ".vhd", ".vhdl", ".scala"}
    )
    _ANALYSIS_CONTEXT_EXCLUDED_DIRS: ClassVar[frozenset[str]] = frozenset(
        {".git", ".ucagent", "__pycache__", "data"}
    )

    def __init__(
        self,
        workspace: str = ".",
        test_dir: str = ".",
        dut_name: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.workspace = os.path.abspath(workspace)
        self.test_dir = (
            os.path.abspath(test_dir)
            if os.path.isabs(test_dir)
            else os.path.abspath(os.path.join(self.workspace, test_dir))
        )
        configured_test_dir = os.path.relpath(
            self.test_dir, self.workspace
        ).replace(os.sep, "/")
        self.description = (
            f"{self.description} Configured TC output directory for this run: "
            f"'{configured_test_dir}'. Exact source node IDs must start with "
            f"'{configured_test_dir}/'."
        )
        self.dut_name = dut_name
        self.analysis_receipts = []
        self._load_analysis_receipts()

    def _receipt_store_path(self) -> Path:
        return Path(self.workspace) / self._RECEIPT_STORE_RELATIVE

    def _receipt_key_path(self) -> Path:
        return Path(self.workspace) / self._RECEIPT_KEY_RELATIVE

    def _receipt_store_lock(self):
        store_path = os.path.realpath(self._receipt_store_path())
        with _RECEIPT_STORE_LOCKS_GUARD:
            lock = _RECEIPT_STORE_LOCKS.get(store_path)
            if lock is None:
                lock = threading.RLock()
                _RECEIPT_STORE_LOCKS[store_path] = lock
            return lock

    def _receipt_scope_identity(self) -> str:
        scope = {
            "workspace": os.path.realpath(self.workspace),
            "test_dir": os.path.realpath(self.test_dir),
            "dut_name": self.dut_name,
        }
        canonical = json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_receipt(receipt: dict[str, Any]) -> bytes:
        unsigned = {
            key: value
            for key, value in receipt.items()
            if key != "integrity_hmac"
        }
        return json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")

    def _read_receipt_key(self, *, create: bool) -> bytes | None:
        path = self._receipt_key_path()
        if path.exists():
            key = bytes.fromhex(path.read_text(encoding="ascii").strip())
            if len(key) != 32:
                raise ValueError(f"Invalid WaveInfo receipt key length in '{path}'.")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return key
        if not create:
            return None

        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return self._read_receipt_key(create=False)
        try:
            os.write(descriptor, key.hex().encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return key

    def _sign_receipt(self, receipt: dict[str, Any], key: bytes) -> str:
        return hmac.new(
            key,
            self._canonical_receipt(receipt),
            hashlib.sha256,
        ).hexdigest()

    def _load_persisted_receipts(
        self,
        key: bytes | None = None,
    ) -> list[dict[str, Any]]:
        with self._receipt_store_lock():
            return self._load_persisted_receipts_unlocked(key)

    def _load_persisted_receipts_unlocked(
        self,
        key: bytes | None = None,
    ) -> list[dict[str, Any]]:
        path = self._receipt_store_path()
        if not path.is_file():
            return []
        if key is None:
            key = self._read_receipt_key(create=False)
        if key is None:
            warning(
                f"Ignoring WaveInfo receipt store '{path}' because its signing key is missing."
            )
            return []

        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            warning(f"Ignoring invalid WaveInfo receipt store '{path}': {error}")
            return []
        if not isinstance(store, dict) or store.get("schema_version") != self._RECEIPT_STORE_VERSION:
            warning(f"Ignoring unsupported WaveInfo receipt store '{path}'.")
            return []
        scope_identity = self._receipt_scope_identity()
        if store.get("scope_identity") != scope_identity:
            warning(
                f"Ignoring WaveInfo receipt store '{path}' because it belongs to a different workspace/test directory."
            )
            return []

        validated = []
        for receipt in store.get("receipts", []):
            if not isinstance(receipt, dict):
                continue
            receipt_id = receipt.get("receipt_id")
            signature = receipt.get("integrity_hmac")
            if not isinstance(receipt_id, str) or not receipt_id:
                continue
            if receipt.get("scope_identity") != scope_identity:
                continue
            if not isinstance(receipt.get("arguments"), dict):
                continue
            if not isinstance(receipt.get("result"), dict):
                continue
            if not isinstance(signature, str) or not hmac.compare_digest(
                signature,
                self._sign_receipt(receipt, key),
            ):
                warning(
                    f"Ignoring WaveInfo receipt '{receipt_id}' because its signature is invalid."
                )
                continue
            validated.append(copy.deepcopy(receipt))
        return validated[-self._RECEIPT_LIMIT :]

    @classmethod
    def _merge_receipts(
        cls,
        *receipt_lists: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for receipts in receipt_lists:
            for receipt in receipts:
                receipt_id = receipt.get("receipt_id")
                if not isinstance(receipt_id, str) or not receipt_id:
                    continue
                merged.pop(receipt_id, None)
                merged[receipt_id] = copy.deepcopy(receipt)
        return list(merged.values())[-cls._RECEIPT_LIMIT :]

    def _load_analysis_receipts(self) -> None:
        with self._receipt_store_lock():
            try:
                self.analysis_receipts = self._load_persisted_receipts_unlocked()
            except Exception as error:
                warning(f"Could not restore persisted WaveInfo receipts: {error}")
                self.analysis_receipts = []

    def _persist_analysis_receipts(self) -> None:
        with self._receipt_store_lock():
            self._persist_analysis_receipts_unlocked()

    def _persist_analysis_receipts_unlocked(self) -> None:
        key = self._read_receipt_key(create=True)
        if key is None:
            raise RuntimeError("Could not create the WaveInfo receipt signing key.")
        persisted = self._load_persisted_receipts_unlocked(key)
        merged = self._merge_receipts(persisted, self.analysis_receipts)
        scope_identity = self._receipt_scope_identity()
        for receipt in merged:
            receipt["scope_identity"] = scope_identity
            receipt["integrity_hmac"] = self._sign_receipt(receipt, key)

        store = {
            "schema_version": self._RECEIPT_STORE_VERSION,
            "scope_identity": scope_identity,
            "receipts": merged,
        }
        path = self._receipt_store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                json.dump(store, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
            self.analysis_receipts = merged
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _normalize_test_case_name(test_case_name: str) -> str:
        normalized = test_case_name.strip().split("::")[-1]
        for suffix in (".fst", ".vcd", ".dat"):
            if normalized.lower().endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        if not normalized or "/" in normalized or "\\" in normalized:
            raise ValueError(
                "test_case_name must resolve to a pytest function name, for example "
                "test_add or tests/test_add.py::TestAdder::test_add[param]"
            )
        return normalized

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(Path(self.workspace).resolve()))
        except ValueError:
            return str(path.resolve())

    @classmethod
    def _session_key(cls, path: Path) -> tuple[float, float, str]:
        match = cls._SESSION_RE.fullmatch(path.name)
        if match is None:
            return (float("-inf"), path.stat().st_mtime, str(path))
        stamp, fraction = match.groups()
        parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S").timestamp()
        parsed += int(fraction) / (10 ** len(fraction))
        return (parsed, path.stat().st_mtime, str(path))

    @staticmethod
    def _wave_name_match(path: Path, basename: str) -> tuple[bool, int]:
        match = re.fullmatch(
            rf"{re.escape(basename)}(?P<suffix>\d*)\.(?:fst|vcd)",
            path.name,
            flags=re.IGNORECASE,
        )
        if match is None:
            return False, 0
        suffix = match.group("suffix")
        return True, int(suffix) if suffix else 0

    @staticmethod
    def _data_name_match(path: Path, basename: str) -> bool:
        return (
            re.fullmatch(
                rf"{re.escape(basename)}(?:\d*)\.dat",
                path.name,
                flags=re.IGNORECASE,
            )
            is not None
        )

    @staticmethod
    def _format_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="milliseconds")

    @classmethod
    def _session_started_at(cls, session: Path) -> str | None:
        match = cls._SESSION_RE.fullmatch(session.name)
        if match is None:
            return None
        stamp, fraction = match.groups()
        timestamp = datetime.strptime(stamp, "%Y%m%d%H%M%S").timestamp()
        timestamp += int(fraction) / (10 ** len(fraction))
        return cls._format_time(timestamp)

    def _valid_sessions(self, data_dir: Path) -> list[Path]:
        return sorted(
            (
                path
                for path in data_dir.rglob("toffee_tmp_*")
                if path.is_dir() and self._SESSION_RE.fullmatch(path.name)
            ),
            key=self._session_key,
            reverse=True,
        )

    @staticmethod
    def _file_created_time(file_stat) -> tuple[float, str]:
        birth_time = getattr(file_stat, "st_birthtime", None)
        if birth_time is not None:
            return float(birth_time), "filesystem_birthtime"
        return float(file_stat.st_ctime), "ctime_fallback_not_guaranteed_creation_time"

    def _run_test_suggestion(self, normalized_name: str) -> str:
        return (
            f'Rerun the failing case alone with RunTestCases(target="<test-file>::'
            f'{normalized_name}") relative to the configured TC output directory and '
            "confirm the DUT fixture calls SetWaveform and "
            "dut.Finish() completes."
        )

    def _error(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        suggestions: list[str] | None = None,
    ) -> OrderedDict:
        result = OrderedDict()
        result["success"] = False
        result["status"] = code
        result["error"] = message
        if details:
            result["details"] = details
        if suggestions:
            result["suggestions"] = suggestions
        return result

    def _inventory(self, max_files: int, file_offset: int) -> OrderedDict:
        """List filesystem metadata for waveforms in the newest test session."""

        test_dir = Path(self.test_dir)
        data_dir = test_dir / "data"
        suggestions = [
            "Run at least one target test with RunTestCases so a current waveform session is created.",
            "Confirm the DUT fixture calls SetWaveform and dut.Finish() completes.",
            "After choosing a test from this list, call WaveInfo(test_case_name=...) to inspect steps and signals.",
        ]
        if not test_dir.is_dir():
            return self._error(
                "test_directory_missing",
                "The configured UnityChip test directory does not exist.",
                details={
                    "configured_test_directory": self._display_path(test_dir),
                    "expected_data_directory": self._display_path(data_dir),
                },
                suggestions=suggestions,
            )
        if not data_dir.is_dir():
            return self._error(
                "waveform_data_directory_missing",
                "No test data directory was found; no waveform inventory is available.",
                details={"searched_directory": self._display_path(data_dir)},
                suggestions=suggestions,
            )

        sessions = self._valid_sessions(data_dir)
        if not sessions:
            return self._error(
                "waveform_session_missing",
                "The test data directory contains no valid toffee_tmp_* session.",
                details={
                    "searched_directory": self._display_path(data_dir),
                    "expected_session_format": "toffee_tmp_YYYYMMDDHHMMSS_mmm",
                },
                suggestions=suggestions,
            )

        latest = sessions[0]
        observed_at = time.time()
        waveform_paths = sorted(
            (
                path
                for path in latest.rglob("*")
                if path.is_file() and path.suffix.lower() in {".fst", ".vcd"}
            ),
            key=lambda path: (path.stat().st_mtime_ns, str(path)),
            reverse=True,
        )
        format_counts: dict[str, int] = {}
        worker_counts: dict[str, int] = {}
        total_size_bytes = 0
        empty_file_count = 0
        file_entries = []
        for file_index, waveform in enumerate(waveform_paths):
            file_stat = waveform.stat()
            file_format = waveform.suffix.lower().lstrip(".")
            try:
                worker = str(waveform.parent.relative_to(latest)) or "."
            except ValueError:
                worker = waveform.parent.name
            format_counts[file_format] = format_counts.get(file_format, 0) + 1
            worker_counts[worker] = worker_counts.get(worker, 0) + 1
            total_size_bytes += file_stat.st_size
            if file_stat.st_size == 0:
                empty_file_count += 1
            if not file_offset <= file_index < file_offset + max_files:
                continue
            created_timestamp, creation_source = self._file_created_time(file_stat)
            display_path = self._display_path(waveform)
            file_entries.append(
                OrderedDict(
                    [
                        ("file_name", waveform.name),
                        ("test_case_name_hint", waveform.stem),
                        ("waveform_file", display_path),
                        ("format", file_format),
                        ("worker", worker),
                        ("size_bytes", file_stat.st_size),
                        ("is_empty", file_stat.st_size == 0),
                        ("created_at", self._format_time(created_timestamp)),
                        ("creation_time_source", creation_source),
                        ("modified_at", self._format_time(file_stat.st_mtime)),
                        ("modified_time_ns", file_stat.st_mtime_ns),
                        (
                            "age_seconds_at_observation",
                            max(0, round(observed_at - file_stat.st_mtime, 3)),
                        ),
                        (
                            "freshness_identity",
                            f"{display_path}:{file_stat.st_size}:{file_stat.st_mtime_ns}",
                        ),
                    ]
                )
            )

        latest_stat = latest.stat()
        dat_file_count = sum(
            1 for path in latest.rglob("*.dat") if path.is_file()
        )
        has_more = file_offset + len(file_entries) < len(waveform_paths)
        recommended_path = (
            waveform_paths[file_offset]
            if file_offset < len(waveform_paths)
            else (waveform_paths[0] if waveform_paths else None)
        )
        recommended_call = (
            OrderedDict(
                [
                    ("test_case_name", recommended_path.stem),
                    ("pattern", []),
                ]
            )
            if recommended_path is not None
            else None
        )
        result = OrderedDict(
            [
                ("success", True),
                (
                    "status",
                    "waveform_inventory" if waveform_paths else "waveform_inventory_empty",
                ),
                ("inventory_scope", "newest_session_only"),
                ("test_directory", self._display_path(test_dir)),
                ("data_directory", self._display_path(data_dir)),
                ("latest_session", self._display_path(latest)),
                ("session_started_at", self._session_started_at(latest)),
                ("latest_session_modified_at", self._format_time(latest_stat.st_mtime)),
                ("observed_at", self._format_time(observed_at)),
                ("available_session_count", len(sessions)),
                ("waveform_file_count", len(waveform_paths)),
                ("waveform_files_shown", len(file_entries)),
                ("waveform_files_offset", file_offset),
                (
                    "waveform_files_truncated",
                    file_offset > 0 or len(waveform_paths) > len(file_entries),
                ),
                ("has_more", has_more),
                ("next_offset", file_offset + len(file_entries) if has_more else None),
                ("max_files", max_files),
                ("format_counts", OrderedDict(sorted(format_counts.items()))),
                ("worker_counts", OrderedDict(sorted(worker_counts.items()))),
                ("data_file_count", dat_file_count),
                ("empty_waveform_file_count", empty_file_count),
                ("total_waveform_size_bytes", total_size_bytes),
                ("waveform_files", file_entries),
                ("receipt_created", False),
                ("evidence_usable", False),
                ("recommended_call", recommended_call),
                (
                    "next_action",
                    "recommended_call.test_case_name is a waveform-discovery basename "
                    "hint only. To inspect a Bug TC, replace it with the complete target "
                    "pytest node ID copied from <TC-...> after removing only TC-. Do not "
                    "repeat inventory: inventory does not establish source-test identity "
                    "or create Bug-analysis evidence or a receipt.",
                ),
            ]
        )
        if not waveform_paths:
            result["suggestions"] = suggestions
        return result

    def _discover_waveform(
        self, test_case_name: str
    ) -> tuple[_WaveSelection | None, OrderedDict | None]:
        try:
            normalized = self._normalize_test_case_name(test_case_name)
        except ValueError as error:
            return None, self._error(
                "invalid_test_case_name",
                str(error),
                details={"provided_test_case_name": test_case_name},
            )

        test_dir = Path(self.test_dir)
        data_dir = test_dir / "data"
        common_suggestions = [
            self._run_test_suggestion(normalized),
            "Use the exact pytest function/Class/parameterized name; do not use a similar test name.",
            "If the test crashed, fix the crash and rerun so waveform flushing/finalization can complete.",
        ]
        if not test_dir.is_dir():
            return None, self._error(
                "test_directory_missing",
                "The configured UnityChip test directory does not exist.",
                details={
                    "configured_test_directory": self._display_path(test_dir),
                    "expected_data_directory": self._display_path(data_dir),
                    "expected_basename": normalized,
                },
                suggestions=common_suggestions,
            )
        if not data_dir.is_dir():
            return None, self._error(
                "waveform_data_directory_missing",
                "No test data directory was found; the target test may never have run.",
                details={
                    "searched_directory": self._display_path(data_dir),
                    "expected_basename": normalized,
                },
                suggestions=common_suggestions,
            )

        sessions = self._valid_sessions(data_dir)
        if not sessions:
            return None, self._error(
                "waveform_session_missing",
                "The test data directory exists, but it contains no valid toffee_tmp_* session.",
                details={
                    "searched_directory": self._display_path(data_dir),
                    "expected_basename": normalized,
                    "expected_session_format": "toffee_tmp_YYYYMMDDHHMMSS_mmm",
                },
                suggestions=common_suggestions,
            )

        latest = sessions[0]

        def collect_matches(session: Path) -> list[tuple[Path, int]]:
            matches: list[tuple[Path, int]] = []
            for path in session.rglob("*"):
                if not path.is_file():
                    continue
                matched, suffix = self._wave_name_match(path, normalized)
                if matched:
                    matches.append((path, suffix))
            return matches

        latest_matches = collect_matches(latest)
        available_names = sorted(
            {
                path.stem
                for path in latest.rglob("*")
                if path.is_file() and path.suffix.lower() in {".fst", ".vcd"}
            }
        )
        dat_matches = sorted(
            self._display_path(path)
            for path in latest.rglob("*.dat")
            if self._data_name_match(path, normalized)
        )
        old_matches: list[str] = []
        for session in sessions[1:]:
            old_matches.extend(
                self._display_path(path) for path, _suffix in collect_matches(session)
            )
            if len(old_matches) >= 10:
                break
        old_matches = old_matches[:10]

        if not latest_matches:
            close_names = get_close_matches(normalized, available_names, n=8, cutoff=0.45)
            parameterized_names = []
            for available_name in available_names:
                if (
                    available_name.endswith("]")
                    and "[" in available_name
                    and available_name[: available_name.find("[")] == normalized
                ):
                    parameterized_names.append(available_name)
            if dat_matches:
                code = "waveform_missing_but_test_data_exists"
                message = (
                    "Matching .dat test data exists in the latest session, but no waveform "
                    "was generated. SetWaveform may not have been called, waveform creation "
                    "may have failed, or the test may have exited before dut.Finish() flushed it."
                )
            elif old_matches:
                code = "stale_waveform_only"
                message = (
                    "The requested waveform exists only in an older session. It is stale and "
                    "will not be used as evidence for the current run."
                )
            else:
                code = "waveform_not_found_in_latest_session"
                message = (
                    "The latest test session has no waveform for the exact requested test. "
                    "The name may be wrong, the parameterized case may differ, or the target "
                    "test did not run in the latest session."
                )
            return None, self._error(
                code,
                message,
                details={
                    "searched_latest_session": self._display_path(latest),
                    "expected_basename": normalized,
                    "available_latest_session_test_names": available_names[:50],
                    "available_names_truncated": len(available_names) > 50,
                    "close_name_matches": close_names,
                    "parameterized_waveform_names": parameterized_names,
                    "matching_data_files": dat_matches,
                    "stale_waveform_candidates_not_used": old_matches,
                },
                suggestions=(
                    [
                        "The latest session has parameterized waveform basenames for this "
                        "function. These names are hints only: cross-check their parameter "
                        "suffixes against an exact FAILED child in report "
                        "tests.test_case_instances, then pass that full child node to "
                        "WaveInfo. Do not use a basename as a pytest node identity."
                    ]
                    + common_suggestions
                    if parameterized_names
                    else common_suggestions
                ),
            )

        latest_matches.sort(
            key=lambda item: (
                1 if item[0].suffix.lower() == ".fst" else 0,
                item[1],
                item[0].stat().st_mtime,
                str(item[0]),
            ),
            reverse=True,
        )
        waveform, suffix = latest_matches[0]
        try:
            worker = str(waveform.parent.relative_to(latest)) or "."
        except ValueError:
            worker = waveform.parent.name
        return (
            _WaveSelection(
                test_case_name=test_case_name,
                expected_basename=normalized,
                data_dir=data_dir,
                session=latest,
                waveform=waveform,
                suffix=suffix,
                worker=worker,
            ),
            None,
        )

    def _selection_info(self, selection: _WaveSelection) -> OrderedDict:
        waveform_stat = selection.waveform.stat()
        session_stat = selection.session.stat()
        observed_at = time.time()
        return OrderedDict(
            [
                ("requested_test_case", selection.test_case_name),
                ("normalized_test_case", selection.expected_basename),
                ("latest_session", self._display_path(selection.session)),
                ("session_started_at", self._session_started_at(selection.session)),
                ("latest_session_modified_at", self._format_time(session_stat.st_mtime)),
                ("worker", selection.worker),
                ("waveform_file", self._display_path(selection.waveform)),
                ("format", selection.waveform.suffix.lower().lstrip(".")),
                ("numeric_suffix", selection.suffix),
                ("size_bytes", waveform_stat.st_size),
                ("modified_at", self._format_time(waveform_stat.st_mtime)),
                ("modified_time_ns", waveform_stat.st_mtime_ns),
                ("observed_at", self._format_time(observed_at)),
                ("age_seconds_at_observation", max(0, round(observed_at - waveform_stat.st_mtime, 3))),
                (
                    "freshness_identity",
                    f"{self._display_path(selection.waveform)}:{waveform_stat.st_size}:{waveform_stat.st_mtime_ns}",
                ),
                ("is_latest_session", True),
                (
                    "selection_rule",
                    "latest session, FST preference, highest numeric suffix, newest mtime",
                ),
            ]
        )

    def _record_analysis_receipt(
        self,
        invocation: dict[str, Any],
        result: OrderedDict,
        *,
        context_files: dict[str, str] | None = None,
    ) -> OrderedDict:
        try:
            normalized_arguments = self.normalize_analysis_arguments(**invocation)
        except Exception:
            normalized_arguments = copy.deepcopy(invocation)

        canonical_result = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        receipt_id = secrets.token_hex(16)
        recorded_at = self._format_time(time.time())
        event_steps = self._event_steps(result)
        if context_files is None:
            context_files = self._analysis_context_snapshot(normalized_arguments)
        context_fingerprint = self._analysis_context_fingerprint(context_files)
        semantic_fingerprint = self.analysis_semantic_fingerprint(
            invocation,
            result,
            context_fingerprint=context_fingerprint,
        )
        receipt = OrderedDict(
            [
                ("receipt_id", receipt_id),
                ("recorded_at", recorded_at),
                ("scope_identity", self._receipt_scope_identity()),
                ("arguments", normalized_arguments),
                (
                    "result",
                    OrderedDict(
                        [
                            ("success", result.get("success")),
                            ("status", result.get("status")),
                            ("evidence_usable", result.get("evidence_usable")),
                            (
                                "result_fingerprint",
                                hashlib.sha256(canonical_result.encode("utf-8")).hexdigest(),
                            ),
                            ("semantic_fingerprint", semantic_fingerprint),
                            ("analysis_context_fingerprint", context_fingerprint),
                            ("analysis_context_files", copy.deepcopy(context_files)),
                            (
                                "waveform_selection",
                                copy.deepcopy(result.get("waveform_selection")),
                            ),
                            ("waveform_info", copy.deepcopy(result.get("waveform_info"))),
                            ("analysis_window", copy.deepcopy(result.get("analysis_window"))),
                            ("event_summary", copy.deepcopy(result.get("event_summary"))),
                            ("patterns", copy.deepcopy(result.get("patterns"))),
                            ("cycle_alignment", copy.deepcopy(result.get("cycle_alignment"))),
                            ("signal_groups", copy.deepcopy(result.get("signal_groups"))),
                            ("signals", copy.deepcopy(result.get("signals"))),
                            ("event_steps", event_steps),
                            ("timeline", copy.deepcopy(result.get("timeline"))),
                            (
                                "waveform_viewer",
                                copy.deepcopy(result.get("waveform_viewer")),
                            ),
                            (
                                "recommended_evidence_call",
                                copy.deepcopy(result.get("recommended_evidence_call")),
                            ),
                        ]
                    ),
                ),
            ]
        )
        persisted = False
        with self._receipt_store_lock():
            self.analysis_receipts.append(receipt)
            if len(self.analysis_receipts) > self._RECEIPT_LIMIT:
                del self.analysis_receipts[: -self._RECEIPT_LIMIT]
            try:
                self._persist_analysis_receipts()
                persisted = True
            except Exception as error:
                warning(
                    f"WaveInfo receipt '{receipt_id}' is memory-only because persistence failed: {error}"
                )
        return OrderedDict(
            [
                ("receipt_id", receipt_id),
                ("recorded_at", recorded_at),
                ("result_fingerprint", receipt["result"]["result_fingerprint"]),
                ("persistence", "workspace_checkpoint" if persisted else "memory_only"),
                ("reusable_after_restart", persisted),
            ]
        )

    def _analysis_context_paths(self, invocation: dict[str, Any]) -> list[Path]:
        """Return bounded source inputs whose changes require semantic review."""

        workspace = Path(self.workspace).resolve()
        test_root = Path(self.test_dir).resolve()
        test_parent = test_root.parent
        selected: set[Path] = set()

        test_case_name = str(invocation.get("test_case_name") or "")
        file_part = test_case_name.split("::", 1)[0].strip()
        if file_part.endswith(".py"):
            candidate = (workspace / file_part).resolve(strict=False)
            if candidate.is_file():
                selected.add(candidate)

        for root, include_python in ((workspace, False), (test_parent, True)):
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in self._ANALYSIS_CONTEXT_SUFFIXES:
                    continue
                try:
                    relative_parts = path.resolve().relative_to(workspace).parts
                except ValueError:
                    continue
                if any(part in self._ANALYSIS_CONTEXT_EXCLUDED_DIRS for part in relative_parts):
                    continue
                if any(part.startswith("toffee_tmp_") for part in relative_parts):
                    continue
                if path.suffix.lower() == ".py":
                    if not include_python:
                        continue
                    try:
                        path.resolve().relative_to(test_root)
                    except ValueError:
                        pass
                    else:
                        continue
                selected.add(path.resolve())
        return sorted(selected, key=lambda path: path.as_posix())

    def _analysis_context_snapshot(
        self,
        invocation: dict[str, Any],
    ) -> OrderedDict[str, str]:
        """Return signed relative paths and hashes for relevant source context."""

        workspace = Path(self.workspace).resolve()
        snapshot = OrderedDict()
        for path in self._analysis_context_paths(invocation):
            try:
                relative = path.relative_to(workspace).as_posix()
                payload = path.read_bytes()
            except (OSError, ValueError):
                continue
            snapshot[relative] = hashlib.sha256(payload).hexdigest()
        return snapshot

    @staticmethod
    def _analysis_context_fingerprint(context_files: dict[str, str]) -> str:
        """Hash an exact test, driver, and HDL source-context snapshot."""

        canonical = json.dumps(
            context_files,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _semantic_viewer_payload(viewer: object) -> dict[str, Any] | None:
        """Return stable viewer fields that participate in evidence meaning."""

        if not isinstance(viewer, dict):
            return None
        payload = viewer.get("payload")
        if not isinstance(payload, dict):
            return None
        keys = ("v", "test_dir", "test_case", "start", "end", "cursor", "signals")
        return {key: copy.deepcopy(payload.get(key)) for key in keys}

    def analysis_semantic_fingerprint(
        self,
        invocation: dict[str, Any],
        result: dict[str, Any],
        *,
        context_fingerprint: str | None = None,
    ) -> str:
        """Hash stable replay evidence while excluding volatile session metadata."""

        normalized_arguments = self.normalize_analysis_arguments(**invocation)
        semantic_result = OrderedDict(
            [
                ("success", result.get("success")),
                ("status", result.get("status")),
                ("evidence_usable", result.get("evidence_usable")),
                ("waveform_info", copy.deepcopy(result.get("waveform_info"))),
                ("analysis_window", copy.deepcopy(result.get("analysis_window"))),
                ("patterns", copy.deepcopy(result.get("patterns"))),
                ("signal_groups", copy.deepcopy(result.get("signal_groups"))),
                ("signals", copy.deepcopy(result.get("signals"))),
                ("event_summary", copy.deepcopy(result.get("event_summary"))),
                ("timeline", copy.deepcopy(result.get("timeline"))),
                ("cycle_alignment", copy.deepcopy(result.get("cycle_alignment"))),
                (
                    "waveform_viewer",
                    self._semantic_viewer_payload(result.get("waveform_viewer")),
                ),
                (
                    "analysis_context_fingerprint",
                    context_fingerprint
                    if context_fingerprint is not None
                    else self._analysis_context_fingerprint(
                        self._analysis_context_snapshot(invocation)
                    ),
                ),
            ]
        )
        canonical = json.dumps(
            {"arguments": normalized_arguments, "result": semantic_result},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ensure_current_analysis_receipt(
        self,
        invocation: dict[str, Any],
        replay: dict[str, Any],
    ) -> OrderedDict:
        """Return one persisted receipt for the exact current replay result."""

        with self._receipt_store_lock():
            return self._ensure_current_analysis_receipt_unlocked(invocation, replay)

    def _ensure_current_analysis_receipt_unlocked(
        self,
        invocation: dict[str, Any],
        replay: dict[str, Any],
    ) -> OrderedDict:

        normalized_arguments = self.normalize_analysis_arguments(**invocation)
        context_files = self._analysis_context_snapshot(normalized_arguments)
        context_fingerprint = self._analysis_context_fingerprint(context_files)
        semantic_fingerprint = self.analysis_semantic_fingerprint(
            normalized_arguments,
            replay,
            context_fingerprint=context_fingerprint,
        )
        selection = replay.get("waveform_selection") or {}
        freshness_identity = selection.get("freshness_identity")
        persisted_receipt_ids: set[str] = set()
        try:
            persisted = self._load_persisted_receipts()
            persisted_receipt_ids = {
                receipt["receipt_id"]
                for receipt in persisted
                if isinstance(receipt.get("receipt_id"), str)
            }
            self.analysis_receipts = self._merge_receipts(
                self.analysis_receipts,
                persisted,
            )
        except Exception as error:
            warning(f"Could not refresh persisted WaveInfo receipts: {error}")

        for receipt in reversed(self.analysis_receipts):
            receipt_result = receipt.get("result") or {}
            receipt_selection = receipt_result.get("waveform_selection") or {}
            if (
                receipt.get("receipt_id") in persisted_receipt_ids
                and receipt.get("arguments") == normalized_arguments
                and receipt_result.get("semantic_fingerprint") == semantic_fingerprint
                and receipt_selection.get("freshness_identity") == freshness_identity
            ):
                result = copy.deepcopy(replay)
                receipt_info = OrderedDict(
                    [
                        ("receipt_id", receipt.get("receipt_id")),
                        ("recorded_at", receipt.get("recorded_at")),
                        ("result_fingerprint", receipt_result.get("result_fingerprint")),
                        ("persistence", "workspace_checkpoint"),
                        ("reusable_after_restart", True),
                    ]
                )
                result["waveform_analysis_receipt"] = receipt_info
                self._attach_bug_document_fields(result, normalized_arguments, receipt_info)
                return result

        result = copy.deepcopy(replay)
        receipt_info = self._record_analysis_receipt(
            normalized_arguments,
            result,
            context_files=context_files,
        )
        result["waveform_analysis_receipt"] = receipt_info
        self._attach_bug_document_fields(result, normalized_arguments, receipt_info)
        return result

    def get_analysis_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """Return a verified receipt from memory or the signed checkpoint store."""

        with self._receipt_store_lock():
            return self._get_analysis_receipt_unlocked(receipt_id)

    def _get_analysis_receipt_unlocked(
        self,
        receipt_id: str,
    ) -> dict[str, Any] | None:

        for receipt in reversed(self.analysis_receipts):
            if receipt.get("receipt_id") == receipt_id:
                return copy.deepcopy(receipt)
        try:
            persisted = self._load_persisted_receipts()
        except Exception as error:
            warning(f"Could not reload persisted WaveInfo receipts: {error}")
            return None
        self.analysis_receipts = self._merge_receipts(
            self.analysis_receipts,
            persisted,
        )
        for receipt in reversed(self.analysis_receipts):
            if receipt.get("receipt_id") == receipt_id:
                return copy.deepcopy(receipt)
        return None

    def get_bug_document_evidence(self, receipt_id: str) -> OrderedDict:
        """Rebuild canonical document fields from one verified final receipt."""

        receipt = self.get_analysis_receipt(receipt_id)
        if receipt is None:
            return self._error(
                "receipt_not_found",
                f"WaveInfo receipt '{receipt_id}' was not found in memory or the signed "
                "workspace receipt store.",
                suggestions=[
                    "Use the receipt_id returned by the final WaveInfo call in this workspace.",
                    "If the waveform changed or the receipt is unavailable, rerun the failing test and final WaveInfo analysis.",
                ],
            )

        receipt_result = copy.deepcopy(receipt.get("result") or {})
        receipt_arguments = copy.deepcopy(receipt.get("arguments") or {})
        receipt_info = {
            "receipt_id": receipt.get("receipt_id"),
            "recorded_at": receipt.get("recorded_at"),
            "result_fingerprint": receipt_result.get("result_fingerprint"),
        }
        self._attach_bug_document_fields(
            receipt_result,
            receipt_arguments,
            receipt_info,
        )
        fields = receipt_result.get("bug_document_fields")
        viewer_link = receipt_result.get("bug_document_viewer_link")
        if not isinstance(fields, dict) or not isinstance(viewer_link, str):
            return self._error(
                "receipt_not_final_evidence",
                f"WaveInfo receipt '{receipt_id}' cannot produce a canonical Bug-document "
                "block. It is exploratory, unusable, or lacks complete signal_groups/viewer data.",
                details={
                    "receipt_status": receipt_result.get("status"),
                    "evidence_usable": receipt_result.get("evidence_usable"),
                    "test_case_name": receipt_arguments.get("test_case_name"),
                },
                suggestions=[
                    "Call WaveInfo with a reproducible explicit window or clock alignment and complete signal_groups.",
                    "Use the new final call's receipt_id with ApplyWaveInfoEvidence.",
                ],
            )
        return OrderedDict(
            [
                ("success", True),
                ("status", "document_evidence_ready"),
                ("receipt_id", receipt_id),
                ("test_case_name", receipt_arguments.get("test_case_name")),
                ("bug_document_fields", fields),
                ("bug_document_viewer_link", viewer_link),
                (
                    "bug_document_completion_required",
                    list(WAVEFORM_LLM_ANALYSIS_FIELDS),
                ),
            ]
        )

    @staticmethod
    def normalize_analysis_arguments(**arguments: Any) -> dict[str, Any]:
        """Return canonical optional arguments used by receipts and checker replay."""

        return WaveInfoAnalysisArgs(**arguments).model_dump(mode="json")

    @staticmethod
    def _mcp_pattern_entries(
        patterns: list[WaveSignalPattern] | None,
    ) -> list[OrderedDict]:
        """Return patterns in the non-nullable shape accepted by the MCP tool."""

        entries = []
        for item in patterns or []:
            entries.append(
                OrderedDict(
                    [
                        ("signal", item.signal),
                        ("event", item.event),
                        (
                            "value",
                            "" if item.value is None else str(item.value),
                        ),
                    ]
                )
            )
        return entries

    @staticmethod
    def _document_pattern_entries(
        patterns: list[dict[str, Any]] | None,
    ) -> list[OrderedDict]:
        """Return the concise pattern shape used in Bug-analysis YAML blocks."""

        entries = []
        for item in patterns or []:
            entry = OrderedDict(
                [
                    ("signal", item.get("signal")),
                    ("event", item.get("event")),
                ]
            )
            if item.get("value") is not None:
                entry["value"] = item.get("value")
            entries.append(entry)
        return entries

    @staticmethod
    def _mcp_signal_groups(
        signal_groups: WaveSignalGroups | dict[str, Any] | None,
    ) -> OrderedDict:
        """Return signal roles in the non-nullable shape accepted by the MCP tool."""

        if not signal_groups:
            model = WaveSignalGroups()
        elif isinstance(signal_groups, WaveSignalGroups):
            model = signal_groups
        else:
            model = WaveSignalGroups(**signal_groups)
        return OrderedDict(
            [("clock_mode", model.clock_mode)]
            + [(field, list(getattr(model, field))) for field in WAVEFORM_SIGNAL_GROUP_FIELDS]
        )

    @staticmethod
    def _event_steps(result: dict[str, Any]) -> list[int]:
        timeline = result.get("timeline") or {}
        return [
            int(wave_step)
            for wave_step, entry in timeline.items()
            if isinstance(entry, dict) and entry.get("triggers")
        ]

    def _attach_bug_document_fields(
        self,
        result: OrderedDict,
        invocation: dict[str, Any],
        receipt_info: dict[str, Any],
    ) -> None:
        """Expose receipt-backed fields without fabricating the LLM's conclusions."""

        if result.get("evidence_usable") is not True:
            return
        selection = result.get("waveform_selection")
        if not isinstance(selection, dict):
            return
        signal_groups = result.get("signal_groups")
        viewer = result.get("waveform_viewer")
        if not isinstance(signal_groups, dict) or not isinstance(viewer, dict):
            result["bug_document_signal_groups_required"] = (
                "Call final WaveInfo again with signal_groups containing the DUT clock mode, "
                "relevant inputs, relevant outputs, protocol controls, and function-specific "
                "key signals. Then use the new receipt_id with ApplyWaveInfoEvidence."
            )
            return

        fields = OrderedDict(
            [
                ("status", "confirmed"),
                ("receipt_id", receipt_info.get("receipt_id")),
                ("result_fingerprint", receipt_info.get("result_fingerprint")),
                ("executed_test_case", invocation.get("test_case_name")),
            ]
        )
        for key in (
            "waveform_file",
            "freshness_identity",
            "size_bytes",
            "session_started_at",
            "modified_at",
            "modified_time_ns",
            "observed_at",
        ):
            fields[key] = selection.get(key)
        fields["pattern"] = self._document_pattern_entries(invocation.get("pattern"))
        fields["signal_groups"] = copy.deepcopy(signal_groups)

        if invocation.get("logged_cycle") is not None:
            candidate = (result.get("cycle_alignment") or {}).get("selected_candidate") or {}
            fields["analysis_mode"] = "clock_aligned"
            for key in (
                "logged_cycle",
                "cycle_tolerance",
                "clock_signal",
                "clock_edge",
                "cycle_origin",
                "context_steps",
                "max_points",
            ):
                fields[key] = invocation.get(key)
            for key in ("clock_occurrence_index", "cycle_delta", "wave_step"):
                fields[key] = candidate.get(key)
        else:
            event_steps = self._event_steps(result)
            if not event_steps:
                event_steps = [
                    int(step)
                    for step in result.get("event_steps", [])
                    if isinstance(step, int) and step >= 0
                ]
            fields["analysis_mode"] = "explicit_window"
            for key in ("start_step", "end_step", "context_steps", "max_points"):
                fields[key] = invocation.get(key)
            fields["wave_step"] = event_steps[0] if event_steps else None
        fields["timeline_truncated"] = False

        result["bug_document_fields"] = OrderedDict(
            [("waveform_analysis", fields)]
        )
        result["bug_document_completion_required"] = list(
            WAVEFORM_LLM_ANALYSIS_FIELDS
        )
        if isinstance(viewer, dict) and isinstance(viewer.get("url"), str):
            result["bug_document_viewer_link"] = build_waveform_viewer_markdown_link(
                viewer["payload"]
            )
        result["bug_document_note"] = (
            "Call ApplyWaveInfoEvidence with this receipt_id. It creates the BG-side "
            "WAVEFORM-REF and the TC's single central WAVEFORM-TC record; do not copy or edit "
            "receipt-backed fields or the WAVEFORM-VIEWER token. Complete alignment_evidence "
            "once for the TC, then complete required_signals, observed_behavior, and "
            "source_correlation under bug_evidence for every associated BG. Before completing "
            "those fields, inspect the specification and test-driver/API Step ordering, "
            "confirm that signal_groups includes the relevant DUT inputs and outputs, the DUT "
            "clock for a clocked design, every acceptance/validity control used by the actual "
            "protocol, and at least one function-specific selector, state, flag, or internal "
            "propagation signal. The online viewer must show the same signed signal set. "
            "Then prove the request acceptance condition, response-valid sampling point, "
            "backpressure/latency, and transaction identity. Ready/valid is only one possible "
            "protocol; use the DUT's actual equivalent conditions. A single Step is not proof "
            "that an output is valid: inspect whether the API already advances or waits, and "
            "the required edge, cycle count, valid/done, handshake, or busy-clear condition. "
            "A value mismatch while the transaction or response is invalid is only an "
            "investigation clue, not Bug proof. Keep YAML and the viewer only in the central "
            "WAVEFORM-TC record. Do not copy analysis_window.effective_* as requested call "
            "arguments."
        )

    def _attach_waveform_viewer(
        self,
        result: OrderedDict,
    ) -> None:
        """Attach a canonical viewer payload only to reproducible final evidence."""

        if result.get("evidence_usable") is not True:
            return
        signal_groups = result.get("signal_groups")
        if not isinstance(signal_groups, dict):
            result["waveform_viewer_error"] = (
                "Final Bug evidence requires complete signal_groups before an online viewer "
                "link can be generated."
            )
            result["waveform_viewer_suggestion"] = (
                "Inspect the DUT ports, test driver/API, specification, and relevant RTL; "
                "then call WaveInfo again with exact paths for the DUT clock mode, relevant "
                "inputs, outputs, protocol controls, and function-specific key signals."
            )
            return
        selection = result.get("waveform_selection") or {}
        window = result.get("analysis_window") or {}
        alignment = result.get("cycle_alignment") or {}
        selected_candidate = alignment.get("selected_candidate") or {}
        event_steps = self._event_steps(result)
        cursor = selected_candidate.get("wave_step")
        if cursor is None and event_steps:
            cursor = event_steps[0]

        signals = []
        resolved_clock = (alignment.get("clock") or {}).get("signal")
        if isinstance(resolved_clock, str) and resolved_clock:
            signals.append(resolved_clock)
        for field_name in WAVEFORM_SIGNAL_GROUP_FIELDS:
            for signal in signal_groups.get(field_name) or []:
                if signal not in signals:
                    signals.append(signal)
        for signal in (result.get("signals") or {}):
            if signal not in signals:
                signals.append(signal)

        try:
            workspace = Path(self.workspace).resolve()
            test_dir = Path(self.test_dir).resolve()
            try:
                relative_test_dir = test_dir.relative_to(workspace)
            except ValueError as error:
                raise WaveformViewerProtocolError(
                    "test directory must be workspace-relative"
                ) from error
            waveform_file = selection.get("waveform_file")
            if not isinstance(waveform_file, str) or not waveform_file:
                raise WaveformViewerProtocolError(
                    "waveform evidence source must be workspace-relative"
                )
            waveform_path = Path(waveform_file)
            if not waveform_path.is_absolute():
                waveform_path = workspace / waveform_path
            try:
                waveform_path.resolve().relative_to(workspace)
            except ValueError as error:
                raise WaveformViewerProtocolError(
                    "waveform evidence source must be workspace-relative"
                ) from error
            payload = normalize_waveform_viewer_payload(
                OrderedDict(
                    [
                        ("v", 2),
                        ("test_dir", relative_test_dir.as_posix() or "."),
                        ("test_case", selection.get("normalized_test_case")),
                        ("start", str(window.get("effective_start_step"))),
                        ("end", str(window.get("effective_end_step"))),
                        ("cursor", str(cursor)),
                        ("signals", signals),
                    ]
                )
            )
        except WaveformViewerProtocolError as error:
            result["waveform_viewer_error"] = str(error)
            if "workspace-relative" in str(error):
                result["waveform_viewer_suggestion"] = (
                    "Generate the failing test waveform inside the current UCAgent workspace, "
                    "rerun the test, and call WaveInfo again."
                )
            else:
                result["waveform_viewer_suggestion"] = (
                    "Narrow the WaveInfo signal patterns to at most 64 actual signals and "
                    "ensure the final window contains a real triggered event, then call "
                    "WaveInfo again."
                )
            return
        result["waveform_viewer"] = OrderedDict(
            [
                ("payload", payload),
                ("url", build_waveform_viewer_url(payload)),
            ]
        )

    @staticmethod
    def _load_trace(
        reader: Any,
        signal: Any,
        begin_step: int | None = None,
        end_step: int | None = None,
    ) -> _SignalTrace:
        loader = getattr(reader, "_load_value_changes", None)
        if loader is None:
            raise RuntimeError(
                "wavekit reader does not provide raw value-change loading; install wavekit 0.7.x"
            )
        # Include a state before the requested window so transitions at its first
        # timestamp can be evaluated. wavekit retains the latest earlier state.
        load_begin = None if begin_step is None else max(0, begin_step - 1)
        load_end = None if end_step is None else end_step + 1
        values = loader(
            signal,
            {"0": 0, "1": 1, "x": 0, "z": 0},
            begin_time=load_begin,
            end_time=load_end,
        )
        x_masks = loader(
            signal,
            {"0": 0, "1": 0, "x": 1, "z": 0},
            begin_time=load_begin,
            end_time=load_end,
        )
        z_masks = loader(
            signal,
            {"0": 0, "1": 0, "x": 0, "z": 1},
            begin_time=load_begin,
            end_time=load_end,
        )

        def as_mapping(array: Any) -> dict[int, int]:
            return {int(row[0]): int(row[1]) for row in array}

        value_by_step = as_mapping(values)
        x_by_step = as_mapping(x_masks)
        z_by_step = as_mapping(z_masks)
        wave_steps = sorted(set(value_by_step) | set(x_by_step) | set(z_by_step))
        states = [
            _ValueState(
                wave_step=wave_step,
                value=value_by_step.get(wave_step, 0),
                x_mask=x_by_step.get(wave_step, 0),
                z_mask=z_by_step.get(wave_step, 0),
            )
            for wave_step in wave_steps
        ]
        return _SignalTrace(name=signal.full_name, width=int(signal.width), states=states)

    @staticmethod
    def _parse_value(value: int | str, width: int) -> int:
        if isinstance(value, bool):
            parsed = int(value)
        elif isinstance(value, int):
            parsed = value
        else:
            text = value.strip().replace("_", "")
            verilog = re.fullmatch(r"(?:(\d+))?'([hHbBdD])([0-9a-fA-F]+)", text)
            if verilog:
                literal_width, base_code, digits = verilog.groups()
                base = {"h": 16, "b": 2, "d": 10}[base_code.lower()]
                parsed = int(digits, base)
                if literal_width is not None and int(literal_width) != width:
                    raise ValueError(
                        f"literal width {literal_width} does not match signal width {width}"
                    )
            elif re.fullmatch(r"\d+", text):
                parsed = int(text, 10)
            else:
                parsed = int(text, 0)
        if parsed < 0 or parsed >= (1 << width):
            raise ValueError(f"value {parsed} does not fit unsigned {width}-bit signal")
        return parsed

    @staticmethod
    def _format_state(state: _ValueState | None, width: int) -> str:
        if state is None:
            return "unavailable"
        if state.x_mask or state.z_mask:
            bits: list[str] = []
            for bit in range(width - 1, -1, -1):
                mask = 1 << bit
                if state.x_mask & mask:
                    bits.append("x")
                elif state.z_mask & mask:
                    bits.append("z")
                else:
                    bits.append("1" if state.value & mask else "0")
            return f"{width}'b{''.join(bits)}"
        if width == 1:
            return f"1'b{state.value}"
        return f"{width}'h{state.value:x}"

    @staticmethod
    def _is_event(
        event: WaveEvent,
        previous: _ValueState | None,
        current: _ValueState,
        equals_value: int | None,
        width: int,
    ) -> bool:
        current_unknown = bool(current.x_mask or current.z_mask)
        previous_unknown = bool(
            previous is not None and (previous.x_mask or previous.z_mask)
        )
        if event == "unknown":
            return current_unknown
        if previous is None:
            return False
        if event == "change":
            return (
                previous.value,
                previous.x_mask,
                previous.z_mask,
            ) != (current.value, current.x_mask, current.z_mask)
        if event in {"rising", "falling"}:
            if width != 1:
                raise ValueError(f"event='{event}' requires a one-bit signal")
            if current_unknown or previous_unknown:
                return False
            if event == "rising":
                return previous.value == 0 and current.value == 1
            return previous.value == 1 and current.value == 0
        assert event == "equals" and equals_value is not None
        return (
            not current_unknown
            and current.value == equals_value
            and (previous_unknown or previous.value != equals_value)
        )

    @staticmethod
    def _clock_edges(trace: _SignalTrace, edge: ClockEdge) -> list[tuple[int, int]]:
        events: list[tuple[int, int]] = []
        for index, current in enumerate(trace.states):
            previous = trace.states[index - 1] if index else None
            if WaveInfo._is_event(edge, previous, current, None, trace.width):
                events.append((len(events), current.wave_step))
        return events

    @staticmethod
    def _clock_candidates(signals: list[Any]) -> list[str]:
        candidates = []
        for signal in signals:
            base = signal.base_name.lower()
            if int(signal.width) == 1 and (
                base in {"clk", "clock"}
                or base.endswith("_clk")
                or base.startswith("clk_")
                or "clock" in base
            ):
                candidates.append(signal.full_name)
        return sorted(candidates)

    @staticmethod
    def _nearest_clock_index(wave_step: int, candidates: list[tuple[int, int]]) -> int:
        times = [item[1] for item in candidates]
        pos = bisect_left(times, wave_step)
        if pos == 0:
            return 0
        if pos == len(times):
            return len(times) - 1
        before = pos - 1
        return before if wave_step - times[before] <= times[pos] - wave_step else pos

    def _analyze(
        self,
        reader: Any,
        selection: _WaveSelection,
        patterns: list[WaveSignalPattern] | None,
        signal_groups: WaveSignalGroups | None,
        logged_cycle: int | None,
        cycle_tolerance: int,
        clock_signal: str | None,
        clock_edge: ClockEdge,
        cycle_origin: int,
        start_step: int | None,
        end_step: int | None,
        context_steps: int,
        max_signals: int,
        max_points: int,
    ) -> OrderedDict:
        first_step = int(reader.begin_time)
        last_step = int(reader.end_time)
        if last_step < first_step:
            return self._error(
                "invalid_waveform_time_range",
                "wavekit reported an invalid waveform time range.",
                details={"first_wave_step": first_step, "last_wave_step": last_step},
            )

        all_signals = sorted(
            reader.get_matched_signals("**").values(), key=lambda signal: signal.full_name
        )
        if not all_signals:
            return self._error(
                "waveform_has_no_signals",
                "The waveform opened successfully but contains no signals.",
                details={"waveform_file": self._display_path(selection.waveform)},
                suggestions=[
                    "Check simulator dump configuration and rerun the failing test.",
                ],
            )

        top_scopes = [scope.full_name for scope in reader.top_scopes]
        selection_info = self._selection_info(selection)
        basic_info = OrderedDict(
            [
                ("step_basis", "wavekit_simulation_timestamp"),
                ("first_wave_step", first_step),
                ("last_wave_step", last_step),
                ("wave_step_span", last_step - first_step + 1),
                ("wave_step_count", last_step - first_step + 1),
                ("wave_step_is_dut_cycle", False),
                ("signal_count", len(all_signals)),
                ("top_scopes", top_scopes),
            ]
        )

        if logged_cycle is not None and not clock_signal:
            return OrderedDict(
                [
                    ("success", False),
                    ("status", "clock_required"),
                    ("waveform_selection", selection_info),
                    ("waveform_info", basic_info),
                    (
                        "cycle_alignment",
                        OrderedDict(
                            [
                                ("logged_cycle", logged_cycle),
                                ("cycle_tolerance", cycle_tolerance),
                                ("status", "clock_required"),
                                ("candidate_clock_signals", self._clock_candidates(all_signals)),
                                (
                                    "reason",
                                    "logged_cycle cannot be compared directly with a wavekit timestamp",
                                ),
                            ]
                        ),
                    ),
                    (
                        "suggestions",
                        [
                            "Call WaveInfo again with the exact one-bit clock_signal and correct clock_edge.",
                            "Confirm whether the logged cycle counter starts before or after reset and whether it advances before drive or after sample.",
                            "Log cycle_basis, transaction ID, relevant inputs/outputs, valid/ready, state, expected, and actual values when rerunning the failing test.",
                        ],
                    ),
                ]
            )

        clock_trace: _SignalTrace | None = None
        clock_edges: list[tuple[int, int]] = []
        resolved_clock: Any | None = None
        if clock_signal:
            try:
                clock_matches = list(reader.get_matched_signals(clock_signal).values())
            except Exception as error:
                return self._error(
                    "invalid_clock_query",
                    f"wavekit rejected clock_signal: {error}",
                    details={
                        "clock_signal": clock_signal,
                        "candidate_clock_signals": self._clock_candidates(all_signals),
                    },
                )
            if len(clock_matches) != 1:
                return self._error(
                    "clock_signal_not_unique",
                    "clock_signal must match exactly one signal.",
                    details={
                        "clock_signal": clock_signal,
                        "matched_clock_signals": [signal.full_name for signal in clock_matches],
                        "candidate_clock_signals": self._clock_candidates(all_signals),
                    },
                    suggestions=["Use a fully-qualified exact clock path."],
                )
            resolved_clock = clock_matches[0]
            if int(resolved_clock.width) != 1:
                return self._error(
                    "invalid_clock_width",
                    "clock_signal must be one bit wide.",
                    details={
                        "clock_signal": resolved_clock.full_name,
                        "width": int(resolved_clock.width),
                    },
                )
            clock_trace = self._load_trace(reader, resolved_clock)
            clock_edges = self._clock_edges(clock_trace, clock_edge)
            if not clock_edges:
                return self._error(
                    "clock_edges_not_found",
                    f"No valid {clock_edge} edges were found in clock_signal.",
                    details={"clock_signal": resolved_clock.full_name},
                    suggestions=[
                        "Check clock_edge, reset behavior, waveform completeness, and X/Z clock values."
                    ],
                )

        explicit_window = start_step is not None or end_step is not None
        requested_start = start_step
        requested_end = end_step
        effective_start = first_step if start_step is None else max(first_step, start_step)
        effective_end = last_step if end_step is None else min(last_step, end_step)
        cycle_window_clamped = False
        requested_occurrence_range: tuple[int, int] | None = None

        if logged_cycle is not None and clock_edges and not explicit_window:
            target_occurrence = cycle_origin + logged_cycle
            requested_low = target_occurrence - cycle_tolerance
            requested_high = target_occurrence + cycle_tolerance
            requested_occurrence_range = (requested_low, requested_high)
            low = max(0, requested_low)
            high = min(len(clock_edges) - 1, requested_high)
            cycle_window_clamped = low != requested_low or high != requested_high
            if low > high:
                effective_start = first_step
                effective_end = last_step
            else:
                context_low = max(0, low - context_steps)
                context_high = min(len(clock_edges) - 1, high + context_steps)
                effective_start = clock_edges[context_low][1]
                effective_end = clock_edges[context_high][1]

        if effective_start > effective_end:
            return self._error(
                "wave_window_out_of_range",
                "The requested wave-step window does not overlap this waveform.",
                details={
                    "requested_start_step": requested_start,
                    "requested_end_step": requested_end,
                    "first_wave_step": first_step,
                    "last_wave_step": last_step,
                },
            )

        if not patterns:
            catalog = OrderedDict()
            for signal in all_signals[:max_signals]:
                catalog[signal.full_name] = OrderedDict([("width", int(signal.width))])
            result = OrderedDict(
                [
                    ("success", True),
                    ("status", "metadata_only"),
                    ("waveform_selection", selection_info),
                    ("waveform_info", basic_info),
                    (
                        "signal_catalog",
                        OrderedDict(
                            [
                                ("signals", catalog),
                                ("shown", len(catalog)),
                                ("total", len(all_signals)),
                                ("truncated", len(all_signals) > len(catalog)),
                            ]
                        ),
                    ),
                ]
            )
            if logged_cycle is not None and clock_edges:
                result["cycle_alignment"] = self._build_cycle_alignment(
                    logged_cycle,
                    cycle_tolerance,
                    cycle_origin,
                    clock_edge,
                    resolved_clock.full_name,
                    clock_edges,
                    requested_occurrence_range,
                    effective_start,
                    effective_end,
                    explicit_window,
                    cycle_window_clamped,
                    {},
                    {},
                    False,
                )
                result["status"] = "insufficient_anchor"
                result["success"] = False
                result["suggestions"] = [
                    "Provide structured pattern entries for logged inputs, handshakes, state, transaction ID, and relevant output pins.",
                    "Do not infer alignment solely from the nearest clock edge or a zero cycle delta.",
                ]
            return result

        matched_by_name: OrderedDict[str, Any] = OrderedDict()
        pattern_matches: list[tuple[WaveSignalPattern, list[Any]]] = []
        for item in patterns:
            try:
                matches = sorted(
                    reader.get_matched_signals(item.signal).values(),
                    key=lambda signal: signal.full_name,
                )
            except Exception as error:
                return self._error(
                    "invalid_signal_query",
                    f"wavekit rejected signal pattern '{item.signal}': {error}",
                    details={"pattern": item.model_dump()},
                )
            if not matches:
                close_names = get_close_matches(
                    item.signal,
                    [signal.full_name for signal in all_signals],
                    n=10,
                    cutoff=0.3,
                )
                return self._error(
                    "signal_not_found",
                    f"Signal pattern '{item.signal}' matched no waveform signal.",
                    details={
                        "pattern": item.model_dump(),
                        "close_signal_matches": close_names,
                        "top_scopes": top_scopes,
                    },
                    suggestions=[
                        "Call WaveInfo with pattern omitted to inspect the signal catalog, then use a more precise wavekit query."
                    ],
                )
            pattern_matches.append((item, matches))
            for signal in matches:
                matched_by_name.setdefault(signal.full_name, signal)

        resolved_signal_groups: OrderedDict[str, Any] | None = None
        if signal_groups is not None:
            resolved_signal_groups = OrderedDict(
                [("clock_mode", signal_groups.clock_mode)]
                + [(field, []) for field in WAVEFORM_SIGNAL_GROUP_FIELDS]
            )
            all_signal_names = [signal.full_name for signal in all_signals]
            for field_name in WAVEFORM_SIGNAL_GROUP_FIELDS:
                for requested_name in getattr(signal_groups, field_name):
                    try:
                        matches = sorted(
                            reader.get_matched_signals(requested_name).values(),
                            key=lambda signal: signal.full_name,
                        )
                    except Exception as error:
                        return self._error(
                            "invalid_signal_group_path",
                            f"wavekit rejected signal_groups.{field_name} path "
                            f"'{requested_name}': {error}",
                            details={"signal_group": field_name, "signal": requested_name},
                        )
                    if len(matches) != 1 or matches[0].full_name != requested_name:
                        return self._error(
                            "signal_group_path_not_exact",
                            f"signal_groups.{field_name} must use an exact full waveform path.",
                            details={
                                "signal_group": field_name,
                                "requested_signal": requested_name,
                                "matched_signals": [signal.full_name for signal in matches],
                                "close_signal_matches": get_close_matches(
                                    requested_name,
                                    all_signal_names,
                                    n=10,
                                    cutoff=0.3,
                                ),
                            },
                            suggestions=[
                                "Call WaveInfo with pattern and signal_groups omitted to "
                                "inspect the signal catalog, then copy exact full paths."
                            ],
                        )
                    signal = matches[0]
                    if field_name == "clocks" and int(signal.width) != 1:
                        return self._error(
                            "invalid_signal_group_clock_width",
                            "Every signal_groups.clocks entry must be one bit wide.",
                            details={"signal": signal.full_name, "width": int(signal.width)},
                        )
                    resolved_signal_groups[field_name].append(signal.full_name)
                    matched_by_name.setdefault(signal.full_name, signal)

            if resolved_clock is not None:
                if resolved_clock.full_name not in resolved_signal_groups["clocks"]:
                    return self._error(
                        "alignment_clock_missing_from_signal_groups",
                        "The resolved clock_signal must also be listed in signal_groups.clocks.",
                        details={
                            "resolved_clock_signal": resolved_clock.full_name,
                            "signal_group_clocks": resolved_signal_groups["clocks"],
                        },
                    )

        loaded_signal_names = list(matched_by_name)
        if resolved_clock is not None and resolved_clock.full_name not in matched_by_name:
            loaded_signal_names.insert(0, resolved_clock.full_name)
        if len(loaded_signal_names) > max_signals:
            return self._error(
                "signal_limit_exceeded",
                "The combined event and context signals exceed max_signals; analysis was "
                "not truncated silently.",
                details={
                    "matched_signal_count": len(loaded_signal_names),
                    "max_signals": max_signals,
                    "first_matches": loaded_signal_names[:max_signals],
                },
                suggestions=[
                    "Narrow wildcard or regex patterns, keep only relevant role signals, "
                    "or raise max_signals up to 64."
                ],
            )

        traces: OrderedDict[str, _SignalTrace] = OrderedDict()
        if clock_trace is not None:
            traces[clock_trace.name] = clock_trace
        for name, signal in matched_by_name.items():
            if name not in traces:
                traces[name] = self._load_trace(
                    reader, signal, effective_start, effective_end
                )

        trigger_map: dict[int, OrderedDict[str, list[dict[str, Any]]]] = {}
        pattern_report: list[OrderedDict] = []
        for item, matches in pattern_matches:
            report = OrderedDict(
                [
                    ("query", item.signal),
                    ("event", item.event),
                ]
            )
            if item.value is not None:
                report["value"] = item.value
            report["matched_signals"] = [signal.full_name for signal in matches]
            event_count = 0
            for signal in matches:
                trace = traces[signal.full_name]
                try:
                    equals_value = (
                        self._parse_value(item.value, trace.width)
                        if item.event == "equals" and item.value is not None
                        else None
                    )
                except ValueError as error:
                    return self._error(
                        "invalid_pattern_value",
                        f"Invalid equals value for '{signal.full_name}': {error}",
                        details={"pattern": item.model_dump(), "signal_width": trace.width},
                    )
                for index, current in enumerate(trace.states):
                    if current.wave_step < effective_start or current.wave_step > effective_end:
                        continue
                    previous = trace.states[index - 1] if index else None
                    try:
                        matched = self._is_event(
                            item.event, previous, current, equals_value, trace.width
                        )
                    except ValueError as error:
                        return self._error(
                            "invalid_event_for_signal",
                            f"Invalid event for '{signal.full_name}': {error}",
                            details={"pattern": item.model_dump(), "signal_width": trace.width},
                        )
                    if not matched:
                        continue
                    event_data: dict[str, Any] = {"event": item.event}
                    if equals_value is not None:
                        event_data["value"] = self._format_state(current, trace.width)
                    signal_events = trigger_map.setdefault(
                        current.wave_step, OrderedDict()
                    ).setdefault(signal.full_name, [])
                    if event_data not in signal_events:
                        signal_events.append(event_data)
                    event_count += 1
            report["event_count"] = event_count
            pattern_report.append(report)

        event_steps = sorted(trigger_map)
        all_change_steps = sorted(
            {
                state.wave_step
                for trace in traces.values()
                for state in trace.states
                if effective_start <= state.wave_step <= effective_end
            }
        )
        timeline_steps = set(event_steps)
        if context_steps:
            for wave_step in event_steps:
                position = bisect_left(all_change_steps, wave_step)
                low = max(0, position - context_steps)
                high = min(len(all_change_steps), position + context_steps + 1)
                timeline_steps.update(all_change_steps[low:high])
        ordered_timeline_steps = sorted(timeline_steps)
        timeline_truncated = len(ordered_timeline_steps) > max_points
        omitted_points = max(0, len(ordered_timeline_steps) - max_points)
        ordered_timeline_steps = ordered_timeline_steps[:max_points]

        timeline = OrderedDict()
        for wave_step in ordered_timeline_steps:
            entry = OrderedDict()
            if wave_step in trigger_map:
                entry["triggers"] = trigger_map[wave_step]
            values = OrderedDict()
            for name, trace in traces.items():
                values[name] = self._format_state(trace.value_at(wave_step), trace.width)
            entry["values"] = values
            timeline[wave_step] = entry

        signal_report = OrderedDict()
        for name, signal in matched_by_name.items():
            signal_report[name] = OrderedDict(
                [
                    ("width", int(signal.width)),
                    (
                        "value_change_count_in_window",
                        sum(
                            1
                            for state in traces[name].states
                            if effective_start <= state.wave_step <= effective_end
                        ),
                    ),
                ]
            )

        result = OrderedDict(
            [
                ("success", True),
                ("status", "events_found" if event_steps else "no_candidate"),
                ("waveform_selection", selection_info),
                ("waveform_info", basic_info),
                (
                    "analysis_window",
                    OrderedDict(
                        [
                            ("requested_start_step", requested_start),
                            ("requested_end_step", requested_end),
                            ("effective_start_step", effective_start),
                            ("effective_end_step", effective_end),
                            (
                                "clamped_to_waveform",
                                (requested_start is not None and requested_start < first_step)
                                or (requested_end is not None and requested_end > last_step),
                            ),
                        ]
                    ),
                ),
                ("patterns", pattern_report),
                ("signal_groups", resolved_signal_groups),
                ("signals", signal_report),
                (
                    "event_summary",
                    OrderedDict(
                        [
                            ("distinct_event_steps", len(event_steps)),
                            ("distinct_loaded_change_steps", len(all_change_steps)),
                            ("timeline_points_returned", len(timeline)),
                            ("timeline_truncated", timeline_truncated),
                            ("omitted_timeline_points", omitted_points),
                        ]
                    ),
                ),
                ("timeline", timeline),
            ]
        )

        if logged_cycle is not None and clock_edges and resolved_clock is not None:
            alignment = self._build_cycle_alignment(
                logged_cycle,
                cycle_tolerance,
                cycle_origin,
                clock_edge,
                resolved_clock.full_name,
                clock_edges,
                requested_occurrence_range,
                effective_start,
                effective_end,
                explicit_window,
                cycle_window_clamped,
                trigger_map,
                traces,
                True,
            )
            result["cycle_alignment"] = alignment
            result["status"] = alignment["status"]
            result["success"] = alignment["status"] not in {
                "no_candidate",
                "insufficient_anchor",
            }

        if timeline_truncated:
            result["evidence_usable"] = False
            result["evidence_warning"] = (
                "Timeline output was truncated. Narrow the signal patterns or wave-step window "
                "before using this result as final Bug evidence."
            )
        elif result["status"] in {"no_candidate", "insufficient_anchor"}:
            result["evidence_usable"] = False
            result["evidence_warning"] = (
                "No unique cycle anchor was established. Add cycle_basis and relevant pin/state "
                "logs, rerun the failing test, or refine the pattern."
            )
        elif logged_cycle is None and not explicit_window:
            result["status"] = "evidence_window_required"
            result["evidence_usable"] = False
            result["evidence_warning"] = (
                "Events were found during a whole-waveform exploratory search, but the "
                "call did not request a reproducible final-evidence window. Call WaveInfo "
                "again with both start_step and end_step from recommended_evidence_call."
            )
            recommended = OrderedDict(
                [
                    ("test_case_name", selection.test_case_name),
                    ("pattern", self._mcp_pattern_entries(patterns)),
                    ("logged_cycle", -1),
                    ("clock_signal", ""),
                    ("start_step", effective_start),
                    ("end_step", effective_end),
                    ("context_steps", context_steps),
                    ("max_points", max_points),
                ]
            )
            if signal_groups is not None:
                recommended["signal_groups"] = self._mcp_signal_groups(signal_groups)
            result["recommended_evidence_call"] = recommended
            result["next_action"] = (
                "Invoke WaveInfo with recommended_evidence_call exactly, then use the new "
                "receipt and its bug_document_fields. The current receipt is exploratory "
                "and cannot confirm a dynamic Bug."
            )
        else:
            result["evidence_usable"] = True
            result["evidence_warning"] = (
                "WaveInfo found reproducible waveform events, not an automatic DUT Bug. The "
                "LLM must inspect the specification and test-driver/API Step ordering, then "
                "confirm the real request acceptance and response-valid conditions, "
                "including whether one Step is sufficient or the API already steps/waits, "
                "backpressure/latency, transaction identity, failing assertion, and source "
                "root cause. Do not classify a mismatch at an arbitrary or protocol-invalid "
                "timestamp as a Bug."
            )
        return result

    def _build_cycle_alignment(
        self,
        logged_cycle: int,
        cycle_tolerance: int,
        cycle_origin: int,
        clock_edge: ClockEdge,
        clock_name: str,
        clock_edges: list[tuple[int, int]],
        requested_occurrence_range: tuple[int, int] | None,
        effective_start: int,
        effective_end: int,
        explicit_window: bool,
        cycle_window_clamped: bool,
        trigger_map: dict[int, OrderedDict[str, list[dict[str, Any]]]],
        traces: dict[str, _SignalTrace],
        require_trigger: bool,
    ) -> OrderedDict:
        if explicit_window:
            candidates = [
                item for item in clock_edges if effective_start <= item[1] <= effective_end
            ]
        else:
            target = cycle_origin + logged_cycle
            low = target - cycle_tolerance
            high = target + cycle_tolerance
            candidates = [item for item in clock_edges if low <= item[0] <= high]

        candidate_occurrences = {occurrence for occurrence, _step in candidates}
        trigger_counts = {occurrence: 0 for occurrence, _step in candidates}
        trigger_details: dict[int, OrderedDict[str, list[dict[str, Any]]]] = {
            occurrence: OrderedDict() for occurrence, _step in candidates
        }
        if candidates:
            for wave_step, signal_events in trigger_map.items():
                nearest_position = self._nearest_clock_index(wave_step, clock_edges)
                occurrence, _clock_step = clock_edges[nearest_position]
                if occurrence not in candidate_occurrences:
                    continue
                for signal_name, events in signal_events.items():
                    trigger_details[occurrence].setdefault(signal_name, []).extend(events)
                    trigger_counts[occurrence] += len(events)

        event_candidates = [
            item for item in candidates if trigger_counts.get(item[0], 0) > 0
        ]
        if require_trigger:
            reported_candidates = event_candidates
        else:
            reported_candidates = candidates

        reported_candidates.sort(
            key=lambda item: (
                abs((item[0] - cycle_origin) - logged_cycle),
                -trigger_counts.get(item[0], 0),
                item[0],
            )
        )
        candidate_anchors: list[OrderedDict] = []
        for occurrence, wave_step in reported_candidates:
            values = OrderedDict()
            for name, trace in traces.items():
                values[name] = self._format_state(trace.value_at(wave_step), trace.width)
            candidate = OrderedDict(
                [
                    ("clock_occurrence_index", occurrence),
                    ("cycle_delta", (occurrence - cycle_origin) - logged_cycle),
                    ("wave_step", wave_step),
                    ("trigger_count", trigger_counts.get(occurrence, 0)),
                ]
            )
            if trigger_details.get(occurrence):
                candidate["triggers"] = trigger_details[occurrence]
            if values:
                candidate["values"] = values
            candidate_anchors.append(candidate)

        if not reported_candidates:
            status = "no_candidate"
        elif not require_trigger:
            status = "insufficient_anchor"
        else:
            best_count = max(anchor["trigger_count"] for anchor in candidate_anchors)
            tied = [
                anchor for anchor in candidate_anchors if anchor["trigger_count"] == best_count
            ]
            status = "candidate_selected" if len(tied) == 1 else "insufficient_anchor"

        selected_candidate = None
        if status == "candidate_selected":
            selected_candidate = max(
                candidate_anchors,
                key=lambda anchor: anchor["trigger_count"],
            )

        requested_range = requested_occurrence_range
        if requested_range is None:
            requested_range = (
                cycle_origin + logged_cycle - cycle_tolerance,
                cycle_origin + logged_cycle + cycle_tolerance,
            )
        alignment = OrderedDict(
            [
                ("status", status),
                ("confirmed", False),
                ("logged_cycle", logged_cycle),
                ("cycle_tolerance", cycle_tolerance),
                ("cycle_delta_unit", "clock_edges"),
                ("wave_step_unit", "wavekit_simulation_timestamp"),
                (
                    "clock",
                    OrderedDict(
                        [
                            ("signal", clock_name),
                            ("edge", clock_edge),
                            ("source", "explicit"),
                            ("total_occurrences", len(clock_edges)),
                        ]
                    ),
                ),
                (
                    "cycle_basis",
                    OrderedDict(
                        [
                            ("cycle_origin", cycle_origin),
                            ("confirmed", False),
                            (
                                "meaning",
                                "clock occurrence index hypothesized to correspond to logged cycle 0",
                            ),
                        ]
                    ),
                ),
                (
                    "requested_clock_occurrence_range",
                    f"{requested_range[0]}-{requested_range[1]}",
                ),
                (
                    "effective_wave_window",
                    f"{effective_start}-{effective_end}",
                ),
                ("window_source", "explicit_wave_steps" if explicit_window else "logged_cycle"),
                ("window_clamped", cycle_window_clamped),
                ("selected_candidate", selected_candidate),
                ("candidate_anchors", candidate_anchors),
                (
                    "confirmation_required",
                    "Match cycle_basis, reset phase, transaction ID, inputs, handshake/state, "
                    "expected/actual values, and relevant pins. A zero cycle_delta alone is not proof.",
                ),
            ]
        )
        return alignment

    def analyze(
        self,
        test_case_name: str | None = None,
        pattern: list[WaveSignalPattern] | None = None,
        signal_groups: WaveSignalGroups | dict[str, Any] | None = None,
        logged_cycle: int | None = None,
        cycle_tolerance: int = 5,
        clock_signal: str | None = None,
        clock_edge: ClockEdge = "rising",
        cycle_origin: int = 0,
        start_step: int | None = None,
        end_step: int | None = None,
        context_steps: int = 1,
        max_signals: int = 32,
        max_points: int = 200,
        max_files: int = 20,
        file_offset: int = 0,
    ) -> OrderedDict:
        """Return the newest-session inventory or one structured waveform analysis."""

        try:
            args = WaveInfoAnalysisArgs(
                test_case_name=test_case_name,
                pattern=pattern,
                signal_groups=signal_groups,
                logged_cycle=logged_cycle,
                cycle_tolerance=cycle_tolerance,
                clock_signal=clock_signal,
                clock_edge=clock_edge,
                cycle_origin=cycle_origin,
                start_step=start_step,
                end_step=end_step,
                context_steps=context_steps,
                max_signals=max_signals,
                max_points=max_points,
                max_files=max_files,
                file_offset=file_offset,
            )
        except Exception as error:
            return self._error(
                "invalid_arguments", f"Invalid WaveInfo arguments: {error}"
            )

        if args.test_case_name is None:
            return self._inventory(args.max_files, args.file_offset)

        selection, discovery_error = self._discover_waveform(args.test_case_name)
        if discovery_error is not None:
            return discovery_error
        assert selection is not None

        if selection.waveform.stat().st_size == 0:
            return self._error(
                "empty_waveform",
                "The selected waveform file is empty and cannot be analyzed.",
                details={"waveform_selection": self._selection_info(selection)},
                suggestions=[
                    self._run_test_suggestion(selection.expected_basename),
                    "Check whether the test crashed before dut.Finish() or waveform flushing completed.",
                ],
            )

        try:
            wavekit = _import_wavekit()
        except (ImportError, ModuleNotFoundError) as error:
            return self._error(
                "wavekit_unavailable",
                f"The wavekit dependency is unavailable: {error}",
                details={"waveform_selection": self._selection_info(selection)},
                suggestions=[
                    "Install UCAgent project dependencies, including wavekit>=0.7.0,<0.8.0."
                ],
            )

        reader_class = (
            wavekit.FstReader
            if selection.waveform.suffix.lower() == ".fst"
            else wavekit.VcdReader
        )
        try:
            with reader_class(str(selection.waveform)) as reader:
                result = self._analyze(
                    reader,
                    selection,
                    args.pattern,
                    args.signal_groups,
                    args.logged_cycle,
                    args.cycle_tolerance,
                    args.clock_signal,
                    args.clock_edge,
                    args.cycle_origin,
                    args.start_step,
                    args.end_step,
                    args.context_steps,
                    args.max_signals,
                    args.max_points,
                )
        except Exception as error:
            result = self._error(
                "waveform_parse_error",
                f"wavekit could not analyze the selected waveform: {type(error).__name__}: {error}",
                details={"waveform_selection": self._selection_info(selection)},
                suggestions=[
                    self._run_test_suggestion(selection.expected_basename),
                    "Check whether the simulator terminated early, the waveform is corrupt, or dut.Finish() failed to flush it.",
                    "If the failure persists after rerunning, inspect simulator/waveform-generation logs.",
                ],
            )
        self._attach_waveform_viewer(result)
        return result

    def replay_analysis(self, **arguments: Any) -> OrderedDict:
        """Replay signed arguments without creating another receipt."""

        return self.analyze(**arguments)

    def _run(
        self,
        test_case_name: str = "",
        pattern: list[WaveInfoToolPattern] = [],
        signal_groups: WaveSignalGroups = WaveSignalGroups(),
        logged_cycle: int = -1,
        cycle_tolerance: int = 5,
        clock_signal: str = "",
        clock_edge: ClockEdge = "rising",
        cycle_origin: int = 0,
        start_step: int = -1,
        end_step: int = -1,
        context_steps: int = 1,
        max_signals: int = 32,
        max_points: int = 200,
        max_files: int = 20,
        file_offset: int = 0,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        del run_manager
        try:
            tool_args = ArgWaveInfo(
                test_case_name=test_case_name,
                pattern=pattern,
                signal_groups=signal_groups,
                logged_cycle=logged_cycle,
                cycle_tolerance=cycle_tolerance,
                clock_signal=clock_signal,
                clock_edge=clock_edge,
                cycle_origin=cycle_origin,
                start_step=start_step,
                end_step=end_step,
                context_steps=context_steps,
                max_signals=max_signals,
                max_points=max_points,
                max_files=max_files,
                file_offset=file_offset,
            )
        except Exception as error:
            result = self._error(
                "invalid_arguments", f"Invalid WaveInfo arguments: {error}"
            )
            return make_llm_tool_ret(result, check_pass=False)
        invocation = tool_args.analysis_arguments()
        result = self.analyze(**invocation)
        if invocation["test_case_name"] is not None:
            receipt_info = self._record_analysis_receipt(invocation, result)
            result["waveform_analysis_receipt"] = receipt_info
            self._attach_bug_document_fields(result, invocation, receipt_info)
        return make_llm_tool_ret(result, check_pass=False)


@dataclass(frozen=True)
class _DocumentEvidenceTarget:
    """Editable Bug reference and central waveform record locations."""

    test_index: int | None
    test_create_index: int | None
    test_indent: str
    reference_index: int | None
    evidence_end_index: int
    associated_bug_tags: tuple[str, ...]
    test_display_title: str
    record_start: int | None = None
    record_end: int | None = None
    open_index: int | None = None
    close_index: int | None = None


class ApplyWaveInfoEvidence(UCTool):
    """Associate one verified WaveInfo receipt with one dynamic BG/TC."""

    name: str = "ApplyWaveInfoEvidence"
    description: str = (
        "Associate one exact FG/FC/CK/BG/TC path with one signed final WaveInfo receipt. The tool "
        "atomically creates or repairs the BG-side WAVEFORM-REF link and the TC's single "
        "central WAVEFORM-TC record. Reusing the TC for another Bug adds that Bug to bug_tags "
        "and bug_evidence instead of duplicating waveform data; call once for each distinct "
        "bug_tag. The receipt signal_groups "
        "must contain the union of signals required by every associated Bug. Reapplying the "
        "same receipt preserves completed analysis fields. Replacing a different receipt "
        "requires replace_existing=true, preserves required_signals, and resets semantic "
        "conclusions to BUG-TODO. receipt_id may be blank to select the newest matching final "
        "receipt. The BG path entry must already exist; a missing TC is created under the "
        "selected occurrence. Use checkpoint_path when the same BG tag repeats across CKs. "
        "Creating a missing TC reads its visible title from the target test's docstring, so "
        "the test source and a non-empty docstring must exist. "
        "The receipt test_case_name must equal test_case_tag after removing TC-, or be one "
        "parameterized child of the same exact workspace-relative file/class/function. "
        "Path-prefix variants, different classes, and different functions are not equivalent. "
        "On an identity mismatch, keep test_case_tag "
        "unchanged and execute the returned recovery_call instead of guessing another path or "
        "manually writing signed evidence. Similar source files are diagnostic hints only. "
        "The target must be an existing workspace-relative Markdown file inside the configured "
        "write directories."
    )
    args_schema: Optional[ArgsSchema] = ArgApplyWaveInfoEvidence
    return_direct: bool = False

    workspace: str = Field(default=".", description="UCAgent workspace root.")
    write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    un_write_dirs: list[str] | None = Field(default=None, exclude=True, repr=False)
    waveinfo: Any = Field(default=None, exclude=True, repr=False)

    _MAX_DOCUMENT_BYTES: ClassVar[int] = 4 * 1024 * 1024

    def __init__(
        self,
        waveinfo: WaveInfo,
        workspace: str = ".",
        write_dirs: list[str] | None = None,
        un_write_dirs: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.workspace = str(Path(workspace).resolve())
        self.write_dirs = copy.deepcopy(write_dirs)
        self.un_write_dirs = copy.deepcopy(un_write_dirs)
        self.waveinfo = waveinfo
        configured_test_dir = os.path.relpath(
            waveinfo.test_dir, self.workspace
        ).replace(os.sep, "/")
        self.description = (
            f"{self.description} Configured TC output directory for this run: "
            f"'{configured_test_dir}'."
        )

    @staticmethod
    def _is_within(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
        except ValueError:
            return False
        return True

    def _configured_directory(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(self.workspace) / path
        return path.resolve(strict=False)

    def _resolve_target(self, target_file: str) -> tuple[Path | None, str | None]:
        root = Path(self.workspace).resolve()
        requested = Path(target_file)
        if requested.is_absolute():
            return None, "target_file must be relative to the configured workspace"
        lexical_target = root / requested
        if lexical_target.is_symlink():
            return None, "target_file must not be a symbolic link"
        try:
            target = lexical_target.resolve(strict=True)
        except FileNotFoundError:
            return None, f"target_file '{target_file}' does not exist"
        except (OSError, RuntimeError) as error:
            return None, f"target_file '{target_file}' could not be resolved: {error}"
        if not self._is_within(target, root):
            return None, f"target_file '{target_file}' resolves outside the workspace"
        if not target.is_file():
            return None, f"target_file '{target_file}' is not a regular file"
        if target.suffix.lower() != ".md":
            return None, "target_file must be a Markdown (.md) document"

        blocked_roots = [
            self._configured_directory(value) for value in self.un_write_dirs or []
        ]
        if any(self._is_within(target, directory) for directory in blocked_roots):
            return None, f"target_file '{target_file}' is in a configured no-write directory"
        if self.write_dirs is not None:
            allowed_roots = [
                self._configured_directory(value) for value in self.write_dirs
            ]
            if not any(self._is_within(target, directory) for directory in allowed_roots):
                return None, (
                    f"target_file '{target_file}' is outside the configured write directories: "
                    f"{self.write_dirs}"
                )
        return target, None

    @staticmethod
    def _normalize_tag(value: str, kind: str) -> str:
        normalized = value.strip()
        if normalized.startswith("<") and normalized.endswith(">"):
            normalized = normalized[1:-1].strip()
        if not re.fullmatch(rf"{kind}-[^<>\r\n]+", normalized):
            raise ValueError(f"{kind.lower()}_tag must use the exact {kind}-... form")
        return normalized

    @classmethod
    def _normalize_target_tags(cls, bug_tag: str, test_case_tag: str) -> tuple[str, str]:
        bug = cls._normalize_tag(bug_tag, "BG")
        test = normalize_test_case_tag(test_case_tag)
        if bug.startswith("BG-STATIC-"):
            raise ValueError("bug_tag must identify a dynamic Bug, not BG-STATIC-*")
        confidence = re.fullmatch(r"BG-.+-(\d{1,3})", bug)
        if confidence is None or not 1 <= int(confidence.group(1)) <= 100:
            raise ValueError(
                "bug_tag must end with a non-zero confidence integer from 1 to 100"
            )
        return bug, test

    @classmethod
    def _normalize_checkpoint_path(cls, checkpoint_path: str) -> str:
        if not checkpoint_path.strip():
            return ""
        parts = [part.strip().strip("<>") for part in checkpoint_path.split("/")]
        if len(parts) != 3:
            raise ValueError(
                "checkpoint_path must contain exactly FG-.../FC-.../CK-..."
            )
        return "/".join(
            cls._normalize_tag(part, kind)
            for part, kind in zip(parts, ("FG", "FC", "CK"))
        )

    @staticmethod
    def _plain_data(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): ApplyWaveInfoEvidence._plain_data(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [ApplyWaveInfoEvidence._plain_data(item) for item in value]
        return copy.deepcopy(value)

    @staticmethod
    def _test_case_matches(receipt_test: str, document_test: str) -> bool:
        """Allow an exact node or its exact-path parameterized child instance."""

        return test_case_identity_relation(document_test, receipt_test) is not None

    def _similar_test_source_files(self, *test_case_names: str) -> list[str]:
        """Return bounded source-file hints without treating them as identities."""

        test_dir = Path(self.waveinfo.test_dir).resolve(strict=False)
        if not test_dir.is_dir():
            return []
        requested_names = []
        for test_case_name in test_case_names:
            file_part = test_case_name.strip().split("::", 1)[0]
            if file_part.endswith(".py"):
                name = Path(file_part).name
                if name not in requested_names:
                    requested_names.append(name)
        if not requested_names:
            return []

        source_files = []
        for path in test_dir.rglob("*.py"):
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if resolved.is_file() and self._is_within(resolved, test_dir):
                source_files.append(resolved)
        available_names = sorted({path.name for path in source_files})
        selected_names = list(requested_names)
        for requested_name in requested_names:
            for name in get_close_matches(
                requested_name,
                available_names,
                n=10,
                cutoff=0.45,
            ):
                if name not in selected_names:
                    selected_names.append(name)
        name_rank = {name: index for index, name in enumerate(selected_names)}
        candidates = sorted(
            (path for path in source_files if path.name in name_rank),
            key=lambda path: (name_rank[path.name], len(path.parts), str(path)),
        )
        display_root = test_dir.parent
        displayed = []
        for path in candidates:
            try:
                value = str(path.relative_to(display_root))
            except ValueError:
                value = self.waveinfo._display_path(path)
            if value not in displayed:
                displayed.append(value)
            if len(displayed) >= 10:
                break
        return displayed

    def _waveinfo_recovery_call(
        self,
        receipt_id: str,
        required_test_case_name: str,
    ) -> OrderedDict | None:
        """Rebuild a signed call in the non-nullable MCP argument shape."""

        receipt = self.waveinfo.get_analysis_receipt(receipt_id)
        if receipt is None:
            return None
        try:
            arguments = WaveInfoAnalysisArgs(**(receipt.get("arguments") or {}))
        except Exception:
            return None
        return OrderedDict(
            [
                ("test_case_name", required_test_case_name),
                ("pattern", self.waveinfo._mcp_pattern_entries(arguments.pattern)),
                (
                    "signal_groups",
                    self.waveinfo._mcp_signal_groups(arguments.signal_groups),
                ),
                (
                    "logged_cycle",
                    arguments.logged_cycle if arguments.logged_cycle is not None else -1,
                ),
                ("cycle_tolerance", arguments.cycle_tolerance),
                ("clock_signal", arguments.clock_signal or ""),
                ("clock_edge", arguments.clock_edge),
                ("cycle_origin", arguments.cycle_origin),
                (
                    "start_step",
                    arguments.start_step if arguments.start_step is not None else -1,
                ),
                (
                    "end_step",
                    arguments.end_step if arguments.end_step is not None else -1,
                ),
                ("context_steps", arguments.context_steps),
                ("max_signals", arguments.max_signals),
                ("max_points", arguments.max_points),
                ("max_files", arguments.max_files),
                ("file_offset", arguments.file_offset),
            ]
        )

    def _receipt_test_mismatch_error(
        self,
        *,
        receipt_id: str,
        receipt_test: str,
        test_case_tag: str,
    ) -> OrderedDict:
        """Explain the exact identity mismatch and provide one deterministic recovery."""

        document_test = test_case_tag[len("TC-") :]
        details = OrderedDict(
            [
                ("receipt_test_case_name", receipt_test),
                ("document_test_case_tag", test_case_tag),
                ("required_waveinfo_test_case_name", document_test),
                (
                    "identity_relation",
                    test_case_identity_relation(document_test, receipt_test),
                ),
                (
                    "similar_test_source_files",
                    self._similar_test_source_files(document_test, receipt_test),
                ),
            ]
        )
        recovery_call = self._waveinfo_recovery_call(receipt_id, document_test)
        if recovery_call is not None:
            details["recovery_call"] = recovery_call
        suggestions = [
            "Keep test_case_tag unchanged. Similar source-file paths are hints only; they "
            "are not equivalent pytest node IDs and must not be auto-selected.",
        ]
        if recovery_call is not None:
            suggestions.extend(
                [
                    "Call WaveInfo once with details.recovery_call exactly.",
                    "Then call ApplyWaveInfoEvidence with the new receipt_id and the unchanged "
                    "test_case_tag; do not retry Apply with guessed path variants.",
                ]
            )
        else:
            suggestions.append(
                "Create one final WaveInfo receipt using details.required_waveinfo_test_case_name "
                "exactly, then retry Apply with that new receipt_id."
            )
        suggestions.append(
            "Do not manually write receipt-backed YAML, waveform anchors, viewer URLs, or tokens."
        )
        return self.waveinfo._error(
            "receipt_test_mismatch",
            f"Receipt '{receipt_id}' analyzed '{receipt_test}', not the exact target "
            f"'<{test_case_tag}>'.",
            details=details,
            suggestions=suggestions,
        )

    def _latest_matching_evidence(
        self,
        document_test: str,
    ) -> tuple[str | None, OrderedDict]:
        """Return the newest signed final receipt matching the document TC."""

        with self.waveinfo._receipt_store_lock():
            return self._latest_matching_evidence_unlocked(document_test)

    def _latest_matching_evidence_unlocked(
        self,
        document_test: str,
    ) -> tuple[str | None, OrderedDict]:

        try:
            persisted = self.waveinfo._load_persisted_receipts()
            self.waveinfo.analysis_receipts = self.waveinfo._merge_receipts(
                self.waveinfo.analysis_receipts,
                persisted,
            )
        except Exception as error:
            warning(f"Could not refresh persisted WaveInfo receipts: {error}")

        matched_receipts = []
        parameterized_receipts = []
        similar_final_receipts = []
        receipts = sorted(
            self.waveinfo.analysis_receipts,
            key=lambda item: str(item.get("recorded_at") or ""),
        )
        for receipt in reversed(receipts):
            receipt_id = receipt.get("receipt_id")
            receipt_test = str((receipt.get("arguments") or {}).get("test_case_name") or "")
            if not isinstance(receipt_id, str) or not receipt_id or not receipt_test:
                continue
            try:
                identity_relation = test_case_identity_relation(
                    document_test, receipt_test
                )
            except ValueError:
                identity_relation = None
            matches = identity_relation is not None
            result = receipt.get("result") or {}
            if identity_relation == "parameterized_instance":
                parameterized_receipts.append(
                    OrderedDict(
                        [
                            ("receipt_id", receipt_id),
                            ("test_case_name", receipt_test),
                            ("status", result.get("status")),
                            ("evidence_usable", result.get("evidence_usable")),
                        ]
                    )
                )
            if not matches:
                try:
                    same_waveform_basename = (
                        self.waveinfo._normalize_test_case_name(receipt_test)
                        == self.waveinfo._normalize_test_case_name(document_test)
                    )
                except ValueError:
                    same_waveform_basename = False
                if same_waveform_basename and result.get("evidence_usable") is True:
                    similar_final_receipts.append(
                        OrderedDict(
                            [
                                ("receipt_id", receipt_id),
                                ("test_case_name", receipt_test),
                                ("status", result.get("status")),
                            ]
                        )
                    )
                continue
            matched_receipts.append(
                OrderedDict(
                    [
                        ("receipt_id", receipt_id),
                        ("test_case_name", receipt_test),
                        ("status", result.get("status")),
                        ("evidence_usable", result.get("evidence_usable")),
                    ]
                )
            )
            evidence = self.waveinfo.get_bug_document_evidence(receipt_id)
            if evidence.get("success") is True:
                return receipt_id, evidence

        details = OrderedDict(
            [
                ("document_test_case_tag", f"TC-{document_test}"),
                ("required_waveinfo_test_case_name", document_test),
                ("matching_receipts", matched_receipts[:10]),
                ("parameterized_receipts", parameterized_receipts[:10]),
                ("similar_final_receipts", similar_final_receipts[:10]),
                (
                    "similar_test_source_files",
                    self._similar_test_source_files(
                        document_test,
                        *(item["test_case_name"] for item in similar_final_receipts[:10]),
                    ),
                ),
            ]
        )
        if similar_final_receipts:
            recovery_call = self._waveinfo_recovery_call(
                similar_final_receipts[0]["receipt_id"],
                document_test,
            )
            if recovery_call is not None:
                details["recovery_call"] = recovery_call
        suggestions = [
            "Keep the document TC unchanged. Candidate source files are hints only and do not "
            "make shortened or prefixed node IDs equivalent.",
        ]
        if parameterized_receipts:
            suggestions.extend(
                [
                    "The documented function has parameterized WaveInfo receipts. Cross-check "
                    "their test_case_name values against an exact FAILED child in report "
                    "tests.test_case_instances, call final WaveInfo with that full node, then "
                    "apply the new receipt to the unchanged function-level test_case_tag.",
                    "Do not select an instance by filename similarity or change the "
                    "document TC tag to a guessed parameter variant.",
                ]
            )
        elif "recovery_call" in details:
            suggestions.extend(
                [
                    "Call WaveInfo once with details.recovery_call exactly.",
                    "Then retry ApplyWaveInfoEvidence with the new receipt_id and the unchanged "
                    "test_case_tag.",
                ]
            )
        else:
            suggestions.extend(
                [
                    "Run the exact failing test so it emits a current waveform.",
                    "Call final WaveInfo with details.required_waveinfo_test_case_name exactly, "
                    "an explicit window or clock alignment, and complete signal_groups.",
                ]
            )
        suggestions.append(
            "Do not retry path variants or manually write receipt-backed YAML, anchors, viewer "
            "URLs, or tokens."
        )
        return None, self.waveinfo._error(
            "matching_final_receipt_not_found",
            f"No signed final WaveInfo receipt can be applied to '<TC-{document_test}>'.",
            details=details,
            suggestions=suggestions,
        )

    @staticmethod
    def _read_existing_analysis(
        lines: list[str],
        open_index: int,
        close_index: int,
    ) -> dict[str, Any]:
        payload_text = textwrap.dedent(
            "".join(lines[open_index + 1 : close_index])
        )
        try:
            payload = yaml.safe_load(payload_text)
        except yaml.YAMLError:
            payload = None
        if not isinstance(payload, dict) or set(payload) != {WAVEFORM_BLOCK_KEY}:
            analysis = None
        else:
            analysis = payload.get(WAVEFORM_BLOCK_KEY)
        if not isinstance(analysis, dict):
            receipt_matches = re.findall(
                r"^[ \t]*receipt_id:[ \t]*['\"]?([0-9a-f]{32})['\"]?[ \t]*$",
                payload_text,
                flags=re.MULTILINE,
            )
            return {"receipt_id": receipt_matches[0]} if len(receipt_matches) == 1 else {}
        return analysis

    def _find_target_region(
        self,
        lines: list[str],
        bug_tag: str,
        test_case_tag: str,
        target_file: str,
        checkpoint_path: str = "",
    ) -> _DocumentEvidenceTarget:
        """Locate one checkpoint-scoped BG/TC and the TC's central evidence record."""

        stripped_lines = [line.strip() for line in lines]
        marker_indexes = {
            marker: [
                index for index, stripped in enumerate(stripped_lines) if stripped == marker
            ]
            for marker in (
                DYNAMIC_BUGS_MARKER,
                DYNAMIC_BUGS_END_MARKER,
                WAVEFORM_EVIDENCE_MARKER,
                WAVEFORM_EVIDENCE_END_MARKER,
            )
        }
        for marker, indexes in marker_indexes.items():
            if len(indexes) != 1:
                raise ValueError(
                    f"'{target_file}' must contain exactly one standalone {marker} marker; "
                    f"found {len(indexes)}"
                )
        dynamic_start = marker_indexes[DYNAMIC_BUGS_MARKER][0]
        dynamic_end = marker_indexes[DYNAMIC_BUGS_END_MARKER][0]
        evidence_start = marker_indexes[WAVEFORM_EVIDENCE_MARKER][0]
        evidence_end = marker_indexes[WAVEFORM_EVIDENCE_END_MARKER][0]
        if not dynamic_start < dynamic_end < evidence_start < evidence_end:
            raise ValueError(
                f"'{target_file}' must place the closed DYNAMIC-BUGS container before the "
                "closed WAVEFORM-EVIDENCE container"
            )

        current_bug = None
        current_bug_index = None
        hierarchy: dict[str, str | None] = {"FG": None, "FC": None, "CK": None}
        current_checkpoint = ""
        available_bugs: list[str] = []
        bug_locations: list[tuple[str, int, str]] = []
        structure_boundaries = [dynamic_end]
        section_locations: list[tuple[int, int]] = []
        test_locations: list[
            tuple[str | None, str, int, int | None, str, str]
        ] = []
        target_tests: list[tuple[int, int | None]] = []
        section_markers = {marker for _name, marker in BUG_ANALYSIS_SECTION_MARKERS}
        section_titles = {title for _name, title in BUG_ANALYSIS_SECTION_TITLES}
        analysis_started_for_bug: set[int] = set()
        in_fence = False
        for index in range(dynamic_start + 1, dynamic_end):
            stripped = stripped_lines[index]
            if stripped.startswith("```"):
                if not in_fence and stripped.lower() == WAVEFORM_FENCE_OPEN:
                    raise ValueError(
                        f"waveform evidence at line {index + 1} must be stored in one "
                        "central WAVEFORM-TC record"
                    )
                if in_fence and stripped == WAVEFORM_FENCE_CLOSE:
                    in_fence = False
                elif not in_fence:
                    in_fence = True
                continue
            if in_fence:
                continue
            if "<WAVEFORM-VIEWER>" in stripped or "/surfer/?wave=" in stripped:
                raise ValueError(
                    f"waveform viewer at line {index + 1} must follow the YAML in one "
                    "central WAVEFORM-TC record"
                )
            if (
                stripped in section_markers | section_titles
                and current_bug_index is not None
            ):
                section_locations.append((current_bug_index, index))
                analysis_started_for_bug.add(current_bug_index)
            for match in DOCUMENT_TAG_PATTERN.finditer(lines[index]):
                kind, value = match.groups()
                label = f"{kind}-{value}"
                try:
                    display_title = parse_dynamic_tag_heading(
                        lines[index], kind, label
                    )
                except ValueError as error:
                    raise ValueError(
                        f"invalid {kind} heading at line {index + 1}: {error}"
                    ) from error
                if kind == "FG":
                    hierarchy.update({"FG": label, "FC": None, "CK": None})
                    current_checkpoint = ""
                    current_bug = None
                    current_bug_index = None
                    structure_boundaries.append(index)
                elif kind == "FC":
                    hierarchy.update({"FC": label, "CK": None})
                    current_checkpoint = ""
                    current_bug = None
                    current_bug_index = None
                    structure_boundaries.append(index)
                elif kind == "CK":
                    hierarchy["CK"] = label
                    current_checkpoint = "/".join(
                        part
                        for part in (hierarchy["FG"], hierarchy["FC"], hierarchy["CK"])
                        if part is not None
                    )
                    current_bug = None
                    current_bug_index = None
                    structure_boundaries.append(index)
                elif kind == "BG":
                    current_bug = label
                    current_bug_index = index
                    bug_locations.append((label, index, current_checkpoint))
                    structure_boundaries.append(index)
                    if label not in available_bugs:
                        available_bugs.append(label)
                elif kind == "TC":
                    if current_bug_index in analysis_started_for_bug:
                        raise ValueError(
                            f"TC heading at line {index + 1} appears after the owning BG's "
                            "analysis fields; place every TC and WAVEFORM-REF before the "
                            "first analysis title"
                        )
                    try:
                        label = normalize_test_case_tag(label)
                    except ValueError as error:
                        raise ValueError(
                            f"invalid TC heading at line {index + 1}: {error}"
                        ) from error
                    test_locations.append(
                        (
                            current_bug,
                            label,
                            index,
                            current_bug_index,
                            display_title,
                            current_checkpoint,
                        )
                    )
                    if (
                        current_bug == bug_tag
                        and label == test_case_tag
                        and (not checkpoint_path or current_checkpoint == checkpoint_path)
                    ):
                        target_tests.append((index, current_bug_index))
        if in_fence:
            raise ValueError(f"'{target_file}' contains an unclosed Markdown fence")
        if bug_tag not in available_bugs:
            shown = ", ".join(available_bugs[:10]) or "<none>"
            raise ValueError(
                f"bug_tag '{bug_tag}' was not found in '{target_file}'; available BG tags: {shown}"
            )
        matching_bug_locations = [
            (index, checkpoint)
            for label, index, checkpoint in bug_locations
            if label == bug_tag and (not checkpoint_path or checkpoint == checkpoint_path)
        ]
        if checkpoint_path and not matching_bug_locations:
            available_paths = [
                checkpoint for label, _index, checkpoint in bug_locations if label == bug_tag
            ]
            raise ValueError(
                f"bug_tag '{bug_tag}' does not occur under checkpoint_path "
                f"'{checkpoint_path}' in '{target_file}'; available checkpoint paths: "
                f"{', '.join(available_paths[:10]) or '<none>'}"
            )
        if len(target_tests) > 1:
            locations = ", ".join(str(index + 1) for index, _owner in target_tests)
            raise ValueError(
                f"'{bug_tag}/{test_case_tag}' is ambiguous in '{target_file}' at lines "
                f"{locations}; pass checkpoint_path to select one exact FG/FC/CK/BG/TC path"
            )

        def bug_end_index(bug_index: int) -> int:
            return min(index for index in structure_boundaries if index > bug_index)

        test_index = None
        test_create_index = None
        reference_index = None
        test_indent = ""
        if target_tests:
            test_index, bug_index = target_tests[0]
            assert bug_index is not None
            indent_match = re.match(r"^[ \t]*", lines[test_index])
            test_indent = indent_match.group(0) if indent_match else ""
            pair_end = bug_end_index(bug_index)
            sibling_indexes = sorted(
                index
                for owner_bug, _label, index, owner_index, _title, _checkpoint
                in test_locations
                if owner_bug == bug_tag and owner_index == bug_index and index > test_index
            )
            if sibling_indexes:
                pair_end = min(pair_end, sibling_indexes[0])
            refs = [
                index
                for index in range(test_index + 1, pair_end)
                if WAVEFORM_REFERENCE_MARKER in lines[index]
            ]
            if len(refs) > 1:
                raise ValueError(
                    f"'{bug_tag}/{test_case_tag}' has multiple WAVEFORM-REF markers"
                )
            reference_index = refs[0] if refs else None
        else:
            matching_bugs = [index for index, _checkpoint in matching_bug_locations]
            if len(matching_bugs) != 1:
                locations = ", ".join(str(index + 1) for index in matching_bugs)
                raise ValueError(
                    f"test_case_tag '{test_case_tag}' is absent and bug_tag '{bug_tag}' "
                    f"occurs {len(matching_bugs)} times at matching lines {locations}; "
                    "pass checkpoint_path to select one exact FG/FC/CK/BG path"
                )
            bug_index = matching_bugs[0]
            bug_end = bug_end_index(bug_index)
            test_create_index = next(
                (
                    index
                    for owner_index, index in section_locations
                    if owner_index == bug_index
                ),
                bug_end,
            )
            siblings = [
                index
                for owner_bug, _label, index, owner_index, _title, _checkpoint
                in test_locations
                if owner_bug == bug_tag and owner_index == bug_index
            ]
            if siblings:
                indent_match = re.match(r"^[ \t]*", lines[siblings[0]])
                test_indent = indent_match.group(0) if indent_match else ""
            else:
                prefix = lines[bug_index].split(f"<{bug_tag}>", 1)[0]
                indent_match = re.match(r"^[ \t]*", prefix)
                test_indent = indent_match.group(0) if indent_match else ""
                if prefix.strip() in {"-", "*", "+"}:
                    test_indent += "  "

        record_headings: list[tuple[str, str, int]] = []
        in_fence = False
        for index in range(evidence_start + 1, evidence_end):
            stripped = stripped_lines[index]
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if "<WAVEFORM-TC-" not in stripped:
                continue
            try:
                canonical, display_title = parse_waveform_record_heading(stripped)
            except ValueError as error:
                raise ValueError(
                    f"invalid WAVEFORM-TC heading at line {index + 1}: {error}"
                ) from error
            record_headings.append((canonical, display_title, index))
        if in_fence:
            raise ValueError(f"'{target_file}' contains an unclosed Markdown fence")
        matching_records = [
            (canonical, display_title, index)
            for canonical, display_title, index in record_headings
            if canonical == test_case_tag
        ]
        associated_bug_tags = tuple(
            sorted(
                {
                    owner_bug
                    for owner_bug, label, _index, _owner_index, _title, _checkpoint
                    in test_locations
                    if owner_bug is not None and label == test_case_tag
                }
                | {bug_tag}
            )
        )
        if len(matching_records) > 1:
            locations = ", ".join(
                str(index + 1) for _tag, _title, index in matching_records
            )
            raise ValueError(
                f"'{test_case_tag}' has multiple central waveform records at lines {locations}"
            )
        if not matching_records:
            matching_test_titles = {
                title
                for _owner, label, _index, _owner_index, title, _checkpoint
                in test_locations
                if label == test_case_tag
            }
            if not matching_test_titles and test_index is None:
                matching_test_titles.add(
                    self._resolve_test_display_title(target_file, test_case_tag)
                )
            if len(matching_test_titles) != 1:
                raise ValueError(
                    f"'{test_case_tag}' must use one consistent visible description"
                )
            return _DocumentEvidenceTarget(
                test_index=test_index,
                test_create_index=test_create_index,
                test_indent=test_indent,
                reference_index=reference_index,
                evidence_end_index=evidence_end,
                associated_bug_tags=associated_bug_tags,
                test_display_title=next(iter(matching_test_titles)),
            )

        _canonical, record_title, heading_index = matching_records[0]
        matching_test_titles = {
            title
            for _owner, label, _index, _owner_index, title, _checkpoint
            in test_locations
            if label == test_case_tag
        }
        if matching_test_titles != {record_title}:
            raise ValueError(
                f"central record for '{test_case_tag}' must reuse its TC visible description"
            )
        previous = heading_index - 1
        while previous > evidence_start and not stripped_lines[previous]:
            previous -= 1
        expected_anchor = f'<a id="{waveform_anchor_id(test_case_tag)}"></a>'
        if stripped_lines[previous] != expected_anchor:
            raise ValueError(
                f"central record for '{test_case_tag}' must have anchor {expected_anchor} "
                f"as the nearest non-empty line before heading line {heading_index + 1}"
            )
        next_headings = [
            index
            for _tag, _title, index in record_headings
            if index > heading_index
        ]
        record_end = min(next_headings) if next_headings else evidence_end
        if next_headings:
            while record_end > heading_index + 1 and not stripped_lines[record_end - 1]:
                record_end -= 1
            if not re.fullmatch(
                r'<a id="[^"]+"></a>',
                stripped_lines[record_end - 1],
            ):
                raise ValueError(
                    f"central record at heading line {record_end + 1} must have a generated "
                    "anchor as its nearest preceding non-empty line"
                )
            record_end -= 1
        open_index = heading_index + 1
        while open_index < record_end and not stripped_lines[open_index]:
            open_index += 1
        if open_index >= record_end or stripped_lines[open_index].lower() != WAVEFORM_FENCE_OPEN:
            raise ValueError(
                f"central record for '{test_case_tag}' must contain a fenced YAML block"
            )
        close_index = open_index + 1
        while close_index < record_end and stripped_lines[close_index] != WAVEFORM_FENCE_CLOSE:
            if stripped_lines[close_index].startswith("```"):
                raise ValueError(
                    f"malformed waveform YAML fence at line {close_index + 1}"
                )
            close_index += 1
        if close_index >= record_end:
            raise ValueError(
                f"central waveform YAML at line {open_index + 1} has no closing fence"
            )
        return _DocumentEvidenceTarget(
            test_index=test_index,
            test_create_index=test_create_index,
            test_indent=test_indent,
            reference_index=reference_index,
            evidence_end_index=evidence_end,
            associated_bug_tags=associated_bug_tags,
            test_display_title=record_title,
            record_start=previous,
            record_end=record_end,
            open_index=open_index,
            close_index=close_index,
        )

    def _resolve_test_display_title(
        self,
        target_file: str,
        test_case_tag: str,
    ) -> str:
        """Read the canonical visible TC title from the target test's docstring."""

        # A parameterized pytest node is an execution child of its source
        # function.  Resolve the visible title from that parent function while
        # retaining the exact child node in the signed receipt.
        parent_tag = test_case_parent(test_case_tag)
        payload = parent_tag[len("TC-") :]
        parts = payload.split("::")
        file_path = Path(parts[0])
        class_name = parts[1] if len(parts) == 3 else None
        function_name = parts[-1]
        target_parent = (Path(self.workspace) / target_file).resolve().parent
        test_root = Path(self.waveinfo.test_dir).resolve().parent
        candidates = []
        for candidate in (
            target_parent / file_path,
            test_root / file_path,
            Path(self.workspace) / file_path,
        ):
            resolved = candidate.resolve(strict=False)
            if resolved not in candidates:
                candidates.append(resolved)
        source_path = next((path for path in candidates if path.is_file()), None)
        if source_path is None:
            searched = ", ".join(str(path) for path in candidates)
            raise ValueError(
                f"cannot create '{test_case_tag}' because its test source was not found; "
                f"searched: {searched}"
            )
        try:
            tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        except (OSError, SyntaxError, UnicodeError) as error:
            raise ValueError(
                f"cannot read the visible title for '{test_case_tag}' from "
                f"'{source_path}': {error}"
            ) from error

        scope = tree.body
        if class_name is not None:
            class_node = next(
                (
                    node
                    for node in scope
                    if isinstance(node, ast.ClassDef) and node.name == class_name
                ),
                None,
            )
            if class_node is None:
                raise ValueError(
                    f"cannot create '{test_case_tag}' because class '{class_name}' "
                    f"was not found in '{source_path}'"
                )
            scope = class_node.body
        function_node = next(
            (
                node
                for node in scope
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
            ),
            None,
        )
        if function_node is None:
            raise ValueError(
                f"cannot create '{test_case_tag}' because function '{function_name}' "
                f"was not found in '{source_path}'"
            )
        docstring = ast.get_docstring(function_node, clean=True)
        if not docstring:
            raise ValueError(
                f"cannot create '{test_case_tag}' because the test function needs a "
                "non-empty docstring for its visible title"
            )
        title = next(line.strip() for line in docstring.splitlines() if line.strip())
        return normalize_display_title(title)

    @staticmethod
    def _render_evidence_record(
        analysis: dict[str, Any],
        viewer_link: str,
        test_case_tag: str,
        test_display_title: str,
        newline: str,
    ) -> list[str]:
        payload = yaml.safe_dump(
            {WAVEFORM_BLOCK_KEY: ApplyWaveInfoEvidence._plain_data(analysis)},
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).rstrip("\n")
        return (
            [
                f'<a id="{waveform_anchor_id(test_case_tag)}"></a>{newline}',
                newline,
                f"{waveform_record_heading(test_case_tag, test_display_title)}{newline}",
                newline,
                f"{WAVEFORM_FENCE_OPEN}{newline}",
            ]
            + [f"{line}{newline}" for line in payload.splitlines()]
            + [
                f"{WAVEFORM_FENCE_CLOSE}{newline}",
                f"{viewer_link}{newline}",
                newline,
            ]
        )

    @staticmethod
    def _receipt_signals(analysis: dict[str, Any]) -> set[str]:
        signal_groups = analysis.get("signal_groups")
        if not isinstance(signal_groups, dict):
            return set()
        return {
            signal
            for field in WAVEFORM_SIGNAL_GROUP_FIELDS
            for signal in signal_groups.get(field, [])
            if isinstance(signal, str) and signal
        }

    @staticmethod
    def _atomic_replace(target: Path, original: str, updated: str) -> None:
        temp_name = None
        original_mode = stat.S_IMODE(target.stat().st_mode)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, original_mode)
            with target.open("r", encoding="utf-8", newline="") as handle:
                current = handle.read()
            if current != original:
                raise RuntimeError(
                    "target document changed while evidence was being prepared; retry with "
                    "the current file instead of overwriting concurrent edits"
                )
            os.replace(temp_name, target)
            temp_name = None
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    def refresh_existing_evidence(
        self,
        *,
        target_file: str,
        refreshes: list[dict[str, str]],
    ) -> OrderedDict:
        """Atomically refresh existing records whose signed semantics are unchanged."""

        target, path_error = self._resolve_target(target_file)
        if path_error:
            return self.waveinfo._error("invalid_target_file", path_error)
        assert target is not None
        if not refreshes:
            return OrderedDict(
                [("success", True), ("status", "no_refresh_required"), ("updated", [])]
            )

        prepared = []
        seen_tests = set()
        try:
            persisted_receipts = {
                receipt.get("receipt_id"): receipt
                for receipt in self.waveinfo._load_persisted_receipts()
                if isinstance(receipt.get("receipt_id"), str)
            }
        except Exception as error:
            return self.waveinfo._error(
                "refresh_receipt_store_unavailable",
                f"Could not load the signed receipt store: {error}",
            )
        for refresh in refreshes:
            try:
                bug_tag, test_case_tag = self._normalize_target_tags(
                    refresh.get("bug_tag", ""),
                    refresh.get("test_case_tag", ""),
                )
                checkpoint_path = self._normalize_checkpoint_path(
                    refresh.get("checkpoint_path", "")
                )
            except ValueError as error:
                return self.waveinfo._error("invalid_document_target", str(error))
            if test_case_tag in seen_tests:
                return self.waveinfo._error(
                    "duplicate_refresh_target",
                    f"refreshes must contain one entry per central TC; duplicated '{test_case_tag}'.",
                )
            seen_tests.add(test_case_tag)
            old_receipt_id = refresh.get("old_receipt_id", "").strip()
            new_receipt_id = refresh.get("new_receipt_id", "").strip()
            old_receipt = persisted_receipts.get(old_receipt_id)
            new_receipt = persisted_receipts.get(new_receipt_id)
            if old_receipt is None or new_receipt is None:
                return self.waveinfo._error(
                    "refresh_receipt_not_found",
                    f"Could not load both signed receipts for '{test_case_tag}'.",
                    details={
                        "old_receipt_id": old_receipt_id,
                        "new_receipt_id": new_receipt_id,
                    },
                )
            old_result = old_receipt.get("result") or {}
            new_result = new_receipt.get("result") or {}
            old_semantic = old_result.get("semantic_fingerprint")
            new_semantic = new_result.get("semantic_fingerprint")
            if (
                not isinstance(old_semantic, str)
                or not old_semantic
                or old_semantic != new_semantic
            ):
                return self.waveinfo._error(
                    "refresh_semantic_review_required",
                    f"Current evidence for '{test_case_tag}' is not semantically identical "
                    "to the documented receipt; automatic replacement is not allowed.",
                    details={
                        "old_receipt_id": old_receipt_id,
                        "new_receipt_id": new_receipt_id,
                        "old_semantic_fingerprint": old_semantic,
                        "new_semantic_fingerprint": new_semantic,
                    },
                )
            evidence = self.waveinfo.get_bug_document_evidence(new_receipt_id)
            if evidence.get("success") is not True:
                return evidence
            receipt_test = str(evidence.get("test_case_name") or "")
            document_test = test_case_tag[len("TC-") :]
            try:
                test_matches = self._test_case_matches(receipt_test, document_test)
            except ValueError as error:
                return self.waveinfo._error("invalid_test_case_target", str(error))
            if not test_matches:
                return self._receipt_test_mismatch_error(
                    receipt_id=new_receipt_id,
                    receipt_test=receipt_test,
                    test_case_tag=test_case_tag,
                )
            prepared.append(
                {
                    "bug_tag": bug_tag,
                    "test_case_tag": test_case_tag,
                    "checkpoint_path": checkpoint_path,
                    "old_receipt_id": old_receipt_id,
                    "new_receipt_id": new_receipt_id,
                    "evidence": evidence,
                }
            )

        try:
            with _DOCUMENT_WRITE_LOCK:
                with target.open("r", encoding="utf-8", newline="") as handle:
                    original = handle.read()
                updated = original
                updated_tests = []
                for item in prepared:
                    newline = "\r\n" if "\r\n" in updated else "\n"
                    lines = updated.splitlines(keepends=True)
                    region = self._find_target_region(
                        lines,
                        item["bug_tag"],
                        item["test_case_tag"],
                        target_file,
                        item["checkpoint_path"],
                    )
                    if (
                        region.record_start is None
                        or region.record_end is None
                        or region.open_index is None
                        or region.close_index is None
                    ):
                        raise ValueError(
                            f"central record for '{item['test_case_tag']}' does not exist"
                        )
                    existing = self._read_existing_analysis(
                        lines,
                        region.open_index,
                        region.close_index,
                    )
                    if existing.get("receipt_id") != item["old_receipt_id"]:
                        raise RuntimeError(
                            f"central record for '{item['test_case_tag']}' changed from expected "
                            f"receipt '{item['old_receipt_id']}'"
                        )
                    existing_bug_tags = existing.get("bug_tags")
                    existing_bug_evidence = existing.get("bug_evidence")
                    if (
                        not isinstance(existing_bug_tags, list)
                        or sorted(existing_bug_tags) != sorted(region.associated_bug_tags)
                        or not isinstance(existing_bug_evidence, dict)
                    ):
                        raise ValueError(
                            f"central Bug associations for '{item['test_case_tag']}' are malformed "
                            "or do not match its BG-side references"
                        )

                    receipt_fields = self._plain_data(
                        item["evidence"]["bug_document_fields"][WAVEFORM_BLOCK_KEY]
                    )
                    receipt_signals = self._receipt_signals(receipt_fields)
                    required_signals = {
                        signal
                        for bug_fields in existing_bug_evidence.values()
                        if isinstance(bug_fields, dict)
                        for signal in bug_fields.get("required_signals", [])
                        if isinstance(signal, str) and signal
                    }
                    missing_required_signals = sorted(required_signals - receipt_signals)
                    if missing_required_signals:
                        raise ValueError(
                            f"new receipt for '{item['test_case_tag']}' is missing required "
                            f"signals: {missing_required_signals}"
                        )

                    generated = OrderedDict(
                        [
                            ("test_case", item["test_case_tag"]),
                            ("bug_tags", list(existing_bug_tags)),
                        ]
                    )
                    generated.update(receipt_fields)
                    for field_name in WAVEFORM_LLM_ANALYSIS_FIELDS:
                        value = existing.get(field_name)
                        if (
                            not isinstance(value, str)
                            or not value.strip()
                            or BUG_TODO_MARKER in value
                        ):
                            raise ValueError(
                                f"cannot preserve incomplete semantic field '{field_name}' for "
                                f"'{item['test_case_tag']}'"
                            )
                        generated[field_name] = value
                    generated["bug_evidence"] = copy.deepcopy(existing_bug_evidence)
                    record_lines = self._render_evidence_record(
                        generated,
                        item["evidence"]["bug_document_viewer_link"],
                        item["test_case_tag"],
                        region.test_display_title,
                        newline,
                    )
                    lines[region.record_start : region.record_end] = record_lines
                    updated = ensure_markdown_file_heading_spacing(
                        target_file,
                        "".join(lines),
                    )
                    updated_tests.append(
                        OrderedDict(
                            [
                                ("test_case_tag", item["test_case_tag"]),
                                ("old_receipt_id", item["old_receipt_id"]),
                                ("new_receipt_id", item["new_receipt_id"]),
                            ]
                        )
                    )
                if updated != original:
                    self._atomic_replace(target, original, updated)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            return self.waveinfo._error(
                "current_evidence_refresh_failed",
                f"Could not atomically refresh current WaveInfo evidence in "
                f"'{target_file}': {error}",
                suggestions=[
                    "Repair the reported document or receipt mismatch, then call Check again.",
                    "Do not rename a TC or select a similar pytest node ID automatically.",
                ],
            )

        return OrderedDict(
            [
                ("success", True),
                ("status", "current_evidence_refreshed"),
                ("target_file", target_file),
                ("updated", updated_tests),
            ]
        )

    def apply_evidence(
        self,
        *,
        target_file: str,
        bug_tag: str,
        test_case_tag: str,
        checkpoint_path: str = "",
        receipt_id: str = "",
        replace_existing: bool = False,
    ) -> OrderedDict:
        """Validate and atomically apply one receipt-backed document block."""

        target, path_error = self._resolve_target(target_file)
        if path_error:
            return self.waveinfo._error("invalid_target_file", path_error)
        assert target is not None
        try:
            bug_tag, test_case_tag = self._normalize_target_tags(
                bug_tag, test_case_tag
            )
            checkpoint_path = self._normalize_checkpoint_path(checkpoint_path)
        except ValueError as error:
            return self.waveinfo._error("invalid_document_target", str(error))

        document_test = test_case_tag[len("TC-") :]
        receipt_selection = "explicit"
        if receipt_id:
            evidence = self.waveinfo.get_bug_document_evidence(receipt_id)
        else:
            receipt_selection = "latest_matching_final"
            receipt_id, evidence = self._latest_matching_evidence(document_test)
            if receipt_id is None:
                return evidence
        if evidence.get("success") is not True:
            return evidence
        receipt_test = str(evidence.get("test_case_name") or "")
        try:
            test_matches = self._test_case_matches(receipt_test, document_test)
        except ValueError as error:
            return self.waveinfo._error("invalid_test_case_target", str(error))
        if not test_matches:
            return self._receipt_test_mismatch_error(
                receipt_id=receipt_id,
                receipt_test=receipt_test,
                test_case_tag=test_case_tag,
            )

        try:
            target_size = target.stat().st_size
        except OSError as error:
            return self.waveinfo._error(
                "invalid_target_file",
                f"Could not inspect target_file '{target_file}': {error}",
            )
        if target_size > self._MAX_DOCUMENT_BYTES:
            return self.waveinfo._error(
                "target_file_too_large",
                f"Target document is larger than {self._MAX_DOCUMENT_BYTES} bytes.",
            )

        try:
            with _DOCUMENT_WRITE_LOCK:
                with target.open("r", encoding="utf-8", newline="") as handle:
                    original = handle.read()
                newline = "\r\n" if "\r\n" in original else "\n"
                lines = original.splitlines(keepends=True)
                region = self._find_target_region(
                    lines,
                    bug_tag,
                    test_case_tag,
                    target_file,
                    checkpoint_path,
                )
                existing = (
                    self._read_existing_analysis(
                        lines,
                        region.open_index,
                        region.close_index,
                    )
                    if region.open_index is not None
                    and region.close_index is not None
                    else {}
                )
                old_receipt = existing.get("receipt_id")
                old_receipt_is_real = (
                    isinstance(old_receipt, str)
                    and bool(old_receipt.strip())
                    and BUG_TODO_MARKER not in old_receipt
                )
                replacing_different = (
                    old_receipt_is_real and old_receipt != receipt_id
                )
                if replacing_different and not replace_existing:
                    return self.waveinfo._error(
                        "existing_receipt_conflict",
                        f"'{test_case_tag}' already references receipt "
                        f"'{old_receipt}'. Set replace_existing=true only after confirming "
                        "that it should be replaced by the new waveform evidence.",
                    )

                receipt_fields = self._plain_data(
                    evidence["bug_document_fields"][WAVEFORM_BLOCK_KEY]
                )
                existing_bug_tags = existing.get("bug_tags", [])
                existing_bug_evidence = existing.get("bug_evidence", {})
                if region.record_start is not None and (
                    not isinstance(existing_bug_tags, list)
                    or not all(isinstance(item, str) for item in existing_bug_tags)
                    or not isinstance(existing_bug_evidence, dict)
                ):
                    raise ValueError(
                        f"central record for '{test_case_tag}' has malformed bug_tags or "
                        "bug_evidence; repair the mapping before applying a receipt"
                    )
                bug_tags = list(region.associated_bug_tags)
                receipt_signals = self._receipt_signals(receipt_fields)
                required_signals = {
                    signal
                    for associated_bug in bug_tags
                    for item in [existing_bug_evidence.get(associated_bug, {})]
                    if isinstance(item, dict)
                    for signal in item.get("required_signals", [])
                    if isinstance(signal, str) and signal
                }
                missing_required_signals = sorted(required_signals - receipt_signals)
                if missing_required_signals:
                    return self.waveinfo._error(
                        "required_signal_union_missing",
                        f"Receipt '{receipt_id}' does not include every signal required by "
                        f"the Bugs already associated with '{test_case_tag}'.",
                        details={"missing_required_signals": missing_required_signals},
                        suggestions=[
                            "Call final WaveInfo for this TC with signal_groups containing the "
                            "union of required signals for all associated Bugs, then apply the "
                            "new receipt with replace_existing=true."
                        ],
                    )

                generated = OrderedDict(
                    [
                        ("test_case", test_case_tag),
                        ("bug_tags", bug_tags),
                    ]
                )
                generated.update(receipt_fields)
                preserved_fields: list[str] = []
                reset_fields: list[str] = []
                for field_name in WAVEFORM_LLM_ANALYSIS_FIELDS:
                    old_value = existing.get(field_name)
                    if (
                        not replacing_different
                        and isinstance(old_value, str)
                        and old_value.strip()
                        and BUG_TODO_MARKER not in old_value
                    ):
                        generated[field_name] = old_value
                        preserved_fields.append(field_name)
                    else:
                        generated[field_name] = BUG_TODO_MARKER
                        reset_fields.append(field_name)

                bug_evidence = OrderedDict()
                for associated_bug in bug_tags:
                    old_bug_fields = existing_bug_evidence.get(associated_bug, {})
                    if not isinstance(old_bug_fields, dict):
                        old_bug_fields = {}
                    bug_fields = OrderedDict()
                    old_required = old_bug_fields.get("required_signals", [])
                    bug_fields["required_signals"] = (
                        list(old_required)
                        if isinstance(old_required, list)
                        and bool(old_required)
                        and all(isinstance(item, str) for item in old_required)
                        else sorted(receipt_signals)
                    )
                    if not bug_fields["required_signals"]:
                        reset_fields.append(
                            f"bug_evidence.{associated_bug}.required_signals"
                        )
                    for field_name in WAVEFORM_BUG_ANALYSIS_FIELDS[1:]:
                        old_value = old_bug_fields.get(field_name)
                        if (
                            not replacing_different
                            and isinstance(old_value, str)
                            and old_value.strip()
                            and BUG_TODO_MARKER not in old_value
                        ):
                            bug_fields[field_name] = old_value
                            preserved_fields.append(
                                f"bug_evidence.{associated_bug}.{field_name}"
                            )
                        else:
                            bug_fields[field_name] = BUG_TODO_MARKER
                            reset_fields.append(
                                f"bug_evidence.{associated_bug}.{field_name}"
                            )
                    bug_evidence[associated_bug] = bug_fields
                generated["bug_evidence"] = bug_evidence

                created_test_case = region.test_index is None
                created_waveform_record = region.record_start is None
                reference_line = (
                    f"{region.test_indent}  {waveform_reference(test_case_tag)}{newline}"
                )
                edits: list[tuple[int, int, list[str]]] = []
                if created_test_case:
                    assert region.test_create_index is not None
                    edits.append(
                        (
                            region.test_create_index,
                            region.test_create_index,
                            [
                                f"{region.test_indent}- {region.test_display_title} "
                                f"<{test_case_tag}>{newline}",
                                reference_line,
                                newline,
                            ],
                        )
                    )
                else:
                    assert region.test_index is not None
                    if region.reference_index is None:
                        edits.append(
                            (region.test_index + 1, region.test_index + 1, [reference_line])
                        )
                    elif region.reference_index != region.test_index + 1:
                        edits.extend(
                            [
                                (region.reference_index, region.reference_index + 1, []),
                                (region.test_index + 1, region.test_index + 1, [reference_line]),
                            ]
                        )
                    else:
                        edits.append(
                            (
                                region.reference_index,
                                region.reference_index + 1,
                                [reference_line],
                            )
                        )
                record_lines = self._render_evidence_record(
                    generated,
                    evidence["bug_document_viewer_link"],
                    test_case_tag,
                    region.test_display_title,
                    newline,
                )
                if region.record_start is None:
                    edits.append(
                        (
                            region.evidence_end_index,
                            region.evidence_end_index,
                            record_lines,
                        )
                    )
                else:
                    assert region.record_end is not None
                    edits.append(
                        (region.record_start, region.record_end, record_lines)
                    )
                updated_lines = list(lines)
                for start, end, replacement in sorted(
                    edits, key=lambda item: item[0], reverse=True
                ):
                    updated_lines[start:end] = replacement
                updated = ensure_markdown_file_heading_spacing(
                    target_file,
                    "".join(updated_lines),
                )
                relative_target = target.relative_to(Path(self.workspace)).as_posix()
                if updated == original:
                    return OrderedDict(
                        [
                            ("success", True),
                            ("status", "already_applied"),
                            ("target_file", relative_target),
                            ("bug_tag", bug_tag),
                            ("test_case_tag", test_case_tag),
                            ("checkpoint_path", checkpoint_path or None),
                            ("receipt_id", receipt_id),
                            ("receipt_selection", receipt_selection),
                            ("created_test_case", False),
                            ("created_waveform_record", False),
                            ("associated_bug_tags", bug_tags),
                            ("preserved_llm_fields", preserved_fields),
                            ("completion_required", reset_fields),
                        ]
                    )
                self._atomic_replace(target, original, updated)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            return self.waveinfo._error(
                "document_update_failed",
                f"Could not apply WaveInfo evidence to '{target_file}': {error}",
                suggestions=[
                    "Keep one unambiguous target FG/FC/CK/BG/TC path inside the closed "
                    "DYNAMIC-BUGS container. If the BG tag repeats across checkpoints, pass "
                    "the exact checkpoint_path.",
                    "Keep one closed central WAVEFORM-EVIDENCE container and one central "
                    "record per TC.",
                    "Resolve duplicate tags, unclosed Markdown fences, permission "
                    "restrictions, or concurrent edits, then retry.",
                ],
            )

        return OrderedDict(
            [
                ("success", True),
                ("status", "evidence_applied"),
                ("target_file", relative_target),
                ("bug_tag", bug_tag),
                ("test_case_tag", test_case_tag),
                ("checkpoint_path", checkpoint_path or None),
                ("receipt_id", receipt_id),
                ("receipt_selection", receipt_selection),
                ("created_test_case", created_test_case),
                ("created_waveform_record", created_waveform_record),
                ("associated_bug_tags", bug_tags),
                ("replaced_receipt_id", old_receipt if replacing_different else None),
                ("preserved_llm_fields", preserved_fields),
                ("completion_required", reset_fields),
                (
                    "next_action",
                    "Apply evidence directly to each remaining exact FG/FC/CK/BG/TC path. "
                    "Within the same CK/BG path, add sibling TCs instead of duplicating the "
                    "BG occurrence. When the same Bug root affects a different CK, create and "
                    "complete that CK-scoped BG path and pass checkpoint_path. For another "
                    "independent Bug exposed by this TC, apply "
                    "the same central record to that Bug's distinct BG and expand final "
                    "WaveInfo signal_groups to the union required by all associated Bugs. "
                    "Then replace each remaining <BUG-TODO> field after reviewing the "
                    "specification, test-driver/API ordering, WaveInfo timeline, and RTL. "
                    "Complete all eight Bug analysis sections once in every CK-scoped BG path "
                    "before Check/Complete.",
                ),
            ]
        )

    def _run(
        self,
        target_file: str,
        bug_tag: str,
        test_case_tag: str,
        checkpoint_path: str = "",
        receipt_id: str = "",
        replace_existing: bool = False,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Apply verified waveform fields without authoring semantic conclusions."""

        del run_manager
        try:
            args = ArgApplyWaveInfoEvidence(
                target_file=target_file,
                bug_tag=bug_tag,
                test_case_tag=test_case_tag,
                checkpoint_path=checkpoint_path,
                receipt_id=receipt_id,
                replace_existing=replace_existing,
            )
        except Exception as error:
            result = self.waveinfo._error(
                "invalid_arguments",
                f"Invalid ApplyWaveInfoEvidence arguments: {error}",
            )
            return make_llm_tool_ret(result, check_pass=False)
        result = self.apply_evidence(**args.model_dump(mode="json"))
        return make_llm_tool_ret(result, check_pass=False)
