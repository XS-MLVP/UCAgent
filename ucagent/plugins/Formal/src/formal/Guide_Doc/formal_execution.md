
# 形式化批次运行与慢属性处置

本指南用于当前 DUT 的受管理形式化验证。先通过可选ext/formal/data技能或普通文件工具维护属性，完整数据例子见 `Guide_Doc/formal_data.md`；`RunFormal(action="run")` 自动生成环境并启动证明，不需要技能脚本。`Check` / `Complete` 核验当前输入证据，不启动长时间验证。

## 时间预算和结果收集

工作流配置 `runtime_options.formal_execution` 定义预算：`first_pass_budget_s` 默认为 300 秒，`analysis_threshold_s` 默认为 1200 秒，`max_active_workers` 默认为 2，`slow_queue_max_workers` 默认为 1，`property_cumulative_budget_s` 默认为 3600 秒。每个属性先获得独立的 300 秒首轮求解机会；若未完成，再进入慢属性队列，第二轮预算为累计阈值的剩余部分（默认 900 秒）。两轮是独立的求解尝试，不会保留上一轮求解器的搜索进度；需要一次不间断的更长求解时，先分析并记录 retry，下一轮可获得更长的不间断预算。只有实际求解时间计入属性累计预算，排队和环境准备时间不算。工具发布 5/20 分钟检查点，但结果可能提前产生；快队列优先分配，每个慢属性的求解不会使其他待执行属性永久排队。

执行顺序：

1. 调用 `RunFormal(action="run")`。同一输入再次调用不会重复启动；若输入改变，应先确认旧运行已结束，必要时调用 `RunFormal(action="cancel")`。
2. 用 `RunFormal(action="status")` 等待新结果并获取快照，请求默认最多300秒，也可传 `wait_s=0` 立即查询；实际等待受当前工具调用预算限制并预留返回时间。检查 `status`、`counts`、`states`、`review_queue` 与 `report`，避免频繁轮询。运行中不修改证明输入，结束或取消后用可选数据技能或普通文件工具提交新版本。
3. 某条属性 20 分钟仍未解决，应检查本次报告与属性逻辑锥、约束、时钟/复位、证明深度；说明观察与假设的区别。优先尝试保持原验证目标的辅助不变量或经证实的证明策略，不能将超时解释为 RTL Bug，也不能增加无规格依据的 assume。
4. 使用 `RunFormal(action="review", property_names=["完整属性名"], disposition="retry", reason="分析依据", next_action="下步动作")` 在当前输入下重新尝试；或用 `disposition="defer"` 明确暂缓，写清未完成风险、恢复条件和下一步动作。暂缓仅在预算耗尽后可用，结果依旧是 `UNPROVEN`。
5. 所有未解决项都有可验证的处置后，登记阶段日志并调用 `Complete`；仅在定位实际缺口时调用Check。一旦修改 RTL、约束或 SVA，旧结果仅供参考，必须通过 `RunFormal(action="run")` 获取当前输入的新证据。

`PROVEN` 是完成证明；`FALSIFIED` 是找到反例，需核对真实输入、参考计算和实际输出再归因；`TRIVIALLY_FALSE` 是常量/静态失败，不能通过改弱验证目标消除。`TRIVIALLY_TRUE` 先检查工具原因与前提可达性，可能是正确恒等式，不一律判为过约束。`UNPROVEN` 表示尚无结论。Cover结果单独统计。`NEEDS_OPERATOR` 表示工具或结果处理问题：按返回动作请求修复，不能改写断言冒充解决。`proof_complete: false` 的未证明缺口即使已暂缓也必须披露。通过 `RunFormal(action="evidence",property_names=["精确完整属性名"])` 取得当前证据引用，不手工编辑运行报告、状态、计数或收据。

## 完整报告示例

以下仅示意报告的**完整布局**，真实属性、时间和结果必须来自 `RunFormal(action="status")` 给出的 `report`，不能复制示例当作证据。

```markdown

# Formal execution report

## Run

- Run: `0123456789abcdef0123456789abcdef`
- State: `AWAITING_REVIEW`
- Fingerprint: `0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef`
- Proof complete: `false`
- Deferred: 1

## Results

| Property | Result | State | Active seconds | Disposition |
| --- | --- | --- | ---: | --- |
| `demo_wrapper.checker_inst.A_CK_READY` | PROVEN | RESOLVED | 1.20 | - |
| `demo_wrapper.checker_inst.A_CK_ORDER` | UNPROVEN | REVIEW | 1200.00 | DEFERRED |

## Decisions

- `demo_wrapper.checker_inst.A_CK_ORDER`: defer — 逻辑锥包含存储状态，经过两轮仍未解决；保持验证缺口; next: 核对约束与状态不变量，再开启新一轮证明

## Evidence

- `state.json`: current machine results and attempt references.
- `snapshots/`: immutable checkpoint results.
- `attempts/`: isolated FormalMC reports and logs.
```

最终 `05_{DUT}_formal_summary.md` 必须分别报告已证明、反例、空泛通过和未证明数量；如有暂缓项，说明未覆盖的验证目标与恢复条件，不能写“全部通过”。
