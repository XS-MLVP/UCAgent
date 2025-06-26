#coding=utf-8

import pytest
from {{DUT}}_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage

# import your dut module here
from {{DUT}} import DUT{{DUT}}  # Replace with the actual DUT class import


def create_dut():
    """
    Create a new instance of the {{DUT}} for testing.
    
    Returns:
        dut_instance: An instance of the {{DUT}} class.
    """
    # Replace with the actual instantiation and initialization of your DUT
    return DUT{{DUT}}()


@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    # 请在这里根据DUT是否为时序电路判断是否需要调用 dut.InitClock
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])         # 上升沿采样，StepRis也适用于组合电路，因为组合电路也可以用Step接口进行推进
    setattr(dut, "fc_cover",
            {g.name:g for g in func_coverage_group})     # 以属性名称fc_cover保存覆盖组到DUT
    yield dut
    # 测试后处理
    set_func_coverage(request, func_coverage_group)      # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT，每个DUT class 都有 Finish 方法


# 根据DUT的功能需要，定义API函数， API函数需要通用且稳定，不是越多越好
# def api_{{DUT}}_{operation_name}(dut, ...):
#    """
#    api description and parameters
#    ...
#    """
#    dut.some_input.value = value
#    dut.Step()
#    return dut.some_output.value
#    # Replace with the actual API function for your DUT
#    ...
#
