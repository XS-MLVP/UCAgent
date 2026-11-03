"""Named backend selection, pywellen decoding, and advanced-option contracts."""

from contextlib import AbstractContextManager
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import pytest
import yaml

from ucagent.tools import WaveInfo
from ucagent.tools.waveform import ArgWaveInfo, WaveInfoAnalysisArgs
from ucagent.tools.uctool import to_mcp_tool
from ucagent.util.config import Config, load_runtime_config, load_yaml_with_env_vars, save_runtime_config
from ucagent.util.waveform_formats import (
    DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY,
    open_waveform_reader, register_waveform_reader, registered_waveform_backends,
    validate_waveform_analysis_backend_priority,
)
from ucagent.util.waveform_formats import registry
from ucagent.util.waveform_formats.read_fst import WellenFstReader, WavekitFstReader
from ucagent.util.waveform_formats.read_vcd import WellenVcdReader, WavekitVcdReader
from ucagent.util.waveform_formats.read_fsdb import WavekitFsdbReader
from test_waveform_tool import VCD_CONTENT, _session, _write_fst, _write_vcd


@pytest.fixture
def wave_tool(tmp_path):
    """Provide real digital fixtures selected through the default configuration."""
    pytest.importorskip('pywellen')
    test_dir = tmp_path / 'tests'
    session = _session(test_dir, 'toffee_tmp_20261030120000_001')
    _write_vcd(session, 'test_demo')
    return WaveInfo(workspace=str(tmp_path), test_dir=str(test_dir)), session


@pytest.mark.parametrize('extension,expected', [('vcd', WellenVcdReader), ('fst', WellenFstReader)])
def test_default_native_reader_names_and_value_mapping(wave_tool, monkeypatch, extension, expected):
    """Both formats use pywellen without importing wavekit, retaining four states."""
    tool, session = wave_tool
    path = _write_fst(session, 'test_native') if extension == 'fst' else _write_vcd(session, 'test_native')
    monkeypatch.setitem(sys.modules, 'wavekit', None)
    query = 'TOP.data[3:0]' if extension == 'fst' else 'TOP.dut.result[3:0]'
    timestamp = 30 if extension == 'fst' else 25
    with open_waveform_reader(path) as reader:
        assert type(reader) is expected
        assert reader.backend_name == 'pywellen'
        signal = next(iter(reader.get_matched_signals(query)['signals'].values()))
        for mapping, expected_value in [
            ({'0': 0, '1': 1, 'x': 0, 'z': 0}, 2),
            ({'0': 0, '1': 0, 'x': 1, 'z': 0}, 4),
            ({'0': 0, '1': 0, 'x': 0, 'z': 1}, 1),
        ]:
            assert reader.load_value_changes(signal, mapping, timestamp, timestamp + 1)['mapped'] == [(timestamp, expected_value)]
    result = tool.analyze(test_case_name='test_native', pattern=[{'signal': query, 'event': 'unknown'}], start_step=timestamp, end_step=timestamp)
    assert result['success'] is True
    assert result['timeline'][timestamp]['values'][query] == "4'b0x1z"


@pytest.mark.parametrize('extension,expected', [('vcd', WavekitVcdReader), ('fst', WavekitFstReader)])
def test_missing_pywellen_falls_back_to_same_file(wave_tool, monkeypatch, extension, expected):
    """Only an unavailable library falls through to the configured alternative."""
    _, session = wave_tool
    path = _write_fst(session, 'test_fallback') if extension == 'fst' else _write_vcd(session, 'test_fallback')
    monkeypatch.setitem(sys.modules, 'pywellen', None)
    with open_waveform_reader(path) as reader:
        assert type(reader) is expected
        assert reader.backend_name == 'wavekit'
        assert reader.get_matched_signals('**')['total'] > 0
    with pytest.raises(ImportError, match='pywellen'):
        with open_waveform_reader(path, backend_priority={extension: ['pywellen']}):
            pass


