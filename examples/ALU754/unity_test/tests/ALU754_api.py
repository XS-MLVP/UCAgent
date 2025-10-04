import os
import pytest
from toffee_test.reporter import get_file_in_tmp_dir, set_func_coverage, set_line_coverage
from toffee_test.reporter import set_user_info, set_title_info
from toffee import Bundle, Signals


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path: bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    return get_file_in_tmp_dir(request, current_path_file("data/"), "ALU754.dat", new_path=new_path)


def create_dut(request):
    """创建DUT实例的工厂函数

    Returns:
        DUT实例，已完成基本初始化
    """
    # 导入并实例化具体的DUT类
    from ALU754 import DUTALU754

    dut = DUTALU754()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # ALU754是组合电路，不需要时钟初始化
    # 设置默认值
    dut.a.value = 0
    dut.b.value = 0
    dut.op.value = 0

    return dut


@pytest.fixture(scope="module")
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut(request)

    # 2. 获取功能覆盖组
    from ALU754_function_coverage_def import get_coverage_groups
    func_coverage_group = get_coverage_groups(dut)

    # 3. ALU754是组合电路，不需要初始化时钟
    # 检查是否有时钟引脚，如果有则初始化（虽然ALU754没有时钟）
    clock_names = ['clock', 'clk', 'clk_i', 'clk_in', 'sys_clk']
    for clk_name in clock_names:
        if hasattr(dut, clk_name):
            dut.InitClock(clk_name)
            print(f"时钟已初始化: {clk_name}")
            break

    # 4. 设置覆盖率采样回调（在StepRis中调用sample采样，必须用dut.Step方法推进电路）
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])

    # 5. 将覆盖组绑定到DUT实例
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})

    # 6. 返回DUT实例给测试函数
    yield dut

    # 7. 测试后处理（清理阶段）
    set_func_coverage(request, func_coverage_group)  # 向toffee_test传递功能覆盖率数据

    # 8. 设置需要收集的代码行覆盖率文件(获取已有路径new_path=False) 向toffee_test传代码行递覆盖率数据
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：ALU754.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("ALU754.ignore"))

    # 9. 设置用户信息到报告 (以下信息请使用模板中给出的值)
    set_user_info("UCAgent-1.0", "user@example.com")
    set_title_info("ALU754 Test Report")

    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源


# 定义ALU754的输入Bundle
class ALU754InputBundle(Bundle):
    """ALU754输入信号Bundle"""
    a, b, op = Signals(3)


# 定义ALU754的输出Bundle
class ALU754OutputBundle(Bundle):
    """ALU754输出信号Bundle"""
    result, overflow, underflow, gt, lt, eq = Signals(6)


# 定义ALU754Env类，封装DUT的引脚和常用操作
class ALU754Env:
    '''ALU754测试环境，封装输入输出引脚和常用操作'''
    
    def __init__(self, dut):
        self.dut = dut
        
        # 封装输入引脚
        self.io_input = ALU754InputBundle()
        self.io_input.bind(dut)
        
        # 封装输出引脚
        self.io_output = ALU754OutputBundle()
        self.io_output.bind(dut)

    def Step(self, i: int = 1):
        """推进DUT的时钟步数
        
        Args:
            i: 步数，默认为1
        """
        return self.dut.Step(i)

    def set_input(self, a=None, b=None, op=None):
        """设置输入值
        
        Args:
            a: 操作数a的值
            b: 操作数b的值
            op: 操作码
        """
        if a is not None:
            self.io_input.a.value = a
        if b is not None:
            self.io_input.b.value = b
        if op is not None:
            self.io_input.op.value = op

    def get_output(self):
        """获取输出值
        
        Returns:
            dict: 包含所有输出信号值的字典
        """
        return {
            'result': self.io_output.result.value,
            'overflow': self.io_output.overflow.value,
            'underflow': self.io_output.underflow.value,
            'gt': self.io_output.gt.value,
            'lt': self.io_output.lt.value,
            'eq': self.io_output.eq.value
        }


# 定义env fixture
@pytest.fixture()
def env(dut):
    # 一般情况下为每个test都创建全新的 env 不需要 yield
    return ALU754Env(dut)


