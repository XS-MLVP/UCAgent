
# ACT4 已有 Extension 审查与自动修复

目标是审查已有测试资产，而不是为新 suite 生成一套替代资产。输入为工作区内独立的
`riscv-arch-test/` Git clone 和只读 ISA 规范；支持 privileged/unprivileged 资产，具体能力以
所选提交为准。输出全部位于 `{OUT}/{DUT}/review/`，原始 checkout 始终不修改。
不要求在线 CTP 必须有 Google Sheet；现有计划、CTP、规范和当前版本的源码共同确定边界。
Skill 不参与必需流程。

## 1. 范围与证据

按 `review_audit → review_repair` 自动推进。审查阶段包含范围盘点与基线验证，修复阶段
包含复验与最终报告。开始立即调用 Check，即使还没有 scope.yaml，也会生成 `environment.json`，
记录 Questa、VCS、Xcelium 的路径发现和实际 covergroup 编译/仿真结果。缺少程序为 not_found，
编译、运行、许可或超时问题为 unusable，最小测试完成为 available。可用不代表原生 ACT4 coverage 已通过。
这些可选工具缺失不阻止继续审查，不要求下载安装商业软件；需要实测覆盖率时才考虑补齐工具和许可。
然后建立 `scope.yaml`，再 Check 冻结原始 HEAD、文件内容、模式及子模块。
已有未提交变更属于本轮基线，不得擅自丢弃；忽略目录中的必要输入也须列入 assets。
所有子模块必须预先初始化。不要复制符号链接到工作区外、绝对符号链接或共享工作树。
开始前核对实际 HEAD、提交日期及本地变更，区分上游已有资产与另外保留的本地输入。
更新输入版本后创建新的审查输出，重新发现资产、读取 CI 和验证工具要求；旧结论不适用于新提交。

逐项发现 test plan、CTP、norm mapping、coverage 定义/初始化、generator、测试源码、
目标配置及其依赖。`assets` 的五类路径必须齐全，不存在的类写 `[]` 并检查其是否是遗漏。
`discovery` 记录搜索路径/命令及选取或排除理由，不能只挑选容易通过的文件。
`references` 记录规范版本、章节、CTP 和计划来源；`targets` 覆盖所有适用 XLEN、特权级、
扩展依赖和目标配置。
`shared_assets` 必填，无共享资产写 `[]`。每项包含 `path`、`consumers` 字符串列表和 `boundary`：
该路径须在 assets 中，列出使用它的 suite，说明本轮覆盖及排除的配置。共享 mapping/generator 的
外部引用不可直接当成本 suite 缺陷；修改前检查相关消费者并安排验证，不因文件共享而自动等待人工批准。
`reference_files` 必须列出实际读取的规范、CTP、元数据原文在工作区内的确切相对文件路径，
不得指向审查输出或符号链接。Check 将这些文件冻结到 `references/<原相对路径>`，
同时核对原件及副本；原文缺失写 `[]`，不能据此判定规范义务完整或覆盖点语义正确。
外部网址和章节说明写在 `references`，不能代替可核验的规范原文。

每个 target 都必须有 `environment/generation/build/reference_model/coverage/lint` 六种 purpose 的 job。
读当前 `.github/workflows`、README 和 DeveloperGuide 确定原生命令；job.source 是 ACT4
内的确切 CI/文档路径。不存在或无法运行的 lane 也要列出，标记 `not_applicable` 或
`unavailable`，给出原因、影响和补齐前提。环境 job 必须标为 `run`，先实际探测。
禁止用空操作冒充验证。
命令使用 argv 列表、相对于隔离 checkout 的 cwd 和 1..3600 秒超时，cwd 不得越出副本。
`environment` job 用 `probe: [程序, 参数, ...]` 检查版本、依赖及实际可运行性；可用
`expected_output` 正则校验版本输出。按当前源码的比较逻辑区分最低版本与精确版本，不能只看注释。
探测失败则执行 `install: [程序, 参数, ...]`，安装退出成功后必须重新探测，复验失败仍不可用。
复用当前 CI 的下载和安装步骤；公开工具缺失时应提供 install，使用已缓存的匹配发行版也可以。
Python 环境探测还应检查 act/testgen/coverage 模块的实际导入路径属于本轮命令副本，
避免外部 editable 安装或继承的 PYTHONPATH 指向另一份 ACT4；必要时在 argv 中用 env 设置
当前提交的相对 Python 源码路径。不要硬编码上一轮临时 checkout 的绝对路径。
`{TOOLS}` 在 probe/install 参数中替换为本轮 `review/tools` 的绝对路径，所有命令的 PATH
首先搜索其中的 `bin`。安装不得写入原始输入或修改其版本校验；安装目录不属于资产修复范围。
商业仿真器的 coverage job 使用 `optional_tool: questa`、`vcs` 或 `xcelium`，保持
`disposition: run` 和完整的原生命令、输入、产物；不要手写 unavailable 代替探测。也允许为
额外 simulator environment job 标记 optional_tool，但不得带 install。可选工具不可用时
仅对应 jobs 记录 unavailable，独立任务继续。generation/build/reference_model/lint 及其环境
不能依赖这些可选 jobs。不能把 Questa 不可用等同于 VCS 不可用；选择与当前原生命令匹配的工具。
工具状态取自 environment.json，不能手改；安装或配置变化后，在 review_audit 使用
`Check(stage_args={"refresh_tools": true})` 重新探测，然后重新收集前后证据。
普通 Check 复用已保存的探测，不重复占用许可。许可证在探测后失效时，实际 job 仍可能失败，保留真实结果。

