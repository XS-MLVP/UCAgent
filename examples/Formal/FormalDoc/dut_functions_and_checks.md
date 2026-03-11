# DUT 功能点与检测点描述指南 (Formal Verification Edition)

## 概述

本文档是形式化验证的**核心规划蓝图**。其主要目的不仅是定义“验什么”（功能点），更是明确“怎么验”（属性风格）。通过系统化的功能分组、功能点识别和检测点设计，为后续自动生成高质量的 SVA 属性奠定基础。

### 核心原则与设计指南

**1. 对应性原则**：本文档中定义的每一个 `<CK-...>` 检测点都必须在最终的 SVA 代码中得到实现。它是 SVA 编写的**唯一直接依据**。

**2. 独立性原则**：检测点之间应尽可能独立，避免逻辑交叉覆盖，确保 Bug 定位的精准性。

**3. 高质量形式化断言设计指南 (Design Philosophy)**：
   - **全状态空间覆盖 (State Space Completeness)**：不同于动态仿真，Formal 验证覆盖所有可能的输入序列。因此，必须精确定义合法输入的边界（Assume），防止伪反例。
   - **完备性 (Check Completeness)**：
     - **Safety (安全性)**：坏事永远不发生（例如：FIFO 永不溢出，One-hot 信号永不多选）。
     - **Liveness (活性)**：好事最终会发生（例如：请求最终被响应）。
   - **正负向结合 (Positive & Negative)**：
     - **正向**：在特定条件下，状态**必须**发生变化（例如：写使能 -> 计数器+1）。
     - **负向 (Frame Conditions)**：在非特定条件下，状态**必须**保持不变（例如：无写使能 -> 计数器 $stable）。这是 Formal 发现隐蔽 Bug 的利器。
   - **X 态悲观 (X-Pessimism)**：必须显式验证关键控制信号（如 Valid, Ready, Grant, State）在任何时候都不为 X 态。

## 文档结构层次

<FG-*> 等标签结构为树状结构，同一个父节点下的子节点不能出现同名

### 层次关系
```
DUT整体功能
├── 功能分组 <FG-*>
│   ├── 功能点1 <FC-*>
│   │   ├── 检测点1 <CK-*> (Style: ...)
│   │   ├── 检测点2 <CK-*> (Style: ...)
│   │   └── ...
│   ├── 功能点2 <FC-*>
│   │   └── ...
│   └── ...
└── ...
```

### 标签系统
- **功能分组标签**：`<FG-{group-name}>` - 标识功能分组, 标识大的功能模块或逻辑分类。
- **功能点标签**：`<FC-{function-name}>` - 标识具体的设计意图或功能规格。
- **检测点标签**：`<CK-{check-point-name}>` - 标识具体的断言点。



**重要提醒**：
- checker工具正是通过这些标签进行规范检测的，标签格式必须严格遵循规范。
- 检查点`<CK-{check-point-name}>` 之间需要尽可能的独立，不要出现对应功能交叉覆盖，以免后续出现bug导致覆盖率分析变得困难。

## 强制性要求：定义属性风格 (Style)

在定义每个 `<CK-...>` 时，必须紧随其后用括号注明其**属性风格**。这直接指导大模型如何生成代码。

**可用风格标签：**
- **`(Style: Comb)`**: **组合逻辑断言**。描述永恒成立的逻辑等式（Invariant）。代码中**严禁**包含时钟边沿触发或时序操作符（如 `|->`）。
- **`(Style: Seq)`**: **时序逻辑断言**。描述跨周期的行为、状态转移或时序协议。代码中**必须**包含时钟 (`@(posedge clk)`) 和时序操作符。
- **`(Style: Cover)`**: **可达性证明**。用于证明关键状态（如 Error、Full）是可达的，以及环境约束（Assume）没有导致验证环境过约束（Over-constrained）。
- **`(Style: Assume)`**: **环境约束**。定义 DUT 输入端口的合法行为。这是 Formal 验证的基石，错误的 Assume 会导致验证结果无效。
- **`(Style: Symbolic)`**: **符号化验证扩展**。专门针对多条目存储（如 FIFO、RAM、Register File）。标记该断言**必须**通过 `fv_idx`（符号化索引）和 `fv_mon_...` 信号来验证阵列的任意单元。通常与其他风格结合，如 `(Style: Seq, Symbolic)`。

