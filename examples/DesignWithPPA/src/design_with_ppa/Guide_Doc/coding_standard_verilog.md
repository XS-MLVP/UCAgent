
# Verilog-2005 建议编码规范

本规范用于工作流默认的 Verilog RTL。目标是让源码在 Yosys、仿真器和下游时序/功耗分析之间保持一致，便于定位功能或 PPA 卡点。它是建议规范，不作为强制风格门禁：优先遵循；当设计 Spec、目标技术、外部 IP 或实测 PPA 需要其他写法时，可以有意偏离，并在源码附近说明原因、范围和验证依据。任何偏离仍必须通过综合、同套功能回归、性能 TC 和 PPA 门禁。

配置的只读 Verilog 库目录会递归提供 `.v` 模块源码。实例化库模块时必须使用其稳定模块名和显式端口连接，不得修改或复制库文件；使用的模块、参数和接口假设应记录在 architecture 或设计总结中。库内容由工作流哈希绑定，建立 PPA base 后不得切换库版本。头文件目录、预编译库和非 `.v` 文件不属于本目录合同，需要时应由后续语言后端扩展显式支持。

## 语言版本与允许的子集

默认使用 IEEE 1364-2005 可综合子集，文件后缀为 `.v`。建议使用：

- ANSI 风格 `module` 端口声明、`parameter`、`localparam`、`wire`、`reg`、连续赋值 `assign` 和显式模块实例化；
- `always @*` 组合过程，以及 `always @(posedge clk ...)` 或 `always @(negedge clk ...)` 时序过程；
- `if/else`、完整 `case`、常量边界 `for`、`generate`/`genvar` 和模块内可综合 `function`；
- 位选、常量范围 part-select、拼接、复制、算术、比较、逻辑、按位、归约和移位运算；
- 静态宽度的 `reg [W-1:0] memory [0:DEPTH-1]`，前提是读写时序语义在 architecture 中明确；
- `default_nettype none` 包围每个源文件，并在文件末恢复为 `default_nettype wire`。

源码应自包含，不使用工作区外 include。确需头文件时使用同一 RTL 目录内的 workspace-relative include，并确保所有综合、测试和报告调用都能解析它；更推荐用参数和子模块替代宏共享状态。

## 不应使用的语法

以下构造不属于默认合同，通常不得用于可综合设计：

- SystemVerilog 语法：`logic`、`bit`、`always_comb`、`always_ff`、`always_latch`、`typedef`、`enum`、`struct`、`union`、`interface`、`package`、class、constraint、SVA 和动态数组；
- 工具扩展或非标准语法：厂商属性 `(* ... *)`、专有 pragma、隐式黑盒、DPI/VPI、加密块、非标准 include 搜索路径，以及依赖某个仿真器宽松解析的端口或声明写法；
- 仿真专用语法：`#delay`、`initial`、`final`、`force/release`、`fork/join`、`wait`、named event、`disable`、`real/realtime/time`、`specify`、UDP，以及 `$display`、`$monitor`、`$finish`、`$stop`、`$random`、文件 I/O 等系统任务；
- 不确定性掩盖：`casex`、用 `casez` 吞掉未知控制位、功能逻辑中的 `===/!==`、无约束的 `x/z` 常量、内部三态总线和依赖 X optimism/pessimism 的行为；
- 不可静态展开的循环、递归函数、运行时可变层级、跨层级引用，以及依赖初始化值而没有 architecture reset 合同的状态；
- 在 Verilog 模式中使用常见但非本规范的 SystemVerilog 扩展，如 `$clog2`、`$bits`、`'0`、`unique case`、`inside` 和 variable part-select `base +: width`。

目标库、成熟 IP 或明确工具链要求使用上述扩展时，记录 `RTL-GUIDE-DEVIATION`，并用当前工作流实测，不要仅根据工具可能支持来推断正确性。

## 注释结构（建议）

注释是帮助审查、调试和后续 PPA 优化的建议规范，不是独立的 Checker 门禁，也不能代替功能测试。每个 RTL 源文件和主要 module 建议按以下结构提供与实现一致的说明：

