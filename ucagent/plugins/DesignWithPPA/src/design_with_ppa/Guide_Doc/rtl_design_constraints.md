
# RTL 设计约束

当前阶段会直接给出唯一允许使用的 RTL 语言、编码规范和源码 glob。只编写该语言的 top 与
必要子模块；不要创建其他硬件语言的替代实现、构建脚本或生成产物。Python reference、API、
adapter、fixture、coverage 和 pytest 保持为测试侧代码。同一套测试由托管的验证运行时分别
执行 reference 与 RTL 实现，不维护两套激励和 expected。测试代码只使用统一的 `env`，不得
添加或读取实现选择参数。

源码必须满足 architecture 中冻结的 top、参数、端口、clock/reset、latency、handshake、
backpressure、非法输入和 CDC 合同，并能通过当前工作流的综合与测试。多文件设计的全部必要
子模块必须匹配当前源码 glob；只能引用 CurrentTips 列出的只读库目录，不能依赖未声明的
本机绝对路径或工作区外源码。

## 共同实现原则

- 组合逻辑必须对所有路径完整赋值，不产生意外 latch，也不依赖未初始化状态。
- 时序状态只在 architecture 声明的 clock/reset 事件更新；reset 极性、同步语义和默认值必须一致。
- 位宽、signedness、截断、扩展、舍入、饱和和溢出策略必须显式，不能依赖语言的隐式推断。
- transaction 接受、ready/valid、backpressure 和输出有效周期必须与 Python reference 一致。
- 不在可综合源码中放置 delay、force/release、文件 I/O、仿真终止任务或测试激励。
- 外部库实例使用稳定模块名、显式参数和显式端口；库内容只读。

当前语言的 `Guide_Doc/coding_standard_*.md` 是建议基线。当 Spec、外部 IP 合同或经过验证的
PPA 优化需要偏离时，可以在相关源码附近写一条 `RTL-GUIDE-DEVIATION` 注释，说明原因、
影响范围和验证依据。偏离不降低综合、功能回归、性能证据或 PPA 完整性要求。

## 源码注释建议

无论当前选择 Verilog、Chisel 还是后续接入的其他 RTL 语言，都建议让源码本身能独立说明设计
意图。每个源文件和主要模块/类应包含功能目的、总体数据流和组合/时序性质；每个参数和端口应
说明含义、方向、位宽、signedness、单位/编码、合法范围以及 valid/ready、backpressure 或
transaction 语义。clock/reset 相关代码前应说明边沿、极性、同步/异步语义、latency 和 stall
行为；核心组合或时序逻辑前应说明状态转移、数据通路、优先级、宽度转换、舍入/饱和/溢出、
特殊编码和非法输入策略。

注释是建议性可读性规范，不是独立的风格完成门禁，也不能替代 architecture、Python executable
spec、测试和 PPA 证据。注释必须与实际实现保持一致，不要求逐行翻译代码。若有合理的语言、
外部 IP 或 PPA 偏离，在实现附近记录 `RTL-GUIDE-DEVIATION`、原因、范围和验证依据。不要在
源码注释中描述中间语言、转换工具或内部工作流实现。

## 完整交付检查示例

下面是完成一个当前语言源码集合后应逐项满足的 canonical 检查记录。它用于自查，不需要另存文件。

```text
top: Adder
sources: all files match the CurrentTips source glob
libraries: only declared read-only library directories are referenced
ports: every architecture port has exact direction, width, and signedness
clock_reset: edges, polarity, synchrony, and reset values match architecture
transactions: acceptance, latency, backpressure, and valid timing match the Python reference
numeric_behavior: extension, truncation, rounding, saturation, and overflow are explicit
synthesis: no latch, delay, force/release, file I/O, or simulation-only task
tests: the shared Python tests pass through Check/Complete in RTL mode
deviations: every intentional coding-standard deviation has one local rationale comment
```

实现完成后调用 `Check`。按返回的首个具体源码位置修正当前语言代码；不要直接导入或运行
RTL DUT。Check 通过后再调用 `Complete`。