## 标准文档格式

### 文档模板

```markdown
# {DUT名称} 功能点与检测点描述

## DUT 整体功能描述

[这里描述DUT的整体功能，包括：]
- 主要用途和应用场景
- 输入输出接口说明
- 关键性能指标
- 工作原理概述

### 端口接口说明
- 输入端口：[端口名称、位宽、功能描述]
- 输出端口：[端口名称、位宽、功能描述]
- 控制信号：[控制信号说明]

### 状态机与时序
- **状态机列表**：

- **状态转移条件**：

- **时序行为**：

## 功能分组与检测点

### 功能分组A

<FG-GROUP-A>

[功能分组的整体描述，说明该分组包含的功能范围]

#### 具体功能A1

<FC-FUNCTION-A1>

[详细描述功能A1的具体实现、输入输出关系、预期行为等]

**检测点：**
- <CK-CHECK-A1-1> **(Style: Comb/Seq/Cover/Assume)** [具体的检测条件和判断标准]
- <CK-CHECK-A1-2> **(Style: Comb/Seq/Cover/Assume)** [具体的检测条件和判断标准]
- ...

#### 具体功能A2

<FC-FUNCTION-A2>

[功能A2的描述...]

**检测点：**
- <CK-CHECK-A2-1> **(Style: Comb/Seq/Cover/Assume)** [具体的检测条件和判断标准]
- ...

### 功能分组B

<FG-GROUP-B>

[继续下一个功能分组...]
```

### 标签放置规范

**✅ 正确的标签放置**
```markdown
### 具体功能1

<FC-FUNC1>

功能描述内容...
```

**❌ 错误的标签放置**
```markdown
### 具体功能1 <FC-FUNC1>
功能描述内容...
```

标签应独立成行，与标题之间用空行分隔，避免在Markdown预览时可见。

## 命名规范和最佳实践

### 命名原则

1. **简洁性**：名称应简短但具有明确含义
2. **一致性**：同类功能使用统一的命名模式
3. **可读性**：名称应易于理解，避免缩写歧义
4. **层次性**：体现功能的层次关系

### 推荐命名模式

#### 功能分组命名
```markdown
<FG-ARITHMETIC>    # 算术运算组
<FG-LOGIC>         # 逻辑运算组
<FG-MEMORY>        # 内存操作组
<FG-CONTROL>       # 控制功能组
<FG-IO>            # 输入输出组
<FG-API>           # 接口约束组 (Formal必须)
```

#### 功能点命名
```markdown
<FC-ADD>           # 加法功能
<FC-FSM-TRANS>     # 状态跳转
<FC-FIFO-PUSH>     # 队列写入
<FC-ARB-GRANT>     # 仲裁授权
```

#### 检测点命名
```markdown
<CK-NORM-*>        # 正常行为
<CK-ERR-*>         # 错误/异常处理
<CK-STABLE-*>      # 稳定性检查 (Frame Condition)
<CK-LEGAL-*>       # 合法性检查 (Sanity Check)
<CK-LIVE-*>        # 活性检查 (Liveness)
```

## 高级形式化检测点模式 (Formal Verification Patterns)

为了确保形式化验证的完备性和有效性，在设计检测点时建议参考以下高级模式：

### 模式 1：数据稳定性与单点修改保证 (Stability & Frame Conditions)
- **目的**: 证明“只有该改的地方改了，其他地方都没动”。这是发现地址译码错误、数组越写、意外覆盖等 Bug 的关键。
- **模式**: 结合条件蕴含与 `$stable`。
- **示例**: `<CK-DATA-STABILITY> (Style: Seq, Symbolic) 验证非目标地址稳定性：当写入地址不等于 fv_idx 时，$stable(fv_mon_data)。`

