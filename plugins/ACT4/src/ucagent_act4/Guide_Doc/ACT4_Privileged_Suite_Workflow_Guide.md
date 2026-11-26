
# ACT4 Privileged Suite 生成工作流指南

本文面向 ACT4 privileged suite 的资产作者、系统验证工程师和 reviewer，解释
`privileged-suite-generation.yaml` 如何把一份覆盖计划逐步变成可追溯、可复现、可贡献的
ACT4 测试资产。初学者可以按章节顺序阅读；熟悉 ACT4 的工程师可直接查看第 4 节的
阶段门禁、第 15 节的 checker 矩阵和第 18 节的交付检查表。

对应配置文件：
`workflows/privileged-suite-generation.yaml`

本文是工作流的阅读指南，不替代 RISC-V 规范、ACT4 Developer Guide 或当前
`riscv-arch-test` 源码。ACT4 会演进；凡是接口、工具版本或命令行为与本文示例
不一致，必须以本轮冻结的 ACT4 Git HEAD 及其文档为准，并把差异记录为证据。

配套资料：

- 先完成 `Guide_Doc/ACT4_Resources_Guide.md` 的资源准备，再准备工具环境；共享规范用 ACT4Resources 读取，写操作仅使用独立 ACT checkout；
- 最终入口为 `{OUT}/final.md` 和 `{OUT}/changes.patch`，其他草稿与证据放在 `{OUT}/intermediate/{DUT}/`；
- [当前 ACT4 checker 总览](ACT4_Checker_Guide/README.md)；
- [阶段设计模板](act4_template/README.md)：coverage、generator、VM/resource、验证与交付；
- `workflows/privileged-suite-generation.yaml`；
- 各 checker 的实现位于 `ucagent_act4/checkers/act4_*.py`，其单元测试位于
  `plugins/ACT4/tests/test_act4_*.py`。

本文所说的“通过”始终是某个明确 gate 在其证据边界内通过，不是对完整 ISA
certification、外部 DUT 或人工审批的统称。

选择插件工作流后，本指南和阶段填写模板自动复制到工作区 `Guide_Doc/`，
不加载 UCAgent 通用指南，也不渲染输出代码模板。按阶段显式阅读这些资料；更新文档
不会自动改变任务提示或 checker 参数。本文描述现有配置与实现，具体测试接口仍以
每轮冻结 ACT4 为准。

## 1. 先理解要解决的问题

处理器实现了很多架构行为。例如，某个 CSR 只能在特定特权级访问，某条指令在
条件不满足时必须触发指定异常，地址翻译完成后必须访问预期的物理页。仅仅让一段
汇编“能够编译”不能证明这些行为正确。

本工作流建立以下证据链：

```text
CTP 测试计划 + RISC-V 规范
             |
             v
逻辑 coverpoint 和规范规则 ID
             |
             v
SystemVerilog coverage + rule mapping + VM/resource contract
             |
             v
ACT4 Python generator -> 自动生成 .S -> 构建 ELF
             |
             v
参考模型运行 -> signature/results/log -> 可贡献性结论
```

这条链遵循三个核心原则：

1. **先冻结事实，再生成资产。** CTP、manual、ACT4 HEAD、target config、UDB、参考
   模型可执行文件和版本必须先形成 provenance/baseline，后续不能按运行结果倒推或
   改写起始条件。
2. **按 consumer 和子场景决策。** 某个公共 trap 服务、coverage backend 或模型
   能力不可用，只影响直接消费它的 profile。可用的 host、positive 或 suite-local
   子场景继续生成；不允许把局部 blocker 扩大到整个扩展。
3. **生成、运行和覆盖分层结论。** 静态 asset checker、ELF 构建、参考模型
   self-checking、RVVI trace 和 UCDB/VDB coverage 是不同证据层，任何一层都不能冒充
   下一层。

### 1.1 权威状态与历史证据

工作流会产生多份报告，它们的职责并不相同：

| 状态问题 | 权威文件 | 说明 |
| --- | --- | --- |
| 最终是否可贡献、生成范围、参考模型结果 | `{DUT}_validation_state.yaml` | build 后的最终机器状态 |
| 每阶段审查结论与限制 | `{DUT}_ai_review.yaml` | 只追加当前阶段，保留历史判断 |
| 使用了哪些开关、由谁定义、是否允许 | `{DUT}_switch_capability_audit.yaml` | 必须先于相关生成/构建动作更新 |
| profile、地址域和 VM 资源 | `{DUT}_vm_resource_contract.yaml` | generator 的资源契约，不是运行结果 |
| 贡献源码、证据文件和框架完整性 | `{DUT}_file_manifest.yaml` | 最终 inventory 与贡献边界 |
| 人类最终入口 | `{OUT}/final.md` | 索引并解释权威状态，不另造状态 |

较早阶段出现“尚未运行”是当时的真实状态。后续证据完成后，最终报告必须明确标注
该结论为 historical 或 superseded，并指向新的权威文件。generator/coverage/contract
修改后，旧 checker JSON 仅证明旧版本；需要新的相关检查和执行证据才能确认新版本。
保留已完成 AI review 阶段，把修复和复查记录到当前阶段，不能自动沿用旧通过结果。

链上每一层解决不同问题：

| 层次 | 回答的问题 | 不能替代什么 |
| --- | --- | --- |
| 规范 | 正确行为是什么 | 不能证明测试实现正确 |
| testplan | 哪些行为要测 | 不能证明测试已生成 |
| coverage | 观察哪些事件和组合 | 不能替代测试激励 |
| generator | 如何产生测试激励 | 不能证明运行通过 |
| 编译 | 源码是否合法并可链接 | 不能证明架构结果正确 |
| 参考模型 self-checking | 测试在模型上的期望结果是否闭环 | 不能等同于真实 DUT 通过 |
| Sail/RVVI coverage | 覆盖模型是否实际命中目标 | 不能由普通 Spike 运行冒充 |

## 2. 基础术语

