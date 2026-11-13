
# ACT4 插件开发

插件实现位于 `src/act4_privileged_suite/`，不修改 UCAgent 核心的默认 workflow、
依赖或 checker 导出。`ucagent-plugin.toml` 支持源码加载，`pyproject.toml` 的
`ucagent.plugins` entry point 支持安装态发现；两者指向相同 provider。

## 资源和注册

- `plugin.py` 声明三个工作流、10 类 checker、依赖和 Guide_Doc。
- `workflows/privileged-suite-generation.yaml` 保留 ITGen 七个资产阶段及其验收规则，
  使用插件 registry 的 checker 短名。
- `checkers/` 包含资产一致性、CTP/manual 来源、审查、switch、manifest 和最终报告校验。
- `Guide_Doc/` 包含运行指南、checker 说明和阶段填写模板，仅在选择本工作流后复制。
- 各阶段 `reference_files` 列出当前模板及所用 gate 的说明，保留原有 ACT4 原生输入。
- `tests/` 保留 ITGen 的 ACT4 checker 回归，并增加插件描述、阶段生命周期及配置测试。

这些文件迁移自 ITGen 的 `itgen/lang/zh/config/act4_priv_suite_generate.yaml`、
`itgen/checker/act4_*.py` 与相应指南及测试。原有 `work_itgen_<Suite>` 构建目录名继续使用。
checker 使用包内导入，所有 Checker 构造函数调用核心基类初始化，不依赖
`sys.path` 注入、ITGen checkout 或顶层模块别名。
生成工作流为 8 个阶段（含环境准备）、25 个资产 gate。环境 checker 先记录并复验工具，
后续执行使用校验过的持久/临时工具 PATH。插件特有适配为
checker 短名注册、manual 路径配置和静态规范引用；生成器独立性校验另外拒绝
`act4_privileged_suite` 私有导入/路径及 `ACT4_MANUAL_ROOT`，允许 ACT4 原生输入。
UCAgent 版本下限采用实际测试的 `26.9.2.dev25`。

`xiangshan-v3-handoff` 只追加注册，生成与 review 的配置和工具启用条件不变。
`ACT4XiangShanChecker` 管理范围选择、输入、目标、构建、交付五个阶段，另有环境准备，完整运行契约见
`Guide_Doc/ACT4_XiangShan_Handoff_Guide.md`。输入可为无 Git 的本地目录；匹配 ACT 框架、
用户输入资产与 checkout 在输出目录之外；缺省输入缺失时，`xiangshan_acquisition.py` 将公开仓库
下载到自身 `repositories/`，不修改用户 checkout。write_dirs 只开放输出，不对输入执行 chmod。
scope 用真实上游搜索清单和香山引文约束优先复用；补全在独立 clone 中调用现有生成工作流，
保留实际执行、阶段完成及资产指纹。缺口生成不扩大原生成工作流的新 privileged suite 能力范围。
生成命令只在显式 prepare/generate 后的副本执行；此隔离是工作区约定，不是 OS 沙箱，
只应执行已审阅的可信原生生成器。目标引用要求实际 V3 checkout 的提交、逐行引文和源文件内容一致；
它验证出处和契约完整性，不机械证明 AI 对硬件参数的推导正确。

`xiangshan_bundle.py` 仅使用标准库，作为交付包的 `act4_driver.py`；`xiangshan_recipient.py` 提供
独立的 `handoff.py` 命令。构建固定调用包内 ACT
workspace 的 `uv run --frozen act`，重新生成 Sail signature 和最终 selfcheck ELF，使用每次新建的
build 目录，逐项核对实际 ELF 与选中测试。原生框架版本不支持该 CLI 时明确失败，不引入旧协议兼容分支。
build/run 收据摘要保存在阶段状态中；Check/Complete 验证当前输入、输出与收据，普通调用不重跑命令。
重新 adapt 会使已有构建、运行和交付失效。`xiangshan_delivery.py` 将运行源码和 ELF/bin/disass 按
原 ACT 路径发布到独立 delivery/；操作指南与测试索引各一份，机器元数据合并到 manifest.json。
日志、signature、原始副本、详细追溯收据与中间产物留在插件输出，不进入最终目录或压缩包。
归档通过标准库 runner 做异目录核验。交付状态区分源码、已构建未执行、模拟器通过和模拟器失败。
模拟器运行记录可执行文件摘要，但不把用户给定的 emu 自动认证为指定硬件提交。

