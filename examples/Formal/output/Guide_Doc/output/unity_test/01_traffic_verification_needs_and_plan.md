# Traffic Light Controller 形式化验证需求分析与验证规划

## 1. 验证目标
本验证任务的核心目标是通过形式化方法（Formal Verification）确保交通灯控制器（Traffic Light Controller）设计的完备性和安全性。重点在于发现逻辑缺陷、状态机死锁以及协议违反等问题。

## 2. 验证范围
验证将覆盖 `main` 顶层模块及其子模块：
- `timer`: 定时器控制逻辑
- `farm_control`: 农场道路灯光控制逻辑
- `hwy_control`: 高速公路灯光控制逻辑

## 3. 关键功能点与属性定义
### 3.1 安全性（Safety）
- **互斥性（Mutual Exclusion）**：农场道路灯（farm_light）和高速公路灯（hwy_light）绝对不能同时为非红色状态（即不能同时为 GREEN 或 YELLOW）。
- **复位状态（Reset State）**：复位后，农场灯必须为 RED，高速公路灯必须为 GREEN。
- **状态转换（State Transitions）**：验证每个控制器的状态转换是否严格遵循设计规格（GREEN -> YELLOW -> RED -> GREEN）。
- **无效状态（Illegal States）**：验证灯光输出始终处于有效的编码范围内。

### 3.2 活性（Liveness）
- **无饥饿（No Starvation）**：
    - 如果农场道路检测到车辆（`car_present == 1`），且高速公路灯处于 GREEN 状态，系统必须最终切换到农场道路 GREEN。
    - 如果农场道路无车（`car_present == 0`），且农场灯处于 GREEN 状态，系统必须最终切换回高速公路 GREEN。
- **终止性（Termination）**：定时器启动后，必须在有限时间内产生 `short` 和 `long` 信号。

### 3.3 可达性（Reachability/Cover）
- 覆盖农场灯和高速公路灯的所有可能状态（GREEN, YELLOW, RED）。
- 覆盖所有状态转换触发条件。

## 4. 验证策略与假设
- **环境假设**：
    - 假设 `short_timer_value` 小于或等于 `long_timer_value`，以确保定时逻辑的合理性。
    - 假设 `clk` 和 `reset_n` 遵循标准时序。
- **抽象策略**：由于定时器位宽较小（5位），直接进行全空间搜索，无需对计数器进行特殊抽象。
- **工具配置**：使用 BMC（Bounded Model Checking）发现早期 Bug，使用 PDR（Property Directed Reachability）进行完备性证明。

## 5. 潜在挑战
- **状态机死锁**：初步分析发现 `hwy_control` 在 `RED` 状态下的转换逻辑可能存在错误，可能导致高速公路灯永远无法变回绿灯。
- **计时器越界**：需要检查当计时器达到最大值时的溢出行为是否影响系统稳定性。

## 6. 预期交付成果
- 完备的形式化验证环境（Wrapper, Checker, Bind）。
- 详细的 SVA 断言集（涵盖 Safety, Liveness, Cover）。
- RTL 缺陷报告（Bug Report）及修复建议。
- 验证总结文档。

**注：属性失败（Fail）是发现设计缺陷的关键。每一个 Fail 都将被视为改进设计质量的机会，我们将通过分析反例（Counterexample）定位根本原因。**
