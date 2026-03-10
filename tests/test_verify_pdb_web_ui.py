#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import signal

from ucagent.verify_pdb import VerifyPDB


class _DummyAgent:
    def __init__(self):
        self._break = False

    def set_break(self, value=True):
        self._break = value

    def is_break(self):
        return self._break

    def message_echo(self, msg, end="\n"):
        pass


def test_web_ui_start_invokes_cli_serve(monkeypatch):
    import ucagent.cli as cli

    original_sigint = signal.getsignal(signal.SIGINT)
    called = {"serve": False}

    def _fake_serve(argv=None):
        called["serve"] = True

    monkeypatch.setattr(cli, "_serve_web_ui", _fake_serve)
    pdb = VerifyPDB(_DummyAgent())
    try:
        pdb.do_web_ui_start("")
        assert called["serve"] is True
    finally:
        signal.signal(signal.SIGINT, original_sigint)


def test_web_ui_start_with_args_is_rejected(monkeypatch):
    import ucagent.cli as cli

    original_sigint = signal.getsignal(signal.SIGINT)
    called = {"serve": False}

    def _fake_serve(argv=None):
        called["serve"] = True

    monkeypatch.setattr(cli, "_serve_web_ui", _fake_serve)
    pdb = VerifyPDB(_DummyAgent())
    try:
        pdb.do_web_ui_start("127.0.0.1 9000")
        assert called["serve"] is False
    finally:
        signal.signal(signal.SIGINT, original_sigint)


def test_web_ui_start_handles_runtime_error(monkeypatch):
    import ucagent.cli as cli

    original_sigint = signal.getsignal(signal.SIGINT)

    def _boom(argv=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_serve_web_ui", _boom)
    pdb = VerifyPDB(_DummyAgent())
    try:
        pdb.do_web_ui_start("")
    finally:
        signal.signal(signal.SIGINT, original_sigint)


def test_web_ui_start_restores_sigint_handler_after_interrupt(monkeypatch):
    import ucagent.cli as cli

    original_sigint = signal.getsignal(signal.SIGINT)

    def _raise_interrupt(argv=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_serve_web_ui", _raise_interrupt)
    pdb = VerifyPDB(_DummyAgent())
    try:
        handler_before = signal.getsignal(signal.SIGINT)
        pdb.do_web_ui_start("")
        handler_after = signal.getsignal(signal.SIGINT)
        assert handler_after == handler_before
    finally:
        signal.signal(signal.SIGINT, original_sigint)
