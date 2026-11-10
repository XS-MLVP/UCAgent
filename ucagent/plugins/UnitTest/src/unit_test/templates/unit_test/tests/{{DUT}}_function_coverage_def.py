#coding=utf-8

import toffee.funcov as fc

# 为测试点添加检测点举例：
#def create_check_points_for_group_A(g, dut):
#    def check_cin_overflow(x):
#        return x.cin.value == 1 and x.cout.value == 1 and \
#               (x.a.value + x.b.value + x.cin.value) & ((1 << 64) - 1) == x.out.value
#    g.add_watch_point(dut,
#        {
#            "CK-NORM": lambda x: x.a.value + x.b.value == x.out.value,
#            "CK-OVERFLOW": lambda x: x.cout.value == 1,
#            "CK-CIN-NORM": lambda x: x.cin.value == 1 and x.a.value + x.b.value + x.cin.value == x.out.value,
#            "CK-CIN-OVERFLOW": check_cin_overflow
#         },
#        name="FC-ADD")
#    g.add_watch_point(dut,
#        {
#            "CK-NORM": lambda x: x.a.value - x.b.value - x.cin.value == x.out.value,
#            "CK-BORROW": lambda x: x.cout.value == 1,
#            "CK-CIN-NORM": lambda x: x.cin.value == 1 and (x.a.value - x.b.value - x.cin.value) == x.out.value,
#            "CK-CIN-BORROW": lambda x: x.cin.value == 1 and x.cout.value == 1,
#            "CK-UN-COVERED": lambda x: True
#        },
#        name="FC-SUB"
#    )


def get_coverage_groups(dut):
    ret = []
    # 在这里创建你需要的功能覆盖组， 例如：
    #  ret.append(fc.CovGroup("FG-A"))
    #  ret.append(fc.CovGroup("FG-B"))
    #  ....
    # 根据DUT的功能需要，为每个分组创建功能点对应的检测点，例如：
    # create_check_points_for_group_A(ret[0], dut)
    # ....
    return ret
