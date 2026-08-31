# Stage 02: build_initial_template

## 阶段目标

调用 WorkflowBuilder 建立工程骨架，然后从 test_input 复制真实示例覆盖占位文件。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{BUILD_CONFIG}`
- `{WFGEN_DIR}/input_example_manifest.yaml`

## 详细执行步骤

1. 第1步：使用 ReadTextFile 读取 {BUILD_CONFIG} 和 {WFGEN_DIR}/input_example_manifest.yaml，再用 PathList 与 GetFileInfo 建立 {TEST_INPUT_DIR} 的完整文件清单。只读取 runtime_contract.required_input 中的文本文件及其直接引用；二进制、大型文件和无关知识材料只核验路径、类型、大小和 Builder 的复制摘要，禁止为复制验证而全文读取所有输入。
2. 第2步：调用 WorkflowBuilder(build_config_path='{BUILD_CONFIG}', base_dir='{OUT}', input_example_manifest_path='{WFGEN_DIR}/input_example_manifest.yaml')。Builder 先创建结构骨架，再按 manifest 的 copy_tree 规则执行二进制原样复制。禁止用 ReadTextFile 加 EditTextFile 重建源文件，否则会改变末尾换行或其他字节。
3. 第2.1步（关键）：检查 WorkflowBuilder 返回的 copied_example_files 数量。用源和目标的 PathList/GetFileInfo 清单逐项确认全部源文件在 {TEST_WORKFLOW_ROOT}/input/example/ 保持相对路径、类型、大小与复制摘要一致；仅对 runtime_contract 的文本入口做内容读取。resource_paths 只决定落点，不允许改写正文。源目录对应位置不得残留空 JSON、占位文字、示例提示或 rtl/README.md。
4. 第2.2步（关键）：覆盖完成后，读取 {TEST_WORKFLOW_ROOT}/input/example/ 下的每个 runtime_contract.required_input 文件，核对其中引用的相对路径真实存在且不逃逸目录。若引用不对应，应回到 input_example_manifest 的 resource_paths 修正复制落点并重新调用 Builder，禁止修改复制后的用户源文件。
5. 第3步：检查 WorkflowBuilder 工具返回信息，确认 root 为 {TEST_WORKFLOW_ROOT}。
6. 第4步：确认 {TEST_WORKFLOW_ROOT}/Makefile、docs/01快速启动.md、requirements.txt、config.yaml、Guide_Doc/overview.md、 Guide_Doc/operation.md、input/example/README.md 和 .workflow/build_report.md 已生成； 逐项确认 runtime_contract.required_input 中声明的每个文件和目录在 input/example/ 下 真实存在；逐项确认 workflow_spec.checkers 已生成对应 `.workflow/checker_specs/*.yaml`、 `checkers/*.py` 和显式正反 fixture；然后运行 make check_example、make check_checker_specs、 make check_checkers 和 make test_checkers 验证。
7. 第5步：使用 SetCurrentStageJournal 记录 WorkflowBuilder 返回信息、test_input 复制结果、 required_input 文件路径核对结果和 make check_example 的输出。
8. 第6步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: build_initial_template
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/Makefile
  - {TEST_WORKFLOW_ROOT}/docs/01快速启动.md
  - {TEST_WORKFLOW_ROOT}/requirements.txt
  - {TEST_WORKFLOW_ROOT}/input/example/README.md
  - {TEST_WORKFLOW_ROOT}/config.yaml
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `build_initial_template` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_builder_output_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `initial_template_requirement_coverage`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `tools/` 中只有 `mcp_adapters.py` | 本阶段只构建 Checker 和工具生成基础设施，尚未进入业务工具生成阶段 | 这是当前分阶段设计的预期状态：Stage 04 设计 smoke spec，Stage 05 生成 smoke 工具，Stage 12/13 设计并生成全部业务工具。不得在本阶段创建空工具文件或绕过 WorkflowToolGenerator |
| `copy_tree` 后 `cmp` 只报告末尾换行不同 | 用文本读写工具重建文件，而不是执行二进制复制 | 将 `input_example_manifest_path` 传给 WorkflowBuilder，由 Builder 原样复制并由 WorkflowBuildOutputChecker 逐字节检查；禁止手工修派生文件 |
| 当前 `workflow/test_checkers` 通过，但从 `{BUILD_CONFIG}` 临时重建仍失败 | 只修改了生成侧 checker spec、源码或 fixture，权威构建配置仍保留错误 | 回到 Stage 1 修正 `{BUILD_CONFIG}` 并重新通过 planned Checker preflight；不得把派生目录的临时通过当作可重复构建证据 |
| `WorkflowCommandRunner` 以 `WORKFLOW-CMD-002` 拒绝标准模板检查 | 使用了带参数、多个目标或旧白名单未登记的命令 | 对标准工程直接使用单个白名单目标 `make check_example`、`make check_checker_specs`、`make check_checkers` 或 `make test_checkers`；不得创建等价临时脚本。只有现有目标无法表达业务专属检查时才允许在 `tmp/` 创建脚本 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