- 文件级注释：模块名、功能目的、输入到输出的总体数据流，以及组合或时序性质。
- module/参数注释：每个 parameter 的含义、单位、合法范围、默认值和对位宽、资源、latency 的影响。
- 端口注释：方向、位宽、signedness、单位或编码，clock/reset 边沿与极性，以及 valid/ready、backpressure 和 transaction 语义。
- 时序注释：状态在哪个边沿更新、reset 是同步还是异步、响应 latency、stall 时保持什么，以及组合输出何时稳定。
- 核心逻辑注释：在关键组合/时序块之前说明数据通路、状态转移和非直观的优先级；对显式扩展、截断、舍入、饱和、溢出、特殊编码和非法输入策略说明原因。
- 偏离注释：若为 Spec、外部 IP 或 PPA 有意偏离本规范，在源码附近写一条 `RTL-GUIDE-DEVIATION`，包含原因、影响范围和验证依据。

注释应解释设计意图和取舍，不必逐行翻译代码。修改接口、时序或核心算法时同步更新注释，不得留下与 architecture、Python executable spec 或实际行为矛盾的描述。推荐的最小文件结构如下：

```verilog
// Module: Example
// Purpose: One-sentence function and dataflow.
// Interface: list every port with direction, width, signedness, and protocol meaning.
// Timing/reset: combinational or sequential behavior, edge, polarity, synchrony, latency.
// Numeric behavior: encoding, extension, truncation, rounding, saturation, invalid inputs.
module Example (...);
    // Core datapath: explain the non-obvious operation immediately before the logic.
endmodule
```

## 位宽与常量

- 所有硬件常量写明宽度和进制，例如 `8'h00`、`1'b0`；避免无尺寸十进制常量参与向量表达式。
- 算术前先定义结果宽度。加法/减法需要保留进位时显式扩展操作数；乘法结果通常使用两个操作数宽度之和。
- 截断必须显式选位；饱和、舍入、溢出和下溢策略必须来自 Spec，不能依赖赋值时的隐式截断。
- 参数派生宽度使用模块内常量函数或由上层显式传入；不要依赖 `$clog2`。零宽度和负范围参数必须在 Spec/architecture 中排除。
- 拼接表达式中的每一项都应有确定宽度。避免把 unsized literal、integer loop variable 或 signed 值直接混入 datapath。

推荐写法：

```verilog
wire [WIDTH:0] extended_sum;

assign extended_sum = {1'b0, lhs} + {1'b0, rhs};
assign result_o = extended_sum[WIDTH-1:0];
assign carry_o  = extended_sum[WIDTH];
```

## Signed 算术与比较

- 不在 wire/reg/input/output 声明上使用 `signed` 关键字：yosys 生成的网表会保留
  `wire signed` 声明，而 OpenSTA 3.1.0 的 Verilog reader 无法解析它，PPA 阶段会因此
  失败。全部信号使用无符号声明，用二补码位模式承载负数——按位行为与 signed 声明
  完全一致。
- 负数运算靠显式手工符号扩展：用 `{operand[MSB], operand}` 拼接复制符号位到统一
  宽度后再相加、相乘或比较；在无符号上下文中直接零扩展会破坏负数。
- 比较与加减在同一个符号扩展宽度上按二补码进行；编码器、饱和与幅值比较按无符号
  处理。
- 逻辑右移统一使用 `>>`；需要算术右移时先手工复制符号位再右移，不使用 `>>>`。

```verilog
// 全无符号二补码数据通路：先显式符号扩展到统一宽度，再相加。
wire [WIDTH:0] lhs_ext = {lhs[WIDTH-1], lhs};
wire [WIDTH:0] rhs_ext = {rhs[WIDTH-1], rhs};
wire [WIDTH:0] sum_ext = lhs_ext + rhs_ext;
```

## 组合逻辑

- 简单逻辑优先连续赋值。需要多分支过程时使用 `always @*`，过程开头先给每个输出/next-state 默认值。
- 组合过程使用阻塞赋值 `=`；同一个信号只由一个连续赋值或一个过程驱动。
- `if/else` 必须覆盖所有路径；`case` 必须有 `default`。未指定分支保持原值会推断 latch，除非 architecture 明确要求 latch 且已记录偏离。
- 条件优先级必须有意表达。互斥选择用完整 `case`；优先级选择用按优先级排列的 `if/else if`。
- 不使用组合反馈。长组合路径拆分时必须同步更新 latency/handshake 合同与测试。

