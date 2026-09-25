
# Bug Review 分析工作流与优化需求

本文是 `bug_review` 分析工作流的维护入口。修改阶段、输入输出、Bug 裁决或报告契约时，先更新本文，再同步工作流 YAML、Guide_Doc、实现与测试。工作流概述说明长期目标；版本章节分别记录现行契约和历史变更。

## 工作流概述

Bug Review 复核已有验证报告中的 Bug 声明：确定输入与待查对象，在隔离工作区副本中重跑现有测试，分析失败与波形，结合原始规格、测试代码和 RTL，判断声明是否为真实 DUT Bug，最后关联证据并发布报告。具体阶段划分、裁决字段和输出文件由对应版本定义。

## 版本记录

这里的 V0、V1 是**分析工作流需求版本**，不等于 `pyproject.toml` 中的插件发行版本，也不表示运行产物已有同名版本字段。

| 版本 | 状态 | 新增或修改的主要内容 | 详细契约 |
| --- | --- | --- | --- |
| V0 | 历史实现，已替换 | 九阶段 benchmark 分析：输入发现、解析、重跑、波形、语义比较、失效模式、根因审查、GT 对齐和发布。 | [V0 历史实现与迁移关系](#v0-历史实现与迁移关系) |
| V1 | 五阶段基础契约 | 调整为五阶段；先形成原 Bug 骨架；纳入新失败；同根因合并且保留所有原声明；排除 DUT Bug 时复核置信度归零；逐阶段明确 `output_files`；支持可配置输出根和多工作区报告。 | [V1 输入与裁决](#v1-输入与裁决)、[V1 五阶段工作流程](#v1-五阶段工作流程) |
| V1.1 | 现行代码契约；真实 DUT 全链路运行待验证 | 增加逐阶段内容校验、复核笔记模板和可选的笔记更新 Skill；权威裁决与证据仍由五阶段工作流产生。 | [V1.1 Checker、模板与 Skill](#v11-checker模板与-skill) |

后续变更在此表增加新版本，并在对应版本章节记录相对上一版新增、修改和移除的契约及实施状态。更新旧版本的事实错误可以直接更正；不要把未落地的目标写成已实现功能。

## V1 输入与裁决

V1 重跑发现的新失败也进入复核。最终交付每个 Bug 的裁决、同根因合并关系、可追溯证据和 HTML 报告。

输入约定为 `inputs/workspace_*`，允许多个 DUT 工作区；`workspace_raid_dec_top` 是输入结构样例。每个工作区可包含 `unity_test/{DUT}_bug_summary.md`、`unity_test/{DUT}_bug_analysis.md`、测试源码、规格、RTL、原始测试报告和历史波形。缺失输入须保留缺失状态与明确诊断，不能把缺失报告当作全部通过。原始输入及其测试、fixture、参考模型和 RTL 始终只读；复核不修补它们。输入保护使用 UCAgent 已有的工作区读写限制和隔离副本机制，不另建源码修改控制系统。

输出根目录默认 `plugins/bug_review/output/`，并且可配置。每个 `workspace_*` 有独立分析产物与 HTML，输出根目录提供跨工作区索引。`{OUT}` 表示 UCAgent 工作流解析后的产物目录；配置输出根目录时，工作流、Checker 和报告链接必须使用同一解析结果。发布与输入目录分离。

### 裁决规则

- **原报告声明不得删除。** 每个原始 Bug ID 保留原文、原置信度、来源位置、关联 BG/ROOT/CK/TC 和复核结论。确认不是 DUT Bug 时，复核置信度为 `0`；原置信度仍作为历史输入事实保存。
- **新增失败可以形成新增 Bug。** 新增记录标记 `origin: discovered`，原报告记录标记 `origin: reported`。新失败同样经过测试正确性、规格、波形和 RTL 审查，不能因一次失败直接成为 Bug。
- **复现状态与责任归因分开。** 再次失败、通过、无法执行、收集失败等属于执行结果；确认 DUT Bug、排除 DUT Bug、证据不足属于裁决。未复现不自动等于误报，失败也不自动等于 DUT Bug。证据不足的复核置信度留空，不用 `0` 冒充已排除。
- **相同根因合并展示，成员保留。** 合并依据是 RTL 首错位置、因果链以及测试和波形证据，不是名称相似、同一文件或同一失败现象。一个根因组可覆盖多个原 Bug、BG、CK 和 TC；每个成员的独立声明、裁决与证据仍可检索。
- **证据必须闭环。** 确认 DUT Bug 需要正确的测试预期、可定位的规格要求、真实失败事务、有效时序窗口中的波形观察，以及能解释现象的 RTL 路径。测试、fixture、模型、驱动、复位、采样或环境问题应如实归因。原始文档文字和历史波形只能提供线索，不能代替本次执行证据；不得编造 receipt、信号或 viewer 链接。

## V1 五阶段工作流程

以下五阶段按顺序执行，已同步到 `workflows/analysis.yaml`、Guide_Doc、阶段调度和报告发布。每阶段都声明 `reference_files`、`output_files` 与 Checker；Agent 在 Check 通过后 Complete。

| 阶段 | 任务和验收重点 | 必需 `output_files` |
| --- | --- | --- |
| `inventory` | 发现并冻结全部 `workspace_*`；解析原 Bug、BG/ROOT、CK、TC 与 Spec/RTL 引用，生成可阅读的复核骨架。每个原始声明恰好有一个清单身份，允许一个声明关联多个路径；无法解析的引用显式列出。 | `{OUT}/input_inventory.json`；`{OUT}/workspaces/*/bug_outline.md`；`{OUT}/workspaces/*/bug_inventory.json` |
| `replay` | 对隔离副本中的现有 UnityTest 用例执行一次权威重跑，覆盖原报告关联用例并发现新失败。按精确 pytest node ID 记录原结果、本次结果、失败阶段、日志和运行环境；零用例、超时、报告缺失、收集/环境错误阻止成功结案。 | `{OUT}/workspaces/*/replay_results.json`；`{OUT}/workspaces/*/case_reviews.json` |
| `waveform` | 对需要裁决的失败用例读取本次波形，核对驱动边沿、请求接受、响应有效、延迟、事务归属、规格预期与首次分歧；记录信号和时间窗口。确有 setup/teardown/collection 诊断的环境失败可说明免波形原因。 | `{OUT}/workspaces/*/waveform_reviews.json`；`{OUT}/workspaces/*/waveform_evidence.json` |
| `correlate` | 汇合原声明、新失败、逐用例归因、波形、Spec 和 RTL；裁决每个 Bug，按证据合并同根因成员，保留被排除的原 Bug 并置复核置信度为 `0`。根因组和成员间双向可追溯。 | `{OUT}/workspaces/*/bug_reviews.json`；`{OUT}/workspaces/*/root_groups.json` |
| `publish` | 从冻结的结构化裁决与证据生成每个工作区的报告数据、Bug 详情和 HTML，以及跨工作区总索引。无确认 Bug 时仍交付原声明的裁决和有效页面。 | `{OUT}/workspaces/*/report_data.json`；`{OUT}/workspaces/*/index.html`；`{OUT}/index.html` |

`output_files` 是文件存在性门禁，不是完整性证明：UCAgent 对一个通配模式只要求至少命中一个文件。因此每阶段 Checker 必须根据冻结的 `input_inventory.json` 核对**每个**工作区的必需产物、对应身份和内容；不能因为一个 DUT 的文件满足通配模式就让其他 DUT 跳过。发布阶段还须验证每个 Bug 详情入口存在、链接指向相应证据、报告计数来自结构化数据。

### 1. 输入清单与骨架

先从 `bug_summary.md` 建立逻辑 Bug 清单，再从 `bug_analysis.md` 提取 FG/FC/CK/BG、TC、ROOT 与中央波形引用。样例摘要列出 26 个逻辑 Bug，而一个逻辑 Bug 可跨多个 CK/TC；骨架必须保存多对多关系，不能把每个 BG 出现位置都算成新 Bug。摘要中的 RTL 行号与 Spec 位置只是候选，需检查目标文件和范围是否仍存在。骨架为每个声明列出已知信息、待核实问题及计划重跑的 TC，使后续阶段有明确任务列表。

`input_inventory.json` 记录工作区身份、输入快照、关键文件可用性和每个 DUT 的处理状态。`bug_inventory.json` 提供机器可读身份与引用；`bug_outline.md` 展示同一骨架，供 Agent 和用户检查。解析失败须指向具体文件、标记或行，并给出继续分析所需的动作。

### 2. 测试重跑与逐用例归因

使用 UCAgent 已有 UnityTest 执行能力，在隔离副本中运行原有测试。应确定一次权威重跑及其报告路径；不要让准备步骤和 `replay` 阶段各执行一轮却混用结果。执行范围覆盖已有用例，才能发现原报告外的新失败。保留原始报告和本次结果的精确关联，包括参数化实例及 setup/teardown/collection 失败。原始报告缺失不妨碍尝试重跑，但缺失状态必须可见。

对每个失败先独立推导规格预期，再检查测试断言、API/driver、fixture、参考模型、复位、握手、Step 与采样时机。`case_reviews.json` 保留精确输入、规格预期、测试预期、DUT 实际结果、验证正确性判断和证据位置。输入代码被冻结；发现测试或环境问题时记录排除或未定原因，不通过改写测试来制造 Pass。

### 3. 波形分析

复用当前 `BugReviewWaveInfo` 对 UCAgent `WaveInfo` 的封装和默认 UnityTest 工作流中的取证规则。最终证据必须使用真实的测试节点、信号路径、时间窗口和工具生成的证据 ID；信号集合覆盖相关输入、输出、协议控制、实际时钟（若有）及解释功能选择或错误传播的关键路径。测试日志周期与波形 step 通过时钟出现序号和事务上下文对齐，不假设编号相等。

一次数据不一致只有在事务被接受、输出有效且达到规定延迟后才可能支持 Bug 结论。波形不可得、信号不足或事务归属不明时记录明确原因和缺失证据，不凭历史记录补造本次取证。一个 TC 关联多个 Bug 时共享该 TC 的波形证据，并为每个 Bug 分别说明它支持或反驳的结论。

### 4. 证据关联与根因合并

逐 Bug 给出复现状态、责任归因、规格依据、测试正确性、首次可观察分歧、RTL 首错与传播路径、支持证据、反证及剩余不确定性。`bug_reviews.json` 保留每条原始声明和新增声明；`root_groups.json` 定义根因组与全部成员。合并后详情页可以共享根因解释，但不能丢失成员各自的 TC、CK、波形和裁决。

确认不是 DUT Bug 的原声明保留完整记录并令 `review_confidence: 0`。确认 DUT Bug 才赋予非零复核置信度；证据不足保留未定状态。置信度表达证据完整度，不由失败用例数量、原报告置信度或 GT 命中情况直接推导。

### 5. 报告与 HTML

先生成 `report_data.json`，再渲染 HTML；页面不能另造事实。每个工作区的索引显示执行状态、确认/排除/未定数量、根因组、原始声明和新增发现。每个 Bug 详情回答：原声称是什么、合法输入与规格预期是什么、本次观察是什么、波形在哪个有效窗口支持或反驳结论、RTL 如何导致现象、还缺什么证据。关联日志、Spec/RTL 片段和完整波形入口可展开查看。总索引列出全部工作区及其状态，单个 DUT 失败不能让其他 DUT 的状态消失。

## V0 历史实现与迁移关系

V0 的 `analysis.yaml` 有九个阶段，`BugReviewStageChecker` 按阶段名检查产物。Agent 通过 `BugReviewRunStage`、`BugReviewTasks`、`BugReviewSubmitResponse`、`BugReviewStatus` 推进任务；波形由 `BugReviewWaveInfo` 包装。启动前的 `input_preparation.py` 复制输入并运行测试，阶段内又可能回放。V1 已将入口改为五阶段，并把唯一权威重跑放在 `replay`。

| V0 阶段 | 已实现的职责与主要产物 |
| --- | --- |
| `inputs` | 发现 DUT 与运行、冻结范围；`input_inventory.json`、`analysis_scope.json`。 |
| `parse` | 解析测试、声明、规格与 RTL 关联；`parsed_inputs.json`。 |
| `replay` | 重跑并审查失败用例；`tasks/*/replay/reviews.json`。 |
| `waveform` | 复核失败波形；`tasks/*/waveform/reviews.json`。 |
| `semantic` | 比较候选 Bug 的语义关系；`tasks/*/semantic/comparison_result.json`。 |
| `failure_mode` | 审查根因失效模式；`tasks/*/failure_mode_complete.json`。 |
| `root_appeal` | 审查 RTL 根因与聚类；`tasks/*/root_review/result.json`。 |
| `alignment` | 报告根因与 GT 对齐；`tasks/*/analysis.json`。 |
| `publish_analysis` | 发布分析清单、报告数据及 HTML；`analysis/analysis_manifest.json`、`analysis/dut_*/report_data.json` 和详情页。 |

V1 对上述阶段的调整如下：

| 当前阶段 | 目标位置 | 迁移重点 |
| --- | --- | --- |
| `inputs`、`parse` | `inventory` | 先建立原报告 Bug 骨架和冻结输入范围，再生成逐 TC 工作项。 |
| `replay` | `replay` | 确定唯一权威重跑，收集新失败并分开保存执行结果与归因。 |
| `waveform` | `waveform` | 继续复用真实波形工具与签名证据，按 Bug 关联 TC。 |
| `semantic`、`failure_mode`、`root_appeal` | `correlate` | 以证据判断同根因并保留原声明身份；多轮审查只有在具体裁决需要时使用。 |
| `alignment` | 不作为复核门禁 | GT 对齐可服务独立评分，不能决定报告 Bug 是否真实。 |
| `publish_analysis` | `publish` | 先生成结构化裁决，再生成逐 Bug 与跨工作区 HTML。 |

V0 的 `plugin.py` 只注册 `analysis`，独立评分入口始终没有接通。V1 移除了未注册的评分工作流、Guide 和 Make 目标，也移除了不再参与 V1 的评分配置、报告服务、任务执行器及旧 benchmark 实现。报告解析和持久化证据所需的模块保留在 `analysis_core/`。

## V1 文件职责与目标结构

参考 `plugins/DesignWithPPA/src/design_with_ppa/` 的包组织及 `workflows/repo-module-tdd.yaml` 对每阶段任务、参考文件、输出文件和 Checker 的声明方式。借鉴职责分界，不为目录形式迁移所有代码。

| 当前文件或目录 | 当前职责 / 优化方向 |
| --- | --- |
| `ucagent-plugin.toml`、`pyproject.toml` | 源码发现、安装入口、依赖和随包资源；路径调整须同步打包清单。 |
| `src/bug_review/plugin.py`、`adapter.py` | 注册分析工作流、工具和 Checker；将五阶段与解析后的输出配置接入。 |
| `src/bug_review/workflows/analysis.yaml` | 声明阶段任务、`reference_files`、`output_files` 与 Checker；以目标五阶段为准。 |
| `src/bug_review/Guide_Doc/analysis.md` | 给执行阶段的 Agent 提供可操作的任务和产物格式；与本文契约一致。 |
| `src/bug_review/inputs.py`、`workflow.py` | 发现 `inputs/workspace_*`、冻结输入清单并在 `replay` 创建隔离执行副本。 |
| `src/bug_review/test_execution.py`、`waveform.py`、`case_analysis.py`、`tasks.py` | 重跑、真实波形取证、逐用例复核和任务状态。 |
| `src/bug_review/analysis_core/` | V1 实际使用的报告解析、测试报告解析及持久化证据模块。 |
| `tests/` | 验证多 workspace、空/缺失输入、重跑失败、波形证据、根因合并、置信度零和 HTML 链接。 |

多个插件可以在同一次 UCAgent 启动中通过重复 `--plugin` 激活，共享已注册的工具与 Checker；一次启动仍只选择一个 `--plugin-workflow`。加载 DesignWithPPA 不会自动让 Bug Review 的 Python 代码调用它的工具。直接复用其他插件的库时，应显式声明包依赖和稳定接口。

## V1 实现与验证

1. **输入。** 已定义原 Bug、新发现、精确 TC、原/复核置信度、执行状态、裁决与根因组关系。`workspace_raid_dec_top` 的输入清单解析出 26 个逻辑 Bug 和 56 条关联测试引用；Spec 候选从 CK 行映射提取。
2. **阶段。** 已同步五阶段 YAML、Guide_Doc、调度和 Checker；每个通配 `output_files` 另由 Checker 按冻结工作区清单逐项核验。无 Bug 或无新失败可生成空集合产物。
3. **重跑与波形。** 已将正式测试执行放在 `replay`，复用 UCAgent 测试和 WaveInfo 工具；执行错误、缺失波形与未定裁决保留明确状态。
4. **根因与报告。** 已实现原声明保留、非 Bug 复核置信度 `0`、按 RTL 位置、首错和因果链合并确认的 Bug，以及结构化报告、逐 Bug HTML 和跨工作区索引。
5. **入口与组织。** 已把输入、输出根配置和插件 Make/README 对齐；包改为与 DesignWithPPA 相同的 `src/` 布局。未接通的评分入口、旧准备脚本及 V1 无关的评分和 benchmark 资源已移除。

## V1.1 Checker、模板与 Skill

- `checkers/analysis.py` 在阶段文件哈希和逐工作区存在性校验之外，核对输入 Bug 身份、报告测试覆盖、需复核用例的波形覆盖、根因成员关系，以及发布报告的计数和详情链接。发现遗漏时拒绝 Complete，并指出对应工作区与产物。
- `templates/analysis/bug_review_notes.md` 初始化可持续编辑的 `notes/bug_review_notes.md`。人工记录区不随摘要更新而丢失；笔记不属于权威 Bug 证据，也不作为阶段门禁。
- 可选的 `skills/review-notes/` 从已完成阶段的结构化产物刷新笔记中的阶段摘要。脚本使用 `.ucagent/runtime_config.json` 的解析后 `OUT`，不执行测试或改写裁决。Skill 未启用时，Agent 直接阅读相同阶段产物并使用普通文件工具记笔记；Checker 标准一致。

完成优化的判据是：单个及多个 `workspace_*` 均可从输入到 HTML 完整执行；原报告每条 Bug 都有保留的裁决，新失败可新增，同根因可合并而不丢成员，非 Bug 的复核置信度为 `0`；输入源码未被改写；每个阶段的声明文件与每个工作区的实际产物一致；报告结论可回溯到本次测试、波形、Spec 和 RTL。当前聚焦测试覆盖这些数据和阶段边界；真实 DUT 的完整回放与波形裁决仍需在可加载插件的 UCAgent 运行环境中执行。插件最低版本要求保持 `UCAgent>=26.9.2.dev6`，与 DesignWithPPA 一致；RTL2Spec 要求 `>=26.9.2.dev14`。本次使用的仓库版本为 `26.6.25.dev3`，因此这里的插件加载校验被版本门禁拒绝，不能据此宣称完成全链路运行验证。
