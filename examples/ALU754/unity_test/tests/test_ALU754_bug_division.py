"""
ALU754除法溢出和下溢检测bug验证
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_division_overflow_detection_bug(env):
    """验证除法模块未能正确检测溢出的bug"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_division_overflow_detection_bug, ["CK-OVERFLOW"])
    
    # 尝试触发除法溢出 - 大数除以小正数应该触发溢出标志
    # 最大正数 (接近 3.4028235e+38) 除以一个很小的正数 (如2^-126)
    max_float = 0x7F7FFFFF  # 最大正规格化数
    tiny_positive = 0x00800000  # 最小正规格化数，值为2^-126
    
    result = api_ALU754_div(env, max_float, tiny_positive)
    
    # 理论上，一个非常大的数除以一个非常小的数应该导致溢出
    # 但ALU754除法模块可能没有正确实现溢出检测
    if result['overflow'] == 0:
        print(f"DETECTED BUG: Division overflow not detected - {hex(max_float)}/{hex(tiny_positive)} = {result}")
        # 这是ALU754除法模块的bug，应该失败以记录bug
        assert False, f"除法模块错误：大数除以小数({hex(max_float)}/{hex(tiny_positive)})应触发溢出但未触发。结果={result}"
    else:
        print(f"Division overflow correctly detected: {result}")
        assert True, "除法溢出检测正确"


def test_division_underflow_detection_bug(env):
    """验证除法模块未能正确检测下溢的bug"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_division_underflow_detection_bug, ["CK-UNDERFLOW"])
    
    # 尝试触发除法下溢 - 极小数除以极大的数应该触发下溢标志
    # 最小正规格化数除以最大正规格化数
    tiny_positive = 0x00800000  # 最小正规格化数
    max_float = 0x7F7FFFFF      # 最大正规格化数
    
    result = api_ALU754_div(env, tiny_positive, max_float)
    
    # 理论上，一个极小的数除以一个极大的数应该导致下溢
    # 但ALU754除法模块可能没有正确实现下溢检测
    if result['underflow'] == 0:
        print(f"DETECTED BUG: Division underflow not detected - {hex(tiny_positive)}/{hex(max_float)} = {result}")
        # 这是ALU754除法模块的bug，应该失败以记录bug
        assert False, f"除法模块错误：小数除以大数({hex(tiny_positive)}/{hex(max_float)})应触发下溢但未触发。结果={result}"
    else:
        print(f"Division underflow correctly detected: {result}")
        assert True, "除法下溢检测正确"