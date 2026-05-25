# Bug 报告领域知识参考

> **本文档是 RTL 缺陷分析与报告阶段的领域知识参考。**
>
> - **数据写入方式**: 通过 `init_bug_report.py` 从 `.formal_records.yaml` 的 `analysis.fa_entries` 中提取 `RTL_BUG` 属性并生成骨架，再用 `update_bug.py` 逐条填写详情，数据存储在 `.formal_records.yaml` 的 `bugs` 字段中。
> - **文档自动生成**: Checker 通过后自动从 JSON 生成 `04_{DUT}_bug_report.md`，**无需手动编写 Markdown**。

---

## BG 标签命名规范

| 前缀 | 类型 | 示例 |
|------|------|------|
| BG-SUM- | 求和/算术相关 | BG-SUM-WIDTH-001 |
| BG-FSM- | 状态机相关 | BG-FSM-DEAD-001 |
| BG-INTF- | 接口协议相关 | BG-INTF-HANDSHAKE-001 |
| BG-LOGIC- | 通用逻辑相关 | BG-LOGIC-OVERFLOW-001 |
| BG-MEM- | 存储/FIFO相关 | BG-MEM-CORRUPT-001 |

---

## Bug 条目必需字段

通过 `update_bug.py` 填写每个 bug 时，以下字段全部必填：

| 字段 | 说明 |
|------|------|
| `fg_id` | 功能组标签（来自 spec） |
| `fc_id` | 功能点标签（来自 spec） |
| `rtl_file` | 缺陷所在的 RTL 文件路径 |
| `rtl_line` | 缺陷所在行号 |
| `description` | 问题描述：什么条件下触发了错误 |
| `root_cause` | 根本原因：RTL 代码中的逻辑错误分析 |
| `trigger` | 触发条件：输入组合或状态序列 |
| `expected` | 预期行为：规格要求的正确表现 |
| `actual` | 实际行为：当前 RTL 的错误表现 |
| `fix` | 修复建议：具体的逻辑修改方案 |
| `severity` | 影响范围：`HIGH` / `MEDIUM` / `LOW` |
| `confidence` | 置信度：`HIGH` / `MEDIUM` / `LOW` |

---

## 故障归因与聚类

在实际 formal 项目中，一个 RTL 缺陷经常导致**多个属性同时 FALSE**（例如一个位宽错误影响所有用到该信号的断言）。不要逐条独立分析，应先做归因聚类：

### 归因步骤

1. **列出所有 RTL_BUG 属性的失败信号**：检查每个反例中，最终导致断言违反的信号是什么。
2. **按共同信号分组**：如果多个属性的违反都涉及同一个 RTL 信号（例如 `sum[7:0]` 被截断），它们大概率是同一个 bug。
3. **选一个代表属性做详细分析**：写清反例波形、根因、修复建议。
4. **其余同组属性引用代表分析**：`根因同 <BG-XXX>，此处省略重复分析`。

### 根因分析总结表

当报告中出现 3 个以上 RTL_BUG 时，**必须**在报告末尾填写总结表：

| 根因编号 | 影响的属性数 | 根因描述 | 修复方案（一句话） |
|---|---|---|---|
| ROOT-1 | 5 | sum 信号位宽不足导致截断 | 修改 Adder.v 第10行：扩展 sum 为 N+1 位 |
