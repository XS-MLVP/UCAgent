---
name: static-bug-validation
description: 静态分析Bug验证与动态关联阶段专属技能,用于指导建立静态 Bug 与动态 Bug 的标签级追踪链接
---

# 静态分析Bug验证与动态关联

## 目标

本阶段的目标是逐个处理`{OUT}/{DUT}_static_bug_analysis.md`中的`<LINK-BUG-[BG-TBD]>`占位标签,通过动态测试给出验证结论,并将静态Bug与动态Bug建立稳定的一一或一对多追踪关系.

## 测试参数契约

新建`test_static_{DUT}_*`动态验证测试时，参考当前工作区已有的普通DUT测试模板，沿用其fixture参数和顺序。通常签名为`def test_static_{DUT}_xxx(env):`或`def test_static_{DUT}_xxx(env, ref_model):`。不得自行增加、删除或交换fixture；若Check报告参数契约不符，按其明确要求修正。

- 测试签名中已有`ref_model`时，必须保持为第二个参数，并依据功能规格独立给出预期；不能读取DUT结果生成预期，也不能照抄被怀疑有缺陷的RTL算法。
- DUT与参考模型不一致时，必须先判定参考模型、测试时序、API、fixture或DUT哪一方违反规格。参考模型错误必须修复到Pass，不能被链接成动态DUT Bug。
- 真实DUT验证使用普通DUT测试模板的`env[, ref_model]`参数。`mock_dut`仅用于Mock组件独立单元测试，不能用于证实静态RTL候选。
- 如果静态候选只在Mock错误、Mock回调顺序或验证环境异常下出现，修复基础设施并将候选判为误报；不得创建动态Bug或WaveInfo证据。

本技能提供两个脚本:
- `recordbug.py`: 将新证实的动态Bug按规范写入`{OUT}/{DUT}_bug_analysis.md`
- `linkbug.py`: 根据`<STATIC-BUG-SUMMARY>`、`<STATIC-BUG-DETAILS>`、`<STATIC-BUG-PROGRESS>`固定分区标记，将静态Bug与动态Bug的关联关系回填到`{OUT}/{DUT}_static_bug_analysis.md`；脚本不解析中文标题，旧的仅标题格式不兼容

这两个脚本分工如下:
- `recordbug.py`负责创建或更新动态Bug记录
- `linkbug.py`负责把静态Bug条目下的`<LINK-BUG-[BG-TBD]>`替换成最终结论

也就是说:
- 若当前静态Bug已经有可直接复用的动态Bug记录,可以直接调用`linkbug.py`
- 若当前静态Bug还没有动态Bug记录，必须先调用`recordbug.py`生成骨架，再由LLM填完波形与分析模板，最后另行调用`linkbug.py`

## 执行步骤

### 步骤1: 扫描待验证静态Bug

操作:
- 读取`{OUT}/{DUT}_static_bug_analysis.md`
- 列出所有仍然带有`<LINK-BUG-[BG-TBD]>`的`<BG-STATIC-*>`条目
- 明确每个静态Bug当前对应的:
  - 功能组`<FG-*>`
  - 功能点`<FC-*>`
  - 检测点`<CK-*>`
  - 源码定位`<FILE-*>`

注意:
- 只处理当前确认过的静态Bug,不要一次性随意修改整个文档
- 若某个静态Bug已经是`<LINK-BUG-[BG-NA]>`或已经关联到真实`BG-*`,说明它已经有结论,除非结论有误,否则不要重复处理

### 步骤2: 检查是否已有可复用的动态验证结果

操作:
- 检查`{OUT}/{DUT}_bug_analysis.md`
- 检查已有测试用例,尤其是Fail测试
- 判断当前静态Bug是否已经被某个动态Bug记录证实

判定规则:
- 若已经存在可以直接对应的动态Bug记录,则无需重复补写测试,直接进入步骤5进行链接回填
- 若尚无对应动态Bug记录,则进入步骤3编写或补充动态验证测试

注意:
- “可以直接对应”不是看名字像不像,而是要基于功能点、触发条件、失败现象、源码根因是否一致来判断
- 多个静态Bug允许对应同一个动态Bug
- 一个静态Bug也允许最终对应多个动态Bug

