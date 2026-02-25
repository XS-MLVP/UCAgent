from Adder_api import *
import pytest


def test_api_Adder_add_basic(env):
    """测试加法器API基础功能

    测试目标:
        验证api_Adder_add函数能正确执行基本加法运算

    测试流程:
        1. 使用典型正数进行加法运算
        2. 验证结果正确性
        3. 检查进位输出

    预期结果:
        - 计算结果正确
        - 进位标志符合预期
        - 无异常抛出
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_Adder_add_basic, ["CK-ADD"])
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_Adder_add_basic, ["CK-BASIC", "CK-OVERFLOW"])
    env.dut.fc_cover["FG-BIT-WIDTH"].mark_function("FC-SUM-WIDTH", test_api_Adder_add_basic, ["CK-SUM-WIDTH"])

    # 测试典型情况
    result, carry = api_Adder_add(env, 100, 200)
    assert result == 300, f"预期结果300，实际{result}"
    assert carry == 0, f"预期进位0，实际{carry}"

    # 测试带进位情况
    result, carry = api_Adder_add(env, 0xFFFFFFFFFFFFFFFF, 1)
    # 由于sum只有63位，0xFFFFFFFFFFFFFFFF + 1 = 0x10000000000000000，sum应为0，cout应为1
    assert result == 0, f"溢出时预期结果0，实际{result}"
    assert carry == 1, f"溢出时预期进位1，实际{carry}"


def test_api_Adder_add_with_carry_in(env):
    """测试加法器API带进位输入功能

    测试目标:
        验证api_Adder_add函数能正确处理进位输入

    测试流程:
        1. 使用进位输入进行加法运算
        2. 验证结果正确性

    预期结果:
        - 计算结果正确
        - 进位标志符合预期
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_Adder_add_with_carry_in, ["CK-CARRY-IN"])

    # 测试带进位输入的情况
    result, carry = api_Adder_add(env, 100, 200, 1)  # 100 + 200 + 1 = 301
    assert result == 301, f"预期结果301，实际{result}"
    assert carry == 0, f"预期进位0，实际{carry}"


def test_api_Adder_add_zero_values(env):
    """测试加法器API零值处理

    测试目标:
        验证api_Adder_add函数能正确处理零值输入

    测试流程:
        1. 使用零值进行加法运算
        2. 验证结果正确性

    预期结果:
        - 计算结果为0
        - 进位标志为0
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_Adder_add_zero_values, ["CK-ZERO"])

    # 测试零值情况
    result, carry = api_Adder_add(env, 0, 0, 0)
    assert result == 0, f"预期结果0，实际{result}"
    assert carry == 0, f"预期进位0，实际{carry}"


def test_api_Adder_add_overflow(env):
    """测试加法器API溢出处理

    测试目标:
        验证api_Adder_add函数能正确处理溢出情况

    测试流程:
        1. 使用可能产生溢出的数值进行加法运算
        2. 验证进位输出正确性

    预期结果:
        - 进位标志正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_Adder_add_overflow, ["CK-OVERFLOW"])

    # 测试溢出情况：最大值相加
    max_val = 0xFFFFFFFFFFFFFFFF
    result, carry = api_Adder_add(env, max_val, max_val)
    # max_val + max_val = 0x1FFFFFFFFFFFFFFFE，会溢出，cout应为1
    assert carry == 1, "最大值相加应产生进位"


def test_api_Adder_add_boundary(env):
    """测试加法器API边界条件

    测试目标:
        验证api_Adder_add函数在边界条件下的正确性

    测试流程:
        1. 使用边界值进行加法运算
        2. 验证结果正确性

    预期结果:
        - 计算结果正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_Adder_add_boundary, ["CK-BOUNDARY"])
    env.dut.fc_cover["FG-BIT-WIDTH"].mark_function("FC-SUM-WIDTH", test_api_Adder_add_boundary, ["CK-SUM-VALUE"])

    # 测试边界条件：最大值和0相加
    max_val = 0xFFFFFFFFFFFFFFFF
    result, carry = api_Adder_add(env, max_val, 0)
    # max_val + 0 = max_val，但由于sum只有63位，实际结果会截断
    # max_val = 0xFFFFFFFFFFFFFFFF = 2^64 - 1
    # 截断后应该是 2^63 - 1 = 0x7FFFFFFFFFFFFFFF
    assert result == 0x7FFFFFFFFFFFFFFF, f"最大值与0相加结果错误，预期0x7FFFFFFFFFFFFFFF，实际{result}"


def test_api_Adder_add_sum_width(env):
    """测试加法器API输出位宽

    测试目标:
        验证api_Adder_add函数的输出sum只有63位

    测试流程:
        1. 执行加法运算
        2. 验证sum值在63位范围内

    预期结果:
        - sum值小于2^63
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-BIT-WIDTH"].mark_function("FC-SUM-WIDTH", test_api_Adder_add_sum_width, ["CK-SUM-WIDTH"])

    # 测试输出位宽
    result, carry = api_Adder_add(env, 100, 200)
    assert result < (1 << 63), f"sum值超出63位范围，实际{result}"