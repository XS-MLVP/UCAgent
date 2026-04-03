import os
import pytest
from toffee import Bundle, Signals
from toffee_test.reporter import get_file_in_tmp_dir, set_func_coverage, set_line_coverage
from {DUT}_function_coverage_def import get_coverage_groups


DEFAULT_CLOCK_NAMES = ("clock", "clk", "clk_i", "clk_in", "sys_clk", "PCLK")


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path: bool):
    return get_file_in_tmp_dir(request, current_path_file("data/"), "{DUT}.dat", new_path=new_path)


def create_dut(request):
    # Expect picker export to create a package directory named `{DUT}` and
    # expose it by putting the parent directory on PYTHONPATH.
    from {DUT} import DUT{DUT}

    dut = DUT{DUT}()
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))
    for clock_name in DEFAULT_CLOCK_NAMES:
        if hasattr(dut, clock_name):
            dut.InitClock(clock_name)
            break
    return dut


class Env(Bundle):
    pass


class {DUT}Env:
    def __init__(self, dut):
        self.dut = dut
        self.io = Env.from_dict({})
        self.io.bind(dut)

    def Step(self, cycles: int = 1):
        return self.dut.Step(cycles)


@pytest.fixture(scope="module")
def dut(request):
    dut = create_dut(request)
    func_coverage_group = get_coverage_groups(dut)
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})
    yield dut
    set_func_coverage(request, func_coverage_group)
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("{DUT}.ignore"))
    for group in func_coverage_group:
        group.clear()
    dut.Finish()


@pytest.fixture()
def env(dut):
    return {DUT}Env(dut)
