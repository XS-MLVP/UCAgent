# DUT Bug 分析指南

本文定义动态与静态 Bug 文档的唯一机器格式。显示标题可以本地化；尖括号标签、YAML 字段、签名 receipt 和 viewer token 必须保持本文规定的结构。

## 1. 先分类

- 正确测试稳定 Fail 且规格、采样和预期均正确：保留严格断言，记录动态 DUT Bug。
- 测试、参考模型、fixture、API、Mock、复位、时序、依赖或环境错误：修复到 Pass，不记录 DUT Bug。
- 仅由源码审查发现、尚未动态复现：只写入`{DUT}_static_bug_analysis.md`，使用`BG-STATIC-*`。
- 静态候选经测试确认：动态文档新建独立`BG-NAME-XX`，静态文档用`LINK-BUG`关联。

动态 Bug 的 Fail 测试必须有真实 WaveInfo 证据。不能弱化断言、伪造 receipt、复制 viewer token，或删除仍能稳定复现 Bug 的 TC/BG 来绕过验收。

## 2. 文档分区

`{DUT}_bug_analysis.md`必须各有一个封闭分区，且顺序固定：

````markdown
# DUT Dynamic Bug Analysis

<DYNAMIC-BUGS>
<!-- FG/FC/CK/BG/TC and Bug analysis live here. -->
</DYNAMIC-BUGS>

<WAVEFORM-EVIDENCE>
<!-- All unique per-TC waveform records live here. -->
</WAVEFORM-EVIDENCE>
````

`<DYNAMIC-BUGS>`中只放 Bug 层级、TC 引用和 Bug 分析，不放波形 YAML 或 viewer。`<WAVEFORM-EVIDENCE>`中集中放全部波形记录，不放 FG/FC/CK/BG 标签。

## 3. Bug 层级与引用

标签顺序为`FG -> FC -> CK -> BG -> TC`。一个非零置信度 BG 至少关联一个真实 Fail TC。每个 BG/TC 关联必须紧跟一个由工具生成的链接：

```markdown
<FG-ARITHMETIC>
<FC-ADD>
<CK-OVERFLOW>
<BG-CIN-OVERFLOW-98>
- <TC-tests/test_adder.py::test_overflow>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-0123456789abcdef)

<BUG-OVERVIEW>
...
<BUG-SYMPTOMS>
...
<BUG-TRIGGER>
...
<BUG-ROOT-CAUSE>
...
<BUG-SOURCE-EVIDENCE>
...
<BUG-CAUSAL-CHAIN>
...
<BUG-FIX>
...
<BUG-RETEST>
...
```

锚点由规范化 TC 标签稳定计算，禁止手工猜测或改写。使用`ApplyWaveInfoEvidence`创建或修复`<WAVEFORM-REF>`。

同一 Bug 有多个 Fail TC：每个 TC 各有一条引用和一份中央记录。同一 Fail TC 触发多个 Bug：每个 BG 下都引用相同锚点，但中央记录仍只有一份。

## 4. 中央波形记录

每个规范化 TC 在整个文档中有且只有一个`<WAVEFORM-TC-...>`记录：

````markdown
<WAVEFORM-EVIDENCE>

<a id="waveform-0123456789abcdef"></a>
### <WAVEFORM-TC-tests/test_adder.py::test_overflow>
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

同一 Bug 有多个 Fail TC 时，对每个 BG/TC 分别调用一次。目标 TC 不存在且 BG 位置唯一时，Apply 会创建 TC 和引用；LLM 不得手工复制 BG、创建兄弟 TC或拼接 receipt。同一 Fail TC 揭示多个独立 Bug 时，使用相同 TC 和不同 BG 分别调用；每次调用只更新目标关联，不会覆盖其他 Bug。签名窗口和 `signal_groups` 同时支持各缺陷时才能复用 receipt。

### 5.1 建立骨架并分阶段写入

`record_dynamic_bug.py`是可选脚本，只接收`BG/TC/BD`并创建新 Bug 的第一份 BG/TC、引用和八个带`<BUG-TODO>`的分析章节。脚本不可用时也不阻塞整个流程，使用文本编辑工具参照本节最小骨架建立相同结构：

```markdown
<DYNAMIC-BUGS>
<FG-NAME>
<FC-NAME>
<CK-NAME>
<BG-NAME-XX>
- <TC-test_file.py::test_name>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#tool-generated-anchor)
<BUG-OVERVIEW>
<BUG-TODO>
<BUG-SYMPTOMS>
<BUG-TODO>
<BUG-TRIGGER>
<BUG-TODO>
<BUG-ROOT-CAUSE>
<BUG-TODO>
<BUG-SOURCE-EVIDENCE>
<BUG-TODO>
<BUG-CAUSAL-CHAIN>
<BUG-TODO>
<BUG-FIX>
<BUG-TODO>
<BUG-RETEST>
<BUG-TODO>
</DYNAMIC-BUGS>
```

锚点和引用仍由 Apply 修复为精确值。不要为同一 BG 的后续 Fail TC 复制该结构。调用 `ApplyWaveInfoEvidence`写入中央记录后，必须清除八个分析章节中的全部 `<BUG-TODO>`；任何非零 BG 残留占位都不能完成。

## 6. 证据保留与重放

签名 receipt、中央 YAML 和 viewer 是持续保留的证据。普通增量 stage 使用`require_current_replay=false`：只验证文档、签名 receipt 与关联，不因后来测试、session 或波形文件变化而要求更新。

只有对应验证项配置`require_current_replay=true`时，才对所有唯一 TC 重放当前波形。重放失败或窗口、候选、信号集合、事件变化时，按返回的 WaveInfo/Apply 调用取得新 receipt 并更新中央记录。

新增一个关联 Bug 属于证据范围扩展：即使普通 stage 不重放，也必须确认当前 receipt 的信号并集足以分析新 Bug；不足时按上一节替换 receipt。

移除或重新分类 Bug 时，同步删除该 BG/TC 引用及中央记录中的`bug_tags`/`bug_evidence`项。如果 TC 的最后一个 Bug 关联被移除，必须删除整份中央`<WAVEFORM-TC-...>`记录，不能留下孤儿波形。

## 7. Bug 根因字段

八个标记必须唯一、有序、内容非空。`<BUG-SOURCE-EVIDENCE>`有两种互斥模式：

- 有源码：包含真实`path:L1-L2`与完整 HDL fenced 代码，并在语言原生注释中各放一次`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`。
- 无可访问源码：单独写`<BUG-SOURCE-UNAVAILABLE>`，用规格、接口、日志和波形完成黑盒因果链，不虚构源码位置。

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
- 每个非零 BG 至少有一个真实 Fail TC和完整八字段分析。
- 每个 BG/TC 紧随精确`<WAVEFORM-REF>`，链接到该 TC 的稳定锚点。
- 每个关联 TC 在中央分区恰有一份记录，无重复、无孤儿。
- `bug_tags`、BG/TC 引用和`bug_evidence`三者完全一致。
- 所有逐 Bug `required_signals`都在顶层签名信号并集中，viewer显示同一信号集合。
- receipt、fingerprint、窗口、pattern、signal_groups、viewer与真实工具结果一致。
- 共享与逐 Bug 语义结论均已完成，无`<BUG-TODO>`。
- 普通 stage 持续保留已签名证据；仅严格 current-replay stage 要求全面重放和必要更新。
