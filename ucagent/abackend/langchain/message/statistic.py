# -*- coding: utf-8 -*-
"""Message statistic utilities for UCAgent."""

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.messages import ToolMessage, RemoveMessage, SystemMessage
from collections import OrderedDict


class MessageStatistic:
    """Class for message statistics."""

    def __init__(self):
        """Initialize message statistics."""
        self.recorded_messages = set()
        self.count_human_messages = 0
        self.count_ai_messages = 0
        self.count_tool_messages = 0
        self.count_system_messages = 0
        self.text_size_human_messages = 0
        self.text_size_ai_messages = 0
        self.text_size_tool_messages = 0
        self.text_size_system_messages = 0
        self.count_unknown_messages = 0
        self.text_size_unknown_messages = 0

    def get_message_text_size(self, msg: BaseMessage) -> int:
        """Get the text size of a message."""
        return len(msg.text)

    def update_message(self, messages):
        """Update message statistics based on the provided messages."""
        if messages is None:
            return
        if not isinstance(messages, list):
            messages = [messages]
        for msg in messages:
            if msg.id in self.recorded_messages:
                continue
            if isinstance(msg, RemoveMessage):
                continue
            self.recorded_messages.add(msg.id)
            if isinstance(msg, HumanMessage):
                self.count_human_messages += 1
                self.text_size_human_messages += self.get_message_text_size(msg)
            elif isinstance(msg, AIMessage):
                self.count_ai_messages += 1
                self.text_size_ai_messages += self.get_message_text_size(msg)
            elif isinstance(msg, ToolMessage):
                self.count_tool_messages += 1
                self.text_size_tool_messages += self.get_message_text_size(msg)
            elif isinstance(msg, SystemMessage):
                self.count_system_messages += 1
                self.text_size_system_messages += self.get_message_text_size(msg)
            else:
                # Unknown message type
                self.count_unknown_messages += 1
                self.text_size_unknown_messages += self.get_message_text_size(msg)

    def reset_statistics(self):
        """Reset all message statistics."""
        self.recorded_messages.clear()
        self.count_human_messages = 0
        self.count_ai_messages = 0
        self.count_tool_messages = 0
        self.count_system_messages = 0
        self.text_size_human_messages = 0
        self.text_size_ai_messages = 0
        self.text_size_tool_messages = 0
        self.text_size_system_messages = 0
        self.count_unknown_messages = 0
        self.text_size_unknown_messages = 0

    def get_statistics(self) -> dict:
        """Get the current message statistics."""
        message_in_count = self.count_human_messages + self.count_ai_messages + self.count_tool_messages + self.count_system_messages
        message_out_count = self.count_ai_messages
        message_in_size = self.text_size_human_messages + self.text_size_ai_messages + self.text_size_tool_messages + self.text_size_system_messages
        message_out_size = self.text_size_ai_messages
        return OrderedDict({
            "count": {
                "human": self.count_human_messages,
                "ai": self.count_ai_messages,
                "tool": self.count_tool_messages,
                "system": self.count_system_messages,
                "unknown": self.count_unknown_messages,
            },
            "size": {
                "human": self.text_size_human_messages,
                "ai": self.text_size_ai_messages,
                "tool": self.text_size_tool_messages,
                "system": self.text_size_system_messages,
                "unknown": self.text_size_unknown_messages,
            },
            "total_count_messages": message_in_count + message_out_count,
            "total_text_size_messages": message_in_size + message_out_size,
            "message_in": message_in_size,
            "message_out": message_out_size,
        })
