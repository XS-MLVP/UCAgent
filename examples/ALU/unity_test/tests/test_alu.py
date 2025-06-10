#coding: utf-8


from alu_api import api_alu_operation, dut


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