def api_ALU754_operate(env, a: int, b: int, operation: int) -> dict:
    """执行ALU754运算操作
    
    该函数是ALU754的基础操作API，用于执行指定的运算操作。
    支持加法、乘法、除法和比较操作。

    Args:
        env: ALU754Env实例，已初始化的测试环境
        a (int): 第一个操作数，32位IEEE 754单精度浮点数，用整数表示
        b (int): 第二个操作数，32位IEEE 754单精度浮点数，用整数表示
        operation (int): 操作码
                         0 - 加法 (a + b)
                         1 - 乘法 (a * b) 
                         2 - 除法 (a / b)
                         3 - 比较 (比较a和b的大小关系)
                         其他值 - 保留

    Returns:
        dict: 包含运算结果的字典
            {
                'result': 运算结果 (32位整数，对于比较操作为0),
                'overflow': 溢出标志 (1为溢出，0为正常),
                'underflow': 下溢标志 (1为下溢，0为正常),
                'gt': 大于标志 (当操作码为3时，a>b为1，否则为0),
                'lt': 小于标志 (当操作码为3时，a<b为1，否则为0),
                'eq': 等于标志 (当操作码为3时，a==b为1，否则为0)
            }

    Note:
        - 该API适用于ALU754的组合电路操作
        - 组合电路一般立即有效，调用Step(1)来推进电路
    """
    # 参数验证
    if not (0 <= a <= 0xFFFFFFFF):
        raise ValueError(f"参数a超出范围: {a}")
    if not (0 <= b <= 0xFFFFFFFF):
        raise ValueError(f"参数b超出范围: {b}")
    if not (0 <= operation <= 7):  # 使用最大可能的op值范围
        raise ValueError(f"操作码超出范围: {operation}")
    
    # 设置输入信号
    env.io_input.a.value = a
    env.io_input.b.value = b
    env.io_input.op.value = operation

    # 推进电路（组合电路一般立即有效，但为统一流程调用Step）
    env.Step(1)

    # 读取输出结果
    outputs = env.get_output()
    
    return outputs


def api_ALU754_add(env, a: int, b: int) -> dict:
    """执行ALU754加法运算
    
    该函数基于基础操作API实现，专门用于执行加法运算。

    Args:
        env: ALU754Env实例，已初始化的测试环境
        a (int): 第一个操作数，32位IEEE 754单精度浮点数，用整数表示
        b (int): 第二个操作数，32位IEEE 754单精度浮点数，用整数表示

    Returns:
        dict: 包含加法运算结果的字典
            {
                'result': 加法运算结果,
                'overflow': 溢出标志,
                'underflow': 下溢标志,
                'gt': 0 (加法操作此标志无效),
                'lt': 0 (加法操作此标志无效),
                'eq': 0 (加法操作此标志无效)
            }
    """
    return api_ALU754_operate(env, a, b, 0)  # 0表示加法操作


def api_ALU754_mul(env, a: int, b: int) -> dict:
    """执行ALU754乘法运算
    
    该函数基于基础操作API实现，专门用于执行乘法运算。

    Args:
        env: ALU754Env实例，已初始化的测试环境
        a (int): 第一个操作数，32位IEEE 754单精度浮点数，用整数表示
        b (int): 第二个操作数，32位IEEE 754单精度浮点数，用整数表示

    Returns:
        dict: 包含乘法运算结果的字典
            {
                'result': 乘法运算结果,
                'overflow': 溢出标志,
                'underflow': 下溢标志,
                'gt': 0 (乘法操作此标志无效),
                'lt': 0 (乘法操作此标志无效),
                'eq': 0 (乘法操作此标志无效)
            }
    """
    return api_ALU754_operate(env, a, b, 1)  # 1表示乘法操作


def api_ALU754_div(env, a: int, b: int) -> dict:
    """执行ALU754除法运算
    
    该函数基于基础操作API实现，专门用于执行除法运算。

    Args:
        env: ALU754Env实例，已初始化的测试环境
        a (int): 被除数，32位IEEE 754单精度浮点数，用整数表示
        b (int): 除数，32位IEEE 754单精度浮点数，用整数表示

    Returns:
        dict: 包含除法运算结果的字典
            {
                'result': 除法运算结果,
                'overflow': 溢出标志,
                'underflow': 下溢标志,
                'gt': 0 (除法操作此标志无效),
                'lt': 0 (除法操作此标志无效),
                'eq': 0 (除法操作此标志无效)
            }
    """
    return api_ALU754_operate(env, a, b, 2)  # 2表示除法操作


def api_ALU754_compare(env, a: int, b: int) -> dict:
    """执行ALU754比较运算
    
    该函数基于基础操作API实现，专门用于比较两个浮点数的大小关系。

    Args:
        env: ALU754Env实例，已初始化的测试环境
        a (int): 第一个操作数，32位IEEE 754单精度浮点数，用整数表示
        b (int): 第二个操作数，32位IEEE 754单精度浮点数，用整数表示

    Returns:
        dict: 包含比较结果的字典
            {
                'result': 0 (比较操作不产生结果),
                'overflow': 0 (比较操作无溢出),
                'underflow': 0 (比较操作无下溢),
                'gt': a > b 的结果 (1为真，0为假),
                'lt': a < b 的结果 (1为真，0为假),
                'eq': a == b 的结果 (1为真，0为假)
            }
    """
    return api_ALU754_operate(env, a, b, 3)  # 3表示比较操作