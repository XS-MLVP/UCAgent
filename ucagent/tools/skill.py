# -*- coding: utf-8 -*-
"""Skills management tools for UCAgent.
This module provides tools to list and manage available skills in the workspace.
"""

import re
import os
import shutil
from pathlib import Path
from typing import Optional, TypedDict, Any, List
import yaml
from pydantic import Field, BaseModel

import subprocess
from .uctool import UCTool, ArgsSchema, EmptyArgs
from ucagent.util.log import warning,info
from ucagent.util.functions import get_abs_path_cwd_ucagent

# Security: Maximum size for SKILL.md files to prevent DoS attacks (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024


# Agent Skills specification constraints (https://agentskills.io/specification)
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024

class SkillMetadata(TypedDict):
    """Metadata for a skill."""
    name: str  # Skill identifier (max 64 chars, lowercase alphanumeric and hyphens)
    description: str  # What the skill does (max 1024 chars)
    path: str  # Path to the SKILL.md file
    metadata: dict[str, str] # Additional metadata from SKILL.md frontmatter
    script: dict # Path to the skill script


def _validate_skill_name(name: str, directory_name: str) -> tuple[bool, str]:
    """Validate skill name per Agent Skills specification.
    Requirements per spec:
    - Max 64 characters
    - Lowercase alphanumeric and hyphens only (a-z, 0-9, -)
    - Cannot start or end with hyphen
    - No consecutive hyphens
    - Must match parent directory name
    Args:
        name: Skill name from YAML frontmatter
        directory_name: Parent directory name
    Returns:
        (is_valid, error_message) tuple. Error message is empty if valid.
    """
    if not name:
        return False, "name is required"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return False, "name exceeds 64 characters"
    # Pattern: lowercase alphanumeric, single hyphens between segments, no start/end hyphen
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        return False, "name must be lowercase alphanumeric with single hyphens only"
    if name != directory_name:
        return False, f"name '{name}' must match directory name '{directory_name}'"
    return True, ""

def _validate_metadata(
    raw: object,
    skill_path: str,
) -> dict[str, str]:
    """Validate and normalize the metadata field from YAML frontmatter.

    YAML `safe_load` can return any type for the `metadata` key. This
    ensures the values in `SkillMetadata` are always a `dict[str, str]` by
    coercing via `str()` and rejecting non-dict inputs.

    Args:
        raw: Raw value from `frontmatter_data.get("metadata", {})`.
        skill_path: Path to the `SKILL.md` file (for warning messages).

    Returns:
        A validated `dict[str, str]`.
    """
    if not isinstance(raw, dict):
        if raw:
            warning(
                f"Ignoring non-dict metadata in {skill_path} (got {type(raw).__name__})",
            )
        return {}
    return {str(k): str(v) for k, v in raw.items()}

def _parse_skill_metadata(
    content: str,
    skill_path: str,
    directory_name: str,
# ) -> SkillMetadata | None:
) -> Optional[SkillMetadata]:
    """Parse YAML frontmatter from SKILL.md content.
    Extracts metadata per Agent Skills specification from YAML frontmatter delimited
    by --- markers at the start of the content.
    Args:
        content: Content of the SKILL.md file
        skill_path: Path to the SKILL.md file (for error messages and metadata)
        directory_name: Name of the parent directory containing the skill
    Returns:
        SkillMetadata if parsing succeeds, None if parsing fails or validation errors occur
    """
    if len(content) > MAX_SKILL_FILE_SIZE:
        warning(f"Skipping {skill_path}: content too large ({len(content)} bytes)")
        return None

    # Match YAML frontmatter between --- delimiters
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        warning(f"Skipping {skill_path}: no valid YAML frontmatter found")
        return None

    frontmatter_str = match.group(1)

    # Parse YAML using safe_load for proper nested structure support
    try:
        frontmatter_data = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        warning(f"Invalid YAML in {skill_path}: {e}")
        return None

    if not isinstance(frontmatter_data, dict):
        warning(f"Skipping {skill_path}: frontmatter is not a mapping")
        return None

    # Validate required fields
    name = frontmatter_data.get("name")
    description = frontmatter_data.get("description")

    if not name or not description:
        warning(f"Skipping {skill_path}: missing required 'name' or 'description'")
        return None

    # Validate name format per spec (warn but continue loading for backwards compatibility)
    is_valid, error = _validate_skill_name(str(name), directory_name)
    if not is_valid:
        warning(
            f"Skill '{name}' in {skill_path} does not follow Agent Skills specification: {error}. Consider renaming for spec compliance."
        )

    # Validate description length per spec (max 1024 chars)
    description_str = str(description).strip()
    if len(description_str) > MAX_SKILL_DESCRIPTION_LENGTH:
        warning(
            f"Description exceeds {MAX_SKILL_DESCRIPTION_LENGTH} characters in {skill_path}, truncating"
        )
        description_str = description_str[:MAX_SKILL_DESCRIPTION_LENGTH]

    return SkillMetadata(
        name=str(name),
        description=description_str,
        path=skill_path,
        metadata=_validate_metadata(frontmatter_data.get("metadata", {}), skill_path),
    )


