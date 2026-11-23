
# Formal 任务数据

任务数据存放在 `.formal_records.yaml`。用 `FormalData` 检查、领取和更新任务数据。`RunFormal` 负责证明和真实证据，`Complete` 验收并推进，`Check` 定位缺口。

## 直接调用 FormalData

先检查当前规划字段：

```json
{"request":{"action":"inspect","section":"planning"}}
```

将填好的 `ready_update` 字段放到 `request`，增加 `"action":"update"` 后一次提交。使用返回的 `expected_sha256` 检查版本。用 `{"request":{"action":"prepare","section":"sva","assumptions":true,"limit":20}}` 领取共享 Assume。所有调用共用下文的数据契约，数据技能与普通文件工具仍可用于同一任务。

第 3 阶段在 CK 描述中注明内部观测需求。第 4 阶段用 `inspect signals` 查实际顶层信号，按需复制其中的 `whitebox_declaration` 到 `spec.whitebox_signals`。工具使用有效参数展开位宽并保留索引方向和符号。子模块层级路径和需要特殊类型的观测应单独记录依赖，当前顶层绑定要求信号使用与 RTL 相同的名字。

## 使用数据技能

需要使用数据技能时，先ListSkill并读取`.ucagent/skills/ext/formal/data/SKILL.md`；默认阶段没有强制技能列表，不要求每阶段重复加载或SetSkillUsage。所有脚本调用沿用原有RunSkillScript格式：

```json
{"commands":[["ext/formal/data","formal_data.py","inspect planning"]]}
```

`inspect planning|basic_info|spec|analysis|bugs|summary|overview`默认只读查看缺项、必要上下文、分页与sha256，不重复展开已有作者正文。需要复核或修订已有内容时加`--full`，需要完整字段契约时加`--schema`（所有节均支持）；优先使用默认视图，不为可选事实表重复填写全部数据。`--offset/--limit`用于列表分页，按返回next_offset继续；截断预览不能当作完整值覆盖。basic_info中clock_count未知应待核实，明确无时钟才填0。

`inspect spec`还给出从实际RTL解析的`effective_interface`：真实声明默认参数、覆盖后的有效值与端口宽度/符号。`spec.parameters`只填写有意的显式整数覆盖；留空使用真实声明默认值，派生参数随基础参数覆盖重新计算。`basic_info.parameters/ports`是说明数据，不控制生成绑定；不要通过改说明中的位宽修复生成错误。无法解析时按返回的来源或spec.parameters位置处理，不猜模块专属默认值。

使用普通`EditTextFile`在输出目录写一个JSON请求文件，例如`formal_test/data_update.json`，再调用：

```json
{"commands":[["ext/formal/data","formal_data.py","update --request-file formal_test/data_update.json"]]}
```

请求文件是结构化对象，不拼接shell内嵌JSON或逐字段set命令。例子展示完整的批量body请求形状；真实哈希必须替换为最近inspect/prepare返回值：

```json
{
  "section":"spec",
  "expected_sha256":"从最近inspect取得的64位小写哈希",
  "bodies":{"CK-PACKET-ELIGIBLE":"(eligible == request);"}
}
```

更新指定节时使用 `data` 或 `bodies`。planning/basic_info/spec/summary 仅替换提供的顶层字段，嵌套对象和列表整体替换。第 3、4 阶段保存 spec 后，使用 `planned_scope` 核对 FG、FC 和各类 CK 数量，审阅当前阶段要求后记录日志并调用 Complete。第 5 阶段直接用 RunFormal preflight 做独立工具冒烟，不领取或实现正式 CK。第 6 阶段先用 `prepare sva --assumptions --limit 20` 完成正式环境 Assume，再用 `prepare sva` 按 FC 审阅顺序领取正式检查点，当前 FC 由 RunFormal pending 返回，未关闭前不得提前实现后续 FC；可用 `--function FC-<ID>` 领取当前功能点。运行后按 pending 的 review_fc 请求模板处理异常，ENV_PENDING 需在当前阶段修复。将实现填入 `ready_update.bodies`。用 `inspect ports --query 名称片段1,名称片段2` 查看端口方向和位宽，用 `inspect signals --query 名称` 查实际内部信号与位宽。更新绑定时，可在同一 spec 请求里同时写 `data.whitebox_signals` 和 `bodies`，两者一起校验和提交。更新后使用返回的新 sha256 和待办继续。移除或改写目标及修改 Assume 时，审阅 `scope_review` 并在阶段日志中记录理由。

