# Stage 03: verify_tool_generation_loop

## 阶段目标

验证工具生成基础设施，不默认生成无关通用工具。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{TEST_WORKFLOW_ROOT}/.workflow/checkers/tool_spec_checker.py`
- `{TEST_WORKFLOW_ROOT}/.workflow/checkers/tool_static_checker.py`
- `{TEST_WORKFLOW_ROOT}/.workflow/checkers/tool_direct_runner.py`
- `{TEST_WORKFLOW_ROOT}/.workflow/tool_tests/run_mcp_tests.py`
- `{TEST_WORKFLOW_ROOT}/tools/mcp_adapters.py`
- `{TEST_WORKFLOW_ROOT}/Makefile`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `Guide_Doc/tool_generation_guide.md`

## 详细执行步骤

1. 第1步：调用 `WorkflowToolGenerator(mode='base', tools=['run_command_tool'], existing_policy='create_only')` 生成并注册固定的受限批处理工具。该工具是运行基础设施，不计入业务 required_tools；其 cwd 必须解析到工作流根目录内，命令必须来自白名单，必须使用 `shell=False`。Python 或 Shell batch 只能通过工作流根级 `tmp/` 内相对 `.py`/`.sh` 文件运行，且解释器命令只接受一个脚本参数；禁止 `python -c`、`bash -c`、绝对路径、`..`、命令拼接、未批准 make 目标和任意危险参数。read_text_file_tool、write_text_file_tool 仍不得无需求生成。
2. 第2步：使用 ReadTextFile 读取 {TEST_WORKFLOW_ROOT}/.workflow/checkers/tool_spec_checker.py、tool_static_checker.py、tool_direct_runner.py、.workflow/tool_tests/run_mcp_tests.py 和 tools/mcp_adapters.py。
3. 第2.1步：确认 tools/mcp_adapters.py 的动态 adapter 只实现 _run，不得定义 def run(self, tool_input...)，也不得在动态类字典中注册 run 函数覆盖项；必须让 BaseTool.run 负责把 _run 返回内容包装成 ToolMessage。否则生成工作流直接 make run 时会报工具返回裸字符串类型错误。 adapter 的 args_schema 字段类型必须使用 Any，避免 MCP/FastMCP 将 JSON 字符串预解析成 list/dict 后被 Pydantic 提前拒绝。
4. 第3步：确认 Makefile 包含 check_tool_specs、check_tools、test_tools、test_mcp，且 make check 会包含这些目标。
5. 第4步：确认 config.yaml 中 tools 是 mapping，包含 tools.RunTestCases.test_dir；GeneratedTools 可以为空，后续 smoke 和全量业务工具阶段会按 requirements_manifest.required_tools 注册真实工具。
6. 第5步：使用 Check 验证 run_command_tool 已有 spec、源码、GeneratedTools 注册、正常 `pwd` 用例和拒绝 inline Python 的失败用例；缺少该基础设施工具必须失败，但不得因为缺少 read_text_file_tool/write_text_file_tool 失败。
7. 第6步：使用 SetCurrentStageJournal 记录工具基础设施检查结果。
8. 第7步：使用 Complete 工具完成阶段。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: verify_tool_generation_loop
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/.workflow/tool_specs
  - {TEST_WORKFLOW_ROOT}/tools/mcp_adapters.py
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `verify_tool_generation_loop` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `workflow_tool_generation_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| 启动日志中的 reference 含 `{TEST_WORKFLOW}` 或 `.//workflow` | 模板替换是单次展开，或 Makefile 直接拼接了带尾斜杠的 `OUT` | 不要继续用等价路径读取；将外层 `TEST_WORKFLOW_ROOT` 固定为 `workflow`，用 `NORMALIZED_OUT` 去除尾斜杠，重启后以 CurrentTips 确认字符串已规范化 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |
| 批处理脚本放在工作流根目录、wfgen 或 `.workflow/` | 误把正式交付目录当成临时执行区，后续清理和迁移会泄漏脚本 | 把脚本创建到 `{TEST_WORKFLOW_ROOT}/tmp/`，通过 `run_command_tool` 或外层 `WorkflowCommandRunner` 执行，完成后删除；`make clean` 必须清空 tmp 内容 |
| `refresh_scaffold` 拒绝覆盖 | 当前源码摘要与生成状态不同，说明文件已人工修改或不是生成器拥有的骨架 | 保留当前源码并读取差异；业务实现使用 `create_only`，不得切换 `force_replace` 规避保护 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
