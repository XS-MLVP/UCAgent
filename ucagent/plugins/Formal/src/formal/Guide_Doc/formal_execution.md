# 形式化批次运行与慢属性处置

## 分批实现与慢目标

6.1 的 Check 按固定的第 4 阶段规划生成 `formal_runs/case_templates.json`。每个模板都有 FG、FC、CK、原规格描述、类型和属性标签。模板占位不生成正式求解结论。6.2 先完成有规格依据的公共 Assume，再按 `case_batch.prepare_call` 领取最多 10 条正式目标。填写本页缺失的 SVA 后按 `case_batch.run_call` 验证。快速失败由所属 FC 修复属性或环境，或根据真实反例记录问题。

6.2 和 7 的每个求解窗口最多 10 项、20 分钟墙钟，含准备与受控退出预留。进入原生求解后仍未决的目标记录为 UNPROVEN，未获得运行机会的目标继续排队。基础设施错误需先修复。定向批与完整回归分别保留输入版本、尝试和运行日志。第 7 阶段仍在当前正式环境下完整清点目标并计算原生覆盖率。已标记慢目标只有在共享环境、目标及原始日志校验一致时才可沿用 UNPROVEN，完整回归明确区分本轮实际执行与引用的缺口。

第 8 阶段集中复核仍未决的目标。用 `RunFormal review` 记录保留风险及恢复条件，或在原目标上显式指定 `retry_engine` 尝试新策略。修改性质或公共输入会重新触发适用的证明、覆盖和分析检查。只有当前原生 Cover 结论可支持“不可达”。第 9 阶段按证据完成反例、缺陷分析与总结。

本指南用于当前 DUT 的受管理形式化验证。先通过可选ext/formal/data技能或普通文件工具维护属性，完整数据例子见 `Guide_Doc/formal_data.md`；`RunFormal(action="run")` 自动生成环境并启动证明，不需要技能脚本。`Check` / `Complete` 核验当前输入证据，不启动长时间验证。

## 工具冒烟与正式功能批次

1. 第 5 阶段调用 `RunFormal(action="preflight")`。工具在独立目录读取当前 RTL、有效参数和端口时钟复位，生成临时最小环境和工具链 Cover。正式 CK、白盒绑定和额外证明 Tcl 由第 6 阶段验证。用返回的 run_id 查询 status，成功后记录日志并 Complete。临时结果只说明编译、展开和求解器启动状态。
2. 第 6.2 阶段先实现正式 Assume。若固定规划明确要求指定复位脚在首个采样点有效，核对 `prepare sva` 提供的 `initial_reset` 元数据和正文后一起提交。工具为首拍监视器生成初始条件。核查反例时，`items[].reset_context`给出本批复位脚、有效电平及原生日志中的首拍监视器记录。释放可达与首拍有效分别核验。
3. `RunFormal(action="pending")` 返回当前 `case_batch`。补齐本页正式目标后按它给出的调用定向验证。用 `review_fc` 登记异常的 CK、批次、证据与原因。已定位的环境或属性问题在当前阶段修复。有效反例可登记为 RTL_BUG 候选，进入第 9 阶段时结合规格和独立证据确认。旧任务没有模板回执时，按 `current_fc` 完成单个 FC 的闭环。
4. 第 7 阶段运行当前正式输入的完整回归，以覆盖缺口和组合结果差异收尾。变更的目标先定向复验，再完整回归；已有分析只有在当前证据与规格关系仍适用时复用。不能凭 COI/Cover 或全部有判定宣称规格没有遗漏。

后续各批都会自动做语法、接口和绑定预检。正式属性或 Assume 可以依据规格修订，修复循环留在当前阶段。共享假设、RTL、参数、复位或绑定改变后，需重新验证受影响目标。`RunFormal(action="pending")` 按 FC 顺序给出待复验 CK 和可直接提交的 `run_call`。慢目标到达审阅点后，`slow_review` 给出本目标已用求解时间和 `defer_call`，填写验证缺口与恢复条件后可提交暂缓。未证明或有界搜索未见反例不能排除 RTL、环境或属性问题。完整验收始终读取当前输入的完整批次。

## 单个 FC 异常审阅请求

