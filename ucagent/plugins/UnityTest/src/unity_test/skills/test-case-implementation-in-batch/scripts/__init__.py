def setup_vstage(stage):
    ''' Register all hooks to the current stage '''
    stage.add_hook("task", modified_task_hook)

def modified_task_hook(orig_task_method):
    ''' Hook function to modify the behavior of the original task function '''
    tasks = orig_task_method()
    if tasks and isinstance(tasks, list):
        return [tasks[0],tasks[1],tasks[5]]
    return tasks

__all__ = ['setup_vstage']
