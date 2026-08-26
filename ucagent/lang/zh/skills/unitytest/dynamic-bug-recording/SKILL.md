---
name: dynamic-bug-recording
description: 为失败测试已确认的动态DUT Bug创建规范BG/TC骨架和中央波形引用；不负责Bug判定、波形取证或根因分析。
---

# 动态 Bug 骨架记录

Markdown 排版契约：本技能生成、维护或展示的任何 Markdown 中，每个 `#` 到 `######` 标题前后各保留一个空行；标题前置空行没有例外：文件开头的标题、Markdown 示例围栏内首个标题和 `<a id="..."></a>` 锚点后的目标标题都必须有前置空行。标题前不得直接连接正文、列表、表格、下一级标题、代码围栏或锚点；字段标题后的规范机器标记（例如 `<BUG-*>`、`<ROOT-*>` 和 `<RELATED-BUGS>`）可以继续与标题紧邻。

当前stage的`skill_list`包含本技能时，Skill启用条件下必须按本技能的方法完成动态Bug分类与文档维护；`record_dynamic_bug.py`只是可选的确定性骨架助手。当前stage没有确认动态Bug时，执行下述无Bug分支即完成本技能要求，但记录动作为`use=false`，不得为了运行脚本或改成`use=true`而制造Bug。Skill整体禁用或当前stage显式设置`force_use_skill: false`时，仍按stage task、Guide_Doc和内置工具完成同一格式与验收标准。

`{DUT}_bug_analysis.md`是跨阶段累计文档。当前stage只运行测试子集时，Checker报告是局部报告：只更新报告中逐字出现的TC；当前Fail必须分类，当前Pass不能继续作为动态Bug复现证据，完全未出现的历史TC保持原状。历史TC未出现在本轮报告不表示它已Pass、失效或路径错误，禁止仅因此删除、改名、移动或重新取证其TC/BG、ROOT关联和中央波形记录。最终完整测试报告才校验累计文档中的全部TC。

同一TC可以按真实报告关系出现在多个完整`FG/FC/CK/BG`路径下，且相关CK可以已经通过覆盖，不能由TC Fail反推CK Fail。同一精确路径内不得重复TC；同名BG/TC跨不同CK时保留所有真实路径，并向`ApplyWaveInfoEvidence`传完整`checkpoint_path`。该TC在中央`<WAVEFORM-EVIDENCE>`中仍只有一份波形记录。

当前stage没有确认新的DUT Bug时，不新增BG、ROOT或波形记录，但不得清空累计历史；只有整个累计文档从未记录动态Bug时，才使用`Guide_Doc/dut_bug_analysis.md`第2.1节的三个空容器结构。完成该无Bug分支并通过`Check`后，调用`SetSkillUsage`时对本Skill提交`list=true/read=true/use=false`，并附加非空`reason`说明“当前阶段无确认动态DUT Bug，已执行无Bug分支且未运行脚本”。这里的`use=false`明确表示本技能的记录动作没有适用对象；它不是跳过`ListSkill`、读取`SKILL.md`或当前阶段检查的理由。

`RunTestCases`只运行已有的真实pytest验证用例，不执行普通Python、临时维护脚本或文档迁移脚本。不得创建伪pytest用例来修改或批量填充Bug文档。脚本存在时只通过`RunSkillScript`执行本技能声明的脚本；直接修改文档时使用文本工具，相同文本出现多次则用`ReplaceStringInFile`的`line_blocks=[[start, end]]`限定到当前Checker阻塞位置，并且一次只处理当前记录的当前字段。

仅在正确测试稳定复现DUT设计缺陷后进入本技能的Bug记录分支或运行骨架脚本。每个Fail TC都不预设责任方；调用脚本、WaveInfo或创建/更新非零BG之前，必须从规格、独立参考模型或可验证公式推导`specification_expected`，并完成`input | specification_expected | test_expected | actual | classification`对照。不得直接相信模板注释、已有断言、静态候选或可疑RTL；静态候选不能覆盖TC级反证。expected不一致时修正测试并重跑，禁止记录Bug。

