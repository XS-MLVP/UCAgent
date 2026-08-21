# DUT Bug 分析指南

本文定义动态与静态 Bug 文档的唯一机器格式。尖括号标签在 Markdown 渲染后可能不可见，因此 FG/FC/CK/BG/TC 和中央波形记录必须同时写出能独立表达含义的中文可见标题；不能用“功能组”“功能”“检测点”“动态 Bug”“失败用例”等类型名代替具体描述。动态 Bug 文档必须使用本文定义的 Markdown 层级、尖括号标签、字段顺序和八个固定分析标题；YAML 字段、签名 receipt 与 viewer token 必须由工具生成并保持原样。不得改用粗体、增加平行章节或重新组织标签。

## 1. 先分类

- 正确测试稳定 Fail 且规格、采样和预期均正确：保留严格断言，记录动态 DUT Bug。
- 测试、参考模型、fixture、API、Mock、复位、时序、依赖或环境错误：修复到 Pass，不记录 DUT Bug。
- 仅由源码审查发现、尚未动态复现：只写入`{DUT}_static_bug_analysis.md`，使用`BG-STATIC-*`。
- 静态候选经测试确认：动态文档新建独立`BG-NAME-XX`，静态文档用`LINK-BUG`关联。

动态 Bug 的 Fail 测试必须有真实 WaveInfo 证据。不能弱化断言、伪造 receipt、复制 viewer token，或删除仍能稳定复现 Bug 的 TC/BG 来绕过验收。

## 2. 文档分区

`{DUT}_bug_analysis.md`必须各有一个封闭分区，且顺序固定：

````markdown
# DUT 动态 Bug 分析

## 动态 Bug 记录
<DYNAMIC-BUGS>
<!-- FG/FC/CK/BG/TC and Bug analysis live here. -->
</DYNAMIC-BUGS>

## 波形证据
<WAVEFORM-EVIDENCE>
<!-- All unique per-TC waveform records live here. -->
</WAVEFORM-EVIDENCE>
````

`<DYNAMIC-BUGS>`中只放 Bug 层级、TC 引用和 Bug 分析，不放波形 YAML 或 viewer。`<WAVEFORM-EVIDENCE>`中集中放全部波形记录，不放 FG/FC/CK/BG 标签。

## 3. Bug 层级与引用

标签顺序为`FG -> FC -> CK -> BG -> TC`。可见标题、Markdown 层级与标签必须写在同一行，并使用以下固定结构。可见标题是该条目的具体语义描述，不能只是标签类型的释义。一个非零置信度 BG 至少关联一个真实 Fail TC。一个 BG 的所有 TC 及其`<WAVEFORM-REF>`必须连续位于该`<BG-*>`标题之后；八个`<BUG-*>`字段整体位于最后一个 TC/引用之后。第一个`<BUG-*>`字段出现后不得再追加 TC。每个 BG/TC 关联必须紧跟一个由工具生成的链接：

```markdown
### 算术功能 <FG-ARITHMETIC>
#### 加法结果 <FC-ADD>
##### 溢出输出 <CK-OVERFLOW>
###### 进位输入溢出丢失（98%） <BG-CIN-OVERFLOW-98>
- 进位输入触发溢出 <TC-tests/test_adder.py::test_overflow>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-0123456789abcdef)

<BUG-OVERVIEW>
###### Bug 概述
...
<BUG-SYMPTOMS>
###### 现象与严重度
...
<BUG-TRIGGER>
###### 触发条件与影响
...
<BUG-ROOT-CAUSE>
###### 根因分析
...
<BUG-SOURCE-EVIDENCE>
###### 源码证据
...
<BUG-CAUSAL-CHAIN>
###### 动态因果链
...
<BUG-FIX>
###### 修复建议
...
<BUG-RETEST>
###### 风险与复验
...
```

可见标题来源固定：FG 和 FC 使用`{OUT}/{DUT}_functions_and_checks.md`中对应功能层级的标题；CK 使用同一文档中该 CK 的检查点名称；BG 使用该缺陷的具体问题描述；TC 使用测试函数 docstring 的首个非空描述行。若同一 TC 关联多个 BG，各处必须使用相同 TC 可见标题。锚点由规范化 TC 标签稳定计算，禁止手工猜测或改写。使用`ApplyWaveInfoEvidence`创建或修复`<WAVEFORM-REF>`。