`needs: [job-id, ...]` 声明依赖，按依赖顺序执行而非列表顺序；未知依赖和循环依赖会失败。
每个可运行 job 都依赖本 target 的环境；build 还必须依赖 generation。
没有 ELF 时先原生生成测试，再构建签名 ELF、运行 Sail 生成签名、重编译为自检 ELF，然后实际执行。
不能用旧 ELF、空目录或仅一次编译替代该流程。任一前置 job 失败/不可用时，依赖 job 记录
`blocked`，不会空跑；修复环境后显式重新收集证据。

`artifacts: [{path: ..., kind: ...}]` 中 kind 为 `coverage/elf/signature/results/generated/other`。
path 为命令副本内精确相对路径，也可指定目录与 `pattern: "**/*.elf"`，禁止越界匹配。
`min_count` 默认为 1，可按测试计划提高；产物必须非空，ELF 必须有 ELF 文件头。
build 必须声明 ELF 产物。执行 job 的 `elf_inputs: [build-id, ...]` 必须指向同 target 的依赖构建，
只使用本轮构建的 ELF，并验证构建后字节未变。coverage 必须保留真实 coverage 产物。
reference_model 必须声明 results 产物及 `pass_pattern`/`fail_pattern` 正则，从当前运行器的
结果格式确定模式。匹配到失败/signature-only 结果、零次通过或通过数不等于输入 ELF 数均失败。
ACT4 `run_tests.py` 的 summary.log 每个 ELF 一行，可以匹配 `RVCP-SUMMARY: TEST PASSED`
并拒绝 `RVCP-SUMMARY: TEST (FAILED|SIGRUN)`。不要用控制台“进程退出成功”代替测试结果。
成功退出但缺少声明产物仍判失败；每个 job 运行前清除其声明的旧产物，保留各 job 的独立证据。
命令本身失败时先根据退出码和日志诊断；附带的产物缺失记录不能掩盖原始构建/执行失败。
`succeeded` 等构建摘要统计的是构建任务，不能转换成签名成功数、ELF 数或测试通过数。
报告的模型通过数仅来自实际 results，前置阻塞的 job 没有执行结果。

为失败诊断另设 `diagnostics: [{path: work/<target>/build, pattern: "**/*.sig.log"}]`，
也可按当前源码补充签名、模拟器日志等选择器。选择器仅含 path 和可选 pattern，安全路径规则
与 artifacts 相同。匹配文件会在临时目录删除前复制到 `diagnostics-before/` 或 `diagnostics-after/`，
成功、失败和超时均保留；没有匹配文件不改变原生命令结果，必需产物仍须写入 artifacts。
每个 job 最多保留 50 个文件，优先选择命令日志明确提及的路径；每个文件最多保留末尾 256 KiB。
证据记录原路径、原大小、截断标志、已保存内容的 SHA-256 及省略/截断数量。截断片段只用于
诊断，不是完整签名或 coverage 证据；文件被省略时缩小匹配范围后重跑，不能声称现场已完整保留。
命令前清除本 job 声明的旧产物及诊断文件，防止把旧日志作为本次结果。
命令副本的 Git 索引会纳入全部冻结源码，包含未提交和显式纳入的忽略文件，让基于 git ls-files 的
lint 检查覆盖这些输入；原始仓库的索引和工作区不变。仍应检查当前 CI 是否需要 make lint、
mise run prek 或显式文件列表等多种检查，不可用单一格式检查替代全部 CI。

在 audit 调用 `Check(stage_args={"run_commands": true})`。审查中发现的资产错误不会阻止
交付报告；报告契约、边界或证据错误会阻塞。审查证据包括可复用的资产格式/一致性结果、
generator 独立性、SV coverpoint/cross 定义、cross 输入 default bins 和 bit-walk bins 的
结构规则、assembly 静态可达性、字节重复候选及每个 job
的真实退出码/日志/产物。
字节相同仅是重复候选；需确认测试义务、约束和配置等价后才建议删除。
首次取证后使用普通 Check 校验报告和证据完整性。仅修改 `scope.references`、`scope.discovery`
或 review 文字可复用原生命令证据；源码、资产边界、targets 或 jobs 变化均要求重新取证。
冻结的 `reference_files` 名单或内容变化须开始新一轮审查，不沿用原判断。
修改说明后校验更新的报告即可继续修复。显式 `run_commands: true` 始终重跑
完整矩阵，不会因为已有缓存而跳过执行；不要为修正报告文字重复下载工具和构建。
`review.md`/`final.md` 先展示自然语言摘要、问题性质与处置数、每项修复/未修复原因和用户协助，
再展示验证限制；逐 job 状态、ELF/模型通过数、失败命令和诊断链接放在可展开的技术详情中。
完整逐点追踪、资产清单和原生结果分别保留在 review.yaml/final.yaml、scope.yaml 与 evidence JSON，
通过报告链接查看，避免把大块原始证据在报告内重复展开。

