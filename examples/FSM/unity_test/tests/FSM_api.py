#coding=utf-8

import pytest
from FSM_function_coverage_def import get_coverage_groups
from toffee_test.reporter import set_func_coverage

# import your dut module here
from FSM import DUTFSM  # Replace with the actual DUT class import


def create_dut():
    """
    Create a new instance of the FSM for testing.
    
    Returns:
        dut_instance: An instance of the FSM class.
    """
    # 创建DUT实例
    dut = DUTFSM()
    
    # 初始化时钟，FSM是一个时序电路
    dut.InitClock("clk")
    
    # 设置初始状态：复位信号为高电平（复位状态）
    dut.reset.value = 1
    
    return dut


@pytest.fixture()
def dut(request):
    # 1. 创建DUT实例
    dut = create_dut()
    
    # 2. 获取功能覆盖组
    func_coverage_group = get_coverage_groups(dut)
    
    # 3. 初始化时钟（仅时序电路需要）
    # FSM是时序电路，需要时钟驱动
    # 时钟已经在create_dut中初始化，这里不再重复
    
    # 4. 设置覆盖率采样回调
    dut.StepRis(lambda _: [g.sample() for g in func_coverage_group])
    
    # 5. 将覆盖组绑定到DUT实例
    setattr(dut, "fc_cover", {g.name: g for g in func_coverage_group})
    
    # 6. 返回DUT实例给测试函数
    yield dut
    
    # 7. 测试后处理（清理阶段）
    set_func_coverage(request, func_coverage_group)  # 向toffee_test传递覆盖率数据
    for g in func_coverage_group:
        g.clear()  # 清空覆盖率统计
    dut.Finish()   # 清理DUT资源


def api_FSM_reset(dut):
    """将FSM重置到初始状态
    
    该API将FSM的reset信号置为高电平一个时钟周期，然后恢复为低电平，
    使FSM回到IDLE状态。
    
    Args:
        dut: FSM DUT实例，必须是已初始化的DUTFSM对象
        
    Returns:
        None
        
    Example:
        >>> api_FSM_reset(dut)
        >>> # FSM现在处于IDLE状态
    """
    # 设置复位信号为高电平
    dut.reset.value = 1
    # 推进一个时钟周期
    dut.Step(1)
    # 恢复复位信号为低电平
    dut.reset.value = 0


def api_FSM_set_key_state(dut, pressed):
    """设置按键状态
    
    该API用于设置FSM的按键输入状态。
    
    Args:
        dut: FSM DUT实例，必须是已初始化的DUTFSM对象
        pressed (bool): 按键状态，True表示按下(低电平)，False表示释放(高电平)
        
    Returns:
        None
        
    Example:
        >>> api_FSM_set_key_state(dut, True)   # 模拟按键按下
        >>> api_FSM_set_key_state(dut, False)  # 模拟按键释放
    """
    # 设置按键输入信号，低电平有效
    dut.key_in.value = 0 if pressed else 1


def api_FSM_step_and_check_pulse(dut):
    """推进一个时钟周期并检查脉冲输出
    
    该API推进一个时钟周期，并返回脉冲输出的状态。
    
    Args:
        dut: FSM DUT实例，必须是已初始化的DUTFSM对象
        
    Returns:
        bool: 脉冲输出状态，True表示有脉冲输出，False表示无脉冲输出
        
    Example:
        >>> api_FSM_set_key_state(dut, True)
        >>> dut.Step(1)  # 推进一个时钟周期
        >>> pulse = api_FSM_step_and_check_pulse(dut)
        >>> print(f"脉冲输出: {pulse}")
    """
    # 推进一个时钟周期
    dut.Step(1)
    # 返回脉冲输出状态
    return bool(dut.pulse_out.value)


def api_FSM_press_key_and_wait_pulse(dut, wait_cycles=10):
    """模拟按键按下并等待脉冲输出
    
    该API模拟按键按下操作，并等待FSM产生脉冲输出。
    这是一个高层API，封装了完整的按键处理流程。
    
    Args:
        dut: FSM DUT实例，必须是已初始化的DUTFSM对象
        wait_cycles (int, optional): 等待脉冲输出的最大时钟周期数，默认为10
        
    Returns:
        bool: 是否检测到脉冲输出，True表示检测到，False表示未检测到
        
    Example:
        >>> # 确保FSM处于IDLE状态
        >>> api_FSM_reset(dut)
        >>> # 模拟按键按下并等待脉冲
        >>> pulse_detected = api_FSM_press_key_and_wait_pulse(dut)
        >>> assert pulse_detected, "应产生脉冲输出"
    """
    # 设置按键为按下状态
    api_FSM_set_key_state(dut, True)
    
    # 等待脉冲输出
    for _ in range(wait_cycles):
        if api_FSM_step_and_check_pulse(dut):
            # 检测到脉冲输出，返回True
            return True
            
    # 未检测到脉冲输出，返回False
    return False