```verilog
always @* begin
    result_next = {WIDTH{1'b0}};
    valid_next  = 1'b0;
    case (opcode_i)
        2'b00: begin
            result_next = lhs_i + rhs_i;
            valid_next  = valid_i;
        end
        2'b01: begin
            result_next = lhs_i ^ rhs_i;
            valid_next  = valid_i;
        end
        default: begin
            result_next = {WIDTH{1'b0}};
            valid_next  = 1'b0;
        end
    endcase
end
```

## 时序逻辑与 Reset

- 时序过程只使用非阻塞赋值 `<=`；不要在同一时序过程混用阻塞赋值更新状态。
- 一个寄存器只在一个时序过程中赋值。clock/reset 边沿、极性和同步/异步语义必须逐字匹配 architecture。
- reset 分支给需要确定启动行为的控制状态、valid 和外部可见寄存器明确值。数据寄存器不 reset 仅在输出始终被 valid 屏蔽且测试证明无泄漏时采用，并记录设计理由。
- clock enable 写成时序过程内的 `if (enable)`，不要用 `clk & enable` 在 RTL 中自建门控时钟。
- 异步 reset 的释放策略由 architecture 约束；RTL 不能宣称实现了仅靠单个 always 块无法保证的板级同步释放。

```verilog
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        state_q <= IDLE;
        valid_o <= 1'b0;
        data_o  <= {WIDTH{1'b0}};
    end else begin
        state_q <= state_d;
        valid_o <= valid_d;
        if (valid_d)
            data_o <= data_d;
    end
end
```

## FSM、计数器与循环

- FSM 状态用 `localparam` 定义固定编码，用独立 `state_q/state_d` 表示当前/下一状态，并为非法状态提供恢复分支。
- 计数器的范围、终值、回绕/饱和行为和比较宽度必须显式。避免 `counter == DEPTH` 时由于宽度不足形成永不命中的条件。
- procedural `for` 只用于编译期可确定次数的并行硬件；循环变量在模块作用域声明为 `integer`，循环体不能含 timing control。
- 大规模展开、优先编码器、变量乘除和宽动态移位可能显著增加面积或关键路径。它们语法可用，但应在 PPA 报告中检查对应 hotspot。

```verilog
localparam [1:0] IDLE = 2'b00;
localparam [1:0] RUN  = 2'b01;
localparam [1:0] DONE = 2'b10;

reg [1:0] state_q;
reg [1:0] state_d;

always @* begin
    state_d = state_q;
    case (state_q)
        IDLE:    if (start_i) state_d = RUN;
        RUN:     if (last_i)  state_d = DONE;
        DONE:                 state_d = IDLE;
        default:              state_d = IDLE;
    endcase
end
```

## 存储器与数组

- 只使用固定深度、固定元素宽度的 unpacked reg array。明确同步写、同步读或异步读语义，并让 reference model 按相同 cycle 行为实现。
- 同一 memory 的多写端口、混合时钟和 read-during-write 行为只有在 Spec/目标宏明确时才使用；否则拆分结构或仲裁。
- 不依赖 `initial`/`$readmemh` 初始化功能状态。常量查找表优先用完整 case 或明确的只读组合函数。
- memory 地址必须有合法范围策略；不能通过截断悄悄把非法地址映射为有效地址，除非 Spec 如此定义。

## Handshake、流水线与 Backpressure

- `valid/ready` 接口只有在同一周期二者同时为 1 时接受 transaction；stall 时 payload 和所有未完成 transaction 状态保持稳定。
- valid-only 接口必须明确每周期是否都能接受；不能在没有 ready 的情况下静默丢弃输入。
- 每一级流水线同时推进 data 和对应 valid/metadata。修改流水级数时同步修改 architecture、Python reference 的 cycle 状态和性能 TC。
- 不在组合路径中形成跨模块 `ready` 环。需要切断时增加寄存器或 skid buffer，并重新测量 latency/throughput。

## CDC 与时钟

- 默认一个 clock domain。跨时钟单 bit 控制使用目标技术认可的同步器；多 bit 数据使用握手、异步 FIFO 或稳定快照协议。
- 不把多 bit bus 的各 bit 独立同步，不把普通组合逻辑输出直接当 clock/reset，不在 RTL 中制造脉冲 clock。
- 新增 clock domain 或 CDC 结构必须先更新 architecture，再实现 reference/test 场景；仅添加注释不能构成 CDC 证明。

## PPA 友好的标准处理

