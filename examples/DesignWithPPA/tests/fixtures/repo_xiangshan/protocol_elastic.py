"""Exercise reset, full-buffer backpressure, and same-cycle dequeue/enqueue."""


def test_reset_and_stall(env):
    """A pending result stays stable under backpressure and reset discards it."""

    assert env.read("resp_valid") == 0
    assert env.read("req_ready") == 1
    env.drive(req_valid=1, resp_ready=0, data=0x0706050403020100, amount=1, left=0)
    env.tick()
    env.drive(req_valid=0)
    for index in range(4):
        env.drive(data=index, amount=index, left=1)
        assert env.read("resp_valid") == 1
        assert env.read("req_ready") == 0
        assert env.read("result") == 0x0605040302010007
        env.tick()
    env.drive(reset=1)
    env.tick()
    env.drive(reset=0)
    assert env.read("resp_valid") == 0


def test_replace_pending(env):
    """Dequeue and enqueue together neither lose nor duplicate a result."""

    env.drive(req_valid=1, resp_ready=1, data=0x0706050403020100, amount=1, left=0)
    env.tick()
    assert env.read("resp_valid") == 1
    assert env.read("result") == 0x0605040302010007
    env.drive(left=1)
    assert env.read("req_ready") == 1
    env.tick()
    env.drive(req_valid=0)
    assert env.read("resp_valid") == 1
    assert env.read("result") == 0x0007060504030201
    env.tick()
    assert env.read("resp_valid") == 0
