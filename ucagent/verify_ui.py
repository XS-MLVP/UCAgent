# -*- coding: utf-8 -*-
"""Terminal User Interface for UCAgent verification."""

import urwid
import os
import readline
import sys
import io
import traceback
import signal
import time
import threading

from ucagent.util.functions import fmt_time_stamp, fmt_time_deta
from ucagent.util.log import YELLOW, RESET
from collections import OrderedDict

class VerifyUI:
    """
    VerifyUI is a class that provides methods to verify the UI components of an application.
    It includes methods for verifying the existence of UI elements and their properties.
    """

    def __init__(self, vpdb, max_messages=1000, prompt="(UnityChip) ", gap_time=0.5):
        self.cfg = vpdb.agent.cfg
        self.vpdb = vpdb
        self.console_input_cap = prompt
        # w_task, h_console, h_status
        self.content_task_fix_width = self.cfg.get_value("tui.task_width", 84)
        self.console_max_height = self.cfg.get_value("tui.console_height", 13)
        self.status_content_fix_height = self.cfg.get_value("tui.status_height", 7)
        # Content and Boxes
        self.content_task = urwid.SimpleListWalker([])
        self.content_stat = urwid.SimpleListWalker([])
        self.content_msgs = urwid.SimpleListWalker([])
        self.content_msgs_focus = 0
        self.content_msgs_scroll = False
        self.content_msgs_maxln = max(100, max_messages)  # Ensure minimum value
        self.content_msgs_buffer = None
        self.box_task = urwid.ListBox(self.content_task)
        self.box_stat = urwid.ListBox(self.content_stat)
        self.box_msgs = urwid.ListBox(self.content_msgs)
        self.console_input = urwid.Edit(self.console_input_cap)
        self.console_input_busy = ["(wait.  )", "(wait.. )", "(wait...)"]
        self.console_input_busy_index = -1
        self.console_default_txt = "\n" * (self.console_max_height - 1)
        self.console_outbuffer = self.console_default_txt
        self.console_output = ANSIText(self.console_outbuffer)
        self.console_output_box = urwid.BoxAdapter(
            urwid.Filler(self.console_output, valign='top'),
            self.console_max_height
        )
        self.console_page_cache = None
        self.console_page_cache_index = 0
        self.task_box_maxfiles = max(1, 5)  # Ensure minimum value
        self.last_cmd = None
        self.last_key = None
        self.last_line = ""
        self.cmd_history_index = readline.get_current_history_length() + 1
        self._pdio = io.StringIO()
        self._ui_lock = threading.Lock()  # Add lock for thread safety
        self.vpdb.agent.set_message_echo_handler(self.message_echo)
        self.gap_time = max(0.1, gap_time)  # Ensure minimum gap time
        self.is_cmd_busy = False
        self.vpdb.agent._mcps_logger = UIMsgLogger(self, level="INFO")
        self.deamon_cmds = OrderedDict()
        self.loop = None  # Initialize loop to None
        # status
        self._is_auto_updating_ui = False
        self.int_layout()
        self._handle_stdout_error()

    def _exit_cleanup(self):
        """
        Clean up resources before exiting.
        """
        self.vpdb.agent.unset_message_echo_handler()
        self.vpdb.agent._mcps_logger = None
        self._clear_stdout_error()

    def exit(self, loop, user_data=None):
        """
        Exit the application gracefully.
        """
        self._exit_cleanup()
        raise urwid.ExitMainLoop()

    def int_layout(self):
        self.u_task_box = urwid.LineBox(self.box_task,
            title=u"Mission")
        self.u_status_box = urwid.LineBox(self.box_stat,
            title=u"Status")
        self.u_messages_box = urwid.LineBox(self.box_msgs,
            title=u"Messages")

        self.u_llm_pip = urwid.Pile([
           (self.status_content_fix_height, self.u_status_box),
           self.u_messages_box
        ])

        self.top_pane = urwid.Columns([
            (self.content_task_fix_width, self.u_task_box),
            ("weight", 20, self.u_llm_pip),
        ], dividechars=0)

        console_box = urwid.LineBox(
            urwid.Pile([
                self.console_output_box,
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
        Update the layout of top_pane to reflect the new value of content_task_fix_width.
        """
        try:
            # Ensure width is within reasonable bounds
            self.content_task_fix_width = max(10, min(self.content_task_fix_width, 200))
            self.status_content_fix_height = max(3, min(self.status_content_fix_height, 100))
            # Update status height in the pile
            self.u_llm_pip = urwid.Pile([
               (self.status_content_fix_height, self.u_status_box),
               self.u_messages_box
            ])
            # Update the layout
            self.root.body.contents[0] = (
                urwid.Columns([
                (self.content_task_fix_width, self.u_task_box),
                ("weight", 20, self.u_llm_pip),
            ], dividechars=0),
                ('weight', 1)
            )
            
            # Safely redraw screen if loop exists
            if hasattr(self, 'loop') and self.loop is not None:
                try:
                    self.loop.draw_screen()
                except:
                    # If draw_screen fails, we'll skip it - the screen will update later
                    pass
        except Exception as e:
            # If update fails, reset to a safe width and try again
            try:
                self.content_task_fix_width = 40  # Reset to default
                self.root.body.contents[0] = (
                    urwid.Columns([
                    (self.content_task_fix_width, self.u_task_box),
                    ("weight", 20, self.u_llm_pip),
                ], dividechars=0),
                    ('weight', 1)
                )
            except:
                # If this also fails, just ignore - the layout will remain as is
                pass

    def update_info(self):
        self.content_task.clear()
        self.content_stat.clear()
        w_task, h_console, h_status = self.content_task_fix_width, self.console_max_height, self.status_content_fix_height
        self.content_stat.append(UCText(self.vpdb.api_status() + f"\nWHH({w_task},{h_console},{h_status})"))
        # task
        task_data = self.vpdb.api_mission_info()
        for i, text in enumerate(task_data):
            if i == 0:
                self.content_task.append(ANSIText(text, align='center'))
                continue
            self.content_task.append(ANSIText(text, align='left'))
        # changed files
        self.content_task.append(UCText(f"\nChanged Files\n", align='center'))
        for d, t, f in self.vpdb.api_changed_files()[:self.task_box_maxfiles]:
            color = None
            mtime = fmt_time_stamp(t)
            if d < 180:
                color = "success_green"
                mtime += f" ({fmt_time_deta(d)})"
            self.content_task.append(UCText((color, f"{mtime}: {f}"), align='left'))
        # Tools
        self.content_task.append(UCText(f"\nTools Call\n", align='center'))
        tool_info = ""
        for name, count, busy in self.vpdb.api_tool_status():
            if busy:
                tool_info += f"{YELLOW}{name}({count}){RESET} "
            else:
                tool_info += f"{name}({count}) "
        self.content_task.append(ANSIText(tool_info, align='left'))
        # Deamon Commands
        if self.deamon_cmds:
            self.content_task.append(UCText(f"\nDeamon Commands\n", align='center'))
            ntime = time.time()
            self.content_task.append(UCText("\n".join([f"{cmd}: {fmt_time_stamp(key)} - {fmt_time_deta(ntime - key, True)}" for key, cmd in self.deamon_cmds.items()]),
                                                align='left'))

    def message_echo(self, msg, end="\n"):
        # Use lock to prevent concurrent modifications
        with self._ui_lock:
            try:
                self.update_info()
                self.update_console_ouput()
                if not msg:
                    return
                
                # Thread-safe message handling
                if self.content_msgs_scroll:
                    if self.content_msgs_buffer is None:
                        self.content_msgs_buffer = ""
                    self.content_msgs_buffer += msg
                    max_buffer_size = 1024*self.content_msgs_maxln
                    if len(self.content_msgs_buffer) > max_buffer_size:
                        self.content_msgs_buffer = self.content_msgs_buffer[-max_buffer_size:]
                    return
                if self.content_msgs_buffer is not None:
                    msg = self.content_msgs_buffer + msg
                self.content_msgs_buffer = None
                try:
                    last_text = self.content_msgs[-1] if len(self.content_msgs) > 0 else None
                    for i, line in enumerate((msg + end).split("\n")):
                        try:
                            if i == 0 and last_text is not None:
                                # Safely append to the last message
                                try:
                                    current_text = last_text.original_widget.get_text()[0]
                                    last_text.original_widget.set_text(current_text + line)
                                except Exception as e:
                                    self.console_output.set_text(self._get_output(
                                        YELLOW + str(e) + RESET + "\n"))
                                    # If appending fails, create a new message
                                    self.content_msgs.append(urwid.AttrMap(ANSIText(line, align='left'), None, None))
                            else:
                                self.content_msgs.append(urwid.AttrMap(ANSIText(line, align='left'), None, None))
                        except Exception:
                            # If creating widget fails, skip this line
                            continue
                    
                    # Safely trim message list
                    try:
                        if len(self.content_msgs) > self.content_msgs_maxln:
                            self.content_msgs[:] = self.content_msgs[-self.content_msgs_maxln:]
                    except Exception:
                        pass
                    
                    # Update focus if not scrolling
                    try:
                        if not self.content_msgs_scroll:
                            msg_count = len(self.content_msgs)
                            if msg_count > 0:
                                self.content_msgs_focus = msg_count - 1
                            else:
                                self.content_msgs_focus = 0
                    except Exception:
                        pass
                    
                    # Update focus display
                    self.update_messages_focus()
                    
                except Exception as e:
                    # If message handling completely fails, just ignore this message
                    pass
            except Exception as e:
                # Complete fallback - ignore the message
                pass

    def update_messages_focus(self):
        try:
            msg_count = len(self.content_msgs)
            if msg_count < 1:
                return
            
            # Ensure focus index is within valid range
            self.content_msgs_focus = max(0, min(self.content_msgs_focus, msg_count - 1))
            
            # Reset all message attributes in the visible range
            for i in range(max(0, self.content_msgs_focus - 5), 
                          min(msg_count, self.content_msgs_focus + 6)):
                try:
                    if i < msg_count and self.content_msgs[i] is not None:
                        self.content_msgs[i].set_attr_map({None: 'body'})
                except Exception:
                    continue
            
            # Set focus and highlight current message
            try:
                if 0 <= self.content_msgs_focus < msg_count:
                    self.content_msgs.set_focus(self.content_msgs_focus)
                    focused_item = self.content_msgs.get_focus()
                    if focused_item and len(focused_item) > 0 and focused_item[0] is not None:
                        focused_item[0].set_attr_map({None: 'yellow'})
            except Exception:
                # If setting focus fails, try to reset to a safe state
                if msg_count > 0:
                    self.content_msgs_focus = msg_count - 1
                    try:
                        self.content_msgs.set_focus(self.content_msgs_focus)
                    except:
                        pass
            
            # Update title
            try:
                self.u_messages_box.set_title(f"Messages ({self.content_msgs_focus + 1}/{msg_count})")
            except:
                self.u_messages_box.set_title("Messages")
                
        except Exception as e:
            # Fallback: reset to safe state
            try:
                msg_count = len(self.content_msgs)
                if msg_count > 0:
                    self.content_msgs_focus = msg_count - 1
                    self.u_messages_box.set_title(f"Messages ({msg_count})")
                else:
                    self.content_msgs_focus = 0
                    self.u_messages_box.set_title("Messages (0)")
            except:
                pass

    def set_messages_focus(self, delta):
        """
        Set the focus of the messages list.
        :param delta: The change in focus, can be positive or negative.
        """
        try:
            msg_count = len(self.content_msgs)
            if msg_count <= 0:
                self.content_msgs_focus = 0
                self.content_msgs_scroll = False
                return
                
            self.content_msgs_scroll = True
            old_focus = self.content_msgs_focus
            self.content_msgs_focus += delta
            
            # Ensure the focus stays within bounds
            self.content_msgs_focus = max(0, min(self.content_msgs_focus, msg_count - 1))
            
            # Only update if focus actually changed
            if old_focus != self.content_msgs_focus:
                self.update_messages_focus()
        except Exception as e:
            # Reset to safe state on error
            try:
                msg_count = len(self.content_msgs)
                if msg_count > 0:
                    self.content_msgs_focus = max(0, min(self.content_msgs_focus, msg_count - 1))
                else:
                    self.content_msgs_focus = 0
                self.content_msgs_scroll = False
            except:
                self.content_msgs_focus = 0
                self.content_msgs_scroll = False

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
            if self.console_outbuffer:
                obuffer = self.console_outbuffer.split("\n")
                if len(obuffer) > self.content_msgs_maxln:
                    self.console_outbuffer = "\n".join(obuffer[-self.content_msgs_maxln:])
        lines = self.console_outbuffer.split("\n")
        width = self._get_console_width()
        if width is not None:
            wrapped = []
            for line in lines:
                if not line:
                    wrapped.append("")
                    continue
                wrapped.extend(self._wrap_console_line(line, width))
            lines = wrapped
        return "\n".join(lines[-self.console_max_height:])

    def _get_console_width(self):
        if getattr(self, "loop", None) is None:
            return None
        if getattr(self.loop, "screen", None) is None:
            return None
        try:
            cols, _ = self.loop.screen.get_cols_rows()
        except Exception:
            return None
        width = max(1, cols - 2)
        return width

    def _wrap_console_line(self, line, width):
        if width <= 0:
            return [line]
        pattern = ANSIText.ANSI_ESCAPE_RE
        tokens = []
        idx = 0
        for match in pattern.finditer(line):
            if match.start() > idx:
                tokens.append(("text", line[idx:match.start()]))
            tokens.append(("ansi", match.group(0)))
            idx = match.end()
        if idx < len(line):
            tokens.append(("text", line[idx:]))
        if not tokens:
            return [""]
        result = []
        current = []
        current_len = 0
        for kind, value in tokens:
            if kind == "ansi":
                current.append(value)
                continue
            segment = value
            while segment:
                remaining = width - current_len
                if remaining <= 0:
                    result.append("".join(current))
                    current = []
                    current_len = 0
                    remaining = width
                take = segment[:remaining]
                current.append(take)
                current_len += len(take)
                segment = segment[remaining:]
                if current_len >= width:
                    result.append("".join(current))
                    current = []
                    current_len = 0
        if current or not result:
            result.append("".join(current))
        return result

    def is_cmd_exit(self, cmd):
        return cmd in ("q", "Q", "exit", "quit")

    def handle_input(self, key):
        """
        Handle user input from the console.
        """
        cmd = self.console_input.get_edit_text().lstrip()
        if key == 'esc':
            if self.content_msgs_scroll:
                self.content_msgs_scroll = False
                self.content_msgs_focus = len(self.content_msgs) - 1
                self.update_messages_focus()
                return
            if self.console_output_page_scroll("exit_page"):
                return
            self.focus_footer()
        elif key == 'enter':
            self.console_input.set_edit_text("")
            if self.is_cmd_exit(cmd):
                self.exit(None)
                return
            if cmd:
                self.last_cmd = cmd
            elif self.last_cmd:
                cmd = self.last_cmd
            else:
                self.update_info()
                return
            self.console_output.set_text(self._get_output(f"(UnityChip) {cmd}\n"))
            self.process_command(cmd)
            self.update_info()
            self.last_line = cmd
        elif key == 'tab':
            try:
                self.complete_cmd(cmd)
            except Exception as e:
                self.console_output.set_text(self._get_output(f"{YELLOW}Complete cmd Error: {str(e)}\n{traceback.format_exc()}{RESET}\n"))
        elif key == 'shift right': # clear console
            self.console_output.set_text(self._get_output(self.console_default_txt, clear=True))
        elif key == 'shift up':
            try:
                self.status_content_fix_height = max(3, self.status_content_fix_height - 1)  # Minimum height of 3
                self.update_top_pane()
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'shift down':
            try:
                self.status_content_fix_height = min(100, self.status_content_fix_height + 1)  # Maximum height of 100
                self.update_top_pane()
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'ctrl up':
            try:
                self.console_max_height = max(3, self.console_max_height + 1)  # Minimum height of 3
                new_text = self.console_outbuffer.split("\n")
                new_text.insert(0, "")
                self.console_outbuffer = "\n".join(new_text)
                self.console_output_box.height = self.console_max_height
                self.console_output.set_text(self._get_output())
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'ctrl down':
            try:
                self.console_max_height = max(3, self.console_max_height - 1)  # Minimum height of 3
                new_text = self.console_outbuffer.split("\n")
                if len(new_text) > 1:  # Ensure we don't remove all text
                    new_text = new_text[1:]
                self.console_outbuffer = "\n".join(new_text)
                self.console_output_box.height = self.console_max_height
                self.console_output.set_text(self._get_output())
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'ctrl left':
            try:
                self.content_task_fix_width = max(10, self.content_task_fix_width - 1)  # Minimum width
                self.update_top_pane()
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'ctrl right':
            try:
                self.content_task_fix_width = min(200, self.content_task_fix_width + 1)  # Maximum width
                self.update_top_pane()
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'shift left':
            self.console_input.set_edit_text("")
        elif key == 'meta up':
            try:
                self.set_messages_focus(-1)
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == 'meta down':
            try:
                self.set_messages_focus(1)
            except Exception as e:
                # If this fails, just ignore the keypress
                pass
        elif key == "meta right":
            self.enable_console_output_page_scroll()
            if self.console_output_page_scroll(1):
                return
        elif key == "meta left":
            self.enable_console_output_page_scroll()
            if self.console_output_page_scroll(-1):
                return
        elif key == "up":
            try:
                if self.console_output_page_scroll(1):
                    return
                self.cmd_history_index -= 1
                self.cmd_history_index = max(0, self.cmd_history_index)
                hist_cmd = self.cmd_history_get(self.cmd_history_index)
                if hist_cmd is not None:
                    self.console_input.set_edit_text(hist_cmd)
                    self.console_input.set_edit_pos(len(hist_cmd))
            except Exception as e:
                # If history access fails, just ignore the keypress
                pass
        elif key == "down":
            try:
                if self.console_output_page_scroll(-1):
                    return
                self.cmd_history_index += 1
                self.cmd_history_index = min(self.cmd_history_index, readline.get_current_history_length() + 1)
                hist_cmd = self.cmd_history_get(self.cmd_history_index)
                if hist_cmd is not None:
                    self.console_input.set_edit_text(hist_cmd)
                    self.console_input.set_edit_pos(len(hist_cmd))
            except Exception as e:
                # If history access fails, just ignore the keypress
                pass
        self.last_key = key
        return True

    def enable_console_output_page_scroll(self):
        if self.console_page_cache is None:
            self.console_page_cache = self.console_outbuffer.split("\n")
            self.console_page_cache_index = len(self.console_page_cache)
            self.console_output_page_scroll(0)

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
        self.cmd_history_set(cmd)
        if cmd == "clear":
            self.console_output.set_text(self._get_output(self.console_default_txt, clear=True))
            return
        if cmd == "list_demo_cmds":
            self.console_output.set_text(self._get_output(self.cmd_list_demo_cmds()))
            return
        scrowl_ret = False
        if cmd.startswith("!"):
            cmd  = cmd[1:]
            scrowl_ret = True
        self.console_input_busy_index = 0

        self.original_sigint = signal.getsignal(signal.SIGINT)
        def _sigint_handler(s, f):
            self.vpdb._sigint_handler(s, f)
        signal.signal(signal.SIGINT, _sigint_handler)
        self.root.focus_part = None
        self._execute_cmd_in_thread(cmd, scrowl_ret)

    def cmd_list_demo_cmds(self):
        """
        List all demo commands that are currently running.
        """
        if not self.deamon_cmds:
            return "No demo commands running."
        ntime = time.time()
        output = "\n".join([f"{fmt_time_stamp(key)}: {cmd}  {fmt_time_deta(ntime - key)}" for key, cmd in self.deamon_cmds.items()])
        return f"Running demo commands:\n{output}"

    def _execute_cmd_in_thread(self, cmd, scrowl_ret):
        """
        Execute a command in a separate thread to avoid blocking the main loop.
        """
        self.is_cmd_busy = True
        cmd = cmd.rstrip()
        is_demo_cmd = cmd.endswith("&")
        key = None
        if is_demo_cmd:
            cmd = cmd[:-1].strip()
            key = time.time()
            self.deamon_cmds[key] = cmd
        def run_cmd(demo_key, rcmd, need_scrowl):
            try:
                self.vpdb.onecmd(rcmd)
            except Exception as e:
                self.console_output.set_text(self._get_output(f"{YELLOW}Command Error: {str(e)}\n{traceback.format_exc()}{RESET}\n"))
            if demo_key is not None:
                if demo_key in self.deamon_cmds:
                    del self.deamon_cmds[demo_key]
                self.console_output.set_text(self._get_output(f"\n\n{YELLOW}Demo command {demo_key} completed.{RESET}\n", clear=True))
            else:
                self.loop.set_alarm_in(0.1, self._on_cmd_complete, need_scrowl)
        thread = threading.Thread(target=run_cmd, args=(key, cmd, scrowl_ret))
        thread.daemon = True
        thread.start()
        if key is not None:
            self._on_cmd_complete(self.loop, False)

    def _on_cmd_complete(self, loop, scrowl_ret):
        self.is_cmd_busy = False
        self.console_input_busy_index = -1
        signal.signal(signal.SIGINT, self.original_sigint)
        self.root.focus_part = 'footer'
        self.update_console_ouput(scrowl_ret)

    def focus_footer(self):
        self.root.focus_part = 'footer'
        self.update_info()

    def _auto_update_ui(self, loop, user_data=None):
        """
        Automatically update the UI at regular intervals.
        This is useful for refreshing the display without user input.
        """
        if self._is_auto_updating_ui:
            return
        self._is_auto_updating_ui = True
        self.update_info()
        if self.content_msgs_scroll:
            self.update_console_ouput(True)
        else:
            self.update_console_ouput(False)
        self._is_auto_updating_ui = False
        loop.set_alarm_in(1.0, self._auto_update_ui)

    def _process_batch_cmd(self):
        p_count = 0
        while len(self.vpdb.init_cmd) > 0:
            cmd = self.vpdb.init_cmd.pop(0)
            if cmd.startswith("tui"):
                continue
            if self.is_cmd_exit(cmd):
                self.exit(None)
                break
            self.console_input.set_edit_text(cmd)
            time.sleep(self.gap_time)
            self.console_input.set_edit_text("")
            self.process_command(cmd)
            if self.vpdb.agent.is_break():
                break
            p_count += 1
        self.console_output.set_text(self._get_output(f"\n\n{YELLOW}Processed {p_count} commands in batch mode.{RESET}\n"))

    def check_exec_batch_cmds(self, loop, user_data=None):
        if len(self.vpdb.init_cmd) > 0:
            self._process_batch_cmd()
        loop.set_alarm_in(1.0, self.check_exec_batch_cmds)

    def complete_cmd(self, line):
        cmp = []
        cmd, args, _ = self.vpdb.parseline(line)
        if " " in line:
            complete_func = getattr(self.vpdb, f"complete_{cmd}", self.vpdb.completedefault)
            arg = args
            if " " in args:
                arg = args.split()[-1]
            idbg = line.find(arg)
            cmp = complete_func(arg, line, idbg, len(line))
        else:
            cmp = self.vpdb.api_all_cmds(line)
        if cmp:
            prefix = os.path.commonprefix(cmp)
            full_cmd = line[:line.rfind(" ") + 1] if " " in line else ""
            if prefix:
                full_cmd += prefix
            else:
                full_cmd = line
            self.console_input.set_edit_text(full_cmd)
            self.console_input.set_edit_pos(len(full_cmd))
            self.console_output.set_text(self._get_output(self.console_input_cap + full_cmd + "\n" + " ".join(cmp) + "\n"))

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
        try:
            if self.console_page_cache is not None:
                pindex = self.console_page_cache_index
                cache_len = len(self.console_page_cache)
                # Ensure pindex is within bounds
                pindex = max(0, min(pindex, cache_len - 1))
                end_index = min(cache_len, pindex + self.console_max_height)
                text_data = "\n"+"\n".join(self.console_page_cache[pindex:end_index])
                console_data = text_data
            else:
                text_data = self._get_pdb_out()
                text_lines = text_data.split("\n")
                # just check the last output check
                if len(text_lines) > self.console_max_height and need_scroll:
                    self.console_page_cache = text_lines
                    self.console_page_cache_index = 0
                    text_data = "\n"+"\n".join(text_lines[:self.console_max_height])
                    self.root.focus_part = None
                console_data = self._get_output(text_data)

            try:
                self.console_output.set_text(console_data)
            except:
                # If setting text fails, try with empty string
                self.console_output.set_text("")
            self.update_console_caption()
            try:
                if hasattr(self, 'loop') and self.loop is not None:
                    self.loop.screen.clear()
                    self.loop.draw_screen()
            except:
                # If screen operations fail, just ignore
                pass
        except Exception as e:
            # Complete fallback - just try to keep UI responsive
            try:
                self.console_output.set_text("Console update error occurred: %s" % e)
                self.update_console_caption()
            except:
                pass

    def update_console_caption(self):
        cap = self.console_input_cap
        if self.is_cmd_busy:
            if self.console_input_busy_index >= 0:
                self.console_input_busy_index += 1
                n = self.console_input_busy_index % len(self.console_input_busy)
                cap = self.console_input_busy[n]
        if self.console_page_cache is not None:
            cap = f"<Up/Down: scroll, Esc: exit>" + cap
        self.console_input.set_caption(cap)

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
    setattr(pdb, "__verify_ui__", app)
    app.loop = loop
    original_sigint = signal.getsignal(signal.SIGINT)
    def _sigint_handler(s, f):
        loop.set_alarm_in(0.0, app.exit)
    signal.signal(signal.SIGINT, _sigint_handler)
    loop.set_alarm_in(0.1, app.check_exec_batch_cmds)
    loop.set_alarm_in(1.0, app._auto_update_ui)
    try:
        loop.run()
    except Exception as e:
        app._exit_cleanup()
        print(f"{YELLOW}TUI Exception: {str(e)}\n{traceback.format_exc()}{RESET}\n")
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


class UCText(urwid.Text):

    def get_line_translation(self, maxcol: int, ta=None):
        try:
            return super().get_line_translation(maxcol, ta)
        except Exception as e:
            pass
        if not self._cache_maxcol or self._cache_maxcol != maxcol or \
            not hasattr(self, "_cache_translation"):
            self._update_cache_translation(maxcol, ta)
        return self._cache_translation

    def __init__(self, markup='', align='left'):
        super().__init__(markup, align=align, wrap='any')


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
        super().__init__('', align=align, wrap='any')
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

    def get_line_translation(self, maxcol: int, ta=None):
        if not self._cache_maxcol or self._cache_maxcol != maxcol or \
            not hasattr(self, "_cache_translation"):
            self._update_cache_translation(maxcol, ta)
        return self._cache_translation


import sys
import traceback
import logging

class UIMsgLogger(logging.Logger):
    
    def __init__(self, ui, level=logging.getLevelName("INFO")):
        super().__init__(name="UIMsgLogger", level=level)
        self.ui = ui

    def log(self, level, msg, *args, **kwargs):
        self.ui.message_echo(f"[{logging.getLevelName(level)}] {msg % args if args else msg}")

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def warn(self, msg, *args, **kwargs):
        self.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg, *args, exc_info=True, **kwargs):
        self.error(msg, *args, **kwargs)
        if exc_info:
            traceback.print_exc(file=self.stream)
