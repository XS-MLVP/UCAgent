#coding=utf-8

"""
Agent backend base module.
"""

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class BackendCapabilities:
    """Observable execution features; unavailable provider metrics are never invented."""

    managed_sessions: bool = False
    model_rounds: bool = False
    resume: bool = False


@dataclass(frozen=True)
class TurnResult:
    """Execution completion only; task submission and Checker acceptance remain separate."""

    reason: str = "finished"


class AgentBackendBase(object):
    """
    Agent backend base class.
    """

    requires_mcp = False
    capabilities = BackendCapabilities()

    def __init__(self, vagent, config, **kwargs):
        """
        Initialize the agent backend with the given configuration.

        :param vagent: The verification agent instance.
        :param config: Configuration dictionary for the backend.
        """
        self.vagent = vagent
        self.config = config
        self.kwargs = kwargs
        self._turn_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._cancel_requested = threading.Event()
        self._closed = False
        self._stat_msg_count_ai = 0
        self._stat_msg_count_tool = 0
        self._stat_msg_count_system = 0

    def run_turn(self, instructions, config=None, *, stream=False):
        """Serialize one backend turn and retain ownership until execution has returned."""
        if not self._turn_lock.acquire(blocking=False):
            raise RuntimeError("This backend session is already executing")
        self._idle.clear()
        try:
            if self._closed:
                raise RuntimeError("This backend session is closed")
            self._cancel_requested.clear()
            if self.vagent.is_break():
                return TurnResult("interrupted")
            work = self.do_work_stream if stream else self.do_work_values
            work(instructions, config if config is not None else self.get_work_config())
            session = getattr(self.vagent, "execution_session", None)
            reason = ("cancelled" if self._cancel_requested.is_set() else
                      "yielded" if session is not None and session.yielded() else
                      "interrupted" if self.vagent.is_break() else "finished")
            return TurnResult(reason)
        finally:
            self._idle.set()
            self._turn_lock.release()

    def cancel(self):
        """Request cancellation; synchronous implementations retain ownership until return."""
        self._cancel_requested.set()

    def wait_idle(self, timeout=None):
        """Wait for actual execution completion rather than a cancellation notification."""
        return self._idle.wait(timeout)

    def close(self, timeout=None):
        """Release backend resources only after its current execution has drained."""
        acquired = self._turn_lock.acquire() if timeout is None else self._turn_lock.acquire(timeout=timeout)
        if not acquired:
            return False
        try:
            if not self._closed:
                self.exit()
                self._closed = True
            return True
        finally:
            self._turn_lock.release()

    def init(self):
        """
        Initialize the backend.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def prepare(self):
        """Prepare model execution when needed; local backends need no extra setup."""

    def get_human_message(self, text: str, *, display_text=None):
        """
        Create and return a human message with the given text.

        :param text: The full text content supplied to the model.
        :param display_text: Optional local display body; external clients own their rendering.
        :return: A HumanMessage instance.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def get_system_message(self, text: str):
        """
        Create and return a system message with the given text.

        :param text: The text content of the system message.
        :return: A SystemMessage instance.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def messages_get_raw(self):
        """
        Retrieve raw messages from the backend.

        :return: A list of raw messages.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def messages_get_status(self):
        """Return a message snapshot suitable for status rendering."""
        return self.messages_get_raw()

    def do_work_values(self, instructions, config):
        """
        Perform work based on the given instructions and configuration.

        :param instructions: Instructions for the work to be done.
        :param config: Configuration for the work.
        :return: Results of the work performed.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def do_work_stream(self, instructions, config):
        """
        Perform work in a streaming manner based on the given instructions and configuration.

        :param instructions: Instructions for the work to be done.
        :param config: Configuration for the work.
        :return: A generator yielding results of the work performed.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    # Optional methods
    def get_message_manage_node(self):
        """
        Get the message management node.

        :return: The message management node.
        """
        return None

    def get_work_config(self):
        """
        Get the work configuration.
        :return: The work configuration.
        """
        return {}

    def exit(self):
        """
        Clean up resources before exiting the backend.
        """
        pass

    def set_debug(self, debug):
        """
        Set the debug mode for the backend.

        :param debug: Boolean indicating whether to enable debug mode.
        """
        pass

    def token_total(self) -> int:
        """
        Get the total number of tokens processed.

        :return: Total token count.
        """
        return -1

    def token_speed(self) -> float:
        """
        Get the token processing speed.

        :return: Token speed.
        """
        return -1.0

    def idle(self) -> float:
        """Get the current or latest model-request idle time."""
        return -1.0

    def stream_character_total(self) -> int:
        """Get the number of streamed output characters observed by the backend."""
        return -1

    def stream_character_speed(self) -> float:
        """Get the current streamed output character rate."""
        return -1.0

    def summary_stream_character_total(self) -> int:
        """Get streamed characters produced by the summary model."""
        return -1

    def get_statistics(self) -> dict:
        """
        Get statistics related to the backend.

        :return: A dictionary of statistics.
        """
        return {
            "message_in": -1,
            "message_out": -1,
        }

    def model_name(self) -> str:
        """
        Get the name of the model used in the backend.

        :return: Model name.
        """
        return "UnknownModel"

    def temperature(self) -> float:
        """
        Get the temperature setting of the model.

        :return: Temperature value.
        """
        return -1.0

    def on_stage_complete(self, stage):
        """
        Callback method called when a stage is finished.

        :param stage: The stage that has finished.
        """
        pass

    def reset_chat(self, force=False):
        """
        Reset the chat state, if applicable.
        """
        pass

    def recover_pending_tool_calls(self, error) -> int:
        """Record failed outputs for tool calls left pending by an exception."""
        return 0
