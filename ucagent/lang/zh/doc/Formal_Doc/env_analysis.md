# 环境分析领域知识参考

> **本文档是环境调试阶段（environment_debugging_iteration）的领域知识参考。**
>
> - **数据写入方式**: 通过 `env_analysis.py -mode init` 生成骨架，再用 `update_analysis.py` 逐条填写分析字段，数据存储在 `.formal_records.yaml` 的 `analysis` 字段中。
> - **Checker 校验**: `EnvironmentAnalysisChecker` 对 **avis.log** 和 **.formal_records.yaml** 进行双源校验，确保所有异常属性都被充分分析。
> - **文档自动生成**: Checker 通过后自动从 JSON 生成 `07_{DUT}_env_analysis.md`，**无需手动编写 Markdown**。

---

## TRIVIALLY_TRUE 根因分类

TRIVIALLY_TRUE 表示属性在给定约束下永远为真，完全丧失验证价值。必须为每个 TT 属性选择一个根因分类：

| 根因 | 含义 | 典型场景 |
|------|------|----------|
| `ASSUME_TOO_STRONG` | assume 约束过强，排除了合法输入组合 | `assume (input == 0)` 导致依赖 input 的断言永真 |
| `SIGNAL_CONSTANT` | 信号在给定约束下被常量折叠 | `$isunknown` 检查对无 X 态信号永远为假，取反后永真 |
| `WRAPPER_ERROR` | wrapper.sv 信号映射错误导致常量传播 | 端口未连接、信号名拼写错误导致默认值 0 |
| `DESIGN_EXPECTED` | 设计预期行为，属性本身即应永真 | 需充分论证为何验证仍然有效 |

### 修复动作

| 动作 | 含义 |
|------|------|
| `FIXED` | 已修改 assume/wrapper/checker，属性不再为 TRIVIALLY_TRUE |
| `ACCEPTED` | 经分析确认为设计预期或不影响验证完整性，标注原因后放行 |

> ⚠️ ACCEPTED 比例不得超过 Checker 配置的阈值（默认 50%），超过说明环境整体过约束。

---

## FALSE 属性判定决策树

对每个 FALSE 属性（包括 assert fail 和 cover fail），必须按以下决策树判定解决状态：

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

### 解决状态枚举

| 状态 | 含义 | 后续动作 |
|------|------|----------|
| `RTL_BUG` | RTL 设计缺陷 | 进入 bug-report 阶段 |
| `ENV_FIXED` | 环境问题已修复 | 重跑验证确认属性状态变化 |
| `ENV_PENDING` | 环境问题已定位但未修复 | **阻止工作流推进**，必须修复 |
| `COVER_EXPECTED_FAIL` | cover 属性失败是预期的 | 需论证该状态确实不可达 |

### 判断"输入是否合法"的方法

- 查看反例中的输入信号值，问自己：在真实硬件运行中，这组输入能同时出现吗？
- 如果涉及协议（如 AXI），检查是否违反了协议时序约束。
- 如果不确定，先加一个 cover property 检验该输入组合是否可达。
