
import pytest
from Adder import DUTAdder
from toffee_test.reporter import set_func_coverage
from unity_test.tests.Adder_function_coverage_def import get_coverage_groups

@pytest.fixture()
def dut(request):
    dut = DUTAdder()
    func_coverage_group = get_coverage_groups(dut)
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    setattr(dut, "fc_cover", {g.name:g for g in func_coverage_group})
    yield dut
    set_func_coverage(request, func_coverage_group)
    for g in func_coverage_group:
        g.clear()
    dut.Finish()

def api_adder_add(dut, a, b, cin):
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = cin
    dut.Step(1)
    return dut.sum.value, dut.cout.value
