

def debug(msg: str):
    """Prints a debug message."""
    print(f"[DEBUG] {msg}")


def info(msg: str):
    """Prints an info message."""
    print(f"[INFO] {msg}")


def warning(msg: str):
    """Prints a warning message."""
    print(f"[WARNING] {msg}")


def error(msg: str):
    """Prints an error message."""
    print(f"[ERROR] {msg}")


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
