# -*- coding: utf-8 -*-
"""Planning and task management tools for UCAgent."""

from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from typing import Optional, List
from pydantic import BaseModel, Field
import vagent.util.functions as fc
import time
from collections import OrderedDict


class PlanPanel:

    def __init__(self, max_str_size=100):
        self.max_str_size = max_str_size
        self.plan = {
            # 'current_task_description': str, 'steps': List[str, is_completed: bool], 'notes': str
        }
        self._reset()

    def _reset(self):
        """Reset the current plan"""
        self.plan = {}

    def _summary(self) -> str:
        """Get a formatted summary of a plan"""
        if self._empty():
            return "\nPlan is empty, please create it as you need."
        def as_cmp_str(is_cmp):
            return "(completed)" if is_cmp else ""
        steps = [
            f"{i+1}{as_cmp_str(is_cmp)}: {desc}" for i, (desc, is_cmp) in enumerate(self.plan['steps'])
        ]
        if self._is_all_completed():
            return "\nAll plan steps are completed! You can create new one depending on your needs."
        steps_text = "\n  ".join(steps)
        return f"\n-------- Plan Panel --------\n" \
               f" Task Description: {self.plan['task_description']}\n" \
               f" Steps:\n  {steps_text}\n" \
               f" Created At: {self.plan['created_at']}\n" \
               f" Updated At: {self.plan['updated_at']}\n" \
               f" Notes: {self.plan.get('notes', 'None')}" \
               f"\n----------------------------\n"

    def _empty(self) -> bool:
        return not bool(self.plan)

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
        """Create a new plan"""
        passed, emsg = self._check_str_size(notes, steps, "CreatePlan failed!")
        if not passed:
            return emsg
        self.plan = {
            'task_description': task_description,
            'steps': [[s, False] for s in steps],
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S"),
            'updated_at': time.strftime("%Y-%m-%d %H:%M:%S"),
            'notes': notes or ""
        }
        return f"Plan created successfully!\n\n{self._summary()}"

    def _complete_steps(self, completed_steps: List[int] = None, notes: str = "") -> str:
        """Update the plan with completed steps, updated steps, and notes"""
        if self._empty():
            return "No active plan to update. Please create a plan first."
        cmp_count = 0
        # Update completed steps
        if completed_steps:
            for step_idx in completed_steps:
                step_idx = step_idx - 1
                if 0 <= step_idx < len(self.plan['steps']) and not self.plan['steps'][step_idx][1]:
                    self.plan['steps'][step_idx][1] = True
                    cmp_count += 1
        # Add notes
        if notes:
            self.plan['notes'] = notes
        self.plan['updated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
        return f"Plan updated successfully! {cmp_count} step(s) marked as completed.\n\n{self._summary()}"

    def _undo_steps(self, steps: List[int] = None, notes: str = "") -> str:
        """Undo completed steps in the plan"""
        if self._empty():
            return "No active plan to update. Please create a plan first."
        undo_count = 0
        # Update completed steps
        if steps:
            for step_idx in steps:
                step_idx = step_idx - 1
                if 0 <= step_idx < len(self.plan['steps']) and self.plan['steps'][step_idx][1]:
                    self.plan['steps'][step_idx][1] = False
                    undo_count += 1
        # Add notes
        if notes:
            self.plan['notes'] = notes
        self.plan['updated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
        return f"Plan updated successfully! {undo_count} step(s) marked as undone.\n\n{self._summary()}"

    def _is_all_completed(self) -> bool:
        """Check if all steps in the plan are completed"""
        if self._empty():
            return False
        return all(is_cmp for _, is_cmp in self.plan['steps'])


class PlanningTool(UCTool):
    plan_panel: PlanPanel = Field(default_factory=PlanPanel, description="Panel managing all plans")
    def __init__(self, plan_panel: PlanPanel, **data):
        super().__init__(**data)
        self.plan_panel = plan_panel


class ArgsPlanningCreate(BaseModel):
    task_description: str = Field(..., description="Description of the task to be planned")
    steps: List[str] = Field(..., description="List of steps to accomplish the task")


class ArgsCompletePlanSteps(BaseModel):
    completed_steps: List[int] = Field(
        default=[], description="List of step index (1-based) that have been completed"
    )
    notes: str = Field(default="", description="Additional notes or updates about the plan")


class ArgsUndoPlanSteps(BaseModel):
    steps: List[int] = Field(
        default=[], description="List of step indices (1-based) to mark as not completed"
    )
    notes: str = Field(default="", description="Additional notes or updates about the plan")


class CreatePlan(PlanningTool):
    """Create a new task plan with detailed steps"""
    name: str = "CreatePlan"
    description: str = (
        "Create a new detailed plan for the current subtask. It will overwrite any existing plan. "
        "This helps organize the approach and track progress systematically. "
        "The steps and notes should be concise and clear. "
        "Use this when starting a new subtask or when you need to reorganize your approach."
    )
    args_schema: Optional[ArgsSchema] = ArgsPlanningCreate

    def _run(self, task_description: str, steps: List[str], run_manager = None) -> str:
        """Create a new plan"""
        assert self.plan_panel is not None, "Plan panel is not initialized."
        return self.plan_panel._create(task_description, steps)


class CompletePlanSteps(PlanningTool):
    name: str = "CompletePlanSteps"
    description: str = (
        "Update the current plan by marking specific steps as completed. "
        "This helps track progress and keep the plan up-to-date."
    )
    args_schema: Optional[ArgsSchema] = ArgsCompletePlanSteps
    def _run(self, completed_steps: List[int] = [], notes: str = "", run_manager = None) -> str:
        """Mark steps as completed in the current plan"""
        assert self.plan_panel is not None, "Plan panel is not initialized."
        return self.plan_panel._complete_steps(completed_steps, notes)


class UndoPlanSteps(PlanningTool):
    name: str = "UndoPlanSteps"
    description: str = (
        "Undo completed steps in the current plan by marking them as not completed. "
        "This is useful if a step was marked completed by mistake or needs to be redone."
    )
    args_schema: Optional[ArgsSchema] = ArgsUndoPlanSteps
    def _run(self, steps: List[int] = [], notes: str = "", run_manager = None) -> str:
        """Undo completed steps in the current plan"""
        assert self.plan_panel is not None, "Plan panel is not initialized."
        return self.plan_panel._undo_steps(steps, notes)

class ResetPlan(PlanningTool):
    name: str = "ResetPlan"
    description: str = (
        "Reset the current plan, clearing all steps and notes. "
        "Use this when you want to start fresh with a new plan."
    )
    args_schema: Optional[ArgsSchema] = None
    def _run(self, run_manager = None) -> str:
        """Reset the current plan"""
        assert self.plan_panel is not None, "Plan panel is not initialized."
        self.plan_panel._reset()
        return "Current plan has been reset. You can create a new plan now."


class GetPlanSummary(PlanningTool):
    name: str = "GetPlanSummary"
    description: str = (
        "Get a summary of the current plan, including task description, steps, and their completion status. "
        "Use this to review the plan and track progress."
    )
    args_schema: Optional[ArgsSchema] = None
    def _run(self, run_manager = None) -> str:
        """Get a summary of the current plan"""
        assert self.plan_panel is not None, "Plan panel is not initialized."
        if self.plan_panel._empty():
            return "No active plan. Please create a plan first."
        return self.plan_panel._summary()
