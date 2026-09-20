
# SoftMax8

SoftMax8 是一个可综合、可验证的定点 SoftMax 单元。8 个 lane 打包在一个 64-bit transaction 中输入，每个 lane 是 8-bit 有符号 Q4.4 定点数；`mode_i` 选择两种归一化分组：向量模式（8 个 lane 一组）或矩阵模式（2×4 矩阵逐行归一化，两行各成一组）。它用于演示 DesignWithPPA 的单元模块 TDD 工作流在查找表 + 归一化运算场景下的能力：工作流读取本 README 和 `spec/` 下的设计规格，在解析后的 `{OUT}` 中动态生成 Python 可执行规格、同套功能测试、选定语言的电路源码、性能测试波形、PPA 报告和版本性能曲线。

本目录是只读设计输入。请勿在此目录写入 RTL、Python 测试、波形、sidecar、PPA 报告、账本或工作流过程文档；这些产物必须落在 `{OUT}`。工作流应自动完成组合/时序性质判断，不要求使用者声明设计类型。

## 设计目标

对输入向量/矩阵计算定点 SoftMax：先在组内求最大值并做 max 减法（`d = x_max - x_i`，整数 code 距离），再经 256 项指数查找表得到 `e`（满量程 1024），组内求和 `S` 后用纯整数公式 `p = floor((e × 65535 + floor(S/2)) / S)` 归一化，输出每个 lane 的 Q0.16 概率（满量程 65535 表示 1.0）。所有运算都是确定性整数运算，不含浮点舍入歧义。

Python reference 不是 mock：必须实现 Q4.4 解码、组内 max 减法、与规范逐项一致的 256 项 exp 查找表、整数归一化以及 reset 和握手状态机。RTL 与 reference 的结果必须逐 lane 一致。

### 打包与 normative 参考向量

lane `k` 是 `x_i` 的第 `k` 个 byte（lane 0 在最低 byte，小端），其概率在 `p_o` 的 bits `[16k+15:16k]`。Q4.4 编码：`0x00`=0.0、`0x7f`=+7.9375、`0x80`=-8.0、`0xf0`=-1.0。

- 向量全零：`x=0x0000000000000000`，组内 8 个 `e` 均为 1024，`S=8192`，每个 lane `p=0x2000`（8192），组内和为 65536。
- 向量 `[0,-1,-2,-3,-4,-5,-6,-7]`：`x=0x00f0e0d0c0b0a090`，`e=[1024,377,139,51,19,7,3,1]`，`S=1621`，`p=[0xa1b7,0x3b8a,0x15f4,0x080e,0x0300,0x011b,0x0079,0x0028]`，组内和为 65535。
- 向量 `[+7.9375,-8.0,-8.0,-8.0,-8.0,-8.0,-8.0,-8.0]`：`x=0x7f80808080808080`，最大 lane 的 `e=1024`、其余 lane `d≥122` 查表为 0，`S=1024`，`p=[0xffff,0,0,0,0,0,0,0]`，这是输出饱和到 65535 与下溢 lane 归零的 normative 例子。
- 矩阵模式（`mode_i=1`）：`x=0x0000000000f0e0d0`，row 0 = `[0,0,0,0]` 得 `p=[0x4000,0x4000,0x4000,0x4000]`，row 1 = `[0,-1,-2,-3]` 得 `p=[0xa4c4,0x3ca9,0x165e,0x0835]`；两行各自独立归一化，行和各为 65536。

这些向量是 normative examples；生成的 smoke 测试必须按规范公式手工推导 expected，不能读取 DUT 输出后再赋给 `expected`。不要把 `0x2000200020002000...` 之类按 16-bit 重复的模式当作概率打包——概率 lane 位于 `p_o` 的 `[16k+15:16k]`，不是 byte 打包。

## 工作流运行

在包含本案例目录的 workspace 中，使用 `SoftMax8` 作为 DUT 名称，并选择 `DesignWithPPA` 插件的 `unit-design-tdd` 工作流（或 `make run CASE=SoftMax8`）。默认至少尝试 5 个候选优化版本；可通过 `DESIGN_WITH_PPA_MIN_OPTIMIZATION_ITERATIONS` 设置最少轮数，通过 `DESIGN_WITH_PPA_MAX_OPTIMIZATION_ITERATIONS` 设置默认 1000 轮的安全上限，并通过 `DESIGN_WITH_PPA_NO_IMPROVEMENT_PATIENCE` 设置默认 3 次的连续无改善容忍次数。候选接受门禁默认只要求 performance 与 timing 两类指标不回退，即在不降低性能与频率/时序的前提下尽可能优化面积与功耗；可通过 `DESIGN_WITH_PPA_NO_REGRESSION_METRICS` 指定逗号分隔的类别子集（可选 performance、area、timing、power，设为全部四类即要求所有指标都不回退，设为空表示不设无回退保护，仅需至少一项指标改善即接受）。版本 0 是功能全通过的 base，后续 accepted/rejected 版本和相对 base 的改善曲线由工作流自动写入 `{OUT}`。

工作流最后应至少交付：

- 可综合的电路源码和完整功能回归通过的同套 Python/RTL 测试；
- 向量/矩阵两种模式各自的 latency/throughput 性能 TC、独立波形和 sidecar；
- 可追溯的性能合同、base/final PPA 和每个评估版本的优化账本；
- `{OUT}/SoftMax8_performance_curve.json` 与 `{OUT}/SoftMax8_ppa_dashboard.html`，看板直接从 JSON 绘制两种模式的性能以及 area、timing、power 的版本变化。

## 输入与输出边界

输入仅包括本 README 和 `spec/*.md`。所有生成文件写入 `{OUT}`；不得修改、删除或创建 `{DUT}` 下的文件。Spec 的物理行必须映射到 FG/FC/CK 或有理由的 `IGNORE`，性能指标必须在性能合同中保留 Spec 路径与行号。
