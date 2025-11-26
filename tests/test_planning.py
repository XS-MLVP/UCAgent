#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test module for ucagent.tools.planning

This module contains comprehensive tests for the planning tools including:
- ToDoPanel functionality
- Planning tool classes (CreateToDo, CompleteToDoSteps, UndoToDoSteps, ResetToDo)
- Integration between tools and panel
- Edge cases and error handling
"""

import unittest
import sys
import os
from unittest.mock import patch, MagicMock
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, project_root)

from ucagent.tools.planning import (
    ToDoPanel, 
    CreateToDo, 
    CompleteToDoSteps, 
    UndoToDoSteps, 
    ResetToDo,
    GetToDoSummary,
    ArgsPlanningCreate,
    ArgsCompleteToDoSteps,
    ArgsUndoToDoSteps
)


class TestToDoPanel(unittest.TestCase):
    """Test the ToDoPanel class functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.panel = ToDoPanel()

    def test_initialization(self):
        """Test ToDoPanel initialization."""
        self.assertTrue(self.panel._empty())
        self.assertEqual(self.panel.plan, {})

    def test_empty_plan_summary(self):
        """Test summary of empty plan."""
        summary = self.panel._summary()
        self.assertIn("Plan is empty", summary)
        self.assertIn("when you understand your current task", summary)

    def test_create_plan_basic(self):
        """Test basic plan creation."""
        task_desc = "Test Task"
        steps = ["Step 1", "Step 2", "Step 3"]
        
        result = self.panel._create(task_desc, steps)
        
        # Check return message
        self.assertIn("Plan created successfully", result)
        self.assertIn(task_desc, result)
        
        # Check internal state
        self.assertFalse(self.panel._empty())
        self.assertEqual(self.panel.plan['task_description'], task_desc)
        self.assertEqual(len(self.panel.plan['steps']), 3)
        
        # Check steps format [[step_name, is_completed], ...]
        for i, step in enumerate(steps):
            self.assertEqual(self.panel.plan['steps'][i][0], step)
            self.assertEqual(self.panel.plan['steps'][i][1], False)

    def test_create_plan_with_notes(self):
        """Test plan creation with notes."""
        task_desc = "Task with notes"
        steps = ["Step A"]
        notes = "Important notes"
        
        result = self.panel._create(task_desc, steps, notes)
        
        self.assertIn("Plan created successfully", result)
        self.assertEqual(self.panel.plan['notes'], notes)

    def test_create_plan_timestamps(self):
        """Test that plan creation sets timestamps."""
        with patch('time.strftime') as mock_time:
            mock_time.return_value = "2023-01-01 12:00:00"
            
            self.panel._create("Test", ["Step 1"])
            
            self.assertEqual(self.panel.plan['created_at'], "2023-01-01 12:00:00")
            self.assertEqual(self.panel.plan['updated_at'], "2023-01-01 12:00:00")

    def test_complete_steps_basic(self):
        """Test basic step completion."""
        # First create a plan
        self.panel._create("Test Task", ["Step 1", "Step 2", "Step 3"])
        
        # Complete steps 1 and 3 (1-based indexing)
        result = self.panel._complete_steps([1, 3], "Completed first and third")
        
        # Check return message
        self.assertIn("2 step(s) marked as completed", result)
        self.assertIn("Completed first and third", result)
        
        # Check internal state
        self.assertTrue(self.panel.plan['steps'][0][1])   # Step 1 completed
        self.assertFalse(self.panel.plan['steps'][1][1])  # Step 2 not completed
        self.assertTrue(self.panel.plan['steps'][2][1])   # Step 3 completed
        self.assertEqual(self.panel.plan['notes'], "Completed first and third")

    def test_complete_steps_empty_plan(self):
        """Test completing steps when no plan exists."""
        result = self.panel._complete_steps([1], "Test notes")
        self.assertIn("No active plan to update", result)

    def test_complete_steps_invalid_indices(self):
        """Test completing steps with invalid indices."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        
        # Try to complete invalid step indices
        result = self.panel._complete_steps([0, 5, -1], "Invalid indices")
        
        # Should not crash and should report 0 steps completed
        self.assertIn("0 step(s) marked as completed", result)

    def test_complete_steps_already_completed(self):
        """Test completing steps that are already completed."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        
        # Complete step 1
        self.panel._complete_steps([1])
        
        # Try to complete step 1 again
        result = self.panel._complete_steps([1])
        
        # Should report 0 new completions
        self.assertIn("0 step(s) marked as completed", result)

    def test_undo_steps_basic(self):
        """Test basic step undo functionality."""
        # Create plan and complete some steps
        self.panel._create("Test", ["Step 1", "Step 2", "Step 3"])
        self.panel._complete_steps([1, 2])
        
        # Undo step 1
        result = self.panel._undo_steps([1], "Undoing step 1")
        
        # Check return message
        self.assertIn("1 step(s) marked as undone", result)
        self.assertIn("Undoing step 1", result)
        
        # Check internal state
        self.assertFalse(self.panel.plan['steps'][0][1])  # Step 1 undone
        self.assertTrue(self.panel.plan['steps'][1][1])   # Step 2 still completed
        self.assertEqual(self.panel.plan['notes'], "Undoing step 1")

    def test_undo_steps_empty_plan(self):
        """Test undoing steps when no plan exists."""
        result = self.panel._undo_steps([1])
        self.assertIn("No active plan to update", result)

    def test_undo_steps_not_completed(self):
        """Test undoing steps that are not completed."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        
        # Try to undo steps that were never completed
        result = self.panel._undo_steps([1, 2])
        
        # Should report 0 undos
        self.assertIn("0 step(s) marked as undone", result)

    def test_summary_with_completed_steps(self):
        """Test plan summary with completed steps."""
        self.panel._create("Test Task", ["Step 1", "Step 2", "Step 3"])
        self.panel._complete_steps([1, 3])
        
        summary = self.panel._summary()
        
        # Check that summary shows completed steps
        self.assertIn("Test Task", summary)
        self.assertIn("1(completed): Step 1", summary)
        self.assertIn("2: Step 2", summary)  # Not completed
        self.assertIn("3(completed): Step 3", summary)

    def test_is_all_completed_false(self):
        """Test _is_all_completed when not all steps are completed."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        self.panel._complete_steps([1])
        
        self.assertFalse(self.panel._is_all_completed())

    def test_is_all_completed_true(self):
        """Test _is_all_completed when all steps are completed."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        self.panel._complete_steps([1, 2])
        
        self.assertTrue(self.panel._is_all_completed())

    def test_is_all_completed_empty_plan(self):
        """Test _is_all_completed with empty plan."""
        self.assertFalse(self.panel._is_all_completed())

    def test_summary_all_completed_message(self):
        """Test that summary shows completion message when all steps done."""
        self.panel._create("Test", ["Step 1", "Step 2"])
        self.panel._complete_steps([1, 2])
        
        summary = self.panel._summary()
        self.assertIn("All steps are completed", summary)

    def test_reset_plan(self):
        """Test plan reset functionality."""
        # Create a plan with some completed steps
        self.panel._create("Test", ["Step 1", "Step 2"])
        self.panel._complete_steps([1])
        
        # Verify plan exists
        self.assertFalse(self.panel._empty())
        
        # Reset the plan
        self.panel._reset()
        
        # Verify plan is empty
        self.assertTrue(self.panel._empty())
        self.assertEqual(self.panel.plan, {})

    def test_update_timestamps(self):
        """Test that operations update the timestamp."""
        with patch('time.strftime') as mock_time:
            # Set initial time for creation
            mock_time.return_value = "2023-01-01 12:00:00"
            self.panel._create("Test", ["Step 1"])
            
            # Set different time for update
            mock_time.return_value = "2023-01-01 13:00:00"
            self.panel._complete_steps([1])
            
            self.assertEqual(self.panel.plan['created_at'], "2023-01-01 12:00:00")
            self.assertEqual(self.panel.plan['updated_at'], "2023-01-01 13:00:00")


class TestPlanningTools(unittest.TestCase):
    """Test the planning tool classes."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.panel = ToDoPanel()
        
        self.create_tool = CreateToDo(todo_panel=self.panel)
        self.complete_tool = CompleteToDoSteps(todo_panel=self.panel)
        self.undo_tool = UndoToDoSteps(todo_panel=self.panel)
        self.reset_tool = ResetToDo(todo_panel=self.panel)
        self.get_summary_tool = GetToDoSummary(todo_panel=self.panel)

    def test_tool_initialization(self):
        """Test that tools are properly initialized with panel."""
        self.assertIs(self.create_tool.todo_panel, self.panel)
        self.assertIs(self.complete_tool.todo_panel, self.panel)
        self.assertIs(self.undo_tool.todo_panel, self.panel)
        self.assertIs(self.reset_tool.todo_panel, self.panel)
        self.assertIs(self.get_summary_tool.todo_panel, self.panel)

    def test_tool_names_and_descriptions(self):
        """Test that tools have proper names and descriptions."""
        self.assertEqual(self.create_tool.name, "CreateToDo")
        self.assertEqual(self.complete_tool.name, "CompleteToDoSteps")
        self.assertEqual(self.undo_tool.name, "UndoToDoSteps")
        self.assertEqual(self.reset_tool.name, "ResetToDo")
        self.assertEqual(self.get_summary_tool.name, "GetToDoSummary")
        
        # Check descriptions are not empty
        self.assertTrue(len(self.create_tool.description) > 0)
        self.assertTrue(len(self.complete_tool.description) > 0)
        self.assertTrue(len(self.undo_tool.description) > 0)
        self.assertTrue(len(self.reset_tool.description) > 0)
        self.assertTrue(len(self.get_summary_tool.description) > 0)
        self.assertTrue(len(self.undo_tool.description) > 0)
        self.assertTrue(len(self.reset_tool.description) > 0)

    def test_create_plan_tool(self):
        """Test CreateToDo tool functionality."""
        result = self.create_tool._run("Test Task", ["Step 1", "Step 2"])
        
        self.assertIn("Plan created successfully", result)
        self.assertFalse(self.panel._empty())

    def test_complete_plan_steps_tool(self):
        """Test CompleteToDoSteps tool functionality."""
        # First create a plan
        self.create_tool._run("Test", ["Step 1", "Step 2"])
        
        # Then complete steps
        result = self.complete_tool._run([1], "Completed step 1")
        
        self.assertIn("1 step(s) marked as completed", result)
        self.assertTrue(self.panel.plan['steps'][0][1])

    def test_undo_plan_steps_tool(self):
        """Test UndoToDoSteps tool functionality."""
        # Create plan and complete steps
        self.create_tool._run("Test", ["Step 1", "Step 2"])
        self.complete_tool._run([1, 2])
        
        # Undo step 1
        result = self.undo_tool._run([1], "Undoing step 1")
        
        self.assertIn("1 step(s) marked as undone", result)
        self.assertFalse(self.panel.plan['steps'][0][1])

    def test_reset_plan_tool(self):
        """Test ResetToDo tool functionality."""
        # Create a plan
        self.create_tool._run("Test", ["Step 1"])
        self.assertFalse(self.panel._empty())
        
        # Reset the plan
        result = self.reset_tool._run()
        
        self.assertIn("plan has been reset", result)
        self.assertTrue(self.panel._empty())

    def test_get_plan_summary_tool(self):
        """Test GetToDoSummary tool functionality."""
        # Test with empty plan
        result = self.get_summary_tool._run()
        self.assertIn("No active plan", result)
        
        # Create a plan and test summary
        self.create_tool._run("Summary Test", ["Step A", "Step B"])
        self.complete_tool._run([1])
        
        result = self.get_summary_tool._run()
        self.assertIn("Summary Test", result)
        self.assertIn("Step A", result)
        self.assertIn("Step B", result)
        self.assertIn("Plan Panel", result)

    def test_tools_share_state(self):
        """Test that all tools share the same panel state."""
        # Create plan with one tool
        self.create_tool._run("Shared Test", ["Step A", "Step B"])
        
        # Complete steps with another tool
        self.complete_tool._run([1])
        
        # Verify state is shared using GetToDoSummary
        summary = self.get_summary_tool._run()
        self.assertIn("Shared Test", summary)
        self.assertIn("1(completed): Step A", summary)
        
        # Undo with third tool
        self.undo_tool._run([1])
        
        # Verify undo worked
        self.assertFalse(self.panel.plan['steps'][0][1])
        
        # Reset with fourth tool
        self.reset_tool._run()
        
        # Verify reset worked
        self.assertTrue(self.panel._empty())

    def test_complete_tool_default_parameters(self):
        """Test CompleteToDoSteps with default parameters."""
        self.create_tool._run("Test", ["Step 1"])
        
        # Call with default parameters (empty lists and strings)
        result = self.complete_tool._run()
        
        # Should not complete any steps
        self.assertIn("0 step(s) marked as completed", result)

    def test_undo_tool_default_parameters(self):
        """Test UndoToDoSteps with default parameters."""
        self.create_tool._run("Test", ["Step 1"])
        self.complete_tool._run([1])
        
        # Call with default parameters
        result = self.undo_tool._run()
        
        # Should not undo any steps
        self.assertIn("0 step(s) marked as undone", result)