### 2.1 ISA、特权架构和 DUT

- **ISA**（Instruction Set Architecture）是软件可见的处理器契约，包括指令、
  寄存器、异常和内存行为。
- **特权架构**定义操作系统和虚拟机管理器依赖的控制能力，例如 M/S/U 特权级、
  CSR、trap、页表和虚拟化。
- **DUT**（Design Under Test）是被测试对象。在配置中 `{DUT}` 也表示 suite 名，
  例如 `H`。它大小写敏感，不是可以猜测或自动纠正的别名。

常见特权级包括：

| 名称 | 含义 |
| --- | --- |
| M-mode | Machine mode，通常是最高特权级 |
| S-mode | Supervisor mode，通常运行操作系统内核 |
| U-mode | User mode，通常运行用户程序 |
| HS-mode | 启用 H 扩展后的宿主 supervisor 上下文 |
| VS/VU-mode | 虚拟机内部的 supervisor/user 上下文 |

### 2.2 CSR、trap 和状态恢复

CSR 是 Control and Status Register。读写 CSR 可能改变中断、地址翻译、异常委托或
虚拟化状态，因此测试不能只做一次 `csrw` 就结束。完整测试通常需要：

1. 保存原状态。
2. 建立所需前置条件。
3. 执行被测操作。
4. 观察返回值、异常原因或内存结果。
5. 把结果写入 signature。
6. 恢复 CSR、地址翻译和特权级，使 ACT4 框架能正常收尾。

**trap** 是异常或中断导致的控制流转移。需要预期异常的测试必须证明 trap 路由、
cause、返回路径和最终模式，而不是把“程序没有继续执行”当成通过。

### 2.3 Coverpoint、bin 和 cross

- **coverpoint** 是一个可观察条件，例如“在 HS-mode 读取某 CSR”。
- **bin** 是 coverpoint 中的取值分类，例如某字段的每个 bit position。
- **cross** 组合多个维度，例如“访问类型 x 特权级 x 异常结果”。

coverage 命中说明某事件被观察到，不自动说明结果正确。因此测试仍必须把可判定的
结果写入 signature，并通过参考模型执行。

### 2.4 Generator、汇编和 ELF

ACT4 privileged test 通常不是手工维护大量 `.S`，而是由 Python generator 通过
当前 registry 和 `TestChunk` API 生成：

- generator 描述 testcase 和汇编片段；
- ACT4 testgen 把它们组织成一个或多个 `.S`；
- 编译器和链接器把 `.S` 生成 ELF；
- 参考模型运行 signature ELF，导出 signature；ACT4 将其转换为 results 并构建最终 ELF。

当前链路是 `test.S -> build/*.sig.elf -> build/*.sig -> build/*.results -> elfs/*.elf`。
最终 ELF 在 DUT/testbench 的执行需要另行记录；生成完成不能当成已运行它。

`.S` 是生成结果，是否提交按固定 ACT 的 Git tracked/ignore 规则判断。修复测试时修改 generator 并重新生成，
不能手工编辑、拆分、复制或重命名 `.S`。

### 2.5 Signature、results 和 sig.log

- `.sig` 是参考模型导出的原始 signature 数据。
- `.results` 是 ACT4 处理后的结果表示。
- `.sig.log` 记录完整参考模型运行，应包含对应测试的 SIGRUN、signature 区间、粒度
  和唯一成功终态。
- `.elf` 是最终可交给 DUT/testbench 的可执行文件。
- `.sig.elf` 是构建过程中的特定中间产物，不能与最终 `.elf` 混为一谈。

本工作流要求每个生成源、最终 ELF、signature、results 和完整日志可按 stem 配对。
编译器退出码为 0 仍不足以代替这套运行证据。

### 2.6 Self-checking、参考模型和 coverage backend

**self-checking** 在这里表示测试已通过配置中真实声明的参考模型运行，并形成完整的
signature 证据。参考模型可以是当前 ACT4 配置支持的 Sail，也可以是本项目明确允许
的其他模型，例如 Spike。

必须区分：

- Spike self-checking 通过：可作为功能运行证据；
- Sail trace 或 RVVI 可用：说明覆盖采样链可能具备条件；
- Questa UCDB 或 VCS VDB coverage 产生并分析：才是 coverage backend 证据。

前一项不能冒充后一项。Sail/RVVI coverage 不可用但其他参考模型 self-checking 通过
时，工作流允许带 limitation 继续，不允许写成 coverage passed。

### 2.7 地址翻译基础

特权测试可能涉及三类地址：

- **GVA**：guest virtual address；
- **GPA**：guest physical address；
- **PA**：host physical address。

常见路径如下：

```text
单阶段：VA --satp--> PA
G-stage：GPA --hgatp--> PA
两阶段：GVA --vsatp--> GPA --hgatp--> PA
```

页表模式、层数、根表对齐、PTE 权限、VPN/PPN、ASID/VMID 和 fence 都会影响结果。
因此工作流不会因为 suite 叫 `H` 就自动创建某种页表，而是要求 coverage 需求和目标
配置共同证明每个 profile 需要哪一种资源。

## 3. 哪些要求来自哪里

为避免把项目策略误说成 ACT4 官方规定，应区分三类要求：

| 来源 | 示例 | 判定方式 |
| --- | --- | --- |
| RISC-V 规范 | 指令/CSR 语义、异常、地址翻译顺序 | 使用本轮复制的规范与 规则 JSON |
| 当前 ACT4 | registry API、TestChunk、构建目标、配置字段 | 使用冻结 Git HEAD 的源码和 Developer Guide |
| 本插件工作流 | 环境准备、七个资产阶段、保护基线、人类 testplan、证据 schema | 使用当前 YAML 和 checker |

工作流不会假设 ACT4 接口永远不变。每轮都先冻结 Git HEAD，再从该版本读取：

- generator 注册方式和返回类型；
- testcase 自动分文件阈值；
- testgen、build、coverage 和 clean 入口；
- `test_config.yaml`、UDB、DUT adapter 和 `ref_model_exe`；
- README 要求的精确工具版本。

