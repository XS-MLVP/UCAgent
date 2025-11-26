# -*- coding: utf-8 -*-
"""Logging utilities for UCAgent."""

import logging
import logging.handlers
import os
from typing import Optional

RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"

L_GREEN = "\033[92m"
L_RED = "\033[91m"
L_YELLOW = "\033[93m"

__log_logger__: Optional[logging.Logger] = None


def get_log_logger() -> Optional[logging.Logger]:
    """Returns a logger instance.

    Returns:
        Logger instance or None if not initialized.
    """
    return __log_logger__


__msg_logger__: Optional[logging.Logger] = None


def get_msg_logger() -> Optional[logging.Logger]:
    """Returns a message logger instance.

    Returns:
        Message logger instance or None if not initialized.
    """
    return __msg_logger__


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
    logger = get_msg_logger()
    if logger:
        logger.info(msg, extra={"end": end})


def message(msg: str, end: str = "\n"):
    """Prints a message."""
    print(msg, flush=True, end=end)
    msg_msg(msg, end)


def log_msg(msg: str, level = logging.INFO, end: str = "\n"):
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
    print(f"[DEBUG] {msg}")
    log_msg(msg, logging.DEBUG)


def echo(msg: str):
    """Prints a message without any formatting."""
    print(msg, flush=True)
    log_msg(msg, logging.INFO)


def echo_g(msg: str):
    """Prints an info message green."""
    print(f"{GREEN}%s{RESET}" % msg, flush=True)
    log_msg(msg, logging.INFO)


def echo_r(msg: str):
    """Prints an error message red."""
    print(f"{RED}%s{RESET}" % msg, flush=True)
    log_msg(msg, logging.ERROR)


def echo_y(msg: str):
    """Prints a warning message yellow."""
    print(f"{YELLOW}%s{RESET}" % msg, flush=True)
    log_msg(msg, logging.WARNING)


def info(msg: str):
    """Prints an info message."""
    print(f"{GREEN}[INFO] %s{RESET}" % msg, flush=True)
    log_msg(msg, logging.INFO)


def warning(msg: str):
    """Prints a warning message."""
    print(f"{YELLOW}[WARN] %s{RESET}" % msg, flush=True)
    log_msg(msg, logging.WARNING)


def error(msg: str):
    """Prints an error message."""
    print(f"{RED}[ERROR] %s{RESET}" % msg, flush=True)
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
