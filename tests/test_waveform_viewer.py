"""Portable waveform metadata, immutable link targets and containment regression tests."""

import json
from pathlib import Path

import pytest

from ucagent.util.waveform_viewer import (
    WaveformViewerProtocolError, build_waveform_metadata, build_waveform_viewer_markdown_link,
    build_waveform_viewer_url, load_waveform_metadata, normalize_waveform_viewer_payload,
    parse_waveform_viewer_markdown_link, validate_waveform_metadata, write_waveform_metadata,
    WaveformMetadataIntegrityError,
)


@pytest.fixture(autouse=True)
def signing_keys(tmp_path, monkeypatch):
    """Keep test signing secrets outside their served workspace and user profile."""
    monkeypatch.setattr('ucagent.util.waveform_viewer._METADATA_KEY_DIRECTORY',
                        tmp_path.parent / (tmp_path.name + '-keys'))


def _files(root):
    """Create explicit wave, DUT and related semantic design files."""
    for value in ('waves/中文 a.fsdb', 'Demo/Demo.v', 'Demo/__init__.py',
                  'src/Demo.scala', 'tests/test_demo.py'):
        path = root / value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture', encoding='utf-8')
    return build_waveform_metadata(root, 'waves/中文 a.fsdb', dut_name='Demo',
        source_files=['src/Demo.scala'], test_case='tests/test_demo.py::test_saturation[x y]')


def test_relative_metadata_roundtrip_and_unicode_link(tmp_path):
    """Paths inside metadata are relative to its directory, links to the workspace."""
    meta, payload, warnings = _files(tmp_path)
    assert meta == 'waves/中文 a.fsdb.json'
    assert payload == dict(schema_version=1, waveform_file='中文 a.fsdb', signals=[],
        source_files=['../Demo/Demo.v', '../src/Demo.scala'], dut_python_path='../Demo/__init__.py',
        test_file='../tests/test_demo.py', test_case='tests/test_demo.py::test_saturation[x y]')
    assert warnings == []
    payload.update(signals=['TOP.dut.clk'], start='0', end='184467440737095516170', cursor='9007199254740993')
    write_waveform_metadata(tmp_path, meta, payload)
    assert load_waveform_metadata(tmp_path, meta)[1] == payload
    path = tmp_path / meta
    stored = json.loads(path.read_text())
    path.write_text(json.dumps(dict(reversed(list(stored.items()))), ensure_ascii=False))
    assert load_waveform_metadata(tmp_path, meta)[1] == payload
    link = build_waveform_viewer_markdown_link(meta)
    assert parse_waveform_viewer_markdown_link(link) == meta
    assert '%20' in link and '/wave/?meta=' in link
    (tmp_path / meta[:-5]).unlink()
    validate_waveform_metadata(tmp_path, meta, payload, must_exist=False)
    with pytest.raises(FileNotFoundError):
        load_waveform_metadata(tmp_path, meta)


@pytest.mark.parametrize('field,value', [('schema_version', True), ('signals', None),
    ('source_files', ['../../../escape.sv']), ('waveform_file', '../a.fsdb'),
    ('dut_python_path', '/etc/passwd'), ('signals', ['\n']), ('source_files', ['C:/a.sv'])])
def test_invalid_metadata_or_escaping_files(tmp_path, field, value):
    """Reject malformed metadata and file paths before any write."""
    meta, payload, _ = _files(tmp_path)
    payload[field] = value
    with pytest.raises((WaveformViewerProtocolError, FileNotFoundError)):
        validate_waveform_metadata(tmp_path, meta, payload)


def test_symlinks_cannot_escape_workspace(tmp_path):
    """Both associated file and JSON symlinks must remain inside the workspace."""
    root = tmp_path / 'workspace'
    root.mkdir()
    meta, payload, _ = _files(root)
    external = tmp_path / 'external.sv'
    external.write_text('secret')
    (root / 'source.sv').symlink_to(external)
    payload['source_files'] = ['../source.sv']
    with pytest.raises(WaveformViewerProtocolError, match='escapes'):
        validate_waveform_metadata(root, meta, payload)
    (root / meta).symlink_to(external)
    with pytest.raises(WaveformViewerProtocolError, match='escapes'):
        write_waveform_metadata(root, meta, payload)


def test_missing_optional_associations_are_not_invented(tmp_path):
    """Missing automatic paths become null or absent with an actionable warning."""
    (tmp_path / 'a.vcd').write_text('wave')
    meta, payload, warnings = build_waveform_metadata(tmp_path, 'a.vcd', dut_name='Missing', test_case='tests/a.py::test_x')
    assert payload['dut_python_path'] is None and payload['test_file'] is None
    assert payload['source_files'] == [] and warnings
    for args in ({'source_files': ['missing.sv']}, {'dut_python_path': 'missing.py'}):
        with pytest.raises(FileNotFoundError):
            build_waveform_metadata(tmp_path, 'a.vcd', **args)
    with pytest.raises(WaveformViewerProtocolError, match='filename'):
        validate_waveform_metadata(tmp_path, 'other.json', payload)


