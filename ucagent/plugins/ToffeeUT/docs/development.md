
# ToffeeUT 开发和运行契约

## 安装边界

插件与 UnitTest 同级，独立包名 `ucagent-toffee-ut`，导入 `toffee_ut`，工作流
`toffee-ut:ut` 和任务交接入口 `toffee-ut:adopt`。它不依赖 UnitTest；默认工作流
指针已切换到 `toffee-ut:ut`，UnitTest/DesignWithPPA 保留为 Legacy 可选工作流。
UCAgent 主发行包仅增加 ToffeeUT 的打包排除项，避免把独立插件与本地 venv 带进主包。

`scripts/setup_env.py` 创建插件目录内的一个 `.venv`，从指定 UCAgent 源码读取核心
requirements，排除 pytoffee/toffee-test 后安装，加上插件的 Toffee 2 依赖，再通过
`.pth` 引用该份 UCAgent 源码。没有第二个 runner 环境；所有工具与测试使用同一个
`sys.executable`。脚本不安装旧 Toffee，不修改 Legacy 环境或 ucv4xs。默认
`requirements.txt` 已使用 Toffee 2；该脚本主要用于与 Legacy 环境并存的独立 venv。

venv 是可选的准备方式，不是工具运行前提。使用已准备的本地解释器与最新源码时，
不调用该脚本、不从旧 venv 补导入路径；让该解释器可导入所选 UCAgent、ToffeeUT 和
兼容的 `uc-toffee`，并核对实际模块路径和 Picker 可执行文件。用户级安装的工具回归
若用临时 HOME 隔离配置，应保留原解释器的 PYTHONUSERBASE，避免子进程误换安装根。

默认 `pip install UCAgent` 现在安装 Toffee 2；Legacy UnitTest/DesignWithPPA 必须在
独立环境使用 `requirements-legacy-unittest.txt`，不能与默认环境混装。此源码接入
不安装 UCAgent 发行包；源码树已有旧 egg-info 时，`pip check` 可能仍按旧元数据
报告缺少 pytoffee/toffee-test，刷新 egg-info 后再核对。其余依赖错误仍需修复；
发行版环境还需操作者提供匹配的 UCAgent 核心。
需要编译实际 DUT 时，外部工具链为 Picker、Verilator、C/C++ 构建工具及
verilator_coverage。Toffee 2 依赖提供 xspcomm 绑定；已有 DUT 包的 ABI 仍需与当前
Python/绑定匹配。缺工具链不会阻止资料和规格工作，构建调用会返回具体阻塞。

## 自己的 opencode + MCP

