---
name: sva-gen
description: 通过 数据技能 bodies 批量实现已有检测点的属性体。
---

# SVA属性实现

根据真实端口/参数与CK目标编写完整sva_body，外层声明和标签自动生成，不编辑派生SV。Comb检查同一采样点关系，同周期布尔|->可用，禁止延迟、历史采样或人为时钟豁免。核对位宽、符号和参考值，编译错不是反例。

数据技能仅为可选捷径：需要批量维护时加载`ext/formal/data`，通过原有RunSkillScript调用`formal_data.py inspect spec`，把返回的结构化请求模板写入输出目录JSON文件，再调用`update --request-file`。不拼shell内嵌JSON或逐字段set，不改变已有Skill执行接口。完整调用与请求格式见`Guide_Doc/formal_data.md`。

技能关闭或目录缺失时，用ReadTextFile及普通文件编辑工具维护相同YAML子树；analysis/bugs先Check协调精确条目，再取得RunFormal当前真实证据。两条路径同等验收，不写run_results或运行状态，不改派生Markdown。

本指南仅按需提供方法，不是默认阶段完成仪式。目标齐备后SetCurrentStageJournal记录日志，再Complete；Check仅定位实际缺口。领域格式与完整例子见`Guide_Doc/sva_property.md`。
