# 人机协同验证

UCAgent 支持在验证过程中进行人机协同，允许用户暂停 AI 执行，人工干预验证过程，然后继续 AI 执行。本文档涵盖命令行/TUI 模式与 Web Master 模式两种人机交互方式。

## 为什么需要人机协同

在硬件验证的实际应用中，人机协同模式能够有效应对以下场景：

### AI 单次通过率较低的关键阶段

某些验证阶段（如规格文档编写、测试用例设计）对后续工作影响重大。AI 生成的内容可能存在理解偏差或细节错误，人工审核后再继续可以避免错误累积。

典型场景：
- 功能规格文档编写完成后，需要人工审核是否准确理解了设计意图。可参照 [GenSpec 规范文档生成模式](../04_case/00_genspec.md)
- 测试用例设计完成后，需要确认是否覆盖了所有关键功能点

### AI 执行卡住需要人工解决

当 AI 遇到无法自动解决的问题时（如环境配置问题、工具错误），需要人工介入解决后再继续。

典型场景：
- 测试用例过于复杂，AI 无法编写出正确的用例
- 测试运行超时需要调整参数或修复代码错误
- 工具输出格式变化导致解析失败

## 人机协同模式总览

UCAgent 提供两种人机协同模式，用户可根据使用场景选择：

### 模式一：命令行 / TUI 模式

适用于本地快速调试、命令细粒度操作。通过终端命令直接与 Agent 交互，支持完整的命令集操作。

### 模式二：Web Master 模式

适用于集中管理、多任务运维、远程协作。提供可视化界面，支持阶段批量控制、产物复盘、多任务管理等高级功能。

## 命令行 / TUI 模式人机协同

### 基本流程

AI 执行 → 阶段检查 → 人工审核/修复 → 标记完成 → 进入下一阶段 → 循环直到任务完成

### 详细操作步骤

#### 暂停 AI 执行

根据不同的使用模式选择暂停方式：

- 直接接入 LLM 模式：按 `Ctrl+C` 暂停
- Code Agent 协同模式：根据 Agent 的暂停方式（如 Gemini-cli 使用 `Esc`）暂停

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

# 查看检查过程的标准输出（lines=-1 表示所有行）
tool_invoke StdCheck lines=-1

# 如果检查进程卡住，可以终止它
tool_invoke KillCheck
```

#### 标记阶段完成

确认问题已解决后，标记当前阶段完成：

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

### 强制人工审核模式

#### 设置必须人工审核的阶段

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

#### 通过人工审核

当阶段设置为需要人工审核时（在状态栏显示 `*`），AI 完成阶段后会等待人工确认：

```bash
# 审核通过，允许进入下一阶段
hmcheck_pass "Reviewed and approved"

# 审核不通过，要求 AI 重新处理
hmcheck_fail "Need to fix the test coverage"
```

### 权限控制

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

> 注意：权限控制适用于直接接入 LLM 模式或强制使用 UCAgent 文件工具时。

### 阶段管理命令

在人机协同过程中，可能需要在不同阶段间跳转：

```bash
# 跳过当前阶段
skip_stage 3

# 取消跳过某阶段
unskip_stage 3

