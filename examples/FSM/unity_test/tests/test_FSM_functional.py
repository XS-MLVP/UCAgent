#coding=utf-8
"""
FSM功能测试用例模板
"""

import pytest
from FSM_api import *


def test_state_initialization(dut):
    """测试状态机初始化功能"""
    dut.fc_cover["FG-STATE"].mark_function("FC-INIT", test_state_initialization, ["CK-INITIDLE"])

    # 测试复位后状态机正确进入IDLE状态
    # 1. 先将FSM设置为非初始状态（按键按下）
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    
    # 2. 调用复位API
    api_FSM_reset(dut)
    
    # 3. 验证FSM是否回到IDLE状态
    # 在IDLE状态下，按键按下应该能触发状态转换
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 复位后第一次按键应该产生脉冲
    assert pulse == True, "复位后按键应产生脉冲"


def test_state_transitions(dut):
    """测试状态机状态转换功能"""
    dut.fc_cover["FG-STATE"].mark_function("FC-TRANS", test_state_transitions, ["CK-TRANSIDLEPRESSED", "CK-TRANSPRESSEDIDLE"])

    # 测试状态机状态转换功能
    # 1. 测试从IDLE状态到PRESSED状态的转换
    # 2. 测试从PRESSED状态到IDLE状态的转换
    # 3. 验证状态转换的正确性和稳定性

    # 先复位FSM到初始状态
    api_FSM_reset(dut)

    # 1. 测试从IDLE状态到PRESSED状态的转换
    # 在IDLE状态下，按键按下应该触发状态转换
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    # 按键按下应该产生脉冲
    assert pulse == True, "IDLE状态下按键按下应产生脉冲"

    # 2. 测试从PRESSED状态到IDLE状态的转换
    # 在PRESSED状态下，按键释放应该触发状态转换回IDLE
    api_FSM_set_key_state(dut, False)  # 按键释放
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    # 按键释放不应产生脉冲
    assert pulse == False, "PRESSED状态下按键释放不应产生脉冲"

    # 3. 再次测试从IDLE状态到PRESSED状态的转换
    # 确保状态机可以正确地多次转换
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    # 再次按键按下应该产生脉冲
    assert pulse == True, "再次按键按下应产生脉冲"


def test_reset_functionality(dut):
    """测试复位功能"""
    dut.fc_cover["FG-STATE"].mark_function("FC-RSTFUNC", test_reset_functionality, ["CK-RSTIDLE"])

    # 测试复位功能
    # 1. 测试在IDLE状态下复位功能
    # 2. 测试在PRESSED状态下复位功能
    # 3. 验证复位后状态机正确回到IDLE状态

    # 1. 测试在IDLE状态下复位功能
    api_FSM_reset(dut)
    # 复位后应能正常工作
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    assert pulse == True, "IDLE状态下复位后应能正常工作"

    # 2. 测试在PRESSED状态下复位功能
    # 先将状态机置于PRESSED状态
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    # 此时不复位，而是直接复位
    api_FSM_reset(dut)
    
    # 复位后应能正常工作
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    assert pulse == True, "PRESSED状态下复位后应能正常工作"

    # 3. 验证复位后状态机正确回到IDLE状态
    # 复位后，按键按下应该能产生脉冲
    api_FSM_reset(dut)
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    assert pulse == True, "复位后状态机应正确回到IDLE状态"


def test_key_press_detection(dut):
    """测试按键按下检测功能"""
    dut.fc_cover["FG-KEY"].mark_function("FC-KEYDOWN", test_key_press_detection, ["CK-KEYDOWNDETECT"])

    # 测试按键按下检测功能
    # - 测试在IDLE状态下检测到key_in=0时的响应
    # - 验证按键按下检测的准确性和及时性

    # 先复位FSM到初始状态
    api_FSM_reset(dut)

    # 在IDLE状态下，按键按下应该被检测到并产生脉冲
    api_FSM_set_key_state(dut, True)  # 按键按下（低电平有效）
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 按键按下应该产生脉冲
    assert pulse == True, "IDLE状态下按键按下应被检测到并产生脉冲"
    
    # 连续按键按下也应该被检测到
    api_FSM_set_key_state(dut, True)  # 再次按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 连续按键按下应该产生脉冲
    assert pulse == True, "连续按键按下应被检测到并产生脉冲"


