"""Check lane identity, wraparound and combinational responsiveness."""


def test_direction_and_wrap(env):
    """Distinct lane bytes reveal reversed direction or bit-level shifts."""

    env.drive(data=0x0706050403020100, amount=1, left=0)
    assert env.read("result") == 0x0605040302010007
    env.drive(left=1)
    assert env.read("result") == 0x0007060504030201
    env.drive(amount=0)
    assert env.read("result") == 0x0706050403020100
    env.tick()