审查至少覆盖以下八类，`review.checks` 不得缺项：

- `act4_compliance`：原生目录、命名、宏/API、CTP/norm 接口、生成器拆分与贡献独立性。
- `omissions`：规范义务、异常/边界/非法组合、XLEN/特权级、配置矩阵和所有资产间追踪。
- `redundancy`：重复义务/用例/生成路径、过度交叉和无意义 bins；保留必要的配置差异。
- `coverpoint_quality`：采样事件、iff、bins/ignore/illegal、cross、不可达/恒真点和语义正确性。
- `test_coverage`：定义→规范→生成器→精确用例→构建→执行/实际命中的完整对应。
- `ci`：原生生成、构建、参考模型、coverage、格式/静态检查与 CI 版本/矩阵的一致性。
- `reproducibility`：HEAD、规范/工具版本、随机种子、命令、依赖、产物和环境限制。
- `contribution_quality`：无私有工作区依赖、可维护性、命名、生成文件来源、范围与许可证。

### 从规范和计划建立义务清单

`evidence.obligation_sources` 独立于现有 coverage 和 generator：它将全部已声明的 test_plans
和 reference_files 划成最多 80 行的来源区块，保留原路径和行号。这样某个义务即使两端都没有
实现，也仍有来源审查任务。区块是阅读边界，不是自动解析出的规范结论；结合相邻段落、表格、
配置和条件提取所有适用义务，不能将一整个复杂区块用一句泛泛描述或 unverified 草草带过。
非文本/空输入保留 0-0 区块，说明无法读取的限制并引用 evidence JSON 中相应信息，不能漏掉它。

review.yaml 和 final.yaml 均有 `obligations` 列表，每项包含：

- `id`：唯一 O<number>，修复后保留原 ID，允许新增，不可删去原缺口。
- `sources`：来自 obligation_sources 的确切 ID 列表；所有来源区块至少有一项义务或有理由的排除。
- `requirement`、`targets`、`reason`：具体行为/预期结果、适用目标列表、映射或排除理由。
- `coverpoints`：实际 group/name 列表；`implementation`：evidence.implementation_sources 中的
  generator/testcase 源码路径列表，不能拿规范、计划或报告本身代替实现。
- `status`：implemented/gap/unverified/not_applicable；implemented 必须有覆盖点和实现链接，
  仍不代表实测命中。gap 即使两个实现端都为空，也必须关联 finding。
- `findings`：相关 F<number> 列表，无问题为 []。

所有 `source:*` 任务引用自身区块内的原文；另外对每项 `obligation:<ID>` 评审来源与实现，
status 分别对应 passed/issues/unverified/not_applicable。基线与修复后路径分别使用
baseline/、candidate/；规范均为 references/。若 source/obligation 仍有未知或缺口，
omissions 总结不得标为 passed。没有规范和计划时 obligations 可空，但不代表完整性已获证明。
共享资产由 `shared:<path>` 任务专门审查消费者与影响边界。
implemented 的判断还须引用关联覆盖点的定义行；gap 的判断须关联该义务对应的 findings。

例如某份已冻结计划第一行明确要求“H 存在而 Sstc 不存在时，STCE 为只读零”，但 coverage
和 generator 都没有对应测试。该项必须写入义务清单，不能因为没有现成 coverpoint 就漏审。
下列为 obligations 的完整单项示例，实际 source ID 和 target 以本轮证据为准：

```yml
obligations:
  - id: O1
    sources: ["source:plan:testplans/priv/Sstc.yaml:1-80"]
    requirement: With H present and Sstc absent, STCE must read as zero and ignore writes.
    targets: [rv64-h-without-sstc]
    status: gap
    reason: The plan defines this configuration, but no corresponding coverage or generator case was found.
    coverpoints: []
    implementation: []
    findings: [F1]
```

F1 的 classification 可以是 confirmed_defect；调查若已确认目标配置尚未建立，diagnosis
取 cause_identified，在补齐可验证的修复方案前不列 changes。若没有找到确切测试实现，
但宏或共享 helper 仍未查清，则先用 suspected_defect/unverified，不抢先宣称确定缺失。
原文已经明确预期行为时，后续 blocker 应描述配置/实现工作，不能写“缺少权威预期”。

`traceability` 必须逐一列出所有扫描到的 `group/coverpoint`。coverage 只能为
`measured/static/gap/unverified`；每项提供规范 obligation、testcases 列表和 evidence。
`static` 的 testcases 必须是 `evidence.testcase_links` 中的精确 `原文件路径::标签`，
evidence 引用对应的保留源码路径；已证明不可达、条件未知或解析有疑点的标签不进入此集合。
源码用例与本轮生成的 `.S` 都会检查，不能凭空填写 testcase；无法建立静态对应时记 unverified。
静态字符串/标签/ELF 符号不能证明命中，条件可达也不能等同执行。`measured` 必须引用真实
成功的 coverage purpose 命令保留的 coverage 产物路径，并确认目标、bin、采样和运行条件确实匹配。
无法解析的宏生成点、动态 generator、外部计划或语义差异明确记为 unverified，人工补查，
不得宣称静态 checker 已证明所有规范义务或实际命中。

