---
name: dynamic-bug-recording
description: 为失败测试已确认的动态DUT Bug创建规范BG/TC骨架和中央波形引用；不负责Bug判定、波形取证或根因分析。
---

# 动态 Bug 骨架记录

Markdown 排版契约：本技能生成、维护或展示的任何 Markdown 中，每个 `#` 到 `######` 标题前后各保留一个空行；文件或 Markdown 示例首行标题不要求前置空行。标题后不得直接连接正文、列表、表格、下一级标题或代码围栏；规范机器伴随行是例外：字段标题后的 `<TAG>` 标记必须与标题紧邻，目标标题前的 `<a id="..."></a>` 锚点也必须与标题紧邻，以保持机器契约和链接有效。

当前stage的`skill_list`包含本技能时，Skill启用条件下必须按本技能的方法完成动态Bug分类与文档维护；`record_dynamic_bug.py`只是可选的确定性骨架助手。当前stage没有确认动态Bug时，执行下述无Bug分支即表示已使用本技能，不得为了运行脚本而制造Bug。Skill整体禁用或当前stage显式设置`force_use_skill: false`时，仍按stage task、Guide_Doc和内置工具完成同一格式与验收标准。

`RunTestCases`只运行已有的真实pytest验证用例，不执行普通Python、临时维护脚本或文档迁移脚本。不得创建伪pytest用例来修改或批量填充Bug文档。脚本存在时只通过`RunSkillScript`执行本技能声明的脚本；直接修改文档时使用文本工具，相同文本出现多次则用`ReplaceStringInFile`的`line_blocks=[[start, end]]`限定到当前Checker阻塞位置，并且一次只处理当前记录的当前字段。

仅在正确测试稳定复现DUT设计缺陷后进入本技能的Bug记录分支或运行骨架脚本。每个Fail TC都不预设责任方；调用脚本、WaveInfo或创建/更新非零BG之前，必须从规格、独立参考模型或可验证公式推导`specification_expected`，并完成`input | specification_expected | test_expected | actual | classification`对照。不得直接相信模板注释、已有断言、静态候选或可疑RTL；静态候选不能覆盖TC级反证。expected不一致时修正测试并重跑，禁止记录Bug。

动态 Bug 的唯一目标是`{OUT}/{DUT}_bug_analysis.md`；可见标题不是文件名规则，不得另建文件。同一报告 node ID 的固定写法是：Markdown使用`- {visible_title} <TC-{exact_report_node_id}>`；本脚本、Apply参数及中央YAML `test_case`使用`TC-{exact_report_node_id}`；WaveInfo `test_case_name`使用`{exact_report_node_id}`。`visible_title`替换为测试docstring的首个非空描述行。没有动态 Bug 时保留该文件，并让`DYNAMIC-BUGS`、`ROOT-CAUSES`、`WAVEFORM-EVIDENCE`三个容器正文全部为空。

无Bug分支的完成条件是：所有失败都已按本技能完成责任分类，验证问题已修复并重跑为Pass，当前阶段没有正确测试稳定复现DUT设计缺陷，且上述三个容器保持规范空结构。此时不得调用`record_dynamic_bug.py`、WaveInfo或Apply，也不得创建BG/TC/ROOT/波形占位；完成这些核对后可将本技能的`use`记录为true。

expected一致后，必须核对测试激励/driver、API callback、Step、采样边沿、有效条件、响应延迟、fixture、参考模型、复位和环境。输入经过取反、编码、掩码、分包或carry/borrow变换时，必须从实际驱动值和规格运算重新计算expected；不能用变换前操作数的expected比较变换后输入，`a+(~b)+0`是`a-b-1`，而`a-b`需要`a+(~b)+1`。CK失败时必须先核对coverage/check function，并继续核对CK predicate、`CovGroup.sample()`执行与采样时机；这些验证问题必须修复并重跑，CK Fail本身不能作为DUT Bug结论。不得把当前Pass用例改成Fail来满足门禁；修复验证逻辑后CK可以转为Pass，此时不再需要Fail复现用例。只有全部验证项正确且DUT actual仍违反规格时，才允许继续。调用前还需确认当前报告将该Fail TC关联到目标精确FG/FC/CK路径，并准备非零置信度`BG-*`、从当前报告逐字生成的`TC-*`和简短描述。Fail TC可以成功触发并覆盖关联CK，不能由TC Fail反推CK Fail，也不要求每个Fail TC关联失败CK。阶段结束时，每个保留的Fail TC必须在其报告关联的至少一个CK下进入非零BG；独立地，每个保留的失败CK也必须有同一CK下的真实Fail TC。不能用本技能制造Bug记录。

