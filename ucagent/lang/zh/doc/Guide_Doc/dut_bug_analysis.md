
# DUT Bug 分析指南

本文定义动态与静态 Bug 文档的唯一机器格式。尖括号标签在 Markdown 渲染后可能不可见，因此 FG/FC/CK/BG/TC 和根因实体必须同时写出能独立表达含义的中文可见标题；不能用类型名代替具体描述。动态 Bug 文档必须使用本文定义的 Markdown 层级、BG 三字段、ROOT 五字段、根因双向链接和中央波形结构；YAML 字段、签名 receipt 与 viewer token 必须由工具生成并保持原样。

动态 Bug 的唯一目标文件是`{OUT}/{DUT}_bug_analysis.md`。“动态 Bug 分析”只是文档可见标题，不是文件名生成规则；禁止根据标题派生或创建另一个文件。静态候选只写入`{OUT}/{DUT}_static_bug_analysis.md`。

文档中的 TC 身份始终使用当前报告的函数级 node ID：删除报告附带的源码行范围，但完整保留 workspace 相对文件路径、可选类名和函数名。非参数化用例在不同接口中使用同一个 node ID；若 Toffee 把多个参数化执行实例聚合到一个函数级报告项，报告的`tests.test_case_instances`会列出实际执行实例，此时文档/Apply/YAML继续使用稳定的函数级 TC，WaveInfo选择其中一个实际失败的精确参数化实例：

| 使用位置 | 唯一写法 |
|---|---|
| 动态 Bug Markdown | `- {visible_title} <TC-{exact_report_node_id}>` |
| `record_dynamic_bug.py`/`ApplyWaveInfoEvidence`参数及中央 YAML `test_case` | `TC-{exact_report_node_id}` |
| `WaveInfo.test_case_name` | 非参数化时为`{exact_report_node_id}`；聚合参数化时为`tests.test_case_instances`中的一个精确 FAILED child node |

参数化 child 只有在删除末尾`[...]`后，与文档 TC 的完整路径、可选类名和函数名逐字相同时才属于该 TC。`file.py::test_x[p]`与`tests/file.py::test_x`、不同类或不同函数永远不等价，不能用文件名相似、函数名相同或目录前缀猜测建立关联。中央 YAML 中工具生成的`executed_test_case`记录实际 WaveInfo child，`test_case`仍记录文档 TC。

TC目录只取当前Checker返回的`Configured TC output directory`实际值，不从本文案例推断。本文的`TC-tests/...`只展示Markdown层级，禁止复制为实际标签。实际文档 node ID 必须从同一次Checker反馈的当前报告选择：确认文件路径以配置目录开头，只删除`:start-end`或`:line`报告行范围；Markdown、脚本/Apply与YAML在最前面加`TC-`。其余路径、类名和函数名一个字符也不能增删。相似节点不代表路径等价。

`RunTestCases(target=...)`是唯一使用另一种路径基准的接口：target 相对于工具返回的实际 pytest 工作目录/配置 TC 输出目录。例如配置目录为`unity_test/tests`时，运行该目录中的用例应传`test_file.py::test_x`，不得再传`unity_test/tests/test_file.py::test_x`。Bug 文档 TC、WaveInfo 和 Apply 仍使用 workspace 相对完整 node ID。工具若返回`PYTEST_TARGET_DIRECTORY_PREFIX`，必须逐字使用其中的`correct_target`重试；这只是修正 RunTestCases 调用，不表示两种 node 字符串等价。

## 1. 先分类

- 每个 Fail TC 都不预设责任方。正确测试稳定 Fail 且规格、采样和预期均正确：保留严格断言，记录动态 DUT Bug。
- 测试、参考模型、fixture、API、Mock、复位、时序、依赖或环境错误：修复到 Pass，不记录 DUT Bug。
- 仅由源码审查发现、尚未动态复现：只写入`{DUT}_static_bug_analysis.md`，使用`BG-STATIC-*`。
- 静态候选经测试确认：动态文档新建独立`BG-NAME-XX`，静态文档用`LINK-BUG`关联。

动态 Bug 的 Fail 测试必须有真实 WaveInfo 证据。不能弱化断言、伪造 receipt、复制 viewer token，或删除仍能稳定复现 Bug 的 TC/BG 来绕过验收。

进入 WaveInfo、创建或更新非零 BG、引用静态候选之前，对每个 Fail TC 必须完成以下门禁：

1. 从功能规格、独立参考模型或可验证公式独立计算`specification_expected`。不得直接相信模板注释、已有断言、静态候选或可疑 RTL；静态候选不能覆盖 TC 级反证。
   若激励包含取反、编码、掩码、分包或 carry/borrow 等变换，必须从实际驱动到 DUT 的值和规格运算重新计算预期，不能拿变换前操作数的预期比较变换后的输入。例如`a + (~b) + 0 = a - b - 1`，实现`a - b`必须驱动`a + (~b) + 1`。
2. 明确对照`input | specification_expected | test_expected | actual | classification`。`specification_expected`与`test_expected`不一致时，修正测试并重跑到 Pass，禁止调用 WaveInfo 或记录 Bug。
3. expected 一致后，核对测试激励、API/driver、callback、`Step`、采样边沿、有效条件、响应延迟、fixture、参考模型、复位和环境。
4. 核对该 TC 关联 CK 的 coverage/check function 是否真实表达规格、`CovGroup.sample()`是否执行以及采样时机是否正确。CK predicate 或 sample 错误属于验证问题，必须修复并重跑。
   不得为了满足失败 CK 门禁而把当前 Pass 用例改成 Fail。正确修复 predicate、关联、采样或驱动后，CK 可以转为 Pass；此时该 CK 不再需要 Fail 复现用例。只有 CK 契约正确且 DUT 确实违反规格时，正确测试才应自然 Fail。
5. 只有上述项目全部正确、DUT `actual`仍违反规格时，才能将`classification`写为 DUT Bug，随后调用 WaveInfo 并创建或更新非零 BG。其他分类必须修复到 Pass。

批量实现阶段只分析当前批次 TC 及当前报告为这些 TC 关联的 CK。属于未来未实现批次、且未与当前 TC 关联的失败 CK，不得在当前批次创建无关 TC/BG；留到所属批次驱动和分类。最终综合与 Bug 记录阶段仍必须满足全部失败 CK 的单向门禁。

