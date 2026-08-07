# Stage 05: implement_smoke_business_tool

## 阶段目标

调用工具生成器实现、注册并验证代表性 smoke 工具。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/smoke_tool_selection.yaml`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `Guide_Doc/tool_generation_guide.md`

## 详细执行步骤

1. 第1步：读取 {WFGEN_DIR}/smoke_tool_selection.yaml，再按其中 spec_path 和 fixture_paths 读取实际 spec 与测试夹具。
2. 第2步：调用 WorkflowToolGenerator(workflow_root='{TEST_WORKFLOW_ROOT}', mode='from_spec', spec_paths=[选择文件中的 spec_path], existing_policy='create_only', update_config=true)。必须先由生成器创建并注册工具，禁止绕过生成器从零创建源码。若实现已经存在，生成器必须保留源码并报告 skipped，禁止切换 force_replace。
3. 第2.1步：`from_spec` 只负责生成符合 spec 的安全框架。读取生成源码；若 `data_required_keys` 仍由 `_default_value` 或其他空默认值填充，必须使用 `EditTextFile` 或 `ReplaceStringInFile` 完善这个已生成文件的真实业务逻辑。不得修改正向用例的 `expected.ok`、删除失败用例或降低输出契约来迁就空壳。
4. 第3步：从 spec.entry.file 读取生成的工具，确认它是普通 Python 类，不绑定 MCP、LangChain 或 UCAgent。
5. 第4步：确认 run(path) 安全解析相对路径，禁止绝对路径和 ..，并返回统一结构 ok/data/errors/warnings/meta。
6. 第5步：确认工具正确实现了 spec 中声明的业务逻辑。
7. 第6步：确认 {TEST_WORKFLOW_ROOT}/config.yaml 已把选择文件中的工具注册到 tools.GeneratedTools，且保留 tools.RunTestCases.test_dir。
8. 第7步：使用 Check 验证业务工具完整生成，确认 make check_tool_specs、make check_tools、make test_tools、make check 全部通过。
9. 第8步：使用 ReadTextFile 查看 .workflow/logs/tool_direct_run.log，确认 basic_test 为 PASS。
10. 第9步：使用 SetCurrentStageJournal 记录工具生成器返回信息、业务工具实现、注册和测试结果。
11. 第10步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: implement_smoke_business_tool
status: passed
artifacts:
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

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `implement_smoke_business_tool` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_generated_tool_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `from_spec` 生成的工具只返回默认值 | 误把框架生成当成业务实现完成 | 保留生成器产出的路径安全、schema 和统一返回结构，使用受控文件编辑工具补齐生成文件中的实际解析或执行逻辑，再运行 direct 与 MCP 测试 |
| `RunBashCommand(cwd='workflow')` 后 Make 仍在父 workspace 执行 | 当前运行工具没有按预期应用 `cwd`，命令因此报告 `No rule to make target` | 不修改 Makefile 目标或业务产物；使用 `make -C workflow <targets>` 显式指定目录，并以返回码和 stdout 作为证据 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