文档与源码不一致时必须阻塞并报告差异，不能凭印象选择一个。

## 4. 工作流总览

工作流先准备资源、环境和原生输入，再规划并验证缺项补全，运行七个资产阶段和原生贡献验证，
共 17 阶段，包含独立 ISA 计划、来源导入、基线审查和生成后复验。补全工作遵循 `Guide_Doc/ACT4_Checker_Guide/ACT4GenerationCompletionChecker.md`。
环境准备契约见
`Guide_Doc/ACT4_Environment_Guide.md`。每个资产阶段先阅读相关资料、在当前 stage journal 中制定工作计划，
再按计划生产或更新资产并记录进度，由现有 checker 验证后进入下一阶段。

| 阶段 | 核心问题 | 关键输出 | 完成门禁 |
| --- | --- | --- | --- |
| 01 coverpoints | 原生计划和 coverage 是否可追溯 | 原生 YAML、派生 CSV/Markdown、coverage、baseline | native plan、coverage、switch、baseline、AI review 均一致 |
| 02 norm mapping | 每条规范 rule 是否映射到真实 coverage 目标 | `coverpoints/norm/{DUT}.yaml` | rule、target、bin/cross 路径集合闭合 |
| 03 VM resources | 每个 consumer 需要什么环境，哪些可正式生成 | VM contract、experimental manifest | profile、能力和地址资源按子场景闭合 |
| 04 generator | 当前 ACT4 API 能否表达所有允许目标 | `priv/extensions/{DUT}.py` | API、target linkage、split、审计与框架完整性通过 |
| 05 build | 生成源码能否形成完整参考模型证据链 | `.S`、ELF、sig、results、sig.log、validation state | stem/XLEN/signature/model/scope 一致且完整 |
| 06 contribution | PR 源码与验证证据是否被正确分离 | contribution set、完整 manifest | 贡献状态、inventory、历史 review、完整性通过 |
| 07 final report | reviewer 能否从一个入口复核最终状态 | 最终 Markdown 报告 | 报告、AI review、manifest 三个 checker 通过 |

阶段 gate 是单向的：`Check` 只给出当前阶段反馈，不推进状态；修复后由 `Complete`
重新执行完整检查并推进。每个阶段都必须更新同一份 AI review。首次 ACT4 写操作前完成
baseline；首次写入后的 04、生成/构建后的 05、贡献整理后的 06 和最终报告后的 07 必须
重新验证 protected framework integrity。

### 4.1 三类最终处置

工作流优先最大化可信资产，同时隔离不确定范围：

| 处置 | 何时使用 | 对主流程的影响 |
| --- | --- | --- |
| allowed / allowed_with_limitations | 当前 API 可生成，直接依赖可满足；限制不破坏资产可信度 | 进入正式 generator 和 generation scope |
| experimental | 规范/API 足以形成候选，但目标能力或运行/coverage 证据不足 | 只写 `experimental/`，不进入正式 pairing 或贡献结论 |
| blocked | 直接依赖缺失，suite-local、positive subset、原生入口和仅生成路径均不可行 | 只阻塞具体 consumer/profile，并记录独立所需动作 |

参考模型失败只是一条 target/profile 级运行事实。更换模型前必须保留首选尝试，定位
首个失败，并分析 suite-local resource、positive subset、native entrypoint 和
generation-vs-validation scope；fallback 只能改变验证后端，不能删除已生成目标。

每阶段都更新同一份 `{DUT}_ai_review.yaml`，只新增或更新当前阶段，不能改写已经完成
的阶段。检查项必须区分：

- `status`：实际结果是 passed、warning、blocked 还是 not_run；
- `confidence`：证据是 confirmed、inferred 还是 unverified；
- `workflow_blocking`：问题是否阻止当前阶段继续。

只有全部检查 passed/confirmed 且没有 limitation 时才能写 `approved`。

### 4.2 工作计划与执行记录

工作计划复用 `StageJournal` / `SetCurrentStageJournal`，作为执行和恢复入口。它描述
“接下来做什么、实际做到了哪一步”，AI review 和 validation state 继续负责审查结论和
验证状态。无需新建计划文件、增加审查 schema 字段、checker 或人工审批。

**何时制定。** 进入阶段后，通过 `CurrentTips` 确认任务，阅读当前 `reference_files`
及必要的前序产物，再细化当前阶段计划。输入阶段先选择原生计划和规范：先记录
资料获取、基线建立的计划，以及七个既有阶段的目标/主要产物/依赖概要；读完本轮原生计划、
specification 和 规则 JSON 快照后，再细化 testplan/coverage 实现项。后续阶段按输入逐步
细化，不要求开工前读完所有资料，也不重复阅读已确认且未变化的文档。

**计划内容。** 将当前 task 结合实际 suite、target/profile、API 和参考证据拆成可执行项。
每项用稳定 ID，说明输入/依赖、具体操作与拟修改路径、预期产物、现有验收依据、进度和
实际证据；相关写入边界可在阶段开头统一说明。任务大小以能独立执行和说明结果为准，
同类目标可按批次合并，不固定项数、不逐文件建项，也不新增任务外的验收要求。
只写“完成本阶段”或照抄 task 不构成可执行计划。

下面是 journal 的简洁填写形式，所有占位项应据实际任务填写，示例不代表已执行：

```markdown
Stage: <当前阶段名>
Goal / scope: <当前目标、target/profile 和相关写入边界>
Workflow outline: <仅首阶段简述七阶段目标、主要产物和依赖；后续引用交接>

| ID | Input / dependency | Action / paths | Output / existing acceptance | Status | Actual result / evidence |
| --- | --- | --- | --- | --- | --- |
| <stage>-P1 | <已读资料或前序项> | <操作及拟修改路径> | <产物及已有检查依据> | pending | 未执行 |

Adjustments: <工作项 ID、原方案、调整原因、新方案；没有则无>
Limitations / handoff: <影响范围、已有报告路径、后续动作；没有则无>
Next: <下一个依赖已满足的工作项和具体动作>
```

