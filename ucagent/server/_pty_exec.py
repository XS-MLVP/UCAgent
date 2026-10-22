"""Claim an inherited PTY in a new session before executing a terminal command."""

import fcntl
import os
import sys
import termios


if __name__ == "__main__":
    # Popen creates the session and attaches fd 0 before this interpreter starts.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execvpe("/bin/sh", ["/bin/sh", "-c", sys.argv[1]], os.environ)
