---
name: static-bug-validation
description: 验证静态Bug候选并维护其与已完成动态Bug或BG-NA的LINK-BUG关联。
---

# 静态 Bug 动态验证

逐个验证`{OUT}/{DUT}_static_bug_analysis.md`中的`<BG-STATIC-*>`候选。测试、参考模型、fixture、API、复位、采样或环境问题必须修复为Pass，不能记录成动态Bug。

`unitytest/dynamic-bug-recording`及其`record_dynamic_bug.py`可选用于首个动态BG/TC骨架；缺少该技能时直接使用文本编辑工具，逐字复现`Guide_Doc/dut_bug_analysis.md`第 5.1 节完整标准案例和第 5.2 节骨架中的中文标题、Markdown层级与标签顺序。

新建`test_static_{DUT}_*`时，参考当前工作区已有的普通DUT测试模板，沿用其fixture参数和顺序：`def test_static_{DUT}_xxx(env):`或`def test_static_{DUT}_xxx(env, ref_model):`。真实DUT测试不能改用`mock_dut`；Mock组件独立单元测试不能用于证实静态RTL候选。

`{OUT}/tests/{DUT}_api.py`、fixture、fake DUT和`fc_cover`绑定是已有公共基础设施。默认只新增或修改当前静态验证测试，不修改API/fixture或伪造覆盖组。只有最早traceback和接口契约明确证明基础设施缺陷时才做最小修复。

一次`Step(1)`只推进仿真，不表示请求已接受或结果有效。必须检查API内部是否已经推进或等待，按规格确认ready/valid或等价接受条件、响应latency和有效采样点；无效窗口的单点data mismatch只能继续调查，不能确认Bug。

最终WaveInfo必须提供完整`signal_groups`，覆盖时钟（若有）、相关输入、输出、协议控制和连接静态根因的关键状态/传播信号，viewer显示同一签名集合。中断或重启后保留已验证receipt；普通阶段不因波形变化重写证据，最终记录阶段再完整重放。

确认DUT Bug时：

1. 保留能稳定复现缺陷的正确断言和Fail结果。
2. 在动态文档中创建独立非静态`<BG-NAME-XX>`，不能复用`BG-STATIC-*`。
3. 为每个Fail TC保留一个`<WAVEFORM-REF>`，并在中央`<WAVEFORM-EVIDENCE>`分区保留该TC唯一的confirmed WaveInfo记录。
4. 完成该动态BG的八个分析字段，以及中央记录中该BG对应的`required_signals`、`observed_behavior`和`source_correlation`。
5. 用可选脚本同时更新静态汇总与详细区的LINK：

同一Fail TC证实多个独立动态Bug时，保留不同BG，并对每个精确BG/TC分别调用`ApplyWaveInfoEvidence`；目标BG/TC之外的Bug记录不会被修改，中央仍只有一份波形记录。单独运行当前静态候选用例时不得删除历史TC/BG；最终记录阶段仍需完整测试运行和严格重放。

```text
["unitytest/static-bug-validation", "linkbug.py", "-SBG 'BG-STATIC-001-CIN-OVERFLOW' -LBG 'BG-CIN-OVERFLOW-98'"]
```

一个静态候选关联多个动态Bug时，`-LBG`使用逗号分隔。候选被证明不成立时使用`-LBG 'BG-NA'`。脚本会拒绝不存在或未完成的动态BG。

技能禁用或脚本不可用时，使用文本编辑工具按`Guide_Doc/dut_bug_analysis.md`建立同一动态结构并直接编辑静态汇总和详情中的两处LINK标签，再执行相同验证；不得因为缺少Skill而暂停或降低验收标准。
