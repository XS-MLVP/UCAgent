# Stage 14: run_full_tool_test_suite

## 阶段目标

执行全部工具静态、direct 和真实 MCP 测试。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`

## 详细执行步骤

1. 运行 make check_tool_specs、make check_tools、make test_tools 和 make test_mcp。
2. 【硬性约束】本阶段严禁在 {TEST_WORKFLOW_ROOT} 下启动任何 TUI 会话（禁止 make run_tui、make run、make tmux 或任何 --tui 参数）。子 UCAgent 必须由 make test_mcp 以 headless 模式启动。TUI 会造成 Ctrl+C 冲突和文件权限残留。
3. 禁止重写、替换或手写 {TEST_WORKFLOW_ROOT}/.workflow/tool_tests/run_mcp_tests.py；该文件必须保持由 WFB mcp_tool_test_runner 模板生成的 streamable HTTP 客户端实现，必须使用 mcp.client.streamable_http.streamablehttp_client 和 mcp.ClientSession。若 make test_mcp 失败，只能修工具 spec、工具实现、adapter 注册或环境端口问题；不得改成 urllib、JSON-RPC POST /mcp、SSE 或自建 mcp_sse_server.py。
4. 测试命令完成后再读取本阶段新产生的 direct 和 MCP 日志汇总、每个工具的 PASS/FAIL 行和必要失败片段，逐个确认 requirements_manifest.required_tools 被发现并真实调用成功；日志不是阶段开始前保证存在的 reference，不能预先写入 reference_files，也不能只看命令退出码。不得为了复核通过项再全文读取 fixture、工具源码、runner、Makefile 或旧日志。
5. 确认没有残留子 UCAgent、端口占用和只读权限，然后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: run_full_tool_test_suite
status: passed
artifacts:
  - 本阶段无新增文件，需记录实际检查证据
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `run_full_tool_test_suite` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `full_mcp_tool_integration_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 残留进程检查把外层 workflow_builder、tmux、IDE 端口判成子 UCAgent | 使用 `pgrep -af ucagent` 或只按端口号做宽泛匹配 | 只匹配包含生成工作流根路径、MCP 测试目录或该次 run_id 的进程；端口必须结合 `ss -ltnp` 的 PID/命令归属判断。外层监督进程不得计入子流程残留 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
