
from Mux_api import *

def test_api_Mux_select_0(dut):
    """
    Test api_Mux_select for sel=0.
    """
    dut.fc_cover['FG-API'].mark_function('FC-OPERATION', test_api_Mux_select_0, ['CK-SELECT-0'])
    in_data = 0b0001
    assert api_Mux_select(dut, 0, in_data) == 1
    in_data = 0b1110
    assert api_Mux_select(dut, 0, in_data) == 0

def test_api_Mux_select_1(dut):
    """
    Test api_Mux_select for sel=1.
    """
    dut.fc_cover['FG-API'].mark_function('FC-OPERATION', test_api_Mux_select_1, ['CK-SELECT-1'])
    in_data = 0b0010
    assert api_Mux_select(dut, 1, in_data) == 1
    in_data = 0b1101
    assert api_Mux_select(dut, 1, in_data) == 0

def test_api_Mux_select_2(dut):
    """
    Test api_Mux_select for sel=2.
    """
    dut.fc_cover['FG-API'].mark_function('FC-OPERATION', test_api_Mux_select_2, ['CK-SELECT-2'])
    in_data = 0b0100
    assert api_Mux_select(dut, 2, in_data) == 1
    in_data = 0b1011
    assert api_Mux_select(dut, 2, in_data) == 0

def test_api_Mux_select_3(dut):
    """
    Test api_Mux_select for sel=3.
    """
    dut.fc_cover['FG-API'].mark_function('FC-OPERATION', test_api_Mux_select_3, ['CK-SELECT-3'])
    in_data = 0b1000
    assert api_Mux_select(dut, 3, in_data) == 1
    in_data = 0b0111
    assert api_Mux_select(dut, 3, in_data) == 0
