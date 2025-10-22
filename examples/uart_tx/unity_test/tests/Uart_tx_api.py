#coding=utf-8

import pytest
from Uart_tx_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage, set_line_coverage, get_file_in_tmp_dir
from toffee_test.reporter import set_user_info, set_title_info
from toffee import Bundle, Signals, Signal

# import your dut module here
from Uart_tx import DUTUart_tx  # Replace with the actual DUT class import

import os


def current_path_file(file_name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)


def get_coverage_data_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    # 获取测试用例名称，为每个测试用例创建对应的代码行覆盖率文件
    tc_name = request.node.name if request is not None else "Uart_tx"
    return get_file_in_tmp_dir(request, current_path_file("data/"), f"{tc_name}.dat",  new_path=new_path)


def get_waveform_path(request, new_path:bool):
    # 通过toffee_test.reporter提供的get_file_in_tmp_dir方法可以让各用例产生的文件名称不重复 (获取新路径需要new_path=True，获取已有路径new_path=False)
    # 获取测试用例名称，为每个测试用例创建对应的波形
    tc_name = request.node.name if request is not None else "Uart_tx"
    return get_file_in_tmp_dir(request, current_path_file("data/"), f"{tc_name}.fst",  new_path=new_path)


def create_dut(request):
    """创建Uart_tx DUT实例的工厂函数
    
    Uart_tx是一个时序电路模块，需要配置时钟。
    
    Args:
        request: pytest的request对象，用于获取测试用例信息
    
    Returns:
        dut_instance: 已完成基本初始化的Uart_tx DUT实例
    """
    # 创建DUT实例
    dut = DUTUart_tx()

    # 设置覆盖率生成文件(必须设置覆盖率文件，否则无法统计覆盖率，导致测试失败)
    dut.SetCoverage(get_coverage_data_path(request, new_path=True))

    # 设置波形生成文件
    dut.SetWaveform(get_waveform_path(request, new_path=True))

    # Uart_tx是时序电路，需要初始化时钟
    # 根据__init__.py，时钟信号名称为PCLK
    dut.InitClock("PCLK")

    return dut


@pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的DUT
def dut(request):
    # 创建DUT实例（时钟已在create_dut中初始化）
    dut = create_dut(request)
    
    # 获取功能覆盖组
    func_coverage_group = get_coverage_groups(dut)

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
    # 代码行覆盖率 ignore 文件的固定路径为当前文件所在目录下的：Uart_tx.ignore，请不要改变
    set_line_coverage(request, get_coverage_data_path(request, new_path=False), ignore=current_path_file("Uart_tx.ignore"))

    # 设置用户信息到报告
    set_user_info("UCAgent-0.9.1.source-code", "unitychip@bosc.ac.cn")
    set_title_info("Uart_tx Test Report")

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


# 定义Uart_tx的引脚封装Bundle
class FIFOBundle(Bundle):
    """FIFO相关引脚封装"""
    # FIFO数据和控制信号
    PWDATA = Signal()          # 8位并行输入数据
    tx_fifo_push = Signal()    # FIFO写入使能
    # FIFO状态信号
    tx_fifo_empty = Signal()   # FIFO空标志
    tx_fifo_full = Signal()    # FIFO满标志
    tx_fifo_count = Signal()   # FIFO数据计数(5位)


class ControlBundle(Bundle):
    """控制信号封装"""
    LCR = Signal()      # 线控制寄存器(8位)
    enable = Signal()   # 发送使能信号


class OutputBundle(Bundle):
    """输出信号封装"""
    TXD = Signal()      # 串行数据输出
    busy = Signal()     # 发送忙标志


