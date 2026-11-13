
# ACT4 Kunminghu V3 测试资产交付

根据用户指定的香山模块自行选择对应 ACT suite 或具体功能，优先复用上游资产，补全适用缺口，
生成带逐用例设计说明和规范追溯关系的源码与自检 ELF 包。默认目标为
kunminghu-v3 的单 hart SimTop；不能将 ELF 直接交给独立 CSR/MMU/LSU 模块充当接口激励。
优先交付可运行 ELF；没有本地香山模拟器时明确标为已构建、未运行，不阻塞交付。
工作流不依赖 Skill、Questa、VCS、Xcelium，也不自动构建整个香山工程。先在 handoff_scope
准备源码、确定功能与上游范围，然后 `prepare_environment` 准备 uv、RISC-V 编译器、Sail 等工具；
位置、复用及验证规则见 `Guide_Doc/ACT4_Environment_Guide.md`。

## 1. 选择输入与原生生成

用户可以提供以下工作区相对目录，已有输入均只读：

- `ACT4_INPUT_ROOT`：包含已有模块资产的 ACT checkout 或本地生成目录，默认 `riscv-arch-test`。
- `ACT4_FRAMEWORK_ROOT`：与资产版本匹配的完整 ACT checkout，默认 `riscv-arch-test`。
- `ACT4_XIANGSHAN_ROOT`：检出 `kunminghu-v3` 的香山 checkout，默认 `XiangShan`；引用子模块源码时需先初始化对应子模块。
- `ACT4_MANUAL_ROOT`：ISA manual 和 norm rule 定义，默认 `riscv-isa-manual`。

用户的 `{DUT}` 是香山模块标识，例如 Vector，不必等于 ACT suite 名。调用
`Check(stage_args={"action":"fetch"})` 准备缺失的默认 checkout；新目录只写入
`{OUT}/{DUT}/handoff/repositories/`。读取 acquisition-paths.json 获得实际路径。
已有用户目录不会被更新到别的提交，显式指定但不存在的非默认路径需要补齐。

阅读香山模块的源码、ISA 依赖和用户范围，拆分架构可观察功能，再调用
`Check(stage_args={"action":"discover","queries":["Vx","Vf","Vls"]})`。
关键词仅为向量示例，必须根据模块实际情况选择，不能用固定的模块一一对应表代替判断。
discovery.json 保留候选文件和指纹；读取匹配计划、覆盖、生成器、用例后解释哪些部分适用，
必要时扩大查询。没有搜索命中不等于证明上游不存在，不能只查物理模块名字就决定生成。

以下是 scope.yaml 的完整示例。Timer 是用户任务名，Sstc 是判断得到的 ACT suite。
路径、行号和原文按本次真实源码填写，示例引文仅演示格式，不是硬件依据：

```yaml
schema_version: 1
module: Timer
request: 验证主管定时器的访问控制
features:
  - id: timer-access
    description: 主管定时器访问控制
    xiangshan:
      path: src/Timer.scala
      lines: [1, 1]
      quote: class Timer
    act4_suites: [Sstc]
    queries: [Sstc]
    inspected:
      - path: testplans/Sstc.csv
        lines: [1, 1]
        quote: Sstc timer access plan
    upstream_status: partial
    assessment: 已检查上游计划，本例缺少相应汇编实现
    gap: 上游没有本轮需要的访问测试源码
    resolution: local
generation_jobs: []
```

upstream_status 是 complete/partial/absent；resolution 是 reuse/local/generate/unavailable。
完整上游资产必须 reuse；partial/absent 必须说明 gap。generate/unavailable 另填 next_action。
每个 function 都需香山原文、真实查询、上游候选检查和具体理由，不能漏掉难以交付的功能。
只有生成器而缺少 `.S` 时运行原生 testgen，仍属于上游复用。

真正需要新 privileged suite 时，在对应 feature 填 `generation_job: G1`，并声明：

```yaml
generation_jobs:
  - id: G1
    suite: MissingPrivSuite
    rationale: 上游缺少所需 privileged 功能实现，现有资产不能覆盖这一义务
    eligibility: 已确认该新 suite 有生成工作流所需的 CTP 和唯一 Sheet tab
```

