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
- `{OUT}/tests/{DUT}_api.py`及其fixture、fake DUT和`fc_cover`绑定是已有公共基础设施。默认只新增或修改当前静态验证测试；不得为了让`mark_function`或覆盖率门禁通过而改写API模板、替换fixture或伪造覆盖组。只有最早traceback和接口契约明确证明公共基础设施缺陷时，才允许做最小修复并重跑其专用检查。

本技能提供两个可选的批量脚本；没有`RunSkillScript`时，所有步骤都可以使用内置文本编辑工具完成:
- `recordbug.py`: 将新证实的动态Bug按规范写入`{OUT}/{DUT}_bug_analysis.md`
- `linkbug.py`: 根据`<STATIC-BUG-SUMMARY>`、`<STATIC-BUG-DETAILS>`、`<STATIC-BUG-PROGRESS>`固定分区标记，将静态Bug与动态Bug的关联关系回填到`{OUT}/{DUT}_static_bug_analysis.md`；脚本不解析中文标题，旧的仅标题格式不兼容

这两个可选脚本分工如下:
- `recordbug.py`负责创建或更新动态Bug记录
- `linkbug.py`负责把静态Bug条目下的`<LINK-BUG-[BG-TBD]>`替换成最终结论

也就是说:
- 若当前静态Bug已经有可直接复用的动态Bug记录，可以直接用文本编辑工具同步回填两处LINK；`linkbug.py`可用时也可执行相同操作
- 若当前静态Bug还没有动态Bug记录，默认使用文本编辑工具按Guide第6.1.1节最小骨架示例建立结构；`recordbug.py`可用时可改用它生成相同骨架。随后用`ApplyWaveInfoEvidence`写入最终receipt的机器字段并由LLM填完语义分析，最后用文本编辑工具或可选`linkbug.py`同步回填LINK

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
- 最终WaveInfo调用必须提供完整`signal_groups`：时序DUT的实际时钟（组合DUT明确声明`combinational`）、与静态候选相关的输入数据/控制、输出数据/状态/有效位、真实协议接受/响应控制，以及至少一个能连接静态源码根因和接口错误的关键内部/状态信号；这些精确路径必须全部进入timeline、签名receipt和在线viewer，禁止只查看目标data
- `pattern`只负责定位事件，不能为了显示上下文把所有必要信号都设为`change`；`signal_groups.protocol`仅在接口确实没有ready/valid/enable/start/busy/done/ack等控制时可为空。信号语义仍由LLM结合规格、API/driver和RTL审查，不由Checker按名字猜测
- `WaveInfo`匹配到事件不等于确认Bug。LLM必须审查backpressure/stall、pipeline或响应latency和事务归属；`valid/enable=0`、`ready/accept=0`、复位/空闲/过渡周期、尚未到响应latency或协议声明data无效时的单点data mismatch只能作为调查线索。若静态候选本身涉及busy期间拒绝请求等语义，应依据规格明确判断该输入是否应被接受

结论分为两类:

