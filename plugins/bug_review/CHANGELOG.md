
# Bug Review 工作流与版本记录

本文前半部分描述**当前实现**，后半部分按功能版本记录主要变化。版本对应关系为：`ANALYSIS_OVERVIEW.md` 的 V1 → `v1.0.0`、V2 → `v1.1.0`、V3 → `v1.2.0`。V1.1、V1.4、V2.1、V3.2 等是各组需求内部的迭代，不单独占用此处的次版本号。具体设计依据、试跑反馈和待验收事项仍以 [ANALYSIS_OVERVIEW.md](ANALYSIS_OVERVIEW.md) 为准。

本页的功能版本号用于整理工作流演进，不表示插件包已经按这些版本发布；`pyproject.toml` 当前仍声明包版本 `0.1.0`。历史迭代没有可靠的统一发布日期，因此版本标题不补写推测日期。本稿整理于 2026-09-27。

## 当前框架

Bug Review 一次处理一个 `inputs/workspace_<name>/` 模块。输入中的 Bug 摘要、详细分析、测试、Spec 和 RTL 是待核查资料；插件把分析文本和可运行测试准备到该模块独立的运行区，在不改动原始内容的前提下收集并重跑全部 pytest 用例。每个阶段由工作流指定目标、参考文件和输出文件，Checker 核对实际产物及证据；Skill 提供操作指导和脚本，波形取证使用 UCAgent 的 WaveInfo 与签名收据。

`review_index.json` 是本次运行的轻量索引：保存模块身份、原 Bug 身份、阶段状态和逐 case／Bug 记录路径。执行、归因、裁决、根因和覆盖率分别保存在独立记录中；原报告长文、Spec／RTL 原文及完整波形不复制进索引。报告从当前活动记录生成，HTML 是可重建的展示结果。

### 六阶段流程

| 阶段 | 核心工作 | 主要产物或变化 |
| --- | --- | --- |
| `full_replay` | 按当前 pytest 配置收集全部精确 node，建立原 Bug 身份骨架，重跑全集并逐项记录基线结果。 | `test_manifest.json`、`replay_summary.json`、`review_index.json`、逐 case 骨架。 |
| `case_triage` | 在阅读原 Bug 根因结论之前，逐个分析失败 case 的测试预期、规格预期、实际行为和环境质量。 | 逐 case 的 `failure_analysis`、`environment_review.json`；必要时记录定向复跑。 |
| `dut_evidence` | 对疑似 DUT 缺陷或时序争议分析有效事务窗口、关键信号和波形；按精确 case 身份附着签名收据。 | 逐 case 的波形结论、窗口、信号组、receipt ID 和 viewer URL。 |
| `report_reconcile` | 再对照原 `bug_summary.md`、`bug_analysis.md`，核实 Spec／RTL 候选、原声明关联、报告遗漏的失败和统计差异。 | 活动归因修订、case↔Bug 关联、`report_reconciliation.json`。 |
| `root_correlation` | 结合正确测试、波形、Spec 与 RTL 作逐 Bug 裁决；把相同首错和因果链的确认项归入同一根因。 | 活动 Bug 裁决修订、`root_causes.json`；原声明始终保留。 |
| `publish` | 从活动记录渲染并核验模块、失败 case、Bug 和源码预览页面，再发布模块入口并更新总门户。 | `report/index.html`、`report/cases/`、`report/bugs/`、`report/sources/`、`report_manifest.json`。 |

失败 case 可归因为环境、测试实现、Spec 理解、规格歧义、证据不足或 DUT 缺陷；一次失败本身不等于 Bug。原报告的 Bug 即使未复现也保留；充分排除 DUT 缺陷时复核置信度为 `0`，证据不足时保持未定。已确认的 DUT Bug 需要可复现的正确测试、有效签名波形、真实 Spec 要求和 RTL 因果链。

### 插件文件组织

| 位置 | 职责 |
| --- | --- |
| `Makefile`、`README.md` | 默认全模块和指定模块的运行入口、基本使用说明。 |
| `src/bug_review/workflows/analysis.yaml` | 六阶段任务、参考文件、输出文件、Skill 与 Checker 配置。 |
| `src/bug_review/workflow.py`、`inputs.py` | 输入发现、独立运行区准备、阶段核验与报告发布。 |
| `src/bug_review/review_*.py`、`tools.py` | 索引及逐项记录、重跑导入、归因事务、证据查询、裁决提交和工具接口。 |
| `src/bug_review/checkers/` | 阶段完成前的确定性校验。 |
| `src/bug_review/Guide_Doc/`、`skills/`、`templates/` | 运行时指导、阶段操作脚本和初始模板。 |
| `src/bug_review/reporting.py`、`lang/zh/report.json` | 报告页面、源码预览、中文文案及页面核验。 |
| `ANALYSIS_OVERVIEW.md` | 需求迭代、设计取舍、实跑反馈与后续规划。 |

### 输出目录：先看哪里

默认根目录为 `plugins/bug_review/output/`，可通过 `OUTPUT_ROOT` 配置。`make bug-review-analysis` 对 `inputs/workspace_*` 逐模块重新运行；`make bug_review_<name>` 只运行指定模块。每次运行都新建 `run-<id>`，公开的 `report/` 指向该模块已核验的运行结果；单模块重跑不改写其他模块的报告。

