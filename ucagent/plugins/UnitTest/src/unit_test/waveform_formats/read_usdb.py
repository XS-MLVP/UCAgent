"""UVD/USDB CLI adapter using usdbaccess for data and dap for scope metadata.

Each query owns an independent process. Metadata is cached per reader; digital
values retain native simulation ticks and arbitrary integer precision.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import itertools
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from .pagination import paginate_signal_matches
from .protocols import (
    BackendArgs, WaveformBackendArgumentError, WaveformSignalMatches, WaveformValueChanges,
)
from .queries import compile_signal_query


@dataclass(frozen=True)
class UsdbScope:
    """Top-level scope with its complete hierarchical name."""

    full_name: str


@dataclass(frozen=True)
class UsdbSignal:
    """Signal identity with an unqualified base name and positive bit width."""

    full_name: str
    base_name: str
    width: int

    @property
    def native_name(self) -> str:
        """Return the CLI query path without a declared packed range suffix."""
        return re.sub(r"\[-?\d+:-?\d+\]$", "", self.full_name)


_UVD_ENV_KEYS = ("UVD_HOME", "UVS_HOME")
_RESOLVED_TOOLS: dict[tuple[str, str | None, str | None], str] = {}


class UsdbRuntimeError(RuntimeError):
    """A UVD CLI query or report conversion failed."""


def _tool_works(candidate: str) -> bool:
    """Probe a wrapper, rejecting execution failures and missing target binaries."""
    try:
        completed = subprocess.run(
            [candidate, "--help"], capture_output=True, text=True, timeout=20,
            check=False, errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    stderr = completed.stderr or ""
    return completed.returncode == 0 or (
        completed.returncode != 127 and "No such file or directory" not in stderr
    )


def _find_tool(name: str) -> str:
    """Find a CLI only in configured installation homes, preserving operator env."""
    homes = tuple(os.environ.get(key) for key in _UVD_ENV_KEYS)
    if name == "dap" and not homes[0]:
        raise UsdbRuntimeError("UVD is not configured: dap requires UVD_HOME. Set it to the UVD installation.")
    cache_key = (name, *homes)
    cached = _RESOLVED_TOOLS.get(cache_key)
    if cached is not None and os.path.isfile(cached):
        return cached
    candidates = [os.path.abspath(os.path.join(home, "bin", name)) for home in homes if home]
    for candidate in dict.fromkeys(candidates):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK) and _tool_works(candidate):
            _RESOLVED_TOOLS[cache_key] = candidate
            return candidate
    raise UsdbRuntimeError(
        f"Cannot find a working '{name}' in the configured UVS/UVD installations. "
        f"Set UVS_HOME and UVD_HOME to valid installation roots. Searched: {candidates}"
    )


def _run_tool(
    command: list[str], *, check: bool = True, cwd: str | Path | None = None,
) -> tuple[int, str]:
    """Run one CLI in an optional working directory and report query failures."""
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False,
            errors="replace", cwd=cwd,
        )
    except OSError as error:
        raise UsdbRuntimeError(f"Cannot execute {command[0]}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise UsdbRuntimeError(f"{command[0]} timed out after 120s") from error
    output = (completed.stdout or "") + (completed.stderr or "")
    if check and completed.returncode != 0:
        detail = output.strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        raise UsdbRuntimeError(f"{command[0]} query failed: {message}")
    return completed.returncode, output


@dataclass(frozen=True)
class _UsdbMetadata:
    """Cached native time bounds, top scopes, and complete digital catalog."""

    begin_time: int
    end_time: int
    scopes: list[UsdbScope]
    signals: dict[str, UsdbSignal]


def _parse_info(output: str) -> tuple[int, int]:
    """Extract and validate native start/end ticks from usdbaccess --info."""
    begin = re.search(r"^start time:\s*(-?\d+)\s*$", output, re.MULTILINE)
    end = re.search(r"^end time:\s*(-?\d+)\s*$", output, re.MULTILINE)
    if begin is None or end is None:
        raise UsdbRuntimeError("usdbaccess --info did not report start/end time")
    bounds = int(begin.group(1)), int(end.group(1))
    if bounds[0] < 0 or bounds[1] < bounds[0]:
        raise UsdbRuntimeError(f"usdbaccess reported an invalid time range {bounds}")
    return bounds


_DIM_TOKEN = re.compile(r"\s([PU]):((?:\[-?\d+:-?\d+\])+)\s*$")


def _parse_hier(output: str) -> dict[str, UsdbSignal]:
    """Parse Var rows, preserving escaped names and expanding unpacked dimensions."""
    signals: dict[str, UsdbSignal] = {}
    for line in output.splitlines():
        if not line.startswith("Var:"):
            continue
        rest = line[len("Var:"):]
        bits_pos = rest.find(" Bits:")
        if bits_pos < 0:
            raise UsdbRuntimeError(f"usdbaccess --hier omitted Bits for: {rest.strip()}")
        fields, bits_text = rest[:bits_pos], rest[bits_pos:]
        bits = re.search(r"Bits:(\d+)", bits_text)
        if bits is None or int(bits.group(1)) <= 0:
            raise UsdbRuntimeError(f"usdbaccess reported an invalid Bits field: {rest.strip()}")
        # Real-valued variables cannot participate in digital four-state mapping.
        if re.search(r"\bType:Real(?:\s|$)", bits_text):
            continue
        width = int(bits.group(1))
        unpacked = []
        packed = None
        remainder = fields
        while (token := _DIM_TOKEN.search(remainder)) is not None:
            dims = [(int(a), int(b)) for a, b in re.findall(r"\[(-?\d+):(-?\d+)\]", token.group(2))]
            if token.group(1) == "P" and packed is None:
                packed = dims
            elif token.group(1) == "U":
                unpacked.append(dims)
            else:
                raise UsdbRuntimeError(f"Duplicate packed dimensions: {rest.strip()}")
            remainder = remainder[:token.start()]
        name = remainder.strip()
        if not name:
            raise UsdbRuntimeError("usdbaccess --hier returned an empty variable name")
        unpacked.reverse()
        if unpacked:
            dimensions = [range(min(a, b), max(a, b) + 1) for dims in unpacked for a, b in dims]
            total = 1
            for dimension in dimensions:
                total *= len(dimension)
            if total > 100000:
                raise UsdbRuntimeError(f"Unpacked dimensions of {name} exceed the 100000-element limit")
            names = [name + "".join(f"[{i}]" for i in indices) for indices in itertools.product(*dimensions)]
        elif packed and len(packed) == 1:
            names = [f"{name}[{packed[0][0]}:{packed[0][1]}]"]
        else:
            names = [name]
        for query_name in names:
            if query_name in signals:
                raise UsdbRuntimeError(f"Duplicate digital signal path: {query_name}")
            base = re.sub(r"(\[[^\]]*\])*$", "", query_name).rsplit(".", 1)[-1]
            signals[query_name] = UsdbSignal(query_name, base, width)
    return signals


def _parse_scopes(output: str) -> list[UsdbScope]:
    """Keep top-level scope rows from the dap getUsdbHier report."""
    scopes = list(dict.fromkeys(
        line.strip() for line in output.splitlines()
        if line.strip() and not line.strip().startswith(("#", "signal:"))
    ))
    return [UsdbScope(name) for name in scopes if not any(
        other != name and name.startswith(other + ".") for other in scopes
    )]


def _parse_value_blocks(output: str) -> dict[str, list[tuple[int, str]]]:
    """Parse digital trace blocks, rejecting malformed or decreasing-time rows."""
    result: dict[str, list[tuple[int, str]]] = {}
    current = None
    for line in output.splitlines():
        stripped = line.strip()
        signal = re.fullmatch(r"Signal: (.+)", stripped)
        if signal:
            current = signal.group(1)
            result.setdefault(current, [])
            continue
        row = re.fullmatch(r"Time:\s*(\d+)\s+Value:\s*([01xXzZ]+)", stripped)
        if stripped.startswith("Time:"):
            if row is None or current is None:
                raise UsdbRuntimeError(f"Malformed digital value row: {stripped}")
            timestamp, state = int(row.group(1)), row.group(2).lower()
            rows = result[current]
            if rows and timestamp < rows[-1][0]:
                raise UsdbRuntimeError(f"Decreasing timestamps for {current}")
            if rows and timestamp == rows[-1][0]:
                rows[-1] = (timestamp, state)
            else:
                rows.append((timestamp, state))
    return result


class UsdbReader:
    """Context-managed USDB reader driving independent usdbaccess/dap queries.

    Construction performs no I/O. The first metadata query caches time bounds,
    scopes and signals. Value queries use native nonnegative simulation ticks.
    """

    backend_name = "uvd"

    def configure_backend(self, backend_args: BackendArgs) -> dict[str, Any]:
        """Accept defaults and help; this adapter has no advanced options."""
        if backend_args == "help":
            return {"options": {}}
        if not isinstance(backend_args, dict) or backend_args:
            raise WaveformBackendArgumentError("UVD supports only empty backend_args or help.")
        return {}

    def __init__(self, path: str | Path):
        """Bind the USDB path without starting a process or reading the file."""
        self.path = str(path)
        self._metadata: _UsdbMetadata | None = None

    def __enter__(self) -> "UsdbReader":
        """Enter without I/O; every query owns its subprocess resources."""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        """Propagate query failures to the caller."""
        return False

    def _ensure_metadata(self) -> _UsdbMetadata:
        """Load metadata once, publishing the cache only after every query succeeds."""
        if self._metadata is not None:
            return self._metadata
        if not os.path.isfile(self.path):
            raise UsdbRuntimeError(f"USDB file does not exist: {self.path}")
        usdbaccess = _find_tool("usdbaccess")
        _, info = _run_tool([usdbaccess, "-i", self.path, "--info"])
        begin, end = _parse_info(info)
        _, hierarchy = _run_tool([usdbaccess, "-i", self.path, "--hier"])
        signals = _parse_hier(hierarchy)
        dap = _find_tool("dap")
        with tempfile.TemporaryDirectory(prefix="usdb_reader_") as scratch:
            report = os.path.join(scratch, "getUsdbHier.log")
            # dap writes its report in cwd; isolate concurrent readers and stale logs.
            code, output = _run_tool(
                [dap, "getUsdbHier", "-export_scope", "-usdb", str(Path(self.path).resolve())],
                check=False, cwd=scratch,
            )
            if code != 0 or not os.path.isfile(report):
                detail = output.strip().splitlines()
                message = f"exit code {code}" if code != 0 else f"scope report missing: {report}"
                if detail:
                    message += f"; {detail[-1]}"
                raise UsdbRuntimeError(f"dap getUsdbHier failed: {message}")
            scopes = _parse_scopes(Path(report).read_text(encoding="utf-8", errors="replace"))
        self._metadata = _UsdbMetadata(begin, end, scopes, signals)
        return self._metadata

    @property
    def begin_time(self) -> int:
        """Return the first inclusive native simulation tick."""
        return self._ensure_metadata().begin_time

    @property
    def end_time(self) -> int:
        """Return the last inclusive native simulation tick."""
        return self._ensure_metadata().end_time

    @property
    def top_scopes(self) -> list[UsdbScope]:
        """Return top-level scopes from CLI metadata."""
        return self._ensure_metadata().scopes

    def get_matched_signals(
        self, path: str, *, offset: int = 0, limit: int = 100,
    ) -> WaveformSignalMatches:
        """Return a sorted page using shared exact/glob/regex/brace query syntax."""
        if type(offset) is not int or offset < 0:
            raise ValueError("signal offset must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("signal limit must be an integer from 1 to 1000")
        matches = compile_signal_query(path)
        metadata = self._ensure_metadata()
        selected = {name: signal for name, signal in metadata.signals.items() if matches(name)}
        return paginate_signal_matches(selected, offset=offset, limit=limit)

    def load_value_changes(
        self, signal: UsdbSignal, value_mapping: Mapping[str, int],
        begin_time: int | None = None, end_time: int | None = None,
    ) -> WaveformValueChanges:
        """Map all four-state transitions in [begin, end), retaining the prior state.

        Duplicate ticks keep the last state. Repeated mapped values remain in
        the result so value, X-mask and Z-mask reads have identical timestamps.
        """
        if not isinstance(signal, UsdbSignal):
            raise ValueError("signal must be a descriptor from this reader's get_matched_signals")
        if not isinstance(value_mapping, Mapping) or set(value_mapping) != {"0", "1", "x", "z"} or any(
            type(value) is not int or value not in (0, 1) for value in value_mapping.values()
        ):
            raise ValueError("value_mapping must map all 0/1/x/z states to integer bits")
        for name, bound in (("begin_time", begin_time), ("end_time", end_time)):
            if bound is not None and (type(bound) is not int or bound < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if begin_time is not None and end_time is not None and begin_time >= end_time:
            raise ValueError("begin_time must be less than end_time")
        metadata = self._ensure_metadata()
        if metadata.signals.get(signal.full_name) is not signal:
            raise UsdbRuntimeError(f"Signal {signal.full_name} is not from this reader; refresh the signal query")
        if end_time == 0:
            return {"mapped": []}
        usdbaccess = _find_tool("usdbaccess")
        with tempfile.TemporaryDirectory(prefix="usdb_reader_") as scratch:
            listing = os.path.join(scratch, "signals.txt")
            Path(listing).write_text(signal.native_name + "\n", encoding="utf-8")
            command = [usdbaccess, "-i", self.path, "--sg", listing]
            # The CLI retains the predecessor's original timestamp with --begin.
            if begin_time is not None:
                command += ["--begin", str(begin_time)]
            # The CLI end is inclusive; the public reader end is exclusive.
            if end_time is not None:
                command += ["--end", str(end_time - 1)]
            _, output = _run_tool(command)
        blocks = _parse_value_blocks(output)
        if signal.native_name not in blocks:
            raise UsdbRuntimeError(f"usdbaccess omitted the requested signal: {signal.native_name}")
        rows = blocks[signal.native_name]
        mapped = []
        for timestamp, state in rows:
            if end_time is not None and timestamp >= end_time:
                continue
            if len(state) != signal.width:
                raise UsdbRuntimeError(f"usdbaccess returned a {len(state)}-bit state for {signal.width}-bit {signal.full_name}")
            value = 0
            for bit in state:
                value = (value << 1) | value_mapping[bit]
            if begin_time is not None and timestamp <= begin_time and mapped:
                mapped[-1] = (timestamp, value)
            else:
                mapped.append((timestamp, value))
        return {"mapped": mapped}
