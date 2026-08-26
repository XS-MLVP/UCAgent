
# 技能 SKILL

## 什么是技能

技能（Skill）是对一类`可复用任务方法`的封装。它把完成某种任务所需的说明、步骤、约束、脚本和辅助资料组织到一个目录中，供 UCAgent 在合适的时候读取和使用。

与只在对话中临时描述步骤相比，技能更适合处理：

- 步骤固定、可重复执行的任务
- 需要脚本辅助的任务
- 对输出格式和执行顺序有明确要求的任务
- 希望在多个阶段复用的方法

## 技能的基本机制

UCAgent 中的技能由以下几部分组成：

- 元数据
  - 写在 `SKILL.md` 文件顶部的 YAML frontmatter 中
  - 当前必须包含 `name` 和 `description`
- 技能正文
  - 写在 `SKILL.md` 中的正文部分
  - 用于描述执行步骤、约束、脚本使用方式和参考说明
- 脚本
  - 放在技能目录下的 `scripts/` 中
  - 通过 `RunSkillScript` 工具执行
- 辅助资源
  - 可放在 `references/` 或其他自定义目录中

需要注意的是：

- `SKILL.md` 不会在启动时全部自动加载进上下文
- UCAgent 通常先通过 `ListSkill` 了解当前可用技能，再通过 `ReadTextFile` 读取某个技能的 `SKILL.md`
- 技能启用时，阶段 `skill_list` 中的专用技能默认必须使用；只有该阶段显式设置 `force_use_skill: false` 时才可选
- `general_skill_list` 中的通用技能始终可选，不会进入阶段的强制使用校验

## 为什么使用技能

- 稳定性更高：相比于工作流,技能能够对阶段行为进行更为详细的描述,以及通过定制化脚本,稳定执行流程较为固定的复杂操作,提高文档编辑相关操作的正确性
- 上下文更省：通过`渐进式加载`机制,只有在需要时才加载完整的技能信息
- 复用性更强：同一个技能目录可以在多个任务中重复使用
- 可约束执行：阶段专用技能默认要求遵循；仅在确实适合可选使用时通过阶段配置显式关闭强制校验

## 技能目录结构

典型目录结构如下：

```text
skill-name/
├── SKILL.md          # 必需：技能说明与元数据
├── scripts/          # 可选：技能脚本
├── references/       # 可选：参考文档
└── ...               # 可选：其他辅助内容
```

说明：

- 技能目录名推荐直接作为技能名使用
- `scripts/__init__.py` 可选；如果存在且实现了 `setup_vstage(stage)`，可用于给当前阶段注册 hook
- `scripts/script_runner.json` 可选，用于为脚本添加对应的runner，目前内置支持`python3`和`bash`，其他脚本文件需要在该json文件中执行对应的runner，json格式为"script":"runner"
- `scripts/` 下除 `__init__.py` 和`script_runner.json`外的文件会被当作可执行脚本列出，供 `RunSkillScript` 使用

## SKILL.md 规范

### 1. 文件开头必须是 YAML frontmatter

当前实现要求 `SKILL.md` 的第一行直接是 `---`，不能在前面插入 HTML 注释或其他内容。

推荐格式如下：

```md
---
name: static-bug-analysis
description: 分析源码中的静态缺陷，并按规定格式记录 Bug 条目
metadata:
  owner: ucagent
  category: analysis
---

# 技能说明

技能目标、执行步骤、注意事项、脚本说明等内容。
```

### 2. 字段说明

- `name`
  - 必填
  - 推荐与技能目录名保持一致
  - 推荐只使用小写字母、数字和连字符 `-`
  - 字数限制: 
- `description`
  - 必填
  - 用于匹配任务,当任务描述与技能描述一致或相关时,将加载该技能的完整内容并使用技能
  - 字数限制: 
- `metadata`
  - 选填
  - 可放任意自定义键值对

## 技能脚本

### 脚本目录

技能脚本通常放在：

```text
skill-name/scripts/
```

### 脚本执行方式

