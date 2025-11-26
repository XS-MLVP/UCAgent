# -*- coding: utf-8 -*-
"""Bash script checkers for UCAgent."""


from ucagent.checkers.base import Checker
from typing import Tuple
import re
import fnmatch


class BashScriptChecker(Checker):
    """Checker for bash scripts."""

    def __init__(self, cmd:str, arguments: list[str]=[], pass_pattern: dict = {}, fail_pattern: dict = {}, need_human_check: bool = False, timeout: int = 0, **kw):
        self.cmd = [cmd] + arguments
        self.arguments = arguments
        self.pass_pattern = pass_pattern # e.g., {"All tests passed": "success_message1", "Passed": "success_message2", ...}
        self.fail_pattern = fail_pattern # e.g., {"Error": "error_message1", "Failed": "error_message2", ...}
        self.set_human_check_needed(need_human_check)
        self.timeout = timeout

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        """Check bash cmd and script output against patterns."""
        import subprocess
        try:
            _timeout = timeout if timeout > 0 else self.timeout
            completed_process = subprocess.run(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_timeout if _timeout > 0 else None,
                text=True
            )
            output = completed_process.stdout + completed_process.stderr
            for pattern, message in self.fail_pattern.items():
                if self.pattern_search(pattern, output):
                    return False, {"message": message,
                                   "STDOUT": completed_process.stdout,
                                   "STDERR": completed_process.stderr}

            for pattern, message in self.pass_pattern.items():
                if self.pattern_search(pattern, output):
                    return True, {"message": message}

            if completed_process.returncode == 0:
                return True, "Command executed successfully."
            else:
                return False, {"message": f"Command failed without matching patterns and exit with non-zero status ({completed_process.returncode}).",
                               "STDOUT": completed_process.stdout,
                               "STDERR": completed_process.stderr}

        except subprocess.TimeoutExpired:
            return False, f"Command: {' '.join(self.cmd)} timed out."
        except Exception as e:
            return False, f"An error occurred: {str(e)} when executing command: {' '.join(self.cmd)}"

    def pattern_search(self, pattern: str, target: str) -> bool:
        """Search for a pattern in the target string.
        
        Priority:
        1. Normal string (exact substring match)
        2. Global pattern (wildcard with * or ?)
        3. Regex pattern (any pattern with special regex chars)
        """
        # Check normal string first
        if self.is_normal_str(pattern):
            return pattern in target
        # Then check global pattern
        elif self.is_global_str(pattern):
            return fnmatch.fnmatch(target, pattern)
        # Finally try as regex
        else:
            try:
                return re.search(pattern, target) is not None
            except re.error:
                # If regex is invalid, fall back to substring match
                return pattern in target

    def is_normal_str(self, pattern: str) -> bool:
        """Check if the pattern is a normal string (no special characters)."""
        special_chars = ['*', '?', '[', ']', '(', ')', '{', '}', '.', '+', '^', '$', '|', '\\']
        return not any(char in pattern for char in special_chars)

    def is_global_str(self, pattern: str) -> bool:
        """Check if the pattern is a global/wildcard string.
        
        Only consider it a wildcard pattern if it has * or ? but doesn't have
        other regex special characters (to avoid treating regex as wildcard).
        """
        has_wildcard = '*' in pattern or '?' in pattern
        if not has_wildcard:
            return False
        # If it has regex-specific chars, it's likely a regex, not a simple wildcard
        regex_specific_chars = ['[', ']', '(', ')', '{', '}', '+', '^', '$', '|', '\\']
        has_regex_chars = any(char in pattern for char in regex_specific_chars)
        return has_wildcard and not has_regex_chars
