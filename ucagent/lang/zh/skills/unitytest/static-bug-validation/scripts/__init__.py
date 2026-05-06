def setup_vstage(stage):
    """Register all hooks to the current stage."""
    stage.add_hook("task", modified_task_hook)


def modified_task_hook(orig_task_method):
    """Restrict the task list to the first generated task."""
    tasks = orig_task_method()
    if tasks and isinstance(tasks, list):
        return [tasks[0]]
    return tasks

__all__ = ["setup_vstage"]
