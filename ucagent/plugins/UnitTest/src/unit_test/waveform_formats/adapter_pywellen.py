"""Digital signal decoding and bounded advanced information through pywellen."""

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import re
from typing import Any

from .pagination import DEFAULT_SIGNAL_LIMIT, paginate_signal_matches
from .protocols import BackendArgs, WaveformBackendArgumentError, WaveformSignalMatches, WaveformValueChanges
from .queries import compile_signal_query


@dataclass(frozen=True)
class _WellenSignal:
    """Stable digital descriptor containing paths and indices, without native handles."""

    full_name: str
    base_name: str
    width: int
    native_name: str
    indices: tuple[int, int]
    selected_indices: tuple[int, int]


class PywellenReaderAdapter(AbstractContextManager):
    """Read selected digital traces while retaining native timestamps and HDL ranges."""

    backend_name = 'pywellen'

    def __init__(self, path: str) -> None:
        """Store the exact file; format subclasses supply metadata before entry."""
        self.path = path
        self._wave = None
        self._variables = {}
        self._signals = {}
        self._options = {}
        self._declarations = {}
        self._begin_time = 0
        self._end_time = 0

    def _add_declaration(self, name: str, width: int) -> None:
        """Retain format declarations, distinguishing scalar indices from arrays."""
        name = re.sub(r'\s+(?=\[)', '', name)
        match = re.fullmatch(r'(.+)\[(-?\d+)(?::(-?\d+))?\]', name)
        if match and (match.group(3) is not None or width == 1):
            base, left, right = match.groups()
            indices = (int(left), int(left if right is None else right))
        else:
            base = name
            indices = (width - 1, 0)
            if width > 1:
                name = f'{name}[{width - 1}:0]'
        self._declarations.setdefault(base, []).append((name, indices))

    def __enter__(self):
        """Open pywellen lazily and build descriptors without loading signal values."""
        import pywellen

        try:
            self._wave = pywellen.Waveform(self.path)
            for var in self._wave.all_vars():
                if not var.is_bit_vector or not var.bitwidth:
                    continue
                width = int(var.bitwidth)
                name = re.sub(r'\s+(?=\[)', '', var.full_name)
                # Wellen represents unpacked array elements as synthetic scopes.
                # Restore the file declaration only when metadata proves that path.
                declared_name = name.replace('.[', '[')
                if declared_name in self._declarations:
                    name = declared_name
                base = name if name in self._declarations else re.sub(r'\[-?\d+:-?\d+\]$', '', name)
                declarations = self._declarations.get(base)
                if not declarations:
                    raise ValueError(f'Missing declaration metadata for {name}')
                indices = declarations[0][1]
                if len(declarations) > 1:
                    # Wellen merges contiguous scalar declarations into one vector,
                    # in descending index order. Preserve each original public path.
                    positions = [bounds[0] for _, bounds in declarations]
                    if any(left != right for _, (left, right) in declarations) or len(set(positions)) != width:
                        raise ValueError(f'Ambiguous declaration metadata for {name}')
                    indices = (max(positions), min(positions))
                if abs(indices[0] - indices[1]) + 1 != width:
                    raise ValueError(f'Declared range disagrees with width for {name}')
                self._variables[var.full_name] = var
                for full_name, selected in declarations:
                    if full_name in self._signals:
                        raise ValueError(f'Duplicate digital signal path: {full_name}')
                    self._signals[full_name] = _WellenSignal(
                        full_name, base.rsplit('.', 1)[-1], abs(selected[0] - selected[1]) + 1,
                        var.full_name, indices, selected,
                    )
            return self
        except BaseException as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        """Drop all native owners, including those allocated before an entry failure."""
        self._variables.clear()
        self._signals.clear()
        self._wave = None
        # PyO3 native parse panics derive directly from BaseException and their
        # type is not importable. Convert only that error, preserving interrupts.
        if exc_type is not None and (exc_type.__module__, exc_type.__name__) == ('pyo3_runtime', 'PanicException'):
            raise ValueError(f'pywellen could not decode the selected waveform: {exc_value}') from exc_value
        return False

    @property
    def begin_time(self) -> int:
        """Return the file's first timestamp, including time without value changes."""
        return self._begin_time

    @property
    def end_time(self) -> int:
        """Return the file's last timestamp, including a final unchanged interval."""
        return self._end_time

    @property
    def top_scopes(self):
        """Return actual top-level hierarchy scopes from pywellen metadata."""
        return self._wave.scopes()

    def configure_backend(self, backend_args: BackendArgs) -> dict[str, Any]:
        """Describe or enable bounded signal metadata and per-window statistics."""
        if backend_args == 'help':
            return {
                'options': {
                    'signal_metadata': {'type': 'boolean', 'default': False, 'description': 'Return hierarchy, declaration type, direction, indices, and enum metadata for the current signal page.'},
                    'statistics': {'type': 'boolean', 'default': False, 'description': 'Return source-state counts for each loaded signal and read window.'},
                },
                'examples': [
                    {'backend_args': {'signal_metadata': True}, 'include_extensions': True},
                    {'backend_args': {'statistics': True}, 'include_extensions': True},
                ],
            }
        if (
            not isinstance(backend_args, dict)
            or set(backend_args) - {'signal_metadata', 'statistics'}
            or any(type(value) is not bool for value in backend_args.values())
        ):
            raise WaveformBackendArgumentError('Unknown advanced option or invalid value; request backend_args="help" for supported options.')
        self._options = dict(backend_args)
        return {}

    def get_matched_signals(self, path: str, *, offset: int = 0, limit: int = DEFAULT_SIGNAL_LIMIT) -> WaveformSignalMatches:
        """Resolve common queries and return only the selected descriptor/metadata page."""
        matches = compile_signal_query(path)
        signals = {name: signal for name, signal in self._signals.items() if matches(name)}
        # Exact bit/slice queries select declared HDL indices, including ascending
        # and negative ranges, without changing the native descriptor's lifetime.
        selection = re.fullmatch(r'(.+)\[(-?\d+)(?::(-?\d+))?\]', path)
        if not signals and selection:
            base, first, last = selection.groups()
            first, last = int(first), int(first if last is None else last)
            for signal in self._signals.values():
                if re.sub(r'\[-?\d+:-?\d+\]$', '', signal.full_name) != base:
                    continue
                low, high = sorted(signal.indices)
                if not low <= first <= high or not low <= last <= high:
                    raise ValueError('Selected indices are outside the declared signal range')
                if first != last and (first < last) != (signal.indices[0] < signal.indices[1]):
                    raise ValueError('Selected indices must follow the declaration direction')
                name = f'{base}[{first}]' if first == last else f'{base}[{first}:{last}]'
                signals[name] = _WellenSignal(name, signal.base_name, abs(first - last) + 1, signal.native_name, signal.indices, (first, last))
        result = paginate_signal_matches(signals, offset=offset, limit=limit)
        if self._options.get('signal_metadata') and result['signals']:
            metadata = {}
            for signal in result['signals'].values():
                var = self._variables[signal.native_name]
                enum_type = var.enum_type
                metadata[signal.full_name] = {
                    'parent_scope': signal.native_name.rpartition('.')[0],
                    'var_type': var.var_type, 'direction': var.direction,
                    'declared_indices': list(signal.indices),
                    'selected_indices': list(signal.selected_indices),
                    'enum_type': [enum_type[0], [list(pair) for pair in enum_type[1]]] if enum_type is not None else None,
                    'vhdl_type_name': var.vhdl_type_name,
                }
            result['extensions'] = {'signal_metadata': metadata}
        return result

    def load_value_changes(
        self, signal: _WellenSignal, value_mapping: Mapping[str, int],
        begin_time: int | None = None, end_time: int | None = None,
    ) -> WaveformValueChanges:
        """Map every source transition, retaining the state before a bounded window."""
        if set(value_mapping) != {'0', '1', 'x', 'z'} or any(type(v) is not int or v not in (0, 1) for v in value_mapping.values()):
            raise ValueError('value_mapping must map all 0/1/x/z states to integer bits')
        var = self._variables[signal.native_name]
        rows = var.signal
        # Native Signal implements indexed access; binary search avoids copying
        # the complete trace just to select a narrow window.
        start = 0 if begin_time is None else max(0, bisect_right(rows, begin_time, key=lambda row: row[0]) - 1)
        stop = len(rows) if end_time is None else bisect_left(rows, end_time, key=lambda row: row[0])
        native_width = abs(signal.indices[0] - signal.indices[1]) + 1
        direction = 1 if signal.indices[1] >= signal.indices[0] else -1
        left = (signal.selected_indices[0] - signal.indices[0]) * direction
        right = (signal.selected_indices[1] - signal.indices[0]) * direction + 1
        mapped = []
        unknown_states = 0
        for index in range(start, stop):
            timestamp, raw = rows[index]
            bits = format(raw, f'0{native_width}b') if isinstance(raw, int) else str(raw).lower()
            padding = bits[0] if bits and bits[0] in 'xz' else '0'
            if not bits or len(bits) > native_width or set(bits) - set('01xz'):
                raise ValueError(f'Invalid digital state for {signal.full_name}')
            bits = bits.rjust(native_width, padding)[left:right]
            unknown_states += bool(set(bits) & set('xz'))
            value = 0
            for bit in bits:
                value = (value << 1) | value_mapping[bit]
            mapped.append((int(timestamp), value))
        result = {'mapped': mapped}
        if self._options.get('statistics'):
            result['extensions'] = {'statistics': {
                'source_states': len(mapped), 'unknown_states': unknown_states,
                'first_timestamp': mapped[0][0] if mapped else None,
                'last_timestamp': mapped[-1][0] if mapped else None,
                'begin_time': begin_time, 'end_time_exclusive': end_time,
            }}
        return result
