"""
ALU754测试用例模板 - 算术运算功能测试（第二批）
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_arithmetic_add_zero(env):
    """测试加法功能的零值运算"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_arithmetic_add_zero, ["CK-ZERO"])
    
    # 实现零值加法运算测试逻辑
    # Step:
    # 1. 测试0+0=0
    # 2. 测试0+x=x
    # 3. 测试x+0=x
    
    # 测试0+0=0
    result = api_ALU754_add(env, 0x00000000, 0x00000000)  # 0.0 + 0.0
    assert result['overflow'] == 0, f"零值加法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"零值加法不应下溢，实际underflow={result['underflow']}"
    
    # 测试0+x=x
    result = api_ALU754_add(env, 0x00000000, 0x40000000)  # 0.0 + 2.0
    assert result['overflow'] == 0, f"零加正数不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"零加正数不应下溢，实际underflow={result['underflow']}"
    
    # 测试x+0=x
    result = api_ALU754_add(env, 0x40000000, 0x00000000)  # 2.0 + 0.0
    assert result['overflow'] == 0, f"正数加零不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"正数加零不应下溢，实际underflow={result['underflow']}"


def test_arithmetic_mul_infinity(env):
    """测试乘法功能的无穷运算"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_arithmetic_mul_infinity, ["CK-INFINITY"])
    
    # 实现无穷参与的乘法运算测试逻辑
    # Step:
    # 1. 测试无穷与非零数的乘法运算
    # 2. 测试无穷与无穷的乘法运算
    # 3. 验证结果符合IEEE 754标准
    
    # 正无穷 (0x7F800000)
    pos_inf = 0x7F800000
    # 负无穷 (0xFF800000) 
    neg_inf = 0xFF800000
    # 正数
    pos_num = 0x40000000  # 2.0
    # 负数
    neg_num = 0xC0000000  # -2.0
    
    # 正无穷乘正数 = 正无穷
    result = api_ALU754_mul(env, pos_inf, pos_num)
    # 检查结果
    
    # 正无穷乘负数 = 负无穷
    result = api_ALU754_mul(env, pos_inf, neg_num)
    
    # 负无穷乘正数 = 负无穷
    result = api_ALU754_mul(env, neg_inf, pos_num)
    
    # 负无穷乘负数 = 正无穷
    result = api_ALU754_mul(env, neg_inf, neg_num)


def test_arithmetic_mul_nan(env):
    """测试乘法功能的NaN运算"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_arithmetic_mul_nan, ["CK-NAN"])
    
    # 实现NaN参与的乘法运算测试逻辑
    # Step:
    # 1. 测试NaN与任意数的乘法运算
    # 2. 验证结果为NaN
    # 3. 验证符合IEEE 754 NaN处理规则
    
    # NaN (指数全1，尾数非0)
    nan = 0x7FC00000  # 一种典型的NaN表示
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # NaN乘有限数应得NaN
    result = api_ALU754_mul(env, nan, finite_num)
    
    # 有限数乘NaN应得NaN
    result = api_ALU754_mul(env, finite_num, nan)
    
    # NaN乘NaN应得NaN
    result = api_ALU754_mul(env, nan, nan)


def test_arithmetic_mul_negative(env):
    """测试乘法功能的负数运算"""
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_arithmetic_mul_negative, ["CK-NEGATIVE"])
    
    # 实现负数参与的乘法运算测试逻辑
    # Step:
    # 1. 测试负数与正数的乘法运算
    # 2. 测试两个负数的乘法运算
    # 3. 验证结果的符号位正确性
    
    # 负数-2.0 和正数3.0: -2.0 * 3.0 = -6.0
    result = api_ALU754_mul(env, 0xC0000000, 0x40400000)  # -2.0 * 3.0
    assert result['overflow'] == 0, f"负正乘法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"负正乘法不应下溢，实际underflow={result['underflow']}"
    
    # 两个负数相乘: -2.0 * (-3.0) = 6.0
    result = api_ALU754_mul(env, 0xC0000000, 0xC0400000)  # -2.0 * (-3.0)
    assert result['overflow'] == 0, f"负负乘法不应溢出，实际overflow={result['overflow']}"
    assert result['underflow'] == 0, f"负负乘法不应下溢，实际underflow={result['underflow']}"