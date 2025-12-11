# -*- coding: utf-8 -*-
"""UCAgent base tool class implementation."""


from langchain_core.tools import BaseTool
from langchain_core.tools.base import ArgsSchema
from pydantic import Field, BaseModel
from typing import Callable, Optional, Any
from mcp.server.fastmcp import Context
from langchain_mcp_adapters.tools import _get_injected_args, create_model, ArgModelBase, FuncMetadata
from mcp.server.fastmcp.tools import Tool as FastMCPTool
import ucagent.util.functions as fc

import threading
import concurrent.futures
import asyncio
from ucagent.util.cqueque import CircularOverwriteQueue
import time


class EmptyArgs(BaseModel):
    """Empty arguments for tools that do not require any input."""
    pass


class UCTool(BaseTool):
    """Base class for UCAgent tools with additional functionality."""

    call_count: int = Field(
        default=0,
        description="Number of times the tool has been called."
    )
    is_disabled: bool = Field(
        default=False,
        description="Indicates if the tool is disabled."
    )
    disable_reason: str = Field(
        default="",
        description="Reason for disabling the tool."
    )
    pre_call_back: Optional[Callable] = Field(
        default=None,
        description="A callback function to be executed before each call to the tool."
    )
    lock_time_out: int = Field(
        default=20,
        description="Maximum time in seconds to wait for acquiring the lock."
    )
    call_time_out: int = Field(
        default=20,
        description="Maximum time in seconds to allow the tool to run."
    )
    last_call_time: float = Field(
        default=0.0,
        description="Timestamp of the last time the tool was called."
    )
    stream_queue: CircularOverwriteQueue = Field(
        default=None,
        description="Queue for streaming data."
    )
    stream_queue_buffer: CircularOverwriteQueue = Field(
        default=None,
        description="Buffer for streaming data."
    )
    is_in_streaming: bool = Field(
        default=False,
        description="Indicates if the tool is currently streaming."
    )
    is_alive_loop: bool = Field(
        default=False,
        description="Indicates if the alive loop is running."
    )
    is_in_call: bool = Field(
        default=False,
        description="Indicates if the tool is currently being called."
    )
    executor: Optional[concurrent.futures.ThreadPoolExecutor] = Field(
        default=None,
        description="Executor for running tasks."
    )
    task_future: Optional[concurrent.futures.Future] = Field(
        default=None,
        description="Future object for the running task."
    )
    force_exit: bool = Field(
        default=False,
        description="Indicates if the tool should forcefully exit."
    )
    sync_block_log_to_client: bool = Field(
        default=False,
        description="send block message to client"
    )
    async_lock: asyncio.Lock = Field(
        default_factory=asyncio.Lock,
        description="Asynchronous lock for thread safety."
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.call_time_out = kwargs.get("call_time_out", 20)
        self.lock_time_out = kwargs.get("lock_time_out", 20)
        self.stream_queue = CircularOverwriteQueue(kwargs.get("stream_queue_size", 1024))
        self.stream_queue_buffer = CircularOverwriteQueue(kwargs.get("stream_queue_size", 1024))
        self.is_in_streaming = False
        self.is_alive_loop = False
        self.is_in_call = False
        self.executor = None
        self.task_future = None
        self.last_call_time = 0.0
        self.sync_block_log_to_client = kwargs.get("sync_block_log_to_client", False)

    def set_disabled(self, value: bool, reason: str = ""):
        self.is_disabled = value
        self.disable_reason = reason
        return self

    def set_force_exit(self, value):
        if value:
            self.cb_force_exit()
        self.force_exit = value

    def cb_force_exit(self):
        pass

    def render_desc(self, kwargs):
        self.description = fc.render_template(self.description, kwargs)
        return self

    def is_force_exit(self):
        return self.force_exit

    def reset_force_exit(self):
        self.stream_queue.clear()
        self.stream_queue_buffer.clear()
        self.set_force_exit(False)

    def is_busy(self):
        return self.is_in_streaming or self.is_alive_loop or self.is_in_call

    def is_hot(self):
        return (time.time() - self.last_call_time) < 1 or self.is_busy()

    def set_call_time_out(self, timeout: int):
        self.call_time_out = timeout
        return self

    def get_call_time_out(self):
        return self.call_time_out

    def get_timeout_error(self):
        data = str(self.stream_queue_buffer)
        self.stream_queue_buffer.clear()
        self.stream_queue.clear()
        return {"error": f"Tool ({self.__class__.__name__}) call timed out after {self.call_time_out} seconds.",
                "logs":  data}

    def invoke(self, input, config = None, **kwargs):
        if self.is_disabled:
            return {"error": f"Tool ({self.__class__.__name__}) is disabled. Reason: {self.disable_reason}"}
        self.call_count += 1
        self.is_in_call = True
        try:
            return super().invoke(input, config, **kwargs)
        finally:
            self.is_in_call = False
            self.last_call_time = time.time()

    def put_alive_data(self, data):
        self.stream_queue.put(data)

    def __alive_loop(self, timeout: int, ctx: Context):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.__async_alive_loop(timeout, ctx))
        except Exception as e:
            fc.info(f"Alive loop error: {e}")
        finally:
            loop.close()

    async def __async_alive_loop(self, timeout: int, ctx: Context):
        self.is_alive_loop = True
        count_down = timeout
        while count_down > 0:
            await asyncio.sleep(1)
            msg = f"tool({self.__class__.__name__}) is blocking, wait {count_down}/{timeout} seconds"
            if not self.is_in_streaming:
                self.is_alive_loop = False
                return
            item = self.stream_queue.try_get()
            if item is None:
                count_down -= 1
                fc.info(msg)
                if self.sync_block_log_to_client:
                    try:
                        await ctx.info({"msg": msg})
                    except Exception as e:
                        fc.info(f"Failed to send msg({msg}) ctx.info: {e}, may be connection failed")
                    continue
            self.stream_queue_buffer.put(item)
            # Send data back to client
            if self.sync_block_log_to_client:
                try:
                    await ctx.info({"msg": item})
                    count_down = timeout  # reset countdown when processing an item
                except Exception as e:
                    fc.info(f"Failed to send ctx.info: {e}, may be connection failed ({msg})")
                    count_down -= 1
        fc.info(f"Tool ({self.__class__.__name__}) call timed out after {timeout} seconds.")
        fc.info(f"Mark tool ({self.__class__.__name__}) need force exit")
        self.set_force_exit(True)
        self.is_alive_loop = False

    async def ainvoke(self, input, config = None, **kwargs):
        if self.is_disabled:
            return {"error": f"Tool ({self.__class__.__name__}) is disabled. Reason: {self.disable_reason}"}
        try:
            await asyncio.wait_for(self.async_lock.acquire(), timeout=self.lock_time_out)
        except asyncio.TimeoutError:
            error_msg = {"error": f"Tool ({self.__class__.__name__}) is busy, get lock timeout ({self.call_time_out} seconds). Please try again later."}
            fc.warning(str(error_msg))
            return error_msg
        except Exception as e:
            error_msg = {"error": f"Tool ({self.__class__.__name__}) acquire lock error: {str(e)}"}
            fc.warning(str(error_msg))
            return error_msg
        try:
            data, alive_thread = await self._ainvoke(input, config, **kwargs)
            return data
        except Exception as e:
            error_msg = {"error": f"Tool ({self.__class__.__name__}) ainvoke error: {str(e)}"}
            fc.warning(str(error_msg))
            return error_msg
        finally:
            if alive_thread is not None:
                alive_thread.join()
            self.async_lock.release()

    async def _ainvoke(self, input, config = None, **kwargs):
        self.call_count += 1
        self.last_call_time = time.time()
        ctx = input.get("ctx", None)
        if not isinstance(ctx, Context):
            try:
                self.is_in_call = True
                return await super().ainvoke(input, config, **kwargs), None
            finally:
                self.is_in_call = False
                self.last_call_time = time.time()
        fc.info(f"call {self.__class__.__name__} in Stream-MPC mode")
        timeout = input.get("timeout", None)
        if timeout is None or timeout <= 0:
            fc.info(f"no timeout ({timeout}) set in input, use tool default call_time_out: {self.call_time_out} seconds")
            timeout = self.call_time_out
        fc.info(f"set tool ({self.__class__.__name__}) timeout to {timeout + self.lock_time_out} (timeout:{timeout} + lock_time_out:{self.lock_time_out}) seconds")
        timeout = timeout + self.lock_time_out
        if self.is_in_streaming:
            error_msg = {"error": f"Tool ({self.__class__.__name__}) is already running. Please wait until it finishes."}
            fc.info(str(error_msg))
            return error_msg, None
        if self.is_alive_loop:
            error_msg = {"error": f"Tool ({self.__class__.__name__}) is in the process of terminating. Please wait until it finishes."}
            fc.info(str(error_msg))
            return error_msg, None
        self.is_in_streaming = True
        self.last_call_time = time.time()
        self.reset_force_exit()
        alive_thread = threading.Thread(target=self.__alive_loop, args=(timeout, ctx), daemon=True)
        alive_thread.start()
        try:
            data = await super().ainvoke(input, config, **kwargs)
        except Exception as e:
            import traceback
            fc.info(f"error: {e}")
            fc.info(traceback.format_exc())
            data = {"error": str(e)}
        self.is_in_streaming = False
        self.last_call_time = time.time()
        fc.info(f"call {self.__class__.__name__} exit Stream-MPC mode")
        return data, alive_thread

    def pre_call(self, *args, **kwargs):
        if self.pre_call_back is None:
            return
        self.pre_call_back(*args, **kwargs)

    def set_pre_call_back(self, func):
        self.pre_call_back = func
        return self


