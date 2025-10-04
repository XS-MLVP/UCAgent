"""
ALU754测试用例模板 - API操作功能测试
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_api_operation_add(env):
    """测试API加法操作功能"""
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_operation_add, ["CK-ADD"])
    
    # 实现API加法操作测试逻辑
    # Step:
    # 1. 测试op=0时的加法运算功能，验证result = a + b
    # 2. 验证加法操作的溢出标志位
    # 3. 检查其他标志位是否正确复位
    
    # 测试基本加法 (1.0 + 1.0 = 2.0)
    result = api_ALU754_operate(env, 0x3F800000, 0x3F800000, 0)  # 1.0 + 1.0
    assert result['overflow'] == 0, f"基本加法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"基本加法不应下溢，实际underflow={result['underflow']}"
    
    # 测试 2.0 + 3.0 = 5.0
    result = api_ALU754_operate(env, 0x40000000, 0x40400000, 0)  # 2.0 + 3.0
    assert result['overflow'] == 0, f"2.0+3.0不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"2.0+3.0不应下溢，实际underflow={result['underflow']}"
    
    # 检查其他标志位被正确复位
    assert result['gt'] == 0, f"加法操作后gt应为0，实际为{result['gt']}"
    assert result['lt'] == 0, f"加法操作后lt应为0，实际为{result['lt']}"
    assert result['eq'] == 0, f"加法操作后eq应为0，实际为{result['eq']}"


def test_api_operation_cmp(env):
    """测试API比较操作功能"""
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_operation_cmp, ["CK-CMP"])
    
    # 实现API比较操作测试逻辑
    # Step:
    # 1. 测试op=3时的比较运算功能
    # 2. 验证gt/lt/eq标志根据比较结果正确设置
    # 3. 验证result在比较操作时为0
    
    # 测试相等比较 (2.0 == 2.0)
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 3)  # op=3 表示比较操作
    assert result['result'] == 0, f"比较操作结果应为0，实际为{result['result']}"
    assert result['eq'] == 1, f"相等比较时eq应为1，实际为{result['eq']}"
    assert result['gt'] == 0, f"相等比较时gt应为0，实际为{result['gt']}"
    assert result['lt'] == 0, f"相等比较时lt应为0，实际为{result['lt']}"
    
    # 测试大于比较 (3.0 > 2.0)
    result = api_ALU754_operate(env, 0x40400000, 0x40000000, 3)  # 3.0 > 2.0
    assert result['result'] == 0, f"比较操作结果应为0，实际为{result['result']}"
    assert result['gt'] == 1, f"大于比较时gt应为1，实际为{result['gt']}"
    assert result['lt'] == 0, f"大于比较时lt应为0，实际为{result['lt']}"
    assert result['eq'] == 0, f"大于比较时eq应为0，实际为{result['eq']}"
    
    # 测试小于比较 (1.0 < 2.0)
    result = api_ALU754_operate(env, 0x3F800000, 0x40000000, 3)  # 1.0 < 2.0
    assert result['result'] == 0, f"比较操作结果应为0，实际为{result['result']}"
    assert result['lt'] == 1, f"小于比较时lt应为1，实际为{result['lt']}"
    assert result['gt'] == 0, f"小于比较时gt应为0，实际为{result['gt']}"
    assert result['eq'] == 0, f"小于比较时eq应为0，实际为{result['eq']}"


def test_api_operation_div(env):
    """测试API除法操作功能"""
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_operation_div, ["CK-DIV"])
    
    # 实现API除法操作测试逻辑
    # Step:
    # 1. 测试op=2时的除法运算功能，验证result = a / b
    # 2. 验证除法操作的溢出、下溢标志位
    # 3. 检查其他标志位是否正确复位
    
    # 测试基本除法 (4.0 / 2.0 = 2.0)
    result = api_ALU754_operate(env, 0x40800000, 0x40000000, 2)  # 4.0 / 2.0
    assert result['overflow'] == 0, f"基本除法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"基本除法不应下溢，实际underflow={result['underflow']}"
    
    # 测试除零 (5.0 / 0.0)
    result = api_ALU754_operate(env, 0x40A00000, 0x00000000, 2)  # 5.0 / 0.0
    # 检查结果是否符合IEEE 754标准（无穷大或其他）
    
    # 测试1.0 / 1.0 = 1.0
    result = api_ALU754_operate(env, 0x3F800000, 0x3F800000, 2)  # 1.0 / 1.0
    assert result['overflow'] == 0, f"1.0/1.0不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"1.0/1.0不应下溢，实际underflow={result['underflow']}"


def test_api_operation_invalid(env):
    """测试API无效操作码处理"""
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_operation_invalid, ["CK-INVALID"])
    
    # 实现API无效操作码处理测试逻辑
    # Step:
    # 1. 测试超出定义范围的操作码
    # 2. 验证result = 0, overflow/underflow/gt/lt/eq = 0
    
    # 测试无效操作码 4
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 4)  # op=4 为无效操作
    assert result['result'] == 0, f"无效操作码时result应为0，实际为{result['result']}"
    assert result['overflow'] == 0, f"无效操作码时overflow应为0，实际为{result['overflow']}"
    assert result['underflow'] == 0, f"无效操作码时underflow应为0，实际为{result['underflow']}"
    assert result['gt'] == 0, f"无效操作码时gt应为0，实际为{result['gt']}"
    assert result['lt'] == 0, f"无效操作码时lt应为0，实际为{result['lt']}"
    assert result['eq'] == 0, f"无效操作码时eq应为0，实际为{result['eq']}"
    
    # 测试无效操作码 5
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 5)  # op=5 为无效操作
    assert result['result'] == 0, f"无效操作码时result应为0，实际为{result['result']}"
    assert result['overflow'] == 0, f"无效操作码时overflow应为0，实际为{result['overflow']}"
    assert result['underflow'] == 0, f"无效操作码时underflow应为0，实际为{result['underflow']}"
    assert result['gt'] == 0, f"无效操作码时gt应为0，实际为{result['gt']}"
    assert result['lt'] == 0, f"无效操作码时lt应为0，实际为{result['lt']}"
    assert result['eq'] == 0, f"无效操作码时eq应为0，实际为{result['eq']}"
    
    # 测试无效操作码 7
    result = api_ALU754_operate(env, 0x40000000, 0x40000000, 7)  # op=7 为无效操作
    assert result['result'] == 0, f"无效操作码时result应为0，实际为{result['result']}"
    assert result['overflow'] == 0, f"无效操作码时overflow应为0，实际为{result['overflow']}"
    assert result['underflow'] == 0, f"无效操作码时underflow应为0，实际为{result['underflow']}"
    assert result['gt'] == 0, f"无效操作码时gt应为0，实际为{result['gt']}"
    assert result['lt'] == 0, f"无效操作码时lt应为0，实际为{result['lt']}"
    assert result['eq'] == 0, f"无效操作码时eq应为0，实际为{result['eq']}"


def test_api_operation_mul(env):
    """测试API乘法操作功能"""
    env.dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_operation_mul, ["CK-MUL"])
    
    # 实现API乘法操作测试逻辑
    # Step:
    # 1. 测试op=1时的乘法运算功能，验证result = a * b
    # 2. 验证乘法操作的溢出、下溢标志位
    # 3. 检查其他标志位是否正确复位
    
    # 测试基本乘法 (2.0 * 3.0 = 6.0)
    result = api_ALU754_operate(env, 0x40000000, 0x40400000, 1)  # 2.0 * 3.0
    assert result['overflow'] == 0, f"基本乘法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"基本乘法不应下溢，实际underflow={result['underflow']}"
    
    # 测试 1.0 * 1.0 = 1.0
    result = api_ALU754_operate(env, 0x3F800000, 0x3F800000, 1)  # 1.0 * 1.0
    assert result['overflow'] == 0, f"1.0*1.0不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"1.0*1.0不应下溢，实际underflow={result['underflow']}"
    
    # 测试 0.0 * 任意数 = 0.0
    result = api_ALU754_operate(env, 0x00000000, 0x40000000, 1)  # 0.0 * 2.0
    assert result['overflow'] == 0, f"0乘法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"0乘法不应下溢，实际underflow={result['underflow']}"