状态按实际进度使用 `pending`、`in_progress`、`done`、`deferred`、`blocked`。`done` 必须有
与该项完成条件对应的产物或实际工具结果；计划命令不能作为执行证据。`deferred` 和
`blocked` 要说明原因、影响范围及后续动作，它们只描述对应工作项，阶段是否阻塞仍由
现有规则决定。可选 coverage 或实验验证不可用时可以 deferred 并引用 limitation；必需
工作不能通过删除计划项或改状态绕过。准备交接时说明每个剩余项的处置即可，不要求
为了“全 done”强行执行不可用的可选验证。

**执行与更新。** 先用 `SetCurrentStageJournal({journal: <完整当前阶段内容>})` 保存计划，
再从依赖已满足的未完成项开始。工作项或一批同类目标完成、方案调整、发生失败、准备
中断以及调用 Complete 前更新记录，不逐条 shell 命令记账。该工具设置当前 journal，
所以每次应保留完整计划及已有执行摘要，不能用最新一条覆盖其他项。完整日志和命令
引用已有报告，只保留足以定位结果的摘要、证据路径和关键失败。

新证据或 Check 反馈要求调整时，保留原方案和原因，先改受影响的后续计划再执行；
涉及模型、开关、contract 或范围变化时继续遵守原有审计规则。实际尝试后才发现的失败
如实记录，不倒写为事前已知。后续阶段发现前序问题，在当前 journal 引用原工作项并
记录修复，不改写已完成阶段。计划与既有 AI review、manifest、Check/Complete 在原有
执行节点一并维护，不为计划单独增加检查调用。

**中断与复盘。** 中断或上下文丢失后读取 `CurrentTips`、`StageJournal`，需要前序交接时
再读 `AllStageJournal`；只核实受中断或变更影响的证据，继续下一未完成项。旧运行没有
事前计划时，根据真实证据整理已完成背景并注明“恢复时整理”，只为剩余工作制定计划，
不补造历史或重开已完成阶段。Complete 前保存完成情况、偏差和遗留事项，是否通过以
实际返回为准。阶段 07 使用各阶段 journal，在已有 `Workflow summary` 和
`Evidence chronology` 中概括计划与实际结果的差异、调整原因、处置和剩余影响；引用
工作项 ID 及已有证据，不复制整份台账，也不预写尚未发生的 Complete 结果。

## 5. 阶段 01：从 CTP 到可读 testplan 和 coverage

### 5.1 先冻结 ACT4 基线

在首次写入 ACT4 前，记录：

- `git rev-parse HEAD`；
- `git status --porcelain`；
- 每个受保护文件或符号链接的 path、type、mode 和 SHA-256。

对象路径不可重复；type 必须是 `file` 或 `symlink`，mode 使用引号包住的八进制字符串，
SHA-256 使用 64 位小写十六进制值。完整填写示例见
`Guide_Doc/ACT4_Checker_Guide/ACT4FileManifestChecker.md`。

Git status 记录的是起点背景，不要求仓库绝对干净。已有非关键改动不会自动失败；
受保护对象在本轮发生内容、路径、类型或权限变化才是硬阻塞。

同时创建：

- `{DUT}_act4_baseline.yaml`：受保护对象快照；
- `{DUT}_file_manifest.yaml`：资产与变更事件账本；
- `{DUT}_switch_capability_audit.yaml`：本 suite 所用开关和能力审计。

### 5.2 原生计划和规范输入

输入阶段已捕获 `inputs/receipt.json`、`source_plans` 中的全部 `plans/` 快照（若存在）、逐文件规范原文
和经核验的 `norm-rules.json`。语义以选定原文为准，规则 ID 取 JSON 的 name；待发布规则
通过原文逐字绑定，并在原生映射中保留 untagged_upstream。两者版本分别固定，
需核对文本。不得用进度表或模型记忆代替规范，也不得编辑收据。

### 5.3 原生计划是唯一权威

逐个创建或完善 `inputs/receipt.json` 的 native_plans 所列原生路径，保留组合目标的子计划结构，
遵循捕获的原生 schema。每个
coverpoint 行填写 name、goal、description、expectation、check、rules；保留来源请求。
规范支持的新行为可以补充。Check 自动派生 `{DUT}.csv` 与 `{DUT}_testplan.md`，无需
手工维护两份相同计划。完整原生示例见 `Guide_Doc/ACT4_Generation_Guide.md section 3`。

### 5.4 按需参考其他 suite

只读固定 ACT 副本中相关 testplans、coverpoints、tests 和 generators。比较前置状态、刺激、
值域、预期和恢复流程，仅采纳目标 suite 自身规范确实要求的遗漏。不能用其他 suite 的覆盖
替代本 suite 测试，也不要求强行新增。实际参考路径与采纳依据记在 journal 或已有设计说明中。

### 5.5 规则与设计追溯

原生行的 rules 必须来自公开规则或已核验的原文绑定。`reports/plan_manual_sv_mapping.md` 解释
原文→原生计划→实际 coverage 观察模型，不能把字段名字相似当作行为一致的证明。
完整输入和映射契约见 `Guide_Doc/ACT4_Generation_Guide.md section 2` 至
`Guide_Doc/ACT4_Generation_Guide.md section 5`。

### 5.6 coverage 实现

coverage 文件和 init 文件应遵循当前工作区 ACT4 中语义相近的 privileged suite 范式，
复用前述测试资产对照中已查阅的相关设计。
每个主要 coverpoint/cross 还要在 mapping 说明中记录：

1. stimulus：如何触发；
2. target selector：测的是哪个 CSR、字段、指令或状态；
3. operation qualifier：读、写、执行、trap 等操作条件；
4. observed outcome：观察什么结果；
5. value domain：覆盖哪些值或 bit position。

异常目标必须采样实际 trap/cause；walking-bit 目标应按 bit position 分箱。默认 bin
不能用于制造无法解释的“覆盖”。

