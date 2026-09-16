"""Managed child-process execution of pure reference models and public-pin unit tests."""

from __future__ import annotations

import copy
import importlib
import importlib.util
from pathlib import Path
import random
import sys
from vcdvcd import VCDVCD

from ..contracts import atomic_json, load_json
from .models import Interface, TaskContract, Workload, read_model
from .waveforms import unit_activity_waveform, waveform_as_vcd


def load_program(path: Path):
    """Load an already validated task program in the isolated test process."""

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


class PinEnvironment:
    """Expose only declared public pins and record results directly from hardware outputs."""

    __slots__ = ("_dut", "_interface", "_contract", "_transactions", "_accepted", "_results",
                 "_fragments", "_trace", "_cycle", "_initial_tick", "_activity_span")

    def __init__(self, dut, interface: Interface, contract: TaskContract, transactions: list, waveform: Path):
        """Reset one fresh DUT before measuring its interface-independent workload."""

        self._dut = dut
        self._interface = interface
        self._contract = contract
        self._transactions = {t["id"]: t for t in transactions}
        self._accepted = {}
        self._results = {}
        self._fragments = {}
        self._trace = []
        self._cycle = 0
        self._activity_span = None
        dut.GetXPort().AsImmWrite()
        dut.ResumeWaveformDump()
        for name, pin in interface.pins.items():
            if pin.direction == "input":
                getattr(dut, name).value = 0
        if interface.clock:
            dut.InitClock(interface.clock)
        if interface.reset:
            getattr(dut, interface.reset).value = interface.reset_active
        dut.RefreshComb()
        dut.Step(interface.reset_cycles)
        if interface.reset:
            getattr(dut, interface.reset).value = 1 - interface.reset_active
        dut.RefreshComb()
        # The reset anchor is derived after Finish() from step-edge counting:
        # FST sessions cannot be reopened while the writer is active.

    @property
    def cycle(self) -> int:
        """Return elapsed cycles since the managed initial reset."""

        return self._cycle

    def drive(self, **values: int) -> None:
        """Drive public input pins with explicit packed values and refresh combinational logic."""

        for name, value in values.items():
            pin = self._interface.pins.get(name)
            if pin is None or pin.direction != "input" or name == self._interface.clock:
                raise ValueError(f"Not a writable public input: {name}")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1 << pin.width:
                raise ValueError(f"Input value is outside packed pin width: {name}={value}")
            getattr(self._dut, name).value = value
        self._dut.RefreshComb()
        self._trace.append({"cycle": self.cycle, "drive": values})
        if self._activity_span is None:
            self._activity_span = [self.cycle, self.cycle]

    def read(self, name: str) -> int:
        """Read one declared pin without granting access to internal DUT state."""

        if name not in self._interface.pins:
            raise ValueError(f"Not a declared public pin: {name}")
        self._dut.RefreshComb()
        return int(getattr(self._dut, name).value)

    def tick(self, count: int = 1) -> None:
        """Advance clock cycles within the frozen workload deadline."""

        if type(count) is not int or count < 1 or self.cycle + count > self._contract.max_cycles:
            raise ValueError("Unit test exceeded contract.max_cycles or requested invalid tick count")
        if self._transactions and len(self._results) == len(self._transactions):
            end_cycle = max(row["completed_cycle"] for row in self._results.values()) + 1
            if self.cycle + count > end_cycle:
                raise ValueError("Do not append idle cycles after the last logical response")
        for _ in range(count):
            self._dut.Step(1)
            self._dut.RefreshComb()
            self._cycle += 1
        if self._activity_span is not None:
            self._activity_span[1] = self.cycle

    def accept(self, transaction_id: str) -> None:
        """Record an offered transaction only when its release and public handshake permit it."""

        if transaction_id not in self._transactions or transaction_id in self._accepted:
            raise ValueError(f"Unknown or duplicate accepted transaction: {transaction_id}")
        if self.cycle < self._transactions[transaction_id]["release_cycle"]:
            raise ValueError(f"Transaction launched before its frozen release cycle: {transaction_id}")
        for pin, value in self._interface.request_when.items():
            if self.read(pin) != value:
                raise ValueError(f"Request handshake not satisfied at {pin}")
        self._accepted[transaction_id] = self.cycle

    def sample(self, transaction_id: str, fields: dict) -> None:
        """Capture logical result bits exclusively from declared output pins.

        A field maps to a pin name or {pin, lsb, width, offset}. Fragments support
        serialization across cycles without letting adapters calculate expected results.
        """

        if transaction_id not in self._accepted or transaction_id in self._results:
            raise ValueError(f"Response has no pending accepted request: {transaction_id}")
        for pin, value in self._interface.response_when.items():
            if self.read(pin) != value:
                raise ValueError(f"Response handshake not satisfied at {pin}")
        if not fields:
            raise ValueError("sample must capture at least one logical field")
        parts = self._fragments.setdefault(transaction_id, {})
        for field, selection in fields.items():
            spec = self._contract.result_fields.get(field)
            if spec is None:
                raise ValueError(f"Unknown logical result field: {field}")
            selection = {"pin": selection} if isinstance(selection, str) else selection
            if not isinstance(selection, dict) or set(selection) - {"pin", "lsb", "width", "offset"}:
                raise ValueError("sample selection must contain pin and optional lsb, width, offset")
            name = selection["pin"]
            pin = self._interface.pins.get(name)
            if pin is None or pin.direction != "output":
                raise ValueError(f"Results must originate from a declared output pin: {name}")
            width, lsb, offset = selection.get("width", pin.width), selection.get("lsb", 0), selection.get("offset", 0)
            if any(type(v) is not int for v in (width, lsb, offset)) or width < 1 or min(lsb, offset) < 0 or lsb + width > pin.width or offset + width > spec.width:
                raise ValueError(f"Result fragment exceeds pin or logical field width: {field}")
            mask = ((1 << width) - 1) << offset
            value, old_mask = parts.get(field, (0, 0))
            if old_mask & mask:
                raise ValueError(f"Result bits sampled twice: {transaction_id}/{field}")
            value |= ((self.read(name) >> lsb) & ((1 << width) - 1)) << offset
            parts[field] = (value, old_mask | mask)
        if all(parts.get(name, (0, 0))[1] == (1 << spec.width) - 1
               for name, spec in self._contract.result_fields.items()):
            if self._contract.ordering == "in_order" and transaction_id != list(self._transactions)[len(self._results)]:
                raise ValueError(f"Response violates in_order semantics: {transaction_id}")
            values = {}
            for field, spec in self._contract.result_fields.items():
                value = parts[field][0]
                values[field] = value - (1 << spec.width) if spec.signed and value >> (spec.width - 1) else value
            self._results[transaction_id] = {"values": values, "accepted_cycle": self._accepted[transaction_id],
                                             "completed_cycle": self.cycle}

    def finish(self) -> dict:
        """Require all requests to complete and return measured results and physical stimuli."""

        if set(self._results) != set(self._transactions):
            raise ValueError(f"Incomplete unit workload: pending={sorted(set(self._transactions) - set(self._results))}")
        if self.cycle <= max(row["completed_cycle"] for row in self._results.values()):
            self.tick()
        self._dut.FlushWaveform()
        span = self._activity_span or [self.cycle - 1, self.cycle]
        return {"results": self._results, "cycles": self.cycle, "input_trace": self._trace,
                "activity_span": span}


