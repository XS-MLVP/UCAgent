
# 形式化验证总结

本阶段填写 `.formal_records.yaml.summary`，在Complete验收时生成 `05_{DUT}_formal_summary.md`。不要直接编辑派生报告。先调用 `RunFormal(action="status")` 获取当前输入的机器结果，再总结功能范围、Bug 和验证缺口；执行和暂缓规则见 `Guide_Doc/formal_execution.md`。

## 输入与完成条件

- 使用当前运行的机器统计、覆盖率、异常属性分析与 Bug 报告；不要修改机器统计或用文字补造证明结果。
- `summary` 必须包含非空 `core_function`、`overall_result`、`acceptance_conclusion`，以及 `completeness.safety`、`completeness.liveness`、`completeness.cover`。
- 可提供 `coi_assessment.unreachable_notes` 列表；没有说明时使用空列表。严重缺陷汇总从已核验Bug记录派生，不提交severe_bugs或重复维护汇总表字段。
- 仍有暂缓属性时，`overall_result` 或 `acceptance_conclusion` 必须明确包含 `UNPROVEN`，说明风险与恢复条件，不能称为全部通过。机器状态和暂缓清单会自动写入报告。
- `proof_complete` 表示全部目标已有判定，不表示没有反例；FALSE 仍须区分环境问题与 RTL 缺陷。COI 覆盖率不等于目标全部已证明。
- 数据技能可用时，经RunSkillScript调用inspect summary并通过JSON请求文件批量update；关闭或缺失技能时用普通文件工具维护相同summary字段。两条路径都核对当前机器结果和Bug关联，登记阶段日志后Complete。

## 完整报告参考示例

下面展示一个已完成处置、但仍有一条 UNPROVEN 目标的完整报告。真实统计、属性和路径必须来自工具，不能复制示例作为证据。报告的章节顺序与生成模板一致。

```markdown

# demo 形式化验证总结报告

> 本文档由 `.formal_records.yaml` 自动生成，请勿手动编辑。

## 1. 验证实施概况

- **被测模块**: demo
- **核心功能**: FIFO 入队、出队与顺序保持
- **工具引擎**: FormalMC
- **测试结果（人工分析）**: 局部控制已证明，顺序保持目标仍为 UNPROVEN。

## 当前输入机器证明状态

- **证明结论全部已判定**: 否；存在未证明属性
- **已证明**: 1
- **反例**: 0
- **静态契约失败 (TrivF)**: 0
- **平凡证明（需按工具原因审核）**: 0
- **未证明**: 1
- **暂缓**: 1（仍为 UNPROVEN，不计入已证明）
- **机器证据报告**: `formal_test/formal_runs/0123456789abcdef0123456789abcdef/report.md`

**暂缓清单（仅展示部分；以机器证据报告为准）**：

- `checker_inst.A_CK_ORDER`：未证明，需按记录中的条件恢复验证。

## 2. 断言与属性统计

| 属性类型 | 提取自 Checker (总数) | Log (Pass) | Log (Fail) | Log (Trivially_True) | 覆盖率(Cover) |
|----------|-----------------------|------------|------------|----------------------|---------------|
| Assume   | 1 | 无数据 | 无数据 | 无数据 | - |
| SVA (CK) | 2 | 1 | 0 | 0 | - |
| Cover    | 1 | - | - | - | 1/1 |

## 3. COI 覆盖率报告 (Cone-Of-Influence)

| 类型 | 目标总数 | 已覆盖数 | 未覆盖数 | 覆盖率 |
|------|----------|----------|----------|--------|
| Net  | 10 | 10 | 0 | 100.0% |
| Dff  | 2 | 2 | 0 | 100.0% |

**未覆盖信号说明：**

- 没有未覆盖的结构信号；这不消除顺序保持属性的证明缺口。

## 4. 验证完备性评估

### 4.1 Safety (安全性) 评估

入队控制已证明；顺序保持属性暂缓，不能据此断言 FIFO 全部行为正确。

### 4.2 Liveness (活跃性) 评估

当前目标未覆盖完整的无饥饿证明，需在后续验证规划中补充。

### 4.3 Cover (可达性) 评估

关键入队状态已可达；可达性结果不能代替顺序保持证明。

## 5. 发现的严重漏洞汇总

| Bug ID | 类型 | 描述 | Checker 关联 |
|--------|------|------|--------------|

## 6. 验收结论

验证仍不完整：checker_inst.A_CK_ORDER 为 UNPROVEN。待辅助状态不变量独立证明后重新激活，不建议将本报告作为完整功能正确性的证明。
```