- 先保证功能正确，再依据报告中的关键路径、cell 类型和功耗实例做有界优化；不要凭直觉全局重写。
- 除法/取模优先常量 2 的幂，通过显式位选/移位实现。其他除法只有 Spec 必需且综合/PPA 可接受时使用。
- 共享乘法器、加法器或比较器会减少面积但可能降低吞吐率；并行展开相反。任何改变都必须保持性能硬门槛并通过接受门禁判定（保护类别内指标不得回退，至少一项指标改善）。
- 减少无意义翻转：stall 或 invalid 时保持大型 datapath 寄存器，但不能破坏 reset、可观测输出或协议。
- 避免宽度过大的中间信号和重复表达式；共享表达式前确认共享 mux 不会成为新关键路径。

## 命名与结构

- module/parameter/port 名必须与 architecture 一致。建议 `_i/_o` 表示方向，`_q/_d` 表示寄存/next-state，`_n` 表示低有效，`clk/rst` 名称保持 Spec 原样。
- 一个文件以一个主要 module 为主；辅助 module 名应唯一且体现职责。端口、声明、组合逻辑、时序逻辑按稳定顺序组织。
- 不用隐式 net；实例端口使用具名连接，不依赖位置顺序；未使用端口有意悬空时写明原因。
- 注释解释协议、不明显的位宽推导、PPA 权衡和偏离原因，不逐句翻译代码。

## 偏离记录

有意偏离时使用靠近实现的简短注释。不要创建“已遵循规范”的自述清单，也不要修改测试来迁就偏离。

```verilog
// RTL-GUIDE-DEVIATION: target SRAM requires this vendor attribute on storage.
// Scope: sample_mem only. Evidence: synthesis smoke, full RTL regression,
// performance TC set, and PPA iteration report for the current candidate.
```

## 完整规范 RTL 示例

```verilog
`default_nettype none

// Module: StreamAdd
// Purpose: One-entry unsigned adder with a ready/valid response buffer.
// Interface: valid_i/lhs_i/rhs_i form the input transaction; ready_o accepts it;
//            valid_o/result_o form the response; ready_i consumes the response.
// Parameters: WIDTH is the unsigned operand/result width and must be positive;
//             this example deliberately discards the carry bit.
// Timing/reset: response state updates on posedge clk; rst_n is asynchronous,
//               active low; a stalled response keeps result_o and valid_o stable.
// Numeric behavior: operands are zero-extended before addition, then explicitly
//                   truncated to WIDTH bits as required by this example contract.
module StreamAdd #(
    // WIDTH controls operand and result width; architecture must define its range.
    parameter WIDTH = 8
) (
    // clk: active rising edge for the one-entry transaction buffer.
    input  wire             clk,
    // rst_n: asynchronous active-low reset; clears valid state and result.
    input  wire             rst_n,
    // valid_i/lhs_i/rhs_i: input transaction and WIDTH-bit unsigned operands.
    input  wire             valid_i,
    input  wire [WIDTH-1:0] lhs_i,
    input  wire [WIDTH-1:0] rhs_i,
    // ready_o: high when this module can accept a transaction this cycle.
    output wire             ready_o,
    // valid_o/result_o: buffered WIDTH-bit unsigned response and its valid flag.
    output reg              valid_o,
    output reg  [WIDTH-1:0] result_o,
    // ready_i: downstream response acceptance; low holds result_o stable.
    input  wire             ready_i
);

wire accept_i;
wire accept_o;
wire [WIDTH:0] sum_full;

assign ready_o  = !valid_o || ready_i;
assign accept_i = valid_i && ready_o;
assign accept_o = valid_o && ready_i;
// Extend both operands before addition so the WIDTH-bit result has an explicit carry policy.
assign sum_full = {1'b0, lhs_i} + {1'b0, rhs_i};

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        valid_o  <= 1'b0;
        result_o <= {WIDTH{1'b0}};
    end else begin
        if (ready_o)
            valid_o <= valid_i;
        if (accept_i)
            result_o <= sum_full[WIDTH-1:0];
        else if (accept_o)
            valid_o <= 1'b0;
    end
end

endmodule

`default_nettype wire
```

该示例使用确定宽度加法、具名协议信号、单驱动时序寄存器、非阻塞赋值、显式异步低有效 reset 和 stall 时数据保持。实际设计仍以 Spec 与 architecture 为准。