def test_explicit_order_and_no_advanced_fallback(wave_tool):
    """Operator order controls selection; unsupported options do not switch readers."""
    tool, session = wave_tool
    tool.backend_priority['vcd'] = ['wavekit', 'pywellen']
    result = tool.analyze(test_case_name='test_demo', backend_args='help')
    assert result['extensions']['backend']['options'] == {}
    invalid = tool.analyze(test_case_name='test_demo', backend_args={'statistics': True})
    assert invalid['status'] == 'invalid_backend_args'
    assert invalid['details']['help_call'] == {'test_case_name': 'test_demo', 'backend_args': 'help'}
    assert registered_waveform_backends('fsdb') == ('wavekit',)
    assert registry._READERS['fsdb']['wavekit'] is WavekitFsdbReader


@pytest.mark.parametrize('when,exception', [('construct', ImportError), ('enter', ImportError), ('construct', ValueError), ('enter', RuntimeError), ('body', ImportError)])
def test_fallback_scope_and_context_cleanup(monkeypatch, when, exception):
    """Constructor/entry dependency failure can retry; parsing and caller errors cannot."""
    monkeypatch.setattr(registry, '_READERS', deepcopy(registry._READERS))
    calls = []

    class Reader(AbstractContextManager):
        """Observe the entry/exit of one configured reader."""

        def __init__(self, name):
            """Retain the selected implementation name."""
            self.name = name

        def __enter__(self):
            """Simulate an optional dependency failure during entry."""
            calls.append(('enter', self.name))
            if self.name == 'first' and when == 'enter':
                raise exception('entry failed')
            return self

        def __exit__(self, exc_type, exc, traceback):
            """Record caller errors and propagate them."""
            calls.append(('exit', self.name, exc_type))
            return False

    def first(path):
        """Fail before entry when requested by the test."""
        calls.append(('construct', 'first'))
        if when == 'construct':
            raise exception('construction failed')
        return Reader('first')

    def second(path):
        """Record fallback construction and return a working context."""
        calls.append(('construct', 'second'))
        return Reader('second')

    register_waveform_reader('probe', first, backend='first')
    register_waveform_reader('probe', second, backend='second')
    if exception is ImportError and when != 'body':
        with open_waveform_reader('exact.probe', backend_priority={'probe': ['first', 'second']}) as reader:
            assert reader.name == 'second'
        assert calls[-1] == ('exit', 'second', None)
    else:
        with pytest.raises(exception):
            with open_waveform_reader('exact.probe', backend_priority={'probe': ['first', 'second']}):
                if when == 'body':
                    raise exception('analysis failed')
        assert ('construct', 'second') not in calls
        if when == 'body':
            assert calls[-1] == ('exit', 'first', ImportError)


@pytest.mark.parametrize('priority', [None, [], 'pywellen', {'vcd': []}, {'vcd': 'pywellen'}, {'vcd': ['pywellen', 'pywellen']}, {'.fst': ['pywellen']}, {'fst': [True]}])
def test_backend_order_validation(priority):
    """Malformed per-format order is rejected without treating it as default."""
    with pytest.raises(ValueError, match='waveform_analysis_backend_priority'):
        validate_waveform_analysis_backend_priority(priority)


def test_backend_configuration_snapshot_and_defaults(tmp_path):
    """Resolved lists override one format and are persisted/revalidated in snapshots."""
    root = Path(__file__).parents[1]
    settings = load_yaml_with_env_vars(str(root / 'ucagent/setting.yaml'))
    assert settings['runtime_options']['waveform_analysis_backend_priority'] == DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY
    cfg = Config({'runtime_options': {'need_ref_model': False, 'mock_components_enabled': False, 'waveform_analysis_backend_priority': {'vcd': ['wavekit']}}, 'tools': {'RunTestCases': {'test_dir': 'tests'}}})
    cfg._temp_cfg = {'DUT': 'Demo', 'OUT': 'out'}
    path = save_runtime_config(str(tmp_path), cfg)
    result = load_runtime_config(str(tmp_path))['runtime_options']['waveform_analysis_backend_priority']
    assert result == {**DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY, 'vcd': ['wavekit']}
    snapshot = json.loads(path.read_text())
    snapshot['runtime_options']['waveform_analysis_backend_priority']['vcd'] = []
    path.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match='waveform_analysis_backend_priority'):
        load_runtime_config(str(tmp_path))
    with pytest.raises(ValueError, match='No waveform reader'):
        WaveInfo(backend_priority={'vcd': ['unknown']})


