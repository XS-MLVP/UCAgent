
# Chisel 7 编码建议规范

本规范用于 DesignWithPPA 工作流选择 `chisel` 作为 RTL 源语言时的实现。目标是让设计语义明确、可综合、容易用同一套 Python/RTL UT 验证，并在多轮 PPA 优化中保持可比较。它是建议规范，不作为强制风格门禁：应优先遵循；当设计 Spec、外部 IP、目标技术或实测 PPA 需要其他写法时，可以有意偏离，并在源码附近使用 `RTL-GUIDE-DEVIATION` 说明理由、范围和验证依据。偏离不会降低功能、综合、性能或 PPA 门禁。

## 固定语言合同

当前后端固定使用以下相互匹配的版本：

- Chisel `7.15.0`；
- Scala `2.13.18`。
- JDK `17` 或更新的兼容 JDK，推荐 JDK 17。

Chisel 大版本间 API 和编译插件不保证兼容。源码只按本合同编写，不复制旧版 Chisel 或 Scala 3 示例。工作流管理构建环境；不要在 `{OUT}/rtl` 创建构建脚本、依赖描述、生成器命令或编译产物。

顶层必须是无 Scala `package` 的、零构造参数的 `class`，类名逐字匹配 architecture 的 `top_module`。顶层可继承 `Module` 或 `RawModule`。需要参数化时，顶层内部用固定常量实例化带参数的子模块；顶层端口和参数语义仍必须在 architecture 中锁定。

配置的只读 Chisel 库目录会递归提供 `.scala` 源码。可以 `import` 其中稳定的 package、Bundle 或 Module API，但不得修改、复制或用 Scala 文件 I/O 读取库目录。使用的库模块、参数和接口假设应记录在 architecture 或设计总结中；库内容由工作流哈希绑定，建立 PPA base 后不得切换库版本。

## 注释结构（建议）

注释用于让接口、时序和数值意图在 Chisel elaboration 与后续优化中保持可读；它是建议规范，不是独立的 Checker 门禁，也不能替代 Python executable spec、UT 或 PPA 证据。每个主要 Scala 源文件和 Module 建议包含：

- 文件或 ScalaDoc 模块说明：功能目的、总体数据流、组合/时序性质，以及本模块不负责的边界。
- `class`/构造参数说明：参数含义、单位、合法范围、默认值和对生成硬件资源、latency 的影响。
- 每个 IO/Bundle 字段说明：方向、`Bool`/`UInt`/`SInt` 类型和明确位宽、signedness、单位或编码，valid/ready 与 transaction 语义。
- 时序说明：隐式或显式 clock/reset 的边沿、极性、同步/异步语义、寄存级数、stall 行为和响应周期。
- 核心逻辑说明：在 `when`、`Mux`、`switch`、乘加/转换和状态寄存器前说明数据流、优先级、状态转移、宽度变化、舍入/饱和/溢出、特殊编码和非法输入策略。
- 偏离说明：为 Spec、外部 IP 或 PPA 有意偏离时，在源码附近写 `RTL-GUIDE-DEVIATION`，注明原因、范围和验证依据。

推荐的最小 ScalaDoc/代码结构如下。注释必须与真实 IO、clock/reset 和硬件语义同步，不要求逐句翻译每一行代码，也不要在注释中描述任何中间语言或内部构建过程：

```scala
/**
  * Module: Example
  * Purpose: one-sentence function and dataflow.
  * Interface: describe every IO direction, type, width, signedness, and protocol field.
  * Timing/reset: clock edge, reset polarity/synchrony, latency, and stall behavior.
  * Numeric behavior: encoding, width conversion, rounding, saturation, and invalid inputs.
  */
class Example extends Module {
  // Core datapath: explain the non-obvious operation immediately before the hardware code.
}
```

## 基础类型和端口