class TestPlanningToolArguments(unittest.TestCase):
    """Test the argument schemas for planning tools."""

    def test_args_planning_create_schema(self):
        """Test ArgsPlanningCreate schema validation."""
        # Valid arguments
        valid_args = ArgsPlanningCreate(
            task_description="Test task",
            steps=["Step 1", "Step 2"]
        )
        self.assertEqual(valid_args.task_description, "Test task")
        self.assertEqual(valid_args.steps, ["Step 1", "Step 2"])

    def test_args_complete_plan_steps_schema(self):
        """Test ArgsCompleteToDoSteps schema validation."""
        # Valid arguments with values
        args_with_values = ArgsCompleteToDoSteps(
            completed_steps=[1, 2],
            notes="Test notes"
        )
        self.assertEqual(args_with_values.completed_steps, [1, 2])
        self.assertEqual(args_with_values.notes, "Test notes")
        
        # Valid arguments with defaults
        args_defaults = ArgsCompleteToDoSteps()
        self.assertEqual(args_defaults.completed_steps, [])
        self.assertEqual(args_defaults.notes, "")

    def test_args_undo_plan_steps_schema(self):
        """Test ArgsUndoToDoSteps schema validation."""
        # Valid arguments with values
        args_with_values = ArgsUndoToDoSteps(
            steps=[1, 3],
            notes="Undo notes"
        )
        self.assertEqual(args_with_values.steps, [1, 3])
        self.assertEqual(args_with_values.notes, "Undo notes")
        
        # Valid arguments with defaults
        args_defaults = ArgsUndoToDoSteps()
        self.assertEqual(args_defaults.steps, [])
        self.assertEqual(args_defaults.notes, "")


