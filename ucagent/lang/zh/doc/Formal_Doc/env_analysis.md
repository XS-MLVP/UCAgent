# {DUT} 形式化验证环境分析报告

> **UCAgent 机器可读模板**
>
> - **目的**: 本模板用于在环境调试阶段（environment_debugging_iteration）对所有异常属性（TRIVIALLY_TRUE、FALSE）进行系统性分析和归档。
> - **来源**: UCAgent（AI）解析 `avis.log` 得到异常属性列表，结合 `checker.sv` 中的 SVA 代码和 RTL 源码，逐一分析并填写本文档。
> - **Checker 校验**: `EnvironmentAnalysisChecker` 会对 **日志（avis.log）-SVA 代码（checker.sv）-本文档** 进行三角校验，确保所有异常属性都被充分分析和跟踪。
>
> ⚠️ **文档分区说明**：
> - §1–§2–§3 的**条目模板**由 `InitEnvAnalysis` 工具自动生成，此处仅供人工参考格式。
> - §2 的**根因分类**和 §3 的**判定决策树**是核心领域知识，LLM 必须理解后再填写分析内容。

---

## 1. 验证结果概览

> AI 自动从 avis.log 提取并填充

| 类型 | 数量 |
|------|------|
| Assert Pass | - |
| Assert TRIVIALLY_TRUE | - |
| Assert Fail | - |
| Cover Pass | - |
| Cover Fail | - |
| **Total** | - |

---

## 2. TRIVIALLY_TRUE 属性分析

> 对每个 TRIVIALLY_TRUE 属性，必须创建独立的 `<TT-NNN>` 分析条目。
> TRIVIALLY_TRUE 表示该属性在给定约束下永远为真，完全丧失验证价值。

<!--
根因分类说明：
  - ASSUME_TOO_STRONG: assume 约束过强，排除了合法输入组合
  - SIGNAL_CONSTANT: 信号在给定约束下被常量折叠（如 $isunknown 检查对无 X 态信号）
  - WRAPPER_ERROR: wrapper.sv 信号映射错误导致常量传播
  - DESIGN_EXPECTED: 设计预期行为，属性本身即应永真（需充分论证）

修复动作说明：
  - FIXED: 已修改 assume/wrapper/checker，属性不再为 TRIVIALLY_TRUE
  - ACCEPTED: 经分析确认为设计预期或不影响验证完整性，标注原因后放行
-->

### <TT-001> {属性名}
- **属性名**: {A_CK_XXX 或 M_CK_XXX}
- **SVA 代码**:
  ```systemverilog
  // 从 checker.sv 中提取对应属性的完整代码
  property CK_XXX;
    ...
  endproperty
  ```
- **根因分类**: {ASSUME_TOO_STRONG | SIGNAL_CONSTANT | WRAPPER_ERROR | DESIGN_EXPECTED}
- **关联 Assume**: {M_CK_YYY — 导致过约束的 assume 属性名，若无则写 N/A}
- **分析**: {具体描述为何此属性 trivially true，包含信号传播路径分析}
- **修复动作**: {FIXED | ACCEPTED}
- **修复说明**: {若 FIXED: 描述做了什么修改及修改后的验证结果；若 ACCEPTED: 论证为何可接受}

<!-- 复制上方模板块，为每个 TRIVIALLY_TRUE 属性创建条目 -->

---

## 3. FALSE 属性分析

> 对每个 FALSE 属性（包括 assert fail 和 cover fail），必须创建独立的 `<FA-NNN>` 分析条目。

### FALSE 属性判定决策树

```
FALSE 属性
  │
  ├─ 属性类型是 cover 且 fail？
  │   └─ 检查是否因过约束导致状态不可达
  │       ├─ 是 → 修复 assume 后改为 ENV_FIXED
  │       └─ 否（该状态确实在设计中不可达）→ COVER_EXPECTED_FAIL
  │
  └─ 属性类型是 assert 且 fail？
      └─ 检查反例中的输入激励是否是合法的输入组合
          ├─ 输入不合法（现实中不可能出现的输入组合）
          │   └─ 说明 assume 约束不足 → ENV_PENDING
          │       → 在 checker.sv 中添加 assume → 重跑 → ENV_FIXED
          │
          └─ 输入合法（现实场景可能出现）
              └─ 检查 RTL 输出是否符合规格
                  ├─ RTL 输出错误 → RTL_BUG
                  └─ RTL 输出正确（断言本身写错了）→ 修改断言 → 重跑
```

**判断"输入是否合法"的方法**：
- 查看反例中的输入信号值，问自己：在真实硬件运行中，这组输入能同时出现吗？
- 如果涉及协议（如 AXI），检查是否违反了协议时序约束。
- 如果不确定，先加一个 cover property 检验该输入组合是否可达。



### <FA-001> {属性名}
- **属性名**: {A_CK_XXX 或 C_CK_XXX}
- **属性类型**: {assert | cover}
- **SVA 代码**:
  ```systemverilog
  // 从 checker.sv 中提取对应属性的完整代码
  property CK_XXX;
    ...
  endproperty
  ```
- **解决状态**: {RTL_BUG | ENV_FIXED | ENV_PENDING | COVER_EXPECTED_FAIL}
- **反例/分析**: {对于 assert fail: 描述反例中的信号值和时序；对于 cover fail: 分析为何该场景不可达}
- **修复说明**: {具体描述做了什么修改(如 added assume)，或是标记为 RTL BUG 的简要原因}

<!-- 复制上方模板块，为每个 FALSE 属性创建条目 -->

