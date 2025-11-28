# 人机协同验证

UCAgent 支持在验证过程中进行人机协同，允许用户暂停 AI 执行，人工干预验证过程，然后继续 AI 执行。

## 为什么需要人机协同

在硬件验证的实际应用中，人机协同模式能够有效应对以下场景：

### AI 单次通过率较低的关键阶段

某些验证阶段（如规格文档编写、测试用例设计）对后续工作影响重大。AI 生成的内容可能存在理解偏差或细节错误，人工审核后再继续可以避免错误累积。

**典型场景：**

- 功能规格文档编写完成后，需要人工审核是否准确理解了设计意图。可参照[GenSpec 规范文档生成模式](../04_case/00_genspec.md)
- 测试用例设计完成后，需要确认是否覆盖了所有关键功能点

### AI 执行卡住需要人工解决

当 AI 遇到无法自动解决的问题时（如环境配置问题、工具错误），需要人工介入解决后再继续。

**典型场景：**

- 测试用例过于复杂，AI 无法编写出正确的用例
- 测试运行超时需要调整参数或修复代码错误
- 工具输出格式变化导致解析失败

## 协同工作流程

### 基本流程

```
AI 执行 → 阶段检查 → 人工审核/修复 → 标记完成 → 进入下一阶段 → 循环直到任务完成
```

### 详细操作步骤

#### 暂停 AI 执行

根据不同的使用模式选择暂停方式：

- **直接接入 LLM 模式**：按 `Ctrl+C` 暂停
- **Code Agent 协同模式**：根据 Agent 的暂停方式（如 Gemini-cli 使用 `Esc`）暂停

#### 查看当前状态

进入交互模式后，使用以下命令了解当前情况：

```bash
# 查看当前任务状态
status

# 查看当前阶段详细信息
task_detail

# 查看当前阶段的提示信息
current_tips

# 查看修改的文件
changed_files
```

#### 人工干预

根据实际需要进行以下操作：

**文件编辑：**

- 直接编辑 AI 生成的文件（规格文档、测试代码等）
- 修复语法错误或逻辑问题
- 补充遗漏的内容

**手动执行命令：**

- 调试测试用例
- 安装依赖或配置环境
- 运行特定的检查命令

**使用交互命令：**

```bash
# 手动调用工具检查当前阶段
tool_invoke Check

# 查看检查过程的标准输出
tool_invoke StdCheck -1

# 如果检查进程卡住，可以终止它
tool_invoke KillCheck
```

#### 标记阶段完成

确认问题已解决后，使用 `Complete` 工具标记当前阶段完成：

```bash
# 通过工具完成当前阶段
tool_invoke Complete

# 或使用 loop 命令让 AI 自己调用 Complete
loop "Please use Complete tool to finish current stage"
```

#### 继续 AI 执行

使用 `loop` 命令恢复 AI 执行，可选择性提供提示信息：

```bash
# 继续执行
loop

# 带提示信息继续执行
loop "I have fixed the test cases, please continue"

# 在 Code Agent 模式下，通过 Agent 的控制台输入提示
```

## 强制人工审核模式

### 设置必须人工审核的阶段

对于关键阶段，可以设置强制人工审核，AI 无法自动跳过该阶段：

```bash
# 设置特定阶段需要人工审核
hmcheck_set 2 true

# 设置所有阶段都需要人工审核
hmcheck_set all true

# 取消某阶段的人工审核要求
hmcheck_set 2 false

# 查看当前阶段的审核状态
hmcheck_cstat

# 列出所有需要人工审核的阶段
hmcheck_list
```

### 通过人工审核

当阶段设置为需要人工审核时（在状态栏显示 `*`），AI 完成阶段后会等待人工确认：

```bash
# 审核通过，允许进入下一阶段
hmcheck_pass "Reviewed and approved"

# 审核不通过，要求 AI 重新处理
hmcheck_fail "Need to fix the test coverage"
```

## 权限控制

通过设置文件写权限，可以控制 AI 是否可以编辑特定文件或目录：