## 6. 阶段 02：规范规则到 coverage 的映射

这一阶段生成 `coverpoints/norm/{DUT}.yaml`。它把规范 rule ID 指向实际存在的
`covergroup/coverpoint[/bin]` 或 cross。

当前契约只接受：

- 规则 JSON 中真实存在的 rule ID；
- `coverpoint` 字段中的当前路径格式；
- 明确的 `NOT COVERED` 或 `OUT-OF-SCOPE` waiver；
- 真实存在且属于当前 suite 的 coverage 目标。

仅使用当前原生映射格式，不从 prose 猜 ID，不用 TODO/TBD 代替覆盖解释。

一个逻辑 coverpoint 可以在 mapping 阶段展开到多个实际 coverpoint/cross；原生 source 请求必须保留，不能通过重复行制造覆盖数量。

## 7. 阶段 03：VM/resource contract

### 7.1 为什么需要 contract

privileged testcase 常依赖页表、入口模式、trap handler、内存窗口或特定扩展。
如果 generator 在没有证据时自行假设这些资源，可能编译成功却运行错误。因此先写
contract，再写 generator。

contract 顶层必须包含：

```yaml
schema_version: 1
suite: H
supported_xlens: [64]
selected_target:
  name: <target name>
  test_config: <path>
  XLEN: 64
```

`selected_target` 是唯一字段；`target` 无效。XLEN 必须与实际 test config/UDB 一致。

### 7.2 profile 的粒度

每个 profile 对应具体子场景，而不是笼统对应整个扩展。至少说明：

- coverage targets；
- execution context；
- resource mode；
- XLEN 和 required extensions；
- capability dependencies；
- 地址符号和 GVA/GPA/PA 域；
- 预期结果与恢复流程；
- decision、限制或 blocker。

resource mode 只能是：

| 模式 | 典型资源 |
| --- | --- |
| `bare_or_csr_only` | 不启用地址翻译 |
| `single_stage` | `satp` 和 S-stage 页表 |
| `g_stage_only` | `hgatp`，显式 guest-memory 访问但不一定进入 guest |
| `two_stage` | `vsatp` + `hgatp`，GVA 到 GPA 再到 PA |

`blocked` 是 decision，不是 resource mode。

### 7.3 allowed、blocked 与 experimental

- `allowed`：当前 ACT4 原生入口、目标能力和执行资源都有直接证据。
- `allowed_with_limitations`：可生成，但有明确的非致命限制。
- `blocked`：该具体子场景的直接执行依赖缺失，且所有替代路径都有证据地不可行。
- `experimental`：能够依据规范/API 生成，但运行或能力证据不足，先隔离保存。

标记 blocked 前必须依次评估：suite-local `.data/.bss` 或汇编能否实现、是否有不依赖
受保护服务的正向子集、是否存在已审计原生入口、缺失项是否只影响运行/coverage。

实验资产只能放在 `unity_test/{DUT}/experimental/`，不能注册到正式 generator，不能
进入主流程 `.S`、ELF pairing、`generation_scope` 或 `contribution_ready`。升级时必须
更新审计和 contract，再由正式 generator 重新生成，不能直接复制实验 `.S`。

## 8. 阶段 04：实现 ACT4 generator

在写 generator 前必须读取冻结 HEAD 中的 registry、`TestData`、`TestChunk`、privileged
writer 和 Developer Guide。需要确认：

- generator callable 的真实返回类型；
- `begin_test_chunk`、`end_test_chunk`、`new_test_chunk` 的语义；
- `TestChunk.code/raw_data/num_testcases/split_name`；
- `group_test_chunks()` 和最终文件命名；
- `testcases_per_file` 的当前限制。

根据 asset_contract.yaml 的 extension_sources 新建或补齐实际原生生成器。以下是顶层
入口的路径示例，不要求共享或子目录实现另建一个重复文件：

```text
riscv-arch-test/generators/testgen/src/testgen/priv/extensions/{DUT}.py
```

既有生成器是可复用、可补全的资产，不构成阻塞。共享源码修改需验证其他消费者；
coverage/init/mapping 按实际新增或修改登记，源文件和贡献集保持一致。
缺失模型、工具、刺激/观察接口和通用增强按
`Guide_Doc/ACT4_Checker_Guide/ACT4GenerationCompletionChecker.md` 实施并验证，不只列出待办。

generator 必须用当前 registry 原生参数声明 required extensions、MARCH、params、
extra defines 和分文件策略。需要改变启动特权级、trap 或结束流程时，先使用 switch
audit 证明为 allowed 的 suite opt-in；不能修改通用 template 或 `tests/env` 来影响所有
suite。

每个 testcase 应能追溯到 coverage target 和 VM profile，并包含完整的 setup、操作、
观测、signature 写入和恢复。动态 helper 若让 checker 无法静态追踪，优先调整为可读的
简单传播关系，不应通过字符串拼接隐藏 coverpoint 名。

## 9. 阶段 05：生成、构建和参考模型验证

### 9.1 有界预检

先从目标配置解析 XLEN、MARCH、参考模型和完整命令行，再生成一个最小批次。预检
重点包括：

- RV32/RV64 专属 CSR 或指令；
- 预期 trap 的 handler 和返回路径；
- 入口与结束时的特权模式；
- reference-model argv；
- `# MARCH: rv${XLEN}...` 与 contract/ELF class 是否一致。

CI 的编译器和模型也是预检输入。先读取冻结版本的 workflow、本地 action、工具约束、
pre-commit 配置以及实际存在的 CI 配置发现入口，确定会选择本 suite 的配置。
如果这些配置同时使用 GCC 和 Clang，就分别检查；GCC 接受的 CSR 别名可能被 Clang
在汇编阶段拒绝，不能因此删掉原本用于测试非法指令异常的负向用例。工具版本与
CI 不同的本地结果只能作为补充证据。完整贡献前复现见第 10.1 节。

