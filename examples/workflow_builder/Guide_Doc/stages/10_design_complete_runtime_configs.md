# Stage 10: design_complete_runtime_configs

## 阶段目标

根据需求清单设计主流程、增量流程和可选评估配置。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/.workflow/workflow_spec.yaml`
- `Guide_Doc/config_generation_guide.md`

## 详细执行步骤

1. 读取 requirements_manifest、原始需求和 .workflow/workflow_spec.yaml。
2. 对每个业务输入区分“用户提供的原始输入”和“工作流生成的派生信息”。阶段 task 必须明确如何从原始输入提取、归纳、规划或设计派生结果；禁止假设用户已经提供最终结构、逐项方案、分析结果或设计配置。
3. 生成 config.yaml、config/inc.yaml 和按需生成的 eval.yaml 时，每个阶段的 task 合计至少包含 100 个有效正文字符，并具体说明输入、操作顺序、调用工具、生成产物、Checker 检查内容和失败处理。禁止生成 config/default.yaml 或 config/empty.yaml。
4. 如果输入包含可用资源清单，配置必须把它描述为候选资源而非强制使用清单；资源选择、处理方式和新增图形需求由业务阶段决定，除非原始需求明确规定。
5. 创建 .workflow/config_specs/main.yaml 和 inc.yaml；main 使用 mode: default 并直接生成根级 config.yaml，inc 使用 mode: inc 并生成 config/inc.yaml。只有 manifest 明确要求独立评估时才创建 eval spec 和根级 eval.yaml。最终配置的阶段必须位于 YAML 根级 stage，禁止写成 workflow.stages。
6. 配置中的 UCAgent 变量必须使用单层花括号语法；目标名只能使用 {DUT}，输出根目录只能使用 {OUT}，禁止使用未定义的 {TARGET} 或双层花括号。阶段 task、reference_files、output_files 和 checker 参数中的路径必须统一写成 input/{DUT}/... 与 {OUT}/{DUT}/...；需要的附加路径变量通过 template_overwrite 声明。
7. 子工作流配置中的所有路径都以生成后的 {TEST_WORKFLOW_ROOT} 自身为根。内部静态文件必须写成 .workflow/workflow_spec.yaml、Guide_Doc/... 或 config/...，严禁把 Builder 访问候选目录时使用的 {TEST_WORKFLOW_ROOT}/ 前缀复制进 config spec；尤其禁止 .//workflow/、./workflow/ 和 workflow/。 例如外层读取 {TEST_WORKFLOW_ROOT}/.workflow/workflow_spec.yaml，写入子工作流 reference_files 时必须转换为 .workflow/workflow_spec.yaml。
8. 禁止把当前 WFB/MWF 的运行时值写入 CWF 配置 spec；不得出现 output/workflow_build、input/workflow_build 或 output/workflow_build。write_dirs 必须且只能是 ['{OUT}/{DUT}']，不得写成 [output]。
9. main/inc 和可选 eval spec 必须包含明确且足够详细的 task，但不得重新发明 Checker、reference_files 或 output_files。这些字段由 `.workflow/workflow_spec.yaml` 的同名阶段权威注入；若 spec 显式提供，内容必须完全一致，否则生成器拒绝。
10. `reference_files` 与 `output_files` 只能使用具体文件路径，禁止目录、通配符和目录形状路径。reference 必须能追溯到固定交付文件、runtime_contract 明确要求的 type=file 输入，或前序阶段的具体输出；不确定能否存在的文件不要写。目录型成果应新增 manifest、summary 或 report 文件作为 output。
11. 为每个待写入的 reference 建立来源表，至少记录“配置与阶段、原始路径、来源类别、声明位置或生产阶段、是否严格前序、结论”。固定交付类必须能在 manifest 的 required_guidedocs、required_user_docs、required_templates、required_configs 或 required_deliverables 中找到精确文件路径；用户输入类必须与 runtime_contract.required_input 中 type=file 的路径精确对应，type=directory 只证明目录存在，不能证明目录内某个文件存在；派生类必须与 `.workflow/workflow_spec.yaml` 中严格前序阶段的某个 output_files 完全一致。
12. 完成来源表后按 main、inc、可选 eval 的顺序分批用 `ReadTextFile` 读取当前 spec 和 workflow_spec 中关联阶段交叉审查；每批结束立即记录来源结论，后续批次只读取此前摘要，不得重新全文读取已完成 spec。当前阶段或后续阶段才生成的文件属于前向引用；拼写相近、扩展名不同、只有 task 提到、只在示例中出现或“预计工具会创建”的文件均不构成存在性证据。无法证明的 reference 必须删除，或先把真实证据文件规划为前序 output。
13. reference_files 只能列出可由 ReadTextFile 读取的文本、YAML、JSON 或源码文件；禁止放目录、图片、PPTX、PDF 等二进制路径。目录必须在 task 中使用 PathList，二进制产物必须用业务工具或 checker 验证。
14. 业务阶段必须直接调用已注册工具完成产物和审查。禁止创建 output/*.py 或其他临时脚本绕过业务工具，禁止用 RunTestCases 代替业务阶段执行；需要复合审查时应扩展正式 inspector/checker 工具接口。
15. 记录主配置、增量配置和存在时的 eval 配置的阶段数量、差异和逐项引用来源审查结论，然后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: design_complete_runtime_configs
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/.workflow/config_specs/main.yaml
  - {TEST_WORKFLOW_ROOT}/.workflow/config_specs/inc.yaml
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `design_complete_runtime_configs` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- 本阶段没有独立业务 Checker 时，仍由持续规划 Checker、输出文件检查和后续阶段交叉验证约束。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `unproven_reference_files` 非空 | 把目录输入、未来产物或推测路径当成必然存在的文件 | 按报告中的配置、阶段和路径回到 workflow_spec；补充真实前序证据产物或删除引用，再重新生成配置 |
| 用户声明了输入目录但其中某文件仍被拒绝 | `type=directory` 只承诺目录，不承诺任意子文件 | 将真正必需的文件作为 `type=file` 明确声明，或在阶段中使用 PathList 枚举目录并由工具处理 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
