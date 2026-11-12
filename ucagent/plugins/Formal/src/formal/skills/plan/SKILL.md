---
name: plan
description: 使用结构化公共数据接口维护验证规划。
---

# 验证规划

先阅读规格与RTL，提炼独立验证目标、范围、假设、交付和风险。风险每项包含risk/mitigation；静态怀疑不能写成已复现Bug。输入空间大小不等于实际证明时间，避免重复背景。

数据技能仅为可选捷径：需要批量维护时加载`ext/formal/data`，通过原有RunSkillScript调用`formal_data.py inspect planning`，把返回的结构化请求模板写入输出目录JSON文件，再调用`update --request-file`。不拼shell内嵌JSON或逐字段set，不改变已有Skill执行接口。完整调用与请求格式见`Guide_Doc/formal_data.md`。

技能关闭或目录缺失时，用ReadTextFile及普通文件编辑工具维护相同YAML子树；analysis/bugs先Check协调精确条目，再取得RunFormal当前真实证据。两条路径同等验收，不写run_results或运行状态，不改派生Markdown。

本指南仅按需提供方法，不是默认阶段完成仪式。目标齐备后SetCurrentStageJournal记录日志，再Complete；Check仅定位实际缺口。领域格式与完整例子见`Guide_Doc/formal_data.md`。
