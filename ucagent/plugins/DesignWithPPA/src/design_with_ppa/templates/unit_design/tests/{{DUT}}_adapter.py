"""One backend-neutral adapter exposing the shared {{DUT}} test API."""

from pathlib import Path
from types import MappingProxyType

from design_with_ppa import create_dut, prepare_native_artifact_path
from {{DUT}}_reference import {{DUT}}Reference


class {{DUT}}Adapter:
    """Expose one backend-neutral environment to APIs, tests, and coverage.

    The selected implementation is private.  Public test code interacts with
    this environment's normalized pins and transaction methods, so a reference
    model may implement a different internal timing sequence than the managed
    RTL object without changing the test contract.
    """

    def __init__(self, backend):
        """Create the selected DUT without backend-specific imports."""

        self.backend = backend
        self._dut = create_dut(backend, {{DUT}}Reference)
        self._dut.GetXPort().AsImmWrite()
        # Register every architecture clock here, before artifact binding,
        # reset, or the first Step. Purely combinational designs register none.
        self._public_pin_names = frozenset(
            spec.name for spec in {{DUT}}Reference.PIN_SPECS
        )
        self.coverage_groups = []
        self.fc_cover = {}
        self.waveform_path = None
        self._waveform_flushed = False
        self._finished = False
        self.cycle = 0
        self.sim_time_ns = 0
        self.last_transaction_timing = None
        self._next_transaction_id = 1
        self._active_transactions = {}
        self._last_event = "initialized"
        self._last_event_data = MappingProxyType({})

    def __getattr__(self, name):
        """Expose declared normalized pins without exposing a public DUT field."""

        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._public_pin_names:
            try:
                return getattr(self._dut, name)
            except AttributeError:
                pass
        raise AttributeError(name)

    @property
    def last_event(self):
        """Return the latest backend-neutral observable event name."""

        return self._last_event

    @property
    def last_event_data(self):
        """Return immutable scalar evidence for the latest event."""

        return self._last_event_data

    def configure_test_artifacts(self, coverage_path, waveform_path):
        """Bind unique RTL evidence paths before the first reset or Step."""

        if self.backend != "rtl":
            return
        # Native writers abort the whole process when an artifact path cannot
        # be opened, so both paths are validated and their parent directories
        # are created on the Python side before reaching the native runtime.
        self.coverage_path = prepare_native_artifact_path(coverage_path, "coverage")
        self.waveform_path = prepare_native_artifact_path(waveform_path, "waveform")
        self._waveform_flushed = False
        self._dut.SetCoverage(str(self.coverage_path))
        self._dut.SetWaveform(str(self.waveform_path))
        self._dut.ResumeWaveformDump()

    def bind_coverage(self, groups):
        """Expose canonical coverage groups through the shared DUT contract."""

        self.coverage_groups = list(groups)
        self.fc_cover = {group.name: group for group in groups}

    def _record_event(self, event, **data):
        """Publish and sample one backend-neutral observable event."""

        if not isinstance(event, str) or not event:
            raise ValueError("coverage event must be a non-empty string")
        self._last_event = event
        self._last_event_data = MappingProxyType(dict(data))
        self.sample_coverage()

    def _record_transaction_accepted(self, accepted_at, **identity):
        """Record one accepted transaction with CK-specific scalar identity."""

        if not identity:
            raise ValueError("accepted transaction evidence requires identity fields")
        reserved = {"transaction_id", "accepted_at", "observed_at", "response_at"}
        if reserved.intersection(identity):
            raise ValueError("accepted transaction identity uses a reserved field")
        transaction_id = self._next_transaction_id
        self._next_transaction_id += 1
        evidence = {
            "transaction_id": transaction_id,
            "accepted_at": accepted_at,
            **identity,
        }
        self._active_transactions[transaction_id] = MappingProxyType(evidence)
        self._record_event("transaction_accepted", **evidence)
        return transaction_id

    def _record_transaction_observation(
        self, transaction_id, observed_at, phase="inflight", **state
    ):
        """Record real in-flight state while retaining accepted-request identity."""

        accepted = self._active_transactions.get(transaction_id)
        if accepted is None:
            raise ValueError("transaction observation refers to an unknown transaction")
        if not isinstance(phase, str) or not phase:
            raise ValueError("transaction observation phase must be a non-empty string")
        reserved = set(accepted) | {"observed_at", "phase", "response_at"}
        if reserved.intersection(state):
            raise ValueError("transaction observation state overwrites identity")
        evidence = {
            **accepted,
            "observed_at": observed_at,
            "phase": phase,
            **state,
        }
        self._record_event("transaction_observation", **evidence)

    def _record_response_observed(self, transaction_id, response_at, **result):
        """Record a response with its accepted identity, then retire the request."""

        accepted = self._active_transactions.pop(transaction_id, None)
        if accepted is None:
            raise ValueError("response refers to an unknown transaction")
        reserved = set(accepted) | {"observed_at", "phase", "response_at"}
        if reserved.intersection(result):
            raise ValueError("response result overwrites accepted transaction identity")
        evidence = {**accepted, "response_at": response_at, **result}
        self._record_event("response_observed", **evidence)

    def reset(self):
        """Apply the architecture reset using shared pin/refresh/step calls."""

        raise NotImplementedError("Implement the architecture reset sequence")

    def start_waveform(self, waveform):
        """Confirm and resume the waveform bound by the fixture before reset."""

        if self.backend != "rtl":
            return
        path = Path(waveform).resolve()
        if path != self.waveform_path:
            raise ValueError("performance TC must use its fixture-owned waveform path")
        self._dut.ResumeWaveformDump()

    def flush_waveform(self):
        """Flush real RTL activity before the performance sidecar is written."""

        if self.backend != "rtl" or self._finished or self._waveform_flushed:
            return
        self._dut.FlushWaveform()
        self._waveform_flushed = True

    def sample_coverage(self):
        """Sample every functional coverage group at the current state."""

        for group in self.coverage_groups:
            group.sample()

    def finish(self):
        """Release backend and per-test coverage resources."""

        if self._finished:
            return
        for group in self.coverage_groups:
            group.clear()
        self._dut.Finish()
        self._finished = True


def create_adapter(backend):
    """Create the backend selected by the pytest fixture."""

    return {{DUT}}Adapter(backend)


def create_python_adapter():
    """Create the executable-reference backend adapter."""

    return create_adapter("python")


def create_rtl_adapter():
    """Create the managed RTL backend adapter for Check/Complete."""

    return create_adapter("rtl")
