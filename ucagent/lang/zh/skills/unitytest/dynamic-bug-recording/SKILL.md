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

脚本从`{OUT}/.TEST_TEMPLATE_IMP_REPORT.json`解析FG/FC/CK，在`<DYNAMIC-BUGS>...</DYNAMIC-BUGS>`内创建BG、TC、`<WAVEFORM-REF>`和八个`<BUG-*>`分析字段。它不创建波形YAML，不调用WaveInfo，也不表示分析完成。

随后必须调用最终WaveInfo，并用`ApplyWaveInfoEvidence`在`<WAVEFORM-EVIDENCE>...</WAVEFORM-EVIDENCE>`中创建该TC唯一的`<WAVEFORM-TC-...>`记录。同一TC关联多个Bug时，对每个BG调用一次Apply工具；中央波形仍只有一份，并在`bug_tags`和`bug_evidence`中列出全部关联。

同一BG的后续失败TC直接调用`ApplyWaveInfoEvidence`，不要复制BG。技能未启用或脚本不可用时，按`Guide_Doc/dut_bug_analysis.md`使用文本编辑工具建立相同标签骨架；任务要求和完成标准不变。
