
# 技能 SKILL

技能把可复用的任务方法、脚本和参考资料放在一个目录中。Agent 先列出技能，再按需读取 `SKILL.md`，避免一次把所有说明加入上下文。技能用于加速和指导任务；关闭技能时，工作流仍须提供完整任务说明、工具路径和相同的 Checker 验收标准。

## 启用和配置

内置配置默认启用技能；未传 CLI 开关时，以分层配置中的 `skill.use_skill` 为准。可显式覆盖：

```bash
ucagent <workspace> <DUT> --use-skill
ucagent <workspace> <DUT> --no-use-skill
```

配置文件中可以关闭：

```yaml
skill:
  use_skill: false
```

`--extra-skill-path <path>` 追加自定义技能并启用技能支持，不能与 `--no-use-skill` 同时使用。初始化时，技能复制到工作区 `.ucagent/skills/`，额外技能位于其中的 `ext/`。工具读取和运行的是工作区副本；修改源码中的技能后，需要重启并重新复制，才会使用新内容。

## 阶段技能与通用技能

阶段配置示例：

```yaml
stage:
  - name: static_analysis
    desc: "分析静态缺陷候选"
    task:
      - "阅读源码和需求，按 Guide_Doc/dut_bug_analysis.md 完成静态分析"
    skill_list:
      - unitytest/static-bug-analysis
    force_use_skill: true
```

| 配置 | 使用要求 |
| --- | --- |
| 技能启用且阶段 `skill_list` 非空 | 默认强制，`Complete` 前必须满足使用证据 |
| 阶段设置 `force_use_skill: false` | 该阶段专用技能可选 |
| 未配置或空 `skill_list` | 不要求 `SetSkillUsage`，不执行阶段技能门禁 |
| `skill.general_skill_list` | 通用技能始终可选 |
| 技能整体关闭 | 所有阶段技能门禁关闭，其他验收要求照常执行 |

技能门禁作用于 `Complete`，不会阻断中间 `Check`。关闭技能也不应因为 `.ucagent/skills/` 不存在而阻断任务。

## 使用流程与证据

强制阶段技能按以下顺序使用：

1. 调用 `ListSkill`，列出当前可用技能。
2. 用 UCAgent 的 `ReadTextFile` 读取返回的工作区 `SKILL.md` 路径。
3. 按技能方法执行任务；需要脚本时，通过 `RunSkillScript` 执行。
4. 调用 `Check` 校验当前产物。
5. 当前 `Check` 通过后，调用 `SetSkillUsage` 确认使用情况。
6. 调用 `Complete` 完成阶段。

`ListSkill` 和 `ReadTextFile` 分别产生真实的 list/read 记录；`RunSkillScript` 整次调用成功后登记脚本使用。`SetSkillUsage` 不能通过模型声明补造这些记录。它可以在 list/read 和当前通过的 `Check` 均具备后，确认已执行的文本方法。

已应用方法时，`SetSkillUsage` 的工具参数如下：

```json
{
  "skill_usage": {
    "unitytest/static-bug-analysis": {
      "list": true,
      "read": true,
      "use": true
    }
  }
}
```

如果当前阶段没有技能可处理的对象，在执行其无适用对象分支、通过 `Check` 后，提交 `use: false` 和非空 `reason`，说明具体原因。该理由不能替代 list/read、跳过当前检查或覆盖已经观察到的 `use: true`；也不能为了满足技能门禁制造 Bug 或产物。`use: true` 时不填写 `reason`。

## 相关工具

| 工具 | 用途 |
| --- | --- |
| `ListSkill` | 返回当前阶段专用技能和可用通用技能的名称、描述、`SKILL.md` 与脚本路径 |
| `ReadTextFile` | 读取技能正文并登记阅读证据 |
| `RunSkillScript` | 顺序执行已列出的技能脚本，全部成功后登记使用 |
| `SetSkillUsage` | 验证并保存当前阶段专用技能的证据 |

