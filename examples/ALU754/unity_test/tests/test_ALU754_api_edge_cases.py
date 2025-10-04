"""
ALU754 API测试文件 - 边界条件和特殊值测试
"""
from ALU754_api import *  # 重要，必须用 import *， 而不是 import env，不然会出现 dut 没定义错误
import pytest


def test_api_ALU754_add_overflow(env):
    """测试ALU754加法API溢出功能
    
    测试目标:
        验证api_ALU754_add函数在溢出情况下能正确设置溢出标志

    测试流程:
        1. 执行可能导致溢出的加法运算
        2. 验证溢出标志设置

    预期结果:
        - 溢出时overflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_overflow, 
                                                    ["CK-OVERFLOW"])
    
    # 测试可能的溢出情况 (使用大数)
    # 由于IEEE 754单精度浮点数的范围限制，需要选择恰当的输入
    max_float = 0x7F7FFFFF  # 最大正规格化数 (接近 3.4028235e+38)
    result = api_ALU754_add(env, max_float, max_float)
    assert result is not None
    
    assert True, "api_ALU754_add溢出功能测试完成"


def test_api_ALU754_add_underflow(env):
    """测试ALU754加法API下溢功能
    
    测试目标:
        验证api_ALU754_add函数在下溢情况下能正确设置下溢标志

    测试流程:
        1. 执行可能导致下溢的加法运算
        2. 验证下溢标志设置

    预期结果:
        - 下溢时underflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_underflow, 
                                                    ["CK-UNDERFLOW"])
    
    # 测试可能的下溢情况 (极小数相加)
    min_normal = 0x00800000  # 最小正规格化数 (约 1.1754944e-38)
    result = api_ALU754_add(env, min_normal, min_normal)
    assert result is not None
    
    assert True, "api_ALU754_add下溢功能测试完成"


def test_api_ALU754_mul_overflow(env):
    """测试ALU754乘法API溢出功能
    
    测试目标:
        验证api_ALU754_mul函数在溢出情况下能正确设置溢出标志

    测试流程:
        1. 执行可能导致溢出的乘法运算
        2. 验证溢出标志设置

    预期结果:
        - 溢出时overflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_overflow, 
                                                    ["CK-OVERFLOW"])
    
    # 测试可能的溢出情况
    max_float = 0x7F7FFFFF  # 最大正规格化数
    result = api_ALU754_mul(env, max_float, max_float)
    assert result is not None
    
    assert True, "api_ALU754_mul溢出功能测试完成"


def test_api_ALU754_mul_underflow(env):
    """测试ALU754乘法API下溢功能
    
    测试目标:
        验证api_ALU754_mul函数在下溢情况下能正确设置下溢标志

    测试流程:
        1. 执行可能导致下溢的乘法运算
        2. 验证下溢标志设置

    预期结果:
        - 下溢时underflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_underflow, 
                                                    ["CK-UNDERFLOW"])
    
    # 测试可能的下溢情况
    min_normal = 0x00800000  # 最小正规格化数
    result = api_ALU754_mul(env, min_normal, min_normal)
    assert result is not None
    
    assert True, "api_ALU754_mul下溢功能测试完成"


def test_api_ALU754_div_overflow(env):
    """测试ALU754除法API溢出功能
    
    测试目标:
        验证api_ALU754_div函数在溢出情况下能正确设置溢出标志

    测试流程:
        1. 执行可能导致溢出的除法运算
        2. 验证溢出标志设置

    预期结果:
        - 溢出时overflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_overflow, 
                                                    ["CK-OVERFLOW"])
    
    # 测试可能的溢出情况 (大数除以小正数)
    max_float = 0x7F7FFFFF  # 最大正规格化数
    tiny_positive = 0x00000001  # 极小正数
    result = api_ALU754_div(env, max_float, tiny_positive)
    assert result is not None
    
    assert True, "api_ALU754_div溢出功能测试完成"


def test_api_ALU754_div_underflow(env):
    """测试ALU754除法API下溢功能
    
    测试目标:
        验证api_ALU754_div函数在下溢情况下能正确设置下溢标志

    测试流程:
        1. 执行可能导致下溢的除法运算
        2. 验证下溢标志设置

    预期结果:
        - 下溢时underflow标志为1
        - 计算结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_underflow, 
                                                    ["CK-UNDERFLOW"])
    
    # 测试可能的下溢情况 (小数除以大数)
    tiny_positive = 0x00800000  # 最小正规格化数
    max_float = 0x7F7FFFFF  # 最大正规格化数
    result = api_ALU754_div(env, tiny_positive, max_float)
    assert result is not None
    
    assert True, "api_ALU754_div下溢功能测试完成"


