# Stage 11: generate_complete_runtime_configs

## 阶段目标

生成并检查主流程、增量流程和可选评估配置。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{TEST_WORKFLOW_ROOT}/.workflow/config_specs/main.yaml`
- `{TEST_WORKFLOW_ROOT}/.workflow/config_specs/inc.yaml`
- `{WFGEN_DIR}/requirements_manifest.yaml`
- `Guide_Doc/config_generation_guide.md`

## 详细执行步骤

1. 分别调用 WorkflowConfigGenerator，并明确传入 workflow_spec_path='.workflow/workflow_spec.yaml'：main spec 直接生成 config.yaml，inc spec 生成 config/inc.yaml；只有 manifest 登记时才生成 eval.yaml。禁止生成 config/default.yaml 后复制，也禁止生成 config/empty.yaml。
2. 确认所有配置均使用根级 stage；main 和 inc 分别覆盖 manifest 中对应路径的阶段，每个 task 的有效正文长度必须至少 100，Checker、reference_files、output_files 必须与 workflow_spec 的同名阶段完全一致；工具注册和 template_overwrite 仍由 config spec 提供。
3. 生成后按 config.yaml、config/inc.yaml、存在时的 eval.yaml 分批重新读取当前配置和相关 workflow_spec 阶段，不能只检查生成器返回摘要或继续沿用设计阶段的记忆。每批先调用 `WorkflowArtifactInspector(action='yaml_summary')`，再读取必要阶段片段；逐项检查 reference_files 和 output_files：每项必须是具体文件，不能是目录、通配符或目录形状路径。完成当前批次后只保留审查表摘要，不得重新全文读取已完成配置；目录型工作成果必须由 manifest、summary 或 report 文件提供可追踪证据。
4. 为最终配置中的每个 reference 建立审查表，记录“配置、阶段、引用、类别、精确声明位置或生产阶段、结论”。静态文件必须已存在，或在 manifest 中作为固定交付文件明确规划；运行时输入必须与 runtime_contract.required_input 中 type=file 的精确路径一致；派生文件必须与权威 workflow_spec 中严格前序阶段的 output_files 完全一致。目录声明、当前或后续阶段产物、未知占位符、拼错路径以及仅凭 task/示例推测的路径均不得通过。
5. 搜索全部生成配置，确认不存在 {TARGET}；使用 example 作为示例目标实际启动时，所有输入路径必须展开到 input/example/，所有输出与 checker 路径必须展开到 output/example/。
6. 搜索全部生成配置的 task、reference_files、output_files 和 checker 参数，确认不存在 .//workflow/、./workflow/ 或 workflow/ 父目录前缀；内部文件必须相对子工作流根目录引用。发现泄漏或引用审计失败时，回到 `.workflow/workflow_spec.yaml` 与对应 config spec 修正后重新调用生成器，不得只手工修改最终 config.yaml。
7. 调用 `WorkflowRuntimeConfigAuditChecker`。只有高危静态审计为空、配置与 workflow_spec 同步、所有 reference 均能证明来源时才可通过。将 checker 返回的 checked_configs、checked_reference_count 和失败明细记录进本阶段规划。
8. 运行配置语法检查并记录结果，然后 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: generate_complete_runtime_configs
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/config.yaml
  - {TEST_WORKFLOW_ROOT}/config/inc.yaml
checks:
  - name: runtime_config_reference_audit
    passed: true
    evidence: checked_configs 与 checked_reference_count
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `generate_complete_runtime_configs` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `WorkflowRuntimeConfigAuditChecker` 同时检查 YAML 静态规则、workflow_spec 同步关系和逐项 reference 来源。任何 critical/high 静态问题、前向引用、未声明运行时输入或不存在且未规划的静态文件都会失败。
- `WorkflowLivingPlanChecker` 检查本阶段记录以追加方式写入，并包含真实审查证据。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `unproven_reference_files` 报告某路径 | 该引用没有严格前序 producer，也不是 type=file 输入或固定交付文件 | 根据报告回到 workflow_spec/config spec 修正并重新生成，禁止手工改最终 YAML |
| 设计 spec 看似正确但最终配置失败 | 权威注入、占位符展开或多个配置间同步后产生了新问题 | 必须重新读取最终配置并以 checker 结果为准，不能只复核输入 spec |
| 临时审查脚本把 `stage` 当成 mapping，或用字符串缩进判断阶段结构 | 没有通过 YAML parser 查看最终对象的真实类型 | 调用 `WorkflowArtifactInspector(action='yaml_summary', path='config.yaml')` 和 `config/inc.yaml`，依据 `root_type`、`stage_container_type`、`stage_count`、`stage_names` 判断；禁止为同类结构审查另写脚本 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
