---
name: test-case-implementation-in-batch
description: 分批测试用例实现与对应Bug分析阶段专属技能，用于依据测试模板注释、功能规格CK原文和覆盖约束实现针对性激励与断言，并完成测试执行、动态Bug分析和报告记录
---

# 测试用例实现与对应Bug分析

## 测试参数与对象边界

以当前批次已经生成的测试模板签名为准。实现测试逻辑时必须原样保留fixture参数及顺序，不得自行增加、删除、交换参数，也不得用`dut`或`mock_dut`替换`env`。

| 测试类别 | 参数契约 |
|---|---|
| 普通DUT测试 | 保留模板已有的`def test_xxx(env):`或`def test_xxx(env, ref_model):` |
| Mock组件独立测试 | `def test_api_{DUT}_mock_xxx(mock_dut):` |

- 模板中已有`ref_model`时，必须保留为第二个参数并用于依据规格独立计算预期；不能读取DUT实际输出后返回同值，也不能为了匹配DUT而复制可疑RTL逻辑。
- DUT与参考模型不一致时，先用规格、边界定义和源码判断哪一方错误。参考模型错误属于验证基础设施问题，必须修复到测试能够给出可信预期；不能记录为DUT Bug。
- 普通DUT测试通过`env`使用已集成的验证环境和外部组件。当前技能不实现`test_api_{DUT}_mock_*`测试，也不能把`env`改成`mock_dut`。
- Mock行为、回调注册或响应时序错误属于验证环境问题，必须修复Mock或`env`后重跑；不能作为DUT Bug保留Fail。
- `{OUT}/tests/{DUT}_api.py`和`{OUT}/tests/{DUT}_function_coverage_def.py`是当前批次的稳定输入，默认只编辑当前测试文件。不得为绕过setup、fake DUT、`mark_function`或覆盖率错误而重写API模板、替换fixture、伪造`fc_cover`、删除覆盖标记或改变coverage上报。
- 若最早traceback确实落在API/fixture/覆盖率实现中，先结合接口契约和源码证明根因；只有当前stage允许且证据明确时才做最小修复，并先运行对应的API/fixture专用测试。不能仅因某个测试失败就猜测并重构公共模板。

## 执行步骤

接收当前批次测试用例后,按照以下步骤完成当前批次测试用例的实现与 Bug 分析任务：

### 步骤1: 模板、规格与约束分析

对当前批次的每个测试用例依次完成：

1. 打开对应测试模板，完整阅读函数的docstring、注释、`TASK/TODO`、已有`mark_function`和覆盖约束。这些内容定义模板的原始测试意图，不能跳过或只按文件名、函数名猜测。
2. 从`mark_function`确定完整`FG/FC/CK`路径，在`{OUT}/{DUT}_functions_and_checks.md`中定位并阅读对应CK原文，提炼触发前提、输入组合、状态/时序、边界/异常行为和预期输出。
3. 阅读`{OUT}/tests/{DUT}_function_coverage_def.py`中的对应检测点约束，将CK原文、模板意图和覆盖约束共同作为测试契约。
4. 为测试契约中的每项关键条件安排明确的输入或状态设置，为每项预期结果安排能够区分DUT正确与错误行为的检查。

注意:
- 若约束条件是`lambda`表达式,则测试激励必须满足该`lambda`表达式
- 若约束条件是一个函数,则测试激励必须满足该函数返回True的条件
- 该部分需要详细分析；测试激励本身必须满足有效约束。DUT设计Bug可能导致输出不满足预期，但不能把不满足输入约束的测试错误当作DUT Bug
- 若模板注释、CK原文、覆盖约束或DUT接口契约不一致，必须查阅相关文件定位原因并修正测试意图，不得静默忽略差异

### 步骤2: 测试用例实现

操作: 将测试激励实现为可执行代码,并添加断言检查输出是否符合预期,并将可执行代码填充到对应测试用例的空模板中

