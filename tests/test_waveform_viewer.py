#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ucagent.util.waveform_viewer import (
    WaveformViewerProtocolError,
    build_waveform_viewer_markdown_link,
    build_waveform_viewer_url,
    decode_waveform_viewer_token,
    encode_waveform_viewer_payload,
    normalize_waveform_viewer_payload,
    parse_waveform_viewer_markdown_link,
    resolve_latest_waveform_file,
)


def _payload():
    return {
        "v": 1,
        "file": "unity_test/tests/data/波形/test_bug.fst",
        "start": "10",
        "end": "184467440737095516170",
        "cursor": "9007199254740993",
        "signals": ["TOP.dut.时钟", "TOP.dut.valid", "TOP.dut.时钟"],
    }


def _raw_token(payload, *, compact=True):
    separators = (",", ":") if compact else None
    raw = json.dumps(payload, ensure_ascii=False, separators=separators).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_canonical_base64url_round_trip_is_deterministic_and_unpadded():
    token = encode_waveform_viewer_payload(_payload())

    assert "=" not in token
    assert token == encode_waveform_viewer_payload(dict(reversed(list(_payload().items()))))
    assert decode_waveform_viewer_token(token) == {
        "v": 1,
        "file": "unity_test/tests/data/波形/test_bug.fst",
        "start": "10",
        "end": "184467440737095516170",
        "cursor": "9007199254740993",
        "signals": ["TOP.dut.时钟", "TOP.dut.valid"],
    }


def test_file_only_dashboard_payload_is_supported():
    payload = {"v": 1, "file": "waves/test.vcd"}

    assert build_waveform_viewer_url(payload).startswith("/surfer/?wave=")
    assert decode_waveform_viewer_token(encode_waveform_viewer_payload(payload)) == payload


def test_logical_v2_payload_round_trip_does_not_contain_session_path():
    payload = {
        "v": 2,
        "test_dir": "unity_test/tests",
        "test_case": "test_bug[param-a]",
        "start": "10",
        "end": "184467440737095516170",
        "cursor": "9007199254740993",
        "signals": ["TOP.dut.时钟", "TOP.dut.valid"],
    }

    token = encode_waveform_viewer_payload(payload)

    assert decode_waveform_viewer_token(token) == payload
    assert "toffee_tmp_" not in token
    link = build_waveform_viewer_markdown_link(payload)
    assert link.startswith("<WAVEFORM-VIEWER> [test_bug(param-a)]")


def test_markdown_link_round_trip_uses_exact_canonical_line():
    link = build_waveform_viewer_markdown_link(_payload())
    token, decoded = parse_waveform_viewer_markdown_link(link)

    assert link == (
        f"<WAVEFORM-VIEWER> [test_bug.fst](/surfer/?wave={token})"
    )
    localized = link.replace("[test_bug.fst]", "[在线确认波形]")
    localized_token, localized_payload = parse_waveform_viewer_markdown_link(localized)
    assert localized_token == token
    assert localized_payload == decoded
    assert decoded["signals"] == ["TOP.dut.时钟", "TOP.dut.valid"]


