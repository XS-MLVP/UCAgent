# Stage 04: design_smoke_business_tool_spec

## 阶段目标

为 smoke 基线设计代表性业务工具规格。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/.workflow/workflow_spec.yaml`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `Guide_Doc/tool_generation_guide.md`

## 详细执行步骤

1. 第1步：读取 {WFGEN_DIR}/requirements_manifest.yaml、Guide_Doc/tool_generation_guide.md、{TEST_WORKFLOW_ROOT}/.workflow/workflow_spec.yaml 和 {TEST_WORKFLOW_ROOT}/config.yaml。
2. 第2步：从 requirements_manifest.required_tools 中选择一个非基础业务工具作为 smoke 工具；不得假定工具名称、输入类型或输出字段。
3. 第3步：创建 {WFGEN_DIR}/smoke_tool_selection.yaml，根级字段必须为 name、spec_path、fixture_paths。name 是所选工具名；spec_path 必须是 .workflow/tool_specs/<name>.yaml；fixture_paths 是当前已创建测试夹具的相对路径列表。 每个路径可以是普通文件，也可以是包含至少一个实际文件的非空目录；目录型输入（例如 RTL 源码树）应直接声明目录， Checker 会递归确认其中存在文件，不要为了通过检查而把目录替换成任意单个文件。
4. 第4步：按选择文件中的实际路径创建至少一个稳定测试夹具和 tool_spec，不要先写工具代码。夹具必须位于 .workflow/tool_tests/cases/ 下；禁止创建根目录 examples/。
5. 第5步：tool_spec 的 entry.file 必须是 tools/<name>.py，class_name 根据工具名生成合法 Python 类名，method 必须是 run；inputs、outputs 和 data_required_keys 必须来自该工具的真实职责。
6. 第6步：tool_spec 必须包含 basic_test，expected.ok=true，并引用 fixture_paths 中的夹具；不得硬编码 PPT、RTL 或其他特定领域字段。
7. 第7步：使用 Check 运行动态 spec checker，确认所选工具属于 manifest、选择文件路径安全、夹具存在且 make check_tool_specs 通过。
8. 第8步：记录选择文件、实际工具名、spec 和夹具路径，然后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: design_smoke_business_tool_spec
status: passed
artifacts:
  - {WFGEN_DIR}/smoke_tool_selection.yaml
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_specs
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_tests/cases
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `design_smoke_business_tool_spec` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_business_tool_spec_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 第一次 Check 只报告 living plan 缺少当前阶段 | 在追加当前阶段记录前直接调用了聚合 Check，LivingPlanChecker 会先于业务 Checker 终止 | 先用明确的 Make 或测试入口取得业务证据，再调用 WorkflowPlanAppender 追加唯一记录，最后运行聚合 Check；不要为了减少一次失败而伪造尚未取得的验证结果 |
| tool spec 结构正确但 `tool_spec_checker` 报入口文件不匹配 | spec `name` 与 `entry.file` 的文件 stem 大小写或命名风格不同 | `entry.file` 的 stem 必须与 spec `name` 完全一致，例如 `AudioJobResolver` 对应 `tools/AudioJobResolver.py`；不要自行改成 snake_case，除非同时修改生成器和 checker 契约并补回归 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