### 步骤3: 编写或补充动态验证测试

操作:
- 针对仍未确认的静态Bug,编写动态验证测试用例
- 测试文件写入`{OUT}/tests/test_{DUT}_static_verify_*.py`
- 测试函数命名格式为`test_static_{DUT}_<BugId>`
- 通过`from {DUT}_api import *`导入env fixture和API
- 若该静态Bug对应明确的`<CK-*>`,则在测试函数起始位置添加功能覆盖标记

注意:
- 测试目标是验证静态分析提出的缺陷是否真实存在
- 每个Fail都必须先排除测试代码、断言、预期值、fixture/API、参考模型、复位/时序和环境问题；这些问题必须修复到Pass
- 只有正确测试稳定复现DUT设计缺陷时才保留由正确断言自然触发的Fail，并完成非零置信度动态Bug和WaveInfo证据；本阶段已实现的验证测试禁止assert False和BG-*-0占位。此限制不影响create_test_case_templates阶段要求空模板使用assert False
- 不允许为了让测试通过而修改断言或弱化测试
- 若某个静态Bug本身是误报,则测试结果应支持其为误报的结论

### 步骤4: 形成动态Bug结论并写入动态Bug文档

操作:
- 运行动态验证测试
- 结合测试结果、功能预期、源码分析形成结论
- 运行或重跑测试时，在失败日志中打印`cycle_basis`、transaction ID、相关输入输出pin、握手/状态、expected和actual
- 调用波形前阅读测试使用的API/driver、callback和`Step`顺序，确认输入驱动边沿、请求接受条件和输出有效窗口；ready/valid只是常见形式，也可能是req/ack、enable、start/busy、固定延迟或其他自定义协议
- 一次`Step(1)`只推进仿真，不能证明请求已经接受或结果已经有效。检查API内部是否已经Step/等待，并按规格要求的采样边沿、固定N周期、`out_valid/done/ack`或`busy`条件读取结果；过早断言属于测试时序问题，不得用于证实静态Bug
- 对合理且稳定的Fail用例真实调用`WaveInfo`，使用结构化pattern确认失败事务的输入、实际握手/接受条件、状态、响应有效条件和错误输出
- `WaveInfo`匹配到事件不等于确认Bug。LLM必须审查backpressure/stall、pipeline或响应latency和事务归属；`valid/enable=0`、`ready/accept=0`、复位/空闲/过渡周期、尚未到响应latency或协议声明data无效时的单点data mismatch只能作为调查线索。若静态候选本身涉及busy期间拒绝请求等语义，应依据规格明确判断该输入是否应被接受

结论分为两类:

1. Bug已证实
- 在`{OUT}/{DUT}_bug_analysis.md`中补充完整动态Bug记录
- 动态Bug标签形如`BG-XXX-90`
- 动态Bug标签严禁使用`BG-STATIC-*`命名；`<BG-STATIC-*>`标签只保留在`{OUT}/{DUT}_static_bug_analysis.md`
- 每个动态`<BG-*>/<TC-*>`必须有真实WaveInfo收据支持的`status: confirmed`波形证据；YAML围栏后的第一条非空内容必须是同一次最终WaveInfo返回的`bug_document_viewer_link`，并保留`<WAVEFORM-VIEWER>`标记及`/surfer/?wave=` URL
- 中断或重启后可以复用通过验证的WaveInfo receipt；单独运行当前静态候选用例时，不得据此删除已有TC/BG、手工改写有效receipt或重造viewer链接。最终记录阶段仍需完整测试运行和严格波形重放
- `recordbug.py`只生成带`<BUG-TODO>`的动态Bug骨架，不做根因判断，也不生成真实波形字段。运行后必须由LLM读取失败日志、WaveInfo timeline和RTL，直接填完该BG内的全部标记字段
- 若一个静态Bug对应多个动态Bug,则应先把这些动态Bug都记录完整

2. 静态分析误报
- 不在`bug_analysis.md`中新增虚假的动态Bug
- 该静态Bug在`static_bug_analysis.md`中的关联标签应改为`BG-NA`

