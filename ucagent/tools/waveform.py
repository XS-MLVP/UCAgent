# -*- coding: utf-8 -*-
"""Read-only waveform discovery and event analysis tools."""

from __future__ import annotations

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
import tempfile
import time
from typing import Any, ClassVar, Literal, Optional

from langchain_core.callbacks import CallbackManagerForToolRun
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field, model_validator

from ucagent.util.functions import make_llm_tool_ret
from ucagent.util.bug_analysis_contract import WAVEFORM_LLM_ANALYSIS_FIELDS
from ucagent.util.log import warning
from .uctool import UCTool


WaveEvent = Literal["change", "rising", "falling", "equals", "unknown"]
ClockEdge = Literal["rising", "falling"]


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


class WaveInfoAnalysisArgs(BaseModel):
    """Canonical arguments used by :class:`WaveInfo` analysis and receipts."""

    test_case_name: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Test function name or full pytest node ID. Omit it to list waveform "
            "files in the newest session. When provided, the final :: component is "
            "used as the exact waveform basename, including parameter IDs."
        ),
    )
    pattern: list[WaveSignalPattern] | None = Field(
        default=None,
        description=(
            "Structured signal/event queries. Omit this to inspect waveform metadata "
            "and the signal catalog."
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
        description="Maximum number of matched signals (catalog output may be truncated).",
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
        if self.clock_signal is not None:
            self.clock_signal = self.clock_signal.strip() or None
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
            "waveform files in the newest session."
        ),
    )
    pattern: list[WaveInfoToolPattern] = Field(
        default=[],
        description=(
            "Structured signal/event queries. Leave empty to inspect waveform metadata "
            "and the signal catalog."
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
        description="Maximum number of matched signals (catalog output may be truncated).",
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
        "The tool searches only the newest toffee_tmp_* session, prefers FST, "
        "and never substitutes another test or a stale session. Signal queries use "
        "wavekit syntax and must be supplied as structured pattern entries. "
        "A pattern-only call is exploratory: final Bug evidence must use either a "
        "complete start_step/end_step window or logged_cycle with an exact clock_signal. "
        "logged_cycle is only a test-log hint: provide clock_signal so the tool can "
        "map clock occurrence indices to wavekit simulation timestamps. Always "
        "confirm a candidate with logged inputs, handshake/state, transaction IDs, "
        "and relevant pins before using it as Bug evidence."
    )
    args_schema: Optional[ArgsSchema] = ArgWaveInfo
    return_direct: bool = False

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
        self.dut_name = dut_name
        self.analysis_receipts = []
        self._load_analysis_receipts()

    def _receipt_store_path(self) -> Path:
        return Path(self.workspace) / self._RECEIPT_STORE_RELATIVE

    def _receipt_key_path(self) -> Path:
        return Path(self.workspace) / self._RECEIPT_KEY_RELATIVE

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
        try:
            self.analysis_receipts = self._load_persisted_receipts()
        except Exception as error:
            warning(f"Could not restore persisted WaveInfo receipts: {error}")
            self.analysis_receipts = []

    def _persist_analysis_receipts(self) -> None:
        key = self._read_receipt_key(create=True)
        if key is None:
            raise RuntimeError("Could not create the WaveInfo receipt signing key.")
        persisted = self._load_persisted_receipts(key)
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
            f'{normalized_name}") and confirm the DUT fixture calls SetWaveform and '
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
                    "Use the non-empty recommended_call.test_case_name verbatim in the "
                    "next WaveInfo call to parse one waveform. Do not repeat inventory: "
                    "inventory does not create Bug-analysis evidence or a receipt.",
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
                    "matching_data_files": dat_matches,
                    "stale_waveform_candidates_not_used": old_matches,
                },
                suggestions=common_suggestions,
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
                            (
                                "waveform_selection",
                                copy.deepcopy(result.get("waveform_selection")),
                            ),
                            ("waveform_info", copy.deepcopy(result.get("waveform_info"))),
                            ("analysis_window", copy.deepcopy(result.get("analysis_window"))),
                            ("event_summary", copy.deepcopy(result.get("event_summary"))),
                            ("cycle_alignment", copy.deepcopy(result.get("cycle_alignment"))),
                            ("event_steps", event_steps),
                            (
                                "recommended_evidence_call",
                                copy.deepcopy(result.get("recommended_evidence_call")),
                            ),
                        ]
                    ),
                ),
            ]
        )
        self.analysis_receipts.append(receipt)
        if len(self.analysis_receipts) > self._RECEIPT_LIMIT:
            del self.analysis_receipts[: -self._RECEIPT_LIMIT]
        persisted = False
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

    def get_analysis_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """Return a verified receipt from memory or the signed checkpoint store."""

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
                        ("value", item.value or ""),
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

        fields = OrderedDict(
            [
                ("status", "confirmed"),
                ("receipt_id", receipt_info.get("receipt_id")),
                ("result_fingerprint", receipt_info.get("result_fingerprint")),
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
        result["bug_document_note"] = (
            "Put a ```yaml fence immediately after the matching <TC-*>, copy "
            "bug_document_fields as the complete YAML mapping, and add the three required "
            "LLM-authored fields under waveform_analysis after checking the returned "
            "timeline and RTL. Do not use the legacy <WAVEFORM-ANALYSIS> tag, JSON, or bare "
            "YAML. Do not copy analysis_window.effective_* as requested call arguments."
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

        if len(matched_by_name) > max_signals:
            return self._error(
                "signal_limit_exceeded",
                "Signal patterns matched more signals than max_signals; analysis was not truncated silently.",
                details={
                    "matched_signal_count": len(matched_by_name),
                    "max_signals": max_signals,
                    "first_matches": list(matched_by_name)[:max_signals],
                },
                suggestions=["Narrow wildcard or regex patterns, or raise max_signals up to 64."],
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
            result["recommended_evidence_call"] = OrderedDict(
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
            result["next_action"] = (
                "Invoke WaveInfo with recommended_evidence_call exactly, then use the new "
                "receipt and its bug_document_fields. The current receipt is exploratory "
                "and cannot confirm a dynamic Bug."
            )
        else:
            result["evidence_usable"] = True
            result["evidence_warning"] = (
                "Waveform evidence supplements the failing assertion and source root-cause "
                "analysis; the LLM must still confirm the candidate against logged context."
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
        return result

    def _run(
        self,
        test_case_name: str = "",
        pattern: list[WaveInfoToolPattern] = [],
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