# 定义Uart_txEnv类，封装DUT的引脚和常用操作
class Uart_txEnv:
    '''Uart_tx测试环境类
    
    封装DUT的引脚和常用操作，提供便捷的测试接口。
    包括FIFO控制、配置管理和状态监控等功能。
    '''

    def __init__(self, dut):
        self.dut = dut
        
        # 使用from_dict方法进行引脚映射
        # FIFO相关引脚封装
        self.fifo = FIFOBundle.from_dict({
            "PWDATA": "PWDATA",
            "tx_fifo_push": "tx_fifo_push",
            "tx_fifo_empty": "tx_fifo_empty",
            "tx_fifo_full": "tx_fifo_full",
            "tx_fifo_count": "tx_fifo_count",
        })
        self.fifo.bind(dut)
        
        # 控制信号封装
        self.ctrl = ControlBundle.from_dict({
            "LCR": "LCR",
            "enable": "enable",
        })
        self.ctrl.bind(dut)
        
        # 输出信号封装
        self.output = OutputBundle.from_dict({
            "TXD": "TXD",
            "busy": "busy",
        })
        self.output.bind(dut)
        
        # 时钟和复位信号直接引用（不封装为Bundle）
        self.PRESETn = self.dut.PRESETn
        
        # 初始化所有输入引脚为0
        self.fifo.PWDATA.value = 0
        self.fifo.tx_fifo_push.value = 0
        self.ctrl.LCR.value = 0
        self.ctrl.enable.value = 1  # enable默认为1，允许发送
        self.PRESETn.value = 1  # 复位信号默认为1（非复位状态）
    
    def reset(self):
        """执行复位操作"""
        # 拉低复位信号
        self.PRESETn.value = 0
        self.Step(2)  # 保持复位2个时钟周期
        # 释放复位信号
        self.PRESETn.value = 1
        self.Step(2)  # 等待2个时钟周期稳定
    
    def wait_idle(self):
        """等待DUT进入空闲状态（busy=0且FIFO为空）"""
        timeout = 10000  # 设置超时
        cycles = 0
        while self.output.busy.value == 1 or self.fifo.tx_fifo_empty.value == 0:
            self.Step(1)
            cycles += 1
            if cycles > timeout:
                raise TimeoutError("等待空闲状态超时")
        return cycles
    
    def fifo_push(self, data):
        """向FIFO写入一个字节数据
        
        Args:
            data: 要写入的8位数据
        """
        if self.fifo.tx_fifo_full.value == 1:
            print("警告: FIFO已满，写入可能失败")
        
        self.fifo.PWDATA.value = data & 0xFF
        self.fifo.tx_fifo_push.value = 1
        self.Step(1)
        self.fifo.tx_fifo_push.value = 0
    
    def configure(self, data_bits=8, parity='none', stop_bits=1):
        """配置UART参数
        
        Args:
            data_bits: 数据位宽 (5, 6, 7, 8)
            parity: 校验类型 ('none', 'even', 'odd', 'stick1', 'stick0')
            stop_bits: 停止位 (1, 2)
        """
        lcr = 0
        
        # 配置数据位宽 LCR[1:0]
        data_bits_map = {5: 0, 6: 1, 7: 2, 8: 3}
        lcr |= data_bits_map.get(data_bits, 3)
        
        # 配置停止位 LCR[2]
        if stop_bits == 2:
            lcr |= 0x04
        
        # 配置校验 LCR[5:3]
        parity_map = {
            'none': 0x00,
            'even': 0x08,      # LCR[3]=1, LCR[5:4]=00
            'odd': 0x18,       # LCR[3]=1, LCR[5:4]=01
            'stick1': 0x28,    # LCR[3]=1, LCR[5:4]=10
            'stick0': 0x38,    # LCR[3]=1, LCR[5:4]=11
        }
        lcr |= parity_map.get(parity, 0x00)
        
        self.ctrl.LCR.value = lcr

    # 直接导出DUT的通用操作Step
    def Step(self, i:int = 1):
        return self.dut.Step(i)


# 定义env fixture, 请取消下面的注释，并根据需要修改名称
@pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的Env
def env(dut):
     # 一般情况下为每个test都创建全新的 env 不需要 yield
     return Uart_txEnv(dut)


# 定义其他Env
# @pytest.fixture(scope="function") # 用scope="function"确保每个测试用例都创建了一个全新的Env
# def env1(dut):
#     return MyEnv1(dut)
#


# ============================================================================
#                          Uart_tx 基础 API 函数
# ============================================================================

