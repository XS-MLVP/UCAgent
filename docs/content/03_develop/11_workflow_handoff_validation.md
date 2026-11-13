
# 工作流接力验证记录

日期：2026-11-13。对应 H1–H5 实现；用户原有 `config.yaml` 修改保留，工作树未提交。使用方法和实现边界见[工作流接力](../02_usage/12_workflow_handoff.md)。

## 实施批次

| 批次 | 已实现内容 | 验证位置 |
| --- | --- | --- |
| H1 | 候选元数据、严格策略、精确输入映射、独立配置继承、声明与活动注册表分离 | `tests/test_workflow_contracts.py`；插件回归 |
| H2 | 同一 Super 的独立交接回合、决策工具、run/token 权限、累计预算、业务验收门槛 | `tests/test_workflow_decisions.py`；multi-agent 回归 |
| H3 | 被动交接执行器、完整后继实例工厂、ready/commit/retire/activate 屏障、失败保留 A | `tests/test_workflow_runtime.py`；Host、backend、初始化回归 |
| H4 | 原子链记录、独占锁、输入快照、配置/源码指纹、检查点恢复、应用级控制端点和旧请求栅栏 | `tests/test_workflow_checkpoint.py`；恢复场景、HTTP 和浏览器回归 |
| H5 | 两个独立本地插件、真实 Agent/Checker 闭环、真实 CLI/MCP 传输、实际模型自测 | `tests/test_workflow_relay.py`；下方在线证据 |

## 自动化结果

- 受影响框架的定向回归：**315 passed，1 skipped**。覆盖工作流接力、multi-agent、worker 上下文、Host/关闭、初始化、操作调度、插件、CLI sessions、cmdline backend、依赖方向、HTTP 控制和运行时文本。跳过项是默认不联网的真实模型自测，已经单独启用执行。
- 最终功能、MCP 同回合重放、TUI、显示与 Host 补充验证：**91 passed，1 skipped**。
- 配置加载、包布局、工具隔离与应用入口补充回归：**60 passed，1 skipped**。
- 公共 HTTP 在途写入收拢和交接期间拒绝业务写入的最终回归：**38 passed，1 skipped**。以上测试集合存在重叠，不累计宣称为不同用例总数。
- 浏览器：`tests/test_workflow_control.js` 与现有 `tests/test_dashboard_stage_view.js` 均通过。验证写请求携带原 run 身份，后台轮询发现 B 后不能把旧编辑提交给 B。
- 全部修改/新增 Python 编译、修改 YAML 解析及 `git diff --check` 通过。
- 当前环境没有 MkDocs 依赖，因此未执行 strict 文档构建；未为此安装或改动依赖。

离线测试使用可控模型，但生产 Agent 构造、插件加载器、Sub 工具、Checker 和交接执行器保持真实。CLI 测试实际启动子进程并使用会话 MCP；它验证传输和生命周期，不作为真实模型推理的替代。

成功路径同时运行“完成加一结果”与“只生成 payload”两种目标。后一目标在 A 结束，没有 B，证明运行时没有把 A → B 写死。

故障覆盖包括：非法策略/路径/输入、未声明源文件、验收后或接受请求后产物变化、缺少阶段产物、业务验收失败、过期 token、同 token 冲突、重复请求、预算耗尽、候选初始化失败、ready 超时、提交后暂停、检查点写失败、锁冲突、配置变动及旧 HTTP 请求。恢复覆盖 accepted、ready、committed 和 activated；已提交后继 ID 不变，A 的产物修改时间不变。

## 真实模型证据

单独运行：

```bash
UCAGENT_RELAY_ONLINE=1 .venv/bin/python -m pytest -q tests/test_workflow_relay.py::test_configured_real_model_relay --basetemp=/tmp/ucagent-relay-evidence-final
```

结果：**1 passed in 49.44s**。使用当前配置的实际模型连接，未替换模型决策。完整保留的临时目录为 `/tmp/ucagent-relay-evidence-final/test_configured_real_model_rel0/`。经过字段筛选、无凭据和决策 token 的结构化记录随文档保存：[workflow_handoff_evidence.json](workflow_handoff_evidence.json)。

| 项目 | 实测结果 |
| --- | --- |
| 宿主 PID | `4056519`，初始 run 与后继激活事件一致 |
| A | `relay-source:produce`；真实委派、Checker 验收完成 |
| B | `relay-sink:consume`；新工作区、独立 Super/Sub 会话，真实委派、Checker 验收完成 |
| A Super session | `f37ea2d0c0c64698b3baf5b69db9fb38` |
| B Super session | `43c4f654ca0e48bda36a416421600170` |
| A Sub session | `e7528c8422304d1da60b47b9defabae4` |
| B Sub session | `79553e4393f94ecc9018e7d1d94d7b56` |
| A 决策 | 实际 `RequestNextWorkflow` 被接受 |
| 交接顺序 | candidate_ready → handoff_committed → source_retired → successor_activated → B 的 workflow_plan_submitted |
| B 决策 | 实际 `CompleteWorkflowChain` 被接受 |
| 最终状态 | `completed`、`quiescent=true`；两个 run 均 `all_completed=true` |
| 最终结果 | `value=8` |
| 输入 SHA-256 | `1b58b6620fe6c9f8b3ba5427f71e14357f7810fed05cbf3fe5a10a10450ab5d7`，与结果 `source_sha256` 一致 |

没有凭两个小插件宣布生产 DUT/EDA 工作流已经通过接力验证。跨 backend、共享可写工作区、并行分支、完整 Sub 队列恢复和无法确认旧进程状态的硬崩溃自动恢复仍不支持。后者会拒绝启动，保留检查点供操作员核对。
