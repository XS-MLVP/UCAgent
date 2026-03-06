# {DUT} 形式化验证环境 (Checker Module) 模板

> **UCAgent 机器可读模板**
>
> - **目的**: 本模板用于生成 `{DUT}` 的 SystemVerilog Checker 模块。
> - **来源**: UCAgent 将读取 `{OUT}/03_{DUT}_functions_and_checks.md` 中的 SVA 属性。
> - **使用者**: 在 `environment_generation` 阶段，UCAgent (AI) 会将提取的 SVA 代码注入到下方的“注入锚点”中，最终生成 `{OUT}/{DUT}_checker.sv` 文件。

## 模块定义
```systemverilog
module {DUT}_checker (
    // AI 将根据 {OUT}/{DUT}_basic_info.md 自动填充端口
    input clk,
    input rst_n,
    // DUT 接口信号
    input [31:0] data_in,
    input valid_in,
    input ready_out
    // ... 其他信号
);

    // 默认时钟块定义 (用于 SVA)
    default clocking cb @(posedge clk);
    endclocking

    // ==========================================
    // 1. 辅助逻辑 (Auxiliary Logic)
    // ==========================================
    // AI 将在此处注入状态跟踪、计数器等辅助性质的逻辑代码
    // <UCAgent-Inject-Aux-Logic>
    
    // logic [3:0] cnt;
    // always_ff @(posedge clk or negedge rst_n) begin
    //     if (!rst_n) cnt <= 0;
    //     else if (valid_in && ready_out) cnt <= cnt + 1;
    // end
    
    // </UCAgent-Inject-Aux-Logic>


    // ==========================================
    // 2. 约束 (Assumptions)
    // ==========================================
    // AI 将在此处注入所有 <PROP_TYPE: assume> 类型的属性
    // <UCAgent-Inject-Assumptions>

    // 【重要】如果设计使用符号化索引 (fv_idx)，必须添加以下约束：
    // 1. 符号化索引稳定性约束 - 防止索引在验证过程中漂移
    // property CK_FV_IDX_STABLE;
    //   @(posedge clk) disable iff (!rst_n)
    //   $stable(fv_idx);
    // endproperty
    // M_CK_FV_IDX_STABLE: assume property (CK_FV_IDX_STABLE);
    //
    // 2. 符号化索引范围约束 - 防止索引越界访问数组
    // property CK_FV_IDX_VALID;
    //   @(posedge clk)  // 注意：不要使用 disable iff，确保复位期间也有效
    //   fv_idx < NUM_PORTS;  // 替换 NUM_PORTS 为实际的数组大小参数
    // endproperty
    // M_CK_FV_IDX_VALID: assume property (CK_FV_IDX_VALID);

    // </UCAgent-Inject-Assumptions>


    // ==========================================
    // 3. 断言 (Assertions) - Safety & Liveness
    // ==========================================
    // AI 将在此处注入所有 <PROP_TYPE: assert> 类型的属性
    // <UCAgent-Inject-Assertions>

    // </UCAgent-Inject-Assertions>


    // ==========================================
    // 4. 覆盖点 (Covers)
    // ==========================================
    // AI 将在此处注入所有 <PROP_TYPE: cover> 类型的属性
    // <UCAgent-Inject-Covers>

    // </UCAgent-Inject-Covers>

endmodule

// ==========================================
// Bind 语句 (将 Checker 绑定到 DUT)
// ==========================================
// AI 将自动生成此 bind 模块
// <UCAgent-Inject-Bind>
/*
bind {DUT} {DUT}_checker u_{DUT}_checker (
    .clk(clk),
    .rst_n(rst_n),
    .data_in(data_in),
    .valid_in(valid_in),
    .ready_out(ready_out)
    // ...
);
*/
// </UCAgent-Inject-Bind>

```

## 注意事项
1. **端口列表**: Checker 的端口列表应与 DUT 的接口保持一致，AI 会尝试自动同步。
2. **时钟与复位**: Checker 模块必须包含时钟和复位信号。
3. **注入锚点**: 请勿修改或删除 `<UCAgent-Inject-...>` 注释块，它们是 AI 工作的关键。
4. **语法兼容性**:
   - 避免使用对表达式进行位选择的语法，如 `(a + b)[WIDTH-1:0]`
   - 使用单行属性语法，如 `assert property (prop) else $error(...)`
   - 避免参数化的位宽选择 `[WIDTH-1:0]`
   - 确保所有信号都有明确的驱动源
   - 使用 `{signal1, signal2}` 连接符进行信号拼接
   - 避免在属性中使用复杂的参数化表达式
   - 不支持 `$global_clock`，考虑使用简单的边沿检测
5. **组合逻辑设计注意事项**:
   - 对于组合逻辑DUT（无时钟），仍需要定义时钟信号用于SVA时序属性，通常使用默认时钟或在TCL脚本中定义
   - 组合逻辑的输入变化会立即反映到输出，因此SVA应验证输入输出之间的函数关系
   - 组合逻辑属性通常使用直接等式比较而非时序操作符，如 `assert property ({cout, sum} == a + b + cin)` 而非 `{input_signals} |-> {output_signals}`
   - 对于纯组合逻辑，可使用 `assert property (@(posedge clk) disable iff (!rst_n) ...)` 语法，FormalMC会处理组合逻辑时序
   - 组合逻辑的属性验证重点关注功能正确性，如 `output == function(input)`
   - 由于组合逻辑是即时响应的，验证重点是输入输出的函数映射关系，而非时序关系
