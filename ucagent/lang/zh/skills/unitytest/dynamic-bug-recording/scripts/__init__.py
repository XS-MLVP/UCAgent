TASK_POLICY = (
    "动态 Bug 文档所有权：仅 `{BUG_DOCUMENT}` 由当前 Skill 管理。"
    "禁止使用 EditTextFile、ReplaceStringInFile、DeleteTextLines、shell 或临时 Python "
    "直接创建、修改或修复该文件；其他文档和代码仍使用当前 stage 允许的普通工具。"
    "结构、关闭标记或 ROOT/BG 关系异常时，调用 RunSkillScript(commands=[[\"unitytest/"
    "dynamic-bug-recording\", \"record_dynamic_bug.py\", \"-MODE repair\"]])；"
    "BG/TC 三字段及唯一 ROOT 关联只用 -MODE bug，ROOT 五字段只用 -MODE root，"
    "波形机器证据只用 WaveInfo 和 ApplyWaveInfoEvidence。Skill 调用失败时严格执行其 "
    "next_action 和 workflow_context.remaining_sequence，逐字保持 identity 中的 BG、TC、"
    "checkpoint 和 ROOT 身份后再次调用 Skill，不得绕过 Skill 手工编辑动态 Bug 文档。"
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