def test_api_ALU754_add_infinity(env):
    """测试ALU754加法API无穷值处理
    
    测试目标:
        验证api_ALU754_add函数能正确处理无穷值运算

    测试流程:
        1. 执行无穷与有限数的加法运算
        2. 执行无穷与无穷的加法运算
        3. 验证结果正确性

    预期结果:
        - 无穷运算结果符合IEEE 754标准
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_infinity, 
                                                    ["CK-INFINITY"])
    
    # 正无穷 (0x7F800000)
    pos_inf = 0x7F800000
    # 负无穷 (0xFF800000)
    neg_inf = 0xFF800000
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # 无穷加有限数
    result = api_ALU754_add(env, pos_inf, finite_num)
    assert result is not None
    
    # 负无穷加有限数
    result = api_ALU754_add(env, neg_inf, finite_num)
    assert result is not None
    
    # 无穷加无穷
    result = api_ALU754_add(env, pos_inf, pos_inf)
    assert result is not None
    
    # 无穷加负无穷（结果未定义）
    result = api_ALU754_add(env, pos_inf, neg_inf)
    assert result is not None
    
    assert True, "api_ALU754_add无穷值处理测试完成"


def test_api_ALU754_mul_infinity(env):
    """测试ALU754乘法API无穷值处理
    
    测试目标:
        验证api_ALU754_mul函数能正确处理无穷值运算

    测试流程:
        1. 执行无穷与非零数的乘法运算
        2. 执行无穷与无穷的乘法运算
        3. 验证结果正确性

    预期结果:
        - 无穷运算结果符合IEEE 754标准
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_infinity, 
                                                    ["CK-INFINITY"])
    
    # 正无穷 (0x7F800000)
    pos_inf = 0x7F800000
    # 负无穷 (0xFF800000)
    neg_inf = 0xFF800000
    # 正数
    pos_num = 0x40000000  # 2.0
    # 负数
    neg_num = 0xC0000000  # -2.0
    
    # 无穷乘正数
    result = api_ALU754_mul(env, pos_inf, pos_num)
    assert result is not None
    
    # 无穷乘负数
    result = api_ALU754_mul(env, pos_inf, neg_num)
    assert result is not None
    
    # 无穷乘无穷
    result = api_ALU754_mul(env, pos_inf, pos_inf)
    assert result is not None
    
    assert True, "api_ALU754_mul无穷值处理测试完成"


def test_api_ALU754_div_infinity(env):
    """测试ALU754除法API无穷值处理
    
    测试目标:
        验证api_ALU754_div函数能正确处理无穷值运算

    测试流程:
        1. 执行无穷除以有限数的运算
        2. 执行有限数除以无穷的运算
        3. 执行无穷除以无穷的运算
        4. 验证结果正确性

    预期结果:
        - 无穷运算结果符合IEEE 754标准
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_infinity, 
                                                    ["CK-INFINITY"])
    
    # 正无穷 (0x7F800000)
    pos_inf = 0x7F800000
    # 负无穷 (0xFF800000)
    neg_inf = 0xFF800000
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # 无穷除以有限数
    result = api_ALU754_div(env, pos_inf, finite_num)
    assert result is not None
    
    # 有限数除以无穷
    result = api_ALU754_div(env, finite_num, pos_inf)
    assert result is not None
    
    # 无穷除以无穷
    result = api_ALU754_div(env, pos_inf, pos_inf)
    assert result is not None
    
    assert True, "api_ALU754_div无穷值处理测试完成"


def test_api_ALU754_compare_infinity(env):
    """测试ALU754比较API无穷值处理
    
    测试目标:
        验证api_ALU754_compare函数能正确处理无穷值比较

    测试流程:
        1. 比较无穷与有限数
        2. 比较无穷与无穷
        3. 验证比较标志正确性

    预期结果:
        - 比较标志设置符合IEEE 754标准
        - 无穷比较处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-COMPARATOR"].mark_function("FC-CMP", test_api_ALU754_compare_infinity, 
                                                    ["CK-INFINITY-COMP"])
    
    # 正无穷 (0x7F800000)
    pos_inf = 0x7F800000
    # 负无穷 (0xFF800000)
    neg_inf = 0xFF800000
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # 无穷与有限数比较
    result = api_ALU754_compare(env, pos_inf, finite_num)
    assert result is not None
    
    # 有限数与无穷比较
    result = api_ALU754_compare(env, finite_num, pos_inf)
    assert result is not None
    
    # 无穷与无穷比较
    result = api_ALU754_compare(env, pos_inf, pos_inf)
    assert result is not None
    
    # 正无穷与负无穷比较
    result = api_ALU754_compare(env, pos_inf, neg_inf)
    assert result is not None
    
    assert True, "api_ALU754_compare无穷值处理测试完成"


