"""Plain message bodies shared by model history, summaries and output rendering."""

from langchain_core.messages import AIMessage, RemoveMessage, ToolMessage

from ucagent.util.functions import get_ai_message_tool_call


def content_text(content):
    """Extract text leaves without serializing provider envelopes or tool-call blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(content_text(block) for block in content)
    if not isinstance(content, dict):
        return ""
    if content.get("type") in {"function_call", "tool_call", "tool_use"}:
        return ""
    if isinstance(content.get("text"), str):
        return content["text"]
    # Only traverse content containers, never arbitrary metadata or arguments.
    return "".join(content_text(content[key]) for key in ("summary", "content") if key in content)


def text_message(message):
    """Copy a block-based body to text while retaining call linkage and usage statistics."""
    if isinstance(message, RemoveMessage) or isinstance(message.content, str):
        return message
    return message.model_copy(update={"content": content_text(message.content)})


def format_message(message, *, body=None):
    """Render one complete message, with tool invocations shown once outside its body."""
    title = "AI" if isinstance(message, AIMessage) else message.type.title()
    parts = [f" {title} Message ".center(80, "=")]
    if isinstance(message, ToolMessage) and message.name:
        parts.append(f"Name: {message.name}")
    text = body if body is not None else message.response_metadata.get("ucagent_display_text")
    if text is None:
        text = content_text(message.content)
    if text:
        parts.append(text)
    if isinstance(message, AIMessage):
        calls = get_ai_message_tool_call(message)
        if calls:
            parts.append(calls)
    if isinstance(message, AIMessage) and len(parts) == 1:
        return ""
    return "\n" + "\n\n".join(parts)


def new_messages(messages, seen):
    """Yield each new graph message once, including batches of parallel tool results."""
    if not seen:
        seen.update(message.id or id(message) for message in messages[:-1])
    for message in messages:
        key = message.id or id(message)
        if key not in seen:
            seen.add(key)
            yield message
