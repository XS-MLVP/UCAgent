# {DUT} 形式化验证环境分析报告

> **UCAgent 机器可读模板**
>
> - **目的**: 本模板用于在环境调试阶段（environment_debugging_iteration）对所有异常属性（TRIVIALLY_TRUE、FALSE）进行系统性分析和归档。
> - **来源**: UCAgent（AI）解析 `avis.log` 得到异常属性列表，结合 `checker.sv` 中的 SVA 代码和 RTL 源码，逐一分析并填写本文档。
> - **Checker 校验**: `EnvironmentAnalysisChecker` 会对 **日志（avis.log）-SVA 代码（checker.sv）-本文档** 进行三角校验，确保所有异常属性都被充分分析和跟踪。

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

<!--
判定结果说明：
  - RTL_BUG: 确认为 RTL 设计缺陷，反例展示了真实的功能错误
  - ENV_ISSUE: 验证环境问题（assume 不足/错误），反例为不真实的输入组合

修复动作说明：
  - MARKED_RTL_BUG: 在 checker.sv 中添加 // [RTL_BUG] 标记
  - ASSUME_ADDED: 添加了新的 assume 约束
  - ASSUME_MODIFIED: 修改了现有 assume 约束
  - COVER_EXPECTED_FAIL: cover 属性 fail 是预期行为（如互斥状态的 cover）
-->

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
- **判定结果**: {RTL_BUG | ENV_ISSUE | COVER_EXPECTED_FAIL}
- **反例/分析**: {对于 assert fail: 描述反例中的信号值和时序；对于 cover fail: 分析为何该场景不可达}
- **修复动作**: {MARKED_RTL_BUG | ASSUME_ADDED | ASSUME_MODIFIED | COVER_EXPECTED_FAIL}
- **修复说明**: {具体描述修复内容或标记原因}

<!-- 复制上方模板块，为每个 FALSE 属性创建条目 -->

---

## 4. 环境健康度总结

> AI 在所有条目填写完毕后更新此节

| 指标 | 值 |
|------|------|
| TRIVIALLY_TRUE 已分析 | {N_analyzed}/{N_total} |
| TRIVIALLY_TRUE 已修复 (FIXED) | {N_fixed} |
| TRIVIALLY_TRUE 已接受 (ACCEPTED) | {N_accepted} |
| ACCEPTED 比例 | {N_accepted/N_total * 100}% |
| FALSE 已分析 | {M_analyzed}/{M_total} |
| FALSE 判定为 RTL_BUG | {M_rtl_bug} |
| FALSE 判定为 ENV_ISSUE | {M_env_issue} |
| FALSE 判定为 COVER_EXPECTED_FAIL | {M_cover_expected} |
| 未修复的 ENV_ISSUE | {M_unresolved} |

**环境声明**: {✅ 所有异常属性已分析完成 | ❌ 仍有 N 个属性未分析}