在 `basic_info.clock_reset` 中分别填写 `reset_active_level`（low/high）、`reset_assertion` 和 `reset_release`（sync/async）。字段可在未确定时留空，`reset_type` 可说明 RTL 行为。

## 初始复位

仅在规格要求验证起点处于复位时，为对应的单条 `Assume` 设置 `initial_reset: true`。第 4 阶段记录规格依据，第 6 阶段用 `prepare sva` 提供的正文。FormalMC 初始化验证专用标记，标记经过第一个时钟采样后清零，Assume 只在该采样约束复位。工具检查标记的原生初始化记录。顶层复位极性使用已配置的映射；释放后的行为按原规格分别验证。

规格明示释放后不得再次进入复位时，另设带 `reset_stable_after_release: true` 的 Assume。使用 `prepare sva` 返回的正文。每次采到非复位状态都要求下一拍保持非复位，显式关闭默认复位中止，使再次拉低的拍也受检查。

用 `inspect spec --query CK-...` 查一条现有 CK，并取得只更新该 CK 的请求模板。该请求可更新 `initial_reset`、`reset_stable_after_release`、`parent_ck_id` 和 `transaction_balance`，也可同时提交相关 `bodies`。

第 6 阶段修订公共证明输入后，更新回执中的 `reopened_ck_ids` 列出此前已处置、现在需重新验证的 CK。按回执提供的 `run_call` 或 `prepare_call` 处理当前 FC。手工修改后用 `RunFormal(action=pending)` 重新取得当前进度。

## 独立事务计数

`transaction_balance` 默认检查响应是否对应在途命令。规划接受上限时为相应 Seq CK 设置 `max_pending`，工具在命令握手前核对在途量，并检查计数溢出。握手始终由 `valid && ready` 形成。只有规格允许同拍响应归还满容量的一格时才设置 `reuse_on_response: true`。顶层出口可设 `binding: egress`，已在 `whitebox_signals` 中绑定的内部标量握手可设 `binding: internal`。生成器核对内部实际位宽。

当规格要求“无在途命令不能响应”时，在对应 Seq CK 中为每个需要独立跟踪的发起端规划一个 `transaction_balance` 条目。字段 `command_valid`、`command_ready`、`response_valid`、`response_ready` 使用已展开的单比特 DUT 接口端口。可选 `counter_bits` 默认 6。计数器溢出会使性质失败，不通过假设限制命令数。只有规格允许无在途命令的同拍响应时，才增加 `zero_cycle_when`，填写须同时满足的布尔条件。省略该字段将禁止这类响应。验证器被动采样端口，不驱动 DUT。

第 4 阶段保存条目和规格依据，保留 `sva_body` 为空。第 6 阶段使用 `prepare sva` 返回的预填 body，按同一 FC 提交更新并定向证明。技能不可用时，将 `RunFormal(action="pending")` 的 `current_fc.planned_bodies` 写入同一 CK。报告命令、响应、复位及同拍例外所依据的规格；不要用 DUT 内部计数或 active 输出替代独立监视状态。

## 准备分析与Bug队列

证明停止后调用：

```json
{"commands":[["ext/formal/data","formal_data.py","prepare analysis"]]}
```

prepare核验当前证据，默认最多返回5项，并按字符预算缩小本页。`items`将精确id/prop_name、缺失字段和证据摘要放在同一项，`ready_update`是唯一更新请求模板，不启动新证明。摘要将初始化和保存采样分开；省略的信号或宽值用该项`full_evidence_call`读取，多周期分析先用`trace_discovery_call`查完整信号名，不从省略部分推断数值。完整契约按类型在同批共享，机器证据无需手抄。审阅真实输入、独立参考计算、观测输出及断言，填写ready_update中的人工分析，再将该对象写入请求文件调用update。证据由技能核验并绑定，不手工复制哈希，不把准备动作当作RTL_BUG归因。

分析请求按类型分开：`items`用`contract_id`引用同批`review_contracts`中的共享契约，不能把不同类型字段混写。各项只有精确`id/prop_name`是定位字段：

| 列表 | 必填人工字段 | 其他可填字段 | 当前允许决定 |
| --- | --- | --- | --- |
| `fa_entries`（assert） | `analysis/resolution`；RTL_BUG另需`expected_requirement` | `action_detail/reference_calculations` | `RTL_BUG`或`ENV_PENDING` |
| `fa_entries`（cover） | `analysis/resolution` | `action_detail` | `COVER_EXPECTED_FAIL`或`ENV_PENDING` |
| `tt_entries`（assert） | `analysis/root_cause/action` | `action_detail/related_assume` | `action=ACCEPTED`仅配合`root_cause=DESIGN_EXPECTED` |