- `Bool()` 表示单 bit；`UInt(width.W)` 表示无符号向量；`SInt(width.W)` 表示二补码有符号向量。
- 使用 `IO(Input(...))`、`IO(Output(...))` 定义叶子端口，或使用一个命名清楚的 `Bundle`。端口名、方向、位宽和 signedness 必须与 architecture 一致。
- `Module` 自动具有隐式 `clock` 和 `reset`；只有 architecture 确实需要该时钟/reset 合同时才使用。纯组合顶层建议继承 `RawModule` 并只声明功能端口。
- `RawModule` 不提供隐式时钟/reset。需要状态时显式声明 `Clock`、`Reset`、`Bool` reset 或 `AsyncReset` 端口，并用 `withClockAndReset` 包围寄存器定义。
- 聚合类型用 `Bundle` 和 `Vec` 表达固定结构。公开端口若使用聚合，必须在 architecture 中逐字段锁定扁平化后的含义。
- 避免 `Analog`、`attach` 和内部三态。只有明确外部 pad/IP 合同时才使用，并记录偏离。

```scala
import chisel3._

class Request(val width: Int) extends Bundle {
  val valid = Bool()
  val opcode = UInt(2.W)
  val payload = UInt(width.W)
}

class CombinationalSelect extends RawModule {
  val select_i = IO(Input(Bool()))
  val lhs_i = IO(Input(UInt(8.W)))
  val rhs_i = IO(Input(UInt(8.W)))
  val result_o = IO(Output(UInt(8.W)))

  result_o := Mux(select_i, lhs_i, rhs_i)
}
```

## 位宽、字面量和推导

- 数据通路、寄存器、memory 元素和公开端口显式写宽度，例如 `UInt(8.W)`、`0.U(8.W)`、`(-1).S(8.W)`。
- 不依赖 Scala `Int`、`Long` 或无宽度 Chisel literal 在复杂表达式中的隐式扩展。常量参与硬件运算时使用 `.U(width.W)` 或 `.S(width.W)`。
- Chisel 的 `+` 返回与最大输入宽度相同的结果；需要进位时使用 `+&`，希望明确截断时使用 `+%` 并在代码中体现结果选位。
- `*`、动态移位和拼接可能扩大结果。给中间结果声明所需宽度，并显式截断、舍入、饱和或符号扩展。
- `getWidth`、`widthOption` 和 Scala 反射不应用来猜测功能位宽。宽度来自 Spec、architecture 或显式构造参数。
- 任何可能产生零宽度、负宽度、空 `Vec`、除零或非法索引的参数在 Scala elaboration 条件中先验证。

```scala
val lhs = Wire(UInt(8.W))
val rhs = Wire(UInt(8.W))
val sumWithCarry = Wire(UInt(9.W))

sumWithCarry := lhs +& rhs
val truncated = sumWithCarry(7, 0)
val carry = sumWithCarry(8)
```

## Signed 算术和比较

- 只有二补码数据使用 `SInt`。不要让 `UInt` 与 `SInt` 在同一表达式中依赖隐式类型变化。
- 用 `.asSInt` 或 `.asUInt` 改变解释时，先确认源宽度正确；这些转换不自动完成数值饱和或重新编码。
- 符号扩展应通过目标宽度的 `SInt` wire 或明确拼接完成。比较前对齐宽度和 signedness。
- 算术右移对 `SInt` 使用 `>>`；逻辑右移对 `UInt` 使用 `>>`。不要用转换顺序掩盖所需的符号语义。
- 定点、浮点、舍入、NaN、饱和和异常策略必须由 Python executable spec 与 CK 明确定义，不能由 Scala/Chisel 默认行为决定。

```scala
val lhs = IO(Input(SInt(8.W)))
val rhs = IO(Input(SInt(8.W)))
val result = IO(Output(SInt(9.W)))

val lhsExtended = Wire(SInt(9.W))
val rhsExtended = Wire(SInt(9.W))
lhsExtended := lhs
rhsExtended := rhs
result := lhsExtended + rhsExtended
```

## Wire 和寄存器

- `Wire(type)` 用于需要明确类型或多处分支赋值的组合节点；创建后必须在所有路径赋值。
- `WireDefault(value)` 适合给组合结果一个明确默认值，再在条件分支覆盖。
- `Reg(type)` 没有 reset 初值，只能在 valid/状态合同保证其值被写入后才可观察时使用。
- `RegInit(value)` 定义 reset 后的确定值；宽度应由显式 literal 或类型确定。
- `RegNext(next, init)` 适合单级延迟；复杂 enable、stall 或多字段 transaction 更适合显式寄存器和 `when`。
- 同一硬件节点应有一个清楚的所有者。避免跨多个逻辑块对同一 `Wire` 或寄存器使用最后连接语义形成隐蔽优先级。