def api_Uart_tx_reset(env):
    """执行Uart_tx模块的复位操作
    
    对Uart_tx执行完整的复位流程，清空FIFO，复位所有状态寄存器和输出信号。
    复位完成后，模块处于初始化的空闲状态。
    
    Args:
        env: Uart_txEnv实例，必须是已初始化的Uart_tx测试环境
        
    Returns:
        None
        
    Example:
        >>> api_Uart_tx_reset(env)
        >>> assert env.output.busy.value == 0  # 复位后应该空闲
        
    Note:
        - 复位信号PRESETn为低电平有效
        - 复位持续2个时钟周期，释放后等待2个时钟周期稳定
        - 复位后enable默认为1，允许发送操作
    """
    env.reset()


def api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1):
    """配置Uart_tx的传输参数
    
    设置UART帧格式，包括数据位宽、校验类型和停止位数量。
    配置通过LCR（线控制寄存器）实现，立即生效。
    
    Args:
        env: Uart_txEnv实例
        data_bits (int): 数据位宽，可选值: 5, 6, 7, 8，默认为8
                        表示每帧发送的数据位数量
        parity (str): 校验类型，可选值: 'none', 'even', 'odd', 'stick1', 'stick0'
                     - 'none': 无校验（默认）
                     - 'even': 偶校验
                     - 'odd': 奇校验
                     - 'stick1': 固定1校验
                     - 'stick0': 固定0校验
        stop_bits (int): 停止位数量，可选值: 1, 2，默认为1
                        5位数据时2停止位为1.5位，其他为2位
        
    Returns:
        None
        
    Raises:
        ValueError: 当参数值不在有效范围内时抛出
        
    Example:
        >>> # 配置为8-N-1（8位数据，无校验，1位停止位）
        >>> api_Uart_tx_configure(env, data_bits=8, parity='none', stop_bits=1)
        >>> 
        >>> # 配置为7-E-1（7位数据，偶校验，1位停止位）
        >>> api_Uart_tx_configure(env, data_bits=7, parity='even', stop_bits=1)
        
    Note:
        - 配置可以在任何时候修改
        - 正在发送的当前帧使用旧配置，下一帧使用新配置
        - 标准配置8-N-1最为常用
    """
    # 参数验证
    if data_bits not in [5, 6, 7, 8]:
        raise ValueError(f"data_bits必须是5, 6, 7, 8之一，当前值: {data_bits}")
    if parity not in ['none', 'even', 'odd', 'stick1', 'stick0']:
        raise ValueError(f"parity必须是'none', 'even', 'odd', 'stick1', 'stick0'之一，当前值: {parity}")
    if stop_bits not in [1, 2]:
        raise ValueError(f"stop_bits必须是1或2，当前值: {stop_bits}")
    
    env.configure(data_bits, parity, stop_bits)


def api_Uart_tx_send_byte(env, data):
    """向Uart_tx的FIFO写入一个字节数据
    
    将8位数据写入Uart_tx的发送FIFO。如果FIFO未满，数据将被成功写入；
    如果FIFO已满，函数会打印警告但仍执行写入操作（数据可能被丢弃）。
    
    Args:
        env: Uart_txEnv实例
        data (int): 要发送的8位数据，范围[0x00, 0xFF]
        
    Returns:
        bool: 写入成功返回True，FIFO已满时返回False
        
    Raises:
        ValueError: 当数据超出8位范围时抛出
        
    Example:
        >>> success = api_Uart_tx_send_byte(env, 0x55)
        >>> if success:
        >>>     print("数据写入成功")
        
    Note:
        - FIFO深度为16字节
        - 写入操作占用1个时钟周期
        - 如果enable=1且FIFO非空，数据会自动开始发送
    """
    # 参数验证
    if not (0 <= data <= 0xFF):
        raise ValueError(f"data必须在0x00-0xFF范围内，当前值: 0x{data:02X}")
    
    # 检查FIFO是否已满
    is_full = env.fifo.tx_fifo_full.value == 1
    if is_full:
        print(f"警告: FIFO已满，写入数据0x{data:02X}可能失败")
    
    # 执行写入
    env.fifo_push(data)
    
    return not is_full


