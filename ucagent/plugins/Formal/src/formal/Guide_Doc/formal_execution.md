
# 形式化批次运行与慢属性处置

本指南用于当前 DUT 的受管理形式化验证。先通过可选ext/formal/data技能或普通文件工具维护属性，完整数据例子见 `Guide_Doc/formal_data.md`；`RunFormal(action="run")` 自动生成环境并启动证明，不需要技能脚本。`Check` / `Complete` 核验当前输入证据，不启动长时间验证。

## 工具冒烟与正式功能批次

1. 第 5 阶段调用 `RunFormal(action="preflight")`。工具在独立目录生成临时最小环境和冒烟属性，编译当前 RTL、展开有效参数与接口，并检查求解器能启动。无需填写正式 CK 表达式，不采用正式 Assume/Assert/Cover；临时结果不计入正式 CK、Bug 分析或覆盖率。用返回的 run_id 查询 status，成功后记录日志并 Complete。它不证明复位行为、环境约束合理或设计功能正确。
2. 第 6 阶段独立实现正式环境义务与功能属性，不复制冒烟表达式。先按规划实现正式 Assume，再按 FC 编写 Assert/Cover；`RunFormal(action="run", scope="selected", fc_id="FC-...")` 运行该功能点，或用 `ck_ids=["CK-..."]` 复验子集。各批采用已实现的全部正式 Assume，缺少正式环境义务时先补齐，不默默忽略。未选功能目标保持未执行。
3. 使用 `RunFormal(action="pending")` 获取 `current_fc`：只实现这个 FC，运行并处理其异常后再进入下一个，不提前实现全量目标。用 `RunFormal(action="review_fc", fc_id=..., reviews=...)` 登记每个异常的当前 `ck_id`、`run_id`、`classification` 和 `reason`；请求形状采用返回模板。环境/属性未解决时分类为 `ENV_PENDING` 并继续当前 FC 的修复，不能关闭。真实失败可记录 `RTL_BUG` 候选，平凡证明为 `DESIGN_EXPECTED`，不可达 Cover 为 `COVER_EXPECTED_FAIL`，这些人工解释不是独立证实 Bug 的保证。未证明目标经 RunFormal review 明确 defer 后保留缺口，不能改称 Pass。
4. 第 7 阶段运行当前正式输入的完整回归，以覆盖缺口和组合结果差异收尾。变更的目标先定向复验，再完整回归；已有分析只有在当前证据与规格关系仍适用时复用。不能凭 COI/Cover 或全部有判定宣称规格没有遗漏。

后续各批都会自动做语法、接口和绑定预检。正式属性或 Assume 可以依据规格修订，修复循环留在当前阶段，不因它们变化跳回第 5 或第 6 阶段；共享假设、RTL、参数、复位或绑定改变后，需重新验证受影响目标。`RunFormal(action="pending")` 按 FC 顺序给出当前公共输入下待复验目标和可直接提交的 `run_call`，历史成功不能支持变化后的前提。完整验收始终读取当前输入的完整批次。

## 单个 FC 异常审阅请求

使用 `pending` 返回的目标与当前证据填写请求。下面是完整的一次 FC 审阅请求；实际 ID 和运行 ID 必须来自当前结果，不能照抄示例值：

```json
{
  "action": "review_fc",
  "fc_id": "FC-PACKET-READY",
  "reviews": [
    {
      "ck_id": "CK-PACKET-READY-EQUATION",
      "run_id": "0123456789abcdef0123456789abcdef",
      "classification": "DESIGN_EXPECTED",
      "reason": "该组合关系与接口规格的 ready 定义一致；报告为常量传播后的恒等式，不能代替请求最终完成的时序要求。"
    }
  ]
}
```

PROVEN 和 COVER_REACHED 不需要填人工审阅。异常解释绑定到当前目标和原始证据；环境、属性或相关输入变化后，以 `pending` 返回的失效项为准重新处理。第 7 阶段可读取适用的局部审阅作为上下文，但最终分析仍需核对当前完整批次的证据和规格关系，不能把局部候选分类直接当正式 Bug。

## 时间预算和结果收集

工作流配置 `runtime_options.formal_execution` 定义预算：`first_pass_budget_s` 默认为 300 秒，`analysis_threshold_s` 默认为 1200 秒，`max_active_workers` 默认为 2，`slow_queue_max_workers` 默认为 1，`property_cumulative_budget_s` 默认为 3600 秒。每个属性先获得独立的 300 秒首轮求解机会；若未完成，再进入慢属性队列，第二轮预算为累计阈值的剩余部分（默认 900 秒）。两轮是独立的求解尝试，不会保留上一轮求解器的搜索进度；需要一次不间断的更长求解时，先分析并记录 retry，下一轮可获得更长的不间断预算。证明请求开始后的墙钟耗时计入属性累计预算，可能包含求解器等待许可的时间。排队和环境准备不计。工具发布 5/20 分钟检查点，但结果可能提前产生；快队列优先分配，每个慢属性的求解不会使其他待执行属性永久排队。

当前工作流在定向批次的快队列中最多让两个断言共享已初始化的会话。每个 CK 单独启动计时并保存日志和波形。完整批次、临时冒烟、慢属性及含自定义 Tcl 的批次使用独立进程。`session_max_properties: 1` 可关闭定向会话复用。

执行顺序：

1. 调用 `RunFormal(action="run")`。同一运行范围和当前输入遇到带源码定位的编译错误时，重复提交会返回原诊断。按 `diagnostics` 修复输入后再提交；如果是操作员已修复外部编译条件，可用 `retry_prepare=true` 重新尝试。输入改变时，先确认旧运行已结束，必要时调用 `RunFormal(action="cancel")`。
第 6 阶段的定向验证用 `review_queue[].max_retry_budget_s` 显示可请求的重试时长。每次重试最多使用一次首轮预算，当前输入的累计上限为分析阈值加一次首轮预算（默认 25 分钟），同时受全局累计预算限制。余额为 0 的未证明目标应记录结论、依据与恢复条件，并在第 7 阶段的完整验证中复核。

2. 用 `RunFormal(action="status")` 等待新结果并获取快照，请求默认最多300秒，也可传 `wait_s=0` 立即查询；实际等待受当前工具调用预算限制并预留返回时间。检查 `status`、`counts`、`states`、`review_queue` 与 `report`，避免频繁轮询。运行中不修改证明输入，结束或取消后用可选数据技能或普通文件工具提交新版本。
3. 某条属性 20 分钟仍未解决，应检查本次报告与属性逻辑锥、约束、时钟/复位、证明深度；说明观察与假设的区别。优先尝试保持原验证目标的辅助不变量或经证实的证明策略，不能将超时解释为 RTL Bug，也不能增加无规格依据的 assume。
4. 使用 `RunFormal(action="review", property_names=["完整属性名"], disposition="retry", reason="分析依据", next_action="下步动作")` 在当前输入下重新尝试；或用 `disposition="defer"` 明确暂缓，写清未完成风险、恢复条件和下一步动作。达到分析阈值进入 `REVIEW` 就可暂缓，结果依旧是 `UNPROVEN`。没有新诊断或策略时优先暂缓并推进下一个 FC，不能仅因相似目标通过就延时重试。有明确依据时，retry 可通过 `retry_budget_s` 指定下一次连续求解的秒数，受剩余累计预算约束。
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
