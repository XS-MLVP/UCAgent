"""Backend-independent waveform reader, value-change, and factory contracts."""

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, Literal, NotRequired, Protocol, TypedDict


BackendArgs = dict[str, Any] | Literal["help"]


class WaveformBackendArgumentError(ValueError):
    """Unsupported advanced options; the caller should request backend_args='help'."""


class WaveformScope(Protocol):
    """A hierarchy scope identified by its full dotted path."""

    @property
    def full_name(self) -> str:
        """Return the full scope path, such as ``TOP.dut``."""
        ...


class WaveformSignal(Protocol):
    """Read-only metadata for a digital signal, possibly with backend handles."""

    @property
    def full_name(self) -> str:
        """Return the exact full dotted signal path, including declared indices."""
        ...

    @property
    def base_name(self) -> str:
        """Return the unqualified signal name used for clock-name hints."""
        ...

    @property
    def width(self) -> int:
        """Return the positive number of bits in the selected signal."""
        ...


class WaveformSignalMatches(TypedDict):
    """Resolved signal descriptors and optional query-related information.

    ``signals`` contains one page ordered by unique full signal path, retaining
    backend-defined mapping keys. ``total`` counts all matches before paging;
    ``offset`` and ``limit`` echo the requested half-open page range.
    ``extensions`` can describe the selected page's hierarchy, related signals,
    or bounded query-wide information. All nested objects use string keys and
    JSON-native values (objects, arrays, scalars, or null), with no tuples or NaN.
    Extensions must not contain native descriptors, handles, or secrets. WaveInfo announces
    nonempty extensions and returns their contents with ``include_extensions=True``.
    """

    signals: Mapping[Any, WaveformSignal]
    total: int
    offset: int
    limit: int
    extensions: NotRequired[dict[str, Any]]


class WaveformValueChanges(TypedDict):
    """One mapped digital trace and optional backend information.

    ``mapped`` yields ascending ``(native_timestamp, mapped_integer)`` pairs.
    ``extensions``, when supplied, is a dictionary of backend-defined fields
    with string keys at every level and JSON-native values (objects, arrays,
    scalars, or null), with no tuples or NaN. It must describe this signal,
    mapping, and read window, and must not contain secrets or native objects.
    WaveInfo announces nonempty extensions and returns their contents only when
    ``include_extensions=True``. Empty traces use an empty iterable.
    """

    mapped: Iterable[tuple[int, int]]
    extensions: NotRequired[dict[str, Any]]


