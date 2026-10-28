"""Simulator artifact defaults and executable DUT fixture examples."""

import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ucagent
from ucagent.util import test_tools
from ucagent.util.functions import tips_of_get_coverage_data_path


LANGUAGE_ROOT = Path(__file__).resolve().parents[1] / "ucagent/lang/zh"


@pytest.mark.parametrize("attributes, expected", [
    ({}, ("fst", "dat")),
    ({"SIMULATOR": "verilator"}, ("fst", "dat")),
    ({"SIMULATOR": " VerILator "}, ("fst", "dat")),
    ({"SIMULATOR": "vcs"}, ("fsdb", "vdb")),
    ({"SIMULATOR": " VCS "}, ("fsdb", "vdb")),
    ({"SIMULATOR": "uvs"}, ("usdb", "cdb")),
    ({"SIMULATOR": " UVS "}, ("usdb", "cdb")),
])
def test_default_subfix_accepts_instances_and_classes(attributes, expected):
    """Read instance or inherited class metadata, with a missing-only default."""
    for dut in (SimpleNamespace(**attributes), type("DUT", (), attributes)):
        assert ucagent.get_default_subfix(dut, "waveform") == expected[0]
        assert ucagent.get_default_subfix(dut, "coverage") == expected[1]


@pytest.mark.parametrize("simulator, error", [
    (None, TypeError),
    (False, TypeError),
    (123, TypeError),
    ([], TypeError),
    ("", ValueError),
    ("  ", ValueError),
    ("unknown", ValueError),
])
def test_default_subfix_rejects_invalid_simulator(simulator, error):
    """Invalid metadata must not silently generate Verilator artifact names."""
    with pytest.raises(error, match="SIMULATOR"):
        ucagent.get_default_subfix(SimpleNamespace(SIMULATOR=simulator), "coverage")


@pytest.mark.parametrize("sub_type, error", [
    (None, TypeError),
    ([], TypeError),
    (1, TypeError),
    ("", ValueError),
    ("wave", ValueError),
    ("Coverage", ValueError),
])
def test_default_subfix_rejects_invalid_artifact_type(sub_type, error):
    """Artifact types have the two documented, unambiguous spellings."""
    with pytest.raises(error, match="sub_type.*'waveform'.*'coverage'"):
        ucagent.get_default_subfix(SimpleNamespace(), sub_type)


def test_default_subfix_extends_with_one_mapping_entry(monkeypatch):
    """A new simulator needs no additional lookup or fixture branches."""
    monkeypatch.setitem(test_tools._SIMULATOR_DEFAULT_SUFFIXES, "example_sim", {
        "waveform": "example_wave", "coverage": "example_cov",
    })
    dut = SimpleNamespace(SIMULATOR="EXAMPLE_SIM")
    assert ucagent.get_default_subfix(dut, "waveform") == "example_wave"
    assert ucagent.get_default_subfix(dut, "coverage") == "example_cov"


@pytest.mark.parametrize("mode", [None, "", "   ", "manual", " MANUAL "])
def test_get_seed_manual_mode_returns_literal_seed(monkeypatch, mode):
    """Unset, empty, or manual UC_SEED_MODEL keeps the literal test seed."""
    if mode is None:
        monkeypatch.delenv("UC_SEED_MODEL", raising=False)
    else:
        monkeypatch.setenv("UC_SEED_MODEL", mode)
    assert ucagent.get_seed(4242) == 4242


@pytest.mark.parametrize("mode", ["random", "time"])
def test_get_seed_generated_modes_return_int_in_31bit_range(monkeypatch, mode):
    """random/time modes ignore the literal seed and return a 31-bit int."""
    monkeypatch.setenv("UC_SEED_MODEL", mode)
    for _ in range(5):
        value = ucagent.get_seed(7)
        assert isinstance(value, int)
        assert 0 <= value <= 2 ** 31 - 1


def test_get_seed_uniform_expression_bounds(monkeypatch):
    """uniform:<min>:<max> draws integers inside the inclusive bounds."""
    monkeypatch.setenv("UC_SEED_MODEL", "uniform:5:7")
    assert all(ucagent.get_seed(1) in (5, 6, 7) for _ in range(20))
    monkeypatch.setenv("UC_SEED_MODEL", "uniform:9:9")
    assert ucagent.get_seed(1) == 9


def test_get_seed_normal_expression_clamps_to_31bit(monkeypatch):
    """normal:<mu>:<sigma> returns a clamped integer seed."""
    monkeypatch.setenv("UC_SEED_MODEL", "normal:1000000:100")
    for _ in range(10):
        value = ucagent.get_seed(1)
        assert isinstance(value, int)
        assert 0 <= value <= 2 ** 31 - 1
    monkeypatch.setenv("UC_SEED_MODEL", "normal:999999999999:0.1")
    assert ucagent.get_seed(1) == 2 ** 31 - 1


