# Stage 16: generate_all_documentation_and_dependencies

## 阶段目标

批量生成、注册和验证全部文档与依赖清单。本文件是维护者根据历史运行经验维护的静态指导，不由运行中的 Agent 修改。执行阶段时必须先读取本文件，再处理业务产物。

## 前置输入与边界

必须逐项使用 `ReadTextFile` 读取配置声明的 reference_files；目录输入应先用 `PathList` 获取真实文件，再逐个读取。不得用搜索结果、自然语言总结或候选产物代替引用证据。

- `{WFGEN_DIR}/requirements_manifest.yaml`
- `{TEST_WORKFLOW_ROOT}/.workflow/guidedoc_specs/*.yaml`
- `Guide_Doc/guidedoc_generation_guide.md`

## 详细执行步骤

1. 先按文档依赖分组并建立组件完成清单。每批最多处理 3-4 个工具或 Checker；本批只读取本批注册信息、源码和 fixture，完成后立即写入对应开发者文档 spec。后续批次只读取两个 spec 中的标题和完成状态，禁止因上下文压缩重新读取已完成批次的源码。
2. 允许同一批中对不同组件并行读取和分析，也允许并行写入不同组件的 spec 区块；不得同时写同一 spec 区块、config.yaml、requirements.txt、共享清单或实现计划。每个批次完成后先从 spec 核对组件标题、路径、class_name、method、源码围栏和正文长度，再进入下一批。
3. 所有组件必须完成真实源码证据：每个章节正文以至少 500 个有效中文字符为目标并满足 300 个有效正文字符硬下限；必须分析实现文件、入口、关键代码、调用路径、字段、分支、异常、扩展点和测试。代码围栏只能逐字复制真实实现中连续 2-6 行非注释有效源码，不能使用伪代码、省略号、跨段拼接或 spec 推测。
4. 两个开发者文档 spec 全部完成后，**只调用一次** `WorkflowGuideDocGenerator`，传入全部受影响 spec_paths 和 `update_config=true`，生成全部 Guide_Doc 与 docs 文档并更新注册。正常流程禁止按组件、按 spec 或按文档重复调用生成器。
5. 生成全部文档后只运行一次 `make check_docs`，读取完整结构化结果，再调用 Check；无需搜索 Builder checker 源码，也不得调用 ChildWorkflowSupervisor。只有检查失败时，才修正对应 spec、重新调用一次生成器并重新运行一次 `make check_docs`。
5.1 生成器调用前先执行确定性的 spec 预检，一次性检查用户文档固定格式、契约标记、禁止占位词和最小正文长度；预检失败时不得调用生成器。预检通过后仍须由 `make check_docs` 检查实际 Markdown 与 runtime_contract、Makefile、config 的一致性，避免只验证 spec 不验证产物。
6. 根据 required_python_dependencies 生成 requirements.txt；required_system_dependencies 以注释说明安装方式，并同步生成环境配置 GuideDoc。生成器写入的 `GENERATED-FROM` 与 `SPEC-SHA256` 必须在生成后读取确认；禁止直接编辑生成 Markdown。

## 关键文件的最小可通过版本

本阶段最小通过版本必须同时提供真实产物、结构化验证证据和持续规划记录。不能只创建空文件或写“已完成”：

```yaml
stage: generate_all_documentation_and_dependencies
status: passed
artifacts:
  - {TEST_WORKFLOW_ROOT}/Guide_Doc
  - {TEST_WORKFLOW_ROOT}/docs
  - {TEST_WORKFLOW_ROOT}/requirements.txt
checks:
  - name: configured_checker
    passed: true
    evidence: 实际日志、结构化报告或测试输出路径
```

实际文件必须采用本阶段 reference、output 和 Checker 约定的 schema；上例只展示所有阶段都必须具备的最小证据外形，不能替代业务内容。

## 常见示例

一次正常执行会先读取本指导、全部业务 reference 和 `wfgen/workflow_implementation_plan.md`，完成 `generate_all_documentation_and_dependencies` 的真实工作，读取 Checker 或测试输出确认结论，然后调用 `WorkflowPlanAppender` 追加本阶段的决策、产物、问题和后续约束。只有规划追加成功且配置中的 Checker 全部通过，才调用 `SetCurrentStageJournal` 和 `Complete`。

## Checker 与通过条件

- `generated_guidedoc_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `generated_user_docs_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。
- `generated_dependency_check`：必须读取真实 artifact 并满足配置及本指导规定的结构化契约。

## 常见问题

| 现象 | 常见根因 | 诊断与正确处理 |
|---|---|---|
| Complete 提示 reference 未读取 | 只做了搜索或读取了替代路径 | 按配置逐项调用 ReadTextFile；目录先 PathList 后逐文件读取 |
| Checker 连续失败 | 产物只满足文件存在，没有满足字段或证据契约 | 阅读完整 Checker 返回值和本阶段最小版本，修正生成逻辑后重跑；不得删除 Checker |
| `stale_generated_documents` | 修改了 spec，但没有再次调用生成器，当前 Markdown 仍携带旧摘要 | 重新调用 WorkflowGuideDocGenerator；不要直接编辑 Markdown，也不要继续重复 Check |
| spec 已修正但错误内容没有变化 | Checker 检查的是旧的生成文档，或只生成了部分不相关 spec | 确认生成器参数包含被修改的 spec，读取输出中的 `GENERATED-FROM` 和 `SPEC-SHA256` 后再检查 |
| 多个组件同时缺少标签 | 直接沿用了上一阶段的设计摘要，或使用自然语言近义词，没有补齐最终文档固定标签 | 回到 spec 按本阶段最终模板逐组件补齐十类标签、真实源码与分析，重新生成；文档总览不能替代组件章节 |
| `source_evidence_errors` 只剩一个组件且多次不变 | 围栏两端都来自真实源码，但中间省略了方法、注释或语句；Checker 匹配整个围栏，不会只寻找其中任意两行 | 删除该大围栏，重新读取实现文件并逐字复制一个最小的连续 2-6 行片段。不要跨方法拼接；需要多处证据时拆成多个各自连续的围栏。重新调用生成器后再 Check |
| 反复在围栏附近增删空行仍不通过 | 空白规范化不会补回被省略的源码，问题是代码序列不连续而非 Markdown 间距 | 停止调整空行和围栏缩进；对照真实文件逐行确认围栏内相邻两行在源码中也相邻，优先使用短片段替换整个围栏 |
| operation GuideDoc 语义完整但生成器逐份报告缺少输入契约 | `Inputs` 或 `Usage` 只写了具体示例、`input/example/` 或输出路径，没有逐字包含机器契约 `input/<TARGET>/` | 对 `operation_contract=true` 的 spec，在 Inputs 和 Usage 中逐字写入 `TARGET`、`input/<TARGET>/`、`input/example`、`output/`、`make check_example`、`make run`；技术说明文档不得机械复制这些运行契约 |
| 规划检查失败 | 覆盖了旧内容、阶段顺序错误或记录过短 | 保留原文件，使用 WorkflowPlanAppender 追加当前唯一阶段记录 |
| 为了通过而修改候选结果 | 把工作流缺陷误当成一次性产物问题 | 修正生成规范、工具或 Checker，并保留失败证据；禁止代替工作流手工伪造结果 |

## FAQ 维护规则

维护者在一次运行结束并确认根因后，才可修改本文件。新增条目必须包含可观察现象、原始 Checker 信息、可复现条件、根因、正确修改位置、回归方法和适用版本；不要记录仅对某次 workspace 有效的临时路径或手工补丁。
