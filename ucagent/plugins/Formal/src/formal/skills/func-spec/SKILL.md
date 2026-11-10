---
name: func-spec
description: 提取独立验证目标并通过 数据技能 批量维护 FG/FC/CK。
---

# 功能规格与检测点

一次维护完整FG/FC/CK层次。ID全任务唯一，前缀FG-/FC-/CK-，style为Assume/Comb/Seq/Cover。选择最小独立目标，Cover不替代assert；无约束需求不凑Assume，无状态不凑活性。Complete统一验收所有层次。

数据技能仅为可选捷径：需要批量维护时加载`ext/formal/data`，通过原有RunSkillScript调用`formal_data.py inspect spec`，把返回的结构化请求模板写入输出目录JSON文件，再调用`update --request-file`。不拼shell内嵌JSON或逐字段set，不改变已有Skill执行接口。完整调用与请求格式见`Guide_Doc/formal_data.md`。

技能关闭或目录缺失时，用ReadTextFile及普通文件编辑工具维护相同YAML子树；analysis/bugs先Check协调精确条目，再取得RunFormal当前真实证据。两条路径同等验收，不写run_results或运行状态，不改派生Markdown。

本指南仅按需提供方法，不是默认阶段完成仪式。目标齐备后SetCurrentStageJournal记录日志，再Complete；Check仅定位实际缺口。领域格式与完整例子见`Guide_Doc/functions_and_checks.md`。
