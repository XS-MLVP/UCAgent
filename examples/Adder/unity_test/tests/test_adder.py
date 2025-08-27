
from unity_test.tests.Adder_api import *

def test_basic(dut):
    """
    测试加法器的基本功能，验证标准加法运算的正确性。
    
    测试目标：
    - 验证普通加法运算（CK-NORM）
    - 验证零值加法（CK-ZERO）  
    - 验证带进位输入的加法（CK-CIN）
    
    预期结果：所有基本加法运算应返回正确的和值，无溢出时cout=0
    """
    dut.fc_cover["FG-ADD"].mark_function("FC-BASIC", test_basic, ["CK-NORM", "CK-ZERO", "CK-CIN"])
    
    # 测试步骤1: 验证普通加法 1 + 2 = 3
    sum, cout = api_Adder_add(dut, 1, 2, 0)
    assert sum == 3, f"普通加法失败: 1 + 2 + 0 = {sum}, 期望 3"
    assert cout == 0, f"普通加法不应产生进位: cout = {cout}, 期望 0"
    
    # 测试步骤2: 验证零值加法 0 + 0 = 0
    sum, cout = api_Adder_add(dut, 0, 0, 0)
    assert sum == 0, f"零值加法失败: 0 + 0 + 0 = {sum}, 期望 0"
    assert cout == 0, f"零值加法不应产生进位: cout = {cout}, 期望 0"
    
    # 测试步骤3: 验证带进位输入的加法 1 + 2 + 1 = 4
    sum, cout = api_Adder_add(dut, 1, 2, 1)
    assert sum == 4, f"进位输入加法失败: 1 + 2 + 1 = {sum}, 期望 4"
    assert cout == 0, f"进位输入加法不应产生溢出: cout = {cout}, 期望 0"

def test_overflow(dut):
    """
    测试加法器的溢出处理功能，验证超出64位范围时的进位输出。
    
    测试目标：
    - 验证无进位输入时的溢出（CK-OVERFLOW_NO_CIN）
    - 验证有进位输入时的溢出（CK-OVERFLOW_WITH_CIN）
    
    预期结果：当加法结果超出64位时，cout应正确设置为1表示溢出
    """
    dut.fc_cover["FG-ADD"].mark_function("FC-OVERFLOW", test_overflow, ["CK-OVERFLOW_NO_CIN", "CK-OVERFLOW_WITH_CIN"])
    
    # 测试步骤1: 验证无进位输入的溢出 (2^64-1) + 1 = 溢出
    sum, cout = api_Adder_add(dut, 2**64 - 1, 1, 0)
    assert cout == 1, f"溢出检测失败: (2^64-1) + 1 + 0, cout = {cout}, 期望 1"
    
    # 测试步骤2: 验证有进位输入的溢出 (2^64-1) + 1 + 1 = 溢出
    sum, cout = api_Adder_add(dut, 2**64 - 1, 1, 1)
    assert cout == 1, f"进位输入溢出检测失败: (2^64-1) + 1 + 1, cout = {cout}, 期望 1"

def test_boundary(dut):
    """
    测试加法器的边界条件处理，验证最大值输入时的正确行为。
    
    测试目标：
    - 验证单个操作数为最大值（CK-MAX_A）
    - 验证另一个操作数为最大值（CK-MAX_B）
    - 验证两个操作数都为最大值（CK-MAX_BOTH）
    
    预期结果：边界值加法应正确处理，必要时产生正确的进位输出
    """
    dut.fc_cover["FG-ADD"].mark_function("FC-BOUNDARY", test_boundary, ["CK-MAX_A", "CK-MAX_B", "CK-MAX_BOTH"])
    
    # 测试步骤1: 验证第一个操作数为最大值 (2^64-1) + 0 = 2^64-1
    sum, cout = api_Adder_add(dut, 2**64 - 1, 0, 0)
    assert sum == 2**64 - 1, f"最大值A边界测试失败: sum = {sum}, 期望 {2**64 - 1}"
    assert cout == 0, f"最大值A边界不应溢出: cout = {cout}, 期望 0"
    
    # 测试步骤2: 验证第二个操作数为最大值 0 + (2^64-1) = 2^64-1
    sum, cout = api_Adder_add(dut, 0, 2**64 - 1, 0)
    assert sum == 2**64 - 1, f"最大值B边界测试失败: sum = {sum}, 期望 {2**64 - 1}"
    assert cout == 0, f"最大值B边界不应溢出: cout = {cout}, 期望 0"
    
    # 测试步骤3: 验证两个操作数都为最大值 (2^64-1) + (2^64-1) = 溢出
    sum, cout = api_Adder_add(dut, 2**64 - 1, 2**64 - 1, 0)
    assert cout == 1, f"双最大值边界溢出检测失败: cout = {cout}, 期望 1"
