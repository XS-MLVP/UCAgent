"""Human-readable terminal rendering shared by the console and Textual frontend."""

import json

from ucagent.util.log import L_BLUE, L_GREEN, L_RED, L_YELLOW, RESET
from ucagent.version import banner


def format_status(stats):
    """Render agent statistics with the original compact wrapping and precision."""
    text = ""
    for key, value in stats.items():
        if isinstance(value, float):
            value = f"{value:.2f}"
        text += ("" if not text or text.endswith("\n") else " ") + f"{key}: {value}"
        if len(text.rsplit("\n", 1)[-1]) > 80:
            text += "\n"
    return text


def format_mission(mission, *, use_skills=False):
    """Render stage indices, review flags, failures and timing without domain access."""
    stages = mission["stages"]
    flags = (("need_fail_llm_suggestion", L_BLUE),
             ("need_pass_llm_suggestion", L_GREEN), ("needs_human_check", L_RED))
    visible = [(key, color) for key, color in flags if any(row.get(key) for row in stages)]
    lines = []
    for stage in stages:
        index = stage["index"]
        color = L_GREEN if index < mission["current_index"] else (
            L_RED if index == mission["current_index"] else "")
        title = stage["title"]
        skills = stage.get("skill_list", [])
        skills_text = f"[{', '.join(skills)}], " if use_skills and skills else ""
        elapsed = stage.get("time_cost", "")
        suffix = f" ({skills_text}{stage.get('fail_count', 0)} fails{', ' + elapsed if elapsed else ''})"
        if stage.get("is_skipped"):
            color, suffix = L_YELLOW, " (skipped)"
        end = RESET if color else ""
        marks = "".join(f"{tint}*{RESET}" if stage.get(key) else " " for key, tint in visible)
        lines.append(f"{color}{index:2d}{end} {marks}{color}{title}{suffix}{end}")
    return lines


def format_data(data):
    """Display scalar and structured command data without transport envelopes."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, list) and all(isinstance(row, str) for row in data):
        return "\n".join(data)
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_result(result, *, use_skills=False):
    """Render a registry result for people while leaving API results structured."""
    if result is None:
        return ""
    data = result.data
    if result.command == "logo_and_version":
        return banner
    if result.command == "quit" and isinstance(data, dict):
        shutdown = data.get("shutdown", {})
        pending = shutdown.get("pending", [])
        if data.get("instance") in {"closed", "failed"}:
            return f"Shutdown {data['instance']}."
        return ("Shutting down" + (" (grace period expired)" if shutdown.get("grace_expired") else "")
                + ": " + ("; ".join(pending) or shutdown.get("phase") or "cleanup")
                + ". Use q to refresh status; q force skips remaining cleanup.")
    if result.command == "status":
        return format_status(data)
    if result.command == "mission_info":
        return data["mission_name"] + "\n" + "\n".join(format_mission(data, use_skills=use_skills))
    if result.command == "help":
        commands = data if isinstance(data, list) else [data]
        return "\n".join(f"{row['usage']}\n  {row['summary']}" + (
            f" (aliases: {', '.join(row['aliases'])})" if row['aliases'] else "") for row in commands)
    if isinstance(data, dict) and "id" in data and "state" in data:
        return f"[{data['id']}] {data['command']}: {data['state']}"
    if result.command in {"pwd", "cd", "chcwd"} and isinstance(data, dict):
        return "\n".join(f"{key}: {value}" for key, value in data.items())
    return format_data(data)


def format_operation(operation, label=None):
    """Show terminal outcomes, including nonzero exits and cancellation, once."""
    text = f"[{operation['id']}] {label or operation['command']}: {operation['state']}"
    error = operation.get("error")
    if error:
        text += f"\n{error['code']}: {error['message']}"
    result = operation.get("result")
    if isinstance(result, dict):
        # Shell streams already passed through the output buffer as they arrived.
        result = {key: value for key, value in result.items() if key not in {"stdout", "stderr"}}
    if result is not None and result != {}:
        text += "\n" + format_data(result)
    return text
