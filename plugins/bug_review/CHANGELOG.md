
# Bug Review 工作流与版本记录

## 当前基线：v1.0（2026-10-05）

本节定义当前 Bug Review 工作流的基线契约。后续功能在此基线上迭代；如果实现与历史版本记录冲突，以本节和当前代码为准。v1.0 不承诺兼容旧版工作区、旧版 `source/`／`tests/` 布局、旧版 case 路径或旧版 JSON 记录。已有运行产物应按 v1.0 重新准备。

### 工作流目标

Bug Review 复核一个已经完成 DUT 准备的 UnityTest 模块。它重新收集并执行当前测试，分别分析测试失败、验证环境、规格、DUT 波形和 RTL 证据，最后把原报告中的 Bug 声明与本次复核结果对账，形成可追溯的 HTML 报告。

一次失败不自动等于 DUT Bug。v1.0 将失败区分为环境问题、测试实现问题、规格理解问题、规格歧义、证据不足和疑似／确认的 DUT 缺陷。确认 DUT Bug 至少需要正确的失败测试、可核实的 Spec 要求、有效的波形或明确诊断，以及能够解释首个偏差的 RTL 证据。

### 两种独立启动入口

两种入口都必须能够独立准备同一份 v1.0 工作区：

```text
Master UI
  编译／启动阶段使用 launch.yaml 和 filelist.f
  Bug Review 工作区使用 Master 已准备好的 DUT、RTL、Spec、Guide_Doc

插件 Make
  make bug_review_<module>
  由插件完成同等的工作区准备并启动 bug_review:analysis
```

`launch.yaml`、`filelist.f`（或 `filelist.txt`）只属于编译和启动输入，编译或启动完成后不复制到 Bug Review 工作区。Master 提供的 `<dut>`、`<dut>_RTL`、`<dut>_Doc` 和 `Guide_Doc` 是唯一来源；Bug Review 只准备并复制 UnityTest 到 `verification_review/run/unity_test/`。

### v1.0 工作区布局

```text
<workspace>/
├── Guide_Doc/                 # 运行时指导
├── <dut>/                     # Master／Make 准备好的 DUT Python 包和运行文件
├── <dut>_RTL/                 # RTL 原文快照
├── <dut>_Doc/                 # Spec／接口／验证文档
├── verification_review/
│   ├── report/                    # 生成的模块报告
│   ├── analysis/                  # 结构化复核记录和阶段诊断
│   ├── notes/                     # 运行笔记
│   └── run/
│       ├── unity_test/
│       │   ├── tests/             # 唯一可执行测试副本
│       │   │   └── data/          # Toffee／波形 session 的 canonical data root
│       │   └── ...                 # 测试 fixture、模型和辅助文件
│       └── test_report/            # pytest/toffee 命令、stdout、stderr、报告快照
└── .ucagent/                  # 阶段历史和签名 WaveInfo 收据
```

v1.0 不创建或依赖顶层 `source/`、顶层 `tests/`、`run/<dut>/` 或工作区根部的 `unity_test` 符号链接。测试文件系统路径只有 `verification_review/run/unity_test/...`；pytest target 使用相对于 `verification_review/run/unity_test` 的 `tests/...`。`verification_review/run/unity_test/data/` 是波形 dump 的唯一目录：每次运行的 toffee 会话由工具自动整体搬入该目录下以其时间戳命名的独立新目录（一次运行一个目录，永不覆盖），`RunTestCases`（pytest cwd）、WaveInfo 与基线清理共同使用该数据根；历史遗留的 `tests/data` 会话在基线导入时原样搬入为独立目录。

### 六个阶段