@pytest.mark.parametrize('changes', [dict(start='1'), dict(start='00', end='2', cursor='1'),
    dict(start='0', end='2', cursor='3'), dict(start=0, end='2', cursor='1'),
    dict(start='0', end='2', cursor='1', signals=[]), dict(signals=['x']*65+['y']*65), dict(command='sh')])
def test_invalid_windows_and_unknown_fields(tmp_path, changes):
    """Keep exact integer strings and reject metadata acting as a command source."""
    _, payload, _ = _files(tmp_path)
    payload['signals'] = ['TOP.clk']
    payload.update(changes)
    if changes.get('signals') == ['x']*65+['y']*65:
        assert normalize_waveform_viewer_payload(payload)['signals'] == ['x', 'y']
    else:
        with pytest.raises(WaveformViewerProtocolError):
            normalize_waveform_viewer_payload(payload)


def test_writes_are_atomic_and_respect_restrictions(tmp_path, monkeypatch):
    """Failed publication preserves the previous final view and leaves no temp files."""
    meta, payload, _ = _files(tmp_path)
    write_waveform_metadata(tmp_path, meta, payload)
    original = (tmp_path / meta).read_bytes()
    payload['signals'] = ['TOP.changed']
    with pytest.raises(PermissionError):
        write_waveform_metadata(tmp_path, meta, payload, un_write_dirs=['waves/**'])
    (tmp_path / 'alias').symlink_to(tmp_path / 'waves', target_is_directory=True)
    with pytest.raises(PermissionError):
        write_waveform_metadata(tmp_path, 'alias/' + Path(meta).name, payload,
                                un_write_dirs=['waves/**'])
    def fail(*args):
        """Simulate an atomic replacement failure."""
        raise OSError('read-only filesystem')
    monkeypatch.setattr('ucagent.util.waveform_viewer.os.replace', fail)
    with pytest.raises(OSError):
        write_waveform_metadata(tmp_path, meta, payload)
    assert (tmp_path / meta).read_bytes() == original
    assert len(list((tmp_path / 'waves').iterdir())) == 2


@pytest.mark.parametrize('content', ['{', '[]', '{}', '"data"'])
def test_malformed_json_is_actionable(tmp_path, content):
    """Reject invalid JSON and invalid schema without producing metadata."""
    (tmp_path / 'a.vcd.json').write_text(content)
    with pytest.raises(WaveformViewerProtocolError):
        load_waveform_metadata(tmp_path, 'a.vcd.json')


@pytest.mark.parametrize('meta', ['../a.vcd.json', '/tmp/a.vcd.json', 'waves//a.vcd.json', 'a.vcd'])
def test_invalid_link_targets(meta):
    """Viewer links accept only canonical workspace relative JSON paths."""
    with pytest.raises(WaveformViewerProtocolError):
        build_waveform_viewer_url(meta)


@pytest.mark.parametrize('meta', ['%FF.vcd.json', '%C0%AF.vcd.json', 'a%ZZ.vcd.json'])
def test_invalid_link_encoding_returns_a_protocol_error(meta):
    """Malformed document URLs must produce a repairable diagnostic instead of a crash."""
    with pytest.raises(WaveformViewerProtocolError):
        parse_waveform_viewer_markdown_link(f'<WAVEFORM-VIEWER> [view](/wave/?meta={meta})')


def test_cyclic_symlink_returns_a_protocol_error(tmp_path):
    """A cyclic path cannot bypass containment or escape through an unhandled exception."""
    (tmp_path / 'loop').symlink_to('loop')
    with pytest.raises(WaveformViewerProtocolError, match='cannot be resolved'):
        load_waveform_metadata(tmp_path, 'loop/a.vcd.json')


@pytest.mark.parametrize('field,value', [
    ('signals', ['TOP.forged']), ('source_files', []), ('dut_python_path', None),
    ('test_file', None), ('test_case', 'tests/test_demo.py::test_forged'),
    ('start', '1'), ('end', '30'), ('cursor', '12'),
    ('waveform_file', 'other.fsdb'), ('integrity_hmac', '0' * 64),
])
def test_metadata_rejects_tampering_before_file_lookup(tmp_path, field, value):
    """Every stored field is authenticated even when the modified structure is valid."""
    meta, payload, _ = _files(tmp_path)
    payload.update(signals=['TOP.clk'], start='0', end='20', cursor='10')
    write_waveform_metadata(tmp_path, meta, payload)
    stored = json.loads((tmp_path / meta).read_text())
    assert len(stored['integrity_hmac']) == 64
    stored[field] = value
    (tmp_path / meta).write_text(json.dumps(stored))
    with pytest.raises(WaveformMetadataIntegrityError):
        load_waveform_metadata(tmp_path, meta)