FA的自由根因解释写在`analysis`中，不提交TT专用的`root_cause/action/related_assume`。TT根因枚举为`ASSUME_TOO_STRONG/SIGNAL_CONSTANT/WRAPPER_ERROR/DESIGN_EXPECTED`；前3类需要修环境后重跑，不能据此接受当前结果。当前仍失败或恒真的条目不能填`ENV_FIXED/FIXED`冒充修复。`ENV_PENDING`可记录尚未解决的问题，但保持待审并阻止推进。

`evidence_ref/prop_type/sva_code`都是机器字段，不在请求里填写。批量请求有任何错误时整批不写入；`formal_data_review_invalid`一次列出有界的所有错误位置、允许字段和值，先修完整批再重试。真实RTL缺陷保留Fail；属性/参考计算错误修复后重新RunFormal。TRIVIALLY_FALSE保留静态失败，不能改弱目标。

`prepare --offset/--limit`分页只适用于同一只读队列。按`review_progress.returned/next_offset`翻页，实际返回数可能少于请求limit；不要自行把offset加limit。**每次update后，按返回的`after_update_command`从offset 0重新取pending**，不要沿用更新前的next_offset。旧偏移越过当前非空队列时明确报`review_pending_offset_stale`，不能把空页当成全部完成。无待审项时ready_update才为null。

Bug阶段对应`prepare bugs`，保留精确id/property。`items[].reviewed_analysis`直接带回首次分析及计算；规格关系和表达式不重复提交，只补缺失的共享根因、源码位置、修复建议和可选`impact_assessment`。观察描述由工具限定为当前反例或静态检查；影响范围推断始终标为人工评估，不由单个反例宣称所有输入的规律。一个共享根因的完整请求形状如下：

```json
{
  "section":"bugs",
  "expected_sha256":"最近prepare返回的哈希",
  "data":{
    "shared":{
      "root_cause_id":"ROOT-PACKET-ELIGIBILITY",
      "root_cause":"共同资格条件取反，导致两个输出观测偏离规格。",
      "fix":"修正条件后按原目标重新验证，尚未确认修复通过。",
      "severity":"HIGH",
      "confidence":"HIGH"
    },
    "entries":[
      {"id":"BG-FORMAL-001","property":"u_left.A_CK_PACKET_ELIGIBLE","ck_id":"CK-PACKET-LEFT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-LEFT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":8},
      {"id":"BG-FORMAL-002","property":"u_right.A_CK_PACKET_ELIGIBLE","ck_id":"CK-PACKET-RIGHT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-RIGHT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":9}
    ]
  }
}
```

共享root_cause_id明确指定，不按模块或相似文本推断；同组共享值必须一致。每个属性仍保留自身的真实触发与输出。需要聚焦读取时调用RunFormal(action="evidence",property_names=["完整属性名"])。它提供原始证据，不自动验证任意规格的数学含义。

## 规格预期与可复现参考计算

首次失败分析的`fa_entries`中填写`expected_requirement`描述规格关系，需要精确值时同时提交`reference_calculations`；update返回工具计算结果。Bug阶段直接复用，不再提交规格关系、表达式或计算答案。`description/expected/reference_results/trigger/actual`均是派生字段。无数值计算、无动态反例的静态契约检查使用空计算列表；证据或参考表达式变化后必须重新审阅，不能用旧计算支持新输入。

每项恰含`id/expression/bindings`。绑定名由任务自定，`source`为`initial`或`sample`，`signal`必须与当前返回证据中的完整名字一致；不能填自选数值代替真实信号。例如某个输入字段需截为低8位时，完整请求形状如下（精确id和哈希取本轮prepare，不直接复制示例）：

```json
{
  "section":"analysis",
  "expected_sha256":"最近prepare返回的哈希",
  "data":{"fa_entries":[{
    "id":"FA-001",
    "prop_name":"u_checker.A_CK_FIELD",
    "analysis":"当前反例输出与独立规格关系不符；已核对当前绑定与表达式。",
    "resolution":"RTL_BUG",
    "expected_requirement":"输出字段应保持输入字段的低8位。",
    "reference_calculations":[{
      "id":"field_low8",
      "expression":"payload & 0xff",
      "bindings":{"payload":{"source":"initial","signal":"input_payload"}}
    }]
  }]}
}
```

