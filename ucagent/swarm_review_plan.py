"""Apply a Swarm creation-time review selection to the resolved workflow."""


def review_stage_names(value):
    """Validate the nonsecret, semicolon-delimited runtime option."""
    if not isinstance(value, str):
        raise ValueError("runtime_options.human_review_stage_names must be a string")
    names = value.split(";") if value else []
    if (len(names) > 64 or len(names) != len(set(names))
            or any(not name or len(name) > 128 or not name.isascii()
                   or not all(c.isalnum() or c == "_" for c in name) for name in names)):
        raise ValueError("Invalid or duplicate human review stage names")
    return names


def apply_review_plan(manager):
    """Resolve all selected stages before changing any HM flag; never disable HM."""
    names = review_stage_names(manager.cfg.get_value(
        "runtime_options.human_review_stage_names", ""))
    selected = []
    for name in names:
        matches = [(i, stage) for i, stage in enumerate(manager.stages) if stage.name == name]
        if len(matches) != 1:
            raise ValueError(f"Human review stage {name!r} is missing or ambiguous in this workflow")
        index, stage = matches[0]
        skipped = stage.is_skipped() or index in (manager.stage_skip_list or [])
        if index in (manager.stage_unskip_list or []):
            skipped = False
        if (index < manager.stage_index and not skipped
                and not getattr(manager, "force_stage_index_explicit", False)
                and stage.is_completed()):
            # Ordinary recovery preserves previously completed work. Explicit
            # forced-stage reruns must select only gates they will execute.
            continue
        if skipped or index < manager.stage_index:
            raise ValueError(f"Human review stage {name!r} is skipped or before the starting stage")
        selected.append(stage)
    for stage in selected:
        stage.do_set_hmcheck_needed(True)