```scala
val nextState = WireDefault(stateReg)
when(clear_i) {
  nextState := 0.U
}.elsewhen(enable_i) {
  nextState := stateReg +% 1.U
}
stateReg := nextState
```

## 条件、选择和完整赋值

- 使用 `when`、`.elsewhen`、`.otherwise` 表达互斥/优先级条件。组合输出先给默认值，保证所有路径赋值。
- `switch`/`is` 适合 opcode/FSM 分支；保留一个安全默认值处理非法编码。
- 二选一使用 `Mux(condition, trueValue, falseValue)`。
- 优先条件列表使用 `MuxCase(default, Seq(cond -> value, ...))`，列表前项优先。
- 查表使用 Chisel 7 的 `MuxLookup(key, default)(Seq(key -> value, ...))` 柯里化形式。
- 不依赖多个无关 `when` 的最后连接顺序，除非优先级是有意的并有 CK 覆盖。

```scala
import chisel3.util.{MuxCase, MuxLookup}

val selected = MuxLookup(opcode_i, 0.U(8.W))(Seq(
  0.U -> lhs_i,
  1.U -> rhs_i,
  2.U -> (lhs_i ^ rhs_i)
))

val priority = MuxCase(0.U(8.W), Seq(
  urgent_i -> urgent_data_i,
  normal_i -> normal_data_i
))
```

## Module、层次与参数

- 一个文件通常包含一个主要模块及其紧密相关的 `Bundle`；大型子模块放入独立 `.scala` 文件。
- 子模块用 `Module(new Child(...))` 实例化；端口逐项连接并保持方向清晰。
- 参数使用不可变 Scala 构造参数，并在类体开头用 `require` 验证合法范围。参数只控制 elaboration，不得从 wall-clock、环境变量、网络、文件系统或随机数取得。
- `for`、`Seq.fill`、`VecInit` 和 Scala collection 操作发生在 elaboration 时，循环边界必须是小而固定的参数。不要误以为 Scala 循环是逐 cycle 执行。
- 避免递归层次、超大展开和根据外部状态变化的模块结构。生成的层次和 top 名在相同源码/配置下必须确定。
- 顶层禁止 Scala `package` 且必须有零参数构造器。带参数的设计使用无参数 top 包装器实例化参数化子模块。

```scala
class AddLane(val width: Int) extends Module {
  require(width >= 2 && width <= 64)
  val lhs_i = IO(Input(UInt(width.W)))
  val rhs_i = IO(Input(UInt(width.W)))
  val result_o = IO(Output(UInt(width.W)))
  result_o := lhs_i +% rhs_i
}

class FourLaneTop extends Module {
  private val width = 8
  val lhs_i = IO(Input(Vec(4, UInt(width.W))))
  val rhs_i = IO(Input(Vec(4, UInt(width.W))))
  val result_o = IO(Output(Vec(4, UInt(width.W))))

  for (index <- 0 until 4) {
    val lane = Module(new AddLane(width))
    lane.lhs_i := lhs_i(index)
    lane.rhs_i := rhs_i(index)
    result_o(index) := lane.result_o
  }
}
```

## Reset、时钟和 CDC

- `Module` 的 `clock`/`reset` 语义必须与 architecture 一致。默认同步 reset 设计使用 `RegInit`；异步 reset 必须显式使用 `AsyncReset` 或 `.asAsyncReset`，并让 architecture/UT 覆盖 assertion 和 release。
- 自定义 clock/reset 域用 `withClockAndReset`，作用域尽量小。不要通过普通逻辑生成或门控 clock。
- clock enable 写成寄存器更新条件；不要用 `Bool` 与 `Clock` 做组合逻辑。
- 默认单时钟域。单 bit 同步器、异步 FIFO 和 handshake CDC 必须采用明确结构；不得逐 bit 同步多 bit bus。
- `RawModule` 中每个寄存器必须位于明确的 `withClockAndReset` 或 `withClock` 上下文。
- reset 后外部可见控制状态和 valid 必须确定。未 reset 的大数据寄存器只能在 valid 严格屏蔽且 UT 证明不会泄漏时使用。

