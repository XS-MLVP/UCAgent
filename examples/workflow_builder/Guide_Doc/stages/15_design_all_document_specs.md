# Stage 15: design_all_document_specs

## 阶段目标

为全部业务阶段设计 GuideDoc 与用户文档 specs。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{WFGEN_DIR}/guidedoc_spec_schema.yaml`
- `{TEST_WORKFLOW_ROOT}/config.yaml`
- `Guide_Doc/guidedoc_generation_guide.md`

## 详细执行步骤

1. 先读取 requirements_manifest.required_guidedocs、required_user_docs、required_tools、required_checkers、config.yaml 和 {WFGEN_DIR}/guidedoc_spec_schema.yaml，建立每批最多 3 份文档的队列。当前批只读取对应阶段名称、注册摘要和输出契约；完成 spec 与覆盖摘要后才进入下一批，禁止重新全文读取已完成文档的设计信息。
2. 为当前批 required_guidedoc 和 required_user_doc 创建单一 YAML 文档 spec；使用 document_type、title、output、sections 和可选 operation_contract。guide_doc 输出到 Guide_Doc/ 并注册，user_doc 输出到 docs/ 且不得注册。
3. required_guidedoc 中的 stage/stages/scope 是文档覆盖契约。每个非豁免业务阶段必须被至少一份 GuideDoc 覆盖； 对复杂步骤要生成独立的阶段文档，例如 Guide_Doc/<stage_name>.md，而不是把所有步骤塞进 operation.md。
4. 每份 GuideDoc 必须包含 Purpose、Inputs、Outputs、Usage、Execution、Checks、Failure Recovery。只有 operation_contract=true 的操作文档强制包含 TARGET、input/<TARGET>/、input/example、output/、make check_example 和 make run，技术文档不得机械重复快速启动内容。
5. 固定生成 docs/README.md、docs/01快速启动.md、docs/02输入输出.md、docs/03步骤及检查.md、docs/04开发者文档-tools.md、docs/05开发者文档-checkers.md，并按需求增加其他用户文档。快速启动和输入输出文档必须说明 make configure、make configure-check、setup.py 非交互参数、本机配置位置及敏感值不落盘规则。每份 docs 文档至少 200 个有效正文字符。
5.1 用户文档必须遵循固定格式契约：README 包含文档地图和快速入口；快速启动包含 make configure、make check 和 make run；输入输出包含 input/<TARGET>/、output/<TARGET>/、metadata/ 和 checksums.sha256；步骤文档解释阶段、工具和 Checker；两份开发者文档必须包含真实源码、关键代码分析和测试说明。禁止 TODO、TBD、待补充和空章节。用户输入契约必须与 runtime_contract、Makefile 和 config 一致，metadata/ 与 checksums.sha256 的必需性不得在不同文档中出现冲突。
6. 本阶段只设计开发者文档的覆盖结构和源码映射。docs/04开发者文档-tools.md 必须覆盖 requirements_manifest.required_tools 与 config.tools.GeneratedTools 中全部启用工具，包括固定的 run_command_tool；docs/05开发者文档-checkers.md 必须覆盖 requirements_manifest.required_checkers 与 `.workflow/workflow_spec.yaml.checkers` 实际注册项的并集，包括基础设施 Checker。每个组件建立包含准确名称的二级至六级 Markdown 标题，并准备至少 100 个有效正文字符的设计摘要。
7. 按每批最多 3 个组件从 `config.tools.GeneratedTools` 和 `.workflow/workflow_spec.yaml.checkers` 取得真实注册信息，再读取对应 spec 或注册项。每个组件设计摘要必须原样写出实现相对路径、`class_name` 和 `method`，并规划下一阶段需要补全的关键逻辑、调用路径、输入输出、主要分支、异常处理、扩展点、测试和修改影响。本阶段不读取全部实现源码、fixture 或 runner，真实源码分析留给下一阶段。
8. 本阶段不得重复承担最终文档验收：不强制逐字源码围栏代码块，不要求十类固定标签全部写完，也不要求提前完成每组件 300 字正文。下一阶段必须重新读取最终源码、把每项扩展到至少 300 个有效正文字符、加入真实源码和关键业务代码分析，再由最终文档 Checker 验收。
9. 设计摘要不能是空标题或泛化占位。它必须说明组件在工作流中的职责、准确源码映射和下一阶段的分析范围，使文档生成阶段无需重新发现组件清单。
10. Inputs 必须准确区分原始输入、可选资源和工作流派生信息。不得要求用户填写应由阶段生成的结构、分析结果、设计参数或中间产物；Execution 必须说明工作流如何从原始输入产生这些结果。
11. 确认每个业务阶段引用对应 GuideDoc，不得只生成 overview.md/operation.md，然后 Complete。

## 开发者组件 Spec 的最小可通过模板

本阶段模板用于冻结组件身份、源码映射和后续分析范围。最终文档的十类标签、真实代码块和 300 字
硬下限由下一阶段补齐并验收：

````markdown
## ExactRegisteredComponentName

**实现文件**：`tools/example.py`
**入口类**：`ExampleTool`
**入口函数**：`run`
**设计摘要**：说明组件职责、上下游数据和下一阶段必须分析的关键分支、异常、扩展点、测试与联动修改范围，至少 100 个有效正文字符。
````

`class_name` 和 `method` 为空时不能虚构，应先检查注册或 spec 是否缺失。Stage 15 的
`guidedoc_spec_check` 只验证组件覆盖、设计摘要长度和源码映射；最终内容约束仍由 Stage 16 负责。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: design_all_document_specs
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/.workflow/guidedoc_specs
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `design_all_document_specs` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `guidedoc_spec_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `developer_doc_spec_errors` 列出全部组件 | 组件标题未命中、设计摘要过短或源码映射不准确 | 对照最小模板逐组件使用准确注册名称，并写明真实实现路径、class_name 和 method |
| 设计阶段长时间逐项修正文档源码 | 把最终文档的逐字代码和 300 字验收提前放进设计阶段 | 设计阶段只冻结覆盖与源码映射；真实代码块、十类分析和最终长度统一留到生成阶段 |
| 某组件有效长度为 0 | 标题不在二级至六级范围，标题未包含准确注册名称，或组件内容被下一个标题截断 | 使用 `## ExactRegisteredName`，把该组件全部分析放在下一组件标题之前 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
