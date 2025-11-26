# -*- coding: utf-8 -*-
"""
Enhanced interaction logic for the verify agent.
This module provides improved interaction management with planning, memory management,
and intelligent tool usage.
"""

import copy
import time
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from ucagent.util.log import info, warning, error
from ucagent.util.functions import yam_str


class InteractionState:
    """Manages the state of agent interactions"""
    
    def __init__(self):
        self.current_phase = "planning"  # planning, execution, verification, reflection
        self.planning_attempts = 0
        self.execution_attempts = 0
        self.max_planning_attempts = 2
        self.max_execution_attempts = 3
        self.phase_history = []
        self.important_context = []
        self.last_reflection_round = 0
        self.reflection_interval = 3  # Reflect every 3 rounds
        
    def transition_to_phase(self, new_phase: str):
        """Transition to a new phase"""
        self.phase_history.append({
            'from': self.current_phase,
            'to': new_phase,
            'timestamp': time.time(),
            'round': len(self.phase_history)
        })
        self.current_phase = new_phase
        info(f"Phase transition: {self.phase_history[-1]['from']} -> {new_phase}")
    
    def should_reflect(self, current_round: int) -> bool:
        """Check if it's time for reflection"""
        return (current_round - self.last_reflection_round) >= self.reflection_interval
    
    def mark_reflection(self, current_round: int):
        """Mark that reflection has occurred"""
        self.last_reflection_round = current_round
    
    def reset_phase_attempts(self):
        """Reset attempt counters for current phase"""
        if self.current_phase == "planning":
            self.planning_attempts = 0
        elif self.current_phase == "execution":
            self.execution_attempts = 0


