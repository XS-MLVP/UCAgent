
# {DUT} 形式化验证环境 (Checker Module) 模板指南

本指南展示 Checker 模块的代码骨架结构、端口声明规范和时钟块定义。
在验证环境中，所有 SVA 断言都会被注入到这个模块的对应区域中。

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


```

## 注意事项

1. **端口列表**: Checker 的端口列表应与 DUT 的接口保持一致，AI 会尝试自动同步。
2. **时钟与复位**: 仅使用 DUT 实际存在且与目标有关的时钟、复位；无时钟/复位设计显式标为不适用。
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
   - 无时钟设计直接验证同周期函数关系，不为满足模板添加虚假时钟、复位或 `disable iff` 豁免。
   - 可以使用布尔前提或同周期 `|->` 条件，不引入延迟和历史采样；真正跨周期的目标使用设计实际时钟。
   - 端口和参数与任务RTL核对；属性体通过可选数据技能的bodies请求文件或普通文件工具维护YAML；不直接编辑生成模块。
