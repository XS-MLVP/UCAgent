"""One process stream bridge with independently owned runtime output buffers."""

from collections import deque
from contextvars import ContextVar
from contextlib import contextmanager
import logging
import sys
import threading

from ucagent.util.output import OUTPUT_METADATA, OUTPUT_RECORDED, output_context


OUTPUT_OWNER = ContextVar("ucagent_output_owner", default=None)


class OutputBuffer:
    """Keep a bounded transcript usable by HTTP and terminal frontends."""

    def __init__(self, *, events=None):
        """Allocate an inert buffer; construction never replaces global streams."""
        self.events = events
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
        if self.events is not None:
            metadata = dict(OUTPUT_METADATA.get())
            self.events.append(text, view="raw", source="console", stream=metadata.get("stream"),
                               scope=metadata.get("scope", "instance"), operation_id=metadata.get("operation_id"),
                               session_id=metadata.get("session_id"))
            if not OUTPUT_RECORDED.get():
                source = metadata.pop("source", "console")
                owned_activity = metadata.get("scope", "instance") == "instance" and source in (
                    "model", "backend", "tool", "stage", "command")
                view = "activity" if owned_activity else "system"
                self.events.append(text, view=view, source=source, **metadata)
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
                StreamBridge.stdout = StreamBridge(sys.stdout, stream="stdout")
                StreamBridge.stderr = StreamBridge(sys.stderr, stream="stderr")
                ServiceLogHandler.install()
                sys.stdout, sys.stderr = StreamBridge.stdout, StreamBridge.stderr
            StreamBridge.buffers.add(self)
            self._installed = True

    @contextmanager
    def capture(self):
        """Route Textual's redirected streams here for exactly one UI attachment."""
        previous = {name: getattr(sys, name) for name in ("stdout", "stderr")}
        was_attached = self.terminal_attached
        self.terminal_attached = True
        bridges = {name: StreamBridge(stream, owner=self, echo=False, stream=name)
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
                ServiceLogHandler.uninstall()
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

    def __init__(self, original, *, owner=None, echo=True, stream="stdout"):
        """Retain the exact stream that must be restored when the bridge is released."""
        self._original = original
        self.stream = stream
        self.owner = owner
        self.echo = echo

    def write(self, text):
        """Mirror each write once into subscribed buffers and the original output."""
        with self.lock:
            owner = OUTPUT_OWNER.get() or self.owner
            buffers = [owner] if owner is not None else list(self.buffers)
        for buffer in buffers:
            metadata = {} if owner is not None else {"scope": "process"}
            with output_context(stream=self.stream, **metadata):
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
    """Forward MCP diagnostic records through an injected runtime sink."""

    def __init__(self, sink):
        """Bind the callback without changing process-global logging configuration."""
        super().__init__()
        self.sink = sink
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record):
        """Preserve record formatting and exception details in the message transcript."""
        with output_context(level=record.levelname):
            self.sink(self.format(record))


class ServiceLogHandler(logging.Handler):
    """Route Uvicorn records before formatting while preserving existing terminal handlers."""

    installed = {}

    def __init__(self, logger):
        """Retain the original handler chain for forwarding and final restoration."""
        super().__init__()
        self.logger = logger
        self.handlers = list(logger.handlers)
        self.propagate = logger.propagate

    @classmethod
    def install(cls):
        """Acquire one process bridge shared by all installed runtime output owners."""
        for name in ("uvicorn.access", "uvicorn.error"):
            if name in cls.installed:
                continue
            logger = logging.getLogger(name)
            handler = cls(logger)
            cls.installed[name] = handler
            logger.handlers = [handler]
            logger.propagate = False

    @classmethod
    def uninstall(cls):
        """Release our handlers without discarding handlers added by another owner."""
        for handler in cls.installed.values():
            logger = handler.logger
            logger.removeHandler(handler)
            logger.handlers = handler.handlers + logger.handlers
            logger.propagate = handler.propagate
            handler.close()
        cls.installed.clear()

    def emit(self, record):
        """Keep access/service logs out of model activity, including their echoed copies."""
        owner = OUTPUT_OWNER.get()
        with StreamBridge.lock:
            buffers = [owner] if owner is not None else list(StreamBridge.buffers)
        for buffer in buffers:
            if buffer.events is not None:
                buffer.events.append(self.format(record) + "\n", view="system",
                                     source="http" if record.name == "uvicorn.access" else "service",
                                     kind="log", level=record.levelname,
                                     scope="instance" if owner is not None else "process")
        # The original handlers still own terminal/file output. Suppress only a
        # second classified event if their formatted text crosses StreamBridge.
        token = OUTPUT_RECORDED.set(True)
        try:
            handlers = list(self.handlers)
            parent = self.logger.parent if self.propagate else None
            while parent is not None:
                handlers.extend(parent.handlers)
                parent = parent.parent if parent.propagate else None
            if not handlers and logging.lastResort is not None:
                handlers = [logging.lastResort]
            for handler in handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)
        finally:
            OUTPUT_RECORDED.reset(token)