@pytest.mark.parametrize(
    "file_name",
    [
        "/tmp/test.vcd",
        "../test.vcd",
        "waves/../test.vcd",
        "waves//test.vcd",
        "waves/./test.vcd",
        "C:/waves/test.vcd",
        "C:\\waves\\test.vcd",
        "https://example.test/test.vcd",
        "waves/test.vcd?download=1",
        "waves/test.fsdb",
    ],
)
def test_unsafe_or_unsupported_waveform_paths_are_rejected(file_name):
    with pytest.raises(WaveformViewerProtocolError):
        normalize_waveform_viewer_payload({"v": 1, "file": file_name})


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 2, "file": "waves/test.vcd"},
        {"v": 2, "test_dir": "tests"},
        {"v": 2, "test_dir": "tests", "test_case": "../test_bug"},
        {"v": 2, "test_dir": "../tests", "test_case": "test_bug"},
        {"v": 2, "test_dir": "/tests", "test_case": "test_bug"},
        {"v": True, "file": "waves/test.vcd"},
        {"v": 1, "file": "waves/test.vcd", "extra": True},
        {"v": 1, "file": "waves/test.vcd", "start": "0"},
        {
            "v": 1,
            "file": "waves/test.vcd",
            "start": "0",
            "end": "2",
            "cursor": "3",
            "signals": ["TOP.clk"],
        },
        {
            "v": 1,
            "file": "waves/test.vcd",
            "start": "00",
            "end": "2",
            "cursor": "1",
            "signals": ["TOP.clk"],
        },
        {
            "v": 1,
            "file": "waves/test.vcd",
            "start": "0",
            "end": "2",
            "cursor": "1",
            "signals": [],
        },
        {
            "v": 1,
            "file": "waves/test.vcd",
            "start": "0",
            "end": "2",
            "cursor": "1",
            "signals": [f"TOP.signal_{index}" for index in range(65)],
        },
    ],
)
def test_invalid_payloads_are_rejected(payload):
    with pytest.raises(WaveformViewerProtocolError):
        normalize_waveform_viewer_payload(payload)


@pytest.mark.parametrize(
    "token",
    [
        "%%%",
        "e30=",
        _raw_token({"v": 1, "file": "waves/test.vcd"}, compact=False),
        _raw_token({"v": 99, "file": "waves/test.vcd"}),
        base64.urlsafe_b64encode(b"not-json").decode("ascii").rstrip("="),
    ],
)
def test_invalid_or_noncanonical_tokens_are_rejected(token):
    with pytest.raises(WaveformViewerProtocolError):
        decode_waveform_viewer_token(token)


def test_duplicate_signals_are_deduplicated_before_limit_validation():
    payload = {
        "v": 1,
        "file": "waves/test.vcd",
        "start": "0",
        "end": "1",
        "cursor": "1",
        "signals": ["TOP.clk"] * 100,
    }

    assert normalize_waveform_viewer_payload(payload)["signals"] == ["TOP.clk"]


def _waveform(session: Path, name: str, content: bytes = b"wave") -> Path:
    path = session / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_latest_waveform_resolution_uses_newest_session_containing_test(tmp_path):
    data_dir = tmp_path / "unity_test" / "tests" / "data"
    old_session = data_dir / "toffee_tmp_20260817120000_001"
    newer_target_session = data_dir / "toffee_tmp_20260817130000_001"
    newest_other_session = data_dir / "toffee_tmp_20260817140000_001"
    _waveform(old_session, "test_bug.fst", b"old")
    expected = _waveform(newer_target_session, "gw0/test_bug010.fst", b"new")
    _waveform(newest_other_session, "test_other.fst", b"other")

    selected = resolve_latest_waveform_file(
        tmp_path,
        "unity_test/tests",
        "test_bug",
    )

    assert selected == expected.resolve()


def test_latest_waveform_resolution_prefers_fst_then_numeric_suffix(tmp_path):
    session = (
        tmp_path
        / "unity_test"
        / "tests"
        / "data"
        / "toffee_tmp_20260817140000_123"
    )
    _waveform(session, "test_bug999.vcd")
    _waveform(session, "gw0/test_bug001.fst")
    expected = _waveform(session, "gw1/test_bug010.fst")

    assert resolve_latest_waveform_file(
        tmp_path,
        "unity_test/tests",
        "test_bug",
    ) == expected.resolve()


def test_latest_waveform_resolution_returns_none_when_test_is_absent(tmp_path):
    session = (
        tmp_path
        / "unity_test"
        / "tests"
        / "data"
        / "toffee_tmp_20260817140000_123"
    )
    _waveform(session, "test_other.fst")

    assert resolve_latest_waveform_file(
        tmp_path,
        "unity_test/tests",
        "test_bug",
    ) is None