MissingPrivSuite 只是字段示例，不能凭空指定不存在的 CTP。scope 通过后，在 inputs 阶段调用
`Check(stage_args={"action":"synthesize","generation_id":"G1","timeout":7200})`。
它在输出内的独立 clone 运行 `privileged-suite-generation`，保留执行日志、完成记录和文件指纹。
只有全部阶段正常完成且未跳过，才允许 generated:G1 导入；实际只导入本轮缺项涉及文件。
已有 suite 不得用该流程覆盖；不受支持的 unprivileged、已有 suite 修改或微架构测试写 unavailable，
说明后续实现需求，不降低生成门槛。无模型后端、缺规范或生成失败需保留真实原因。

输入目录无需 Git；香山源码需要 Git 提交身份。三个路径不能越出工作区、使用符号链接、与输出重叠。
可以将已有源码复制到工作区，保留正常文件权限；不要修改原始源文件或为了只读而 chmod 输入。
依赖框架必须匹配资产使用的 ACT API，不自动把旧生成器转换成另一版本。

调用示例，`ACT4_WORKSPACE` 指已经准备好上述目录的工作区：

```bash
ACT4_INPUT_ROOT=local-assets/Sstc \
ucagent "$ACT4_WORKSPACE" Timer \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:xiangshan-v3-handoff \
  --output act4_xiangshan --backend langchain --tui
```

以下所有文档写在 `{OUT}/{DUT}/handoff/`。创建完整的 `input.yaml`：

```yaml
schema_version: 1
suite: Timer
framework_paths:
  - README.md
  - pyproject.toml
  - uv.lock
  - framework
  - generators
  - tests/env
  - COPYING.APACHE
  - COPYING.BSD
  - COPYING.CC
imports:
  - origin: local
    features: [timer-access]
    source: assembly/Sstc-00.S
    destination: tests/priv/Sstc/Sstc-00.S
  - origin: local
    features: [timer-access]
    source: includes/timer_helpers.h
    destination: tests/priv/Sstc/timer_helpers.h
generation: []
```

这是本地目录中已有 `.S` 的完整输入示例。读取真实目录后使用实际文件名，不制造不存在的
`assembly/` 或帮助文件。origin 为 upstream/local/manual/generated:G1，source 相对该来源根目录；
destination 相对隔离 ACT 副本。每项 features 关联 scope 的功能 ID，且与来源选择一致。
上游为 ACT4_FRAMEWORK_ROOT 或自动下载路径，本地为 ACT4_INPUT_ROOT，manual 为实际 ISA 根目录。
需要的规范原文可导入 references/，SV 定义与 norm 映射可导入 coverpoints/；不能只导入 `.S`
就凭空写映射。每个可交付功能都需实际测试、计划或生成器资产，不能只导入说明就声称实现。
来自 riscv-arch-test 时可把整个模块目录映射到相同位置；所有额外 include、incbin 数据、
共享汇编辅助文件也显式导入。保留资产原有版权与许可证。`framework_paths` 包含原生构建
所需源码及依赖描述，不选 `.venv`、历史 work/output 或编译产物；tests 下只选 `tests/env`。

只有生成器、没有 `.S` 时，导入模块生成器、计划及需要的公共资源，使用当前框架真实入口。
下面是另一个完整输入示例，生成命令适用于提供 `testgen` CLI 的框架；先查本次源码确认选项：

```yaml
schema_version: 1
suite: Timer
framework_paths:
  - README.md
  - pyproject.toml
  - uv.lock
  - framework
  - generators
  - tests/env
  - COPYING.APACHE
  - COPYING.BSD
  - COPYING.CC
framework_exclude:
  - generators/testgen/src/testgen/priv/extensions/Sstc.py
imports:
  - origin: local
    features: [timer-access]
    source: Sstc.py
    destination: generators/testgen/src/testgen/priv/extensions/Sstc.py
  - origin: local
    features: [timer-access]
    source: testplans
    destination: testplans
generation:
  - [uv, run, --frozen, testgen, testplans, -o, tests, --extensions, Sstc, --jobs, "1"]
```