同一 Bug 有多个 Fail TC：每个 TC 各有一条引用和一份中央记录。同一 Fail TC 触发多个 Bug：每个 BG 下都引用相同锚点，但中央记录仍只有一份。

## 4. 中央波形记录

每个规范化 TC 在整个文档中有且只有一个`<WAVEFORM-TC-...>`记录。中央记录的可见标题必须逐字复用对应 TC 的可见标题并追加“波形”：

````markdown
<WAVEFORM-EVIDENCE>

<a id="waveform-0123456789abcdef"></a>
### 进位输入触发溢出波形 <WAVEFORM-TC-tests/test_adder.py::test_overflow>
```yaml
waveform_analysis:
  test_case: TC-tests/test_adder.py::test_overflow
  bug_tags:
    - BG-CARRY-95
    - BG-CIN-OVERFLOW-98
  status: confirmed
  receipt_id: 0123456789abcdef0123456789abcdef
  result_fingerprint: ...
  waveform_file: ...
  freshness_identity: ...
  size_bytes: 1234
  session_started_at: ...
  modified_at: ...
  modified_time_ns: 1234
  observed_at: ...
  pattern: [...]
  signal_groups:
    clock_mode: clocked
    clocks: [...]
    inputs: [...]
    outputs: [...]
    protocol: [...]
    key_signals: [...]
  analysis_mode: explicit_window
  start_step: 100
  end_step: 120
  context_steps: 1
  max_points: 200
  wave_step: 110
  timeline_truncated: false
  alignment_evidence: ...
  bug_evidence:
    BG-CARRY-95:
      required_signals: [...]
      observed_behavior: ...
      source_correlation: ...
    BG-CIN-OVERFLOW-98:
      required_signals: [...]
      observed_behavior: ...
      source_correlation: ...
```
<WAVEFORM-VIEWER> [viewer](/surfer/?wave=...)

</WAVEFORM-EVIDENCE>
````

YAML 的唯一顶层键是`waveform_analysis`。关闭围栏后的第一条非空内容必须是同一 receipt 生成的`<WAVEFORM-VIEWER>`链接。

结构约束：

- `test_case`必须等于记录标签中的规范化 TC。
- `bug_tags`必须是排序、去重、非空列表，并精确等于所有引用该 TC 的 BG。
- `bug_evidence`键必须精确等于`bug_tags`。
- `alignment_evidence`描述该 TC 共享的日志、时钟边沿、事务接受、响应有效和波形定位关系，只写一次。
- 每个 BG 的`required_signals`是非空、去重的精确信号路径列表；必须全部包含在顶层签名`signal_groups`中。
- 每个 BG 独立填写`observed_behavior`和`source_correlation`，避免把多个根因混成一段结论。
- 顶层`signal_groups`及 viewer 必须暴露所有 BG 的`required_signals`并集，以及完整时钟、输入、输出、协议和功能上下文。

BG 条目只保留 TC 和`<WAVEFORM-REF>`；YAML 与 viewer 只出现在该 TC 的中央记录中。

## 5. WaveInfo 与 Apply 工具

MCP 调用中未使用的可选参数按工具 schema 传空字符串、空数组或`-1`哨兵；工具返回中的`null`是其 canonical 表示，不能再把`null`作为下一次 MCP 参数。

