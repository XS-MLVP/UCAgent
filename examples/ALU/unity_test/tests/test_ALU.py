#coding: utf-8


from ALU_api import api_ALU_operation, dut


def test_add_norm(dut):
    """
    测试ALU加法运算的正常情况
    
    测试目标：验证ALU在正常加法运算下的基本功能
    测试内容：执行简单的加法运算，不产生进位
    覆盖点：FC-ADD.CK-NORM (正常加法运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-ADD", test_add_norm, ["CK-NORM"])
    
    # 测试步骤1：设置加法运算参数 - 1 + 1 = 2，不产生进位
    # op=0(ADD), a=1, b=1, cin=0
    out, cout = api_ALU_operation(dut, 0, 1, 1, 0)
    
    # 测试步骤2：验证运算结果
    assert out == 2, f"期望输出2，实际输出{out}"
    
    # 测试步骤3：验证无进位输出
    assert cout == 0, f"期望无进位(0)，实际进位{cout}"


def test_add_carry(dut):
    """
    测试ALU加法运算的进位情况
    
    测试目标：验证ALU在加法运算产生进位时的功能
    测试内容：执行会产生进位的加法运算
    覆盖点：FC-ADD.CK-CARRY (加法进位)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-ADD", test_add_carry, ["CK-CARRY"])
    
    # 测试步骤1：设置最大值加法运算参数 - 0xFFFFFFFFFFFFFFFF + 1 = 0，产生进位
    # op=0(ADD), a=0xFFFFFFFFFFFFFFFF(最大64位无符号数), b=1, cin=0
    out, cout = api_ALU_operation(dut, 0, 0xFFFFFFFFFFFFFFFF, 1, 0)
    
    # 测试步骤2：验证运算结果为0（溢出后从0开始）
    assert out == 0, f"期望输出0（溢出），实际输出{out}"
    
    # 测试步骤3：验证产生进位
    assert cout == 1, f"期望产生进位(1)，实际进位{cout}"