第 6 阶段的 `slow_review` 和第 7 阶段的 `review_queue` 会为已规划的目标提供 `proof_history`。其中 `root_ck_id` 标识原目标，`solver_seconds` 与 `attempts` 按定向和完整回归分别统计原目标及其派生 CK 的已结束求解。更改正式输入会使旧证据失效，实际消耗仍计入历史。此统计不包含准备、排队、冒烟和诊断，不改变当前证明结论或本批次剩余预算。

第 4 阶段 Complete 会留存原目标描述、CK ID、FC 归属和派生关系。第 6、7 阶段修复属性或环境时保留原 Assert/Cover 目标，新增派生 CK 明确填写 `parent_ck_id`，新增覆盖目标记录规格依据。定向运行和完整验收会核对原证明目标的类别和父关系。原描述可用于审核属性、FC 归属及共享 Assume 的规格修订。

批次运行中按 `status_call` 等新进度。有可审阅的慢目标时立即返回，即使其他目标仍在执行。第 6 阶段当前定向批次停止后，`status` 随结果返回 `fc_progress`，可直接按当前 FC 的下一步继续。待审目标存在原始 VCD 时，使用 `trace_call` 获取准确批次与信号列表，再用 `trace_query` 提交完整信号路径列表 `signals` 和原生时间范围 `start`、`end`。波形采样可省略 `mode=samples`。

第 6.2、7 阶段把未决原生尝试及环境版本写入当前报告。新完整批次清点原始目标，并校验可引用的 UNPROVEN 记录；环境或目标失效时重新执行。第 8 阶段结合目标及其派生 CK 的累计记录选择复核策略。

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

默认配置的首轮求解预算为 300 秒，最多并行 2 个工作进程。第 6.2、7 阶段另有每批 20 分钟墙钟上限，涵盖准备、排队、求解和受控退出。首次未决即记录并让其余目标继续。第 8 阶段有新诊断或策略时可显式重试，工具按目标记录求解时间和各阶段开销。旧工作区沿用原先的快慢队列及其预算。

当前工作流在定向批次的快队列中最多让两个断言共享已初始化的会话。每个 CK 单独启动计时并保存日志和波形。完整批次、临时冒烟、慢属性及含自定义 Tcl 的批次使用独立进程。`session_max_properties: 1` 可关闭定向会话复用。

若原生日志显示在验证启动前等待许可证，工具会单独记录该等待。存在并行作业时，当前批次改为单进程，并按原预算补做该目标的一次尝试。许可证等待不扣除求解预算。许可证仍不可用时，从返回的工具错误和原始日志处置后重试。

工具超时时先查当前报告。批次的 `inventory_timing.timeout_phase` 记录编译准备、结果枚举或退出阶段。属性尝试的 `attempt_console` 提供具体日志。已收到求解结束信号后，写报告或退出超时属于工具错误，等待时间不计入求解预算。修复对应阶段的工具问题后再复验。

执行顺序：

1. 调用 `RunFormal(action="run")`。同一运行范围和当前输入遇到带源码定位的编译错误时，重复提交会返回原诊断。按 `diagnostics` 修复输入后再提交；如果是操作员已修复外部编译条件，可用 `retry_prepare=true` 重新尝试。输入改变时，先确认旧运行已结束，必要时调用 `RunFormal(action="cancel")`。
2. 第 6 阶段按返回的 `run_call` 启动定向批次并最多等待 5 秒。短批次可直接返回 `fc_progress`，长批次按 `status_call` 继续等新结果。`status` 默认最多等待 300 秒，`wait_s=0` 立即查询，实际等待受工具调用预算限制。检查 `status`、`counts`、`states`、`review_queue` 与 `report`。运行中保留当前证明输入，结束或取消后提交新版本。
3. 某条属性进入审阅仍未解决时，应检查本次报告与属性逻辑锥、约束、时钟/复位、证明深度；说明观察与假设的区别。优先尝试保持原验证目标的辅助不变量或经证实的证明策略，不能将超时解释为 RTL Bug，也不能增加无规格依据的 assume。
4. 第 6.2、7 阶段把已运行仍未决的性质及其日志转入第 8 阶段。第 8 阶段使用 `RunFormal(action="review", disposition="defer")` 按当前证据记录剩余风险、恢复条件及后续策略。有依据时用 `disposition="retry"` 在原目标上进行定向试验，可设置 `retry_budget_s` 及 `retry_engine="ind"` 或 `"pdrx"`。单目标引擎参数只作用于这次尝试。公共环境配置或性质有实质更改时重新核验受影响的义务。
5. 所有未解决项都有可验证的处置后，登记阶段日志并调用 `Complete`；仅在定位实际缺口时调用Check。一旦修改 RTL、约束或 SVA，旧结果仅供参考，必须通过 `RunFormal(action="run")` 获取当前输入的新证据。