注意:
- 先有动态Bug记录,再回填静态Bug链接
- 不能先把静态Bug链接改掉,再回头补`bug_analysis.md`
- `WaveInfo`找不到波形时，使用其诊断检查测试名、最新session、`.dat`/`.fst`、`SetWaveform`和`dut.Finish()`，修复后重跑；`status: unavailable`不能作为已证实动态Bug的最终证据
- 测试日志cycle与wavekit wave step可能相差0到数个周期，必须通过指定时钟的occurrence index和事务上下文对齐，不能直接相减
- `alignment_evidence`必须说明测试如何驱动、事务按什么条件接受、输出何时有效以及为何属于失败事务；`observed_behavior`只能在协议允许的响应/采样窗口比较expected与actual。该语义由LLM结合规格、测试和RTL审查，不能交给Checker按特定信号名推断

当Bug已证实时，先使用`RunSkillScript`执行`recordbug.py`生成骨架：

```bash
python3 script -BG 'BG-ADD-SPECIAL-VALUE-90' -TC 'TC-unity_test/tests/test_ALU754_arithmetic.py::test_add_special' -BD '+INF 与 -INF 相加时未返回 NaN，而是错误输出 0x00000000。'
```

其中:
- `script`替换为`recordbug.py`脚本路径
- `-BG`是动态Bug标签
- `-BG`不能是`BG-STATIC-*`；例如静态标签`BG-STATIC-007-OVERFLOW`被动态证实后，应另取`BG-MUL-OVERFLOW-THRESHOLD-85`
- `-TC`是用于证实该Bug的失败测试用例标签
- `-BD`是Bug简述
- 不存在`-ROOT/-FILE/-FIX`参数；旧命令会被拒绝

注意:
- `recordbug.py`只把未完成骨架写入`{OUT}/{DUT}_bug_analysis.md`
- 脚本返回后必须继续：用真实`bug_document_fields`替换每个TC后的波形YAML占位块，并用同一结果的`bug_document_viewer_link`整行替换紧随围栏的链接占位；链接`[...]`中的展示文字可改，但不得修改`<WAVEFORM-VIEWER>`、URL或token，也不得手工构造token。随后读取RTL并用文本编辑工具替换所有`<BUG-TODO>`及其提示文字；完成Bug概述、现象与等级、触发条件与影响范围、根因分析、源码证据与逐行分析、动态因果链、修复建议、风险与复验计划。Checker不解析自然语言占位词。有源码时三个`<BUG-SOURCE-*>`因果标签必须位于完整HDL fenced代码块内；无源码时使用`<BUG-SOURCE-UNAVAILABLE>`完成黑盒分析，两个分支互斥
- 八个字段由固定顺序的独立行标记定义：`<BUG-OVERVIEW>`、`<BUG-SYMPTOMS>`、`<BUG-TRIGGER>`、`<BUG-ROOT-CAUSE>`、`<BUG-SOURCE-EVIDENCE>`、`<BUG-CAUSAL-CHAIN>`、`<BUG-FIX>`、`<BUG-RETEST>`。只填标记之间的内容，禁止删除、复制、改名或调换标记；中文粗体标题只是可本地化的展示文字，Checker和脚本不解析标题。旧的仅标题格式不兼容
- 有源码时必须写真实`path:L1-L2`、HDL代码块，以及各出现一次的`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`；无源码时在`<BUG-SOURCE-EVIDENCE>`字段中加入独立行`<BUG-SOURCE-UNAVAILABLE>`并完成黑盒因果分析
- 仍有占位符或缺少任一标记字段时，动态Bug记录未完成，不能调用`linkbug.py`、`Check`或`Complete`
- `linkbug.py`在写回真实`BG-*`前，会检查这些`BG-*`是否存在、八个标记是否唯一且有序、字段是否非空、是否残留占位符以及是否已有`status: confirmed`波形块
- 因此，若`recordbug.py`尚未执行或骨架尚未填完，`linkbug.py`都会拒绝把`BG-*`写回静态报告

### 步骤5: 使用脚本回填静态Bug链接

操作:
- 当某个静态Bug已经确定最终对应的动态Bug标签后,使用`RunSkillScript`执行`linkbug.py`
- 该脚本会同步更新两个位置:
  - `<STATIC-BUG-SUMMARY>`分区表格中的“动态Bug关联”列
  - `<STATIC-BUG-DETAILS>`分区中该`<BG-STATIC-*>`条目下的`<LINK-BUG-[...]>`标签
- 三个静态分区标记必须各自独占一行、恰好出现一次，并保持`<STATIC-BUG-SUMMARY>` -> `<STATIC-BUG-DETAILS>` -> `<STATIC-BUG-PROGRESS>`顺序；标题文字可以本地化，脚本不会读取标题

命令格式如下:

```bash
python3 script -SBG 'BG-STATIC-001-XXX' -LBG 'BG-ADD-XXX-90'
python3 script -SBG 'BG-STATIC-002-YYY' -LBG 'BG-NA'
python3 script -SBG 'BG-STATIC-003-ZZZ' -LBG 'BG-FSM-DEAD-92,BG-FSM-DEFAULT-85'
```

其中:
- `script`替换为`linkbug.py`脚本路径
- `-SBG`表示`static_bug_analysis.md`中原始静态Bug标签,必须是`BG-STATIC-*`
- `-LBG`表示要写回的链接目标:
  - 若Bug已证实,填写一个或多个真实动态Bug标签`BG-*`
  - 若静态Bug是误报,填写`BG-NA`
  - 若有多个动态Bug,使用英文逗号`,`分隔,脚本会写成`<LINK-BUG-[BG-1][BG-2]>`

执行`linkbug.py`前,脚本会做以下校验:
- `-SBG`必须真实存在于`{OUT}/{DUT}_static_bug_analysis.md`的汇总表和详细分析中
- 若`-LBG`不是`BG-NA`,则其中每个动态Bug标签都必须真实存在于`{OUT}/{DUT}_bug_analysis.md`
- 若任一校验失败,脚本会报错并停止,不会修改静态报告

### 步骤6: 检查替换结果

操作:
- 执行脚本后,重新检查目标静态Bug对应的两个位置是否已一致更新:
  - 汇总表的最后一列
  - 详细分析中的`<LINK-BUG-[...]>`

注意:
- 这两个位置必须完全一致
- 若脚本报错,根据报错修正参数后重试
- 已成功回填的静态Bug不需要重复执行

### 步骤7: 完成阶段收尾

操作:
- 重复步骤1到步骤6,直到所有`<LINK-BUG-[BG-TBD]>`都被替换
- 确认阶段结束时:
  - `static_bug_analysis.md`中不再存在任何`<LINK-BUG-[BG-TBD]>`
  - 所有已证实静态Bug都能在`bug_analysis.md`中找到对应动态Bug记录
  - 所有误报静态Bug都被标记为`BG-NA`

## 核心原则

- 1.**先验证,后回填**: 先确认动态验证结论,再更新静态Bug链接
- 2.**只改链接,不改Bug主体**: `linkbug.py`只修改指定静态Bug的链接标签与汇总表关联列,不改动其余正文
- 3.**两处同步**: 汇总表和详细分析中的链接结果必须保持一致
- 4.**真实关联**: 只有在`bug_analysis.md`中已有完整记录的动态Bug,才能写回真实`BG-*`
- 5.**误报显式标记**: 误报必须写为`BG-NA`,不能保留`BG-TBD`
- 6.**先记动态Bug,再回填静态Bug**: 新发现的动态Bug必须先通过`recordbug.py`写入`bug_analysis.md`,再通过`linkbug.py`建立关联
- 7.**两阶段写入**: 新增BG/TC结构必须通过`recordbug.py`；随后必须用文本编辑工具填完该BG的波形和分析模板。`static_bug_analysis.md`中的链接回填仍必须通过`linkbug.py`
- 8.**动态证据必需**: 非零置信度动态Bug必须有Fail测试和可重放的confirmed WaveInfo证据；波形暂不可用时不能完成该Bug记录

## 关键规则

- `-SBG`必须是`BG-STATIC-*`格式
- `-BG`和`-LBG`表示动态Bug标签，禁止使用`BG-STATIC-*`格式
- `-LBG`必须是以下两种之一:
  - 单个`BG-*`
  - 多个`BG-*`用英文逗号分隔
  - 或者`BG-NA`
