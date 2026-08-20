# -*- coding: utf-8 -*-
"""
Tool orchestrator for intelligent tool selection and usage optimization.
This module provides context-aware tool recommendations and usage guidance.
"""

import copy
import time
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum
from ucagent.util.log import info, warning, error


class ToolCategory(Enum):
    """Categories for tool classification"""
    SEARCH = "search"
    MEMORY = "memory"
    FILE_OPS = "file_operations"
    VERIFICATION = "verification"
    PLANNING = "planning"
    ANALYSIS = "analysis"
    REFLECTION = "reflection"
    EXECUTION = "execution"


class ToolRecommendationEngine:
    """Engine for providing intelligent tool recommendations"""
    
    def __init__(self):
        self.tool_categories = self._initialize_tool_categories()
        self.usage_patterns = {}
        self.context_tool_mapping = self._initialize_context_mappings()
    
    def _initialize_tool_categories(self) -> Dict[ToolCategory, List[str]]:
        """Initialize tool categorization"""
        return {
            ToolCategory.SEARCH: [
                'SemanticSearchInGuidDoc', 'ReadTextFile', 'PathList',
                'SearchText', 'FindFiles'
            ],
            ToolCategory.MEMORY: [
                'MemoryPut', 'MemoryGet'
            ],
            ToolCategory.FILE_OPS: [
                'ReadTextFile', 'EditTextFile', 'MoveFile',
                'DeleteFile', 'CreateDirectory', 'PathList'
            ],
            ToolCategory.VERIFICATION: [
                'RunTestCases', 'Status', 'Detail', 'CurrentTips'
            ],
            ToolCategory.PLANNING: [
                'CreateToDo', 'CompleteToDoSteps', 'UndoToDoSteps', 'ResetToDo', 'GetToDoSummary'
            ],
            ToolCategory.ANALYSIS: [
                'GetFileInfo', 'SearchText', 'ReadTextFile',
                'ReadBinFile'
            ],
            ToolCategory.REFLECTION: [
                'Reflect', 'HumanHelp'
            ],
            ToolCategory.EXECUTION: [
                'RunTestCases', 'EditTextFile', 'ReplaceStringInFile'
            ]
        }
    
    def _initialize_context_mappings(self) -> Dict[str, List[ToolCategory]]:
        """Initialize context to tool category mappings"""
        return {
            'information_gathering': [
                ToolCategory.SEARCH, ToolCategory.MEMORY, ToolCategory.FILE_OPS
            ],
            'planning_phase': [
                ToolCategory.PLANNING, ToolCategory.SEARCH, ToolCategory.MEMORY
            ],
            'implementation': [
                ToolCategory.FILE_OPS, ToolCategory.EXECUTION, ToolCategory.PLANNING
            ],
            'verification': [
                ToolCategory.VERIFICATION, ToolCategory.EXECUTION, ToolCategory.ANALYSIS
            ],
            'debugging': [
                ToolCategory.ANALYSIS, ToolCategory.REFLECTION, ToolCategory.SEARCH
            ],
            'exploration': [
                ToolCategory.SEARCH, ToolCategory.FILE_OPS, ToolCategory.MEMORY
            ],
            'focused_execution': [
                ToolCategory.EXECUTION, ToolCategory.VERIFICATION, ToolCategory.PLANNING
            ],
            'recovery': [
                ToolCategory.REFLECTION, ToolCategory.SEARCH, ToolCategory.MEMORY
            ]
        }
    
    def get_recommended_tools(self, context: str, current_phase: str = None, 
                            exclude_categories: List[ToolCategory] = None) -> List[str]:
        """Get recommended tools for a given context"""
        exclude_categories = exclude_categories or []
        
        # Get relevant categories for the context
        relevant_categories = self.context_tool_mapping.get(context, [])
        
        # Filter out excluded categories
        relevant_categories = [cat for cat in relevant_categories if cat not in exclude_categories]
        
        # Collect tools from relevant categories
        recommended_tools = []
        for category in relevant_categories:
            if category in self.tool_categories:
                recommended_tools.extend(self.tool_categories[category])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_tools = []
        for tool in recommended_tools:
            if tool not in seen:
                seen.add(tool)
                unique_tools.append(tool)
        
        return unique_tools[:8]  # Limit to top 8 recommendations
    
    def get_tool_usage_guidance(self, tool_name: str, context: str) -> str:
        """Get specific usage guidance for a tool in a given context"""
        guidance_map = {
            'SemanticSearchInGuidDoc': {
                'exploration': "Use broad search terms to discover relevant documentation and examples",
                'focused_execution': "Search for specific implementation details or requirements",
                'recovery': "Search for alternative approaches or troubleshooting information"
            },
            'MemoryPut': {
                'planning_phase': "Save planning insights and task breakdown",
                'implementation': "Store intermediate results and important discoveries",
                'verification': "Save test results and verification outcomes"
            },
            'MemoryGet': {
                'exploration': "Retrieve related previous work or context",
                'recovery': "Review previous approaches and their outcomes",
                'focused_execution': "Get specific context needed for current task"
            },
            'CreateToDo': {
                'planning_phase': "Create a detailed plan with specific steps and priorities",
                'recovery': "Create a new plan based on lessons learned",
                'exploration': "Create an exploratory plan for investigating options"
            },
            'CompleteToDoSteps': {
                'implementation': "Mark completed steps and track progress",
                'verification': "Mark verification steps as completed",
                'focused_execution': "Track specific task completion"
            },
            'ResetToDo': {
                'recovery': "Reset and create a fresh approach based on new understanding",
                'planning_phase': "Start over with a completely new planning approach"
            },
            'ReadTextFile': {
                'exploration': "Read documentation and example files to understand context",
                'implementation': "Read source files to understand implementation details",
                'verification': "Read test files and results to understand requirements"
            },
            'Reflect': {
                'recovery': "Analyze what went wrong and identify alternative approaches",
                'verification': "Reflect on whether current approach meets requirements",
                'planning_phase': "Consider different approaches and their trade-offs"
            }
        }
        
        tool_guidance = guidance_map.get(tool_name, {})
        return tool_guidance.get(context, f"Use {tool_name} appropriately for the current task")
    
    def analyze_tool_effectiveness(self, usage_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze tool effectiveness based on usage history"""
        if not usage_history:
            return {'status': 'no_data'}
        
        tool_stats = {}
        context_effectiveness = {}
        
        for usage in usage_history:
            tool_name = usage.get('tool_name')
            context = usage.get('context')
            success = usage.get('success', False)
            
            if tool_name:
                if tool_name not in tool_stats:
                    tool_stats[tool_name] = {'uses': 0, 'successes': 0}
                tool_stats[tool_name]['uses'] += 1
                if success:
                    tool_stats[tool_name]['successes'] += 1
            
            if context:
                if context not in context_effectiveness:
                    context_effectiveness[context] = {'attempts': 0, 'successes': 0}
                context_effectiveness[context]['attempts'] += 1
                if success:
                    context_effectiveness[context]['successes'] += 1
        
        # Calculate effectiveness rates
        tool_effectiveness = {}
        for tool, stats in tool_stats.items():
            if stats['uses'] > 0:
                tool_effectiveness[tool] = stats['successes'] / stats['uses']
        
        context_success_rates = {}
        for context, stats in context_effectiveness.items():
            if stats['attempts'] > 0:
                context_success_rates[context] = stats['successes'] / stats['attempts']
        
        return {
            'tool_effectiveness': tool_effectiveness,
            'context_success_rates': context_success_rates,
            'most_effective_tools': sorted(tool_effectiveness.items(), 
                                         key=lambda x: x[1], reverse=True)[:5],
            'total_usage_sessions': len(usage_history)
        }


class ToolUsageTracker:
    """Tracks tool usage patterns and effectiveness"""
    
    def __init__(self):
        self.usage_history = []
        self.session_tools = set()
        self.current_session_start = time.time()
    
    def record_tool_usage(self, tool_name: str, context: str, success: bool, 
                         duration: float = None, parameters: Dict[str, Any] = None):
        """Record a tool usage event"""
        usage_record = {
            'tool_name': tool_name,
            'context': context,
            'success': success,
            'timestamp': time.time(),
            'duration': duration,
            'parameters': parameters or {},
            'session_id': id(self)  # Simple session identification
        }
        
        self.usage_history.append(usage_record)
        self.session_tools.add(tool_name)
        
        # Keep history manageable
        if len(self.usage_history) > 1000:
            self.usage_history = self.usage_history[-800:]  # Keep recent 800 records
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session tool usage"""
        return {
            'session_duration': time.time() - self.current_session_start,
            'unique_tools_used': len(self.session_tools),
            'total_tool_calls': len([u for u in self.usage_history 
                                   if u['session_id'] == id(self)]),
            'tools_used': list(self.session_tools)
        }
    
    def get_recent_usage_patterns(self, window_size: int = 10) -> Dict[str, Any]:
        """Analyze recent usage patterns"""
        recent_usage = self.usage_history[-window_size:] if self.usage_history else []
        
        if not recent_usage:
            return {'status': 'no_recent_usage'}
        
        tool_frequency = {}
        success_rate = 0
        contexts = set()
        
        for usage in recent_usage:
            tool = usage['tool_name']
            tool_frequency[tool] = tool_frequency.get(tool, 0) + 1
            if usage['success']:
                success_rate += 1
            contexts.add(usage['context'])
        
        return {
            'most_used_tools': sorted(tool_frequency.items(), 
                                    key=lambda x: x[1], reverse=True)[:3],
            'recent_success_rate': success_rate / len(recent_usage),
            'contexts_active': list(contexts),
            'total_recent_calls': len(recent_usage)
        }


class ToolOrchestrator:
    """Main orchestrator for intelligent tool management"""
    
    def __init__(self, agent):
        self.agent = agent
        self.recommendation_engine = ToolRecommendationEngine()
        self.usage_tracker = ToolUsageTracker()
        self.context_history = []
    
    def get_tool_recommendations(self, context: str, max_recommendations: int = 5) -> List[Dict[str, str]]:
        """Get tool recommendations with usage guidance"""
        recommended_tools = self.recommendation_engine.get_recommended_tools(context)
        
        recommendations = []
        for tool in recommended_tools[:max_recommendations]:
            guidance = self.recommendation_engine.get_tool_usage_guidance(tool, context)
            recommendations.append({
                'tool_name': tool,
                'usage_guidance': guidance,
                'category': self._get_tool_category(tool)
            })
        
        return recommendations
    
    def get_strategy_specific_recommendations(self, strategy_type: str) -> str:
        """Get tool recommendations formatted for specific strategies"""
        context_mapping = {
            'exploration': 'exploration',
            'focused': 'focused_execution',
            'systematic': 'planning_phase',
            'recovery': 'recovery'
        }
        
        context = context_mapping.get(strategy_type, 'exploration')
        recommendations = self.get_tool_recommendations(context)
        
        if not recommendations:
            return "- Use available tools as appropriate for the task"
        
        formatted_recommendations = []
        for rec in recommendations:
            formatted_recommendations.append(f"- {rec['tool_name']}: {rec['usage_guidance']}")
        
        return "\n   ".join(formatted_recommendations)
    
    def record_tool_usage_outcome(self, tool_name: str, context: str, success: bool):
        """Record the outcome of tool usage for learning"""
        self.usage_tracker.record_tool_usage(tool_name, context, success)
    
    def get_usage_insights(self) -> Dict[str, Any]:
        """Get insights about tool usage patterns and effectiveness"""
        recent_patterns = self.usage_tracker.get_recent_usage_patterns()
        session_summary = self.usage_tracker.get_session_summary()
        effectiveness_analysis = self.recommendation_engine.analyze_tool_effectiveness(
            self.usage_tracker.usage_history
        )
        
        return {
            'recent_patterns': recent_patterns,
            'session_summary': session_summary,
            'effectiveness_analysis': effectiveness_analysis
        }
    
    def suggest_tool_optimization(self) -> List[str]:
        """Suggest optimizations based on usage patterns"""
        insights = self.get_usage_insights()
        suggestions = []
        
        # Analyze recent success rate
        recent_patterns = insights.get('recent_patterns', {})
        recent_success_rate = recent_patterns.get('recent_success_rate', 1.0)
        
        if recent_success_rate < 0.5:
            suggestions.append("Recent tool usage has low success rate. Consider using Reflect tool to analyze approach.")
        
        # Check for tool diversity
        session_summary = insights.get('session_summary', {})
        unique_tools = session_summary.get('unique_tools_used', 0)
        total_calls = session_summary.get('total_tool_calls', 0)
        
        if total_calls > 10 and unique_tools < 3:
            suggestions.append("Low tool diversity detected. Consider exploring different tool categories.")
        
        # Check for effectiveness patterns
        effectiveness = insights.get('effectiveness_analysis', {})
        if effectiveness.get('status') != 'no_data':
            most_effective = effectiveness.get('most_effective_tools', [])
            if most_effective:
                best_tool = most_effective[0][0]
                suggestions.append(f"Consider using {best_tool} more frequently (highest effectiveness rate).")
        
        return suggestions if suggestions else ["Tool usage patterns appear optimal."]
    
    def _get_tool_category(self, tool_name: str) -> str:
        """Get the category for a given tool"""
        for category, tools in self.recommendation_engine.tool_categories.items():
            if tool_name in tools:
                return category.value
        return "unknown"
    
    def get_orchestrator_status(self) -> Dict[str, Any]:
        """Get comprehensive status of the tool orchestrator"""
        return {
            'total_tracked_usage': len(self.usage_tracker.usage_history),
            'session_summary': self.usage_tracker.get_session_summary(),
            'available_categories': list(self.recommendation_engine.tool_categories.keys()),
            'optimization_suggestions': self.suggest_tool_optimization()
        }