注意:
- 使用API接口调用芯片功能，避免直接操作底层信号
- 覆盖CK要求的典型值、边界值、特殊值及必要的状态、时序和异常组合
- 不能用`assert`语句去判断输入端约束条件是否满足,直接通过充分的分析与设计测试激励的方式来确保输入端约束条件被满足
- 添加能够区分正确与错误DUT行为的断言（Eg: `assert actual == expected, error_msg`）
- 断言必须有意义，不允许类型判断、大范围的数值比较等无效断言
- 禁止仅调用API、只确认没有异常、只检查类型/非空、使用无依据的宽松范围，或仅声明`mark_function`而没有实际验证CK行为
- 完成前逐个复核：模板注释中的测试意图已经落实，CK原文的关键条件均有对应激励，CK预期结果均有严格的expected/actual断言；`mark_function`本身不等于完成CK验证
- 不能为了通过测试而写断言,也不能在已知有Bug的情况下写能通过测试的断言
- 可能触发Bug的断言消息应打印cycle及cycle_basis、transaction ID、相关输入输出pin、valid/ready或状态、expected和actual，便于后续用`WaveInfo`构建精确pattern；增加日志不能新增Step、改变callback顺序或改变测试时序
- 判断输出前必须先阅读本测试实际调用的API/driver、callback和`Step`顺序，确认输入在哪个边沿驱动、请求何时被DUT接受、输出何时有效。ready/valid只是常见形式，也可能是req/ack、enable、start/busy、固定延迟或其他自定义协议，不能按信号名称猜测
- 一次`Step(1)`只推进仿真，不自动表示请求已接受或结果已有效。必须确认API内部是否已经执行Step/等待握手，并依据规格选择组合settle、指定采样边沿、固定N周期、`out_valid/done/ack`成立或`busy`清零等真实采样条件；禁止API调用后机械地只Step一次就读取结果并判错

### 步骤3: 测试用例执行

操作: 实现当前批次的所有测试用例后，用`RunTestCases('{TEST_BATCH_RUN_ARGS}')`执行测试(TEST_BATCH_RUN_ARGS的具体信息在阶段任务描述部分中)

注意:
- 只执行当前批次要求实现的测试用例

### 步骤4: 测试结果分析

操作: 分析测试结果，针对待实现的测试用例的执行结果进行如下分析:
- 分析`failed_ck`中与当前批次待实现的测试用例相关的检测点:
  - 若正确测试稳定复现DUT设计缺陷,导致输出约束无法满足,则进入动态Bug确认与标记流程
  - 若是测试代码、断言、预期值、检测点、fixture/API、参考模型、复位/时序或环境问题,必须修复并重跑到`PASSED`,不得标记为DUT Bug或保留`FAILED`
- 分析`failed_tc`中当前批次待实现的测试用例:
  - 若确认是DUT设计Bug,保留正确断言自然触发的`FAILED`,并完成非零置信度动态Bug记录、CK关联、源码根因和真实WaveInfo证据
  - 否则修正测试或验证基础设施并重跑,直到`PASSED`

总之,当前批次的测试用例有以下情况:
1. 测试用例`FAILED`且对应检测点失败：先分类；确认DUT Bug才标记，否则修复到`PASSED`
2. 测试用例`FAILED`但对应检测点未失败：关联或测试逻辑异常，必须修正；不能仅凭测试Fail标记Bug
3. 测试用例`PASSED`且对应检测点通过：正常
4. 测试用例`PASSED`但对应检测点失败：覆盖关联、采样或断言存在矛盾，必须修正

以下述结构生成测试用例的 Bug 骨架:
  - `BG`: 仅用于已动态复现的DUT设计Bug，格式为BG-NAME-NUM，NUM为1到100的置信度。示例：BG-CIN-OVERFLOW-98；BG-*-0不能解释失败用例
  - `TC`: 测试用例标签，必须是TC-前缀,以及测试用例路径.示例: TC-tests/test_adder.py::test_xxx
  - `BD`: DUT Bug的简要描述

