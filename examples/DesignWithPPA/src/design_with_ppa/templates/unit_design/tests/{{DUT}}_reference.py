"""Pin-compatible Python executable specification for {{DUT}}."""

from design_with_ppa import PinSpec, ReferenceDUT


class {{DUT}}Reference(ReferenceDUT):
    """Model the exact pins, combinational logic, and active-edge state."""

    PIN_SPECS = (
        # Replace these examples with every architecture port.
        # PinSpec("clk_i", "input"),
        # PinSpec("rst_ni", "input"),
        # PinSpec("data_i", "input", width=8),
        # PinSpec("data_o", "output", width=8),
    )

    def __init__(self):
        """Initialize declared pins and all deterministic internal state."""

        super().__init__()
        # Pin attributes are immutable ReferencePin objects. Always update a
        # pin through ``pin.value`` or ``drive_output(name, value)``; assigning
        # ``self.<pin> = ...`` replaces a pin and is rejected by ReferenceDUT.
        # Initialize model state defined by the architecture contract.

    def reset(self):
        """Restore pins and model state according to the reset contract."""

        self.reset_pins()
        self.cycle = 0
        # Restore model state, then expose reset-state combinational outputs.
        self.RefreshComb()

    def _refresh_comb(self):
        """Evaluate combinational outputs from current pins and model state."""

        raise NotImplementedError("Implement the complete combinational specification")

    def _step(self):
        """Apply one active clock edge without an implicit comb refresh."""

        raise NotImplementedError("Implement the complete active-edge specification")

    def _capture_model_state(self):
        """Return every non-pin state value needed by CheckPoint/Restore."""

        raise NotImplementedError("Return complete deterministic model state")

    def _restore_model_state(self, state):
        """Restore the value returned by _capture_model_state."""

        del state
        raise NotImplementedError("Restore complete deterministic model state")