Check/Complete 的最终分类必须同时满足三个方向：每个非零动态 BG 至少关联一个由当前报告确认、且映射到同一 CK 的正确 Fail TC；每个阶段结束时仍为 Fail 的 DUT 测试必须在其报告关联的至少一个 CK 下进入非零动态 BG；每个阶段结束时仍失败的 CK 必须至少有一个由当前报告关联到该精确 FG/FC/CK 路径的正确 Fail TC，并在相同 CK/BG/TC 关系下完成记录。前两个条件不要求 Fail TC 所关联的 CK 也失败：TC 可以因断言发现 DUT Bug 而 Fail，同时成功触发并覆盖该 CK，因此 CK 可以已经 Pass。TC 状态与 CK 覆盖状态相互独立，不能由 TC Fail 反推 CK Fail。失败 CK 的要求是另一个单向条件。整体关系是多对多而不是一一对应：一个 BG 可以有多个 Fail TC，一个 Fail TC也可以揭示多个独立 BG。测试、断言、预期值、fixture、API、参考模型、覆盖检查或采样、复位、时序、依赖和环境问题必须修复到 Pass，不得为了满足关系检查制造 Fail、关联无关 TC 或写入动态 DUT Bug。

CK 失败本身不证明 DUT 存在 Bug。必须先检查该 CK 的 coverage/check function 是否真实表达规格、`CovGroup.sample()`调用和采样时机是否正确、测试激励或 driver 是否真正触发目标场景、独立规格 expected 与测试 expected 是否一致，以及结果是否在有效边沿、响应条件和延迟后采样。上述任一项错误都属于验证问题，必须修复并重跑。只有这些条件都正确后，DUT 错误行为仍使正确复现 TC 自然 Fail，才能创建非零动态 BG 并取证；该 TC 关联的 CK 可以已经 Pass。若 CK 自身仍 Fail，则独立应用“失败 CK 必须有同 CK Fail TC”的单向门禁。

### 1.1 局部测试报告与累计 Bug 文档

`{DUT}_bug_analysis.md`是跨阶段累计文档。有些阶段或批次只运行配置选中的测试子集，例如随机阶段只运行`{OUT}/tests/test_{DUT}_random*.py`。这种 Check/Complete 返回的是局部报告，只能更新报告中逐字出现的 TC：当前 Fail 必须完成分类，当前 Pass 不得继续作为动态 Bug 复现证据；完全未出现在本轮报告中的历史 TC 保持原状。历史 TC 缺席不表示它已 Pass、失效或 node ID 错误，禁止仅因此删除、改名、移动或重新取证其 TC/BG、ROOT 双向关联和中央波形记录。最终综合阶段运行完整 DUT 测试集合后，才对累计文档中的全部 TC 执行全量一致性门禁。

同一 TC 可以真实触发多个 CK，并在多个完整`FG/FC/CK/BG`路径下出现；这些 CK 可以已经通过覆盖，不能由 TC Fail 反推 CK Fail。同一精确路径内，一个 TC 只能出现一次；同名 BG/TC 位于不同 CK 时是不同路径关联，必须全部保留。调用`ApplyWaveInfoEvidence`时用完整`checkpoint_path`消除路径歧义，而该 TC 在`<WAVEFORM-EVIDENCE>`中仍只保留一份中央波形记录。

某个局部阶段没有确认新的 DUT Bug 时，不新增 BG、ROOT 或波形记录，但仍保留累计文档中的历史记录。只有整个累计文档从未记录任何动态 Bug 时，才使用第 2.1 节的三个空容器结构。

## 2. 文档分区

`{DUT}_bug_analysis.md`必须各有一个封闭分区，且顺序固定：

````markdown

# DUT 动态 Bug 分析

## 动态 Bug 记录

<DYNAMIC-BUGS>
<!-- FG/FC/CK/BG/TC and Bug analysis live here. -->
</DYNAMIC-BUGS>

## 根因分析

<ROOT-CAUSES>
<!-- Each root cause is defined once and linked to one or more BG paths. -->
</ROOT-CAUSES>

## 波形证据

<WAVEFORM-EVIDENCE>
<!-- All unique per-TC waveform records live here. -->
</WAVEFORM-EVIDENCE>
````

`<DYNAMIC-BUGS>`中只放 Bug 层级、TC 引用和 Bug 分析，不放波形 YAML 或 viewer。`<ROOT-CAUSES>`位于动态 Bug 分区之后、中央波形分区之前；每个根因只定义一次，并通过内嵌完整 FG/FC/CK/BG 路径的`<RELATED-BUG-...>`及其可点击链接反向列出关联。`<WAVEFORM-EVIDENCE>`中集中放全部波形记录，不放 FG/FC/CK/BG 标签。

### 2.1 未发现动态 Bug

没有发现动态 Bug 时仍必须保留唯一目标文件，不得省略文件、另建摘要文件、写`BG-*-0`占位或在容器内写“未发现 Bug”等说明。完成态必须是以下精确空结构；三个容器正文均为空，不含注释、TC/BG、ROOT 或波形记录：

```markdown

# {DUT} 动态 Bug 分析

## 动态 Bug 记录

<DYNAMIC-BUGS>
</DYNAMIC-BUGS>

## 根因分析

<ROOT-CAUSES>
</ROOT-CAUSES>

## 波形证据

<WAVEFORM-EVIDENCE>
</WAVEFORM-EVIDENCE>
```

## 3. Bug 层级与引用

标签顺序为`FG -> FC -> CK -> BG -> TC`。可见标题、Markdown 层级与标签必须写在同一行，并使用以下固定结构。可见标题是该条目的具体语义描述，不能只是标签类型的释义。一个非零置信度 BG 至少关联一个真实 Fail TC。一个 BG 的所有 TC 及其`<WAVEFORM-REF>`必须连续位于该`<BG-*>`标题之后；随后只写三个 BG 字段。`<BUG-TRIGGER>`正文末尾紧跟唯一的`<CAUSE-REF-ROOT-XXX>`，不再在 BG 中写源码、因果链、修复或复验字段：

```markdown

### 算术功能 <FG-ARITHMETIC>

#### 加法结果 <FC-ADD>

##### 溢出输出 <CK-OVERFLOW>

###### 进位输入溢出丢失（98%） <BG-CIN-OVERFLOW-98>

- 进位输入触发溢出 <TC-tests/test_adder.py::test_overflow>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-0123456789abcdef)

###### Bug 概述

<BUG-OVERVIEW>
...

###### 现象与严重度

<BUG-SYMPTOMS>
...

###### 触发条件与影响

<BUG-TRIGGER>
...
<CAUSE-REF-ROOT-CIN-OVERFLOW> [中间量宽度不足](#root-cause-cin-overflow)
```

