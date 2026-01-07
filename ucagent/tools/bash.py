# -*- coding: utf-8 -*-
"""Bash operations tools for UCAgent."""

from typing import Optional, Dict
from ucagent.util.log import info, str_return, str_error
from .uctool import UCTool

from langchain_core.callbacks import (
    CallbackManagerForToolRun,
)
from pydantic import BaseModel, Field

import os
import subprocess


class RunBashCommandInput(BaseModel):
    command: str = Field(description="The bash command to run.")
    timeout: Optional[int] = Field(default=60, description="The timeout in seconds.")
    env_vars: Optional[Dict[str, str]] = Field(default=None, description="Additional environment variables.")


class RunBashCommand(UCTool):
    """Tool to run bash commands in the workspace."""
    name: str = "RunBashCommand"
    description: str = (
        "Run a bash command in the terminal. "
        "Useful for running shell commands, makefiles, or other CLI tools. "
        "Supports timeouts and environment variables."
        "Note: Dangerous commands like 'rm', 'dd', 'mkfs', 'shutdown', '> /dev/sd' are prohibited."
    )
    args_schema: type[BaseModel] = RunBashCommandInput
    workspace: str = Field(default=".", description="Workspace root directory.")

    def _run(self, 
             command: str, 
             timeout: int = 60, 
             env_vars: dict = None, 
             run_manager: CallbackManagerForToolRun = None) -> str:
        """Run the bash command and return the output."""
        
        # Security check: dangerous commands
        dangerous_patterns = [
            "rm ", "rm\t", "rm\n",  # remove
            "dd ", "dd\t", "dd\n",  # disk destroyer
            "mkfs",                 # format filesystem
            "> /dev/sd", ">/dev/sd",# raw device write
            "shutdown", "reboot",   # system state
            ":(){ :|:& };:",       # fork bomb
            "mv /"                  # move root
            "sudo ", "sudo\t", "sudo\n",     # elevated privileges
            "chmod ", "chmod\t", "chmod\n",  # change permissions
            "chown ", "chown\t", "chown\n",  # change ownership
        ]
        
        cmd_check = command.strip()
        for pattern in dangerous_patterns:
            if pattern in cmd_check:
                # Check strict start or surrounding spaces/separators could be more complex, 
                # but simple substring check is a safe baseline for 'rm ' etc.
                # However, 'rm' might be part of 'firmware', so we look for word boundaries loosely if needed.
                # For safety, explicit commands usually have spaces or are at start.
                
                # Simple heuristic: if the pattern appears as a distinct token
                # This prevents blocking "farm" when checking for "rm"
                is_danger = False
                
                # Check if it starts with the command
                if cmd_check.startswith(pattern.strip() + " ") or cmd_check == pattern.strip():
                    is_danger = True
                # Check for " command " or ";command" or "|command"
                elif f" {pattern.strip()} " in cmd_check:
                    is_danger = True
                elif f";{pattern.strip()}" in cmd_check or f"|{pattern.strip()}" in cmd_check:
                    is_danger = True
                    
                # Special cases for redirections which are patterns themselves
                if pattern in ["> /dev/sd", ">/dev/sd", ":(){ :|:& };:"]:
                    if pattern in cmd_check:
                         is_danger = True

                if is_danger:
                     return str_error(f"Command contains prohibited dangerous operation: '{pattern.strip()}'")

        # Resolve working directory
        abs_workspace = os.path.abspath(self.workspace)
        work_dir = abs_workspace

        if not os.path.exists(work_dir):
            return str_error(f"Working directory '{work_dir}' does not exist.")

        # Prepare environment
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        info(f"Run Bash: {command} (in {work_dir})")

        try:
            # Execute command
            # shell=True allows using pipes and other shell features
            process = subprocess.run(
                command,
                cwd=work_dir,
                timeout=timeout,
                capture_output=True,
                text=True,
                shell=True,
                executable="/bin/bash",
                env=env
            )
            
            stdout = process.stdout
            stderr = process.stderr
            return_code = process.returncode

            # Format output
            output_parts = []
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                output_parts.append(f"STDERR:\n{stderr}")
            
            full_output = "\n".join(output_parts)
            
            if return_code == 0:
                msg = "Command executed successfully."
                if full_output:
                    msg += f"\n{full_output}"
                return str_return(msg)
            else:
                msg = f"Command failed with return code {return_code}."
                if full_output:
                    msg += f"\n{full_output}"
                return str_error(msg)

        except subprocess.TimeoutExpired:
            return str_error(f"Command timed out after {timeout} seconds.")
        except Exception as e:
            return str_error(f"Execution failed: {str(e)}")
    
    def __init__(self, workspace: str):
        super().__init__()
        self.workspace = os.path.abspath(workspace)
