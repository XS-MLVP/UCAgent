---
name: bug-report
description: 依据已验证分析和工具反例通过 数据技能 批量填写缺陷详情。
---

# 缺陷观测与共享根因

只记录当前已核验RTL_BUG断言，Cover、未知和工具错误不是RTL Bug。显式root_cause_id关联共享根因，每条保留真实触发、预期与观测；不编造最小反例或声称修复已验证。失败属性数与独立根因数分开。

数据技能仅为可选捷径：需要批量维护时加载`ext/formal/data`，通过原有RunSkillScript调用`formal_data.py prepare bugs`，把返回的结构化请求模板写入输出目录JSON文件，再调用`update --request-file`。不拼shell内嵌JSON或逐字段set，不改变已有Skill执行接口。完整调用与请求格式见`Guide_Doc/formal_data.md`。

技能关闭或目录缺失时，用ReadTextFile及普通文件编辑工具维护相同YAML子树；analysis/bugs先Check协调精确条目，再取得RunFormal当前真实证据。两条路径同等验收，不写run_results或运行状态，不改派生Markdown。

本指南仅按需提供方法，不是默认阶段完成仪式。目标齐备后SetCurrentStageJournal记录日志，再Complete；Check仅定位实际缺口。领域格式与完整例子见`Guide_Doc/bug_report.md`。
