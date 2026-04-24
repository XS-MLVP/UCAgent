# COI 覆盖率分析与优化指南

## 什么是 COI

COI（Cone of Influence）覆盖率是一个**静态/结构性指标**——它衡量的是："设计中有多少信号至少落入了某个 assertion/assume/cover 属性的扇入锥？"

**关键认知**：
- COI **不关心属性是 PASS 还是 FALSE**。即使一个 assert 因为 RTL BUG 而失败，它引用的信号仍然会被计入已覆盖集合。
- 因此，**"因为有 RTL BUG 所以覆盖率低"是错误的推理**。如果 COI 不达标，唯一原因是你的断言集合没有引用到足够多的设计信号。
- COI 不等于功能覆盖率。100% COI 不意味着验证完整，但低 COI 一定意味着有盲区。

## fanin.rep 的格式与解读

`fanin.rep` 文件由形式化引擎生成，包含四类覆盖率指标和未覆盖信号列表：

```
Coverage Metrics:
  Inputs  : covered/total (pct%)
  Outputs : covered/total (pct%)
  Dffs    : covered/total (pct%)    ← 寄存器状态覆盖
  Nets    : covered/total (pct%)    ← 组合逻辑覆盖

Uncovered signals:
  - signal_name_1
  - signal_name_2
  ...
```

### 各指标含义

- **Inputs（输入端口）**：如果 assume 约束了所有输入，通常为 100%。
- **Outputs（输出端口）**：如果 assert 检查了所有输出，通常为 100%。
- **Dffs（寄存器）**：未覆盖的 Dff 意味着某些寄存器状态从未被任何时序断言的扇入锥触及。通常需要新增 `(Style: Seq)` 断言。
- **Nets（组合逻辑）**：未覆盖的 Net 通常是中间组合逻辑或子模块输出。需要新增 `(Style: Comb)` 或 `(Style: Seq)` 断言。
- **Uncovered signals 列表**：即行动目标——每一个信号都需要被某个断言引用，或被标记为 `[UNREACHABLE]`。

## 信号类型 → 断言策略映射

| 未覆盖信号类型 | 推荐断言 Style | 典型断言模式 |
|---|---|---|
| 寄存器/触发器 (Dff) | `(Style: Seq)` | 验证其传输关系：`condition |=> reg == expected_value` |
| 组合逻辑输出 (Net) | `(Style: Comb)` | 验证其布尔关系：`output == f(inputs)` |
| 状态机状态 (FSM) | `(Style: Seq)` + `(Style: Cover)` | 验证转移条件 + Cover 可达性 |
| 控制信号 (Flag/Enable) | `(Style: Seq)` | 验证其激活/去激活条件 |
| 内部子模块输出 | `(Style: Comb)` 或 `(Style: Seq)` | 需要在 wrapper.sv 中导出为白盒信号 |

## Cover vs Assert 的 COI 贡献差异

**Cover 属性对 COI 的贡献远小于 Assert。** 形式化引擎对 cover 的扇入分析只追踪"条件是否可达"，不会深入追踪信号每一位的具体逻辑关系。

❌ **错误做法**（用 cover 水 COI）：
```systemverilog
// 这只是检查 timer_count 能否 >= threshold，几乎不增加 COI
cover property (@(posedge clk) timer_count >= short_timer_value);
```

✅ **正确做法**（用 assert 验证行为）：
```systemverilog
// 验证 timer_count 的递增逻辑，每一位都进入 COI
property CK_TIMER_COUNT_INC;
  @(posedge clk) disable iff (!rst_n)
  (!start_timer && timer_state != 0) |=> (timer_count == $past(timer_count) + 1);
endproperty
A_CK_TIMER_COUNT_INC: assert property (CK_TIMER_COUNT_INC);
```

**规则：每个未覆盖信号至少需要一个验证其"行为正确性"的 assert，仅用 cover 引用是不够的。**

## UNREACHABLE 标记规则

有时候某些信号逻辑在当前配置下确实无法触及。

### 判断标准（必须全部满足才能标记 UNREACHABLE）

1. 信号被死参数化（如 `if (PARAM == 0)` 分支，但 PARAM 恒为 1）
2. 或信号被强制下拉/上拉的输入管脚传播
3. 或信号属于当前验证范围外的模块接口（如 DFT、JTAG 端口）

⚠️ **不能滥用 UNREACHABLE**：如果你不确定信号是否可达，先尝试写一个 `cover property` 来验证可达性，而不是直接标记。

操作步骤：
1. 在 `{OUT}/03_{DUT}_functions_and_checks.md` 中将这些项添加 `[UNREACHABLE]` 标记。
2. 附上简要的不可达原因说明。

## COI 优化迭代流程

覆盖率优化是一个迭代过程，应遵循以下流程避免引入新问题：

### 迭代优先级

1. **先 Dff（寄存器），后 Net（组合逻辑）**：Dff 未覆盖通常意味着核心状态逻辑没被验证，影响更大。
2. **先高扇出信号，后低扇出信号**：一个高扇出信号的 assert 可以同时覆盖多个下游 Net。
3. **先功能相关信号，后辅助信号**：优先覆盖与 DUT 核心功能直接相关的信号。

### 每轮迭代规模

- **每轮最多补 5–10 个断言**，避免一次性引入过多属性导致新的 TRIVIALLY_TRUE 或 FALSE。
- 每轮补完后**必须重跑验证**（`RunFormalVerification`），确认新属性全部 PASS 且无副作用。
- 如果新增属性出现 FALSE 或 TT，**立即处理**后再继续补下一批。

### 停止条件

满足以下任一条件即可结束迭代：
1. **COI ≥ 阈值**（默认 90%，由 `CoverageAnalysisChecker` 的 `coi_threshold` 参数控制）。
2. **剩余未覆盖信号全部被标记为 `[UNREACHABLE]`**，且标记理由充分。
3. **剩余未覆盖信号属于 wrapper 未导出的深层子模块内部信号**，需要额外白盒导出才能覆盖——此时记录为"后续改进项"。
