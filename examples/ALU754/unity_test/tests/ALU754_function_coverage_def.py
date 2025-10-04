import toffee.funcov as fc
from toffee import Bundle, Signals
from typing import List


def get_coverage_groups(dut) -> List[fc.CovGroup]:
    """获取所有功能覆盖组

    Args:
        dut: DUT实例，可为None（用于获取覆盖组结构）

    Returns:
        List[CovGroup]: 功能覆盖组列表
    """
    # 创建功能覆盖组，名称对应功能描述文档中的<FG-*>标签
    funcov_api = fc.CovGroup("FG-API")
    funcov_arithmetic = fc.CovGroup("FG-ARITHMETIC")
    funcov_comparator = fc.CovGroup("FG-COMPARATOR")
    funcov_special_values = fc.CovGroup("FG-SPECIAL-VALUES")

    # 初始化各覆盖组
    init_function_coverage(dut, [
        funcov_api,
        funcov_arithmetic,
        funcov_comparator,
        funcov_special_values
    ])

    return [
        funcov_api,
        funcov_arithmetic,
        funcov_comparator,
        funcov_special_values
    ]


def init_coverage_group_api(g, dut):
    """初始化API功能覆盖组"""
    # 通用operation功能
    g.add_watch_point(dut,
        {
            # 加法操作：验证op=0时的加法运算功能
            "CK-ADD": lambda x: x.op.value == 0,
            # 乘法操作：验证op=1时的乘法运算功能
            "CK-MUL": lambda x: x.op.value == 1,
            # 除法操作：验证op=2时的除法运算功能
            "CK-DIV": lambda x: x.op.value == 2,
            # 比较操作：验证op=3时的比较运算功能
            "CK-CMP": lambda x: x.op.value == 3,
            # 无效操作码：验证op值超出定义范围时的处理
            "CK-INVALID": lambda x: x.op.value >= 4,
        },
        name="FC-OPERATION")


def init_coverage_group_arithmetic(g, dut):
    """初始化算术运算功能覆盖组"""
    # 加法功能
    g.add_watch_point(dut,
        {
            # 基本加法：验证正常浮点数的加法运算
            "CK-BASIC": lambda x: x.op.value == 0 and x.overflow.value == 0 and x.underflow.value == 0,
            # 加法溢出：验证结果超出浮点表示范围时溢出标志的正确性
            "CK-OVERFLOW": lambda x: x.op.value == 0 and x.overflow.value == 1,
            # 加法下溢：验证结果小于浮点最小正数时下溢标志的正确性
            "CK-UNDERFLOW": lambda x: x.op.value == 0 and x.underflow.value == 1,
            # 零值运算：验证操作数为0时的运算正确性
            "CK-ZERO": lambda x: x.op.value == 0 and (x.a.value == 0 or x.b.value == 0),
            # 负数运算：验证负数参与的加法运算
            "CK-NEGATIVE": lambda x: x.op.value == 0 and ((x.a.value >> 31) == 1 or (x.b.value >> 31) == 1),
            # NaN运算：验证NaN参与的加法运算结果为NaN
            "CK-NAN": lambda x: x.op.value == 0 and is_nan(x.a.value) or is_nan(x.b.value),
            # 无穷运算：验证无穷参与的加法运算
            "CK-INFINITY": lambda x: x.op.value == 0 and (is_infinity(x.a.value) or is_infinity(x.b.value)),
        },
        name="FC-ADD")

    # 乘法功能
    g.add_watch_point(dut,
        {
            # 基本乘法：验证正常浮点数的乘法运算
            "CK-BASIC": lambda x: x.op.value == 1 and x.overflow.value == 0 and x.underflow.value == 0,
            # 乘法溢出：验证结果超出浮点表示范围时溢出标志的正确性
            "CK-OVERFLOW": lambda x: x.op.value == 1 and x.overflow.value == 1,
            # 乘法下溢：验证结果小于浮点最小正数时下溢标志的正确性
            "CK-UNDERFLOW": lambda x: x.op.value == 1 and x.underflow.value == 1,
            # 零乘数：验证操作数为0时结果为0
            "CK-ZERO-FACTOR": lambda x: x.op.value == 1 and (x.a.value == 0 or x.b.value == 0),
            # 负数运算：验证负数参与的乘法运算
            "CK-NEGATIVE": lambda x: x.op.value == 1 and ((x.a.value >> 31) == 1 or (x.b.value >> 31) == 1),
            # NaN运算：验证NaN参与的乘法运算结果为NaN
            "CK-NAN": lambda x: x.op.value == 1 and is_nan(x.a.value) or is_nan(x.b.value),
            # 无穷运算：验证无穷参与的乘法运算
            "CK-INFINITY": lambda x: x.op.value == 1 and (is_infinity(x.a.value) or is_infinity(x.b.value)),
        },
        name="FC-MUL")

    # 除法功能
    g.add_watch_point(dut,
        {
            # 基本除法：验证正常浮点数的除法运算
            "CK-BASIC": lambda x: x.op.value == 2 and x.overflow.value == 0 and x.underflow.value == 0,
            # 除法溢出：验证结果超出浮点表示范围时溢出标志的正确性
            "CK-OVERFLOW": lambda x: x.op.value == 2 and x.overflow.value == 1,
            # 除法下溢：验证结果小于浮点最小正数时下溢标志的正确性
            "CK-UNDERFLOW": lambda x: x.op.value == 2 and x.underflow.value == 1,
            # 除零运算：验证被除数为0时的行为
            "CK-DIV-BY-ZERO": lambda x: x.op.value == 2 and x.b.value == 0,
            # 零被除：验证0除以非零数的运算
            "CK-ZERO-DIV": lambda x: x.op.value == 2 and x.a.value == 0 and x.b.value != 0,
            # NaN运算：验证NaN参与的除法运算结果为NaN
            "CK-NAN": lambda x: x.op.value == 2 and is_nan(x.a.value) or is_nan(x.b.value),
            # 无穷运算：验证无穷参与的除法运算
            "CK-INFINITY": lambda x: x.op.value == 2 and (is_infinity(x.a.value) or is_infinity(x.b.value)),
        },
        name="FC-DIV")