1. Bug已证实
- 在`{OUT}/{DUT}_bug_analysis.md`中补充完整动态Bug记录
- 动态Bug标签形如`BG-XXX-90`
- 动态Bug标签严禁使用`BG-STATIC-*`命名；`<BG-STATIC-*>`标签只保留在`{OUT}/{DUT}_static_bug_analysis.md`
- 每个动态`<BG-*>/<TC-*>`必须有真实WaveInfo收据支持的`status: confirmed`波形证据；证据的`signal_groups`和在线viewer必须完整展示时钟（若有）、相关输入、相关输出、协议控制和功能关键路径。YAML与其后的`<WAVEFORM-VIEWER>`链接必须由`ApplyWaveInfoEvidence`从同一个最终receipt直接写入
- 同一动态Bug有多个Fail TC时，将它们保留在同一个BG条目中，并对每个TC分别调用一次`ApplyWaveInfoEvidence`：复用相同`bug_tag`，更换`test_case_tag`和`receipt_id`。BG位置唯一时工具会自动创建尚不存在的兄弟TC；不要重复生成或手工复制BG/TC。兄弟TC不会互相覆盖，也不需要`replace_existing=true`
- 同一Fail TC证实多个独立动态Bug时，为每个根因保留不同BG，并用相同`test_case_tag`分别调用`ApplyWaveInfoEvidence`；目标BG/TC之外的Bug记录不会被修改。只有签名窗口和`signal_groups`都能支持各Bug时才能跨BG复用同一receipt，跨BG应用不需要`replace_existing=true`
- 中断或重启后可以复用通过验证的WaveInfo receipt；单独运行当前静态候选用例时，不得据此删除已有TC/BG、手工改写有效receipt或重造viewer链接。最终记录阶段仍需完整测试运行和严格波形重放
- `recordbug.py`只生成带`<BUG-TODO>`的动态Bug骨架，不做根因判断，也不生成真实波形字段。最终WaveInfo调用后必须使用`ApplyWaveInfoEvidence`写入机器证据，再由LLM读取失败日志、timeline和RTL，填完该BG内的三个语义结论及全部分析标记字段
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

当Bug已证实时，先按Guide第6.1.1节使用文本编辑工具生成骨架；若`RunSkillScript`可用，也可以执行`recordbug.py`生成相同骨架：

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
- 骨架建立并取得最终WaveInfo receipt后必须继续：调用`ApplyWaveInfoEvidence(target_file=..., bug_tag=..., test_case_tag=..., receipt_id=...)`，由工具替换每个TC后的波形YAML和紧随围栏的viewer链接占位；不得让LLM复制`bug_document_fields`、URL或token。随后读取RTL并用文本编辑工具替换三个YAML语义字段及其他所有`<BUG-TODO>`和提示文字；完成Bug概述、现象与等级、触发条件与影响范围、根因分析、源码证据与逐行分析、动态因果链、修复建议、风险与复验计划。Checker不解析自然语言占位词。有源码时三个`<BUG-SOURCE-*>`因果标签必须位于完整HDL fenced代码块内；无源码时使用`<BUG-SOURCE-UNAVAILABLE>`完成黑盒分析，两个分支互斥。目标已有不同真实receipt时，只有确认旧证据需要被取代才传`replace_existing=true`，并按新波形重写三个语义字段
- 八个字段由固定顺序的独立行标记定义：`<BUG-OVERVIEW>`、`<BUG-SYMPTOMS>`、`<BUG-TRIGGER>`、`<BUG-ROOT-CAUSE>`、`<BUG-SOURCE-EVIDENCE>`、`<BUG-CAUSAL-CHAIN>`、`<BUG-FIX>`、`<BUG-RETEST>`。只填标记之间的内容，禁止删除、复制、改名或调换标记；中文粗体标题只是可本地化的展示文字，Checker和脚本不解析标题。旧的仅标题格式不兼容
- 有源码时必须写真实`path:L1-L2`、HDL代码块，以及各出现一次的`<BUG-SOURCE-FIRST-ERROR>`、`<BUG-SOURCE-PROPAGATION>`、`<BUG-SOURCE-OBSERVABLE>`；无源码时在`<BUG-SOURCE-EVIDENCE>`字段中加入独立行`<BUG-SOURCE-UNAVAILABLE>`并完成黑盒因果分析
- 仍有占位符或缺少任一标记字段时，动态Bug记录未完成，不能回填最终LINK、调用`Check`或`Complete`
- 写回真实`BG-*`前，必须确认这些`BG-*`存在、八个标记唯一且有序、字段非空、没有占位符，并已有`status: confirmed`波形块；可选`linkbug.py`会执行同样校验
- 因此，动态骨架尚未建立或尚未填完时，不得把真实`BG-*`写回静态报告

### 步骤5: 回填静态Bug链接

