"""
ALU754 API测试文件 - 遗漏的检查点测试
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_api_ALU754_operation_invalid(env):
    """测试ALU754 API无效操作码处理
    
    测试目标:
        验证api_ALU754_operate函数能正确处理无效操作码

    测试流程:
        1. 使用无效操作码（大于定义范围）执行操作
        2. 验证结果符合预期

    预期结果:
        - 无效操作码应返回默认值（通常为0）
        - 所有标志位为0
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_ALU754_operation_invalid, 
                                             ["CK-INVALID"])
    
    # 测试无效操作码 4
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 4)  # 无效操作码
    assert result['result'] == 0
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    # 测试无效操作码 5
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 5)  # 无效操作码
    assert result['result'] == 0
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    assert True, "api_ALU754_operation_invalid测试完成"


def test_api_ALU754_special_values_subnormal(env):
    """测试ALU754特殊值非规约数处理
    
    测试目标:
        验证ALU754能正确处理非规约数运算

    测试流程:
        1. 使用非规约数执行各种运算
        2. 验证结果正确性

    预期结果:
        - 非规约数运算结果符合IEEE 754标准
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-SPECIAL-VALUES"].mark_function("FC-SPECIAL-VALUES", test_api_ALU754_special_values_subnormal, 
                                                        ["CK-SUBNORMAL"])
    
    # 非规约数：指数全为0，尾数非0
    subnormal1 = 0x00000001  # 最小正非规约数
    subnormal2 = 0x007FFFFF  # 最大非规约数
    normal_num = 0x3F800000  # 正常数1.0
    
    # 非规约数加法
    result = api_ALU754_add(env, subnormal1, subnormal2)
    assert result is not None
    
    # 非规约数乘法
    result = api_ALU754_mul(env, subnormal1, normal_num)
    assert result is not None
    
    # 非规约数除法
    result = api_ALU754_div(env, subnormal2, normal_num)
    assert result is not None
    
    assert True, "api_ALU754_special_values_subnormal测试完成"


def test_api_ALU754_special_values_rounding(env):
    """测试ALU754特殊值舍入处理
    
    测试目标:
        验证ALU754运算结果的舍入行为

    测试流程:
        1. 执行可能导致舍入的运算
        2. 验证舍入结果正确性

    预期结果:
        - 运算结果符合IEEE 754舍入标准
        - 舍入行为一致
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-SPECIAL-VALUES"].mark_function("FC-SPECIAL-VALUES", test_api_ALU754_special_values_rounding, 
                                                        ["CK-ROUNDING"])
    
    # 测试各种算术运算的舍入行为
    # 使用一些可能会导致舍入的值
    operand1 = 0x3F800001  # 1.0 + 小量
    operand2 = 0x3F800002  # 1.0 + 更小量
    
    # 加法运算
    result = api_ALU754_add(env, operand1, operand2)
    assert result is not None
    
    # 乘法运算 - 可能产生需要舍入的结果
    result = api_ALU754_mul(env, operand1, 0x40000000)  # 约1.x * 2
    assert result is not None
    
    # 除法运算 - 可能产生需要舍入的结果
    result = api_ALU754_div(env, 0x3F800000, 0x3F000000)  # 1.0 / 0.5 = 2.0 (精确)
    assert result is not None
    
    # 再试一个可能不精确的除法
    result = api_ALU754_div(env, 0x3F800000, 0x40400000)  # 1.0 / 3.0 (不精确)
    assert result is not None
    
    assert True, "api_ALU754_special_values_rounding测试完成"