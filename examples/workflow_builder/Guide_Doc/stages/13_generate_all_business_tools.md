# Stage 13: generate_all_business_tools

## 阶段目标

批量生成、注册全部业务工具。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/.workflow/tool_specs/` 中实际存在的 spec 文件名；先枚举，再按单工具小批次处理，不得在同一轮全文读取全部 spec、源码和 fixture。

## 详细执行步骤

1. 先用 `PathList` 取得工具 spec 的路径清单，按依赖关系建立顺序队列。默认每批只处理一个工具；只有两个工具不存在共享注册表写入、没有上游产物依赖且各自源码和 fixture 总量很小时，才允许一批两个工具。为每批记录工具名、spec、源码、一个正例、一个反例和预期输出路径，确认文件所有权互不重叠。
2. 当前批次只读取该工具的 spec、生成后的源码和最多一个正例、一个反例 fixture。禁止在本阶段全文读取其他工具的 fixture、`tool_direct_runner.py`、`tool_static_checker.py`、Makefile、output 目录、旧测试日志或全部测试结果；这些文件不能帮助当前工具的业务实现，且会把无关文本带入下一次模型决策。
3. 对当前批次尚无实现的 spec，调用一次 `WorkflowToolGenerator(existing_policy='create_only', update_config=true)`。已有源码必须报告 skipped 并保持字节不变；只有生成状态摘要匹配的未修改骨架才允许 `refresh_scaffold`，人工实现后的工具禁止 `force_replace`。生成器会修改共享 `config.yaml`，因此不同批次必须串行，不能为单个 spec 并发调用生成器。
4. 生成器返回后，只补齐当前工具源码和其专属 fixture，检查路径安全、统一返回结构、领域库调用和核心行为。若 from_spec 仅生成通用骨架，必须在当前批次补齐真实业务逻辑和负例失败条件。完成后在当前上下文留下不超过一段的摘要，只包含工具名、修改文件、正反例结论和未决项；下一批不得重读已完成工具源码或 fixture。
5. 全部小批次完成后，串行运行 `make check_tools` 和 `make test_tools`。只读取命令汇总、失败工具名和必要失败片段；不得为了复核通过结果再全文读取全部 fixture。修复失败时回到对应单工具批次，完成后再 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: generate_all_business_tools
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/tools
  - {TEST_WORKFLOW_ROOT}/config.yaml
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `generate_all_business_tools` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- 本阶段没有独立业务 Checker 时，仍由持续规划 Checker、输出文件检查和后续阶段交叉验证约束。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |
| 批量生成后 smoke 工具业务逻辑变回 `_default_value` | 对所有 spec 使用了旧版 `overwrite=true` 或 `force_replace`，生成骨架覆盖了已有实现 | 从可信版本恢复业务实现；后续批量生成固定使用 `create_only`，逐项处理 created 与 skipped 报告 |
| 工具测试通过但真实需求未实现 | 为迁就骨架返回值而降低 `expected.ok`、删除失败用例或放宽字段断言 | 恢复原测试语义，保留全部既有正反用例，只能追加覆盖；修改业务源码直至原测试与新增测试同时通过 |
| 连续读取不同 fixture 后模型请求反复中断、压缩或长时间无进展 | 同一轮把全量 spec、源码、正反 fixture、runner、Makefile 和旧日志读入，导致当前业务决策携带大量无关上下文 | 停止继续读取；按本文件改为单工具批次，只保留当前 spec、源码和一正一反 fixture。通过 `make test_tools` 获取全量结论，下一阶段再读取 runner、Makefile 和失败摘要；重启后从当前阶段继续，不得手工修补候选产物。 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