按 README 启动 UCAgent 工具服务后，在任务工作区的 OpenCode V2 配置中合并以下
MCP 条目。不要覆盖其他配置或填入模型密钥；只监听本机回环地址。

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "ut": {
        "type": "remote",
        "url": "http://127.0.0.1:5000/mcp",
        "oauth": false,
        "timeout": { "execution": 3700000 }
      }
    }
  }
}
```

这里的本地 UCAgent 服务不使用 OAuth；不要把这个示例用于需要身份认证的外网服务。
启动 `opencode /abs/workspace`，用 `/models` 选择当前项目可用的模型，并让它：

```text
请通过 UCAgent 的 RoleInfo 和 CurrentTips 获取当前任务，使用其 ReadTextFile 阅读
阶段 reference_files，然后按 toffee-ut 工作流执行。所有修改限于当前任务允许目录。
资料盘点、骨架、编译、测试和汇总使用 UTProject、BuildToffeeDUT、RunToffee。
```

不用自动 loop、不由 UCAgent 发起另一个 opencode，就可以保留自己的交互终端和模型
选择。若明确希望 UCAgent 自动调用现有 opencode 后端，可增加
`--backend=opencode --loop`；模型用其已支持的 CLI 追加参数传入：

```bash
export UC_ENV_CMD_BACKEND_EX_ARGS="--model <provider/model>"
```

这只影响自动调用模式，不影响你自己的交互会话。后端客户端配置由现有 UCAgent
负责，插件不修改它。OpenCode V2 的依据为官方
[MCP](https://opencode.ai/v2/docs/mcp-servers)、
[模型](https://opencode.ai/v2/docs/models)和 [CLI](https://opencode.ai/v2/docs/cli)说明。

## 确定性接口

| 入口 | 职责 |
|---|---|
| `UTProject(inspect)` | 真实输入发现、hash、schema2 DUT 映射与资料分流 |
| `UTProject(scaffold)` | 按文件创建新工程；已有 schema2 工程只接入、不插入占位测试 |
| `BuildToffeeDUT` | 结构化 timing/rtl_defines/include_dirs 编译用户 RTL，复核输入字节与配方；拒绝覆盖已有包，失败保留日志 |
| `RunToffee` | 同一选定解释器运行实际选择，串行/xdist、取消/超时、逐例阶段和构建证据 |
| `WaveInfo` | 读取精确节点的信号目录、事件窗口并生成绑定运行的波形观察收据 |
| `CoverageInfo` | 分页读取当前 DUT 的实际原生行/分支/toggle 计数及未覆盖点 |
| `UTProject(audit)` / Checker | 相同的阶段验收，不自动启动测试或改变资料 |
| `UTProject(summary)` | 从当前运行更新 docs/README.md 的人读总览和证据入口，保留生成区块外的人工说明 |

离线 CLI 复用同一实现。例如：

```bash
toffee-ut inspect /abs/workspace MyDUT --rtl-dir inputs/rtl --document inputs/spec.md
toffee-ut scaffold /abs/workspace MyDUT --native-package MyDUT
toffee-ut audit /abs/workspace MyDUT --phase plan
toffee-ut run /abs/workspace MyDUT --workers 1
toffee-ut summary /abs/workspace MyDUT
```

CLI 不经过 UCAgent 的文件写策略，使用者负责只对授权工作区运行；所有路径仍受工作
区边界检查。UTProject/编译/运行工具同时检查词法路径和链接实际目标的写权限。
`ut_timeout` 与单次 RunToffee 的 timeout 单位为秒，上限均为 3600；默认 1200。
构建参数和输入闭包限制见 `Guide_Doc/ut-project.md`；纯替身构建回归不提供原生构建
或硬件通过信用，实际工具链必须在授权 DUT 上执行。

当前工作流逐项保留旧 `unittest.yaml` 的 20 个顶层阶段及 19 个子阶段，按
`Guide_Doc/ut-stages.md` 使用 ToffeeUT 的工程布局和阶段工件，不导入旧插件或接回旧
Checker。由于父容器仅作分组、可选子阶段有跳过状态，UCAgent 实际执行节点数按配置
变化，不等同于 39 个全部必须执行。

`ut_reference_model` 和 `ut_mock_components` 默认 false，分别控制参考模型与 Mock。
`ut_line_coverage` 默认 true，控制独立原生覆盖复盘；缺采集不会自动跳过。
`ut_human_env_spec_review` 和 `ut_human_env_review` 默认 false，分别启用
人工复核及 HumanChecker。仅启用真实适用的可选阶段；其他设计、场景、环境、测试、
静态候选和归因阶段不随资料情况被跳过；无可映射输入文档时仅逐行映射子阶段
显示为跳过，父阶段仍检查功能点与检查点。配置非布尔值在启动前拒绝。

验证文档继续维护既有 `kind: design`/`verification`：行为组、检查点、场景结果矩阵
在同一规格内；逐行物理映射在 `docs/spec/verification/` 下。静态审阅与阶段人工解释
在 `docs/reviews/` 下，以免后写分析文字使已有签名测试源码身份过期。
`RunToffee` 的阶段角色标记只说明对应节点真实执行，不自动证明判据独立。
`rtl` 根因分类逐节点验证 `WaveInfo` 收据、当前 run/nodeid、独立要求和事件级分析，
不再无条件拒绝。缺观察仍保留真实 FAIL 并报告未达成，不通过改标签或跳过复核解决。

## 按任务接入与选择阶段

`toffee-ut:adopt` 包含“任务与边界、相关成果与依赖、阶段安排与人工确认”三个阶段。
它不依赖 schema2 或现成完整运行，只要求 `--output` 指向已有目录；不调用主流程的
准备函数、不生成骨架、不刷新 input_inventory，也不使既有运行因盘点而失效。
业务文件唯一允许写入的位置是 `<OUT>/docs/reviews/<DUT>-adoption.md`，构建、执行、
通用 shell 和 UTProject 均不在该流程的可用工具面。最终使用真实 HumanChecker 批准，
文本 `Check` 只验证结构与本地引用，不认证语义、执行或主流程进度。

主流程新增两个运行选项：

| 选项 | 默认值 | 作用 |
|---|---|---|
| `ut_task` | 空字符串 | 用户本次任务说明；显式选择阶段时必须非空 |
| `ut_task_stages` | null | null 保持完整配置；非空、无重复的稳定阶段名列表只选择这些工作 |

阶段名来自实际 `ut.yaml`，没有硬编码的安全跳过名单。显式父阶段选择包含其已启用
后代；只选子阶段时，未被选择的祖先保留为容器，不运行父汇总门禁或无关兄弟阶段。
节点名称、原顺序和所选节点的检查不变。禁用或不适用节点不能被选择自动开启，
必须先确认其原有可选配置。局部任务完成不表示全 DUT 通过；缺必要合同或证据时仍
报告依赖，由用户决定扩展任务或停止，不通过局部选择来放松所选检查。

例如当前任务只修 monitor：

```yaml
runtime_options:
  ut_task: 修复 monitor 同拍多通道漏采，并验证受影响路径
  ut_task_stages:
    - env_fixture_implementation
    - evaluate_env_fixture
