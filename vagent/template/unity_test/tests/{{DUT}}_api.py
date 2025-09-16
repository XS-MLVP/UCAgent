#coding=utf-8

import pytest
from {{DUT}}_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage, set_line_coverage

# import your dut module here
from {{DUT}} import DUT{{DUT}}  # Replace with the actual DUT class import

import os

def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def create_dut():
    """
    Create a new instance of the {{DUT}} for testing.
    
    Returns:
        dut_instance: An instance of the {{DUT}} class.
    """
    # Replace with the actual instantiation and initialization of your DUT
    dut = DUT{{DUT}}()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(current_path_file("{{DUT}}.dat"))

    # 设置覆波形生成文件（根据需要设置，可选）
    # dut.SetWaveform(current_path_file("{{DUT}}.fst"))

    return dut


@pytest.fixture()
def dut(request):
    dut = create_dut()                                   # 创建DUT
    func_coverage_group = get_coverage_groups(dut)
    # 请在这里根据DUT是否为时序电路判断是否需要调用 dut.InitClock
    # dut.InitClock("clk")

    # 上升沿采样，StepRis也适用于组合电路用dut.Step推进时采样.
    # 必须要有g.sample()采样覆盖组, 如何不在StepRis/StepFail中采样，则需要在test function中手动调用，否则无法统计覆盖率导致失败
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           func_coverage_group])

    # 以属性名称fc_cover保存覆盖组到DUT
    setattr(dut, "fc_cover",
            {g.name:g for g in func_coverage_group})

    # 返回DUT实例
    yield dut

    # 测试后处理
    # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    set_func_coverage(request, func_coverage_group)

    # 设置需要收集的代码行覆盖率文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    set_line_coverage(request, current_path_file("{{DUT}}.dat"),
                      ignore=current_path_file("{{DUT}}.ignore"))  # 向toffee_test传代码行递覆盖率数据

    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT，每个DUT class 都有 Finish 方法


# 如果需要定义env fixture, 请取消下面的注释，并根据需要修改名称
# @pytest.fixture()
# def env(dut):
#     return MyEnv(dut)
#
# @pytest.fixture()
# def env1(dut):
#     return MyEnv1(dut)
#
#
# 根据DUT的功能需要，定义API函数， API函数需要通用且稳定，不是越多越好
# def api_{{DUT}}_{operation_name}(env, ...):
#    """
#    api description and parameters
#    ...
#    """
#    dut = env.dut
#    dut.some_input.value = value
#    dut.Step()
#    return dut.some_output.value
#    # Replace with the actual API function for your DUT
#    ...
