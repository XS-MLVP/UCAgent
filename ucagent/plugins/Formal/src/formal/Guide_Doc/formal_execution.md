
# 形式化批次运行与慢属性处置

本指南用于当前 DUT 的受管理形式化验证。先通过可选ext/formal/data技能或普通文件工具维护属性，完整数据例子见 `Guide_Doc/formal_data.md`；`RunFormal(action="run")` 自动生成环境并启动证明，不需要技能脚本。`Check` / `Complete` 核验当前输入证据，不启动长时间验证。

## 基础预检与功能批次

1. 在属性计划中用 `baseline: true` 标识共用基础 Assert/Cover。所有 Assume 都属于基础。第 5 阶段实现这些目标，用 `RunFormal(action="preflight")` 编译，并检查标记为基础的 Cover。通过阶段检查后冻结基础表达式、时钟复位、参数、绑定和 Tcl 配置。确需修订时回到第 5 阶段，修订 YAML 后重新预检与验收。
2. 第 6 阶段按 FC 编写与定向运行。用 `RunFormal(action="run", scope="selected", fc_id="FC-...")` 执行该 FC 已实现的功能 Assert/Cover，或改用 `ck_ids=["CK-..."]` 指定已实现的子集。未实现的 FC 检查列在 `unimplemented_ck_ids`。同批保留完整基础假设。用运行 ID 和枚举出的完整属性名查证据、审阅和取消。原 CK 改写时保留 ID，拆分时记录补充目标及其证明关系。
3. 第 7 阶段对当前输入运行完整批次，再分析反例、恒真和覆盖缺口。修改功能属性时复用同样的定向验证流程。完整验收以当前输入的完整批次为依据。

`RunFormal(action="pending")` 按 FC 的审阅顺序列出当前基线下的待复验 CK。修改部分属性时，提交首个可运行批次的 `run_call`。基线发生变化时重新预检；存在自定义 Tcl 且 Checker 变化时，将相关定向结果重新核对。

## 时间预算和结果收集

工作流配置 `runtime_options.formal_execution` 定义预算：`first_pass_budget_s` 默认为 300 秒，`analysis_threshold_s` 默认为 1200 秒，`max_active_workers` 默认为 2，`slow_queue_max_workers` 默认为 1，`property_cumulative_budget_s` 默认为 3600 秒。每个属性先获得独立的 300 秒首轮求解机会；若未完成，再进入慢属性队列，第二轮预算为累计阈值的剩余部分（默认 900 秒）。两轮是独立的求解尝试，不会保留上一轮求解器的搜索进度；需要一次不间断的更长求解时，先分析并记录 retry，下一轮可获得更长的不间断预算。只有实际求解时间计入属性累计预算，排队和环境准备时间不算。工具发布 5/20 分钟检查点，但结果可能提前产生；快队列优先分配，每个慢属性的求解不会使其他待执行属性永久排队。

当前工作流在定向批次的快队列中最多让两个断言共享已初始化的会话。每个 CK 单独启动计时并保存日志和波形。完整批次、基础 Cover、慢属性及含自定义 Tcl 的批次使用独立进程。`session_max_properties: 1` 可关闭定向会话复用。

执行顺序：

1. 调用 `RunFormal(action="run")`。同一运行范围和当前输入遇到带源码定位的编译错误时，重复提交会返回原诊断。按 `diagnostics` 修复输入后再提交；如果是操作员已修复外部编译条件，可用 `retry_prepare=true` 重新尝试。输入改变时，先确认旧运行已结束，必要时调用 `RunFormal(action="cancel")`。
2. 用 `RunFormal(action="status")` 等待新结果并获取快照，请求默认最多300秒，也可传 `wait_s=0` 立即查询；实际等待受当前工具调用预算限制并预留返回时间。检查 `status`、`counts`、`states`、`review_queue` 与 `report`，避免频繁轮询。运行中不修改证明输入，结束或取消后用可选数据技能或普通文件工具提交新版本。
3. 某条属性 20 分钟仍未解决，应检查本次报告与属性逻辑锥、约束、时钟/复位、证明深度；说明观察与假设的区别。优先尝试保持原验证目标的辅助不变量或经证实的证明策略，不能将超时解释为 RTL Bug，也不能增加无规格依据的 assume。
4. 使用 `RunFormal(action="review", property_names=["完整属性名"], disposition="retry", reason="分析依据", next_action="下步动作")` 在当前输入下重新尝试；或用 `disposition="defer"` 明确暂缓，写清未完成风险、恢复条件和下一步动作。达到分析阈值进入 `REVIEW` 就可暂缓，结果依旧是 `UNPROVEN`。有明确依据时，retry 可通过 `retry_budget_s` 指定下一次连续求解的秒数，受剩余累计预算约束。
5. 所有未解决项都有可验证的处置后，登记阶段日志并调用 `Complete`；仅在定位实际缺口时调用Check。一旦修改 RTL、约束或 SVA，旧结果仅供参考，必须通过 `RunFormal(action="run")` 获取当前输入的新证据。

`PROVEN` 是完成证明；`FALSIFIED` 是找到反例，需核对真实输入、参考计算和实际输出再归因；`TRIVIALLY_FALSE` 是常量/静态失败，不能通过改弱验证目标消除。`TRIVIALLY_TRUE` 先检查工具原因与前提可达性，可能是正确恒等式，不一律判为过约束。`UNPROVEN` 表示尚无结论。Cover结果单独统计。`NEEDS_OPERATOR` 表示工具或结果处理问题：按返回动作请求修复，不能改写断言冒充解决。`proof_complete: false` 的未证明缺口即使已暂缓也必须披露。通过 `RunFormal(action="evidence",property_names=["精确完整属性名"])` 取得当前证据引用，不手工编辑运行报告、状态、计数或收据。

## 原生诊断

通过 `AnalyzeFormal(mode="environment", run_id=...)` 核对指定运行中工具识别的时钟、复位与约束。复位释放或基础事务可达性异常时，可用 `mode="overconstraint"` 做有界搜索，`depth` 默认 10。诊断只覆盖返回的搜索深度。

对 `TRIVIALLY_TRUE` 或慢断言，用 `mode="sanity"` 检查空泛性，或用 `mode="fanin"` 查看断言依赖信号，同时带上精确的 `property_name`。结果包含原始日志和对应运行 ID，证明状态仍以原运行报告为准。

- 修改安全断言后，可用 `AnalyzeFormal(mode="replay", run_id=原批次, property_name=原属性名)` 先重现原失败，再在同一反例上检查当前 CK。支持显式单时钟、单比特布尔式、`|->`、`|=>` 与一拍 `$past`。证据不足时，直接定向求解。回放成功仅记录该轨迹的观察结果。
- 对已报告为 `COVER_UNREACHABLE` 的 Cover，用 `mode="unreachable"` 在原输入上进行有界复核和原生解释。复核失败或超时保留原批次状态；解释供审阅和设计进一步对照使用。
- 对慢断言，可用 `mode="bounded_search"` 请求一次有界反例搜索。默认深度 20，读取工具报告的实际深度和反例。即使在该深度未找到反例，仍以正式批次的证明结果为准。

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