### 模式 2：强制可达性与过约束检查 (Reachability & Sanity)
- **目的**: 杜绝 `TRIVIALLY_TRUE`（无效证明）。如果环境约束写得太死（例如 `assume (reset == 1)`），所有属性都会伪通过。
- **强制规则**: 必须为每一个关键状态（Full, Empty, Hit, Error, State_X）定义 Cover 检测点。
- **示例**: `<CK-FULL-REACHABLE> (Style: Cover) 证明 FIFO 能够达到 Full 状态。`

### 模式 3：活性与不饥饿 (Liveness & No Starvation)
- **目的**: 验证设计不会死锁或饥饿（Something Good Eventually Happens）。Formal 工具会寻找无限循环的反例。
- **示例**: `<CK-REQ-EVENTUALLY-GRANT> (Style: Seq) 验证活性：如果 Request 置起且未撤销，Grant 最终必须置起 (s_eventually)。`

### 模式 4：构造正确性 (Construction Correctness)
- **目的**: 验证复杂数据结构（如链表、树、Ring Buffer）的内部指针逻辑一致性。
- **示例**: `<CK-PTR-MATH> (Style: Comb) 验证 FIFO 计数器：cnt == (wr_ptr - rd_ptr) & MASK。`

## 常用结构的典型检测点设计 (Best Practice Patterns)

### 1. 状态机 (FSM)
- `<CK-FSM-ONE-HOT>` (Style: Comb): 验证状态寄存器必须是独热码（针对 One-hot 编码的状态机）。
- `<CK-FSM-VALID-STATE>` (Style: Comb): 验证状态寄存器不会进入未定义的无效编码（针对二进制编码）。
- `<CK-FSM-TRANS-RESET>` (Style: Seq): 验证复位释放后，状态机必须处于 IDLE/RESET 状态。
- `<CK-FSM-DEADLOCK>` (Style: Seq): 验证状态机最终会回到 IDLE 状态（防止死锁）。

### 2. 握手协议 (Valid/Ready)
- `<CK-VALID-STABILITY>` (Style: Seq): 验证 Valid 建立后，在 Ready 之前 Data 和 Control 必须保持稳定（不允许撤回请求）。
- `<CK-HANDSHAKE-X-CHECK>` (Style: Comb): 验证 Valid 和 Ready 信号绝不为 X 态。
- `<CK-DATA-TRANSFER>` (Style: Seq): 证明当 `valid && ready` 发生时，数据被正确采样或传输。

### 3. 仲裁器 (Arbiter)
- `<CK-ARB-MUTEX>` (Style: Comb): 互斥性检查，同一时刻最多只有一个 Grant 有效（One-hot）。
- `<CK-ARB-FAIRNESS>` (Style: Seq): 公平性检查，高优先级请求不能永远饿死低优先级请求。

### 4. 存储/队列 (FIFO/Buffer)
- `<CK-FIFO-OVERFLOW>` (Style: Seq): 安全性检查，当 Full 时写请求必须被阻塞或忽略，且写指针不动。
- `<CK-FIFO-UNDERFLOW>` (Style: Seq): 安全性检查，当 Empty 时读请求无效，读指针不动。
- `<CK-FIFO-ORDERING>` (Style: Seq, Symbolic): 数据完整性检查，写入的数据必须按顺序读出，值不变。

#### 必要分组

在所有功能点与检测点描述文档中，必须要有以下分组：

<FG-API> # 测试API分组，对DUT验证时需要用到的标准API

## 完整示例：同步 FIFO (Formal Verification Edition)

### 设计规格
一个深度为 16，数据位宽 32 位的同步 FIFO。支持 Flush 功能。

### 端口接口说明
- `clk, rst_n`: 系统时钟与复位
- `push, pop`: 写请求，读请求
- `wdata`: 写数据 [31:0]
- `rdata`: 读数据 [31:0]
- `full, empty`: 状态标志
- `flush`: 清空信号

---

