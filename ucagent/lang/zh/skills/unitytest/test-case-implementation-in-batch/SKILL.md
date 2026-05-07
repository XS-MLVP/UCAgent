---
name: test-case-implementation-in-batch
description: 分批测试用例实现与对应bug分析阶段专属技能,用于指导测试用例实现,Bug分析与报告撰写
---

# 测试用例实现与对应Bug分析

## 执行步骤

接收当前批次测试用例后,按照以下步骤完成当前批次测试用例的实现与 Bug 分析任务：

### 步骤1: 约束分析

操作: 针对测试用例对应的检测点,阅读并分析`{DUT}_function_coverage_def.py`中对应检测点的约束,设计出能满足该约束的测试激励,可以参考`约束条件示例`中的例子

注意:
- 若约束条件是`lambda`表达式,则测试激励必须满足该`lambda`表达式
- 若约束条件是一个函数,则测试激励必须满足该函数返回True的条件
- 该部分需要详细分析,在无`设计Bug`和`测试Bug`的前提下,设计出满足约束条件的测试激励
- 若后续分析发现存在`设计Bug`或`测试Bug`,则允许不符合约束情况

### 步骤2: 测试用例实现

操作: 将测试激励实现为可执行代码,并添加断言检查输出是否符合预期,并将可执行代码填充到对应测试用例的空模板中

注意:
- 使用API接口调用芯片功能，避免直接操作底层信号
- 设计充分的测试数据：典型值、边界值、特殊值
- 不能用`assert`语句去判断输入端约束条件是否满足,直接通过充分的分析与设计测试激励的方式来确保输入端约束条件被满足
- 添加断言检查输出是否符合预期（Eg: assert output == excepted_output, error_msg）
- 断言必须有意义，不允许类型判断、大范围的数值比较等无效断言
- 不能为了通过测试而写断言,也不能在已知有Bug的情况下写能通过测试的断言

### 步骤3: 测试用例执行

操作: 实现当前批次的所有测试用例后，用`RunTestCases('{TEST_BATCH_RUN_ARGS}')`执行测试(TEST_BATCH_RUN_ARGS的具体信息在阶段任务描述部分中)

注意:
- 只执行当前批次要求实现的测试用例

### 步骤4: 测试结果分析

操作: 分析测试结果，针对待实现的测试用例的执行结果进行如下分析:
- 分析`failed_ck`中与当前批次待实现的测试用例相关的检测点:
  - 若是设计缺陷,导致对输出的约束始终无法得到满足,属于`设计Bug`,则`标记`
  - 若是测试缺陷,误设计了完全不合理的检测点,例如两个正数相加检测下溢这类,属于`测试Bug`,则`标记`,且必须保证该测试用例是`FAILED`的,不能`PASSED`
  - 若不属于上述两种情况,则对该测试用例重复上述步骤(1,2,3),直到满足为止
- 分析`failed_tc`中当前批次待实现的测试用例:
  - 若`FAILED`是合理的,即确实发现了`设计Bug`或是`测试Bug`,则标记
  - 否则,则对该测试用例重复上述步骤(1,2,3)，直到结果合理为止

总之,当前批次的测试用例有以下情况:
1. 测试用例在`failed_tc`中,且对应检测点在`failed_ck`中: `标记`
2. 测试用例在`failed_tc`中,但对应检测点不在`failed_ck`中: `标记`
3. 测试用例不在`failed_tc`中,但对应检测点不在`failed_ck`中: 跳过
4. 测试用例不在`failed_tc`中,但对应检测点在`failed_ck`中: 不存在这种情况,修改测试用例的实现,使其满足以上3种情况

以下述结构对测试用例进行标记:
  - `BG`: Bug标签，格式为BG-NAME-NUM,必须是BG-前缀,以及数字后缀NUM,其中数字为置信度,范围为[0,100].示例: BG-CIN-OVERFLOW-98;若是`测试Bug`,则置信度必须置为0
  - `TC`: 测试用例标签，必须是TC-前缀,以及测试用例路径.示例: TC-tests/test_adder.py::test_xxx
  - `BD`: Bug的简要描述;若是`测试Bug`,则描述测试设计的不合理之处
  - `FILE`: Bug涉及的源文件路径和相关代码的行数范围，格式为"Adder_RTL/文件.v:L1-L2",其中L1和L2分别是起始行和结束行,可以是单行或多行. 示例: "Adder_RTL/Adder.v:10-14"(代码务必高度相关且简洁,只列出与潜在Bug相关的代码);若是`测试Bug`,则列出{DUT}_function_and_check.md中对应检测点所在行数,路径必须是相对于当前工作目录的相关路径
  - `ROOT`: Bug根因分析,必须基于源码进行详细分析,说明为什么有这个缺陷,导致了什么问题(ROOT和FILE里的源码必须对应);如果源码不存在,则需要基于设计进行缺陷分析
  - `FIX`: Bug修复建议,以`FILE`所指的多行源代码为基础,直接在其上进行修改,最终仅返回修改后的源代码(注意添加换行符'\n',保持美观)

注意:
- 通常情况下,测试用例与检测点一一关联,例如:test_Adder_api.py:56-90::test_result_sample这个测试用例就关联FG-API/FC-API-OPERATION/CK-RESULT-SAMPLE
- `RunTestCases`可能执行了很多的测试用例,但当前步骤中,只针对待实现的当前批次测试用例进行分析工作

### 步骤5: Bug记录

操作:分析完当前批次测试用例后,针对`标记`的测试用例,使用`RunSkillScript`工具执行`recordbug.py`脚本,将这些测试用例记录下来,以便后续阶段进行Bug修复和回归测试,命令格式如下:
```bash
python3 script -BG 'BG' -TC 'TC' -BD 'BD' -ROOT 'ROOT' -FILE 'FILE' -FIX 'FIX'
python3 script -BG 'BG' -TC 'TC' -BD 'BD' -ROOT 'ROOT' -FILE 'FILE' -FIX 'FIX'
...
```


### 步骤6：阶段检查

操作：完成当前批次的测试用例后，使用`Check`工具进行阶段检查.若未通过检查,则基于反馈信息修正测试用例后,直到阶段检查通过为止;若通过检查,则执行下一批次的测试用例实现,或者是使用`Complete`工具进入下一阶段

### RunSkillScript工具使用说明:
- 允许一次性列举多条命令,但每条命令必须独立完整,且必须符合格式要求,例如记录Fail但合理的测试用例时,若有10个Fail但合理的测试用例待记录
- 其他参数值替换为每个测试用例记录内容,只允许使用定义的参数,禁止额外参数,且参数值必须符合上述格式要求,每个参数必须使用单括号括起来
- 使用`RunSkillScript`工具时,若有10条命令要执行,前5条命令行执行正常,成功记录,但第6条命令执行失败时,根据反馈信息修改第6条命令以及后续命令中存在的相同问题,并且使用`RunSkillScript`工具重新执行第6条命令以及后续命令,已经成功的命令不需要重新执行,只需要执行未完成的命令,直至所有命令执行完毕
- **最重要**:{DUT}_bug_analysis.md的修改只能通过`RunSkillScript`工具执行,严禁使用其他tool对该文件进行任何修改操作.


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