### 9.2 清理和重新生成

只使用 suite 专属 `WORKDIR=work_itgen_{DUT}`。重跑时若当前 HEAD 提供 `clean-tests`，使用
该入口；否则确认本版本 `make clean` 的作用范围后使用。新鲜副本可跳过清理并注明。
不能调用猜测出来的 target，也不能扫描或清理其他 `work*`。

生成的 `.S` 数量由 TestChunk 边界和 ACT4 自动分文件逻辑决定。每个文件必须有独立
header/footer 和 signature 结构，不能人工拆分。

### 9.3 构建 self-checking ELF

命令形态为：

```bash
WORKDIR=work_itgen_H \
CONFIG_FILES=<config>/test_config.yaml \
EXTENSIONS=H \
CLEAN_INTERMEDIATES= \
make
```

实际 suite、配置和额外参数必须来自本轮审计。不能启用
`CLEAN_INTERMEDIATES=True`，因为工作流需要保留 `.sig`、`.results` 和 `.sig.log`。

每个日志必须证明：

- SIGRUN 对应正确源文件；
- 只有一个最终 SUCCESS；
- begin/end 地址存在；signature granularity 由日志或匹配原生 ELF 的 XLEN/8 规则确定，
  后者须以冻结 ACT4 的签名命令实现为依据，不能由已有记录数反推；
- `.sig` 与 `.results` 的记录数完整覆盖 signature 区间。

`.sig` 记录必须是十六进制值，长度不超过 granularity 对应位数，允许省略前导零；results
接受带标签、空白、注释和逗号操作数的 `.word/.quad` 整数数据指令，不强制按 XLEN 选择
指令，也不比较两个文件的数值。SUCCESS 后允许普通统计输出。

04 先用原生选择清单核对基线审查的全部必验 build。05/06 对同一矩阵逐配置绑定
源码、XLEN 和 ELF/signature/results/log。只对适用源码要求证据，但并集不得漏掉正式源文件；
主配置写入 self_checking，其他配置的成功签名构建写入 attempts。选择信息无法解析时直接报错，
不回退到其他配置的历史产物。`reference_runs_checked` 是进入日志检查的数量；
`complete_reference_runs` 只统计日志、signature/results 格式和区间检查均无 error 的链路，
不表示最终 ELF 已在 DUT 上执行。

checker 还会用 sentinel 对 `final_trap_sig_offset` 前的连续结果做最低限度进度诊断。
由于当前生成格式没有 testcase-to-slot 精确元数据，这只是 warning 级诊断，不能单独
证明或否定逐 testcase 通过。

### 9.3A testcase 可达性与目标排除

描述符数量、源文件存在和 signature 容量都不能证明 testcase 入口实际进入编译结果。
启用 `ACT4TestAssetChecker` 的 `check_testcase_reachability` 后，构建和贡献检查会：

1. 将每个 `_str` 描述符关联到同名入口标签；
2. 保守分析入口所在的完整预处理条件；
3. 使用只读 `nm` 统计所选 ELF 中保留的测试标签。

只有同一 testcase 在 RV32 和 RV64 下都能被证明为不可达时，才以
`testcase_guard_unsatisfiable` 阻止阶段。未知宏、复杂表达式、符号表不可读以及正常的
XLEN/目标能力排除不能推出错误；这些情况记录为 `unverified` 或 warning。报告中的
`compiled_testcases` 只表示标签被编译保留，不能代替参考模型执行、DUT 执行或
Sail/RVVI coverage。若发现互斥值域是生成器错误，必须修复 generator 后通过原生 testgen
重新生成 `.S`，不能手工编辑汇编。

### 9.4 可选的 Sail/RVVI coverage

只有冻结 HEAD 所需的 Sail 版本和 Questa/VCS coverage backend 可用时，才运行类似：

```bash
WORKDIR=work_itgen_H \
COVERAGE_CONFIG_FILES=<sail-config>/test_config.yaml \
EXTENSIONS=H \
make coverage
```

coverage 使用 `COVERAGE_CONFIG_FILES`，不能用 `CONFIG_FILES` 冒充。未执行时不要创建
假的 `_overall_summary.txt`、suite summary/report/uncovered 文件。

### 9.5 validation state

阶段输出 `{DUT}_validation_state.yaml`。完整填写提纲见
[验证与交付模板](act4_template/privileged_validation_handoff_template.md)，不能省略
当前配置要求的 `reference_model_evaluation`：

| 字段 | 内容与判定 |
| --- | --- |
| source_generated、supported_xlens | 实际生成状态及与 contract/ELF 一致的 XLEN |
| self_checking | model、原始 executable/config_file、passed、实际 command |
| sail_coverage | passed、实际 command、未通过的 blocked_reason |
| generation_scope | status、generated_targets、partial_targets、blocked_targets |
| reference_model_evaluation.preferred | 运行前冻结 model/executable/config_file/selection_basis |
| reference_model_evaluation.attempts | 每次 tested/passed/failed targets、命令、失败分类、证据与诊断 |
| reference_model_evaluation.fallback | used/model/reason/affected_targets/evidence，scope_reduction=false |
| contribution_ready | 根据实际证据和限制填写，不预设 true |

coverage 不可用时用 `passed: false`、空 command 和具体原因；当前 05/06 配置允许已有
self-checking 证据的资产保留这一 limitation。unknown 失败不能触发 fallback；模型能力
缺口只有在至少两个失败 target 共享直接依赖和共同根因时才使用分组 diagnosis。
同一 attempt 内同一 target 的 outcome 不得冲突；不同 attempt 的诊断可随修复和重跑更新，
按记录顺序使用该目标最近的 diagnosis outcome 对照最终范围，保留之前的实际尝试证据。

当前 checker 只接受 `generation_scope`，其中各集合的含义为：

- `generated_targets`：至少一个 profile 已生成；
- `partial_targets`：同一目标同时有已生成和 blocked 子场景；
- `blocked_targets`：没有任何可生成 profile；
- 有 partial 或 blocked target 时，status 必须是 `partial`。

