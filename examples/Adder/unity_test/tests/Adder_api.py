
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

def api_Adder_add(dut, a, b, cin):
    """执行加法器的加法运算操作

    该API函数封装了加法器DUT的基本加法运算功能，支持两个操作数的加法运算
    以及可选的进位输入。函数自动处理信号设置、时钟推进和结果读取的完整流程。

    Args:
        dut: Adder DUT实例，必须是已初始化的DUTAdder对象
        a (int): 第一个操作数，取值范围[0, 2^64-1]，表示加法器输入A的数值
        b (int): 第二个操作数，取值范围[0, 2^64-1]，表示加法器输入B的数值  
        cin (int): 进位输入，取值为0或1，表示来自前级的进位信号

    Returns:
        Tuple[int, int]: 包含两个元素的元组
            - sum (int): 加法运算结果，A + B + Cin的和值
            - cout (int): 进位输出，0表示无进位，1表示有进位

    Example:
        >>> sum_result, carry_out = api_Adder_add(dut, 100, 200, 0)
        >>> print(f"结果: {sum_result}, 进位: {carry_out}")
        结果: 300, 进位: 0
        
        >>> sum_result, carry_out = api_Adder_add(dut, 0xFFFFFFFFFFFFFFFF, 1, 0)
        >>> print(f"溢出结果: {sum_result}, 进位: {carry_out}")
        溢出结果: 0, 进位: 1

    Note:
        - 该API适用于组合逻辑加法器，使用Step(1)确保信号稳定
        - 输入参数无范围检查，调用者需确保参数在有效范围内
        - 支持64位无符号整数运算，溢出时通过进位输出标识
    """
    dut.a.value = a
    dut.b.value = b
    dut.cin.value = cin
    dut.Step(1)
    return dut.sum.value, dut.cout.value
