"""Optional waveform receipt ownership and exact measured signal values."""

from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from .json_io import read_object


def wave_tool(layout):
    """Construct the native tool only when waveform review is enabled."""
    from ucagent.util.config import load_runtime_config
    from ucagent.tools.waveform import WaveInfo
    runtime = load_runtime_config(str(layout.workspace))
    if not layout.review().options.waveform_enabled:
        raise ValueError('waveform review is disabled')
    return WaveInfo(workspace=str(layout.workspace), test_dir=str(layout.work), dut_name=runtime['DUT'],
                    session_scope='all', allowed_case_index=str((layout.out / 'review.json').relative_to(layout.workspace)))


def receipt_fields(layout, case_id, invocation_id, receipt_id, tool):
    """Bind evidence to a Case and a tool-harvested invocation session."""
    from ucagent.tools.waveform import WaveInfo
    if not layout.review().options.waveform_enabled:
        raise ValueError('waveform review is disabled')
    case = layout.case(case_id)
    if not any(e.invocation_id == invocation_id and e.provenance == 'rerun' for e in case.executions):
        raise ValueError('waveform requires an imported execution of this Case')
    tool = tool or wave_tool(layout)
    receipt = tool.get_analysis_receipt(receipt_id)
    name = layout.review().cases[case_id].waveform_test_case_name
    if not receipt or receipt.get('arguments', {}).get('test_case_name') != name:
        raise ValueError('receipt belongs to another Case or is unavailable')
    if tool.get_bug_document_evidence(receipt_id).get('success') is not True:
        raise ValueError('receipt must contain usable final evidence, not exploratory metadata')
    result = receipt['result']
    relative = result.get('waveform_selection', {}).get('waveform_file', '')
    path = (layout.workspace / relative).resolve()
    if not relative or not path.is_relative_to(layout.work):
        raise ValueError('waveform must belong to this run execution copy')
    manifest = read_object(layout.path(f'runs/waveforms/{invocation_id}.json'))
    sessions = [Path(item).resolve() for item in manifest['sessions']]
    if not any(path.is_relative_to(session) for session in sessions):
        raise ValueError('waveform session does not belong to the selected invocation')
    owners = WaveInfo.waveform_case_owners(path, [e.waveform_test_case_name for e in layout.review().cases.values()])
    if owners != [name]:
        raise ValueError('waveform Case ownership is ambiguous or conflicting; obtain isolated evidence')
    return {'receipt_id': receipt_id, 'invocation_id': invocation_id,
            'viewer_url': (result.get('waveform_viewer') or {}).get('url', ''),
            'source_file': relative, 'signal_groups': result.get('signal_groups', {}),
            'analysis_window': result.get('analysis_window', {})}


def event_value(path, time, signal_path):
    """Read an actual VCD/FST value with full bit width and X/Z masks."""
    import wavekit
    from ucagent.tools.waveform import WaveInfo
    path = Path(path)
    reader_type = wavekit.FstReader if path.suffix == '.fst' else wavekit.VcdReader
    with reader_type(str(path)) as reader:
        if not reader.begin_time <= time <= reader.end_time:
            raise ValueError('event time outside actual waveform')
        matches = [s for s in reader.get_matched_signals('**').values()
                   if re.sub(r'\[\d+:\d+\]$', '', s.full_name) == signal_path]
        if len(matches) != 1:
            raise ValueError('signal is missing or ambiguous; use ReviewSignalCatalog')
        trace = WaveInfo._load_trace(reader, matches[0], max(int(reader.begin_time), time - 1), time)
        state = trace.value_at(time)
        if state is None:
            raise ValueError('event has no measurable value')
        return ''.join('x' if state.x_mask >> bit & 1 else 'z' if state.z_mask >> bit & 1
                       else str(state.value >> bit & 1) for bit in reversed(range(trace.width)))


def event_window(wave, time, signal_path):
    """Validate raw time and signal identity against the signed viewing window."""
    from ucagent.util.waveform_viewer import decode_waveform_viewer_token
    payload = decode_waveform_viewer_token(parse_qs(urlsplit(wave.viewer_url).query)['wave'][0])
    if not int(payload['start']) <= time <= int(payload['end']):
        raise ValueError('event outside signed window')
    names = {re.sub(r'\[\d+:\d+\]$', '', s) for s in payload['signals']}
    if signal_path not in names:
        raise ValueError('signal not included in signed evidence')


def waveform_issues(layout, case, tool=None):
    """Check attached evidence without asking unrelated Cases to produce waveforms."""
    issues = []
    for wave in case.waveforms:
        try:
            expected = receipt_fields(layout, case.case_id, wave.invocation_id, wave.receipt_id, tool)
            if any(getattr(wave, key) != value for key, value in expected.items()):
                raise ValueError('waveform machine fields differ from receipt')
            for ref in wave.source_refs:
                layout.source(ref, 1)
        except (ValueError, OSError, KeyError) as error:
            issues.append({'case_id': case.case_id, 'field': 'waveforms', 'error': str(error)})
    for event in case.events:
        wave = next((w for w in case.waveforms if w.receipt_id == event.receipt_id), None)
        try:
            if wave is None:
                raise ValueError('event receipt is not attached')
            event_window(wave, event.time, event.signal_path)
        except (ValueError, KeyError) as error:
            issues.append({'case_id': case.case_id, 'field': event.event_id, 'error': str(error)})
    return issues