1. 阅读规格、测试 API/driver/callback 和`Step`顺序，确认真实驱动边沿、请求接受条件、响应有效条件和采样延迟。
2. 先用 WaveInfo inventory/metadata 找到正确测试波形和信号目录。只给`test_case_name`和`pattern`、但没有完整对齐窗口时是探索调用；`status: evidence_window_required`不能作为最终证据，必须逐字使用 `recommended_evidence_call`再次调用，不能把 `effective_start_step/effective_end_step` 手工复制进文档。
3. 用结构化 pattern 定位真实失败事务。日志 cycle 与 wave step 可能相差多个周期；按时钟 occurrence 和事务上下文对齐，不能直接当作同一索引。
4. 最终调用使用`logged_cycle + clock_signal`或完整`start_step + end_step`，并提供完整`signal_groups`。`start_step` 和 `end_step` 必须同时提供，且不能与`logged_cycle`混用。成功的最终取证返回会包含 `bug_document_fields`与`bug_document_viewer_link`；`waveform_analysis:` 必须是唯一顶层键，二者只能通过 Apply 写入。
5. 用真实`receipt_id`调用：

```text
ApplyWaveInfoEvidence(
  target_file="{OUT}/{DUT}_bug_analysis.md",
  bug_tag="BG-CIN-OVERFLOW-98",
  test_case_tag="TC-tests/test_adder.py::test_overflow",
  receipt_id="..."
)
```

6. 根据规格、timeline 和 RTL 完成`alignment_evidence`与各`bug_evidence.<BG>`语义字段，以及 BG 下八个分析字段。`<BUG-TODO>`不能残留。

`signal_groups` 的固定子字段为`clock_mode`、`clocks`、`inputs`、`outputs`、`protocol`和`key_signals`。viewer 中的顺序按`clocks -> inputs -> outputs -> protocol -> key_signals`构造。最终调用若缺少完整角色，先从`signal_catalog`补全真实路径；例如接口确实存在`TOP.dut.ready`时应放入`protocol`，不能只显示结果 data。

先确认事务有效，再判断数据是否错误。调用一次 `Step(1)` 只表示仿真时间推进了一步；必须检查 API 内部是否已经调用 `Step`、等待握手或采样结果。无效周期的一次单点 data mismatch 只能作为继续调查的线索。请求接受、响应有效和信号角色必须结合规格、API/driver和RTL判断，不能根据特定信号名猜测。

同一 TC 新增 Bug 时，对新 BG 再调用一次 Apply。若原 receipt 已包含新 Bug 所需信号，工具复用中央记录并保留已有分析；若需要新增信号，重新调用最终 WaveInfo，使`signal_groups`成为所有 Bug 所需信号的并集，再使用`replace_existing=true`。替换不同 receipt 时，工具保留各 BG 的`required_signals`，并重置共享和逐 Bug 语义结论，要求重新审查。

同一 Bug 有多个 Fail TC 时，对每个 BG/TC 分别调用一次。目标 TC 不存在且 BG 位置唯一时，Apply 会从目标测试函数的非空 docstring 读取中文可见标题，在该 BG 的`<BUG-OVERVIEW>`之前创建 TC 和引用；测试源码或 docstring 不存在时会拒绝生成，LLM 不得猜测标题。LLM 不得手工复制 BG、创建兄弟 TC或拼接 receipt。同一 Fail TC 揭示多个独立 Bug 时，使用相同 TC 和不同 BG 分别调用；每次调用只更新目标关联，不会覆盖其他 Bug。签名窗口和 `signal_groups` 同时支持各缺陷时才能复用 receipt。

### 5.1 完整标准案例

以下案例是动态 Bug 文档的完整标准结构。实际文档保留文档标题、Markdown 层级、标签位置、字段顺序、八个固定分析标题和 fenced block 位置；FG/FC/CK/BG/TC 标题必须按实际功能、检查点、缺陷和测试描述填写，不能复制类型占位文字。案例中的 receipt、fingerprint、时间和 viewer token 只说明字段形态；实际值必须来自当前 `WaveInfo` 和 `ApplyWaveInfoEvidence`，禁止复制案例值。