| 阶段 | 目的 | 主要结果 |
| --- | --- | --- |
| `full_replay` | 收集当前 pytest 全部 node，建立执行基线并导入每个结果。 | `test_manifest.json`、`replay_summary.json`、case 骨架 |
| `case_triage` | 独立于原 Bug 结论分析每个失败／错误／xpassed case，审查环境质量。 | `failure_analysis`、`environment_review.json` |
| `dut_evidence` | 为疑似 DUT 失败选择代表 case，获取签名波形和可核实的事务证据。 | `waveform`、receipt、viewer、attribution draft |
| `report_reconcile` | 对照原 Bug 摘要、分析、Spec、RTL 和本次 case 结果，提交 Bug↔case 归属。 | attribution revision、`report_reconciliation.json` |
| `root_correlation` | 对每个 Bug 作 confirmed/refuted/inconclusive 裁决并合并共享根因。 | Bug decision、`root_causes.json` |
| `publish` | 渲染并核验模块首页、case、Bug、源码和波形资源。 | `report/index.html`、`report_manifest.json` |

### 输入契约

一次复核处理一个 `inputs/<module>/`。输入目录需要：

| 输入 | v1.0 要求 |
| --- | --- |
| `unity_test/tests/` | 必需；包含可由 pytest 收集的测试、fixture、驱动、参考模型和辅助代码。 |
| 原 Bug 文档 | `unity_test/<dut>_bug_summary.md`、`unity_test/<dut>_bug_analysis.md` 至少一份，建议两份都提供。 |
| `<dut>/` | 与当前 Python 环境兼容的 DUT 包和运行文件。Master 模式下由 Master 准备，Make 模式下由 `init_<module>` 准备。 |
| `<dut>_RTL/`、`<dut>_Doc/` | 与 DUT 版本匹配的 RTL 和规格文档，供证据引用。 |
| `.pytest.ini` | 可选；存在时用于保持原测试收集和运行参数。 |
| `launch.yaml`、`filelist.f` | 仅供编译／启动，不进入 v1.0 Bug Review 工作区。 |

输入中的旧波形、覆盖率、`.ucagent/` checkpoint 和旧 `uc_test_report/` 不作为本次执行结果。本次测试结果以 `verification_review/run/test_report/` 和 `verification_review/analysis/replay_summary.json` 为准。

### 核心代码文件

| 文件 | 职责 |
| --- | --- |
| `src/bug_review/workflows/analysis.yaml` | 声明六阶段、阶段任务、参考文件、Skill 和 Checker。 |
| `src/bug_review/core/layout.py` | 定义 v1.0 工作区布局、canonical 路径和逻辑路径解析。 |
| `src/bug_review/core/records.py` | Pydantic 记录模型；当前记录 schema 为 `bug_review.v8`。 |
| `src/bug_review/core/inventory.py`、`tools/collection.py` | 收集测试、建立 `review_index.json` 和 case 初始记录。 |
| `src/bug_review/core/replay.py` | 保存全量重放结果、批次快照和执行证据。 |
| `src/bug_review/core/claims.py`、`core/attribution.py` | 原报告主张提取、归因草稿校验和 revision 提交。 |
| `src/bug_review/core/validation.py` | case、Bug、根因、引用、波形和阶段完成条件的确定性校验。 |
| `src/bug_review/checkers/stages/*.py` | 六个阶段的 Checker 实现。 |
| `src/bug_review/core/reporting.py` | 生成模块首页、case／Bug 页面、源码预览和报告 manifest。 |
| `src/bug_review/publishing.py` | 发布报告、复制可用波形资源并重建顶层入口。 |
| `src/bug_review/Guide_Doc/analysis.md` | 给工作流 Agent 的阶段操作和产物契约。 |
| `src/bug_review/skills/` | 可选的阶段指导和加速脚本；禁用时不能削弱阶段目标或 Checker。 |

### 核心数据结构

`verification_review/analysis/review_index.json` 是活动记录的入口，不保存完整原文。它包含：

```text
ReviewIndex
├── workspace              # 模块和工作区身份
├── source_files           # DUT、Spec、RTL 和原报告位置
├── stage_status           # 六阶段状态
├── bugs                   # BugEntry：原声明、原标签和归因候选
├── cases                  # CaseEntry：规范 case ID、pytest target、record_path
├── attribution_revision   # 当前归因 revision
├── claim_mapping_path     # 当前主张映射
└── root_path              # 当前根因裁决
```

每个 case 的活动记录是 `CaseRecord`：