def main() -> None:
    """Execute reference self-tests or one compiled unit's complete managed test suite."""

    operation, root_arg = sys.argv[1:]
    root = Path(root_arg).resolve()
    contract = read_model(root, "contract.yaml", TaskContract)
    workload = read_model(root, "verification/workload.yaml", Workload)
    if operation == "reference":
        reference = load_program(root / "verification/reference.py")
        expected = {}
        for scenario in workload.scenarios:
            transactions = [t.model_dump() for t in scenario.transactions]
            random.seed(workload.seed)
            values = reference.evaluate(copy.deepcopy(transactions))
            random.seed(workload.seed)
            if values != reference.evaluate(copy.deepcopy(transactions)):
                raise ValueError(f"Reference is not deterministic: {scenario.name}")
            if not isinstance(values, dict) or set(values) != {t.id for t in scenario.transactions}:
                raise ValueError(f"Reference results must cover exactly every transaction: {scenario.name}")
            for transaction_id, result in values.items():
                if not isinstance(result, dict) or set(result) != set(contract.result_fields):
                    raise ValueError(f"Reference result fields differ from contract: {transaction_id}")
                for field, value in result.items():
                    spec = contract.result_fields[field]
                    lower, upper = (-(1 << (spec.width - 1)), 1 << (spec.width - 1)) if spec.signed else (0, 1 << spec.width)
                    if type(value) is not int or not lower <= value < upper:
                        raise ValueError(f"Reference result is outside field width: {transaction_id}/{field}")
            for transaction_id, example in scenario.expected_examples.items():
                if values[transaction_id] != example:
                    raise ValueError(f"Reference self-test failed: {scenario.name}/{transaction_id}")
            expected[scenario.name] = values
        atomic_json(root / "expected.json", expected)
        return
    if operation != "rtl":
        raise ValueError("Runner operation must be reference or rtl")
    interface = read_model(root / "candidate", "interface.yaml", Interface)
    adapter = load_program(root / "candidate/adapter.py")
    protocol = load_program(root / "candidate/protocol.py")
    sys.path.insert(0, str(root / "run/design_with_ppa/python-dut"))
    factory = getattr(importlib.import_module("unit_runtime"), "DUT" + interface.top)
    expected = load_json(root / "expected.json")
    results = {"protocol_tests": [], "scenarios": {}}
    waves = root / "waves"
    waves.mkdir()
    for name in sorted(n for n in vars(protocol) if n.startswith("test_")):
        dut = factory()
        try:
            dut.SetWaveform(str(waves / (name + ".fst")))
            env = PinEnvironment(dut, interface, contract, [], waves / (name + ".fst"))
            getattr(protocol, name)(env)
            results["protocol_tests"].append(name)
        finally:
            dut.Finish()
    for scenario in workload.scenarios:
        dut = factory()
        wave = waves / (scenario.name + ".fst")
        try:
            dut.SetWaveform(str(wave))
            transactions = [t.model_dump() for t in scenario.transactions]
            env = PinEnvironment(dut, interface, contract, transactions, wave)
            random.seed(workload.seed)
            adapter.run(env, copy.deepcopy(transactions))
            result = env.finish()
            observed = {key: row["values"] for key, row in result["results"].items()}
            if observed != expected[scenario.name]:
                raise ValueError(f"Unit semantic mismatch in {scenario.name}: expected={expected[scenario.name]}, observed={observed}")
            result["waveform"] = wave.relative_to(root).as_posix()
            results["scenarios"][scenario.name] = result
        finally:
            dut.Finish()
        activity = waves / (scenario.name + "-activity.vcd")
        result["waveform_alignment"] = unit_activity_waveform(
            wave, activity, interface, activity_span=result["activity_span"],
            clock_period_ns=contract.clock_period_ns)
        result["initial_native_tick"] = result["waveform_alignment"]["native_start_tick"]
        result["raw_waveform"] = result["waveform"]
        result["waveform"] = activity.relative_to(root).as_posix()
        # Native dumps only feed the sealed activity projection; their identity
        # is preserved in waveform_alignment (raw_sha256). Remove the raw and
        # any temporary converted copy so a measured workspace never
        # accumulates large waveforms.
        wave.unlink()
        wave.with_suffix(".vcd").unlink(missing_ok=True)
    atomic_json(root / "unit_results.json", results)


if __name__ == "__main__":
    main()