def api_Uart_tx_send_bytes(env, data_list):
    """向Uart_tx的FIFO批量写入多个字节
    
    依次将多个字节写入FIFO。如果FIFO空间不足，会在满后停止写入。
    
    Args:
        env: Uart_txEnv实例
        data_list (list): 要发送的数据列表，每个元素为0x00-0xFF的整数
        
    Returns:
        int: 实际成功写入的字节数
        
    Raises:
        ValueError: 当列表中任何数据超出8位范围时抛出
        
    Example:
        >>> data = [0x48, 0x65, 0x6C, 0x6C, 0x6F]  # "Hello"
        >>> count = api_Uart_tx_send_bytes(env, data)
        >>> print(f"写入了{count}个字节")
        
    Note:
        - 函数会依次写入每个字节，每次占用1个时钟周期
        - 如果FIFO在写入过程中变满，会停止后续写入
        - 建议单次写入不超过16个字节（FIFO容量）
    """
    # 参数验证
    for i, data in enumerate(data_list):
        if not (0 <= data <= 0xFF):
            raise ValueError(f"data_list[{i}]超出范围: 0x{data:02X}")
    
    success_count = 0
    for data in data_list:
        if api_Uart_tx_send_byte(env, data):
            success_count += 1
        else:
            # FIFO已满，停止写入
            break
    
    return success_count


def api_Uart_tx_wait_idle(env, timeout=10000):
    """等待Uart_tx完成所有发送操作并进入空闲状态
    
    轮询检查busy和FIFO状态，直到busy=0且FIFO为空，表示所有数据已发送完成。
    如果超时，抛出TimeoutError异常。
    
    Args:
        env: Uart_txEnv实例
        timeout (int): 最大等待时钟周期数，默认10000周期
                      设置为0表示无超时限制（不推荐）
        
    Returns:
        int: 实际等待的时钟周期数
        
    Raises:
        TimeoutError: 当等待时间超过timeout时抛出
        ValueError: 当timeout为负数时抛出
        
    Example:
        >>> api_Uart_tx_send_byte(env, 0xAA)
        >>> cycles = api_Uart_tx_wait_idle(env, timeout=5000)
        >>> print(f"发送完成，耗时{cycles}个时钟周期")
        
    Note:
        - UART传输速度取决于波特率配置（16个时钟周期/位）
        - 一个完整的8-N-1帧需要10位 × 16 = 160个时钟周期
        - 建议timeout设置至少为：(FIFO字节数 + 1) × 200
    """
    # 参数验证
    if timeout < 0:
        raise ValueError(f"timeout不能为负数: {timeout}")
    
    cycles = 0
    max_cycles = timeout if timeout > 0 else float('inf')
    
    while env.output.busy.value == 1 or env.fifo.tx_fifo_empty.value == 0:
        env.Step(1)
        cycles += 1
        if cycles > max_cycles:
            raise TimeoutError(f"等待空闲超时，已等待{cycles}个时钟周期")
    
    return cycles


def api_Uart_tx_get_fifo_status(env):
    """获取Uart_tx FIFO的当前状态
    
    读取FIFO的empty、full和count状态信号，返回完整的FIFO状态信息。
    
    Args:
        env: Uart_txEnv实例
        
    Returns:
        dict: FIFO状态字典，包含以下键：
            - 'empty' (bool): FIFO是否为空
            - 'full' (bool): FIFO是否已满
            - 'count' (int): FIFO中的数据字节数（0-16）
            - 'free_space' (int): FIFO中的剩余空间字节数（0-16）
            
    Example:
        >>> status = api_Uart_tx_get_fifo_status(env)
        >>> print(f"FIFO: {status['count']}/16，剩余{status['free_space']}字节")
        >>> if status['full']:
        >>>     print("FIFO已满，无法继续写入")
        
    Note:
        - 该函数只读取状态，不修改任何信号
        - 读取操作不占用额外时钟周期
        - FIFO容量固定为16字节
    """
    count = env.fifo.tx_fifo_count.value
    return {
        'empty': env.fifo.tx_fifo_empty.value == 1,
        'full': env.fifo.tx_fifo_full.value == 1,
        'count': count,
        'free_space': 16 - count
    }


def api_Uart_tx_set_enable(env, enable):
    """设置Uart_tx的enable控制信号
    
    控制Uart_tx的发送使能。enable=1时允许发送，enable=0时暂停发送。
    暂停时会保持当前状态，恢复时从暂停处继续。
    
    Args:
        env: Uart_txEnv实例
        enable (bool): True或1表示使能，False或0表示禁止
        
    Returns:
        None
        
    Example:
        >>> # 禁止发送
        >>> api_Uart_tx_set_enable(env, False)
        >>> # 恢复发送
        >>> api_Uart_tx_set_enable(env, True)
        
    Note:
        - enable=0时，bit_counter停止计数，发送暂停
        - 暂停期间TXD和状态保持不变
        - 恢复后从暂停处继续，不会丢失数据
    """
    env.ctrl.enable.value = 1 if enable else 0
    env.Step(1)  # 推进一个时钟周期使设置生效