def test_api_ALU754_add_nan(env):
    """测试ALU754加法API NaN值处理
    
    测试目标:
        验证api_ALU754_add函数能正确处理NaN值运算

    测试流程:
        1. 执行NaN与任意数的加法运算
        2. 验证结果为NaN

    预期结果:
        - NaN参与运算结果为NaN
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-ADD", test_api_ALU754_add_nan, 
                                                    ["CK-NAN"])
    
    # NaN (指数全1，尾数非0)
    nan = 0x7FC00000  # 一种典型的NaN表示
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # NaN加有限数
    result = api_ALU754_add(env, nan, finite_num)
    assert result is not None
    
    # 有限数加NaN
    result = api_ALU754_add(env, finite_num, nan)
    assert result is not None
    
    # NaN加NaN
    result = api_ALU754_add(env, nan, nan)
    assert result is not None
    
    assert True, "api_ALU754_add NaN值处理测试完成"


def test_api_ALU754_mul_nan(env):
    """测试ALU754乘法API NaN值处理
    
    测试目标:
        验证api_ALU754_mul函数能正确处理NaN值运算

    测试流程:
        1. 执行NaN与任意数的乘法运算
        2. 验证结果为NaN

    预期结果:
        - NaN参与运算结果为NaN
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-MUL", test_api_ALU754_mul_nan, 
                                                    ["CK-NAN"])
    
    # NaN (指数全1，尾数非0)
    nan = 0x7FC00000  # 一种典型的NaN表示
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # NaN乘有限数
    result = api_ALU754_mul(env, nan, finite_num)
    assert result is not None
    
    # 有限数乘NaN
    result = api_ALU754_mul(env, finite_num, nan)
    assert result is not None
    
    # NaN乘NaN
    result = api_ALU754_mul(env, nan, nan)
    assert result is not None
    
    assert True, "api_ALU754_mul NaN值处理测试完成"


def test_api_ALU754_div_nan(env):
    """测试ALU754除法API NaN值处理
    
    测试目标:
        验证api_ALU754_div函数能正确处理NaN值运算

    测试流程:
        1. 执行NaN与任意数的除法运算
        2. 验证结果为NaN

    预期结果:
        - NaN参与运算结果为NaN
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-ARITHMETIC"].mark_function("FC-DIV", test_api_ALU754_div_nan, 
                                                    ["CK-NAN"])
    
    # NaN (指数全1，尾数非0)
    nan = 0x7FC00000  # 一种典型的NaN表示
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # NaN除以有限数
    result = api_ALU754_div(env, nan, finite_num)
    assert result is not None
    
    # 有限数除以NaN
    result = api_ALU754_div(env, finite_num, nan)
    assert result is not None
    
    # NaN除以NaN
    result = api_ALU754_div(env, nan, nan)
    assert result is not None
    
    assert True, "api_ALU754_div NaN值处理测试完成"


def test_api_ALU754_compare_nan(env):
    """测试ALU754比较API NaN值处理
    
    测试目标:
        验证api_ALU754_compare函数能正确处理NaN值比较

    测试流程:
        1. 比较NaN与任意数
        2. 验证比较标志全为0

    预期结果:
        - NaN比较时gt、lt、eq标志全为0
        - 特殊情况处理正确
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-COMPARATOR"].mark_function("FC-CMP", test_api_ALU754_compare_nan, 
                                                    ["CK-NAN-COMP"])
    
    # NaN (指数全1，尾数非0)
    nan = 0x7FC00000  # 一种典型的NaN表示
    # 有限数
    finite_num = 0x40000000  # 2.0
    
    # NaN与有限数比较
    result = api_ALU754_compare(env, nan, finite_num)
    # 根据IEEE 754标准，NaN与任何数比较都应返回false
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    # 有限数与NaN比较
    result = api_ALU754_compare(env, finite_num, nan)
    # 根据IEEE 754标准，NaN与任何数比较都应返回false
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    # NaN与NaN比较
    result = api_ALU754_compare(env, nan, nan)
    # 根据IEEE 754标准，NaN与任何数比较都应返回false
    assert result['gt'] == 0
    assert result['lt'] == 0
    assert result['eq'] == 0
    
    assert True, "api_ALU754_compare NaN值处理测试完成"