def test_help_is_visible_without_loading_signal_values(wave_tool, monkeypatch):
    """Explicit help returns bounded usage directly, even with hidden extensions."""
    tool, _ = wave_tool

    def forbidden(*args, **kwargs):
        """Fail if help loads traces or runs ordinary analysis."""
        pytest.fail('help loaded traces or ran ordinary analysis')

    monkeypatch.setattr(WaveInfo, '_analyze', forbidden)
    result = yaml.safe_load(tool.invoke({'test_case_name': 'test_demo', 'backend_args': 'help'}))
    assert result['status'] == 'advanced_help'
    assert result['evidence_usable'] is False
    assert result['extensions']['backend']['options']['statistics']['type'] == 'boolean'
    assert 'extensions_hint' not in result
    receipt = tool.get_analysis_receipt(result['waveform_analysis_receipt']['receipt_id'])
    assert receipt['arguments']['backend_args'] == 'help'
    schema = to_mcp_tool(tool).parameters['properties']['backend_args']
    assert {part.get('type') for part in schema['anyOf']} == {'string', 'object'}
    assert any(part.get('const') == 'help' for part in schema['anyOf'])


@pytest.mark.parametrize('options', [None, [], '', 'HELP', 'statistics', {'statistics': object()}, {'statistics': float('nan')}, {1: True}])
def test_invalid_backend_arguments_are_rejected(wave_tool, options):
    """Both public argument models enforce JSON objects or the help literal."""
    tool, _ = wave_tool
    for model in (ArgWaveInfo, WaveInfoAnalysisArgs):
        with pytest.raises((ValueError, TypeError)):
            model(test_case_name='test_demo', backend_args=options)
    assert tool.analyze(test_case_name='test_demo', backend_args=options)['status'] == 'invalid_arguments'


@pytest.mark.parametrize('options', [{'unknown': True}, {'statistics': 1}, {'statistics': 'true'}, {'signal_metadata': []}])
def test_unsupported_advanced_options_return_help_call(wave_tool, options):
    """Backend-owned option errors are actionable and do not masquerade as parse errors."""
    tool, _ = wave_tool
    result = tool.analyze(test_case_name='test_demo', backend_args=options)
    assert result['status'] == 'invalid_backend_args'
    assert tool.analyze(**result['details']['help_call'])['status'] == 'advanced_help'