def init_coverage_group_comparator(g, dut):
    """初始化比较功能覆盖组"""
    # 比较功能
    g.add_watch_point(dut,
        {
            # 大于比较：验证A > B时gt为1，lt和eq均为0
            "CK-GT": lambda x: x.op.value == 3 and x.gt.value == 1 and x.lt.value == 0 and x.eq.value == 0,
            # 小于比较：验证A < B时lt为1，gt和eq均为0
            "CK-LT": lambda x: x.op.value == 3 and x.lt.value == 1 and x.gt.value == 0 and x.eq.value == 0,
            # 等于比较：验证A == B时eq为1，gt和lt均为0
            "CK-EQ": lambda x: x.op.value == 3 and x.eq.value == 1 and x.gt.value == 0 and x.lt.value == 0,
            # NaN比较：验证任一操作数为NaN时，gt、lt、eq均为0
            "CK-NAN-COMP": lambda x: x.op.value == 3 and (is_nan(x.a.value) or is_nan(x.b.value)),
            # 零值比较：验证正零与负零的比较结果
            "CK-ZERO-COMP": lambda x: x.op.value == 3 and ((x.a.value == 0 and x.b.value == 0x80000000) or (x.a.value == 0x80000000 and x.b.value == 0)),
            # 无穷比较：验证无穷值之间的比较
            "CK-INFINITY-COMP": lambda x: x.op.value == 3 and (is_infinity(x.a.value) or is_infinity(x.b.value)),
            # 负数比较：验证负数间的比较运算
            "CK-NEGATIVE-COMP": lambda x: x.op.value == 3 and ((x.a.value >> 31) == 1 or (x.b.value >> 31) == 1),
        },
        name="FC-CMP")


def init_coverage_group_special_values(g, dut):
    """初始化特殊值处理覆盖组"""
    # 特殊值运算
    g.add_watch_point(dut,
        {
            # NaN算术：验证NaN参与的所有算术运算结果为NaN
            "CK-NAN-ARITH": lambda x: is_nan(x.a.value) or is_nan(x.b.value),
            # 无穷算术：验证无穷参与的算术运算
            "CK-INFINITY-ARITH": lambda x: is_infinity(x.a.value) or is_infinity(x.b.value),
            # 零值算术：验证+0和-0参与的算术运算
            "CK-ZERO-ARITH": lambda x: x.a.value == 0 or x.a.value == 0x80000000 or x.b.value == 0 or x.b.value == 0x80000000,
            # 非规约数：验证非规约浮点数的运算处理
            "CK-SUBNORMAL": lambda x: is_subnormal(x.a.value) or is_subnormal(x.b.value),
            # 舍入处理：验证运算结果的舍入行为
            "CK-ROUNDING": lambda x: (x.op.value in [0, 1, 2])  # 所有算术运算都涉及舍入
        },
        name="FC-SPECIAL-VALUES")


def init_function_coverage(dut, cover_group):
    """初始化所有功能覆盖"""
    coverage_init_map = {
        "FG-API": init_coverage_group_api,
        "FG-ARITHMETIC": init_coverage_group_arithmetic,
        "FG-COMPARATOR": init_coverage_group_comparator,
        "FG-SPECIAL-VALUES": init_coverage_group_special_values,
    }

    for g in cover_group:
        init_func = coverage_init_map.get(g.name)
        if init_func:
            init_func(g, dut)
        else:
            print(f"警告：未找到覆盖组 {g.name} 的初始化函数")


def is_nan(value):
    """检查IEEE 754浮点数是否为NaN"""
    # NaN: 指数全为1且尾数不为0
    exp = (value >> 23) & 0xFF
    mantissa = value & 0x7FFFFF
    return exp == 0xFF and mantissa != 0


def is_infinity(value):
    """检查IEEE 754浮点数是否为无穷"""
    # 正无穷: 0x7F800000, 负无穷: 0xFF800000
    exp = (value >> 23) & 0xFF
    mantissa = value & 0x7FFFFF
    return exp == 0xFF and mantissa == 0


def is_subnormal(value):
    """检查IEEE 754浮点数是否为非规约数"""
    # 非规约数: 指数全为0且尾数不为0
    exp = (value >> 23) & 0xFF
    mantissa = value & 0x7FFFFF
    return exp == 0 and mantissa != 0