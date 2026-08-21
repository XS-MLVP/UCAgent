# Stage 22: prepare_and_verify_migration_packages

## 阶段目标

准备并验证洁净的全量与部分迁移包。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/install.py`
- `{TEST_WORKFLOW_ROOT}/.install/README.md`

## 详细执行步骤

1. 确认 requirements_manifest.milestones.release_ready=true 后，运行 python install.py --prepare both 和 python install.py --check。
2. 确认 full 包包含最终工具、checker、spec、测试、Guide_Doc、模板和配置；partial 包排除工具/checker及其 spec/test。
3. 确认两种包都不包含 .ucagent、.git、缓存、运行日志、output/ 和 reports/ 下的运行文件、旧 GuideDocs、.install/packages 嵌套内容；同时确认 requirements.txt、完整 docs/、可运行 input/example/、acceptance_rules 要求的空 output/ 等目录和测试夹具日志被保留。
4. 分别部署 full 和 partial 到临时目录并进行文件级验证；本阶段不要启动 UCAgent。
5. 记录包文件数量和洁净度结果，然后 Complete。
6. full/partial 包的保留与排除规则只能从 acceptance_rules.yaml 和固定 partial 排除策略推导，禁止临时脚本维护第二份清单；部署验证目录必须在验证结束后删除。
7. 生成包后立即执行边界预检：partial 不得出现 tools、checkers、`.workflow/tool_specs`、`.workflow/tool_tests`、`.workflow/checker_specs`、`.workflow/checker_tests` 或 `.workflow/checkers`；full/partial 都必须满足 acceptance_rules 的必需文件和目录。预检失败必须在本阶段修复并重新 package/check_package，不能把边界问题留给下一阶段。

## 临时诊断文件生命周期（强制）

本阶段允许把一次性诊断脚本、命令输出和部署试验目录放在工作区根目录的
`tmp/` 下，但这些内容只允许存在于“诊断期间”，不能进入迁移包，也不能作为
Checker 的最终输入。每次诊断前先列出 `tmp/` 当前内容并记录用途；诊断完成后，
必须删除本阶段创建的全部临时脚本、日志和临时部署目录，再重新使用
`WorkflowArtifactInspector(action='migration_manifest')` 和 `Check`。调用 `Check`
前必须再次用 `PathList(path='tmp', depth=-1)` 验证目录为空；如果存在任何
`diag_*.py`、命令输出或临时目录，先清理再检查，不能通过增加更多诊断脚本来
覆盖失败。禁止把诊断脚本复制到 `workflow/`、`.install/` 或包目录中。若需要
保留证据，应把摘要写入阶段 journal 或规划记录，而不是保留原始临时文件。

失败重试也必须遵循同一生命周期：先读取完整 Checker 返回值，复用或覆盖已有
诊断材料，完成分析后清理 `tmp/`，再重跑同一个验证；连续失败时不得不断生成
未清理的临时文件。部署到系统临时目录的 full/partial 验证副本也
必须在本阶段结束前删除。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: prepare_and_verify_migration_packages
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/.install/manifest.json
  - {TEST_WORKFLOW_ROOT}/.install/packages/full/install.py
  - {TEST_WORKFLOW_ROOT}/.install/packages/partial/install.py
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `prepare_and_verify_migration_packages` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `generated_migration_package_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `make package` 或 `make check_package` 被旧白名单拒绝，Agent 准备创建 subprocess 包装脚本 | 把标准、无参数 Make 目标误认为必须通过临时 Python 执行 | 直接使用 `WorkflowCommandRunner` 的 `make package`、`make check_package`；禁止创建等价包装脚本。随后调用 `WorkflowArtifactInspector(action='migration_manifest')` 比对声明与真实包树 |
| acceptance 要求的文件未进入包，或 checker 硬编码清单与 acceptance 冲突 | install.py、临时脚本和 checker 各自维护必需文件列表 | `.workflow/acceptance_rules.yaml` 是 full/partial 必需公开路径的唯一来源；partial 仅按固定模式策略排除工具、Checker 及内部 spec/test，不能任意省略其他 acceptance 文件；在本阶段立即完成边界预检 |
| Checker 反复失败且 `workflow/tmp/` 出现本阶段产生的临时文件 | 诊断材料被留在工作区根级 `tmp/`，而迁移包 Checker 将非空 `tmp/` 判定为不洁净 | 先读取完整结构化 Checker 返回值，复用已有诊断材料完成分析；随后删除本阶段全部临时脚本、日志和部署目录，用 `PathList(tmp)` 确认为空，再重新调用 `WorkflowArtifactInspector` 和 `Check`。不要继续累积未清理的临时文件 |
| Checker 将 `input/example` 或工具/Checker 测试夹具中的 `logs/` 文件报告为 dirty | 共享洁净度规则把夹具内部的 `logs` 目录误当成运行时日志 | 确认路径位于明确的示例或测试夹具前缀下；这类源夹具应保留。维护者应修正共享 delivery contract 的豁免规则并增加回归用例，不要删除用户输入示例或测试样本来迎合 Checker |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