上例展示用本地模块生成器替换隔离副本中的同名生成器；原始 ACT checkout 不修改。
framework_exclude 只允许明确列出的 testgen 文件，且每项必须有同目标的本地 import，
同时记录被替代文件的来源摘要。相同目标不能重复导入，也不能隐式覆盖其他框架文件。
更简单的方法是在输入准备阶段提供已经整合好的 ACT checkout，以其生成器作为
`framework_paths` 的一部分。不要在工作流中修改通用框架来迁就输入。

调用 `Check(stage_args={"action":"prepare"})` 复制所选内容。若声明了生成命令，再调用
`Check(stage_args={"action":"generate","timeout":1800})`。命令在 `bundle/act4/` 运行，
仅接受原生 `uv`、`python3`、`make` argv，不进行 shell 字符串展开。读取对应日志修复依赖；
仅执行已经阅读的可信生成器。输入目录不写入。生成不得重写已经导入的测试及共享文件；
已有 `.S` 时通常不运行生成器。

完成后读取 `input-inventory.json`，确认模块、源码列表与用户输入一致。若发现遗漏依赖，
补充 input.yaml，返回 handoff_inputs 再显式 prepare；旧副本和收据移入 previous-inputs 留存，
新快照重新执行后续阶段。普通 Check 不接受发生变化的输入。无 `.S`、空模块、
路径冲突、符号链接或输入内容变化都不能通过。普通 Check 不再次运行命令，随后 Complete。

## 2. 建立 V3 目标与选择范围

先从本次香山源码确定 commit、配置类和 SimTop 平台。不要把 V2 的 UDB、PMA、计时器或
中断宏直接改名为 V3；也不要假定配置类一定叫 `KunminghuV3Config`，某些 V3 checkout
使用 `DefaultConfig`。引用必须来自实际 checkout，且文件内容与其 Git 提交一致。

创建 `target.yaml`：`family` 固定为 `kunminghu-v3`，`commit` 是实际 HEAD，`top` 为 `SimTop`。
`configuration` 是存在于源码中的 Scala 类。`memory` 使用整数 base/size，描述交付 ELF 的
RAM 范围，与链接脚本和 Sail 测试内存对应。`allow_source_only` 默认 false；只有调查了实际
构建障碍，且明确愿意交付不可直接运行的源码时才改为 true，同时填写具体限制和恢复动作。

下面给出完整的格式示例。为便于展示，引用来自一个**说明格式用的微型源码仓库**，其
`src/Platform.scala` 共八行，内容依次是下面八条 quote；它不是实际香山路径，也不是已核实的
V3 硬件配置。执行任务时必须使用实际 V3 文件、行号、提交与推理，不能复制示例作为硬件依据。

```yaml
schema_version: 1
family: kunminghu-v3
commit: 511ca530d11f90d411264c6a074a65cdb3b3c887
configuration: DefaultConfig
top: SimTop
memory:
  base: 2147483648
  size: 268435456
allow_source_only: false
limitations:
  - No matching emulator is available locally; the design team must run the delivered ELFs.
decisions:
  configuration:
    reason: Select the single-hart SimTop configuration declared in the source.
    references:
      - path: src/Platform.scala
        lines: [1, 1]
        quote: class DefaultConfig
  isa:
    reason: Configure RV64 and Sstc; review all required dependencies before choosing tests.
    references:
      - path: src/Platform.scala
        lines: [2, 2]
        quote: val extensions = Seq("RV64", "Sstc")
  memory:
    reason: Link test code and data into the declared RAM window.
    references:
      - path: src/Platform.scala
        lines: [3, 3]
        quote: val testRam = (0x80000000L, 0x10000000L)
  boot:
    reason: The selected reset path reaches the ACT entry in RAM.
    references:
      - path: src/Platform.scala
        lines: [4, 4]
        quote: val bootTarget = 0x80000000L
  termination:
    reason: Pass and fail use a0 as the result operand for the simulation trap.
    references:
      - path: src/Platform.scala
        lines: [5, 5]
        quote: val simulationTrap = 0x0005006bL
  console:
    reason: Emit ACT selfcheck summaries through the simulated UART transmit register.
    references:
      - path: src/Platform.scala
        lines: [6, 6]
        quote: val uartTx = 0x40600004L
  timer:
    reason: Use the actual timer device and check its tick rate before choosing wait bounds.
    references:
      - path: src/Platform.scala
        lines: [7, 7]
        quote: val timerBase = 0x38000000L
  interrupts:
    reason: This example selects timer tests only; no external-interrupt stimulus is claimed.
    references:
      - path: src/Platform.scala
        lines: [8, 8]
        quote: val externalInterruptSource = "PLIC"
```