def test_advanced_extensions_hidden_paginated_signed_and_replayed(wave_tool):
    """Options survive catalog continuation and signed analysis/replay without mutation."""
    tool, _ = wave_tool
    options = {'signal_metadata': True, 'statistics': True}
    first = tool.analyze(test_case_name='test_demo', signal_limit=2, backend_args=options)
    assert 'extensions' not in first
    assert first['extensions_available']['signal_queries'] == {'**': ['signal_metadata']}
    next_call = first['signal_catalog']['next_call']
    assert next_call['backend_args'] == options
    second = tool.analyze(**{**next_call, 'include_extensions': True})
    metadata = second['extensions']['signal_queries']['**']['signal_metadata']
    assert set(metadata) == set(second['signal_catalog']['signals'])
    assert len(metadata) == 2
    arguments = {'test_case_name': 'test_demo', 'pattern': [{'signal': 'TOP.dut.result[3:0]', 'event': 'unknown'}], 'start_step': 20, 'end_step': 30, 'backend_args': options, 'include_extensions': True}
    result = yaml.safe_load(tool.invoke(arguments))
    assert result['success'] is True
    stats = result['extensions']['value_changes']['TOP.dut.result[3:0]']['value']['statistics']
    assert stats['source_states'] == 2
    assert stats['unknown_states'] == 1
    receipt = tool.get_analysis_receipt(result['waveform_analysis_receipt']['receipt_id'])
    assert receipt['arguments']['backend_args'] == options
    assert tool.replay_analysis(**receipt['arguments'])['extensions'] == result['extensions']
    changed = deepcopy(receipt['arguments'])
    changed['backend_args']['statistics'] = False
    assert tool.analysis_semantic_fingerprint(changed, result) != tool.analysis_semantic_fingerprint(receipt['arguments'], result)
    assert options == {'signal_metadata': True, 'statistics': True}
    ordinary = tool.analyze(test_case_name='test_demo')
    assert 'extensions_available' not in ordinary
    overflow = tool.analyze(test_case_name='test_demo', pattern=[{'signal': '**'}], max_signals=1, backend_args=options, include_extensions=True)
    assert overflow['details']['catalog_call']['backend_args'] == options


@pytest.mark.parametrize('query,count', [('TOP.dut.*', 5), ('**.clk', 1), ('TOP.**.clk', 1), ('TOP.dut.{clk,valid}', 2), ('TOP.dut./(clk|valid)/', 2), ('TOP.dut.data', 1), ('TOP.dut.data[2:1]', 1)])
def test_pywellen_query_syntax(wave_tool, query, count):
    """Whole buses, slices, hierarchy wildcards, regex and alternatives resolve."""
    _, session = wave_tool
    with WellenVcdReader(str(session / 'master/test_demo.vcd')) as reader:
        assert reader.get_matched_signals(query)['total'] == count


@pytest.mark.parametrize('query', ['TOP./bad', 'TOP.{bad', 'TOP.}', 'TOP./[/', 'TOP.dut.data[8:0]', 'TOP.dut.data[1:2]'])
def test_pywellen_invalid_queries_raise(wave_tool, query):
    """Malformed queries and out-of-declaration slices do not return guessed matches."""
    _, session = wave_tool
    with WellenVcdReader(str(session / 'master/test_demo.vcd')) as reader:
        with pytest.raises((ValueError, re.error)):
            reader.get_matched_signals(query)


def test_indexed_arrays_wide_values_and_time_bounds(tmp_path):
    """Preserve indices, widths above 64 bits, X/Z masks, and unchanged final ticks."""
    pytest.importorskip('pywellen')
    path = tmp_path / 'edge.vcd'
    path.write_text('''$scope module TOP $end
$var wire 4 ! asc [0:3] $end
$var wire 4 # neg [-1:-4] $end
$var wire 1 & flag [5] $end
$var wire 4 % mem[0] [7:4] $end
$var wire 130 + wide [129:0] $end
$upscope $end
$enddefinitions $end
#5
b1010 !
bxz01 #
1&
b1100 %
b1 +
#10
b''' + '1' + '0' * 129 + ''' +
#50
$comment #9999 is not a simulation timestamp $end
''')
    mapping = {'0': 0, '1': 1, 'x': 0, 'z': 0}
    with WellenVcdReader(str(path)) as reader:
        assert (reader.begin_time, reader.end_time) == (5, 50)
        expected = {'TOP.asc[1:2]': 1, 'TOP.flag[5]': 1, 'TOP.mem[0][7:4]': 12, 'TOP.wide[129:0]': 2**129}
        for query, value in expected.items():
            signal = next(iter(reader.get_matched_signals(query)['signals'].values()))
            assert reader.load_value_changes(signal, mapping, 15, 50)['mapped'][-1][1] == value
            assert reader.load_value_changes(signal, mapping, 0, 5)['mapped'] == []
        signal = next(iter(reader.get_matched_signals('TOP.neg[-1:-4]')['signals'].values()))
        assert reader.load_value_changes(signal, {'0': 0, '1': 0, 'x': 1, 'z': 0})['mapped'] == [(5, 8)]
        assert reader.load_value_changes(signal, {'0': 0, '1': 0, 'x': 0, 'z': 1})['mapped'] == [(5, 4)]
    assert reader._wave is None
    assert reader._variables == {}