表达式使用数学整数的`+ - * // % << >> & | ^`和一元`+ - ~`，不隐含HDL位宽或有符号转换；需要截断、符号重解释时显式写关系。只允许整数、绑定名和这些运算，不执行函数或任意代码。每批最多10项、每项20个绑定、表达式2048字符、128语法节点、整数/移位上限4096位。未知、缺失和不完整信号不能用于计算。

初始化与保存采样是不同上下文，均不自动代表失败周期。计算结果只核验“所写表达式在这些绑定值上的结果”，不证明表达式就是正确规格。规格解释和根因仍需人工审阅；不要在其他自由文本中再抄写一个未经检查的计算结果，也不要仅凭COI/Cover断言规格完备。

输入变化后，`prepare analysis` 可返回 `previous_review` 草稿。审阅当前证据后再填写提交字段。若 `prepare bugs` 返回 `formal_analysis_pending`，先完成所列当前归因，再填写 Bug。

## 技能关闭或缺失时

不调用ListSkill、RunSkillScript或SetSkillUsage。使用ReadTextFile读取当前`.formal_records.yaml`和阶段输入，以EditTextFile/ReplaceStringInFile编辑本阶段拥有的YAML子树，保留其它节，不修改run_results和运行文件。用读取得到的文件哈希防止覆盖并发修改。

- planning/basic_info/spec：按下面完整例子及阶段目标填写。参数、声明、时钟复位只记录真实事实；一次维护完整FG/FC/CK层次。
- SVA：直接填写已有CK的sva_body；外层property声明与标签由生成器提供，不编辑派生SV。
- analysis：当前运行结束后Check协调精确条目；读取返回队列和RunFormal evidence，填写人工字段，证据引用原样使用对应属性的当前返回值。不能自行造引用、删层次或重编号。
- bugs：Check协调当前已核验RTL_BUG观测；用普通文件工具填写相同字段。同root_cause_id的root_cause/fix/severity须一致。
- summary：只填人工判断、completeness、coi_assessment与acceptance_conclusion，严重缺陷汇总由已核验Bug记录派生，不再填写severe_bugs或机器统计。

两条路径都必须满足同一字段、身份与真实证据标准。目标齐备后SetCurrentStageJournal记录日志，再Complete；遇具体缺口才Check，不绕过验收。修改证明输入后必须重新RunFormal，旧证据不支持新输入。

## 完整任务数据示例

以下是一个已实现、尚未证明的完整组合门控任务。例子是结构参考，不是机器证据；当前阶段只更新自己拥有的节，不用整份样例覆盖其它任务。

```yaml
dut: PacketGate
planning:
  project_overview: 输入 request 决定输出 eligible。
  verification_scope:
    included: [输出与请求组合等价]
    excluded: [无状态设计不适用活性证明]
  assumptions: []
  strategy: [先证明完整组合关系，再根据真实反例定位]
  deliverables: [属性与当前运行报告]
  risks:
    - risk: 规格与实现的端口解释可能不一致
      mitigation: 先核对真实接口和规格，再判定失败
basic_info:
  module_type: 资格门控
  is_top: true
  design_type: 纯组合逻辑
  ports:
    inputs:
      - {name: request, width: 1, signal_type: data, desc: 资格请求}
    outputs:
      - {name: eligible, width: 1, signal_type: data, desc: 资格输出}
  parameters: []
  core_functions: [请求到资格输出的映射]
  correctness_requirements: [eligible 等于 request]
  clock_reset: {clock_count: 0, clock_signal: '', reset_signal: ''}
spec:
  parameters: {}
  whitebox_signals: []
  function_groups:
    - id: FG-LOGIC
      name: 资格判断
      functions:
        - id: FC-PACKET
          title: 检查资格输出是否跟随请求
          description: 对 request 的全部合法取值，eligible 在同周期等于 request。
          review_order: 1
          check_points:
            - {id: CK-PACKET-ELIGIBLE, style: Comb, description: 输出跟随请求, sva_body: '(eligible == request);'}
analysis: {tt_entries: [], fa_entries: []}
bugs: []
summary: null
```

从这份数据继续：RunFormal run/status。技能可用则prepare analysis；无技能则Check协调。核对异常与真实witness后填写分析，再日志与Complete。没有环境约束、状态、时钟、复位或活性目标时说明不适用，不为凑模板创造假设。完整派生报告参考Guide_Doc/env_analysis.md、Guide_Doc/bug_report.md与Guide_Doc/formal_summary.md。存在暂缓须披露UNPROVEN，不称全部通过。

## 定向证明与多周期证据

