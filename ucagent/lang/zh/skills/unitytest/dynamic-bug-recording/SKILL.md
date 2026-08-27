---
name: dynamic-bug-recording
description: 为正确失败测试确认的动态DUT Bug优先确定性维护BG、TC、ROOT和波形引用；支持幂等重复调用、受控格式恢复与跨阶段累计。
---

# 动态 Bug 确定性记录

Skill启用且本公共Skill可用时，优先通过本技能声明的`record_dynamic_bug.py`以及内置`WaveInfo`、`ApplyWaveInfoEvidence`维护已确认动态DUT Bug，避免主动用文本工具编辑`{OUT}/{DUT}_bug_analysis.md`。脚本以原子替换方式维护Markdown结构；同一命令可幂等重试，也可在后续stage继续追加新的精确路径、TC、BG或ROOT关联。若脚本不能恢复已有文档的格式损坏，可按下述受控兜底只修复诊断指出的最小范围。这个编辑偏好只针对动态Bug文档；其他文档和代码仍使用当前stage允许的普通工具。

本Skill是`general_skill_list`中的公共可选加速路径，全阶段可发现，不属于任何stage的强制`skill_list`，不调用`SetSkillUsage`。Skill整体禁用、公共Skill未配置，或工作区未复制`.ucagent/skills`时，仍按stage task、Guide_Doc/dut_bug_analysis.md中的第 5.1 节（section 5.1）和内置文本编辑工具完成完全相同的规范产物；Skill缺失不得暂停、跳过Bug记录或降低证据标准。

`{OUT}/{DUT}_bug_analysis.md`是跨阶段累计文档；当前报告可能只是局部报告。历史TC/BG/ROOT和中央波形必须保留，缺少当前报告的TC不代表它已Pass或失效。同名BG/TC在不同CK下不等价，路径验收单位始终是完整`FG/FC/CK/BG`；一个TC的中央波形仍只有一份。

## 进入条件

每个Fail TC都不预设责任方。调用脚本、WaveInfo或创建/更新非零BG之前，必须从规格、独立参考模型或可验证公式推导`specification_expected`，完成`input | specification_expected | test_expected | actual | classification`对照，并核对测试激励、API/driver、callback、Step、采样边沿、有效条件、响应延迟、fixture、参考模型、复位、环境、CK predicate、`CovGroup.sample()`及采样时机。不得直接相信已有断言、可疑RTL或静态候选，静态候选不能覆盖TC级反证。验证问题必须修复到Pass；只有正确测试仍稳定复现DUT违反规格时才记录Bug。

CK失败时必须先核对coverage/check function、predicate和sample时机；CK Fail本身不能作为DUT Bug结论，不得把当前Pass用例改成Fail来满足门禁。输入变换时按真实驱动值和规格重算expected，`a+(~b)+0`是`a-b-1`。验收单位是完整`FG/FC/CK/BG`路径；不同路径不等价，不要求每个Fail TC关联失败CK。

在记录前还要核对测试激励/driver、API callback、Step顺序、复位和响应有效窗口，确认Fail不是验证基础设施问题。

当前Fail必须分类。无Bug分支的完成条件是验证问题均已修复到Pass且没有正确测试稳定复现DUT缺陷；此时不运行本脚本、不调用WaveInfo或Apply，也不新增BG、TC、ROOT或波形占位。累计文档已有历史记录时保持原状；累计文档从未记录Bug时保留规范标题和三个空容器。公共Skill没有使用证据门禁：无Bug时直接继续当前stage的`Check`/`Complete`，有确认Bug时执行下述方法后再`Check`。

## 固定工作流

1. 运行当前stage的真实测试并取得当前报告。`record_dynamic_bug.py`只读取`.ucagent/runtime_config.json`中的`test_output_dir`和`current_test_report`，并将解析出的`test_output_dir`作为本次实际TC输出目录；报告缺失时重新运行当前stage真实测试，禁止创建、复制或修改报告。
2. 如果脚本、Check或Complete报告ROOT容器、关闭标记或ROOT/BG反向关系异常，先调用`["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-MODE repair"]`。`repair`不读取当前测试报告、不接受任何Bug/ROOT语义参数，只依据每个BG唯一的`<CAUSE-REF-ROOT-*>`重建ROOT反向关系，删除不受支持的`</RELATED-BUGS>`和`</ROOT>`，拆分粘连的`</ROOT-CAUSES>`，并保留全部BG/TC/ROOT分析正文和中央波形。若返回失败，先按`next_action`执行一次对应语义MODE并重调`repair`。只有相同文档阻塞仍存在、或结构损坏使该动作无法执行时，才用普通文本工具修复`error/details`指出的精确标记、路径或行；优先遵循返回的`manual_edit_fallback.scope`，保留其他BG、TC、ROOT分析和全部`WAVEFORM-EVIDENCE`内容，不用shell或临时Python。手工修复后立即执行`manual_edit_fallback.after_edit`；未返回该字段时立即重跑`-MODE repair`和`Check`。
3. 对每个新BG路径的第一份精确`FG/FC/CK/BG/TC`关联调用一次`-MODE bug`。命令同时写入三个完整BG字段、唯一ROOT引用和ROOT反向链接，不产生需要手工填写的BG字段；已有CK/BG的后续兄弟TC直接进入步骤5。
4. 对每个不同ROOT调用一次`-MODE root`。该命令一次写入ROOT五个完整字段；同一ROOT关联多个BG时只调用一次或在分析更新后幂等重调，既有反向链接会保留。
5. 使用最终`WaveInfo`取得签名receipt，再对每个精确BG/TC路径调用`ApplyWaveInfoEvidence`。Apply原子维护BG侧`<WAVEFORM-REF>`和TC唯一中央波形记录。
6. 调用`Check`。如果语义内容需要修订，优先使用对应`MODE`重调脚本；如果同一文档格式阻塞在步骤2的恢复后仍存在，执行步骤2的最小文本修复兜底。如果receipt需要修订，按工具返回的恢复调用重调WaveInfo/Apply，不得手工构造或修改机器证据。

