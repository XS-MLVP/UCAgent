# Stage 08: verify_generated_tools_through_mcp

## 阶段目标

由当前构建 Agent 启动子 UCAgent，并通过真实 MCP 调用验证基础生成工具。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `Guide_Doc/tool_generation_guide.md`
- `{TEST_WORKFLOW_ROOT}/.workflow/tool_tests/run_mcp_tests.py`
- `{TEST_WORKFLOW_ROOT}/tools/mcp_adapters.py`
- `{TEST_WORKFLOW_ROOT}/Makefile`

## 详细执行步骤

1. 第1步：使用 ReadTextFile 读取 Guide_Doc/tool_generation_guide.md 中的 MCP 集成测试操作协议，以及 {TEST_WORKFLOW_ROOT}/.workflow/tool_tests/run_mcp_tests.py 和 {TEST_WORKFLOW_ROOT}/tools/mcp_adapters.py。
2. 第1.1步：复查 tools/mcp_adapters.py 的返回协议。只允许 _run 返回 JSON 字符串，禁止覆盖 BaseTool.run； 直接 UCAgent 运行依赖 BaseTool.run 自动生成 ToolMessage，MCP 测试依赖该 ToolMessage 的 text 内容解析 JSON。
3. 第2步：确认测试职责属于当前构建 Agent：必须验证工具后再交付给未来运行生成工作流的 Agent，不能把验证责任留给下一层。
4. 第2.1步【硬性约束】：本阶段严禁在 {TEST_WORKFLOW_ROOT} 下启动任何 TUI 会话（禁止 make run_tui、make run、make tmux 或任何 --tui 参数）。子 UCAgent 必须由 Check 工具或 make test_mcp 以 headless 模式启动。在子工作流中开 TUI 会导致 Ctrl+C 冲突和文件权限残留，直接造成 checker 失败。
5. 第3步：使用 Check 工具触发本阶段的 checker（checker 内部会自动执行 make test_mcp，启动子 UCAgent MCP Server 并完成 list_tools 和 call_tool 验证）。如果 Check 不可用，才允许手动运行 make test_mcp，但仍禁止 TUI。
6. 第4步：使用 ReadTextFile 读取 {TEST_WORKFLOW_ROOT}/output/mcp_test_result.log，确认 list_tools 以及 config.yaml 中当前所有启用的 GeneratedTools 均有对应的 MCP call PASS；不得写死工具数量或适配器类名。
7. 第5步：使用 ReadTextFile 读取 {TEST_WORKFLOW_ROOT}/.workflow/logs/tool_mcp_run.log，确认请求确实进入子 UCAgent，并确认子 UCAgent 通过 q 正常退出且恢复文件权限。
8. 第6步：MCP 测试完成后再次运行 make check，确认没有残留只读权限、端口占用或运行中子 UCAgent。
9. 第7步：如果测试失败，必须根据两个日志修复 adapter、注册、启动参数或工具实现，然后重新运行 Check（或 make test_mcp）和 make check，直到通过。
10. 第8步：根据真实 direct/MCP 返回和日志创建 `{WFGEN_DIR}/mcp_baseline_evidence.yaml`，至少记录工具名、direct 结果、MCP 结果、日志路径、失败摘要和生成时间。后续阶段只引用该稳定摘要，不把 Checker 临时日志声明成 reference。
11. 第9步：使用 SetCurrentStageJournal 记录 MCP 工具发现、全部当前启用工具调用、退出清理和测试后 make check 的结果。
12. 第10步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: verify_generated_tools_through_mcp
status: passed
artifacts:
  - {WFGEN_DIR}/mcp_baseline_evidence.yaml
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `verify_generated_tools_through_mcp` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_mcp_tool_integration_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
