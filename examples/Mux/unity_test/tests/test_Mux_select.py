
from Mux_api import *

def test_Mux_select_0(dut):
    """
    Test Mux select for sel=0.
    """
    dut.fc_cover['FG-SELECT'].mark_function('FC-SELECT-0', test_Mux_select_0, ['CK-BASIC', 'CK-ISOLATION'])
    # Test basic functionality
    in_data = 0b0001
    assert api_Mux_select(dut, 0, in_data) == 1
    # Test isolation
    in_data = 0b1110
    assert api_Mux_select(dut, 0, in_data) == 0

def test_Mux_select_1(dut):
    """
    Test Mux select for sel=1.
    """
    dut.fc_cover['FG-SELECT'].mark_function('FC-SELECT-1', test_Mux_select_1, ['CK-BASIC', 'CK-ISOLATION'])
    # Test basic functionality
    in_data = 0b0010
    assert api_Mux_select(dut, 1, in_data) == 1
    # Test isolation
    in_data = 0b1101
    assert api_Mux_select(dut, 1, in_data) == 0

def test_Mux_select_2(dut):
    """
    Test Mux select for sel=2.
    """
    dut.fc_cover['FG-SELECT'].mark_function('FC-SELECT-2', test_Mux_select_2, ['CK-BASIC', 'CK-ISOLATION'])
    # Test basic functionality
    in_data = 0b0100
    assert api_Mux_select(dut, 2, in_data) == 1
    # Test isolation
    in_data = 0b1011
    assert api_Mux_select(dut, 2, in_data) == 0

def test_Mux_select_3(dut):
    """
    Test Mux select for sel=3.
    """
    dut.fc_cover['FG-SELECT'].mark_function('FC-SELECT-3', test_Mux_select_3, ['CK-BASIC', 'CK-ISOLATION'])
    # Test basic functionality
    in_data = 0b1000
    assert api_Mux_select(dut, 3, in_data) == 1
    # Test isolation
    in_data = 0b0111
    assert api_Mux_select(dut, 3, in_data) == 0
