"""Retry incomplete model responses without replaying any tool or graph step."""

import asyncio
import time

import httpx
from openai import APIConnectionError
from langchain.agents.middleware.types import AgentMiddleware
from ucagent.util.log import warning


TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, APIConnectionError)


def call_with_transport_retry(operation, *, cancelled=lambda: False, max_retries=2, delay=1.0):
    """Retry only transport failures, returning only a complete invocation result."""
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except TRANSPORT_ERRORS as error:
            if attempt == max_retries or cancelled():
                raise
            warning(f"Model transport retry {attempt + 1}/{max_retries}: {type(error).__name__}; incomplete response discarded")
            deadline = time.monotonic() + delay * (2 ** attempt)
            while time.monotonic() < deadline:
                if cancelled():
                    raise
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


class TransportRetryMiddleware(AgentMiddleware):
    """Retry the model node only; tool execution remains outside this boundary."""

    def __init__(self, cancelled=lambda: False, max_retries=2, delay=1.0):
        """Bound retries and allow an interactive stop to cancel backoff."""
        self.cancelled = cancelled
        self.max_retries = max_retries
        self.delay = delay

    def wrap_model_call(self, request, handler):
        """A failed streamed reply never becomes a committed AI/tool-call message."""
        return call_with_transport_retry(lambda: handler(request), cancelled=self.cancelled,
                                         max_retries=self.max_retries, delay=self.delay)

    async def awrap_model_call(self, request, handler):
        """Keep async cancellation and backoff responsive without replaying tools."""
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except TRANSPORT_ERRORS as error:
                if attempt == self.max_retries or self.cancelled():
                    raise
                warning(f"Model transport retry {attempt + 1}/{self.max_retries}: {type(error).__name__}; incomplete response discarded")
                deadline = time.monotonic() + self.delay * (2 ** attempt)
                while time.monotonic() < deadline:
                    if self.cancelled():
                        raise
                    await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