class RoleInfo(UCTool):
    """A tool to provide role information."""
    args_schema: Optional[ArgsSchema] = EmptyArgs
    name: str = "RoleInfo"
    description: str = (
        "Returns the role information of you. "
    )

    # custom info
    role_info: str = Field(
        default="You are an expert AI software/hardware engineering agent.",
        description="The role information to be returned by the tool."
    )

    def _run(self, *args, **kwargs):
        return self.role_info

    def __init__(self, role_info: str = None, **kwargs):
        super().__init__(**kwargs)
        if role_info:
            self.role_info = role_info


def to_fastmcp(tool: BaseTool) -> FastMCPTool:
    """Convert a LangChain tool to a FastMCP tool."""
    if not issubclass(tool.args_schema, BaseModel):
        raise ValueError(
            "Tool args_schema must be a subclass of pydantic.BaseModel. "
            "Tools with dict args schema are not supported."
        )
    parameters = tool.tool_call_schema.model_json_schema()
    field_definitions = {
        field: (field_info.annotation, field_info)
        for field, field_info in tool.tool_call_schema.model_fields.items()
    }
    arg_model = create_model(
        f"{tool.name}Arguments",
        **field_definitions,
        __base__=ArgModelBase,
    )
    fn_metadata = FuncMetadata(arg_model=arg_model)

    async def fn(**arguments: dict[str, Any]) -> Any:
        return await tool.ainvoke(arguments)

    injected_args = _get_injected_args(tool)
    if len(injected_args) > 0:
        raise NotImplementedError("LangChain tools with injected arguments are not supported")

    context_kwarg = "ctx" if issubclass(tool.__class__, UCTool) else None
    fastmcp_tool = FastMCPTool(
        fn=fn,
        name=tool.name,
        description=tool.description,
        parameters=parameters,
        fn_metadata=fn_metadata,
        is_async=True,
        context_kwarg=context_kwarg,
    )
    return fastmcp_tool
