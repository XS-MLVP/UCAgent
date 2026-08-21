---
name: dynamic-bug-recording
description: 为失败测试已确认的动态DUT Bug创建规范BG/TC骨架和中央波形引用；不负责Bug判定、波形取证或根因分析。
---

# 动态 Bug 骨架记录

本技能及脚本是可选辅助。

仅在正确测试稳定复现DUT设计缺陷后使用本技能。调用前准备非零置信度`BG-*`、精确`TC-tests/...`和简短描述。

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'TC-tests/test_adder.py::test_overflow' -BD '完整加法结果被错误截断。'"]
```

脚本从`{OUT}/.TEST_TEMPLATE_IMP_REPORT.json`解析FG/FC/CK，再从`{OUT}/{DUT}_functions_and_checks.md`读取FG/FC/CK的中文可见名称，从测试函数docstring首个非空描述行读取TC名称，并用`BD`生成BG名称。它按`Guide_Doc/dut_bug_analysis.md`第 5.1 节完整标准案例创建固定Markdown层级、BG、TC、`<WAVEFORM-REF>`和八个`<BUG-*>`分析字段。它不创建波形YAML，不调用WaveInfo，也不表示分析完成。

脚本生成的是带`<BUG-TODO>`的未完成骨架。FG/FC/CK/BG/TC行必须保留“具体中文可见名称 + 尖括号标签”，不能只写标签，也不能用“功能组”“功能”“检测点”“动态 Bug”“失败用例”等类型名充当名称。同一BG的全部TC及其`<WAVEFORM-REF>`连续放在BG标题后，八个`<BUG-*>`字段整体放在最后一个TC/引用后；字段开始后不得再追加TC。后续填写分析正文时不得改用粗体、调整标题级别、交换字段或增加平行章节。八个固定字段必须依次为“Bug 概述、现象与严重度、触发条件与影响、根因分析、源码证据、动态因果链、修复建议、风险与复验”。

随后必须调用最终WaveInfo，并用`ApplyWaveInfoEvidence`在`<WAVEFORM-EVIDENCE>...</WAVEFORM-EVIDENCE>`中创建该TC唯一的`<WAVEFORM-TC-...>`记录。中央记录标题逐字复用TC可见名称并追加“波形”。同一TC关联多个Bug时，对每个BG调用一次Apply工具；中央波形仍只有一份，并在`bug_tags`和`bug_evidence`中列出全部关联。

同一BG的后续失败TC直接调用`ApplyWaveInfoEvidence`，不要复制BG；工具从目标测试函数docstring读取中文可见标题，并把新TC插入`<BUG-OVERVIEW>`之前，因此测试源码和docstring必须先存在。技能未启用或脚本不可用时，使用文本编辑工具按相同来源填写具体中文名称，并复现Guide第 5.1 节的层级与结构；任务要求和完成标准不变。