class WaveformReader(Protocol):
    """Minimal reader surface consumed by WaveInfo, independent of its library.

    All timestamps are nonnegative integers in the file's native simulation
    ticks, never DUT cycles or converted wall-clock units. Signal descriptors
    returned by this reader remain valid until its factory context exits.
    """

    @property
    def backend_name(self) -> str:
        """Return the registered implementation name for operator execution logs."""
        ...

    def configure_backend(self, backend_args: BackendArgs) -> dict[str, Any]:
        """Configure one analysis call and return JSON-serializable extensions.

        Input example: ``{"signal_metadata": True, "statistics": True}``.
        The dictionary is isolated to this opened reader. Reject unknown keys,
        invalid values, file access, execution, or changes to standard evidence
        semantics with WaveformBackendArgumentError. Empty input requests defaults.
        The literal ``"help"`` only describes options; it must not load traces.

        Output example for ``"help"``::

            {"options": {"signal_metadata": {"type": "boolean", "default": False}},
             "examples": [{"backend_args": {"signal_metadata": True}}]}

        Ordinary output is exposed under extensions.backend with the usual
        default-hidden policy. Explicit help is always visible there, even when
        include_extensions=False. Subsequent signal/value queries can return
        option-dependent extensions scoped to their page, signal, and window.
        Readers with no advanced features accept {} and help, report an empty
        options mapping, and reject nonempty dictionaries. Never mutate input.
        """
        ...

    @property
    def begin_time(self) -> int:
        """Return the first inclusive native simulation timestamp."""
        ...

    @property
    def end_time(self) -> int:
        """Return the last inclusive native simulation timestamp."""
        ...

    @property
    def top_scopes(self) -> Sequence[WaveformScope]:
        """Return the real top-level hierarchy scopes, or an empty sequence."""
        ...

    def get_matched_signals(
        self, path: str, *, offset: int = 0, limit: int = 100,
    ) -> WaveformSignalMatches:
        """Resolve a signal query and return descriptors plus optional extensions.

        Input:
            ``path`` is an exact dotted path or a query using ``*``, recursive
            ``**``, ``/{regex}/``, or brace alternatives/ranges.
            ``offset`` is a nonnegative integer; ``limit`` is an integer from
            1 to 1000. The default page is [0, 100), ordered by full signal path.

        Output:
            A ``WaveformSignalMatches`` dictionary with required ``signals``,
            ``total``, ``offset``, ``limit``, and optional ``extensions``.
            Return exactly min(limit, max(total - offset, 0)) descriptors;
            ``total`` counts all matches, not just the selected page. Mapping
            keys are backend-defined and ignored by WaveInfo; values expose full_name,
            base_name, and width. No matches or an offset beyond total return
            an empty signals mapping with the actual total and requested bounds.
            Query extensions may still explain the hierarchy or related candidates.
            Invalid queries raise an exception. Querying must not load traces
            or invalidate previously returned signal descriptors.
            Extensions must describe the selected page or bounded query-wide
            facts, rather than include details for every omitted signal.

        Example input::

            reader.get_matched_signals("TOP.dut.data[7:0]", offset=0, limit=100)

        Example output (the descriptor may also retain private backend handles)::

            from types import SimpleNamespace

            data_signal = SimpleNamespace(
                full_name="TOP.dut.data[7:0]", base_name="data", width=8,
            )
            {
                "signals": {"data": data_signal},
                "total": 1,
                "offset": 0,
                "limit": 100,
                "extensions": {
                    "hierarchy": {
                        "TOP.dut.data[7:0]": {"parent_scope": "TOP.dut"},
                    },
                    "related_signals": {
                        "TOP.dut.data[7:0]": ["TOP.dut.valid", "TOP.dut.ready"],
                    },
                },
            }

        Extension dictionaries belong to the query, not to its mapping keys.
        Use exact signal paths inside them to identify associated signals.
        For 250 matches, offset=100 and limit=100 return indices [100, 200),
        total=250, and 50 remaining matches. The next offset is 200. Backends
        without native paging can use ``paginate_signal_matches``.
        """
        ...

    def load_value_changes(
        self,
        signal: WaveformSignal,
        value_mapping: Mapping[str, int],
        begin_time: int | None = None,
        end_time: int | None = None,
    ) -> WaveformValueChanges:
        """Return mapped value changes and optional extension fields.

        Input:
            ``signal`` is a descriptor from this reader's result["signals"].
            ``value_mapping`` contains all four lowercase ``0/1/x/z`` keys
            with integer bit values. ``begin_time`` is an optional inclusive
            start and ``end_time`` an optional exclusive end, in native ticks.

        Output:
            A ``WaveformValueChanges`` dictionary with required ``mapped``
            rows and optional JSON-serializable ``extensions`` describing this
            signal, mapping, and window. Map each source bit then assemble the
            unsigned integer in declared bit order. Return every source
            transition, including repeated mapped values: WaveInfo loads value,
            X mask, and Z mask separately and aligns their timestamps. Preserve
            full integer precision for wide signals and times.

        ``None`` bounds mean unbounded. A bounded load includes the latest state
        at or before ``begin_time``, using its original timestamp, followed by
        changes strictly before the exclusive ``end_time``. Return no rows when
        the signal has no state in that range. Loading must not change metadata
        or interfere with subsequent loads of the same signal.

        Example input (source states: 0 -> 8'b00000000,
        10 -> 8'b00000011, 20 -> 8'b0000xz01, 30 -> 8'b11111111)::

            signal = reader.get_matched_signals("TOP.dut.data[7:0]")["signals"]["data"]
            reader.load_value_changes(
                signal,
                {"0": 0, "1": 1, "x": 0, "z": 0},
                begin_time=15,
                end_time=30,
            )

        Example output (retain the state at 10; exclude the change at 30)::

            {
                "mapped": [(10, 3), (20, 1)],
                "extensions": {
                    "raw_values": [[10, "00000011"], [20, "0000xz01"]],
                    "quality": {"source": "native", "gaps": []},
                },
            }

        The same source under X-mask mapping returns [(10, 0), (20, 8)],
        and under Z-mask mapping returns [(10, 0), (20, 4)]. A backend that
        supplies no extensions returns only ``{"mapped": rows}``.
        """
        ...


class WaveformReaderFactory(Protocol):
    """Callable that opens exactly one selected waveform under resource control.

    A factory accepts a path string (relative to the caller's current directory
    or absolute) and returns a context manager yielding a WaveformReader. The
    context must close file/native resources on normal and exceptional exits and
    release partially opened resources if opening fails. It must propagate read
    errors and must not substitute another file or format. Load optional backend
    dependencies only when invoked/entered, never during registration/import.
    Structural typing permits functions, callable objects, and reader classes;
    no inheritance from UCAgent or wavekit is required.
    """

    def __call__(self, path: str, /) -> AbstractContextManager[WaveformReader]:
        """Create a resource-owning reader context for exactly ``path``."""
        ...