`PROVEN` 是完成证明；`FALSIFIED` 是找到反例，需核对真实输入、参考计算和实际输出再归因；`TRIVIALLY_FALSE` 是常量/静态失败，不能通过改弱验证目标消除。`TRIVIALLY_TRUE` 先检查工具原因与前提可达性，可能是正确恒等式，不一律判为过约束。`UNPROVEN` 表示尚无结论。Cover结果单独统计。`NEEDS_OPERATOR` 表示工具或结果处理问题：按返回动作请求修复，不能改写断言冒充解决。`proof_complete: false` 的未证明缺口即使已暂缓也必须披露。通过 `RunFormal(action="evidence",property_names=["精确完整属性名"])` 取得当前证据引用，不手工编辑运行报告、状态、计数或收据。

## 原生诊断

当 `basic_info.clock_reset.reset_release` 声明为 `sync` 或 `async` 时，第 6 阶段关闭 FC 和第 7 阶段接受完整回归都要求正式环境下的复位释放可达。首个正式批次完成后，按状态中的 `environment_check.analyze_call` 调用 `AnalyzeFormal`。当前第 6 阶段的定向诊断返回 `fc_progress` 时，依其中给出的当前动作继续。工具复制冻结输入并加入临时 Cover，将原生结果保存在独立目录。验收验证原生日志，并在 RTL、接口、参数、时钟复位和 Assume 一致的批次之间复用诊断。自定义 Tcl 还要求检查器一致。不可达时核对启动、复位表达式与 Assume，修复后复验当前批次。未得到确定诊断时保持待审。展开后的释放事件可达性检查独立于 DUT 复位行为断言。

定向重验后，`prior_review_draft` 可显示相同性质、同一判定的旧审阅。失败反例的两份原始波形各自按原文件摘要核对。若证据只在 VCD 开头的导出时间有差异，工具会标记 `trace_payload=same_except_export_date`。复核旧说明与当前环境和证据的关系，使用 `review_call` 中当前批次的 ID 提交新审阅。

合法的工具结果揭示边界规格缺失时，使用 `SPEC_GAP`。用 `reason` 说明环境、属性与结果的证据，用 `spec_gap.requirement_ref`、`question` 和 `follow_up` 记录待确认的规则及后续复验。动态失败须有原始反例波形。此处置允许推进 FC，原属性和判定保留。已经定位的环境与属性错误继续按 `ENV_PENDING` 修复。第 7 阶段用本次完整批次重新核对并绑定仍开放的规格缺口。

通过 `AnalyzeFormal(mode="environment", run_id=...)` 核对指定运行中工具识别的时钟、复位与约束。复位释放或基础事务可达性异常时，可用 `mode="overconstraint"` 做有界搜索，`depth` 默认 10。诊断只覆盖返回的搜索深度。

对 `TRIVIALLY_TRUE` 或慢断言，用 `mode="sanity"` 检查空泛性，或用 `mode="fanin"` 查看断言依赖信号，同时带上精确的 `property_name`。结果包含原始日志和对应运行 ID，证明状态仍以原运行报告为准。

- 修改安全断言后，可用 `AnalyzeFormal(mode="replay", run_id=原批次, property_name=原属性名)` 先重现原失败，再在同一反例上检查当前 CK。支持显式单时钟、单比特布尔式、等位宽信号比较、`|->`、`|=>` 与可回放表达式的一拍 `$past`。遇到未知位或无法精确绑定的信号时保留证据不足状态。回放记录该轨迹的观察结果，修订后的目标仍进行定向求解。
- 对已报告为 `COVER_UNREACHABLE` 的 Cover，用 `mode="unreachable"` 在原输入上进行有界复核和原生解释。复核失败或超时保留原批次状态；解释供审阅和设计进一步对照使用。
- Check 按当前完整批次的原生 COI 报告接受结构覆盖。报告缺失或失效时，提交返回的 `refresh_call` 给 `AnalyzeFormal`。工具从同一完整批次恢复报告，并保留该批的原有判定。恢复后重新 Check；若验证输入已改动，先跑新版本完整回归。
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