def test_empty_and_malformed_native_waveforms(tmp_path):
    """Empty designs and malformed files cannot manufacture analysis data."""
    pytest.importorskip('pywellen')
    session = _session(tmp_path / 'tests', 'toffee_tmp_20261030120000_001')
    path = session / 'master/test_empty.vcd'
    path.write_text('$scope module TOP $end\n$upscope $end\n$enddefinitions $end\n#0\n#40\n')
    tool = WaveInfo(workspace=str(tmp_path), test_dir='tests')
    assert tool.analyze(test_case_name='test_empty')['status'] == 'waveform_has_no_signals'
    path.write_text('not a waveform')
    assert tool.analyze(test_case_name='test_empty')['status'] == 'waveform_parse_error'
    path.write_text('')
    assert tool.analyze(test_case_name='test_empty')['status'] == 'empty_waveform'


@pytest.mark.parametrize('fallback', [False, True])
def test_operator_logs_show_backend_without_exposing_it_to_llm(wave_tool, monkeypatch, fallback):
    """Human logs identify order, fallback, selection and completion without option values."""
    from ucagent.tools import waveform

    tool, _ = wave_tool
    messages = []
    if fallback:
        monkeypatch.setitem(sys.modules, 'pywellen', None)
    monkeypatch.setattr(registry, 'log_msg', messages.append)
    monkeypatch.setattr(waveform, 'log_info', messages.append)
    chosen = 'wavekit' if fallback else 'pywellen'
    result = tool.analyze(test_case_name='test_demo')
    assert result['success'] is True
    assert 'reader_backend' not in result
    assert any('backend_order' in message and 'backends=pywellen,wavekit' in message for message in messages)
    assert any('backend_selected' in message and f'backend={chosen}' in message for message in messages)
    assert any('analysis_started' in message and f'backend={chosen}' in message for message in messages)
    assert any('analysis_finished' in message and f'backend={chosen}' in message and 'status=metadata_only' in message and 'elapsed=' in message for message in messages)
    assert any('backend_unavailable' in message for message in messages) is fallback
    assert not any('backend_args=' in message for message in messages)


def test_custom_advanced_options_passthrough_and_extension_scope(wave_tool, monkeypatch):
    """A registered backend can implement nested custom features without tool changes."""
    from ucagent.tools import ApplyWaveInfoEvidence

    tool, _ = wave_tool
    monkeypatch.setattr(registry, '_READERS', deepcopy(registry._READERS))
    received = []

    class CustomVcdReader(WellenVcdReader):
        """Use a test-specific analysis option while retaining ordinary digital reading."""

        backend_name = 'custom'

        def configure_backend(self, backend_args):
            """Consume an isolated nested object and return a bounded backend result."""
            received.append(deepcopy(backend_args))
            if backend_args == 'help':
                return {'options': {'correlate': {'type': 'object'}}, 'examples': [{'backend_args': {'correlate': {'depth': 2}}}]}
            backend_args['correlate']['depth'] += 1
            return {'correlations': {'groups': 2, 'depth': backend_args['correlate']['depth']}}

    register_waveform_reader('vcd', CustomVcdReader, backend='custom')
    tool.backend_priority['vcd'] = ['custom']
    options = {'correlate': {'depth': 2}}
    args = {'test_case_name': 'test_demo', 'backend_args': options}
    default = tool.analyze(**args)
    assert default['extensions_available']['backend'] == ['correlations']
    assert 'extensions' not in default
    result = yaml.safe_load(tool.invoke({**args, 'include_extensions': True}))
    assert result['extensions']['backend'] == {'correlations': {'groups': 2, 'depth': 3}}
    receipt_id = result['waveform_analysis_receipt']['receipt_id']
    receipt = tool.get_analysis_receipt(receipt_id)
    assert receipt['arguments']['backend_args'] == options
    assert tool.replay_analysis(**receipt['arguments'])['extensions'] == result['extensions']
    recovery = ApplyWaveInfoEvidence(waveinfo=tool, workspace=tool.workspace)._waveinfo_recovery_call(receipt_id, 'tests/test_demo.py::test_demo')
    assert recovery['backend_args'] == options
    assert recovery['include_extensions'] is True
    assert all(value == options for value in received)
    assert options == {'correlate': {'depth': 2}}