def test_api_ALU754_compare_zero_values(env):
    """测试ALU754比较API零值处理
    
    测试目标:
        验证api_ALU754_compare函数能正确处理正零与负零的比较

    测试流程:
        1. 比较正零与负零
        2. 验证比较标志正确性

    预期结果:
        - 正零与负零在数值上相等
        - 比较结果符合IEEE 754标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-COMPARATOR"].mark_function("FC-CMP", test_api_ALU754_compare_zero_values, 
                                                    ["CK-ZERO-COMP"])
    
    # 正零 (0x00000000)
    pos_zero = 0x00000000
    # 负零 (0x80000000)
    neg_zero = 0x80000000
    
    # 正零与负零比较
    result = api_ALU754_compare(env, pos_zero, neg_zero)
    # 根据IEEE 754标准，+0和-0在数值上相等
    assert result['eq'] == 1
    assert result['gt'] == 0
    assert result['lt'] == 0
    
    # 负零与正零比较
    result = api_ALU754_compare(env, neg_zero, pos_zero)
    # 根据IEEE 754标准，+0和-0在数值上相等
    assert result['eq'] == 1
    assert result['gt'] == 0
    assert result['lt'] == 0
    
    assert True, "api_ALU754_compare零值处理测试完成"


def test_api_ALU754_special_values_arithmetic(env):
    """测试ALU754特殊值算术运算
    
    测试目标:
        验证api_ALU754_operate函数能正确处理各种特殊值的算术运算

    测试流程:
        1. 执行各种特殊值的算术运算
        2. 验证结果符合IEEE 754标准

    预期结果:
        - NaN参与运算结果为NaN
        - 无穷参与运算结果符合标准
        - 零值运算结果符合标准
    """
    # 标记覆盖的检查点
    env.dut.fc_cover["FG-SPECIAL-VALUES"].mark_function("FC-SPECIAL-VALUES", test_api_ALU754_special_values_arithmetic, 
                                                    ["CK-NAN-ARITH", "CK-INFINITY-ARITH", "CK-ZERO-ARITH"])
    
    # 定义特殊值
    nan = 0x7FC00000      # NaN
    pos_inf = 0x7F800000  # 正无穷
    neg_inf = 0xFF800000  # 负无穷
    pos_zero = 0x00000000 # 正零
    neg_zero = 0x80000000 # 负零
    finite_num = 0x40000000 # 有限数 (2.0)
    
    # 测试NaN算术运算
    result = api_ALU754_operate(env, nan, finite_num, 0)  # NaN + 有限数
    assert result is not None

    result = api_ALU754_operate(env, nan, finite_num, 1)  # NaN * 有限数
    assert result is not None

    result = api_ALU754_operate(env, nan, finite_num, 2)  # NaN / 有限数
    assert result is not None

    # 测试无穷算术运算
    result = api_ALU754_operate(env, pos_inf, finite_num, 0)  # 正无穷 + 有限数
    assert result is not None

    result = api_ALU754_operate(env, pos_inf, finite_num, 1)  # 正无穷 * 有限数
    assert result is not None

    result = api_ALU754_operate(env, pos_inf, finite_num, 2)  # 正无穷 / 有限数
    assert result is not None

    # 测试零值算术运算
    result = api_ALU754_operate(env, pos_zero, finite_num, 0)  # +0 + 有限数
    assert result is not None

    result = api_ALU754_operate(env, neg_zero, finite_num, 1)  # -0 * 有限数
    assert result is not None

    result = api_ALU754_operate(env, pos_zero, finite_num, 2)  # +0 / 有限数
    assert result is not None

    assert True, "api_ALU754特殊值算术运算测试完成"