# Traffic Light Controller RTL 缺陷分析报告

## 环境调试摘要
- **环境问题修复**：0 个。
- **环境质量指标**：环境约束（Assume）合理，无过度约束导致 TRIVIALLY_TRUE 的情况（TRIVIALLY_TRUE 均为逻辑恒等证明）。
- **确认的 RTL 缺陷总数**：1 个核心缺陷，导致 2 个活性断言失败。

---

## Failed Property: checker_inst.A_CK_HWY_R_TO_G

- **根本原因**：在 `hwy_control` 模块中，高速公路灯在 `RED` 状态下的转移逻辑存在硬编码错误。当收到 `enable_hwy` 使能信号时，状态机未能按预期切换到 `GREEN` 状态，而是错误地保持在 `RED` 状态。
- **代码定位**：`traffic/traffic.v` 第 178 行。
  ```verilog
  177: `RED:
  178:   if (enable_hwy) hwy_light <= `RED; // 缺陷位置：应为 `GREEN
  ```
- **概念性反例 (CEX)**：
    1. 复位后：`hwy_light = GREEN`, `farm_light = RED`。
    2. 触发切换：高速公路有车且长计时期满，`hwy_light` 依次变为 `YELLOW` -> `RED`。
    3. 农场通行：`farm_light` 变为 `GREEN`，农场道路开始通行。
    4. 农场结束：农场检测无车或长计时期满，`farm_light` 依次变为 `YELLOW` -> `RED`。
    5. 握手失败：`farm_control` 发出 `enable_hwy` 信号。
    6. 错误行为：`hwy_control` 在 `RED` 状态下收到 `enable_hwy`，执行 `hwy_light <= RED`。
    7. 结果：系统进入死锁状态，两个方向均为 `RED`，且 `hwy_light` 无法再变为 `GREEN`。
- **预期行为**：当 `hwy_light == RED` 且 `enable_hwy` 为真时，`hwy_light` 应变为 `GREEN`。
- **实际行为**：`hwy_light` 保持为 `RED`。
- **修复建议**：
  将 `traffic.v` 第 178 行修改为：
  ```verilog
  if (enable_hwy) hwy_light <= `GREEN;
  ```

---

## Failed Property: `checker_inst.A_CK_LIVE_FARM_GREEN`

- **根本原因**：该活性断言失败是由于上述 `A_CK_HWY_R_TO_G` 缺陷引起的派生问题。由于高速公路灯无法回到 `GREEN` 状态，系统逻辑链条断裂，导致后续的调度逻辑（如农场灯的再次使能）无法正常触发，从而违反了活性要求。
- **预期行为**：如果农场有车，系统最终应轮转到农场绿灯。
- **修复建议**：修复 `A_CK_HWY_R_TO_G` 即可。

---

## Failed Property: `checker_inst.A_CK_LIVE_HWY_GREEN`

- **根本原因**：同上。由于 `hwy_control` 状态机无法从 `RED` 转移回 `GREEN`，导致高速公路灯在第一次循环后永远无法变绿。
- **预期行为**：如果农场无车，高速公路应最终保持绿灯。
- **修复建议**：修复 `A_CK_HWY_R_TO_G` 即可。