### 静态事实与 AI 语义审查

先读取 `evidence-before.json`，再由你对机器不能判定的内容逐项给出判断。两类证据的职责如下：

| 内容 | 可机械核验的事实 | 你必须审查的语义 |
| --- | --- | --- |
| 资产契约 | 格式解析、映射/符号引用、注册扫描、独立性 | 与当前 ACT4 API/贡献约定是否一致，诊断是否受扫描范围或语法限制影响 |
| 完整性 | 声明资产、点集合、规范原文快照 | 从规范义务反查计划、激励、异常、边界、XLEN/特权配置，找出未建模的义务 |
| 冗余 | 字节相同候选 | 对比前置状态、义务、配置和预期结果，判断重复是否必要；不同字节也可能语义重复 |
| 覆盖点 | 表达式、条件、bins、cross 成员 | 采样时机、iff、值域、illegal/ignore bins、cross 维度是否合理 |
| 用例对应 | descriptor/label、条件可达性、真实构建/运行/产物 | 激励和断言是否实现义务，是否真正触发对应 bin，哪些结论只来自静态链接 |
| CI | 依赖矩阵、退出码、非空 ELF、执行计数和日志 | 当前上游矩阵是否列全，排除项是否适用，结果与声明是否一致 |

`review_tasks` 是本轮必需审查清单，包含 `topic:<八类主题>`、`point:<group/name>`、
`diagnostic:<编号>:<编号>`、`reachability:<保留路径>`、`duplicate:<编号>`、`source:*`、`shared:*`。
在此基础上，两轮判断均须增加全部 `obligation:<ID>` 和 `finding:<ID>`，最终轮还须覆盖 change 任务。
只使用本轮实际出现的 ID，不自行猜测或沿用上一轮的编号。每项必须在 `semantic_review.judgments`
中出现且只出现一次；义务和依据相同的任务可以合并。逐点判断必须引用其定义行，
不能用一段通用结论覆盖所有覆盖点。带 path 的任务必须引用该源码，重复候选须引用全部候选。
静态诊断逐一说明是资产缺陷、扫描限制、范围偏差还是
证据不足；原始错误/告警始终保留，AI 的解释不能将失败的机器结果改成通过。

`semantic_review` 必填 `reviewer: ai`、当前证据的 `review_digest` 作为 `evidence_digest`，
以及非空 `judgments`。每个判断包含：

- `tasks`：本轮确切 task ID 字符串列表。
- `status`：passed/issues/unverified/not_applicable；`confidence`：confirmed/inferred/unverified。
  passed 只能搭配 confirmed；issues 必须关联已有 finding。confidence 表示本轮依据的充分程度。
- `reasoning`、`conclusion`：从引用的事实与规范/要求比较后得出的推理和结论，不能只重复状态。
  对已有证据做实质分析；缺少原文或执行条件时明确划出不能判断的部分，不能批量填未知了事。
- `limitation`：unverified、not_applicable 或非 confirmed 时必填，说明具体边界。
  `next_action`：issues/unverified 时必填，说明补什么证据或做什么修复。
- `findings`：关联的 F<number> 列表，无问题可为 `[]`。
- `diagnostics`：该判断覆盖的 diagnostic task ID 到 asset_defect/scanner_limitation/scope_mismatch/unresolved
  的映射；无 diagnostic task 时省略或写 {}。asset_defect 必须是 issues 并关联 finding，unresolved 不能 passed。
- `basis`：非空引用列表，每项提供 `path`、`lines: [起行, 终行]`、`quote`、`observation`。
  path 相对于 review 目录，只能引用冻结源码/规范、本轮 evidence JSON 或保留日志/产物；不能用自己写的报告作证明。
  源文件为空或二进制无法逐行引用时，引用 evidence JSON 中对应文件身份/诊断并说明限制。
  行号从 1 开始，最多 100 个物理行，quote 必须与选定行逐字一致，使用 `|-` 避免多余末尾换行。
  observation 说明原文证明了什么，不能把引用中没有的内容当作事实。

规范完整性或覆盖点质量的总审查标为 passed 时，必须引用冻结的 `references/` 原文。
推断不能写成确认通过；AI 不能证明未运行的 CI 成功，也不能把源码标签升级为实测命中。
报告顶层 checks 不能在相关 AI 判断仍为 issues/unverified 时写 passed。
证据重收集后使用新 digest 重新审查，普通 Check 校验现有判断，不额外调用模型。

## 2. 自动修复与最终报告

所有 `evidence` 字段使用非空字符串列表；结论、位置、义务、风险和原因使用非空文本，
不能用布尔值或数值充当说明。`testcases`、change 的 `findings` 和 `validation_jobs`
使用字符串列表。

完整审查写 `review.yaml`，Check 生成 `review.md` 和 `evidence-before.json`。
每个 finding 使用唯一 `F<number>`，分别记录：

- `classification`：confirmed_defect/suspected_defect/validation_gap/not_a_defect。缺少仿真器是验证限制，不能算确认的测试资产错误。
- `diagnosis`：symptoms_only/cause_identified/repair_ready。确认现象、确认根因、能安全修复是不同进度。
- `investigation`：非空列表，每次包含实际 `action`、`result` 和与语义判断同格式的精确 `basis` 引用。
  先搜索并阅读现有规范、计划、共享代码和目标配置；有运行失败时分析真实失败用例、指令/PC、
  CSR 状态、预期异常与模型能力。不同失败不得未经分析合并成一个根因。