`````markdown
# Adder 动态 Bug 分析

## 动态 Bug 记录
<DYNAMIC-BUGS>

### 算术功能 <FG-ARITHMETIC>
#### 加法结果 <FC-ADD-RESULT>
##### 进位输出 <CK-CARRY-OUT>
###### 完整和进位丢失（95%） <BG-SUM-CARRY-DROPPED-95>
- 进位输入产生进位 <TC-tests/test_adder.py::test_cin_carry>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-9f3516eabf18829d)

<BUG-OVERVIEW>
###### Bug 概述
当 `a + b + cin` 产生第 `WIDTH+1` 位进位时，DUT 在组合加法路径中提前截断中间结果，导致 `cout` 始终为 0。

<BUG-SYMPTOMS>
###### 现象与严重度
边界用例 `a=8'hff, b=8'h00, cin=1` 的期望结果为 `{cout,sum}=9'h100`，实际结果为 `9'h000`。该问题会破坏所有依赖进位输出的多字加法，严重度为高。

<BUG-TRIGGER>
###### 触发条件与影响
触发条件是两个操作数与 `cin` 的无符号和大于 `2^WIDTH-1`。低 `WIDTH` 位未溢出时结果正常；发生进位时，`sum` 保留低位而 `cout` 丢失，影响 `CK-CARRY-OUT` 及其上层级联运算。

<BUG-ROOT-CAUSE>
###### 根因分析
`sum_full` 只声明为 `WIDTH` 位，却承接 `WIDTH+1` 位表达式。赋值时最高进位位被截断，后续拼接只能在已截断值前补 0，因此无法恢复真实 `cout`。

<BUG-SOURCE-EVIDENCE>
###### 源码证据
首个错误位于 `rtl/Adder.sv:24-26`：

```systemverilog
24: logic [WIDTH-1:0] sum_full; // <BUG-SOURCE-FIRST-ERROR> 中间量少一位，无法保存进位。
25: assign sum_full = {1'b0, a} + {1'b0, b} + cin; // <BUG-SOURCE-PROPAGATION> 宽表达式在写入 sum_full 时被截断。
26: assign {cout, sum} = {1'b0, sum_full}; // <BUG-SOURCE-OBSERVABLE> 输出端观察到固定为 0 的 cout。
```

<BUG-CAUSAL-CHAIN>
###### 动态因果链
测试在有效组合输入窗口驱动 `8'hff + 8'h00 + 1`；完整和为 `9'h100`；第 25 行写入 8 位 `sum_full` 后变为 `8'h00`；第 26 行再补零形成 `9'h000`；波形中的 `cout=0` 与失败断言一致。

<BUG-FIX>
###### 修复建议
将 `sum_full` 声明为 `logic [WIDTH:0]`，直接执行 `assign {cout, sum} = sum_full;`。保持表达式和中间存储均为 `WIDTH+1` 位，避免在进位提取前发生截断。

<BUG-RETEST>
###### 风险与复验
复验 `0+0+0`、最大值加 0、最大值加 1、最大值加最大值及随机输入，并检查 `sum` 与 `cout`。同时回归所有级联使用 `cout` 的上层用例，并在新波形中确认第 `WIDTH+1` 位从中间量传播到输出。

</DYNAMIC-BUGS>

## 波形证据
<WAVEFORM-EVIDENCE>

<a id="waveform-9f3516eabf18829d"></a>
### 进位输入产生进位波形 <WAVEFORM-TC-tests/test_adder.py::test_cin_carry>
```yaml
waveform_analysis:
  test_case: TC-tests/test_adder.py::test_cin_carry
  bug_tags:
    - BG-SUM-CARRY-DROPPED-95
  status: confirmed
  receipt_id: 0123456789abcdef0123456789abcdef
  result_fingerprint: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  waveform_file: unity_test/tests/waveform/test_cin_carry.fst
  freshness_identity: unity_test/tests/waveform/test_cin_carry.fst:4096:1787286677000000000
  size_bytes: 4096
  session_started_at: 2026-08-21T14:30:00+08:00
  modified_at: 2026-08-21T14:31:17+08:00
  modified_time_ns: 1787286677000000000
  observed_at: 2026-08-21T14:31:18+08:00
  pattern:
    - signal: TOP.dut.cin
      event: equals
      value: "0x1"
    - signal: TOP.dut.sum[7:0]
      event: equals
      value: "0x0"
  signal_groups:
    clock_mode: combinational
    clocks: []
    inputs:
      - TOP.dut.a[7:0]
      - TOP.dut.b[7:0]
      - TOP.dut.cin
    outputs:
      - TOP.dut.sum[7:0]
      - TOP.dut.cout
    protocol: []
    key_signals:
      - TOP.dut.sum_full[7:0]
  analysis_mode: explicit_window
  start_step: 40
  end_step: 44
  context_steps: 1
  max_points: 200
  wave_step: 42
  timeline_truncated: false
  alignment_evidence: 测试在 step 40 驱动输入并等待组合稳定；step 42 的输入仍为 ff、00、1，输出已稳定为 00、0，与同一次断言采样对应。
  bug_evidence:
    BG-SUM-CARRY-DROPPED-95:
      required_signals:
        - TOP.dut.a[7:0]
        - TOP.dut.b[7:0]
        - TOP.dut.cin
        - TOP.dut.sum_full[7:0]
        - TOP.dut.sum[7:0]
        - TOP.dut.cout
      observed_behavior: 完整输入和应为 9'h100，但中间量与输出均为 0，最高进位没有到达 cout。
      source_correlation: rtl/Adder.sv:24-26 的 sum_full 宽度截断与波形中丢失的最高位一致。
```
<WAVEFORM-VIEWER> [Open waveform](/surfer/?wave=TOOL_GENERATED_TOKEN)

</WAVEFORM-EVIDENCE>
`````

标准案例体现以下不可变边界：每个层级即使不显示尖括号标签也能从可见标题理解其含义；一个 BG 的全部分析都位于该 BG 内；BG 下只保留失败 TC 与引用；一个 TC 的 YAML 和 viewer 只在中央波形分区出现一次；源码路径含真实行范围，三个源码因果标签各在 HDL fenced block 中出现一次。

### 5.2 建立骨架并分阶段写入

`record_dynamic_bug.py`是可选脚本，只接收`BG/TC/BD`并创建新 Bug 的第一份 BG/TC、引用和八个带`<BUG-TODO>`的分析章节。脚本从功能检查文档读取 FG/FC/CK 的中文名称，从测试 docstring 读取 TC 名称，并用`BD`生成 BG 名称。脚本不可用时也不阻塞整个流程，使用文本编辑工具从相同来源读取名称，参照第 5.1 节的完整标准案例和本节骨架建立相同结构。

#### 5.2.1 多分支层次骨架

FG、FC、CK、BG、TC 都是一对多层次，不是一条固定单链。以下骨架明确展示两个 FG；每个 FG 下两个 FC；每个 FC 下两个 CK；每个 CK 下两个 BG；每个 BG 下两个 TC。为突出树结构，本图省略每条 TC 后由`ApplyWaveInfoEvidence`生成的`<WAVEFORM-REF>`以及每个 BG 的八个分析字段；实际文档不得省略，必须按第 5.2.2 节展开。

```markdown
<DYNAMIC-BUGS>
### 算术功能 <FG-ARITHMETIC>
#### 加法结果 <FC-ADD-RESULT>
##### 求和输出 <CK-SUM-OUT>
###### 边界求和截断（95%） <BG-SUM-TRUNCATED-95>
- 最大值加一求和 <TC-tests/test_adder.py::test_sum_max_plus_one>
- 随机溢出求和 <TC-tests/test_adder.py::test_sum_random_overflow>
###### 模式切换后求和陈旧（90%） <BG-SUM-STALE-90>
- 加法模式切换求和 <TC-tests/test_adder.py::test_sum_after_mode_switch>
- 复位后首次求和 <TC-tests/test_adder.py::test_sum_after_reset>
##### 进位输出 <CK-CARRY-OUT>
###### 完整和进位丢失（95%） <BG-CARRY-DROPPED-95>
- 进位输入产生进位 <TC-tests/test_adder.py::test_cin_carry>
- 双最大值产生进位 <TC-tests/test_adder.py::test_double_max_carry>
###### 无溢出时进位误置（85%） <BG-CARRY-SPURIOUS-85>
- 小数值相加无进位 <TC-tests/test_adder.py::test_small_add_no_carry>
- 零值相加无进位 <TC-tests/test_adder.py::test_zero_add_no_carry>
#### 减法结果 <FC-SUB-RESULT>
##### 差值输出 <CK-DIFFERENCE-OUT>
###### 负差值截断（92%） <BG-DIFFERENCE-TRUNCATED-92>
- 小数减大数 <TC-tests/test_subtractor.py::test_negative_difference>
- 随机负差值 <TC-tests/test_subtractor.py::test_random_negative_difference>
###### 相等操作数差值非零（88%） <BG-EQUAL-DIFFERENCE-NONZERO-88>
- 最大值自减 <TC-tests/test_subtractor.py::test_max_minus_self>
- 随机值自减 <TC-tests/test_subtractor.py::test_random_minus_self>
##### 借位输出 <CK-BORROW-OUT>
###### 负差值借位丢失（94%） <BG-BORROW-DROPPED-94>
- 零减一产生借位 <TC-tests/test_subtractor.py::test_zero_minus_one_borrow>
- 随机负差值借位 <TC-tests/test_subtractor.py::test_random_borrow>
###### 非负差值借位误置（84%） <BG-BORROW-SPURIOUS-84>
- 最大值减零无借位 <TC-tests/test_subtractor.py::test_max_minus_zero_no_borrow>
- 大数减小数无借位 <TC-tests/test_subtractor.py::test_positive_difference_no_borrow>

### 接口控制 <FG-PROTOCOL>
#### 请求控制 <FC-REQUEST-CONTROL>
##### 请求接受 <CK-REQUEST-ACCEPT>
###### 就绪请求未接受（93%） <BG-READY-REQUEST-DROPPED-93>
- 单周期就绪请求 <TC-tests/test_protocol.py::test_ready_request_accept>
- 连续就绪请求 <TC-tests/test_protocol.py::test_back_to_back_accept>
###### 未就绪请求被误接受（89%） <BG-STALLED-REQUEST-ACCEPTED-89>
- 背压期间单次请求 <TC-tests/test_protocol.py::test_stalled_request_rejected>
- 背压期间连续请求 <TC-tests/test_protocol.py::test_stalled_burst_rejected>
##### 背压保持 <CK-BACKPRESSURE-HOLD>
###### 背压期间请求数据变化（91%） <BG-REQUEST-DATA-UNSTABLE-91>
- 单周期背压数据保持 <TC-tests/test_protocol.py::test_request_hold_one_cycle>
- 多周期背压数据保持 <TC-tests/test_protocol.py::test_request_hold_multi_cycle>
###### 背压解除后请求丢失（87%） <BG-REQUEST-LOST-AFTER-STALL-87>
- 单周期背压解除 <TC-tests/test_protocol.py::test_request_after_short_stall>
- 多周期背压解除 <TC-tests/test_protocol.py::test_request_after_long_stall>
#### 响应控制 <FC-RESPONSE-CONTROL>
##### 响应有效 <CK-RESPONSE-VALID>
###### 结果就绪时有效信号缺失（94%） <BG-RESPONSE-VALID-MISSING-94>
- 单次响应有效 <TC-tests/test_protocol.py::test_single_response_valid>
- 连续响应有效 <TC-tests/test_protocol.py::test_back_to_back_response_valid>
###### 空闲周期有效信号误置（86%） <BG-RESPONSE-VALID-SPURIOUS-86>
- 复位后空闲响应 <TC-tests/test_protocol.py::test_idle_valid_after_reset>
- 请求间隔空闲响应 <TC-tests/test_protocol.py::test_idle_valid_between_requests>
##### 响应顺序 <CK-RESPONSE-ORDER>
###### 连续响应顺序颠倒（92%） <BG-RESPONSE-ORDER-REVERSED-92>
- 两笔连续响应顺序 <TC-tests/test_protocol.py::test_two_response_order>
- 随机突发响应顺序 <TC-tests/test_protocol.py::test_random_burst_order>
###### 背压后响应重复（88%） <BG-RESPONSE-DUPLICATED-88>
- 单周期背压后响应 <TC-tests/test_protocol.py::test_response_after_short_stall>
- 多周期背压后响应 <TC-tests/test_protocol.py::test_response_after_long_stall>
</DYNAMIC-BUGS>
```

禁止把同一 FG/FC/CK/BG 标签复制成多个平行节点。已有父节点时在该节点范围内添加新的子节点；同一 BG 的多个 TC 只增加 TC 与引用，不复制八个分析字段。同一 TC 关联多个 BG 时，在每个 BG 下保留同名 TC 与相同中央锚点，但中央波形记录仍只有一份。

#### 5.2.2 单个 BG 的完整字段骨架

以下骨架用于展开上图中的每个新 BG；方括号内容必须替换为实际可见名称。两个 TC 示例刻意放在八字段之前，用于强调固定顺序：

```markdown
<DYNAMIC-BUGS>
### [功能组具体名称] <FG-NAME>
#### [功能具体名称] <FC-NAME>
##### [检查点具体名称] <CK-NAME>
###### [缺陷具体描述]（XX%） <BG-NAME-XX>
- [测试 docstring 描述] <TC-test_file.py::test_name>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#tool-generated-anchor)
- [另一个测试 docstring 描述] <TC-test_file.py::test_another_name>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#another-tool-generated-anchor)
<BUG-OVERVIEW>
###### Bug 概述
<BUG-TODO>
<BUG-SYMPTOMS>
###### 现象与严重度
<BUG-TODO>
<BUG-TRIGGER>
###### 触发条件与影响
<BUG-TODO>
<BUG-ROOT-CAUSE>
###### 根因分析
<BUG-TODO>
<BUG-SOURCE-EVIDENCE>
###### 源码证据
<BUG-TODO>
<BUG-CAUSAL-CHAIN>
###### 动态因果链
<BUG-TODO>
<BUG-FIX>
###### 修复建议
<BUG-TODO>
<BUG-RETEST>
###### 风险与复验
<BUG-TODO>
</DYNAMIC-BUGS>
```

方括号内的文字是必须替换的可见标题，不是允许保留的模板文本。锚点和引用仍由 Apply 修复为精确值。LLM 必须替换标签值、可见标题和分析正文，但不得修改 Markdown 层级、八个固定分析标题、字段顺序或容器布局。不要为同一 BG 的后续 Fail TC 复制该结构；新增 TC 必须插入该 BG 的`<BUG-OVERVIEW>`之前。调用 `ApplyWaveInfoEvidence`写入中央记录后，必须清除八个分析章节中的全部 `<BUG-TODO>`；任何非零 BG 残留占位都不能完成。

## 6. 证据保留与重放

签名 receipt、中央 YAML 和 viewer 是持续保留的证据。普通增量 stage 使用`require_current_replay=false`：只验证文档、签名 receipt 与关联，不因后来测试、session 或波形文件变化而要求更新。

只有对应验证项配置`require_current_replay=true`时，才对所有唯一 TC 重放当前波形。重放失败或窗口、候选、信号集合、事件变化时，按返回的 WaveInfo/Apply 调用取得新 receipt 并更新中央记录。

新增一个关联 Bug 属于证据范围扩展：即使普通 stage 不重放，也必须确认当前 receipt 的信号并集足以分析新 Bug；不足时按上一节替换 receipt。

移除或重新分类 Bug 时，同步删除该 BG/TC 引用及中央记录中的`bug_tags`/`bug_evidence`项。如果 TC 的最后一个 Bug 关联被移除，必须删除整份中央`<WAVEFORM-TC-...>`记录，不能留下孤儿波形。

## 7. Bug 根因字段

八个标记必须唯一、有序、内容非空。每个标记后的第一条非空行必须依次为`###### Bug 概述`、`###### 现象与严重度`、`###### 触发条件与影响`、`###### 根因分析`、`###### 源码证据`、`###### 动态因果链`、`###### 修复建议`、`###### 风险与复验`；不得翻译、改写、改成粗体或更换标题级别。`<BUG-SOURCE-EVIDENCE>`有两种互斥模式：

- 有源码：包含真实`path:L1-L2`与完整 HDL fenced 代码，并在语言原生注释中各放一次`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`。
- 无可访问源码：单独写`<BUG-SOURCE-UNAVAILABLE>`，用规格、接口、日志和波形完成黑盒因果链，不虚构源码位置。

无源码分支必须完整写成以下形态，不能只留下标记：

```markdown
<BUG-SOURCE-EVIDENCE>
###### 源码证据
<BUG-SOURCE-UNAVAILABLE>
当前工作区未提供可访问的 RTL/HDL。接口规格规定请求在 `valid && ready` 时接受，失败日志和已确认波形共同显示响应有效周期的 `result` 比期望值少 1；因此根因范围限定在接受后到结果输出之间的状态更新或算术路径，不能虚构具体文件与行号。
```

一个 BG 的概述、症状、触发条件、根因、源码因果链、修复建议和复验计划只写一次；多个 TC 只增加引用与各自中央波形，不复制整段根因。

有源码时，根因分析必须包含源码代码块，例如：

```systemverilog
// path/to/file.sv:L10-L12
assign accepted = valid && ready; // <BUG-SOURCE-FIRST-ERROR> Wrong acceptance condition.
assign state_n = accepted ? NEXT : state; // <BUG-SOURCE-PROPAGATION> Error enters state.
assign result = state; // <BUG-SOURCE-OBSERVABLE> Error reaches the checked output.
```

不要在文档末尾再建立一个与 BG 标签分离的“根因分析汇总”。

## 8. 静态 Bug 标签

静态候选只写在`{DUT}_static_bug_analysis.md`，使用`<BG-STATIC-NNN-NAME>`。文件必须依次包含`<STATIC-BUG-SUMMARY>`、`<STATIC-BUG-DETAILS>`和`<STATIC-BUG-PROGRESS>`。每个候选使用`<FILE-path/to/file.v:L1-L2>`定位，并在汇总和详情中保持同一链接：待验证为`<LINK-BUG-[BG-TBD]>`，动态证实后为`<LINK-BUG-[BG-NAME-XX]>`，误报为`<LINK-BUG-[BG-NA]>`。

若没有任何可分析文件，使用`<FG-NULL>/<FC-NULL>/<CK-NULL>/<BG-STATIC-NULL>`；输入文件标签写作`<file>path/to/file.v</file>`。静态候选动态证实后，必须创建独立非静态 BG，并遵循本文的中央波形格式；不能把`BG-STATIC-*`写进动态文档。

## 9. 可选 Skill

Skill 只是辅助，不能成为任务前置条件。`unitytest/dynamic-bug-recording`可创建首个 BG/TC/引用骨架，`unitytest/static-bug-validation`可原子更新静态 LINK。Skill 禁用、未复制或脚本不可用时，使用文本工具按本文标签建立相同结构并继续任务，产物和验收标准完全相同。

## 10. 完成检查

- 两个容器各出现一次、均正确关闭、顺序正确。
- 文档标题、分区标题、FG/FC/CK/BG/TC 层级和八个字段标题与第 5.1 节完整标准案例一致；每个标签行都有具体可见标题，不含类型名或方括号占位。
- 每个中央波形标题逐字复用关联 TC 的可见标题并追加“波形”。
- 每个非零 BG 至少有一个真实 Fail TC和完整八字段分析。
- 每个 BG 的全部 TC/引用连续位于 BG 标题后，八个`<BUG-*>`字段位于最后一个 TC/引用后，字段开始后不再出现 TC。
- 每个 BG/TC 紧随精确`<WAVEFORM-REF>`，链接到该 TC 的稳定锚点。
- 每个关联 TC 在中央分区恰有一份记录，无重复、无孤儿。
- `bug_tags`、BG/TC 引用和`bug_evidence`三者完全一致。
- 所有逐 Bug `required_signals`都在顶层签名信号并集中，viewer显示同一信号集合。
- receipt、fingerprint、窗口、pattern、signal_groups、viewer与真实工具结果一致。
- 共享与逐 Bug 语义结论均已完成，无`<BUG-TODO>`。
- 普通 stage 持续保留已签名证据；仅严格 current-replay stage 要求全面重放和必要更新。
