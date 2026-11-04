
# 香山 Kunminghu V3 资产交付

`xiangshan-v3-handoff` 接受香山模块名及用户描述，例如向量模块 `Vector`、访存模块 `LSU`。
工作流自行分析该模块的架构可观察功能，映射到一个或多个 ACT suite 或其中的具体部分，
优先复用 riscv-arch-test 的现成资产，再考虑本地补充和缺口生成。
最终输出带设计说明、逐用例 coverpoint/norm rule 追溯关系的 `.S` 与自检 ELF。
目标为 Kunminghu V3 单 hart SimTop 整核环境，不能把 ELF 直接作为独立向量、CSR 或 LSU 接口 testbench。

## 启动与输入

按 [插件安装说明](../README.md) 安装后，只需指定香山模块，不必提前知道 ACT suite 名：

```bash
ACT4_WORKSPACE="$PWD/output/xiangshan-Vector"
mkdir -p "$ACT4_WORKSPACE"
ucagent "$ACT4_WORKSPACE" Vector \
  --plugin act4-privileged-suite \
  --plugin-workflow act4-privileged-suite:xiangshan-v3-handoff \
  --output act4_xiangshan --backend langchain --tui
```

在任务描述中说明希望覆盖的功能和已知目标约束。向量模块不会直接等同于 Vx：工作流应检查
整数、浮点、访存及适用的状态/异常相关资产，并逐项说明选择、排除和未交付内容。

可提供以下工作区相对目录，已有输入保持只读且不自动切换提交：

| 设置 | 默认目录 | 用途 |
| --- | --- | --- |
| `ACT4_FRAMEWORK_ROOT` | `riscv-arch-test` | 优先检索的上游 ACT 资产和匹配构建框架 |
| `ACT4_INPUT_ROOT` | `riscv-arch-test` | 可选本地补充资产目录 |
| `ACT4_XIANGSHAN_ROOT` | `XiangShan` | Kunminghu V3 源码及目标依据 |
| `ACT4_MANUAL_ROOT` | `riscv-isa-manual` | norm rule 原文及新 suite 生成规范 |

默认 checkout 缺失时，`fetch` 将其下载到输出的 `handoff/repositories/` 内；实际位置记录在
`acquisition-paths.json`。显式指定但缺失的非默认目录会报错，不擅自替换用户版本。
需联网下载时保留失败日志；可提供完整本地 checkout 后重新运行。输入和输出目录不得重叠。

本地补充示例：设置 `ACT4_INPUT_ROOT=local-assets/vector`，其余启动参数不变。
即使提供本地资产，也先检查上游，只有明确的缺口才使用补充内容。

## 流程

| 阶段 | 工作 |
| --- | --- |
| handoff_scope | 准备源码、分析香山模块、检索 ACT，冻结逐功能范围和缺口 |
| prepare_environment | 根据实际选定输入准备构建依赖，复用兼容软件 |
| handoff_inputs | 混合导入上游/本地资产；必要时调用隔离的生成子流程；执行原生 testgen |
| handoff_target | 核对 V3 配置，逐个选择 `.S`，建立逐 testcase→coverpoint→norm rule 关系 |
| handoff_build | 构建带说明的自检 ELF；有匹配 emu 时运行 |
| handoff_delivery | 精简交付目录，输出操作指南、ACT 测试索引及构建运行资产，异目录核验 |

上游只有生成器而没有 `.S` 时，运行已有原生生成器即可，不启动 AI 重新设计。
真正的缺口才调用现有 `privileged-suite-generation`：在独立 clone 中创建新 privileged suite，
必须满足其 CTP/Sheet、规范和全部验收条件。该生成工作流不支持任意 unprivileged 新套件或
覆盖已有 suite；这种缺口以及微架构场景应明确列为 unavailable。不能通过删改生成门槛伪装已补全。
生成子流程需要已配置的模型后端及额度；生成和 review 工作流自身的契约不变。

## 报告与文件说明

最终目录为 `<OUT>/<香山模块>/handoff/delivery/`，压缩包为同级的 `<模块>-kunminghu-v3.tar.gz`。
包内仅保留两个人工阅读入口：`README.md` 操作指南与 `TESTS.md` 测试索引。
指南说明环境准备、批量/单程序编译运行、修改后重建、阅读报告和定位失败；索引提供程序总表、
逐 testcase 设计、coverpoint 反向关系和 norm rule 解释，功能范围与缺口仅用于导航。

保留原 ACT suite 路径、testcase 标签与 covergroup/coverpoint 标识，不按香山物理模块重组测试。
`src/`、`elf/`、`bin/`、`disass/` 按相同相对路径对应，目标文件放 `config/`，构建依赖放 `framework/`。
源码顶部解释前置条件、初始化、执行、检查方式及限制；各 testcase 前说明激励和预期。
ELF 保留非加载的 `.note.ucagent.act4`，用 `python3 handoff.py describe <包内ELF路径>` 读取。

不另交付逐 ELF 报告、原始源码副本、日志、signature、中间 ELF、AI 记录或追溯收据。
这些证据保留在插件输出的 bundle/ 和 handoff-report.md/json；脚本必需的参数与文件摘要合并在 manifest.json。
静态映射区分上游原生关系和 ISA 推导关系，不代表实测 coverpoint/bin 命中或完整手册覆盖。
原生 testcase 标签与参数展开后的 SV 点名不一致时，保留标签并记录映射说明；若只能核实
同一指令组的 `cp_asm_count`，报告明确标出专用覆盖关系尚未核实，不把指令计数当作专用场景覆盖。

```bash
make verify
make list
make doctor
make setup
make build TEST=priv/Sstc/example.S
make run TEST=priv/Sstc/example.S EMU=/path/to/matching/emu LOCAL=1
```

TEST 使用实际 `make list` 中的完整 ACT 程序路径。省略 TEST 为批量操作；不将内部 coverpoint
或 testcase 截成独立程序。setup 复用兼容工具或安装到 local/tools/，仍需满足网络与宿主机条件。
重建按原生 ACT 流程重新生成 Sail 参考结果，同时生成 ELF/bin/disass。
接收方新增日志、中间文件和构建产物均位于 local/；LOCAL=1 只运行最新成功重建，默认运行原交付 ELF。
修改 src/ 或 config/ 后使用 `make build TEST=... MODIFIED=1`，原设计映射和执行证据失效并明确标记需复核。

运行现成 ELF 需要 Python 3.11+ 和匹配 emu，不需要 UCAgent、Sail 或商业仿真器。
状态严格区分 `source_only`、`built_not_run`、`emulator_passed`、`emulator_failed`。
没有 emu 时可以交付，但必须说明尚未运行 RTL。环境规则见 [环境说明](environment.md)，
完整产物格式见 [运行指南](../src/act4_privileged_suite/Guide_Doc/ACT4_XiangShan_Handoff_Guide.md)。
