from {DUT}_api import *
import random


def test_random(env):
    env.dut.fc_cover["FG-PLACEHOLDER"].mark_function("FC-PLACEHOLDER", test_random, ["CK-PLACEHOLDER"])

    a = random.randint(0, (1 << 8) - 1)
    b = random.randint(0, (1 << 8) - 1)
    cin = random.randint(0, 1)

    _ = (a, b, cin)
    env.Step(1)


# Optional pattern for UCAgent-managed loops:
# for _ in range(ucagent.repeat_count()):
#     ...