### 状态机与时序
(此处无复杂状态机，主要为读写指针逻辑)
- 指针逻辑：循环队列，位宽 5bit (含折叠位) 或 4bit + 标志位。
- 时序：读写均为时钟上升沿触发。

## 功能分组与检测点

### 1. 验证环境约束 (API)

<FG-API>

#### 输入合法性约束

<FC-INPUT-ASSUME>

**检测点：**
- <CK-API-RST-LEGAL> **(Style: Assume)** 假设复位信号有效（初始复位）：`initial assert(!rst_n)`。
- <CK-API-INPUT-KNOWN> **(Style: Assume)** 假设关键控制信号无 X 态：`!$isunknown({push, pop, flush})`。

### 2. 核心控制逻辑

<FG-CONTROL>

#### 标志位逻辑

<FC-FLAGS>

**检测点：**
- <CK-FULL-LOGIC> **(Style: Comb)** 验证 Full 生成逻辑：`full == (cnt == DEPTH)`。
- <CK-EMPTY-LOGIC> **(Style: Comb)** 验证 Empty 生成逻辑：`empty == (cnt == 0)`。

#### 指针与计数器更新

<FC-POINTERS>

**检测点：**
- <CK-CNT-INC> **(Style: Seq)** 验证计数器加：`(!full && push && !pop) |=> cnt == $past(cnt) + 1`。
- <CK-CNT-DEC> **(Style: Seq)** 验证计数器减：`(!empty && pop && !push) |=> cnt == $past(cnt) - 1`。
- <CK-CNT-STABLE> **(Style: Seq)** 验证计数器保持：`(!push && !pop) || (push && pop) |=> cnt == $past(cnt)` (注意：需处理 full/empty 边界)。
- <CK-FLUSH-RESET> **(Style: Seq)** 验证清空：`flush |=> (cnt == 0 && wr_ptr == 0 && rd_ptr == 0)`。

### 3. 数据完整性 (Symbolic)

<FG-DATA>

#### 符号化数据一致性

<FC-DATA-PATH>

**检测点：**
- <CK-FIFO-ORDERING> **(Style: Seq, Symbolic)** 验证数据先入先出：
  `push && wdata == fv_data && !full |-> ##[1:$] (pop && rdata == fv_data)` 
  *(注：这是高级 Liveness 属性，更推荐用 Scoreboard 逻辑或符号化索引)*。
- <CK-MEM-STABILITY> **(Style: Seq, Symbolic)** 验证非写入地址数据保持：
  `(push && wr_ptr != fv_idx) |=> $stable(mem[fv_idx])`。

### 4. 安全性与异常

<FG-SAFETY>

#### 溢出保护

<FC-OVERFLOW-PROTECT>

**检测点：**
- <CK-NO-OVERFLOW> **(Style: Seq)** 验证写保护：`full && push |=> $stable(wr_ptr) && $stable(mem)`。
- <CK-NO-UNDERFLOW> **(Style: Seq)** 验证读保护：`empty && pop |=> $stable(rd_ptr)`。

### 5. 可达性证明

<FG-COVERAGE>

#### 状态覆盖

<FC-STATE-COVER>

**检测点：**
- <CK-COVER-FULL> **(Style: Cover)** 证明 Full 状态可达。
- <CK-COVER-FLUSH-WHEN-FULL> **(Style: Cover)** 证明在满状态下可以 Flush。
- <CK-COVER-WRAP-AROUND> **(Style: Cover)** 证明指针可以回绕（Wrap around）。

## 质量检查清单

### 完整性检查
- [ ] 每个功能分组至少包含一个功能点
- [ ] 每个功能点至少包含一个检测点
- [ ] 所有标签格式正确且唯一
- [ ] 功能描述清晰完整

### 一致性检查
- [ ] 命名风格统一
- [ ] 标签放置位置正确
- [ ] 检测点覆盖主要场景
- [ ] 功能点之间无重复或遗漏

### 可测试性检查
- [ ] 检测点可以通过测试用例验证
- [ ] 检测条件明确可判断
- [ ] 边界条件和异常情况已考虑
- [ ] 测试数据可以设计
