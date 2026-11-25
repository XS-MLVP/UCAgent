"""Focused contracts for the backend-neutral executable reference DUT."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from design_with_ppa.python_dut import (
    PinSpec,
    PythonDUTError,
    ReferenceDUT,
    create_dut,
)


class _RegisterReference(ReferenceDUT):
    """Small stateful model used to prove refresh, edge, and restore ordering."""

    PIN_SPECS = (
        PinSpec("data_i", "input", width=4),
        PinSpec("comb_o", "output", width=4),
        PinSpec("state_o", "output", width=4),
    )

    def __init__(self) -> None:
        """Initialize one internal register and refresh counter."""

        super().__init__()
        self.state = 0
        self.refresh_count = 0

    def _refresh_comb(self) -> None:
        """Expose current input and registered state without advancing time."""

        self.refresh_count += 1
        self.drive_output("comb_o", self.data_i.value)
        self.drive_output("state_o", self.state)

    def _step(self) -> None:
        """Capture the current input on one active edge."""

        self.state = self.data_i.value

    def _capture_model_state(self) -> dict[str, int]:
        """Save subclass state in a deterministic mapping."""

        return {"state": self.state, "refresh_count": self.refresh_count}

    def _restore_model_state(self, state: object) -> None:
        """Restore the mapping emitted by ``_capture_model_state``."""

        assert isinstance(state, dict)
        self.state = int(state["state"])
        self.refresh_count = int(state["refresh_count"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "not-port"},
        {"name": "a", "direction": "sink"},
        {"name": "a", "direction": "input", "width": True},
        {"name": "a", "direction": "input", "width": 0},
        {"name": "a", "direction": "input", "signed": 1},
        {"name": "a", "direction": "input", "width": 2, "initial": 4},
    ],
)
def test_pin_spec_rejects_nonportable_declarations(kwargs: dict) -> None:
    """Invalid names, directions, widths, flags, and reset values must fail."""

    defaults = {"name": "a", "direction": "input"}
    defaults.update(kwargs)
    with pytest.raises(PythonDUTError):
        PinSpec(**defaults)


def test_reference_pin_values_are_width_checked_packed_patterns() -> None:
    """Signed pins accept signed values and explicit packed unsigned patterns."""

    dut = ReferenceDUT((PinSpec("signed_i", "input", width=4, signed=True),))
    dut.signed_i.value = -1
    assert dut.signed_i.value == 0xF
    assert int(dut.signed_i) == 0xF
    dut.signed_i.value = 0x8
    assert dut.signed_i.value == 0x8
    with pytest.raises(PythonDUTError):
        dut.signed_i.value = -9
    with pytest.raises(TypeError):
        dut.signed_i.value = 1.5
    with pytest.raises(AttributeError, match="assign signed_i.value"):
        dut.signed_i = 0


def test_immediate_write_refresh_and_step_order_is_explicit() -> None:
    """Writing, refreshing, stepping, and post-edge refreshing stay distinct."""

    dut = _RegisterReference()
    assert dut.GetXPort().AsImmWrite()["data_i"] is dut.data_i
    dut.data_i.value = 7
    assert dut.comb_o.value == 0
    assert dut.state_o.value == 0

    dut.RefreshComb()
    assert dut.cycle == 0
    assert dut.comb_o.value == 7
    assert dut.state_o.value == 0

    dut.Step(1)
    assert dut.cycle == 1
    assert dut.state == 7
    assert dut.state_o.value == 0

    dut.RefreshComb()
    assert dut.cycle == 1
    assert dut.state_o.value == 7


def test_edge_callbacks_receive_cycle_then_registered_arguments() -> None:
    """Reference callbacks match the shared cycle-first callback signature."""

    dut = _RegisterReference()
    observed: list[tuple[str, int, str]] = []
    dut.StepRis(
        lambda cycle, label, *, suffix: observed.append(
            ("rise", cycle, f"{label}{suffix}")
        ),
        args=("r",),
        kwargs={"suffix": "1"},
    )
    dut.StepFal(
        lambda cycle, label: observed.append(("fall", cycle, label)),
        args=("f",),
    )

    dut.Step(2)

    assert observed == [
        ("rise", 1, "r1"),
        ("fall", 1, "f"),
        ("rise", 2, "r1"),
        ("fall", 2, "f"),
    ]


def test_checkpoint_restores_pins_cycle_and_subclass_state() -> None:
    """A checkpoint is complete enough for deterministic reference replay."""

    dut = _RegisterReference()
    dut.data_i.value = 3
    dut.RefreshComb()
    dut.Step()
    assert dut.CheckPoint("accepted") == 0
    dut.data_i.value = 9
    dut.RefreshComb()
    dut.Step()
    assert dut.state == 9

    assert dut.Restore("accepted") == 0

    assert dut.cycle == 1
    assert dut.data_i.value == 3
    assert dut.state == 3
    assert dut.refresh_count == 1
    with pytest.raises(PythonDUTError, match="does not exist"):
        dut.Restore("missing")


def test_python_factory_requires_a_reference_dut() -> None:
    """The public factory validates the executable reference implementation."""

    assert isinstance(create_dut("python", _RegisterReference), _RegisterReference)
    with pytest.raises(PythonDUTError, match="return a ReferenceDUT"):
        create_dut("python", lambda: object())
    with pytest.raises(PythonDUTError, match="backend must"):
        create_dut("unknown", _RegisterReference)


def test_rtl_factory_uses_only_managed_subprocess_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RTL construction cannot accept a caller-selected module or class path."""

    class _Port:
        """Record immediate-write activation from the factory."""

        immediate = False

        def AsImmWrite(self):
            """Enable immediate writes and return the port view."""

            self.immediate = True
            return self

    class _RTL:
        """Provide the minimum managed DUT surface."""

        def __init__(self) -> None:
            """Create one port view."""

            self.port = _Port()

        def GetXPort(self):
            """Return the port view."""

            return self.port

        def RefreshComb(self):
            """Model the managed combinational refresh method."""

        def Step(self, count=1):
            """Model the managed edge step method."""

            del count

        def Finish(self):
            """Model the managed lifecycle method."""

    module = ModuleType("managed_dut")
    module.DUTmanaged_dut = _RTL
    monkeypatch.setitem(sys.modules, "managed_dut", module)
    monkeypatch.setenv("_DESIGN_WITH_PPA_RTL_DUT_MODULE", "managed_dut")
    monkeypatch.setenv("_DESIGN_WITH_PPA_RTL_DUT_CLASS", "DUTmanaged_dut")

    dut = create_dut("rtl", _RegisterReference)

    assert isinstance(dut, _RTL)
    assert dut.port.immediate is True


def test_rtl_factory_and_reference_waveforms_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent managed identity and reference waveform attempts are rejected."""

    monkeypatch.delenv("_DESIGN_WITH_PPA_RTL_DUT_MODULE", raising=False)
    monkeypatch.delenv("_DESIGN_WITH_PPA_RTL_DUT_CLASS", raising=False)
    with pytest.raises(PythonDUTError, match="Check or Complete"):
        create_dut("rtl", _RegisterReference)

    dut = _RegisterReference()
    with pytest.raises(PythonDUTError, match="cannot produce RTL waveform"):
        dut.SetWaveform("forbidden.vcd")
    dut.Finish()
    dut.Finish()
    with pytest.raises(PythonDUTError, match="already been finished"):
        dut.RefreshComb()