```text
CaseRecord
├── replay            # status、baseline、report node、执行阶段和重跑记录
├── test_review       # 测试正确性、输入、测试预期和驱动时序
├── failure_analysis  # 失败类别、场景、Spec 预期、测试预期、实际行为、理由和引用
└── waveform          # conclusion、窗口、信号组、receipt、viewer 和诊断
```

Bug 级记录由 `BugRecord` 表示，包含 `phenomenon.scenario`、`phenomenon.spec_expected`、`phenomenon.actual`、`phenomenon.bug_root_cause`、case 关联和 `Decision`。四个现象字段分别回答“验证什么、规格要求什么、当前 case 发生什么、RTL 为什么这样做”，并携带可跳转的源码或证据引用。根因记录由 `RootsRecord` 表示，保存共享 RTL 引用、首个错误、因果链和成员 Bug。

v1.0 的页面展示将“现象分析”和“证据溯源”分开：现象分析说明验证场景、规格预期、实际行为和 BUG 根因；证据溯源分别提供 Spec、Case、RTL 三张可点击行号表。后续字段结构化改造应在此展示契约上迭代，不再让每个 case 自由生成不可比较的长段落。

### 输出结构

```text
output/
├── index.html                 # 所有已发布模块的入口
├── serve.py                   # 可独立启动的静态报告服务
└── <module>/
    ├── verification_review/
    │   ├── analysis/
    │   │   ├── review_index.json
    │   │   ├── cases/ 或 attributions/<revision>/cases/
    │   │   ├── replay_summary.json
    │   │   ├── test_manifest.json
    │   │   ├── environment_review.json
    │   │   ├── report_reconciliation.json
    │   │   ├── coverage.json
    │   │   └── diagnostics/
    │   ├── report/
    │   │   ├── index.html
    │   │   ├── cases/
    │   │   ├── bugs/
    │   │   ├── sources/
    │   │   ├── waveforms/ 或 surfer/
    │   │   └── report_manifest.json
    │   ├── notes/
    │   └── run/
    │       ├── unity_test/
    │       └── test_report/
    └── .ucagent/
```

读取 case 或 Bug 时必须先读取 `verification_review/analysis/review_index.json`，再使用其中的 `record_path`；不能根据 case 编号或 Bug 编号自行拼接路径。报告是 `verification_review/analysis/` 活动记录的可重建视图，不应被当作分析数据源。

### v1.0 已知边界与后续迭代方向

- v1.0 使用当前 `bug_review.v8` 记录模型；场景、规格预期、测试预期、实际行为和归因理由已经拆成结构化事实字段。
- v1.0 允许 Skill 提供 stdout 摘要、失败签名和填写模板，但 Skill 是可选的；禁用 Skill 时，Agent 仍可使用普通文件工具和更新工具完成同一契约。
- v1.0 已固定 `verification_review/run/unity_test/tests/` 为 canonical 测试目录、`verification_review/run/unity_test/data/` 为唯一波形 dump 数据根；不继续扩展旧路径兼容分支。
- 报告已把现象分析改为口语化叙述，把证据溯源改为 Spec、Case、RTL 三张可点击证据表，并明确代表 case 与同机理 case 的影响范围。
- 后续迭代可增加失败签名族记录，让同一机理只分析一次，每个 case 只保留当前输入、窗口和首个偏差等差异事实。

本文的“当前基线：v1.0”描述现行实现和新工作区契约。文档末尾的 `v1.0.0`～`v1.4.0` 条目是历史演进记录，用于解释设计来源，不是当前运行布局；历史条目中出现的 `source/`、`results/tests/`、`runs/run-<id>/` 等路径不应复制到新的 v1.0 工作区。后续版本在当前基线上递增，并同步更新本节、输入契约和运行时指导。具体设计依据、试跑反馈和待验收事项仍以 [ANALYSIS_OVERVIEW.md](ANALYSIS_OVERVIEW.md) 为准。

本页的功能版本号用于整理工作流演进，不表示插件包已经按这些版本发布；`pyproject.toml` 当前声明包版本 `0.1.2`。历史迭代没有可靠的统一发布日期，因此版本标题不补写推测日期。本稿更新于 2026-10-09。

## 当前框架（v1.0 摘要）

