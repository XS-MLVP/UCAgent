# -*- coding: utf-8 -*-
"""
Advanced interaction logic for the verify agent.
This module provides adaptive interaction strategies with context analysis and performance tracking.
"""

import copy
import time
import statistics
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from ucagent.util.log import info, warning, error
from ucagent.util.functions import yam_str


class ContextComplexity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AdaptiveStrategy(Enum):
    EXPLORATORY = "exploratory"
    FOCUSED = "focused"
    SYSTEMATIC = "systematic"
    RECOVERY = "recovery"


class ContextAnalyzer:
    """Analyzes interaction context to determine complexity and requirements"""
    
    def __init__(self):
        self.analysis_cache = {}
        self.context_keywords = {
            'complexity_indicators': {
                'high': ['complex', 'intricate', 'sophisticated', 'advanced', 'multiple dependencies'],
                'medium': ['moderate', 'standard', 'typical', 'several steps'],
                'low': ['simple', 'basic', 'straightforward', 'single step']
            },
            'domain_indicators': {
                'verification': ['verify', 'test', 'check', 'validation', 'coverage'],
                'design': ['design', 'architecture', 'implement', 'create'],
                'debugging': ['debug', 'fix', 'error', 'issue', 'problem'],
                'analysis': ['analyze', 'examine', 'investigate', 'research']
            }
        }
    
    def analyze_context(self, current_tips: str, message_history: List[str]) -> Dict[str, Any]:
        """Analyze current context and return complexity assessment"""
        context_key = hash(current_tips + str(len(message_history)))
        
        if context_key in self.analysis_cache:
            return self.analysis_cache[context_key]
        
        analysis = {
            'complexity': self._assess_complexity(current_tips, message_history),
            'domain': self._identify_domain(current_tips),
            'progress_indicators': self._analyze_progress(message_history),
            'uncertainty_level': self._assess_uncertainty(current_tips, message_history),
            'tool_usage_patterns': self._analyze_tool_usage(message_history)
        }
        
        self.analysis_cache[context_key] = analysis
        return analysis
    
    def _assess_complexity(self, tips: str, history: List[str]) -> ContextComplexity:
        """Assess the complexity of the current context"""
        complexity_score = 0
        text_to_analyze = tips + " " + " ".join(history[-3:])  # Recent history
        
        # Check complexity indicators
        for level, keywords in self.context_keywords['complexity_indicators'].items():
            for keyword in keywords:
                if keyword.lower() in text_to_analyze.lower():
                    if level == 'high':
                        complexity_score += 3
                    elif level == 'medium':
                        complexity_score += 2
                    else:
                        complexity_score += 1
        
        # Consider message history length as complexity indicator
        if len(history) > 10:
            complexity_score += 2
        elif len(history) > 5:
            complexity_score += 1
        
        # Map score to complexity level
        if complexity_score >= 8:
            return ContextComplexity.CRITICAL
        elif complexity_score >= 5:
            return ContextComplexity.HIGH
        elif complexity_score >= 2:
            return ContextComplexity.MEDIUM
        else:
            return ContextComplexity.LOW
    
    def _identify_domain(self, tips: str) -> str:
        """Identify the primary domain of the current task"""
        domain_scores = {}
        
        for domain, keywords in self.context_keywords['domain_indicators'].items():
            score = sum(1 for keyword in keywords if keyword in tips.lower())
            domain_scores[domain] = score
        
        return max(domain_scores, key=domain_scores.get) if domain_scores else 'general'
    
    def _analyze_progress(self, history: List[str]) -> Dict[str, Any]:
        """Analyze progress indicators from message history"""
        if not history:
            return {'trend': 'starting', 'stagnation_risk': 0}
        
        # Simple heuristics for progress analysis
        recent_messages = history[-5:]
        
        # Check for repetitive patterns
        unique_recent = len(set(recent_messages))
        stagnation_risk = max(0, (len(recent_messages) - unique_recent) / len(recent_messages))
        
        # Determine trend
        if stagnation_risk > 0.6:
            trend = 'stagnating'
        elif len(history) > len(set(history)) * 1.5:
            trend = 'struggling'
        else:
            trend = 'progressing'
        
        return {
            'trend': trend,
            'stagnation_risk': stagnation_risk,
            'message_diversity': unique_recent / len(recent_messages) if recent_messages else 1.0
        }
    
    def _assess_uncertainty(self, tips: str, history: List[str]) -> float:
        """Assess the level of uncertainty in the current context"""
        uncertainty_indicators = [
            'unclear', 'uncertain', 'not sure', 'maybe', 'possibly', 
            'might', 'could be', 'unclear', 'ambiguous'
        ]
        
        text_to_analyze = tips + " " + " ".join(history[-3:])
        uncertainty_count = sum(1 for indicator in uncertainty_indicators 
                              if indicator in text_to_analyze.lower())
        
        return min(1.0, uncertainty_count / 5)  # Normalize to 0-1
    
    def _analyze_tool_usage(self, history: List[str]) -> Dict[str, int]:
        """Analyze tool usage patterns from history"""
        # This would need to be enhanced to actually parse tool usage from history
        # For now, return a placeholder
        return {
            'tool_calls': len([msg for msg in history if 'tool' in msg.lower()]),
            'unique_tools': 0,  # Would need actual parsing
            'tool_success_rate': 0.8  # Would need actual tracking
        }


