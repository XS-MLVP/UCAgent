# Stage 21: clean_release_candidate

## 阶段目标

清理运行历史、缓存、日志和无效重复文件。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/.install/README.md`

## 详细执行步骤

1. 在不删除最终源文件、spec、测试和交付模板的前提下，清理 .ucagent、__pycache__、.pytest_cache、.workflow/logs、output/ 下的运行产物以及错误重复的文档目录；运行 make clean 清空根级 tmp/ 中全部普通文件、隐藏文件和子目录，但保留空的 tmp/ 与 output/。检查根目录、wfgen、tools 和 .workflow/，任何 run_checks、临时 batch 或一次性中间文件都必须删除，迁移包只能保留空 tmp/ 目录。
2. 确认最终工程不包含绝对路径、临时迁移部署目录、本次测试产生的运行日志和根目录 examples/；不得删除 .workflow/*_tests/cases 下作为测试输入的夹具日志。
3. 重新运行静态 make check 和最终需求覆盖检查，确认清理没有破坏 input/output 运行契约与发布候选，然后 Complete。
4. 发布树检查必须以 `.workflow/acceptance_rules.yaml` 为唯一公开文件来源；`.workflow/tool_tests/cases/` 下的 fixture 和其合法日志不得按文件名误删，根级 `tmp/`、`.workflow/logs/` 和 output 运行结果必须按共享清洁度规则区分处理。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: clean_release_candidate
status: passed
artifacts:
  - 本阶段无新增文件，需记录实际检查证据
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `clean_release_candidate` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- 本阶段没有独立业务 Checker 时，仍由持续规划 Checker、输出文件检查和后续阶段交叉验证约束。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `make check` 通过后发布树又出现 logs、`.workflow/local/environment.yaml` 或 `output/tool_tests` | 测试本身会重新生成运行证据，清理顺序错误 | 固定采用“测试取证 → 需求覆盖取证 → `make clean` → 删除额外运行产物 → `WorkflowArtifactInspector(action='release_tree')`”顺序；测试 fixture 目录中的合法日志由共享清洁度策略保留 |
| release_tree 报必需文件缺失或固定 output 文件被当成运行产物 | 使用了手工清单，未以 acceptance 为准 | 必需公开路径只从 `.workflow/acceptance_rules.yaml` 读取；`output/README.md`、`.gitkeep`、`.keep` 只有被 acceptance 明确声明时才允许，其他 output 文件仍必须清理 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