Bug Review 一次处理一个 `inputs/<name>/` 模块（目录名即模块名）。标准输入与补齐方式见 [INPUTS.md](INPUTS.md)。输入中的 Bug 摘要、详细分析、测试、Spec 和 RTL 是待核查资料；Makefile 在独立工作区准备只读原文快照、测试执行副本和 DUT 包，随后收集并重跑全部 pytest 用例。每个阶段由工作流指定目标、参考文件和输出文件，Checker 核对实际产物及证据；Skill 提供操作指导，波形取证使用 UCAgent 的 WaveInfo 与签名收据。阶段核验与发布分别由 `checkers/` 与 `publishing.py` 完成；启动复核由 UCAgent 以 `--plugin` 加载插件。

`review_index.json` 是本次运行的轻量索引：保存模块身份、原 Bug 身份、阶段状态和逐 case／Bug 记录路径。初始 Bug 骨架不推断 BG／FC／CK 或 case 归属；复核后的关系由 LLM 填入归因草稿，再经过来源与一致性校验提交。执行、归因、裁决、根因和覆盖率分别保存在独立记录中；原报告长文、Spec／RTL 原文及完整波形不复制进索引。报告从当前活动记录生成，HTML 是可重建的展示结果。

### 六阶段流程

| 阶段 | 核心工作 | 主要产物或变化 |
| --- | --- | --- |
| `full_replay` | 按当前 pytest 配置收集全部精确 node，建立原 Bug 身份骨架，重跑全集并逐项记录基线结果。 | `test_manifest.json`、`replay_summary.json`、`review_index.json`、逐 case 骨架。 |
| `case_triage` | 在阅读原 Bug 根因结论之前，逐个分析失败 case 的测试预期、规格预期、实际行为和环境质量。 | 逐 case 的 `failure_analysis`、`environment_review.json`；必要时记录定向复跑。 |
| `dut_evidence` | 对疑似 DUT 缺陷或时序争议分析有效事务窗口、关键信号和波形；原文 BG 块只作初步 case 线索，签名收据仍绑定精确 case。 | 空白归因草稿；逐 case 的波形结论、窗口、信号组、receipt ID 和 viewer URL。 |
| `report_reconcile` | 由 LLM 阅读原 `bug_summary.md`、`bug_analysis.md`、测试、Spec 与 RTL，填写 BG／FC／CK、主张行段和 case 归属，再核实统计差异。 | 活动归因修订、`claim_mapping.json`、case↔Bug 关联、`report_reconciliation.json`。 |
| `root_correlation` | 结合正确测试、波形、Spec 与 RTL 作逐 Bug 裁决；把相同首错和因果链的确认项归入同一根因。 | 活动 Bug 裁决修订、`root_causes.json`；原声明始终保留。 |
| `publish` | 从活动记录渲染并核验模块、失败 case、Bug、源码与可用的完整波形预览，再发布模块入口并更新总门户。 | `report/index.html`、`report/cases/`、`report/bugs/`、`report/sources/`、可用时的 `report/surfer/` 与 `report/waveforms/`、`report_manifest.json`。 |

失败 case 可归因为环境、测试实现、Spec 理解、规格歧义、证据不足或 DUT 缺陷；一次失败本身不等于 Bug。原报告的 Bug 即使未复现也保留；充分排除 DUT 缺陷时复核置信度为 `0`，证据不足时保持未定。已确认的 DUT Bug 需要可复现的正确测试、有效签名波形、真实 Spec 要求和 RTL 因果链。

### 插件文件组织

| 位置 | 职责 |
| --- | --- |
| `Makefile`、`README.md` | 默认全模块和指定模块的运行入口、基本使用说明。 |
| `src/bug_review/workflows/analysis.yaml` | 六阶段任务、参考文件、输出文件、Skill 与 Checker 配置。 |
| `Makefile`、`src/bug_review/publishing.py` | 模块工作区准备与报告发布。 |
| `src/bug_review/core/`、`tools/` | 共享记录、校验和报告实现，以及复核工具接口。 |
| `src/bug_review/checkers/` | 阶段完成前的确定性校验。 |
| `src/bug_review/Guide_Doc/`、`skills/`、`templates/` | 运行时指导、阶段操作脚本和初始模板。 |
| `src/bug_review/core/reporting.py`、`lang/zh/report.json` | 报告页面、源码预览、中文文案及页面核验。 |
| `ANALYSIS_OVERVIEW.md` | 需求迭代、设计取舍、实跑反馈与后续规划。 |

