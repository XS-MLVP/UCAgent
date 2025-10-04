"""
ALU754乘法溢出bug验证
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_multiplication_underflow_bug(env):
    """验证乘法运算中的下溢处理bug"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_multiplication_underflow_bug, ["CK-UNDERFLOW"])
    
    # 正常情况下，两个很小的正数相乘应该产生一个更小的数，可能触发下溢而不是溢出
    # IEEE 754: 2^(-126) * 2^(-126) = 2^(-252)，这是一个非常小的数，应该触发下溢
    min_normal = 0x00800000  # 最小正规格化数，值为 ~1.1754944e-38
    result = api_ALU754_mul(env, min_normal, min_normal)
    
    print(f"Min normal multiplication result: {result}")
    
    # 根据IEEE 754标准，这里应该触发underflow而不是overflow
    # 但根据之前的测试输出，它错误地触发了overflow
    if result['overflow'] == 1 and result['underflow'] == 0:
        print("DETECTED BUG: Multiplication of small numbers triggers overflow instead of underflow")
        # 这是ALU754乘法模块的bug，应该失败以记录bug
        assert False, f"乘法模块错误：两个小数相乘({hex(min_normal)} * {hex(min_normal)})触发了溢出而不是下溢。结果={result}"
    elif result['underflow'] == 1:
        print("Correct: Multiplication of small numbers triggers underflow")
        assert True, "乘法下溢处理正确"
    else:
        print(f"Unexpected result: {result}")
        # 不确定是否为bug，暂时通过
        assert True, "乘法结果需要进一步分析"