`xiangshan_trace.py` 校验每个选中源码的原生 testcase 标签、覆盖声明及规范引用；native_mapping
复查上游 norm 映射，isa_reasoned 保留推导依据且不冒充上游映射。`traceability.json` 是报告、
源码注释与 ELF 描述的共同输入，所有 testcase 必须有设计、激励和预期结果，文件需说明
preconditions/setup/exercise/check/limitations，不能只写摘要。保留 ACT 用例与覆盖点组织，功能分类仅辅助索引。
原始源码不改，selected-tests 添加注释及非加载 SHT_NOTE，链接脚本保留 `.note.ucagent.act4`。
构建和复验读取 note 并与冻结描述比对，加载段中的自检标记与退出指令仍独立检查；不接受
仅在说明区存在这些字符串的 ELF。包内脚本只用标准库读取 note，不生成逐 ELF 重复报告。
objcopy/objdump 从同一最终 ELF 导出产物，校验裸二进制范围并记录加载地址。

接收方支持按完整 ACT 程序路径选择构建和运行。重建在 local/ 下的隔离副本运行，重新生成 Sail
预期值，原始交付不变；显式 --modified 只接受 src/config 修改，更新描述中的复核状态。
未成功的新构建阻止 --local 运行旧产物，构建后输入漂移也需重建；原证据不自动继承。
环境工具按可移植配方在 local/tools 安装或复用，操作日志只在接收方执行后产生。

`workflows/extension-review.yaml` 提供独立 ISA 计划、审查、修复三个阶段，`ACT4ReviewChecker` 管理
冻结基线、审查契约、真实命令证据、声明的修复范围、候选差异与最终补丁；复用
`ACT4AssetChecker` 和现有 SV/assembly 分析，不使用仅允许新 suite 的 manifest 门禁。
初审允许资产检查或 CI 失败，门禁要求报告完整、真实并保留限制。修复在候选副本进行；
输入目录通过文件工具写入白名单保护，并在每次 Check 检查内容、模式；Git 输入还核对 HEAD 及子模块。
工作流只将 Guide_Doc 配置为 `un_write_dirs`，避免核心初始化的 chmod 改动输入模式；
`write_dirs` 只允许输出目录。外部 shell/MCP 仍须遵守只读输入约定，边界不是 OS 沙箱。

`review_plan` 先用用户范围及 ISA 原文建立 isa-plan.yaml，冻结来源及选区后逐块设计激励、观察和
适用性；Complete 接受原始计划，阶段状态绑定 plan/context/来源身份。只有完成该步骤才能进行
资产审查和执行计划校验；后续 obligations.plan_items 对照全部 I<number>，新增发现可为空列表。
每个原计划项均须保留对照，误判可引用规范解释排除，不能重写初稿以匹配已有资产。
阶段和引用白名单防止流程跳过与证据混用，不提供模型上下文隔离，不能证明模型完全未受先验影响。
`review_audit` 合并范围盘点、基线冻结与完整审查。review_plan 首次 Check 在 isa-plan.yaml 之前也可运行，
先生成受状态摘要保护的 environment.json，探测 Questa/VCS/Xcelium 的可执行文件及最小
SystemVerilog covergroup 编译/仿真。每条探测命令超时 20 秒，普通 Check 复用结果；
refresh_tools 允许在 plan/audit 显式重探测，并使已有原生命令证据失效。有 scope 时继续冻结基线，Complete
仍要求真实命令证据及完整 review.yaml。`review_repair` 依次运行 repair、final 两个 gate，
准备 candidate、校验声明路径和复验结果，并要求最终报告后才能完成。
流程自动推进，恢复会话沿用基线、证据指纹及 candidate 状态。信息不足的 finding 可标为
deferred/not_fixed，但须记录分类、诊断进度、带精确引文的调查动作、具体 blocker、责任方和最终风险；
需要用户输入时单独写具体请求及为何只能由用户提供。dismissed 表示经证据排除的疑点，不计为修复。
修复提案只能关联 confirmed_defect/repair_ready；fixed 仍要求实际修改、
关联验证通过和当前语义复核。更新修复计划时重新校验报告，执行输入变化时重新取证。
规范示例见独立运行指南，避免在生成工作流文档中复制另一套契约。