```

将已确认配置另存为 `task.yaml`。两个入口分别启动，沿用同一个插件 venv 和用户自己的
OpenCode/MCP 会话，不自动启动另一模型 Agent：

```bash
python -m ucagent /abs/workspace MyDUT --output existing_project \
  --plugin ./ucagent/plugins/ToffeeUT --plugin-workflow toffee-ut:adopt \
  --config /abs/task.yaml --no-history --mcp-server-no-file-tools -hm --tui
```

接入批准并停止旧实例后再启动：

```bash
python -m ucagent /abs/workspace MyDUT --output existing_project \
  --plugin ./ucagent/plugins/ToffeeUT --plugin-workflow toffee-ut:ut \
  --config /abs/task.yaml --no-history --mcp-server-no-file-tools -hm --tui
```

**历史边界：**框架按工作区保存阶段索引，不自动隔离两个入口或不同阶段选择。
切换前操作者应另存需要的 `.ucagent/ucagent_info.json`，再使用 `--no-history`；
该参数只禁止加载，后续仍保存本次进度，不能宣称旧记录已被隔离或自动合并。
同一入口、同一任务选择中断续做时才沿用原进度；不要为接入删除运行产物或历史目录。
接入的完整工件格式和任务执行边界以 `Guide_Doc/ut-adoption.md` 为准。

## 方法集合与启用范围

10 个问题方法各自保留适用输入、操作步骤、产出、验收和源案例依据：需求边界、观察精度、
行为等价类、实现追溯、退出残余、包分层、合法激励、独立 oracle、checker/运行时、归因证据。
设计导航、执行/复核导航、ucv4xs 项目入口也分别保留，合计 13 个可发现 Skill；阶段给当前
推荐，通用列表允许按问题跨阶段取用，不要求每轮全读。运行时选择入口为
`Guide_Doc/ut-methods.md`，方法不带生成、执行或计数脚本。

P01–P12 速查卡随执行导航复制；依赖升级、fixture 集中、框架选型、迁移边界四篇 pending
随项目入口作为参考复制，不注册为 Skill、不列入阶段推荐，也不提升为强制验收标准。
读取本身不授权改变锁、环境、工程、发布或删除。禁用 Skill、缺少技能目录时，仍按同一
阶段任务、Guide_Doc、工具、模板和验收执行；不依赖 Skill 使用记录推进。

这批内容适配自 ucv4xs 实际工作树，含未提交修订；文件指纹、来源路径和适配边界见
[来源记录](../src/toffee_ut/skills/ucv4xs-workflow/references/SOURCES.md)。方法正文、速查卡和
待审参考保留 MPL-2.0 及许可全文，插件代码和工作流为 Apache-2.0；发行元数据声明两者。
wheel/sdist 与工作区复制均包含这些参考，不依赖读取原来的本机 ucv4xs 目录。
案例保留经验和原路径，不打包原工程运行产物，不把历史结果说成本轮复现。

Skill 在初始化时复制，已有运行实例不会自动读取源文件修改；需要重启实例重新复制。
对旧开发资源不添加别名或自动迁移路径；使用新工作区或由操作者移走旧 Skill 资源后重新
初始化，不自行删除现有工作区内容。

## 运行与证据

- RunToffee 使用 Toffee 的原生 managed pytest backend 和不存在的新输出目录；
  串行/xdist 均由同一个 backend 收集和合并，不另造覆盖运行器。直接加载 backend
  保留解析后的 Python import roots，不让 CLI 把旧安装插件放到当前源码前。
  请求新运行时先废弃旧 latest
  指针，超时、收集失败或证据不完整不会回退到旧绿灯；保留历史目录及日志。
- pytest adapter 使用 Toffee 的 phase_record/case_status，不从 JUnit 反推判定。
  记录精确 nodeid、全部阶段、场景、自检类别、实际 fixture 所有的 DUT 来源和请求 seed。
- 阶段可选 `captured_diagnostics` 只提取名称精确匹配 `Captured stdout/stderr/log <when>`
  的标准文本 sections，保留原序及重复，不用 capstdout 等累计视图，不添加日志 handler、
  流重定向或任意属性协议。按 Unicode 码点计数、头部保留，每段 6000 字符，每阶段总共
  12000 字符及 12 段（含空段）；各段保存 name/text、original_chars、retained_chars、
  truncated，字段内含 unit/retention/limits，完全省略段另累计 omitted_sections/omitted_chars。
  cases 文件继续受现有收据 hash/签名保护，不改 verdict 或门禁，不追补历史。
  renderer 将其独立展示为 runtime captured diagnostics, not independent proof；没有字段、
  无输出或关闭 capture 不产生语义结论；日志中 expected/observed、完成及种子声明都不升级
  为独立判据或运行时结构化检查证明。完整字段例子见 `Guide_Doc/ut-results.md`。
- selftest/shared 用例动态创建的功能组排除自动捕获；模块导入时或 session 共享的
  辅助组必须由工程声明 `capture=False`，用例标记不能追溯隔离已创建的全局对象。
- 禁止环境 PYTEST_ADDOPTS/PYTEST_PLUGINS 或 pytest.ini addopts 暗中改变工具选择。
  conftest 声明的插件仍正常加载；配置项如 asyncio_mode 保留。插件引起的 deselection
  被记录，不能当成完整回归。
- 原生覆盖关联核对 actual fixture class/source 和 manifest 的构建文件，避免只跑
  Python 自检却借用别的 DUT 覆盖。要求引用的构建原件仍在工作区范围内。
- 源码、规格、工程配置、原生包和显式盘点输入按实际字节记录，运行中或运行后变化
  都会拒绝用于当前验收；docs/bugs 与报告说明不属于测试源，不因补充归因而失效。
- receipt.json 和 latest.json 使用工作区私有 key 作 HMAC，校验原始产物及输入身份。
  这是防误改/防手写进度冒充的完整性措施，不是针对可执行任意本地代码的恶意测试
  的安全隔离；不要把它描述为沙箱或可信执行证明。
- manifest 的 committed/coverage_complete 与硬件 PASS 分开。UNCERTAIN、覆盖未达目标、
  推断要求、跳过和排除范围不能计入 PASS。真实设计失败允许以 FAIL 交付；验证设施
  错误必须修复。结构验收不证明激励合法、oracle 独立或行为全集完整，仍需语义复核。
- api_tests/random 在原角色、场景、native 和 seed 条件下接受 PASS 或已核验的 call
  阶段 RTL FAIL。FAIL 路径复用交付的当前问题归因及逐节点 WaveInfo 收据/分析验证，
  要求场景对应 confirmed 要求、当前 open rtl 问题和本 DUT 匹配的 native manifest
  身份；已知设施错误、未确认或缺证据的失败不豁免，设施自检仍须 PASS。定向阶段不
  附加完整回归、覆盖或无关残余关闭要求，不改写 raw FAIL，也不放宽最终交付门禁。
  该路径同时复用已知 failure-only 检查，仅检查当前失败节点的函数身份（含参数化/类），
  不因有效issue放过空模板，也不扫描未选中的模板来扩大定向实现范围。
- 实现门禁及场景批次排除已知 failure-only 空体（仅立即 pytest.fail、assert False 或
  raise AssertionError，可带文档说明），不依据错误消息关键字或问题分类判断；模板创建
  阶段仍允许失败占位。实际 API/比较后保留的 FAIL 不受此规则豁免或降级。这里只拒绝
  能明确识别的空体，不推断任意 Python 调用/fixture 已完成合法刺激和检查。
- 报告投影只消费已校验的 current run 和维护合同；纯渲染器不运行测试、不读测试实现、
  不修改 cases/receipt，也不按异常文本猜实现状态或合并根因。raw、非 selftest 功能候选、
  selftest 分开计数；每个 case 保留全部阶段、角色、声明种子、原生登记、构建身份和原件
  链接，允许关联多份 issue，未归因失败不被吞掉。问题记录数、失败 case 数不是根因数。
- 人读场景到 case 表保留所有维护场景、要求/basis、范围理由、call 候选 nodeid 和原始
  case 结果，未执行和排除项不因没有详细 case 而消失。它不改变结构化证据或计数，
  多标签/多节点只作多对多追溯，不自动产生实现、原生执行、比较或完成信用。
- scenario 的 stimulus/expected/oracle/completion 与 requirement 来源/basis 是计划合同，
  不是实际比较、逐 UID 完成或 oracle 独立性的运行证明；缺少的实际字段明确披露，不能从
  PASS、标签、错误字符串或覆盖计数补造。requested/declared seed 都不证明 native 生效。
  runtime 只显示收据已有字段；源码 hash 表和完整 build 原件链接到 receipt/manifest，
  源码映射使用排序、紧凑 JSON 的 SHA-256 标识，避免复制完整 hash 表。没有收据字段的
  工具提交、构建选项及跨版本同刺激结论不作证明。
- summary 管理生成区块，链接从 docs/README.md 出发（results 用 `../results/`）；
  保留机器证据原义与区块外的人工说明，final 依据当前证据核对生成内容。问题正文示例见
  `Guide_Doc/ut-results.md`，交付渲染回归见 `tests/reports/test_reports.py`。

## 当前限制与测试范围

目录与验证方法参考 ucv4xs 的 `docs/reference/module-layout.md` 和 `skills/` 下的
design/execution/review 方法，落实为本插件的独立实现。插件不导入 ucv4xs 运行代码；
采用已有工程时，该工程自身的运行依赖（例如 ucv 包）仍需安装到同一个 venv。

本实现不迁移 schema1、旧 UnitTest、标记覆盖或旧 WaveInfo 协议。ToffeeUT 的独立
WaveInfo 使用 wavekit 读取 VCD/FST；默认原生捕获在登记 DUT 时设置运行内的唯一
waveform 路径，不调用 Step、reset 或 immediatewrite，仍由原 fixture Finish。
运行收据对波形字节、nodeid 与原生实例身份签名；分析收据另存，不改变原运行。
已生成的观察收据不因原波形清理而失效，普通 Check 不重放或重新仿真；若原文件仍在但
被修改，则明确拒绝。新的窗口分析需要原件，不能从旧的分析文字还原缺失波形。
根因解释仍需语义审查，不因机器收据存在自动正确。Native seed 必须由实际 fixture 接入，
记录请求值不等于已经证明原生种子生效。共享 origin 的 first/last 不提供完整逐例
覆盖归因，场景标签也不证明相应比较已经发生。

插件回归使用临时工作区，验证契约、配置、模板和真实 Toffee/pytest adapter；构建
调用使用受控替身校验 argv、输出和取消，不编译额外示例 DUT。真实 RTL 全流程须在
用户选择的实际 DUT 上运行，不能用插件回归结果声称硬件验证已跑通。
