#coding=utf8

import urwid
import os
import readline
import sys
import io
import traceback
import signal
import time
import threading

from vagent.util.functions import fmt_time_stamp, fmt_time_deta
from vagent.util.log import YELLOW, RESET

class VerifyUI:
    """
    VerifyUI is a class that provides methods to verify the UI components of an application.
    It includes methods for verifying the existence of UI elements and their properties.
    """

    def __init__(self, vpdb, max_messages=1000, prompt="(UnityChip) ", gap_time=0.5):
        self.vpdb = vpdb
        self.console_input_cap = prompt
        self.content_task = urwid.SimpleListWalker([])
        self.content_stat = urwid.SimpleListWalker([])
        self.content_msgs = urwid.SimpleListWalker([])
        self.content_msgs_focus = 0
        self.content_msgs_maxln = max_messages
        self.box_task = urwid.ListBox(self.content_task)
        self.box_stat = urwid.ListBox(self.content_stat)
        self.box_msgs = urwid.ListBox(self.content_msgs)
        self.console_input = urwid.Edit(self.console_input_cap)
        self.console_input_busy = ["(wait.  )", "(wait.. )", "(wait...)"]
        self.console_input_busy_index = -1
        self.console_max_height = 15
        self.console_default_txt = "\n" * (self.console_max_height - 1)
        self.console_outbuffer = self.console_default_txt
        self.console_output = ANSIText(self.console_outbuffer)
        self.console_page_cache = None
        self.console_page_cache_index = 0
        self.content_task_fix_width = 40
        self.task_box_maxfiles = 5
        self.last_cmd = None
        self.last_key = None
        self.last_line = ""
        self.complete_remain = []
        self.complete_maxshow = 100
        self.complete_tips = "\nAvailable commands:\n"
        self.cmd_history_index = readline.get_current_history_length() + 1
        self._pdio = io.StringIO()
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self.gap_time = gap_time
        self.is_cmd_busy = False
        self.int_layout()
        self._handle_stdout_error()

    def exit(self, loop, user_data=None):
        """
        Exit the application gracefully.
        """
        self.vpdb.agent.unset_message_echo_handler()
        self._clear_stdout_error()
        raise urwid.ExitMainLoop()

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
            (self.content_task_fix_width, self.u_task_box),
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

    def update_top_pane(self):
        """
        Update the layout of top_pane to reflect the new value of content_asm_fix_width.
        """
        self.root.body.contents[0] = (
            urwid.Columns([
            (self.content_task_fix_width, self.u_task_box),
            ("weight", 20, self.u_llm_pip),
        ], dividechars=0),
            ('weight', 1)
        )
        self.loop.draw_screen()

    def update_info(self):
        self.content_task.clear()
        self.content_stat.clear()
        self.content_stat.append(urwid.Text(self.vpdb.api_status()))
        # task
        task_data = self.vpdb.api_task_list()
        self.content_task.append(urwid.Text(f"\n{task_data['mission_name']}\n", align='center'))
        current_index = task_data['task_index']
        for i, (task_name, task) in enumerate(task_data['task_list']["stage_list"]):
            task_desc = task["desc"]
            fail_count = task["fail_count"]
            color = None
            if i < current_index:
                color = "success_green"
            elif i == current_index:
                color = "norm_red"
            text = f"{i}: {task_name}\n  {task_desc} ({fail_count} fails)"
            if color:
                utxt = urwid.Text((color, text), align='left')
            else:
                utxt = urwid.Text(text, align='left')
            self.content_task.append(utxt)
        # changed files
        self.content_task.append(urwid.Text(f"\nChanged Files\n", align='center'))
        for d, t, f in self.vpdb.api_changed_files()[:self.task_box_maxfiles]:
            color = None
            mtime = fmt_time_stamp(t)
            if d < 180:
                color = "success_green"
                mtime += f" ({fmt_time_deta(d)})"
            self.content_task.append(urwid.Text((color, f"{mtime}:\n {f}"), align='left'))
        # Tools
        self.content_task.append(urwid.Text(f"\nTools Call\n", align='center'))
        tool_info = " ".join([f"{t[0]}({t[1]})" for t in self.vpdb.api_tool_status()])
        self.content_task.append(urwid.Text(tool_info, align='left'))

    def message_echo(self, msg, end="\n"):
        self.update_info()
        self.update_console_ouput()
        if not msg:
            return
        last_text = self.content_msgs[-1] if len(self.content_msgs) > 0 else None
        for i, line in enumerate((msg + end).split("\n")):
            if i== 0 and last_text is not None:
                last_text.original_widget.set_text(last_text.original_widget.get_text()[0] + line)
            else:
                self.content_msgs.append(urwid.AttrMap(ANSIText(line, align='left'), None, None))
        if len(self.content_msgs) > self.content_msgs_maxln:
            self.content_msgs[:] = self.content_msgs[-self.content_msgs_maxln:]
            self.content_msgs[-2].set_attr_map({None: 'body'})
            self.content_msgs[-1].set_attr_map({None: 'body'})
        msg_count = len(self.content_msgs)
        self.content_msgs_focus = msg_count - 1
        self.update_messages_focus()

    def update_messages_focus(self):
        msg_count = len(self.content_msgs)
        if msg_count < 1:
            return
        self.content_msgs.get_focus()[0].set_attr_map({None: 'body'})
        self.content_msgs.set_focus(self.content_msgs_focus)
        self.content_msgs.get_focus()[0].set_attr_map({None: 'yellow'})
        self.u_messages_box.set_title(f"Messages ({self.content_msgs_focus}/{msg_count})")

    def set_messages_focus(self, delta):
        """
        Set the focus of the messages list.
        :param delta: The change in focus, can be positive or negative.
        """
        self.content_msgs_focus += delta
        self.content_msgs_focus = max(0, min(self.content_msgs_focus, len(self.content_msgs) - 1))
        self.update_messages_focus()

    def _get_output(self, txt="", clear=False):
        if clear:
            self.console_outbuffer = txt
        if txt:
            buffer = (self.console_outbuffer[-1] if self.console_outbuffer else "") + txt.replace("\t", "    ")
            # FIXME: why need remove duplicated '\n' ?
            buffer = buffer.replace('\r', "\n").replace("\n\n", "\n")
            if self.console_outbuffer:
                self.console_outbuffer = self.console_outbuffer[:-1] + buffer
            else:
                self.console_outbuffer = buffer
            self.console_outbuffer = "\n".join(self.console_outbuffer.split("\n")[-self.console_max_height:])
        return self.console_outbuffer

    def handle_input(self, key):
        """
        Handle user input from the console.
        """
        cmd = self.console_input.get_edit_text().lstrip()
        if key == 'esc':
            if self.console_output_page_scroll("exit_page"):
                return
            self.exit(None)
        elif key == 'enter':
            self.console_input.set_edit_text("")
            if cmd in ("q", "Q", "exit", "quit"):
                self.exit(None)
                return
            if cmd:
                self.last_cmd = cmd
            elif self.last_cmd:
                cmd = self.last_cmd
            else:
                self.update_info()
                return
            self.console_output.set_text(self._get_output(cmd + "\n"))
            self.process_command(cmd)
            self.update_info()
            self.last_line = cmd
        elif key == 'tab':
            try:
                self.complete_cmd(cmd)
            except Exception as e:
                self.console_output.set_text(self._get_output(f"{YELLOW}Complete cmd Error: {str(e)}\n{traceback.format_exc()}{RESET}\n"))
        elif key == 'ctrl up':
            self.console_max_height += 1
            new_text = self.console_outbuffer.split("\n")
            new_text.insert(0, "")
            self.console_outbuffer = "\n".join(new_text)
            self.console_output.set_text(self._get_output())
        elif key == 'ctrl down':
            self.console_max_height -= 1
            new_text = self.console_outbuffer.split("\n")
            new_text = new_text[1:]
            self.console_outbuffer = "\n".join(new_text)
            self.console_output.set_text(self._get_output())
        elif key == 'ctrl left':
            self.content_task_fix_width -= 1
            self.update_top_pane()
        elif key == 'ctrl right':
            self.content_task_fix_width += 1
            self.update_top_pane()
        elif key == 'shift up':
            self.set_messages_focus(-1)
        elif key == 'shift down':
            self.set_messages_focus(1)
        elif key == "up":
            if self.console_output_page_scroll(1):
                return
            self.cmd_history_index -= 1
            self.cmd_history_index = max(0, self.cmd_history_index)
            hist_cmd = self.cmd_history_get(self.cmd_history_index)
            if hist_cmd is not None:
                self.console_input.set_edit_text(hist_cmd)
                self.console_input.set_edit_pos(len(hist_cmd))
        elif key == "down":
            if self.console_output_page_scroll(-1):
                return
            self.cmd_history_index += 1
            self.cmd_history_index = min(self.cmd_history_index, readline.get_current_history_length() + 1)
            hist_cmd = self.cmd_history_get(self.cmd_history_index)
            if hist_cmd is not None:
                self.console_input.set_edit_text(hist_cmd)
                self.console_input.set_edit_pos(len(hist_cmd))
        self.last_key = key
        return True

    def cmd_history_get(self, index):
        current_history_length = readline.get_current_history_length()
        if index < 1 or index > current_history_length:
            return None
        return readline.get_history_item(index)

    def cmd_history_set(self, cmd):
        pre_cmd_index = readline.get_current_history_length()
        if not (pre_cmd_index > 0 and readline.get_history_item(pre_cmd_index) == cmd):
            readline.add_history(cmd)
        self.cmd_history_index = readline.get_current_history_length() + 1

    def process_command(self, cmd):
        if cmd == "clear":
            self.console_output.set_text(self._get_output(self.console_default_txt, clear=True))
            return
        scrowl_ret = False
        if cmd.startswith("!"):
            cmd  = cmd[1:]
            scrowl_ret = True
        self.cmd_history_set(cmd)
        self.console_input_busy_index = 0

        self.original_sigint = signal.getsignal(signal.SIGINT)
        def _sigint_handler(s, f):
            self.vpdb._sigint_handler(s, f)
        signal.signal(signal.SIGINT, _sigint_handler)
        self.root.focus_part = None
        self._execute_cmd_in_thread(cmd, scrowl_ret)

    def _execute_cmd_in_thread(self, cmd, scrowl_ret):
        """
        Execute a command in a separate thread to avoid blocking the main loop.
        """
        self.is_cmd_busy = True
        def run_cmd():
            try:
                self.vpdb.onecmd(cmd)
            except Exception as e:
                self.console_output.set_text(self._get_output(f"{YELLOW}Command Error: {str(e)}\n{traceback.format_exc()}{RESET}\n"))
            self.loop.set_alarm_in(0.1, self._on_cmd_complete, scrowl_ret)
        thread = threading.Thread(target=run_cmd)
        thread.start()

    def _on_cmd_complete(self, loop, scrowl_ret):
        self.is_cmd_busy = False
        self.console_input_busy_index = -1
        signal.signal(signal.SIGINT, self.original_sigint)
        self.root.focus_part = 'footer'
        self.update_console_ouput(scrowl_ret)

    def _auto_update_ui(self, loop, user_data=None):
        """
        Automatically update the UI at regular intervals.
        This is useful for refreshing the display without user input.
        """
        self.update_console_ouput(True)
        loop.set_alarm_in(1.0, self._auto_update_ui)

    def _process_batch_cmd(self):
        p_count = 0
        while len(self.vpdb.init_cmd) > 0:
            cmd = self.vpdb.init_cmd.pop(0)
            if cmd.startswith("tui"):
                continue
            self.console_input.set_edit_text(cmd)
            time.sleep(self.gap_time)
            self.console_input.set_edit_text("")
            self.process_command(cmd)
            if self.vpdb.agent.is_break():
                break
            p_count += 1
        self.console_output.set_text(self._get_output(f"\n\n{YELLOW}Processed {p_count} commands in batch mode.{RESET}\n"))

    def check_exec_batch_cmds(self, loop, user_data=None):
        self._process_batch_cmd()

    def complete_cmd(self, line):
        if self.last_key == "tab" and self.last_line == line:
            end_text = ""
            cmd = self.complete_remain
            if not cmd:
                return
            if len(cmd) > self.complete_maxshow:
                end_text = f"\n...({len(cmd) - self.complete_maxshow} more)"
            self.console_output.set_text(self._get_output() + self.complete_tips + " ".join(cmd[:self.complete_maxshow]) + end_text)
            self.complete_remain = cmd[self.complete_maxshow:]
            return
        self.complete_remain = []
        state = 0
        cmp = []
        cmd, args, _ = self.vpdb.parseline(line)
        if " " in line:
            complete_func = getattr(self.vpdb, f"complete_{cmd}", None)
            if complete_func:
                arg = args
                if " " in args:
                    arg = args.split()[-1]
                idbg = line.find(arg)
                cmp = complete_func(arg, line, idbg, len(line))
        else:
            while True:
                cmp_item = self.vpdb.complete(line, state)
                if not cmp_item:
                    break
                state += 1
                cmp.append(cmp_item)
        if cmp:
            prefix = os.path.commonprefix(cmp)
            full_cmd = line[:line.rfind(" ") + 1] if " " in line else ""
            if prefix:
                full_cmd += prefix
            else:
                full_cmd = line
            self.console_input.set_edit_text(full_cmd)
            self.console_input.set_edit_pos(len(full_cmd))
            end_text = ""
            if len(cmp) > self.complete_maxshow:
                self.complete_remain = cmp[self.complete_maxshow:]
                end_text = f"\n...({len(self.complete_remain)} more)"
            self.console_output.set_text(self._get_output() + self.complete_tips + " ".join(cmp[:self.complete_maxshow]) + end_text)

    def console_output_page_scroll(self, deta):
        if self.console_page_cache is None:
            return False
        if deta  == "exit_page":
            if self.console_page_cache is not None:
                self.console_page_cache = None
                self.console_page_cache_index = 0
                self.console_output.set_text(self._get_output())
                self.console_input.set_caption(self.console_input_cap)
                self.root.focus_part = 'footer'
        else:
            self.console_page_cache_index += deta
            self.console_page_cache_index = min(self.console_page_cache_index, len(self.console_page_cache) - self.console_max_height)
            self.console_page_cache_index = max(self.console_page_cache_index, 0)
        self.update_console_ouput(False)
        return True

    def update_console_ouput(self, need_scroll=False):
        if self.console_page_cache is not None:
            pindex = self.console_page_cache_index
            text_data = "\n"+"\n".join(self.console_page_cache[pindex:pindex + self.console_max_height])
        else:
            text_data = self._get_pdb_out()
            text_lines = text_data.split("\n")
            # just check the last output check
            if len(text_lines) > self.console_max_height and need_scroll:
                self.console_page_cache = text_lines
                self.console_page_cache_index = 0
                text_data = "\n"+"\n".join(text_lines[:self.console_max_height])
                self.console_input.set_caption(f"<Up/Down: scroll, Esc: exit>")
                self.root.focus_part = None
        self.console_output.set_text(self._get_output(text_data))
        if self.console_input_busy_index >= 0:
            self.console_input_busy_index += 1
            n = self.console_input_busy_index % len(self.console_input_busy)
            self.console_input.set_caption(self.console_input_busy[n])
        else:
            self.console_input.set_caption(self.console_input_cap)
        self.loop.screen.clear()
        self.loop.draw_screen()

    def _get_pdb_out(self):
        self._pdio.flush()
        output = self._pdio.getvalue()
        self._pdio.truncate(0)
        self._pdio.seek(0)
        return output

    def _handle_stdout_error(self):
        if getattr(self.vpdb, "stdout", None):
            self.old_stdout = self.vpdb.stdout
            self.vpdb.stdout = self._pdio
            self.sys_stdout = sys.stdout
            sys.stdout = self._pdio
        else:
            self.old_stdout = sys.stdout
            sys.stdout = self._pdio
        if getattr(self.vpdb, "stderr", None):
            self.old_stderr = self.vpdb.stderr
            self.vpdb.stderr = self._pdio
            self.sys_stderr = sys.stderr
            sys.stderr = self._pdio
        else:
            self.old_stderr = sys.stderr
            sys.stderr = self._pdio

    def _clear_stdout_error(self):
        if getattr(self, "old_stdout", None):
            if getattr(self.vpdb, "stdout", None):
                self.vpdb.stdout = self.old_stdout
                sys.stdout = self.sys_stdout
            else:
                sys.stdout = self.old_stdout
        if getattr(self, "old_stderr", None):
            if getattr(self.vpdb, "stderr", None):
                self.vpdb.stderr = self.old_stderr
                sys.stderr = self.sys_stderr
            else:
                sys.stderr = self.old_stderr


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
    loop.set_alarm_in(0.1, app.check_exec_batch_cmds)
    loop.set_alarm_in(1.0, app._auto_update_ui)
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
