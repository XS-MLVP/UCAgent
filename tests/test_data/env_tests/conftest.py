# coding=utf-8

import pytest


class DummyDut:
    def __init__(self):
        # minimal DUT for tests
        self.xclock = type("Clk", (), {
            "ClearRisCallBacks": lambda self: None,
        })()

    def Step(self, n):
        pass

    def StepRis(self, cb):
        pass


@pytest.fixture(scope="function")
def dut(request):
    # provide a dummy dut fixture for env tests
    yield DummyDut()


@pytest.fixture(scope="function")
def env(dut):
    # a minimal env object for tests
    class Env:
        def __init__(self, dut):
            self.dut = dut
    return Env(dut)
