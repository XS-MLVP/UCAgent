"""One process stream bridge with independently owned runtime output buffers."""

from collections import deque
from contextvars import ContextVar
from contextlib import contextmanager
import logging
import sys
import threading


OUTPUT_OWNER = ContextVar("ucagent_output_owner", default=None)


class OutputBuffer:
    """Keep a bounded transcript usable by HTTP and terminal frontends."""

    def __init__(self):
        """Allocate an inert buffer; construction never replaces global streams."""
        self._lock = threading.RLock()
        self._lines = deque(maxlen=2000)
        self._pending = ""
        self._subscribers = []
        self._installed = False
        self.terminal_attached = False

    def write(self, text):
        """Store one output chunk and notify attached views without echoing it twice."""
        if not isinstance(text, str):
            text = text.decode("utf-8", errors="replace")
        with self._lock:
            lines = (self._pending + text).split("\n")
            self._lines.extend(lines[:-1])
            self._pending = lines[-1]
            callbacks = list(self._subscribers)
        for callback in callbacks:
            callback(text)
        return len(text)

    def emit(self, text):
        """Publish explicit runtime output and echo it when no local display consumes it."""
        self.write(text)
        if not self.terminal_attached:
            stream = sys.stdout
            while isinstance(stream, StreamBridge):
                stream = stream._original
            stream.write(text)
            stream.flush()

    def inject(self, text):
        """Record explicit frontend input without writing to the process terminal."""
        self.write(text + "\n")

    def get_lines(self, n=200):
        """Read completed and pending lines as a detached list."""
        with self._lock:
            lines = list(self._lines) + ([self._pending] if self._pending else [])
        return lines[-n:] if n > 0 else lines

    def clear(self):
        """Clear display output without changing runtime or operation state."""
        with self._lock:
            self._lines.clear()
            self._pending = ""

    def subscribe(self, callback, *, replay=False):
        """Subscribe a transient frontend to future chunks."""
        with self._lock:
            if callback not in self._subscribers:
                if replay:
                    text = "".join(line + "\n" for line in self._lines) + self._pending
                    if text:
                        callback(text)
                self._subscribers.append(callback)

    def unsubscribe(self, callback):
        """Detach a frontend without discarding buffered output."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def install(self):
        """Acquire the shared bridge once for this owner."""
        with StreamBridge.lock:
            if self._installed:
                return
            if not StreamBridge.buffers:
                StreamBridge.stdout = StreamBridge(sys.stdout)
                StreamBridge.stderr = StreamBridge(sys.stderr)
                sys.stdout, sys.stderr = StreamBridge.stdout, StreamBridge.stderr
            StreamBridge.buffers.add(self)
            self._installed = True

    @contextmanager
    def capture(self):
        """Route Textual's redirected streams here for exactly one UI attachment."""
        previous = {name: getattr(sys, name) for name in ("stdout", "stderr")}
        was_attached = self.terminal_attached
        self.terminal_attached = True
        bridges = {name: StreamBridge(stream, owner=self, echo=False)
                   for name, stream in previous.items()}
        for name, bridge in bridges.items():
            setattr(sys, name, bridge)
        try:
            yield
        finally:
            self.terminal_attached = was_attached
            for name, bridge in bridges.items():
                if getattr(sys, name) is bridge:
                    setattr(sys, name, previous[name])

    def close(self):
        """Restore original streams after the last owner releases its bridge."""
        with StreamBridge.lock:
            StreamBridge.buffers.discard(self)
            self._installed = False
            if not StreamBridge.buffers:
                for name in ("stdout", "stderr"):
                    bridge = getattr(StreamBridge, name)
                    if bridge is not None and getattr(sys, name) is bridge:
                        setattr(sys, name, bridge._original)


class StreamBridge:
    """Fan out process writes through one wrapper, restoring the actual downstream stream."""

    lock = threading.RLock()
    buffers = set()
    stdout = None
    stderr = None
    records_console = True

    def __init__(self, original, *, owner=None, echo=True):
        """Retain the exact stream that must be restored when the bridge is released."""
        self._original = original
        self.owner = owner
        self.echo = echo

    def write(self, text):
        """Mirror each write once into subscribed buffers and the original output."""
        with self.lock:
            owner = OUTPUT_OWNER.get() or self.owner
            buffers = [owner] if owner is not None else list(self.buffers)
        for buffer in buffers:
            buffer.write(text)
        if self.echo and not any(buffer.terminal_attached for buffer in buffers):
            return self._original.write(text)
        return len(text)

    def flush(self):
        """Flush the underlying stream without emitting additional buffered text."""
        return self._original.flush()

    def __getattr__(self, name):
        """Preserve encoding, TTY and descriptor capabilities of the original stream."""
        return getattr(self._original, name)


class MessageHandler(logging.Handler):
    """Forward MCP log records through the runtime-owned message buffer."""

    def __init__(self, sink):
        """Bind the callback without changing process-global logging configuration."""
        super().__init__()
        self.sink = sink
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record):
        """Preserve record formatting and exception details in the message transcript."""
        self.sink(self.format(record))
