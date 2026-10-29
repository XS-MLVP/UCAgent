
# ACT4 已有 Extension 审查与授权修复

目标是审查已有测试资产，而不是为新 suite 生成一套替代资产。输入为工作区内独立的
`riscv-arch-test/` Git clone 和只读 ISA 规范；支持 privileged/unprivileged 资产，具体能力以
所选提交为准。输出全部位于 `{OUT}/{DUT}/review/`，原始 checkout 始终不修改。
不要求在线 CTP 必须有 Google Sheet；现有计划、CTP、规范和当前版本的源码共同确定边界。
Skill 不参与必需流程。

## 1. 范围与证据

按 `review_inventory → review_audit → review_authorization → review_repair → review_final`
推进。先建立 `scope.yaml`，再 Check 冻结原始 HEAD、文件内容、模式及子模块。
已有未提交变更属于本轮基线，不得擅自丢弃；忽略目录中的必要输入也须列入 assets。
所有子模块必须预先初始化。不要复制符号链接到工作区外、绝对符号链接或共享工作树。
开始前核对实际 HEAD、提交日期及本地变更，区分上游已有资产与另外保留的本地输入。
更新输入版本后创建新的审查输出，重新发现资产、读取 CI 和验证工具要求；旧结论不适用于新提交。

逐项发现 test plan、CTP、norm mapping、coverage 定义/初始化、generator、测试源码、
目标配置及其依赖。`assets` 的五类路径必须齐全，不存在的类写 `[]` 并检查其是否是遗漏。
`discovery` 记录搜索路径/命令及选取或排除理由，不能只挑选容易通过的文件。
`references` 记录规范版本、章节、CTP 和计划来源；`targets` 覆盖所有适用 XLEN、特权级、
扩展依赖和目标配置。
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
Questa/VCS 先检查既有安装、可用合法介质与许可证，并进行最小编译/执行验证；有条件时安装。
确实缺少介质/许可证时可不提供 install，但必须给出 `reason`，指出缺少项、影响和恢复动作。
不得把版本命令成功等同于 license checkout 成功，也不得用另一仿真器替代所要求的 coverage。

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
冻结的 `reference_files` 名单或内容变化须开始新一轮审查，不沿用原判断和授权。
修改说明同样改变授权摘要，已批准的方案仍须重新授权。显式 `run_commands: true` 始终重跑
完整矩阵，不会因为已有缓存而跳过执行；不要为修正报告文字重复下载工具和构建。
`review.md`/`final.md` 展示审查决策、逐 job 状态、ELF/模型通过数、失败命令和诊断链接。
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
`diagnostic:<编号>:<编号>`、`reachability:<保留路径>`、`duplicate:<编号>`。
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
- `basis`：非空引用列表，每项提供 `path`、`lines: [起行, 终行]`、`quote`、`observation`。
  path 相对于 review 目录，只能引用冻结源码/规范、本轮 evidence JSON 或保留日志/产物；不能用自己写的报告作证明。
  源文件为空或二进制无法逐行引用时，引用 evidence JSON 中对应文件身份/诊断并说明限制。
  行号从 1 开始，最多 100 个物理行，quote 必须与选定行逐字一致，使用 `|-` 避免多余末尾换行。
  observation 说明原文证明了什么，不能把引用中没有的内容当作事实。

规范完整性或覆盖点质量的总审查标为 passed 时，必须引用冻结的 `references/` 原文。
推断不能写成确认通过；AI 不能证明未运行的 CI 成功，也不能把源码标签升级为实测命中。
报告顶层 checks 不能在相关 AI 判断仍为 issues/unverified 时写 passed。
证据重收集后使用新 digest 重新审查，普通 Check 校验现有判断，不额外调用模型。

## 2. 人工授权与修复

所有 `evidence` 字段使用非空字符串列表；结论、位置、义务、风险和原因使用非空文本，
不能用布尔值或数值充当说明。`testcases`、change 的 `findings` 和 `validation_jobs`
使用字符串列表。

完整审查写 `review.yaml`，Check 生成 `review.md`、`evidence-before.json` 和
`authorization.json`。每个 finding 使用唯一 `F<number>`，每个 change 必须关联 findings，
声明确切文件路径、动作、风险和复验 job IDs。批准只允许这些路径；没有发现允许
`findings: []`、`changes: []`。不得自行制造问题以获得修改许可。
有发现但尚不能提出安全修复时，在 recommendation 中说明待确认根因、补齐动作和风险。
`authorization.json` 的 mode 为 repair 或 report_only，并列出 findings_without_changes。
report_only 的空路径批准仅接受审查结果，不授权源码修改；后续新增修改仍需重新审批。
`post_assets` 必须列出修复后的五类完整资产集合，无变化时逐类复制 `scope.assets`。
新增或删除的集合成员必须在批准路径内；不能从集合中隐藏仍然存在的原始资产。
新增 coverage 定义也必须列入，最终 traceability 才能按真实修复后的定义复验。

进入 `review_authorization`，展示报告、失败/未验证项及摘要。调用 Complete 后等待人类。
操作员在 UCAgent PDB 控制台执行 `hmcheck_pass <authorization.json 中的 digest>`，
再继续 agent；拒绝使用 `hmcheck_fail <原因>`。这是操作员控制命令，不是给 agent 调用的工具。
报告中的 approved 字段、`ApproveStagePass` 或文字同意均不能替代该操作。
摘要绑定基线、报告、命令矩阵和审查证据；内容改变后必须重新批准。

