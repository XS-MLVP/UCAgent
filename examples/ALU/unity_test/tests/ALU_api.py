#coding=utf-8


import pytest
from ALU import DUTALU
from ALU_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage


def create_dut():
    """
    Create a new instance of the ALU (Arithmetic Logic Unit) for testing.
    
    Returns:
        ALU: An instance of the ALU class.
    """
    return DUTALU()


def api_ALU_operation(dut, op, a, b, c=0):
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
    dut.Step(1)  # Simulate a clock step， 如果在该处使用RefreshComb推进组合电路，则可以在这里手动调用所有CovGroup的sample方法进行功能覆盖采样
                 # dut.Step 方法会自动调用dut.StepRis设置的回调函数
    return dut.out.value, dut.cout.value


@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    # 该ALU的实现为组合电路，不需要 InitClock
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])         # 在上升沿回调函数中进行CovGroup的采样，虽然Fake ALU为组合电路，但也可以通过Step接口推进和覆盖率采样
                                                         # 如果不在这里进行sample，需要在其他合理的地方进行sample，不然无法获取覆统计数据
    setattr(dut, "fc_cover",
            {g.name:g for g in func_coverage_group})     # 以属性名称fc_cover保存覆盖组到DUT
    yield dut
    # 测试后处理
    set_func_coverage(request, func_coverage_group)      # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT
