# Stage 12: design_all_business_tool_specs

## 阶段目标

为需求清单中的全部业务工具设计 specs 和测试。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `Guide_Doc/tool_generation_guide.md`

## 详细执行步骤

1. 读取 requirements_manifest.required_tools 和每个业务阶段的输入输出，建立按依赖排序的单工具队列。每批默认只处理一个工具，只读取当前工具直接相关的需求片段与阶段输入输出；完成当前 spec、fixture 和简短摘要后才进入下一批，禁止一次读取全部工具细节、fixture 或未来源码。
2. 为当前批 required_tool 创建 .workflow/tool_specs/<name>.yaml；每个 spec 必须包含正向、边界和失败测试，禁止只保留 <smoke_tool>。expected.ok=true 的测试输入夹具必须放在 .workflow/tool_tests/cases/，禁止创建根目录 examples，禁止依赖会在发布清理中删除的 output/、reports/ 或 .workflow/logs/。
3. 区分两类路径：写入子工作流 spec/config 的路径保持 `.workflow/...` 或 `output/...`；当前外层 Builder Agent 调用 `ReadTextFile`、`PathList`、`GetFileInfo`、`RunTestCases` 等工具时，必须使用 `{TEST_WORKFLOW_ROOT}/.workflow/...` 或 `{TEST_WORKFLOW_ROOT}/output/...`。不得把子工作流相对路径直接交给外层工具。
4. 会创建或修改文件的测试，其输出路径必须放在 output/tool_tests/ 下；不得把输出写回只读的 docs/、tools/ 或 .workflow/tool_tests/cases/ 输入夹具目录，以保证 direct 和 MCP 两种运行方式一致。
5. 每个业务工具的正向测试必须覆盖需求中声明的核心能力，而不是只验证返回结构。例如声明支持图片、表格、页码、格式转换或协议解析时，spec 必须提供包含这些特性的夹具，并在 data_required_keys 或后续 inspector 中验证真实产物。
6. 工具至少覆盖需求解析中要求的 为 requirements_manifest.required_tools 中列出的全部业务工具设计 specs能力。
7. 业务工具测试由 `.workflow/tool_specs/*.yaml` 驱动，必须在 `{TEST_WORKFLOW_ROOT}` 内运行 `make check_tool_specs` 和 `make test_tools`。全部 spec 写完后各运行一次，只读取汇总、失败工具名和必要失败片段，禁止逐份预读所有 fixture。不得虚构 `test_tool_checks.py`，也不得用外层 `RunTestCases`/pytest 代替 `tool_direct_runner`。
8. 修复全部协议和测试错误后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: design_all_business_tool_specs
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_specs
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `design_all_business_tool_specs` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- 本阶段没有独立业务 Checker 时，仍由持续规划 Checker、输出文件检查和后续阶段交叉验证约束。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |
| `RunTestCases` 或 `GetFileInfo` 报外层 `.workflow/tool_tests/cases` 不存在 | 把只对子工作流内部有效的 `.workflow/...` 路径直接传给了外层 Builder 工具 | spec/config 中继续写 `.workflow/...`；外层工具调用改用 `{TEST_WORKFLOW_ROOT}/.workflow/...`，不要在外层 workspace 创建同名补丁目录 |
| pytest 报 `test_tool_checks.py` 不存在或收集 0 项 | 把 YAML spec 驱动的工具测试误当成 pytest 测试 | 在 `{TEST_WORKFLOW_ROOT}` 内运行 `make check_tool_specs`、`make check_tools` 和 `make test_tools`；测试入口是 `.workflow/checkers/tool_direct_runner.py`，不得创建虚假的 pytest 文件 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