def test_native_large_catalog_metadata_is_page_scoped(wave_tool):
    """Real pywellen pages keep extensions bounded and continuation calls complete."""
    tool, session = wave_tool
    declarations = '\n'.join(f'$var wire 1 s{index} data{index:04} $end' for index in reversed(range(250)))
    values = '\n'.join(f'0s{index}' for index in range(250))
    path = session / 'master/test_many.vcd'
    path.write_text(f'$scope module TOP $end\n{declarations}\n$upscope $end\n$enddefinitions $end\n#0\n{values}\n#40\n')
    arguments = {'test_case_name': 'test_many', 'backend_args': {'signal_metadata': True}, 'include_extensions': True}
    names = []
    for count in (100, 100, 50):
        result = tool.analyze(**arguments)
        catalog = result['signal_catalog']
        assert catalog['total'] == 250
        assert len(catalog['signals']) == count
        metadata = result['extensions']['signal_queries']['**']['signal_metadata']
        assert set(metadata) == set(catalog['signals'])
        names.extend(catalog['signals'])
        arguments = catalog.get('next_call')
    assert arguments is None
    assert names == [f'TOP.data{index:04}' for index in range(250)]


def test_pywellen_entry_failure_releases_native_references(wave_tool, monkeypatch):
    """Metadata construction failures drop the newly opened native owner immediately."""
    import pywellen
    from types import SimpleNamespace

    _, session = wave_tool
    owners = []

    class BrokenWave:
        """Expose conflicting widths to force failure after the native open."""

        def __init__(self, path):
            """Observe the object handed to the adapter."""
            owners.append(self)

        def all_vars(self):
            """Return one valid signal followed by an invalid duplicate."""
            return [SimpleNamespace(is_bit_vector=True, bitwidth=4, full_name='TOP.dut.data'), SimpleNamespace(is_bit_vector=True, bitwidth=8, full_name='TOP.dut.data')]

    monkeypatch.setattr(pywellen, 'Waveform', BrokenWave)
    reader = WellenVcdReader(str(session / 'master/test_demo.vcd'))
    with pytest.raises(ValueError, match='Declared range'):
        reader.__enter__()
    assert reader._wave is None
    assert reader._signals == {}
    assert reader._variables == {}


def test_native_enum_metadata_uses_json_arrays(wave_tool, monkeypatch):
    """Native tuple metadata becomes JSON arrays before tool output and signing."""
    from types import SimpleNamespace

    tool, session = wave_tool
    with WellenVcdReader(str(session / 'master/test_demo.vcd')) as reader:
        reader.configure_backend({'signal_metadata': True})
        original = reader._variables['TOP.dut.data']
        metadata = SimpleNamespace(
            var_type=original.var_type, direction=original.direction,
            enum_type=('state_t', [('00', 'IDLE'), ('01', 'BUSY')]),
            vhdl_type_name='state_t',
        )
        monkeypatch.setitem(reader._variables, 'TOP.dut.data', metadata)
        result = reader.get_matched_signals('TOP.dut.data[3:0]')
        extra = tool._reader_extensions(result)
        enum_type = extra['signal_metadata']['TOP.dut.data[3:0]']['enum_type']
        assert enum_type == ['state_t', [['00', 'IDLE'], ['01', 'BUSY']]]
        assert yaml.safe_load(yaml.safe_dump(extra)) == json.loads(json.dumps(extra))


