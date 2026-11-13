"""Cancellable native async model requests inside the synchronous tool/stage graph."""

import asyncio
import threading
from concurrent.futures import CancelledError

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel


class ModelRequestCancelled(CancelledError):
    """Signal an acknowledged cancellation after the model coroutine has unwound."""


class ModelRequests:
    """Own a per-backend event loop; cancel network awaits without interrupting tools."""

    def __init__(self, owner):
        """Defer loop creation until a real model request and keep no global client state."""
        self.owner = owner
        self._lock = threading.RLock()
        self._loop = None
        self._thread = None
        self._active = None
        self._models = []
        self._closed = False

    def _serve(self, ready):
        """Run native async clients on the same loop for their complete lifetime."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        ready.set()
        try:
            loop.run_forever()
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            loop.close()

    def invoke(self, model, messages, *, phase="model", **kwargs):
        """Wait for an async model call, retaining ownership until cancellation has drained."""
        with self._lock:
            if self._closed or self.owner.is_break():
                raise ModelRequestCancelled("Model request cancelled")
            if self._active is not None:
                raise RuntimeError("A model request is already active on this backend")
            if self._loop is None:
                ready = threading.Event()
                self._thread = threading.Thread(target=self._serve, args=(ready,),
                                                name="ucagent-model-io", daemon=True)
                self._thread.start()
                ready.wait()
            base = model
            while hasattr(base, "bound"):
                base = base.bound
            if all(base is not item for item in self._models):
                self._models.append(base)
            # The base implementation delegates to a synchronous executor. Such
            # a call must really finish; cancelling its Future cannot stop its thread.
            native = (isinstance(base, BaseChatModel)
                      and type(base)._agenerate is not BaseChatModel._agenerate)
            call = {"phase": phase, "cancellable": native, "task": None,
                    "cancel_requested": False, "done": threading.Event()}
            self._active = call

        async def execute():
            """Capture completion only after provider cancellation and callbacks unwind."""
            try:
                with self._lock:
                    call["task"] = asyncio.current_task()
                    cancelled = call["cancel_requested"] or self.owner.is_break()
                if cancelled:
                    raise ModelRequestCancelled("Model request cancelled before dispatch")
                call["result"] = await model.ainvoke(messages, **kwargs)
            except asyncio.CancelledError:
                call["error"] = ModelRequestCancelled("Model request cancelled")
            except BaseException as error:
                call["error"] = error
            finally:
                call["done"].set()

        asyncio.run_coroutine_threadsafe(execute(), self._loop)
        try:
            while not call["done"].wait(0.05):
                if self.owner.is_break():
                    self.cancel()
            if self.owner.is_break():
                raise ModelRequestCancelled("Model request cancelled")
            if "error" in call:
                raise call["error"]
            return call["result"]
        finally:
            with self._lock:
                self._active = None

    def cancel(self):
        """Post cancellation once; never treat a live synchronous fallback as stopped."""
        with self._lock:
            call = self._active
            if call is None or call["cancel_requested"] or call["done"].is_set():
                return
            call["cancel_requested"] = True
            if call["cancellable"] and call["task"] is not None:
                self._loop.call_soon_threadsafe(call["task"].cancel)

    def status(self):
        """Expose bounded wait diagnostics without messages, URLs or credentials."""
        with self._lock:
            call = self._active
            return ({key: call[key] for key in ("phase", "cancellable", "cancel_requested")}
                    if call is not None else None)

    def close(self):
        """Close owned async clients on their loop after the graph relinquishes requests."""
        with self._lock:
            if self._closed:
                return
            if self._active is not None:
                raise RuntimeError("Cannot close a backend while its model request is active")
            self._closed = True
            loop = self._loop
        if loop is None:
            return

        async def close_clients():
            """Release provider-owned HTTP pools without touching shared trace exporters."""
            seen = set()
            for model in self._models:
                client = getattr(model, "root_async_client", None)
                if client is not None and id(client) not in seen:
                    seen.add(id(client))
                    await client.close()

        try:
            asyncio.run_coroutine_threadsafe(close_clients(), loop).result()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            self._thread.join()


class AsyncModelView:
    """Delegate model binding while routing synchronous invoke through native async I/O."""

    def __init__(self, model, requests, phase="model"):
        """Keep the actual provider and its callbacks unchanged."""
        self.model, self.requests, self.phase = model, requests, phase

    def __getattr__(self, name):
        """Preserve provider capability and token-estimation attributes."""
        return getattr(self.model, name)

    def bind_tools(self, tools, **kwargs):
        """Bind tools on the actual model and keep cancellation at invocation time."""
        return AsyncModelView(self.model.bind_tools(tools, **kwargs), self.requests, self.phase)

    def bind(self, **kwargs):
        """Preserve provider options for calls without tools."""
        return AsyncModelView(self.model.bind(**kwargs), self.requests, self.phase)

    def invoke(self, messages, **kwargs):
        """Run the bound provider with inherited graph callbacks and context."""
        return self.requests.invoke(self.model, messages, phase=self.phase, **kwargs)


class CancellableModelCalls(AgentMiddleware):
    """Keep graph tools synchronous while making provider requests actively cancellable."""

    def __init__(self, requests):
        """Share only the current backend's request owner."""
        self.requests = requests

    def wrap_model_call(self, request, handler):
        """Use the standard model middleware boundary without replacing graph execution."""
        return handler(request.override(model=AsyncModelView(request.model, self.requests)))