class PerformanceTracker:
    """Tracks interaction performance and provides optimization suggestions"""
    
    def __init__(self):
        self.metrics = {
            'round_times': [],
            'strategy_performance': {},
            'complexity_handling': {},
            'tool_effectiveness': {},
            'success_rates': []
        }
        self.current_session_start = time.time()
    
    def record_round_performance(self, strategy: AdaptiveStrategy, complexity: ContextComplexity, 
                               duration: float, success: bool):
        """Record performance metrics for a round"""
        self.metrics['round_times'].append(duration)
        
        # Track strategy performance
        strategy_key = strategy.value
        if strategy_key not in self.metrics['strategy_performance']:
            self.metrics['strategy_performance'][strategy_key] = {
                'total_rounds': 0, 'successful_rounds': 0, 'avg_duration': 0
            }
        
        strategy_stats = self.metrics['strategy_performance'][strategy_key]
        strategy_stats['total_rounds'] += 1
        if success:
            strategy_stats['successful_rounds'] += 1
        
        # Update average duration
        current_avg = strategy_stats['avg_duration']
        total_rounds = strategy_stats['total_rounds']
        strategy_stats['avg_duration'] = ((current_avg * (total_rounds - 1)) + duration) / total_rounds
        
        # Track complexity handling
        complexity_key = complexity.value
        if complexity_key not in self.metrics['complexity_handling']:
            self.metrics['complexity_handling'][complexity_key] = {
                'attempts': 0, 'successes': 0
            }
        
        self.metrics['complexity_handling'][complexity_key]['attempts'] += 1
        if success:
            self.metrics['complexity_handling'][complexity_key]['successes'] += 1
        
        # Track overall success rate
        self.metrics['success_rates'].append(1.0 if success else 0.0)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get current performance summary"""
        if not self.metrics['round_times']:
            return {'status': 'no_data'}
        
        return {
            'total_rounds': len(self.metrics['round_times']),
            'average_round_time': statistics.mean(self.metrics['round_times']),
            'recent_success_rate': self._calculate_recent_success_rate(),
            'best_strategy': self._identify_best_strategy(),
            'session_duration': time.time() - self.current_session_start,
            'complexity_success_rates': self._get_complexity_success_rates()
        }
    
    def _calculate_recent_success_rate(self, window: int = 5) -> float:
        """Calculate success rate for recent rounds"""
        if not self.metrics['success_rates']:
            return 0.0
        
        recent_rates = self.metrics['success_rates'][-window:]
        return statistics.mean(recent_rates) if recent_rates else 0.0
    
    def _identify_best_strategy(self) -> str:
        """Identify the best performing strategy"""
        if not self.metrics['strategy_performance']:
            return 'no_data'
        
        best_strategy = None
        best_score = 0
        
        for strategy, stats in self.metrics['strategy_performance'].items():
            if stats['total_rounds'] > 0:
                success_rate = stats['successful_rounds'] / stats['total_rounds']
                # Weight by both success rate and efficiency (inverse of duration)
                efficiency = 1 / max(stats['avg_duration'], 0.1)
                score = success_rate * efficiency
                
                if score > best_score:
                    best_score = score
                    best_strategy = strategy
        
        return best_strategy or 'unknown'
    
    def _get_complexity_success_rates(self) -> Dict[str, float]:
        """Get success rates by complexity level"""
        rates = {}
        for complexity, stats in self.metrics['complexity_handling'].items():
            if stats['attempts'] > 0:
                rates[complexity] = stats['successes'] / stats['attempts']
            else:
                rates[complexity] = 0.0
        return rates
    
    def suggest_strategy_adjustment(self, current_strategy: AdaptiveStrategy, 
                                 context_analysis: Dict[str, Any]) -> Optional[AdaptiveStrategy]:
        """Suggest strategy adjustment based on performance"""
        performance = self.get_performance_summary()
        
        if performance.get('status') == 'no_data':
            return None
        
        recent_success_rate = performance['recent_success_rate']
        complexity = context_analysis['complexity']
        
        # If recent performance is poor, suggest strategy change
        if recent_success_rate < 0.3:
            if complexity == ContextComplexity.HIGH:
                return AdaptiveStrategy.SYSTEMATIC
            elif context_analysis['progress_indicators']['trend'] == 'stagnating':
                return AdaptiveStrategy.EXPLORATORY
            else:
                return AdaptiveStrategy.RECOVERY
        
        # If performance is good, maintain or optimize current strategy
        if recent_success_rate > 0.8:
            if current_strategy == AdaptiveStrategy.EXPLORATORY and complexity == ContextComplexity.LOW:
                return AdaptiveStrategy.FOCUSED
        
        return None  # No change suggested


class AdvancedInteractionState:
    """Advanced state management for adaptive interactions"""
    
    def __init__(self):
        self.current_strategy = AdaptiveStrategy.SYSTEMATIC
        self.context_analyzer = ContextAnalyzer()
        self.performance_tracker = PerformanceTracker()
        self.strategy_history = []
        self.round_start_time = None
        self.adaptation_threshold = 3  # Rounds before considering adaptation
        
    def begin_round(self):
        """Mark the beginning of a new round"""
        self.round_start_time = time.time()
    
    def end_round(self, success: bool, context_analysis: Dict[str, Any]):
        """Mark the end of a round and record performance"""
        if self.round_start_time:
            duration = time.time() - self.round_start_time
            self.performance_tracker.record_round_performance(
                self.current_strategy, 
                context_analysis['complexity'], 
                duration, 
                success
            )
            self.round_start_time = None
    
    def adapt_strategy(self, context_analysis: Dict[str, Any]) -> bool:
        """Adapt strategy based on context and performance"""
        # Only consider adaptation after minimum rounds
        if len(self.strategy_history) < self.adaptation_threshold:
            return False
        
        suggested_strategy = self.performance_tracker.suggest_strategy_adjustment(
            self.current_strategy, context_analysis
        )
        
        if suggested_strategy and suggested_strategy != self.current_strategy:
            info(f"Adapting strategy from {self.current_strategy.value} to {suggested_strategy.value}")
            self.strategy_history.append({
                'from': self.current_strategy,
                'to': suggested_strategy,
                'reason': 'performance_optimization',
                'timestamp': time.time()
            })
            self.current_strategy = suggested_strategy
            return True
        
        return False
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get comprehensive state summary"""
        return {
            'current_strategy': self.current_strategy.value,
            'strategy_changes': len(self.strategy_history),
            'performance_summary': self.performance_tracker.get_performance_summary(),
            'recent_adaptations': self.strategy_history[-3:] if self.strategy_history else []
        }