```bash
# 查看当前读写权限配置
list_rw_paths

# 添加可写路径（允许 AI 编辑）
add_write_path unity_test/

# 添加禁止写入路径（保护文件不被 AI 修改）
add_un_write_path docs/

# 删除可写路径
del_write_path unity_test/

# 删除禁止写入路径
del_un_write_path docs/
```

**注意：** 权限控制适用于直接接入 LLM 模式或强制使用 UCAgent 文件工具时。

## 阶段管理命令

在人机协同过程中，可能需要在不同阶段间跳转：

```bash
# 跳过当前阶段
skip_stage 3

# 取消跳过某阶段
unskip_stage 3

# 通过工具返回上一个阶段
tool_invoke GoToStage 2
```

## 常用交互命令参考

| 命令                    | 功能                             | 用法示例                        |
| ----------------------- | -------------------------------- | ------------------------------- |
| `status`                | 查看任务整体状态和所有阶段       | `status`                        |
| `task_detail`           | 查看特定阶段的详细信息           | `task_detail 2`                 |
| `current_tips`          | 获取当前阶段的提示信息           | `current_tips`                  |
| `tool_invoke Check`     | 检查当前阶段是否满足要求         | `tool_invoke Check`             |
| `tool_invoke Complete`  | 标记当前阶段完成                 | `tool_invoke Complete`          |
| `tool_invoke StdCheck`  | 查看检查过程最后n行的输出（-1表示所有行）| `tool_invoke StdCheck -1` |
| `tool_invoke KillCheck` | 终止卡住的检查进程               | `tool_invoke KillCheck`         |
| `tool_invoke GoToStage` | 跳转到指定阶段                   | `tool_invoke GoToStage 2`       |
| `loop`                  | 继续 AI 执行，可一并给出提示词   | `loop "Fixed the issue"`        |
| `hmcheck_set`           | 设置某阶段是否需要审核           | `hmcheck_set 2 true`            |
| `hmcheck_pass`          | 通过人工审核，可一并给出提示词   | `hmcheck_pass "Approved"`       |
| `hmcheck_fail`          | 不通过人工审核，可一并给出提示词 | `hmcheck_fail "Need fixes"`     |
| `hmcheck_cstat`         | 查看当前阶段审核状态             | `hmcheck_cstat`                 |
| `hmcheck_list`          | 列出所有需要审核的阶段           | `hmcheck_list`                  |
| `changed_files`         | 查看最近 n 个已修改的文件        | `changed_files 10`              |
| `add_un_write_path`     | 禁止 AI 写入指定路径             | `add_un_write_path src/`        |
| `del_un_write_path`     | 解除写入禁止                     | `del_un_write_path src/`        |
| `skip_stage`            | 跳过指定阶段                     | `skip_stage 3`                  |
| `unskip_stage`          | 取消跳过阶段                     | `unskip_stage 3`                |
| `help`                  | 查看所有可用命令                 | `help`                          |
| `tool_list`             | 列出所有 AI 可用工具             | `tool_list`                     |
| `tui`                   | 进入 TUI 界面                    | `tui`                           |
| `q` / `quit`            | 退出 UCAgent                     | `quit`                          |

## 典型应用场景

### 场景 1：关键阶段主动审核

```bash
# 设置规格文档阶段必须人工审核
hmcheck_set 1 true

# AI 完成规格文档编写后会自动暂停
# 人工审核文档内容...

# 审核通过后继续
hmcheck_pass "Specification reviewed"
loop
```

### 场景 2：AI 执行失败后人工修复

```bash
# AI 执行过程中按 Ctrl+C 暂停

# 查看当前状态
status
current_tips

# 手动修改生成的代码文件
# vim unity_test/test_adder.py

# 手动运行测试验证修复
# pytest unity_test/test_adder.py

# 标记阶段完成
tool_invoke Complete

# 继续下一阶段
loop
```

### 场景 3：检查进程卡住

```bash
# AI 调用 Check 工具时卡住
# 按 Ctrl+C 暂停

# 查看检查输出（-1 表示查看所有行）
tool_invoke StdCheck lines=-1

# 终止卡住的进程
tool_invoke KillCheck

# 修复问题后重新检查
tool_invoke Check

# 如果通过则完成阶段
tool_invoke Complete
loop
```