def api_Uart_tx_monitor_txd(env, bit_count, sample_rate=16):
    """监控TXD输出，捕获指定数量的位
    
    在指定的时钟周期内采样TXD信号，用于验证UART帧格式和数据传输。
    每个位由sample_rate个时钟周期组成，在中间位置采样。
    
    Args:
        env: Uart_txEnv实例
        bit_count (int): 要捕获的位数量，范围[1, 100]
        sample_rate (int): 每位的时钟周期数，默认16（标准UART波特率）
        
    Returns:
        list: 采样得到的位序列，每个元素为0或1
        
    Raises:
        ValueError: 当参数超出有效范围时抛出
        TimeoutError: 当busy长时间保持高电平时抛出
        
    Example:
        >>> # 发送一个字节
        >>> api_Uart_tx_send_byte(env, 0x55)  # 0b01010101
        >>> # 捕获完整的8-N-1帧（1起始位+8数据位+1停止位=10位）
        >>> bits = api_Uart_tx_monitor_txd(env, 10)
        >>> assert bits[0] == 0  # 起始位
        >>> assert bits[-1] == 1  # 停止位
        
    Note:
        - 采样点在每个位周期的中间位置（第8个时钟周期）
        - 该函数会阻塞直到采样完成
        - 适用于验证帧格式、数据正确性、校验位等
    """
    # 参数验证
    if not (1 <= bit_count <= 100):
        raise ValueError(f"bit_count必须在1-100范围内，当前值: {bit_count}")
    if not (1 <= sample_rate <= 32):
        raise ValueError(f"sample_rate必须在1-32范围内，当前值: {sample_rate}")
    
    bits = []
    sample_offset = sample_rate // 2  # 在每个位周期的中间采样
    
    for i in range(bit_count):
        # 等待到采样点
        for _ in range(sample_offset):
            env.Step(1)
        
        # 采样TXD
        bits.append(env.output.TXD.value)
        
        # 等待到下一个位的开始
        for _ in range(sample_rate - sample_offset):
            env.Step(1)
    
    return bits


def api_Uart_tx_parse_frame(bits, data_bits=8, parity='none'):
    """解析UART帧，提取数据和校验位
    
    从捕获的位序列中解析UART帧结构，验证起始位、数据位、校验位和停止位。
    
    Args:
        bits (list): 通过api_Uart_tx_monitor_txd捕获的位序列
        data_bits (int): 数据位宽度，可选值: 5, 6, 7, 8
        parity (str): 校验类型，可选值: 'none', 'even', 'odd', 'stick1', 'stick0'
        
    Returns:
        dict: 解析结果字典，包含：
            - 'valid' (bool): 帧是否有效
            - 'data' (int): 提取的数据值
            - 'start_bit' (int): 起始位值（应该为0）
            - 'data_bits' (list): 数据位列表
            - 'parity_bit' (int): 校验位值（如果有）
            - 'stop_bit' (int): 停止位值（应该为1）
            - 'error' (str): 错误描述（如果有）
            
    Example:
        >>> bits = api_Uart_tx_monitor_txd(env, 10)
        >>> frame = api_Uart_tx_parse_frame(bits, data_bits=8, parity='none')
        >>> if frame['valid']:
        >>>     print(f"接收到数据: 0x{frame['data']:02X}")
        
    Note:
        - UART采用LSB-first顺序传输
        - 起始位必须为0，停止位必须为1
        - 如果帧无效，error字段会包含错误原因
    """
    result = {
        'valid': False,
        'data': 0,
        'start_bit': None,
        'data_bits': [],
        'parity_bit': None,
        'stop_bit': None,
        'error': None
    }
    
    # 计算期望的帧长度
    expected_len = 1 + data_bits  # 起始位 + 数据位
    if parity != 'none':
        expected_len += 1  # 校验位
    expected_len += 1  # 停止位
    
    # 检查位序列长度
    if len(bits) < expected_len:
        result['error'] = f"位序列太短，需要{expected_len}位，实际{len(bits)}位"
        return result
    
    idx = 0
    
    # 解析起始位
    result['start_bit'] = bits[idx]
    if result['start_bit'] != 0:
        result['error'] = f"起始位错误，应为0，实际为{result['start_bit']}"
        return result
    idx += 1
    
    # 解析数据位（LSB first）
    result['data_bits'] = bits[idx:idx+data_bits]
    data_value = 0
    for i, bit in enumerate(result['data_bits']):
        data_value |= (bit << i)
    result['data'] = data_value
    idx += data_bits
    
    # 解析校验位（如果有）
    if parity != 'none':
        result['parity_bit'] = bits[idx]
        idx += 1
        
        # 验证校验位
        data_parity = sum(result['data_bits']) % 2
        expected_parity = None
        if parity == 'even':
            expected_parity = data_parity
        elif parity == 'odd':
            expected_parity = 1 - data_parity
        elif parity == 'stick1':
            expected_parity = 1
        elif parity == 'stick0':
            expected_parity = 0
        
        if expected_parity is not None and result['parity_bit'] != expected_parity:
            result['error'] = f"校验位错误，期望{expected_parity}，实际{result['parity_bit']}"
            return result
    
    # 解析停止位
    result['stop_bit'] = bits[idx]
    if result['stop_bit'] != 1:
        result['error'] = f"停止位错误，应为1，实际为{result['stop_bit']}"
        return result
    
    result['valid'] = True
    return result