```text
output/
├── index.html                         # 所有已发布模块的入口
└── workspace_<name>/
    ├── report/                         # 当前公开报告，指向一次已完成运行
    │   ├── index.html                  # 模块概况、覆盖率、失败 case 和高置信 Bug
    │   ├── cases/                      # 失败 case 详情
    │   ├── bugs/                       # 每条 Bug 的裁决与证据详情
    │   ├── sources/                    # 被引用源码的全文预览与行段高亮
    │   └── report_manifest.json        # 页面和证据链接清单
    └── runs/
        └── run-<id>/                   # 本次运行的私有工作区
            ├── review_job.json         # 输入模块及运行配置快照
            ├── uc_test_report/         # 本次 pytest/toffee 的可写报告目录
            ├── .ucagent/               # 阶段状态和签名 WaveInfo 收据存储
            └── results/
                ├── review_index.json   # 当前活动记录与阶段状态的入口
                ├── test_manifest.json  # 本次收集的完整 case 集合
                ├── replay_summary.json # 全量重跑的逐项结果
                ├── environment_review.json
                ├── coverage.json
                ├── wave_signal_presets.json
                ├── cases/              # 初始逐 case 记录
                ├── attributions/       # 归因修订及其 case／对账记录
                ├── reviews/            # 逐 Bug 裁决与根因修订
                ├── report/             # 发布前的报告原件
                ├── inputs/             # 分析所需原文镜像
                ├── tests/              # 可运行测试副本
                ├── drafts/             # 尚未激活的草稿
                └── diagnostics/        # 收集失败时的完整日志
```

**阅读顺序**：看结论先打开 `output/index.html`，进入对应模块的 `report/index.html`，再点失败 case 或 Bug 详情。核查运行全集和缺口时看该次运行的 `test_manifest.json`、`replay_summary.json` 与 `environment_review.json`；追溯某条裁决时从 `review_index.json` 中的活动路径找到逐 Bug／case 记录和根因修订，不按 ID 猜测文件名。签名收据存于该次运行的 `.ucagent/waveinfo_receipts.json`，case 记录只保存收据引用与波形摘要。`report/` 只公开报告页面；`runs/` 保存运行记录、草稿和输入镜像。覆盖率数字只在 `coverage.json` 有可核实来源时展示，否则明确标示不可用。

## 版本变化

### v1.2.0 — V3：全量失败归因与证据报告

**当前功能基线；V3.0～V3.2 的代码已实现，真实模块的完整重跑与页面效果仍待本版验收。**

- 从“按原报告选择关联 case”改为按当前 pytest 配置收集并重跑**整个模块**；先分析每个失败 case，再阅读原 Bug 根因并对账。新增环境质量审查，明确测试错误、Spec 误读、环境故障和疑似 DUT 缺陷等不同归因。
- 工作流扩为六阶段。签名波形按索引中的精确 case 身份附着；`ApplyReceiptToCase` 复制收据和 viewer URL，`ValidateCaseRecords` 可随时核查逐 case 证据；裁决草稿可 dry-run 后整批提交。
- 原报告 BG 条目级 case 引用与报告级聚合清单分开保存。`CommitAttribution` 一次更新 Bug→case 与 case→Bug 关联；`CreateAttributionDraft` 预填原报告的 Spec／RTL 候选，`ReviewCaseDiff` 提供规范 case ID 的批量差集。相同根因的裁决共享标准 RTL 字段，逐字段诊断可定位不一致处。
- pytest 收集报告写入本次运行可写目录；失败保留完整日志且不建立权威索引，环境修复后可重试。公开报告与私有运行记录分区，发布后更新模块入口和总门户。
- 模块、case、Bug 页面使用中文。模块 Bug 主表只列 `confirmed` 且复核置信度不低于 `0.8` 的项，其他声明与裁决仍保留；Bug 页的 Spec／RTL 引用可打开报告内源码全文并高亮对应行段。

### v1.1.0 — V2：按模块重跑与分对象记录

**对应 V2.0～V2.1，已由 v1.2.0 的全量失败归因流程承接。**

- 增加默认全部模块重跑与 `make bug_review_<name>` 单模块重跑；每个模块使用独立 `runs/<run-id>/`，`output/index.html` 汇集已发布模块。
- 将单一大型 `bug_review.json` 拆为轻量 `review_index.json`、共享逐 case 记录、逐 Bug 裁决、根因及覆盖率记录。按 Bug ID 按需读取原报告与当前证据，降低长文和大 JSON 的传输负担。
- 增加批量源码行段核实、结构化裁决提交和修订查询；增强 WaveInfo 的查询诊断、收据查询和 case 身份定位。模块、Bug、失败 case 的三级报告从结构化记录生成并核验。

### v1.0.0 — V1：原报告 Bug 复核基础流程

**对应 V1～V1.4；其中的五阶段与单一 JSON 布局属于历史实现，现行流程见本文开头。**

- 建立“输入骨架 → 测试重跑 → 波形分析 → 证据关联与根因合并 → 发布报告”的基础复核链路，逐阶段声明产物并通过 Checker 门禁。
- 保留每条原 Bug 声明及原始置信度；允许记录新发现的 DUT Bug；排除 DUT Bug 时把复核置信度设为 `0`，确认项仅在 RTL 首错与因果链相同时合并根因。
- 引入阶段 Skill、可更新的复核笔记和 HTML 报告；后续 V1 内部迭代把准备范围收敛为分析文本、测试与 DUT 运行包，并曾以单一 `bug_review.json` 传递五阶段状态。

后续版本在本节顶部追加条目，记录实际新增、修改和移除的用户可见能力；尚未实现的需求继续写入 `ANALYSIS_OVERVIEW.md`。