### 输出目录：先看哪里

默认根目录为 `plugins/bug_review/output/`，可通过 `OUTPUT_ROOT` 配置。`make bug_review_all` 依次复核 `inputs/` 下全部模块；`make bug_review_<module>` 只运行指定模块。每个模块使用独立工作区，已有模块目录时 `init_<module>` 拒绝覆盖。

```text
output/
├── index.html                 # 所有已发布模块的入口
├── serve.py                   # 独立报告服务
└── <module>/
    ├── analysis/               # 索引、case、归因、裁决、草稿及诊断
    ├── report/                 # 直接渲染并校验的模块报告与资源
    ├── <module>/               # DUT 可导入包和运行文件
    ├── <module>_RTL/           # RTL 快照
    ├── <module>_Doc/           # Spec 和接口文档
    ├── Guide_Doc/              # 运行时指导
    ├── run/
    │   ├── unity_test/         # 唯一测试执行副本
    │   └── test_report/        # pytest/toffee 报告和执行日志
    └── .ucagent/               # 阶段状态和签名 WaveInfo 收据
```

从 `analysis/review_index.json` 的活动路径找到逐 Bug／case 记录和根因修订，不按 ID 猜测文件名。签名收据存于模块工作区的 `.ucagent/`；`report/` 只公开报告及预览资源。覆盖率数字只在 `analysis/coverage.json` 有可核实来源时展示，否则明确标示不可用。

## 版本变化

### v1.3.2 — 波形按运行分目录保留并固化定向取证流程

- 波形 dump 改为按运行保留：每次 `RunTestCases` 结束时，工具自动把本次 toffee 会话整体搬入 `unity_test/data` 下以其时间戳命名的独立新目录（一次运行一个目录，永不覆盖；时间戳撞名时自动追加序号），历史遗留 `tests/data` 会话在基线导入时原样搬入为独立目录。此前 toffee helper 每次新建会话会删除旧会话（`max_tmp_history=1`），批次之间的失败用例波形因此丢失，只能整批重跑；现在跨批次保留。
- 基线导入清理改为按会话执行：导入只在各会话内删除通过/跳过 case 的 fst/dat 波形，失败、错误、xfailed、xpassed 及无法归属 case 的波形在各自会话中原位保留；参数化用例共享函数名按"任一归属需要证据即保留"处理，不再跨会话合并或整目录删除。导入结果回报搬入的会话数、删除的文件数与字节数。
- WaveInfo 默认仍只搜最新会话；bug_review 工作流经 `tools.WaveInfo.session_scope: all` 显式切换为按新到旧搜索全部会话，优先 fst，被命中波形来自较早会话时在返回中标注 `is_latest_session=false` 及其所属会话时间，不再因新会话为空而拒绝旧会话中保留的失败用例证据。
- dut_evidence 阶段固化两条纪律：除可用性盘点指出的定向复跑外禁止再次运行任何测试，已保留波形被覆盖或删除后也不得通过重跑补做；返回 `evidence_window_required` 时逐字按返回的 `recommended_evidence_call` 重试同一 case，不自行发明新窗口。
- 基线索引中的 `waveform_test_case_name` 在写入时即规范化为工作区相对形式（`tests/...::name`），full_replay 对账与证据校验共享同一身份函数，消除报告前缀导致的身份不一致。
- 波形盘点脚本 `check_wave_availability.py` 改为对照全部会话（新到旧）分类 fst/vcd 可用、仅 dat、缺失三类，并打印当前全部会话目录。

### v1.3.1 — 工具自动记录覆盖率证据并清理无用波形