class TestPlanningIntegration(unittest.TestCase):
    """Test integration scenarios and edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.panel = ToDoPanel()
        self.create_tool = CreateToDo(todo_panel=self.panel)
        self.complete_tool = CompleteToDoSteps(todo_panel=self.panel)
        self.undo_tool = UndoToDoSteps(todo_panel=self.panel)
        self.reset_tool = ResetToDo(todo_panel=self.panel)
        self.get_summary_tool = GetToDoSummary(todo_panel=self.panel)

    def test_full_workflow(self):
        """Test a complete planning workflow."""
        # 1. Create a plan
        result = self.create_tool._run("Complete Project", [
            "Design architecture",
            "Implement core features", 
            "Write tests",
            "Deploy to production"
        ])
        self.assertIn("Plan created successfully", result)
        
        # 2. Complete some steps
        result = self.complete_tool._run([1, 2], "Architecture and core features done")
        self.assertIn("2 step(s) marked as completed", result)
        
        # 3. Check progress
        summary = self.panel._summary()
        self.assertIn("1(completed): Design architecture", summary)
        self.assertIn("2(completed): Implement core features", summary)
        self.assertIn("3: Write tests", summary)  # Not completed
        
        # 4. Undo one step (found issue)
        result = self.undo_tool._run([2], "Found bug in core features")
        self.assertIn("1 step(s) marked as undone", result)
        
        # 5. Complete remaining steps
        result = self.complete_tool._run([2, 3, 4], "All remaining work completed")
        self.assertIn("3 step(s) marked as completed", result)
        
        # 6. Verify all completed
        self.assertTrue(self.panel._is_all_completed())
        summary = self.panel._summary()
        self.assertIn("All steps are completed", summary)

    def test_multiple_plan_cycles(self):
        """Test creating multiple plans in sequence."""
        # First plan
        self.create_tool._run("Plan 1", ["Task A", "Task B"])
        self.complete_tool._run([1])
        
        # Verify first plan state
        self.assertIn("Plan 1", self.panel._summary())
        self.assertTrue(self.panel.plan['steps'][0][1])
        
        # Reset and create new plan
        self.reset_tool._run()
        self.create_tool._run("Plan 2", ["Task X", "Task Y", "Task Z"])
        
        # Verify new plan
        summary = self.panel._summary()
        self.assertIn("Plan 2", summary)
        self.assertNotIn("Plan 1", summary)
        self.assertEqual(len(self.panel.plan['steps']), 3)
        
        # All steps should be incomplete in new plan
        for step in self.panel.plan['steps']:
            self.assertFalse(step[1])

    def test_edge_case_empty_steps_list(self):
        """Test creating plan with empty steps list."""
        result = self.create_tool._run("Empty Plan", [])
        
        self.assertIn("Plan created successfully", result)
        self.assertEqual(len(self.panel.plan['steps']), 0)
        
        # Should be considered "all completed" since there are no steps
        self.assertTrue(self.panel._is_all_completed())

    def test_edge_case_single_step_plan(self):
        """Test plan with only one step."""
        self.create_tool._run("Single Step", ["Only step"])
        
        # Complete the single step
        result = self.complete_tool._run([1])
        self.assertIn("1 step(s) marked as completed", result)
        
        # Should be all completed
        self.assertTrue(self.panel._is_all_completed())
        summary = self.panel._summary()
        self.assertIn("All steps are completed", summary)

    def test_plan_with_special_characters(self):
        """Test plan with special characters in descriptions."""
        special_task = "Test with 特殊字符 and émojis 🚀"
        special_steps = [
            "Step with üñíçødé",
            "Step with symbols: @#$%^&*()",
            "Step with newlines\nand\ttabs"
        ]
        
        result = self.create_tool._run(special_task, special_steps)
        
        self.assertIn("Plan created successfully", result)
        self.assertEqual(self.panel.plan['task_description'], special_task)
        
        # Complete and check summary
        self.complete_tool._run([1])
        summary = self.panel._summary()
        self.assertIn(special_task, summary)
        self.assertIn("üñíçødé", summary)

    def test_concurrent_operations_simulation(self):
        """Test that operations maintain consistency."""
        # Create plan
        self.create_tool._run("Concurrent Test", ["Step 1", "Step 2", "Step 3"])
        
        # Simulate rapid operations
        self.complete_tool._run([1, 2])
        self.undo_tool._run([1])
        self.complete_tool._run([1, 3])
        self.undo_tool._run([2, 3])
        self.complete_tool._run([1, 2, 3])
        
        # Final state should be all completed
        self.assertTrue(self.panel._is_all_completed())

    def test_notes_accumulation(self):
        """Test how notes are handled across operations."""
        self.create_tool._run("Notes Test", ["Step 1", "Step 2"], "Initial notes")
        
        # Add more notes through completion
        self.complete_tool._run([1], "Completed step 1")
        self.assertEqual(self.panel.plan['notes'], "Completed step 1")
        
        # Add more notes through undo
        self.undo_tool._run([1], "Undoing step 1 due to issue")
        self.assertEqual(self.panel.plan['notes'], "Undoing step 1 due to issue")
        
        # Notes should appear in summary
        summary = self.panel._summary()
        print(summary)
        self.assertIn("Undoing step 1 due to issue", summary)


if __name__ == '__main__':
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestToDoPanel))
    suite.addTests(loader.loadTestsFromTestCase(TestPlanningTools))
    suite.addTests(loader.loadTestsFromTestCase(TestPlanningToolArguments))
    suite.addTests(loader.loadTestsFromTestCase(TestPlanningIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=3)
    result = runner.run(suite)
    
    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)