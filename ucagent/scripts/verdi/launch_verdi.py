"""Launch Verdi from portable waveform metadata and restore its native-tick view."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

# Direct execution must import the exact package containing this installed script.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ucagent.util.waveform_viewer import load_waveform_metadata, resolve_workspace_path


def tcl_word(value: str) -> str:
    """Quote one literal Tcl word without command or variable substitution."""
    return '"' + ''.join('\\' + char if char in '\\"$[]{}' else
                         '\\n' if char == '\n' else '\\r' if char == '\r' else char
                         for char in value) + '"'


def launch(meta: Path, verdi: str, extra_args: list[str], *, workspace: Path | None = None,
           dbdir: Path | None = None) -> int:
    """Verify metadata, select its compiled design and restore a docked Verdi view."""
    workspace = (workspace or Path.cwd()).resolve()
    meta = meta.resolve(strict=True)
    _, payload = load_waveform_metadata(workspace, meta.relative_to(workspace).as_posix())
    wave_name = payload["waveform_file"]
    wave = (meta.parent / wave_name).resolve(strict=True)
    sources = [(meta.parent / value).resolve(strict=True) for value in payload["source_files"]]
    rtl = [str(path) for path in sources if path.suffix.lower() in {".v", ".sv", ".vh", ".svh"}]
    # Picker stores the elaborated VCS database beside the DUT Python entry. Use
    # those signed associations rather than searching unrelated workspace designs.
    database = None
    if dbdir is not None:
        candidate = dbdir if dbdir.is_absolute() else workspace / dbdir
        relative = candidate.relative_to(workspace).as_posix()
        database = resolve_workspace_path(workspace, relative, must_exist=False)
        if not database.is_dir():
            raise ValueError("Verdi --dbdir must name a design database directory")
    else:
        entry = payload["dut_python_path"]
        locations = []
        if entry:
            dut = (meta.parent / entry).resolve(strict=True)
            locations.append([dut.parent])
        locations.append(list(dict.fromkeys(path.parent for path in sources)))
        for directories in locations:
            candidates = {path.parent for directory in directories
                          for path in directory.glob("*.daidir/simv.kdb")}
            if len(candidates) > 1:
                raise ValueError("Multiple VCS design databases; configure --dbdir for this viewer")
            if candidates:
                candidate = candidates.pop()
                database = resolve_workspace_path(workspace, candidate.relative_to(workspace).as_posix(), must_exist=False)
                break
    if database is not None:
        # Do not pass database symlinks outside the selected workspace to Verdi.
        kdb = resolve_workspace_path(workspace, (database / "simv.kdb").relative_to(workspace).as_posix(),
                                     must_exist=False)
        for path in database.rglob("*"):
            if path.is_symlink():
                resolve_workspace_path(workspace, path.relative_to(workspace).as_posix(), must_exist=False)
        if not kdb.is_file() or "KDB=TRUE" not in kdb.read_text(encoding="utf-8"):
            raise ValueError("Verdi design database requires simv.kdb with KDB=TRUE; rebuild the DUT with VCS -kdb")
    commands = [
        'verdiSetPrefEnv -bUndockNewCreatedWindow off',
        'set wave [wvCreateWindow]',
        'if {$wave eq "" || $wave eq "0"} {error "Cannot create waveform window"}',
        'set opened [wvOpenFile -win $wave ' + tcl_word(str(wave)) + ']',
        'if {$opened eq "" || $opened eq "0"} {error "Cannot load waveform file"}',
    ]
    for signal in payload["signals"]:
        # Signal names are wavekit hierarchy paths; Tcl sees one literal nWave path.
        commands.append('if {![wvAddSignal -win $wave -delim . ' + tcl_word(signal) +
                        ']} {error ' + tcl_word('Cannot add waveform signal: ' + signal) + '}')
    if any(key in payload for key in ('start', 'end', 'cursor')):
        values = [payload[key] for key in ('start', 'end', 'cursor')]
        commands += [
            'set file_unit [wvGetFileTimeUnit -win $wave]',
            'if {![regexp {^([0-9]+(?:[.][0-9]+)?)[ ]*([GMKmunpf]?s)$} $file_unit -> scale unit]} {',
            '  error "Cannot determine waveform native time unit: $file_unit"',
            '}',
            # Set display to exactly one native tick: no cycle or assumed-ns conversion.
            'if {![wvSetWindowTimeUnit -win $wave $scale $unit]} {',
            '  error "Cannot set waveform native display time unit: $file_unit"',
            '}',
            'if {![wvZoom -win $wave ' + values[0] + ' ' + values[1] +
            ']} {error "Cannot restore waveform time range"}',
            'if {![wvSetCursor -win $wave ' + values[2] +
            ']} {error "Cannot restore waveform cursor"}',
        ]
    commands.append('wvRaiseWindow -win $wave')
    script = 'set startup ' + tcl_word('\n'.join(commands)) + '\n' + \
             'if {[catch $startup failure]} {\n' + \
             '  puts stderr "Cannot restore waveform view: $failure"\n  exit 1\n}\n'
    with tempfile.TemporaryDirectory(prefix='ucagent-verdi-') as directory:
        startup = Path(directory) / 'view.tcl'
        startup.write_text(script, encoding='utf-8')
        argv = [verdi, *extra_args]
        if database is not None:
            argv += ['-dbdir', str(database)]
        elif rtl:
            argv += ['-sv', *rtl]
        argv += ['-logdir', str(Path(directory) / 'logs'), '-play', str(startup)]
        return subprocess.run(argv, check=False).returncode


def main() -> int:
    """Parse configured argv and report actionable launcher failures to Xpra logs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meta', type=Path, required=True)
    parser.add_argument('--verdi', default='verdi')
    parser.add_argument('--dbdir', type=Path, help='Workspace-contained VCS design database directory')
    parser.add_argument('verdi_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        extra = args.verdi_args[1:] if args.verdi_args[:1] == ['--'] else args.verdi_args
        return launch(args.meta, args.verdi, extra, dbdir=args.dbdir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Cannot open waveform in Verdi: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