脚本不是自动运行的，而是通过 `RunSkillScript` 工具执行。该工具支持一次提交多条命令，按顺序执行。

执行时具备以下特点：

- 当前工作目录为任务 `workspace`
- 环境变量中预先注入：
  - `DUT`
  - `OUT`
- 每条命令使用 shell 执行
- 如果中途某条命令失败，会直接返回该条命令的错误信息
- 已成功执行的前序命令不会自动回滚

### 文档中如何描述脚本

需要在 `SKILL.md` 中明确写出：

- 何时调用脚本
- 调用哪个脚本(脚本路径将自动补全)
- 参数含义及格式

例如：

```md
分析结果,并将结果按照以下结构记录:
`FILE`: Bug相关的源文件及行数
`BG`:Bug标签
`BD`:Bug描述

当完成全部分析后，使用 `RunSkillScript` 工具执行`record_result.py`脚本,命令行如下：
`python3 record_result.py -FILE 'FILE' -BG 'BG' -BD 'BD'`
```

## hook 机制

某些技能的执行方式可能与工作流阶段自身的任务描述有重叠或冲突。为此，技能可以通过 `scripts/__init__.py` 中的 `setup_vstage(stage)` 为当前阶段注册 hook。

示例：

```python
def setup_vstage(stage):
    stage.add_hook("task", modified_task_hook)


def modified_task_hook(orig_task_method):
    tasks = orig_task_method()
    if tasks and isinstance(tasks, list):
        return [tasks[0]]
    return tasks


__all__ = ["setup_vstage"]
```

说明：

- `setup_vstage(stage)` 会在阶段初始化时调用
- `stage.add_hook(method_name, hook_func)` 可替换当前 `VerifyStage` 实例上的方法行为
- hook 作用对象是当前阶段实例，不是全局对象

当前限制：

- 只有阶段 `skill_list` 中声明的技能会尝试加载其 `scripts/__init__.py`
- 只有 `VerifyStage` 实例上已有的方法才能被 hook
- 这套机制当前主要面向 `ucagent/stage/vstage.py` 中的 `VerifyStage`

## 技能启用方式

### 默认启用与命令行开关

技能功能默认开启，无需额外添加参数。以下命令会使用内置默认值启用技能：

```bash
ucagent <workspace> <dut_name>
```

也可以显式启用或关闭：

```bash
--use-skill
--no-use-skill
```

含义：

- `--use-skill` 显式启用技能机制，并覆盖配置文件中的关闭值
- `--no-use-skill` 显式关闭技能机制，并覆盖配置文件中的开启值
- 启用后，把 UCAgent 默认技能拷贝到当前工作区的 `.ucagent/skills/` 目录下
- 未指定命令行开关时，使用分层配置中的 `skill.use_skill`；内置配置为 `true`

也可以在配置文件中设置默认行为：

```yaml
skill:
  use_skill: false
```

命令行中显式传入的 `--use-skill` 或 `--no-use-skill` 优先于配置文件；未显式传入时，用户配置、工作区配置或任务配置中的 `skill.use_skill` 仍按正常配置优先级生效。

可以额外指定一个技能目录：

```bash
--extra-skill-path=extra_skill_dir/sub_dir/skill-a
```

含义：
- 额外拷贝指定路径下的技能`skill-a`到工作区 `.ucagent/skills/ext` 目录下，目录结构为`.ucagent/skills/ext/sub_dir/skill-a`，会忽略最外层的技能目录`extra_skill_dir`
- `--extra-skill-path` 会启用技能，不能与 `--no-use-skill` 同时使用

## 技能在工作区中的位置

启用后，技能会被复制到工作区下的`.ucagent/skills/`目录中,后续 `ListSkill`、`ReadTextFile`、`RunSkillScript` 看到的技能，都是以工作区中的这份副本为准。

## 阶段级技能配置

