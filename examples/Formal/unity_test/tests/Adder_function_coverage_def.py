import toffee.funcov as fc

# 1. 创建功能覆盖组
funcov_api = fc.CovGroup("FG-API")
funcov_arithmetic = fc.CovGroup("FG-ARITHMETIC")
funcov_bit_width = fc.CovGroup("FG-BIT-WIDTH")

# 覆盖组列表
funcov_group = [funcov_api, funcov_arithmetic, funcov_bit_width]


def init_coverage_group_api(g, dut):
    """初始化API覆盖组"""
    g.add_watch_point(dut,
        {
            "CK-ADD": lambda x: x.a.value == 0 and x.b.value == 0 and x.cin.value == 0 and x.sum.value == 0 and x.cout.value == 0,
        },
        name="FC-OPERATION")


def init_coverage_group_arithmetic(g, dut):
    """初始化算术运算覆盖组"""
    def check_basic(x):
        # 基本加法：无进位输入时的基本加法运算
        if x.cin.value == 0:
            expected_sum = (x.a.value + x.b.value) & ((1 << 63) - 1)
            return x.sum.value == expected_sum
        return False
    
    def check_carry_in(x):
        # 进位输入：有进位输入时的加法运算
        if x.cin.value == 1:
            expected_sum = (x.a.value + x.b.value + 1) & ((1 << 63) - 1)
            return x.sum.value == expected_sum
        return False
    
    def check_overflow(x):
        # 加法溢出：验证结果超出64位时进位输出正确性
        # 当a+b+cin >= 2^64时，cout应该为1
        sum_64bit = x.a.value + x.b.value + x.cin.value
        expected_cout = 1 if sum_64bit >= (1 << 64) else 0
        return x.cout.value == expected_cout
    
    def check_zero(x):
        # 零值运算：验证操作数为0时的运算正确性
        if x.a.value == 0 and x.b.value == 0 and x.cin.value == 0:
            return x.sum.value == 0 and x.cout.value == 0
        return False
    
    def check_boundary(x):
        # 边界条件：验证最大值、最小值等边界条件下的运算
        # 检查是否涉及边界值
        max_val = (1 << 64) - 1
        return (x.a.value == 0 or x.a.value == max_val or 
                x.b.value == 0 or x.b.value == max_val)

    g.add_watch_point(dut,
        {
            "CK-BASIC": check_basic,
            "CK-CARRY-IN": check_carry_in,
            "CK-OVERFLOW": check_overflow,
            "CK-ZERO": check_zero,
            "CK-BOUNDARY": check_boundary,
        },
        name="FC-ADD")


def init_coverage_group_bit_width(g, dut):
    """初始化位宽处理覆盖组"""
    def check_sum_width(x):
        # 输出位宽：验证sum只有63位的输出是否符合设计意图
        # 这里我们检查sum的值是否在63位范围内
        return x.sum.value < (1 << 63)
    
    def check_sum_value(x):
        # 输出值正确性：验证63位输出值的正确性，特别是最高位的处理
        # 计算期望值并与实际值比较
        expected_sum = (x.a.value + x.b.value + x.cin.value) & ((1 << 63) - 1)
        return x.sum.value == expected_sum

    g.add_watch_point(dut,
        {
            "CK-SUM-WIDTH": check_sum_width,
            "CK-SUM-VALUE": check_sum_value,
        },
        name="FC-SUM-WIDTH")


def init_function_coverage(dut, cover_group):
    """初始化所有功能覆盖"""
    coverage_init_map = {
        "FG-API": init_coverage_group_api,
        "FG-ARITHMETIC": init_coverage_group_arithmetic,
        "FG-BIT-WIDTH": init_coverage_group_bit_width,
    }
    
    for g in cover_group:
        init_func = coverage_init_map.get(g.name)
        if init_func:
            init_func(g, dut)
        else:
            print(f"警告：未找到覆盖组 {g.name} 的初始化函数")


def get_coverage_groups(dut):
    """获取功能覆盖组列表
    
    Args:
        dut: DUT实例，可为None（用于获取覆盖组结构）
        
    Returns:
        List[CovGroup]: 功能覆盖组列表
    """
    init_function_coverage(dut, funcov_group)
    return funcov_group