review 专用 ACT4_REVIEW_ROOT 默认为 riscv-arch-test，支持工作区内的独立 Git clone 或无 Git 的
本地模块目录；使用独立路径验证入口，不改变 generation 的初始化规则。目录输入完整指纹化，
没有虚构的 HEAD，缺少 Git 不阻止目录 review 启动；Git 输入实际冻结时才需要 Git 命令。
原生命令在独立副本运行：Git 输入保留提交及索引语义，本地目录直接复制冻结源码，无共享
hardlinks 或反向链接；生成文件不反写 baseline/candidate。每项命令记录 argv、cwd、退出码、日志和
产物摘要。后续 Check 使用绑定源码/矩阵的缓存，只有显式 `run_commands: true` 才重跑。
矩阵通过 `needs` 排序并传播前置失败；每个 target 声明 environment lane，公开工具探测失败时
运行声明的安装命令并复验。安装只使用输出下的 tools 目录。商业工具以 optional_tool 声明，
不提供安装流程；不可用时只跳过依赖它的可选 job，必要 job 不得依赖可选 job。
可选 lane 未执行时完整 ci_passed 仍为 false，报告独立计算必要验证结果，允许如实完成审查。
build 依赖 generation，执行依赖同 target 的非空 ELF 构建产物，
模型结果按原生格式核对通过数等于输入 ELF 数；零测试、空产物和 signature-only 结果均失败。
日志、产物和候选内容变化会使证据失效。静态结果与 measured coverage 分开，通用门禁
只能核验 coverage 产物来源，具体 bins/义务等价仍需 AI 与人类结合原生产物审查。

review 在保留现有资产检查的基础上启用完整声明资产的格式解析、generator 独立性及现有
cross default-bin/bitwalk 结构检查，
复用 assembly 条件分析建立源码/本轮生成用例的 descriptor-label 对应；条件未知、确定不可达
或解析异常的链接不能标为 static。measured 仅接受成功 coverage lane 的正式产物。
规范输入通过 `scope.reference_files` 单独冻结并核对原件；这些设置仅在 review 中启用，
不改变共享 checker 的默认参数或生成工作流的门禁。共享 checker 的 `coverage_context_files`
默认为空；review 显式传入背景 SV，只补充 mapping 符号解析，不扩张 coverage/generator 审查集合。
review 不执行跨不同 mapping 路径的同源比较，重复诊断保留全部 occurrence 后按事实合并。
审查任务用 `UnityChipBatchTask` 分批，完成状态始终从当前报告和冻结证据重新核验；
文档工具只在 review 项目注册，负责引文提取和安全序列化，不提供语义判断。
review 的 `batch_size` 默认 12，允许 1..50；`max_stalled_checks` 默认 8，必须为正整数。
连续相同失败按实际 Check 调用计数，成功、诊断变化或已核验进度变化会重置计数；达到阈值设置
Agent 的 break 状态，避免在一次后端调用内部反复调用工具。外层 `max_stalled_rounds` 也只在
review 配置中启用，不改变其它工作流的默认循环行为。
review 还提供绑定具体诊断及进度的 `failure_key`，阶段重复失败提示使用该显式身份区分同一字段的
不同错误；未提供此字段的 checker 仍按 error_code/location 计数。

机器从全部声明计划及 reference_scope 选定的规范范围生成最多 80 行的 obligation_sources/source
任务，独立于 coverage/testgen 是否存在；同一计划不重复登记，排除范围保留 boundary 审查任务。
Agent 从这些区块提取 obligations，建立目标、覆盖点与实现的
正向映射；缺口必须关联 finding，排除必须说明理由。此划分是阅读完整性约束，不是 ISA 语义解析器，
不能证明未声明的来源已经找到，也不能机械证明每条义务已被正确解释。修复后保留原义务 ID 和
已删除计划的基线来源，防止通过删计划消除待审查项。shared_assets 单列消费者及审查边界。