注意:
- 通常情况下,测试用例与检测点一一关联,例如:test_Adder_api.py:56-90::test_result_sample这个测试用例就关联FG-API/FC-API-OPERATION/CK-RESULT-SAMPLE
- 阶段完成不要求已确认DUT Bug的复现用例Pass；精确条件是：所有非DUT-Bug用例Pass，所有剩余Fail均为已完成动态取证的DUT Bug复现用例
- `create_test_case_templates`阶段生成空模板时必须使用`assert False, "Not implemented"`；当前实现阶段必须删除该占位断言，换成真实激励和严格预期检查
- 已实现测试禁止用`assert False`制造Fail，禁止修改正确预期或弱化断言来制造Pass，也禁止用`BG-*-0`保留测试/基础设施失败
- `RunTestCases`可能执行了很多的测试用例,但当前步骤中,只针对待实现的当前批次测试用例进行分析工作
- `record_dynamic_bug.py`只负责在封闭的`<DYNAMIC-BUGS>`分区生成`FG/FC/CK/BG/TC`、`<WAVEFORM-REF>`和分析字段骨架，不创建波形YAML，也不负责根因判断；脚本成功绝不表示Bug分析完成
- 对可复现的动态Bug，必须真实调用`WaveInfo`取得最终receipt，再调用`ApplyWaveInfoEvidence`原子维护BG侧`<WAVEFORM-REF>`和中央`<WAVEFORM-EVIDENCE>`分区中的唯一`<WAVEFORM-TC-...>`记录。不要复制receipt字段或viewer token；BG内只保留TC与引用，YAML和viewer只放在中央记录中
- 只带pattern但没有`logged_cycle+clock_signal`或完整`start_step+end_step`的调用属于探索调用；返回`evidence_window_required`时必须逐字使用`recommended_evidence_call`重调，不能把`analysis_window.effective_*`手工写入文档冒充原调用参数
- 最终显式窗口调用必须同时提供`start_step`和`end_step`。成功后使用真实`receipt_id`调用`ApplyWaveInfoEvidence(target_file=..., bug_tag=..., test_case_tag=..., receipt_id=...)`。随后完成TC共享的`alignment_evidence`，并在`bug_evidence.<BG>`下完成该Bug的`required_signals`、`observed_behavior`、`source_correlation`
- 同一Bug有多个Fail TC时，对每个TC分别调用一次Apply工具；同一Fail TC揭示多个独立Bug时，为每个BG用相同TC调用一次。一个TC始终只有一个中央波形记录，`bug_tags`和`bug_evidence`必须精确覆盖所有引用它的BG
- 多Bug共享TC时，最终WaveInfo的`signal_groups`必须暴露所有Bug所需信号的并集；新增Bug需要扩展信号时重新取得最终receipt，并传`replace_existing=true`。替换receipt会保留各Bug的`required_signals`，重置共享对齐结论和逐Bug语义结论
- 最终WaveInfo调用必须填写完整`signal_groups`：时序DUT列出实际时钟，组合DUT声明`combinational`且不虚构时钟；同时列出当前功能相关输入数据/选择/使能、相关输出数据/状态/有效位、接口真实的请求接受与响应有效控制，以及至少一个能解释功能选择、状态或错误传播的关键外部/内部信号。所有路径必须来自`signal_catalog`，并由同一receipt签名后进入timeline和viewer；禁止只查看目标result就判Bug
- `pattern`只用于定位真实失败事件，`signal_groups`用于加载必要上下文；不要为了让viewer出现信号而把所有上下文都设成`change`。`protocol`只有在规格与接口确认不存在ready/valid/enable/start/busy/done/ack等控制时才可为空，不能根据控制信号名称猜测协议语义
- 有波形时用结构化pattern匹配输入、握手、状态和输出；无波形时先用metadata-only调用获取诊断，修复测试名称或波形生成流程并重跑，`status: unavailable`不能完成阶段
- `WaveInfo`匹配到事件只说明该波形片段可重放，不会自动判定Bug。LLM必须结合规格和测试驱动方式审查真实接受条件、backpressure/stall、pipeline或响应latency、事务ID/顺序以及输出有效窗口；pattern和timeline应包含ready/valid或DUT实际使用的等价协议锚点
- `valid/enable=0`、`ready/accept=0`、复位/空闲/过渡周期、尚未达到响应latency或协议声明data无效时看到的单点data mismatch只能作为调查线索，不能直接生成BG。若规格明确要求busy期间忽略请求或保持某值，则应引用该约束判断，而不是机械套用握手规则
- 波形审查还要核对测试到底推进了多少Step、API内部是否已推进/等待以及实际输出有效信号何时成立；如果断言过早采样，属于测试时序问题，必须修复到正确采样后再分类
- `<BG-STATIC-*>`只允许写在`{DUT}_static_bug_analysis.md`；一旦测试动态证实，必须在`{DUT}_bug_analysis.md`新建独立`<BG-NAME-xx>`并提供confirmed波形证据，再从静态文档用`<LINK-BUG-*>`关联
- 日志中的cycle与wavekit的wave step不是同一概念，二者可能相差0到数个周期且时间戳尺度也可能不同；必须指定clock_signal，通过clock occurrence index对齐，并在候选有歧义时增强日志后重跑
- 找不到波形时，按`WaveInfo`返回的测试名称、最新session、`.dat`、SetWaveform、dut.Finish和文件损坏诊断逐项处理；不能改用旧session或其他测试的波形
- 中断或重启后可以复用通过验证的`WaveInfo` receipt；当前批次只运行部分用例时，不得删除历史TC/BG、手工改写有效receipt或重造viewer链接。最终记录阶段必须运行完整测试集合并严格重放全部动态Bug TC
- `bug_document_viewer_link`必须由`ApplyWaveInfoEvidence`直接写入；不得让LLM复制或修改标记、URL和token

