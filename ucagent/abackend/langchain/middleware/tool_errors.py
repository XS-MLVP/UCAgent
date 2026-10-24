"""Bound consecutive failed tool batches inside a single agent graph invocation."""
from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage
from ucagent.util.log import warning


class ToolErrorGuard(AgentMiddleware):
    """Pause before another model call after repeated wholly failed tool batches."""

    def __init__(self, max_rounds=3, on_pause=lambda: None):
        """Configure the round limit and notify the outer autonomous loop."""
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds < 0:
            raise ValueError("loop_settings.max_tool_error_rounds must be a non-negative integer")
        self.max_rounds = max_rounds
        self.on_pause = on_pause

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime=None):
        """Count complete failed batches; successful tools and user input reset the streak."""
        if not self.max_rounds:
            return None
        failed = 0
        batch = []
        for message in reversed(state.get("messages", [])):
            if isinstance(message, ToolMessage):
                batch.append(message)
            elif isinstance(message, AIMessage):
                calls = message.tool_calls
                if (not calls or len(batch) != len(calls)
                        or {item.tool_call_id for item in batch} != {call["id"] for call in calls}
                        or any(item.status != "error" for item in batch)):
                    break
                failed += 1
                batch = []
                if failed >= self.max_rounds:
                    warning(f"Pausing after {failed} consecutive failed tool batches; repair tool arguments before resuming.")
                    self.on_pause()
                    return {"jump_to": "end"}
            else:
                break
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime=None):
        """Apply the same guard for asynchronous graph execution."""
        return self.before_model(state, runtime)
