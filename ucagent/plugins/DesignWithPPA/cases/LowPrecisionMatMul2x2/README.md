
# LowPrecisionMatMul2x2

LowPrecisionMatMul2x2 是一个可综合、可验证的 2×2 低精度浮点矩阵乘法单元。它用于演示 DesignWithPPA 的单元模块 TDD 工作流：工作流读取本 README 和 `spec/` 下的设计规格，在解析后的 `{OUT}` 中动态生成 Python 可执行规格、同套功能测试、选定语言的电路源码、性能测试波形、PPA 报告和版本性能曲线。

本目录是只读设计输入。请勿在此目录写入 RTL、Python 测试、波形、sidecar、PPA 报告、账本或工作流过程文档；这些产物必须落在 `{OUT}`。工作流应自动完成组合/时序性质判断，不要求使用者声明设计类型。

## 设计目标

实现 `C = A × B`，其中 `A`、`B` 和 `C` 都是 2×2 矩阵。每个元素使用统一的 8-bit packed 编码，`precision_i` 选择两种有限浮点格式：FP4（E2M1，有效载荷低 4 bit）或 FP8（E4M3，有效载荷 8 bit）。输入矩阵在一个 transaction 中锁存，单元在规定的时序窗口内产生完整结果并报告完成。

FP4 与 FP8 必须共享同一外部 transaction 合同和可复用测试 API。Python reference 不是 mock：必须实现格式解码、有限值乘加、累加、舍入/饱和策略以及 reset 和握手状态机。RTL 与 reference 的结果必须逐元素一致。

### Packed-vector reference example

FP4 的 magnitude code 是一个直接查表：`000->0`、`001->0.5`、`010->1`、
`011->1.5`、`100->2`、`101->3`、`110->4`、`111->6`；bit 3 是 sign。每个矩阵元素
占一个 8-bit byte，element 0 在最低 byte，顺序为 `[m00, m01, m10, m11]`。因此
`1.0` 使用 byte `0x02`，`-1.0` 使用 byte `0x0a`，`2.0` 使用 byte `0x04`。
例如 `A=[[1,0],[0,0]]` 的输入是 `0x00000002`，而不是把 nibble 或 byte 索引
重复到高位。独立的 smoke expected 必须按此表和 `C[i][j] = A[i][0]*B[0][j] +
A[i][1]*B[1][j]` 手工推导，不能读取 DUT 输出后再赋给 `expected`。

边界测试也必须按相同的低字节优先规则打包。可复用的确定性向量为：取消使用
`A=0x00000a02`（`[m00=+1,m01=-1,m10=0,m11=0]`）和
`B=0x00020002`（`[m00=+1,m01=0,m10=+1,m11=0]`），因此 `C` 的四个累加值均为
零且 `zero_kind` 为 `cancellation`；负下溢使用 `A=0x00000009`
（`m00=-0.5`）和 `B=0x00000001`（`m00=+0.5`），`c00=-0.25` 在 ties-to-even
规则下编码为负零 byte `0x08`，并将 `zero_kind` 标记为 `negative_underflow`。
不要把 `0x02020002` 或 `0x80000000` 当作这两个向量，它们分别把非零值放在
不同的矩阵元素或直接表示输入负零。

## 工作流运行

在包含本案例目录的 workspace 中，使用 `LowPrecisionMatMul2x2` 作为 DUT 名称，并选择 `DesignWithPPA` 插件的 `unit-design-tdd` 工作流。默认至少尝试 5 个候选优化版本；可通过 `DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS` 设置最少轮数，通过 `DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS` 设置默认 1000 轮的安全上限，并通过 `DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE` 设置默认 3 次的连续无改善容忍次数。候选接受门禁默认只要求 performance 与 timing 两类指标不回退，即在不降低性能与频率/时序的前提下尽可能优化面积与功耗；可通过 `DESIGN_WITH_PPA_NO_REGRESSION_METRICS` 指定逗号分隔的类别子集（可选 performance、area、timing、power，设为全部四类即要求所有指标都不回退，设为空表示不设无回退保护，仅需至少一项指标改善即接受）。版本 0 是功能全通过的 base，后续 accepted/rejected 版本和相对 base 的改善曲线由工作流自动写入 `{OUT}`。

工作流最后应至少交付：

- 可综合的电路源码和完整功能回归通过的同套 Python/RTL 测试；
- FP4、FP8 各自的 latency/throughput 性能 TC、独立波形和 sidecar；
- 可追溯的性能合同、base/final PPA 和每个评估版本的优化账本；
- `{OUT}/LowPrecisionMatMul2x2_performance_curve.json` 与 `{OUT}/LowPrecisionMatMul2x2_ppa_dashboard.html`，看板直接从 JSON 绘制 FP4/FP8 性能以及 area、timing、power 的版本变化。

## 输入与输出边界

输入仅包括本 README 和 `spec/*.md`。所有生成文件写入 `{OUT}`；不得修改、删除或创建 `{DUT}` 下的文件。Spec 的物理行必须映射到 FG/FC/CK 或有理由的 `IGNORE`，性能指标必须在性能合同中保留 Spec 路径与行号。
