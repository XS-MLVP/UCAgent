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
    "最后依次调用 Check、SetSkillUsage 和 Complete。"
)


def setup_vstage(stage):
    """Make the active dynamic Bug task expose its Skill-owned file boundary."""

    values = getattr(stage.cfg, "_temp_cfg", {})
    out_dir = values.get("OUT") if isinstance(values, dict) else None
    dut = values.get("DUT") if isinstance(values, dict) else None
    bug_document = (
        f"{out_dir}/{dut}_bug_analysis.md"
        if out_dir and dut
        else "{OUT}/{DUT}_bug_analysis.md"
    )

    def task_hook(orig_task_method):
        return modified_task_hook(orig_task_method, bug_document=bug_document)

    stage.add_hook("task", task_hook)


def modified_task_hook(orig_task_method, bug_document="{OUT}/{DUT}_bug_analysis.md"):
    """Append the dynamic Bug document ownership policy without changing other tasks."""

    tasks = orig_task_method()
    if not isinstance(tasks, list):
        return tasks
    policy = TASK_POLICY.format(BUG_DOCUMENT=bug_document)
    if policy in tasks:
        return tasks
    return [*tasks, policy]


__all__ = ["setup_vstage"]
