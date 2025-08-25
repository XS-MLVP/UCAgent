
import toffee.funcov as fc

funcov_add = fc.CovGroup("FG-ADD")
funcov_group = [funcov_add]

def init_coverage_group_add(g, dut):
    # Check if watch points already exist to prevent duplication
    if "FC-BASIC" not in g.cov_points:
        g.add_watch_point(dut,
            {
                "CK-ZERO": lambda x: x.a.value == 0 and x.b.value == 0 and x.cin.value == 0 and x.sum.value == 0 and x.cout.value == 0,
                "CK-NORM": lambda x: x.a.value + x.b.value == x.sum.value and x.cout.value == 0,
                "CK-CIN": lambda x: x.a.value + x.b.value + x.cin.value == x.sum.value and x.cout.value == 0,
            },
            name="FC-BASIC")
    if "FC-OVERFLOW" not in g.cov_points:
        g.add_watch_point(dut,
            {
                "CK-OVERFLOW_NO_CIN": lambda x: x.a.value + x.b.value >= 2**64 and x.cout.value == 1,
                "CK-OVERFLOW_WITH_CIN": lambda x: x.a.value + x.b.value + x.cin.value >= 2**64 and x.cout.value == 1,
            },
            name="FC-OVERFLOW")
    if "FC-BOUNDARY" not in g.cov_points:
        g.add_watch_point(dut,
            {
                "CK-MAX_A": lambda x: x.a.value == 2**64 - 1 and x.b.value == 0,
                "CK-MAX_B": lambda x: x.a.value == 0 and x.b.value == 2**64 - 1,
                "CK-MAX_BOTH": lambda x: x.a.value == 2**64 - 1 and x.b.value == 2**64 - 1,
            },
            name="FC-BOUNDARY")

def init_function_coverage(dut, cover_group):
    init_coverage_group_add(cover_group[0], dut)

def get_coverage_groups(dut):
    init_function_coverage(dut, funcov_group)
    return funcov_group