可见标题来源固定：FG 和 FC 使用`{OUT}/{DUT}_functions_and_checks.md`中对应功能层级的标题；CK 使用同一文档中该 CK 的检查点名称；BG 使用该缺陷的具体问题描述；TC 使用测试函数 docstring 的首个非空描述行。若同一 TC 关联多个 BG，各处必须使用相同 TC 可见标题。锚点由规范化 TC 标签稳定计算，禁止手工猜测或改写。使用`ApplyWaveInfoEvidence`创建或修复`<WAVEFORM-REF>`。

同一 Bug 有多个 Fail TC：每个 TC 各有一条引用和一份中央记录。同一 Fail TC 触发多个 Bug：每个 BG 下都引用相同锚点，但中央记录仍只有一份。

每个根因实体必须使用一个在整个文档中唯一的`<ROOT-XXX>`标签，并至少关联一个真实存在的完整 BG 路径；禁止创建孤立根因。一个 BG 必须且只能关联一个根因。如果两个缺陷组合后才产生可复现错误，该组合本身就是一个带独立`<ROOT-XXX>`标签的根因实体。一个根因可以关联多个不同 CK 作用域的 BG。BG 侧使用内嵌完整根因标签的`<CAUSE-REF-ROOT-XXX>`，根因侧使用内嵌完整 BG 路径的`<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>`；两侧都紧跟可点击链接且必须双向一致。链接必须指向工具生成的稳定锚点。源码证据、因果链、修复建议、风险和复验只写在 ROOT 实体中，并覆盖该 ROOT 的全部关联 BG。

```markdown

## 根因分析

<ROOT-CAUSES>
<a id="root-cause-cin-overflow"></a>

### 中间量宽度不足 <ROOT-CIN-OVERFLOW>

#### 根因分析
<ROOT-CAUSE-ANALYSIS>
中间量在计算完整结果前被声明为过窄宽度，最高位在输出赋值前已经丢失。

#### 源码证据
<ROOT-SOURCE-EVIDENCE>
<ROOT-SOURCE-UNAVAILABLE>
当前示例省略具体 HDL；真实文档必须提供源码行范围或明确说明源码不可访问。

#### 因果链
<ROOT-CAUSAL-CHAIN>
完整输入在有效窗口产生进位，过窄中间量截断最高位，所有关联 BG 的输出均观察到 `cout=0`。

#### 修复建议
<ROOT-FIX>
将中间量扩展为 `WIDTH+1` 位，并在所有关联路径重新验证。

#### 风险与复验
<ROOT-RETEST>
覆盖无进位、边界进位、最大值和随机组合，并回归所有关联 CK。

#### 关联 Bug
<RELATED-BUGS>
- <RELATED-BUG-FG-ARITHMETIC/FC-ADD/CK-OVERFLOW/BG-CIN-OVERFLOW-98> [FG-ARITHMETIC/FC-ADD/CK-OVERFLOW/BG-CIN-OVERFLOW-98](#bug-0123456789abcdef)
</ROOT-CAUSES>
```

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
  executed_test_case: tests/test_adder.py::test_overflow
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

BG 条目中的波形关联部分只保留 TC 和`<WAVEFORM-REF>`，其后三个 BG 字段仍按本文结构填写；YAML 与 viewer 只出现在该 TC 的中央记录中。

## 5. WaveInfo 与 Apply 工具

MCP 调用中未使用的可选参数按工具 schema 传空字符串、空数组或`-1`哨兵；工具返回中的`null`是其 canonical 表示，不能再把`null`作为下一次 MCP 参数。

先读取Checker给出的实际`Configured TC output directory`、函数级报告 node ID 和可选的`tests.test_case_instances`。非参数化时，WaveInfo只从最终`<TC-...>`去掉最前面的`TC-`。聚合参数化时，文档 TC 保持不变，metadata探索、pattern探索和最终取证必须从`tests.test_case_instances`选择一个实际 FAILED child，并对同一精确 child 完成 WaveInfo；不得只传函数名或自行拼接参数ID。

无参数 inventory 中的`test_case_name_hint`和`recommended_call.test_case_name`只是波形文件 basename 定位提示，不建立 pytest 源码身份。它们可以帮助确认是否存在对应波形，但不能覆盖目标 TC 或报告给出的完整 node ID。Checker/工具返回的`similar_test_source_files`或相似节点同样只供核对拼写，不能自动选中、合并证据或替换标签。

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

若 Apply 返回`receipt_test_mismatch`或`matching_final_receipt_not_found`：

1. 保持`test_case_tag`逐字不变，不尝试增加或删除路径前缀。
2. 若`details.parameterized_receipts`非空，将其中的完整`test_case_name`与当前报告`tests.test_case_instances`逐字核对，选择实际 FAILED child 并用该 node 重新完成最终 WaveInfo；不得按波形 basename、文件名相似或参数字面猜测。若返回`details.recovery_call`，则原样调用一次 WaveInfo。
3. 使用新调用返回的`receipt_id`和原`test_case_tag`再次调用 Apply。
4. 不得手工写 receipt-backed YAML、waveform anchor、viewer URL 或 token。

同一 tool、status 和 target 连续返回相同错误后，不得继续尝试相似参数。没有`recovery_call`，或原样执行后仍返回同一错误时，将其报告为工具契约阻塞并停止修改当前 Bug/波形记录；不要用文本编辑替代签名工具。

6. 根据规格、timeline 和 RTL 完成中央波形语义字段、BG 三字段和 ROOT 五字段。`<BUG-TODO>`不能残留。

`signal_groups` 的固定子字段为`clock_mode`、`clocks`、`inputs`、`outputs`、`protocol`和`key_signals`。viewer 中的顺序按`clocks -> inputs -> outputs -> protocol -> key_signals`构造。最终调用若缺少完整角色，先从`signal_catalog`补全真实路径；例如接口确实存在`TOP.dut.ready`时应放入`protocol`，不能只显示结果 data。

