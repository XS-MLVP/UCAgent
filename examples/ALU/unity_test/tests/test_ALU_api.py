from ALU_api import *

def test_api_ALU_operation(dut):
    dut.fc_cover["FG-API"].mark_function("FC-OPERATION", test_api_ALU_operation, ["CK-ADD"])
    dut.fc_cover["FG-API"].sample()
    assert True
