
# npu_pe_core

实现可综合的 FP4 / FP8 块缩放矩阵乘加模块 `npu_pe_core`，完成功能验证与 PPA 优化。默认计算一个 4×4 输出 tile，支持 E2M1、E4M3FN、E5M2、E8M0 块缩放以及 FP32 输出。在保持数值和接口合同不变的前提下，探索吞吐、延迟、频率、面积与功耗的取舍。

将本 README 和 `spec/*.md` 作为只读设计输入。所有生成文件写入当前任务指定的 `{OUT}`，不得在本目录创建、修改或删除文件。本 case 不提供外部 RTL 库。

## 阅读顺序与验收范围

依次阅读下列规格，提取可从顶层引脚验证的功能与性能要求，再设计架构和测试。

| 文件 | 内容 |
|---|---|
| [设计规格](spec/01_design_specification.md) | 功能范围、精确数值规则、参数与实现自由度 |
| [接口与时序](spec/02_interface_and_timing.md) | 配置寄存器、原子输入包、结果行输出和复位 |
| [功能验证](spec/03_functional_verification.md) | 独立参考模型、同套测试、边界与参数化验证 |
| [性能与优化](spec/04_performance_and_optimization.md) | 确定性 workload、性能计量和版本证据 |

强制功能包括五种 FP4/FP8 格式组合、32 元素块缩放、K=1..4096、FP32 结果、Bias、Bypass/ReLU/ReLU6、尾块和反压。GELU/SiLU、低精度输出、DFT、FPGA 上板等属于扩展，具体范围以主规格为准。

主规格中的微架构是参考。4×4 表示输出形状，不强制实例化 16 个物理 PE；每个输入字包含 4 个 FP8 或 8 个 FP4 元素，不强制相同的物理计算并行度。可以探索不同数据流、流水深度、资源复用、缓存、精确归约结构和低功耗策略，但不能改变公共接口、舍入规则、特殊值语义或测试 workload。

所有测试的可见 DUT 输入输出仅限 [接口与时序](spec/02_interface_and_timing.md) 的顶层引脚表。Python reference 必须提供相同的引脚、位宽和握手语义；测试 API 只能通过这些引脚驱动和读取 DUT。内部寄存器、层次路径、调试信号或 Python 私有状态不能成为 expected、通过条件或性能计数来源。端口表是固定合同，内部 RTL 文件组织不改变测试边界。

## RTL 文件组织建议

按“一个独立功能一个文件”组织电路源码，顶层负责模块连接与必要的控制协调。独立功能应有清晰接口；不要把配置、浮点运算、数据搬运和完整阵列控制全部堆在一个文件中。相同功能通过多次实例化复用，不要为每个 PE 或 lane 复制源码。

以下为 Verilog 模式的建议文件，位置均在 `{OUT}/rtl/`。除公共顶层 `npu_pe_core` 外，文件名、内部模块名及具体拆分允许随选定架构调整；不适用的参考功能无需建立空模块。

| 建议文件 | 独立职责 |
|---|---|
| `npu_pe_core.v` | 唯一公共顶层，连接配置、数据路径、控制和输出 |
| `pe_config_regs.v` | 配置读写、复位值、合法性判定和事务配置快照 |
| `pe_tile_controller.v` | start/busy/done 生命周期、输入计数、块边界与事务取消 |
| `pe_input_buffer.v` | 原子输入包缓存、ready/valid 和尾 lane 标记 |
| `pe_operand_decode.v` | E2M1/E4M3FN/E5M2 精确解码与特殊值分类 |
| `pe_product.v` | 低精度精确乘积及 NaN/Inf/零的乘法语义 |
| `pe_block_reduce.v` | 单个输出元素的块内精确归约 |
| `pe_block_scale.v` | E8M0 指数调整、scale bypass 与 NaN scale 处理 |
| `pe_fp32_round.v` | 精确有限值到 FP32 的 RNE、subnormal、溢出及零编码 |
| `pe_fp32_add.v` | FP32 加法，用于跨块累加和 Bias，可实例化或分时复用 |
| `pe_accumulator.v` | 各输出元素的有序块累加状态与 FP32 加法调度 |
| `pe_activation.v` | Bypass/ReLU/ReLU6 及对应 NaN/Inf 行为 |
| `pe_output_buffer.v` | FP32 结果保存、行序号和输出反压保持 |
| `pe_array.v` | 选用阵列结构时的计算单元连接、广播或脉动路由 |
| `pe_delay_line.v` | 选用脉动结构时的数据与元数据同步延迟 / 停顿 |

流水级和独立功能不是同一个概念：一个功能可包含多级流水，同一个加法功能可供多个调用方使用；无需机械地每一级建一个文件。算术融合或专用化可以调整边界，但应在生成的架构文档中说明职责和验证方式，保持可单独理解的功能模块。

Chisel 模式按相同职责划分 `.scala` 文件，类名可采用 `PeBlockReduce` 等命名，导出的顶层仍为 `npu_pe_core`。由工具导出的 Verilog 文件布局不要求与手写 Scala 一一对应。两个语言模式都需使实际源码清单覆盖所有子模块。

## 执行要求

1. 按规格建立功能检查点与行映射，在架构文档中记录公共引脚、参数、数值语义、实现选择和有限时序上界。参考结构不应转成额外验收条件。
2. 建立独立的位精确 Python reference 和仅经顶层引脚交互的共享测试 API，先验证独立数值向量、协议和边界行为。
3. 使用当前任务指定的 Verilog 或 Chisel 实现电路，在 Python reference 与 RTL 上执行同套功能测试，全部通过后建立 base。
4. 按 `spec/04_performance_and_optimization.md` 测量固定 workload，提出并验证候选。遵循当前任务已确定的优化轮数和接受策略，记录每轮改善与代价，最终交付最后一个 accepted 版本。

## 交付要求

- 参数化、可综合的 Verilog 或 Chisel 源码，以及解释实现选择的架构合同。
- 位精确 Python reference、仅经公共引脚交互的共享 API、同套功能测试与通过证据。
- FP4/FP8 的短 K 延迟、长 K 吞吐及零块 workload，各自独立的 RTL 波形和 sidecar。
- 源码、测试和 workload 可追溯的 base / candidate / final PPA 报告与优化账本。
- `{OUT}/npu_pe_core_performance_curve.json`、`{OUT}/npu_pe_core_ppa_dashboard.html` 和最终设计说明。

生成结果必须区分已测量数据、理论上限和估算，不能把参考工艺预算或参考结构的峰值算力作为验收结果。
