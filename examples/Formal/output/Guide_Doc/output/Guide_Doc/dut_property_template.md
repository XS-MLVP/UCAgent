# {DUT} 形式化属性 (SVA) 生成模板 (v3.1)

本模板是 SVA 代码生成的**执行手册**。请根据规划文档 (`03_...md`) 中每个检测点 `<CK_...>` 后面的 `(Style: ...)` 标签，严格选择对应的代码模板。
注意: 对于规划文档中的每一个检测点 `<CK_...>` 在实现时都要有一个属性与他对应`property CK_...;`

---

## 1. 核心生成原则 (Core Principles)

### 原则 1：杜绝无效的“占位符”断言
- **强制规则**: **严禁**生成如 `... |-> 1'b1;` 的占位符断言。如果你无法为检查点编写有意义的逻辑，必须生成 `TODO` 注释。
- **正确示例**: `// TODO: <CK_COMPLEX_ALGO> requires a complex reference model and is not auto-generated.`

### 原则 2：精确断言标志位 (Flags)
- **强制规则**: 必须基于精确的场景断言标志位。
- **正向**: 在明确会导致标志位有效的场景下，断言其**必须**为1。
- **负向**: 在明确保证不会触发标志位的“安全”输入子集下，断言其**必须**为0。
- **禁止**: 严禁做宽泛的假设（例如假设常规输入永远不会溢出）。

### 原则 3：分而治之 (Divide and Conquer)
- **强制规则**: 优先使用多个、具体的、独立的断言，而不是单一的复杂断言。
- **示例**: 将“零值加法”分解为 `CK_ADD_A_PLUS_ZERO` 和 `CK_ADD_ZERO_PLUS_B`。

### 原则 4：领域特定逻辑 (Domain-Specific Logic)
- **强制规则**: 必须遵守领域特定规则（如浮点数、总线协议）。
- **IEEE 754 浮点数关键规则速查表 (必须遵守)**:
    | 场景              | 结果  | 备注                       |
    | ----------------- | ----- | -------------------------- |
    | `x` op `NaN`      | `NaN` | `op`为任何运算             |
    | `x` cmp `NaN`     | `false` | `cmp`为任何比较            |
    | `非零 / 0`        | `Inf` | 符号位由二者符号异或决定   |
    | `0 / 0`           | `NaN` |                            |
    | `Inf / Inf`       | `NaN` |                            |
    | `Inf - Inf`       | `NaN` | （同号的无穷大减法）       |
    | `0 * Inf`         | `NaN` |                            |
    | `+0` == `-0`      | `true`  | 在比较时相等               |

---

## 2. 标准代码模板 (Standard Templates)

根据规划文档中的 `(Style: ...)` 标签选择模板。

### 2.1 组合逻辑模板 (Style: Comb)
**适用**: 纯组合逻辑检查，不依赖时序历史。
**禁止**: 严禁使用 `@(posedge clk)`, `##`, `$rose`, `$past`。

```systemverilog
// <CK_NAME>
// 描述: {从规划文档中提取描述}
property CK_NAME;
  // 逻辑: 前提条件 |-> 预期结果 (无时钟，无时序操作符)
  {TRIGGER_CONDITION} |-> {EXPECTED_BEHAVIOR};
endproperty
A_CK_NAME: assert property (CK_NAME);
```

### 2.2 时序逻辑模板 (Style: Seq)
**适用**: 需要跨周期检查、状态机跳转、寄存器更新等。
**必须**: 包含时钟定义和复位逻辑。

```systemverilog
// <CK_NAME>
// 描述: {从规划文档中提取描述}
property CK_NAME;
  @(posedge clk) disable iff (!rst_n)
  // 逻辑: 前提 |-> 结果
  {TRIGGER_CONDITION} |-> {EXPECTED_BEHAVIOR};
endproperty
A_CK_NAME: assert property (CK_NAME);
```

### 2.3 覆盖属性模板 (Style: Cover)
**适用**: 验证场景是否可达，或者特定序列是否发生。

```systemverilog
// <CK_NAME>
property CK_NAME;
  @(posedge clk) disable iff (!rst_n)
  {SCENARIO_EXPRESSION};
endproperty
C_CK_NAME: cover property (CK_NAME);
```

### 2.4 环境约束模板 (Style: Assume)
**适用**: 约束输入激励，排除非法输入组合。

```systemverilog
// <CK_NAME>
property CK_NAME;
  @(posedge clk)
  // 逻辑: 限制输入信号的行为
  {CONSTRAINT_EXPRESSION};
endproperty
M_CK_NAME: assume property (CK_NAME);
```