def test_invalid_call_extensions_fail_before_receipt_serialization(wave_tool, monkeypatch):
    """Mixed nested keys cannot escape validation into receipt hashing."""
    tool, _ = wave_tool

    def invalid_options(self, backend_args):
        """Return malformed call-level extensions from an otherwise valid backend."""
        return {'quality': {1: 'numeric key', 'name': 'mixed keys'}}

    monkeypatch.setattr(WellenVcdReader, 'configure_backend', invalid_options)
    result = yaml.safe_load(tool.invoke({'test_case_name': 'test_demo', 'include_extensions': True}))
    assert result['status'] == 'waveform_parse_error'
    assert 'extensions' not in result
    receipt = tool.get_analysis_receipt(result['waveform_analysis_receipt']['receipt_id'])
    assert receipt['result']['status'] == 'waveform_parse_error'


@pytest.mark.parametrize('value', [{'nested': {1: 'not a JSON key'}}, {'nested': (1, 2)}])
def test_advanced_args_reject_non_json_nested_shapes(value):
    """Persisted/replayed JSON must have the same semantics as the initial call."""
    for model in (ArgWaveInfo, WaveInfoAnalysisArgs):
        with pytest.raises(ValueError, match='JSON'):
            model(test_case_name='test_demo', backend_args=value)


@pytest.mark.parametrize('args', [{'backend_args': 'help'}, {'test_case_name': ' ', 'backend_args': {'statistics': True}}, {'test_case_name': 'test_demo', 'backend_args': 'help', 'pattern': [{'signal': '**'}]}])
def test_advanced_requests_require_target_and_separate_help(args):
    """Help requires an exact target and cannot silently discard event patterns."""
    for model in (ArgWaveInfo, WaveInfoAnalysisArgs):
        with pytest.raises(ValueError):
            model(**args)


def test_mcp_executes_help_and_nested_advanced_arguments(wave_tool):
    """Converted MCP dispatch preserves the object/string union and results."""
    import asyncio

    tool, _ = wave_tool
    converted = to_mcp_tool(tool)
    help_result = yaml.safe_load(asyncio.run(converted.run(
        {'test_case_name': 'test_demo', 'backend_args': 'help'}, context=None,
    )))
    assert help_result['status'] == 'advanced_help'
    assert 'statistics' in help_result['extensions']['backend']['options']
    options = {'signal_metadata': True}
    result = yaml.safe_load(asyncio.run(converted.run(
        {'test_case_name': 'test_demo', 'backend_args': options, 'include_extensions': True}, context=None,
    )))
    assert result['success'] is True
    assert set(result['extensions']['signal_queries']['**']['signal_metadata']) == set(result['signal_catalog']['signals'])
    receipt = tool.get_analysis_receipt(result['waveform_analysis_receipt']['receipt_id'])
    assert receipt['arguments']['backend_args'] == options


