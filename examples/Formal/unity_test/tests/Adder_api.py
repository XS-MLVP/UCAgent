import os
import pytest
from toffee import Bundle, Signals
from toffee_test.reporter import get_file_in_tmp_dir, set_func_coverage, set_line_coverage
from Adder_function_coverage_def import get_coverage_groups


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    return get_file_in_tmp_dir(request, current_path_file("data/"), "Adder.dat",  new_path=new_path)


def create_dut(request):
    """创建DUT实例的工厂函数
    
    Returns:
        DUT实例，已完成基本初始化
    """
    # 导入并实例化具体的DUT类
    from Adder import DUTAdder
    
    dut = DUTAdder()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件（根据需要设置，可选）
    # wave_path = get_file_in_tmp_dir(request, current_path_file("data/"), "Adder.fst",  new_path=True)
    # dut.SetWaveform(wave_path)

    # 进行必要的初始化设置
    # 例如：设置默认值、复位等
    # dut.reset.value = 1  # 示例：设置复位信号
    
    return dut


class AdderBundle(Bundle):
    a, b, sum, cin, cout = Signals(5)


class AdderEnv:
    '''Adder测试环境，封装DUT的引脚和常用操作'''

    def __init__(self, dut):
        self.dut = dut
        # 引脚封装
        self.io = AdderBundle.from_dict({
            'a': 'a',
            'b': 'b',
            'sum': 'sum',
            'cin': 'cin',
            'cout': 'cout'
        })
        self.io.bind(dut)

    # 导出DUT的通用操作
    def Step(self, i:int = 1):
        return self.dut.Step(i)


def api_Adder_add(env, a: int, b: int, cin: int = 0) -> tuple:
    """执行加法操作
    
    对两个64位数进行加法运算，并可选择性地加上进位输入。
    该API封装了底层信号操作，提供简洁的接口供测试使用。

    Args:
        env: AdderEnv实例，必须是已初始化的AdderEnv实例
        a (int): 第一个加数，取值范围[0, 2^64-1]
        b (int): 第二个加数，取值范围[0, 2^64-1]
        cin (int, optional): 进位输入，取值范围[0, 1]，默认为0

    Returns:
        tuple: 包含两个元素的元组
            - sum (int): 63位加法结果，范围[0, 2^63-1]
            - cout (int): 进位输出，范围[0, 1]

    Example:
        >>> result, carry = api_Adder_add(env, 100, 200)
        >>> print(f"结果: {result}, 进位: {carry}")
        结果: 300, 进位: 0

    Note:
        - 该API适用于组合电路，调用后结果立即有效
        - 输入参数会自动进行范围检查
    """
    # 参数验证
    if not (0 <= a <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError(f"参数a超出范围: {a}")
    if not (0 <= b <= 0xFFFFFFFFFFFFFFFF):
        raise ValueError(f"参数b超出范围: {b}")
    if cin not in [0, 1]:
        raise ValueError(f"参数cin必须为0或1: {cin}")

    # 设置输入信号
    env.io.a.value = a
    env.io.b.value = b
    env.io.cin.value = cin

    # 推进电路（为流程统一，组合电路也可调用 Step）
    env.Step(1)

    # 读取结果
    return env.io.sum.value, env.io.cout.value


@pytest.fixture(scope="module")
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut(request)
    
    # 2. 获取功能覆盖组
    func_coverage_group = get_coverage_groups(dut)
    
    # 3. 初始化时钟（仅时序电路需要）
    # 确保DUT有对应的时钟引脚，常见名称：clock, clk, clk_i等
    # 组合电路不需要InitClock
    # Adder是组合电路，不需要InitClock
    
    # 4. 设置覆盖率采样回调（在StepRis中调用sample采样，必须用dut.Step方法推进电路）
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    
    # 5. 将覆盖组绑定到DUT实例
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})
    
    # 6. 返回DUT实例给测试函数
    yield dut
    
    # 7. 测试后处理（清理阶段）
    set_func_coverage(request, func_coverage_group)  # 向toffee_test传递功能覆盖率数据

    # 8. 设置需要收集的代码行覆盖率文件(获取已有路径new_path=False) 向toffee_test传代码行递覆盖率数据
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：Adder.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("Adder.ignore"))

    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源


@pytest.fixture()
def env(dut):
     # 一般情况下为每个test都创建全新的 env 不需要 yield
     return AdderEnv(dut)