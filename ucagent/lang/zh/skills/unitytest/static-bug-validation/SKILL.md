---
name: static-bug-validation
description: 验证静态Bug候选并维护其与已完成动态Bug或BG-NA的LINK-BUG关联。
---

# 静态 Bug 动态验证

Markdown 排版契约：本技能生成、维护或展示的任何 Markdown 中，每个 `#` 到 `######` 标题前后各保留一个空行；标题前置空行没有例外：文件开头的标题、Markdown 示例围栏内首个标题和 `<a id="..."></a>` 锚点后的目标标题都必须有前置空行。标题前不得直接连接正文、列表、表格、下一级标题、代码围栏或锚点；字段标题后的规范机器标记（例如 `<BUG-*>`、`<ROOT-*>` 和 `<RELATED-BUGS>`）可以继续与标题紧邻。

逐个验证`{OUT}/{DUT}_static_bug_analysis.md`中的`<BG-STATIC-*>`候选。测试、参考模型、fixture、API、复位、采样或环境问题必须修复为Pass，不能记录成动态Bug。

动态确认结果只写入`{OUT}/{DUT}_bug_analysis.md`，不得根据可见标题派生另一个文件。Markdown、record/Apply和中央YAML `test_case`使用函数级报告node。非参数化WaveInfo使用同一node；报告含`tests.test_case_instances`时，文档TC保持函数级node，WaveInfo选择一个实际FAILED参数化child，且child必须与文档TC具有逐字相同的完整路径/类/函数父节点。不同路径永远不等价。没有确认动态 Bug 时保留三个空容器。

确认DUT Bug后，若公共`unitytest/dynamic-bug-recording`已启用且已复制，优先通过其`record_dynamic_bug.py`的`-MODE bug`写入精确BG/TC路径、三个BG字段、唯一ROOT引用和反向链接，再用`-MODE root`写入ROOT五字段，尽可能不主动编辑动态Bug文档。BG机器锚点、ROOT容器、关闭标记或双向关系异常时调用一次`-MODE repair`重建全部生成式锚点和关系，不得按Checker逐条编辑缺失锚点；执行返回的`next_action`后相同文档格式阻塞仍存在，才按`error/details`或返回的`manual_edit_fallback`最小编辑，并立即重跑`-MODE repair`和Check。公共Skill不调用`SetSkillUsage`。脚本不写波形YAML，仍需真实WaveInfo和Apply；这些机器证据不得手工编辑。Skill缺失、禁用或脚本不可用时使用文本编辑工具，按Guide_Doc/dut_bug_analysis.md中的第 5.1 节完整标准案例填写相同结构。FG/FC/CK名称来自功能检查文档，BG名称来自具体缺陷描述，TC名称来自测试docstring；不能只写尖括号标签或类型名。

新建`test_static_{DUT}_*`时，参考当前工作区已有的普通DUT测试模板，沿用其fixture参数和顺序：`def test_static_{DUT}_xxx(env):`或`def test_static_{DUT}_xxx(env, ref_model):`。真实DUT测试不能改用`mock_dut`；Mock组件独立单元测试不能用于证实静态RTL候选。

静态验证文件必须使用`test_{DUT}_static_verify_<name>.py`，其中每个pytest函数必须以`test_static_{DUT}_`开头。普通定向TC不能冒用`test_static_`，API和随机TC也必须留在对应专用文件中；命名错误应在本阶段一次修正全部函数定义及其`mark_function`引用。

`{OUT}/tests/{DUT}_api.py`、fixture、fake DUT和`fc_cover`绑定是已有公共基础设施。默认只新增或修改当前静态验证测试，不修改API/fixture或伪造覆盖组。只有最早traceback和接口契约明确证明基础设施缺陷时才做最小修复。

一次`Step(1)`只推进仿真，不表示请求已接受或结果有效。必须检查API内部是否已经推进或等待，按规格确认ready/valid或等价接受条件、响应latency和有效采样点；无效窗口的单点data mismatch只能继续调查，不能确认Bug。

最终WaveInfo必须提供完整`signal_groups`，覆盖时钟（若有）、相关输入、输出、协议控制和连接静态根因的关键状态/传播信号，viewer显示同一签名集合。中断或重启后保留已验证receipt；普通阶段不因波形变化重写证据，最终记录阶段完整重放，并由Checker原子刷新语义等价的当前机器证据。TC身份或语义变化时按Checker返回的当前receipt/精确恢复动作复核。

确认DUT Bug时：

1. 保留能稳定复现缺陷的正确断言和Fail结果。
2. 在动态文档中创建独立非静态`<BG-NAME-XX>`，不能复用`BG-STATIC-*`。
3. 为每个Fail TC保留一个`<WAVEFORM-REF>`，并在中央`<WAVEFORM-EVIDENCE>`分区保留该TC唯一的confirmed WaveInfo记录。
4. 为该动态BG选择且只选择一个根因；ROOT使用唯一`<ROOT-XXX>`标签并完成五个ROOT分析字段，通过`<CAUSE-REF-ROOT-XXX>`和内嵌完整路径的`<RELATED-BUG-FG-.../FC-.../CK-.../BG-...>`建立双向链接；BG只保留三个字段，中央记录保留该BG的波形结论。
5. 用可选脚本同时更新静态汇总与详细区的LINK：

同一Fail TC证实多个独立动态Bug时，保留不同BG，并对每个精确BG/TC分别调用`ApplyWaveInfoEvidence`；目标BG/TC之外的Bug记录不会被修改，中央仍只有一份波形记录。单独运行当前静态候选用例时不得删除历史TC/BG；最终记录阶段仍需完整测试运行和严格重放。

```text
["unitytest/static-bug-validation", "linkbug.py", "-SBG 'BG-STATIC-001-CIN-OVERFLOW' -LBG 'BG-CIN-OVERFLOW-98'"]
```

一个静态候选关联多个动态Bug时，`-LBG`使用逗号分隔。候选被证明不成立时使用`-LBG 'BG-NA'`。脚本会拒绝不存在或未完成的动态BG。

技能禁用或脚本不可用时，使用文本编辑工具按`Guide_Doc/dut_bug_analysis.md`建立同一动态结构并直接编辑静态汇总和详情中的两处LINK标签，再执行相同验证；不得因为缺少Skill而暂停或降低验收标准。
