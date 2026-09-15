"""Picker-compatible Python-DUT primitives for executable reference models."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from .rtl import _generated_python_dut_identity, _workspace_python_dut_root


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RTL_DUT_MODULE_ENV = "_DESIGN_WITH_PPA_RTL_DUT_MODULE"
_RTL_DUT_CLASS_ENV = "_DESIGN_WITH_PPA_RTL_DUT_CLASS"
_RTL_MANIFEST_RELATIVE = Path(".ucagent/design_with_ppa/rtl_backend_manifest.json")


class PythonDUTError(ValueError):
    """Report an invalid reference-DUT definition or backend selection."""


def prepare_native_artifact_path(path: Any, label: str) -> Path:
    """Resolve one native artifact path and make its parent directory usable.

    The RTL native writers abort the whole process when they cannot open an
    artifact file (for example a coverage path whose directory does not
    exist), silently swallowing every pending pytest diagnostic.  Adapters
    must therefore validate artifact paths on the Python side and hand only
    absolute paths with existing parent directories to the native runtime.
    """

    if not isinstance(path, (str, os.PathLike)):
        raise PythonDUTError(
            f"{label} artifact path must be a string or path-like value, "
            f"got {type(path).__name__}"
        )
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PythonDUTError(
            f"cannot create the {label} artifact directory "
            f"{resolved.parent}: {exc}"
        ) from exc
    return resolved


def register_managed_test_options(parser: Any) -> None:
    """Register the public pytest selector used by managed design tests."""

    parser.addoption(
        "--design-backend",
        choices=("python", "rtl"),
        default="python",
        help="Select the executable-spec or RTL test mode.",
    )


def managed_test_implementation(pytest_config: Any) -> str:
    """Return the validated implementation selected for one pytest run."""

    implementation = pytest_config.getoption("--design-backend")
    if implementation not in {"python", "rtl"}:
        raise PythonDUTError("managed test implementation is invalid")
    return implementation


_EPHEMERAL_BUILD_DIR_RE = re.compile(r"/\.build-[A-Za-z0-9_]+/")


def normalize_line_coverage_source_paths(dat_file: str | os.PathLike[str]) -> None:
    """Point one coverage file at installed sources instead of staging paths.

    The managed RTL runtime compiles in an ephemeral ``.build-*`` staging
    directory and installs the result one level higher, but the native
    runtime records the staging paths inside every coverage ``.dat``.
    Downstream report rendering aborts when a recorded source file no
    longer exists, so rewrite the staging component back to the installed
    location before the file is registered.  Best effort: unreadable or
    unwritable files are left untouched and never fail the test run.
    """

    path = Path(dat_file)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    normalized = _EPHEMERAL_BUILD_DIR_RE.sub("/", text)
    if normalized == text:
        return
    try:
        path.write_text(normalized, encoding="utf-8")
    except OSError:
        pass


def _portable_rtl_dut_identity(
    reference_factory: Callable[[], "ReferenceDUT"],
) -> tuple[Path, str, str]:
    """Resolve and verify a generated RTL runtime from a moved workspace."""

    try:
        reference_source = Path(inspect.getfile(reference_factory)).resolve()
    except (OSError, TypeError) as exc:
        raise PythonDUTError(
            "managed RTL DUT is unavailable; the reference source cannot locate its workspace"
        ) from exc
    manifest_path = next(
        (
            parent / _RTL_MANIFEST_RELATIVE
            for parent in reference_source.parents
            if (parent / _RTL_MANIFEST_RELATIVE).is_file()
            and not (parent / _RTL_MANIFEST_RELATIVE).is_symlink()
        ),
        None,
    )
    if manifest_path is None:
        raise PythonDUTError(
            "managed RTL DUT is unavailable; run Check or Complete once in this workspace"
        )
    workspace_path = manifest_path.parent.parent.parent
    candidate = manifest_path
    while candidate != workspace_path:
        if candidate.is_symlink():
            raise PythonDUTError("managed RTL DUT manifest traverses a symbolic link")
        candidate = candidate.parent

    def reject_constant(value: str) -> None:
        """Reject JSON extensions that cannot participate in a signed identity."""

        raise ValueError(f"non-finite JSON value is not allowed: {value}")

    try:
        with manifest_path.open("r", encoding="utf-8") as file_obj:
            manifest = json.load(file_obj, parse_constant=reject_constant)
    except (OSError, ValueError) as exc:
        raise PythonDUTError("managed RTL DUT manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise PythonDUTError("managed RTL DUT manifest must contain an object")
    if manifest.get("schema_version") != "1.4":
        raise PythonDUTError("managed RTL DUT manifest schema_version is invalid")
    import_identity = manifest.get("python_dut_import")
    if not isinstance(import_identity, dict) or set(import_identity) != {
        "module",
        "class",
    }:
        raise PythonDUTError("managed RTL DUT manifest has no valid import identity")
    module_name = import_identity.get("module")
    class_name = import_identity.get("class")
    if not isinstance(module_name, str) or not _IDENTIFIER_RE.fullmatch(module_name):
        raise PythonDUTError("managed RTL DUT module identity is invalid")
    if not isinstance(class_name, str) or not _IDENTIFIER_RE.fullmatch(class_name):
        raise PythonDUTError("managed RTL DUT class identity is invalid")
    generated_content = manifest.get("generated_content")
    if not isinstance(generated_content, dict) or set(generated_content) != {
        "file_count",
        "content_sha256",
    }:
        raise PythonDUTError("managed RTL DUT content receipt is invalid")

    workspace = workspace_path.resolve()
    runtime_root = _workspace_python_dut_root(workspace)
    candidate = runtime_root
    while candidate != workspace:
        if candidate.exists() and candidate.is_symlink():
            raise PythonDUTError("managed RTL DUT runtime traverses a symbolic link")
        candidate = candidate.parent
    if not runtime_root.resolve().is_relative_to(workspace):
        raise PythonDUTError("managed RTL DUT runtime escapes its workspace")
    package_root = runtime_root / module_name
    try:
        observed_content = _generated_python_dut_identity(package_root)
    except ValueError as exc:
        raise PythonDUTError(str(exc)) from exc
    if observed_content != generated_content:
        raise PythonDUTError("managed RTL DUT runtime differs from its build receipt")
    return runtime_root, module_name, class_name


def _packed_value(value: int, width: int, signed: bool, name: str) -> int:
    """Normalize one assignment to its packed unsigned representation."""

    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int):
        raise TypeError(f"pin {name}.value must be an integer")
    maximum = (1 << width) - 1
    minimum = -(1 << (width - 1)) if signed else 0
    if value < minimum or value > maximum:
        kind = "signed or packed unsigned" if signed else "unsigned"
        raise PythonDUTError(
            f"pin {name}.value={value} does not fit {width}-bit {kind} range"
        )
    return value & maximum


@dataclass(frozen=True)
class PinSpec:
    """Describe one packed DUT pin exposed through a ``.value`` property."""

    name: str
    direction: str
    width: int = 1
    signed: bool = False
    initial: int = 0

    def __post_init__(self) -> None:
        """Reject declarations that cannot match a packed hardware port."""

        if not isinstance(self.name, str) or not _IDENTIFIER_RE.fullmatch(self.name):
            raise PythonDUTError("pin name must be a portable Python identifier")
        if self.direction not in {"input", "output", "inout"}:
            raise PythonDUTError("pin direction must be input, output, or inout")
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width < 1:
            raise PythonDUTError("pin width must be a positive integer")
        if type(self.signed) is not bool:
            raise PythonDUTError("pin signed must be boolean")
        _packed_value(self.initial, self.width, self.signed, self.name)


class ReferencePin:
    """Hold one reference-model pin with Picker-compatible value access."""

    def __init__(self, spec: PinSpec) -> None:
        """Initialize the pin from a validated declaration."""

        self.spec = spec
        self._value = _packed_value(spec.initial, spec.width, spec.signed, spec.name)

    @property
    def value(self) -> int:
        """Return the current packed unsigned bit pattern."""

        return self._value

    @value.setter
    def value(self, value: int) -> None:
        """Assign an integer using the declared width and signedness."""

        self._value = _packed_value(
            value, self.spec.width, self.spec.signed, self.spec.name
        )

    def reset(self) -> None:
        """Restore the pin's declared initial value."""

        self.value = self.spec.initial

    def __int__(self) -> int:
        """Return the same packed value exposed by Picker pins."""

        return self._value


