#coding=utf-8

import pytest
from {{DUT}}_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage, set_line_coverage, get_file_in_tmp_dir
from toffee_test.reporter import set_user_info, set_title_info
from toffee import Bundle, Signals, Signal

# import your dut module here
from {{DUT}} import DUT{{DUT}}  # Replace with the actual DUT class import

import os


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    return get_file_in_tmp_dir(request, current_path_file("data/"), "{{DUT}}.dat",  new_path=new_path)


def create_dut(request):
    """
    Create a new instance of the {{DUT}} for testing.
    
    Returns:
        dut_instance: An instance of the {{DUT}} class.
    """
    # Replace with the actual instantiation and initialization of your DUT
    dut = DUT{{DUT}}()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件（根据需要设置，可选）
    # wave_path = get_file_in_tmp_dir(request, current_path_file("data/"), "{{DUT}}.fst",  new_path=True)
    # dut.SetWaveform(wave_path)

    return dut


@pytest.fixture(scope="module")
def dut(request):
    dut = create_dut(request)                         # 创建DUT
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

    # 设置需要收集的代码行覆盖率文件(获取已有路径new_path=False) 向toffee_test传代码行递覆盖率数据
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：{{DUT}}.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("{{DUT}}.ignore"))

    # 设置用户信息到报告
    set_user_info("UCAgent-{{Version}}", "{{Email}}")
    set_title_info("{{DUT}} Test Report")

    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT，每个DUT class 都有 Finish 方法


# 根据需要定义子Bundle
# class MyPort(Bundle):
#     # 定义引脚多个引脚用Signals
#     signal1, signal2 = Signals(2)
#     # 定义单个引脚用Signal
#     signal3 = Signal()
#     # 根据需要定义Port对应的操作
#     def some_operation(self):
#         ...


# 定义{{DUT}}Env类，封装DUT的引脚和常用操作
class {{DUT}}Env:
    '''请在这里对Env的功能进行描述'''

    def __init__(self, dut):
        self.dut = dut
        # 请在这里根据DUT的引脚定义，提供toffee.Bundle进行引脚封装
        #  1.如果引脚有多组，且有不同前缀，请用from_prefix方法
        # self.some_input1 = MyPort.from_prefix("some_input_") # 去掉前缀后的dut引脚必须和MyPort中的引脚成员同名，例如some_input_signal1和signal1对应
        # self.some_input1.bind(dut)
        #  2.如果引脚无法分组，请用from_dict方法进行映射
        # self.some_input2 = MyPort.from_dict({...})
        # self.some_input2.bind(dut)

    # 根据需要定义Env的常用操作
    #def reset(self):
    #    # 根据DUT的复位方式，完成复位操作
    #    ...

    # 直接导出DUT的通用操作Step
    def Step(self, i:int = 1):
        return self.dut.Step(i)


# 定义env fixture, 请取消下面的注释，并根据需要修改名称
@pytest.fixture()
def env(dut):
     # 一般情况下为每个test都创建全新的 env 不需要 yield
     return {{DUT}}Env(dut)


# 定义其他Env
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
#    env.some_input.value = value
#    env.Step()
#    return env.some_output.value
#    # Replace with the actual API function for your DUT
#    ...


# 本文件为模板，请根据需要修改，删除不需要的代码和注释