def test_add_cin_norm(dut):
    """
    测试ALU带进位输入的加法运算正常情况
    
    测试目标：验证ALU在有进位输入时的加法功能
    测试内容：执行带进位输入的加法运算，不产生进位输出
    覆盖点：FC-ADD.CK-CIN-NORM (带进位输入的正常加法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-ADD", test_add_cin_norm, ["CK-CIN-NORM"])
    
    # 测试步骤1：设置带进位输入的加法运算参数 - 1 + 1 + 1 = 3
    # op=0(ADD), a=1, b=1, cin=1
    out, cout = api_ALU_operation(dut, 0, 1, 1, 1)
    
    # 测试步骤2：验证运算结果（两数相加再加进位输入）
    assert out == 3, f"期望输出3（1+1+1），实际输出{out}"
    
    # 测试步骤3：验证无进位输出
    assert cout == 0, f"期望无进位(0)，实际进位{cout}"


def test_add_cin_carry(dut):
    """
    测试ALU带进位输入的加法运算产生进位情况
    
    测试目标：验证ALU在有进位输入时产生进位输出的功能
    测试内容：执行带进位输入的加法运算，产生进位输出
    覆盖点：FC-ADD.CK-CIN-CARRY (带进位输入且产生进位的加法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-ADD", test_add_cin_carry, ["CK-CIN-CARRY"])
    
    # 测试步骤1：设置带进位输入且产生进位的加法运算参数 - 0xFFFFFFFFFFFFFFFF + 0 + 1 = 0
    # op=0(ADD), a=0xFFFFFFFFFFFFFFFF(最大值), b=0, cin=1
    out, cout = api_ALU_operation(dut, 0, 0xFFFFFFFFFFFFFFFF, 0, 1)
    
    # 测试步骤2：验证运算结果为0（最大值加1溢出）
    assert out == 0, f"期望输出0（溢出），实际输出{out}"
    
    # 测试步骤3：验证产生进位（进位输入导致溢出）
    assert cout == 1, f"期望产生进位(1)，实际进位{cout}"


def test_add_overflow(dut):
    """
    测试ALU加法运算的溢出情况
    
    测试目标：验证ALU在加法运算溢出时的处理功能
    测试内容：执行会导致溢出的加法运算
    覆盖点：FC-ADD.CK-OVERFLOW (加法溢出)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-ADD", test_add_overflow, ["CK-OVERFLOW"])
    
    # 测试步骤1：设置溢出加法运算参数 - 0xFFFFFFFFFFFFFFFE + 2 = 0
    # op=0(ADD), a=0xFFFFFFFFFFFFFFFE(次大值), b=2, cin=0
    out, cout = api_ALU_operation(dut, 0, 0xFFFFFFFFFFFFFFFE, 2, 0)
    
    # 测试步骤2：验证运算结果为0（溢出回绕）
    assert out == 0, f"期望输出0（溢出回绕），实际输出{out}"
    
    # 测试步骤3：验证产生进位（表示溢出）
    assert cout == 1, f"期望产生进位(1)表示溢出，实际进位{cout}"


def test_sub_norm(dut):
    """
    测试ALU减法运算的正常情况
    
    测试目标：验证ALU在正常减法运算下的基本功能
    测试内容：执行简单的减法运算，不产生借位
    覆盖点：FC-SUB.CK-NORM (正常减法运算), FC-SUB.CK-UN-COVERED (未覆盖分支)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-SUB", test_sub_norm, ["CK-NORM"])

    # 测试步骤1：设置减法运算参数 - 5 - 3 = 2，不产生借位
    # op=1(SUB), a=5, b=3, cin=0
    out, cout = api_ALU_operation(dut, 1, 5, 3, 0)
    
    # 测试步骤2：验证运算结果
    assert out == 2, f"期望输出2（5-3），实际输出{out}"
    
    # 测试步骤3：验证无借位输出
    assert cout == 0, f"期望无借位(0)，实际借位{cout}"


def test_un_cover(dut):
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-SUB", test_un_cover, ["CK-UN-COVERED"])
    assert False


def test_sub_borrow(dut):
    """
    测试ALU减法运算的借位情况
    
    测试目标：验证ALU在减法运算产生借位时的功能
    测试内容：执行会产生借位的减法运算
    覆盖点：FC-SUB.CK-BORROW (减法借位)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-SUB", test_sub_borrow, ["CK-BORROW"])
    
    # 测试步骤1：设置产生借位的减法运算参数 - 2 - 3 = 0xFFFFFFFFFFFFFFFF
    # op=1(SUB), a=2, b=3, cin=0
    out, cout = api_ALU_operation(dut, 1, 2, 3, 0)
    
    # 测试步骤2：验证运算结果（借位后的补码表示）
    assert out == 0xFFFFFFFFFFFFFFFF, f"期望输出0xFFFFFFFFFFFFFFFF（借位结果），实际输出{hex(out)}"
    
    # 测试步骤3：验证产生借位
    assert cout == 1, f"期望产生借位(1)，实际借位{cout}"


def test_sub_cin_norm(dut):
    """
    测试ALU带借位输入的减法运算正常情况
    
    测试目标：验证ALU在有借位输入时的减法功能
    测试内容：执行带借位输入的减法运算，不产生借位输出
    覆盖点：FC-SUB.CK-CIN-NORM (带借位输入的正常减法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-SUB", test_sub_cin_norm, ["CK-CIN-NORM"])
    
    # 测试步骤1：设置带借位输入的减法运算参数 - 10 - 5 - 1 = 4
    # op=1(SUB), a=10, b=5, cin=1（额外减去1）
    out, cout = api_ALU_operation(dut, 1, 10, 5, 1)
    
    # 测试步骤2：验证运算结果（被减数减去减数再减去借位输入）
    assert out == 4, f"期望输出4（10-5-1），实际输出{out}"
    
    # 测试步骤3：验证无借位输出
    assert cout == 0, f"期望无借位(0)，实际借位{cout}"


def test_sub_cin_borrow(dut):
    """
    测试ALU带借位输入的减法运算产生借位情况
    
    测试目标：验证ALU在有借位输入时产生借位输出的功能
    测试内容：执行带借位输入的减法运算，产生借位输出
    覆盖点：FC-SUB.CK-CIN-BORROW (带借位输入且产生借位的减法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-SIMPLE"].mark_function("FC-SUB", test_sub_cin_borrow, ["CK-CIN-BORROW"])
    
    # 测试步骤1：设置带借位输入且产生借位的减法运算参数 - 0 - 0 - 1 = 0xFFFFFFFFFFFFFFFF
    # op=1(SUB), a=0, b=0, cin=1（额外减去1导致借位）
    out, cout = api_ALU_operation(dut, 1, 0, 0, 1)
    
    # 测试步骤2：验证运算结果（0减1产生借位，结果为最大值）
    assert out == 0xFFFFFFFFFFFFFFFF, f"期望输出0xFFFFFFFFFFFFFFFF（借位结果），实际输出{hex(out)}"
    
    # 测试步骤3：验证产生借位（借位输入导致下溢）
    assert cout == 1, f"期望产生借位(1)，实际借位{cout}"


def test_mul_norm(dut):
    """
    测试ALU乘法运算的正常情况
    
    测试目标：验证ALU在正常乘法运算下的基本功能
    测试内容：执行简单的乘法运算，不产生溢出
    覆盖点：FC-MUL.CK-NORM (正常乘法运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-MUL", test_mul_norm, ["CK-NORM"])
    
    # 测试步骤1：设置乘法运算参数 - 2 * 3 = 6，不产生溢出
    # op=2(MUL), a=2, b=3, cin=0
    out, cout = api_ALU_operation(dut, 2, 2, 3, 0)
    
    # 测试步骤2：验证运算结果
    assert out == 6, f"期望输出6（2*3），实际输出{out}"
    
    # 测试步骤3：验证无溢出（高位为0）
    assert cout == 0, f"期望无溢出(0)，实际溢出{cout}"


def test_mul_overflow(dut):
    """
    测试ALU乘法运算的溢出情况
    
    测试目标：验证ALU在乘法运算溢出时的处理功能
    测试内容：执行会导致溢出的乘法运算
    覆盖点：FC-MUL.CK-OVERFLOW (乘法溢出)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-MUL", test_mul_overflow, ["CK-OVERFLOW"])
    
    # 测试步骤1：设置溢出乘法运算参数 - (1<<63) * 2 = 0，高64位非零
    # op=2(MUL), a=(1<<63)最高位为1, b=2, cin=0
    out, cout = api_ALU_operation(dut, 2, 1<<63, 2, 0)
    
    # 测试步骤2：验证运算结果为0（低64位）
    assert out == 0, f"期望输出0（溢出低位），实际输出{out}"
    
    # 测试步骤3：验证产生溢出（高64位非零）
    assert cout == 1, f"期望产生溢出(1)，实际溢出{cout}"


def test_mul_signed(dut):
    """
    测试ALU有符号乘法运算
    
    测试目标：验证ALU在有符号数乘法运算的功能
    测试内容：执行有符号数的乘法运算
    覆盖点：FC-MUL.CK-SIGNED (有符号乘法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-MUL", test_mul_signed, ["CK-SIGNED"])
    
    # 测试步骤1：设置有符号乘法运算参数 - (-2) * 3 = -6
    # op=2(MUL), a=(1<<64)-2（-2的二进制补码）, b=3, cin=0
    a = (1<<64) - 2  # -2 的补码表示
    out, cout = api_ALU_operation(dut, 2, a, 3, 0)
    
    # 测试步骤2：验证运算结果为-6的补码表示
    expected = (1<<64) - 6  # -6 的补码表示
    assert out == expected, f"期望输出{expected}（-6的补码），实际输出{out}"


def test_mul_unsigned(dut):
    """
    测试ALU无符号乘法运算
    
    测试目标：验证ALU在无符号数乘法运算的功能
    测试内容：执行无符号数的乘法运算
    覆盖点：FC-MUL.CK-UNSIGNED (无符号乘法)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-MUL", test_mul_unsigned, ["CK-UNSIGNED"])
    
    # 测试步骤1：设置无符号乘法运算参数 - 2 * 3 = 6
    # op=2(MUL), a=2, b=3, cin=0
    out, cout = api_ALU_operation(dut, 2, 2, 3, 0)
    
    # 测试步骤2：验证运算结果（无符号乘法）
    assert out == 6, f"期望输出6（2*3无符号），实际输出{out}"


def test_and(dut):
    """
    测试ALU逻辑与运算
    
    测试目标：验证ALU的按位逻辑与功能
    测试内容：执行两个操作数的按位逻辑与运算
    覆盖点：FC-BITOP.CK-AND (按位与运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_and, ["CK-AND"])
    
    # 测试步骤1：设置按位与运算参数 - 0b1010 & 0b1100 = 0b1000
    # op=3(AND), a=0b1010, b=0b1100, cin=0
    out, cout = api_ALU_operation(dut, 3, 0b1010, 0b1100, 0)
    
    # 测试步骤2：验证运算结果（按位与操作）
    assert out == 0b1000, f"期望输出{bin(0b1000)}，实际输出{bin(out)}"


def test_or(dut):
    """
    测试ALU逻辑或运算
    
    测试目标：验证ALU的按位逻辑或功能
    测试内容：执行两个操作数的按位逻辑或运算
    覆盖点：FC-BITOP.CK-OR (按位或运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_or, ["CK-OR"])
    
    # 测试步骤1：设置按位或运算参数 - 0b1010 | 0b1100 = 0b1110
    # op=4(OR), a=0b1010, b=0b1100, cin=0
    out, cout = api_ALU_operation(dut, 4, 0b1010, 0b1100, 0)
    
    # 测试步骤2：验证运算结果（按位或操作）
    assert out == 0b1110, f"期望输出{bin(0b1110)}，实际输出{bin(out)}"


def test_xor(dut):
    """
    测试ALU逻辑异或运算
    
    测试目标：验证ALU的按位逻辑异或功能
    测试内容：执行两个操作数的按位逻辑异或运算
    覆盖点：FC-BITOP.CK-XOR (按位异或运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_xor, ["CK-XOR"])
    
    # 测试步骤1：设置按位异或运算参数 - 0b1010 ^ 0b1100 = 0b0110
    # op=5(XOR), a=0b1010, b=0b1100, cin=0
    out, cout = api_ALU_operation(dut, 5, 0b1010, 0b1100, 0)
    
    # 测试步骤2：验证运算结果（按位异或操作）
    assert out == 0b0110, f"期望输出{bin(0b0110)}，实际输出{bin(out)}"


def test_not(dut):
    """
    测试ALU逻辑非运算
    
    测试目标：验证ALU的按位逻辑非功能
    测试内容：执行单个操作数的按位逻辑非运算
    覆盖点：FC-BITOP.CK-NOT (按位非运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_not, ["CK-NOT"])
    
    # 测试步骤1：设置按位非运算参数 - ~0b1010 = 0xFFFFFFFFFFFFFFF5
    # op=6(NOT), a=0b1010, b=0（忽略）, cin=0
    out, cout = api_ALU_operation(dut, 6, 0b1010, 0, 0)
    
    # 测试步骤2：验证运算结果（按位非操作，64位掩码）
    expected = (~0b1010) & ((1<<64)-1)  # 64位掩码
    assert out == expected, f"期望输出{hex(expected)}，实际输出{hex(out)}"


def test_shl(dut):
    """
    测试ALU左移位运算
    
    测试目标：验证ALU的左移位功能
    测试内容：执行左移位运算
    覆盖点：FC-BITOP.CK-SHL (左移位运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_shl, ["CK-SHL"])
    
    # 测试步骤1：设置左移位运算参数 - 1 << 3 = 8
    # op=7(SHL), a=1, b=3（移位位数）, cin=0
    out, cout = api_ALU_operation(dut, 7, 1, 3, 0)
    
    # 测试步骤2：验证运算结果（左移3位）
    assert out == 8, f"期望输出8（1<<3），实际输出{out}"


def test_shr(dut):
    """
    测试ALU右移位运算
    
    测试目标：验证ALU的右移位功能
    测试内容：执行右移位运算
    覆盖点：FC-BITOP.CK-SHR (右移位运算)
    """
    # 标记功能覆盖点
    dut.fc_cover["FG-HARD"].mark_function("FC-BITOP", test_shr, ["CK-SHR"])
    
    # 测试步骤1：设置右移位运算参数 - 8 >> 3 = 1
    # op=8(SHR), a=8, b=3（移位位数）, cin=0
    out, cout = api_ALU_operation(dut, 8, 8, 3, 0)
    
    # 测试步骤2：验证运算结果（右移3位）
    assert out == 1, f"期望输出1（8>>3），实际输出{out}"

