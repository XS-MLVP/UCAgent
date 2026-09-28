
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
| V1.1 | 已实现 | 增加逐阶段内容校验、复核笔记模板和可选的笔记更新 Skill；权威裁决与证据仍由五阶段工作流产生。 | [V1.1 Checker、模板与 Skill](#v11-checker模板与-skill) |
| V1.2 | 已实现，后被 V1.3 替换 | 曾加入自动推进阶段工具及五个阶段 Skill；本版保留为迭代记录。 | [V1.2 阶段 Skill 与波形取证](#v12-阶段-skill-与波形取证) |
| V1.3 | 已实现；被 V1.4 取代 | 移除 Bug Review 自定义阶段和任务工具；阶段 Skill 直接指导 UCAgent 原生工具；准备阶段曾完整复制输入工作区；各阶段分别写入多个 JSON。 | [V1.3 原生工具驱动的阶段](#v13-原生工具驱动的阶段) |
| V1.4 | 已实现；已有一次 `workspace_raid_dec_top` 实跑反馈 | 不复制完整工作区；只准备分析文本、测试目录和 DUT 运行包；RunTestCases 只运行 JSON 选择的用例；五阶段更新同一 JSON；HTML 直接从该 JSON 渲染。 | [V1.4 最小输入副本与单一复核 JSON](#v14-最小输入副本与单一复核-json) |
| V2.0 | 代码已实现；已有使用者试跑反馈，问题尚未逐项独立复现 | 默认重跑全部模块，`make bug_review_<name>` 只重跑指定模块；`output/` 顶层提供总索引，各模块独立保存状态和报告；收敛参考文件门禁，改进 JSON 更新、诊断与波形证据查询。 | [V2.0 按模块重跑与工具体验](#v20-按模块重跑与工具体验) |
| V2.1 | 已有 `workspace_raid_enc_top` 试跑反馈，后被 V3.0 取代 | 将单一大 JSON 拆为轻量索引与按 Bug/case 存放的复核记录，按 Bug ID 按需汇集原文和证据；改进波形诊断、引用核实、裁决提交与三级报告。 | [V2.1 试跑反馈与优化规划](#v21-试跑反馈与优化规划) |
| V3.0 | 代码已实现，待真实模块试跑验收 | 对选中模块全量重跑并先分析失败 case；对照原报告、合并 DUT 根因；修复收据转写、身份映射、草稿校验和发布入口，明确验证环境质量及最终报告目录。 | [V3.0 全量失败归因与环境质量](#v30-全量失败归因与环境质量) |
| V3.1 | 代码已实现，待真实模块验收 | 修正原报告 case 关联权威来源；将归因关联作为一次校验与提交；减少逐文件 SHA 操作；自动完成发布状态；完善模块与详情页的层次、配色和输出目录写入。 | [V3.1 归因事务与报告呈现](#v31-归因事务与报告呈现) |
| V3.2 | 代码已实现，待真实模块验收 | 统一收集与执行的可写报告路径、失败诊断和重试；批量准备原报告候选及 case 差集；明确共享根因和阶段已读证据；最终报告改为中文、高置信 Bug 列表与可高亮的源码全文预览。 | [V3.2 收集环境、对账与报告阅读](#v32-收集环境对账与报告阅读) |
| V4.0 | 代码已实现，待真实模块试跑验收；功能版本 `v1.3.0` | 脚本仅创建格式，LLM 根据原文填写 BG／FC／CK 层级和 case 归属；允许有来源的关联纠错；缩短波形、裁决和阶段取证的重复操作。 | [V4.0 主张归属与长流程体验规划](#v40-主张归属与长流程体验规划) |

后续变更在此表增加新版本，并在对应版本章节记录相对上一版新增、修改和移除的契约及实施状态。更新旧版本的事实错误可以直接更正；不要把未落地的目标写成已实现功能。

## V1.4 最小输入副本与单一复核 JSON

V1.4 将阶段状态、Bug 主张、证据、执行、裁决、根因关系和报告数据合并到一个工作区级 JSON。它替换 V1.3 的多阶段 JSON 输出和完整输入工作区复制。

### 输入与复制边界

- `inventory` 分析原始 `inputs/workspace_<name>/unity_test/<DUT>_bug_summary.md` 与 `<DUT>_bug_analysis.md`。因为 Agent 文件工具限定在工作区内，准备步骤只把报告、Markdown/HDL/line-map 文本镜像到 `{OUT}/inputs/workspace_<name>/`，LLM 从该镜像读取并把源工作区相对路径写入 JSON。
- 输出中只准备分析所需的 Markdown/HDL/line-map 文本、UnityTest cases 目录及 helper/fixture，以及 DUT 可导入的仿真 Python 包和运行库；不复制完整工作区、coverage、旧波形、`.ucagent` 或无关二进制产物。
- `replay` 只对 `bug_review.json` 中明确选择的 TC 调用默认 `RunTestCases`。允许逐例或小批量重跑；不为达到全量覆盖而重跑无关用例。
- 源工作区中的 summary、analysis、Spec、RTL 和测试均只读。证据 JSON 保留原始源文件路径、行范围和实际测试 node ID；复制后的测试路径另存为执行定位信息。

### 单一 JSON 契约

每个工作区仅维护一个权威文件 `{OUT}/workspaces/<workspace>/bug_review.json`，schema 为 `bug_review.v3`。它是阶段间唯一传递状态，也是 HTML 发布的数据源。inventory Skill 脚本创建 JSON 骨架；报告 Skill 脚本直接从该 JSON 渲染 HTML。Bug 语义、证据选择、测试正确性、裁决和根因关系由 LLM 阅读输入副本后填入或更新 JSON。Checker 逐阶段校验 JSON 当前状态、源 Bug 保留、case 执行、WaveInfo 签名 receipt、根因关系和 HTML 链接。

JSON 顶层包含 workspace/source 元数据、`stage_status`、`suspected_bugs`、`cases` 和 `root_causes`。`suspected_bugs` 每项对应摘要中的一条疑似 Bug；`bug_summary` 保留该条原始摘要行及字段，`evidence` 汇集详细分析中的主张和关联证据，包括 Spec 位置、FG/FC/CK 检查点、TC、测试代码与 RTL 首错/传播路径。仅在详细分析中出现而摘要没有对应项的声明，作为额外原始条目保留并标明其来源。`cases` 以规范化 TC node ID 为键，避免同一 TC 关联多个 Bug 时重复保存执行与波形记录；Bug 项通过 case ID 引用它。裁决字段保存 verdict、复核置信度、依据和 root ID。原始声明和置信度始终保留；`refuted` 的复核置信度必须是 `0`，不能删除该项。相同 RTL 首错及因果链的确认 Bug 共享一个 root cause，成员仍各自保留。

### 五阶段工作流与产物

| 阶段 | 操作 | 必需产物 |
| --- | --- | --- |
| `inventory` | 读取输入工作区原始 summary 和 analysis；调用 inventory Skill 创建 JSON 空骨架，LLM 填充每条疑似 Bug、声明和待查证据；保留报告中未能对应的条目。 | `{OUT}/workspaces/*/bug_review.json`（`stage_status.inventory=complete`） |
| `replay` | 根据 JSON 选择相关 TC；在 `{OUT}/tests/workspace_<name>/` 的 UnityTest 副本中，直接调用 UCAgent `RunTestCases` 逐例或小批运行，并在 JSON 写执行状态和测试正确性分析。 | 同一 `bug_review.json`（包含所选 case 的 replay 与 test review） |
| `waveform` | 对复现且测试正确的可疑 DUT 失败直接调用默认 `WaveInfo`；在 JSON 记录原始结果、receipt、信号组、窗口、对齐和事务分析。 | 同一 `bug_review.json`（包含 case waveform evidence） |
| `correlate` | 更新每条原始/新发现 Bug 的裁决和置信度；仅按相同 RTL 首错与因果链合并确认项的 root cause。 | 同一 `bug_review.json`（完整 decisions 与 root causes） |
| `publish` | 对 JSON 执行结构校验，再由报告 Skill 脚本读取同一 JSON 生成详情页、工作区索引和总索引；HTML 不再依赖另一个 `report_data.json`。 | 同一 `bug_review.json`；`{OUT}/workspaces/*/index.html`、Bug 详情页、`{OUT}/index.html` |

准备清单格式为 `bug_review_job.v4`；不同输入或旧版准备记录必须使用新输出目录，避免旧多文件状态混入当前 JSON。阶段 `output_files` 可重复声明 `bug_review.json`，但每阶段 Checker 校验本阶段字段，不能把文件存在或 LLM 自报状态当成完成证明。HTML 是可再生成的展示物，不作为裁决事实源。

## V2.0 按模块重跑与工具体验

V2.0 依据 `workspace_raid_dec_top` 的一次实跑反馈实现；新布局已有使用者试跑反馈，问题记录于 V2.1，尚未逐项独立复现。此前运行的 Agent 报告：26 条原声明、55 个关联 case；选择重跑 33 个 case，形成 33 个 WaveInfo receipt；26 条裁决归入 23 个根因组，并生成总索引和 26 个详情页。这些数字是 V1.4 运行的反馈基线，不代表对裁决正确性的独立复核。运行耗时约 2 小时 46 分；V2.0 重点减少重复执行、人工恢复和格式试错，保留真实测试、波形与 Spec/RTL 证据门禁。

### 1. 用 Make 选择重跑范围

现有 Makefile 已有 `make bug_review_<name>`，但它只能在新的输出根下选择单模块。准备代码把 `source_runs` 冻结在输出根的 `review_job.json`：已有 A 的输出后，选择 B 会因任务范围不同被拒绝；同一输出根的 UCAgent 阶段历史也可能使 B 直接进入已完成状态。因此 V2.0 要保留这条简单命令，并打通“同一输出根下独立启动指定模块”，不增加自动扫描完成状态、输入指纹或跳过调度。

- `make bug-review-analysis` 默认选择 `inputs/workspace_*` 下的全部模块，并对每个模块重新执行五阶段；已有结果不改变默认重跑范围。
- `make bug_review_<name>` 只选择 `inputs/workspace_<name>`，执行该模块的五阶段；重复调用即重新复核该模块。两个入口都使用可配置的 `OUTPUT_ROOT`，默认仍是 `plugins/bug_review/output/`。
- `output/` 顶层只作为跨模块入口，目标布局为 `output/index.html` 和 `output/workspace_<name>/` 子目录。每个模块的子目录保存自己的 UCAgent 阶段历史、准备清单、测试副本、签名 receipt、`results/bug_review.json`、`results/index.html`、Bug 详情页及页面引用的源文件；其余模块的状态不混在根目录。
- 同一模块每次重跑在该模块目录下新建独立执行区，例如 `output/workspace_<name>/runs/<run-id>/`。执行成功后用 `output/workspace_<name>/results` 链接到本次执行区的 `results/`，再重建 `output/index.html`；失败则保留此前发布的有效页面。签名 receipt 仍留在对应执行区，已发布结果保留其真实作用域，后续核验不把 receipt 当成可移动文件。
- 重新发布只替换本次选中的模块结果，其他模块的 JSON、详情页、测试记录和 receipt 不改写。总索引根据已发布且可打开的模块页面生成，链接到 `workspace_<name>/results/index.html`。V2.0 每次工作流只处理一个模块，运行中权威 JSON 为 `{OUT}/bug_review.json`；阶段 YAML、Checker、Guide、Skill 和报告脚本同步调整此路径。
- 准备清单改为本次模块执行区私有，不能再让共享 `output/review_job.json` 的冻结 `source_runs` 阻止新模块。Make 在启动前显示本次选中的模块及输出子目录，避免把单模块命令误认为全量运行。

现有 V1.4 `output/results/workspaces/*` 与根目录 `.ucagent` 属于旧布局。签名 receipt 绑定原工作区绝对路径，不能通过移动目录迁入新模块区。过渡期间总索引可继续链接旧版已完成页面，新增 B 无需重跑旧 A；A 下次被明确选中重跑后才在 `output/workspace_A/` 生成新版产物。旧版结果全部替换后，根目录才能收敛为总索引和模块子目录；旧版状态的清理是单独的数据迁移步骤，不作为新增模块的前置条件。

验收场景：先完成 A，再新增 B，执行 `make bug_review_B` 时只对 B 调用 RunTestCases/WaveInfo；A 的 JSON、详情页和 receipt 文件字节不变，总索引列出 A+B。再次执行 `make bug_review_A` 时只重跑 A；执行 `make bug-review-analysis` 时 A 与 B 都重新跑。B 中途失败时，A 的报告仍可查看。

### 2. 工具与阶段契约优化

| 优先级 | 实跑问题 | V2.0 处理位置与契约 |
| --- | --- | --- |
| P0 | `reference_files` 展开测试目录，门禁要求逐项 `ReadTextFile`，甚至诱发目录占位操作。 | 插件工作流只声明确实要求阅读的普通文件，如 Guide、当前模块报告和当前 JSON；不把目录或测试树 glob 当成“已读”门禁。具体测试、Spec、RTL 由任务选取和 Checker 的证据引用约束。保留 UCAgent 原有真实读取记录机制，不增设可绕过阅读的 `register_reference`。 |
| P0 | WaveInfo 输出溢出时 receipt 与 case 对应关系难恢复；无效调用也出现在 store。 | UCAgent 核心提供只读、签名验证的 `WaveInfoReceipts(test_case_name, usable_only, limit, offset)`；同一工具以 `receipt_id` 获取详情，`include_result=true` 时按 `timeline_offset/timeline_limit` 分页返回保存结果。列表返回精确 `test_case_name`、`receipt_id`、记录时间、调用窗口、状态、可用性和信号组。默认过滤不可用记录，允许显式查看失败记录用于诊断。WaveInfo 当次响应也带精确 case 身份、可用性、`timeline_truncated` 和遗漏点数。插件直接使用核心工具。 |
| P0 | 大 JSON 靠整文件 `json.dump`、手工备份；当前文件工具写目录仅开放 `notes/`。 | 插件提供只修改本次执行区 `{OUT}/bug_review.json` 的 `UpdateBugReviewJSON(expected_sha256, operations)`：支持 `suspected_bugs`、`cases`、`root_causes`、`stage_status` 内的 JSON Pointer `add/replace`，复用 `EditTextFile` 的版本冲突检查与原子写入；成功更新后将更新前内容保存为 `bug_review.json.bak`。Skill 给出按 Bug/case 定点更新示例；Skill 关闭时仍开放同一工具与格式说明。 |
| P0 | Checker 对 `spec_ref` 类型和 `路径:行号` 格式只抛底层错误，造成多轮 Check 试错。 | 插件 Checker 返回有界的结构化问题列表，逐项给出工作区、`bug_id`/case、JSON 字段路径、实际类型或值摘要、期待格式、示例和下一步。`spec_ref`/`rtl_ref` 明确要求一条相对 `{OUT}/inputs/<workspace>/` 的现存源文件引用 `路径:起始行[-结束行]`；多个证据放在 `evidence.spec`/`evidence.rtl` 数组。现有 `Check` 已执行只读校验，不新增 `dry_run` 参数。 |
| P1 | 长窗口截断、信号名带换行和大结果显示溢出导致重复调用或误判。 | WaveInfo 响应及收据查询显式报告截断和遗漏点数；`WaveInfoReceipts` 支持保存结果的时间线分页。Skill 指导先取精确信号名、选择覆盖事务的窗口，再调用最终 WaveInfo；缺少必要事件时保持未定。原有信号路径错误仍需依据工具诊断修正。 |
| P1 | `SetSkillUsage` 顺序与技能名传输不清楚，阶段收尾重复。 | 阶段任务和 Guide 写清 `ListSkill → ReadTextFile(SKILL.md) → 完成产物 → Check → SetSkillUsage → Journal → Complete`，并从 CurrentTips 复制当前阶段的精确 Skill 名。核心错误显示收到的 Skill 名及期望名，便于定位控制字符；不把被污染的名字自动规范化为另一项已记录证据。先不合并 `stage_finish`，保留独立 Check 与使用证据语义。 |
| P1 | 报告 Skill 静默结束；Bash 当前目录漂移。 | `render_report.py` 输出本次生成的文件路径、数量和 JSON 来源；Skill 脚本仍由 `RunSkillScript` 以固定 DUT 工作区为当前目录执行，所有产物定位使用运行配置的 `OUT`。无需改动通用 `RunSkillScript` 返回协议。 |

### 3. 实施顺序与完成标准

1. 先实现两个 Make 入口的重跑范围、模块专属目录与根目录总索引，确保新增 B 的单模块命令不会重开 A；默认入口仍重跑全部。同步 Make/CLI、发布器、Checker、Guide、阶段 Skill 和产物格式。
2. 修正 `reference_files`，加入 JSON 定点更新及字段级诊断；用 `spec_ref` 错误、并发修改、目录引用和 26 条裁决的批量更新场景验收。
3. 在 UCAgent 核心加签名 receipt 查询及 WaveInfo 结果摘要，随后更新波形 Skill；用同名不同会话、失败 receipt、显示截断和精确 TC 映射场景验收。
4. 更新阶段提示、脚本输出与操作说明；分别检查 Skill 启用和关闭的同一产物契约，并以 A 已完成后新增 B、单独重跑 A、默认重跑 A+B、B 失败保留旧报告的场景完成集成验收。

V2.0 不以“33 个失败全部 confirmed”作为成功判据。裁决仍由正确测试、真实波形、Spec 和 RTL 因果链支持；`refuted` 保留原声明且复核置信度为 `0`，证据不足保持 `inconclusive`。

## V2.1 试跑反馈与优化规划

本节记录 V2.0 工作流的使用者反馈及下一版目标；具体故障表现来自试跑复盘，尚未逐项独立复现。V2.1 保持五阶段、模块独立运行区和按模块发布，把“一个大 JSON 承载所有内容”调整为轻量模块索引及按对象存放的复核记录。新增的工具负责定位、校验和原子写入，Bug 语义、测试正确性与 Spec/RTL 因果判断仍由复核者根据真实证据完成。V2.1 不修改输入测试、规格或 RTL。

### 1. 试跑问题记录

| 区域 | 观察到的问题 | 对复核的影响 |
| --- | --- | --- |
| WaveInfo 查询 | `/…/` regex pattern 得到零匹配且调用端未见明确诊断；`event="unknown"` 得到空结果；信号路径需先探测再复制精确名。 | 容易把查询语法或事件选择错误误判为波形没有信号。现有代码有 `signal_not_found` 与 `no_candidate` 分支，需核对本次调用的实际返回和显示链路，区分“工具未诊断”和“诊断未呈现”。 |
| WaveInfo 窗口与输出 | 越界 `end_step` 被截到波尾；`analysis_window.clamped_to_waveform` 存在于保存结果中，但调用端未看到醒目提示。大结果落为临时 `.txt`，内容并非 JSON，文件路径和格式不清楚。 | 请求窗口与有效证据窗口容易混淆；溢出后的读取方式靠猜。 |
| WaveInfo 参数与身份 | `signal_groups` 与 pattern 命中的信号共同占用 `max_signals`；同一 case 在报告、RunTestCases、WaveInfo/receipt 中使用不同路径形态。 | 首次取证反复调限额和 case 名，receipt 查询可能返回 `CASE_RECEIPT_NOT_FOUND`。 |
| JSON 更新 | 单一 JSON 混合原始声明、完整波形结果与所有阶段裁决；一次 16 op、约 17 KB 的请求中部分文本出现 `\r`，报错只定位末尾一个 op；`/root_causes` 整组替换被拒且合法路径未列明；每次修改后 SHA 失效。 | correlate 被拆成 30 多次串行调用，结构与传输错误难区分；读取一个 Bug 也须先穿过整份文档。`\r` 的注入层尚未定位，不能只凭现象认定为工具实现错误。 |
| 阅读与门禁 | 546 KB 的 `bug_analysis.md` 超过 ReadTextFile 单次 131072 字符限制；阶段参考文件只有通过 ReadTextFile 才登记已读，`count=0` 的用途不直观，失败到 Check 才暴露。 | 需要 SearchText 加分段读取；为完成登记而重复调用，增加上下文和试错。 |
| 数据与校验 | decision/root 字段、置信度和合并规则主要写在 Skill 散文中；需临时脚本摸索 `analysis_claims/evidence/cases` 并手工 join；写入时未统一校验 root 双向关系、共享字段、置信度。 | Check 才发现结构错误；原文、case 和波形的按 Bug 汇集也靠临时脚本。 |
| 引用与发布 | 14 个 Bug 的 Spec/RTL 候选需读约 20 个文件切片核实；渲染后页面与 JSON 的 receipt、viewer、引用和链接还需另写脚本核对。 | 可机械核验的部分占用大量人工时间，发布正确性依赖临时脚本。 |

### 2. 轻量索引与按 Bug 读取

V2.1 的模块索引 `{OUT}/review_index.json` 保存工作区身份、原始报告位置、阶段状态、按原报告顺序排列的 Bug ID，以及 Bug、case、root、覆盖率记录的相对路径。Bug 索引项保存 `origin`、原始 `bug_summary`/`bug_analysis` 的精确文件与行段、原报告置信度、Spec/RTL 候选位置及关联 case ID；case 索引项保存报告 node ID、RunTestCases target、WaveInfo `test_case_name` 和记录路径。索引不存原报告全文、完整 Spec/RTL 片段、波形 timeline 或整段 LLM 分析；当前裁决也只在逐 Bug 记录中保存一份。各路径须解析到本次执行区，Bug ID 和 case node ID 不直接拼成文件名。

| 对象 | 本次运行的持久化内容 | 读取方式 |
| --- | --- | --- |
| `{OUT}/reviews/<revision>/bugs/<key>.json` | 该 Bug 的验证场景、预期/实际行为、证据定位、裁决、置信度、root ID 与简明因果说明；保留 `reported`/`discovered` 身份。 | 按索引中的文件路径读取；原声明长文和 Spec/RTL 仍通过 `path:start[-end]` 回到准备好的只读输入镜像。`<key>` 由索引映射，不从 Bug ID 猜测。 |
| `{OUT}/cases/<case-key>.json` | 一次复测的状态、测试正确性审查、与 Bug 的关联、波形观察摘要、有效窗口和签名 `receipt_id`。`case-key` 由精确 node ID 稳定映射，路径由索引提供。 | 一个 case 关联多个 Bug 时共享此记录；完整已签名 WaveInfo 结果通过 `WaveInfoReceipts(receipt_id, include_result=true)` 按需读取。 |
| `{OUT}/reviews/<revision>/root_causes.json` | root ID、共享的 `rtl_ref/first_error/causal_chain` 及成员 Bug ID。 | correlate 校验每个已确认 Bug 的 root ID 与三字段；报告只在 Bug 详情引用共享根因。 |
| `{OUT}/coverage.json` | 能核实的行/功能覆盖率数值、来源路径、统计口径与所属运行；无法核实时保存明确的缺失状态。 | 模块概况按需加载，不从选择性复测推导原始全量覆盖率。 |

增加一个按 `bug_id` 查询的 `bug-context` Skill 脚本：从索引解析原 summary/analysis 的相关行段、关联 case 的复测与波形摘要、Spec/RTL 候选及已核实引用，按 `summary/cases/waveform/spec/rtl/decision` 分节返回有界内容；可选择节和行数以免再次读入 546 KB 原文。它只汇集和展示已有资料，不改写裁决、不制造 receipt，也不以近似 case 名拼接证据。签名收据详情仍通过 WaveInfoReceipts 读取。Skill 关闭时，阶段任务和 Guide 给出按索引路径使用 ReadTextFile、SearchText 和 WaveInfoReceipts 的等价路径，Checker 标准不变。

### 3. V2.1 目标接口与实施顺序

| 优先级 | 改动位置 | 目标契约及验收 |
| --- | --- | --- |
| P0 | `review_ref_check(refs[])`，供 correlate 使用 | 批量接受 `path:start[-end]`，限定在本次模块准备好的只读输入镜像内，检查文件存在、行段顺序与边界，返回规范化引用、行文本及逐条错误。它只证明引用定位有效；文字是否支持结论仍须人工/LLM 判读。相同解析规则供 Checker 与写入前校验复用，错误指出 `bug_id`、字段及引用。 |
| P0 | 批量提交 decision/root | 以工作区内的结构化暂存文件承载 `decisions[]` 与 `roots[]`，避免大段文本作为工具参数传输。先校验 verdict/`review_confidence`、confirmed 证据与引用、root↔bug 双向成员、`rtl_ref/first_error/causal_chain` 三字段一致及同签名合并；全部通过后生成一组不可变的 Bug/root 记录，再以索引的一次 SHA 保护更新切换当前裁决版本。失败逐项返回文件与字段路径，不切换版本；暂存文件不是权威报告。 |
| P0 | 机器可读 V2.1 契约 | 使用 `bug_review.v4` 标识新布局，分别定义索引、Bug、case、root 和覆盖率的机器可读 schema，以及各阶段必填条件；初始化脚本、Guide、Skill、工具入参、Checker、渲染器以同一契约为准。字段说明包含类型、枚举、必填条件和示例。新运行直接生成新结构；V2.0 已发布的 v3 页面留在原运行区，迁移不是新模块运行的前置条件。 |
| P1 | WaveInfo 与 WaveInfoReceipts | `/…/` 信号查询按完整路径执行正则匹配；零信号匹配和 `unknown` 零事件给出可操作诊断。直接响应标出窗口 clamp；响应统一为 JSON 文本，大结果若由宿主溢出到 `.txt`，文件内容仍可按 JSON 读取，也可按 receipt 查询；`signal_budget` 展示 pattern/context 去重计数。索引显式映射报告 case ID、RunTestCases target 与 WaveInfo `test_case_name`，receipt 查询返回精确名称，不按相似 basename 猜测。 |
| P1 | 小对象更新 | 用各 Bug/case 的独立记录和索引定位替代对单一大 JSON 的 JSON Pointer 链式更新；写入工具给出允许文件/字段和逐项错误，使用单文件 SHA 冲突检测。先定位 `\r` 出现于调用传输、参数解析还是写入，再修责任层；工具不得静默清洗文本。V2.0 的 `UpdateBugReviewJSON` 不作为 V2.1 的写入入口。 |
| P1 | 报告渲染与核验 | `render_report.py --verify` 从索引及其引用的 Bug/case/root/coverage 记录生成并核对模块页、每条 Bug 页、适用的 receipt/viewer/Spec/RTL 引用及站内链接；原始证据从输入镜像读取，不从 HTML 反推。发布 Checker 使用同一核验逻辑。验收包含缺页、坏链接、缺 receipt/viewer、引用越界和正常多 Bug 模块。 |
| P2 | 阅读门禁说明 | 在 CurrentTips/阶段任务中预告待读文件与 `ReadTextFile(count=0)` 的“登记存在但不读取正文”语义；大文件使用 SearchText 和分段 ReadTextFile 阅读相关内容，不能把登记当作已分析正文。优先改进现有门禁诊断，不增加可绕过真实阅读的任意注册工具。 |

批量提交优先复用现有原子写入和 SHA 冲突保护；文件式输入解决请求体大小，**不**把文件内容当成已验证结论。不可变裁决记录先写入本次执行区，索引只在全部校验通过后指向该组文件，避免多文件写到一半就发布混合版本。若调用端仍发生控制字符损坏，以输入文件与写入结果逐字核对定位责任层。Skill 开启或关闭时都要有相同的记录格式、写入路径和 Checker 标准。

### 4. 三级报告与阶段数据

| 层级 | 页面和内容 | 数据来源与限制 |
| --- | --- | --- |
| 门户 | `output/index.html`，列出所有已发布模块、DUT、发布状态和进入模块页的链接。 | 从每个模块当前发布的 `results/review_index.json` 与页面生成；单模块重跑仅更新该模块，其他模块页面与 receipt 保持原样。 |
| 模块概况 | `output/workspace_<name>/results/index.html`，展示复核范围与时间、选中/重跑 case 数、确认/排除/未定 Bug 数、根因组数、行覆盖率、功能覆盖率及疑似 Bug 表格。表格至少有 Bug ID、原声明摘要、复核结论、置信度、关联 case 数和详情链接。 | 从索引找到逐 Bug/case 记录，再计算本次复核数字；原声明摘要从原报告行段提取。覆盖率来自带来源的 `coverage.json`，展示统计口径、分子/分母或原始值、所属运行及“原始报告/本次重跑”范围。 |
| Bug 详情 | `output/workspace_<name>/results/bug_NNNN.html`，按验证场景、规格预期、实际行为、复测结果、关联 case、波形分析、Spec、RTL、裁决依据和共享根因组织内容；可从 case 进入真实 viewer 与 receipt。 | `inventory` 索引原报告场景和预期候选；`replay` 写逐 case 的本次观察与测试正确性；`waveform` 写逐 case 的有效窗口、关键信号、事件与收据引用；`correlate` 核实 Spec/RTL，写逐 Bug 的最终场景/预期/实际及因果结论。多个 Bug 共享 case/根因时链接同一证据，不复制或重造 receipt。 |

V2.1 的逐 Bug 记录保存可展示的 `validation_scenario`、`expected_behavior`、`observed_behavior`；`coverage.json` 保存模块指标，各字段明确来源和状态。行覆盖率只接受实际统计产物，不把 `*_line_coverage_analysis.md` 的 `{TBD}` 当数值。功能覆盖率须区分 FG/FC/CK“已实现”与 CK“运行采样命中”，不能把示例总结中的 `20/20`、`80/80`、`173/173` 实现率标成采样覆盖率。由于 Bug Review 只选择性重跑相关 case，原始全量验证与本次复跑的覆盖率必须分开展示；没有可信统计时显示“暂无可核实数据”和来源缺口，不推算成 `0%` 或 `100%`。覆盖率缺失不改变 Bug 裁决。

各阶段明确 `output_files`：inventory 生成 `{OUT}/review_index.json` 与 `{OUT}/coverage.json`（可标缺失）；replay 更新索引及其中选定的 case 文件；waveform 更新索引及同一批 case 文件的波形摘要和 receipt 引用；correlate 生成 `{OUT}/reviews/<revision>/bugs/*.json`、`root_causes.json` 并在校验通过后切换索引；publish 生成 `{OUT}/index.html`、逐 Bug `bug_NNNN.html` 及页面清单。YAML 对可能为空的 case/Bug 集合只声明必有的索引或 root 文件；Checker 按索引列出的精确文件逐项核验。门户 `output/index.html` 由模块发布步骤重建，不能由本模块索引冒充跨模块索引。HTML 只从已校验的记录和有明确来源的原始资料投影。

### 5. V2.1 实现位置与状态

`review_store.py` 的 Pydantic 模型提供 `bug_review.v4` 机器可读结构；`create_review_json.py` 建立索引、coverage 和共享 case 骨架；`ReviewBugContext` 与 `bug-context` Skill 按 ID 读取有界原文。`ReviewRefCheck` 核实源行段，`UpdateReviewRecord` 写小记录，`SubmitReviewDecisions` 校验整批裁决并一次切换活动版本。`WaveInfo` 返回 JSON 文本与明确的查询、信号预算及窗口提示，`WaveInfoReceipts` 读取真实签名结果。`render_report.py --verify`、`RenderBugReviewReport` 与发布 Checker 使用同一页面核验逻辑。

本轮完成代码与文档的静态检查；仍需按以下完成判据试跑真实模块，包括 Skill 开启/关闭、无 Bug 模块及新增模块发布。试跑反馈继续记录在本文档的 V2.1 小节，下一版本在版本表另增一行。

### 6. V2.1 完成判据

1. 用至少一个真实模块逐阶段验证 schema、按 Bug ID 查询、工具调用、Check/Complete 与三级页面；包含 Skill 开启和关闭路径。错误字段、无效引用、根因不一致、大批量决策和并发 SHA 冲突都给出可定位诊断，失败时索引仍指向上一份完整裁决。
2. 用同一批裁决比较版本切换前后的 Bug 数量、原声明定位、case 关联、root 成员和原始置信度；大 payload 不再需要 15 次以上逐项写入。按 Bug ID 查询能在有界输出里列出原文位置、关联 case、receipt 和 Spec/RTL 引用，引用核实器返回真实行文本，但不替复核者作语义判断。
3. 对 WaveInfo 的 regex、`unknown`、超界窗口、信号预算、结果溢出和 case ID 映射分别检查直接响应与签名 receipt；调用者可辨别“零匹配”“零事件”“窗口被截断”和“证据可用”。
4. 发布前自动核对 JSON、模块页和每条 Bug 页；覆盖率有明确口径或明确缺失。新增模块只重跑指定模块时，门户可进入新旧模块，旧模块的 JSON、HTML 与 receipt 不变。

## V3.0 全量失败归因与环境质量

V3.0 将复核对象从“原报告关联的 Bug case”扩展为“选中模块当前 pytest 配置实际收集的全部 case”。定向、随机和 Mock 用例，以及参数化实例、skip、xfail、xpass 与收集错误都进入运行清单；显式排除项及其配置来源单独记录。测试全集以本次收集结果为准，不使用历史报告的 case 列表定义分母。模块入口保持不变：`make bug-review-analysis` 逐模块运行，`make bug_review_<name>` 只运行指定模块。原始及准备好的测试、fixture、参考模型、Spec 和 RTL 保持只读。

### 1. 调整依据与判断顺序

V2.1 的 inventory 从原 Bug 声明建立 case 索引，replay 仅选择与声明直接相关的 case，无法保证发现报告漏记的失败。样例 `workspace_raid_dec_top` 的测试总结统计表写 178 例、123 通过、55 失败，结论段写 118 通过、55 失败；差出的 5 例可能是随机用例的统计范围，需按精确 node ID 和原始运行口径核实，不能仅凭两个总数认定报告错误。

先冻结全量执行事实，再独立分析失败 case。原 `bug_summary.md`、`bug_analysis.md` 在第一阶段仅机械提取声明 ID 和来源位置；其 Bug 根因描述在第四阶段才作为待核查主张参与语义对账，避免 case 初判被旧结论带偏。全量回归只做一次权威基线；后续仅针对失败、执行不完整或不稳定 case 定向复跑，并保存它与基线的关系。

### 2. 六阶段目标流程与产物

下表定义 V3.0 契约。`{OUT}` 是本次模块执行区的结果目录；`review_index.json` 继续只保存身份、阶段状态与文件路径。每阶段 YAML 声明 `reference_files` 和必有的 `output_files`；可能为空的 case/Bug 集合由 Checker 按索引逐项核验。Schema、Guide、Skill、Checker 和渲染器已切换到六阶段代码；实际运行验收仍待完成。

| 阶段 | 工作及完成条件 | 目标 `output_files` |
| --- | --- | --- |
| `full_replay` | 机械索引原报告；按当前 pytest 配置收集精确 node ID，记录测试配置、执行命令、版本、随机种子和排除项；在隔离副本中分批执行全集。每个收集项有 Pass/Fail/Error/Skip/XFail/XPass 或明确未执行原因，收集错误单列。 | `{OUT}/review_index.json`、`{OUT}/test_manifest.json`、`{OUT}/replay_summary.json`；索引列出的逐 case 执行记录 |
| `case_triage` | 逐个失败 case 独立核对 Spec、测试断言、驱动、fixture、参考模型、复位及采样；记录失败阶段、规格预期、测试预期、实际结果、证据引用和初步归因。对失败或不稳定项定向复跑，必要时比较单独与全套运行。收集、setup、teardown 或环境故障同样有结论或明确缺口。 | `{OUT}/review_index.json`、`{OUT}/environment_review.json`；索引列出的逐 case 失败分析 |
| `dut_evidence` | 对疑似 DUT 缺陷及需要时序证据的争议 case 使用默认 WaveInfo，核对有效事务、Spec 要求、RTL 首错和传播路径；据证据修正 case 归因。测试和环境故障无需制造 receipt。 | `{OUT}/review_index.json`；索引列出的逐 case 波形摘要与真实 receipt 引用 |
| `report_reconcile` | 对照 `bug_summary.md`、`bug_analysis.md` 和原测试总结；保留全部原声明、原置信度及来源，核实旧声明的当前支持情况。将报告漏记且有证据的 DUT 候选加入 Bug 清单；逐项说明报告外失败、旧失败现通过、case 关联与统计口径差异。旧失败现通过须给出原失败行段引用。 | `{OUT}/review_index.json`、`{OUT}/report_reconciliation.json`；索引列出的逐 Bug 草案与 case↔Bug 关联 |
| `root_correlation` | 裁决每条原始和新增 Bug；仅按相同 RTL 首错与因果链合并确认项，保存成员双向关联。原声明不得删除；排除 DUT Bug 时复核置信度为 0，未复现本身不足以排除。 | `{OUT}/review_index.json`、活动版本的 `root_causes.json` 与逐 Bug 裁决记录 |
| `publish` | 在本次运行区生成并核验模块概况、逐失败 case 页和逐 Bug 页；展示全量执行缺口、环境质量、失败归因、报告对账、覆盖率和疑似 Bug。完成阶段后发布模块报告，并重建跨模块门户。 | `{OUT}/report/index.html`、`{OUT}/report/report_manifest.json`；索引列出的 case/Bug 详情页；模块发布后更新 `output/index.html` |

### 3. case 归因与 Bug 裁决的边界

逐 case 记录分开保存执行事实、测试正确性审查、初步归因与取证后的最终归因。执行状态是 Pass/Fail/Error 等运行事实；原因类别至少区分环境故障、测试误读 Spec、测试实现或时序问题、疑似/已证实 DUT 缺陷、Spec 歧义和证据不足。失败分析应指出 collection、setup、驱动、断言或 teardown 的发生位置，并引用精确日志、测试源码、Spec 行段及适用的波形 receipt。判定“测试误读 Spec”须指出实际条款与测试预期的冲突；规格歧义保持待澄清，不能直接判为测试错误。

一个 case 可关联多个 Bug，也可不关联 Bug；每个失败 case 都要有独立归因，不能为非 DUT 失败新建虚假 Bug。原报告 Bug 即使关联 case 本次通过也继续保留，标注未复现与剩余证据；只有充分反证才能裁为 `refuted`。确认 DUT Bug 仍需正确测试、可定位的 Spec 要求、有效事务中的签名波形和能解释首次偏差的 RTL 因果链。同一根因的多个 Bug 共享根因记录，各 Bug 与 case 的独立证据仍可查询。

### 4. 验证环境质量与发布状态

`environment_review.json` 保存具体质量发现及受影响 case，不生成无来源的总分。至少核对收集完整性、导入/编译/仿真环境、fixture 与 reset 隔离、驱动和采样时序、断言及参考模型独立性、随机种子与失败可复现性。覆盖率区分原报告全量统计和本次回归采样；无法核实的数值显示缺口，不把 FG/FC/CK 已实现数当作采样覆盖率。

模块状态区分“复核完整”和“复核未完成”。若收集、执行或环境故障阻断部分 case，仍可发布已核实内容，但须列出未执行或未归因项、原因及影响范围，不得宣称覆盖全部失败。Checker 按收集全集核对每个 node ID 的执行或排除原因、每个失败项的归因、每条原 Bug 声明的保留、case↔Bug 关系和发布页面；显式缺口可以形成不完整报告，静默遗漏不能通过。单模块未完成不得抹除其他模块的已发布结果。

### 5. 实施顺序与验收

1. 建立 pytest 收集全集、分批执行和逐项对账的产物契约；覆盖遗漏失败、参数化实例、随机/Mock、skip/xfail、收集错误、超时及未执行项。全量回归只在选中模块执行，定向复跑须关联权威基线。
2. 增加逐 case 归因、环境质量记录及对应 Skill/Checker；覆盖测试误读 Spec、断言错误、fixture/时序、环境故障、顺序依赖、规格歧义和证据不足。原 Bug 根因文字不能单独构成 case 初判证据。
3. 复用 V2.1 的 WaveInfo receipt、来源核实和小对象更新机制；完成原报告语义对账后再提交 Bug 裁决与根因分组。覆盖漏报 DUT Bug、非 DUT 失败无 Bug 归属、旧 Bug 未复现、旧 Bug 被反证及多个 case 共享根因。
4. 同步 YAML、Guide_Doc、Skill、Schema、Checker 和三级报告；核对 Skill 开关、单模块与全部模块运行、完整与不完整状态、case/Bug 页和总索引。按下述实跑反馈完成工具与发布修复。V3.0 实际完成状态待真实工作流验收后再更新版本表。

### 实施记录

本次代码实现使用 `bug_review.v5` 索引及记录、`bug_review_job.v7` 准备清单和六阶段 YAML。`PrepareReviewInventory` 收集 pytest node 并建立原声明身份/来源索引，原报告 Spec/RTL 候选留待对账阶段填入；`CaptureReplayReport` 保存 RunTestCases 当前报告快照并导入匹配结果，Checker 回读快照核对基线。`failure_analysis`、`environment_review.json` 和 `report_reconciliation.json` 分别承载失败归因、环境质量与旧报告对账。`ApplyReceiptToCase`、`ResolveReviewCase`、`ValidateCaseRecords`、`CreateDecisionDraft` 以及提交 dry-run 覆盖本节工具修复；默认 WaveInfo 在最终签名调用前核对索引身份并可展开命名信号组。报告生成在私有 `report/`，最终阶段完成回调发布到模块公开入口；`bug_review.workflow publish` 可重建门户，也支持把已完成 V2.1 HTML 作为标记旧版的报告恢复公开。静态语法、YAML 解析和差异空白检查已通过；真实模块全流程、Skill 开关与页面实际浏览待验收。

### 6. V2.1 实跑反馈与 V3.0 工具修复

以下故障数量与操作经过来自 `workspace_raid_enc_top` 的使用者复盘，尚未逐项独立复现；本节将其作为 V3.0 的验收输入。该运行区已有 `results/index.html`、Bug 详情页和 `review_index.json` 的 `stage_status.publish=complete`，但模块公开入口及 `output/index.html` 均未生成。当前发布函数仅在启动包装命令收尾时调用，发布不能只依赖该路径。

| 优先级 | 实跑问题 | V3.0 目标与验收 |
| --- | --- | --- |
| P0 | 手工转写 viewer URL 损坏 6 个 case：三处信号路径漏 `_top`、两处重复 `_top`、一处 base64 损坏。 | 增加 `ApplyReceiptToCase(case_id, receipt_id, expected_sha256)`：从已签名收据取得窗口、信号组和 `waveform_viewer.url`，先核对索引中的精确 `waveform_test_case_name`，再原子写入对应 case 的机器证据字段；保留分析者填写的观察和结论。URL 不经 LLM 重新编码。收据无效、身份不符或 SHA 冲突均不写入。 |
| P0 | WaveInfo 用非索引全名也会产生签名收据，身份不符到阶段 Check 才暴露；三套 case 名靠复制粘贴传播。 | 提供按精确 `case_id` 查询的身份解析入口，返回 `case_id`、`replay_target`、从本次测试报告确认的 `waveform_test_case_name` 和可复制的 WaveInfo 调用身份。插件工作流向默认 WaveInfo 提供当前模块的合法全名集合，最终取证调用若不匹配，在签名之前指出可用全名；附加收据时再次拒绝不匹配。此约束只在 Bug Review 运行中启用，不让默认 WaveInfo 从相似路径猜测名称。已签名收据不提供“改名重挂”：先用仍在的波形以正确身份重新调用 WaveInfo，波形缺失时才重跑测试。 |
| P0 | case 字段错误在 `UpdateReviewRecord` 写入时未被发现，拖到阶段 Check；没有随时可调用的轻量 lint。 | 增加只读 `ValidateCaseRecords(case_ids?, max_issues?)`，与写入工具和阶段 Checker 共用校验规则：收据身份、URL 与已签名值逐字相同、可解码 viewer payload、窗口/信号组一致、replay/test_review/waveform 条件字段完整。返回有界的 case ID、字段和修复动作；写入前拒绝确定性错误。 |
| P1 | 30.6 KB 的 `decisions.json` 手工复制大量 case ID；只能提交时得知 Schema、引用和 root 错误。 | 从索引生成符合当前提交格式的草稿骨架，预填 Bug ID 与 case 关联；原报告定位和 `reported_confidence` 留在索引，生成器只在说明输出中提示来源，不向逐 Bug 裁决添加无效字段。判断、根因和复核置信度留待复核者填写。`SubmitReviewDecisions(dry_run=true)` 使用与正式提交相同的校验，返回全部有界错误，不写修订文件、不切换索引；正式提交仍保持单次原子激活和 SHA 冲突保护。 |
| P1 | `ReviewBugContext` 按单条引用限行，较多引用仍产生 65.8 KB、92.7 KB 输出；原声明场景/预期/实际需再解析长 Markdown。 | 增加整次调用的字符预算、引用和 case 分页及截断位置；`claims` 模式只返回按 Bug ID 解析出的场景、预期、实际三项及每项原文行段。无法可靠解析时返回缺失和候选行段，不凭摘要补造声明。普通模式也保证总输出有界。 |
| P1 | 多个 case 重复填写同一组约 20 个信号，人工数组发生漂移。 | 在模块运行区保存有名称的信号组 preset；默认 WaveInfo 可按工作区 preset 名称展开完整 `signal_groups`，取证前检查每条路径在当前波形中精确存在。收据仍签署展开后的真实路径列表，报告和 Checker 以签名结果为准，不以 preset 名称代替证据。 |
| P1 | `ReadTextFile` 登记、`Check` 后 `SetSkillUsage` 的顺序隐蔽；使用者反馈会话压缩后登记丢失。 | Guide 与阶段任务写明当前阶段的 `ListSkill → ReadTextFile(SKILL.md) → Check → SetSkillUsage`，并列出须由 MCP `ReadTextFile` 登记的参考文件；检查跨会话证据持久化，真实已读证据若丢失则修复恢复路径，不能凭压缩摘要伪造阅读。诊断在阶段开始或工具调用处提示，避免直到 Check 才发现。 |
| P2 | `render_report.py` 输出包含 Pydantic `schema` 字段遮蔽警告。 | 定位产生警告的模型字段，以内部安全字段名和对外 JSON 别名保留当前磁盘契约；报告脚本输出只保留产物与诊断。 |

`ApplyReceiptToCase` 和 lint 处理机器字段与可确定的结构错误，不代替分析者判断 Spec、测试正确性或 DUT 根因。信号组 preset 复用输入，签名收据证明实际使用的信号。正式提交前读取当前 SHA 仍是必要的并发保护；脚手架和 dry-run 只减少重复转录与提交试错，不绕过版本冲突检查。

### 7. V3.0 发布布局与恢复入口

目标布局为 `output/index.html` 作为所有**已发布**模块的门户；`output/workspace_<name>/report/index.html` 是模块最终报告入口，`report/cases/` 与 `report/bugs/` 是第三层详情。`output/workspace_<name>/runs/<run-id>/` 只保存该次执行的 `review_index.json`、case/Bug/root JSON、测试副本、签名 receipt、草稿及历史；对外 `report/` 只暴露已核验的 HTML、页面清单与其必要的源引用资源。页面链接不能依赖 `runs/` 的临时相对路径，签名 receipt 仍留在原执行工作区，不移动或改写。

发布分两步：阶段 `publish` 先在本次运行区渲染并核验 `{OUT}/report/`；阶段成功完成后，将该模块的 `report/` 作为一个整体切换为公开入口，再从所有已发布模块重建 `output/index.html`。发布条件取完整的工作流状态和页面核验结果，不能仅以外层子进程退出码决定。Make、插件直接启动与恢复发布应调用同一幂等发布入口；对已经完成但门户缺失的运行可只重建模块入口和总索引，不重跑测试、WaveInfo 或裁决。重建后检查门户及每个模块/详情链接可打开；发布失败保留此前有效入口，不把中间运行文件当成最终报告。

验收至少覆盖：已完成模块缺总索引时补发、直接启动而非 Make 包装、两个模块仅重跑其一、发布中断后恢复、旧报告保留、case/Bug 页面与源引用链接、不可用 viewer 的明确诊断，以及公开目录不混入 `drafts/`、`tests/`、`.ucagent/` 和原始 receipt store。

## V3.1 归因事务与报告呈现

V3.1 依据 `workspace_raid_enc_top` 第二次实跑反馈实施。反馈称报告级 tests 聚合清单有 23 处与 BG 条目级 `<TC-…>` 错位，使用者为通过门禁合并两份清单，形成 106 条关联和 23 个双归属。这些数字是运行反馈，不代表关联正确性。最终报告的模块、Bug 和失败 case 页面也需要清晰区分结论、证据和长篇原文。本次不调整 `output/index.html` 门户视觉。

### 1. 原报告 case 来源与归因事务

每条原 Bug 的 BG 条目级 TC 引用是该声明的权威 case 关联；报告级 tests 聚合清单作为带来源的历史事实另存，不能自动加入 `BugEntry.case_ids`。条目级身份无法解析时保留明确缺口，由复核者核对原文，不能根据名称猜测。Checker 保留全部原 Bug ID、原置信度、检查点和原文来源，按条目级关联检查复核结果；两种来源的差异进入对账记录和报告，不通过 UNION 消除差异。

`CommitAttribution(draft_path, dry_run)` 从一份 `bug_id → case_ids` 草稿出发，自动推导全部 case 的反向 `bug_ids` 及报告对账集合。`dry_run` 给出逐 Bug/case 的 `expected`、`actual`、`missing`、`extra`；正式提交先校验完整关系，再写入新修订并一次切换活动索引。失败时索引仍指向旧修订。工具返回实际变更路径和修订标识。本次执行区由一个工作流顺序写入，输入及准备好的测试、Spec、RTL 只读；归因事务不要求逐文件 SHA。现有小对象编辑可继续使用，但不是关联主路径。

`CreateDecisionDraft` 支持从活动索引刷新已有草稿的 `case_ids`，保留人工裁决字段并预览差异；`SubmitReviewDecisions` 关联不一致时直接返回差集。原报告门禁、case 门禁和归因提交共享结构化诊断，至少包含对象 ID、字段、期望、实际、缺失、额外值和下一步。旧 revision 提供有界 list/diff；恢复旧裁决须按当前活动关联重新校验。当前 `UpdateReviewRecord` 代码只写指定目标，使用者观察到的 case 写入后 index SHA 变化须先定位实际写入来源；工具只能报告实际变更。

### 2. 阅读证据与发布状态

大 `bug_analysis.md` 使用按 Bug ID 的有界上下文和原文行段阅读，不要求一次传输整份文件。阶段提示清楚列出本阶段的文件与 Skill 已读证据、缺失项和下一动作；内容未变的已读证据可复用，不能凭对话摘要制造阅读记录。

`RenderBugReviewReport(verify_only=true)` 保持只读；publish Check 校验页面、清单、签名证据和链接，不要求预先手工设置 `stage_status.publish=complete`。Complete 成功后，插件回调记录发布状态、切换模块公开报告并重建门户。报告渲染只写本次执行区 `{OUT}/report/`；发布只写配置的 output 根目录及对应模块目录。准备和发布前检查目标目录能否创建、写入，并返回具体不可写路径及下一动作；不递归调整输入或既有报告权限，不把私有 `runs/` 暴露为公开页面。

### 3. 模块与详情页

模块页首屏显示复核状态、收集/执行/失败/确认 Bug/缺口数量、覆盖率及口径；随后是按裁决与归因可扫读的 Bug 和失败 case 表，环境质量、原报告差异及数据来源放在表后。Bug 详情先显示裁决、复核置信度、根因组及结论，再按场景、预期/实际、正确失败测试、签名波形、Spec、RTL 因果链呈现证据。失败 case 详情先显示执行状态、失败阶段和归因，再并列展示 Spec 预期、测试预期和实际行为。长 node ID、信号组和源码摘录可展开；缺失证据显示原因，不渲染为 0 或空白结论。

页面用浅灰背景 `#F7F9FC`、白色卡片、深色正文 `#101828`。确认 DUT Bug 用深红 `#B42318`，疑似/证据不足用琥珀 `#B54708`，测试/环境原因用紫色 `#6941C6`，通过用绿色 `#027A48`，排除用灰色 `#667085`。颜色同时配文字标签；窄屏下并列证据区域纵向排列。渲染器、页面清单与 `verify_pages` 同步更新，页面结论只来自活动记录。

### 4. 实施与验收

先同步 schema、inventory、Checker 和归因事务，再更新草稿与诊断；随后修正 publish 收尾和 output 写入路径，最后更新页面及核验。验收覆盖：报告级错位清单不会制造双归属；关联一次提交且失败时旧修订完整；不要求逐 case 读取 SHA；草稿刷新保留判断；publish 无须手动改索引；不可写 output 报告明确路径；完整/未完成报告在桌面与窄屏能直接看到结论、缺口和证据入口。

本次实现以 `bug_review.v6` 索引保存 BG 级关联、聚合清单来源及活动归因修订。归因草稿一次预检和提交，自动更新全部 case 反向关系及对账记录；单记录编辑、收据附着和裁决提交已去除逐文件 SHA 入参。决策草稿支持同步关联，修订查询返回活动指针及变更摘要。publish Check 只核验报告，完成回调发布后记录状态；报告工具与发布入口返回不可写路径。模块页与两类详情页已按本节布局和色彩渲染，门户视觉维持现状。静态编译、YAML 解析和差异空白检查已通过；真实模块全流程和页面浏览仍需在下一次运行中观察。

## V3.2 收集环境、对账与报告阅读

本版依据 `workspace_raid_dec_top` 六阶段实跑复盘和最终报告阅读反馈。收集曾因 pytest ini 将 `uc_test_report` 写入只读 `{OUT}/tests/` 而 `INTERNALERROR`；现场恢复测试副本权限后，又遇到带 quarantine 属性的 dylib 被系统拒绝加载。最后通过现场处理收集到 204 个 node。该过程证明收集与正式 RunTestCases 的报告路径不一致；不把一次现场 `chmod`、移除 quarantine 或单纯失败数量相等固化为工作流规则。

### 1. 全量收集的路径与失败恢复

保留 `{OUT}/inputs/` 与 `{OUT}/tests/` 的只读边界。`collect_nodes` 显式把 toffee/pytest 报告写入本次执行区可写的 `<run>/uc_test_report/`，与 RunTestCases 的实际报告路径一致；不修改原始或准备好的 `.pytest.ini`，也不禁用 pytest 插件。收集命令、pytest 配置和报告目录写入 manifest。非零退出、收集错误或空集合时保存完整 stdout/stderr 与有界关键诊断，且不建立正式 `review_index.json`、case 骨架或基线；环境修复后相同工具调用可以重试，不需手工删除失败骨架。macOS 动态库若被系统拒绝，诊断给出真实库路径与可检查的隔离属性；插件不自动清除 quarantine，也不扫描加载全部动态库。

### 2. 原报告候选与 case 对账

`CreateAttributionDraft` 复用现有 `_inventory` 批量预填每个原 Bug 的 Spec/RTL 候选和 BG 级 case 关联，并保留报告级聚合清单的独立来源。`CommitAttribution(dry_run=true)` 对草稿候选给出 `expected/actual/missing/extra`，正式提交一次性更新索引和 case 双向关联。复核者仍须使用 `ReviewRefCheck` 核实候选行段及语义；机械提取不是确认 Bug。新增只读 case 差集视图，依索引身份映射返回“原声明关联”“本次收集”“本次失败”的集合及差集，不能把原声明关联直接当作历史失败事实；旧失败现通过只在有原始失败引用时成立。批量输出使用 `case_id` 作为唯一对账键，并明确对应的 `replay_target` 与 `waveform_test_case_name`。

BG 条目级 `<TC-…>` 是原 Bug 必须保留的关联，`aggregate_case_ids` 只记录报告级聚合来源。聚合独有 case 不自动加入 `case_ids`；新增关联由独立 case 证据支持。归因预检逐 Bug 列出 BG 必需、聚合仅有、草稿新增与缺失四组，避免把为通过门禁而作的 UNION 误写成规则。`review_index.json.bugs` 是以 Bug ID 为键的对象，Guide 给出按键遍历示例。

### 3. 根因文字与阶段证据

同 root 的已确认 Bug 决策中 `rtl_ref`、`first_error`、`causal_chain` 与 root 字段必须逐字一致；各 Bug 独有的观察与 case 细节写入 `observed_behavior` 和 `rationale`。`CreateDecisionDraft` 在明确指定 `root_id` 且 root 已在草稿中时，可按显式选项同步这三个标准字段，不根据相似文本自动合并 root。提交错误逐字段返回 root 标准值与当前值。

每阶段任务和 Skill 说明进入阶段时按 CurrentTips 登记本阶段 reference_files：`ReadTextFile(count=0)` 仅用于已阅读且内容未变的文件登记，不返回正文；首次阅读文件及阅读 `SKILL.md` 使用返回正文的调用。原生 Read/shell 不产生工作流已读证据。Skill 名使用 CurrentTips 中的完整 `ext/bug_review/...`。本版不改变 UCAgent 全局跨阶段已读门禁或新增通用 RegisterRead 工具。波形取证继续使用精确身份、`ReviewRefCheck`、`ApplyReceiptToCase` 与签名收据；不把“所有 JSON 必须纯 ASCII”作为内容规则。

### 4. 中文报告与源码全文预览

本版调整模块和详情页，`output/index.html` 门户视觉仍维持现状。页面语言设为 `zh-CN`，标题、表头、状态与说明尽量用中文，精确 Bug ID、case node、信号及源路径不翻译。模块页的“Bug decisions”改为“高置信 Bug”，仅展示 `verdict=confirmed` 且 `review_confidence >= 0.8` 的记录，按置信度降序；表头用“复核置信度”替代“Decision”。其他裁决仍留在权威数据与可生成的详情页，模块页显示未在主表展示的数量，避免误读为删除原声明。

Bug 详情页在验证场景、预期行为、实际行为下方用一段中文概述归因、根因位置及造成的现象，详细首错与因果链仍在证据链中。证据链之后是默认展开的“相关文档”，链接原报告摘要、分析原文和关联 DUT 规格文档；报告级用例清单以表格列出复核关联当前缺陷的用例、仅原报告汇总提及的用例及重跑结果。末段“相关源码”默认折叠，仅列 RTL 文件/行段与简析：决定性 RTL 引用说明首错及因果链，其余候选明确标记为原报告线索，不能冒充已核实结论。Spec 引用保留在相关文档和证据链。点击引用打开报告内去重后的独立全文预览页，定位并高亮 `路径:起始行-结束行`，支持脱离私有 `runs/` 浏览。仅为被引用的文本源生成独立 HTML 预览页；HTML 转义源码、校验引用不越界，并在 `report_manifest.json` 和 `verify_pages` 中校验预览页、链接及目标行段。case 页和 Bug 页保留各自完整的执行/裁决证据，过滤仅作用于模块主表。

### 5. 实施顺序与验收

先修改收集命令和失败恢复，再更新归因草稿/差集及根因字段诊断，随后同步 YAML、Guide、Skill，最后更新报告与核验。验收关注：只读测试树下收集成功；收集失败没有权威索引且可直接重试；隔离库失败给出路径；原候选无需手工复刻解析器；BG 与聚合差集正确；共享 root 字段可定点修复；阶段参考文件与 Skill 阅读动作明确；模块主表只显示高置信确认 Bug；中文详情页可打开全文并高亮引用行段。

本次已实现：收集报告目录重定向、失败日志与可重试索引创建；原报告候选预填及一次归因提交；`ReviewCaseDiff` 批量差集；指定 root 的标准字段同步及逐字段诊断；阶段 Guide/Skill 提示；中文报告主表筛选、源码全文页、行段高亮与发布清单核验。输入与测试副本仍保持只读，macOS 隔离属性仅诊断。已完成静态语法、配置解析和差异格式检查；真实 DUT 环境及浏览器页面效果留待下一次工作流运行反馈。

## V4.0 主张归属与长流程体验规划

本节根据 `workspace_raid_enc_top` 一次六阶段、超过七小时的使用者复盘实施；问题数量和耗时为该次运行反馈，尚未逐项独立复现。功能变化记为 `v1.3.0`。本节描述本次实现及仍需真实工作区试跑核实的边界。

### 1. 核心问题与数据权威

现有 `parse_bug_claims` 能找到 `<BG-...>`，却优先用所在 FG/FC/CK 路径生成 `bug_identity`；`_inventory` 再用该身份汇总 `analysis_refs` 与 case。`ReviewBugContext(sections=["claims"])` 只读取索引给出的这些行段。因此错误起点在**把脚本推断当成主张归属事实**。该次反馈出现约五个 Bug 主张为空、CMD2 串入其他 Bug，以及 BP 取得 PWRITE 行段。报告级聚合测试、CK 路径和 BG 标题都应作为 LLM 阅读原文时的线索与来源，不由其中任意一个自动决定最终 BG→FC→CK 或 Bug→case 关系。

原 `CommitAttribution` 要求草稿包含索引和重新解析出的原始 case 集合。若二者都来自错位的机械解析，取并集只能把已知误关联永久留在活动记录。**本版不实现 `normalize=true` 自动并集**。Skill 脚本与工具只创建空白格式，例如顶层 `schema` 与空的 `bugs: []`；LLM 阅读 `bug_summary.md`、`bug_analysis.md` 的 BG 标题和条目、测试、Spec 与 RTL 后，填写每条 Bug 的主张行段、BG／FC／CK 层级、case 归属、信息来源和判断理由。脚本不扫描或推断这些关系，也不代填具体 Bug 信息。原文标签与 LLM 的判断不一致时，两者并存并写明差异原因，不能静默覆盖原声明或原置信度。

### 2. 优先实施的改动

| 优先级 | 改动 | 对使用者的行为与验收 |
| --- | --- | --- |
| P0 | 建立空白主张映射格式，由 LLM 填写 | Skill 脚本只生成字段结构与填写示例，例如 `bug_id`、`claim_refs`、`bg_ids`、`fc_ids`、`ck_ids`、`case_ids`、`source_labels`、`rationale`；不自动解析原文填值。LLM 通过分段阅读、搜索和行段引用逐条填写。`ReviewBugContext` 读取已填写的映射并按 Bug ID 返回有界原文；未填写时明确提示所缺字段，不按 CK 或关键词补猜。 |
| P0 | 允许 `CommitAttribution` 提交经复核的关系 | 草稿区分原文所见标签与 LLM 最终关联，逐项注明来源和必要的纠偏理由。`dry_run` 列出相对当前索引的移除、保留、新增及双向 case 变化；正式提交一次更新索引、case 反向关联与对账修订。Checker 核实引用实际存在、原声明均有去向、关系双向一致及差异有说明，不强制旧扫描集合，也不替 LLM 判断语义是否正确。旧运行记录不原地改写，使用新运行区按新格式重建。 |
| P0 | 在 `dut_evidence` 开始前提供 LLM 填写的 case→BG 线索 | `case_triage` 先独立分析失败，随后 LLM 可仅根据原文结构与测试事实填写初步 case→BG 映射，供波形阶段选取相关 case 和信号；原根因文字仍不作为独立证据。WaveInfo 收据绑定精确 case，后续调整 Bug 关联不使收据本身失效；若新增关联需要更多信号，仅补该 case 的不足证据。六阶段顺序保持不变。 |
| P1 | 缩小 receipt 查询结果 | 先使用现有 `WaveInfoReceipts(test_case_name, limit, offset)` 精确查询；若批量代表回执仍需多次调用，在插件侧用索引提供按 `bug_id`／case IDs 的有界摘要视图，默认只返 case、receipt ID、可用状态和窗口，信号组与 timeline 按 receipt ID 另查。核心 WaveInfo 不直接解析插件 Bug ID；不再一次返回大批完整信号组。 |
| P1 | 简化裁决草稿填写 | Skill 脚本只生成空白裁决格式与字段说明，不预填 Bug ID、case、引用、根因文本或裁决值。LLM 根据活动记录和原始证据填写所有具体信息；现有 `SubmitReviewDecisions(dry_run=true)` 负责检查字段形状、共享根因文本一致性及双向关联，并返回定点错误。避免另建第二套提交门禁。 |
| P1 | 暴露阶段进度与 Skill 缺口 | `CurrentTips`／阶段 Checker 给出尚未取证的 case 数、已有可用 receipt 数和可续做的精确 case 清单；继续用现有逐 case 文件、receipt 和 journal 断点，不另造进度数据库。`SetSkillUsage` 被拒时返回当前阶段每个 Skill 的已观察 `list/read/use`、本次提交值、当前 Check 状态及下一步。先复现该次报错链；现有代码已对部分缺失字段给出动作，不重复实现“显式记录”来绕过真实已读门禁。 |
| P2 | 统一入口身份与来源标注 | 扩展 `ResolveReviewCase` 为**精确且无歧义**的身份转换：接受规范 case ID、完整 pytest node、合法 `TC-` 标签或完整 WaveInfo 名，返回全部等价形式及收据状态；只给 basename 时列候选并要求选择，不猜测。原报告根因段及类似 `RAID_ISSUES` 的结论材料在 `ReviewBugContext`／`ReviewRefCheck` 结果中标注“原报告主张，不是独立 Spec/RTL 证明”；保留阅读能力，不引入手工维护的 quarantine 清单。 |

### 3. 判断边界与报告反馈

根因分组建议可在确认真实 RTL 首错后作为只读候选视图，按 `rtl_ref`、首错和因果链列相同与相近项，同时突出同文件不同位置或不同因果链；不自动合并，也不把原报告根因文字当证明。该功能低于 P0/P1 的归属修复，先观察草稿工具是否已足够。

模块主表的 `0.8` 是**展示阈值**，不是确认 Bug 的置信度门槛。主表将达到阈值的已确认 Bug 按最终 root ID 聚合，一组一行，列出所有可点击的成员 Bug、成员置信度范围和去重后的用例数；按组内最低置信度排序。高置信度 KPI 计根因组数，而非 Bug 声明数。总门户从模块报告清单读取相同的根因组数，不再以原始 Bug 条目数代替，也不插入指南链接。被排除的 DUT Bug 保留原声明和详情，但不计入根因组。`CreateDecisionDraft` 预览可显示每条已确认 Bug 是否进入主表、低于阈值的确认项数量；不得为了上榜而抬高复核置信度。原声明和详情仍可追溯。

长 Markdown 继续使用 `ReviewBugContext` 按 BG 块和行段分页；`ReadTextFile` 的长度上限与其行号前缀不由插件绕过。本次 heredoc 中文失败应先取得 Python 版本、实际脚本字节和完整 `SyntaxError`，不能仅凭现象把 `# -*- coding: utf-8 -*-` 当作 Python 3 的通用修复。对于大量裁决写入，优先使用上述草稿脚本与 JSON 文件，避免依赖大型临时 heredoc。

### 4. 实施次序与完成判据

实施顺序为：定义空白映射格式、LLM 填写步骤与按行段读取入口，让索引、`ReviewBugContext` 和归因提交消费该映射，移除 CK／关键词自动归属的硬门禁；波形阶段允许使用初步 case 线索且保持收据绑定 case；加入有界回执摘要、空白裁决格式、身份转换、阶段进度与来源标注。已同步工作流 YAML、Guide_Doc、Skill、Schema、诊断和报告中的关联来源说明，`CHANGELOG.md` 记录 `v1.3.0`。

完成判据为：脚本输出的映射和裁决草稿不含任何自动填入的 BG／FC／CK、case、主张、引用或裁决内容；LLM 填写后，本次反馈中的五个空主张、CMD2 串扰和 BP/PWRITE 错位都有准确原文行段与归属理由；23 处关联分歧可逐项解释并纠错，活动记录不再因旧门禁保留已知错误从属；代表 receipt 查询结果有界；共享 root 的文本不一致时能指出具体字段和值；阶段中断可从已落盘 case 与收据继续；Skill 拒绝和身份歧义都给出明确下一步。真实 Spec/RTL 语义、测试正确性和根因结论由复核者判断。

本次已实现空白 `attribution.json`／`decisions.json`、原 BG 块分页、复核归属提交及源码覆盖校验、草稿驱动的 `ReviewBugContext`／case 差集、`ReviewReceiptSummary`、`ReviewStageProgress`、精确别名解析和原报告来源标注。`SetSkillUsage` 继续使用现有全局诊断，本版未改变其状态取证机制；根因聚类建议仍是可选后续项。已完成 Python 静态编译、YAML／JSON 解析和差异格式检查；真实 DUT 全流程与页面交互待下一次试跑反馈。

### 5. 签名波形的静态报告预览

Surfer 的前端资源是静态 HTML／JavaScript／WebAssembly，原签名链接中的 v2 `wave` 令牌则默认把波形下载指向 UCAgent 的动态 `/api/waveform/latest`。报告发布时只复制收据明确选中的、大小与修改时间仍匹配的 FST／VCD 原文件到 `report/waveforms/`，并把 Surfer 静态资源放到 `report/surfer/`。预览链接保留原令牌的信号集合和分析窗口，仅把数据地址改到同一报告中的静态快照。总门户同时发布 `output/serve.py`；接收方只拿到整个 `output/` 文件夹时，在其根目录运行 `python3 serve.py`，用浏览器访问打印的本地 HTTP 地址即可，不需要 UCAgent 或插件源码。插件开发环境也可运行 `make bug-review-serve`。本地服务提供静态页面、波形与 WebAssembly 所需响应头；用 `file://` 直接打开报告无法可靠启动 Surfer。分享时要保留模块 `report` 到其 `runs/` 中已发布结果的相对链接关系。

签名收据和预览文件承担不同作用：收据仍是工作流的证据，静态快照只是浏览器展示材料。发布前已轮换的原波形不能从其他运行、同名文件或原报告推测补齐；这类 case 显示关键观察和收据，但不提供完整预览。现有公开报告重新渲染后，`workspace_raid_dec_top` 的 26 条签名波形均有可用快照，`workspace_raid_enc_top` 的 83 条中有 4 条可用，其余 79 条原文件已不在该次运行区。HTML／清单核验覆盖快照链接、原令牌、Surfer 资源及页面与活动记录的一致性。

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

V1 曾通过 `BugReviewWaveInfo` 封装 UCAgent `WaveInfo`。V1.3 改为直接调用默认 WaveInfo；最终证据使用真实测试节点、信号路径、时间窗口和工具生成的 `receipt_id`。信号集合覆盖相关输入、输出、协议控制、实际时钟（若有）及解释功能选择或错误传播的关键路径。测试日志周期与波形 step 通过时钟出现序号和事务上下文对齐，不假设编号相等。

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
| `src/bug_review/plugin.py` | 注册五阶段工作流和 Checker；不注册 Bug Review 专用执行工具。 |
| `src/bug_review/workflows/analysis.yaml` | 声明阶段任务、`reference_files`、`output_files` 与 Checker；以目标五阶段为准。 |
| `src/bug_review/Guide_Doc/analysis.md` | 给执行阶段的 Agent 提供可操作的任务和产物格式；与本文契约一致。 |
| `src/bug_review/inputs.py`、`workflow.py` | 发现 `inputs/workspace_*`、将输入复制到 `{OUT}/tests/workspace_*`，并在 Checker 中验证直接生成的阶段产物。 |
| `src/bug_review/skills/` | 各阶段工作目标、UCAgent 工具步骤、产物格式和报告 HTML 渲染脚本。 |
| `src/bug_review/analysis_core/` | 原 Bug 报告解析与原子 JSON 写入。 |
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

## V1.2 阶段 Skill 与波形取证

- Agent 调用无阶段参数的 `BugReviewAdvance`。工具从当前工作流状态确定阶段，生成产物或返回待办；每项待办仍由 `BugReviewTasks` 和 `BugReviewSubmitResponse` 处理。调度器内部仍按阶段执行，Checker 继续验证每阶段的 `output_files`。
- `inventory-review`、`replay-review`、`waveform-review`、`evidence-correlation`、`report-publication` 五个阶段 Skill 分别给出本阶段的操作顺序、证据判断和产物复核。启用 Skill 时，阶段要求读取并使用对应 Skill，Check 后登记使用证据；关闭 Skill 或工作区没有 `.ucagent/skills` 时，阶段 task 与 `Guide_Doc/analysis.md` 仍提供全部工具调用、格式、证据和完成标准，Checker 标准不变。
- 波形阶段沿用默认工作流的取证原则：先确认测试、驱动与规格预期正确；最终 `signal_groups` 包含真实时钟或明确组合模式、相关输入数据/选择/使能、输出数据/状态/有效位、真实请求接受/响应控制、至少一条功能选择/状态/错误传播路径。一个 TC 关联多个 Bug 时覆盖信号并集，签名 timeline、receipt 和在线 viewer 使用同一组真实路径。`pattern` 只定位事件。日志 cycle 与波形 step 按时钟出现顺序及事务上下文对齐；核对有效窗口、背压、响应延迟和归属后才能作 DUT 结论。
- `replay` 已在输出根目录的 `tasks/<workspace>/replay/runs/<workspace>/workspace` 创建隔离副本并执行测试。Makefile 无需额外提前复制 `workspace_*`，避免重复占用空间及来源歧义；可直接查看该副本和旁边的 `execution.json`。

## V1.3 原生工具驱动的阶段

- 插件不再注册 `BugReviewAdvance`、`BugReviewTasks`、`BugReviewSubmitResponse`、`BugReviewStatus` 或 `BugReviewWaveInfo`。五阶段按 CurrentTips 调用文件工具、`RunTestCases`、默认 `WaveInfo` 和阶段 Skill；不通过 Bug Review 工具接收待办结构或提交判断。
- `prepare-analysis` 在 UCAgent 启动前将选定的 `workspace_*` 复制到 `{OUT}/tests/<workspace>/`。`RunTestCases.test_dir` 与默认 WaveInfo 的测试目录均使用 `{OUT}/tests`，不同工作区保留独立子目录。源目录不修改；复制输入作为只读分析资料。
- 五个阶段 Skill 写明目标、输入、工具调用、产物文件和完成条件。启用 Skill 时按 stage `skill_list` 读取执行；Skill 整体禁用时，stage task 和 Guide 仍包含等价任务路径。
- 阶段产物直接由 UCAgent 文件工具或 Skill script 写到 `{OUT}`。Checker 按输入身份、测试覆盖、波形收据引用、根因成员关系、置信度和 HTML 链接验证产物，不要求 Python workflow 先运行并密封状态。
- 波形阶段调用 UCAgent 默认 `WaveInfo`，保留它返回的原始 `receipt_id`、结果、签名信号组与 viewer；分析引用真实工具输出，不从 Bug Review 包装层推导证据。

完成优化的判据是：单个及多个 `workspace_*` 均可从输入到 HTML 完整执行；原报告每条 Bug 都有保留的裁决，新失败可新增，同根因可合并而不丢成员，非 Bug 的复核置信度为 `0`；输入源码未被改写；每个阶段的声明文件与每个工作区的实际产物一致；报告结论可回溯到本次测试、波形、Spec 和 RTL。V1.3 的真实 DUT 重跑、默认 WaveInfo 调用及 HTML 全流程仍需在满足版本要求的 UCAgent 运行环境中验证。插件最低版本要求保持 `UCAgent>=26.9.2.dev6`，与 DesignWithPPA 一致；RTL2Spec 要求 `>=26.9.2.dev14`。本次仓库版本为 `26.6.25.dev3`，低于插件最低版本。
