# Stage 06: strengthen_smoke_business_tool_tests

## 阶段目标

增强代表性 smoke 工具测试并重新验证。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/smoke_tool_selection.yaml`
- `Guide_Doc/tool_generation_guide.md`

## 详细执行步骤

1. 第1步：读取 {WFGEN_DIR}/smoke_tool_selection.yaml，并按其中路径读取实际 spec、工具和 direct runner 日志。
2. 第2步：根据所选工具的真实职责创建第二个边界测试夹具，不得假定输入是 Verilog、图片或文本。
3. 第3步：把第二个夹具路径追加到选择文件的 fixture_paths，并更新实际 tool_spec，新增 edge_case_test，expected.ok=true。
4. 第4步：更新 spec 后必须调用 `WorkflowToolGenerator(existing_policy='create_only')`，确认生成器对源码报告 skipped，并把新增 `edge_case_test` 追加到冻结测试基线。若生成器报告既有测试 missing/changed，必须恢复原测试，不得更新基线迁就改写。然后读取当前实现并直接补充边界处理。只有生成状态能够证明文件仍是未修改骨架时才允许 `refresh_scaffold`，人工实现过的业务源码禁止 `force_replace`。
5. 第4.1步：`basic_test` 与 `edge_case_test` 的成功结果都必须包含符合 spec 的有意义业务数据。禁止降低 `expected.ok`、删除既有失败用例、放宽预期字段、把真实失败改成成功回退，或用默认空值冒充增强完成。
6. 第5步：使用 Check 运行通用 generated tool checker，确认 basic_test 和 edge_case_test 两个测试都存在，并确认 make check_tool_specs、make check_tools、make test_tools、make check 全部通过。
7. 第6步：读取 .workflow/logs/tool_direct_run.log，确认 basic_test 和 edge_case_test 均为 PASS。
8. 第7步：使用 SetCurrentStageJournal 记录增强测试、重新生成和验证结果。
9. 第8步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: strengthen_smoke_business_tool_tests
status: passed
artifacts:
  - {WFGEN_DIR}/smoke_tool_selection.yaml
  - {TEST_WORKFLOW_ROOT}/config.yaml
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_specs
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_tests/cases
  - {TEST_WORKFLOW_ROOT}/tools
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `strengthen_smoke_business_tool_tests` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_generated_tool_strengthened_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 增强 spec 后原有业务逻辑消失 | 错误使用 `force_replace` 或旧版 `overwrite=true` 重建了通用框架 | 停止继续覆盖，从历史或当前变更恢复真实实现；后续固定使用 `create_only`，只有摘要匹配的纯骨架允许 `refresh_scaffold` |
| 配置任务已有新规则，但 ReadTextFile 仍读到旧阶段指导 | 父 Makefile 只初始化过 workspace 的 Guide_Doc，没有在后续启动同步维护者版本 | 检查 `prepare_input` 是否把 `GUIDE_DOC_SOURCE_DIR` 复制到 `WORKSPACE_GUIDE_DOC_DIR`；修复同步逻辑并重启，再读取指导确认新增步骤真实可见，禁止直接改 workspace 副本 |
| 写入工具报告“文件已存在”或精确编辑后出现重复 import | 对已有文件继续使用 create/write 模式，或未读取最新内容就重复应用编辑 | 创建前先用 GetFileInfo/PathList 确认文件状态；已有文本使用 `ReplaceStringInFile` 或带精确范围的编辑，编辑后立即回读相关区域。不得通过删除真实文件再重建来规避模式错误 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
