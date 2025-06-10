#coding=utf-8


import pytest
from alu import DUTALU
from alu_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage


def create_dut():
    """
    Create a new instance of the ALU (Arithmetic Logic Unit) for testing.
    
    Returns:
        ALU: An instance of the ALU class.
    """
    return DUTALU()


def api_alu_operation(dut, op, a, b, c=0):
    """
    Perform operations on the ALU.

    Args:
        dut (ALU): The ALU instance.
        op (int): Operation code (0 for addition, 1 for subtraction, etc.).
        a (int): First operand.
        b (int): Second operand.
        c (int): Carry-in value (0 or 1). Defaults to 0.

    Returns:
        tuple: Result of the addition and carry out flag.
    """
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = c
    dut.op.value = op
    dut.Step(1)  # Simulate a clock step
    return dut.out.value, dut.cout.value


@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    dut.InitClock("clock")                               # 初始化时钟
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])         # 上升沿采样
    setattr(dut, "_g",
            {g.name:g for g in func_coverage_group})     # 保存覆盖组到DUT
    yield dut
    # 测试后处理
    set_func_coverage(request, func_coverage_group)      # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT
