# DUT 缺陷分析文档

## 概述

当测试执行过程中发现某些检查点（Check Point）未能通过时，需要在 `{DUT}_bug_analysis.md` 文档中进行详细的缺陷分析。本文档用于记录和分析测试用例失败的检查点，评估缺陷的严重程度，并提供根因分析。

## 文档结构

缺陷分析文档包含以下部分：
1. **Bug概述** - 按 <FG-*>, <FC-*>, <CK-*>, <BG-*> 的层级结构标记并列出所有Bug描述，在bug描述下用 <TC-*> 列出所有由该bug导致的Fail测试用例
2. **Bug分析** - 基于源代码，对bug根本原因进行深入分析和归类

**注意：**
- 所有Bug都需要有至少一个Fail的测试用例与其对应
- 没检测通过的检查点必须继续补充真实激励和严格断言来判定原因，不能在已实现测试中添加`assert False`伪造Bug复现；如果没有真实Fail用例，就不能把它确认为动态Bug
- <FG-*> 等标签结构为树状结构，同一个父节点下的子节点不能出现同名
- 在 <BG-*-xx> 中给bug命名时，应当取简洁、有意义、可读性强、容易理解的名字
- 在 <TC-*>标签中，测试用例如果是基于Class的，也需要带上类名，例如： <TC-test_example.py::TestMyClassName::test_function_name>
- 在 <TC-*> 标签中标记的测试用例必须为 Fail，但 Fail 只是 DUT Bug 的必要条件，不是充分证据；还必须确认测试和验证基础设施正确、与失败 CK 一致、基于源码定位根因，并由真实 `WaveInfo` 动态确认

## 动态 Bug 的波形确认

`{OUT}/{DUT}_bug_analysis.md` 是动态确认文档。写入其中的每个置信度非 0 Bug 都必须已经由 Fail 测试动态复现，并真实调用 `WaveInfo` 提取事件证据，最终记录为 `status: confirmed`。`WaveInfo` 找不到或无法解析波形时，其返回只用于诊断和修复波形生成流程，`status: unavailable` 不能作为已确认 Bug 的最终证据，也不能让阶段完成。波形证据用于确认失败发生时 DUT 的真实输入、握手、状态和输出，但不能替代正确的失败断言和基于源代码的根因分析。

测试阶段的完成条件不是“所有真实 DUT 测试都必须 Pass”，而是：所有非 DUT-Bug 用例必须 Pass；所有剩余 Fail 必须恰好是正确测试稳定复现的 DUT 设计 Bug，并且已完成非零置信度动态 Bug 记录、CK 关联、源码根因分析和真实 `WaveInfo` confirmed 证据。Mock、fixture、参考模型以及只验证测试框架/API 调用链自身且不以 DUT 功能输出为判定对象的测试属于验证基础设施，必须全部 Pass，不能作为 DUT Bug 记录；使用正确预期检查真实 DUT 输出的 API 功能测试仍适用 DUT-Bug Fail 规则。

每个已实现测试的 Fail 必须先排除测试代码、断言、预期值、检测点、fixture/API、参考模型、复位/时序和环境问题。属于这些问题时必须修复后重跑到 Pass；禁止以“测试 Bug”、`assert False` 或 `<BG-*-0>` 占位保留 Fail。确认属于 DUT 设计 Bug 后，必须保留正确、严格的预期和断言，让 DUT 的错误行为自然触发 Fail；不得修改预期或弱化断言来误报 Pass。

这里对 `assert False` 的限制只适用于已经进入执行和 Bug 分析的真实测试。`create_test_case_templates` 阶段的所有未实现空模板必须保留 `assert False, "Not implemented"`，以防模板意外 Pass；模板进入实现阶段后必须删除该占位并替换为真实测试逻辑。模板阶段的这种 Fail 只表示尚未实现，不是 DUT Bug，也不写入动态 Bug 文档。

- 如果当前用例有有效波形，Bug 记录必须包含 `WaveInfo` 证据。
- 如果没有波形或波形暂时无法解析，必须按 `WaveInfo` 的详细诊断检查测试名称、最新 session、`SetWaveform`、`dut.Finish()`、空文件或损坏文件，修复后重跑失败用例并重新调用工具；在获得 confirmed 证据前不能完成阶段。
- 仅由静态分析发现且尚未动态复现的潜在 Bug 只能保留在 `{OUT}/{DUT}_static_bug_analysis.md`。动态复现后，必须在动态文档新建不带 `STATIC` 前缀的 `<BG-NAME-xx>`，并从静态文档用 `<LINK-BUG-[BG-NAME-xx]>` 关联。
- `{OUT}/{DUT}_bug_analysis.md` 禁止出现任何 `<BG-STATIC-*>` 标签；`<BG-STATIC-*>` 和 `<BG-STATIC-NULL>` 仅属于 `{OUT}/{DUT}_static_bug_analysis.md`。
- `stale_waveform_only`、输出被截断、周期对齐有歧义、没有候选事件，或未确认时钟基准的结果，不能作为最终 Bug 证据。

### 失败日志要求

运行或重跑可能触发 Bug 的用例时，断言消息应打印足够的定位信息，至少包括：

- `cycle` 及 `cycle_basis`：cycle 0 从何时开始、使用哪个时钟边沿、计数在驱动前还是采样后更新、reset 周期是否计入；
- transaction ID 或请求序号；
- 与失败有关的输入、输出 pin；
- `valid/ready` 等握手信号和关键状态；
- expected 和 actual 值，以及 opcode、地址、长度等事务属性。

例如：

```python
assert actual == expected, (
    "cycle=%d cycle_basis=after_reset_rising_edge txn=%d "
    "valid=%d ready=%d op=0x%x a=0x%x b=0x%x "
    "expected=0x%x actual=0x%x overflow=%d"
    % (
        cycle,
        txn_id,
        valid,
        ready,
        op,
        a,
        b,
        expected,
        actual,
        overflow,
    )
)
```

增加日志不能额外调用 `Step()`、改变 callback 顺序、增加 DUT 周期或改变原测试时序。日志只用于提高失败事件与波形事件的可对齐性。

### 波形发现与新鲜度

不知道当前有哪些波形或不确定测试名称时，先调用不带参数的 `WaveInfo()`。它只列出最新 `toffee_tmp_*` session，不混入旧 session，返回 session 开始/修改/观察时间、波形总数、格式和 worker 分布、总大小，以及每个文件的文件名、测试名提示、相对路径、格式、worker、大小、创建时间、修改时间、年龄和 `freshness_identity`。默认每页最多显示 20 个文件，可用 `max_files` 调整页大小，并用返回的 `next_offset` 作为下一次调用的 `file_offset`；`has_more` 表示是否还有下一页，`waveform_files_truncated` 表示当前结果不是完整明细。

```yaml
status: waveform_inventory
inventory_scope: newest_session_only
latest_session: unity_test/tests/data/toffee_tmp_20260815045449_961
session_started_at: '2026-08-15T04:54:49.961+08:00'
observed_at: '2026-08-15T05:02:00.000+08:00'
waveform_file_count: 2
waveform_files_offset: 0
has_more: false
next_offset: null
format_counts:
  fst: 2
waveform_files:
  - file_name: test_div_inf_by_num.fst
    test_case_name_hint: test_div_inf_by_num
    waveform_file: unity_test/tests/data/toffee_tmp_.../master/test_div_inf_by_num.fst
    size_bytes: 1631
    created_at: '2026-08-15T04:54:50.857+08:00'
    creation_time_source: filesystem_birthtime
    modified_at: '2026-08-15T04:54:50.857+08:00'
    freshness_identity: unity_test/tests/data/toffee_tmp_.../master/test_div_inf_by_num.fst:1631:1786740890857000000
receipt_created: false
evidence_usable: false
recommended_call:
  test_case_name: test_div_inf_by_num
  pattern: []
```

无参数 inventory 只用于发现文件，不批量解析所有波形，也不生成 `waveform_analysis_receipt`，因此不能作为 Bug 波形证据。返回 `recommended_call` 后，下一次必须逐字使用其中的非空 `test_case_name` 调用 `WaveInfo`，先获取 wave step 和信号目录，再构建事件 pattern。如果工具调用记录仍显示 `test_case_name` 为空，不得重复调用 inventory；应修正工具参数，使实际调用中出现非空字符串。`recommended_call.pattern: []` 表示先做 metadata 调用，不是最终事件证据。

MCP 参数使用非空哨兵而不是 `null`：不使用测试名、pattern、cycle、clock 或时间窗时，分别传 `test_case_name: ""`、`pattern: []`、`logged_cycle: -1`、`clock_signal: ""`、`start_step: -1`、`end_step: -1`。一旦分析具体波形，`test_case_name` 必须是 inventory 中的真实非空测试名；不要显式传 `null`。工具内部会把 `-1`、空字符串、空 pattern 规范化成 receipt 和返回结果中的 `null`，这是调用后的 canonical 表示，不是下一次 MCP 调用应传的值。例如 `arguments.start_step: null` 表示原调用没有请求显式窗口，而不是请求了 `analysis_window.effective_start_step` 所显示的范围。

`WaveInfo(test_case_name=...)` 会从配置的测试目录下查找最新的 `toffee_tmp_YYYYMMDDHHMMSS_mmm` 会话，只使用该会话中与测试用例精确同名的 `.fst` 或 `.vcd` 文件；优先使用 FST，再选择最高数字后缀和最新修改时间。工具不会用旧会话或其他测试用例的波形代替目标波形。

每次成功发现波形后的返回结果都包含 `waveform_selection` 和 `waveform_info`：

- `session_started_at`：从最新 session 目录名解析出的会话开始时间；
- `modified_at` 和 `modified_time_ns`：波形文件修改时间；
- `observed_at` 和 `age_seconds_at_observation`：本次工具观察时间及波形年龄；
- `waveform_info.first_wave_step`、`last_wave_step`、`wave_step_span` 和 `wave_step_count`：波形覆盖的 wavekit 仿真时间范围；它们不是 DUT 周期数；
- `waveform_selection.size_bytes`、`waveform_file` 和 `freshness_identity`。

单独重跑失败用例后，应再次调用 `WaveInfo`，比较两次返回的 `freshness_identity`。如果路径、大小和 `modified_time_ns` 都没有变化，不能直接假定产生了新波形，应检查测试是否实际运行、`SetWaveform` 是否调用、测试是否在 `dut.Finish()` 前崩溃，以及波形是否完成刷新。

找不到波形时，应按工具返回的诊断处理。常见原因包括测试名称或参数化名称不正确、目标测试没有在最新 session 运行、只有 `.dat` 而没有波形、测试异常退出、`SetWaveform` 未调用、`dut.Finish()` 未执行、文件为空或损坏，以及 `wavekit` 依赖不可用。

### `WaveInfo` pattern 格式

`pattern` 是结构化列表，不允许传入 Python、NumPy 或任意表达式。每项格式如下：

```yaml
- signal: TOP.dut.valid
  event: rising
- signal: TOP.dut.op[2:0]
  event: equals
  value: "0x3"
- signal: TOP.dut.{overflow,underflow}
  event: change
- signal: TOP.dut.**
  event: unknown
```

`signal` 使用 wavekit 查询语法，支持精确路径、`*`、`**`、`/{regex}/` 和花括号候选/范围。事件含义为：

| event | 含义 |
|-------|------|
| `change` | 值发生变化，包括已知值与 X/Z 之间的变化 |
| `rising` | 单比特信号从已知 0 变为已知 1 |
| `falling` | 单比特信号从已知 1 变为已知 0 |
| `equals` | 信号转换进入指定整数、十进制、十六进制、二进制或 Verilog 字面值 |
| `unknown` | 信号出现 X 或 Z，结果保留具体 X/Z 位 |

不传 `pattern` 时，工具只返回波形元数据和信号目录，可先用这种方式确认层级与信号全名。

只传 `test_case_name` 和非空 `pattern`，但既没有 `logged_cycle + clock_signal`，也没有同时提供 `start_step + end_step` 时，工具会搜索完整波形帮助发现事件，但这只是探索调用。即使找到事件，结果也会明确返回：

```yaml
status: evidence_window_required
evidence_usable: false
analysis_window:
  requested_start_step: null
  requested_end_step: null
  effective_start_step: 0
  effective_end_step: 40
recommended_evidence_call:
  test_case_name: test_mux_select
  pattern:
    - signal: TOP.dut.sel
      event: change
      value: ''
  logged_cycle: -1
  clock_signal: ''
  start_step: 0
  end_step: 40
  context_steps: 1
  max_points: 200
```

必须逐字使用 `recommended_evidence_call` 重新调用 `WaveInfo`，并在 Bug 文档中引用新调用产生的 receipt。探索 receipt 不能通过修改 Bug 文档变成最终证据；尤其不能把 `effective_start_step/effective_end_step` 手工复制为顶层 `start_step/end_step`，因为 Checker 校验的是 receipt 中真实的 requested 参数。`start_step` 和 `end_step` 必须同时提供，不能只提供一个；显式窗口与 `logged_cycle` 对齐是两个独立证据模式，不能混在同一次调用中。

### cycle 与 wave step 对齐

测试日志的 `cycle` 不能直接当作 wavekit 的 step。必须区分：

- `logged_cycle`：失败日志打印的周期编号；
- `clock_occurrence_index`：指定时钟有效边沿在完整波形中的全局序号；
- `wave_step`：wavekit 的仿真时间戳；
- `cycle_delta`：候选时钟边沿换算出的周期编号与 `logged_cycle` 的差，单位是时钟边沿，不是时间戳。

一个 DUT 周期可能跨越多个 wave step；日志的 cycle 还可能因为 reset、驱动/采样顺序、callback、流水线或计数起点与波形中的周期相差 0 到数个周期。因此禁止使用 `wave_step - logged_cycle` 计算周期偏移，也不能因为 `cycle_delta` 为 0 就认定对齐成功。

建议使用两次调用完成对齐。

第一次调用在日志周期附近寻找候选时钟边沿：

```python
WaveInfo(
    test_case_name="tests/test_fadd.py::test_fadd_nan",
    logged_cycle=120,
    cycle_tolerance=5,
    clock_signal="TOP.dut.clk",
    clock_edge="rising",
    pattern=[
        {"signal": "TOP.dut.valid", "event": "rising"},
        {"signal": "TOP.dut.op[2:0]", "event": "equals", "value": "0x3"},
        {"signal": "TOP.dut.a[31:0]", "event": "equals", "value": "0xffffffff"},
    ],
)
```

`cycle_tolerance` 的单位是时钟边沿，默认检查 `logged_cycle +/- 5`，最大为 100。必须用日志中的 transaction ID、输入、opcode/地址、握手、状态和关键 pin，从 `candidate_anchors` 中确认唯一候选。`clock_signal` 缺失或匹配多个信号时，先根据工具给出的候选时钟改用精确路径重试。

例如，以下结果表示日志 cycle 120 最可能对应波形中第 121 个有效上升沿，该边沿发生在 wave step 2440，周期编号差为 +1：

```yaml
cycle_alignment:
  status: candidate_selected
  confirmed: false
  logged_cycle: 120
  cycle_delta_unit: clock_edges
  wave_step_unit: wavekit_simulation_timestamp
  candidate_anchors:
  - clock_occurrence_index: 121
    cycle_delta: 1
    wave_step: 2440
    trigger_count: 3
```

`candidate_selected` 仍只是工具按事件匹配选出的候选，`confirmed: false` 提醒分析者必须核对上下文。

第二次调用使用确认后的 wave step 做精确取证：

```python
WaveInfo(
    test_case_name="test_fadd_nan",
    clock_signal="TOP.dut.clk",
    start_step=2420,
    end_step=2500,
    pattern=[
        {"signal": "TOP.dut.clk", "event": "rising"},
        {"signal": "TOP.dut.valid", "event": "change"},
        {"signal": "TOP.dut.ready", "event": "change"},
        {"signal": "TOP.dut.result[31:0]", "event": "change"},
        {"signal": "TOP.dut.overflow", "event": "change"},
    ],
)
```

如果多个候选无法区分，工具返回 `insufficient_anchor`；应增强失败日志后重跑。如果没有事件，工具返回 `no_candidate`；应检查信号名、时钟边沿、cycle 基准和容差，而不是任选一个相邻周期。

### Bug 文档中的波形证据

`{OUT}/{DUT}_bug_analysis.md` 中每个置信度非 0、且由 Fail 用例动态复现的 `<BG-*>/<TC-*>` 组合，都必须在对应 `<TC-*>` 后放置一个 `<WAVEFORM-ANALYSIS>...</WAVEFORM-ANALYSIS>` 标签块。该块必须是这个 `<TC-*>` 之后的第一个非空内容；允许缩进和空白行，但不允许在中间插入说明、根因分析正文、另一个 `<TC-*>`、其他标签或普通文本。每个 `<TC-*>` 都独立拥有自己的波形块，不能把多个用例的波形统一堆在 Bug 条目末尾。动态文档只允许 `<BG-NAME-xx>`，禁止 `<BG-STATIC-*>`。`<BG-STATIC-*>` 只能写在 `{OUT}/{DUT}_static_bug_analysis.md` 中，静态文档本身不添加波形标签；静态发现一旦被测试证实，应新建动态 Bug 标签并通过 `<LINK-BUG-*>` 关联两个文档。

标签内容是 YAML 映射。`receipt_id` 和 `result_fingerprint` 必须来自 LLM 对 `WaveInfo` 的真实调用返回；Checker 会在当前 agent 内存和 workspace 的签名 checkpoint 中查询该收据，并核对调用的测试名、pattern、参数和结果。仅复制或编造波形路径、时间、step、候选值，或者只调用 metadata 而没有完成事件分析，均不能通过 Checker。agent 中断或重启后，如果使用相同 workspace、DUT 和测试目录，签名有效的 receipt 会自动恢复，不需要重新调用 `WaveInfo` 或重写所有波形块；签名无效、收据丢失、作用域改变或重放失败时，才需要重新运行对应测试并更新该用例的收据。不要手工编辑 `.ucagent` 中的 receipt 存储文件。

`Check` 会重新运行测试，因此可能生成比文档记录更新的波形。Checker 不要求旧 `freshness_identity` 等于 Check 新生成文件的身份，而是同时执行两项验证：

1. 标签中的波形身份和结论必须与其 `receipt_id` 对应的真实历史调用完全一致；
2. Checker 使用同一收据中的 pattern 和参数，对本次 Check 生成的最新波形重新分析，确认 Bug 事件仍可复现且候选没有变化。

#### 时钟对齐模式

有日志 cycle 的时序 Bug 使用 `analysis_mode: clock_aligned`。以下块必须紧随对应 `<TC-tests/test_adder.py::test_add_with_cin_overflow_boundary>`（仅可有空白行），不能放在 Bug 条目末尾或另一个测试用例之后：

```markdown
<WAVEFORM-ANALYSIS>
status: confirmed
receipt_id: 真实WaveInfo返回的receipt_id
result_fingerprint: 真实WaveInfo返回的result_fingerprint
waveform_file: unity_test/tests/data/toffee_tmp_.../master/test_add_with_cin_overflow_boundary.fst
freshness_identity: unity_test/tests/data/toffee_tmp_.../master/test_add_with_cin_overflow_boundary.fst:12345:1786702064722832592
size_bytes: 12345
session_started_at: '2026-08-14T15:00:00.123+08:00'
modified_at: '2026-08-14T15:00:02.456+08:00'
modified_time_ns: 1786702064722832592
observed_at: '2026-08-14T15:00:03.000+08:00'
analysis_mode: clock_aligned
pattern:
  - signal: TOP.dut.valid
    event: rising
  - signal: TOP.dut.op[2:0]
    event: equals
    value: "0x3"
  - signal: TOP.dut.result[31:0]
    event: change
logged_cycle: 120
cycle_tolerance: 5
clock_signal: TOP.dut.clk
clock_edge: rising
cycle_origin: 0
context_steps: 1
max_points: 200
clock_occurrence_index: 121
cycle_delta: 1
wave_step: 2440
timeline_truncated: false
alignment_evidence: txn=17、valid/ready、op=3和输入值与失败日志唯一一致，确认日志cycle 120对应边沿121
observed_behavior: wave step 2440后result和overflow与expected不一致，具体值为...
source_correlation: 波形中的错误输出与RTL文件...第...行的位宽截断逻辑一致
</WAVEFORM-ANALYSIS>
```

`clock_occurrence_index`、`cycle_delta` 和 `wave_step` 必须与收据中的 `selected_candidate` 完全一致。收据必须是 `candidate_selected`、`evidence_usable: true` 且时间线未截断；`insufficient_anchor`、`no_candidate` 或 metadata-only 调用不能填写为 confirmed。

#### 显式时间窗模式

没有测试 cycle、组合逻辑或已由事件确定仿真时间窗时，使用 `analysis_mode: explicit_window`。最终取证调用必须在调用 `WaveInfo` 时真实传入完整窗口，例如：

```python
WaveInfo(
    test_case_name="test_mux_select",
    pattern=[
        {"signal": "TOP.dut.sel[1:0]", "event": "equals", "value": "0x3"},
        {"signal": "TOP.dut.out[31:0]", "event": "change", "value": ""},
    ],
    logged_cycle=-1,
    clock_signal="",
    start_step=20,
    end_step=80,
    context_steps=1,
    max_points=200,
)
```

成功的最终取证返回会包含 `bug_document_fields`，其中的 receipt、波形身份、pattern、调用窗口和 `wave_step` 已与真实调用绑定，应优先复制该映射，而不是根据 `analysis_window` 手工重建。然后必须查看 `timeline` 和 RTL，真实补写返回中列出的 `bug_document_completion_required`：`alignment_evidence`、`observed_behavior` 和 `source_correlation`。工具不会替 LLM 编造这三个分析结论。

`wave_step` 必须是收据和当前波形时间线中真正带有 trigger 的事件点：

```markdown
<WAVEFORM-ANALYSIS>
status: confirmed
receipt_id: 真实WaveInfo返回的receipt_id
result_fingerprint: 真实WaveInfo返回的result_fingerprint
waveform_file: unity_test/tests/data/toffee_tmp_.../master/test_mux_select.fst
freshness_identity: unity_test/tests/data/toffee_tmp_.../master/test_mux_select.fst:4567:1786702064722832592
size_bytes: 4567
session_started_at: '2026-08-14T15:00:00.123+08:00'
modified_at: '2026-08-14T15:00:02.456+08:00'
modified_time_ns: 1786702064722832592
observed_at: '2026-08-14T15:00:03.000+08:00'
analysis_mode: explicit_window
pattern:
  - signal: TOP.dut.sel[1:0]
    event: equals
    value: "0x3"
  - signal: TOP.dut.out[31:0]
    event: change
start_step: 20
end_step: 80
context_steps: 1
max_points: 200
wave_step: 40
timeline_truncated: false
alignment_evidence: sel进入3时的输入和测试失败日志一致，wave step 40是唯一对应事务
observed_behavior: sel=3后out仍保持旧输入值，actual为...，expected为...
source_correlation: 波形行为与RTL文件...第...行缺失的sel=3分支一致
</WAVEFORM-ANALYSIS>
```

#### 波形暂不可用时的处理

找不到或无法解析波形时，应先用 `WaveInfo(test_case_name=...)` 做一次不带 pattern 的真实调用，利用返回的状态、候选测试名称、最新 session 路径、`.dat`/`.fst` 情况和修复建议定位原因。该调用是诊断步骤，不是最终 Bug 证据，不得在动态 Bug 文档中用 `status: unavailable` 冒充确认结果。

处理顺序必须是：核对完整 pytest node ID和参数化名称；确认失败用例确实在最新 session 运行；检查 `SetWaveform` 和 `dut.Finish()`；修复波形生成、flush、依赖或文件损坏问题；单独重跑失败用例；再次调用 `WaveInfo`，用有效 pattern 获得 `evidence_usable: true` 的事件证据；最后写入 `status: confirmed` 块。完成前 checker 会持续失败。

每个 confirmed 记录都必须说明候选为何唯一、是否发生截断、观测到的行为如何支持源码根因。波形只能证明实际动态行为，最终 Bug 结论仍需要源码位置、根因和可执行的修复建议。


### 在进行缺陷根因分析时，需要结合源代码进行分析（{DUT}的源文件通常为{DUT}.v、{DUT}.sv、或者{DUT}.scala），并在文档中把bug相关的部分列出来，用注释说明bug原因，例如：

**Verilog代码bug示例：**
```verilog
// Adder.v 第8-12行，位宽错误导致溢出处理异常
8:   input [WIDTH-1:0] a,
9:   input [WIDTH-1:0] b, 
10:  output [WIDTH-2:0] sum,    // BUG: 应该是 [WIDTH-1:0]，少了1位导致高位截断
11:  output cout
12: );
13: 
14: assign {cout, sum} = a + b + cin;  // 由于sum位宽不足，高位丢失
```

然后同样以源代码的方式给出修复建议：

**Verilog修复示例：**
```verilog
// 修复后的Adder.v 第8-16行
8:   input [WIDTH-1:0] a,
9:   input [WIDTH-1:0] b, 
10:  output [WIDTH-1:0] sum,    // 修复: 恢复正确的位宽定义
11:  output cout
12: );
13: 
14: wire [WIDTH:0] full_result = a + b + cin;  // 使用完整位宽进行计算
15: assign sum = full_result[WIDTH-1:0];       // 取低位作为结果
16: assign cout = full_result[WIDTH];          // 取最高位作为进位输出
```

**注意**： 在给出代码时，需要在第一行的注释中说明是哪个文件，每一行的开头为行号。

## Bug分析格式

### 基本语法规则

- 使用功能组标签 `<FG-*>` 对失败检查点进行分组
- 使用功能点标签 `<FC-*>` 标识具体功能
- 使用检查点标签 `<CK-*>` 标识失败的具体检查点
- 使用Bug标签 `<BG-*-xx>` 标识动态复现的DUT缺陷名称和置信度（有效动态Bug的xx取值1-100）
- 使用多个测试用例标签 `<TC-*>` 标识测出bug的所有测试用例，这些测试用例必须为Fail（Fail的测试用例意味着bug）
- 每个置信度非0的动态 `<BG-*>/<TC-*>` 组合必须关联一个 `status: confirmed`、经过真实 `WaveInfo` 收据验证的 `<WAVEFORM-ANALYSIS>` 标签；动态文档禁止 `<BG-STATIC-*>`，静态Bug只写入独立的静态分析文档
- `<WAVEFORM-ANALYSIS>` 必须是对应 `<TC-*>` 后的第一个非空行；允许空白行和 Markdown 缩进，不允许插入描述、根因、其他标签或另一个测试标签。每一个 `<TC-*>` 都必须有独立波形块，不能在 Bug 条目末尾汇总

例如：

```
## 未测试通过检测点分析

<FG-ARITHMETIC>

#### 加法功能 <FC-ADD>
- <CK-BOUNDARY> 边界值处理：当操作数为最大值时，结果计算错误，Bug置信度 85% <BG-MAXBOUNDARY-85>
  - 触发bug的测试用例:
    -  <TC-test_example.py::test_case_1> test_example.py::test_case_1 用例说明
    -  <TC-test_example.py::test_case_2> test_example.py::test_case_2 用例说明
    ...
  - Bug根因分析：
  ...
```

### 置信度评估指南

| 置信度范围 | 含义 | 建议处理方式 |
|-----------|------|-------------|
| 90-100% | 确认存在缺陷 | 立即修复 |
| 70-89% | 很可能存在缺陷 | 优先修复 |
| 50-69% | 可能存在缺陷 | 进一步调查 |
| 20-49% | 尚未充分确认，不应作为最终动态Bug | 继续调查；完成阶段前确认并提高置信度，或修复非DUT问题到Pass |
| 1-19% | 很可能是测试或验证基础设施问题 | 不得保留Fail；修复后Pass，不能作为有效动态Bug |
| 0% | 无效/历史占位，不是动态Bug证据 | 不得用于解释Fail，清理占位或修复非DUT问题到Pass |

### Bug条目示例

下列示例演示了一个（虚构的）算术逻辑单元（ALU）在一次回归中发现的缺陷层级。为避免重复展示大段 YAML，下列列表省略了每个 `<TC-*>` 后的波形块；实际 `{OUT}/{DUT}_bug_analysis.md` 不得省略，必须按“Bug 文档中的波形证据”一节，为每个非零置信度动态 `<BG-*>/<TC-*>` 组合写入完整且带真实收据的 `status: confirmed` `<WAVEFORM-ANALYSIS>`。纯静态Bug条目不得出现在该动态文档中；零置信度标签不能解释或保留任何Fail。

## 未测试通过检测点分析

<FG-ARITHMETIC>

#### 加法功能 <FC-ADD>
- <CK-CIN-OVERFLOW> 带进位溢出处理异常：在最大无符号数 + 1 + cin=1 时未正确拉高溢出标志；Bug 置信度 98% <BG-CIN_OVERFLOW-98>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_adder.py::test_add_with_cin_overflow_boundary> 边界 + 进位溢出
    - <TC-tests/test_adder.py::test_add_with_cin_random> 随机激励下复现（多次）
  - 备注：两条测试均稳定 Fail，波形比对一致，已锁定 RTL 逻辑问题

- <CK-BOUNDARY> 最大值 + 1 结果截断：期望得到进位或正确饱和，但结果被截断；Bug 置信度 85% <BG-ADD_BOUNDARY-85>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_adder.py::test_add_unsigned_max_plus_one>
  - 备注：与 <CK-CIN-OVERFLOW> 共享部分根因（位宽+溢出逻辑）

#### 减法功能 <FC-SUB>
- <CK-BORROW> 借位信号错误：当被减数 < 减数时 borrow 未置位；Bug 置信度 92% <BG-SUB_BORROW-92>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_sub.py::test_sub_basic_borrow>
    - <TC-tests/test_sub.py::test_sub_chain_with_borrow>

- <CK-UNDERFLOW> 下溢标志不稳定：同一输入在不同仿真次序下标志位不一致；Bug 置信度 72% <BG-SUB_UNDERFLOW-72>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_sub.py::test_sub_underflow_flag>
  - 备注：疑似组合逻辑竞争 / 采样时序问题

<FG-LOGIC>

#### 位操作功能 <FC-BITOP>
- <CK-SHL> 左移超范围行为未定义：移位数 >= 宽度时出现 X 或旧值残留；Bug 置信度 88% <BG-SHL_RANGE-88>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_shift.py::test_shl_over_width>
    - <TC-tests/test_shift.py::test_shl_boundary>

- <CK-SHR> 算术右移符号扩展错误：负数高位填充值不正确；Bug 置信度 95% <BG-SHR_SIGNEXT-95>
  - 触发 Bug 的测试用例：
    - <TC-tests/test_shift.py::test_shr_sign_extend>

#### 比较功能 <FC-COMPARE>
- <CK-EQUAL> 罕见输入组合下偶发失配：无法稳定复现，疑似测试激励或未初始化寄存器影响；Bug 置信度 18% <BG-CMP_EQUAL-18>
  - 触发（疑似）测试用例：
    - <TC-tests/test_compare.py::test_equal_random_sweep>
  - 后续计划：添加更高可控度的定向激励并捕获波形

<FG-CONTROL>

#### 分支预测 <FC-BRANCH>
- 确认属于设计规范允许的策略差异时，不记录动态Bug，也不使用人工失败占位；测试应按正确规范断言并Pass。若需要保留说明，写在规格或验证计划中，而不是用 `<BG-*-0>/<TC-*>` 保留Fail


### 标签与字段书写要点（示例总结）

| 层级 | 示例 | 说明 |
|------|------|------|
| 功能组 FG | <FG-ARITHMETIC> | 顶层功能域，全部大写 |
| 功能点 FC | <FC-ADD> | 具体子功能 |
| 检查点 CK | <CK-CIN-OVERFLOW> | 单一可验证点，短横线分隔 |
| 缺陷 BUG | <BG-CIN_OVERFLOW-98> | 后缀数字=置信度（0-100） |
| 测试用例 TC | <TC-tests/test_adder.py::test_add_with_cin_overflow_boundary> | 路径+函数全称 |

补充规范：
1. 一个 <CK-*> 允许关联多个 <BG-*>
2. 若一个 Bug 影响多个检查点，需在`根因分析`部分统一列出受影响集合
3. 禁止临时失败占位；未确认问题不得用 `assert False` 或 `<BG-*-0>` 留在 Fail 集合中

## 缺陷根因分析

根因分析部分不使用标签，直接使用路径格式（如 `FG-ARITHMETIC/FC-ADD/CK-CIN-OVERFLOW`）来引用失败的检查点和BUG，不能有`<`或者`>`出现。

### 分析框架

每个缺陷分析应包含：
1. **缺陷描述** - 简明扼要描述问题现象
2. **影响范围** - 列出受影响的检查点 / 关联 Bug 标签
3. **根本原因** - 分析问题的根本原因（需要基于源代码）
4. **修复建议** - 提供具体的修复方案（可附代码差异、伪代码）
5. **验证方法** - 说明如何验证修复效果（新增/复用哪些测试、波形关键观察点）

### 根因分析示例

#### 1. 进位处理缺陷

**缺陷描述：** 加法器在处理带进位输入的溢出场景时，未能正确设置溢出标志位。

**影响范围：**
- FG-ARITHMETIC/FC-ADD/CK-CIN-OVERFLOW （BG-CIN_OVERFLOW-98）
- FG-ARITHMETIC/FC-ADD/CK-BOUNDARY （BG-ADD_BOUNDARY-85）

**根本原因：** 
在RTL设计中，溢出检测逻辑只考虑了两个操作数的加法结果，忽略了进位输入对溢出判断的影响。具体来说，当 `(a + b + cin) > MAX_VALUE` 时，应该设置溢出标志，但当前实现只检查了 `(a + b) > MAX_VALUE`。

**具体代码缺陷：**
```verilog
// Adder.v 第25-30行，溢出检测逻辑错误
25: wire [WIDTH-1:0] sum_temp;
26: wire carry_temp;
27: 
28: assign {carry_temp, sum_temp} = a + b;          // BUG: 未考虑cin
29: assign {cout, sum} = {carry_temp, sum_temp} + cin;
30: assign overflow = carry_temp;                   // BUG: 溢出判断错误
```

**修复建议：**
```verilog
// 正确的实现
wire [WIDTH:0] full_sum = a + b + cin;
assign {cout, sum} = full_sum[WIDTH:0];
assign overflow = full_sum[WIDTH];                  // 正确的溢出检测
```

**验证方法：** 重新执行涉及 CK-CIN-OVERFLOW 的两个测试用例，并添加定向向量：`a = MAX`, `b = 1`, `cin = 1`；波形中重点确认：进位链、sum 高位、overflow 标志；修复后应全部 Pass。

#### 2. 移位操作缺陷

**缺陷描述：** 左移和右移操作在移位位数等于或超过数据位宽时行为不符合预期。

**影响范围：**
- FG-LOGIC/FC-BITOP/CK-SHL （BG-SHL_RANGE-88）
- FG-LOGIC/FC-BITOP/CK-SHR （BG-SHR_SIGNEXT-95）

**根本原因：**
设计中未对移位位数进行有效性检查，当移位位数 >= 数据位宽时，应该有明确的行为定义（如清零或保持原值），但当前实现产生了不确定的结果。

**具体代码缺陷：**
```systemverilog
// Shifter.sv 第67-75行，移位范围检查缺失
67: always_comb begin
68:   case (operation)
69:     SHL: result = data << shift_amount;         // BUG: 未检查shift_amount范围
70:     SHR: result = data >> shift_amount;         // BUG: 可能产生不确定结果
71:     ASR: result = $signed(data) >>> shift_amount; // BUG: 同样的问题
72:   endcase
73: end
```

**修复建议：**
```systemverilog
// 添加移位位数检查
localparam int MAX_SHIFT = $clog2(WIDTH);
wire shift_valid = shift_amount < MAX_SHIFT;

always_comb begin
  case (operation)
    SHL: result = shift_valid ? (data << shift_amount) : '0;
    SHR: result = shift_valid ? (data >> shift_amount) : '0;
    ASR: result = shift_valid ? ($signed(data) >>> shift_amount) : {WIDTH{data[WIDTH-1]}};
  endcase
end
```

**验证方法：** 使用边界移位位数（31, 32, 33 对于32位数据）进行测试，确认结果的一致性。

#### 3. 状态机转换错误

**缺陷描述：** 缓存控制器在同时收到读写请求时进入了错误状态，导致后续操作异常。

**影响范围：**
- FG-CONTROL/FC-CACHE/CK-CONFLICT
- FG-CONTROL/FC-CACHE/CK-STATE-TRANS

**根本原因：**
状态机设计时未考虑读写冲突的异常情况处理，当同时收到读写请求时，应该拒绝操作并返回错误状态，但当前实现选择了其中一个操作继续执行。

**具体代码缺陷：**
```systemverilog
// CacheController.sv 第112-125行，状态转换逻辑错误
112: IDLE: begin
113:   if (read_req && !write_req) begin
114:     current_state <= READ_STATE;
115:   end else if (!read_req && write_req) begin
116:     current_state <= WRITE_STATE;
117:   end else if (read_req && write_req) begin    // BUG: 冲突处理错误
118:     current_state <= READ_STATE;              // 应该进入ERROR_STATE
119:     read_ack <= 1'b1;                         // BUG: 错误地确认读操作
120:   end
121: end
```

**修复建议：**
```systemverilog
// 正确的冲突处理
IDLE: begin
  if (read_req && write_req) begin
    current_state <= ERROR_STATE;
    error_code <= ERR_CONFLICT;
  end else if (read_req) begin
    current_state <= READ_STATE;
  end else if (write_req) begin
    current_state <= WRITE_STATE;
  end
end
```

**验证方法：** 构造同时发起读写请求的测试场景，验证错误状态和错误码的正确设置。

#### 4. Chisel 流水线缺陷

**缺陷描述：** ALU流水线在处理数据冒险时出现计算错误，特别是连续相关操作时。

**影响范围：**
- FG-PIPELINE/FC-HAZARD/CK-DATA-HAZARD
- FG-PIPELINE/FC-FORWARD/CK-BYPASS

**根本原因：**
流水线前递逻辑实现不完整，未正确处理写后读（RAW）数据冒险，导致使用了过期的寄存器值。

**具体代码缺陷：**
```scala
// Pipeline.scala 第156-168行，前递逻辑不完整
156: // EX阶段
157: val ex_result = Wire(UInt(32.W))
158: val ex_alu_op = Wire(UInt(4.W))
159: 
160: when(id_ex_reg.valid) {
161:   val operand_a = Mux(forward_a === 0.U, 
162:                       rf.read_data1,           // BUG: 可能是过期数据
163:                       ex_wb_result)            // 只考虑了EX->EX前递
164:   val operand_b = Mux(forward_b === 0.U,
165:                       rf.read_data2,           // BUG: 同样的问题
166:                       ex_wb_result)            // 缺少MEM->EX前递
167:   ex_result := alu.compute(operand_a, operand_b, ex_alu_op)
168: }
```

**修复建议：**
```scala
// 完整的前递逻辑
val operand_a = MuxCase(rf.read_data1, Seq(
  (forward_a === 1.U) -> mem_wb_result,    // MEM->EX前递
  (forward_a === 2.U) -> ex_wb_result      // EX->EX前递
))
val operand_b = MuxCase(rf.read_data2, Seq(
  (forward_b === 1.U) -> mem_wb_result,    // MEM->EX前递  
  (forward_b === 2.U) -> ex_wb_result      // EX->EX前递
))
```

**验证方法：** 编写连续相关指令的测试序列，验证数据前递的正确性和计算结果的准确性。

#### 5. 未知缺陷待调查

**缺陷描述：** 某些检查点失败但暂时无法确定根本原因。

**影响范围：**
- FG-LOGIC/FC-COMPARE/CK-EQUAL （BG-CMP_EQUAL-18）

**当前状态：** 正在调查中，需要更详细的仿真分析和波形查看。

**下一步行动：**
1. 收集更多失败案例的输入数据
2. 进行详细的时序仿真分析
3. 检查相关的组合逻辑实现
4. 与设计团队进行技术讨论

## 质量保证要求

### 强制要求

1. **完整性检查**：每个Bug都必须有对应的标签 `BG-*-xx` 标签
2. **置信度评估**：置信度必须基于客观分析，不能随意设定
3. **根因分析**：高置信度（>70%）的缺陷必须提供详细的根因分析
4. **修复跟踪**：每个缺陷都应有对应的修复计划和验证方法

### 文档维护

- 缺陷修复后及时更新文档状态
- 保留历史记录以供后续分析参考
- 定期回顾分析质量，持续改进分析方法

-----

**重要提示：** 
- 在文本中引用标签时，为防止被解析导致错误，需要去掉尖括号，例如`FG-CONTROL`、`CK-MISPREDICT`、`BG-*-xx`等
- Bug 对应的测试用例应该 Fail，功能正常的检查点对应的测试用例应该 Pass；若出现`全部测试用例 Fail`，应优先排查：测试基线 / 复位时序 / 公共依赖环境。
- 当一个测试用例覆盖多个测试点时，如可行，应拆分为多个细粒度用例，使定位和覆盖统计更清晰。
- 标签`BG-*-xx`中xx为0时不构成有效动态Bug，也不能解释任何Fail。对应测试若不是DUT Bug必须修复到Pass；若确认是DUT Bug，则改为非零置信度并补齐真实动态证据。
- Check Point或测试Fail但尚未确认DUT Bug时，阶段仍未完成；继续诊断并得到“修复非DUT问题后Pass”或“确认DUT Bug并完整取证后保留Fail”的结论，不能用`BG-*-0`绕过。

---

## 静态分析Bug文档规范（`{DUT}_static_bug_analysis.md`）

静态分析阶段通过源码审查（不运行仿真）发现潜在设计缺陷，其结果记录在独立文件 `{OUT}/{DUT}_static_bug_analysis.md` 中，与动态测试结果文件 `{DUT}_bug_analysis.md` 相互补充，共同构成完整的Bug记录体系。

### 标签层级结构

静态分析文档与动态测试文档使用**完全相同的** `FG → FC → CK` 层级组织结构。`<BG-STATIC-*>` 挂靠在 `<CK-*>` 之下，其下一级是**动态Bug关联标签 `<LINK-BUG-*>`**，用于在 `static_bug_validation` 阶段建立静态Bug与动态Bug之间的可追踪链接。每个 `<LINK-BUG-*>` 下还必须包含**源文件位置标签 `<FILE-*>`**，标记该Bug在源代码中的具体位置。

**重要**：一个 `<CK-*>` 检测点下可以挂靠多个 `<BG-STATIC-*>` 标签，每个标签代表在该检测点发现的一个独立Bug。

```
<FG-功能组>                                 ← 与 _functions_and_checks.md 共用或新增 <FG-STATIC>
  <FC-功能点>                               ← 与 _functions_and_checks.md 共用或新增 <FC-STATIC-*>
    <CK-检测点>                             ← 一个CK检测点（可挂靠多个BG-STATIC）
      <BG-STATIC-序号-名称1>                ← 第一个静态Bug
        <LINK-BUG-[BG-TBD]>                 ← 静态分析时默认填写，validation阶段必须替换
          <FILE-filepath:line1-line2>       ← 源文件位置（必填），紧排在 LINK-BUG 行下
      <BG-STATIC-序号-名称2>                ← 第二个静态Bug（同一CK下）
        <LINK-BUG-[BG-TBD]>
          <FILE-filepath:line1-line2>
```

