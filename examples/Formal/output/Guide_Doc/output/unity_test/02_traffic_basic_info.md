# Traffic Light Controller 基础信息文档

## 1. 接口定义
模块名称：`main`

| 信号名 | 方向 | 位宽 | 描述 |
| ------ | ---- | ---- | ---- |
| clk | input | 1 | 系统主时钟 |
| reset_n | input | 1 | 复位信号（低电平有效）。注：RTL 实现为同步复位。 |
| car_present | input | 1 | 车辆检测信号（1: 有车, 0: 无车） |
| long_timer_value | input | 5 | 长计时器阈值输入 |
| short_timer_value | input | 5 | 短计时器阈值输入 |
| farm_light | output | 2 | 农场道路交通灯状态（0: GREEN, 1: YELLOW, 2: RED） |
| hwy_light | output | 2 | 高速公路交通灯状态（0: GREEN, 1: YELLOW, 2: RED） |

## 2. 核心组成部分
设计由三个子模块组成，通过顶层 `main` 进行连接。

### 2.1 timer (定时器模块)
- **功能**：根据输入阈值产生计时信号。
- **关键寄存器**：
    - `state`: 控制计时的状态机（START, SHORT, LONG）。
    - `timer`: 5位计数器。
- **输出**：`short` (达到短阈值), `long` (达到长阈值)。

### 2.2 farm_control (农场灯控制)
- **功能**：实现农场道路的状态切换。
- **关键状态机**：`farm_light`。
- **逻辑**：在收到 `enable_farm` 后从 RED 转为 GREEN。

### 2.3 hwy_control (高速路灯控制)
- **功能**：实现高速公路的状态切换。
- **关键状态机**：`hwy_light`。
- **逻辑**：在收到 `enable_hwy` 后从 RED 转为 GREEN（注：RTL 此处存在逻辑错误，实际代码中转为了 RED）。

## 3. 时钟与复位方案
- **时钟**：单时钟域 `clk`。
- **复位**：同步复位，低电平有效。所有寄存器在 `reset_n == 0` 的时钟上升沿进入初始状态。
    - `farm_light` 复位值为 `RED` (2'd2)。
    - `hwy_light` 复位值为 `GREEN` (2'd0)。
    - `timer` 计数器复位值为 0。

## 4. 关键参数与宏定义
- `TIMER_WIDTH`: 5位。
- 状态编码：
    - `GREEN`: 2'd0
    - `YELLOW`: 2'd1
    - `RED`: 2'd2
- 车辆检测：
    - `YES`: 1
    - `NO`: 0

## 5. 设计实现注意点
1. **同步复位**：尽管文档描述可能提到异步，但 RTL 实际为同步复位逻辑。
2. **逻辑冲突**：`hwy_control` 中的 `RED` 状态转移逻辑存在明显的 Bug。
3. **互斥性依赖**：系统依赖 `enable_farm` 和 `enable_hwy` 在两个方向控制器之间传递控制权，以维持互斥。