@pytest.mark.parametrize('kind', ['identifier', 'bits', 'implicit_range', 'empty_trace', 'corrupt_value'])
def test_vcd_metadata_and_decoding_boundaries(wave_tool, monkeypatch, kind):
    """Identifier codes, merged bits, empty traces and native panics preserve correctness."""
    from ucagent.tools import waveform

    tool, session = wave_tool
    mapping = {'0': 0, '1': 1, 'x': 0, 'z': 0}
    declaration, values, expected = {
        'identifier': ('$var wire 4 #9999 bus [3:0] $end', 'b0001 #9999', {'TOP.bus[3:0]': [(5, 1)]}),
        'bits': ('$var wire 1 ! data [0] $end\n$var wire 1 " data [1] $end', '0!\n1"', {'TOP.data[0]': [(5, 0)], 'TOP.data[1]': [(5, 1)]}),
        'implicit_range': ('$var wire 4 ! bus $end', 'b1 !', {'TOP.bus[3:0]': [(5, 1)]}),
        'empty_trace': ('$var wire 4 ! bus $end', '', {'TOP.bus[3:0]': []}),
        'corrupt_value': ('$var wire 4 ! bus $end', 'b002 !', {}),
    }[kind]
    path = session / 'master/test_boundary.vcd'
    path.write_text('$scope module TOP $end\n' + declaration + '\n$upscope $end\n$enddefinitions $end\n#5\n' + values + '\n#50\n')
    if kind == 'corrupt_value':
        messages = []
        monkeypatch.setattr(waveform, 'log_info', messages.append)
        monkeypatch.setattr(waveform, 'log_msg', messages.append)
        result = tool.analyze(test_case_name='test_boundary', pattern=[{'signal': 'TOP.bus[3:0]'}])
        assert result['status'] == 'waveform_parse_error'
        assert any('backend=pywellen' in message and 'status=waveform_parse_error' in message for message in messages)
        assert 'panicked' not in json.dumps(result)
        assert 'PanicException' not in json.dumps(result)
        return
    with WellenVcdReader(str(path)) as reader:
        assert (reader.begin_time, reader.end_time) == (5, 50)
        actual = {
            signal.full_name: reader.load_value_changes(signal, mapping)['mapped']
            for signal in reader.get_matched_signals('**')['signals'].values()
        }
        assert actual == expected


def test_ambiguous_native_declarations_fail_without_guessing(wave_tool):
    """Duplicate indistinguishable native names cannot be assigned to the wrong bits."""
    tool, session = wave_tool
    path = session / 'master/test_ambiguous.vcd'
    path.write_text('''$scope module TOP $end
$var wire 1 ! data [5] $end
$var wire 1 " data [8] $end
$upscope $end
$enddefinitions $end
#0
0!
1"
''')
    assert tool.analyze(test_case_name='test_ambiguous')['status'] == 'waveform_parse_error'


@pytest.mark.parametrize('enabled', [False, True])
def test_resolved_yaml_backend_order_overrides_per_format(tmp_path, monkeypatch, enabled):
    """YAML list replacement is stable across environment/runtime boolean choices."""
    from ucagent.util.config import _merge_config_file

    root = Path(__file__).parents[1]
    monkeypatch.setenv('NEED_REF_MODEL', str(enabled).lower())
    monkeypatch.setenv('IGNORE_MOCK_COMPONENT', str(not enabled).lower())
    cfg = Config()
    loaded = []
    _merge_config_file(cfg, str(root / 'ucagent/setting.yaml'), loaded)
    _merge_config_file(cfg, str(root / 'ucagent/lang/zh/config/default.yaml'), loaded)
    override = tmp_path / 'backend.yaml'
    override.write_text('runtime_options:\n  waveform_analysis_backend_priority:\n    vcd: [wavekit]\n')
    _merge_config_file(cfg, str(override), loaded)
    order = cfg.runtime_options.waveform_analysis_backend_priority.as_dict()
    assert order == {**DEFAULT_WAVEFORM_ANALYSIS_BACKEND_PRIORITY, 'vcd': ['wavekit']}
    tool = WaveInfo(workspace=str(tmp_path), backend_priority=order)
    assert tool.backend_priority == order
    assert cfg.runtime_options.need_ref_model is enabled
    assert cfg.runtime_options.mock_components_enabled is enabled
    cfg.update_template({'DUT': 'Demo', 'OUT': 'out'})
    cfg.un_freeze()
    cfg._temp_cfg = {'DUT': 'Demo', 'OUT': 'out'}
    save_runtime_config(str(tmp_path), cfg)
    assert load_runtime_config(str(tmp_path))['runtime_options']['waveform_analysis_backend_priority'] == order
