"""Simulator artifact defaults and executable DUT fixture examples."""

import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

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