主 Agent 必须完成 `semantic_review`：机器证据列出八类主题、来源、共享依赖、逐 coverpoint/cross、静态诊断、
条件疑点和字节重复候选，另逐项审查 obligation/finding；每项给出推理、结论、置信度及可验证的原文引用。
静态诊断另有 asset_defect/scanner_limitation/scope_mismatch/unresolved 分类，原始静态结果保持不变。
门禁校验任务完整性、
输入摘要、行号/引文、关联 finding 和结论一致性，不宣称能机械证明推理正确。
修复后以 after 证据复核全部任务、原 finding 和变更文件，未解决的判断进入最终风险。
复用仅引用已验收的审查快照：源输入、配置、验证结果/产物、任务定义和引文全部不变才生成
reuse-final.json；finding/change/义务最终状态仍重新判断，未知依赖变化保守全量失效。
复用记录仍进入同一 UnityChipBatchTask 并重新校验身份，不维护第二套进度或把 unverified 升为 passed。
完整运行契约及示例集中在 `Guide_Doc/ACT4_Extension_Review_Guide.md`。

final.md 先呈现摘要、按问题性质和处置状态统计的结果、调查与未修复原因、用户请求，随后
列出验证限制；前后原生命令表及日志放在可展开详情中，完整结构化证据链接到 YAML/JSON。
扫描告警数与确认缺陷数分开，空补丁或可选 coverage 缺失不再掩盖实际完成的审查。

review 的 confirmed_defect 要求 repair_plan，未修复原因区分真实外部依赖、内部工作未完成和预算停止。
外部阻塞须提供四种替代路径的调查依据；这些约束校验证据及完整性，不证明语义推理正确。
ACT4ReviewDocument 支持 isa-plan 的 status/quote/update、定向 context 和最终 reuse；独立计划
只引用 ISA 快照，接受后禁止编辑。最小实验通过 Check 的 experiment 参数进行，
复用原有命令执行/取证路径、阶段状态及可选工具探测，不启动生成工作流。
实验目录、允许修改路径、任务依赖及收据与正式 candidate 分开；实验不能证明正式修复已通过。
实验收据及已验收快照摘要由阶段状态绑定，普通文档文字或手工伪造的 JSON 不构成调用证据。
max_experiments 默认 6（1..50），max_experiment_seconds 默认 1800（1..3600）；所有 review
阶段须使用一致限额，累计执行额度跨 Check 实例保留。命令共享截止时间，达到上限不再启动后续命令。
隔离副本不是操作系统安全沙箱，仍只应执行已审计的原生工程命令。
validation-plan 核对原生 ci.yaml 排除项及最终 run_cmd，已知偏离必须明确标为诊断；
不自动证明动态矩阵选择，未知布局保留未核实，局部 make lint 不冒充完整上游 lint。
所有新增入口只在 review 项目激活，生成工作流的配置、资源与默认门禁保持不变。

本工作流不主动启用核心 `check_pass_refinement` 独立 LLM 复核：核心当前在建议生成异常时
会将阶段标为 approved（`ucagent/stage/vmanager.py` 的 `gen_pass_suggestion`），不宜将它
作为强制语义门禁。采用主 Agent 的结构化审查，不增加第二套模型 API 配置，也不把 schema
校验当成独立模型已审查的证明。

manual 路径由工作流的 `template_overwrite.ACT4_MANUAL_ROOT` 提供，加载 YAML 时解析
`ACT4_MANUAL_ROOT` 环境变量，再由 UCAgent 模板系统统一渲染进提示和 checker 参数。
各工作流的 context factory 在初始化前验证输出是工作区内非空相对目录，解析符号链接
后输入和输出仍位于工作区内，且输出、选定输入、manual 两两不重叠；不修改最终配置。
新增配置应继续走 UCAgent 的最终配置，不在 checker 中重复读取环境变量。

## 源码与安装态

在仓库根目录执行 Python 会优先导入当前 checkout，不一定使用环境中已安装的核心。
初次构建前若缺少生成的 `ucagent/_version.py`，源码版本为 `0.9.1+source.code`，会被
插件最低版本检查拒绝，即使 `pip show UCAgent` 显示一个兼容版本。

开发当前核心与插件时，先在仓库根目录执行一次 `python3 -m pip install -e .`，再安装
插件开发依赖。该步骤由构建系统生成核心版本，不要手写 `_version.py`、修改版本门槛
或在测试中伪造通过。检查 `python3 -c 'from ucagent.version import __version__; print(__version__)'`
后再执行下面的源码校验。

