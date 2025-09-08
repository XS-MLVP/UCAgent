#coding=utf-8

from .uctool import UCTool
from langchain_core.tools.base import ArgsSchema
from typing import Optional, List
from pydantic import BaseModel, Field
import json
import time


class ArgsPlanningCreate(BaseModel):
    """Arguments for creating a task plan"""
    task_description: str = Field(..., description="Description of the current subtask")
    steps: List[str] = Field(..., description="List of planned steps to complete the task")
    expected_outputs: List[str] = Field(default=[], description="Expected outputs or deliverables")
    priority: str = Field(default="medium", description="Priority level: high, medium, low")


class ArgsPlanningUpdate(BaseModel):
    """Arguments for updating a task plan"""
    plan_id: str = Field(..., description="ID of the plan to update")
    completed_steps: List[int] = Field(default=[], description="Indices of completed steps (0-based)")
    updated_steps: List[str] = Field(default=[], description="Updated or new steps")
    notes: str = Field(default="", description="Additional notes or observations")


class ArgsPlanningGet(BaseModel):
    """Arguments for retrieving plan information"""
    plan_id: str = Field(default="", description="ID of specific plan to retrieve (empty for current active plan)")


class PlanningTool(UCTool):
    """Base planning tool with shared functionality"""
    
    def __init__(self):
        super().__init__()
        self._plans = {}
        self._current_plan_id = None
    
    def _generate_plan_id(self) -> str:
        """Generate a unique plan ID"""
        return f"plan_{int(time.time() * 1000)}"
    
    def _get_plan_summary(self, plan: dict) -> str:
        """Get a formatted summary of a plan"""
        total_steps = len(plan['steps'])
        completed_steps = len(plan['completed_steps'])
        progress = f"{completed_steps}/{total_steps}"
        
        summary = f"Plan ID: {plan['id']}\n"
        summary += f"Task: {plan['task_description']}\n"
        summary += f"Progress: {progress} steps completed\n"
        summary += f"Priority: {plan['priority']}\n"
        summary += f"Created: {plan['created_at']}\n"
        
        if plan['notes']:
            summary += f"Notes: {plan['notes']}\n"
        
        summary += "\nSteps:\n"
        for i, step in enumerate(plan['steps']):
            status = "✓" if i in plan['completed_steps'] else "○"
            summary += f"  {status} {i+1}. {step}\n"
        
        if plan['expected_outputs']:
            summary += "\nExpected Outputs:\n"
            for output in plan['expected_outputs']:
                summary += f"  - {output}\n"
        
        return summary


class CreatePlan(PlanningTool):
    """Create a new task plan with detailed steps"""
    name: str = "CreatePlan"
    description: str = (
        "Create a new detailed plan for the current subtask. "
        "This helps organize the approach and track progress systematically. "
        "Use this when starting a new subtask or when you need to reorganize your approach."
    )
    args_schema: Optional[ArgsSchema] = ArgsPlanningCreate

    def _run(self, task_description: str, steps: List[str], expected_outputs: List[str] = None, 
             priority: str = "medium", run_manager = None) -> str:
        """Create a new plan"""
        plan_id = self._generate_plan_id()
        
        plan = {
            'id': plan_id,
            'task_description': task_description,
            'steps': steps,
            'expected_outputs': expected_outputs or [],
            'priority': priority,
            'completed_steps': [],
            'notes': '',
            'created_at': time.strftime("%Y-%m-%d %H:%M:%S"),
            'updated_at': time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        self._plans[plan_id] = plan
        self._current_plan_id = plan_id
        
        return f"Plan created successfully!\n\n{self._get_plan_summary(plan)}"


class UpdatePlan(PlanningTool):
    """Update an existing plan with progress or modifications"""
    name: str = "UpdatePlan"
    description: str = (
        "Update an existing plan by marking steps as completed, adding new steps, or adding notes. "
        "Use this to track progress and adapt the plan as work progresses."
    )
    args_schema: Optional[ArgsSchema] = ArgsPlanningUpdate

    def _run(self, plan_id: str, completed_steps: List[int] = None, updated_steps: List[str] = None, 
             notes: str = "", run_manager = None) -> str:
        """Update an existing plan"""
        if plan_id not in self._plans:
            return f"Error: Plan with ID '{plan_id}' not found."
        
        plan = self._plans[plan_id]
        
        # Update completed steps
        if completed_steps:
            for step_idx in completed_steps:
                if 0 <= step_idx < len(plan['steps']) and step_idx not in plan['completed_steps']:
                    plan['completed_steps'].append(step_idx)
        
        # Update steps
        if updated_steps:
            plan['steps'] = updated_steps
            # Reset completed steps that are now out of range
            plan['completed_steps'] = [i for i in plan['completed_steps'] if i < len(updated_steps)]
        
        # Add notes
        if notes:
            if plan['notes']:
                plan['notes'] += f"\n{notes}"
            else:
                plan['notes'] = notes
        
        plan['updated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
        
        return f"Plan updated successfully!\n\n{self._get_plan_summary(plan)}"


class GetPlan(PlanningTool):
    """Retrieve current or specific plan information"""
    name: str = "GetPlan"
    description: str = (
        "Retrieve information about the current active plan or a specific plan by ID. "
        "Use this to review the current plan, check progress, or recall previous plans."
    )
    args_schema: Optional[ArgsSchema] = ArgsPlanningGet

    def _run(self, plan_id: str = "", run_manager = None) -> str:
        """Get plan information"""
        if not plan_id:
            plan_id = self._current_plan_id
        
        if not plan_id:
            return "No active plan found. Use CreatePlan to create a new plan."
        
        if plan_id not in self._plans:
            return f"Error: Plan with ID '{plan_id}' not found."
        
        plan = self._plans[plan_id]
        return self._get_plan_summary(plan)


class ListPlans(PlanningTool):
    """List all available plans"""
    name: str = "ListPlans"
    description: str = (
        "List all available plans with basic information. "
        "Use this to see all plans that have been created."
    )

    def _run(self, run_manager = None) -> str:
        """List all plans"""
        if not self._plans:
            return "No plans found. Use CreatePlan to create a new plan."
        
        summary = f"Found {len(self._plans)} plan(s):\n\n"
        
        for plan_id, plan in self._plans.items():
            total_steps = len(plan['steps'])
            completed_steps = len(plan['completed_steps'])
            progress = f"{completed_steps}/{total_steps}"
            current_marker = " (CURRENT)" if plan_id == self._current_plan_id else ""
            
            summary += f"• {plan_id}{current_marker}\n"
            summary += f"  Task: {plan['task_description']}\n"
            summary += f"  Progress: {progress} | Priority: {plan['priority']}\n"
            summary += f"  Created: {plan['created_at']}\n\n"
        
        return summary
