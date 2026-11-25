# coding=utf-8

class MockA:
    def on_clock_edge(self, cycles):
        return cycles


class MockB:
    def on_clock_edge(self, cycles):
        return cycles * 2