@pytest.mark.parametrize("mode, match", [
    ("bogus", "Use 'manual', 'random', 'time'"),
    ("uniform:1", "exactly two"),
    ("uniform:1:2:3", "exactly two"),
    ("uniform:a:9", "must be integers"),
    ("uniform:9:5", "min <= max"),
    ("normal:1", "exactly two"),
    ("normal:x:1", "must be numbers"),
    ("normal:1:-2", "sigma >= 0"),
])
def test_get_seed_rejects_invalid_mode_with_corrective_hint(monkeypatch, mode, match):
    """Invalid seed modes must fail with the accepted form, never fall back."""
    monkeypatch.setenv("UC_SEED_MODEL", mode)
    with pytest.raises(ValueError, match=match):
        ucagent.get_seed(1)


@pytest.mark.parametrize("bad_seed", ["1234", 12.5, True, None])
def test_get_seed_rejects_non_int_manual_seed(monkeypatch, bad_seed):
    """The manual-mode seed argument must be a plain int in every mode."""
    monkeypatch.delenv("UC_SEED_MODEL", raising=False)
    with pytest.raises(TypeError, match="int manual-mode seed"):
        ucagent.get_seed(bad_seed)


class _DUT:
    """Record simulator configuration and create representative artifact paths."""

    initializations = 0

    def __init__(self):
        """Track real construction so fake-mode tests can exclude simulation."""
        type(self).initializations += 1
        self.finished = False

    def SetCoverage(self, path):
        """Represent coverage as a database directory or a regular file."""
        self.coverage_path = path
        if path.endswith(".vdb"):
            Path(path).mkdir()
        else:
            Path(path).touch()

    def SetWaveform(self, path):
        """Record the waveform output supplied by the rendered factory."""
        self.waveform_path = path
        Path(path).touch()

    def StepRis(self, callback):
        """Accept the fixture's functional coverage sampling callback."""
        self.callback = callback

    def Finish(self):
        """Record resource cleanup at the end of the fixture."""
        self.finished = True


@pytest.fixture(params=["template", "guide"])
def rendered_api(request, tmp_path, monkeypatch):
    """Execute the API template and the guide's complete fixture example."""
    if request.param == "template":
        source = (LANGUAGE_ROOT / "template/unity_test/tests/{{DUT}}_api.py").read_text(
            encoding="utf-8"
        )
    else:
        guide = (LANGUAGE_ROOT / "doc/Guide_Doc/dut_fixture.md").read_text(encoding="utf-8")
        source = guide.split("```python\n", 1)[1].split("```", 1)[0]
    source = source.replace("{{DUT}}", "Demo").replace("{{Version}}", "test").replace(
        "{{Email}}", "test@example.com"
    )
    dut_module = ModuleType("Demo")
    dut_module.DUTDemo = _DUT
    coverage_module = ModuleType("Demo_function_coverage_def")
    coverage_module.get_coverage_groups = lambda dut: []
    monkeypatch.setitem(sys.modules, dut_module.__name__, dut_module)
    monkeypatch.setitem(sys.modules, coverage_module.__name__, coverage_module)
    api = ModuleType("Demo_api")
    api.__file__ = str(tmp_path / "Demo_api.py")
    exec(compile(source, api.__file__, "exec"), api.__dict__)
    monkeypatch.setenv("UC_IS_IMP_TEMPLATE", "false")
    return api


@pytest.mark.parametrize("simulator, waveform, coverage", [
    (None, "fst", "dat"),
    ("verilator", "fst", "dat"),
    (" VCS ", "fsdb", "vdb"),
    ("UVS", "usdb", "cdb"),
])
@pytest.mark.parametrize("with_request", [False, True])
def test_fixture_paths_round_trip_and_report(
    rendered_api, monkeypatch, simulator, waveform, coverage, with_request,
):
    """Creation and teardown reuse the same path, including VCS directories."""
    if simulator is not None:
        monkeypatch.setattr(_DUT, "SIMULATOR", simulator, raising=False)
    request = SimpleNamespace(
        node=SimpleNamespace(name="test_operation"),
        config=SimpleNamespace(_toffee_test_start_time=1700000000),
        scope="function",
    ) if with_request else None
    monkeypatch.setattr(rendered_api, "set_func_coverage", lambda *args: None)
    monkeypatch.setattr(rendered_api, "set_user_info", lambda *args: None)
    monkeypatch.setattr(rendered_api, "set_title_info", lambda *args: None)
    reports = []
    if not with_request:
        monkeypatch.setattr(
            rendered_api, "set_line_coverage",
            lambda req, path, **kwargs: reports.append(path),
        )
    fixture = rendered_api.dut.__wrapped__(request)
    dut = next(fixture)
    name = "test_operation" if with_request else "Demo"
    assert Path(dut.waveform_path).name == f"{name}.{waveform}"
    assert Path(dut.coverage_path).name == f"{name}.{coverage}"
    assert Path(dut.coverage_path).is_dir() == (coverage == "vdb")
    assert rendered_api.get_coverage_data_path(request, dut, new_path=False) == dut.coverage_path
    assert rendered_api.get_waveform_path(request, dut, new_path=False) == dut.waveform_path
    assert rendered_api.get_coverage_data_path(request, dut, new_path=True) != dut.coverage_path
    with pytest.raises(StopIteration):
        next(fixture)
    if with_request:
        assert json.loads(request.node.__line_coverage__)["datfile"] == dut.coverage_path
    else:
        assert reports == [dut.coverage_path]
    assert dut.finished is True