```scala
class ExplicitClockDomain extends RawModule {
  val clk_i = IO(Input(Clock()))
  val rst_ni = IO(Input(Bool()))
  val data_i = IO(Input(UInt(8.W)))
  val data_o = IO(Output(UInt(8.W)))

  val dataReg = withClockAndReset(clk_i, (!rst_ni).asAsyncReset) {
    RegInit(0.U(8.W))
  }
  withClockAndReset(clk_i, (!rst_ni).asAsyncReset) {
    dataReg := data_i
  }
  data_o := dataReg
}
```

## Ready/Valid、流水线和 Backpressure

- ready/valid 在同一 cycle 同时为真时才接受 transaction。stall 时 valid、payload 和未完成 transaction 状态保持稳定。
- 可使用 `chisel3.util.Decoupled`，也可显式端口；architecture 和 Python API 必须使用同一 transaction 定义。
- 每一级流水同时推进 data、valid 和关联 metadata。修改流水级数时同步更新 latency、reference cycle 状态、CK 和性能 TC。
- 不形成跨模块组合 ready 环。需要断开时使用寄存器或经过验证的 queue/skid-buffer 结构。
- `Queue` 的 depth、pipe/flow 行为是功能合同的一部分，不能只为 PPA 临时修改而不更新测试。

## Vec、Bundle 和索引

- `Vec(count, type)` 的 count 必须是正且固定的 elaboration 参数。动态索引需要定义越界策略，并由输入位宽保证合法或显式处理非法值。
- `VecInit` 用于从确定长度序列构造硬件；不要从无序 collection 生成端口或功能映射。
- `Bundle` 字段名保持稳定。避免依赖反射字段顺序、匿名 Bundle 深层嵌套或不透明自动连接。
- 批量连接只有在两侧类型、方向和字段语义完全一致时使用；公开接口建议逐字段连接，方便 CK 定位。

## Memory 和初始化

- 组合读 memory 使用 `Mem`，同步读使用 `SyncReadMem`；读 latency 和 read-during-write 行为必须在 architecture 与 reference 中精确定义。
- 默认不使用文件初始化、运行时资源或 Scala 文件 I/O 创建功能状态。常量小表优先 `VecInit` 或 `MuxLookup`。
- 多写端口、跨时钟 memory 和推断技术 SRAM 只有在 Spec/技术库明确时使用，并记录偏离与验证证据。
- 地址位宽、合法范围、越界行为和 reset 后可观察内容必须有 CK。不能依靠截断把非法地址静默映射为有效地址。

## 可综合硬件与 Scala elaboration

以下内容可用于确定性 elaboration：不可变 `val`、小型固定 `Seq`、常量范围 `for`、纯函数、case class 参数和 `require`。它们只生成硬件，不表示硬件运行时行为。

不得把以下 host-language 行为用于设计功能：

- wall-clock、线程、sleep、Future、网络、进程、环境变量或文件系统读取；
- `scala.util.Random`、无固定顺序的 collection 遍历、全局可变状态或跨 elaboration 缓存；
- `println`、日志或异常作为硬件输出/协议的一部分；
- 运行时 class loading、反射、动态源码生成或依赖机器路径的结构；
- 仿真专用 `printf`、`stop`、`assert` 代替可观察的功能合同。

Scala `if` 处理 elaboration 常量；硬件条件必须使用 `when` 或 `Mux`。Scala 变量重新赋值只改变生成器程序，不能替代 `Wire`/`Reg`。

## 版本敏感和实验性 API

- 优先 `chisel3._` 与少量稳定的 `chisel3.util` 基础 API。
- 避免旧教程中的 `io := IO(...)` 风格、`cloneType` 手写覆盖、旧 `Chisel` 包、旧 Driver 和已弃用的命令入口。
- 默认不使用 experimental hierarchy、DataView、probe、property、layer、intrinsic、formal contract、BoringUtils 或 compiler annotation API。
- 不依赖 Scala 3 语法、extension method、given/using 或其他与固定 Scala 2.13 合同不一致的特性。
- `MuxLookup` 使用 `MuxLookup(key, default)(Seq(...))`；不要猜测其他大版本的重载形式。
- 必须使用版本敏感 API 时，在源码附近记录 `RTL-GUIDE-DEVIATION`，并以当前完整回归和 PPA 结果为准。

## BlackBox 和外部 IP

