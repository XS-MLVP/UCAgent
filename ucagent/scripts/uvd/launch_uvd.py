"""Launch UVD from portable waveform metadata and restore its native-tick view."""

import argparse
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

# Direct execution must import the exact package containing this installed script.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# _parse_hier produced the names in the metadata; UsdbReader would also run the slow dap query.
from ucagent.util.waveform_formats.read_usdb import UsdbRuntimeError, _find_tool, _parse_hier, _run_tool
from ucagent.util.waveform_viewer import load_waveform_metadata, resolve_workspace_path


def tcl_word(value: str) -> str:
    """Quote one literal Tcl word without command or variable substitution."""
    return '"' + ''.join('\\' + char if char in '\\"$[]{}' else char for char in value) + '"'


def native_unit(wave: Path) -> str:
    """Read the tick size that the metadata time values are counted in."""
    _, report = _run_tool([_find_tool('usdbaccess'), '-i', str(wave), '--info'])
    match = re.search(r'^time scale:\s*([0-9]+(?:s|ms|us|ns|ps|fs))\s*$', report, re.MULTILINE)
    if match is None:
        raise ValueError(f'Cannot determine waveform native time unit: {report.strip()[-200:]}')
    return match[1]


def check_signals(wave: Path, signals: list[str]) -> None:
    """Reject absent signals here: addSignals blocks the script on a modal dialog instead of failing."""
    if not signals:
        return
    _, hierarchy = _run_tool([_find_tool('usdbaccess'), '-i', str(wave), '--hier'])
    missing = set(signals) - set(_parse_hier(hierarchy))
    if missing:
        raise ValueError(f'Waveform has no signal: {", ".join(sorted(missing))}; regenerate its viewing metadata')


def find_database(workspace: Path, meta_dir: Path, payload: dict, dbdir: Path | None) -> Path | None:
    """Select the design database by the signed associations, not by searching the workspace."""
    if dbdir is not None:
        database = resolve_workspace_path(workspace, (workspace / dbdir).relative_to(workspace).as_posix(), must_exist=False)
        if not (database / 'ddb.db').is_dir():
            raise ValueError('UVD --dbdir requires a design database with ddb.db; rebuild the DUT with uvs -ddb')
    else:
        sources = [(meta_dir / value).resolve(strict=True) for value in payload['source_files']]
        locations = [list(dict.fromkeys(path.parent for path in sources))]
        if payload['dut_python_path']:
            # Picker stores the database beside the DUT Python entry.
            locations.insert(0, [(meta_dir / payload['dut_python_path']).resolve(strict=True).parent])
        database = None
        for directories in locations:
            candidates = {path.parent for directory in directories for path in directory.glob('*.db/ddb.db')}
            if len(candidates) > 1:
                raise ValueError('Multiple UVS design databases; configure --dbdir for this viewer')
            if candidates:
                database = resolve_workspace_path(workspace, candidates.pop().relative_to(workspace).as_posix(), must_exist=False)
                break
    if database is not None:
        # Do not pass database symlinks outside the selected workspace to UVD.
        for path in database.rglob('*'):
            if path.is_symlink():
                resolve_workspace_path(workspace, path.relative_to(workspace).as_posix(), must_exist=False)
    return database


def startup_script(payload: dict, unit: str | None, failure: Path) -> str:
    """Restore signals, window and cursor; report a Tcl error through a file for launch() to act on."""
    commands = []
    if payload['signals']:
        names = ' '.join(tcl_word(name) for name in payload['signals'])
        commands.append(f'util_wave_item -id primary -action addSignals -values [list {names}]')
    script = ('proc ucagent_run {script} {\n'
              '  if {[catch {uplevel #0 $script} failure]} {\n'
              '    set channel [open ' + tcl_word(str(failure)) + ' w]\n'
              '    puts $channel $failure\n    close $channel\n  }\n}\n')
    if unit is not None:
        commands += [
            # Display exactly one native tick: no cycle or assumed-ns conversion.
            f'util_wave_time -id primary -action setTimeUnit -value {unit}',
            f'util_wave_marker -id primary -action setMarkerValue -value {payload["cursor"]}/{unit} -name C -isMoving false',
        ]
    script += 'ucagent_run ' + tcl_word('\n'.join(commands)) + '\n'
    if unit is not None:
        # addSignals queues UVD's default zoom for the first signal; zooming now would be overwritten.
        zoom = f'util_wave_zoom -id primary -action zoomRange -timeRange {payload["start"]}-{payload["end"]}'
        script += 'after idle [list ucagent_run ' + tcl_word(zoom) + ']\n'
    return script


def launch(meta: Path, uvd: str, extra_args: list[str], *, workspace: Path | None = None,
           dbdir: Path | None = None) -> int:
    """Verify metadata, select its compiled design and restore the UVD view."""
    workspace = (workspace or Path.cwd()).resolve()
    meta = meta.resolve(strict=True)
    _, payload = load_waveform_metadata(workspace, meta.relative_to(workspace).as_posix())
    wave = (meta.parent / payload['waveform_file']).resolve(strict=True)
    database = find_database(workspace, meta.parent, payload, dbdir)
    check_signals(wave, payload['signals'])
    unit = native_unit(wave) if 'start' in payload else None
    # uvd writes uvgui.ini, wave.png and univistaLog/ into its cwd; keep them out of the workspace.
    with tempfile.TemporaryDirectory(prefix='ucagent-uvd-') as directory:
        failure = Path(directory) / 'failure'
        startup = Path(directory) / 'view.tcl'
        startup.write_text(startup_script(payload, unit, failure), encoding='utf-8')
        # Qt centres an unplaced window on Xpra's 8192x4096 root, outside the browser that attaches later.
        argv = [uvd, '-geometry', '1500x740+0+0', *extra_args, '-u', str(wave), '-s', str(startup),
                '--log_dir', str(Path(directory) / 'logs')]
        if database is not None:
            argv += ['-d', str(database)]
        process = subprocess.Popen(argv, cwd=directory)
        try:
            # uvd cannot be relied on to quit from Tcl: exit prompts to save signals, app_exit
            # refuses during background tasks, and neither carries an exit code.
            while process.poll() is None:
                if failure.exists() and failure.stat().st_size:
                    print(f'Cannot restore waveform view: {failure.read_text(encoding="utf-8").strip()}', file=sys.stderr)
                    return 1
                time.sleep(0.2)
            return process.returncode
        finally:
            process.kill()
            process.wait()


def main() -> int:
    """Parse configured argv and report actionable launcher failures to Xpra logs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meta', type=Path, required=True)
    parser.add_argument('--uvd', default='uvd')
    parser.add_argument('--dbdir', type=Path, help='Workspace-contained UVS design database directory')
    parser.add_argument('uvd_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    # Xpra ends sessions with SIGTERM: unwind so launch() kills uvd and the temporary directory goes.
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    try:
        extra = args.uvd_args[1:] if args.uvd_args[:1] == ['--'] else args.uvd_args
        return launch(args.meta, args.uvd, extra, dbdir=args.dbdir)
    except (OSError, ValueError, KeyError, TypeError, UsdbRuntimeError) as error:
        print(f'Cannot open waveform in UVD: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