动态 Bug 的唯一目标是`{OUT}/{DUT}_bug_analysis.md`；可见标题不是文件名规则，不得另建文件。Markdown、本脚本、Apply和中央YAML `test_case`使用当前函数级报告node（只删除源码行范围）。非参数化WaveInfo使用同一node；若报告含`tests.test_case_instances`，文档TC保持函数级node，WaveInfo选择一个实际FAILED参数化child，Apply只接受同一完整路径/类/函数的child receipt，并由工具在YAML `executed_test_case`记录该child。`visible_title`取测试docstring首个非空描述行。没有动态 Bug 时保留三个空容器。

无Bug分支的完成条件是：所有失败都已按本技能完成责任分类，验证问题已修复并重跑为Pass，当前阶段没有正确测试稳定复现DUT设计缺陷，且上述三个容器保持规范空结构。此时不得调用`record_dynamic_bug.py`、WaveInfo或Apply，也不得创建BG/TC/ROOT/波形占位；完成这些核对并通过当前`Check`后，将本技能记录为`use=false`并在`reason`中说明无适用对象。只有实际应用了文本方法或成功执行了声明脚本，才记录`use=true`。

expected一致后，必须核对测试激励/driver、API callback、Step、采样边沿、有效条件、响应延迟、fixture、参考模型、复位和环境。输入经过取反、编码、掩码、分包或carry/borrow变换时，必须从实际驱动值和规格运算重新计算expected；不能用变换前操作数的expected比较变换后输入，`a+(~b)+0`是`a-b-1`，而`a-b`需要`a+(~b)+1`。CK失败时必须先核对coverage/check function，并继续核对CK predicate、`CovGroup.sample()`执行与采样时机；这些验证问题必须修复并重跑，CK Fail本身不能作为DUT Bug结论。不得把当前Pass用例改成Fail来满足门禁；修复验证逻辑后CK可以转为Pass，此时不再需要Fail复现用例。只有全部验证项正确且DUT actual仍违反规格时，才允许继续。调用前还需确认当前报告将该Fail TC关联到目标精确FG/FC/CK路径，并准备非零置信度`BG-*`、从当前报告逐字生成的`TC-*`和简短描述。Fail TC可以成功触发并覆盖关联CK，不能由TC Fail反推CK Fail，也不要求每个Fail TC关联失败CK。阶段结束时，每个保留的Fail TC必须在其报告关联的至少一个CK下进入非零BG；独立地，每个保留的失败CK也必须有同一CK下的真实Fail TC。不能用本技能制造Bug记录。

`record_dynamic_bug.py`先读取`.ucagent/runtime_config.json`中的`test_output_dir`和`current_test_report`。`Check`或`RunTestCases`每次真实运行Unity测试后，会把含`failed_test_case_with_check_point_list`的当前阶段报告发布到`current_test_report`指向的`.ucagent/current_test_report.json`；脚本只读取该统一报告，不读取任何阶段私有报告。进入新阶段时旧报告失效，因此脚本若提示当前报告不存在，先运行当前阶段的真实测试，再重试，禁止手工创建或复制报告。直接使用Checker的`Configured TC output directory`和`Similar current FAILED report node IDs`给出的实际值：从目标报告node ID只删除`:start-end`或`:line`，再加`TC-`。下方`EXACT_TC_TAG_FROM_CHECKER`必须替换为该完整实际标签，不是可提交的字面量：

```text
["unitytest/dynamic-bug-recording", "record_dynamic_bug.py", "-BG 'BG-CIN-OVERFLOW-98' -TC 'EXACT_TC_TAG_FROM_CHECKER' -BD '完整加法结果被错误截断。'"]
```