先确认事务有效，再判断数据是否错误。调用一次 `Step(1)` 只表示仿真时间推进了一步；必须检查 API 内部是否已经调用 `Step`、等待握手或采样结果。无效周期的一次单点 data mismatch 只能作为继续调查的线索。请求接受、响应有效和信号角色必须结合规格、API/driver和RTL判断，不能根据特定信号名猜测。

同一 TC 新增 Bug 时，对新 BG 再调用一次 Apply。若原 receipt 已包含新 Bug 所需信号，工具复用中央记录并保留已有分析；若需要新增信号，重新调用最终 WaveInfo，使`signal_groups`成为所有 Bug 所需信号的并集，再使用`replace_existing=true`。替换不同 receipt 时，工具保留各 BG 的`required_signals`，并重置共享和逐 Bug 语义结论，要求重新审查。

同一 Bug 有多个 Fail TC 时，对每个 BG/TC 分别调用一次。目标 TC 不存在且 BG 位置唯一时，Apply 会从目标测试函数的非空 docstring 读取中文可见标题，在该 BG 的首个分析标题之前创建 TC 和引用；测试源码或 docstring 不存在时会拒绝生成，LLM 不得猜测标题。LLM 不得手工复制 BG、创建兄弟 TC或拼接 receipt。同一 Fail TC 揭示多个独立 Bug 时，使用相同 TC 和不同 BG 分别调用；每次调用只更新目标关联，不会覆盖其他 Bug。签名窗口和 `signal_groups` 同时支持各缺陷时才能复用 receipt。

### 5.1 完整标准案例

以下完整案例中的`tests/...`仅用于展示结构，不提供实际TC目录。实际操作必须使用Checker明确返回的`Configured TC output directory`及完整FAILED report node ID，禁止从案例复制任何TC路径。

以下案例是动态 Bug 文档的完整标准结构。它同时展示两个独立 ROOT、三个 BG、两个 TC 和两份中央波形记录：第一个 ROOT 关联两个 BG，这两个 BG 由同一个 TC 揭示并共用唯一一份中央波形；第二个 ROOT 关联另一个 BG 和 TC，该 TC 拥有自己的中央波形。实际文档保留文档标题、Markdown 层级、标签位置、BG/ROOT 字段顺序和 fenced block 位置；FG/FC/CK/BG/TC 标题必须按实际语义填写。案例中的 receipt、fingerprint、时间和 viewer token 只说明字段形态；实际值必须来自当前工具结果。

