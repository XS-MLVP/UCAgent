# -*- coding: utf-8 -*-
"""Logging utilities for UCAgent."""

import logging
import logging.handlers
import os
import sys
from typing import Callable, Optional
from datetime import datetime

RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"

L_GREEN = "\033[92m"
L_RED = "\033[91m"
L_YELLOW = "\033[93m"
L_BLUE = "\033[94m"

__silent__: bool = False
__log_logger__: Optional[logging.Logger] = None


def get_log_time_str():
    """Returns the current time as a formatted string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def get_log_logger() -> Optional[logging.Logger]:
    """Returns a logger instance.

    Returns:
        Logger instance or None if not initialized.
    """
    return __log_logger__


__msg_logger__: Optional[logging.Logger] = None
__console_sync_handler__: Optional[Callable[[str], None]] = None


def get_msg_logger() -> Optional[logging.Logger]:
    """Returns a message logger instance.

    Returns:
        Message logger instance or None if not initialized.
    """
    return __msg_logger__


def set_console_sync_handler(handler: Optional[Callable[[str], None]]) -> None:
    """Set an optional sink used to mirror console-visible output elsewhere."""
    global __console_sync_handler__
    __console_sync_handler__ = handler


def get_console_sync_handler() -> Optional[Callable[[str], None]]:
    """Get the current console sync handler."""
    return __console_sync_handler__


def _stream_chain_records_console(stream) -> bool:
    visited: set[int] = set()
    current = stream
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if getattr(current, "_record_to_vpdb", False):
            return True
        if current.__class__.__name__ == "PersistentConsoleMirror" and hasattr(current, "_vpdb"):
            return True
        # Do NOT check for _ConsoleCapture, as we want to sync to it
        current = getattr(current, "_original", None)
    return False


def _sync_console_output(text: str) -> None:
    if not text:
        return
    handler = __console_sync_handler__
    if handler is None:
        return
    if _stream_chain_records_console(sys.stdout):
        return
    handler(text)


def set_silent(silent: bool = True) -> None:
    """Enable or disable non-error console logging output."""
    global __silent__
    __silent__ = bool(silent)


def is_silent() -> bool:
    """Return whether logging output is currently silenced."""
    return __silent__


def init_log_logger(name: str = "ucagent-log", level: int = logging.DEBUG,
                log_file:str="log/ucagent-log.log"):
    """Initializes the logger with the given name and level."""
    global __log_logger__
    __log_logger__ = logging.getLogger(name)
    __log_logger__.setLevel(level)
    __log_logger__.handlers.clear()
    log_path = os.path.dirname(log_file)
    if log_path and not os.path.exists(log_path):
        os.makedirs(log_path)
    fh = logging.FileHandler(log_file, mode='a')
    fm = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setLevel(level)
    fh.setFormatter(fm)
    __log_logger__.addHandler(fh)


def init_msg_logger(name: str = "ucagent-msg", level: int = logging.INFO,
                log_file:str="log/ucagent-msg.log"):
    """Initializes the message logger with the given name and level."""
    global __msg_logger__
    __msg_logger__ = logging.getLogger(name)
    __msg_logger__.setLevel(level)
    __msg_logger__.handlers.clear()
    log_path = os.path.dirname(log_file)
    if log_path and not os.path.exists(log_path):
        os.makedirs(log_path)
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount
        =5)
    fh.setLevel(level)
    __msg_logger__.addHandler(fh)


def msg_msg(msg: str, end: str = "\n"):
    """Prints a message with a newline at the end."""
    if is_silent():
        return
    logger = get_msg_logger()
    if logger:
        logger.info(msg, extra={"end": end})


def message(msg: str, end: str = "\n"):
    """Prints a message."""
    if is_silent():
        return
    print(msg, flush=True, end=end)
    _sync_console_output(f"{msg}{end}")
    msg_msg(msg, end)


def log_msg(msg: str, level = logging.INFO, end: str = "\n"):
    if is_silent() and level < logging.ERROR:
        return
    logger = get_log_logger()
    if logger:
        extra = {"end": end}
        if level == logging.DEBUG:
            logger.debug(msg, extra=extra)
        elif level == logging.INFO:
            logger.info(msg, extra=extra)
        elif level == logging.WARNING:
            logger.warning(msg, extra=extra)
        elif level == logging.ERROR:
            logger.error(msg, extra=extra)
        elif level == logging.CRITICAL:
            logger.critical(msg, extra=extra)


def debug(msg: str):
    """Prints a debug message."""
    if is_silent():
        return
    rendered = f"[{get_log_time_str()} DEBUG] {msg}"
    print(rendered)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.DEBUG)


def echo(msg: str):
    """Prints a message without any formatting."""
    if is_silent():
        return
    print(msg, flush=True)
    _sync_console_output(f"{msg}\n")
    log_msg(msg, logging.INFO)


def echo_g(msg: str):
    """Prints an info message green."""
    if is_silent():
        return
    rendered = f"{GREEN}%s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.INFO)


def echo_r(msg: str):
    """Prints an error message red."""
    rendered = f"{RED}%s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.ERROR)


def echo_y(msg: str):
    """Prints a warning message yellow."""
    if is_silent():
        return
    rendered = f"{YELLOW}%s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.WARNING)


def info(msg: str):
    """Prints an info message."""
    if is_silent():
        return
    rendered = f"{GREEN}[{get_log_time_str()} INFO] %s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.INFO)


def warning(msg: str):
    """Prints a warning message."""
    if is_silent():
        return
    rendered = f"{YELLOW}[{get_log_time_str()} WARN] %s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.WARNING)


def error(msg: str):
    """Prints an error message."""
    rendered = f"{RED}[{get_log_time_str()} ERROR] %s{RESET}" % msg
    print(rendered, flush=True)
    _sync_console_output(f"{rendered}\n")
    log_msg(msg, logging.ERROR)


def str_info(msg: str):
    """Inserts a string into an info message format."""
    return f"[INFO] {msg}"


def str_warning(msg: str):
    """Inserts a string into a warning message format."""
    return f"[WARNING] {msg}"

def str_error(msg: str):
    """Inserts a string into an error message format."""
    return f"[ERROR] {msg}"


def str_return(msg: str):
    """Inserts a string into a return message format."""
    return f"[RETURN]\n{msg}"


def str_data(msg: str, key="DATA"):
    """Inserts a string into a return message format."""
    return f"[{key}]\n{msg}"
