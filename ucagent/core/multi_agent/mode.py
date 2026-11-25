"""Separate the public execution mode from the role of an internal child."""


def agent_role(cfg):
    """Resolve one canonical role and reject ambiguous or obsolete mode settings."""
    runtime = cfg.get_value("runtime_options", {})
    runtime = runtime.as_dict() if hasattr(runtime, "as_dict") else runtime
    run = cfg.get_value("agent_run", {})
    run = run.as_dict() if hasattr(run, "as_dict") else run
    for key in ("multi_agent_enabled", "global_agent_enabled"):
        if key in runtime:
            raise ValueError("Use runtime_options.agent_mode: single or multi; remove runtime_options." + key)
    mode = runtime.get("agent_mode", "single")
    if mode not in ("single", "multi"):
        raise ValueError("runtime_options.agent_mode must be single or multi")
    role = run.get("role")
    if role is not None and (role != "super" or mode != "multi"):
        raise ValueError("agent_run.role is reserved for an internal Super in multi mode")
    return role or ("global" if mode == "multi" else "single")