`<BG-STATIC-*>` 下的 `<LINK-BUG-*>` 子标签状态转换：

| 子标签 | 状态 | 含义 |
|--------|------|------|
| `<LINK-BUG-[BG-TBD]>` | 待验证 | 静态分析阶段默认填写，表示尚未有对应动态测试结果 |
| `<LINK-BUG-[BG-NAME-xx]>` | 已证实（单个） | 替换 `<LINK-BUG-[BG-TBD]>`，填写 `_bug_analysis.md` 中对应动态Bug的实际标签名 |
| `<LINK-BUG-[BG-NAME1-xx][BG-NAME2-xx]>` | 已证实（多个） | 一个静态Bug对应多个动态Bug时，用多个 `[BG-*]` 方括号组依次拼写；每个标签均须在 `_bug_analysis.md` 中存在 |
| `<LINK-BUG-[BG-NA]>` | 误报 | 替换 `<LINK-BUG-[BG-TBD]>`，表示经动态测试验证该潜在Bug不存在 |

**`static_bug_validation` 阶段的核心任务就是消除所有 `<LINK-BUG-[BG-TBD]>`：**
- 扫描 `_static_bug_analysis.md` 中所有 `<LINK-BUG-[BG-TBD]>` 标签
- 对每一个编写动态测试用例，根据测试结果将 `<LINK-BUG-[BG-TBD]>` 替换为 `<LINK-BUG-[BG-NAME-xx]>`（或多标签形式）或 `<LINK-BUG-[BG-NA]>`
- 阶段完成时 `_static_bug_analysis.md` 中**不允许有任何 `<LINK-BUG-[BG-TBD]>` 残留**

`<LINK-BUG-*>` 标签是标准的层级标签，可由 `parse_nested_keys` 统一解析（层级：`FG → FC → CK → BG-STATIC → LINK-BUG`）。

与动态格式的对比：

| 层级 | 动态测试文档（`_bug_analysis.md`） | 静态分析文档（`_static_bug_analysis.md`） |
|------|----------------------------------|------------------------------------------|
| 功能组 | `<FG-*>` | `<FG-*>`（同，可引用已有或新增 `<FG-STATIC>`） |
| 功能点 | `<FC-*>` | `<FC-*>`（同，可引用已有或新增 `<FC-STATIC-*>`） |
| 检测点 | `<CK-*>` | `<CK-*>`（同，可引用已有或在 `_functions_and_checks.md` 中新增） |
| 静态Bug标签 | 无 | `<BG-STATIC-序号[-名称]>`（挂靠在 CK 之下） |
| 动态Bug关联 | `<BG-功能名-置信度数字>`（直接在 CK 下） | `<LINK-BUG-[BG-TBD]>` / `<LINK-BUG-[BG-NAME-xx]>` / `<LINK-BUG-[BG-NA]>`（挂靠在 BG-STATIC 之下） |
| 源文件位置 | 无 | `<FILE-filepath:line1-line2>`（挂靠在 LINK-BUG 之下，**必填**） |
| 测试用例 | `<TC-*>`（必须 Fail） | **不出现**（写入 `_bug_analysis.md`） |

### 源文件位置标签 `<FILE-filepath:linerange>`

每个 `<LINK-BUG-*>` 标签下必须紧跟至少一个 `<FILE-*>` 子标签，标明该静态Bug在源代码中的具体位置，格式为：

```
  - <FILE-filepath:line1-line2[,line3-line4,...]>
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `filepath` | 源文件**相对于工作区根目录**的相对路径，不含空格 | `UartTx.v`，`src/rtl/fsm.v` |
| `:` | 路径与行号分隔符（固定为英文冒号） | `:` |
| `line1-line2` | 连续行范围，start ≤ end | `50-56`，`100-120` |
| `,line3-line4` | 多个不连续行范围，逗号分隔 | `50-56,100-120` |

**一个 `<LINK-BUG-*>` 可以携带多个 `<FILE-*>` 标签**，对应同一静态Bug涉及多个文件或多处代码段的情形：

```
  - <LINK-BUG-[BG-TBD]>
    - <FILE-UartTx.v:50-56>
    - <FILE-UartTx.v:100-105>
    - <FILE-pkg/uart_pkg.sv:22-24>
```

#### 未发现Bug（在所有文件中都未发现任何bug）

在所有文件中都未发现潜在Bug时，用标签`<FG-NULL><FC-NULL><CK-NULL><BG-STATIC-NULL>` 表示。该标签无需 `<LINK-BUG-*>` 子标签，因此也无需 `<LINK-BUG-*>`和`<FILE-*>` 子标签。

`<BG-STATIC-NULL>`仅在所有文件中都未发现任何Bug时使用，不能和`<BG-STATIC-*>`同时使用。


**Checker 强制验证**：每个非 NULL 的 `<BG-STATIC-*>` 下的 `<LINK-BUG-*>` 子标签必须至少包含一个格式合法的 `<FILE-*>` 子标签，否则报错。同时 Checker 会通过 `self.get_path(filepath)` 验证 `filepath` 指向的源文件在工作区中实际存在；若文件不存在则报错，提示将路径更正为相对于工作区根目录的正确相对路径（例如 `rtl/dut.v:50-56`，而非绝对路径）。

**源代码引用要求**：在 `<FILE-*>` 标签行下方（作为自由文本子内容），必须贴出对应的 RTL 源代码片段（fenced code block），以便审阅者无需打开原始文件即可理解Bug上下文：

```markdown
  - <FILE-UartTx.v:50-56>
    ```verilog
    50: always @(posedge clk) begin
    51:   case (state)
    52:     IDLE: if (start) state <= SEND;   // BUG: 未检查 tx_busy
    53:     SEND: if (bit_cnt == 8) state <= IDLE;
    54:     // default 分支缺失
    55:   endcase
    56: end
    ```
```

### 批次分析进度标记 `<file>`

`static_bug_analysis` 阶段采用**批次推进**方式：`UnityChipBatchCheckerStaticBug` Checker 每次从待分析文件列表中取出若干个文件（由 `batch_size` 控制，默认为 1），由 LLM 对其进行静态审查并将结果写入 `{DUT}_static_bug_analysis.md`。

每完成一批次的分析后，LLM 需要在 `{DUT}_static_bug_analysis.md` **末尾**维护一个 **`## 批次分析进度`** 进度表格，记录每个已分析文件及其发现的疑似Bug数量。

#### 进度表格格式

````markdown
## 批次分析进度

| 源文件 | 发现疑似Bug数 | 状态 |
|--------|-------------|------|
| <file>UartTx/UartTx.v</file> | 1 | ✅ 完成 |
| <file>UartTx/uart_pkg.sv</file> | 0 | ✅ 完成 |
````

**操作规则：**

1. **首次追加**：若文档末尾尚无 `## 批次分析进度` 章节，先创建该章节和表格标题行，再添加文件行；
2. **后续批次**：直接在已有表格中**追加新行**，不重新创建章节；
3. 每个已分析文件**一行**，格式固定为 `| <file>文件路径</file> | N | ✅ 完成 |`。

**列说明：**

| 列 | 要求 | 示例 |
|----|------|------|
| 源文件 | `<file>` 标签包裹路径，与工作区根目录的相对路径**完全一致**（大小写敏感） | `<file>UartTx/UartTx.v</file>` |
| 发现疑似Bug数 | 本批次分析该文件发现的疑似 Bug 数量（整数，可为 0） | `1`、`0` |
| 状态 | 固定写 `✅ 完成` | — |

**Checker 的状态推导机制（无状态）：**

`UnityChipBatchCheckerStaticBug` 是**无状态**的，每次检查时通过正则解析文档中所有 `<file>…</file>` 标记来确定已完成的文件列表：

- 若某文件的路径出现在任意 `<file>` 标记中（无论其位于纯文本还是表格行内），则认为该文件已完成分析；
- 否则该文件将被纳入下一批次；
- 当所有文件均有对应标记后，Checker 自动调用 `UnityChipCheckerStaticBugFormat` 执行完整格式校验；
- `<file>` 标记（进度追踪）与 `<FILE-*>` 源文件位置标签（Bug 层级中的结构化标签）**功能不同，勿混淆**。

> **注意**：`## 批次分析进度` 章节是追加在文档正文之后的**进度元数据**，不属于标签层级结构，`parse_nested_keys` 不会解析它；`<file>` 标签内容中的斜杠、冒号等字符不影响主体文档的标签解析。

### 静态Bug标签 `<BG-STATIC-*>`

