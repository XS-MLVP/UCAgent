#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for command-line backend process interruption."""

import os
import shlex
import sys
import threading
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.abackend.cmdline import UCAgentCmdLineBackend


class _FakeAgent:
    def __init__(self) -> None:
        self._break = False
        self.messages = []

    def message_echo(self, txt: str) -> None:
        self.messages.append(txt)

    def is_break(self) -> bool:
        return self._break

    def set_break(self, value=True) -> None:
        self._break = value


def test_process_bash_cmd_interrupts_silent_process():
    agent = _FakeAgent()
    backend = UCAgentCmdLineBackend(agent, config=object(), cli_cmd_ctx="")
    backend.CWD = current_dir

    cmd = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'"

    def trigger_break() -> None:
        time.sleep(0.2)
        agent.set_break(True)

    breaker = threading.Thread(target=trigger_break)
    breaker.start()

    start = time.time()
    return_code, output_lines = backend.process_bash_cmd(cmd)
    elapsed = time.time() - start

    breaker.join(timeout=1)

    assert elapsed < 5
    assert return_code is not None
    assert return_code != 0
    assert output_lines == []
    assert backend._fail_count == 0