八个 decisions 全部保留。每项填写非空 reason 和至少一条 reference；每条 reference 包含
工作区香山根目录下的相对 path、包含首尾的 lines、与原文一致的 quote，单条不超过 100 行。
不适用的能力说明原因和来源。涉及子模块时保留实际子模块提交来源。机械检查验证出处和
文档完整性，不能代替你对硬件行为、规范与参数的语义核对。

在 `config/` 准备五个原生 ACT 文件：

| 文件 | 必须完成的工作 |
| --- | --- |
| `test_config.yaml` | 连接目标配置、编译器与 Sail，使用 PATH 命令名 |
| `udb.yaml` | 按当前 V3 实现声明 RV64、扩展、分页、PMP 等参数 |
| `sail.json` | 设置对应参考模型参数及测试内存；保留 Sail 签名流程所需专用设备 |
| `link.ld` | 保留 ACT 段布局，匹配入口、RAM、栈与签名数据地址，并保留非加载描述 note |
| `rvmodel_macros.h` | 实现启动补充、UART 摘要、PASS/FAIL 和本套测试需要的中断/故障接口 |

完整的 `test_config.yaml` 示例：

```yaml
name: xiangshan-kmhv3
compiler_exe: riscv64-unknown-elf-gcc
objdump_exe: riscv64-unknown-elf-objdump
ref_model_exe: sail_riscv_sim
udb_config: udb.yaml
linker_script: link.ld
dut_include_dir: .
harts: 1
include_priv_tests: true
```

参考模型始终是 Sail，不能填入 `emu`。成功退出与失败退出必须分别传递 0 和非零结果，
保留 ACT 自检之后才结束的顺序。不能复制旧 riscv-tests 的整套启动/异常代码覆盖 ACT 框架。
上述其他四个文件按输入 ACT 版本的原生契约编写，不提供未经核实的固定 V3 参数模板。
目标文件必须自包含，使用内联宏，不依赖生产机器绝对路径或目标目录之外的私有 header。

为输入清单中每个非 `tests/env` 的 `.S` 创建选择记录。完整 `selection.yaml` 示例：

```yaml
schema_version: 1
tests:
  - path: priv/Sstc/Sstc-00.S
    disposition: include
    reason: Exercises implemented Sstc behavior on the selected RV64 target.
```

path 相对隔离副本的 `tests/`。`include` 是预期产生一个最终 ELF 的测试；`support` 是被
其他汇编引用且位于原生不扫描的 `env` 目录中的帮助文件；`exclude` 是有明确目标不适用依据的测试。不能仅因失败或超时排除。
全部文件都要有记录，至少一个 include。include 源码须保留原生 START_TEST_CONFIG / END_TEST_CONFIG
元数据头。非签名测试只有该头中明确声明 `NEEDS_SIGNATURE: false`
时才不要求 Sail signature；普通测试默认要求完整签名流程。

调用 `Check(stage_args={"action":"adapt"})`，检查生成的 `bundle/build-plan.json`、
`target-evidence.json` 和隔离的 `selected-tests/`。修改目标后重新 adapt 会使旧构建、运行与
交付证据失效，必须重新 build；原始资产不变。不要直接编辑 bundle 内的冻结文件。

## 3. 构建与可选运行

环境阶段已复用或准备 uv、RISC-V 编译器和 Sail。构建在隔离副本中按锁文件同步 Python/UDB 依赖；
不得写入原始 checkout。不要引入商业工具依赖。完整构建调用：

```text
Check(stage_args={"action":"build","timeout":3600,"jobs":1})
```

它通过包内框架执行 `uv run --frozen act`，不调用 make 的自动再生成目标，避免覆盖输入 `.S`。
每次使用新的构建目录，不从旧输出挑选 ELF。构建会检查：