`RunTestCases`只运行已有真实pytest用例；本脚本只能通过`RunSkillScript`执行。`RunSkillScript.commands`中的每条命令严格使用`[skill_name, skill_script, args]`三字符串结构。

## 多次调用上下文

新增一条动态Bug不是单次脚本调用。`MODE bug`、必要的`MODE repair`和`MODE root`每次都会返回`workflow_context`；后续调用以这个结构化字段为续跑上下文，不凭记忆重建身份：

- `phase`说明刚完成或被阻塞的阶段；`completed`列出已确定性写入的内容。
- `identity`保存后续调用必须逐字复用的BG、函数级TC、完整checkpoint和ROOT身份。不得换用相似node、同名BG的其他CK或新ROOT标签。
- `next_skill_mode`是下一次脚本模式；`remaining_sequence`给出后续Skill、WaveInfo、Apply和Check的顺序。先完成下一次Skill调用，再执行后续工具，不得跳到Check后反复试错。
- `continuation_rule`始终只约束`{OUT}/{DUT}_bug_analysis.md`。其他文档和代码仍按当前stage正常编辑。

`MODE repair`成功后，使用`workflow_context.resume_mode`重试此前失败的`MODE bug`或`MODE root`调用；不要因为结构已修复就跳过原本尚未完成的语义字段。脚本失败时保留原有身份，先执行一次`next_action`和`workflow_context.remaining_sequence`；只有步骤2定义的文档恢复条件成立时才做最小文本修复，修复后立即回到Skill恢复流程。

## BG 与 TC

`-MODE bug`的规范调用如下，所有参数均为必填：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-MODE bug -BG 'BG-CARRY-DROPPED-95' -TC 'TC-{OUT}/tests/test_{DUT}_carry.py::test_carry' -BD '进位结果丢失' -CHECKPOINT 'FG-ARITHMETIC/FC-ADD/CK-CARRY' -ROOT-TAG 'ROOT-ADDER-CARRY-WIDTH' -ROOT-TITLE '加法进位位宽不足' -OVERVIEW '规格要求完整保留加法进位，实际结果在输出前被截断。' -SYMPTOMS '最大操作数组合稳定返回缺少最高进位位的错误结果，影响所有依赖完整和的功能。' -TRIGGER '两个操作数之和超出结果低位宽度时稳定触发，错误传播到结果断言。'"]
```

- `-TC`逐字使用当前报告的函数级node，只删除文件上的`:start-end`或`:line`，再添加`TC-`；路径必须以runtime config解析出的实际`test_output_dir`开头。
- `-CHECKPOINT`逐字使用当前报告为该TC关联的一个精确`FG/FC/CK`路径。一个TC关联多个Bug路径时逐路径调用，不得让脚本猜测路径。
- `-BG`必须是非`BG-STATIC-*`且置信度大于0的`BG-NAME-XX`。`-BD`是可见标题；三个分析参数只传字段正文，不传Markdown标题、机器标签、ROOT引用、代码围栏或锚点。
- `-ROOT-TAG`使用文档级唯一`ROOT-NAME`。多个BG确属同一根因时使用同一个ROOT标签；组合缺陷使用独立ROOT标签。
- 同一精确路径重复调用会更新BG标题和三个字段，并保留TC、ROOT关系和中央波形。后续stage新增BG路径或修订BG/ROOT关系时重调`MODE bug`；已有CK/BG仅新增兄弟TC时直接调用WaveInfo/Apply。脚本不会因当前局部报告未出现历史TC而删除历史记录。
- 每个 BG 必须且只能有一个根因；ROOT通过内嵌完整FG/FC/CK/BG路径的`<RELATED-BUG-...>`反向关联全部所属BG。需要改变根因划分时，用新的`-ROOT-TAG`重调`MODE bug`，脚本会迁移该路径并清理失效反向链接。

## ROOT

有可访问源码时，`-MODE root`使用规范`path:start-end`和三个真实行号。脚本读取该范围的当前源码，自动生成合法语言围栏，并把三个ROOT源码标记放入对应源码行的原生注释中；LLM不编写fenced block：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-MODE root -ROOT-TAG 'ROOT-ADDER-CARRY-WIDTH' -ROOT-TITLE '加法进位位宽不足' -ANALYSIS '中间结果在赋给输出前按低位宽度截断，最高进位位因此丢失。' -SOURCE-LOCATION 'rtl/adder.sv:24-28' -FIRST-ERROR-LINE 25 -FIRST-ERROR-NOTE '中间结果声明宽度不足，首次丢失最高进位位。' -PROPAGATION-LINE 26 -PROPAGATION-NOTE '截断值直接进入结果赋值路径。' -OBSERVABLE-LINE 27 -OBSERVABLE-NOTE '错误低位结果到达测试检查的输出端口。' -CAUSAL-CHAIN '合法输入被接受后，位宽不足先截断进位，截断值再传到结果输出，最终导致关联TC断言失败。' -FIX '扩大中间结果与输出路径宽度，显式保留进位位，且不改变合法低位运算语义。' -RETEST '重跑全部关联CK、零值、最大值和进位边界用例，并复核输出与内部进位波形。'"]
```

