#coding=utf-8

import pytest
from Mux_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage, set_line_coverage, get_file_in_tmp_dir
from toffee import Bundle, Signals

# import your dut module here
from Mux import DUTMux  # Replace with the actual DUT class import

import os


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    return get_file_in_tmp_dir(request, current_path_file("data/"), "Mux.dat",  new_path=new_path)


def create_dut(request):
    """
    Create a new instance of the Mux for testing.
    
    Returns:
        dut_instance: An instance of the Mux class.
    """
    # Replace with the actual instantiation and initialization of your DUT
    dut = DUTMux()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件（根据需要设置，可选）
    # wave_path = get_file_in_tmp_dir(request, current_path_file("data/"), "Mux.fst",  new_path=True)
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
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：Mux.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("Mux.ignore"))

    for g in func_coverage_group:                        # 采样覆盖组
        g.clear()                                        # 清空统计
    dut.Finish()                                         # 清理DUT，每个DUT class 都有 Finish 方法


# 定义Mux的引脚Bundle
class MuxIO(Bundle):
    in_data, sel, out = Signals(3)
    # 根据需要定义Port对应的操作
    def some_operation(self):
        pass


# 定义MuxEnv类，封装DUT的引脚和常用操作
class MuxEnv:
    '''Mux测试环境，封装了DUT的引脚和常用操作'''

    def __init__(self, dut):
        self.dut = dut
        # Mux的引脚封装
        self.io = MuxIO.from_dict({
            'in_data': 'in_data',
            'sel': 'sel',
            'out': 'out'
        })
        self.io.bind(dut)

    # 根据需要定义Env的常用操作
    def reset(self):
        # Mux是组合电路，没有复位信号，这里提供一个空实现
        pass

    def select_input(self, sel_value, in_data_value):
        '''设置选择信号和输入数据'''
        self.io.sel.value = sel_value
        self.io.in_data.value = in_data_value
        self.Step()

    def get_output(self):
        '''获取输出值'''
        return self.io.out.value

    # 直接导出DUT的通用操作Step
    def Step(self, i:int = 1):
        return self.dut.Step(i)


# 定义env fixture, 请取消下面的注释，并根据需要修改名称
@pytest.fixture()
def env(dut):
     # 一般情况下为每个test都创建全新的 env 不需要 yield
     return MuxEnv(dut)


# 定义其他Env
# @pytest.fixture()
# def env1(dut):
#     return MyEnv1(dut)
#


def api_Mux_select(env, in_data: int, sel: int) -> int:
    """根据选择信号从输入数据中选择对应的位并输出
    
    该API用于控制Mux多路选择器，根据2位选择信号从4位输入数据中选择对应的位输出。
    Mux是一个组合电路，输入信号设置后立即生效。
    
    Args:
        env: MuxEnv实例，已初始化的Mux测试环境
        in_data (int): 4位输入数据，范围[0, 15]，每一位对应一个输入通道
                      bit[0]对应输入通道0，bit[1]对应输入通道1，以此类推
        sel (int): 2位选择信号，范围[0, 3]，用于选择输出哪个输入通道
                  0表示选择in_data[0]，1表示选择in_data[1]，2表示选择in_data[2]，3表示选择in_data[0]（默认路径）
        
    Returns:
        int: 选择的输出值，0或1
        
    Raises:
        ValueError: 当参数超出有效范围时抛出
        
    Example:
        >>> output = api_Mux_select(env, 0b1010, 0b01)
        >>> print(f"输出值: {output}")
        输出值: 1
        
    Note:
        - 该API适用于组合电路，调用后立即得到结果
        - 当sel=3时，会选择in_data[0]作为输出（默认路径）
    """
    # 参数验证
    if not (0 <= in_data <= 0xF):
        raise ValueError(f"输入数据超出范围[0, 15]: {in_data}")
    if not (0 <= sel <= 0x3):
        raise ValueError(f"选择信号超出范围[0, 3]: {sel}")
    
    # 设置输入信号
    env.io.in_data.value = in_data
    env.io.sel.value = sel
    
    # 推进电路（组合电路一般立即有效；为流程统一仍调用Step）
    env.Step(1)
    
    # 读取结果
    return env.io.out.value


# 本文件为模板，请根据需要修改，删除不需要的代码和注释