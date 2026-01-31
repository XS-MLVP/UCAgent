# {DUT} 形式化验证策略与总览

> **UCAgent 机器可读模板**
>
> - **目的**: 本模板定义了 `{DUT}` 形式化验证的顶层策略和配置。
> - **使用者**: UCAgent (AI) 在多个阶段会参考此文档，尤其是在 `script_generation` 阶段，用于生成 FormalMC Tcl 脚本。
> - **内容**: 本文档不包含具体的 SVA 属性代码，而是专注于**“如何验证”**的策略层面。

## 1. 验证目标与范围 (Verification Goal & Scope)
- **主要目标**: 证明 `{DUT}` 设计满足关键的功能属性 (Safety) 和活性属性 (Liveness)。
- **验证范围**:
  - `{DUT}` 模块及所有接口。
  - **重点关注**: [请列出重点验证的子模块或功能，例如：FSM, Arbiter, FIFO]
- **引用文档**: 
  - 设计规格: `{DUT}/README.md`
  - 功能分析: `{OUT}/{DUT}_functions_and_checks.md`

## 2. 设计关键信息 (Critical Design Information)
> AI 将从 `{OUT}/{DUT}_basic_info.md` 提取信息并在此确认

- **时钟信号**: `{clk_name}` (对于组合逻辑DUT，可能需要定义虚拟时钟用于SVA)
- **复位信号**: `{rst_name}` (对于组合逻辑DUT，复位可能不适用)
- **复位类型**: [同步/异步], [高/低电平有效]
- **逻辑类型**: [组合逻辑/时序逻辑] (重要：说明DUT是组合逻辑还是时序逻辑)

## 3. 形式化验证策略 (Formal Verification Strategy)

### 3.1 抽象与替换策略 (Abstraction/Replacement Strategy)
- **大型算术单元**: [例如：乘法器/除法器，是否需要替换为黑盒(blackbox)或简化模型]
- **存储器 (Memory)**: [例如：RAM/ROM，是作为黑盒处理还是使用形式化友好的模型]
- **策略描述**: [简述为何采用此策略，例如“为避免状态空间爆炸，将32x32乘法器抽象为无约束的输出”]

### 3.2 引擎配置策略 (Engine Configuration Strategy)
> 这些配置将直接影响 `script_generation` 阶段生成的 Tcl 脚本

- **默认证明引擎**: `pdrx`
  - *描述*: 用于最终的属性全量证明。
- **快速Debug引擎**: `bmc`
  - *描述*: 用于快速寻找反例 (counterexample)。可以设置一个合理的深度，如 `bmc -depth 50`。
- **活性(Liveness)引擎**: `liveness`
  - *描述*: 专门用于证明活性属性。
- **并行策略**: `par -t 4`
  - *描述*: 使用4个核心并行执行，加快收敛速度。

### 3.3 核心脚本命令定义 (Core Script Command Definition)
> 以下内容是生成 Tcl 脚本的关键指令，AI 将直接使用。

- **时钟定义 `def_clk`**: `def_clk -edge pos {clk_name}`
- **复位定义 `def_rst`**: `def_rst -async -act 1 {rst_name}`
  - *修改提示*: 根据实际复位类型修改 `-async` (异步) / `-sync` (同步) 和 `-act 1` (高有效) / `-act 0` (低有效)。
- **复位后约束 `add_cons`**: `add_cons -postreset {约束内容}`
  - *描述*: 定义复位释放后的初始状态约束，例如 `add_cons -postreset {!req}`。

## 4. 验证流程交付物 (Verification Deliverables)
- **属性定义**: `{OUT}/{DUT}_properties.md`
- **验证环境**: `{OUT}/{DUT}_checker.sv`
- **执行脚本**: `{OUT}/{DUT}_formal.tcl`
- **最终报告**: `{OUT}/{DUT}_formal_report.md`

## 5. FormalMC 特定注意事项
- **SystemVerilog 语法兼容性**: 
  - 避免使用对表达式进行位选择的语法，如 `(a + b)[WIDTH-1:0]`
  - 使用单行属性语法，如 `assert property (prop) else $error(...)`
  - 避免参数化的位宽选择 `[WIDTH-1:0]`
- **Checker 模块编写**:
  - 确保所有信号都有明确的驱动源
  - 使用 `{signal1, signal2}` 连接符进行信号拼接
  - 避免在属性中使用复杂的参数化表达式
- **TCL脚本编写**:
  - 正确指定设计和检查器文件路径
  - 使用合适的证明引擎设置
  - **特别注意**: 即使是组合逻辑DUT，也必须在TCL脚本中定义时钟信号，如 `def_clk -edge pos clk`，因为SVA属性需要时钟参考
- **组合逻辑设计注意事项**:
  - 对于组合逻辑DUT（无内部时钟），需要在TCL脚本中定义虚拟时钟用于SVA属性验证
  - 使用 `def_clk` 命令定义默认时钟，即使DUT本身是组合逻辑
  - 组合逻辑验证重点在功能正确性，如 `assert property (@(posedge clk) {output_signals} == function(input_signals))`
  - 组合逻辑属性通常使用直接等式比较而非时序操作符，如 `assert property ({cout, sum} == a + b + cin)`
  - 组合逻辑属性通常不包含时序关系，主要验证输入输出的函数映射关系
  - 对于组合逻辑，SVA属性中可以省略时钟敏感性，如 `assert property ({output_signals} == function(input_signals))`
