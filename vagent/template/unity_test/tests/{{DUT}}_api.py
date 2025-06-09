#coding=utf-8

import pytest
from {{DUT}}_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage

# import your dut module here
import {{DUT}}  # Replace with the actual DUT class import


def create_dut():
    """
    Create a new instance of the {{DUT}} for testing.
    
    Returns:
        dut_instance: An instance of the {{DUT}} class.
    """
    # Replace with the actual instantiation and initialization of your DUT
    return {{DUT}}()


@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])         # 上升沿采样
    setattr(dut, "coverage_groups",
            {g.name:g for g in func_coverage_group})     # 保存覆盖组到DUT
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
#    # Replace with the actual API function for your DUT
