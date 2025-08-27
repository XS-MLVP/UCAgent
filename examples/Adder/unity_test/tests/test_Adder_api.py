
from Adder_api import *

def test_api_Adder_add(dut):
    """
    测试加法器API接口的正确性，验证API调用是否按预期工作。
    
    测试目标：
    - 验证简单加法API调用（CK-SIMPLE）
    - 验证带进位输入的API调用（CK-CIN）
    
    预期结果：API应正确封装底层加法器操作，返回准确的(sum, cout)元组
    """
    dut.fc_cover["FG-API"].mark_function("FC-ADD", test_api_Adder_add,
                                         ["CK-SIMPLE","CK-CIN"])
    
    # 测试步骤1: 验证简单加法API - api_Adder_add(1, 2, 0) = (3, 0)
    result = api_Adder_add(dut, 1, 2, 0)
    assert result == (3, 0), f"简单加法API失败: api_Adder_add(1, 2, 0) = {result}, 期望 (3, 0)"  # CK-SIMPLE
    
    # 测试步骤2: 验证带进位输入API - api_Adder_add(1, 2, 1) = (4, 0)  
    result = api_Adder_add(dut, 1, 2, 1)
    assert result == (4, 0), f"进位输入API失败: api_Adder_add(1, 2, 1) = {result}, 期望 (4, 0)"  # CK-CIN
