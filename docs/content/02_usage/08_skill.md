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
- 只有阶段中显式配置到 `skill_list` 的技能，才会被强制要求使用

## 为什么使用技能

- 稳定性更高：相比于工作流,技能能够对阶段行为进行更为详细的描述,以及通过定制化脚本,稳定执行流程较为固定的复杂操作,提高文档编辑相关操作的正确性
- 上下文更省：通过`渐进式加载`机制,只有在需要时才加载完整的技能信息
- 复用性更强：同一个技能目录可以在多个任务中重复使用
- 可约束执行：对于必须遵循固定步骤的任务，可以通过阶段配置强制使用技能

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
- `scripts/` 下除 `__init__.py` 外的文件会被当作可执行脚本列出，供 `RunSkillScript` 使用

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

这里写技能目标、执行步骤、注意事项、脚本说明等内容。
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

当完成全部分析后，使用 `RunSkillScript` 工具执行`recordbug.py`脚本,命令行如下：
`python3 recordbug.py -FILE 'FILE' -BG 'BG' -BD 'BD'`
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

### 命令行开启技能

可通过命令行参数开启技能功能：

```bash
--use-skill
```

含义：

- 启用技能机制
- 把 UCAgent 默认技能拷贝到当前工作区的 `.ucagent/skills/` 目录下

也可以额外指定一个技能目录：

```bash
--use-skill=/path/to/extra-skills
```

含义：

- 启用技能机制
- 拷贝默认技能
- 再额外拷贝指定路径下的技能到工作区 `.ucagent/skills/` 目录

如果未声明 `--use-skill`，则技能功能默认关闭。

## 技能在工作区中的位置

启用后，技能会被复制到工作区下的`.ucagent/skills/`目录中,后续 `ListSkill`、`ReadTextFile`、`RunSkillScript` 看到的技能，都是以工作区中的这份副本为准。

## 阶段级技能配置

可在工作流阶段配置 `skill_list`，声明本阶段必须使用的技能。

示例：

```yaml
stages:
  - name: example-stage
    skill_list:
      - "static-bug-analysis"
```

含义：

- 当前阶段必须使用 `static-bug-analysis`
- UCAgent 在完成阶段前，不仅要使用该技能，还要通过技能使用记录校验

如果阶段配置了 `skill_list`，但启动时没有开启 `--use-skill`，则会报错。

## 技能使用流程

推荐按以下顺序理解和使用技能：

1. 启动 UCAgent 时开启 `--use-skill`
2. 通过 `ListSkill` 查看当前可用技能
3. 使用 `ReadTextFile` 读取目标技能的 `SKILL.md`
4. 按 `SKILL.md` 中的方法完成任务
5. 如技能要求脚本，使用 `RunSkillScript` 执行对应命令
6. 若当前阶段配置了 `skill_list`，在阶段完成前使用 `SetSkillUsage` 检查并设置技能使用情况

对于强制技能，通常至少要满足三件事：

- 已通过 `ListSkill` 列出
- 已通过 `ReadTextFile` 读取对应 `SKILL.md`
- 实际执行过程已遵循技能步骤或调用了技能指定脚本

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

- `commands` 为字符串数组
- 支持一次执行多条命令
- 按顺序逐条执行
- 某条失败后直接返回错误，不会继续后续命令

示意：

```json
{
  "commands": [
    "python3 skills/static-bug-analysis/scripts/recordbug.py -FILE 'a.py:10-20' -BG 'BG-STATIC-001-NULL'",
    "python3 skills/static-bug-analysis/scripts/recordbug.py -FILE 'b.py:5-9' -BG 'BG-STATIC-002-STATE'"
  ]
}
```

### SetSkillUsage

用途：

- 在阶段完成前，设置并校验本阶段的技能使用情况

适用场景：

- 当前阶段配置了 `skill_list`

需要提交的三个维度：

- `list`
  - 是否已通过 `ListSkill` 看到该技能
- `read`
  - 是否已通过 `ReadTextFile` 读取该技能的 `SKILL.md`
- `use`
  - 是否实际按技能说明执行了任务

示意：

```json
{
  "static-bug-analysis": {
    "list": true,
    "read": true,
    "use": true
  }
}
```

如果 `skill_list` 中任一技能未满足这三项要求，阶段不能正常通过。

## 常见注意事项

- `SKILL.md` 开头必须直接是 YAML frontmatter，否则技能可能无法被识别
- 仅把技能目录放在仓库里不够，运行时还需要开启 `--use-skill`
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
使用 `RunSkillScript` 执行`generate.py`脚本：

`python3 skills/example-skill/scripts/generate.py -ARG1 'value1' -ARG2 'value2'`

## 注意事项

- 哪些文件禁止直接编辑
- 哪些输出格式必须保持一致
- 脚本失败后如何修正参数并重试
```
