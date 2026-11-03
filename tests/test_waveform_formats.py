"""Backend-independent reader contracts, adapters, and optional extension output."""

from contextlib import AbstractContextManager
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from ucagent.tools import WaveInfo
from ucagent.tools.uctool import to_mcp_tool
from ucagent.util.waveform_formats import (
    open_waveform_reader, paginate_signal_matches, register_waveform_reader,
)
from ucagent.util.waveform_formats import registry


class _RecordedReader(AbstractContextManager):
    """Read explicit digital transitions from a JSON test fixture without wavekit."""

    backend_name = "recorded"

    def configure_backend(self, backend_args):
        """Support the canonical no-option and help requests."""
        if backend_args == "help":
            return {"options": {}}
        assert backend_args == {}
        return {}

    def __init__(self, path, extensions, query_extensions, calls):
        """Load independent fixture data and retain lifecycle observations."""
        self.payload = json.loads(Path(path).read_text())
        self.begin_time = 0
        self.end_time = 40
        self.top_scopes = [SimpleNamespace(full_name="TOP")]
        self.signals = {
            name: SimpleNamespace(full_name=name, base_name=name.split(".")[-1], width=len(rows[0][1]))
            for name, rows in self.payload.items()
        }
        self.extensions = extensions
        self.query_extensions = query_extensions
        self.calls = calls

    def __enter__(self):
        """Observe opening without importing a waveform library."""
        self.calls.append("opened")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Observe cleanup on successful and failed analysis."""
        self.calls.append("closed")
        return False

    def get_matched_signals(self, path, *, offset=0, limit=100):
        """Implement exact and catalog queries used by these focused tests."""
        if path == "**":
            matches = self.signals
        else:
            matches = {
                name: signal for name, signal in self.signals.items()
                if name == path or (path.endswith(".**") and name.startswith(path[:-2]))
            }
        result = paginate_signal_matches(matches, offset=offset, limit=limit)
        if path in self.query_extensions:
            result["extensions"] = deepcopy(self.query_extensions[path])
        return result

    def load_value_changes(self, signal, value_mapping, begin_time=None, end_time=None):
        """Map source bits and retain the previous state for a bounded window."""
        rows = self.payload[signal.full_name]
        before = [row for row in rows if begin_time is not None and row[0] <= begin_time]
        selected = (before[-1:] if before else []) + [
            row for row in rows if begin_time is None or row[0] > begin_time
        ]
        result = {
            "mapped": [
                (timestamp, sum(value_mapping[bit] << index for index, bit in enumerate(reversed(bits))))
                for timestamp, bits in selected if end_time is None or timestamp < end_time
            ],
        }
        if self.extensions != {}:
            result["extensions"] = deepcopy(self.extensions)
            if isinstance(result["extensions"], dict):
                result["extensions"]["mapping"] = dict(value_mapping)
        return result


@pytest.fixture
def recorded_waveform(tmp_path, monkeypatch):
    """Register a separate-library reader with configurable extension payloads."""
    monkeypatch.setattr(registry, "_READERS", dict(registry._READERS))
    target = tmp_path / "tests/data/toffee_tmp_20261030120000_001/master/test_recorded.recorded"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "TOP.clk": [[0, "0"], [5, "1"], [10, "0"], [15, "1"], [20, "0"], [25, "1"]],
        "TOP.data": [[0, "00"], [10, "01"], [20, "xz"], [30, "11"]],
        "TOP.valid": [[0, "0"], [10, "1"]],
    }))
    state = SimpleNamespace(extensions={}, query_extensions={}, calls=[], waveform=target)

    def factory(path):
        """Create the independent fixture reader only when analysis selects it."""
        return _RecordedReader(path, state.extensions, state.query_extensions, state.calls)

    register_waveform_reader("recorded", factory)
    tool = WaveInfo(workspace=str(tmp_path), test_dir="tests", format_priority=["recorded"])
    return tool, state


def test_import_and_config_validation_do_not_import_wavekit():
    """Package import and registration must work without the built-in backend."""
    script = """
