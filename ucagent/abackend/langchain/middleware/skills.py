"""Skills middleware for loading and exposing agent skills to the system prompt.

This module implements Anthropic's agent skills pattern with progressive disclosure,
loading skills from filesystem directories.

## Architecture

Skills are loaded from one or more **sources** - filesystem paths where skills are
organized. Sources are loaded in order, with later sources overriding earlier ones
when skills have the same name (last one wins). This enables layering: base -> user
-> project -> team skills.

## Skill Structure

Each skill is a directory containing a SKILL.md file with YAML frontmatter:

```
/skills/analyze/
├── SKILL.md          # Required: YAML frontmatter + markdown instructions
└── helper.py         # Optional: supporting files
```

SKILL.md format:
```markdown
---
name: web-research
description: Structured approach to conducting thorough web research
license: MIT
---

# Web Research Skill

## When to Use
- User asks you to research a topic
...
```

## Skill Metadata (SkillMetadata)

Parsed from YAML frontmatter per Agent Skills specification:
- `name`: Skill identifier (max 64 chars, lowercase alphanumeric and hyphens)
- `description`: What the skill does (max 1024 chars)
- `path`: Filesystem path to the SKILL.md file
- Optional: `license`, `compatibility`, `metadata`, `allowed_tools`

"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Annotated

import yaml
from langchain.agents.middleware.types import PrivateStateAttr

from typing import NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
)
from ucagent.util.log import warning
from langchain_core.messages import SystemMessage,RemoveMessage
from langgraph.graph.message import (
    REMOVE_ALL_MESSAGES,
)

# Security: Maximum size for SKILL.md files to prevent DoS attacks (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024

# Agent Skills specification constraints (https://agentskills.io/specification)
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024


class SkillMetadata(TypedDict):
    """Metadata for a skill per Agent Skills specification (https://agentskills.io/specification)."""

    """Skill identifier (max 64 chars, lowercase alphanumeric and hyphens)."""
    name: str
    """What the skill does (max 1024 chars)."""
    description: str
    """Path to the SKILL.md file."""
    path: str
    """License name or reference to bundled license file."""
    license: str | None
    """Environment requirements (max 500 chars)."""
    compatibility: str | None
    """Arbitrary key-value mapping for additional metadata."""
    metadata: dict[str, str]
    """Space-delimited list of pre-approved tools. (Experimental)"""
    allowed_tools: list[str]


class SkillsState(AgentState):
    """State for the skills middleware."""
    skills_metadata: NotRequired[Annotated[list[SkillMetadata], PrivateStateAttr]]


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""
    skills_metadata: list[SkillMetadata]


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


def _parse_skill_metadata(
    content: str,
    skill_path: str,
    directory_name: str,
) -> SkillMetadata | None:
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
        warning("Skipping %s: content too large (%d bytes)", skill_path, len(content))
        return None

    # Match YAML frontmatter between --- delimiters
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        warning("Skipping %s: no valid YAML frontmatter found", skill_path)
        return None

    frontmatter_str = match.group(1)

    # Parse YAML using safe_load for proper nested structure support
    try:
        frontmatter_data = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        warning("Invalid YAML in %s: %s", skill_path, e)
        return None

    if not isinstance(frontmatter_data, dict):
        warning("Skipping %s: frontmatter is not a mapping", skill_path)
        return None

    # Validate required fields
    name = frontmatter_data.get("name")
    description = frontmatter_data.get("description")

    if not name or not description:
        warning("Skipping %s: missing required 'name' or 'description'", skill_path)
        return None

    # Validate name format per spec (warn but continue loading for backwards compatibility)
    is_valid, error = _validate_skill_name(str(name), directory_name)
    if not is_valid:
        warning(
            "Skill '%s' in %s does not follow Agent Skills specification: %s. Consider renaming for spec compliance.",
            name,
            skill_path,
            error,
        )

    # Validate description length per spec (max 1024 chars)
    description_str = str(description).strip()
    if len(description_str) > MAX_SKILL_DESCRIPTION_LENGTH:
        warning(
            "Description exceeds %d characters in %s, truncating",
            MAX_SKILL_DESCRIPTION_LENGTH,
            skill_path,
        )
        description_str = description_str[:MAX_SKILL_DESCRIPTION_LENGTH]

    if frontmatter_data.get("allowed-tools"):
        allowed_tools = frontmatter_data.get("allowed-tools").split(" ")
    else:
        allowed_tools = []

    return SkillMetadata(
        name=str(name),
        description=description_str,
        path=skill_path,
        metadata=frontmatter_data.get("metadata", {}),
        license=frontmatter_data.get("license", "").strip() or None,
        compatibility=frontmatter_data.get("compatibility", "").strip() or None,
        allowed_tools=allowed_tools,
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
                    warning(f"Copied skill '{skill_dir.name}' to {dest_skill_dir}")
                except Exception as e:
                    warning(f"Failed to copy skill directory {skill_dir} to workspace: {e}")
            
            # Read SKILL.md content
            try:
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError as e:
                warning("Error decoding %s: %s", skill_md_path, e)
                continue
            except IOError as e:
                warning("Error reading %s: %s", skill_md_path, e)
                continue
            
            # Parse metadata
            skill_metadata = _parse_skill_metadata(
                content=content,
                skill_path=str(skill_md_path),
                directory_name=skill_dir.name,
            )
            if skill_metadata:
                skills.append(skill_metadata)
    
    except PermissionError as e:
        warning("Permission denied accessing %s: %s", source_path, e)
    except Exception as e:
        warning("Error scanning skills directory %s: %s", source_path, e)
    
    return skills


async def _alist_skills(source_path: str, workspace: str = None) -> list[SkillMetadata]:
    """List all skills from a directory (async version).
    """
    # For now, delegate to synchronous version
    # In production, consider using aiofiles for true async file I/O
    return _list_skills(source_path, workspace)


SKILLS_SYSTEM_PROMPT = """

**技能专家**：
你是一个拥有丰富专业技能库的专家,擅长使用特定的专业技能完成特定任务。技能库中的**可用技能**的名称及其描述如下(技能名称:技能描述):
{skills_list}

**技能使用步骤**：
- **描述匹配**：每次接受用户请求时,首先检查用户请求的任务是否可以与技能描述匹配,或者与技能描述中的关键词匹配
- **激活使用**：如果描述匹配,**必须**激活并使用对应技能
- **阅读完整说明**：激活技能后,通过对应技能的路径找到并阅读对应的 SKILL.md 获取详细指导
- **遵循工作流**：严格按照 SKILL.md 中的步骤和最佳实践执行
- **按需访问**： SKILL.md 所在目录下可能包含辅助脚本、参考文档等,按需访问

**注意**：专业技能在处理特定任务是能取得更好的效果,因此只要任务与描述相匹配,就使用对应技能,不要犹豫或跳过。
**使用优先级**：技能(skill) > 工具(tool) 
!!!牢记,你可以使用以上技能,不要忘记他们的存在!!!
"""


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills to the system prompt.

    Loads skills from filesystem sources and injects them into the system prompt
    using progressive disclosure (metadata first, full content on demand).

    Skills are loaded in source order with later sources overriding earlier ones.
    """

    def __init__(self, vagent, *, sources: list[str]) -> None:
        """ Args:
                vagent: VAgent instance (for system prompt access)
                sources: List of skill source paths (e.g., ["ucagent/lang/zh/skill/"]).
        """
        self.vagent = vagent
        self.sources = sources
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            paths = [f"{source_path}" for source_path in self.sources]
            return f"(No skills available yet. You can create skills in {' or '.join(paths)})"

        lines = []
        for skill in skills:
            lines.append(f"- **{skill['name']}**:   {skill['description']}")
            if skill["allowed_tools"]:
                lines.append(f"  -> Allowed tools: {', '.join(skill['allowed_tools'])}")
            path_list=skill['path'].split("/")
            true_path="skills/"+path_list[-2]+"/"+path_list[-1]
            lines.append(f"  -> 阅读 `{true_path}` 获得技能的完整内容和使用说明。")

        return "\n".join(lines)

    def modify_system_prompt(self, state,skills: list[SkillMetadata]) -> ModelRequest:
        """Inject skills documentation into a model request's system message."""
        messages=state["messages"]
        system_prompt = messages[0]
        last_messages=messages[1:]
        
        # 防止重复添加 Skills System 内容
        content = system_prompt.content
        if "## 技能系统" not in content:
            skills_metadata = skills
            skills_list = self._format_skills_list(skills_metadata)
            skills_section = self.system_prompt_template.format(
                skills_list=skills_list,
            )
            content = content + skills_section
        
        new_system_message = SystemMessage(content=content)
        return [RemoveMessage(id=REMOVE_ALL_MESSAGES)]+[new_system_message]+last_messages

    def before_agent(self, state: SkillsState):
        """Load skills metadata before agent execution (synchronous)."""
        # Skip if skills is already present in role prompt
        messages=state["messages"]
        role=messages[0].content
        if "技能" in role:
            return None
        
        all_skills: dict[str, SkillMetadata] = {}
        # Load skills from each source in order, later sources override earlier ones (last one wins)
        workspace = getattr(self.vagent, 'workspace', None)
        for source_path in self.sources:
            source_skills = _list_skills(source_path, workspace)
            for skill in source_skills:
                all_skills[skill["name"]] = skill

        skills = list(all_skills.values())
        return {"messages": self.modify_system_prompt(state,skills)}

    async def abefore_agent(self, state: SkillsState):
        """Load skills metadata before agent execution (async)."""
        # Skip if skills_metadata is already present in state (even if empty)
        if "skills_metadata" in state:
            return None

        all_skills: dict[str, SkillMetadata] = {}
        # Load skills from each source in order, later sources override earlier ones (last one wins)
        workspace = getattr(self.vagent, 'workspace', None)
        for source_path in self.sources:
            source_skills = await _alist_skills(source_path, workspace)
            for skill in source_skills:
                all_skills[skill["name"]] = skill

        skills = list(all_skills.values())
        return {"messages": self.modify_system_prompt(state,skills)}

__all__ = ["SkillMetadata", "SkillsMiddleware"]