confirmed_defect 在尚未 fixed 时，其 finding 判断仍应为 issues/confirmed 并关联自身 ID，
不能因暂缓修复而把已确认的问题降成“未知”。not_a_defect 需要 confirmed 的排除判断。

每个 change 必须关联 confirmed_defect 且 repair_ready 的 findings，声明确切文件路径、
动作、风险和复验 job IDs。只修改这些声明路径；没有发现允许 `findings: []`、`changes: []`。
有发现但缺少规范、预期行为、配置或复现证据等必要信息时，在 recommendation 中说明
缺失信息、待确认根因、补齐动作和风险，不猜测修复。只把有充分依据的修复列入 changes，
其余 finding 保留到最终报告；所有问题都无法安全修复时 changes 可为空。
`post_assets` 必须列出修复后的五类完整资产集合，无变化时逐类复制 `scope.assets`。
新增或删除的集合成员必须在 changes 声明的路径内；不能从集合中隐藏仍然存在的原始资产。
新增 coverage 定义也必须列入，最终 traceability 才能按真实修复后的定义复验。

审查 Complete 后直接进入 `review_repair`。先 Check 准备 `candidate/`，此时缺少
修复后证据或 final.yaml 的提示表示下一步尚待完成；在 candidate 中实施已声明的修复，再运行
`Check(stage_args={"run_commands": true})`；命令生成物保留到 evidence 所指位置，不能把
日志/缓存误当贡献源码。generated `.S` 应由 generator 重生成，不手工弱化断言。
发现额外问题时，先更新 review.yaml 的 findings、changes、post_assets 和相应判断，Check
校验后继续修复。必要信息不足时保持相关资产不变，记录原因并继续其它工作。
暂缓某项原定修复时保留其 finding，将 changes 和 post_assets 更新为实际实施的计划与资产集合。
重启后读取现有报告与证据继续；基线或证据完整性失败时按 Check 提示恢复或重新取证。

`final.yaml` 的 summary 用易懂的自然语言回答检查了什么、发现什么、修复什么、剩余问题及原因。
不得以静态告警数代替缺陷数，也不能以空补丁暗示审查没有价值。
每一个 finding 保留 classification、diagnosis、investigation，并交代 fixed/deferred/not_fixed/dismissed、evidence 及 reason。
deferred/not_fixed 的 reason 说明缺失信息或未修复原因及影响，next_action 说明需要补齐的
资料、配置或验证动作；不得为了完成流程强行修改。fixed 必须有声明路径的实际变化且
关联复验 jobs 全通过。工具缺失/CI 失败仍可交付部分修复报告，必须
保留 remaining_risks，`ci_passed: false`，不得伪报全部完成。最终 traceability 针对修复后的
全部 coverpoints，并列出 coverage_changes（即使无变化也写 `[]`）。
`coverage_changes` 每项包含 `coverpoint: group/name` 和 `reason`；新增、删除的每个点必须
有一项说明，已有点的 bins/约束/义务变化也在这里解释，不能通过删除 coverpoint 隐藏缺口。

deferred/not_fixed 另需 `blocker`：kind 为 specification/configuration/reproduction/tooling/implementation；
detail 写确切缺项或未完成的工作，impact 写影响，why_not_resolved 解释现有资料和已尝试动作为何
尚不能解决，owner 为 agent/user/upstream。行为已由规范明确但测试没写，应归 implementation，
不能谎称缺规范。共同源码的影响分析、失败诊断等普通工作归 agent；只有确实需要外部输入时
才归 user，同时写 request（具体可提供的资料/配置/工具能力）和 reason_user_needed。
例如缺少许可证只限制 measured coverage，不足以解释为何不修一个已有规范依据的 mapping 错误。
dismissed 用于经过调查排除的疑点，必须 classification 为 not_a_defect 且语义复核 confirmed，
它不计为修复，也不需要制造源码改动。CI 总状态仍反映全部声明 lane，可选 lane 缺失时 ci_passed
仍为 false；报告另列必要验证是否通过，流程可以完整交付。
最终 `semantic_review` 必须重新评估 `evidence-after.json.review_tasks`，使用 after 的
`review_digest`，并额外覆盖每个 `finding:<ID>` 及 `change:<确切变更路径>`。
修改项引用 candidate 中的源码，删除项引用 baseline；可同时引用基线进行前后比较。
fixed finding 的 AI 复核必须为 passed/confirmed，仍为 issues/unverified 的结论不能称为已修复。
所有未解决的语义疑点及推断也须写入 remaining_risks，即使命令均通过也不能省略。
Check 生成 `final.md` 和 `changes.patch`，包含原始审查、前后验证、逐项处置、精确变更、
未修复原因、后续动作及风险。修复阶段 Complete 要求这些报告通过校验；已完整披露的
未修复项允许交付，无可安全修复项时输出空补丁。补丁支持 UTF-8 文本源码及模式变更，
不支持二进制或符号链接变更。
由人类应用到原始 checkout，应用前 `git apply --check` 并确认 HEAD/dirty baseline，应用后
再跑原生 CI；不能把隔离副本验证当成远端 GitHub CI 已通过。

