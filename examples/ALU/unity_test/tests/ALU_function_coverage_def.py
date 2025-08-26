#coding=utf-8
import toffee.funcov as fc

funcov_FG_API = fc.CovGroup("FG-API")
funcov_FG_SIMPLE = fc.CovGroup("FG-SIMPLE")
funcov_FG_HARD = fc.CovGroup("FG-HARD")

funcov_group = [funcov_FG_API, funcov_FG_SIMPLE, funcov_FG_HARD]


def init_coverage_group_api(g, dut):
    g.add_watch_point(dut, {
        "CK-ADD": lambda x: True,
        "CK-SUB": lambda x: True,
        "CK-SUB": lambda x: True,
    },
    name="FC-OPERATION")


def init_coverage_group_simple(g, dut):
    g.add_watch_point(dut,
        {
            "CK-NORM": lambda x: x.a.value - x.b.value - x.cin.value == x.out.value,
            "CK-BORROW": lambda x: x.cout.value == 1,
            "CK-CIN-NORM": lambda x: x.cin.value == 1 and (x.a.value - x.b.value - x.cin.value) == x.out.value,
            "CK-CIN-BORROW": lambda x: x.cin.value == 1 and x.cout.value == 1,
            "CK-UN-COVERED": lambda x: True
        },
        name="FC-SUB"
    )


def init_coverage_group_hard(g, dut):
    g.add_watch_point(
        dut,
        {
            "CK-NORM": lambda x: x.a.value * x.b.value & ((1 << 64) - 1) == x.out.value,
            "CK-OVERFLOW": lambda x: (x.a.value * x.b.value) >> 64 != 0 and x.cout.value == 1,
            "CK-SIGNED": lambda x: ((int(x.a.value) if x.a.value < (1 << 63) else x.a.value - (1 << 64)) *
                                    (int(x.b.value) if x.b.value < (1 << 63) else x.b.value - (1 << 64))) & ((1 << 64) - 1) == x.out.value,
            "CK-UNSIGNED": lambda x: (x.a.value * x.b.value) & ((1 << 64) - 1) == x.out.value
        },
        name="FC-MUL"
    )
    g.add_watch_point(
        dut,
        {
            "CK-AND": lambda x: x.op.value == 3 and (x.a.value & x.b.value) == x.out.value,
            "CK-OR": lambda x: x.op.value == 4 and (x.a.value | x.b.value) == x.out.value,
            "CK-XOR": lambda x: x.op.value == 5 and (x.a.value ^ x.b.value) == x.out.value,
            "CK-NOT": lambda x: x.op.value == 6 and (~x.a.value & ((1 << 64) - 1)) == x.out.value,
            "CK-SHL": lambda x: x.op.value == 7 and ((x.a.value << (x.b.value & 0x3F)) & ((1 << 64) - 1)) == x.out.value,
            "CK-SHR": lambda x: x.op.value == 8 and (x.a.value >> (x.b.value & 0x3F)) == x.out.value
        },
        name="FC-BITOP"
    )


def init_function_coverage(dut, cover_group):
    for g in cover_group:
        {
            "FG-API": init_coverage_group_api,
            "FG-SIMPLE": init_coverage_group_simple,
            "FG-HARD": init_coverage_group_hard
        }.get(g.name, lambda x, y: None)(g, dut)


def get_coverage_groups(dut):
    init_function_coverage(dut, funcov_group)     # 初始化功能覆盖
    return funcov_group

