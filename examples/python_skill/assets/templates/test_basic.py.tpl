from {DUT}_api import *


def test_basic(env):
    assert hasattr(env, "dut")
    env.dut.fc_cover["FG-PLACEHOLDER"].mark_function("FC-PLACEHOLDER", test_basic, ["CK-PLACEHOLDER"])
    env.Step(1)
