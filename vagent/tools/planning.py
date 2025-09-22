# -*- coding: utf-8 -*-
"""Planning and task management tools for UCAgent."""

from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from typing import Optional, List
from pydantic import BaseModel, Field
import time


class ToDoPanel:

    def __init__(self, max_str_size=100):
        self.max_str_size = max_str_size
        self.todo_list = {
            # 'current_task_description': str, 'steps': List[str, is_completed: bool], 'notes': str
        }
        self.stat_tool = None
        self._reset()

    def set_stat_tool(self, stat_tool):
        self.stat_tool = stat_tool

    def set_stat_tool_des(self, des: str):
        if self.stat_tool:
            self.stat_tool.description = des

    def _reset(self):
        """Reset the current ToDo"""
        self.todo_list = {}

    def set_tool_process(self):
        if self._empty():
            self.set_stat_tool_des("No Active ToDo List.")
        elif self._is_all_completed():
            self.set_stat_tool_des("Current ToDo list is completed! You can create a new one depending on your needs.")
        else:
            cmp_count = sum(is_cmp for _, is_cmp in self.todo_list['steps'])
            un_cmp_count = len(self.todo_list['steps']) - cmp_count
            self.set_stat_tool_des(f"Current ToDo List has {len(self.todo_list['steps'])} steps, {cmp_count} completed and {un_cmp_count} uncompleted.")

    def _summary(self) -> str:
        """Get a formatted summary of a ToDo"""
        if self._empty():
            return "\nCurrent ToDo list is empty, please create it as you need."
        def as_cmp_str(is_cmp):
            return "(completed)" if is_cmp else ""
        steps = [
            f"{i+1}{as_cmp_str(is_cmp)}: {desc}" for i, (desc, is_cmp) in enumerate(self.todo_list['steps'])
        ]
        if self._is_all_completed():
            return "\nCurrent ToDo list is completed! You can create a new one depending on your needs."
        steps_text = "\n  ".join(steps)
        return f"\n-------- ToDo List --------\n" \
               f" Task Description: {self.todo_list['task_description']}\n" \
               f" Steps:\n  {steps_text}\n" \
               f" Created At: {self.todo_list['created_at']}\n" \
               f" Updated At: {self.todo_list['updated_at']}\n" \
               f" Notes: {self.todo_list.get('notes', 'None')}" \
               f"\n----------------------------\n"

    def _empty(self) -> bool:
        return not bool(self.todo_list)

    def _check_str_size(self, notes, steps, emsg, info_size=10, min_steps=2, max_steps=20):
        if notes:
            if len(notes) > self.max_str_size:
                return False, f"Error: {emsg} len(notes[{notes[:info_size]}]) > max_str_size({self.max_str_size}), the notes should be streamlined!"
        if len(steps) > max_steps:
            return False, f"Error: {emsg} total steps({len(steps)}) exceed max_steps({max_steps})"
        if len(steps) < min_steps:
            return False, f"Error: {emsg} total steps({len(steps)}) less than min_steps({min_steps})"
        ex_steps = []
        for m in steps:
            if len(m) > self.max_str_size:
                ex_steps.append(f"{m[:info_size]}...")
        if ex_steps:
            return False, f"Error: {emsg} len(steps[{', '.join(ex_steps)}]) > max_str_size({self.max_str_size}), the steps should be streamlined!"
        return True, ""

    def _create(self, task_description: str, steps: List[str], notes=None) -> str:
        """Create a new ToDo"""
        passed, emsg = self._check_str_size(notes, steps, "CreateToDo failed!")
        if not passed:
            self.set_tool_process()
            return emsg
        self.todo_list = {
            'task_description': task_description,
            'steps': [[s, False] for s in steps],
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S"),
            'updated_at': time.strftime("%Y-%m-%d %H:%M:%S"),
            'notes': notes or ""
        }
        self.set_tool_process()
        return f"ToDo created successfully!\n\n{self._summary()}"

    def _complete_steps(self, completed_steps: List[int] = None, notes: str = "") -> str:
        """Update the ToDo with completed steps, updated steps, and notes"""
        if self._empty():
            self.set_tool_process()
            return "No active ToDo to update. Please create a ToDo first."
        cmp_count = 0
        # Update completed steps
        if completed_steps:
            for step_idx in completed_steps:
                step_idx = step_idx - 1
                if 0 <= step_idx < len(self.todo_list['steps']) and not self.todo_list['steps'][step_idx][1]:
                    self.todo_list['steps'][step_idx][1] = True
                    cmp_count += 1
        # Add notes
        if notes:
            self.todo_list['notes'] = notes
        self.todo_list['updated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.set_tool_process()
        return f"ToDo updated successfully! {cmp_count} step(s) marked as completed.\n\n{self._summary()}"

    def _undo_steps(self, steps: List[int] = None, notes: str = "") -> str:
        """Undo completed steps in the ToDo"""
        if self._empty():
            self.set_tool_process()
            return "No active ToDo to update. Please create a ToDo first."
        undo_count = 0
        # Update completed steps
        if steps:
            for step_idx in steps:
                step_idx = step_idx - 1
                if 0 <= step_idx < len(self.todo_list['steps']) and self.todo_list['steps'][step_idx][1]:
                    self.todo_list['steps'][step_idx][1] = False
                    undo_count += 1
        # Add notes
        if notes:
            self.todo_list['notes'] = notes
        self.todo_list['updated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.set_tool_process()
        return f"ToDo updated successfully! {undo_count} step(s) marked as undone.\n\n{self._summary()}"

    def _is_all_completed(self) -> bool:
        """Check if all steps in the ToDo are completed"""
        if self._empty():
            return False
        return all(is_cmp for _, is_cmp in self.todo_list['steps'])


class ToDoTool(UCTool):
    todo_panel: ToDoPanel = Field(default_factory=ToDoPanel, description="Panel managing all ToDos")
    def __init__(self, todo_panel: ToDoPanel, **data):
        super().__init__(**data)
        self.todo_panel = todo_panel


class ArgsToDoCreate(BaseModel):
    task_description: str = Field(..., description="Description of the task to be done")
    steps: List[str] = Field(..., description="List of steps to accomplish the task")


class ArgsCompleteToDoSteps(BaseModel):
    completed_steps: List[int] = Field(
        default=[], description="List of step index (1-based) that have been completed"
    )
    notes: str = Field(default="", description="Additional notes or updates about the ToDo")


class ArgsUndoToDoSteps(BaseModel):
    steps: List[int] = Field(
        default=[], description="List of step indices (1-based) to mark as not completed"
    )
    notes: str = Field(default="", description="Additional notes or updates about the ToDo")


class CreateToDo(ToDoTool):
    """Create a new Todo ToDo with detailed steps"""
    name: str = "CreateToDo"
    description: str = (
        "Create a new detailed ToDo for the current subtask. It will overwrite any existing ToDo. "
        "This helps organize the approach and track progress systematically. "
        "The steps and notes should be concise and clear. "
        "Use this when starting a new subtask or when you need to reorganize your approach."
    )
    args_schema: Optional[ArgsSchema] = ArgsToDoCreate

    def _run(self, task_description: str, steps: List[str], run_manager = None) -> str:
        """Create a new ToDo"""
        assert self.todo_panel is not None, "ToDo panel is not initialized."
        return self.todo_panel._create(task_description, steps)


class CompleteToDoSteps(ToDoTool):
    name: str = "CompleteToDoSteps"
    description: str = (
        "Update the current ToDo by marking specific steps as completed. "
        "This helps track progress and keep the ToDo up-to-date."
    )
    args_schema: Optional[ArgsSchema] = ArgsCompleteToDoSteps
    def _run(self, completed_steps: List[int] = [], notes: str = "", run_manager = None) -> str:
        """Mark steps as completed in the current ToDo"""
        assert self.todo_panel is not None, "ToDo panel is not initialized."
        return self.todo_panel._complete_steps(completed_steps, notes)


class UndoToDoSteps(ToDoTool):
    name: str = "UndoToDoSteps"
    description: str = (
        "Undo completed ToDo steps in the current ToDo by marking them as not completed. "
        "This is useful if a step was marked completed by mistake or needs to be redone."
    )
    args_schema: Optional[ArgsSchema] = ArgsUndoToDoSteps
    def _run(self, steps: List[int] = [], notes: str = "", run_manager = None) -> str:
        """Undo completed steps in the current ToDo"""
        assert self.todo_panel is not None, "ToDo panel is not initialized."
        return self.todo_panel._undo_steps(steps, notes)

class ResetToDo(ToDoTool):
    name: str = "ResetToDo"
    description: str = (
        "Reset the current ToDo, clearing all steps and notes. "
        "Use this when you want to start fresh with a new ToDo."
    )
    args_schema: Optional[ArgsSchema] = None
    def _run(self, run_manager = None) -> str:
        """Reset the current ToDo"""
        assert self.todo_panel is not None, "ToDo panel is not initialized."
        self.todo_panel._reset()
        return "Current ToDo has been reset. You can create a new ToDo now."


class GetToDoSummary(ToDoTool):
    name: str = "GetToDoSummary"
    description: str = (
        "Get a summary of the current ToDo, including task description, steps, and their completion status. "
        "Use this to review the ToDo and track progress."
    )
    args_schema: Optional[ArgsSchema] = None
    def _run(self, run_manager = None) -> str:
        """Get a summary of the current ToDo"""
        assert self.todo_panel is not None, "ToDo panel is not initialized."
        if self.todo_panel._empty():
            return "No active ToDo. Please create a ToDo first."
        return self.todo_panel._summary()


class ToDoState(ToDoTool):
    name: str = "ToDoState"
    description: str = (
        "Current ToDo list is empty, please create a new ToDo as you need."
    )
    args_schema: Optional[ArgsSchema] = None

    def __init__(self, *a, **data):
        super().__init__(*a, **data)
        self.todo_panel.set_stat_tool(self)

    def _run(self, run_manager = None) -> str:
        """Get the current state of the ToDo list"""
        return self.description
