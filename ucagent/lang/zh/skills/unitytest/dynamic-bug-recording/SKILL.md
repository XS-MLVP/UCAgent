---
name: dynamic-bug-recording
description: 为失败测试已确认的动态DUT Bug创建规范BG/TC骨架和中央波形引用；不负责Bug判定、波形取证或根因分析。
---

# 动态 Bug 骨架记录

本技能及脚本是可选辅助。

`RunTestCases`只运行已有的真实pytest验证用例，不执行普通Python、临时维护脚本或文档迁移脚本。不得创建伪pytest用例来修改或批量填充Bug文档。脚本存在时只通过`RunSkillScript`执行本技能声明的脚本；直接修改文档时使用文本工具，相同文本出现多次则用`ReplaceStringInFile`的`line_blocks=[[start, end]]`限定到当前Checker阻塞位置，并且一次只处理当前记录的当前字段。

仅在正确测试稳定复现DUT设计缺陷后使用本技能。每个Fail TC都不预设责任方；调用本技能、WaveInfo或创建/更新非零BG之前，必须从规格、独立参考模型或可验证公式推导`specification_expected`，并完成`input | specification_expected | test_expected | actual | classification`对照。不得直接相信模板注释、已有断言、静态候选或可疑RTL；静态候选不能覆盖TC级反证。expected不一致时修正测试并重跑，禁止记录Bug。

expected一致后，必须核对测试激励/driver、API callback、Step、采样边沿、有效条件、响应延迟、fixture、参考模型、复位和环境。CK失败时必须先核对coverage/check function，并继续核对CK predicate、`CovGroup.sample()`执行与采样时机；这些验证问题必须修复并重跑，CK Fail本身不能作为DUT Bug结论。只有全部验证项正确且DUT actual仍违反规格时，才允许继续。调用前还需确认当前报告将该Fail TC关联到目标精确FG/FC/CK路径，并准备非零置信度`BG-*`、精确`TC-tests/...`和简短描述。Fail TC可以成功触发并覆盖关联CK，不能由TC Fail反推CK Fail，也不要求每个Fail TC关联失败CK。阶段结束时，每个保留的Fail TC必须在其报告关联的至少一个CK下进入非零BG；独立地，每个保留的失败CK也必须有同一CK下的真实Fail TC。不能用本技能制造Bug记录。

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'TC-tests/test_adder.py::test_overflow' -BD '完整加法结果被错误截断。'"]
```

脚本从`{OUT}/.TEST_TEMPLATE_IMP_REPORT.json`解析FG/FC/CK，再从`{OUT}/{DUT}_functions_and_checks.md`读取FG/FC/CK的中文可见名称，从测试函数docstring首个非空描述行读取TC名称，并用`BD`生成BG名称。它按Guide_Doc/dut_bug_analysis.md中的第 5.1 节完整标准案例创建固定Markdown层级、BG、TC、`<WAVEFORM-REF>`和八个`<BUG-*>`分析字段。它不创建波形YAML，不调用WaveInfo，也不表示分析完成。

脚本生成的是带`<BUG-TODO>`的未完成骨架。FG/FC/CK/BG/TC行必须保留“具体中文可见名称 + 尖括号标签”，不能只写标签，也不能用“功能组”“功能”“检测点”“动态 Bug”“失败用例”等类型名充当名称。验收单位是完整`FG/FC/CK/BG`路径。同一CK分支内，同一个BG只出现一次：该路径下的全部TC及其`<WAVEFORM-REF>`连续放在BG标题后，八个`<BUG-*>`字段整体放在最后一个TC/引用后；字段开始后不得再追加TC。若同一根因影响不同CK，可在每个CK下复用同一个BG标签，但每个CK作用域的BG路径都必须有该CK关联TC、引用和完整八字段；不能跨CK共享最后一套字段。每个字段先写固定六级中文标题，下一非空行写对应`<BUG-*>`标签，再写正文。后续填写分析正文时不得改用粗体、调整标题级别、交换字段或增加平行章节。八个固定字段必须依次为“Bug 概述、现象与严重度、触发条件与影响、根因分析、源码证据、动态因果链、修复建议、风险与复验”。

随后必须调用最终WaveInfo，并用`ApplyWaveInfoEvidence`在`<WAVEFORM-EVIDENCE>...</WAVEFORM-EVIDENCE>`中创建该TC唯一的`<WAVEFORM-TC-...>`记录。中央记录标题逐字复用TC可见名称并追加“波形”。同一TC关联多个Bug时，对每个BG调用一次Apply工具；中央波形仍只有一份，并在`bug_tags`和`bug_evidence`中列出全部关联。

同一真实pytest节点不会因测试目录相对路径或工作区相对路径等不同前缀成为两个TC。同一CK/BG下只保留一个TC/引用和一个中央记录；若Checker报告`EQUIVALENT_TC_ASSOCIATION_DUPLICATE`，按`keep_test_label`保留原证据，只删除`duplicate_test_label`对应的重复关联和中央记录，不重跑测试、WaveInfo或Apply。

同一CK/BG路径的后续失败TC直接调用`ApplyWaveInfoEvidence`，不要在该CK内复制BG；工具从目标测试函数docstring读取中文可见标题，并把新TC插入首个分析标题之前。若同名BG出现在多个CK下，先用脚本或文本工具建立目标CK下的完整BG/TC路径，再调用`ApplyWaveInfoEvidence(..., checkpoint_path="FG-.../FC-.../CK-...")`选择精确路径。测试源码和docstring必须先存在。技能未启用或脚本不可用时，使用文本编辑工具按相同来源填写具体中文名称，并复现Guide_Doc/dut_bug_analysis.md中的第 5.1 节层级与结构；任务要求和完成标准不变。