def _list_skills(source_path: str, workspace: str = None) -> list[SkillMetadata]:
    """List all skills from a directory.
    Scans directory for subdirectories containing SKILL.md files, reads their content,
    parses YAML frontmatter, and returns skill metadata.
    Expected structure:
        source_path/
        ├── skill-1-name/
        │   ├── SKILL.md        # Required
        │   └── helper.py       # Optional
        ├── skill-2-name/
        │   ├── SKILL.md        # Required
    Args:
        source_path: Path to the skills directory
        workspace: Path to workspace directory. If provided, skills will be copied to workspace/skills/
    Returns:
        List of skill metadata from successfully parsed SKILL.md files
    """
    skills: list[SkillMetadata] = []

    # Convert to Path object for easier manipulation
    base_path = Path(source_path)

    # Check if source path exists
    if not base_path.exists():
        warning(f"Skills source path does not exist: {source_path}")
        return []

    if not base_path.is_dir():
        warning(f"Skills source path is not a directory: {source_path}")
        return []

    # Iterate through all subdirectories
    try:
        for skill_dir in base_path.iterdir():
            if not skill_dir.is_dir():
                continue

            # Check if SKILL.md exists in this directory
            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue

            # Copy skill directory to workspace if workspace is provided
            if workspace:
                try:
                    workspace_skills_dir = Path(workspace) / "skills"
                    workspace_skills_dir.mkdir(parents=True, exist_ok=True)
                    dest_skill_dir = workspace_skills_dir / skill_dir.name

                    # Copy the entire skill directory to workspace
                    if dest_skill_dir.exists():
                        shutil.rmtree(dest_skill_dir)
                    shutil.copytree(skill_dir, dest_skill_dir)
                except Exception as e:
                    warning(f"Failed to copy skill directory {skill_dir} to workspace: {e}")

            # Read SKILL.md content
            try:
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError as e:
                warning(f"Error decoding {skill_md_path}: {e}")
                continue
            except IOError as e:
                warning(f"Error reading {skill_md_path}: {e}")
                continue

            # Parse metadata
            skill_metadata = _parse_skill_metadata(
                content=content,
                skill_path=str(skill_md_path),
                directory_name=skill_dir.name
            )
            if skill_metadata:
                skill_metadata['script'] = {}
                script_dir = skill_dir / "scripts"
                if script_dir.exists() and script_dir.is_dir():
                    for f in script_dir.iterdir():
                        if f.is_file() and f.name != '__init__.py' and f.name != 'hooks.py':
                            skill_metadata['script'][f.name] = str(f)
                skills.append(skill_metadata)

    except PermissionError as e:
        warning(f"Permission denied accessing {source_path}: {e}")
    except Exception as e:
        warning(f"Error scanning skills directory {source_path}: {e}")

    return skills

def list_skills_in_format(skills: list[SkillMetadata], workspace: str = '.', able_to_list: list = []) -> str:
    """Format a list of skills into a readable string.
    Args:
        skills: List of SkillMetadata to format
        workspace: Path to the workspace directory
        able_to_list: List of skill names that are able to be listed
    Returns:
        A formatted string listing each skill's name, description, and path
    """
    result_lines = []
    count=1
    for skill in skills:
        if (not able_to_list) or skill['name'] in able_to_list:
            result_lines.append(f"{count}. Skill Name: {skill['name']}")
            result_lines.append(f"   Skill Description: {skill['description']}")
            result_lines.append(f"   Skill Path: {Path(skill['path']).relative_to(Path(workspace))}")
            if skill.get('script'):
                result_lines.append("   Script Path:")
                for fname, fpath in skill['script'].items():
                    result_lines.append(f"     - {fname}: {Path(fpath).relative_to(Path(workspace))}")
            count+=1
    return "\n".join(result_lines)