用 `FormalData inspect spec` 查询同批 CK。`query` 接受最多十个以逗号分隔的 CK、FC、FG 标识，前缀匹配需以星号结尾。带上原始 `run_id` 可读该批封存的 SVA 和 Assume，返回结果标明来源并可分页。省略批次时读取当前记录。

对规格明确为「接受事务后下一拍呈现输出」的 Seq CK，调用 `FormalData` 的 `draft_transfer`。提交现有 `ck_id`、`source_valid`、`source_ready`、`result_valid`，并为 `fields` 中的每项指定 `before` 和 `after` 信号。`during_reset` 根据规格选择 `suspend` 或 `check`。工具核对展开后位宽和绑定，生成 `|=>` 及前拍字段比较。返回的 `ready_update` 供审阅后提交，草拟过程保持只读。

若规格明确要求外部应答端只能响应已接受的请求，给相应 Assume CK 添加 `transaction_balance`。每个独立通道使用一项。下面的例子允许同拍完成命令与响应，是否允许由接口规格决定。

```json
{"transaction_balance":[{"binding":"egress","command_valid":"request_valid","command_ready":"request_ready","response_valid":"reply_valid","response_ready":"reply_ready","zero_cycle_when":"1'b1","counter_bits":6}]}
```

`prepare sva` 生成正文。监听器从复位开始，在命令握手时增加在途计数，在响应握手时减少。只要还有在途请求，外部端点就可以在后续任意拍给出响应，即使没有新命令。未允许同拍时省略 `zero_cycle_when`。计数超出可表示范围后，本复位周期内放开该条约束，以免误排合法流量。若分析需要精确覆盖该范围，用独立 Assert 检查规格中的容量上界并核对证据。新增假设应记录协议依据和对原反例的影响。

对于“每次交付必须匹配复位以来最近一次接受值”的 Seq CK，`FormalData` 的 `draft_latest_transfer` 接收现有 `ck_id` 和 `rule`。下面用独立标签通道说明绑定。结合规格核对后可一次提交返回的 `ready_update`，再定向验证。

```json
{"action":"draft_latest_transfer","ck_id":"CK-RESPONSE-TAG","rule":{"capture_valid":"req_valid","capture_ready":"req_ready","captured":"req_tag","delivery_valid":"rsp_valid","delivery_ready":"rsp_ready","observed":"rsp_tag","simultaneous":"previous","reset_assertion":"sync"}}
```

检查器保存已握手的值，在全部交付拍比较。若规格以通道位图编码来源，`observed` 也可填写按最低位至最高位排列的 `{"valid":"lane_valid","ready":"lane_ready"}` 列表，每位表示该通道当拍实际完成握手。若 RTL 已提供成组位图，可直接绑定 `{"valid_vector":"lanes_valid","ready_vector":"lanes_ready"}`，逐位与后和捕获值比较。按规格选 `previous` 或 `current` 决定同拍捕获且交付时使用的值，并指定 `sync` 或 `async` 清除历史。没有历史的交付会失败，同拍直通仅在选择 `current` 且当拍完成捕获时成立。对于允许多笔在途且按队头交付的协议，应使用与队列深度和顺序相符的独立模型。


用 `RunFormal(action="run", scope="selected", fc_id="FC-...")` 执行一个功能批次，
或传入 `ck_ids=["CK-..."]` 定向复验。同时指定 `fc_id` 时，所有 CK 须属于该 FC。
第 6 阶段优先提交更新结果中的 `run_call`，当前 FC 仍有正文待填时按 `prepare_call` 继续。
可用 `RunFormal(action="inventory")` 列出
已枚举批次的精确属性名。后续查询、审阅、取消和证据读取均使用返回的 `run_id`，可一并提供 `scope`。
定向批次使用完整 Assume，未选目标为 `NOT_EXECUTED`。完整验收仍通过当前
输入的完整批次。

要查看原始反例的多周期证据，先用 `RunFormal(action="evidence",
property_names=[...], trace_query={"mode":"signals","signal_query":"**"})`
查找完整信号路径。然后用 `mode="samples"`、`signals` 和包含端点的
`start`、`end` 取样。有明确采样时钟时再指定完整路径 `clock` 与
`edge`。按返回的 `next_cursor` 继续同一查询。原始时间戳与求解器报告的
失败深度分别使用。窗口越界时，按返回的 `first_tick` 和 `last_tick` 修正范围。

数据 Skill 可将同一工具请求写为 OUT 下的 JSON 文件，再调用
`formal_data.py proof --request-file <path>`。用 `inspect extra_config --full`
读取配置，`update` 使用同一 revision 契约更新 `extra_config.tcl`。