def api_Uart_tx_send_and_verify(env, data, data_bits=8, parity='none', stop_bits=1):
    """发送数据并验证TXD输出的正确性
    
    这是一个高层API，结合发送、监控和验证功能。发送一个字节数据，
    捕获TXD输出，并验证帧格式和数据正确性。
    
    Args:
        env: Uart_txEnv实例
        data (int): 要发送的数据，范围[0x00, 0xFF]
        data_bits (int): 数据位宽，可选值: 5, 6, 7, 8，默认8
        parity (str): 校验类型，默认'none'
        stop_bits (int): 停止位数量，可选值: 1, 2，默认1
        
    Returns:
        dict: 验证结果，包含：
            - 'success' (bool): 验证是否成功
            - 'sent_data' (int): 发送的数据
            - 'received_data' (int): 从TXD解析出的数据
            - 'frame' (dict): 完整的帧解析结果
            - 'error' (str): 错误描述（如果有）
            
    Raises:
        ValueError: 当参数超出有效范围时抛出
        
    Example:
        >>> result = api_Uart_tx_send_and_verify(env, 0xA5, data_bits=8, parity='even')
        >>> assert result['success'], result['error']
        >>> assert result['received_data'] == 0xA5
        
    Note:
        - 自动配置UART参数
        - 自动计算需要捕获的位数
        - 验证数据、校验位和帧格式
    """
    # 配置UART
    api_Uart_tx_configure(env, data_bits, parity, stop_bits)
    
    # 清空FIFO并发送数据
    api_Uart_tx_reset(env)
    api_Uart_tx_send_byte(env, data)
    
    # 等待发送开始（busy变高）
    timeout = 100
    cycles = 0
    while env.output.busy.value == 0:
        env.Step(1)
        cycles += 1
        if cycles > timeout:
            return {
                'success': False,
                'sent_data': data,
                'received_data': None,
                'frame': None,
                'error': '等待发送开始超时'
            }
    
    # 计算帧长度
    frame_len = 1 + data_bits  # 起始位 + 数据位
    if parity != 'none':
        frame_len += 1
    frame_len += stop_bits
    
    # 监控TXD
    bits = api_Uart_tx_monitor_txd(env, frame_len)
    
    # 解析帧
    frame = api_Uart_tx_parse_frame(bits, data_bits, parity)
    
    # 验证结果
    result = {
        'success': frame['valid'] and frame['data'] == data,
        'sent_data': data,
        'received_data': frame['data'] if frame['valid'] else None,
        'frame': frame,
        'error': frame['error'] if not frame['valid'] else None
    }
    
    return result


# 本文件为模板，请根据需要修改，删除不需要的代码和注释