
RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"


def debug(msg: str):
    """Prints a debug message."""
    print(f"[DEBUG] {msg}")


def info(msg: str):
    """Prints an info message."""
    print(f"{GREEN}[INFO] %s{RESET}" % msg, flush=True)


def warning(msg: str):
    """Prints a warning message."""
    print(f"{YELLOW}[WARN] %s{RESET}" % msg, flush=True)


def error(msg: str):
    """Prints an error message."""
    print(f"{RED}[ERROR] %s{RESET}" % msg, flush=True)


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
