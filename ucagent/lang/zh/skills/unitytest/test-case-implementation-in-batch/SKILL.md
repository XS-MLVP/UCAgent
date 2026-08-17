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
- `recordbug.py`只负责生成`FG/FC/CK/BG/TC`结构、波形占位块和分析章节骨架，不负责根因判断；脚本成功只表示骨架已创建，绝不表示Bug分析完成
- 对可复现的动态Bug，必须真实调用`WaveInfo`，并在动态Bug文档对应`<BG-*>/<TC-*>`后立即写入```yaml代码块；该块必须且只能包含顶层`waveform_analysis`映射，并在其下保存工具返回的`receipt_id`和`status: confirmed`。禁止使用旧`<WAVEFORM-ANALYSIS>`标签、裸YAML或JSON围栏；Checker会核对收据并在当前波形上重放pattern，不能伪造波形字段
- 只带pattern但没有`logged_cycle+clock_signal`或完整`start_step+end_step`的调用属于探索调用；返回`evidence_window_required`时必须逐字使用`recommended_evidence_call`重调，不能把`analysis_window.effective_*`手工写入文档冒充原调用参数
- 最终显式窗口调用必须同时提供`start_step`和`end_step`，成功后优先复制`bug_document_fields`，再根据真实timeline和RTL补写`alignment_evidence`、`observed_behavior`、`source_correlation`
- 有波形时用结构化pattern匹配输入、握手、状态和输出；无波形时先用metadata-only调用获取诊断，修复测试名称或波形生成流程并重跑，`status: unavailable`不能完成阶段
- `<BG-STATIC-*>`只允许写在`{DUT}_static_bug_analysis.md`；一旦测试动态证实，必须在`{DUT}_bug_analysis.md`新建独立`<BG-NAME-xx>`并提供confirmed波形证据，再从静态文档用`<LINK-BUG-*>`关联
- 日志中的cycle与wavekit的wave step不是同一概念，二者可能相差0到数个周期且时间戳尺度也可能不同；必须指定clock_signal，通过clock occurrence index对齐，并在候选有歧义时增强日志后重跑
- 找不到波形时，按`WaveInfo`返回的测试名称、最新session、`.dat`、SetWaveform、dut.Finish和文件损坏诊断逐项处理；不能改用旧session或其他测试的波形

### 步骤5: Bug记录

#### 5.1 生成骨架

针对确认的DUT Bug，使用`RunSkillScript`执行`recordbug.py`。脚本只接收`BG/TC/BD`，并在动态Bug文档中生成带`<BUG-TODO>`的未完成骨架：
```bash
python3 script -BG 'BG-CIN-OVERFLOW-98' -TC 'TC-tests/test_adder.py::test_overflow' -BD '完整加法已截断但overflow仍为0。'
```

不要向脚本传`ROOT/FILE/FIX`；这些参数已删除。不要把脚本输出当成完成结果，也不要在仍有`<BUG-TODO>`时调用`Check`或`Complete`。

#### 5.2 LLM 填写分析

脚本返回后，必须继续完成以下工作，不能结束当前任务：

1. 读取失败断言的expected/actual、事务上下文和对应CK原文。
2. 调用`WaveInfo`取得最终confirmed证据，用真实`bug_document_fields`完整替换每个TC后的波形占位块。
3. 打开DUT RTL/HDL，定位能解释波形错误的首个错误决策和传播路径；不要只复述测试失败或`source_correlation`。
4. 使用`EditTextFile`或`ReplaceStringInFile`直接编辑已生成的BG条目，逐项替换所有`<BUG-TODO>`及其提示文字，完成：Bug概述、现象与等级、触发条件与影响范围、根因分析、源码证据与逐行分析、动态因果链、修复建议、风险与复验计划。Checker只识别`<BUG-TODO>`，不解析“待补充”等自然语言。
5. 有源码时，源码证据必须包含真实`path:L1-L2`和完整HDL fenced代码块；`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`必须各出现一次并位于代码块的语言原生注释中，标签后方写具体解释。无源码时在`<BUG-SOURCE-EVIDENCE>`字段中加入独立行`<BUG-SOURCE-UNAVAILABLE>`，并用接口协议、失败日志和波形完成黑盒因果链，禁止伪造源码。两种分支互斥，不能同时使用无源码标记与HDL代码块或三个源码因果标签。
6. 重新读取整个BG条目，确认根因、源码、波形和修复互相一致，且该BG内没有任何占位文本。

WaveInfo 收据陈旧、缺失或无法重放时，重新运行对应失败用例并重新调用 WaveInfo，然后替换该 TC 的证据块。只要正确实现的测试仍 Fail，禁止删除 `<TC-*>`、`<BG-*>` 或整个 FG/FC/CK 分支来规避 Checker；只有正确测试已经 Pass，或复查证明它不是 DUT Bug 时，才可同步重新分类或删除记录。

动态条目容器使用独立行`<DYNAMIC-BUGS>`定位，八个字段的唯一机器结构是以下独立行标记，顺序固定：`<BUG-OVERVIEW>`、`<BUG-SYMPTOMS>`、`<BUG-TRIGGER>`、`<BUG-ROOT-CAUSE>`、`<BUG-SOURCE-EVIDENCE>`、`<BUG-CAUSAL-CHAIN>`、`<BUG-FIX>`、`<BUG-RETEST>`。LLM只填写标记之间的内容，不能删除、复制、改名或调换标记。相邻中文粗体标题只是展示文字，可以本地化；Checker和Skill脚本不依赖标题文字。旧的仅标题格式不兼容。

脚本生成结构，LLM负责分析和填空；两步缺一不可。所有根因、修复和复验内容必须留在所属BG条目内，不建立全局根因汇总。

### 步骤6：阶段检查

操作：完成当前批次的测试用例后，使用`Check`工具进行阶段检查.若未通过检查,则基于反馈信息修正测试用例后,直到阶段检查通过为止;若通过检查,则执行下一批次的测试用例实现,或者是使用`Complete`工具进入下一阶段

### RunSkillScript工具使用说明:
- 允许一次性列举多条命令,但每条命令必须独立完整,且必须符合格式要求,例如记录Fail但合理的测试用例时,若有10个Fail但合理的测试用例待记录
- 其他参数值替换为每个测试用例记录内容,只允许使用定义的参数,禁止额外参数,且参数值必须符合上述格式要求,每个参数必须使用单括号括起来
- 使用`RunSkillScript`工具时,若有10条命令要执行,前5条命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`RunSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令,直至所有命令执行完毕
- `recordbug.py`是新增BG/TC结构的唯一入口；脚本生成骨架后，必须使用文本编辑工具在该BG内部填写真实波形与分析内容。不得手工创建另一套BG层级，也不得跳过填空步骤。


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