class EnhancedInteractionLogic:
    """Enhanced interaction logic for better task planning and execution"""
    
    def __init__(self, agent):
        self.agent = agent
        self.state = InteractionState()
        self.planning_tools = None
        self._init_planning_tools()
    
    def _init_planning_tools(self):
        """Initialize planning tools"""
        try:
            from ucagent.tools.planning import CreateToDo, CompleteToDoSteps, UndoToDoSteps, ResetToDo, GetToDoSummary, ToDoPanel
            # Create shared plan panel
            self.todo_panel = ToDoPanel()
            self.planning_tools = {
                'create': CreateToDo(todo_panel=self.todo_panel),
                'complete': CompleteToDoSteps(todo_panel=self.todo_panel),
                'undo': UndoToDoSteps(todo_panel=self.todo_panel),
                'reset': ResetToDo(todo_panel=self.todo_panel),
                'summary': GetToDoSummary(todo_panel=self.todo_panel)
            }
        except Exception as e:
            warning(f"Failed to initialize planning tools: {e}")
            self.planning_tools = None
            self.todo_panel = None
    
    def enhanced_one_loop(self, msg: str = None):
        """Enhanced one_loop with improved interaction logic"""
        if msg:
            self.agent.set_continue_msg(msg)
        
        # Determine the appropriate interaction strategy based on current state
        interaction_strategy = self._determine_interaction_strategy()
        
        # Execute the strategy
        if interaction_strategy == "planning_required":
            self._handle_planning_phase()
        elif interaction_strategy == "execution_with_guidance":
            self._handle_execution_phase()
        elif interaction_strategy == "reflection_needed":
            self._handle_reflection_phase()
        elif interaction_strategy == "memory_consolidation":
            self._handle_memory_consolidation()
        else:
            # Fallback to standard loop
            self._handle_standard_execution()
        
        self.agent.invoke_round += 1
        return self.agent
    
    def _determine_interaction_strategy(self) -> str:
        """Determine the best interaction strategy based on current context"""
        current_round = self.agent.invoke_round
        
        # Check if reflection is needed
        if self.state.should_reflect(current_round) and current_round > 0:
            return "reflection_needed"
        
        # Check if we're starting a new task or haven't planned yet
        if (self.state.current_phase == "planning" or 
            self.state.planning_attempts == 0 and current_round % 5 == 0):
            return "planning_required"
        
        # Check if we need memory consolidation
        if current_round > 0 and current_round % 7 == 0:
            return "memory_consolidation"
        
        # Default to execution with guidance
        if self.state.current_phase in ["execution", "verification"]:
            return "execution_with_guidance"
        
        return "standard_execution"
    
    def _handle_planning_phase(self):
        """Handle the planning phase with explicit planning steps"""
        info("Entering planning phase")
        self.state.transition_to_phase("planning")
        self.state.planning_attempts += 1
        
        # Get current task context
        current_tips = self.agent.stage_manager.get_current_tips()
        
        # Create enhanced planning message
        planning_message = self._create_planning_message(current_tips)
        
        # Execute planning
        self._execute_with_message(planning_message)
        
        # Transition to execution phase
        self.state.transition_to_phase("execution")
    
    def _handle_execution_phase(self):
        """Handle the execution phase with progress tracking"""
        info("Entering execution phase")
        self.state.execution_attempts += 1
        
        # Get current plan status
        plan_status = self._get_current_plan_status()
        
        # Create execution message with plan guidance
        execution_message = self._create_execution_message(plan_status)
        
        # Execute with guidance
        self._execute_with_message(execution_message)
        
        # Check if we need to transition phases
        if self.state.execution_attempts >= self.state.max_execution_attempts:
            self.state.transition_to_phase("verification")
    
    def _handle_reflection_phase(self):
        """Handle the reflection phase for self-assessment"""
        info("Entering reflection phase")
        self.state.mark_reflection(self.agent.invoke_round)
        
        # Create reflection message
        reflection_message = self._create_reflection_message()
        
        # Execute reflection
        self._execute_with_message(reflection_message)
        
        # Reset to planning or execution based on reflection results
        self.state.transition_to_phase("execution")
    
    def _handle_memory_consolidation(self):
        """Handle memory consolidation phase"""
        info("Entering memory consolidation phase")
        
        # Create memory consolidation message
        memory_message = self._create_memory_consolidation_message()
        
        # Execute memory consolidation
        self._execute_with_message(memory_message)
    
    def _handle_standard_execution(self):
        """Handle standard execution (fallback)"""
        info("Using standard execution approach")
        self.agent.one_loop()
    
    def _create_planning_message(self, current_tips: str) -> str:
        """Create a planning-focused message"""
        planning_prompt = f"""
PLANNING PHASE - Let's create a detailed plan for the current subtask.

Current Task Context:
{current_tips}

Please follow this planning process:

1. ANALYZE THE TASK:
   - Use SemanticSearchInGuidDoc to search for relevant documentation and examples
   - Understand the specific requirements and constraints
   - Identify key components that need to be addressed

2. CREATE A DETAILED PLAN:
   - Use CreateToDo to create a structured plan with specific steps
   - Break down the task into manageable, concrete steps
   - Define expected outputs for each major step
   - Set appropriate priority level

3. GATHER NECESSARY INFORMATION:
   - Use MemoryGet to retrieve any relevant previous work or context
   - Review relevant files using ReadTextFile
   - Document important findings

4. SAVE PLANNING INSIGHTS:
   - Use MemoryPut to save the planning insights and approach
   - Store scope as 'planning' with current task context

Start with step 1 - analyze the task using available documentation and context.
"""
        return planning_prompt
    
    def _create_execution_message(self, plan_status: str) -> str:
        """Create an execution-focused message with plan guidance"""
        execution_prompt = f"""
EXECUTION PHASE - Execute the planned steps systematically.

Current Plan Status:
{plan_status}

Execution Guidelines:

1. FOLLOW THE PLAN:
   - Execute the next incomplete step from your plan
   - Use CompleteToDoSteps to mark completed steps when finished
   - If you encounter issues, consider using ResetToDo to create a new approach

2. USE AVAILABLE TOOLS STRATEGICALLY:
   - SemanticSearchInGuidDoc: When you need reference information or examples
   - MemoryPut/MemoryGet: Store and retrieve important discoveries or results
   - File tools: Read, write, and manage files as needed
   - Check tools: Verify your work meets requirements

3. TRACK PROGRESS:
   - Document significant findings and decisions
   - Use CompleteToDoSteps to mark steps as completed when finished
   - Save important intermediate results to memory

4. MAINTAIN QUALITY:
   - Verify each step meets the requirements before moving on
   - Use reflection if you encounter unexpected obstacles

Focus on executing the next step in your plan. Be systematic and thorough.
"""
        return execution_prompt
    
    def _create_reflection_message(self) -> str:
        """Create a reflection-focused message"""
        reflection_prompt = f"""
REFLECTION PHASE - Time to assess progress and adjust approach.

Please conduct a comprehensive reflection:

1. ASSESS CURRENT PROGRESS:
   - Review your current plan status (the plan summary is available)
   - What has been accomplished successfully?
   - What challenges or obstacles have you encountered?

2. EVALUATE APPROACH:
   - Are the current steps effective?
   - Is there a better or more efficient approach?
   - What have you learned that wasn't anticipated in the original plan?

3. USE REFLECTION TOOLS:
   - If available, use the Reflect tool for structured self-assessment
   - Consider using SqThink for sequential reasoning about next steps

4. CONSOLIDATE INSIGHTS:
   - Use MemoryPut to save important insights from this reflection
   - If major changes needed, use ResetToDo to create a new approach
   - Document any major strategy changes

5. PLAN NEXT STEPS:
   - What are the most important next actions?
   - Are there any risks or dependencies to consider?
   - Should the approach be modified?

Begin with assessing your current progress and plan status.
"""
        return reflection_prompt
    
    def _create_memory_consolidation_message(self) -> str:
        """Create a memory consolidation message"""
        memory_prompt = f"""
MEMORY CONSOLIDATION PHASE - Organize and preserve important information.

Please consolidate important information and insights:

1. REVIEW RECENT WORK:
   - What important discoveries or results have been achieved recently?
   - What key insights or lessons learned should be preserved?
   - Are there any important intermediate results or configurations?

2. ORGANIZE MEMORY:
   - Use MemoryPut to save important findings with appropriate scope
   - Organize information by categories: 'task-specific', 'technical-insights', 'lessons-learned'
   - Ensure critical context is preserved for future reference

3. UPDATE DOCUMENTATION:
   - Document any significant discoveries in appropriate files
   - Update plans or status information if needed

4. PREPARE FOR CONTINUATION:
   - What context will be most important for future work?
   - Are there any critical dependencies or requirements to remember?

Focus on preserving the most valuable insights and context from recent work.
"""
        return memory_prompt
    
    def _get_current_plan_status(self) -> str:
        """Get the current plan status"""
        if self.todo_panel:
            try:
                return self.todo_panel._summary()
            except Exception as e:
                warning(f"Failed to get plan status: {e}")
        return "No active plan available. Consider creating a plan with CreateToDo."
    
    def _execute_with_message(self, message: str):
        """Execute the agent with a specific message"""
        # Set the custom message
        self.agent.set_continue_msg(message)
        
        # Execute one loop with the message
        while True:
            tips = self.agent.get_current_tips()
            if self.agent.is_exit():
                return
            self.agent.do_work(tips, self.agent.get_work_config())
            if not self.agent._tool__call_error:
                break
            if self.agent.is_break():
                return
    
    def get_interaction_status(self) -> Dict[str, Any]:
        """Get current interaction status"""
        return {
            'current_phase': self.state.current_phase,
            'planning_attempts': self.state.planning_attempts,
            'execution_attempts': self.state.execution_attempts,
            'phase_history': self.state.phase_history[-5:],  # Last 5 transitions
            'last_reflection_round': self.state.last_reflection_round,
            'current_round': self.agent.invoke_round
        }
