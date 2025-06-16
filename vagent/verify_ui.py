#coding=utf8

import urwid


class VerifyUI:
    """
    VerifyUI is a class that provides methods to verify the UI components of an application.
    It includes methods for verifying the existence of UI elements and their properties.
    """

    def __init__(self, vpdb, prompt="(UnityChip) "):
        self.vpdb = vpdb
        self.console_input_cap = prompt
        self.content_task = urwid.SimpleListWalker([])
        self.content_stat = urwid.SimpleListWalker([])
        self.content_msgs = urwid.SimpleListWalker([])
        self.box_task = urwid.ListBox(self.content_task)
        self.box_stat = urwid.ListBox(self.content_stat)
        self.box_msgs = urwid.ListBox(self.content_msgs)
        self.console_input = urwid.Edit(self.console_input_cap)
        self.console_default_txt = "\n\n\n\n"
        self.console_outbuffer = self.console_default_txt
        self.console_output = ANSIText(self.console_outbuffer)
        self.int_layout()

    def int_layout(self):
        self.u_task_box = urwid.LineBox(self.box_task,
            title=u"Mission")
        self.u_status_box = urwid.LineBox(self.box_stat,
            title=u"Status")
        self.u_messages_box = urwid.LineBox(self.box_msgs,
            title=u"Messages")

        self.u_llm_pip = urwid.Pile([
           (5, self.u_status_box),
           self.u_messages_box
        ])

        self.top_pane = urwid.Columns([
            (30, self.u_task_box),
            ("weight", 20, self.u_llm_pip),
        ], dividechars=0)

        console_box = urwid.LineBox(
            urwid.Pile([
                ("flow", self.console_output),
                ('flow', self.console_input),
            ]),
            title="Console")

        self.root = urwid.Frame(
            body=urwid.Pile([
                ('weight', 1, self.top_pane)
            ]),
            footer=console_box,
            focus_part="footer"
        )
        self.update_info()

    def update_info(self):
        self.content_task.clear()
        self.content_stat.clear()
        self.content_msgs.clear()
        self.content_stat.append(urwid.Text(" LLM: Qwen3-32B    AI-Message Count: 0    Tool-Message Count: 0"))
        self.content_stat.append(urwid.Text(" Tools: "))
        self.content_stat.append(urwid.Text(" Start Time: "))

    def exit(self, loop, user_data=None):
        """
        Exit the application gracefully.
        """
        raise urwid.ExitMainLoop()

    def handle_input(self, key):
        """
        Handle user input from the console.
        """
        if key in ('q', 'Q', 'esc'):
            self.exit(None)
        elif key == 'enter':
            text = self.console_input.get_edit_text().strip()
            if text == "update":
                self.update_info()
        else:
            # Allow other keys to be processed by urwid
            return False
        return True

def enter_simple_tui(pdb):
    import signal
    app = VerifyUI(pdb)
    loop = urwid.MainLoop(
        app.root,
        palette=palette,
        unhandled_input=app.handle_input,
        handle_mouse=False
    )
    app.loop = loop
    original_sigint = signal.getsignal(signal.SIGINT)
    def _sigint_handler(s, f):
        loop.set_alarm_in(0.0, app.exit)
    signal.signal(signal.SIGINT, _sigint_handler)
    loop.run()
    signal.signal(signal.SIGINT, original_sigint)


palette = [
    ('success_green',  'light green', 'black'),
    ('norm_red',       'light red',   'black'),
    ('error_red',      'light red',   'black'),
    ('body',           'white',       'black'),
    ('divider',        'white',       'black'),
    ('border',         'white',       'black'),
    # Add ANSI color mappings
    ('black',          'black',       'black'),
    ('dark red',       'dark red',    'black'),
    ('dark green',     'dark green',  'black'),
    ('brown',          'brown',       'black'),
    ('dark blue',      'dark blue',   'black'),
    ('dark magenta',   'dark magenta','black'),
    ('dark cyan',      'dark cyan',   'black'),
    ('light gray',     'light gray',  'black'),
    ('dark gray',      'dark gray',   'black'),
    ('light red',      'light red',   'black'),
    ('light green',    'light green', 'black'),
    ('yellow',         'yellow',      'black'),
    ('light blue',     'light blue',  'black'),
    ('light magenta',  'light magenta','black'),
    ('light cyan',     'light cyan',  'black'),
    ('white',          'white',       'black'),
]

import re
class ANSIText(urwid.Text):
    """
    A subclass of urwid.Text that supports ANSI color codes.
    """
    ANSI_COLOR_MAP = {
        '30': 'black',
        '31': 'dark red',
        '32': 'dark green',
        '33': 'brown',
        '34': 'dark blue',
        '35': 'dark magenta',
        '36': 'dark cyan',
        '37': 'light gray',
        '90': 'dark gray',
        '91': 'light red',
        '92': 'light green',
        '93': 'yellow',
        '94': 'light blue',
        '95': 'light magenta',
        '96': 'light cyan',
        '97': 'white',
    }

    ANSI_ESCAPE_RE = re.compile(r'\x1b\[(\d+)(;\d+)*m')

    def __init__(self, text='', align='left'):
        super().__init__('', align)
        self.set_text(text)

    def set_text(self, text):
        """
        Parse the ANSI text and set it with urwid attributes.
        """
        parsed_text = self._parse_ansi(text)
        super().set_text(parsed_text)

    def _parse_ansi(self, text):
        """
        Parse ANSI escape sequences and convert them to urwid attributes.
        """
        segments = []
        current_attr = None
        pos = 0

        for match in self.ANSI_ESCAPE_RE.finditer(text):
            start, end = match.span()
            if start > pos:
                segments.append((current_attr, text[pos:start]))
            ansi_codes = match.group(0)
            current_attr = self._ansi_to_attr(ansi_codes)
            pos = end

        if pos < len(text):
            segments.append((current_attr, text[pos:]))

        return segments

    def _ansi_to_attr(self, ansi_code):
        """
        Convert ANSI escape codes to urwid attributes.
        """
        codes = ansi_code[2:-1].split(';')
        if len(codes) == 0:
            return None  # Reset attributes

        fg_code = codes[0]
        fg_color = self.ANSI_COLOR_MAP.get(fg_code, None)
        if fg_color:
            return fg_color
        return None