`````markdown

# Adder 动态 Bug 分析

## 动态 Bug 记录

<DYNAMIC-BUGS>

### 算术功能 <FG-ARITHMETIC>

#### 加法结果 <FC-ADD-RESULT>

##### 进位输出 <CK-CARRY-OUT>

<a id="bug-5f90c59ed3dbea70"></a>

###### 完整和进位丢失（95%） <BG-SUM-CARRY-DROPPED-95>

- 进位输入产生进位 <TC-tests/test_adder.py::test_cin_carry>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-9f3516eabf18829d)

###### Bug 概述

<BUG-OVERVIEW>
当 `a + b + cin` 产生第 `WIDTH+1` 位进位时，DUT 在组合加法路径中提前截断中间结果，导致 `cout` 始终为 0。

###### 现象与严重度

<BUG-SYMPTOMS>
边界用例 `a=8'hff, b=8'h00, cin=1` 的期望结果为 `{cout,sum}=9'h100`，实际结果为 `9'h000`。该问题会破坏所有依赖进位输出的多字加法，严重度为高。

###### 触发条件与影响

<BUG-TRIGGER>
触发条件是两个操作数与 `cin` 的无符号和大于 `2^WIDTH-1`。低 `WIDTH` 位未溢出时结果正常；发生进位时，`sum` 保留低位而 `cout` 丢失，影响 `CK-CARRY-OUT` 及其上层级联运算。
<CAUSE-REF-ROOT-SUM-CARRY-WIDTH> [加法中间量宽度不足](#root-cause-sum-carry-width)

##### 完整结果 <CK-FULL-RESULT>

<a id="bug-e510f134f5bdaabd"></a>

###### 完整结果被截断（93%） <BG-FULL-RESULT-TRUNCATED-93>

- 进位输入产生进位 <TC-tests/test_adder.py::test_cin_carry>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-9f3516eabf18829d)

###### Bug 概述

<BUG-OVERVIEW>
完整结果检查要求把 `cout` 与 `sum` 作为一个 `WIDTH+1` 位结果比较；DUT 在产生进位时返回的组合结果缺少最高位。

###### 现象与严重度

<BUG-SYMPTOMS>
同一边界用例期望完整结果为 `9'h100`，实际 `{cout,sum}` 为 `9'h000`。依赖完整结果总线进行范围判断的使用方会把溢出结果误判为 0，严重度为高。

###### 触发条件与影响

<BUG-TRIGGER>
任意使完整无符号和超过 `WIDTH` 位的输入都会触发；影响 `CK-FULL-RESULT` 的整体数值语义。该 BG 与 `BG-SUM-CARRY-DROPPED-95` 由同一 TC 揭示，但仍是不同 CK 下的独立 BG 路径。
<CAUSE-REF-ROOT-SUM-CARRY-WIDTH> [加法中间量宽度不足](#root-cause-sum-carry-width)

#### 饱和加法 <FC-SATURATING-ADD>

##### 饱和结果 <CK-SATURATION-OUTPUT>

<a id="bug-d0f8a6d4227d547c"></a>

###### 饱和功能未生效（92%） <BG-SATURATION-DISABLED-92>

- 饱和加法达到上限 <TC-tests/test_adder.py::test_saturation_limit>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#waveform-547f03228d4694a0)

###### Bug 概述

<BUG-OVERVIEW>
启用无符号饱和加法后，DUT 没有在结果溢出时钳位到最大值，而是输出截断后的低位结果。

###### 现象与严重度

<BUG-SYMPTOMS>
用例驱动 `a=8'hff, b=8'h01, cin=0, saturate_en=1`，期望 `sat_sum=8'hff`，实际为 `8'h00`。所有依赖饱和保护的累加路径都可能回绕，严重度为高。

###### 触发条件与影响

<BUG-TRIGGER>
触发条件是 `saturate_en=1` 且无符号完整和大于 `8'hff`；不溢出时透传结果正常。该问题只影响饱和结果选择路径，与普通加法的进位输出检查相互独立。
<CAUSE-REF-ROOT-SATURATION-DETECTOR-CONSTANT> [饱和溢出检测被固定为无效](#root-cause-saturation-detector-constant)

</DYNAMIC-BUGS>

## 根因分析

<ROOT-CAUSES>
<a id="root-cause-sum-carry-width"></a>

### 加法中间量宽度不足 <ROOT-SUM-CARRY-WIDTH>

#### 根因分析
<ROOT-CAUSE-ANALYSIS>
`sum_full` 只声明为 `WIDTH` 位，却承接 `WIDTH+1` 位表达式；赋值时最高进位位被截断，后续拼接只能在已截断值前补 0，因此无法恢复真实 `cout`。

#### 源码证据
<ROOT-SOURCE-EVIDENCE>
首个错误位于 `rtl/Adder.sv:24-26`：
```systemverilog
24: logic [WIDTH-1:0] sum_full; // <ROOT-SOURCE-FIRST-ERROR> 中间量少一位，无法保存进位。
25: assign sum_full = {1'b0, a} + {1'b0, b} + cin; // <ROOT-SOURCE-PROPAGATION> 宽表达式在写入 sum_full 时被截断。
26: assign {cout, sum} = {1'b0, sum_full}; // <ROOT-SOURCE-OBSERVABLE> 输出端观察到固定为 0 的 cout。
```

#### 因果链
<ROOT-CAUSAL-CHAIN>
测试在有效组合输入窗口驱动 `8'hff + 8'h00 + 1`；完整和为 `9'h100`；第 25 行写入 8 位 `sum_full` 后变为 `8'h00`；第 26 行再补零形成 `9'h000`；因此 `CK-CARRY-OUT` 观察到进位丢失，`CK-FULL-RESULT` 观察到完整结果被截断，两个关联 BG 与同一份波形和失败断言一致。

#### 修复建议
<ROOT-FIX>
将 `sum_full` 声明为 `logic [WIDTH:0]`，直接执行 `assign {cout, sum} = sum_full;`，保持表达式和中间存储均为 `WIDTH+1` 位。

#### 风险与复验
<ROOT-RETEST>
复验 `0+0+0`、最大值加 0、最大值加 1、最大值加最大值及随机输入；同时回归 `CK-CARRY-OUT` 和 `CK-FULL-RESULT`，并在新波形中确认最高位在 `sum_full`、`cout` 和完整结果之间一致传播。

#### 关联 Bug
<RELATED-BUGS>
- <RELATED-BUG-FG-ARITHMETIC/FC-ADD-RESULT/CK-CARRY-OUT/BG-SUM-CARRY-DROPPED-95> [FG-ARITHMETIC/FC-ADD-RESULT/CK-CARRY-OUT/BG-SUM-CARRY-DROPPED-95](#bug-5f90c59ed3dbea70)
- <RELATED-BUG-FG-ARITHMETIC/FC-ADD-RESULT/CK-FULL-RESULT/BG-FULL-RESULT-TRUNCATED-93> [FG-ARITHMETIC/FC-ADD-RESULT/CK-FULL-RESULT/BG-FULL-RESULT-TRUNCATED-93](#bug-e510f134f5bdaabd)

<a id="root-cause-saturation-detector-constant"></a>

### 饱和溢出检测被固定为无效 <ROOT-SATURATION-DETECTOR-CONSTANT>

#### 根因分析
<ROOT-CAUSE-ANALYSIS>
`saturation_overflow` 被常量 `1'b0` 驱动，导致饱和选择条件在所有输入下都为假；即使完整加法已经溢出，结果选择器也只会输出回绕后的低位结果。

#### 源码证据
<ROOT-SOURCE-EVIDENCE>
首个错误位于 `rtl/Adder.sv:40-43`：
```systemverilog
40: logic saturation_overflow;
41: assign saturation_overflow = 1'b0; // <ROOT-SOURCE-FIRST-ERROR> 溢出检测被固定为无效。
42: assign saturated_sum = saturate_en && saturation_overflow ? {WIDTH{1'b1}} : sum_full; // <ROOT-SOURCE-PROPAGATION> 错误条件使选择器始终走普通结果分支。
43: assign sat_sum = saturated_sum; // <ROOT-SOURCE-OBSERVABLE> 饱和输出观察到回绕值而不是最大值。
```

#### 因果链
<ROOT-CAUSAL-CHAIN>
测试驱动 `8'hff + 8'h01` 并使能饱和；数学结果超过 8 位；第 41 行仍令 `saturation_overflow=0`；第 42 行选择已回绕的 `sum_full=8'h00`；第 43 行输出 `sat_sum=8'h00`，与关联 BG 的独立失败波形一致。

#### 修复建议
<ROOT-FIX>
用 `WIDTH+1` 位完整和的最高位生成 `saturation_overflow`，并仅在 `saturate_en && saturation_overflow` 时选择 `{WIDTH{1'b1}}`；不要从已经截断的低位结果反推溢出。

#### 风险与复验
<ROOT-RETEST>
分别复验饱和关闭、饱和开启但未溢出、恰好等于最大值、超过最大值和随机边界输入；确认修复不改变普通加法模式，并在第二份波形中确认检测信号与结果选择同步变化。

#### 关联 Bug
<RELATED-BUGS>
- <RELATED-BUG-FG-ARITHMETIC/FC-SATURATING-ADD/CK-SATURATION-OUTPUT/BG-SATURATION-DISABLED-92> [FG-ARITHMETIC/FC-SATURATING-ADD/CK-SATURATION-OUTPUT/BG-SATURATION-DISABLED-92](#bug-d0f8a6d4227d547c)
</ROOT-CAUSES>

## 波形证据

<WAVEFORM-EVIDENCE>

<a id="waveform-9f3516eabf18829d"></a>

### 进位输入产生进位波形 <WAVEFORM-TC-tests/test_adder.py::test_cin_carry>

```yaml
waveform_analysis:
  test_case: TC-tests/test_adder.py::test_cin_carry
  bug_tags:
    - BG-FULL-RESULT-TRUNCATED-93
    - BG-SUM-CARRY-DROPPED-95
  status: confirmed
  receipt_id: 0123456789abcdef0123456789abcdef
  result_fingerprint: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  executed_test_case: tests/test_adder.py::test_cin_carry
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
    BG-FULL-RESULT-TRUNCATED-93:
      required_signals:
        - TOP.dut.a[7:0]
        - TOP.dut.b[7:0]
        - TOP.dut.cin
        - TOP.dut.sum[7:0]
        - TOP.dut.cout
      observed_behavior: 完整结果应为 9'h100，但 {cout,sum} 为 9'h000，最高位缺失使整体数值错误。
      source_correlation: rtl/Adder.sv:24-26 的中间量截断直接解释完整结果少一位的现象。
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
<WAVEFORM-VIEWER> [Open waveform](/surfer/?wave=TOOL_GENERATED_TOKEN_FOR_CARRY)

<a id="waveform-547f03228d4694a0"></a>

### 饱和加法达到上限波形 <WAVEFORM-TC-tests/test_adder.py::test_saturation_limit>

```yaml
waveform_analysis:
  test_case: TC-tests/test_adder.py::test_saturation_limit
  bug_tags:
    - BG-SATURATION-DISABLED-92
  status: confirmed
  receipt_id: fedcba9876543210fedcba9876543210
  result_fingerprint: fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
  executed_test_case: tests/test_adder.py::test_saturation_limit
  waveform_file: unity_test/tests/waveform/test_saturation_limit.fst
  freshness_identity: unity_test/tests/waveform/test_saturation_limit.fst:4352:1787286737000000000
  size_bytes: 4352
  session_started_at: 2026-08-21T14:32:00+08:00
  modified_at: 2026-08-21T14:32:17+08:00
  modified_time_ns: 1787286737000000000
  observed_at: 2026-08-21T14:32:18+08:00
  pattern:
    - signal: TOP.dut.saturate_en
      event: equals
      value: "0x1"
    - signal: TOP.dut.sat_sum[7:0]
      event: equals
      value: "0x0"
  signal_groups:
    clock_mode: combinational
    clocks: []
    inputs:
      - TOP.dut.a[7:0]
      - TOP.dut.b[7:0]
      - TOP.dut.cin
      - TOP.dut.saturate_en
    outputs:
      - TOP.dut.sat_sum[7:0]
    protocol: []
    key_signals:
      - TOP.dut.sum_full[7:0]
      - TOP.dut.saturation_overflow
      - TOP.dut.saturated_sum[7:0]
  analysis_mode: explicit_window
  start_step: 70
  end_step: 74
  context_steps: 1
  max_points: 200
  wave_step: 72
  timeline_truncated: false
  alignment_evidence: 测试在 step 70 驱动 ff、01、0 并使能饱和；step 72 的输入保持稳定，溢出检测仍为 0，sat_sum 已稳定为 00，与该用例的断言采样对应。
  bug_evidence:
    BG-SATURATION-DISABLED-92:
      required_signals:
        - TOP.dut.a[7:0]
        - TOP.dut.b[7:0]
        - TOP.dut.saturate_en
        - TOP.dut.sum_full[7:0]
        - TOP.dut.saturation_overflow
        - TOP.dut.saturated_sum[7:0]
        - TOP.dut.sat_sum[7:0]
      observed_behavior: saturate_en 为 1 且完整和溢出时，saturation_overflow 仍为 0，sat_sum 输出回绕值 00 而不是 ff。
      source_correlation: rtl/Adder.sv:40-43 的常量溢出检测与波形中始终为 0 的 saturation_overflow 一致。
```
<WAVEFORM-VIEWER> [Open waveform](/surfer/?wave=TOOL_GENERATED_TOKEN_FOR_SATURATION)

</WAVEFORM-EVIDENCE>
`````

标准案例体现以下不可变边界：文档中有两个唯一 ROOT 和三个完整 BG；`ROOT-SUM-CARRY-WIDTH`通过两条完整路径关联两个 BG，两个 BG 分别反向引用同一个 ROOT，ROOT 五字段仍只写一次；`ROOT-SATURATION-DETECTOR-CONSTANT`只关联第三个 BG，说明独立根因必须建立独立实体。同一个`TC-tests/test_adder.py::test_cin_carry`可以出现在两个 BG 下，但两个引用都跳到唯一的中央记录；该记录的`bug_tags`和`bug_evidence`同时列出两个 BG，`signal_groups`覆盖两份`required_signals`的并集。另一个 TC 具有第二份独立中央记录，不能把两个 TC 的 YAML 或 viewer 合并。每个 BG 只写三个字段并只引用一个 ROOT；每个 ROOT 至少反向关联一个 BG；源码路径含真实行范围，每个 ROOT 的三个源码因果标签各在自己的 HDL fenced block 中出现一次。

### 5.2 建立骨架并分阶段写入

`record_dynamic_bug.py`是可选脚本，只接收`BG/TC/BD`并创建新 Bug 的第一份 BG/TC、三个字段、根因引用和 ROOT 五字段骨架。脚本从`.ucagent/runtime_config.json`读取实际TC目录和统一`current_test_report`路径；`Check`或`RunTestCases`真实运行Unity测试后发布当前阶段报告，进入新阶段时旧报告失效。脚本只从该报告的`failed_test_case_with_check_point_list`精确解析TC到FG/FC/CK的关系，不读取阶段私有报告；若当前报告不存在，先运行当前阶段真实测试，禁止手工创建、复制或猜测报告。脚本从功能检查文档读取 FG/FC/CK 名称，从测试 docstring 读取 TC 名称，并用`BD`生成初始根因实体；LLM 必须用真实结论替换全部`<BUG-TODO>`，必要时重命名根因标签并同步引用。

#### 5.2.1 多分支层次骨架

FG、FC、CK、BG、TC 都是一对多层次，不是一条固定单链。以下树形说明可省略重复字段以突出层级；实际文档中的每个 BG 必须按Guide_Doc/dut_bug_analysis.md中的第 5.2.2 节展开三个字段和根因引用。

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

禁止把同一 FG/FC/CK/BG 标签复制成多个平行节点。已有父节点时在该节点范围内添加新的子节点；同一 BG 的多个 TC 只增加 TC 与引用，不复制三个 BG 字段。同一 TC 关联多个 BG 时，在每个 BG 下保留同名 TC 与相同中央锚点，但中央波形记录仍只有一份。

#### 5.2.2 单个 BG 的完整字段骨架

以下骨架用于展开上图中的每个新 BG；方括号内容必须替换为实际可见名称。两个 TC 示例刻意放在三个 BG 字段之前，用于强调固定顺序：

```markdown
<DYNAMIC-BUGS>

### [功能组具体名称] <FG-NAME>

#### [功能具体名称] <FC-NAME>

##### [检查点具体名称] <CK-NAME>

<a id="tool-generated-bug-anchor"></a>

###### [缺陷具体描述]（XX%） <BG-NAME-XX>

- [测试 docstring 描述] <TC-test_file.py::test_name>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#tool-generated-anchor)
- [另一个测试 docstring 描述] <TC-test_file.py::test_another_name>
  <WAVEFORM-REF> [WAVEFORM-EVIDENCE](#another-tool-generated-anchor)

###### Bug 概述

<BUG-OVERVIEW>
<BUG-TODO>

###### 现象与严重度

<BUG-SYMPTOMS>
<BUG-TODO>

###### 触发条件与影响

<BUG-TRIGGER>
<BUG-TODO>
<CAUSE-REF-ROOT-NAME> [根因具体描述](#root-cause-name)
</DYNAMIC-BUGS>

## 根因分析

<ROOT-CAUSES>
<a id="root-cause-name"></a>

### [根因具体描述] <ROOT-NAME>

#### 根因分析
<ROOT-CAUSE-ANALYSIS>
<BUG-TODO>

#### 源码证据
<ROOT-SOURCE-EVIDENCE>
<BUG-TODO>

#### 因果链
<ROOT-CAUSAL-CHAIN>
<BUG-TODO>

#### 修复建议
<ROOT-FIX>
<BUG-TODO>

#### 风险与复验
<ROOT-RETEST>
<BUG-TODO>

#### 关联 Bug
<RELATED-BUGS>
- <RELATED-BUG-FG-NAME/FC-NAME/CK-NAME/BG-NAME-XX> [FG-NAME/FC-NAME/CK-NAME/BG-NAME-XX](#tool-generated-bug-anchor)
</ROOT-CAUSES>
```

方括号内的文字是必须替换的可见标题，不是允许保留的模板文本。BG、根因和波形锚点必须按规范生成，双向链接目标必须精确一致。LLM 必须完成 BG 的三个字段和 ROOT 的五个字段，不得修改 Markdown 层级、标题、字段顺序或容器布局。不要为同一 BG 的后续 Fail TC 复制该结构；新增 TC 必须插入第一个 BG 字段之前。调用 `ApplyWaveInfoEvidence`写入中央记录后，必须清除全部 `<BUG-TODO>`。

## 6. 证据保留与重放

签名 receipt、中央 YAML 和 viewer 是持续保留的证据。普通增量 stage 使用`require_current_replay=false`：只验证文档、签名 receipt 与关联，不因后来测试、session 或波形文件变化而要求更新。

只有对应验证项配置`require_current_replay=true`时，才对所有唯一 TC 重放当前波形。重放失败或窗口、候选、信号集合、事件变化时，按返回的 WaveInfo/Apply 调用取得新 receipt 并更新中央记录。

新增一个关联 Bug 属于证据范围扩展：即使普通 stage 不重放，也必须确认当前 receipt 的信号并集足以分析新 Bug；不足时按上一节替换 receipt。

移除或重新分类 Bug 时，同步删除该 BG/TC 引用及中央记录中的`bug_tags`/`bug_evidence`项。如果 TC 的最后一个 Bug 关联被移除，必须删除整份中央`<WAVEFORM-TC-...>`记录，不能留下孤儿波形。

## 7. BG 与 ROOT 字段

每个 BG 只保留三个唯一、有序、非空字段：`###### Bug 概述`/`<BUG-OVERVIEW>`、`###### 现象与严重度`/`<BUG-SYMPTOMS>`、`###### 触发条件与影响`/`<BUG-TRIGGER>`。`<BUG-TRIGGER>`先写真实触发条件和影响范围，最后一个非空块必须是唯一的`<CAUSE-REF-ROOT-XXX>`可点击链接。

标题排版规则：每个 Markdown 标题前后各保留一个空行，标题前置空行没有例外。文件开头的标题、Markdown 示例围栏内的首个标题、BG/ROOT 的 `<a id="..."></a>` 锚点后的目标标题都必须有前置空行。BG/ROOT 字段标题后的 `<BUG-*>`、`<ROOT-*>` 或 `<RELATED-BUGS>` 标记仍必须与字段标题紧邻；不要在字段标题与这些后置机器标记之间插入空行。

每个 ROOT 依次包含`<ROOT-CAUSE-ANALYSIS>`、`<ROOT-SOURCE-EVIDENCE>`、`<ROOT-CAUSAL-CHAIN>`、`<ROOT-FIX>`、`<ROOT-RETEST>`和`<RELATED-BUGS>`。一个 ROOT 关联多个 BG 时，因果链必须解释各 BG 如何从共同首错传播到不同观察点，复验必须覆盖所有关联 CK。`<ROOT-SOURCE-EVIDENCE>`有两种互斥模式：

- 有源码：包含不带`L`的真实`path:起始行-结束行`与完整 HDL fenced 代码；单行也重复行号。在语言原生注释中各放一次`<ROOT-SOURCE-FIRST-ERROR>`、`<ROOT-SOURCE-PROPAGATION>`、`<ROOT-SOURCE-OBSERVABLE>`。
- 无可访问源码：单独写`<ROOT-SOURCE-UNAVAILABLE>`，用规格、接口、日志和波形完成黑盒因果链，不虚构源码位置。

有源码位置必须逐字使用不带`L`的`path:起始行-结束行`。例如`Adder/Adder.v:10-14`有效；单行必须重复行号写成`Adder/Adder.v:10-10`，不能写成`Adder/Adder.v:10`；`Adder/Adder.v:L10-L14`也无效，必须改成`Adder/Adder.v:10-14`。这类纯格式修复不需要重新运行测试、WaveInfo或Bug分类。

无源码分支必须完整写成以下形态，不能只留下标记：

```markdown

#### 源码证据
<ROOT-SOURCE-EVIDENCE>
<ROOT-SOURCE-UNAVAILABLE>
当前工作区未提供可访问的 RTL/HDL。接口规格规定请求在 `valid && ready` 时接受，失败日志和已确认波形共同显示响应有效周期的 `result` 比期望值少 1；因此根因范围限定在接受后到结果输出之间的状态更新或算术路径，不能虚构具体文件与行号。
```

验收单位是完整`FG/FC/CK/BG`路径。同一 CK 分支内，同一个 BG 只出现一次，并保留该路径自己的三个 BG 字段。共享 ROOT 的五个字段不在各 BG 重复；每个 TC 仍只有一份中央波形记录。

有源码时，每个 ROOT 的`<ROOT-SOURCE-EVIDENCE>`必须包含源码代码块。例如：

```systemverilog
// path/to/file.sv:10-12
assign accepted = valid && ready; // <ROOT-SOURCE-FIRST-ERROR> Wrong acceptance condition.
assign state_n = accepted ? NEXT : state; // <ROOT-SOURCE-PROPAGATION> Error enters state.
assign result = state; // <ROOT-SOURCE-OBSERVABLE> Error reaches the checked output.
```

根因实体必须位于唯一`<ROOT-CAUSES>`分区，每个实体使用一个文档级唯一的`<ROOT-XXX>`标签，不能再建立其他自由文本“根因分析汇总”。每个 BG 恰好通过一个`<CAUSE-REF-ROOT-XXX>`引用一个根因；每个根因至少通过一个`<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>`反向关联真实存在的完整 BG 路径，禁止孤立根因；关系标签内嵌目标标记，链接文本、目标和锚点必须完全一致。一个根因可以关联多个 BG，但一个 BG 不得引用多个根因。组合条件形成缺陷时，将该组合作为一个具有独立`<ROOT-XXX>`标签的根因实体。

## 8. 静态 Bug 标签

静态候选只写在`{DUT}_static_bug_analysis.md`，使用`<BG-STATIC-NNN-NAME>`。文件必须依次包含`<STATIC-BUG-SUMMARY>`、`<STATIC-BUG-DETAILS>`和`<STATIC-BUG-PROGRESS>`。每个候选使用不带`L`的`<FILE-path/to/file.v:起始行-结束行>`定位（单行重复行号），并在汇总和详情中保持同一链接：待验证为`<LINK-BUG-[BG-TBD]>`，动态证实后为`<LINK-BUG-[BG-NAME-XX]>`，误报为`<LINK-BUG-[BG-NA]>`。

若没有任何可分析文件，使用`<FG-NULL>/<FC-NULL>/<CK-NULL>/<BG-STATIC-NULL>`；输入文件标签写作`<file>path/to/file.v</file>`。静态候选动态证实后，必须创建独立非静态 BG，并遵循本文的中央波形格式；不能把`BG-STATIC-*`写进动态文档。

## 9. 可选 Skill

Skill 只是辅助，不能成为任务前置条件。`unitytest/dynamic-bug-recording`可创建首个 BG/TC/引用骨架，`unitytest/static-bug-validation`可原子更新静态 LINK。Skill 禁用、未复制或脚本不可用时，使用文本工具按本文标签建立相同结构并继续任务，产物和验收标准完全相同。

## 10. 完成检查

- Check/Complete 失败时，只处理反馈中的第一个阻塞项和明确`next_action`；同一记录的其他字段和其他记录不属于本次动作，不得顺带修改或全局替换。修复后再次检查以取得下一项。若反馈中的`rerun_test`、`rerun_waveinfo`或`apply_evidence`为`false`，禁止对应重跑或Apply；纯格式或语义字段修复不得重建BG/TC或重新分类Bug。
- 根因关系失败时，优先使用反馈中列出的完整可用引用：BG 侧选择一条完整`<CAUSE-REF-ROOT-...>`链接，ROOT 侧选择或添加一条完整`<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>`链接。不得只复制可见标题、只写 Markdown 链接或猜测锚点；候选均不符合语义时，先修正 ROOT 划分，再重新检查。
- `RunTestCases`只运行已有的真实pytest验证用例，不是任意Python或文档维护脚本执行器。禁止创建临时脚本或伪pytest用例来修改、迁移或批量填充本文档。使用文本工具修改文档；相同文本出现多次时，给`ReplaceStringInFile`传只覆盖当前阻塞位置的`line_blocks=[[start, end]]`，每次只填写当前记录、当前字段的真实结论。已声明的Skill脚本只能通过`RunSkillScript`执行。
- 三个容器各出现一次、均正确关闭，并按`DYNAMIC-BUGS -> ROOT-CAUSES -> WAVEFORM-EVIDENCE`排序。
- 文档标题、分区标题、FG/FC/CK/BG/TC 层级、BG 三字段和 ROOT 五字段与Guide_Doc/dut_bug_analysis.md中的第 5.1 节完整标准案例一致。
- 每个中央波形标题逐字复用关联 TC 的可见标题并追加“波形”。
- 每个非零 BG 至少有一个真实 Fail TC、完整三个 BG 字段和唯一 ROOT 引用。
- 每个阶段结束时仍为 Fail 的 DUT 测试都在其报告关联的至少一个 CK 下具有非零 BG/TC 记录；不存在未分类 Fail。该 CK 可以已经被 TC 成功触发并通过覆盖，不要求每个 Fail TC 关联失败 CK。
- 每个阶段结束时仍失败的 CK 都有至少一个由当前报告关联到同一精确 CK 的正确 Fail TC，并在该 CK 下具有非零 BG/TC 记录。
- 每个 BG 的全部 TC/引用连续位于 BG 标题后，三个`<BUG-*>`字段位于最后一个 TC/引用后，字段开始后不再出现 TC。
- 每个 BG/TC 紧随精确`<WAVEFORM-REF>`，链接到该 TC 的稳定锚点。
- 每个关联 TC 在中央分区恰有一份记录，无重复、无孤儿。
- 每个文档 TC 逐字使用当前函数级报告 node ID（只去掉报告附带的源码行范围）。非参数化 receipt 与其精确相等；参数化 receipt 必须是同一完整路径/类/函数的一个精确 FAILED child，中央`executed_test_case`与 receipt 一致。路径前缀不同就是不同身份；相似文件或节点列表只帮助核对拼写，不参与匹配。
- `bug_tags`、BG/TC 引用和`bug_evidence`三者完全一致。
- 所有逐 Bug `required_signals`都在顶层签名信号并集中，viewer显示同一信号集合。
- receipt、fingerprint、窗口、pattern、signal_groups、viewer与真实工具结果一致。
- 共享与逐 Bug 语义结论均已完成，无`<BUG-TODO>`。
- 任何非零 BG 或 ROOT 残留`<BUG-TODO>`都不能完成阶段。
- 普通 stage 持续保留已签名证据；仅严格 current-replay stage 要求全面重放和必要更新。
