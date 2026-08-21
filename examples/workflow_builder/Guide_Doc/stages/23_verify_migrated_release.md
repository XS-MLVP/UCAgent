# Stage 23: verify_migrated_release

## 阶段目标

验证迁移后的发布包仍满足交付边界。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{TEST_WORKFLOW_ROOT}/.install/manifest.json`

## 详细执行步骤

本阶段是只读验收阶段。不得修改 `install.py`、`.install/README.md`、
`.workflow/acceptance_rules.yaml`、迁移包或前序阶段产物。若发现包边界、必需文件
或部署契约问题，必须保留结构化失败证据并返回 Stage 22 修复；不得为了让本阶段
通过而临时放宽 partial 排除规则或保留被排除的工具/Checker。

1. 读取 .install/manifest.json，确认 full/partial 包边界和洁净度。
2. 在临时 full 和 partial 部署目录执行 make check_example，并核对 docs/01快速启动.md 与 requirements.txt；full 还必须执行 make check、静态安装检查、需求文件检查和 input/output 运行契约检查；partial 不启动 UCAgent。
3. 确认源工程和迁移包均无运行中子 UCAgent，记录最终交付路径并 Complete。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: verify_migrated_release
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

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `verify_migrated_release` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `final_migration_package_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| 验证脚本一次报告多项失败，但手工查看迁移包正常 | 脚本假设 YAML `stage` 是 dict、用 `workflow/` 子串误伤 `.workflow/`，或把部署后测试生成的 output 当成快照污染 | 先调用 `WorkflowArtifactInspector` 的 `yaml_summary` 和 `migration_manifest` 获取结构化事实；部署前快照洁净度与部署后测试产物必须分开判断。已有 inspector 能表达的检查禁止重写临时脚本 |
| 最终 checker 报固定 `output/README.md` 为 dirty | checker 的目录禁令与 acceptance 必需文件发生冲突 | 不得删除固定交付文件来迎合 checker；由共享 delivery contract 读取 acceptance，仅允许被明确声明的 README.md/.gitkeep/.keep，其他 output 运行产物保持禁止 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
