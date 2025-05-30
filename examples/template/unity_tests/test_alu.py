#coding: utf-8

import pytest
import toffee.funcov as fc
from toffee_test.reporter import set_func_coverage

from api_alu import api_alu_operation, create_dut

funcov_FG_SIMPLE = fc.CovGroup("FG-SIMPLE")
funcov_FG_HARD = fc.CovGroup("FG-HARD")

funcov_group = [funcov_FG_SIMPLE, funcov_FG_HARD]


def init_coverage_group_simple(g, dut):
    def check_cin_overflow(x):
        return x.cin.value == 1 and x.cout.value == 1 and \
               (x.a.value + x.b.value + x.cin.value) & ((1 << 64) - 1) == x.out.value
    g.add_watch_point(dut,
        {
            "CK-NORM": lambda x: x.a.value + x.b.value == x.out.value,
            "CK-OVERFLOW": lambda x: x.cout.value == 1,
            "CK-CIN-NORM": lambda x: x.cin.value == 1 and x.a.value + x.b.value + x.cin.value == x.out.value,
            "CK-CIN-OVERFLOW": check_cin_overflow
         },
        name="FC-ADD")
    g.add_watch_point(dut,
        {
            "CK-NORM": lambda x: x.a.value - x.b.value - x.cin.value == x.out.value,
            "CK-BORROW": lambda x: x.cout.value == 1,
            "CK-CIN-NORM": lambda x: x.cin.value == 1 and (x.a.value - x.b.value - x.cin.value) == x.out.value,
            "CK-CIN-BORROW": lambda x: x.cin.value == 1 and x.cout.value == 1
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
            "FG-SIMPLE": init_coverage_group_simple,
            "FG-HARD": init_coverage_group_hard
        }.get(g.name, lambda x, y: None)(g, dut)


@pytest.fixture()
def dut(request):
    dut = create_dut()                            # 创建DUT
    init_function_coverage(dut, funcov_group)     # 初始化功能覆盖
    dut.InitClock("clock")                        # 初始化时钟
    dut.StepRis(lambda _: [g.sample()
                           for g in
                           funcov_group])         # 上升沿采样
    setattr(dut, "_g",
            {g.name:g for g in funcov_group})     # 保存覆盖组到DUT
    yield dut
    # 测试后处理
    set_func_coverage(request, funcov_group)      # 需要在测试结束的时候，通过set_func_coverage把覆盖组传递给toffee_test*
    for g in funcov_group:                        # 采样覆盖组
        g.clear()                                 # 清空统计
    dut.Finish()                                  # 清理DUT


def test_add_normal(dut):
    out, _ = api_alu_operation(dut, 0, 1, 2)
    dut._g["FG-SIMPLE"].mark_function("FC-ADD", test_add_normal, ["CK-NORM"])  # 标记覆盖哪个功能和测点
    assert out == 3


def test_add_overflow(dut):
    # 0xFFFFFFFFFFFFFFFF + 1 = 0 (溢出), cout=1
    out, cout = api_alu_operation(dut, 0, 0xFFFFFFFFFFFFFFFF, 1, 0)
    dut._g["FG-SIMPLE"].mark_function("FC-ADD", test_add_overflow, ["CK-OVERFLOW"])
    assert out == 0
    assert cout == 1


def test_add_cin_norm(dut):
    # 2 + 3 + 1 = 6
    out, cout = api_alu_operation(dut, 0, 2, 3, 1)
    dut._g["FG-SIMPLE"].mark_function("FC-ADD", test_add_cin_norm, ["CK-CIN-NORM"])
    assert out == 6
    assert cout == 0


def test_add_cin_overflow(dut):
    # 0xFFFFFFFFFFFFFFFF + 0 + 1 = 0 (溢出), cout=1
    out, cout = api_alu_operation(dut, 0, 0xFFFFFFFFFFFFFFFF, 0, 1)
    dut._g["FG-SIMPLE"].mark_function("FC-ADD", test_add_cin_overflow, ["CK-CIN-OVERFLOW"])
    assert out == 0
    assert cout == 1


def test_sub_norm(dut):
    # 5 - 3 = 2
    out, cout = api_alu_operation(dut, 1, 5, 3, 0)
    dut._g["FG-SIMPLE"].mark_function("FC-SUB", test_sub_norm, ["CK-NORM"])
    assert out == 2
    assert cout == 0


def test_sub_borrow(dut):
    # 2 - 3 = 0xFFFFFFFFFFFFFFFF (借位), cout=1
    out, cout = api_alu_operation(dut, 1, 2, 3, 0)
    dut._g["FG-SIMPLE"].mark_function("FC-SUB", test_sub_borrow, ["CK-BORROW"])
    assert out == 0xFFFFFFFFFFFFFFFF
    assert cout == 1


def test_sub_cin_norm(dut):
    # 10 - 5 - 1 = 4
    out, cout = api_alu_operation(dut, 1, 10, 5, 1)
    dut._g["FG-SIMPLE"].mark_function("FC-SUB", test_sub_cin_norm, ["CK-CIN-NORM"])
    assert out == 4
    assert cout == 0


def test_sub_cin_borrow(dut):
    # 0 - 0 - 1 = 0xFFFFFFFFFFFFFFFF (借位), cout=1
    out, cout = api_alu_operation(dut, 1, 0, 0, 1)
    dut._g["FG-SIMPLE"].mark_function("FC-SUB", test_sub_cin_borrow, ["CK-CIN-BORROW"])
    assert out == 0xFFFFFFFFFFFFFFFF
    assert cout == 1


def test_mul_norm(dut):
    # 2 * 3 = 6
    out, cout = api_alu_operation(dut, 2, 2, 3, 0)
    dut._g["FG-HARD"].mark_function("FC-MUL", test_mul_norm, ["CK-NORM"])
    assert out == 6
    assert cout == 0


def test_mul_overflow(dut):
    # (1<<63) * 2 = 0, 高64位非零，cout=1
    out, cout = api_alu_operation(dut, 2, 1<<63, 2, 0)
    dut._g["FG-HARD"].mark_function("FC-MUL", test_mul_overflow, ["CK-OVERFLOW"])
    assert out == 0
    assert cout == 1


def test_mul_signed(dut):
    # -2 * 3 = -6 (有符号乘法)
    a = (1<<64) - 2  # -2 的补码
    out, cout = api_alu_operation(dut, 2, a, 3, 0)
    dut._g["FG-HARD"].mark_function("FC-MUL", test_mul_signed, ["CK-SIGNED"])
    # 期望结果为补码形式的 -6
    assert out == (1<<64) - 6


def test_mul_unsigned(dut):
    # 2 * 3 = 6 (无符号乘法)
    out, cout = api_alu_operation(dut, 2, 2, 3, 0)
    dut._g["FG-HARD"].mark_function("FC-MUL", test_mul_unsigned, ["CK-UNSIGNED"])
    assert out == 6


def test_and(dut):
    # 0b1010 & 0b1100 = 0b1000
    out, cout = api_alu_operation(dut, 3, 0b1010, 0b1100, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_and, ["CK-AND"])
    assert out == 0b1000


def test_or(dut):
    # 0b1010 | 0b1100 = 0b1110
    out, cout = api_alu_operation(dut, 4, 0b1010, 0b1100, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_or, ["CK-OR"])
    assert out == 0b1110


def test_xor(dut):
    # 0b1010 ^ 0b1100 = 0b0110
    out, cout = api_alu_operation(dut, 5, 0b1010, 0b1100, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_xor, ["CK-XOR"])
    assert out == 0b0110


def test_not(dut):
    # ~0b1010 = 0xFFFFFFFFFFFFFFF5
    out, cout = api_alu_operation(dut, 6, 0b1010, 0, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_not, ["CK-NOT"])
    assert out == (~0b1010) & ((1<<64)-1)


def test_shl(dut):
    # 1 << 3 = 8
    out, cout = api_alu_operation(dut, 7, 1, 3, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_shl, ["CK-SHL"])
    assert out == 8


def test_shr(dut):
    # 8 >> 3 = 1
    out, cout = api_alu_operation(dut, 8, 8, 3, 0)
    dut._g["FG-HARD"].mark_function("FC-BITOP", test_shr, ["CK-SHR"])
    assert out == 1