## 3. 完整规范示例

以下是一轮完整、诚实的“环境暂缺，暂不修复”审查。假设 `generators/H.py` 已存在，
所选提交 `README.md` 说明工具准备。示例展示整个必填格式，不是可照抄的测试结论；
实际任务必须替换全部路径、target、义务、证据、命令和结论。
以下不完整 generator 的原文用于演示精确引用；真实审查不能用它代替已有的生成器：

```python
"""Native H generator fixture."""
VALUE = 1
```

示例假定本轮仅产生八类主题任务及 mapping 缺失、generator 未注册两个诊断任务。
实际必须以 evidence.review_tasks 为准；将示例 evidence_digest 替换为相应证据的 review_digest。

`scope.yaml`：

```yaml
schema_version: 1
suite: H
assets:
  test_plans: []
  coverage: []
  generators: [generators/H.py]
  test_cases: []
  mappings: []
targets: [rv64-example]
references: ["ISA manual commit and H chapter recorded in stage journal"]
reference_files: []
shared_assets: []
discovery: ["Searched plans, coverpoints, generators and tests; only generators/H.py exists"]
jobs:
  - id: env
    target: rv64-example
    source: README.md
    purpose: environment
    disposition: run
    probe: [act4-example-missing-python-runtime, --version]
    timeout_seconds: 30
    reason: "Public native Python runtime is not yet prepared; inspect this commit's setup instructions and install into review/tools"
  - {id: gen, target: rv64-example, source: README.md, purpose: generation, disposition: unavailable, reason: "Native generator dependencies not installed; generation remains unverified"}
  - {id: build, target: rv64-example, source: README.md, purpose: build, disposition: unavailable, reason: "Cross compiler absent; ELF validation remains unverified"}
  - {id: model, target: rv64-example, source: README.md, purpose: reference_model, disposition: unavailable, reason: "Reference model absent; runtime remains unverified"}
  - {id: cov, target: rv64-example, source: README.md, purpose: coverage, disposition: unavailable, reason: "Coverage runner absent; no measured hits"}
  - {id: lint, target: rv64-example, source: README.md, purpose: lint, disposition: unavailable, reason: "Native lint dependencies absent; lint remains unverified"}
```

`review.yaml`：

```yaml
schema_version: 1
suite: H
summary: Existing assets are incomplete and native validation is unavailable; no repair proposed yet.
checks:
  act4_compliance: {status: issues, evidence: [evidence-before.json], conclusion: "Review deterministic findings; native conformance not established"}
  omissions: {status: issues, evidence: [scope.yaml], conclusion: "No declared coverage, plan or generated cases"}
  redundancy: {status: unverified, evidence: [generators/H.py], conclusion: "No testcase matrix available to establish semantic duplication"}
  coverpoint_quality: {status: unverified, evidence: [scope.yaml], conclusion: "Coverage definition missing"}
  test_coverage: {status: unverified, evidence: [evidence-before.json], conclusion: "No measured coverage"}
  ci: {status: unverified, evidence: [evidence-before.json], conclusion: "All native validation lanes unavailable"}
  reproducibility: {status: issues, evidence: [baseline.json, scope.yaml], conclusion: "Sources frozen but toolchain not prepared"}
  contribution_quality: {status: unverified, evidence: [generators/H.py], conclusion: "Need upstream API and dependency review"}
findings:
  - id: F1
    topic: omissions
    severity: high
    location: scope.yaml
    evidence: [scope.yaml, evidence-before.json]
    problem: No coverage or generated tests are available for the selected target.
    recommendation: "Locate authoritative assets and prepare native validation before proposing edits. Root-cause ownership is unconfirmed; speculative repairs risk changing intended test semantics."
    classification: suspected_defect
    diagnosis: symptoms_only
    investigation:
      - action: Read the declared generator and compare with the missing asset categories.
        result: This file contains no generator implementation; intended ISA obligations remain unknown.
        basis:
          - path: baseline/generators/H.py
            lines: [1, 2]
            quote: |-
              """Native H generator fixture."""
              VALUE = 1
            observation: The entire fixture only defines a constant.
changes: []
obligations: []
post_assets:
  test_plans: []
  coverage: []
  generators: [generators/H.py]
  test_cases: []
  mappings: []
traceability: []
semantic_review:
  reviewer: ai
  evidence_digest: REPLACE_WITH_BEFORE_REVIEW_DIGEST
  judgments:
    - tasks: ["topic:act4_compliance", "topic:omissions", "diagnostic:0:0", "diagnostic:0:1", "finding:F1"]
      diagnostics: {"diagnostic:0:0": unresolved, "diagnostic:0:1": unresolved}
      status: issues
      confidence: inferred
      reasoning: "The declared generator only defines a constant, while the static report finds no native mapping or H registration. Together with the empty declared plans/coverage/tests this indicates incomplete assets in the selected scope. It does not establish which ISA obligations are missing."
      conclusion: The selected assets do not yet provide a reviewable H test suite.
      limitation: Authoritative specification and complete asset discovery are still required.
      next_action: Locate the native mapping, registration and authoritative test assets before proposing repairs.
      findings: [F1]
      basis:
        - path: baseline/generators/H.py
          lines: [1, 2]
          quote: |-
            """Native H generator fixture."""
            VALUE = 1
          observation: The entire declared generator contains no stimulus or registration.
    - tasks: ["topic:ci", "topic:contribution_quality", "topic:coverpoint_quality", "topic:redundancy", "topic:reproducibility", "topic:test_coverage"]
      status: unverified
      confidence: unverified
      reasoning: "A constant-only generator provides no sampling, bins, testcase obligations, expected outcomes or native integration to compare. Missing tool execution and specification sources prevent assessing the remaining requirements. Similarity alone cannot justify deleting tests."
      conclusion: No semantic correctness, necessary duplication or measured coverage claim can be established.
      limitation: No declared coverpoints/testcases, pinned specification text or runnable native validation.
      next_action: Obtain the actual suite and pinned specification, prepare tools, then inspect stimulus and retained coverage results.
      findings: []
      basis:
        - path: baseline/generators/H.py
          lines: [1, 2]
          quote: |-
            """Native H generator fixture."""
            VALUE = 1
          observation: There are no coverage definitions or testcase generation operations in this source.
```