脚本从当前报告解析FG/FC/CK，从功能检查文档读取可见名称，从测试docstring读取TC名称，并用`BD`生成BG名称。它按Guide_Doc/dut_bug_analysis.md中的第 5.1 节创建BG三个字段、唯一`<CAUSE-REF-ROOT-XXX>`、ROOT五字段和内嵌完整FG/FC/CK/BG路径的反向链接。它不创建波形YAML，不调用WaveInfo，也不表示分析完成。

脚本生成的是带`<BUG-TODO>`的未完成骨架。BG只保留“Bug概述、现象与严重度、触发条件与影响”三个字段，根因引用位于TRIGGER末尾。源码证据、因果链、修复建议、风险与复验只在唯一ROOT实体中填写。每个ROOT使用唯一`<ROOT-XXX>`并至少关联一个完整BG路径；每个BG只能关联一个ROOT，组合缺陷使用独立ROOT。一个ROOT关联多个BG时，ROOT因果链和复验必须覆盖所有分支。

验收单位是完整`FG/FC/CK/BG`路径。每个路径必须独立保留自己的TC、三个BG字段和唯一ROOT引用；ROOT共享分析和TC中央波形不得复制到各路径。
每个 BG 必须且只能有一个根因；每个 ROOT 至少关联一个真实存在的完整 BG 路径，且两侧链接必须完全一致。

随后必须调用最终WaveInfo，并用`ApplyWaveInfoEvidence`在`<WAVEFORM-EVIDENCE>...</WAVEFORM-EVIDENCE>`中创建该TC唯一的`<WAVEFORM-TC-...>`记录。中央记录标题逐字复用TC可见名称并追加“波形”。同一TC关联多个Bug时，对每个BG调用一次Apply工具；中央波形仍只有一份，并在`bug_tags`和`bug_evidence`中列出全部关联。

文档TC和Apply必须逐字使用Checker返回的函数级pytest node，只允许删除报告附带的文件行范围；路径必须以runtime config中的`Configured TC output directory`开头。非参数化WaveInfo只去掉`TC-`；参数化聚合时从`tests.test_case_instances`选择实际FAILED child，不得自行拼接参数ID。child删除末尾`[...]`后必须与文档TC的完整路径/类/函数逐字相同；`file.py::test`与`tests/file.py::test`永远不等价。inventory和相似节点只供定位/核对，不参与匹配。

`RunTestCases(target=...)`的target相对于上述配置TC目录，不能再次包含该目录前缀；Bug TC、WaveInfo和Apply则使用workspace相对完整路径。若工具返回`PYTEST_TARGET_DIRECTORY_PREFIX`，使用其中`correct_target`原样重试，不能把该修正解释为TC身份等价。

Apply返回`receipt_test_mismatch`或`matching_final_receipt_not_found`时，保持函数级test_case_tag不变。若`details.parameterized_receipts`非空，将其中`test_case_name`与当前报告`tests.test_case_instances`逐字核对，选择实际FAILED child并用该完整node重新完成最终WaveInfo；否则原样执行`details.recovery_call`一次。再用新receipt_id重调Apply。不得按波形basename猜路径/参数ID或手写receipt YAML、anchor、viewer URL/token；无有效候选/恢复调用时停止并报告工具契约阻塞。

同一CK/BG路径的后续失败TC直接调用`ApplyWaveInfoEvidence`，不要在该CK内复制BG；工具从目标测试函数docstring读取中文可见标题，并把新TC插入首个分析标题之前。若同名BG出现在多个CK下，先用脚本或文本工具建立目标CK下的完整BG/TC路径，再调用`ApplyWaveInfoEvidence(..., checkpoint_path="FG-.../FC-.../CK-...")`选择精确路径。测试源码和docstring必须先存在。技能未启用或脚本不可用时，使用文本编辑工具按相同来源填写具体中文名称，并复现Guide_Doc/dut_bug_analysis.md中的第 5.1 节层级与结构；任务要求和完成标准不变。