这些状态分别表达以下事实，沿用已有字段和报告，不新增必填字段、检查阶段或审批：

| 维度 | 现有证据与含义 |
| --- | --- |
| 正式生成范围 | `generation_scope` 对照 contract 的 allowed/blocked 目标集合；complete 不代表所有设想子场景已实现 |
| 子场景与实验范围 | VM contract、experimental manifest 和已有 review limitations 记录未生成、未验证或实验子场景；experimental 不计入正式 generation_scope，也不单独阻塞贡献 |
| Self-checking | `self_checking` 及所选配置的实际产物链，不自动证明最终 ELF 的 DUT 执行 |
| Coverage | `sail_coverage` 及实际 coverage 报告；缺少 backend 仍按已有规则记录非阻塞 limitation |

## 10. 阶段 06：贡献准备

这一阶段不通过“复制最终文件”修补结果，而是核对整个证据链：

- `.S` 是否都来自正式 generator；
- 每个 `.S` 是否有匹配的最终 `.elf/.sig/.results/.sig.log`；
- allowed profile 是否都有 testcase；
- blocked/partial 是否与 VM contract 和 generation scope 精确一致；
- coverage、mapping、generator 是否仍满足 checker；
- 受保护 ACT4 文件是否与基线完全一致。

`contribution_set` 只列 PR 中真正提交的 ACT4 源资产，例如 suite coverage、norm mapping、
generator 和需要贡献的 CTP 源文件。以下内容不能进入 contribution set：

- 被上游 Git 规则忽略的生成 `.S`；
- ELF、signature、results；
- work tree、虚拟环境、缓存和普通日志；
- checker 输出和内部报告。

这些文件仍可作为验证证据登记在 manifest 的相应 category 中。

贡献源码须脱离本地过程文件使用：VM/generator contract、coverage intent、审查报告、辅助
脚本与配置可以用于生成和验证，但不得成为交付源码的私有运行依赖。稳定的原生依赖直接
复用；新建或修改的计划、规则/参数映射、CTP 章节与源码进入 contribution_set。

### 10.1 选择相关配置与原生验证

依据冻结版本的 CI、README、CONTRIBUTING、原生 target 和模型能力，确定相关编译器、
XLEN 和 test_config，写入 asset_contract.validation_configs。不能仅按名字猜测 suite 被选中。
完整契约见 `Guide_Doc/ACT4_Generation_Guide.md section 4`。

本阶段的 local_ci_reproduction 区分已完成证据与下一阶段待执行工作：已发现且未修复的
suite 错误阻塞；尚未执行的验证记 not_run 和 limitation，不能预填 passed。

随后在 validate_native_contribution 阶段运行 Check(action=validate)。它只将贡献集应用到
固定 HEAD 的临时副本，检查生成结果同步、源码 hooks、UDB 参数、CTP 渲染、选定配置的
编译和最终 ELF 执行。所有源代码变化、hooks 改写或零 ELF 均不可当作通过；根据具体日志
回到原生源文件修复，更新 manifest/hash 后重跑。不要另建重复的手工验证副本。

详细操作见 `Guide_Doc/ACT4_Checker_Guide/ACT4NativeValidationChecker.md`。验证结果来自
实际执行收据，最终报告分别说明资产齐备、原生验证和人工提交前提。默认是 suite 级原生
消费，不是完整上游 CI；未执行的 CI 组合、可选 coverage 或共享源码影响应明确列出，按需
追加回归。不能把替代模型或不同参数的通过写成原 CI 已通过。

## 11. 阶段 07：最终人类报告

最终 Markdown 不是把日志拼在一起，而是面向 reviewer 的索引和结论。稳定章节包括：

- Executive conclusion；
- Final validation state；
- Workflow summary；
- Report index；
- Coverage scope；
- Evidence chronology；
- Limitations and non-claims；
- Human inspector checklist；
- Reproduction。

Final validation state 必须包含结构化 YAML，精确复述 validation state：

```yaml
source_contribution_ready: true
generation_scope_status: partial
```

Evidence chronology 解释早期报告和最终状态的时间关系。旧结论只能标记为 historical
或 superseded 并指向新证据，不能静默挑选有利结果。

最终报告必须明确哪些事情没有被证明，例如：

- 未经过人工审批；
- 未在外部 DUT 上执行；
- 未运行 Sail/RVVI coverage；
- 没有生成 UCDB/VDB；
- partial、blocked 或 experimental 子场景不属于完整 suite coverage。

## 12. ACT4 关键代码保护

本流程禁止为了让单个 suite 通过而修改通用框架。受保护范围包括：

- `framework/**`；
- testgen 通用源码和脚本，本 suite 的 `priv/extensions/{DUT}.py` 除外；
- `generators/coverage/**`、`generators/ctp/**`；
- `tests/env/**`；
- `Makefile`、`run_tests.py`、`pyproject.toml`、`uv.lock`、`.mise.toml`；
- `config/**`；
- 既有链接脚本、`rvmodel_macros.h`、`sail.json`；
- 通用 trap/setup/signature、registry、template 和 target configuration。

禁止的动作不仅是修改内容，还包括新增受保护对象、删除、移动、重命名、改变文件
类型和 chmod。即使随后恢复字节，也必须记录 policy violation，本轮不能宣称可贡献。

这不意味着不能使用开关。允许的控制项必须走当前 ACT4 已有入口：

| class | 正确入口 |
| --- | --- |
| runtime selection | 命令行传入 `CONFIG_FILES`、`EXTENSIONS`、`WORKDIR` 等 |
| suite opt-in | 本 suite generator 的注册参数或 extra defines |
| suite 规则 JSON | 当前 registry API |
| build owned | 由 ACT4 build 自己控制 |
| DUT capability | UDB/派生配置或 DUT config 声明 |
| DUT adapter | 独立配置并通过当前 test_config 接口选择 |
| reference model | validation config 中的真实模型配置 |

