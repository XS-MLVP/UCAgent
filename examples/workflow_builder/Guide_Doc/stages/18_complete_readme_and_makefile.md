# Stage 18: complete_readme_and_makefile

## 阶段目标

完善最终 README、Makefile 和运行脚本。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/README.md`
- `{TEST_WORKFLOW_ROOT}/docs/01快速启动.md`
- `{TEST_WORKFLOW_ROOT}/Makefile`

## 详细执行步骤

1. 根据 runtime_contract、需求和最终组件更新 README，必须说明如何通过 TARGET 选择具体目标、input/<TARGET>/ 必需文件、input/example/ 示例、output/ 输出、变量替换、主流程与增量流程、可选 eval 模式、测试、报告、故障恢复和迁移。
2. README 和 docs/01快速启动.md 必须明确每个输入是原始材料、可选资源还是配置，并说明哪些结构、分析和设计由工作流自动产生。不得通过示例或模板暗示用户需要预先完成工作流本身的职责。
3. 生成并完善 docs/01快速启动.md；内容必须以 input/example/ 为唯一快速开始示例，按顺序给出 make check、make check_example、make run TARGET=example，并明确输出位于 output/。禁止写入无法直接执行的占位命令。
4. 完善 Makefile，TARGET 默认值必须为空，必须保留 configure、configure-check 和 setup.py 受控环境区块，并包含 check_target、prepare_input、prepare_runtime 和 check_input； run/run_inc/run_tui 必须依赖 prepare_runtime；check_example 必须逐项校验 runtime_contract.required_input 并验证 JSON 等结构化输入。用户输入不得被要求包含 data/__init__.py；UCAgent 运行包只能位于 output/.runtime_targets/。Makefile 必须定义 WORKFLOW_WORKSPACE ?= $(CURDIR)，所有 UCAgent 启动命令必须使用 $(UCAGENT) $(WORKFLOW_WORKSPACE) $(TARGET)，禁止使用 $(UCAGENT) ./ $(TARGET)。smoke 必须使用独立 SMOKE_TARGET；requirements_manifest.required_make_targets 全部可用。
5. 确认 run/run_inc/run_tui/smoke 均通过 tools.mcp_adapters 动态传入 --ex-tools；运行结束时若 .ucagent/ucagent_info.json 的 all_completed=true，Makefile 必须返回 0，即使 UCAgent 的 Exit 路径返回了中断状态。
6. 确认 tools/mcp_adapters.py 保持 WFB 模板契约。不能覆盖 BaseTool.run，不能注册 run 函数覆盖项；_run 返回 json.dumps(result, ensure_ascii=False, sort_keys=True)，让 BaseTool 在直接 UCAgent 运行时包装成 ToolMessage。
7. make check、test_tools 和 test_checkers 只能依赖源码、spec 以及 .workflow/*_tests/cases/ 下的持久测试夹具；禁止依赖会在发布清理中删除的 tmp、output、reports 或运行日志。Makefile 的 clean 必须保留根级 tmp/ 目录但清空其中全部普通与隐藏内容；所有临时脚本、run_checks 文件和一次性中间结果只能写入 tmp/，不得写到根目录、wfgen、tools 或 .workflow/。
8. 严格按照 docs/01快速启动.md 运行 bundled example，再运行 make help、make check 和安装检查，修复后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: complete_readme_and_makefile
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/README.md
  - {TEST_WORKFLOW_ROOT}/docs/01快速启动.md
  - {TEST_WORKFLOW_ROOT}/Makefile
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `complete_readme_and_makefile` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- 本阶段没有独立业务 Checker 时，仍由持续规划 Checker、输出文件检查和后续阶段交叉验证约束。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