- `CaptureReplayReport` 在基线补齐全集后，自动把本次保存的 `coverage_data/code_coverage.json` 与 `toffee_report.json` 证据引用（含精确行数范围）、`run_scope` 和行覆盖分子/分母写入 `coverage.json`；评审者只核对机械字段并按需在 `basis` 补充口径说明，不再手写 `source_ref`。未补齐全集的部分批次不写覆盖率，证据缺失的指标保持原状由评审者显式记录。
- 覆盖率证据引用格式错误的 Checker 诊断改为给出确切的修复动作（`UpdateReviewRecord` 补行号后重新 Check），并明确已完成的测试运行绝不因记录字段重复执行、已导入的基线不可重复导入。
- 全量重跑基线补齐全集后，`CaptureReplayReport` 同时清理并统一波形位置：全部 dump 收敛到 `verification_review/run/unity_test/data` 下最新 `toffee_tmp_*` 会话（与 `RunTestCases` cwd、WaveInfo 数据根同址）；更早会话及历史遗留 `unity_test/tests/data` 会话中失败、错误、xfailed、xpassed case 的 dump 先并入该会话（同名以最新会话为准），再删除原目录；最新会话内仅删除通过/跳过/未运行 case 的 fst/dat 文件，失败等异常及无法归属的文件保留供 dut_evidence 直接取证。参数化用例共享的函数名按“任一归属需要证据即保留”处理；导入结果回报删除的会话数、文件数与字节数。
- dut_evidence 波形只消费第一阶段保留的失败用例 dump，不整批重跑：waveform-review skill 新增 `scripts/check_wave_availability.py` 一次盘点目标 case 的 dump 可用性（fst/vcd 可用、仅 dat、缺失三类），仅对缺失或仅 dat 的 case 按精确 replay_target 定向复跑。
- dut_evidence 取证改为单次完成：逐字使用 `ResolveReviewCase` 返回的 `waveform_test_case_name`（不自行拼接路径或补 `.py` 后缀），直接以完整 signal_groups 与有效事务窗口取得签名收据，取消“先探测后取证”的固定预跑；仅在 `metadata_only`/`signal_not_found` 时降级探测，信号名以收据 `signal_groups` 或 preset 为准、未知信号用 regex pattern 探索；`max_points`/`max_signals` 低于默认会截断 timeline 使 `evidence_usable=false` 整次作废。可用收据立即 `ApplyReceiptToCase`，观察与关联文字用 `UpdateCaseRecords` 批量落盘。
- 插件 WaveInfo 绑定统一到 `verification_review/run/unity_test`，与 `RunTestCases.test_dir`（pytest cwd，决定 dump 会话落点）同址；此前 `unity_test/tests` 层级会让 WaveInfo 找不到重跑产生的 dump 会话。agent 级默认 WaveInfo 支持 `tools.WaveInfo.test_dir` 覆盖（空值回退 `tools.RunTestCases.test_dir`），插件两处配置保持一致。
- 基线导入自动归档并预填失败证据：`RunTestCases` 每次运行把 pytest 原始 stdout 随 current test report 发布（`pytest_stdout`），导入时归档到 `{OUT}/diagnostics/run_logs/<批次>.txt`，并按 traceback 把机械事实（断言摘要、断言行、失败位置、观测异常行、证据引用、assertion 阶段）预填进对应 failed case 的 `failure_analysis`——只填空字段、绝不覆盖评审者内容；参数化同名失败永不猜测，无法对齐的段落计入 `failure_evidence.ambiguous`。
- 新增 `UpdateCaseRecords` 批量写入：草稿形如 `{"cases": {case_id: 完整记录}}` 放在 `{OUT}/drafts/`，一次校验全部（case_id 一致、索引存在、bug_ids 与索引对齐、case_issues）再统一落盘，任一非法则整批不写；52 个失败 case 的逐条两调用（草稿+写入）收敛为每批一次调用。单 case 校验逻辑与 `UpdateReviewRecord` 共用同一实现。
- replay-review Skill 脚本改为复用 `bug_review.core.failures` 的解析/提炼，并自动合并 current report 的 `pytest_stdout` 与历史 run_logs 两个证据源（新到旧、同名取最新）；取消“先把 RunTestCases 返回手工保存到 run_logs”的前置步骤。
- agent 级默认 WaveInfo 支持 `tools.WaveInfo.test_dir` 覆盖（空值回退 `tools.RunTestCases.test_dir`）。

