
from unity_test.tests.Adder_api import *

def test_basic(dut):
    try:
        sum, cout = api_adder_add(dut, 1, 2, 0)
        assert sum == 3
        assert cout == 0

        sum, cout = api_adder_add(dut, 0, 0, 0)
        assert sum == 0
        assert cout == 0

        sum, cout = api_adder_add(dut, 1, 2, 1)
        assert sum == 4
        assert cout == 0
    finally:
        dut.fc_cover["FG-ADD"].mark_function("FC-BASIC", test_basic, ["CK-NORM", "CK-ZERO", "CK-CIN"])

def test_overflow(dut):
    try:
        sum, cout = api_adder_add(dut, 2**64 - 1, 1, 0)
        assert cout == 1

        sum, cout = api_adder_add(dut, 2**64 - 1, 1, 1)
        assert cout == 1
    finally:
        dut.fc_cover["FG-ADD"].mark_function("FC-OVERFLOW", test_overflow, ["CK-OVERFLOW_NO_CIN", "CK-OVERFLOW_WITH_CIN"])

def test_boundary(dut):
    try:
        sum, cout = api_adder_add(dut, 2**64 - 1, 0, 0)
        assert sum == 2**64 - 1
        assert cout == 0

        sum, cout = api_adder_add(dut, 0, 2**64 - 1, 0)
        assert sum == 2**64 - 1
        assert cout == 0

        sum, cout = api_adder_add(dut, 2**64 - 1, 2**64 - 1, 0)
        assert cout == 1
    finally:
        dut.fc_cover["FG-ADD"].mark_function("FC-BOUNDARY", test_boundary, ["CK-MAX_A", "CK-MAX_B", "CK-MAX_BOTH"])
