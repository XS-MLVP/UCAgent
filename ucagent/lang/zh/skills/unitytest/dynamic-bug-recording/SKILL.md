---
name: dynamic-bug-recording
description: 为已由失败测试确认的动态DUT Bug创建规范BG/TC分析骨架；不用于静态候选记录、Bug判定或波形与根因分析。
---

# 动态 Bug 骨架记录

本技能只提供可选的动态 Bug 骨架脚本。调用前必须已经通过正确测试确认DUT设计缺陷，并取得待记录的非零置信度`BG-*`和精确`TC-tests/...`标签。

使用`RunSkillScript`调用：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'TC-tests/test_adder.py::test_overflow' -BD '完整加法结果被错误截断。'"]
```

脚本从`{OUT}/.TEST_TEMPLATE_IMP_REPORT.json`反查该TC关联的FG/FC/CK，并在`{OUT}/{DUT}_bug_analysis.md`中创建第一份BG/TC、波形占位和八个分析字段。它不判断根因、不调用WaveInfo，也不代表Bug分析已经完成。

脚本不可用或本技能未启用时，按`Guide_Doc/dut_bug_analysis.md`第6.1.1节使用文本编辑工具创建同等骨架，不得暂停任务或降低完成标准。

同一BG的后续失败TC不要再次调用本脚本。应使用`ApplyWaveInfoEvidence`创建兄弟TC并写入真实机器证据，再由LLM完成所有波形语义字段和分析字段。