class ListSkill(UCTool):
    name: str = "ListSkill"
    description: str = (
        "List the specified skills you can use."
        "Returns the name, description, and path for each skill."
    )
    args_schema: Optional[ArgsSchema] = EmptyArgs
    workspace: str = Field(
        default=".",
        description="Workspace directory path"
    )
    agent: Optional[Any] = Field(
        default=None,
        description="VerifyAgent instance to access message history"
    )

    def __init__(self, workspace: str = ".", **kwargs):
        super().__init__(workspace=workspace, **kwargs)

    def bind(self, agent):
        """Bind the VerifyAgent instance."""
        self.agent = agent
        return self

    def _run(self, *args, **kwargs) -> str:
        """List all available skills in the workspace you can use.
        Returns:
            A formatted string containing information about all available skills.
        """
        skills_path = get_abs_path_cwd_ucagent(self.workspace, "skills")
        if not skills_path.exists():
            raise ValueError(f"Skill directory not found: {skills_path}. You need to start UCAgent with arg(--use-skill) to copy skills into the workspace.")
        skills = _list_skills(str(skills_path), workspace=None)

        if not skills:
            raise ValueError(f"No available skills found in skill directory {skills_path}. Skills should be subdirectories containing a SKILL.md file.")

        stage_manager = self.agent.stage_manager
        current_stage = stage_manager.get_current_stage()
        skills_to_list = []
        skill_names_added = set()  
        # 1. add skills in skill_list
        if current_stage and current_stage.skill_list:
            for skill in skills:
                if skill['name'] in current_stage.skill_list:
                    skills_to_list.append(skill)
                    skill_names_added.add(skill['name'])
        # 2. add skills in general_skill_list
        general_skill_list = stage_manager.cfg.get_value('skill.general_skill_list', [])
        if general_skill_list:
            for skill in skills:
                if skill['name'] in general_skill_list and skill['name'] not in skill_names_added:
                    skills_to_list.append(skill)
                    skill_names_added.add(skill['name']) 

        # List SKILL with their (name, description and path)
        result_lines = [f"Found {len(skills_to_list)} available skills:"]
        result_lines += list_skills_in_format(skills_to_list, workspace=self.workspace).split("\n")
        result_lines.append("Tip: When the task description matches a skill description, use the `ReadTextFile` tool to read the corresponding skill's SKILL.md file, learn the skill, and apply it.")      
        result= "\n".join(result_lines)

        return result
    
class ArgsRunSkillScript(BaseModel):
    commands: List[str] = Field(description="A list of commands declared in the SKILL.md of a skill."\
                                            "Each command must meet the following format:"\
                                            "python3 script -ARG1 VALUE1 -ARG2 VALUE2 ... -ARGN VALUEN"\
                                            "python3 can be change to other execution based on the type of script"
                                            "script is the path of the script to be executed"
                                            "followed by a list of arguments, where each argument is prefixed with a hyphen (-) and followed by its corresponding value.")

class RunSkillScript(UCTool):
    name: str = "RunSkillScript"
    description: str = (
        "Run the commands in a list declared in the SKILL.md of a skill"
    )
    args_schema: Optional[ArgsSchema] = ArgsRunSkillScript
    workspace: str = Field(
        default=".",
        description="Workspace directory path"
    )
    agent: Optional[Any] = Field(
        default=None,
        description="VerifyAgent instance"
    )

    def __init__(self, workspace: str = ".", **kwargs):
        super().__init__(workspace=workspace, **kwargs)

    def bind(self, agent):
        """Bind the VerifyAgent instance."""
        self.agent = agent
        return self

    def _run(self, commands: List[str]) -> str:
        """Execute a skill script command.
        Returns:
            The output of the command execution.
        """
        env= os.environ.copy()
        env["DUT"] = str(self.agent.cfg._temp_cfg["DUT"])
        env["OUT"] = str(self.agent.cfg._temp_cfg["OUT"])
        run_result=""
        for command in commands:
            try:
                process = subprocess.run(
                    command,
                    shell=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=self.workspace,
                    env=env
                )
                run_result+=process.stdout
            except subprocess.CalledProcessError as e:
                return f"Command failed with exit code {e.returncode}:\n{e.stdout}"
            except FileNotFoundError:
                return f"Command not found: {command.split()[0]}"
        return run_result

__all__ = ["ListSkill", "RunSkillScript"]