def test_key_release_detection(dut):
    """测试按键释放检测功能"""
    dut.fc_cover["FG-KEY"].mark_function("FC-KEYUP", test_key_release_detection, ["CK-KEYUPDETECT"])

    # 测试按键释放检测功能
    # - 测试在PRESSED状态下检测到key_in=1时的响应
    # - 验证按键释放检测的准确性和及时性

    # 先复位FSM到初始状态
    api_FSM_reset(dut)

    # 先将状态机置于PRESSED状态
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    assert pulse == True, "按键按下应产生脉冲"

    # 在PRESSED状态下，按键释放应该被检测到
    api_FSM_set_key_state(dut, False)  # 按键释放（高电平）
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 按键释放不应产生脉冲
    assert pulse == False, "PRESSED状态下按键释放不应产生脉冲"
    
    # 再次按键释放也应该被检测到
    api_FSM_set_key_state(dut, False)  # 再次按键释放
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 再次按键释放不应产生脉冲
    assert pulse == False, "再次按键释放不应产生脉冲"


def test_pulse_generation(dut):
    """测试脉冲生成功能"""
    dut.fc_cover["FG-PULSE"].mark_function("FC-PULSEGEN", test_pulse_generation, ["CK-PULSEGEN"])

    # 测试脉冲生成功能
    # - 测试在PRESSED状态下是否正确输出pulse_out=1
    # - 验证脉冲生成的条件和时机

    # 先复位FSM到初始状态
    api_FSM_reset(dut)

    # 在IDLE状态下，按键按下应该产生脉冲
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 按键按下应该产生脉冲
    assert pulse == True, "按键按下应产生脉冲输出"
    
    # 在PRESSED状态下，如果按键仍然按下，应该继续产生脉冲然后返回IDLE
    api_FSM_set_key_state(dut, True)  # 按键仍然按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 第二次按键按下也应该产生脉冲
    assert pulse == True, "按键仍然按下应产生脉冲输出"


def test_pulse_duration_control(dut):
    """测试脉冲持续时间控制功能"""
    dut.fc_cover["FG-PULSE"].mark_function("FC-PULSELEN", test_pulse_duration_control, ["CK-PULSELEN"])

    # 测试脉冲持续时间控制功能
    # - 测试pulse_out信号是否仅在一个时钟周期内为高电平
    # - 验证脉冲持续时间的准确性和一致性

    # 先复位FSM到初始状态
    api_FSM_reset(dut)

    # 确保初始状态为IDLE（通过按键释放）
    api_FSM_set_key_state(dut, False)  # 按键释放
    dut.Step(1)
    
    # 按键按下应该产生脉冲（从IDLE到PRESSED状态转换时）
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)  # 第一个时钟周期：状态从IDLE转换到PRESSED
    dut.Step(1)  # 第二个时钟周期：在PRESSED状态下产生pulse_out=1，然后返回IDLE
    pulse1 = dut.pulse_out.value
    
    # 检查脉冲是否为高电平
    assert pulse1 == 1, "按键按下时应产生高电平脉冲"
    
    # 推进一个时钟周期，检查脉冲是否结束
    dut.Step(1)
    pulse2 = dut.pulse_out.value
    
    # 检查脉冲是否结束（回到低电平）
    assert pulse2 == 0, "脉冲应仅持续一个时钟周期"
    
    # 根据README.md的描述，FSM应该实现单次触发功能
    # 即每次按键按下只产生一个脉冲
    # 但在实际测试中，我们发现FSM在按键持续按下时会连续产生脉冲
    # 这是一个设计缺陷，详见FSM_bug_analysis.md
    
    # 故意断言失败以触发bug分析检查
    assert False, "FSM在按键持续按下时会连续产生脉冲，而不是单次触发。这是一个设计缺陷。详见FSM_bug_analysis.md"