class AdvancedInteractionLogic:
    """Advanced interaction logic with adaptive strategies and performance tracking"""
    
    def __init__(self, agent):
        self.agent = agent
        self.state = AdvancedInteractionState()
        self.planning_tools = None
        self.tool_orchestrator = None
        self._init_components()
    
    def _init_components(self):
        """Initialize planning tools and tool orchestrator"""
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
        
        try:
            from .orchestrator import ToolOrchestrator
            self.tool_orchestrator = ToolOrchestrator(self.agent)
        except Exception as e:
            warning(f"Failed to initialize tool orchestrator: {e}")
            self.tool_orchestrator = None
    
    def advanced_one_loop(self, msg: str = None) -> Any:
        """Advanced one_loop with adaptive strategies and performance tracking"""
        self.state.begin_round()
        
        if msg:
            self.agent.set_continue_msg(msg)
        
        try:
            # Analyze current context
            current_tips = self.agent.stage_manager.get_current_tips()
            message_history = self._get_recent_message_history()
            context_analysis = self.state.context_analyzer.analyze_context(current_tips, message_history)
            
            # Adapt strategy if needed
            strategy_adapted = self.state.adapt_strategy(context_analysis)
            
            # Select and execute interaction approach
            success = self._execute_adaptive_strategy(context_analysis, strategy_adapted)
            
            # Record performance
            self.state.end_round(success, context_analysis)
            
            self.agent.invoke_round += 1
            return self.agent
            
        except Exception as e:
            error(f"Error in advanced interaction logic: {e}")
            # Fallback to standard execution
            self.agent.one_loop()
            self.state.end_round(False, {'complexity': ContextComplexity.LOW})
            return self.agent
    
    def _execute_adaptive_strategy(self, context_analysis: Dict[str, Any], strategy_adapted: bool) -> bool:
        """Execute the appropriate strategy based on context analysis"""
        strategy = self.state.current_strategy
        complexity = context_analysis['complexity']
        
        info(f"Executing {strategy.value} strategy for {complexity.value} complexity task")
        
        try:
            if strategy == AdaptiveStrategy.EXPLORATORY:
                return self._execute_exploratory_strategy(context_analysis)
            elif strategy == AdaptiveStrategy.FOCUSED:
                return self._execute_focused_strategy(context_analysis)
            elif strategy == AdaptiveStrategy.SYSTEMATIC:
                return self._execute_systematic_strategy(context_analysis)
            elif strategy == AdaptiveStrategy.RECOVERY:
                return self._execute_recovery_strategy(context_analysis)
            else:
                # Fallback
                self.agent.one_loop()
                return True
        except Exception as e:
            error(f"Error executing {strategy.value} strategy: {e}")
            return False
    
    def _execute_exploratory_strategy(self, context_analysis: Dict[str, Any]) -> bool:
        """Execute exploratory strategy for discovery and broad investigation"""
        message = f"""
EXPLORATORY STRATEGY - Broad Investigation and Discovery

Context: {context_analysis['domain']} task with {context_analysis['complexity'].value} complexity

Exploration Approach:
1. DISCOVERY PHASE:
   - Use SemanticSearchInGuidDoc with broad search terms to discover relevant information
   - Explore multiple angles and approaches to understand the problem space
   - Use MemoryGet to check for any related previous work or insights

2. INFORMATION GATHERING:
   - Read relevant documentation and examples
   - Investigate multiple potential solutions or approaches
   - Document interesting findings for later reference

3. TOOL EXPLORATION:
   {self._get_tool_recommendations('exploration')}

4. CONTEXT BUILDING:
   - Use MemoryPut to save interesting discoveries
   - Build a comprehensive understanding before committing to specific approaches

Focus on breadth over depth initially. Discover options before making decisions.
"""
        self._execute_with_message(message)
        return True
    
    def _execute_focused_strategy(self, context_analysis: Dict[str, Any]) -> bool:
        """Execute focused strategy for targeted task completion"""
        message = f"""
FOCUSED STRATEGY - Targeted Task Completion

Context: {context_analysis['domain']} task with {context_analysis['complexity'].value} complexity

Focused Approach:
1. TARGET IDENTIFICATION:
   - Clearly identify the specific goal and success criteria
   - Use GetPlan to check current plan and focus on the next specific step

2. DIRECT EXECUTION:
   - Execute the most direct path to task completion
   - Minimize exploratory activities and focus on implementation
   - Use tools specifically for the current objective

3. EFFICIENT TOOL USAGE:
   {self._get_tool_recommendations('focused')}

4. PROGRESS TRACKING:
   - Use CompleteToDoSteps to mark specific progress when steps are done
   - Save only essential results to memory

Execute the next planned step directly and efficiently.
"""
        self._execute_with_message(message)
        return True
    
    def _execute_systematic_strategy(self, context_analysis: Dict[str, Any]) -> bool:
        """Execute systematic strategy for complex, structured tasks"""
        message = f"""
SYSTEMATIC STRATEGY - Structured Problem Solving

Context: {context_analysis['domain']} task with {context_analysis['complexity'].value} complexity

Systematic Approach:
1. STRUCTURED ANALYSIS:
   - Break down the current task into logical phases
   - Use CreateToDo to ensure structured approach with defined steps
   - Map dependencies and requirements systematically

2. METHODICAL EXECUTION:
   - Execute one phase completely before moving to the next
   - Verify each step before proceeding
   - Document intermediate results thoroughly

3. COMPREHENSIVE TOOL USAGE:
   {self._get_tool_recommendations('systematic')}

4. VALIDATION AND VERIFICATION:
   - Check each phase for completeness and correctness
   - Use memory to track systematic progress
   - Maintain detailed documentation of the systematic approach

Follow the structured plan methodically, ensuring each phase is complete and verified.
"""
        self._execute_with_message(message)
        return True
    
    def _execute_recovery_strategy(self, context_analysis: Dict[str, Any]) -> bool:
        """Execute recovery strategy when facing difficulties or stagnation"""
        message = f"""
RECOVERY STRATEGY - Problem Resolution and Course Correction

Context: {context_analysis['domain']} task with detected difficulties

Recovery Approach:
1. PROBLEM DIAGNOSIS:
   - Analyze what has been attempted and why it may not be working
   - Use MemoryGet to review previous approaches and results
   - Identify specific obstacles or misunderstandings

2. ALTERNATIVE APPROACHES:
   - Search for different methods or examples using SemanticSearchInGuidDoc
   - Consider completely different approaches to the problem
   - Look for simpler or more direct solutions

3. RESET AND RESTART:
   - Use ResetToDo to create a fresh approach based on new understanding
   - If available, use the Reflect tool for structured problem analysis
   - Consider stepping back to a higher level view

4. TARGETED TOOL USAGE:
   {self._get_tool_recommendations('recovery')}

5. INCREMENTAL PROGRESS:
   - Focus on small, achievable steps to rebuild momentum
   - Verify each small step works before proceeding
   - Document what works and what doesn't

Start by diagnosing the current obstacles and identifying alternative approaches.
"""
        self._execute_with_message(message)
        return True
    
    def _get_tool_recommendations(self, strategy_type: str) -> str:
        """Get tool recommendations based on strategy type"""
        if self.tool_orchestrator:
            try:
                return self.tool_orchestrator.get_strategy_specific_recommendations(strategy_type)
            except Exception as e:
                warning(f"Failed to get tool recommendations: {e}")
        
        # Fallback recommendations
        recommendations = {
            'exploration': "- Use SemanticSearchInGuidDoc with broad terms\n   - Try ReadTextFile for documentation review\n   - Use MemoryGet to check related work",
            'focused': "- Use specific tools for the current task\n   - Minimize tool switching\n   - Use CompleteToDoSteps for progress tracking",
            'systematic': "- Use CreateToDo for structured planning\n   - Use comprehensive tool set as needed\n   - Use MemoryPut for detailed documentation",
            'recovery': "- Use Reflect tool if available\n   - Use SemanticSearchInGuidDoc for alternatives\n   - Use MemoryGet to review previous work"
        }
        
        return recommendations.get(strategy_type, "- Use available tools as appropriate for the task")
    
    def _get_recent_message_history(self) -> List[str]:
        """Get recent message history for context analysis"""
        try:
            # This would need to be implemented based on how the agent stores message history
            # For now, return a placeholder
            return []
        except Exception:
            return []
    
    def _execute_with_message(self, message: str):
        """Execute the agent with a specific message"""
        self.agent.set_continue_msg(message)
        
        while True:
            tips = self.agent.get_current_tips()
            if self.agent.is_exit():
                return
            self.agent.do_work(tips, self.agent.get_work_config())
            if not self.agent._tool__call_error:
                break
            if self.agent.is_break():
                return
    
    def get_advanced_status(self) -> Dict[str, Any]:
        """Get comprehensive status of advanced interaction logic"""
        return {
            'interaction_state': self.state.get_state_summary(),
            'current_round': self.agent.invoke_round,
            'components_available': {
                'planning_tools': self.planning_tools is not None,
                'tool_orchestrator': self.tool_orchestrator is not None
            }
        }
