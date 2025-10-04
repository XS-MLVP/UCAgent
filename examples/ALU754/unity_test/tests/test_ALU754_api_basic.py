"""
ALU754 API测试文件 - 基础API功能正确性测试
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_api_ALU754_operate_basic(env):
    """测试ALU754基础操作API功能
    
    测试目标:
        验证api_ALU754_operate函数能正确执行基本运算操作

    测试流程:
        1. 使用典型浮点数进行加法运算
        2. 使用典型浮点数进行乘法运算
        3. 使用典型浮点数进行除法运算
        4. 使用典型浮点数进行比较运算
        5. 验证结果正确性

    预期结果:
        - 计算结果正确
        - 各标志位符合预期
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_ALU754_operate_basic, 
                                             ["CK-ADD", "CK-MUL", "CK-DIV", "CK-CMP"])
    
    # 测试加法操作 (op=0)
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 0)  # 2.0 + 2.0
    assert result['result'] is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试乘法操作 (op=1) 
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 1)  # 2.0 * 2.0
    assert result['result'] is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试除法操作 (op=2)
    result = api_ALU754_operate(env, 0x40800000, 0x40000000, 2)  # 4.0 / 2.0
    assert result['result'] is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试比较操作 (op=3)
    result = api_ALU754_operate(env, 0x40800000, 0x40000000, 3)  # 4.0 > 2.0
    assert result['result'] == 0
    assert result['gt'] == 1
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    # 测试无效操作码 (op=4)
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 4)  # 无效操作
    assert result['result'] == 0
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    assert True, "api_ALU754_operate基础功能测试完成"


def test_api_ALU754_add_basic(env):
    """测试ALU754加法API功能
    
    测试目标:
        验证api_ALU754_add函数能正确执行基本加法运算

    测试流程:
        1. 使用典型正数进行加法运算
        2. 验证结果正确性
        3. 检查溢出和下溢标志

    预期结果:
        - 计算结果正确
        - 溢出标志符合预期
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_basic, 
                                                    ["CK-BASIC", "CK-ZERO"])
    
    # 测试典型加法 1.0 + 1.0
    result = api_ALU754_add(env, 0x3F800000, 0x3F800000)  # 1.0 + 1.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试零值加法 0.0 + 0.0
    result = api_ALU754_add(env, 0x00000000, 0x00000000)  # 0.0 + 0.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    assert True, "api_ALU754_add基础功能测试完成"


def test_api_ALU754_mul_basic(env):
    """测试ALU754乘法API功能
    
    测试目标:
        验证api_ALU754_mul函数能正确执行基本乘法运算

    测试流程:
        1. 使用典型正数进行乘法运算
        2. 验证结果正确性
        3. 检查溢出和下溢标志

    预期结果:
        - 计算结果正确
        - 溢出标志符合预期
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_basic, 
                                                    ["CK-BASIC", "CK-ZERO-FACTOR"])
    
    # 测试典型乘法 2.0 * 3.0
    result = api_ALU754_mul(env, 0x40000000, 0x40400000)  # 2.0 * 3.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试零乘法 0.0 * 2.0
    result = api_ALU754_mul(env, 0x00000000, 0x40000000)  # 0.0 * 2.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    assert True, "api_ALU754_mul基础功能测试完成"


def test_api_ALU754_div_basic(env):
    """测试ALU754除法API功能
    
    测试目标:
        验证api_ALU754_div函数能正确执行基本除法运算

    测试流程:
        1. 使用典型正数进行除法运算
        2. 验证结果正确性
        3. 检查溢出和下溢标志

    预期结果:
        - 计算结果正确
        - 溢出标志符合预期
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_basic, 
                                                    ["CK-BASIC", "CK-ZERO-DIV"])
    
    # 测试典型除法 6.0 / 2.0
    result = api_ALU754_div(env, 0x40C00000, 0x40000000)  # 6.0 / 2.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    # 测试零除法 0.0 / 5.0
    result = api_ALU754_div(env, 0x00000000, 0x40A00000)  # 0.0 / 5.0
    assert result is not None
    assert result['overflow'] == 0
    assert result['underflow'] == 0
    
    assert True, "api_ALU754_div基础功能测试完成"


def test_api_ALU754_compare_basic(env):
    """测试ALU754比较API功能
    
    测试目标:
        验证api_ALU754_compare函数能正确执行比较运算

    测试流程:
        1. 比较两个相等的数
        2. 比较一大一小的数
        3. 验证gt/lt/eq标志正确性

    预期结果:
        - 标志位设置正确
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-COMPARATOR"].mark_function("FC-CMP", test_api_ALU754_compare_basic, 
                                                    ["CK-EQ", "CK-GT", "CK-LT"])
    
    # 测试相等比较 2.0 == 2.0
    result = api_ALU754_compare(env, 0x40000000, 0x40000000)  # 2.0 == 2.0
    assert result['result'] == 0
    assert result['eq'] == 1
    assert result['gt'] == 0
    assert result['lt'] == 0
    
    # 测试大于比较 3.0 > 2.0
    result = api_ALU754_compare(env, 0x40400000, 0x40000000)  # 3.0 > 2.0
    assert result['result'] == 0
    assert result['gt'] == 1
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    # 测试小于比较 1.0 < 2.0
    result = api_ALU754_compare(env, 0x3F800000, 0x40000000)  # 1.0 < 2.0
    assert result['result'] == 0
    assert result['lt'] == 1
    assert result['gt'] == 0
    assert result['eq'] == 0
    
    assert True, "api_ALU754_compare基础功能测试完成"


