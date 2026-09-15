# -*- coding: utf-8 -*-
"""Lazy public exports for UCAgent tools.

Importing one tool module must not initialize unrelated optional tool stacks. In
particular, lightweight plugin tools should not load memory-model dependencies
merely because they inherit :class:`UCTool`.
"""

from importlib import import_module
from typing import Any


_EXPORT_GROUPS = {
    "extool": (
        "SqThink",
        "ReflectionTool",
        "SimpleReflectionTool",
    ),
    "fileops": (
        "is_file_writeable",
        "BaseReadWrite",
        "StrictToolArgs",
        "ArgSearchText",
        "SearchText",
        "ArgFindFiles",
        "FindFiles",
        "ArgPathList",
        "PathList",
        "ArgReadBinFile",
        "ReadBinFile",
        "ArgReadTextFile",
        "ReadTextFile",
        "ArgEditTextFile",
        "EditTextFile",
        "ArgCopyFile",
        "CopyFile",
        "ArgMoveFile",
        "MoveFile",
        "ArgDeleteFile",
        "DeleteFile",
        "ArgCreateDirectory",
        "CreateDirectory",
        "ArgDeleteTextLines",
        "DeleteTextLines",
        "ArgReplaceStringInFile",
        "ReplaceStringInFile",
        "ArgGetFileInfo",
        "GetFileInfo",
    ),
    "human": (
        "ArgHumanHelp",
        "HumanHelp",
    ),
    "testops": (
        "ArgRunPyTest",
        "RunPyTest",
        "RunUnityChipTest",
    ),
    "uctool": (
        "EmptyArgs",
        "ExtraArgModelBase",
        "ForbidExtraArgModelBase",
        "UCTool",
        "RoleInfo",
        "to_fastmcp",
    ),
    "memory": (
        "ArgsMemSearch",
        "new_embed",
        "SemanticSearchInGuidDoc",
        "ArgsMemoryPut",
        "ArgsMemoryGet",
        "MemoryTool",
        "MemoryPut",
        "MemoryGet",
    ),
    "planning": (
        "ToDoPanel",
        "ToDoTool",
        "ArgsToDoCreate",
        "ArgsCompleteToDoSteps",
        "ArgsUndoToDoSteps",
        "CreateToDo",
        "CompleteToDoSteps",
        "UndoToDoSteps",
        "ResetToDo",
        "GetToDoSummary",
        "ToDoState",
    ),
    "workdiff": (
        "ArgsWorkDiff",
        "WorkDiff",
        "ArgsWorkCommit",
        "WorkCommit",
    ),
    "bash": (
        "RunBashCommandInput",
        "RunBashCommand",
    ),
    "skill": (
        "ListSkill",
        "RunSkillScript",
    ),
    "waveform": (
        "WaveSignalPattern",
        "WaveSignalGroups",
        "WaveInfoAnalysisArgs",
        "WaveInfoToolPattern",
        "ArgWaveInfo",
        "ArgApplyWaveInfoEvidence",
        "WaveInfoBugReview",
        "WaveInfoEvidenceReview",
        "WaveInfoEvidenceReviewItem",
        "ArgReviewWaveInfoEvidenceBatch",
        "WaveInfo",
        "ApplyWaveInfoEvidence",
        "ReviewWaveInfoEvidenceBatch",
    ),
}
_EXPORTS = {
    name: module_name
    for module_name, names in _EXPORT_GROUPS.items()
    for name in names
}
_SUBMODULES = frozenset(_EXPORT_GROUPS)

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load only the module that owns the requested public tool symbol."""

    if name in _SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy symbols and submodules to introspection tools."""

    return sorted(set(globals()) | set(__all__) | set(_SUBMODULES))