- 原生命令实际成功；每个 include 测试都有唯一的最终 ELF，没有多出或被静默过滤的测试。
- ELF 是 RV64 little-endian RISC-V 可执行文件，入口及加载段位于声明的 RAM 内。
- 最终 ELF 包含 ACT 成功/失败摘要与香山结束指令；不能交付 `.sig.elf` 作为自检用例。
- 普通测试有实际 Sail `.sig`、`.results` 和 `.sig.log`，构建输入未被修改。
- 同一最终 ELF 经匹配的 objcopy/objdump 导出非空 bin/disass；校验 bin 的加载范围并记录加载地址。

失败时查看 `bundle/build-result.json` 与其 log 字段。修复工具/依赖后重试；若配置错误，
修改源 `config/`、`target.yaml` 或 `selection.yaml`，再 adapt/build。不得手工修正签名、
修改测试主体、关闭断言或删除架构义务。即使本机最终只能交付源码，也必须保留真实构建尝试。

如果用户提供了现成匹配的香山 `emu`，按工作区内真实相对路径执行：

```text
Check(stage_args={"action":"run","emulator":"XiangShan/build/emu","timeout":14400,"cycles":20000000})
```

timeout 是本次动作的总墙钟预算，cycles 是每个 ELF 的周期上限；可用 StdCheck 查看当前命令
日志，KillCheck 会终止命令及其子进程，停止后先查看日志再重试。预算耗尽的用例明确列为
not_run。runner 使用 `-i ELF --no-diff -C N`，同时要求自检 PASSED 与 GOOD TRAP。
缺摘要、SIGRUN、BAD TRAP、非零退出、超时或周期上限都不能当作通过。失败也可以作为诊断交付，
保留日志并区分环境问题、模型差异、测试缺陷与可能的 RTL 缺陷。

没有 emu 则跳过 run。不能仅凭 ELF 编译或 Sail 通过声称已在香山验证；模拟器二进制摘要
用于复现，不自动证明它就是指定硬件提交。交付时明确要求设计人员确认其 commit/config/top。

## 4. 交付与摘要

执行 `Check(stage_args={"action":"package"})`，生成独立的 delivery/ 和相同内容的
`{DUT}-kunminghu-v3.tar.gz`。以下是完整交付布局示例，程序仍使用原 ACT 路径：

```text
handoff/
  Sstc-kunminghu-v3.tar.gz
  handoff-report.md
  handoff-report.json
  bundle/                         原始资产、构建日志、Sail 结果、执行证据，仅供交付方
  delivery/
    README.md                     唯一操作指南
    TESTS.md                      唯一测试索引和逐用例设计报告
    manifest.json                 脚本使用的文件摘要和构建参数
    Makefile
    handoff.py
    act4_driver.py
    src/priv/Sstc/example.S
    elf/priv/Sstc/example.elf
    bin/priv/Sstc/example.bin
    disass/priv/Sstc/example.disass
    config/
      test_config.yaml
      udb.yaml
      sail.json
      link.ld
      rvmodel_macros.h
    framework/                    必需的匹配 ACT 构建源码、宏、覆盖与规范定义
```

不向 delivery/ 或压缩包复制生产日志、signature、.results、中间 ELF、AI 生成记录、
重复原始测试源码、逐 ELF 报告、traceability.json 或其他审计收据；保留在 bundle/ 或插件输出。
许可证和构建必需的文件需要保留。source_only 不交付半成品 ELF/bin/disass。
归档按明确清单生成并在异目录核验，不依赖原工作区或 UCAgent。

TESTS.md 包含 ACT 程序总表、功能范围与缺口、每个 testcase 的设计、coverpoint 反向索引
和 norm rule 解释。功能分类不改变 ACT 的测试结构；静态映射不代表实测覆盖命中。
README 说明如何阅读索引、检查环境、批量或单程序编译运行、修改测试和定位失败。
报告中的运行状态只描述所提供 emu 的结果，不证明其硬件身份或完整手册覆盖。

接收方在包根目录执行：

```bash
make verify
make list
make doctor
make setup
make build TEST=priv/Sstc/example.S
make run TEST=priv/Sstc/example.S EMU=/path/to/matching/emu LOCAL=1
make run EMU=/path/to/matching/emu TIMEOUT=14400
```

