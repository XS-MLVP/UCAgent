
# Formal 任务数据技能

任务数据存放在 `.formal_records.yaml`。数据技能 `ext/formal/data` 是可选的批量更新捷径，通过现有 `RunSkillScript` 执行；不存在独立的FormalData工具。`RunFormal`负责证明和真实证据，`Complete`验收推进，`Check`用于定位缺口。技能关闭或目录缺失时，用普通文件工具完成同一YAML和相同验收，不能跳过任务。

## 技能可用时：一次加载，结构化请求

需要使用数据技能时，先ListSkill并读取`.ucagent/skills/ext/formal/data/SKILL.md`；默认阶段没有强制技能列表，不要求每阶段重复加载或SetSkillUsage。所有脚本调用沿用原有RunSkillScript格式：

```json
{"commands":[["ext/formal/data","formal_data.py","inspect planning"]]}
```

`inspect planning|basic_info|spec|analysis|bugs|summary|overview`只读查看已知字段、完整契约、缺失项、分页与sha256。`--offset/--limit`用于列表分页，按返回next_offset继续；截断预览不能当作完整值覆盖。端口和参数必须来自实际规格/RTL，空值不代表可以编造。

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

分析条目保留精确id/prop_name；只填写analysis/root_cause/action/action_detail/related_assume/resolution等人工字段。真实RTL缺陷保留Fail；错误属性或环境必须修复并取得新运行结果；Cover、超时、未知和工具错误不能冒充RTL Bug。TRIVIALLY_TRUE可能是正确恒等式，依据原因审核；TRIVIALLY_FALSE是静态失败，不能改弱原目标来消除工具状态。

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
      {"id":"BG-FORMAL-001","property":"u_left.A_CK_PACKET_ELIGIBLE","description":"左输出与规格不符。","trigger":"当前左侧witness的request=1。","expected":"eligible=1。","actual":"eligible=0。","ck_id":"CK-PACKET-LEFT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-LEFT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":8},
      {"id":"BG-FORMAL-002","property":"u_right.A_CK_PACKET_ELIGIBLE","description":"右输出受同一条件错误影响。","trigger":"当前右侧witness的request=0。","expected":"eligible=0。","actual":"eligible=1。","ck_id":"CK-PACKET-RIGHT","fg_id":"FG-LOGIC","fc_id":"FC-PACKET-RIGHT","rtl_file":"PacketGate/PacketGate.sv","rtl_line":9}
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