尤其不能由 suite 伪造 `*_SUPPORTED`。这类宏表达 DUT 能力事实，不是“让编译通过”的
开关。

## 13. Switch capability audit 怎么读

`audited_sources` 的每一项必须带类型：

```yaml
audited_sources:
  - kind: file
    value: riscv-arch-test/README.md
  - kind: command
    value: command -v sail_riscv_sim
  - kind: tool_result
    value: <实际版本输出>
```

文件证据必须是精确路径，不能使用 glob。每个 control 记录 owner、有效状态、原生入口、
允许动作、是否需要改基线、决定、证据和影响 profile。

`allowed` 必须同时满足：原生入口存在、不改受保护代码、目标能力成立、预处理顺序有效。
仅看到一个宏名或在网上见过类似用法都不够。

## 14. File manifest 怎么读

当前只接受 `schema_version: 2`。manifest 包含四个核心部分：

1. `baseline`：首次写入前的 Git/哈希基线；
2. `contribution_set`：真正准备提交的 ACT4 源文件；
3. `files` 和 `change_events`：交付物、证据与变化原因；
4. `framework_integrity`：受保护对象比较结论。

manifest 自身无法保存自己的最终哈希，否则每写入一次哈希又会改变文件。因此它的
`sha256_after` 必须为 null，并用 `hash_note` 说明 self-referential manifest。

`.venv/**`、普通 work 中间产物、缓存和无证据价值的 log/stamp 不登记。作为通过证据
的 `.S/.elf/.sig/.results/.sig.log` 必须逐文件登记。

## 15. 验收职责与结论边界

共同输入、原生资产、参数/CTP 接入、独立贡献验证及最终结果块见
`Guide_Doc/ACT4_Generation_Guide.md`。各 gate 的具体操作见
`Guide_Doc/ACT4_Checker_Guide/README.md`。

特权流程继续保留 coverage 语义、switch 能力、VM scope、参考模型尝试、签名完整性和
file manifest 约束。原生贡献验证额外确认只应用交付文件后能否重生成、运行 hooks、消费
参数/CTP、编译和执行选定配置。报告分别说明资产是否齐备、哪些验证真正运行、哪些提交
前提仍需人工完成。静态计数不能解释为动态命中，模型通过不能解释为 DUT 认证通过。

## 16. 常见失败与处理方式

| 现象 | 常见原因 | 正确处理 |
| --- | --- | --- |
| 规则索引不完整 | 标签未发布或独立规范尚未收录 | 绑定固定原文并追踪待补标签，不伪造正式 ID；继续生成 |
| 原生请求丢失 | 修改计划时删除了原覆盖目标 | 恢复来源请求，保留测试范围 |
| 人类 testplan 漂移 | 只改了机器 CSV | 同步 Markdown 的表、rule 和详细小节 |
| rule 不存在 | 从 prose 猜了 ID | 从所选 规则 JSON 的 name 取值 |
| mapping 找不到 symbol | 名称、covergroup 或 cross 不真实 | 对照实际 coverage 文件修复，不启用旧别名 |
| 编译成功但无 sig.log | 只做了 compile 或中间文件被清理 | 用真实参考模型完整构建，保留中间证据 |
| Spike 通过但 coverage 失败 | 把功能运行和 coverage 混为一谈 | self-checking 记 passed，coverage 记 not_run/limitation |
| 需要改 tests/env 才能运行 | 当前通用框架缺能力 | 拆分可行子场景，受影响 profile 记 framework blocker |
| 整个 coverpoint 被 blocked | blocker 传播粒度太粗 | 按操作/上下文拆 allowed、partial、blocked profile |
| framework integrity 失败 | 修改或 chmod 了受保护对象 | 本轮如实记录 violation；不要恢复后掩盖 |

## 17. 推荐阅读和执行顺序

第一次参与时，按以下顺序阅读：

1. 本指南，建立概念和证据层次。
2. 当前 `privileged-suite-generation.yaml`，查看精确 schema 和 checker 参数。
3. 冻结 HEAD 的 ACT4 `README.md` 与 `docs/DeveloperGuide.md`。
4. 相似 privileged suite 的 coverage、mapping 和 generator。
5. 当前 target 的 test config、UDB、DUT adapter 和 env 预处理顺序。
6. 选中的 RISC-V specification 与 norm-rules.json。

典型入口是：

```bash
act4-run /absolute/path/run.yaml
```

执行时按第 4.2 节在当前 stage journal 制定计划、逐项记录和恢复进度；使用 Check 获取
判定和反馈（部分 checker 会写报告），把修复关联到工作项。更新 journal 的结果与交接后，
使用 Complete 再次验证并推进。不要绕过失败阶段直接填“通过”，也不要把工具超时
写成测试成功。

## 18. 最终交付检查表

- CTP 和 manual provenance 能追溯到本轮快照、Git HEAD 和 SHA-256。
- source item 都是语义 ID，没有位置编码。
- 机器 CSV 与人类 Markdown 的 coverpoint/rule 集合完全一致。
- 功能、接口、前置状态、预期结果、时序恢复和测试注意事项分别描述。
- rule ID 全部来自 规则 JSON，mapping 目标全部真实存在。
- VM/resource profile 按具体子场景决定，没有粗粒度 blocker。
- 实验资产保持隔离，没有进入正式 generator 或 contribution set。
- generator 使用冻结 HEAD 的当前 TestChunk/registry API。
- `.S` 全部由 generator 重新生成，没有手工编辑。
- 最终 ELF、signature、results 和每个测试的 sig.log 完整配对。
- validation state 使用 `generation_scope` 和 `reference_model_evaluation`；VM contract 使用 `selected_target`。
- Spike/Sail/self-checking/RVVI/UCDB/VDB 的结论没有混写。
- manifest v2 完整，contribution set 只含贡献源码。
- ACT4 受保护对象与基线一致，policy violations 为空。
- 最终报告列出所有 limitation 和 non-claim，没有声称人工审批或未执行的验证。
