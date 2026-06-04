# -*- coding: utf-8 -*-
"""Skills management tools for UCAgent.
This module provides tools to list and manage available skills in the workspace.
"""

import re
import os
import json
import shlex
import shutil
import copy
from pathlib import Path
from typing import Optional, TypedDict, Any, List, Sequence
import yaml
from pydantic import Field, BaseModel

import subprocess
from .uctool import UCTool, ArgsSchema, EmptyArgs
from ucagent.util.log import warning
import ucagent.util.functions as fc

# Security: Maximum size for SKILL.md files to prevent DoS attacks (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024


# Agent Skills specification constraints (https://agentskills.io/specification)
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024
SCRIPT_RUNNER_CONFIG = "script_runner.json"
SCRIPT_NON_EXECUTABLE_FILES = {"__init__.py", SCRIPT_RUNNER_CONFIG}
DEFAULT_SCRIPT_RUNNERS = {
    ".py": "python3",
    ".sh": "bash",
    ".bash": "bash",
}
_SKILL_LIST_CACHE: dict[str, list["SkillMetadata"]] = {}

class SkillMetadata(TypedDict):
    """Metadata for a skill."""
    name: str  # Skill identifier, relative to the workspace skill root
    description: str  # What the skill does (max 1024 chars)
    path: str  # Path to the SKILL.md file
    metadata: dict[str, str] # Additional metadata from SKILL.md frontmatter
    script: dict # Path to the skill script


def _get_script_runner(workspace: str, script_path: str) -> str:
    """Get a script runner by extension or script_runner.json."""
    script_file = Path(script_path)
    script_abs_path = script_file if script_file.is_absolute() else Path(workspace) / script_file
    runner = DEFAULT_SCRIPT_RUNNERS.get(script_file.suffix)

    if runner is None:
        config_path = script_abs_path.parent / SCRIPT_RUNNER_CONFIG
        if not config_path.exists():
            raise ValueError(f"Cannot get runner for script '{script_file.name}': {config_path} not found.")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {config_path}: {e}") from e
        except OSError as e:
            raise ValueError(f"Failed to read {config_path}: {e}") from e
        if not isinstance(config, dict):
            raise ValueError(f"Invalid {config_path}: expected a JSON object.")
        runner = config.get(script_file.name)

    if not isinstance(runner, str) or not runner.strip():
        raise ValueError(f"Invalid runner for script '{script_file.name}': runner must be a non-empty string.")
    runner = runner.strip()
    if len(shlex.split(runner)) != 1:
        raise ValueError(f"Invalid runner for script '{script_file.name}': runner must be a single executable.")
    if shutil.which(runner) is None:
        raise ValueError(f"Invalid runner for script '{script_file.name}': executable not found: {runner}")
    return runner


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


def _scan_skills(workspace: str) -> list[SkillMetadata]:
    """List all skills from a directory.
    Scans directory recursively for SKILL.md files, reads their content,
    parses YAML frontmatter, and returns skill metadata.
    Expected structure:
        skill_path/
        ├── group-a/
        │   ├── skill-1-name/
        │   │   ├── SKILL.md    # Required
        │   │   ├── scripts
        │   │   │   └── __init__.py   # Optional
        │   │   │   └── script_1.py   # Optional
        ├── skill-2-name/
        │   ├── SKILL.md        # Required
    Args:
        workspace: Path to the workspace directory containing skills
    Returns:
        List of skill metadata from successfully parsed SKILL.md files
    """
    skills: list[SkillMetadata] = []

    # Convert to Path objects for easier manipulation
    workspace_path = Path(workspace).resolve()
    source_path = fc.get_workspace_skill_root(workspace)
    base_path = Path(source_path)
    base_path_resolved = base_path.resolve()

    # Check if source path exists
    if not base_path.exists():
        warning(f"Skills source path does not exist: {source_path}")
        return []

    if not base_path.is_dir():
        warning(f"Skills source path is not a directory: {source_path}")
        return []

    # Iterate through all skill directories recursively by SKILL.md marker file
    try:
        for skill_md_path in sorted(base_path.rglob("SKILL.md")):
            if not skill_md_path.is_file():
                continue
            skill_dir = skill_md_path.parent

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
                skill_path=skill_md_path.resolve().relative_to(workspace_path).as_posix(),
                directory_name=skill_dir.name
            )
            if skill_metadata:
                skill_metadata['name'] = skill_dir.resolve().relative_to(base_path_resolved).as_posix()
                skill_metadata['script'] = {}
                script_dir = skill_dir / "scripts"
                if script_dir.exists() and script_dir.is_dir():
                    for f in sorted(script_dir.iterdir()):
                        if f.is_file() and f.name not in SCRIPT_NON_EXECUTABLE_FILES:
                            skill_metadata['script'][f.name] = f.resolve().relative_to(workspace_path).as_posix()
                skills.append(skill_metadata)

    except PermissionError as e:
        warning(f"Permission denied accessing {source_path}: {e}")
    except Exception as e:
        warning(f"Error scanning skills directory {source_path}: {e}")

    return skills


def _list_skills(workspace: str) -> list[SkillMetadata]:
    """List skills from a workspace, using a per-process cache."""
    workspace_key = Path(workspace).resolve().as_posix()
    if workspace_key not in _SKILL_LIST_CACHE:
        _SKILL_LIST_CACHE[workspace_key] = copy.deepcopy(_scan_skills(workspace))
    return copy.deepcopy(_SKILL_LIST_CACHE[workspace_key])