class ReferenceXPort(Mapping[str, ReferencePin]):
    """Expose reference pins through the XPort subset used by shared tests."""

    def __init__(self, owner: "ReferenceDUT") -> None:
        """Bind this port view to one reference DUT."""

        self._owner = owner

    def AsImmWrite(self) -> "ReferenceXPort":
        """Select immediate pin writes and return this view for chaining."""

        self._owner._immediate_write = True
        return self

    def __getitem__(self, name: str) -> ReferencePin:
        """Return a named pin or raise ``KeyError``."""

        return self._owner._pins[name]

    def __iter__(self) -> Iterator[str]:
        """Iterate pins in declaration order."""

        return iter(self._owner._pins)

    def __len__(self) -> int:
        """Return the number of declared pins."""

        return len(self._owner._pins)


class ReferenceDUT:
    """Base class for deterministic models matching Picker's public DUT surface.

    Subclasses implement ``_refresh_comb`` for combinational evaluation and
    ``_step`` for one active edge. ``Step`` intentionally does not refresh
    combinational logic: tests write every immediate input, call ``RefreshComb``,
    call ``Step(1)``, then refresh again before reading post-edge comb outputs.
    """

    PIN_SPECS: tuple[PinSpec, ...] = ()

    def __init__(self, pin_specs: Iterable[PinSpec] | None = None) -> None:
        """Create declared pins and deterministic cycle/callback state."""

        specs = tuple(self.PIN_SPECS if pin_specs is None else pin_specs)
        if not specs:
            raise PythonDUTError("reference DUT must declare at least one PinSpec")
        self._pins: dict[str, ReferencePin] = {}
        for spec in specs:
            if not isinstance(spec, PinSpec):
                raise PythonDUTError("reference DUT declarations must be PinSpec")
            if spec.name in self._pins:
                raise PythonDUTError(f"duplicate reference DUT pin: {spec.name}")
            pin = ReferencePin(spec)
            self._pins[spec.name] = pin
            object.__setattr__(self, spec.name, pin)
        self._xport = ReferenceXPort(self)
        self._clock_names: list[str] = []
        self._rise_callbacks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []
        self._fall_callbacks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []
        self._checkpoints: dict[str, tuple[int, dict[str, int], Any]] = {}
        self._immediate_write = False
        self._finished = False
        self.cycle = 0

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent replacing a pin when ``pin.value`` assignment was intended."""

        current = self.__dict__.get(name)
        if isinstance(current, ReferencePin):
            raise AttributeError(
                f"pin {name} cannot be replaced; assign {name}.value instead"
            )
        object.__setattr__(self, name, value)

    def GetXPort(self) -> ReferenceXPort:
        """Return the reference pin collection."""

        return self._xport

    def InitClock(self, name: str) -> None:
        """Register one declared one-bit input as a logical clock."""

        pin = self._pins.get(name)
        if pin is None:
            raise PythonDUTError(f"clock pin is not declared: {name}")
        if pin.spec.direction == "output" or pin.spec.width != 1:
            raise PythonDUTError("clock pin must be a one-bit input or inout")
        if name not in self._clock_names:
            self._clock_names.append(name)

    def GetXClock(self) -> "ReferenceDUT":
        """Return the deterministic clock controller for this DUT."""

        return self

    def RefreshComb(self) -> None:
        """Evaluate combinational logic once without advancing cycle state."""

        self._require_live()
        self._refresh_comb()

    def Step(self, count: int = 1) -> None:
        """Advance ``count`` active edges without an implicit comb refresh."""

        self._require_live()
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise PythonDUTError("Step count must be a positive integer")
        for _ in range(count):
            self._step()
            self.cycle += 1
            self._run_callbacks(self._rise_callbacks)
            self._run_callbacks(self._fall_callbacks)

    def StepRis(
        self,
        callback: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Register a callback sampled after each active model edge."""

        self._register_callback(self._rise_callbacks, callback, args, kwargs)

    def StepFal(
        self,
        callback: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Register a callback sampled at each deterministic fall boundary."""

        self._register_callback(self._fall_callbacks, callback, args, kwargs)

    def CheckPoint(self, name: str) -> int:
        """Save cycle and pin state under a non-empty name."""

        if not isinstance(name, str) or not name:
            raise PythonDUTError("checkpoint name must be a non-empty string")
        self._checkpoints[name] = (
            self.cycle,
            {pin_name: pin.value for pin_name, pin in self._pins.items()},
            self._capture_model_state(),
        )
        return 0

    def Restore(self, name: str) -> int:
        """Restore cycle and pins from a named checkpoint."""

        if name not in self._checkpoints:
            raise PythonDUTError(f"checkpoint does not exist: {name}")
        self.cycle, values, model_state = self._checkpoints[name]
        for pin_name, value in values.items():
            self._pins[pin_name].value = value
        self._restore_model_state(model_state)
        return 0

    def SetCoverage(self, filename: str | os.PathLike[str]) -> None:
        """Accept the RTL coverage hook without fabricating Python coverage."""

        del filename

    def GetCovMetrics(self) -> int:
        """Return zero because a Python model has no RTL coverage metrics."""

        return 0

    def SetWaveform(self, filename: str | os.PathLike[str]) -> None:
        """Reject attempts to use reference traces as RTL waveform evidence."""

        del filename
        raise PythonDUTError("Python reference DUT cannot produce RTL waveform evidence")

    def ResumeWaveformDump(self) -> None:
        """Reject waveform control because reference execution has no RTL trace."""

        raise PythonDUTError("Python reference DUT cannot produce RTL waveform evidence")

    def PauseWaveformDump(self) -> None:
        """Reject waveform control because reference execution has no RTL trace."""

        raise PythonDUTError("Python reference DUT cannot produce RTL waveform evidence")

    def WaveformPaused(self) -> int:
        """Report that unsupported reference waveform capture is paused."""

        return 1

    def GetWaveFormat(self) -> str:
        """Return no waveform format for reference execution."""

        return ""

    def FlushWaveform(self) -> None:
        """Reject waveform flushing because no reference trace may be emitted."""

        raise PythonDUTError("Python reference DUT cannot produce RTL waveform evidence")

    def Finish(self) -> None:
        """Release this model; repeated calls are harmless."""

        self._finished = True

    def reset_pins(self) -> None:
        """Restore declared pin initial values without changing subclass state."""

        for pin in self._pins.values():
            pin.reset()

    def drive_output(self, name: str, value: int) -> None:
        """Assign a declared model output with width checking."""

        pin = self._pins.get(name)
        if pin is None or pin.spec.direction == "input":
            raise PythonDUTError(f"model output pin is not declared: {name}")
        pin.value = value

    def _refresh_comb(self) -> None:
        """Evaluate one combinational pass; override when the DUT has comb logic."""

    def _step(self) -> None:
        """Advance one active edge; combinational-only DUTs keep the no-op."""

    def _capture_model_state(self) -> Any:
        """Return subclass state stored by ``CheckPoint``; override when needed."""

        return None

    def _restore_model_state(self, state: Any) -> None:
        """Restore state returned by ``_capture_model_state``."""

        if state is not None:
            raise PythonDUTError(
                "reference DUT returned checkpoint state without a restore hook"
            )

    def _register_callback(
        self,
        target: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
        callback: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any] | None,
    ) -> None:
        """Validate and store one Picker-style edge callback."""

        if not callable(callback):
            raise TypeError("edge callback must be callable")
        if not isinstance(args, tuple) or not isinstance(kwargs or {}, dict):
            raise TypeError("edge callback args/kwargs have invalid types")
        target.append((callback, args, dict(kwargs or {})))

    def _run_callbacks(
        self,
        callbacks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
    ) -> None:
        """Invoke callbacks with the cycle first, followed by registered args."""

        for callback, args, kwargs in tuple(callbacks):
            callback(self.cycle, *args, **kwargs)

    def _require_live(self) -> None:
        """Reject simulation work after ``Finish``."""

        if self._finished:
            raise PythonDUTError("reference DUT has already been finished")


def create_dut(backend: str, reference_factory: Callable[[], ReferenceDUT]) -> Any:
    """Create the reference or synchronized RTL DUT for one shared test suite.

    Check/Complete supplies the verified RTL identity to its isolated test
    subprocess. A direct pytest run can recover the same identity from the
    portable workspace runtime and its content receipt.
    """

    if backend not in {"python", "rtl"}:
        raise PythonDUTError("backend must be 'python' or 'rtl'")
    if not callable(reference_factory):
        raise TypeError("reference_factory must be callable")
    if backend == "python":
        dut = reference_factory()
        if not isinstance(dut, ReferenceDUT):
            raise PythonDUTError("reference_factory must return a ReferenceDUT")
        return dut

    module_name = os.environ.get(_RTL_DUT_MODULE_ENV, "")
    class_name = os.environ.get(_RTL_DUT_CLASS_ENV, "")
    runtime_root: Path | None = None
    if not _IDENTIFIER_RE.fullmatch(module_name) or not _IDENTIFIER_RE.fullmatch(
        class_name
    ):
        runtime_root, module_name, class_name = _portable_rtl_dut_identity(
            reference_factory
        )
        runtime_path = str(runtime_root)
        if runtime_path in sys.path:
            sys.path.remove(runtime_path)
        sys.path.insert(0, runtime_path)
    try:
        module = importlib.import_module(module_name)
        if runtime_root is not None:
            origin_value = getattr(module, "__file__", None)
            if not isinstance(origin_value, str):
                raise ImportError("generated RTL module has no regular origin")
            origin = Path(origin_value).resolve()
            package_root = (runtime_root / module_name).resolve()
            if origin != package_root / "__init__.py" and not origin.is_relative_to(
                package_root
            ):
                raise ImportError("generated RTL module resolved outside its runtime")
        dut_class = getattr(module, class_name)
        dut = dut_class()
    except Exception as exc:
        raise PythonDUTError(
            "managed RTL DUT is unavailable; synchronize it through Check or Complete"
        ) from exc
    missing = [
        name
        for name in ("GetXPort", "RefreshComb", "Step", "Finish")
        if not callable(getattr(dut, name, None))
    ]
    if missing:
        raise PythonDUTError(
            f"managed RTL DUT is missing required methods: {', '.join(missing)}"
        )
    dut.GetXPort().AsImmWrite()
    return dut


__all__ = [
    "PinSpec",
    "PythonDUTError",
    "ReferenceDUT",
    "ReferencePin",
    "ReferenceXPort",
    "create_dut",
    "managed_test_implementation",
    "prepare_native_artifact_path",
    "register_managed_test_options",
]