---

## 3. 高级验证模式 (Advanced Patterns)

### 3.1 符号化索引稳定性 (Symbolic Index Constraint)
**适用**: 当使用符号化索引 `fv_idx` 验证数组/RAM 时，**必须**添加以下约束以防止索引漂移和越界。

```systemverilog
// <CK_FV_IDX_CONSTRAINTS> (Style: Assume)
// 1. 稳定性: 防止 fv_idx 在验证过程中漂移，确保 $past() 采样正确
property CK_FV_IDX_STABLE;
  @(posedge clk) disable iff (!rst_n)
  $stable(fv_idx);
endproperty
M_CK_FV_IDX_STABLE: assume property (CK_FV_IDX_STABLE);

// 2. 有效范围: 防止越界访问 (注意：不使用 disable iff，复位期间也有效)
property CK_FV_IDX_VALID;
  @(posedge clk)
  fv_idx < NUM_PORTS; // 替换为实际数组大小参数
endproperty
M_CK_FV_IDX_VALID: assume property (CK_FV_IDX_VALID);

// 3. 确定性: 确保索引值不是 X 态
property CK_FV_IDX_KNOWN;
  @(posedge clk)
  !$isunknown(fv_idx);
endproperty
M_CK_FV_IDX_KNOWN: assume property (CK_FV_IDX_KNOWN);
```

### 3.2 符号化索引单点修改保证 (Symbolic Single Point Change)
**适用**: 验证存储阵列的数据更新。

```systemverilog
// 正向: 仅当地址匹配且写使能时，数据更新
// 负向: 当地址不匹配时，数据保持稳定
property CK_MEM_UPDATE;
  @(posedge clk) disable iff (!rst_n)
  ((write_en && addr != fv_idx) || !write_en) |=> $stable(fv_mon_data);
endproperty
A_CK_MEM_UPDATE: assert property (CK_MEM_UPDATE);
```

### 3.3 握手协议稳定性 (Handshake Stability)
**适用**: Valid/Ready 协议。

```systemverilog
// Valid 建立后，在 Ready 到来前必须保持稳定
property CK_VALID_STABILITY;
  @(posedge clk) (valid && !ready) |=> (valid && $stable(data));
endproperty
M_CK_VALID_STABILITY: assume property (CK_VALID_STABILITY);
```

### 3.4 强制可达性覆盖 (Reachability Coverage)
**适用**: 证明关键状态（Full, Empty, Error）可达，防止环境过约束。

```systemverilog
// <CK_REACHABLE_STATE>
property CK_REACHABLE_STATE;
  @(posedge clk) disable iff (!rst_n)
  {SIGNAL} == {VALUE};
endproperty
C_CK_REACHABLE_STATE: cover property (CK_REACHABLE_STATE);
```

---

## 4. 关键检查清单与最佳实践 (Checklist & Best Practices)

### 4.1 强制白盒验证 (White-box Verification)
**必须**通过 Wrapper 引出 DUT 内部状态，不要仅依赖 IO。
- **FIFO**: 引出 `readPtr`, `writePtr`, `count`, `empty`, `full`。
- **FSM**: 引出 `state`, `next_state`。

### 4.2 复位极性核对 (Reset Polarity)
- 检查 RTL：`if (reset)` -> 高有效；`if (!rst_n)` -> 低有效。
- Wrapper 连接必须正确：`.reset(~rst_n)` 或 `.rst_n(rst_n)`。

### 4.3 优先级排除原则 (Priority Exclusion)
在验证常规行为（如计数器递增）时，**必须**在前提中排除高优先级信号：
- `(!io_flush)`
- `(!io_clear)`
- `(!is_bypass)`

### 4.4 Bypass 模式处理
- 如果设计有直通模式（Empty 时写直接读），内部存储通常不更新。
- 定义 `wire is_bypass = empty & write_valid & read_ready;` 并在涉及内部存储的断言中排除它。

### 4.5 时序操作符规范
- **组合逻辑/状态定义**: 使用 `|->` (Same cycle)。
- **时序逻辑/寄存器更新**: 使用 `|=>` (Next cycle)。

---

## 5. 最终质量自检 (Final QA)

1.  **Style: Comb 检查**: 确认没有使用 `@(posedge ...)`, `##`, `$past` 等时序语法。
2.  **Style: Seq 检查**: 确认包含了时钟和复位逻辑。
3.  **占位符检查**: 确认没有 `|-> 1'b1`。
4.  **命名一致性**: SVA 属性名必须与 `<CK_...>` 标签完全一致。