- 默认设计必须自包含，不使用 `BlackBox`、inline HDL、resource annotation 或外部源码。
- Spec 要求成熟 IP 时，architecture 必须锁定模块名、参数、端口、clock/reset、仿真模型和综合模型，并保证工作流可获得同一份受控源码。
- 不把功能逻辑藏入未经测试的 BlackBox，也不引用工作区外绝对路径。
- 外部 IP 无法进入功能仿真、综合或 PPA 时，该候选不能作为 accepted 版本。

## PPA 友好的处理

- 先保证同套 Python/RTL UT 全通过，再根据报告中的关键路径、cell 类型和功耗热点做单一假设的有界修改。
- 用精确位宽减少面积和翻转；避免为了方便把所有中间量扩大为 32/64 bit。
- 大型 `Vec` 动态索引、宽 `MuxLookup`、优先级链、变量乘除和动态移位会形成明显 mux/关键路径，应通过报告确认。
- 并行 lane 提升吞吐但增加面积/功耗；共享运算器降低面积但可能增加 latency 或降低 throughput。任何权衡都必须满足硬门槛与接受门禁规则（保护类别内指标不得回退，至少一项指标改善）。
- stall/invalid 时可保持大型寄存器减少翻转，但不能改变 ready/valid、reset 或可观察输出语义。
- 不使用 `dontTouch`、层次保留或命名 annotation 阻止正常优化，除非有外部接口/调试/技术原因并记录偏离。

## 命名和结构

- top class 名逐字匹配 architecture；端口建议 `_i/_o`，寄存状态建议 `Reg` 后缀或语义化名称，next-state 使用 `next...`。
- 不使用 Scala `package` 包住顶层，不给顶层构造器增加参数。子模块和 helper 名在整个源码集合中唯一。
- 注释解释协议、位宽、状态、PPA 权衡和偏离，不逐句翻译代码。
- 只维护匹配当前源码 glob 的 Chisel/Scala 源码，不创建其他硬件语言的替代实现或构建产物。

## 偏离记录

有意偏离时在相关源码附近写简短注释，说明原因、范围和证据。不要创建“已遵循规范”的自述清单。

```scala
// RTL-GUIDE-DEVIATION: the target SRAM macro requires a BlackBox wrapper.
// Scope: sampleMemory only. Evidence: shared RTL regression, stable performance
// stimulus, synthesis smoke, and the current PPA iteration report.
```

## 完整规范 Chisel 示例

```scala
/**
  * Module: StreamAdd
  * Purpose: one-entry unsigned adder with a ready/valid response buffer.
  * Interface: lhs_i/rhs_i are 8-bit unsigned operands; valid_i and ready_o
  *            define input acceptance; result_o/valid_o and ready_i define response.
  * Timing/reset: synchronous reset through Module's reset; a response is held
  *                until ready_i is high, so stall does not change result_o.
  * Numeric behavior: +% deliberately keeps the result at 8 bits and discards carry.
  */
import chisel3._

class StreamAdd extends Module {
  private val width = 8

  val valid_i = IO(Input(Bool()))
  val ready_o = IO(Output(Bool()))
  val lhs_i = IO(Input(UInt(width.W)))
  val rhs_i = IO(Input(UInt(width.W)))
  val valid_o = IO(Output(Bool()))
  val ready_i = IO(Input(Bool()))
  val result_o = IO(Output(UInt(width.W)))

  // State: validReg marks the buffered response; resultReg stores its payload.
  val validReg = RegInit(false.B)
  val resultReg = RegInit(0.U(width.W))
  val outputCanAdvance = !validReg || ready_i
  val inputAccepted = valid_i && outputCanAdvance

  // Core handshake datapath: update the payload only on an accepted input;
  // all response fields remain stable while the downstream side is stalled.
  when(outputCanAdvance) {
    validReg := valid_i
    when(inputAccepted) {
      resultReg := lhs_i +% rhs_i
    }
  }

  ready_o := outputCanAdvance
  valid_o := validReg
  result_o := resultReg
}
```

该示例顶层无 package、无构造参数，使用固定 Chisel 7 基础 API、显式位宽、`RegInit`、单一寄存器所有者和一项缓冲 ready/valid 语义。stall 时结果与 valid 保持，reset 后输出状态确定。实际 top、端口、reset、latency 和数值行为必须以当前 Spec 与 architecture 为准。