只验证已安装核心时，应在仓库外运行 `ucagent --validate-plugin`，以绝对路径加载
本插件；测试同样使用绝对路径，并加 `--import-mode=importlib`，避免仓库根目录
进入导入路径。记录实际使用的核心版本，不把安装态回归说成当前核心源码回归。

## 验证与打包

在插件目录执行：

```bash
python3 -m pip install -e '.[dev]'
make validate
make test
make package
```

也可在 UCAgent 根目录直接加载源码：

```bash
python3 ucagent.py --validate-plugin ./plugins/ACT4
PYTHONPATH=plugins/ACT4/src python3 -m pytest -q plugins/ACT4/tests
```

`make test` 使用临时工作区和合成资产，检查成功与失败边界，不联网生成真实 suite。
阶段启动测试使用 UCAgent blank backend，验证 Skill 开启/关闭时均能装配完整工作流，
并验证 manual 路径覆盖、Guide_Doc 复制与目录策略。
路径测试覆盖输出越界、符号链接越界、输出与 ACT4 重叠及外部只读 manual；manifest
测试覆盖已有 suite generator、重复基线路径与缺失/错误的对象身份字段；最终报告
测试区分 YAML 布尔值与数值，避免 `1`/`0` 冒充 readiness。
`test_documentation_contracts.py` 将指南中的完整清单、最终报告和参考运行记录交给真实
checker 校验，并检查运行文档与生成报告的标题间距，防止示例和实际契约漂移。
插件契约测试还覆盖配置搜索路径、全部 checker 的名称冲突、依赖缺失、命令版本探测
失败和工作流专属依赖的按需激活。原有测试分别覆盖 CTP/manual 来源、资产集合与语义、
generator API/拆分/独立性、VM scope、testcase 可达性、ELF/签名、审查、switch、manifest
和最终报告；测试不等价于真实套件的编译、参考模型执行或 coverage 命中。
正式 ACT4 生成和模拟执行需按 README 准备真实依赖并另行运行。

`test_act4_review_checker.py` 覆盖三个阶段的真实 Complete、自动修复及重启恢复、两种
Skill 设置，以及初审失败、信息不足或无需修改时仍可交付报告的语义。
合成 CI 命令用于验证非零退出、缺工具、超时、缺产物及陈旧产物不得冒充成功；另测
源码/基线/日志/产物漂移、未声明路径、新 coverage 资产、完整追踪和最终处置。
同时覆盖缺失/初始化子模块、dirty 子模块输入、越界路径与符号链接，以及布尔/数值等
不能冒充文本说明或证据列表的格式边界。
环境和依赖测试覆盖已安装时跳过安装、安装/版本复验失败、缺商业许可、依赖循环/未知 ID、
缺 ELF 自动先构建、无效 ELF 阻塞执行，以及原生结果为空/失败/数量不符和安装证据漂移。
review 专属回归覆盖失败/超时诊断保留、截断和省略标记、诊断篡改及越界、未跟踪/忽略资产
进入原生 lint 索引、说明修改复用证据并继续修复，以及精简报告中的 ELF/模型计数。
显式重新执行仍运行完整矩阵，诊断片段不能代替 coverage 证据或覆盖 ELF 输入。
语义审查回归还覆盖格式错误与逐点/重复/条件任务发现、缺失/重复任务、伪造引用与行号、
规范快照漂移、陈旧 digest、无依据的通过/修复声明和 after 复核；完整指南示例也执行这些门禁。
另测注释中的 descriptor 不得形成链接、真实行号、空/二进制输入及静态分析不可用时的诚实报告。
补丁测试使用 `git apply --check` 验证新增、删除、模式、CRLF、无末尾换行和含空格路径。
这些测试不宣称真实 extension 或远端 CI 已通过。

`setup.py` 构建时临时带入根目录 LICENSE/NOTICE，构建结束后清理副本；
sdist 带入它们以支持脱离仓库重建 wheel。发布前检查 wheel 的 entry point、所有
checker 模块、workflow、Guide_Doc 和 `.dist-info/licenses/`，并在仓库外测试安装态加载。
无需为本插件增加核心依赖或仓库根目录 CI。