操作:
- 当某个静态Bug已经确定最终对应的动态Bug标签后，对已有报告使用`ReplaceStringInFile(path, old_string, new_string)`同步更新两个位置；若`RunSkillScript`可用，也可执行`linkbug.py`完成相同更新:
  - `<STATIC-BUG-SUMMARY>`分区表格中的“动态Bug关联”列
  - `<STATIC-BUG-DETAILS>`分区中该`<BG-STATIC-*>`条目下的`<LINK-BUG-[...]>`标签
- 三个静态分区标记必须各自独占一行、恰好出现一次，并保持`<STATIC-BUG-SUMMARY>` -> `<STATIC-BUG-DETAILS>` -> `<STATIC-BUG-PROGRESS>`顺序；标题文字可以本地化，Checker不会读取标题

可选脚本命令格式如下:

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

直接编辑或执行`linkbug.py`前，都要做以下校验:
- `-SBG`必须真实存在于`{OUT}/{DUT}_static_bug_analysis.md`的汇总表和详细分析中
- 若`-LBG`不是`BG-NA`,则其中每个动态Bug标签都必须真实存在于`{OUT}/{DUT}_bug_analysis.md`
- 若任一校验失败，不得修改静态报告；可选脚本会报错并停止

### 步骤6: 检查替换结果

操作:
- 编辑或执行脚本后,重新检查目标静态Bug对应的两个位置是否已一致更新:
  - 汇总表的最后一列
  - 详细分析中的`<LINK-BUG-[...]>`

注意:
- 这两个位置必须完全一致
- 若文本替换或脚本报错,根据具体错误修正目标或参数后重试
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
- 2.**只改链接,不改Bug主体**: 文本编辑或可选`linkbug.py`只修改指定静态Bug的链接标签与汇总表关联列,不改动其余正文
- 3.**两处同步**: 汇总表和详细分析中的链接结果必须保持一致
- 4.**真实关联**: 只有在`bug_analysis.md`中已有完整记录的动态Bug,才能写回真实`BG-*`
- 5.**误报显式标记**: 误报必须写为`BG-NA`,不能保留`BG-TBD`
- 6.**先记动态Bug,再回填静态Bug**: 新发现的动态Bug必须先通过文本编辑工具或可选`recordbug.py`写入并完成`bug_analysis.md`,再通过文本编辑工具或可选`linkbug.py`建立关联
- 7.**两阶段写入**: 新增BG/TC结构可通过文本编辑工具按Guide骨架示例完成，也可使用可选`recordbug.py`；随后必须用`ApplyWaveInfoEvidence`写入波形机器字段，再用文本编辑工具填完该BG的语义分析模板。`static_bug_analysis.md`中的链接可直接同步编辑，`linkbug.py`只是可选助手
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
- 若目标静态Bug不存在,或者该条目下没有唯一可替换的`LINK-BUG`标签,必须停止修改并先修复结构
- 若`-LBG`为真实动态Bug标签,则这些标签必须先存在于`bug_analysis.md`

## 可选`RunSkillScript`使用说明

1. 允许一次输入多条同类命令：可以批量执行若干`recordbug.py`生成骨架；填充模板后，再单独批量执行对应的`linkbug.py`。不能在同一次`RunSkillScript`调用中跳过LLM填空而从record直接link
2. 若前几条命令执行成功,后续某条失败,只需要修正失败命令以及其后未执行完成的命令,不需要重复执行已成功命令
3. 参数值必须使用单引号包裹,尤其是`-LBG`中有逗号时更需要加引号
4. 若一个静态Bug最终对应多个动态Bug,多个BG标签必须在同一条命令的`-LBG`里一次性给出
5. 若本轮需要新建动态Bug记录，使用文本编辑工具或可选脚本时都必须保持以下顺序:
   - 先创建动态Bug骨架（直接编辑或执行`recordbug.py`）
   - 再由LLM用文本编辑工具填完真实WaveInfo和全部分析章节
   - 确认无占位符后，再同步编辑两处LINK或另行执行`linkbug.py`

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
