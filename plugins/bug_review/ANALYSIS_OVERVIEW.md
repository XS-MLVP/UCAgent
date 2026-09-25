
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
| V1.4 | 现行代码契约；已有一次 `workspace_raid_dec_top` 实跑反馈 | 不复制完整工作区；只准备分析文本、测试目录和 DUT 运行包；RunTestCases 只运行 JSON 选择的用例；五阶段更新同一 JSON；HTML 直接从该 JSON 渲染。 | [V1.4 最小输入副本与单一复核 JSON](#v14-最小输入副本与单一复核-json) |
| V2.0 | 规划中，尚未实施 | 默认重跑全部模块，`make bug_review_<name>` 只重跑指定模块；`output/` 顶层提供总索引，各模块独立保存状态和报告；收敛参考文件门禁，改进 JSON 更新、诊断与波形证据查询。 | [V2.0 按模块重跑与工具体验](#v20-按模块重跑与工具体验) |

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

V2.0 依据 `workspace_raid_dec_top` 的一次实跑反馈规划。该次运行的 Agent 报告：26 条原声明、55 个关联 case；选择重跑 33 个 case，形成 33 个 WaveInfo receipt；26 条裁决归入 23 个根因组，并生成总索引和 26 个详情页。这些数字是本次运行的反馈基线，不代表对裁决正确性的独立复核。运行耗时约 2 小时 46 分；V2.0 重点减少重复执行、人工恢复和格式试错，保留真实测试、波形与 Spec/RTL 证据门禁。

### 1. 用 Make 选择重跑范围

现有 Makefile 已有 `make bug_review_<name>`，但它只能在新的输出根下选择单模块。准备代码把 `source_runs` 冻结在输出根的 `review_job.json`：已有 A 的输出后，选择 B 会因任务范围不同被拒绝；同一输出根的 UCAgent 阶段历史也可能使 B 直接进入已完成状态。因此 V2.0 要保留这条简单命令，并打通“同一输出根下独立启动指定模块”，不增加自动扫描完成状态、输入指纹或跳过调度。

- `make bug-review-analysis` 默认选择 `inputs/workspace_*` 下的全部模块，并对每个模块重新执行五阶段；已有结果不改变默认重跑范围。
- `make bug_review_<name>` 只选择 `inputs/workspace_<name>`，执行该模块的五阶段；重复调用即重新复核该模块。两个入口都使用可配置的 `OUTPUT_ROOT`，默认仍是 `plugins/bug_review/output/`。
- `output/` 顶层只作为跨模块入口，目标布局为 `output/index.html` 和 `output/workspace_<name>/` 子目录。每个模块的子目录保存自己的 UCAgent 阶段历史、准备清单、测试副本、签名 receipt、`results/bug_review.json`、`results/index.html`、Bug 详情页及页面引用的源文件；其余模块的状态不混在根目录。
- 同一模块每次重跑在该模块目录下新建独立执行区，例如 `output/workspace_<name>/runs/<run-id>/`。执行成功后把该模块的单一 JSON、HTML 和所需源文件发布到 `output/workspace_<name>/results/`，再重建 `output/index.html`；失败则保留此前发布的有效页面。签名 receipt 仍留在对应执行区，已发布结果记录其真实作用域，后续核验不把 receipt 当成可移动文件。
- 重新发布只替换本次选中的模块结果，其他模块的 JSON、详情页、测试记录和 receipt 不改写。总索引根据已发布且可打开的模块页面生成，链接到 `workspace_<name>/results/index.html`。V2.0 每次工作流只处理一个模块，运行中权威 JSON 为 `{OUT}/bug_review.json`；阶段 YAML、Checker、Guide、Skill 和报告脚本同步调整此路径。
- 准备清单改为本次模块执行区私有，不能再让共享 `output/review_job.json` 的冻结 `source_runs` 阻止新模块。Make 在启动前显示本次选中的模块及输出子目录，避免把单模块命令误认为全量运行。

现有 V1.4 `output/results/workspaces/*` 与根目录 `.ucagent` 属于旧布局。签名 receipt 绑定原工作区绝对路径，不能通过移动目录迁入新模块区。过渡期间总索引可继续链接旧版已完成页面，新增 B 无需重跑旧 A；A 下次被明确选中重跑后才在 `output/workspace_A/` 生成新版产物。旧版结果全部替换后，根目录才能收敛为总索引和模块子目录；旧版状态的清理是单独的数据迁移步骤，不作为新增模块的前置条件。

验收场景：先完成 A，再新增 B，执行 `make bug_review_B` 时只对 B 调用 RunTestCases/WaveInfo；A 的 JSON、详情页和 receipt 文件字节不变，总索引列出 A+B。再次执行 `make bug_review_A` 时只重跑 A；执行 `make bug-review-analysis` 时 A 与 B 都重新跑。B 中途失败时，A 的报告仍可查看。

### 2. 工具与阶段契约优化

| 优先级 | 实跑问题 | V2.0 处理位置与契约 |
| --- | --- | --- |
| P0 | `reference_files` 展开测试目录，门禁要求逐项 `ReadTextFile`，甚至诱发目录占位操作。 | 插件工作流只声明确实要求阅读的普通文件，如 Guide、当前模块报告和当前 JSON；不把目录或测试树 glob 当成“已读”门禁。具体测试、Spec、RTL 由任务选取和 Checker 的证据引用约束。保留 UCAgent 原有真实读取记录机制，不增设可绕过阅读的 `register_reference`。 |
| P0 | WaveInfo 输出溢出时 receipt 与 case 对应关系难恢复；无效调用也出现在 store。 | UCAgent 核心提供只读、签名验证的 `ListWaveInfoReceipts(test_case_name, usable_only, limit, offset)` 和按 `receipt_id` 获取详情的入口。列表返回精确 `test_case_name`、`receipt_id`、会话/时间、调用窗口、状态、可用性和信号组摘要；详情按需返回已保存的完整 result。默认过滤不可用记录，允许显式查看失败记录用于诊断。WaveInfo 当次响应也带精确 case 身份、可用性、`timeline_truncated` 和遗漏点数。插件直接使用核心工具，不重新封装波形分析。 |
| P0 | 大 JSON 靠整文件 `json.dump`、手工备份；当前文件工具写目录仅开放 `notes/`。 | 插件提供仅作用于当前模块 `bug_review.json` 的 JSON Pointer 批量更新工具或等价通用 JSON 文件工具：调用含 `expected_sha256`、操作列表和目标路径；逐项检查指针、类型及当前阶段允许的字段，整批原子写入，冲突不覆盖。阶段开始保留一次可恢复快照；Skill 给出按 Bug/case 定点更新示例。Skill 关闭时仍开放同一工具与格式说明。 |
| P0 | Checker 对 `spec_ref` 类型和 `路径:行号` 格式只抛底层错误，造成多轮 Check 试错。 | 插件 Checker 返回有界的结构化问题列表，逐项给出工作区、`bug_id`/case、JSON 字段路径、实际类型或值摘要、期待格式、示例和下一步。`spec_ref`/`rtl_ref` 明确要求一条相对 `{OUT}/inputs/<workspace>/` 的现存源文件引用 `路径:起始行[-结束行]`；多个证据放在 `evidence.spec`/`evidence.rtl` 数组。现有 `Check` 已执行只读校验，不新增 `dry_run` 参数。 |
| P1 | 长窗口截断、信号名带换行和大结果显示溢出导致重复调用或误判。 | WaveInfo 明确报告截断及可缩窄的窗口/分页建议；信号路径报错返回被拒路径及信号目录中的精确候选，不静默改写路径。Skill 指导先取精确信号名、选择覆盖事务的窗口，再调用最终 WaveInfo；缺少必要事件时保持未定。完整结果从签名 receipt 读取。 |
| P1 | `SetSkillUsage` 顺序与技能名传输不清楚，阶段收尾重复。 | 阶段任务和 Guide 写清 `ListSkill → ReadTextFile(SKILL.md) → 完成产物 → Check → SetSkillUsage → Journal → Complete`，并从 CurrentTips 复制当前阶段的精确 Skill 名。核心错误显示收到的 Skill 名及期望名，便于定位控制字符；不把被污染的名字自动规范化为另一项已记录证据。先不合并 `stage_finish`，保留独立 Check 与使用证据语义。 |
| P1 | 报告 Skill 静默结束；Bash 当前目录漂移。 | `render_report.py` 输出本次生成的文件路径、数量和 JSON 来源；Skill 脚本仍由 `RunSkillScript` 以固定 DUT 工作区为当前目录执行，所有产物定位使用运行配置的 `OUT`。无需改动通用 `RunSkillScript` 返回协议。 |

### 3. 实施顺序与完成标准

1. 先实现两个 Make 入口的重跑范围、模块专属目录与根目录总索引，确保新增 B 的单模块命令不会重开 A；默认入口仍重跑全部。同步 Make/CLI、发布器、Checker、Guide、阶段 Skill 和产物格式。
2. 修正 `reference_files`，加入 JSON 定点更新及字段级诊断；用 `spec_ref` 错误、并发修改、目录引用和 26 条裁决的批量更新场景验收。
3. 在 UCAgent 核心加签名 receipt 查询及 WaveInfo 结果摘要，随后更新波形 Skill；用同名不同会话、失败 receipt、显示截断和精确 TC 映射场景验收。
4. 更新阶段提示、脚本输出与操作说明；分别检查 Skill 启用和关闭的同一产物契约，并以 A 已完成后新增 B、单独重跑 A、默认重跑 A+B、B 失败保留旧报告的场景完成集成验收。

V2.0 不以“33 个失败全部 confirmed”作为成功判据。裁决仍由正确测试、真实波形、Spec 和 RTL 因果链支持；`refuted` 保留原声明且复核置信度为 `0`，证据不足保持 `inconclusive`。

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