import sys
sys.modules['wavekit'] = None
sys.modules['pywellen'] = None
from ucagent.util.waveform_formats import registered_waveform_formats
from ucagent.util.config import Config
assert registered_waveform_formats() == ('fst', 'vcd', 'fsdb')
"""
    subprocess.run([sys.executable, "-c", script], check=True, cwd=Path(__file__).parents[1])


@pytest.mark.parametrize("extension,reader_name", [("fst", "FstReader"), ("vcd", "VcdReader"), ("fsdb", "FsdbReader")])
@pytest.mark.parametrize("fail_analysis", [False, True])
def test_format_adapters_dispatch_map_and_close(monkeypatch, extension, reader_name, fail_analysis):
    """Every format wraps its own backend and closes it on all analysis exits."""
    calls = []
    descriptor = SimpleNamespace(full_name="TOP.data", base_name="data", width=130)
    begin = 2**65
    mapped = [(begin - 1, 2**129), (begin + 1, 2**129 + 1)]

    class Backend(AbstractContextManager):
        """Observe the adapter boundary without depending on a native runtime."""

        begin_time = begin
        end_time = begin + 100
        top_scopes = [SimpleNamespace(full_name="TOP")]

        def __init__(self, path):
            """Record exact-file dispatch."""
            calls.append(("opened", path))

        def __exit__(self, exc_type, exc_value, traceback):
            """Record cleanup and preserve exceptions."""
            calls.append(("closed", exc_type))
            return False

        def get_matched_signals(self, path):
            """Record the exact query forwarded by the adapter."""
            calls.append(("query", path))
            return {"backend_key": descriptor}

        def _load_value_changes(self, signal, value_mapping, begin_time=None, end_time=None):
            """Record all value-loading arguments and return full-precision rows."""
            calls.append(("load", signal, value_mapping, begin_time, end_time))
            return mapped

    monkeypatch.setitem(sys.modules, "wavekit", SimpleNamespace(**{reader_name: Backend}))
    mapping = {"0": 0, "1": 1, "x": 0, "z": 0}
    try:
        with open_waveform_reader(f"selected.{extension.upper()}", backend_priority={extension: ["wavekit"]}) as reader:
            assert type(reader).__module__ == f"ucagent.util.waveform_formats.read_{extension}"
            assert reader.begin_time == begin
            assert reader.end_time == begin + 100
            assert reader.top_scopes[0].full_name == "TOP"
            assert reader.get_matched_signals("TOP.data") == {
                "signals": {"backend_key": descriptor}, "total": 1, "offset": 0, "limit": 100,
            }
            assert reader.load_value_changes(descriptor, mapping, begin, begin + 2) == {"mapped": mapped}
            if fail_analysis:
                raise RuntimeError("analysis failed")
    except RuntimeError:
        assert fail_analysis
    assert calls == [
        ("opened", f"selected.{extension.upper()}"),
        ("query", "TOP.data"),
        ("load", descriptor, mapping, begin, begin + 2),
        ("closed", RuntimeError if fail_analysis else None),
    ]


def test_independent_backend_runs_without_wavekit_and_without_extensions(recorded_waveform, monkeypatch):
    """A registered reader can analyze X/Z states without any wavekit dependency."""
    tool, state = recorded_waveform
    monkeypatch.setitem(sys.modules, "wavekit", None)
    assert tool.analyze()["format_counts"] == {"recorded": 1}
    assert state.calls == []
    result = tool.analyze(
        test_case_name="test_recorded", pattern=[{"signal": "TOP.data", "event": "unknown"}],
        start_step=20, end_step=20, include_extensions=True,
    )
    assert result["success"] is True
    assert result["timeline"][20]["values"]["TOP.data"] == "2'bxz"
    assert result["waveform_info"]["step_basis"] == "waveform_simulation_timestamp"
    assert not any(key.startswith("extensions") for key in result)
    assert state.calls == ["opened", "closed"]


def test_extensions_are_advertised_then_returned_through_local_and_mcp_calls(recorded_waveform):
    """Default output reveals keys; opt-in returns each signal/mapping payload."""
    tool, state = recorded_waveform
    state.extensions = {"quality": {"source": "captured", "gaps": []}, "raw": ["xz"]}
    arguments = {
        "test_case_name": "test_recorded",
        "pattern": [{"signal": "TOP.data", "event": "unknown"}],
        "start_step": 0, "end_step": 40,
        "clock_signal": "TOP.clk",
    }
    default = tool.analyze(**arguments)
    expected_keys = {channel: ["mapping", "quality", "raw"] for channel in ("value", "x_mask", "z_mask")}
    assert default["extensions_available"] == {
        "value_changes": {"TOP.clk": expected_keys, "TOP.data": expected_keys},
    }
    assert "include_extensions=true" in default["extensions_hint"]
    assert "extensions" not in default
    assert "captured" not in json.dumps(default)

    result = yaml.safe_load(tool.invoke({**arguments, "include_extensions": True}))
    assert result["extensions_available"] == default["extensions_available"]
    assert "extensions_hint" not in result
    assert result["timeline"] == default["timeline"]
    for signal in ("TOP.clk", "TOP.data"):
        for channel, mapping in (
            ("value", {"0": 0, "1": 1, "x": 0, "z": 0}),
            ("x_mask", {"0": 0, "1": 0, "x": 1, "z": 0}),
            ("z_mask", {"0": 0, "1": 0, "x": 0, "z": 1}),
        ):
            assert result["extensions"]["value_changes"][signal][channel] == {**state.extensions, "mapping": mapping}
    receipt = tool.get_analysis_receipt(result["waveform_analysis_receipt"]["receipt_id"])
    assert receipt["arguments"]["include_extensions"] is True
    assert receipt["result"]["extensions"] == result["extensions"]
    assert tool.replay_analysis(**receipt["arguments"])["extensions"] == result["extensions"]
    reloaded = WaveInfo(workspace=tool.workspace, test_dir="tests", format_priority=["recorded"])
    assert reloaded.get_analysis_receipt(receipt["receipt_id"])["result"]["extensions"] == result["extensions"]
    changed = deepcopy(result)
    changed["extensions"]["value_changes"]["TOP.data"]["value"]["raw"] = ["00"]
    assert tool.analysis_semantic_fingerprint(receipt["arguments"], result) != tool.analysis_semantic_fingerprint(receipt["arguments"], changed)
    schema = to_mcp_tool(tool).parameters
    assert schema["properties"]["include_extensions"]["type"] == "boolean"
    assert schema["properties"]["include_extensions"]["default"] is False
    assert state.calls == ["opened", "closed"] * 3


def test_default_receipt_omits_extension_contents(recorded_waveform):
    """The disabled option must hide extension values in tool output and receipts."""
    tool, state = recorded_waveform
    state.extensions = {"raw": ["private-detailed-value"]}
    result = yaml.safe_load(tool.invoke({"test_case_name": "test_recorded", "pattern": [{"signal": "TOP.data"}]}))
    receipt = tool.get_analysis_receipt(result["waveform_analysis_receipt"]["receipt_id"])
    assert receipt["arguments"]["include_extensions"] is False
    assert "extensions" not in receipt["result"]
    assert receipt["result"]["extensions_available"] == result["extensions_available"]
    assert "private-detailed-value" not in json.dumps([result, receipt])


def test_metadata_without_value_loads_does_not_probe_extensions(recorded_waveform):
    """Metadata calls announce extensions only when a clock trace was loaded."""
    tool, state = recorded_waveform
    state.extensions = {"quality": "captured"}
    metadata = tool.analyze(test_case_name="test_recorded", include_extensions=True)
    assert metadata["success"] is True
    assert not any(key.startswith("extensions") for key in metadata)
    clock_metadata = tool.analyze(test_case_name="test_recorded", clock_signal="TOP.clk")
    assert set(clock_metadata["extensions_available"]["value_changes"]) == {"TOP.clk"}
    assert "include_extensions=true" in clock_metadata["extensions_hint"]


@pytest.mark.parametrize("changes", [{"mapped": []}, {"mapped": [], "extensions": {}}])
def test_empty_traces_and_empty_extensions(changes):
    """Empty source traces remain readable without manufacturing signal states."""
    reader = SimpleNamespace(load_value_changes=lambda *args, **kwargs: changes)
    signal = SimpleNamespace(full_name="TOP.empty", width=1)
    trace = WaveInfo._load_trace(reader, signal, 10, 20)
    assert trace.states == []
    assert trace.value_at(10) is None
    assert trace.extensions == {}


@pytest.mark.parametrize("extensions", [None, [], {1: "invalid key"}, {"nested": {1: "invalid key", "name": "mixed keys"}}, {"nested": ("tuple",)}, {"native": object()}, {"invalid": float("nan")}])
def test_invalid_extensions_fail_with_cleanup_and_operator_diagnostics(recorded_waveform, monkeypatch, extensions):
    """Malformed backend output fails safely even when extension display is off."""
    from ucagent.tools import waveform

    tool, state = recorded_waveform
    state.extensions = extensions
    messages = []
    monkeypatch.setattr(waveform, "log_msg", messages.append)
    result = tool.analyze(test_case_name="test_recorded", pattern=[{"signal": "TOP.data"}])
    assert result["status"] == "waveform_parse_error"
    assert result["success"] is False
    assert "operator" in str(result["suggestions"])
    assert messages
    assert state.calls == ["opened", "closed"]


def test_unknown_extension_fails_without_guessing_a_reader():
    """Unregistered extensions must not be sent to a different backend."""
    with pytest.raises(ValueError, match="No waveform reader is registered"):
        open_waveform_reader("test.not_registered")


@pytest.mark.parametrize("changes", [None, [], {"extensions": {}}])
def test_value_change_results_require_mapped_rows(recorded_waveform, monkeypatch, changes):
    """Invalid result shapes must fail instead of being guessed or normalized."""
    tool, state = recorded_waveform

    def invalid_result(*args, **kwargs):
        """Return a malformed response at the public backend boundary."""
        return changes

    monkeypatch.setattr(_RecordedReader, "load_value_changes", invalid_result)
    result = tool.analyze(test_case_name="test_recorded", pattern=[{"signal": "TOP.data"}])
    assert result["status"] == "waveform_parse_error"
    assert state.calls == ["opened", "closed"]


@pytest.mark.parametrize("include_extensions", [False, True])
def test_query_extensions_are_available_without_loading_traces(recorded_waveform, monkeypatch, include_extensions):
    """Catalog metadata can expose query information through the same display option."""
    tool, state = recorded_waveform
    state.query_extensions["**"] = {
        "hierarchy": {"TOP.data": {"parent_scope": "TOP"}},
        "related_signals": {"TOP.data": ["TOP.clk", "TOP.valid"]},
    }

    def forbid_trace_load(*args, **kwargs):
        """Metadata lookup must not load values just to obtain query extensions."""
        pytest.fail("query extension lookup loaded a trace")

    monkeypatch.setattr(_RecordedReader, "load_value_changes", forbid_trace_load)
    result = yaml.safe_load(tool.invoke({
        "test_case_name": "test_recorded", "include_extensions": include_extensions,
    }))
    assert result["status"] == "metadata_only"
    assert result["extensions_available"] == {
        "signal_queries": {"**": ["hierarchy", "related_signals"]},
    }
    receipt = tool.get_analysis_receipt(result["waveform_analysis_receipt"]["receipt_id"])
    assert receipt["result"]["extensions_available"] == result["extensions_available"]
    if include_extensions:
        assert result["extensions"] == {"signal_queries": state.query_extensions}
        assert receipt["result"]["extensions"] == result["extensions"]
        assert tool.replay_analysis(**receipt["arguments"])["extensions"] == result["extensions"]
        reloaded = WaveInfo(workspace=tool.workspace, test_dir="tests", format_priority=["recorded"])
        assert reloaded.get_analysis_receipt(receipt["receipt_id"])["result"]["extensions"] == result["extensions"]
        changed = deepcopy(result)
        changed["extensions"]["signal_queries"]["**"]["hierarchy"]["TOP.data"]["parent_scope"] = "OTHER"
        assert tool.analysis_semantic_fingerprint(receipt["arguments"], result) != tool.analysis_semantic_fingerprint(receipt["arguments"], changed)
        assert "extensions_hint" not in result
    else:
        assert "extensions" not in result
        assert "extensions" not in receipt["result"]
        assert "parent_scope" not in json.dumps([result, receipt])
        assert "include_extensions=true" in result["extensions_hint"]


@pytest.mark.parametrize("include_extensions", [False, True])
def test_query_extensions_keep_catalog_clock_pattern_and_context_scopes(recorded_waveform, include_extensions):
    """Query and value metadata coexist without treating related signals as matches."""
    tool, state = recorded_waveform
    state.query_extensions.update({
        "**": {"hierarchy": {"TOP": {"kind": "module"}}},
        "TOP.clk": {"related_signals": ["TOP.valid"]},
        "TOP.data": {"quality": {"kind": "signal"}},
        "TOP.valid": {"related_signals": ["TOP.undumped"]},
    })
    state.extensions = {"quality": {"kind": "trace"}}
    result = tool.analyze(
        test_case_name="test_recorded", clock_signal="TOP.clk",
        pattern=[{"signal": "TOP.data", "event": "unknown"}],
        signal_groups={
            "clock_mode": "clocked", "clocks": ["TOP.clk"], "inputs": ["TOP.valid"],
            "outputs": ["TOP.data"], "key_signals": ["TOP.data"],
        },
        start_step=0, end_step=40, include_extensions=include_extensions,
    )
    assert result["success"] is True
    assert result["extensions_available"]["signal_queries"] == {
        path: sorted(extra) for path, extra in state.query_extensions.items()
    }
    assert set(result["extensions_available"]["value_changes"]) == {"TOP.clk", "TOP.data", "TOP.valid"}
    assert set(result["signals"]) == {"TOP.clk", "TOP.data", "TOP.valid"}
    if include_extensions:
        assert result["extensions"]["signal_queries"] == state.query_extensions
        assert result["extensions"]["signal_queries"]["TOP.data"]["quality"] == {"kind": "signal"}
        assert result["extensions"]["value_changes"]["TOP.data"]["value"]["quality"] == {"kind": "trace"}
    else:
        assert "extensions" not in result
        assert "undumped" not in json.dumps(result)
        assert "include_extensions=true" in result["extensions_hint"]


def test_empty_query_extensions_do_not_add_output_fields(recorded_waveform):
    """Explicit empty query dictionaries behave like omitted extensions."""
    tool, state = recorded_waveform
    state.query_extensions["**"] = {}
    for include in (False, True):
        result = tool.analyze(test_case_name="test_recorded", include_extensions=include)
        assert result["success"] is True
        assert not any(key.startswith("extensions") for key in result)


def test_unmatched_query_preserves_related_candidate_extensions(recorded_waveform):
    """An empty match set can carry useful metadata without inventing signals."""
    tool, state = recorded_waveform
    state.query_extensions["TOP.missing"] = {"related_signals": ["TOP.data"]}
    result = tool.analyze(
        test_case_name="test_recorded", pattern=[{"signal": "TOP.missing"}], include_extensions=True,
    )
    assert result["status"] == "signal_not_found"
    assert result["extensions"] == {"signal_queries": state.query_extensions}
    assert result["details"]["pattern"]["signal"] == "TOP.missing"


@pytest.mark.parametrize("extensions", [None, [], {1: "invalid key"}, {"nested": {1: "invalid key", "name": "mixed keys"}}, {"nested": ("tuple",)}, {"native": object()}, {"invalid": float("nan")}])
def test_invalid_query_extensions_fail_with_cleanup(recorded_waveform, monkeypatch, extensions):
    """Query extension payloads obey the same dictionary and JSON checks as traces."""
    from ucagent.tools import waveform

    tool, state = recorded_waveform
    state.query_extensions["**"] = extensions
    messages = []
    monkeypatch.setattr(waveform, "log_msg", messages.append)
    result = tool.analyze(test_case_name="test_recorded")
    assert result["status"] == "waveform_parse_error"
    assert "operator" in str(result["suggestions"])
    assert messages
    assert state.calls == ["opened", "closed"]


@pytest.mark.parametrize("matches", [None, [], {}, {"signals": []}])
def test_query_results_require_a_signals_mapping(recorded_waveform, monkeypatch, matches):
    """Malformed match results fail without interpreting them as a different schema."""
    tool, state = recorded_waveform

    def invalid_matches(*args, **kwargs):
        """Return the malformed result at the public query boundary."""
        return matches

    monkeypatch.setattr(_RecordedReader, "get_matched_signals", invalid_matches)
    result = tool.analyze(test_case_name="test_recorded")
    assert result["status"] == "waveform_parse_error"
    assert state.calls == ["opened", "closed"]


def test_query_extensions_snapshot_reused_backend_buffers(recorded_waveform, monkeypatch):
    """Later queries must not overwrite the metadata captured for earlier queries."""
    tool, state = recorded_waveform
    shared = {"context": {"path": ""}}

    def shared_result(reader, path, *, offset=0, limit=100):
        """Return one mutable extension buffer reused by every backend query."""
        shared["context"]["path"] = path
        matches = reader.signals if path == "**" else {path: reader.signals[path]}
        result = paginate_signal_matches(matches, offset=offset, limit=limit)
        result["extensions"] = shared
        return result

    monkeypatch.setattr(_RecordedReader, "get_matched_signals", shared_result)
    result = tool.analyze(
        test_case_name="test_recorded", pattern=[{"signal": "TOP.data"}], include_extensions=True,
    )
    assert result["extensions"]["signal_queries"] == {
        "**": {"context": {"path": "**"}}, "TOP.data": {"context": {"path": "TOP.data"}},
    }
    assert state.calls == ["opened", "closed"]


@pytest.fixture
def large_recorded_waveform(recorded_waveform):
    """Supply enough independently readable signals for multiple catalog pages."""
    tool, state = recorded_waveform
    state.waveform.write_text(json.dumps({
        f"TOP.bank{bank}.data{index:04}": [[0, "0"], [10, "1"]]
        for bank, count in ((0, 250), (1, 70)) for index in reversed(range(count))
    }))
    return tool, state


@pytest.mark.parametrize("offset,shown", [(0, 100), (100, 100), (200, 50), (250, 0), (500, 0)])
def test_reader_pages_are_sorted_and_preserve_backend_keys(offset, shown):
    """Paging preserves descriptor identity and the real total at all boundaries."""
    signals = {
        index: SimpleNamespace(full_name=f"TOP.s{index:04}")
        for index in reversed(range(250))
    }
    page = paginate_signal_matches(signals, offset=offset)
    assert (page["total"], page["offset"], page["limit"]) == (250, offset, 100)
    assert list(page["signals"]) == list(range(offset, min(250, offset + 100)))
    assert len(page["signals"]) == shown
    for key, signal in page["signals"].items():
        assert signal is signals[key]


@pytest.mark.parametrize("kwargs", [
    {"offset": -1}, {"offset": True}, {"offset": "0"},
    {"limit": 0}, {"limit": 1001}, {"limit": True}, {"limit": 1.5},
])
def test_reader_rejects_invalid_page_bounds(kwargs):
    """Invalid bounds must not become negative slices or unbounded queries."""
    with pytest.raises(ValueError, match="signal (offset|limit)"):
        paginate_signal_matches({}, **kwargs)


def test_default_catalog_pages_cover_all_signals_without_duplicates(large_recorded_waveform):
    """The default [0, 100) page supplies counts and a complete next-page call."""
    tool, state = large_recorded_waveform
    arguments = {"test_case_name": "test_recorded"}
    names = []
    for offset, shown in ((0, 100), (100, 100), (200, 100), (300, 20)):
        result = yaml.safe_load(tool.invoke(arguments))
        catalog = result["signal_catalog"]
        assert result["success"] is True
        assert catalog["query"] == "**"
        assert catalog["total"] == result["waveform_info"]["signal_count"] == 320
        assert catalog["offset"] == offset
        assert catalog["limit"] == 100
        assert catalog["shown"] == len(catalog["signals"]) == shown
        assert catalog["end_offset"] == offset + shown
        assert catalog["remaining"] == 320 - offset - shown
        names.extend(catalog["signals"])
        receipt = tool.get_analysis_receipt(result["waveform_analysis_receipt"]["receipt_id"])
        assert receipt["result"]["signal_catalog"] == catalog
        assert receipt["arguments"]["signal_offset"] == offset
        if catalog["has_more"]:
            arguments = catalog["next_call"]
            assert arguments["signal_offset"] == offset + shown
            assert "next_call" in result["next_action"]
        else:
            assert catalog["next_offset"] is None
            assert "next_call" not in catalog
    assert names == sorted(json.loads(state.waveform.read_text()))
    assert len(set(names)) == 320


def test_catalog_filter_offset_empty_and_out_of_range_pages(large_recorded_waveform):
    """Filtering and nondefault page bounds are echoed with correct recovery actions."""
    tool, _ = large_recorded_waveform
    result = tool.analyze(
        test_case_name="test_recorded", signal_query="TOP.bank1.**", signal_offset=10, signal_limit=25,
    )
    catalog = result["signal_catalog"]
    assert (catalog["total"], catalog["shown"], catalog["remaining"]) == (70, 25, 35)
    assert list(catalog["signals"])[0] == "TOP.bank1.data0010"
    assert list(catalog["signals"])[-1] == "TOP.bank1.data0034"
    assert catalog["next_call"]["signal_query"] == "TOP.bank1.**"
    assert catalog["next_call"]["signal_offset"] == 35
    assert tool.analyze(**catalog["next_call"])["signal_catalog"]["offset"] == 35
    assert result["waveform_info"]["signal_count"] == 320
    empty = tool.analyze(test_case_name="test_recorded", signal_query="TOP.missing")
    assert empty["signal_catalog"]["total"] == 0
    assert empty["signal_catalog"]["signals"] == {}
    assert "Broaden signal_query" in empty["next_action"]
    past_end = tool.analyze(test_case_name="test_recorded", signal_offset=500)
    assert past_end["signal_catalog"]["signals"] == {}
    assert past_end["signal_catalog"]["total"] == 320
    assert past_end["signal_catalog"]["next_call"]["signal_offset"] == 0


def test_analysis_queries_use_full_match_counts_and_find_signals_beyond_catalog_page(large_recorded_waveform):
    """Catalog paging cannot turn a broad event query into a passing partial analysis."""
    tool, _ = large_recorded_waveform
    over_limit = tool.analyze(test_case_name="test_recorded", pattern=[{"signal": "TOP.bank0.**"}])
    assert over_limit["status"] == "signal_limit_exceeded"
    assert over_limit["details"]["matched_signal_count"] == 250
    assert len(over_limit["details"]["first_matches"]) == 33
    assert "TOP.bank0.data0249" not in json.dumps(over_limit)
    catalog = tool.analyze(**over_limit["details"]["catalog_call"])["signal_catalog"]
    assert catalog["total"] == 250
    assert catalog["shown"] == 100
    assert catalog["remaining"] == 150
    exact = tool.analyze(
        test_case_name="test_recorded", pattern=[{"signal": "TOP.bank1.data0069", "event": "rising"}],
        start_step=0, end_step=40,
    )
    assert exact["success"] is True
    assert exact["timeline"][10]["values"] == {"TOP.bank1.data0069": "1'b1"}
    assert exact["waveform_info"]["signal_count"] == 320


def test_ambiguous_clock_diagnostic_is_bounded(large_recorded_waveform):
    """A broad clock query reports its actual size with only one preview page."""
    tool, _ = large_recorded_waveform
    result = tool.analyze(test_case_name="test_recorded", clock_signal="**")
    assert result["status"] == "clock_signal_not_unique"
    assert result["details"]["matched_clock_signal_count"] == 320
    assert len(result["details"]["matched_clock_signals"]) == 100
    assert result["details"]["matched_clock_signals_truncated"] is True
    assert result["signal_query_summary"]["**"]["remaining"] == 220


def test_query_extensions_follow_the_selected_page(large_recorded_waveform, monkeypatch):
    """Paging query extensions keeps omitted-signal details out of the response."""
    tool, _ = large_recorded_waveform
    original = _RecordedReader.get_matched_signals

    def paged_hierarchy(reader, path, *, offset=0, limit=100):
        """Build hierarchy details only for descriptors returned on this page."""
        result = original(reader, path, offset=offset, limit=limit)
        result["extensions"] = {"hierarchy": {
            signal.full_name: {"parent_scope": signal.full_name.rsplit(".", 1)[0]}
            for signal in result["signals"].values()
        }}
        return result

    monkeypatch.setattr(_RecordedReader, "get_matched_signals", paged_hierarchy)
    first = tool.analyze(test_case_name="test_recorded", include_extensions=True)
    assert len(first["extensions"]["signal_queries"]["**"]["hierarchy"]) == 100
    assert "TOP.bank0.data0100" not in json.dumps(first)
    second = tool.analyze(**first["signal_catalog"]["next_call"])
    assert set(second["extensions"]["signal_queries"]["**"]["hierarchy"]) == set(second["signal_catalog"]["signals"])
    assert len(second["signal_catalog"]["signals"]) == 100
    assert "TOP.bank0.data0000" not in json.dumps(second)
    filtered = tool.analyze(
        test_case_name="test_recorded", signal_query="TOP.bank1.**", signal_limit=10,
        include_extensions=True,
    )
    assert set(filtered["extensions"]["signal_queries"]) == {"TOP.bank1.**"}
    assert len(filtered["extensions"]["signal_queries"]["TOP.bank1.**"]["hierarchy"]) == 10


@pytest.mark.parametrize("kwargs", [
    {"signal_limit": 0}, {"signal_limit": 1001}, {"signal_limit": True},
    {"signal_offset": -1}, {"signal_offset": 1.5}, {"signal_offset": True},
    {"signal_query": " "},
    {"signal_offset": 1, "pattern": [{"signal": "TOP.data"}]},
    {"signal_query": "TOP.data", "pattern": [{"signal": "TOP.data"}]},
    {"signal_limit": 10, "pattern": [{"signal": "TOP.data"}]},
])
def test_tool_catalog_options_are_validated_in_local_and_mcp_paths(recorded_waveform, kwargs):
    """Invalid bounds and mixed catalog/event modes fail before opening a reader."""
    tool, state = recorded_waveform
    assert tool.analyze(test_case_name="test_recorded", **kwargs)["status"] == "invalid_arguments"
    assert yaml.safe_load(tool._run(test_case_name="test_recorded", **kwargs))["status"] == "invalid_arguments"
    assert state.calls == []


def test_signal_catalog_requires_a_target_test(recorded_waveform):
    """Nondefault signal options must not be silently ignored in file inventory mode."""
    tool, state = recorded_waveform
    for kwargs in ({"signal_query": "TOP.data"}, {"signal_offset": 1}, {"signal_limit": 10}):
        assert tool.analyze(**kwargs)["status"] == "invalid_arguments"
        assert yaml.safe_load(tool._run(**kwargs))["status"] == "invalid_arguments"
    assert state.calls == []


@pytest.mark.parametrize("field,value", [
    ("total", 321), ("total", True), ("offset", 1), ("limit", 99),
])
def test_inconsistent_reader_page_metadata_is_rejected(recorded_waveform, monkeypatch, field, value):
    """A backend must not hide missing matches behind an inaccurate page summary."""
    tool, state = recorded_waveform
    original = _RecordedReader.get_matched_signals

    def inconsistent_page(reader, path, *, offset=0, limit=100):
        """Corrupt one canonical pagination field on an otherwise valid result."""
        result = original(reader, path, offset=offset, limit=limit)
        result[field] = value
        return result

    monkeypatch.setattr(_RecordedReader, "get_matched_signals", inconsistent_page)
    result = tool.analyze(test_case_name="test_recorded")
    assert result["status"] == "waveform_parse_error"
    assert state.calls == ["opened", "closed"]


def test_actual_wavekit_reader_returns_bounded_nonoverlapping_pages(tmp_path):
    """Exercise full mapping adaptation and paging through the real VCD backend."""
    path = tmp_path / "many.vcd"
    path.write_text(
        "$timescale 1ns $end\n$scope module TOP $end\n"
        + "".join(f"$var wire 1 id{index:04} s{index:04} $end\n" for index in reversed(range(250)))
        + "$upscope $end\n$enddefinitions $end\n#0\n"
        + "".join(f"0id{index:04}\n" for index in range(250))
        + "#10\n1id0000\n"
    )
    with open_waveform_reader(path, backend_priority={"vcd": ["wavekit"]}) as reader:
        first = reader.get_matched_signals("**")
        middle = reader.get_matched_signals("**", offset=100)
        last = reader.get_matched_signals("**", offset=200)
        assert [len(page["signals"]) for page in (first, middle, last)] == [100, 100, 50]
        assert all(page["total"] == 250 for page in (first, middle, last))
        names = [signal.full_name for page in (first, middle, last) for signal in page["signals"].values()]
        assert names == [f"TOP.s{index:04}" for index in range(250)]
        signal = next(iter(first["signals"].values()))
        rows = reader.load_value_changes(signal, {"0": 0, "1": 1, "x": 0, "z": 0})["mapped"]
        assert [tuple(map(int, row)) for row in rows] == [(0, 0), (10, 1)]


def test_top_scope_names_are_bounded_with_total_and_remaining(recorded_waveform, monkeypatch):
    """A large number of roots cannot bypass the signal-output bound."""
    tool, _ = recorded_waveform
    original = _RecordedReader.__enter__

    def many_scopes(reader):
        """Expose a valid large top-scope sequence for the metadata query."""
        reader.top_scopes = [SimpleNamespace(full_name=f"ROOT{index:04}") for index in range(250)]
        return original(reader)

    monkeypatch.setattr(_RecordedReader, "__enter__", many_scopes)
    info = tool.analyze(test_case_name="test_recorded")["waveform_info"]
    assert len(info["top_scopes"]) == 100
    assert info["top_scope_count"] == 250
    assert info["top_scopes_remaining"] == 150
    assert info["top_scopes_truncated"] is True