def test_unsigned_copied_or_missing_key_metadata_is_rejected(tmp_path):
    """Unsigned content and signatures copied to another path/workspace cannot be trusted."""
    import ucagent.util.waveform_viewer as viewer
    meta, payload, _ = _files(tmp_path)
    write_waveform_metadata(tmp_path, meta, payload)
    original = (tmp_path / meta).read_bytes()
    copy = tmp_path / 'copied' / Path(meta).name
    copy.parent.mkdir()
    copy.write_bytes(original)
    with pytest.raises(WaveformMetadataIntegrityError):
        load_waveform_metadata(tmp_path, copy.relative_to(tmp_path).as_posix())
    copy.unlink()
    copy.symlink_to(tmp_path / meta)
    with pytest.raises(WaveformMetadataIntegrityError, match='resolved'):
        load_waveform_metadata(tmp_path, copy.relative_to(tmp_path).as_posix())
    with pytest.raises(WaveformViewerProtocolError, match='resolved'):
        write_waveform_metadata(tmp_path, copy.relative_to(tmp_path).as_posix(), payload)
    other = tmp_path / 'workspace'
    other.mkdir()
    other_meta, _, _ = _files(other)
    (other / other_meta).write_bytes(original)
    with pytest.raises(WaveformMetadataIntegrityError):
        load_waveform_metadata(other, other_meta)
    (tmp_path / meta).write_text(json.dumps(payload))
    with pytest.raises(WaveformMetadataIntegrityError):
        load_waveform_metadata(tmp_path, meta)
    (tmp_path / meta).write_bytes(original)
    key = next(viewer._METADATA_KEY_DIRECTORY.glob('*.key'))
    assert key.stat().st_mode & 0o777 == 0o600
    assert not key.is_relative_to(tmp_path)
    key.unlink()
    with pytest.raises(WaveformMetadataIntegrityError, match='missing'):
        load_waveform_metadata(tmp_path, meta)
    assert not key.exists()


def test_metadata_duplicate_keys_and_corrupt_content_are_not_silently_accepted(tmp_path):
    """Reject ambiguous JSON, while an explicit tool publication repairs corrupt bytes."""
    meta, payload, _ = _files(tmp_path)
    write_waveform_metadata(tmp_path, meta, payload)
    path = tmp_path / meta
    content = path.read_text()
    path.write_text(content.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    with pytest.raises(WaveformViewerProtocolError, match='duplicate'):
        load_waveform_metadata(tmp_path, meta)
    path.write_bytes(b'\xff')
    with pytest.raises(WaveformViewerProtocolError, match='UTF-8'):
        load_waveform_metadata(tmp_path, meta)
    write_waveform_metadata(tmp_path, meta, payload)
    assert load_waveform_metadata(tmp_path, meta)[1] == payload


@pytest.mark.parametrize('damage', ['symlink', 'public-key', 'public-directory', 'short-key'])
def test_metadata_private_key_storage_fails_closed(tmp_path, damage):
    """Unsafe or corrupt key storage must never authorize existing viewing metadata."""
    import ucagent.util.waveform_viewer as viewer
    meta, payload, _ = _files(tmp_path)
    write_waveform_metadata(tmp_path, meta, payload)
    directory = viewer._METADATA_KEY_DIRECTORY
    key = next(directory.glob('*.key'))
    if damage == 'symlink':
        other = directory / 'actual-key'
        key.rename(other)
        key.symlink_to(other)
    elif damage == 'public-key':
        key.chmod(0o644)
    elif damage == 'public-directory':
        directory.chmod(0o755)
    else:
        key.write_bytes(b'invalid')
    with pytest.raises(WaveformMetadataIntegrityError):
        load_waveform_metadata(tmp_path, meta)


def test_json_size_bound_and_concurrent_key_publication(tmp_path):
    """Concurrent publishers share one complete key and oversized input stays bounded."""
    from concurrent.futures import ThreadPoolExecutor
    import ucagent.util.waveform_viewer as viewer
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: viewer._metadata_key(tmp_path, create=True), range(16)))
    assert len(set(keys)) == 1
    meta, payload, _ = _files(tmp_path)
    write_waveform_metadata(tmp_path, meta, payload)
    (tmp_path / meta).write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(WaveformViewerProtocolError, match='1 MiB'):
        load_waveform_metadata(tmp_path, meta)