静态Bug标签格式为 `<BG-STATIC-序号>` 或 `<BG-STATIC-序号-名称>`，序号从 `001` 开始递增：

- `<BG-STATIC-001>` — 纯序号形式
- `<BG-STATIC-001-FSM-DEAD>` — 推荐格式，附加简洁名称提高可读性
- `<BG-STATIC-NULL>` — **无Bug声明**：静态审查完成后**所有文件都未发现任何潜在缺陷**时使用；**不需要** `<LINK-BUG-*>` 子标签；**不允许**与其他 `<BG-STATIC-*>` 标签共存。Checker 强制验证：若文档中既无任何 `<BG-STATIC-*>` 标签、又无 `<BG-STATIC-NULL>`，则报错。

**`<FG-*>`/`<FC-*>`/`<CK-*>` 的来源规则：**

| 情形 | 做法 |
|------|------|
| 静态bug对应已有功能点 | 直接使用 `_functions_and_checks.md` 中已有的 `<FG-*>`、`<FC-*>`、`<CK-*>` 标签 |
| 静态bug对应已有功能点但缺少检测点 | 在 `_functions_and_checks.md` 中补充新 `<CK-*>` 检测点，再在静态文档中引用 |
| 静态bug对应全新功能域（源码中发现但原规格未覆盖） | 在 `_functions_and_checks.md` 中新增 `<FG-STATIC>`、`<FC-STATIC-*>`、`<CK-STATIC-*>`，再引用 |

高/中置信度潜在Bug新增的 `<CK-*>` 检测点，必须可通过 DUT 输入输出端口观测（不依赖内部信号状态），以确保后续动态测试可验证。

### 静态分析置信度

| 置信度 | 含义 | 后续处理 |
|--------|------|---------|
| 高 | RTL 逻辑明确有误，无需仿真即可判断是Bug | 必须补充 `<CK-*>` 检测点；动态测试阶段优先复现 |
| 中 | 代码逻辑可疑，行为不确定，需测试验证 | 应补充 `<CK-*>` 检测点；动态测试阶段进行验证 |
| 低 | 边界条件存疑或风格问题，可能不影响功能 | 可在资源充裕时进行验证，检测点可选 |

### `{DUT}_static_bug_analysis.md` 文档结构

```markdown
# {DUT} RTL 源码静态分析报告

## 一、架构概述

（简要描述模块层次、数据流、关键设计单元）

## 二、审查范围

- 审查文件列表：...
- 对应功能测试点文档：{OUT}/{DUT}_functions_and_checks.md

## 三、潜在Bug汇总

（按置信度从高到低排列；动态Bug关联列初始全部填写 LINK-BUG-[BG-TBD]，validation 后更新）

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|---------|---------|--------|---------|------------|
| 001 | BG-STATIC-001-NAME | FG-XXX/FC-YYY/CK-ZZZ | 描述... | 高 | Foo.v | LINK-BUG-[BG-TBD] |
| 002 | BG-STATIC-002-NAME | FG-XXX/FC-YYY/CK-ZZZ | 描述... | 中 | Foo.v | LINK-BUG-[BG-TBD] |

## 四、详细分析

（与动态bug文档相同的层级结构，Bug标签改为 <BG-STATIC-*>；每个 <BG-STATIC-*> 下必须紧跟一行动态Bug关联子标签）

### <FG-功能组> 功能组描述
#### <FC-功能点> 功能点描述
##### <CK-检测点> 检测点描述
  - <BG-STATIC-001-NAME> Bug描述
    - <LINK-BUG-[BG-TBD]>    ← 静态分析阶段默认填写；validation后替换为 <LINK-BUG-[BG-NAME-xx]> 或 <LINK-BUG-[BG-NA]>
      - <FILE-{DUT}.v:xx-yy>   ← 必填；标记Bug所在源文件和行号范围
        ```verilog
        xx: ...
        yy: ...
        ```
    - **触发条件**：（输入/状态组合）
    - **预期行为**：（正确应有的输出）
    - **推断实际行为**：（RTL 推断出的错误输出）
    - **修复建议**：
      ```verilog
      // 修复后
      xx: ...   // 修复说明
      ```
```

> **注意**：`<LINK-BUG-[BG-TBD]>` 是每条静态Bug的**必填子标签**，在 `static_bug_analysis` 阶段写入，紧排在 `<BG-STATIC-*>` 行的下一子条目。`<FILE-filepath:line1-line2>` 是 `<LINK-BUG-*>` 的**必填子标签**，紧排在 `<LINK-BUG-*>` 行的下一子条目，并附带 RTL 源代码片段。`static_bug_validation` 阶段结束后不允许有 `<LINK-BUG-[BG-TBD]>` 残留。

### 动态Bug关联标签规范（`<LINK-BUG-[BG-TBD]>` → `<LINK-BUG-[BG-NAME-xx]>` / `<LINK-BUG-[BG-NA]>`）

每个 `<BG-STATIC-*>` 下方的第一个子项**必须**是动态Bug关联标签，格式固定为：

```
  - <LINK-BUG-[标签内容]>
```

其中 `[标签内容]` 按如下规则确定：

| 标签格式 | 阶段 | 含义 | 要求 |
|----------|------|------|------|
| `<LINK-BUG-[BG-TBD]>` | `static_bug_analysis` 写入 | 待验证，尚未有动态测试结果 | 所有新建静态Bug的默认值，不允许在 `static_bug_validation` 结束时残留 |
| `<LINK-BUG-[BG-NAME-xx]>` | `static_bug_validation` 更新 | 已证实，对应单个动态Bug | 必须在 `{DUT}_bug_analysis.md` 中存在对应完整 `<BG-NAME-xx>` + `<TC-*>` 记录 |
| `<LINK-BUG-[BG-N1-xx][BG-N2-xx]>` | `static_bug_validation` 更新 | 已证实，对应多个动态Bug | 用多个 `[BG-*]` 方括号组依次拼写；每个动态Bug均须在 `{DUT}_bug_analysis.md` 中有完整记录 |
| `<LINK-BUG-[BG-NA]>` | `static_bug_validation` 更新 | 误报，经动态测试验证该潜在Bug不存在 | 在该行下方（可选）添加一行误判说明 |

**`static_bug_validation` 阶段完成标准**：`{DUT}_static_bug_analysis.md` 中不存在任何 `<LINK-BUG-[BG-TBD]>` 标签，Checker 会通过 `parse_nested_keys` 解析该文件强制验证此规则。

### 完整示例（三阶段演进）

以 UartTx 模块为例，展示从静态发现到动态验证的完整标签演进过程。

**阶段一：`static_bug_analysis` 阶段完成时**（所有静态Bug均为 `<LINK-BUG-[BG-TBD]>`）

```markdown
## 三、潜在Bug汇总

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|---------|---------|--------|---------|------------|
| 001 | BG-STATIC-001-FSM-DEAD | FG-CONTROL/FC-FSM/CK-FSM-BUSY-CONFLICT | FSM跳转缺少tx_busy保护 | 高 | UartTx.v | LINK-BUG-[BG-TBD] |
| 002 | BG-STATIC-002-FSM-DEFAULT | FG-CONTROL/FC-FSM/CK-FSM-BUSY-CONFLICT | FSM缺少default分支 | 高 | UartTx.v | LINK-BUG-[BG-TBD] |
| 003 | BG-STATIC-003-WIDTH-MISMATCH | FG-TIMING/FC-BAUD/CK-BAUD-OVERFLOW | baud_cnt位宽可能不足 | 中 | UartTx.v | LINK-BUG-[BG-TBD] |

## 四、详细分析

### <FG-CONTROL> 控制组
#### <FC-FSM> 状态机功能
##### <CK-FSM-BUSY-CONFLICT> 状态机检测点（该检测点下发现两个Bug）
  - <BG-STATIC-001-FSM-DEAD> IDLE→SEND 跳转缺少 tx_busy 保护，start 在发送中拉高时可能进入未定义状态；置信度：高
    - <LINK-BUG-[BG-TBD]>
      - <FILE-UartTx.v:50-56>
        ```verilog
        50: always @(posedge clk) begin
        51:   case (state)
        52:     IDLE: if (start) state <= SEND;          // BUG: 未检查 tx_busy
        53:     SEND: if (bit_cnt == 8) state <= IDLE;
        54:     // default 分支缺失
        55:   endcase
        56: end
        ```
  - <BG-STATIC-002-FSM-DEFAULT> FSM缺少default分支，可能进入非法状态；置信度：高
    - <LINK-BUG-[BG-TBD]>
      - <FILE-UartTx.v:50-56>
        ```verilog
        50: always @(posedge clk) begin
        51:   case (state)
        52:     IDLE: if (start) state <= SEND;
        53:     SEND: if (bit_cnt == 8) state <= IDLE;
        54:     // BUG: default 分支缺失，可能导致锁死
        55:   endcase
        56: end
        ```

### <FG-TIMING>
#### 波特率计数功能 <FC-BAUD>
##### <CK-BAUD-OVERFLOW> baud_cnt 位宽为 8 位，当分频系数超过 255 时可能截断；置信度：中 
  - <BG-STATIC-002-WIDTH-MISMATCH>
    - <LINK-BUG-[BG-TBD]>
      - <FILE-UartTx.v:20>
        ```verilog
        20: reg [7:0] baud_cnt;   // BUG: 8位宽不足以确论覆盖所有分频参数
        ```

**阶段二：`static_bug_validation` 阶段完成时**（`<LINK-BUG-[BG-TBD]>` 全部被替换，无残留）

```markdown
## 三、潜在Bug汇总