- 汇总表中写入格式为:
  - `LINK-BUG-[BG-XXX-90]`
  - `LINK-BUG-[BG-XXX-90][BG-YYY-85]`
  - `LINK-BUG-[BG-NA]`
- 详细分析中写入格式为:
  - `<LINK-BUG-[BG-XXX-90]>`
  - `<LINK-BUG-[BG-XXX-90][BG-YYY-85]>`
  - `<LINK-BUG-[BG-NA]>`
- 一个`<BG-STATIC-*>`条目下应当只有一个`<LINK-BUG-[...]>`标签
- 若脚本发现目标静态Bug不存在,或者该条目下没有唯一可替换的`LINK-BUG`标签,必须报错并停止
- 若`-LBG`为真实动态Bug标签,则这些标签必须先存在于`bug_analysis.md`

## `RunSkillScript`使用说明

1. 允许一次输入多条同类命令：可以批量执行若干`recordbug.py`生成骨架；填充模板后，再单独批量执行对应的`linkbug.py`。不能在同一次`RunSkillScript`调用中跳过LLM填空而从record直接link
2. 若前几条命令执行成功,后续某条失败,只需要修正失败命令以及其后未执行完成的命令,不需要重复执行已成功命令
3. 参数值必须使用单引号包裹,尤其是`-LBG`中有逗号时更需要加引号
4. 若一个静态Bug最终对应多个动态Bug,多个BG标签必须在同一条命令的`-LBG`里一次性给出
5. 若本轮需要新建动态Bug记录，强制顺序是:
   - 先执行`recordbug.py`
   - 再由LLM用文本编辑工具填完真实WaveInfo和全部分析章节
   - 确认无占位符后，另行执行`linkbug.py`

## 示例

### 示例1: 证实为单个动态Bug

```bash
python3 recordbug.py -BG 'BG-MUL-OVERFLOW-THRESHOLD-85' -TC 'TC-unity_test/tests/test_ALU754_arithmetic.py::test_mul_overflow' -BD '最大规格化数乘以 2.0 时未拉高 overflow，也未输出 +INF。'
# 填完该BG的WaveInfo证据和全部分析章节后，才能执行下一条linkbug.py
python3 script -SBG 'BG-STATIC-007-OVERFLOW-THRESHOLD' -LBG 'BG-MUL-OVERFLOW-THRESHOLD-85'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-TBD]` -> `LINK-BUG-[BG-MUL-OVERFLOW-THRESHOLD-85]`
- 详细分析:
  - `<LINK-BUG-[BG-TBD]>` -> `<LINK-BUG-[BG-MUL-OVERFLOW-THRESHOLD-85]>`

### 示例2: 判定为误报

```bash
python3 script -SBG 'BG-STATIC-003-DENORMAL-LOSS' -LBG 'BG-NA'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-TBD]` -> `LINK-BUG-[BG-NA]`
- 详细分析:
  - `<LINK-BUG-[BG-TBD]>` -> `<LINK-BUG-[BG-NA]>`

### 示例3: 对应多个动态Bug

```bash
python3 recordbug.py -BG 'BG-FSM-DEAD-92' -TC 'TC-unity_test/tests/test_demo.py::test_static_demo_1' -BD '第一个动态Bug描述'
python3 recordbug.py -BG 'BG-FSM-DEFAULT-85' -TC 'TC-unity_test/tests/test_demo.py::test_static_demo_2' -BD '第二个动态Bug描述'
# 分别填完两个BG的WaveInfo证据和全部分析章节后，再建立静态链接
python3 script -SBG 'BG-STATIC-020-FSM-ISSUE' -LBG 'BG-FSM-DEAD-92,BG-FSM-DEFAULT-85'
```

替换效果:
- 汇总表:
  - `LINK-BUG-[BG-FSM-DEAD-92][BG-FSM-DEFAULT-85]`
- 详细分析:
  - `<LINK-BUG-[BG-FSM-DEAD-92][BG-FSM-DEFAULT-85]>`