# 通过工具返回上一个阶段
tool_invoke GoToStage 2
```

### 常用交互命令参考

| 命令 | 功能 | 用法示例 |
|------|------|----------|
| `status` | 查看任务整体状态和所有阶段 | `status` |
| `task_detail` | 查看特定阶段的详细信息 | `task_detail 2` |
| `current_tips` | 获取当前阶段的提示信息 | `current_tips` |
| `tool_invoke Check` | 检查当前阶段是否满足要求 | `tool_invoke Check` |
| `tool_invoke Complete` | 标记当前阶段完成 | `tool_invoke Complete` |
| `tool_invoke StdCheck` | 查看检查过程输出（lines=-1 表示所有行） | `tool_invoke StdCheck lines=-1` |
| `tool_invoke KillCheck` | 终止卡住的检查进程 | `tool_invoke KillCheck` |
| `tool_invoke GoToStage` | 跳转到指定阶段 | `tool_invoke GoToStage 2` |
| `loop` | 继续 AI 执行 | `loop "Fixed the issue"` |
| `hmcheck_set` | 设置某阶段是否需要审核 | `hmcheck_set 2 true` |
| `hmcheck_pass` | 通过人工审核 | `hmcheck_pass "Approved"` |
| `hmcheck_fail` | 不通过人工审核 | `hmcheck_fail "Need fixes"` |
| `hmcheck_cstat` | 查看当前阶段审核状态 | `hmcheck_cstat` |
| `hmcheck_list` | 列出所有需要审核的阶段 | `hmcheck_list` |
| `changed_files` | 查看最近修改的文件 | `changed_files 10` |
| `tool_list` | 列出所有 AI 可用工具 | `tool_list` |
| `add_un_write_path` | 禁止 AI 写入指定路径 | `add_un_write_path src/` |
| `del_un_write_path` | 解除写入禁止 | `del_un_write_path src/` |
| `skip_stage` | 跳过指定阶段 | `skip_stage 3` |
| `unskip_stage` | 取消跳过阶段 | `unskip_stage 3` |
| `help` | 查看所有可用命令 | `help` |
| `tui` | 进入 TUI 界面 | `tui` |
| `q / quit` | 退出 UCAgent | `quit` |

## Web Master 模式人机协同

所有 TUI 终端命令全部封装为页面可视化控件，一一对应等价关系：

1. **HM 勾选框** = `hmcheck_set` 强制人工审核开关
2. **LPass/LFail 按钮** = `hmcheck_pass` / `hmcheck_fail` 审核操作
3. **Skip 复选框** = `skip_stage` / `unskip_stage` 阶段跳过
4. **内置 Check 终止按钮** = `tool_invoke Check` / `KillCheck`
5. **树形阶段列表** = `status` / `task_detail` 状态查询
6. **Web Terminal** = 完整 TUI 命令输入窗口（兼容高级自定义指令）

### 典型使用场景

1. 关键规格文档生成后：页面勾选 HM 强制审核，核对无误点击 LPass 放行
2. 测试用例校验卡死：页面一键终止检查，修改文件后重新校验
3. 多阶段批量审核：多选任务节点，统一执行 Pass/Skip 批量操作

### 两种协同模式选用建议

1. 纯命令行调试、自动化脚本场景：使用 TUI 原生指令
2. 新手、团队协作、可视化复盘场景：优先 Master Web 按钮操作

> 更多 Master Web 模式的部署与运维问题，参考 [Web Master 模式文档](./07_web_master.md)。

## 典型应用场景

### 场景 1：关键阶段主动审核

适用情况：规格文档、测试用例设计等关键阶段，需要人工确认质量后再继续。

操作步骤：
1. 设置规格文档阶段必须人工审核：`hmcheck_set 1 true`
2. AI 完成规格文档编写后自动暂停
3. 人工审核文档内容（Web 模式可直接查看文件与 Diff）
4. 审核通过后继续：`hmcheck_pass "Specification reviewed"` + `loop`

### 场景 2：AI 执行失败后人工修复

适用情况：AI 生成代码有错误、测试不通过，需要人工介入修复。

操作步骤：
1. AI 执行过程中按 `Ctrl+C` 暂停（或 Web 端中断）
2. 查看当前状态：`status` / `current_tips`
3. 手动修改生成的代码文件，例如：`vim unity_test/test_adder.py`
4. 手动运行测试验证修复，例如：`pytest unity_test/test_adder.py`
5. 标记阶段完成：`tool_invoke Complete`
6. 继续下一阶段：`loop`

### 场景 3：检查进程卡住

适用情况：AI 调用 Check 工具时进程无响应，需要人工干预。

操作步骤：
1. AI 调用 Check 工具时卡住，按 `Ctrl+C` 暂停
2. 查看检查输出：`tool_invoke StdCheck lines=-1`
3. 终止卡住的进程：`tool_invoke KillCheck`
4. 修复问题后重新检查：`tool_invoke Check`
5. 如果通过则完成阶段：`tool_invoke Complete` + `loop`

### 场景 4：多任务批量管理（Web Master 专属）

适用情况：同时管理多个验证任务，需要批量设置策略、监控进度。

操作步骤：
1. 在 Dashboard 查看所有 Agent 状态
2. 进入 Task 页面筛选运行中任务
3. 进入 Agent 页面批量设置 HM/Skip 策略
4. 对失败任务逐一进入 Diff 视图复盘

## FAQ 常见问题

**Q1：什么时候用 TUI，什么时候用 Web？**

A：TUI 适合本地快速调试、命令细粒度操作；Web 适合集中管理、多任务运维、远程协作。

**Q2：LF（LLM Fail）概率性报错是什么原因？**

A：LF 评审是大模型语义校验，本身具有概率性。同一文档不同轮次推理时，模型关注点、宽松程度可能波动。解决方案：
1. 强化文档内容，脱离临界质量区间
2. 开启人工审核（HM），由人工把关
3. 调整 LLM temperature 参数降低随机性

> 更多 Master Web 部署与运维相关问题（如编译成功但启动失败、公网部署注意事项等），参考 [Web Master 模式文档](./07_web_master.md)。
