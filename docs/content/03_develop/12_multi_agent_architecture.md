
# 多 Agent 开发架构

本页面向维护调度、授权、后端和验收代码的开发者。用户启动和工具调用契约以 [多 Agent](../02_usage/11_multi_agent.md) 与 [Global Agent](../02_usage/13_global_agent.md) 为准；通用分层见 [架构与工作原理](02_architecture.md)。

## 角色、进程与源码所有权

```text
Global 宿主：请求队列、目录、Super 生命周期和结果验收
  └─ Super 子进程：一个工作流、StageManager、规划和委派
       └─ Sub 执行会话：授权范围、角色工具、后端与提交
```

这是职责树，不是“一角色必有一个 Python 进程”。Super 是独立任务进程；Sub 的会话由 Super 调度，命令行后端再启动各自的 CLI 进程。LangChain 与命令行后端使用同一授权/验收边界，不以自然语言承诺代替隔离。

| 代码位置 | 所有权 |
| --- | --- |
| `ucagent/core/multi_agent/mode.py` | 公开 single/multi 与内部 Super 身份校验 |
| `ucagent/core/multi_agent/global_agent/` | 工作流目录、启动契约、角色工具、产物回执验证 |
| `ucagent/runtime/agent_sessions.py` | Super 的准备、调度、attempt、资源和终态处理 |
| `ucagent/runtime/agent_events.py` | 事件保存、Global 输入及结果通知的串行交付 |
| `ucagent/interfaces/server/super_launcher.py` | 子进程启动/回收、输出和远程视图适配 |
| `ucagent/core/multi_agent/super_agent/service.py` | 计划、Sub 调度、取消、执行结束后的验收 |
| `ucagent/core/multi_agent/super_agent/supervisor.py` | StageDriver、阶段授权 lease、独占写入与 step token |
| `ucagent/core/multi_agent/super_agent/worker.py` | Sub 工具绑定、输入输出边界和提交前条件 |
| `ucagent/core/agent/session.py` / `ucagent/core/backends/cmdline.py` | 后端执行会话、客户端端点/配置/进程生命周期 |

应用层连接这些现有组件并注入端点和启动能力；核心模块不导入运行层或界面层来创建网络服务。公开 multi 的跨工作流选择属于 Global；`core/workflow/` 中的内部接力引擎不参与这条公开启动链，见 [工作流接力](../02_usage/12_workflow_handoff.md)。

## 多层状态不能合并为一个 done

| 层次 | 通过或结束的意义 | 尚不能推出 |
| --- | --- | --- |
| BatchTask | 当前批产物通过，可推进下一批 | 全阶段完成 |
| Sub 提交 | 结果已提交，准备停止当前执行 | 子进程/工具已退出、产物最终通过 |
| Sub 验证 | 授权输入输出检查通过 | 整个授权范围的最终门禁通过 |
| StageDriver 收尾 | 所有写入者停止后，授权范围通过适用验收 | Super 进程已退出或 Global 已接收结果 |
| Super 回执 | 框架记录工作流完成及产物摘要 | Global 已复核身份、attempt、退出结果和文件 |
| Global 请求完成 | 子任务终态与结果通知处理结束 | 进程必须退出；还取决于退出选项 |

UI 快照、调度状态和业务回执应保留各自含义，不通过改名或复制状态字段让它们“看起来一致”。用户侧证据位置与退出条件见 [Global Agent](../02_usage/13_global_agent.md)。

## 授权与阶段推进

StageDriver 为当前委派建立 lease，记录授权根、子阶段序列和预期阶段位置。它在独占所有权下调用原有 StageManager；迟到请求不能越过失效授权或已经改变的当前阶段。

- `Check` 在当前授权步骤执行原有检查和 BatchTask 转换。正常下一批继续使用同一 Sub，不返回 Super 重新规划。
- `CompleteSubStage` 只能推进当前授权后代。调用必须携带最新 `step_token`；返回后按新的 tips/token 继续，旧 token 返回 `STALE_STEP_TOKEN`，不能盲目重放。
- `step_token` 用于子阶段授权，不等于 HTTP/人工审核使用的 `control_revision`。二者解决不同范围的过期写入问题，不能互换。
- 单阶段 `ready` 提交要求当前检查有效、所有批次通过、适用 Skill 证据与 journal 就绪。可能改变业务结果的工具调用会使此前检查凭据失效，需要重新 `Check`。
- 子树提交要求授权子阶段全部结束；文件任务不获得阶段工具，按显式输入/输出与产物契约验证。`needs_attention` 可以报告未完成工作，但不绕过成功验收。

工具是否提供、由谁调用，以 [角色工具矩阵](../02_usage/11_multi_agent.md#role-tool-matrix) 为准。不要为了统一工具名而重新给 Sub 或监督角色暴露根阶段 `Complete`。

## 提交、执行退出与最终验收

Sub 返回结果后，执行线程仍负责关闭工具与后端、检查受保护输入以及验证/发布声明产物。构造中、执行中、已提交未退出和取消未退出都保留容量占用。调度器不能因为收到提交文本就提前释放名额或启动冲突写入者。

全部写入者停止后，`_accept_scope` 重新计算产物摘要，再调用 `StageDriver.finish`。普通根阶段执行原有最终门禁；纯分组根在授权后代均完成后收拢范围，不凭空增加父 Checker。两种分支对应不同阶段结构，而不是两套业务正确性标准。

Global 还要在 Super 结束时验证框架回执中的身份、工作流、attempt、阶段和产物。进程零退出码、模型“完成”回复或单独存在的回执均不充分。运行记录不是供用户手工补写的恢复接口。

## 取消、恢复与安全边界

取消请求、后端停止、工具 drain 和阶段授权释放是不同事件。恢复规划必须基于最新批次状态；预算累计和已完成批次不能因为换 plan/task 名称而被重置。存活暂停任务恢复与已结束 Super 的新 attempt 重试是两条路径。

阶段/子树任务继承工作流写策略；拆分文件任务使用声明输入/输出的私有副本并在验证后发布产物。目录隔离、只读约束和 MCP 授权不等于操作系统安全沙箱；外部 CLI 原生能力须独立受控。端点凭据和生成配置不能写入公开诊断。

## 修改后的验证重点

- 授权过期、错误阶段、旧 token、重复/迟到提交不能推进阶段。
- 多批任务保持同一 Sub；失败恢复读取最新批次，提交过早不会结束可继续修复的会话。
- 子树与单阶段、纯分组与带门禁根、文件任务分别覆盖成功和拒绝路径。
- 提交后产物变更、受保护输入变更、缺失 journal/Skill、伪造回执均不能通过。
- 取消过程中不提前释放容量；所有写入结束后才收尾，CLI 不回报 session ID 时不恢复到不相关会话。
- Global 的准备失败、重试 attempt、回执身份/摘要错误、结果通知和自动退出分别验证。

确定性离线后端适合验证调度与协议，不替代真实模型、MCP 客户端能力限制和 EDA 工具的集成验证。文档中的公共标识符和启动示例也应随契约测试更新。

文档回归分两层：`tests/test_docs_contracts.py` 在普通单测中验证启动示例、Make 展开命令、示例导入与中英文标识符；`tests/test_docs_i18n.py` 在安装文档依赖后验证实际站点的双语页面、导航和锚点。两者不能相互替代；修改导航或页面后还应执行 `mkdocs build -f mkdocs.yml --strict`。根包导入的分层约束由 `tests/test_dependency_boundaries.py` 检查。