| 序号 | Bug标签 | 功能路径 | 描述摘要 | 置信度 | 涉及文件 | 动态Bug关联 |
|------|---------|---------|---------|--------|---------|------------|
| 001 | BG-STATIC-001-FSM-DEAD | FG-CONTROL/FC-FSM/CK-FSM-BUSY-CONFLICT | FSM跳转缺少tx_busy保护 | 高 | UartTx.v | LINK-BUG-[BG-FSM-DEAD-92] |
| 002 | BG-STATIC-002-FSM-DEFAULT | FG-CONTROL/FC-FSM/CK-FSM-BUSY-CONFLICT | FSM缺少default分支 | 高 | UartTx.v | LINK-BUG-[BG-FSM-DEFAULT-85] |
| 003 | BG-STATIC-003-WIDTH-MISMATCH | FG-TIMING/FC-BAUD/CK-BAUD-OVERFLOW | baud_cnt位宽可能不足 | 中 | UartTx.v | LINK-BUG-[BG-NA] |

## 四、详细分析

### <FG-CONTROL>
#### <FC-FSM> 状态机功能
##### <CK-FSM-BUSY-CONFLICT> 状态机检测点（该检测点下发现两个Bug）
  - <BG-STATIC-001-FSM-DEAD> IDLE→SEND 跳转缺少 tx_busy 保护，start 在发送中拉高时可能进入未定义状态；置信度：高
    - <LINK-BUG-[BG-FSM-DEAD-92]>    ← 已替换，该静态Bug证实对应一个动态Bug
      - <FILE-UartTx.v:50-56>    ← 源文件位置不变
        ```verilog
        50: always @(posedge clk) begin
        51:   case (state)
        52:     IDLE: if (start) state <= SEND;          // BUG: 未检查 tx_busy
        53:     SEND: if (bit_cnt == 8) state <= IDLE;
        54:     // default 分支缺失
        55:   endcase
        56: end
        ```
  - <BG-STATIC-002-FSM-DEFAULT> FSM缺少default分支，可能进入非法状态；置信度：高
    - <LINK-BUG-[BG-FSM-DEFAULT-85]>    ← 已替换，该静态Bug证实对应一个动态Bug
      - <FILE-UartTx.v:50-56>    ← 源文件位置不变
        ```verilog
        50: always @(posedge clk) begin
        51:   case (state)
        52:     IDLE: if (start) state <= SEND;
        53:     SEND: if (bit_cnt == 8) state <= IDLE;
        54:     // BUG: default 分支缺失，可能导致锁死
        55:   endcase
        56: end
        ```

### <FG-TIMING>
#### <FC-BAUD> 波特率计数功能
##### <CK-BAUD-OVERFLOW> baud_cnt 位宽为 8 位，当分频系数超过 255 时可能截断；置信度：中 
  - <BG-STATIC-003-WIDTH-MISMATCH>
    - <LINK-BUG-[BG-NA]>             ← 已替换，误报
      - <FILE-UartTx.v:20>    ← 源文件位置不变
        ```verilog
        20: reg [7:0] baud_cnt;   // 实际参数通过 parameter 约束不超过 200，8位宽足够
        ```
    - 误判说明：波特率参数通过 `parameter` 约束不超过 200，8 位宽足够
```

**阶段三：`{DUT}_bug_analysis.md` 中对应的动态Bug记录**（由 `static_bug_validation` 阶段写入）

```markdown
### <FG-CONTROL>
#### <FC-FSM> 状态机功能
##### <CK-FSM-BUSY-CONFLICT> 测试 start 在 tx_busy=1 期间重新置位时 FSM 行为
  - <BG-FSM-DEAD-92>
    - <TC-FSM-REENTRANT-FAIL> start_during_send：验证FSM重入保护
      - 测试结果：FAIL ← 证实静态分析Bug BG-STATIC-001-FSM-DEAD

##### <CK-FSM-BUSY-CONFLICT> 测试缺少 default 分支时 FSM 进入非法状态的行为
  - <BG-FSM-DEFAULT-85>
    - <TC-FSM-ILLEGAL-STATE> illegal_state_enter：验证default分支缺失
      - 测试结果：FAIL ← 证实静态分析Bug BG-STATIC-002-FSM-DEFAULT
```

### 标签书写要点

| 层级 | 格式示例 | 说明 |
|------|---------|------|
| 功能组 FG | `<FG-CONTROL>` | 与 `_functions_and_checks.md` 共用，或新增 `<FG-STATIC>` |
| 功能点 FC | `<FC-FSM>` | 与 `_functions_and_checks.md` 共用，或新增 `<FC-STATIC-*>` |
| 检测点 CK | `<CK-FSM-BUSY-CONFLICT>` | 需同步写入 `_functions_and_checks.md`（高/中置信度必须） |
| 静态Bug | `<BG-STATIC-001-FSM-DEAD>` | 挂靠在 `<CK-*>` 之后，序号+名称格式；**一个 `<CK-*>` 下可以有多个 `<BG-STATIC-*>` 标签** |
| 静态Bug（无Bug声明） | `<BG-STATIC-NULL>` | 挂靠在 `<FG-NULL>`、`<FC-NULL>`、`<CK-NULL>` 之后；不需要 `<LINK-BUG-*>` 子标签；不可与其他 `<BG-STATIC-*>` 共存 |
| 动态Bug关联（待验证） | `<LINK-BUG-[BG-TBD]>` | 每个 `<BG-STATIC-*>` 的**必填**子标签，`static_bug_analysis` 阶段写入 |
| 动态Bug关联（已证实，单个） | `<LINK-BUG-[BG-FSM-DEAD-92]>` | `static_bug_validation` 后替换，需在 `_bug_analysis.md` 中有对应完整记录 |
| 动态Bug关联（已证实，多个） | `<LINK-BUG-[BG-FSM-DEAD-92][BG-FSM-DEFAULT-85]>` | 一个静态Bug证实存在多个动态Bug时，用多个 `[BG-*]` 方括号组依次拼写；每个标签均须在 `_bug_analysis.md` 中有完整记录 |
| 动态Bug关联（误报） | `<LINK-BUG-[BG-NA]>` | `static_bug_validation` 后替换，可选附加误判说明行 |
| 源文件位置（单个范围） | `<FILE-UartTx.v:50-56>` | 每个 `<LINK-BUG-*>` 的**必填**子标签；路径相对于项目根目录；行号范围 `N-M` |
| 源文件位置（多范围） | `<FILE-UartTx.v:50-56,100-120>` | 同一文件的多个不连续行范围，逗号分隔 |
| 源文件位置（多文件） | `<FILE-pkg/uart_pkg.sv:22-24>` | 同一 `<LINK-BUG-*>` 下可配置多个 `<FILE-*>` 子标签 |

**注意**：
- `<BG-STATIC-*>` 标签仅在 `{DUT}_static_bug_analysis.md` 中使用，不出现在 `{DUT}_bug_analysis.md` 中
- **一个 `<CK-*>` 检测点下可以挂靠多个 `<BG-STATIC-*>` 标签，每个标签代表在该检测点发现的一个独立Bug**
- `<BG-STATIC-NULL>` 是必须显式书写的无Bug声明，不可省略——若 `_static_bug_analysis.md` 中既无任何 `<BG-STATIC-*>` 又无 `<BG-STATIC-NULL>`，Checker 将报错
- `<LINK-BUG-*>` 标签仅在 `{DUT}_static_bug_analysis.md` 中使用，不出现在 `{DUT}_bug_analysis.md` 中
- `<FILE-*>` 标签是 `<LINK-BUG-*>` 的必填子标签，Checker 强制验证其存在和格式；`<FILE-*>` 行下方必须附带对应 RTL 源代码片段
- `static_bug_validation` 阶段结束后，`{DUT}_static_bug_analysis.md` 中**不允许有任何 `<LINK-BUG-[BG-TBD]>` 残留**，Checker 通过 `parse_nested_keys` 强制验证
- 在文中引用标签时去掉尖括号，例如 `BG-STATIC-001`，防止解析错误
- 静态分析报告的主体文档内容须使用 `{DOC_GEN_LANG}` 指定的语言编写