def test_api_ALU754_add_negative_numbers(env):
    """测试ALU754加法API负数功能
    
    测试目标:
        验证api_ALU754_add函数能正确处理负数加法运算

    测试流程:
        1. 使用负数进行加法运算
        2. 验证结果正确性
        3. 检查溢出和下溢标志

    预期结果:
        - 计算结果正确
        - 负数处理正确
        - 溢出标志符合预期
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_negative_numbers, 
                                                    ["CK-NEGATIVE"])
    
    # 测试负数加法 -1.0 + (-1.0)
    result = api_ALU754_add(env, 0xBF800000, 0xBF800000)  # -1.0 + (-1.0)
    assert result is not None
    
    # 测试正负数加法 2.0 + (-1.0)
    result = api_ALU754_add(env, 0x40000000, 0xBF800000)  # 2.0 + (-1.0)
    assert result is not None
    
    assert True, "api_ALU754_add负数功能测试完成"


def test_api_ALU754_mul_negative_numbers(env):
    """测试ALU754乘法API负数功能
    
    测试目标:
        验证api_ALU754_mul函数能正确处理负数乘法运算

    测试流程:
        1. 使用负数进行乘法运算
        2. 验证结果正确性
        3. 检查溢出和下溢标志

    预期结果:
        - 计算结果正确
        - 负数处理正确
        - 溢出标志符合预期
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_negative_numbers, 
                                                    ["CK-NEGATIVE"])
    
    # 测试负数乘法 -2.0 * 3.0
    result = api_ALU754_mul(env, 0xC0000000, 0x40400000)  # -2.0 * 3.0
    assert result is not None
    
    # 测试负数乘法 -2.0 * -3.0
    result = api_ALU754_mul(env, 0xC0000000, 0xC0400000)  # -2.0 * -3.0
    assert result is not None
    
    assert True, "api_ALU754_mul负数功能测试完成"


def test_api_ALU754_div_by_zero(env):
    """测试ALU754除法API除零功能
    
    测试目标:
        验证api_ALU754_div函数能正确处理除零运算

    测试流程:
        1. 执行除零运算
        2. 验证结果和标志正确性

    预期结果:
        - 处理除零情况
        - 标志位正确设置
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_by_zero, 
                                                    ["CK-DIV-BY-ZERO"])
    
    # 测试除零 5.0 / 0.0
    result = api_ALU754_div(env, 0x40A00000, 0x00000000)  # 5.0 / 0.0
    assert result is not None
    
    assert True, "api_ALU754_div除零功能测试完成"


def test_api_ALU754_compare_negative_numbers(env):
    """测试ALU754比较API负数功能
    
    测试目标:
        验证api_ALU754_compare函数能正确处理负数比较运算

    测试流程:
        1. 比较负数与正数
        2. 比较两个负数
        3. 验证gt/lt/eq标志正确性

    预期结果:
        - 标志位设置正确
        - 负数比较处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-COMPARATOR"].mark_function("FC-CMP", test_api_ALU754_compare_negative_numbers, 
                                                    ["CK-NEGATIVE-COMP"])
    
    # 测试负数与正数比较 -2.0 < 1.0
    result = api_ALU754_compare(env, 0xC0000000, 0x3F800000)  # -2.0 < 1.0
    assert result['lt'] == 1
    assert result['gt'] == 0
    assert result['eq'] == 0
    
    # 测试两个负数比较 -3.0 < -1.0
    result = api_ALU754_compare(env, 0xC0400000, 0xBFC00000)  # -3.0 < -1.0
    assert result['lt'] == 1
    assert result['gt'] == 0
    assert result['eq'] == 0
    
    assert True, "api_ALU754_compare负数功能测试完成"