def test_factory_uses_instance_simulator_over_class_default(rendered_api, monkeypatch):
    """Instance-only simulator metadata must control the generated paths."""
    initialize = _DUT.__init__

    def initialize_vcs(self):
        """Model a DUT that declares its simulator during construction."""
        initialize(self)
        self.SIMULATOR = "vcs"

    monkeypatch.setattr(_DUT, "SIMULATOR", "verilator", raising=False)
    monkeypatch.setattr(_DUT, "__init__", initialize_vcs)
    dut = rendered_api.create_dut(None)
    assert Path(dut.coverage_path).name == "Demo.vdb"
    assert Path(dut.waveform_path).name == "Demo.fsdb"


@pytest.mark.parametrize("simulator, coverage", [(None, "dat"), ("vcs", "vdb"), ("uvs", "cdb")])
def test_fake_dut_preserves_simulator_without_real_initialization(
    rendered_api, monkeypatch, simulator, coverage,
):
    """Fake and independent Mock DUTs keep declared metadata without simulation."""
    if simulator is not None:
        monkeypatch.setattr(_DUT, "SIMULATOR", simulator, raising=False)
    clock = SimpleNamespace(Add=lambda port: None, getEvent=lambda: None)
    xsp = SimpleNamespace(
        XData=object, XPin=object, XClock=lambda *args: clock,
        XPort=object, TEST_get_u64_step_func=lambda: None,
    )
    monkeypatch.setitem(_DUT.__init__.__globals__, "xsp", xsp)
    monkeypatch.setenv("UC_IS_IMP_TEMPLATE", "true")
    initializations = _DUT.initializations
    for dut in (rendered_api.create_dut(None), ucagent.get_mock_dut_from(_DUT)):
        assert getattr(dut, "SIMULATOR", None) == simulator
        assert rendered_api.get_coverage_data_path(None, dut, new_path=False).endswith(
            f"Demo.{coverage}"
        )
    assert _DUT.initializations == initializations


def test_coverage_repair_tip_uses_dut_simulator(rendered_api, monkeypatch):
    """A checker repair must retain simulator-aware naming and per-test identity."""
    monkeypatch.setattr(_DUT, "SIMULATOR", "vcs", raising=False)
    tip = tips_of_get_coverage_data_path("Demo")
    namespace = dict(rendered_api.__dict__)
    exec(tip[tip.index("def get_coverage_data_path"):], namespace)
    assert namespace["get_coverage_data_path"](None, _DUT(), new_path=True).endswith("Demo.vdb")


@pytest.fixture(params=["wrapped", "direct", "mixed"])
def picker_dut(request, tmp_path, monkeypatch):
    """Load representative picker wrappers without constructing a simulator."""
    declarations = []
    for index, (name, width, direction) in enumerate([
        ("clk", 0, "In"), ("request", 8, "In"), ("response", 129, "Out"),
    ]):
        value = f"xsp.XData({width}, xsp.XData.{direction})"
        if request.param == "wrapped" or (request.param == "mixed" and index == 1):
            value = f"xsp.XPin({value}, self.event)"
        declarations.append(f"        self.{name} = {value}\n")
    source = (
        '"""Generated picker DUT interface for pin compatibility tests."""\n'
        'class DUT:\n'
        '    """Expose pins without permitting real DUT initialization."""\n'
        '    SIMULATOR = "vcs"\n'
        '    def __init__(self):\n'
        '        """Reject any attempt to start real simulation."""\n'
        '        raise AssertionError("real DUT must not be initialized")\n'
        '        self.metadata = dict()\n'
        '        self.enabled = True\n'
        + "".join(declarations)
    )
    module = ModuleType("picker_mock_dut")
    module.__file__ = str(tmp_path / "picker_mock_dut.py")
    Path(module.__file__).write_text(source, encoding="utf-8")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module.DUT


def test_get_pin_info_supports_picker_pin_layouts(picker_dut):
    """Both layouts preserve declaration order, scalar pins, and wide buses."""
    assert list(test_tools.get_pin_info(picker_dut).items()) == [
        ("clk", 0), ("request", 8), ("response", 129),
    ]


