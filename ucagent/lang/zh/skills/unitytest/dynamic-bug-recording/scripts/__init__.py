import os


TASK_POLICY = (
    "动态 Bug 文档优先维护策略：对 `{BUG_DOCUMENT}` 尽可能使用当前 Skill，避免主动用"
    "文本工具直接修改。其他文档和代码仍使用当前 stage 允许的普通工具。结构、关闭标记"
    "或 ROOT/BG 关系异常时，先调用 RunSkillScript(commands=[[\"unitytest/"
    "dynamic-bug-recording\", \"record_dynamic_bug.py\", \"-MODE repair\"]])；"
    "BG/TC 三字段及唯一 ROOT 关联优先用 -MODE bug，ROOT 五字段优先用 -MODE root，"
    "波形机器证据只用 WaveInfo 和 ApplyWaveInfoEvidence。Skill 或 Check 报告文档格式异常时，"
    "先执行一次返回的 next_action 或 -MODE repair；若相同阻塞仍存在，或 Skill 返回 "
    "manual_edit_fallback.allowed=true 且其 precondition 已满足，才用普通文本编辑工具修复 "
    "error/details 指出的最小范围，保留 identity 中的 BG、TC、checkpoint、ROOT 以及其他"
    "分析和波形。若返回 manual_edit_fallback 则按其 scope 编辑；编辑后立即执行其 "
    "after_edit，未返回时立即重跑 -MODE repair 和 Check，再按 workflow_context."
    "remaining_sequence 继续；不要用 shell 或临时 Python 改文档。"
    "最后依次调用 Check 和 Complete；公共 Skill 不调用 SetSkillUsage。"
)


def _resolved_path(stage, value):
    if not isinstance(value, str) or not value.strip() or "{" in value:
        return None
    path = value if os.path.isabs(value) else os.path.join(stage.workspace, value)
    return os.path.normcase(os.path.realpath(path))


def _references_target(stage, value, target):
    if isinstance(value, str):
        return _resolved_path(stage, value) == target
    if isinstance(value, dict):
        return any(
            _references_target(stage, item, target)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (list, tuple, set)):
        return any(_references_target(stage, item, target) for item in value)
    return False


def _stage_handles_bug_document(stage, bug_document):
    """Detect artifact writers and validators without coupling to stage names."""

    target = _resolved_path(stage, bug_document)
    if target is None:
        return False
    stage_values = [getattr(stage, "output_files", [])]
    stage_values.extend(
        getattr(checker, "__dict__", {})
        for checker in getattr(stage, "checker", [])
    )
    return any(_references_target(stage, value, target) for value in stage_values)


def setup_vstage(stage):
    """Expose the Skill-first policy only where the Bug artifact is consumed."""

    values = getattr(stage.cfg, "_temp_cfg", {})
    out_dir = values.get("OUT") if isinstance(values, dict) else None
    dut = values.get("DUT") if isinstance(values, dict) else None
    bug_document = (
        f"{out_dir}/{dut}_bug_analysis.md"
        if out_dir and dut
        else "{OUT}/{DUT}_bug_analysis.md"
    )
    if not _stage_handles_bug_document(stage, bug_document):
        return
    hook_key = "dynamic_bug_recording_task_hook"
    if getattr(stage, "meta_data", {}).get(hook_key):
        return

    def task_hook(orig_task_method):
        return modified_task_hook(orig_task_method, bug_document=bug_document)

    stage.add_hook("task", task_hook)
    stage.meta_data[hook_key] = True


def modified_task_hook(orig_task_method, bug_document="{OUT}/{DUT}_bug_analysis.md"):
    """Append the dynamic Bug document preference without changing other tasks."""

    tasks = orig_task_method()
    if not isinstance(tasks, list):
        return tasks
    policy = TASK_POLICY.format(BUG_DOCUMENT=bug_document)
    if policy in tasks:
        return tasks
    return [*tasks, policy]


__all__ = ["setup_vstage"]