`-SOURCE-LOCATION`必须是workspace相对的`.sv/.svh/.v/.vh/.vhd/.vhdl/.scala`文件，使用不带`L`的`path:start-end`；单行使用`start=start`。三个证据行必须位于该范围内，可以是同一行，但每个说明都必须描述该行承担的真实角色。

无可访问RTL/HDL时，使用互斥的`-SOURCE-UNAVAILABLE`，不要同时传源码位置或行号：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-MODE root -ROOT-TAG 'ROOT-BLACKBOX-RESULT' -ROOT-TITLE '结果路径黑盒缺陷' -ANALYSIS '接口证据将首错范围限定在请求接受后到结果输出之间。' -SOURCE-UNAVAILABLE '当前工作区没有可访问RTL/HDL；规格、失败日志和已确认波形共同限定该黑盒结论。' -CAUSAL-CHAIN '合法请求被接受后，响应有效周期出现稳定错误结果，并被关联TC断言观察。' -FIX '检查请求接受后的状态更新和结果生成逻辑，保持接口时序不变。' -RETEST '重跑关联协议、边界输入和响应时序用例，并复核签名波形。'"]
```

`MODE root`要求目标ROOT已由`MODE bug`建立。重复调用只更新可见标题和五个ROOT字段，保留所有`<RELATED-BUG-...>`反向链接。

## 波形证据

本脚本不生成receipt、波形YAML、viewer URL或token。非参数化WaveInfo只去掉`TC-`并使用完整node；参数化报告从`tests.test_case_instances`选择同一路径、类和函数的实际FAILED child。不同路径、类和函数不等价，inventory和相似节点只供定位/核对，不参与匹配。最终调用提供完整`signal_groups`，随后调用：

```text
ApplyWaveInfoEvidence(target_file="{OUT}/{DUT}_bug_analysis.md", bug_tag="BG-CARRY-DROPPED-95", test_case_tag="TC-{OUT}/tests/test_{DUT}_carry.py::test_carry", receipt_id="RECEIPT_FROM_FINAL_WAVEINFO", checkpoint_path="FG-ARITHMETIC/FC-ADD/CK-CARRY")
```

同一TC关联多个BG时逐BG调用Apply，但中央记录仍只有一份，`bug_tags`、`bug_evidence`和签名`signal_groups`覆盖全部关联。Apply返回`receipt_test_mismatch`或`matching_final_receipt_not_found`时保持函数级`test_case_tag`不变：有`parameterized_receipts`时选择当前报告中的实际FAILED child重新调用最终WaveInfo，否则原样执行`details.recovery_call`一次，再用新receipt重调Apply。禁止手写或复制机器证据。

当同名BG跨CK或目标路径有歧义时，调用`ApplyWaveInfoEvidence(..., checkpoint_path="FG-.../FC-.../CK-...")`选择精确分支。

## 完成条件

每个保留Fail TC都在当前报告关联的至少一个精确CK下具有非零BG；每个仍失败CK也有同一CK下的真实Fail TC。每个BG的三个字段完整且只引用一个ROOT；每个ROOT的五个字段完整并反向关联全部所属BG路径；每个TC紧跟真实`<WAVEFORM-REF>`且只有一份中央confirmed证据。文档中不存在`<BUG-TODO>`，Check通过后直接推进stage；公共Skill不记录stage专用使用状态。