TEST 是完整 ACT 程序路径；省略时选择全部程序，不接受内部 testcase/coverpoint ID 作为独立程序。
setup 复用匹配工具或按交付配方安装到 local/tools/，缺少基础命令、网络或平台不匹配时报告具体缺项。
运行交付 ELF 只需 Python 3.11+ 与匹配 emu，不需要 Sail、编译器、UCAgent 或商业模拟器。
接收方日志和构建中间结果进入 local/，新产物位于 local/elf、local/bin、local/disass。
默认运行原交付 ELF；LOCAL=1 只运行最新成功重建的选择，不回退到旧产物。

允许接收方修改 src/ 或 config/ 后使用 `make build TEST=... MODIFIED=1`。
重新生成 Sail 预期值，并标记原映射需复核；不能沿用旧运行结论，也不能修改 framework/。
整个 .S 中的 ACT 测试序列保持不变，不自动切割内部 testcase。构建后再次修改输入会阻止 LOCAL 运行。

交付状态为 source_only、built_not_run、emulator_passed 或 emulator_failed。
插件输出的 handoff-report.md/json 保留总结及审计入口，不再放入交付包形成重复报告。
没有匹配 emu 时可以交付 built_not_run，但必须向接收方说明尚未执行。

## 5. 逐用例设计、覆盖点与规范追溯

selection.yaml 填完后调用 `Check(stage_args={"action":"inventory"})`，读取 trace-inventory.json。
按原生 ACT 的 `_cg_` 测试标签枚举；无此标签时按 Testcase 注释边界枚举；无内部测试标记的
源文件视为一个 file 测试。遇到无法识别的生成器布局，先检查真实源码，不把多个独立测试
误说成一个，不用文件摘要替代各已枚举 testcase。声明每个 source 的全部 case ID，不能遗漏或重复。

在原始 `bundle/act4/tests/` 源码和导入的 coverpoints/references 上引用精确行号，创建
traceability.yaml。summary 是文件级目的；preconditions/setup/exercise/check/limitations 分别解释
前置条件、初始化、整体执行过程、结果判定和未覆盖范围，均为非空文本。不要只罗列指令，
应让读者知道如何构造状态、为何能够观察被测行为，以及失败如何反馈。
description/stimulus/expected 是每个测试的目的、
如何构造输入与观察预期结果。coverpoint intent 解释设计意图，不能只把 ID 换成自然语言。
例如写清“分别设置哪个控制位，在哪个特权级访问哪个 CSR，通过什么异常或读回值区分结果”。

以下是完整结构示例，其中 Fixture 是用于展示格式的合成资产，不是 ACT 上游规则；
生产任务必须替换为真实用例、SV 定义、norm 原文与逐字引文。假设导入源文件为：

```text
tests/priv/Fixture/one.S 的第 1 行：Fixture_cg_cp_zero_case0:
tests/priv/Fixture/one.S 的第 2 行：addi a0, zero, 0
coverpoints/priv/Fixture.svh 的第 1 行：covergroup Fixture_cg;
coverpoints/priv/Fixture.svh 的第 2 行：cp_zero: coverpoint value;
coverpoints/priv/Fixture.svh 的第 3 行：endgroup
references/rules.adoc 的第 1 行：[[fixture_zero]]
references/rules.adoc 的第 2 行：The fixture requires a zero result.
coverpoints/norm/Fixture.yaml 的第 1 行：normative_rule_definitions:
coverpoints/norm/Fixture.yaml 的第 2 行：  - name: fixture_zero
coverpoints/norm/Fixture.yaml 的第 3 行：    coverpoint: [Fixture_cg/cp_zero]
```