可在工作流阶段配置 `skill_list` 和 `force_use_skill` 参数。只有技能启用且当前阶段配置了非空 `skill_list` 时，才检查本阶段专用技能的使用；未配置或空列表不会触发 `SetSkillUsage` 或阶段 Skill 门禁。非空 `skill_list` 声明本阶段专用且默认必须使用的技能；只有显式设置 `force_use_skill: false`，才把该阶段的专用技能改为可选。`general_skill_list` 是独立的全阶段通用技能集合，始终可选且不触发阶段 Skill 门禁。

示例：

```yaml
stages:
  - name: example-stage
    skill_list:
      - "unitytest/static-bug-analysis"
```

含义：

- 当前阶段必须使用 `unitytest/static-bug-analysis` 技能，并在 `Complete` 前通过技能使用记录校验
- `force_use_skill` 默认为 `true`，通常无需显式填写
- 若要让当前阶段的 `skill_list` 可选，显式设置 `force_use_skill: false`；此时未读取或未使用这些技能不会阻断 `Check` 或 `Complete`
- `general_skill_list` 不受 `force_use_skill` 影响，始终不会阻断阶段

通过 `--no-use-skill` 或配置关闭技能时，所有阶段 Skill 使用门禁均不生效，工作流不会因 `skill_list` 或其默认值而报错。阶段仍须通过 task、Guide_Doc、内置工具和 Checker 完成同一任务与验收标准。

## 技能使用流程

推荐按以下顺序理解和使用技能：

1. 启动 UCAgent（技能默认开启；若配置中已关闭，可用 `--use-skill` 显式开启）
2. 通过 `ListSkill` 查看当前可用技能
3. 使用 `ReadTextFile` 读取目标技能的 `SKILL.md`
4. 按 `SKILL.md` 中的方法完成任务
5. 仅当技能方法要求已声明脚本时，使用 `RunSkillScript` 执行对应命令
6. 调用 `Check` 校验当前产物；`Check`不会自动把Skill登记为已使用
7. 仅当当前stage配置了非空`skill_list`时，调用`SetSkillUsage`验证并保存全部必需证据；已应用文本方法时提交`use: true`，没有适用对象时提交`use: false`和非空`reason`
8. 调用 `Complete` 推进阶段；显式设为可选的阶段技能可在实际使用后记录，通用技能不进入强制校验

对于强制技能，必须满足以下条件：

- 已通过 `ListSkill` 列出
- 已通过 `ReadTextFile` 读取对应 `SKILL.md`
- 当前`Check`已通过
- 二选一记录结果：已应用方法时提交`use: true`；没有适用对象时提交`use: false`和非空`reason`

## 技能相关工具

### ListSkill

用途：

- 列出当前阶段可以使用的技能

技能列举优先级如下:

- 当前阶段 `skill_list` 中声明的技能(所有)
- 配置中的 `general_skill_list`,即通用技能(总数不超过`max_skill_list_count`个)

返回内容通常包括：

- 技能名
- 技能描述
- `SKILL.md` 路径
- 可用脚本路径

### RunSkillScript

用途：

- 执行技能文档中声明的脚本命令

特点：

- `commands` 是非空数组，每项都是3个字符串组成的`[skill_name, skill_script, args]`
- 优先传真实嵌套JSON数组；只有后端无法正确传输嵌套数组时，才把完整外层数组编码成JSON字符串
- 按顺序逐条执行
- 某条失败后直接返回错误，不会继续后续命令；整次调用全部成功后才登记脚本使用证据

示意：

```json
{
  "commands": [
    ["unitytest/dynamic-bug-recording","record_dynamic_bug.py","-BG 'BG-OVERFLOW-95' -TC 'TC-unity_test/tests/test_a.py::test_overflow' -BD '溢出结果错误'"],
    ["unitytest/dynamic-bug-recording","record_dynamic_bug.py","-BG 'BG-STATE-90' -TC 'TC-unity_test/tests/test_b.py::test_state' -BD '状态转换错误'"]
  ]
}
```

### SetSkillUsage

用途：

- 验证并保存本阶段专用技能的当前证据；它不能根据模型声明创建或提升list/read或脚本执行证据，但可在真实list/read和当前`Check`通过后确认文本方法的`use: true`，或确认带非空reason的无适用对象`use: false`