有证据支持的修复提案填入 `changes`，例如（不是第二套格式）：

```yaml
changes:
  - findings: [F1]
    paths: [generators/H.py]
    action: Add the missing boundary subcases through the native generator API.
    risk: Generated testcase count and expected signatures will change.
    validation_jobs: [gen, build, model, cov, lint]
```

调查后仍缺必要信息，`final.yaml` 完整内容：

```yaml
schema_version: 1
suite: H
summary: Review delivered without source changes; validation and coverage remain unverified.
findings:
  - id: F1
    status: deferred
    evidence: [review.yaml, evidence-after.json]
    reason: The pinned specification and complete native assets are missing; expected behavior cannot be established safely.
    next_action: Obtain the specification and authoritative suite inputs, prepare the native environment, and repeat validation.
    classification: suspected_defect
    diagnosis: symptoms_only
    investigation:
      - action: Reinspect the unchanged candidate after native validation.
        result: No implementation or authoritative specification was recovered.
        basis:
          - path: candidate/generators/H.py
            lines: [1, 2]
            quote: |-
              """Native H generator fixture."""
              VALUE = 1
            observation: The candidate still only defines a constant.
    blocker:
      kind: specification
      detail: No pinned H specification or authoritative suite has been provided in this fixture.
      impact: Cannot establish the intended behavior or propose a safe semantic repair.
      why_not_resolved: Inspecting the declared generator and selected assets did not recover the missing requirements.
      owner: agent
obligations: []
ci_passed: false
remaining_risks: ["Native CI unavailable; no claim of ACT4 compliance or measured coverage"]
coverage_changes: []
traceability: []
semantic_review:
  reviewer: ai
  evidence_digest: REPLACE_WITH_AFTER_REVIEW_DIGEST
  judgments:
    - tasks: ["topic:act4_compliance", "topic:omissions", "diagnostic:0:0", "diagnostic:0:1"]
      diagnostics: {"diagnostic:0:0": unresolved, "diagnostic:0:1": unresolved}
      status: issues
      confidence: inferred
      reasoning: "The specification and complete native assets are missing. The candidate remains a constant-only generator and after-evidence still reports missing mapping and registration, so the original asset gap remains."
      conclusion: The original conformance and asset completeness issues remain open.
      limitation: The specification and complete native assets have not been recovered.
      next_action: Obtain the authoritative suite inputs and derive a concrete repair plan.
      findings: [F1]
      basis:
        - path: candidate/generators/H.py
          lines: [1, 2]
          quote: |-
            """Native H generator fixture."""
            VALUE = 1
          observation: The candidate still contains no native test generator implementation.
    - tasks: ["topic:ci", "topic:contribution_quality", "topic:coverpoint_quality", "topic:redundancy", "topic:reproducibility", "topic:test_coverage", "finding:F1"]
      status: unverified
      confidence: unverified
      reasoning: "There is still no stimulus, expected outcome or coverage definition to compare with ISA requirements. The deferred F1 cannot be called fixed; after-validation provides no missing semantic or execution evidence."
      conclusion: Deliver an unchanged candidate with explicit unresolved risks.
      limitation: No pinned specification, full suite or real coverage run.
      next_action: Recover the required inputs and tools, then repeat review and validation.
      findings: [F1]
      basis:
        - path: candidate/generators/H.py
          lines: [1, 2]
          quote: |-
            """Native H generator fixture."""
            VALUE = 1
          observation: The reviewed candidate provides no testcase semantics or bin-hit evidence.
```

这轮没有足够依据修改源码，直接输出空的 `changes.patch` 和完整 `final.md`，注明缺失信息，
不能将 deferred 或 unavailable 偷换成 fixed/passed。

## 4. 环境准备与构建执行示例

