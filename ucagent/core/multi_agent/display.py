"""Readable multi-agent messages without changing prompts or tool protocol results."""

import json

from ucagent.util.functions import format_message_value


def control_result(action, content):
    """Project only opted-in orchestration results; ordinary tool text stays verbatim."""
    if action in {"", "read", "check"}:
        return content
    data = content
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return content
    if not isinstance(data, dict):
        return content if isinstance(content, str) else format_message_value(content)
    if action == "tips" and not data.get("error") and not data.get("error_code"):
        for key in ("stage", "tips"):
            if isinstance(data.get(key), str):
                return data[key]
        if "stage" in data and data["stage"] is None:
            return "No active stage."
    if isinstance(data.get("plans"), dict) and isinstance(data.get("tasks"), list):
        # Queue snapshots repeat budgets, counters and history. Keep the outcome,
        # artifacts and every validation/error detail needed to understand it.
        visible = {"workflow": data.get("workflow_state"),
                   "workers": f"{data.get('running', 0)}/{data.get('max_workers', '?')}",
                   "plans": {name: {key: value for key, value in plan.items()
                                    if key != "tasks" and value is not None}
                             for name, plan in data["plans"].items()},
                   "tasks": [{key: value for key, value in task.items()
                              if key != "budget" and value is not None and value != {}}
                             for task in data["tasks"]]}
        failures = [event for event in data.get("events", ()) if event.get("error") or event.get("reason")]
        if failures:
            visible["failures"] = failures
        for key in ("error", "error_code", "reason", "next_action"):
            if key in data:
                visible[key] = data[key]
        return format_message_value(visible)
    # These fields are machine coordination, not verification data. Do not apply
    # the projection recursively inside Checker diagnostics or artifact contents.
    visible = {key: value for key, value in data.items()
               if key not in {"budget", "step_token", "planning_token", "scope_root", "stage_index"}}
    tips = visible.pop("tips", None)
    rendered = format_message_value(visible) if visible else ""
    return "\n\n".join(part for part in (rendered, tips) if isinstance(part, str) and part)


def planning_message(context):
    """Show the stage, user request and previous outcome without the planning envelope."""
    parts = [context.get("phase_label") or "Workflow handoff"] if context.get("phase") == "handoff" else [control_result("tips", context)]
    if context.get("workflow_complete") and context.get("phase") != "handoff":
        parts.append("Workflow complete.")
    if context.get("user_instruction"):
        parts.append("User instruction:\n" + str(context["user_instruction"]))
    if context.get("previous_result"):
        parts.append("Previous result:\n" + control_result("status", context["previous_result"]))
    return "\n\n".join(parts)