### 步骤5: Bug记录

#### 5.1 生成骨架

针对确认的DUT Bug，默认可使用文本编辑工具逐字参照Guide第 5.1 节完整标准案例和第 5.2 节骨架，只建立一次带`<BUG-TODO>`的未完成BG结构和第一份TC。若共享技能`unitytest/dynamic-bug-recording`可用，也可以通过`RunSkillScript`执行一次只接收`BG/TC/BD`的`record_dynamic_bug.py`生成相同中文骨架；同一BG的后续Fail TC直接交给`ApplyWaveInfoEvidence`创建：
```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'TC-tests/test_adder.py::test_overflow' -BD '完整加法已截断但overflow仍为0。'"]
```

脚本参数仅为`BG/TC/BD`。不要把脚本输出当成完成结果，也不要在仍有`<BUG-TODO>`时调用`Check`或`Complete`。

#### 5.2 LLM 填写分析

骨架建立后，必须继续完成以下工作，不能结束当前任务：

1. 读取失败断言的expected/actual、事务上下文和对应CK原文，并阅读测试使用的API/driver、callback与`Step`顺序，确认真实驱动边沿、接受条件和输出采样窗口。
2. 调用`WaveInfo`取得最终confirmed证据；`signal_groups`覆盖该TC关联的全部Bug所需信号并集。随后调用`ApplyWaveInfoEvidence`，由工具创建缺失的兄弟TC、引用和中央记录；打开viewer确认签名信号集合均已显示。目标TC已有不同真实receipt时显式传`replace_existing=true`，再重新完成被重置的语义结论。
3. 打开DUT RTL/HDL，定位能解释波形错误的首个错误决策和传播路径；不要只复述测试失败或`source_correlation`。
4. 使用`EditTextFile`或`ReplaceStringInFile`直接编辑已生成的BG条目，逐项替换所有`<BUG-TODO>`及其提示文字，完成：Bug概述、现象与等级、触发条件与影响范围、根因分析、源码证据与逐行分析、动态因果链、修复建议、风险与复验计划。必须清除全部`<BUG-TODO>`，不得换成“待补充”等自然语言占位。
5. 有源码时，源码证据必须包含真实`path:L1-L2`和完整HDL fenced代码块；`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`必须各出现一次并位于代码块的语言原生注释中，标签后方写具体解释。无源码时在`<BUG-SOURCE-EVIDENCE>`字段中加入独立行`<BUG-SOURCE-UNAVAILABLE>`，并用接口协议、失败日志和波形完成黑盒因果链，禁止伪造源码。两种分支互斥，不能同时使用无源码标记与HDL代码块或三个源码因果标签。
6. 重新读取整个BG条目，确认根因、源码、波形和修复互相一致，且该BG内没有任何占位文本。

WaveInfo 收据陈旧、缺失或无法重放时，重新运行对应失败用例并重新调用 WaveInfo，然后通过`ApplyWaveInfoEvidence(..., replace_existing=true)`替换该 TC 的中央记录。只要正确实现的测试仍 Fail，禁止删除 `<TC-*>`、`<BG-*>` 或整个 FG/FC/CK 分支来绕过验收；只有正确测试已经 Pass，或复查证明它不是 DUT Bug 时，才可同步重新分类或删除记录。