以下完整 scope 示例以提交 `0a29a3afdaba96b04f77e6e2559030475720a9b2` 的 H、
sail-rv64-max 为例：其 CI 使用 Sail 0.16、GNU 工具链发行版 2026.08.27。
其它提交必须重新读取实际版本约束和命令，不要将此示例当成版本自动发现结果。
审查资产仅示范 generator；实际任务应列全已有资产。原生 Python 安装复用 mise/uv，
开始前按 README 安装 mise；同样将其探测、安装动作写入环境 jobs，不省略其它工具。
示例故意把 coverage 放在 build 前，依赖关系仍保证先生成和构建。Questa 的
最小编译/仿真由开始时的 Check 完成，coverage 的 optional_tool 声明与原生命令匹配。
安装失败也会继续收集不依赖它的检查，之后在完整 review.yaml/final.yaml 中如实报告。

```yaml
schema_version: 1
suite: H
assets:
  test_plans: []
  coverage: []
  generators: [generators/testgen/src/testgen/priv/extensions/H.py]
  test_cases: []
  mappings: []
targets: [sail-rv64-max]
references: ["Pinned ISA manual H chapter; record actual commit in the review"]
reference_files: []
shared_assets: []
discovery: ["Illustrative generator-only boundary; expand to all existing H assets in a real review"]
jobs:
  - id: runtime
    target: sail-rv64-max
    source: .mise.toml
    purpose: environment
    disposition: run
    probe: [mise, exec, --, uv, run, python, -c, "import act, testgen, covergroupgen; from pathlib import Path; assert all(Path(module.__file__).resolve().is_relative_to(Path.cwd()) for module in (act, testgen, covergroupgen))"]
    install: [mise, install]
    timeout_seconds: 3600
  - id: sail
    target: sail-rv64-max
    source: .github/actions/setup-tools/action.yml
    purpose: environment
    disposition: run
    probe: [sail_riscv_sim, --version]
    expected_output: '\A0\.16\s*\Z'
    install: [bash, -c, 'set -euo pipefail; curl -fL "https://github.com/riscv/sail-riscv/releases/download/0.16/sail-riscv-$(uname)-$(arch).tar.gz" -o "{TOOLS}/sail.tar.gz"; tar xzf "{TOOLS}/sail.tar.gz" -C "{TOOLS}" --strip-components=1']
    timeout_seconds: 1800
  - id: compiler
    target: sail-rv64-max
    source: .github/actions/setup-tools/action.yml
    purpose: environment
    disposition: run
    probe: [riscv64-unknown-elf-gcc, -dumpfullversion]
    expected_output: '\A(1[5-9]|[2-9][0-9])\.[0-9]+.*'
    install: [bash, -c, 'set -euo pipefail; curl -fL "https://github.com/riscv-collab/riscv-gnu-toolchain/releases/download/2026.08.27/riscv64-elf-ubuntu-24.04-gcc.tar.xz" -o "{TOOLS}/gcc.tar.xz"; tar xJf "{TOOLS}/gcc.tar.xz" -C "{TOOLS}" --strip-components=1']
    timeout_seconds: 3600
  - id: coverage
    target: sail-rv64-max
    source: Makefile
    purpose: coverage
    optional_tool: questa
    disposition: run
    needs: [build]
    elf_inputs: [build]
    argv: [make, coverage, EXTENSIONS=H, COVERAGE_SIMULATOR=questa, CONFIG_FILES=config/sail/sail-rv64-max/test_config.yaml, JOBS=2]
    timeout_seconds: 3600
    artifacts: [{path: work/sail-rv64-max/reports/H_report.txt, kind: coverage}]
    diagnostics: [{path: work/sail-rv64-max, pattern: '**/*.log'}]
  - id: generation
    target: sail-rv64-max
    source: Makefile
    purpose: generation
    disposition: run
    needs: [runtime]
    argv: [make, tests, EXTENSIONS=H, JOBS=2]
    timeout_seconds: 3600
  - id: build
    target: sail-rv64-max
    source: Makefile
    purpose: build
    disposition: run
    needs: [generation, sail, compiler]
    argv: [make, elfs, EXTENSIONS=H, CONFIG_FILES=config/sail/sail-rv64-max/test_config.yaml, FAST=True, JOBS=2]
    timeout_seconds: 3600
    artifacts: [{path: work/sail-rv64-max/elfs, pattern: '**/*.elf', kind: elf}]
    diagnostics:
      - {path: work/sail-rv64-max/build, pattern: '**/*.sig.log'}
      - {path: work/sail-rv64-max/build, pattern: '**/*.sig'}
  - id: model
    target: sail-rv64-max
    source: .github/workflows/regress.yml
    purpose: reference_model
    disposition: run
    needs: [build]
    elf_inputs: [build]
    argv: [./run_tests.py, 'sail_riscv_sim --config config/sail/sail-rv64-max/sail.json', work/sail-rv64-max/elfs, --jobs, '2']
    timeout_seconds: 3600
    artifacts:
      - path: work/sail-rv64-max/summary.log
        kind: results
        pass_pattern: 'RVCP-SUMMARY: TEST PASSED - Test File'
        fail_pattern: 'RVCP-SUMMARY: TEST (FAILED|SIGRUN)'
    diagnostics: [{path: work/sail-rv64-max, pattern: '**/*.log'}]
  - id: lint
    target: sail-rv64-max
    source: Makefile
    purpose: lint
    disposition: run
    needs: [runtime]
    argv: [make, lint]
    timeout_seconds: 3600
```