### 历史 v1.4.0 — V4.1：输入与运行区精简

**代码已实现；真实 LoadUnit 与远程 Master 全流程待目标环境验收。**

- 根目录 `launch.yaml`、`filelist.f`（兼容 `filelist.txt`）、测试与原 Bug 报告构成标准输入；`input-preparation` 仅在缺少材料时补齐。运行准备不再自动编译：要求先按 filelist 编译好 DUT 包（插件根目录 `make init_<dut>`，仅包目录缺失时由 picker 编译），并验证其能被当前 Python 导入；filelist 解析跳过 `+incdir+` 等编译器指令。
- 输入目录名即模块名（`inputs/<module>/`，不再使用 `workspace_` 前缀），运行区为 `output/<module>/runs/run-<id>/`。启动仅由 UCAgent 以 `--plugin` 直接加载插件完成：插件移除了 `run-analysis`／`launch` 包装入口、`picker_build` 重编译机制与 `picker-package`／`picker-check` 子命令。插件 Makefile 参照主 Makefile 的 `init_% → test_%／mcp_%` 结构：`init_<module>`（picker 编译与运行区准备）派生 `bug_review_<module>`（无人值守）与 `mcp_bug_review_<module>`（`--tui`），另有 `bug_review_all`、`status_<module>`、`publish_<module>`、`serve`、`plugin-check`。原 `workflow.py` 拆为可直接导入的 `prepare.py`、`checkers/analysis.py`（阶段核验）、`publishing.py`（发布与总门户）和 `layout.py`／`inventory.py`，命令行收敛为 `python -m bug_review prepare-analysis|status|publish`；仅被历史实现引用的 `analysis_core/` 移除，原子 JSON 写入并入 `json_io.py`。
- 历史运行准备曾建立 `source/` 原文快照、`results/tests/` 测试副本和 `<module>/runs/run-<id>/` 运行区。v1.0 已将这些布局收敛为工作区根部的 `<dut>`／`<dut>_RTL`／`<dut>_Doc` 与 `verification_review/run/unity_test/`，不再沿用历史路径。
- 模块报告发布为实体目录，旧公开报告保存在本次 run；归档运行在 Master 同步回规范 run 后发布。总门户与报告页面无需私有运行区即可分享。

### v1.3.0 — V4：原始主张归属由 LLM 复核

**代码已实现，真实模块全流程待试跑验收。**

- 初始索引只保留原 Bug 身份和未经归属的 BG 原文块。`ReportClaimBlocks` 按行段列出原标签和 TC 字样；归因草稿与裁决草稿的工具和 Skill 脚本只创建空白格式，具体关系、引用和结论由 LLM 阅读证据后填写。
- `CommitAttribution` 核对每个原 BG 块都有去向、原标签和复核关系分别保留、引用存在、case 双向关联一致，然后一次提交映射与对账记录。`ReviewBugContext` 可按尚未提交的草稿查看主张，不再按 CK 路径或关键词推断归属。
- 增加按 Bug／case 过滤的有界收据摘要、可续做 case 进度、精确 case 别名解析及原报告材料的来源提示。复核记录保留原标签、复核后层级及归属理由。JSON 契约更新为 `bug_review.v7`；新运行区按当前格式建立。
- 模块报告将高置信度确认 Bug 按最终根因聚合，一组一行并保留成员详情链接；Bug 详情使用统一布局，归因与根因以中文段落概述，相关文档与 RTL 源码分别呈现。
- Bug 与失败 case 详情的签名波形提供关键观察和完整预览按钮。发布时复制 Surfer 静态前端、仍可从签名收据定位的原波形及可独立运行的 `output/serve.py`；本地报告服务直接提供静态资源，保留原令牌中的信号和时间窗口，不请求 UCAgent 动态波形接口。收据对应的原文件已轮换时显示不可预览原因，不用其他运行的波形代替。

### v1.2.0 — V3：全量失败归因与证据报告

**V3.0～V3.2 的代码已实现，随后由 v1.3.0 的归属流程承接。**

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