动态条目容器使用独立行`<DYNAMIC-BUGS>`定位，八个字段的唯一机器结构是以下独立行标记，顺序固定：`<BUG-OVERVIEW>`、`<BUG-SYMPTOMS>`、`<BUG-TRIGGER>`、`<BUG-ROOT-CAUSE>`、`<BUG-SOURCE-EVIDENCE>`、`<BUG-CAUSAL-CHAIN>`、`<BUG-FIX>`、`<BUG-RETEST>`。每个标记后的第一条非空行必须逐字使用Guide第 5.1 节的六级中文标题。LLM只填写标题后的证据正文，不能删除、复制、改名、翻译、调换标记或标题，也不能改用粗体或其他标题级别。

文本编辑或可选脚本生成结构，LLM负责分析和填空；两步缺一不可。所有根因、修复和复验内容必须留在所属BG条目内，不建立全局根因汇总。

### 步骤6：阶段检查

操作：完成当前批次的测试用例后，使用`Check`工具进行阶段检查.若未通过检查,则基于反馈信息修正测试用例后,直到阶段检查通过为止;若通过检查,则执行下一批次的测试用例实现,或者是使用`Complete`工具进入下一阶段

### 可选RunSkillScript工具使用说明:
- 允许一次性列举多条命令,但每条命令必须独立完整,且必须符合格式要求,例如记录Fail但合理的测试用例时,若有10个Fail但合理的测试用例待记录
- 其他参数值替换为每个测试用例记录内容,只允许使用定义的参数,禁止额外参数,且参数值必须符合上述格式要求,每个参数必须使用单括号括起来
- 使用`RunSkillScript`工具时,若有10条命令要执行,前5条命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`RunSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令,直至所有命令执行完毕
- 共享技能`unitytest/dynamic-bug-recording`及其`record_dynamic_bug.py`可用时，只用于新Bug的第一份BG/TC结构；共享技能未复制、Skill整体禁用或脚本不可用时，使用文本编辑工具按Guide第 5.1 节完整标准案例和第 5.2 节骨架只建立一次相同中文BG结构。后续兄弟TC、引用和中央记录由`ApplyWaveInfoEvidence`维护，再完成共享`alignment_evidence`、逐Bug语义字段和BG分析章节。不得手工创建另一套BG层级，也不得跳过填空步骤。


### 约束条件示例
```python
def check_norm_bit24(x):
  if x.op.value != 0:
      return False
  # 排除特殊值
  if is_nan(x.a.value) or is_nan(x.b.value) or is_inf(x.a.value) or is_inf(x.b.value):
      return False
  # 检测同号相加产生进位的场景
  # 条件：同号、正数（非零）、指数相同、尾数之和会产生进位到第24位
  a_sign = get_sign(x.a.value)
  b_sign = get_sign(x.b.value)
  if a_sign != b_sign:
      return False
  if is_zero(x.a.value) or is_zero(x.b.value):
      return False
  exp_a = (x.a.value >> 23) & 0xFF
  exp_b = (x.b.value >> 23) & 0xFF
  if exp_a != exp_b:
      return False
  # 当两个尾数都>=0.5时，相加可能产生进位
  mant_a = x.a.value & 0x7FFFFF
  mant_b = x.b.value & 0x7FFFFF
  return mant_a >= 0x400000 and mant_b >= 0x400000
```
对于上述`check_`函数,测试激励必须满足以下约束条件:
- 操作类型必须是加法：x.op.value == 0
- 输入不能是特殊值：
    - a 不是 NaN
    - b 不是 NaN
    - a 不是 Inf
    - b 不是 Inf
- 两个操作数必须同号：sign(a) == sign(b)
- 两个操作数都不能是 0：a != 0 且 b != 0
- 两个操作数指数必须相同：exp(a) == exp(b)
- 两个操作数尾数都至少为 0.5（仅看 fraction 字段）：
    - mant_a >= 0x400000
    - mant_b >= 0x400000

若是lambda表达式,例如:
```python
lambda x: x.a.value == 0x7F800000
```
这表示测试激励必须满足 x.a.value == 0x7F800000 的条件,即 a 是正无穷的场景
