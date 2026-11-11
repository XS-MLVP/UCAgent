
# Formal 任务数据技能

任务数据存放在 `.formal_records.yaml`。数据技能 `ext/formal/data` 是可选的批量更新捷径，通过现有 `RunSkillScript` 执行；不存在独立的FormalData工具。`RunFormal`负责证明和真实证据，`Complete`验收推进，`Check`用于定位缺口。技能关闭或目录缺失时，用普通文件工具完成同一YAML和相同验收，不能跳过任务。

## 技能可用时：一次加载，结构化请求

需要使用数据技能时，先ListSkill并读取`.ucagent/skills/ext/formal/data/SKILL.md`；默认阶段没有强制技能列表，不要求每阶段重复加载或SetSkillUsage。所有脚本调用沿用原有RunSkillScript格式：

```json
{"commands":[["ext/formal/data","formal_data.py","inspect planning"]]}
```

`inspect planning|basic_info|spec|analysis|bugs|summary|overview`只读查看当前缺项、分页与sha256；planning/basic_info/summary的完整结构按需使用`--schema`，不要为可选事实表重复填写全部数据。`--offset/--limit`用于列表分页，按返回next_offset继续；截断预览不能当作完整值覆盖。basic_info中clock_count未知应待核实，明确无时钟才填0。

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

更新指定节时`data`和`bodies`选一个。planning/basic_info/spec/summary只替换提供的顶层字段，嵌套对象和列表整体替换，因此须保留全部需要项。bodies只用于已有唯一CK-ID的完整属性体。冲突不会覆盖较新内容，重新inspect再写请求。机器计数、运行状态与证据文件不能由请求改写。

## 准备分析与Bug队列

证明停止后调用：

```json
{"commands":[["ext/formal/data","formal_data.py","prepare analysis"]]}
```

prepare核验当前证据、协调精确队列并返回ready_update请求对象及原始witness上下文，不启动新证明。审阅真实输入、独立参考计算、观测输出及断言，填写ready_update中的人工分析，再将该对象写入请求文件调用update。证据由技能核验并绑定，不手工复制哈希，不把准备动作当作RTL_BUG归因。

分析请求按类型分开，必须使用prepare返回的`review_contracts`。各项只有精确`id/prop_name`是定位字段；不能把不同类型字段混写：

| 列表 | 必填人工字段 | 其他可填字段 | 当前允许决定 |
| --- | --- | --- | --- |
| `fa_entries`（assert） | `analysis/resolution` | `action_detail` | `RTL_BUG`或`ENV_PENDING` |
| `fa_entries`（cover） | `analysis/resolution` | `action_detail` | `COVER_EXPECTED_FAIL`或`ENV_PENDING` |
| `tt_entries`（assert） | `analysis/root_cause/action` | `action_detail/related_assume` | `action=ACCEPTED`仅配合`root_cause=DESIGN_EXPECTED` |

FA的自由根因解释写在`analysis`中，不提交TT专用的`root_cause/action/related_assume`。TT根因枚举为`ASSUME_TOO_STRONG/SIGNAL_CONSTANT/WRAPPER_ERROR/DESIGN_EXPECTED`；前3类需要修环境后重跑，不能据此接受当前结果。当前仍失败或恒真的条目不能填`ENV_FIXED/FIXED`冒充修复。`ENV_PENDING`可记录尚未解决的问题，但保持待审并阻止推进。

`evidence_ref/prop_type/sva_code`都是机器字段，不在请求里填写。批量请求有任何错误时整批不写入；`formal_data_review_invalid`一次列出有界的所有错误位置、允许字段和值，先修完整批再重试。真实RTL缺陷保留Fail；属性/参考计算错误修复后重新RunFormal。TRIVIALLY_FALSE保留静态失败，不能改弱目标。

`prepare --offset/--limit`分页只适用于同一只读队列。**每次update后，按返回的`after_update_command`从offset 0重新取pending**，不要沿用更新前的next_offset。旧偏移越过当前非空队列时明确报`review_pending_offset_stale`，不能把空页当成全部完成。无待审项时ready_update才为null。

Bug阶段对应`prepare bugs`，保留精确id/property。一个共享根因的完整请求形状如下；真实id、名称和哈希均来自本次准备，不复制示例作证据：

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
      {"id":"BG-FORMAL-001","property":"u_left.A_CK_PACKET_ELIGIBLE","description":"左输出与规格不符。","expected":"eligible=1。","ck_id":"CK-PACKET-LEFT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-LEFT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":8},
      {"id":"BG-FORMAL-002","property":"u_right.A_CK_PACKET_ELIGIBLE","description":"右输出受同一条件错误影响。","expected":"eligible=0。","ck_id":"CK-PACKET-RIGHT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-RIGHT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":9}
    ]
  }
}
```

共享root_cause_id明确指定，不按模块或相似文本推断；同组共享值必须一致。每个属性仍保留自身的真实触发与输出。需要聚焦读取时调用RunFormal(action="evidence",property_names=["完整属性名"])。它提供原始证据，不自动验证任意规格的数学含义。

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
