
## FSM 缺陷分析

## 未测试通过检测点分析

<FG-PULSE>

#### 脉冲持续时间控制功能 <FC-PULSELEN>
- <CK-PULSELEN> 脉冲持续时间：测试发现脉冲在按键持续按下时会连续产生，而不是仅在第一次按键按下时产生一次，与预期的单次触发行为不符，Bug置信度 90% <BUG-RATE-90>

## 缺陷根因分析

#### 1. 脉冲持续时间控制缺陷

**缺陷描述：** FSM在按键持续按下时会连续产生脉冲，而不是仅在第一次按键按下时产生一次。这与README.md中描述的"每次按键按下只产生一个脉冲，实现单次触发功能"不符。

**影响范围：**
- FG-PULSE/FC-PULSELEN/CK-PULSELEN

**根本原因：** 
在RTL设计中，状态机的实现逻辑存在缺陷。根据FSM.v的代码：
```verilog
PRESSED: begin
    if (key_in == 1'b0) begin
        pulse_out = 1'b1;  // Mealy 输出：按键仍按下时输出一个脉冲
        next_state = IDLE; // 然后立刻返回 IDLE
    end else begin
        next_state = PRESSED;
    end
end
```

当按键持续按下时（key_in=0），状态机会在IDLE和PRESSED状态之间来回切换：
1. IDLE状态：检测到key_in=0，转换到PRESSED状态
2. PRESSED状态：key_in=0，输出pulse_out=1，返回IDLE状态
3. IDLE状态：检测到key_in=0，再次转换到PRESSED状态
4. PRESSED状态：key_in=0，再次输出pulse_out=1，返回IDLE状态
...

这种实现方式导致按键持续按下时会连续产生脉冲，而不是单次触发。

**具体代码缺陷：**
```verilog
// FSM.v 第31-38行，状态转换逻辑错误
31: PRESSED: begin
32:     if (key_in == 1'b0) begin
33:         pulse_out = 1'b1;  // BUG: 每次按键按下都会产生脉冲
34:         next_state = IDLE; // BUG: 状态立即返回IDLE，导致连续触发
35:     end else begin
36:         next_state = PRESSED;
37:     end
38: end
```

**修复建议：**
```verilog
// 修复后的实现应该确保按键按下后，即使按键持续按下也不会再次触发
// 可以通过增加一个中间状态或使用额外的标志位来实现

// 方案1：增加一个防重复触发的状态
typedef enum logic [1:0] {
    IDLE      = 2'b00,
    PRESSED   = 2'b01,
    HOLD      = 2'b10
} state_t;

// 方案2：使用标志位防止重复触发
reg triggered;

always @(posedge clk or posedge reset) begin
    if (reset) begin
        current_state <= IDLE;
        triggered <= 1'b0;
    end else begin
        case (current_state)
            IDLE: begin
                if (key_in == 1'b0) begin
                    current_state <= PRESSED;
                    triggered <= 1'b1;  // 标记已触发
                end
            end
            PRESSED: begin
                if (key_in == 1'b1) begin
                    current_state <= IDLE;
                    triggered <= 1'b0;  // 清除触发标记
                end
                // 即使按键仍按下，也不再触发
            end
        endcase
    end
end

// 输出逻辑
always @(*) begin
    pulse_out = 1'b0;
    if (current_state == PRESSED && triggered) begin
        pulse_out = 1'b1;
    end
end
```

**验证方法：** 重新执行涉及CK-PULSELEN的测试用例，确认在按键持续按下时只产生一次脉冲，而不是连续产生脉冲。
