# Traffic Light Controller 功能点与检测点描述

## DUT 整体功能描述
Traffic Light Controller 是一个用于管理十字路口农场道路（farm）和高速公路（hwy）交通灯的系统。它根据车辆检测（car_present）和定时器信号协调两个方向的灯光状态，确保在任何时刻只有一个方向可以通行（GREEN 或 YELLOW）。

### 端口接口说明
- `clk`: 系统时钟
- `reset_n`: 同步复位，低电平有效
- `car_present`: 车辆检测（1: 有车, 0: 无车）
- `long_timer_value`: 长计时阈值 [4:0]
- `short_timer_value`: 短计时阈值 [4:0]
- `farm_light`: 农场道路灯状态 [1:0]
- `hwy_light`: 高速公路灯状态 [1:0]

### 状态机与时序
- **状态编码**：GREEN=0, YELLOW=1, RED=2。
- **农场灯逻辑**：RED -> GREEN (if enable_farm) -> YELLOW (if !car || long) -> RED (if short).
- **高速路灯逻辑**：RED -> GREEN (if enable_hwy) -> YELLOW (if car && long) -> RED (if short).
- **定时器逻辑**：START -> SHORT -> LONG。

---

## 功能分组与检测点

### 1. 验证环境约束

<FG-API>

#### 输入合法性约束

<FC-INPUT-ASSUME>

**检测点：**
- <CK_API_RST_SYNC> **(Style: Assume)** 假设初始复位：`initial assert(!reset_n)`。
- <CK_API_TIMER_THRESHOLD> **(Style: Assume)** 假设短计时阈值小于长计时阈值：`short_timer_value < long_timer_value`。
- <CK_API_TIMER_MIN> **(Style: Assume)** 假设阈值大于 0，防止计数器立即翻转：`short_timer_value > 0 && long_timer_value > 0`。
- <CK_API_INPUT_KNOWN> **(Style: Assume)** 确保输入信号无 X 态。

### 2. 安全性保障

<FG-SAFETY>

#### 互斥性检查

<FC-MUTEX>

**检测点：**
- <CK_SAFE_MUTEX> **(Style: Comb)** 互斥性：农场灯和高速路灯不能同时为非 RED 状态。
- <CK_SAFE_NOT_BOTH_GREEN> **(Style: Comb)** 农场灯和高速路灯不能同时为 GREEN。
- <CK_SAFE_NOT_BOTH_YELLOW> **(Style: Comb)** 农场灯和高速路灯不能同时为 YELLOW。

#### 状态合法性

<FC-LEGAL-STATE>

**检测点：**
- <CK_SAFE_FARM_VAL> **(Style: Comb)** 农场灯输出值必须在 [0,2] 范围内。
- <CK_SAFE_HWY_VAL> **(Style: Comb)** 高速路灯输出值必须在 [0,2] 范围内。

### 3. 控制逻辑与状态转移

<FG-CONTROL>

#### 复位行为

<FC-RESET-BEHAVIOR>

**检测点：**
- <CK_RESET_FARM_RED> **(Style: Seq)** 复位后农场灯为 RED。
- <CK_RESET_HWY_GREEN> **(Style: Seq)** 复位后高速路灯为 GREEN。

#### 农场灯状态转移

<FC-FARM-TRANS>

**检测点：**
- <CK_FARM_G_TO_Y> **(Style: Seq)** 农场灯 GREEN 转 YELLOW 条件：`(!car_present || long_timer)`。
- <CK_FARM_Y_TO_R> **(Style: Seq)** 农场灯 YELLOW 转 RED 条件：`short_timer`。
- <CK_FARM_R_TO_G> **(Style: Seq)** 农场灯 RED 转 GREEN 条件：`enable_farm`。
- <CK_FARM_STABLE> **(Style: Seq)** 无转移条件时农场灯应保持稳定。

#### 高速路灯状态转移

<FC-HWY-TRANS>

**检测点：**
- <CK_HWY_G_TO_Y> **(Style: Seq)** 高速路灯 GREEN 转 YELLOW 条件：`(car_present && long_timer)`。
- <CK_HWY_Y_TO_R> **(Style: Seq)** 高速路灯 YELLOW 转 RED 条件：`short_timer`。
- <CK_HWY_R_TO_G> **(Style: Seq)** 高速路灯 RED 转 GREEN 条件：`enable_hwy`。
- <CK_HWY_STABLE> **(Style: Seq)** 无转移条件时高速路灯应保持稳定。

### 4. 定时器逻辑

<FG-TIMER>

#### 计数器更新

<FC-TIMER-COUNT>

**检测点：**
- <CK_TIMER_RESET> **(Style: Seq)** 当 `start_timer` 或 `reset_n` 为低时，`timer` 计数器复位。
- <CK_TIMER_INC> **(Style: Seq)** 非复位/启动状态下，计数器应递增。

#### 标志位生成

<FC-TIMER-FLAGS>

**检测点：**
- <CK_TIMER_SHORT_VALID> **(Style: Comb)** `short` 标志位在状态为 SHORT 或 LONG 时有效。
- <CK_TIMER_LONG_VALID> **(Style: Comb)** `long` 标志位在状态为 LONG 时有效。

### 5. 活性与进度

<FG-LIVENESS>

#### 无饥饿性

<FC-NO-STARVATION>

**检测点：**
- <CK_LIVE_FARM_GREEN> **(Style: Seq)** 如果 `car_present` 持续有效，农场灯最终必须变为 GREEN。
- <CK_LIVE_HWY_GREEN> **(Style: Seq)** 如果 `car_present` 持续无效，高速路灯最终必须变为 GREEN。

### 6. 可达性覆盖

<FG-COVERAGE>

#### 状态覆盖

<FC-STATE-COVER>

**检测点：**
- <CK_COVER_FARM_G> **(Style: Cover)** 农场灯 GREEN 可达。
- <CK_COVER_FARM_Y> **(Style: Cover)** 农场灯 YELLOW 可达。
- <CK_COVER_HWY_Y> **(Style: Cover)** 高速路灯 YELLOW 可达。
- <CK_COVER_HWY_R> **(Style: Cover)** 高速路灯 RED 可达。