```yaml
schema_version: 1
rules:
  - id: fixture_zero
    description: 合成示例要求结果为零，仅用于格式展示
    definition:
      path: references/rules.adoc
      lines: [1, 2]
      quote: |-
        [[fixture_zero]]
        The fixture requires a zero result.
coverpoints:
  - id: Fixture_cg/cp_zero
    intent: 观察结果为零的取值，用于检验示例的零值路径
    group:
      path: coverpoints/priv/Fixture.svh
      lines: [1, 1]
      quote: covergroup Fixture_cg;
    definition:
      path: coverpoints/priv/Fixture.svh
      lines: [2, 2]
      quote: "cp_zero: coverpoint value;"
    rules:
      - id: fixture_zero
        kind: native_mapping
        reason: 示例映射文件明确将零值规则关联到该覆盖点
        evidence:
          path: coverpoints/norm/Fixture.yaml
          lines: [2, 3]
          quote: |2-
              - name: fixture_zero
                coverpoint: [Fixture_cg/cp_zero]
tests:
  - path: priv/Fixture/one.S
    summary: 合成示例设置零值结果，用于展示文件和逐测试说明格式
    preconditions: 本例只描述 RV64 汇编片段，完整交付必须具备 ACT 启动与检查环境
    setup: 使用恒为零的 x0，无需其他输入初始化
    exercise: 执行 addi 将零值写入 a0
    check: 观察 a0 是否为零；此片段本身没有完整自检，生产用例需解释实际检查机制
    limitations: 仅为格式示例，不声称验证真实定时器或完整 ACT 流程
    cases:
      - id: Fixture_cg_cp_zero_case0
        description: 使用零寄存器与零立即数构造零值结果
        stimulus: 执行 addi a0, zero, 0
        expected: a0 为零；生产用例还必须说明实际签名或断言机制
        coverpoints: [Fixture_cg/cp_zero]
        evidence:
          path: tests/priv/Fixture/one.S
          lines: [1, 2]
          quote: |-
            Fixture_cg_cp_zero_case0:
            addi a0, zero, 0
```

每个引用只取连续 1..100 行。每个 coverpoint ID 使用精确 `covergroup/coverpoint`，
group 引用实际组声明，definition 引用该组内或其 include 中的 coverpoint/cross 声明。
ACT 原生 testcase 标签可能使用模板名，而实际 SV 点名展开了 SEW 等参数。此时不修改标签：
映射必须仍在同一 covergroup，另外列入该组的 `cp_asm_count`，在 testcase 的 `evidence`
中引用实际执行的指令，并填写 `mapping_reason` 解释展开关系。`cp_asm_count` 的声明必须
明确匹配该指令；它仅证明指令执行的设计对应，不能替代专用场景的 bin 覆盖。
无法证明更细对应时只列指令计数点，并在 `mapping_reason` 和程序 limitations 中说明
专用映射缺口，不得仅凭名称相似声称命中专用覆盖点。
每个规则必须有规范原文和设计解释。native_mapping 会核对实际 norm YAML 里的规则/点名，
支持其 brace 和通配表达式。没有上游映射时只能在有真实 ISA 依据的情况下使用
`kind: isa_reasoned`，evidence 必须与该规则的 definition 相同，reason 说明推导关系。
不能虚构规则 ID、把 TODO 变成规则或把推导关系说成上游映射。无法建立关系就保留缺口，
不要把该用例作为已完成追溯的资产悄悄交付。

adapt 统一生成 traceability.json 与 selected-tests 的注释，保留原始 tests 字节不变。
文件顶部说明测试目的、前置条件、执行和检查过程、限制、涉及 coverpoints/norm rules；
每个 testcase 前写设计、激励和预期。保持原 ACT 的路径、标签和 testcase→coverpoint 关系，
不能按香山物理模块重命名、拆分用例。功能列表只作导航。
同一描述写入源码末尾的非加载 ELF note，链接脚本的 SECTIONS 中必须保留：

```ld
.note.ucagent.act4 0 : { KEEP(*(.note.ucagent.act4)) }
```

不要对该 note 添加 SHF_ALLOC，也不要在 `/DISCARD/` 中删除它。构建会读取最终 ELF note，
与冻结的文件说明逐项比较，不接受缺失或过期描述。note 不改变测试指令、断言或期望值。
ELF 开头保留二进制文件头，不能前置文字；不另附 `.elf.md`，设计说明统一在 TESTS.md 中查阅。
包内运行 `python3 handoff.py describe <包内ELF路径>` 可查看内嵌说明。

报告正文完整列出文件→testcase→coverpoint→norm rule，同时列出每个 coverpoint 的反向用例。
这表示测试的静态设计对应，不证明实际触发了所有 bins；模型执行和香山执行状态另外报告。