def list_skills_in_format(
    skills: list[SkillMetadata],
    workspace: str = '.',
    able_to_list: Optional[Sequence[str]] = None,
) -> str:
    """Format a list of skills into a readable string.
    Args:
        skills: List of SkillMetadata to format
        workspace: Path to the workspace directory
        able_to_list: List of skill names that are able to be listed
    Returns:
        A formatted string listing each skill's path-style name, description, and path
    """
    def _format_display_path(path_value: str) -> str:
        p = Path(path_value)
        if not p.is_absolute():
            return str(p)
        try:
            return str(p.relative_to(Path(workspace)))
        except ValueError:
            return str(p)

    allowed_skills = set(able_to_list or [])
    result_lines = []
    count=1
    for skill in skills:
        if skill['name'] in allowed_skills:
            result_lines.append(f"{count}. Skill Name: {skill['name']}")
            result_lines.append(f"   Skill Description: {skill['description']}")
            result_lines.append(f"   Skill Path: {_format_display_path(skill['path'])}")
            if skill.get('script'):
                result_lines.append("   Script Path:")
                for fname, fpath in skill['script'].items():
                    result_lines.append(f"     - {fname}: {_format_display_path(fpath)}")
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
        skills_path = Path(fc.get_workspace_skill_root(self.workspace))
        if not skills_path.exists():
            raise ValueError(f"Skill directory not found: {skills_path}. You need to start UCAgent with arg(--use-skill) to copy skills into the workspace.")
        skills = _list_skills(self.workspace)

        if not skills:
            raise ValueError(f"No available skills found in skill directory {skills_path}. Skills should be subdirectories containing a SKILL.md file.")

        stage_manager = self.agent.stage_manager
        current_stage = stage_manager.get_current_stage()
        max_skill_list_count = stage_manager.cfg.get_value('skill.max_skill_list_count', 0)
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
                if max_skill_list_count and len(skills_to_list) >= max_skill_list_count:
                    break
                if skill['name'] in general_skill_list and skill['name'] not in skill_names_added:
                    skills_to_list.append(skill)
                    skill_names_added.add(skill['name']) 

        # List SKILL with their path-style name, description and path
        result_lines = [f"Found {len(skills_to_list)} available skills:"]
        result_lines += list_skills_in_format(
            skills_to_list,
            workspace=self.workspace,
            able_to_list=[skill["name"] for skill in skills_to_list],
        ).split("\n")
        result_lines.append("Tip: When the task description matches a skill description, use the `ReadTextFile` tool to read the corresponding skill's SKILL.md file, learn the skill, and apply it.")
        result= "\n".join(result_lines)

        return result

class ArgsRunSkillScript(BaseModel):
    commands: List[List[str]] = Field(description="A list of commands to execute the skill script by RunSkillScript."\
                                                   "Each command is a 3-element string array: [skill_name, skill_script, args]."\
                                                   "skill_name is the path-style name of an available skill, such as unitytest/functions-and-checks."\
                                                   "skill_script is the script filename with extension, not a path."\
                                                   "The runner is inferred from the script extension, or from script_runner.json in the script directory."\
                                                   "args is a single string of command arguments, for example: -ARG1 'VALUE1' -ARG2 'VALUE2'."\
                                                   "Multiple commands can be provided in the list at once.")

class RunSkillScript(UCTool):
    name: str = "RunSkillScript"
    description: str = (
        "Run the commands in a list declared in the SKILL.md of a skill"
        "Support multiple commands in the list at once"
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

    def _run(self, commands: List[List[str]]) -> str:
        """Execute a skill script command.
        Returns:
            The output of the command execution.
        """
        skills_path = Path(fc.get_workspace_skill_root(self.workspace))
        if not skills_path.exists():
            return f"Skill directory not found: {skills_path}. You need to start UCAgent with arg(--use-skill) to copy skills into the workspace."
        skills = _list_skills(self.workspace)
        skill_by_path_name = {skill["name"]: skill for skill in skills}

        env= os.environ.copy()
        env["DUT"] = str(self.agent.cfg._temp_cfg["DUT"])
        env["OUT"] = str(self.agent.cfg._temp_cfg["OUT"])
        run_result=""
        for index, command in enumerate(commands, start=1):
            if len(command) != 3:
                return f"Command {index} invalid: expected [skill_name, skill_script, args], got {len(command)} elements."

            skill_name, skill_script, args = command
            if not all(isinstance(item, str) for item in command):
                return f"Command {index} invalid: skill_name, skill_script, and args must all be strings."

            skill_name = skill_name.strip()
            skill_script = skill_script.strip()
            if not skill_name:
                return f"Command {index} invalid: skill_name is empty."
            if not skill_script:
                return f"Command {index} invalid: skill_script is empty."
            if Path(skill_script).name != skill_script:
                return f"Command {index} invalid: skill_script must be a filename, not a path: {skill_script}"

            skill = skill_by_path_name.get(skill_name)
            if not skill:
                return f"Command {index} invalid: skill not found: {skill_name}"

            scripts = skill.get("script", {})
            script_path = scripts.get(skill_script)
            if not script_path:
                available_scripts = ", ".join(sorted(scripts.keys())) or "none"
                return (
                    f"Command {index} invalid: script '{skill_script}' is not under skill "
                    f"'{skill_name}'. Available scripts: {available_scripts}"
                )

            try:
                parsed_args = shlex.split(args)
            except ValueError as e:
                return f"Command {index} invalid: failed to parse args: {e}"

            runner = _get_script_runner(self.workspace, script_path)
            argv = [runner, script_path, *parsed_args]
            try:
                process = subprocess.run(
                    argv,
                    shell=False,
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
            except FileNotFoundError as e:
                raise ValueError(f"Command {index} runner not found: {runner}") from e
        return run_result

__all__ = ["ListSkill", "RunSkillScript"]
