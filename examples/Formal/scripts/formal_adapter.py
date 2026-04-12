# -*- coding: utf-8 -*-
"""Formal Tool Adapter Interface."""

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class FormalToolAdapter(ABC):
    """Abstract base interface that must be implemented by all formal tool adapters."""

    # ---- Identity ----
    @abstractmethod
    def tool_name(self) -> str:
        """Returns the internal name of the tool (e.g. 'formalmc')."""
        pass

    @abstractmethod
    def tool_display_name(self) -> str:
        """Returns the user-facing display name of the tool."""
        pass

    # ---- Paths ----
    @abstractmethod
    def log_filename(self) -> str:
        """Returns the primary log filename used by this tool."""
        pass

    @abstractmethod
    def coverage_report_path(self, tests_dir: str) -> Optional[str]:
        """
        Returns the absolute path to the coverage report file if the tool 
        generates an independent file (e.g., fanin.rep). Returns None if 
        coverage is embedded within the primary log.
        """
        pass

    # ---- Execution ----
    @abstractmethod
    def build_command(self, tcl_path: str, exec_dir: str) -> List[str]:
        """Constructs the command list to execute the tool."""
        pass

    # ---- Log Parsing ----
    @abstractmethod
    def parse_log(self, log_path: str) -> Dict[str, list]:
        """
        Parses the tool's log to extract property results.
        Returns a dictionary with standard keys:
            - pass: List of passed properties
            - false: List of falsified properties
            - trivially_true: List of trivially true/proven properties
            - cover_pass: List of reachable covers
            - cover_fail: List of unreachable/uncoverable covers
        """
        pass

    @abstractmethod
    def validate_log_has_results(self, log_content: str) -> bool:
        """Validates whether the log content actually contains evaluation results."""
        pass

    @abstractmethod
    def extract_blackbox_count(self, log_content: str) -> int:
        """Extracts the number of blackboxes reported by the synthesis engine in the log."""
        pass

    # ---- Script Validation ----
    @abstractmethod
    def required_script_commands(self) -> List[str]:
        """Returns a list of TCL commands that must be present in the user scripts."""
        pass

    # ---- Coverage Parsing ----
    @abstractmethod
    def parse_coverage(self, tests_dir: str) -> dict:
        """
        Parses the cone-of-influence coverage.
        Returns a dictionary containing:
            - overall_pct (float): Overall coverage percentage (0.0 to 100.0)
            - uncovered (List[str]): List of uncovered signal names
        """
        pass


def get_adapter(tool_name: str = None) -> FormalToolAdapter:
    """Factory function: Returns the adapter instance based on tool name or environment variable."""
    tool = tool_name or os.environ.get("FORMAL_TOOL", "formalmc")
    
    from .adapters import ADAPTER_REGISTRY
    
    adapter_class = ADAPTER_REGISTRY.get(tool.lower())
    if not adapter_class:
        raise ValueError(f"Unsupported formal tool adapter: '{tool}'. "
                         f"Available tools: {list(ADAPTER_REGISTRY.keys())}")
    
    return adapter_class()
