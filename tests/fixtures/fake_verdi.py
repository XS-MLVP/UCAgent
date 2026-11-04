#!/usr/bin/env python3
"""Graphical Verdi test double executing real startup Tcl against explicit JSON fixtures.

The selected .fsdb is test JSON, never a decoded proprietary waveform. Only the
launcher commands exercised here are implemented; Xpra and its client stay real.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tkinter as tk


class FakeVerdi:
    """Expose nWave startup commands and draw their resulting state in a Tk window."""

    def __init__(self, root, args):
        """Register actual Tcl callbacks before evaluating the launcher's startup file."""
        self.root = root
        self.args = args
        self.fixture = None
        self.state = dict(application='fake_verdi', pid=os.getpid(), display=os.environ.get('DISPLAY'),
                          waveform=None, sources=args.sv, signals=[], native_unit=None,
                          display_unit=None, start=None, end=None, cursor=None, reviewed=0)
        self.status = tk.StringVar(value='Waiting for startup Tcl')
        root.title('fake_verdi')
        root.geometry('1100x650')
        root.configure(background='#101722')
        tk.Label(root, text='fake_verdi — Xpra integration test', foreground='#e6edf7',
                 background='#172338', font=('DejaVu Sans', 18, 'bold')).pack(fill='x', pady=10)
        tk.Label(root, textvariable=self.status, foreground='#afc5e3', background='#101722',
                 anchor='w', justify='left').pack(fill='x', padx=20)
        self.canvas = tk.Canvas(root, background='#101722', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=16, pady=10)
        tk.Button(root, text='Mark reviewed (R)', command=self.review).pack(pady=10)
        root.bind('<Key-r>', self.review)
        root.bind('<Key-R>', self.review)
        callbacks = {'wvCreateWindow': self.create_window, 'wvOpenFile': self.open_file,
                     'wvAddSignal': self.add_signal, 'wvGetFileTimeUnit': self.get_time_unit,
                     'wvSetWindowTimeUnit': self.set_time_unit, 'wvZoom': self.zoom,
                     'wvSetCursor': self.set_cursor,
                     'verdiSetPrefEnv': lambda *args: '', 'wvRaiseWindow': lambda *args: root.lift()}
        for name, callback in callbacks.items():
            root.tk.createcommand(name, callback)
        root.tk.eval(args.play.read_text(encoding='utf-8'))
        if self.fixture is None:
            raise ValueError('Startup Tcl did not open the fixture waveform')
        root.bind('<Configure>', lambda event: self.draw() if event.widget is root else None)
        root.update_idletasks()
        self.draw()
        self.publish()
        print('FAKE_VERDI_READY', flush=True)

    def create_window(self):
        """Return the stable Tcl identity for the real Tk waveform window."""
        return 'wave1'

    def open_file(self, *arguments):
        """Read only an explicitly marked fixture and preserve the exact opened path."""
        path = Path(arguments[-1]).resolve(strict=True)
        fixture = json.loads(path.read_text(encoding='utf-8'))
        if fixture.get('fake_verdi_fixture') != 1 or not fixture.get('signals'):
            raise ValueError('fake_verdi requires an explicitly marked test waveform fixture')
        self.fixture = fixture
        self.state.update(waveform=str(path), native_unit=fixture['native_unit'])
        return str(path)

    def add_signal(self, *arguments):
        """Reject absent signals instead of silently displaying a fabricated trace."""
        signal = arguments[-1]
        if self.fixture is None or signal not in self.fixture['signals']:
            return 0
        self.state['signals'].append(signal)
        return 1

    def get_time_unit(self, *arguments):
        """Return the fixture's actual native scale to the unchanged launch script."""
        return self.fixture['native_unit']

    def set_time_unit(self, *arguments):
        """Accept only the fixture's actual native tick for display restoration."""
        unit = ''.join(arguments[-2:])
        if unit != self.fixture['native_unit']:
            return 0
        self.state['display_unit'] = unit
        return 1

    def zoom(self, *arguments):
        """Capture exact decimal native timestamps without floating point conversion."""
        start, end = arguments[-2:]
        if int(start) > int(end):
            return 0
        self.state.update(start=start, end=end)
        return 1

    def set_cursor(self, *arguments):
        """Restore the exact requested cursor before drawing the application."""
        self.state['cursor'] = arguments[-1]
        return 1

    def review(self, event=None):
        """Record an actual remote mouse or keyboard interaction for browser acceptance."""
        self.state['reviewed'] += 1
        self.draw()
        self.publish()

    def publish(self):
        """Atomically expose application state only after Tk has rendered the window."""
        self.state['window_id'] = self.root.winfo_id()
        path = self.args.fake_state
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def draw(self):
        """Render selected fixture transitions, native window bounds and the cursor."""
        if self.fixture is None:
            return
        state = self.state
        reviewed = ' | Reviewed' if state['reviewed'] else ''
        self.root.title('fake_verdi | ' + Path(state['waveform']).name + reviewed)
        self.status.set('Waveform: ' + state['waveform'] + '\nNative tick: ' + str(state['native_unit']) +
                        '    Window: ' + str(state['start']) + ' … ' + str(state['end']) +
                        '    Cursor: ' + str(state['cursor']) + '\nRTL: ' + ', '.join(state['sources']))
        canvas = self.canvas
        canvas.delete('all')
        left, right = 300, max(700, canvas.winfo_width() - 30)
        start = int(state['start'] or 0)
        end = int(state['end'] or self.fixture['end'])
        span = max(1, end - start)
        for tick in range(6):
            x = left + (right - left) * tick / 5
            canvas.create_line(x, 30, x, 400, fill='#29374b')
            canvas.create_text(x, 16, text=str(start + span * tick // 5), fill='#91a6c1')
        for row, name in enumerate(state['signals']):
            top = 55 + row * 75
            canvas.create_text(8, top + 15, anchor='w', text=name, fill='#e6edf7')
            transitions = self.fixture['signals'][name]
            points = []
            current = transitions[0][1]
            for timestamp, value in transitions:
                timestamp = int(timestamp)
                if timestamp <= start:
                    current = value
                    continue
                if timestamp > end:
                    break
                if not points:
                    points += [left, top + (30 if not int(current) else 0)]
                x = left + (timestamp - start) * (right - left) / span
                points += [x, top + (30 if not int(current) else 0),
                           x, top + (30 if not int(value) else 0)]
                current = value
            if not points:
                points = [left, top + (30 if not int(current) else 0)]
            points += [right, top + (30 if not int(current) else 0)]
            canvas.create_line(*points, fill='#62d6ab', width=2)
        if state['cursor'] is not None:
            x = left + (int(state['cursor']) - start) * (right - left) / span
            canvas.create_line(x, 30, x, 400, fill='#edb966', width=2)
            canvas.create_text(x + 5, 420, anchor='w', text='cursor ' + state['cursor'], fill='#edb966')


def main():
    """Accept the same startup boundary as Verdi plus an explicit test state path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fake-state', type=Path, required=True)
    parser.add_argument('-sv', nargs='+', default=[])
    parser.add_argument('-logdir')
    parser.add_argument('-play', type=Path, required=True)
    args = parser.parse_args()
    root = tk.Tk()
    try:
        FakeVerdi(root, args)
        root.mainloop()
        return 0
    except (OSError, ValueError, KeyError, tk.TclError) as error:
        print('fake_verdi startup failed: ' + str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        root.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