`ListSkill` 优先列出全部阶段技能，再按 `skill.max_skill_list_count` 限制补充通用技能；阶段技能不会因该上限被截断。技能标识是相对于工作区技能根目录的路径，例如 `unitytest/static-bug-analysis`。

`RunSkillScript.commands` 是非空数组，每项为三个字符串：`[skill_name, script_filename, args]`。脚本名不含目录或 runner。假设自定义技能 `example/analysis` 已列出脚本 `analyze.py`，调用形式为：

```json
{
  "commands": [
    ["example/analysis", "analyze.py", "--input 'input.md'"]
  ]
}
```

优先传嵌套 JSON 数组。脚本按顺序执行，任一失败就停止；已执行的文件修改不会自动回滚，整次调用失败也不会登记本次脚本使用。

## 技能目录与元数据

```text
analysis/
├── SKILL.md
├── scripts/                  # 可选
│   ├── analyze.py
│   ├── __init__.py           # 可选阶段 hook
│   └── script_runner.json    # 可选 runner 映射
└── references/               # 可选辅助资料
```

`SKILL.md` 第一行必须直接是 `---`，frontmatter 至少包含 `name` 和 `description`：

```markdown
---
name: analysis
description: 分析输入资料，按项目约定生成并检查结果
metadata:
  category: analysis
---

# 分析输入资料

## 目标与输入

列出适用任务、输入文件和前置条件。

## 执行步骤

说明读取哪些资料、如何分析、何时调用脚本以及如何校验。

## 输出与验收

说明允许写入的路径、完整产物格式和失败后的修复步骤。
```

- `name`：不超过 64 个字符，只使用小写字母、数字和连字符，并满足命名校验。
- `description`：说明适用任务，最多 1024 字符；超长部分会被截断。描述帮助 Agent 选择技能，不会自动触发脚本。
- `metadata`：可选的字符串键值映射；运行时会将键和值转换为字符串。

正文要给出可执行步骤和真实脚本参数。强制格式和证据规则还必须在阶段任务、Guide_Doc 和模板中可用，避免技能关闭后丢失验收依据。

## 脚本运行环境

脚本进程以 DUT 工作区为当前目录。`RunSkillScript` 使用 `shlex` 拆分参数，再以 runner 和 argv 启动进程，`shell=False`；不要依赖管道、重定向或 shell 变量展开。

- `.py` 使用运行 UCAgent 的 Python 解释器；`.sh`、`.bash` 使用 Bash。
- 其他脚本在 `scripts/script_runner.json` 中以 `{"filename": "executable"}` 指定单一可执行程序，不能附带 runner 参数。
- 环境中的 `DUT`、`OUT` 来自 `.ucagent/runtime_config.json` 的已解析配置。
- `RunSkillScript` 读取快照中的 `ucagent_python_path`，将其放在子进程 `PYTHONPATH` 首位，去重并保留其他导入路径。

Python 技能脚本需要导入 `ucagent` 时，通过 `RunSkillScript` 执行。脚本用 `load_runtime_config(workspace)` 读取运行配置，不要重新解释原始功能环境变量，或从复制后的脚本位置猜测 UCAgent 源码目录。快照中的导入路径缺失、非绝对路径或已失效时，重启 UCAgent 重新生成快照。

## 阶段 hook（高级）

技能可以在非空 `scripts/__init__.py` 中提供 `setup_vstage(stage)`，通过 `stage.add_hook(method_name, hook_func)` 包装当前阶段已有的方法。阶段专用 `skill_list` 和 `skill.general_skill_list` 中的技能都会参与 hook 加载，并去重。

hook 只作用于当前阶段实例。注册要保持幂等，避免导入时执行隐藏操作；也不能把强制行为只放进 hook，导致禁用技能后无法完成任务。

开发和测试技能时，至少验证启用、关闭及技能目录缺失三种情况。工作流中的配置方式见[工作流配置](../03_develop/03_workflow.md)，工具与路径策略见[定制工具](../03_develop/05_customize.md)。
