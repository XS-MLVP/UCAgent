#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIGINT behavior tests for VerifyPDB."""

import os
import signal
import sys

import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.verify_pdb import VerifyPDB


class _DummyAgent:
    def __init__(self):
        self._break = False
        self.echo_msgs = []

    def set_break(self, value=True):
        self._break = value

    def is_break(self):
        return self._break

    def message_echo(self, msg, end="\n"):
        self.echo_msgs.append((msg, end))


def test_sigint_first_press_sets_break():
    original_sigint = signal.getsignal(signal.SIGINT)
    agent = _DummyAgent()
    pdb = VerifyPDB(agent)
    try:
        pdb._sigint_handler(signal.SIGINT, None)
        assert agent.is_break() is True
        assert len(agent.echo_msgs) == 1
        assert "SIGINT received. Stopping execution" in agent.echo_msgs[0][0]
    finally:
        signal.signal(signal.SIGINT, original_sigint)


def test_sigint_second_press_exits_immediately():
    original_sigint = signal.getsignal(signal.SIGINT)
    agent = _DummyAgent()
    pdb = VerifyPDB(agent)
    try:
        pdb._sigint_handler(signal.SIGINT, None)
        with pytest.raises(KeyboardInterrupt):
            pdb._sigint_handler(signal.SIGINT, None)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
