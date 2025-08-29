
module FSM (
    input clk,           // 时钟信号
    input reset,         // 异步复位，高电平有效
    input key_in,        // 按键输入，0 表示按下（低电平有效）
    output reg pulse_out // 输出脉冲，高电平有效，单次触发
);
    // Mealy 状态定义
    typedef enum logic {
        IDLE   = 1'b0,
        PRESSED = 1'b1
    } state_t;
    state_t current_state, next_state;
    // 状态寄存器更新（时序逻辑）
    always @(posedge clk or posedge reset) begin
        if (reset)
            current_state <= IDLE;
        else
            current_state <= next_state;
    end
    // 下一状态逻辑 + 输出逻辑（组合逻辑）
    always @(*) begin
        // 默认值
        next_state = current_state;
        pulse_out = 1'b0;
        case (current_state)
            IDLE: begin
                if (key_in == 1'b0) begin
                    next_state = PRESSED;
                end
            end
            PRESSED: begin
                if (key_in == 1'b0) begin
                    pulse_out = 1'b1;  // Mealy 输出：按键仍按下时输出一个脉冲
                    next_state = IDLE; // 然后立刻返回 IDLE
                end else begin
                    next_state = PRESSED;
                end
            end
            default: begin
                next_state = IDLE;
            end
        endcase
    end
endmodule