适用场景：

- 当前阶段配置了 `skill_list`，需要满足默认强制要求，或实际使用了显式设为可选的阶段技能

需要提交的三个维度：

- `list`
  - 成功调用 `ListSkill` 后自动登记
- `read`
  - 成功通过 `ReadTextFile` 读取该技能的 `SKILL.md` 后自动登记
- `use`
  - 整次 `RunSkillScript` 全部成功后自动登记脚本路径；文本方法在list/read已登记且当前`Check`通过后，由`SetSkillUsage`登记为`true`；无适用对象分支由`SetSkillUsage`保持为`false`
- `reason`（仅`use: false`时必填）
  - 非空说明文本；当当前阶段没有Skill可处理的对象、因而无需运行脚本或修改产物时，用它记录已执行的无适用对象分支。`use: true`时不得填写；它不能替代list/read或当前`Check`

示意：

```json
{
  "unitytest/static-bug-analysis": {
    "list": true,
    "read": true,
    "use": false,
    "reason": "当前批次没有可分析的RTL源文件，已按Skill的黑盒分支完成且未运行脚本。"
  }
}
```

只有技能启用且当前stage实际配置了非空`skill_list`时，才检查该stage的Skill使用；未配置`skill_list`或列表为空时，不要求调用`SetSkillUsage`，`Check`和`Complete`也不执行Skill使用门禁。非空`skill_list`中任一技能未满足要求都会阻断`Complete`，除非该阶段显式设置`force_use_skill: false`。固定顺序是`ListSkill -> ReadTextFile(SKILL.md) -> 执行方法或无适用对象分支 -> Check -> SetSkillUsage -> Complete`。已应用文本方法或成功脚本调用时提交`use: true`；当前阶段没有可处理对象时，通过`Check`后提交`use: false`及非空`reason`，明确说明没有需要该Skill处理的对象。`use: false`不能跳过`ListSkill`、读取`SKILL.md`或当前`Check`，也不能制造Bug或其他产物。证据在产生时立即持久化，使用当前契约写入的证据可在同一阶段重启后恢复；格式不合法或版本不符的状态不会恢复。`general_skill_list`始终可选且不触发stage Skill使用门禁；技能整体禁用时，阶段Skill门禁不生效。

## 常见注意事项

- `SKILL.md` 开头必须直接是 YAML frontmatter，否则技能可能无法被识别
- 仅把技能目录放在仓库里不够，运行时还需要保持技能开启；不要使用 `--no-use-skill` 或在配置中设置 `skill.use_skill: false`
- 对于强制技能，只“知道有这个技能”不够，通常还必须实际读取并使用 `SKILL.md`
- `read` 的判定依赖读取工作区中 `skills/.../SKILL.md` 这份文件
- 如果技能文档要求必须通过 `RunSkillScript` 修改某类文件，就不应绕过该工具直接编辑
- `scripts/` 下的脚本文件不会自动加载为模型上下文，它们只是可被执行的脚本资源

## 编写建议

写一个好用的技能，建议至少做到：

- `description` 直接描述适用任务，不写得过泛
- `SKILL.md` 中明确给出执行顺序
- 对脚本参数格式给出可直接复用的示例
- 明确哪些文件允许直接改，哪些必须通过脚本改

## 推荐模板

```md
---
name: example-skill
description: 用固定模板生成测试文档，并通过脚本完成批量写入
metadata:
  category: template
---

# 技能目标

说明这个技能解决什么问题。

## 适用场景

- 场景 1
- 场景 2

## 执行步骤

1. 先做什么
2. 再做什么
3. 什么时候执行脚本

## 脚本使用

以如下参数记录信息:
`value1`:参数1的含义
`value2`:参数2的含义
使用 `RunSkillScript` 执行`record_result.py`脚本：

`["example/analysis","record_result.py","-FILE 'a.py:10-20' -BG 'BG-001'"]`

## 注意事项

- 哪些文件禁止直接编辑
- 哪些输出格式必须保持一致
- 脚本失败后如何修正参数并重试
```