@pytest.mark.parametrize("has_xpin", [True, False])
def test_mock_dut_supports_picker_pin_apis(picker_dut, monkeypatch, has_xpin):
    """Mock pins share port data and retain clock behavior across both APIs."""
    class XPin:
        """Model the legacy wrapper's shared value and clock event."""

        def __init__(self, xdata, event):
            """Keep the supplied data and event without copying them."""
            self.xdata = xdata
            self.event = event

        @property
        def value(self):
            """Read the underlying port data."""
            return self.xdata.value

        @value.setter
        def value(self, value):
            """Update the underlying port data."""
            self.xdata.value = value

    xdata_cls = MagicMock(side_effect=lambda width, direction: SimpleNamespace(
        W=lambda: width, direction=direction, value=0,
    ))
    clock = MagicMock()
    port = MagicMock()
    pins = {}
    port.Add.side_effect = pins.__setitem__
    port.__getitem__.side_effect = pins.__getitem__
    xsp = SimpleNamespace(
        XData=xdata_cls, XClock=MagicMock(return_value=clock),
        XPort=MagicMock(return_value=port), TEST_get_u64_step_func=lambda: 123,
    )
    if has_xpin:
        xsp.XPin = XPin
    monkeypatch.setitem(picker_dut.__init__.__globals__, "xsp", xsp)
    dut = ucagent.get_mock_dut_from(picker_dut)
    assert dut.SIMULATOR == "vcs"
    assert dut._is_initialized is True
    assert list(dut._pins) == ["clk", "request", "response"]
    for name, width, value in [("clk", 0, 1), ("request", 8, 255), ("response", 129, 2 ** 128)]:
        pin = getattr(dut, name)
        assert dut._pins[name] is pin
        if has_xpin:
            assert isinstance(pin, XPin)
            assert pin.xdata is pins[name]
            assert pin.event is dut.event
        else:
            assert pin is pins[name]
        assert pins[name].W() == width
        assert pins[name].direction is xdata_cls.InOut
        pin.value = value
        assert pins[name].value == value
        pins[name].value = value - 1
        assert pin.value == value - 1
    assert json.loads(str(dut)) == {
        "clk[0]": 0, "request[8]": 254, "response[129]": 2 ** 128 - 1,
    }
    dut.InitClock("clk")
    assert clock.Add.call_args_list[0].args == (port,)
    assert clock.Add.call_args_list[1].args == (pins["clk"],)
    dut.Step(2)
    clock.Step.assert_called_once_with(2)
    dut.StepRis(print, ("rise",), {"end": ""})
    clock.StepRis.assert_called_once_with(print, ("rise",), {"end": ""})
    dut.StepFal(print, ("fall",), {"end": ""})
    clock.StepFal.assert_called_once_with(print, ("fall",), {"end": ""})


def test_mock_dut_with_installed_xspcomm(picker_dut, monkeypatch):
    """Exercise real pin writes, port registration, and clock callbacks."""
    xsp = pytest.importorskip("xspcomm")
    monkeypatch.setitem(picker_dut.__init__.__globals__, "xsp", xsp)
    dut = ucagent.get_mock_dut_from(picker_dut)
    dut.InitClock("clk")
    dut.request.value = 0xA5
    dut.response.value = 2 ** 128
    assert dut.xport["request"].value == 0xA5
    assert dut.xport["response"].W() == 129
    assert json.loads(str(dut))["response[129]"] == 2 ** 128
    edges = []

    def on_edge(cycle, edge):
        """Record callbacks and drive a wide pin through its public value."""
        edges.append((cycle, edge))
        dut.response.value += 1

    dut.StepRis(on_edge, ("rise",))
    dut.StepFal(on_edge, kwargs={"edge": "fall"})
    dut.Step(2)
    assert sorted(edge for _, edge in edges) == ["fall", "fall", "rise", "rise"]
    assert dut.response.value == 2 ** 128 + 4
    assert json.loads(str(dut))["response[129]"] == 2 ** 128 + 4


@pytest.mark.parametrize("assignment", [
    "self.pin = xsp.XPin()",
    "self.pin = xsp.XData()",
    "self.pin = xsp.XPin(object(), None)",
    "self.pin = xsp.XData(width, None)",
    "self.pin = xsp.XData('8', None)",
    "self.pin = xsp.XData(True, None)",
    "self.pin = object()",
])
def test_get_pin_info_skips_assignments_without_literal_width(monkeypatch, assignment):
    """Non-pin or incomplete declarations cannot become mock pin widths."""
    source = f"class DUT:\n    def __init__(self):\n        {assignment}\n"
    monkeypatch.setattr(test_tools.inspect, "getsource", lambda cls: source)
    assert test_tools.get_pin_info(_DUT) == {}
