def setup_vstage(stage):  
    stage.add_hook("task", modified_task_hook)

def modified_task_hook(orig_task_method):
        tasks = orig_task_method()
        if tasks and isinstance(tasks, list):
            return [tasks[0]]
        return tasks