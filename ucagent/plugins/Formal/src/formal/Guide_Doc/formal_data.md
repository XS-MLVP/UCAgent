
# Formal 任务数据技能

任务数据存放在 `.formal_records.yaml`。数据技能 `ext/formal/data` 是可选的批量更新捷径，通过现有 `RunSkillScript` 执行；不存在独立的FormalData工具。`RunFormal`负责证明和真实证据，`Complete`验收推进，`Check`用于定位缺口。技能关闭或目录缺失时，用普通文件工具完成同一YAML和相同验收，不能跳过任务。

## 技能可用时：一次加载，结构化请求

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

更新指定节时`data`和`bodies`选一个。planning/basic_info/spec/summary只替换提供的顶层字段，嵌套对象和列表整体替换，因此须保留全部需要项。bodies只用于已有唯一CK-ID的完整属性体。成功更新会返回新sha256、剩余作者缺项或待审项；没有缺项时不必再次inspect确认写入，审阅摘要、记录阶段日志后调用Complete。返回仅说明作者字段校验，不代表证明或阶段已经通过。冲突不会覆盖较新内容，重新inspect再写请求。机器计数、运行状态与证据文件不能由请求改写。

## 准备分析与Bug队列

证明停止后调用：

```json
{"commands":[["ext/formal/data","formal_data.py","prepare analysis"]]}
```

prepare核验当前证据、协调精确队列并返回ready_update请求对象及原始witness上下文，不启动新证明。审阅真实输入、独立参考计算、观测输出及断言，填写ready_update中的人工分析，再将该对象写入请求文件调用update。证据由技能核验并绑定，不手工复制哈希，不把准备动作当作RTL_BUG归因。

分析请求按类型分开：`review_items`用`contract_id`引用同批`review_contracts`中的共享契约，不能把不同类型字段混写。各项只有精确`id/prop_name`是定位字段：

| 列表 | 必填人工字段 | 其他可填字段 | 当前允许决定 |
| --- | --- | --- | --- |
| `fa_entries`（assert） | `analysis/resolution`；RTL_BUG另需`expected_requirement` | `action_detail/reference_calculations` | `RTL_BUG`或`ENV_PENDING` |
| `fa_entries`（cover） | `analysis/resolution` | `action_detail` | `COVER_EXPECTED_FAIL`或`ENV_PENDING` |
| `tt_entries`（assert） | `analysis/root_cause/action` | `action_detail/related_assume` | `action=ACCEPTED`仅配合`root_cause=DESIGN_EXPECTED` |

FA的自由根因解释写在`analysis`中，不提交TT专用的`root_cause/action/related_assume`。TT根因枚举为`ASSUME_TOO_STRONG/SIGNAL_CONSTANT/WRAPPER_ERROR/DESIGN_EXPECTED`；前3类需要修环境后重跑，不能据此接受当前结果。当前仍失败或恒真的条目不能填`ENV_FIXED/FIXED`冒充修复。`ENV_PENDING`可记录尚未解决的问题，但保持待审并阻止推进。

`evidence_ref/prop_type/sva_code`都是机器字段，不在请求里填写。批量请求有任何错误时整批不写入；`formal_data_review_invalid`一次列出有界的所有错误位置、允许字段和值，先修完整批再重试。真实RTL缺陷保留Fail；属性/参考计算错误修复后重新RunFormal。TRIVIALLY_FALSE保留静态失败，不能改弱目标。

`prepare --offset/--limit`分页只适用于同一只读队列。**每次update后，按返回的`after_update_command`从offset 0重新取pending**，不要沿用更新前的next_offset。旧偏移越过当前非空队列时明确报`review_pending_offset_stale`，不能把空页当成全部完成。无待审项时ready_update才为null。

Bug阶段对应`prepare bugs`，保留精确id/property。`reused_analysis`直接带回首次分析及计算；规格关系和表达式不重复提交，只补缺失的共享根因、源码位置、修复建议和可选`impact_assessment`。观察描述由工具限定为当前反例或静态检查；影响范围推断始终标为人工评估，不由单个反例宣称所有输入的规律。一个共享根因的完整请求形状如下：

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
          description: 全输入组合关系
          check_points:
            - {id: CK-PACKET-ELIGIBLE, style: Comb, description: 输出跟随请求, sva_body: '(eligible == request);'}
analysis: {tt_entries: [], fa_entries: []}
bugs: []
summary: null
```

从这份数据继续：RunFormal run/status。技能可用则prepare analysis；无技能则Check协调。核对异常与真实witness后填写分析，再日志与Complete。没有环境约束、状态、时钟、复位或活性目标时说明不适用，不为凑模板创造假设。完整派生报告参考Guide_Doc/env_analysis.md、Guide_Doc/bug_report.md与Guide_Doc/formal_summary.md。存在暂缓须披露UNPROVEN，不称全部通过。

## 定向证明与多周期证据

可用 `RunFormal(action="inventory")` 列出已枚举批次的精确属性名。使用
`RunFormal(action="run", scope="selected", property_names=[...])` 发起定向
复验。后续查询、审阅、取消和证据读取均使用返回的 `run_id` 和 `scope`。
定向批次使用完整 Assume，未选目标为 `NOT_EXECUTED`。完整验收仍通过当前
输入的完整批次。

要查看原始反例的多周期证据，先用 `RunFormal(action="evidence",
property_names=[...], trace_query={"mode":"signals","signal_query":"**"})`
查找完整信号路径。然后用 `mode="samples"`、`signals` 和包含端点的
`start`、`end` 取样。有明确采样时钟时再指定完整路径 `clock` 与
`edge`。按返回的 `next_cursor` 继续同一查询。原始时间戳与求解器报告的
失败深度分别使用。

数据 Skill 可将同一工具请求写为 OUT 下的 JSON 文件，再调用
`formal_data.py proof --request-file <path>`。用 `inspect extra_config --full`
读取配置，`update` 使用同一 revision 契约更新 `extra_config.tcl`。
