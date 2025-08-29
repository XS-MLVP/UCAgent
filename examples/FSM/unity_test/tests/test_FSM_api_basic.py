#coding=utf-8
"""
FSM API测试文件
"""

import pytest
from FSM_api import *


def test_api_FSM_reset(dut):
    """测试FSM重置API基础功能

    测试目标:
        验证api_FSM_reset函数能正确将FSM重置到初始状态

    测试流程:
        1. 将FSM设置为非初始状态（模拟按键按下）
        2. 调用api_FSM_reset函数重置FSM
        3. 验证FSM是否回到初始状态

    预期结果:
        - FSM应正确重置到IDLE状态
        - 无异常抛出
    """
    # 标记覆盖率
    dut.fc_cover["FG-STATE"].mark_function("FC-INIT", test_api_FSM_reset, ["CK-INITIDLE"])
    dut.fc_cover["FG-STATE"].mark_function("FC-RSTFUNC", test_api_FSM_reset, ["CK-RSTIDLE"])
    
    # 先将FSM设置为非初始状态（按键按下）
    api_FSM_set_key_state(dut, True)
    dut.Step(1)
    
    # 调用重置API
    api_FSM_reset(dut)
    
    # 验证FSM是否回到初始状态
    # 在初始状态下，pulse_out应为0且按键未按下时应无脉冲
    api_FSM_set_key_state(dut, True)  # 按键按下
    dut.Step(1)
    pulse = api_FSM_step_and_check_pulse(dut)
    # 重置后第一次按键应该产生脉冲
    assert pulse == True, "重置后按键应产生脉冲"


def test_api_FSM_set_key_state(dut):
    """测试设置按键状态API基础功能

    测试目标:
        验证api_FSM_set_key_state函数能正确设置按键输入状态

    测试流程:
        1. 调用api_FSM_set_key_state设置按键为按下状态
        2. 验证key_in信号是否正确设置
        3. 调用api_FSM_set_key_state设置按键为释放状态
        4. 验证key_in信号是否正确设置

    预期结果:
        - 按键按下时key_in.value应为0
        - 按键释放时key_in.value应为1
        - 无异常抛出
    """
    # 标记覆盖率
    dut.fc_cover["FG-API"].mark_function("FC-KEY", test_api_FSM_set_key_state, ["CK-KEYIFUNC"])
    dut.fc_cover["FG-KEY"].mark_function("FC-KEYDOWN", test_api_FSM_set_key_state, ["CK-KEYDOWNDETECT"])
    dut.fc_cover["FG-KEY"].mark_function("FC-KEYUP", test_api_FSM_set_key_state, ["CK-KEYUPDETECT"])
    
    # 测试设置按键为按下状态
    api_FSM_set_key_state(dut, True)
    assert dut.key_in.value == 0, "按键按下时key_in应为0"
    
    # 测试设置按键为释放状态
    api_FSM_set_key_state(dut, False)
    assert dut.key_in.value == 1, "按键释放时key_in应为1"
    
    # 手动采样以确保检查点被触发
    dut.fc_cover["FG-KEY"].sample()


def test_api_FSM_step_and_check_pulse(dut):
    """测试推进时钟周期并检查脉冲API基础功能

    测试目标:
        验证api_FSM_step_and_check_pulse函数能正确推进时钟周期并返回脉冲状态

    测试流程:
        1. 重置FSM到初始状态
        2. 设置按键为按下状态
        3. 调用api_FSM_step_and_check_pulse推进时钟周期
        4. 验证返回的脉冲状态是否正确
        5. 设置按键为释放状态
        6. 调用api_FSM_step_and_check_pulse推进时钟周期

    预期结果:
        - 函数应正确推进一个时钟周期
        - 返回的脉冲状态应与pulse_out信号一致
        - 无异常抛出
    """
    # 标记覆盖率
    dut.fc_cover["FG-API"].mark_function("FC-PULSE", test_api_FSM_step_and_check_pulse, ["CK-PULSEIFUNC"])
    dut.fc_cover["FG-STATE"].mark_function("FC-TRANS", test_api_FSM_step_and_check_pulse, ["CK-TRANSIDLEPRESSED", "CK-TRANSPRESSEDIDLE"])
    
    # 重置FSM
    api_FSM_reset(dut)
    
    # 设置按键为按下状态
    api_FSM_set_key_state(dut, True)
    
    # 推进时钟周期并检查脉冲
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 验证返回的脉冲状态与pulse_out信号一致
    assert pulse == bool(dut.pulse_out.value), "返回的脉冲状态应与pulse_out信号一致"
    
    # 设置按键为释放状态
    api_FSM_set_key_state(dut, False)
    
    # 推进时钟周期并检查脉冲
    pulse = api_FSM_step_and_check_pulse(dut)
    
    # 验证返回的脉冲状态与pulse_out信号一致
    assert pulse == bool(dut.pulse_out.value), "返回的脉冲状态应与pulse_out信号一致"
    
    # 手动采样以确保检查点被触发
    dut.fc_cover["FG-STATE"].sample()


def test_api_FSM_press_key_and_wait_pulse(dut):
    """测试按键按下并等待脉冲API基础功能

    测试目标:
        验证api_FSM_press_key_and_wait_pulse函数能正确模拟按键按下并检测脉冲输出

    测试流程:
        1. 重置FSM到初始状态
        2. 调用api_FSM_press_key_and_wait_pulse模拟按键按下
        3. 验证是否检测到脉冲输出

    预期结果:
        - 应能检测到脉冲输出
        - 无异常抛出
    """
    # 标记覆盖率
    dut.fc_cover["FG-PULSE"].mark_function("FC-PULSEGEN", test_api_FSM_press_key_and_wait_pulse, ["CK-PULSEGEN"])
    dut.fc_cover["FG-PULSE"].mark_function("FC-PULSELEN", test_api_FSM_press_key_and_wait_pulse, ["CK-PULSELEN"])
    dut.fc_cover["FG-API"].mark_function("FC-CLK", test_api_FSM_press_key_and_wait_pulse, ["CK-CLKFUNC"])
    dut.fc_cover["FG-API"].mark_function("FC-RST", test_api_FSM_press_key_and_wait_pulse, ["CK-RSTIFUNC"])
    
    # 重置FSM
    api_FSM_reset(dut)
    
    # 模拟按键按下并等待脉冲
    pulse_detected = api_FSM_press_key_and_wait_pulse(dut)
    
    # 验证是否检测到脉冲输出
    assert pulse_detected == True, "应检测到脉冲输出"