批准阶段实际完成后才可在 `candidate/` 修改批准的路径。先 Check 准备副本，再修复并运行
`Check(stage_args={"run_commands": true})`；命令生成物保留到 evidence 所指位置，不能把
日志/缓存误当贡献源码。generated `.S` 应由批准的 generator 重生成，不手工弱化断言。
发现额外修改需求时停止，让操作员回到授权阶段更新提案并重新批准。
重启能恢复已完成审批，但未完成审批不保留为授权；若丢失可信状态，使用新输出目录重审。
源 checkout、基线、已审报告或证据漂移均不能继续沿用旧授权。

`final.yaml` 必须交代每一个 finding 的 fixed/deferred/not_fixed、证据及原因；fixed 必须有
批准路径的实际变化且关联复验 jobs 全通过。工具缺失/CI 失败仍可交付部分修复报告，必须
保留 remaining_risks，`ci_passed: false`，不得伪报全部完成。最终 traceability 针对修复后的
全部 coverpoints，并列出 coverage_changes（即使无变化也写 `[]`）。
`coverage_changes` 每项包含 `coverpoint: group/name` 和 `reason`；新增、删除的每个点必须
有一项说明，已有点的 bins/约束/义务变化也在这里解释，不能通过删除 coverpoint 隐藏缺口。
最终 `semantic_review` 必须重新评估 `evidence-after.json.review_tasks`，使用 after 的
`review_digest`，并额外覆盖每个 `finding:<ID>` 及 `change:<确切变更路径>`。
修改项引用 candidate 中的源码，删除项引用 baseline；可同时引用基线进行前后比较。
fixed finding 的 AI 复核必须为 passed/confirmed，仍为 issues/unverified 的结论不能称为已修复。
所有未解决的语义疑点及推断也须写入 remaining_risks，即使命令均通过也不能省略。
Check 生成 `final.md` 和 `changes.patch`，包含原始审查、前后验证、授权、逐项处置、精确
变更及风险。补丁支持 UTF-8 文本源码及模式变更，不支持二进制或符号链接变更。
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
discovery: ["Searched plans, coverpoints, generators and tests; only generators/H.py exists"]
jobs:
  - id: env
    target: rv64-example
    source: README.md
    purpose: environment
    disposition: run
    probe: [act4-example-missing-licensed-simulator, --version]
    timeout_seconds: 30
    reason: "No licensed simulator installation or installer/license available; operator must provide these before coverage can run"
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
changes: []
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
    - tasks: ["topic:act4_compliance", "topic:omissions", "diagnostic:0:0", "diagnostic:0:1"]
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

人工审查决定暂不修改后，`final.yaml` 完整内容：

```yaml
schema_version: 1
suite: H
summary: Review delivered without source changes; validation and coverage remain unverified.
findings:
  - id: F1
    status: deferred
    evidence: [review.yaml, evidence-after.json]
    reason: No source repair approved; prepare native environment and authoritative assets first.
ci_passed: false
remaining_risks: ["Native CI unavailable; no claim of ACT4 compliance or measured coverage"]
coverage_changes: []
traceability: []
semantic_review:
  reviewer: ai
  evidence_digest: REPLACE_WITH_AFTER_REVIEW_DIGEST
  judgments:
    - tasks: ["topic:act4_compliance", "topic:omissions", "diagnostic:0:0", "diagnostic:0:1"]
      status: issues
      confidence: inferred
      reasoning: "No source repair was approved. The candidate remains a constant-only generator and after-evidence still reports missing mapping and registration, so the original asset gap remains."
      conclusion: The original conformance and asset completeness issues remain open.
      limitation: The specification and complete native assets have not been recovered.
      next_action: Obtain the authoritative suite inputs and agree a concrete repair scope.
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
      next_action: Recover the required inputs and tools, then start a newly authorized review.
      findings: [F1]
      basis:
        - path: candidate/generators/H.py
          lines: [1, 2]
          quote: |-
            """Native H generator fixture."""
            VALUE = 1
          observation: The reviewed candidate provides no testcase semantics or bin-hit evidence.
```

这轮即使没有修改仍必须经过真实人工审批，输出空的 `changes.patch` 和完整 `final.md`，
不能将 deferred 或 unavailable 偷换成 fixed/passed。

## 4. 环境准备与构建执行示例

以下完整 scope 示例以提交 `0a29a3afdaba96b04f77e6e2559030475720a9b2` 的 H、
sail-rv64-max 为例：其 CI 使用 Sail 0.16、GNU 工具链发行版 2026.08.27。
其它提交必须重新读取实际版本约束和命令，不要将此示例当成版本自动发现结果。
审查资产仅示范 generator；实际任务应列全已有资产。原生 Python 安装复用 mise/uv，
开始前按 README 安装 mise；同样将其探测、安装动作写入环境 jobs，不省略其它工具。
示例故意把 coverage 放在 build 前，依赖关系仍保证先生成和构建。Questa 的 probe 包含
最小编译/仿真；若存在合法安装介质，应增补 install 参数，不能只保留缺工具说明。
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
  - id: questa
    target: sail-rv64-max
    source: docs/DeveloperGuide.md
    purpose: environment
    disposition: run
    probe:
      - bash
      - -c
      - |
        set -e
        command -v vsim
        cd "{TOOLS}"
        printf '%s\n' 'module review_smoke; initial $finish; endmodule' > review_smoke.sv
        test -d review_work || vlib review_work
        vlog -work review_work review_smoke.sv
        vsim -c review_work.review_smoke -do 'run -all; quit -f'
    reason: "Supply an authorized Questa installer and working license, add install, then rerun the compilation/simulation probe; measured coverage remains blocked meanwhile"
    timeout_seconds: 120
  - id: coverage
    target: sail-rv64-max
    source: Makefile
    purpose: coverage
    disposition: run
    needs: [build, questa]
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