`record_dynamic_bug.py`先读取`.ucagent/runtime_config.json`中的`test_output_dir`作为本次实际TC输出目录，并拒绝目录不一致的`-TC`。直接使用Checker的`Configured TC output directory`和`Similar current FAILED report node IDs`给出的实际值：从目标报告node ID只删除`:start-end`或`:line`，再加`TC-`。下方`EXACT_TC_TAG_FROM_CHECKER`必须替换为该完整实际标签，不是可提交的字面量：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'EXACT_TC_TAG_FROM_CHECKER' -BD '完整加法结果被错误截断。'"]
```

脚本从当前报告解析FG/FC/CK，从功能检查文档读取可见名称，从测试docstring读取TC名称，并用`BD`生成BG名称。它按Guide_Doc/dut_bug_analysis.md中的第 5.1 节创建BG三个字段、唯一`<CAUSE-REF-ROOT-XXX>`、ROOT五字段和内嵌完整FG/FC/CK/BG路径的反向链接。它不创建波形YAML，不调用WaveInfo，也不表示分析完成。

脚本生成的是带`<BUG-TODO>`的未完成骨架。BG只保留“Bug概述、现象与严重度、触发条件与影响”三个字段，根因引用位于TRIGGER末尾。源码证据、因果链、修复建议、风险与复验只在唯一ROOT实体中填写。每个ROOT使用唯一`<ROOT-XXX>`并至少关联一个完整BG路径；每个BG只能关联一个ROOT，组合缺陷使用独立ROOT。一个ROOT关联多个BG时，ROOT因果链和复验必须覆盖所有分支。

验收单位是完整`FG/FC/CK/BG`路径。每个路径必须独立保留自己的TC、三个BG字段和唯一ROOT引用；ROOT共享分析和TC中央波形不得复制到各路径。
每个 BG 必须且只能有一个根因；每个 ROOT 至少关联一个真实存在的完整 BG 路径，且两侧链接必须完全一致。

随后必须调用最终WaveInfo，并用`ApplyWaveInfoEvidence`在`<WAVEFORM-EVIDENCE>...</WAVEFORM-EVIDENCE>`中创建该TC唯一的`<WAVEFORM-TC-...>`记录。中央记录标题逐字复用TC可见名称并追加“波形”。同一TC关联多个Bug时，对每个BG调用一次Apply工具；中央波形仍只有一份，并在`bug_tags`和`bug_evidence`中列出全部关联。

TC、WaveInfo和Apply必须逐字使用Checker返回的完整pytest node ID，只允许删除报告附带的文件行范围；其文件路径必须以脚本从runtime config返回的`Configured TC output directory`开头。每次WaveInfo的`test_case_name`只去掉`TC-`。不得去掉或增加目录、改文件名或只传函数名。inventory的basename/recommended_call只用于定位波形，不建立源码身份；相似节点只供复制完整报告node ID，不参与匹配。

Apply返回`receipt_test_mismatch`或`matching_final_receipt_not_found`时，保持test_case_tag不变，原样执行`details.recovery_call`一次，再用新receipt_id和原标签重调Apply。不得猜路径变体或手工写receipt YAML、anchor、viewer URL/token。同一tool+status+target连续同错后停止尝试相似参数；没有recovery_call或执行后仍同错时，停止修改当前Bug/波形记录并报告工具契约阻塞。

同一CK/BG路径的后续失败TC直接调用`ApplyWaveInfoEvidence`，不要在该CK内复制BG；工具从目标测试函数docstring读取中文可见标题，并把新TC插入首个分析标题之前。若同名BG出现在多个CK下，先用脚本或文本工具建立目标CK下的完整BG/TC路径，再调用`ApplyWaveInfoEvidence(..., checkpoint_path="FG-.../FC-.../CK-...")`选择精确路径。测试源码和docstring必须先存在。技能未启用或脚本不可用时，使用文本编辑工具按相同来源填写具体中文名称，并复现Guide_Doc/dut_bug_analysis.md中的第 5.1 节层级与结构；任务要求和完成标准不变。
