# coding=utf-8

class MockD:
    # wrong signature: missing cycles arg
    def on_clock_edge(self):
        return 0
