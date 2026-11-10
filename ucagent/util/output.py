"""Source metadata for output producers, independent of runtime and frontend owners."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect


OUTPUT_METADATA = ContextVar("ucagent_output_metadata", default={})
OUTPUT_SINK = ContextVar("ucagent_output_sink", default=None)
OUTPUT_RECORDED = ContextVar("ucagent_output_recorded", default=False)


@contextmanager
def output_context(**metadata):
    """Temporarily annotate emitted text without changing its terminal representation."""
    token = OUTPUT_METADATA.set({**OUTPUT_METADATA.get(), **metadata})
    try:
        yield
    finally:
        OUTPUT_METADATA.reset(token)


def output_source(source=None, kind="message", level=None):
    """Annotate synchronous or asynchronous producers for the duration of a call."""
    metadata = {"kind": kind}
    if source is not None:
        metadata["source"] = source
    if level is not None:
        metadata["level"] = level

    def decorate(function):
        """Preserve the producer signature and correctly scope coroutine execution."""
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                """Keep metadata local to this asynchronous invocation."""
                with output_context(**metadata):
                    return await function(*args, **kwargs)
            return asynchronous

        @wraps(function)
        def synchronous(*args, **kwargs):
            """Restore enclosing metadata after a synchronous invocation."""
            with output_context(**metadata):
                return function(*args, **kwargs)
        return synchronous
    return decorate


def publish_output(text, **metadata):
    """Publish explicit activity through an injected sink without a runtime dependency."""
    sink = OUTPUT_SINK.get()
    if sink is not None:
        sink(text, **{**OUTPUT_METADATA.get(), **metadata})
