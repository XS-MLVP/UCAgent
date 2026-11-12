---
name: sva-audit
description: 依据当前完整属性身份与工具证据批量填写异常分析。
---

# 环境与属性分析

先核对真实witness、独立参考计算、实际输出与本条断言。TRIVIALLY_TRUE可能是正确恒等式，按工具原因审核；TRIVIALLY_FALSE是静态失败，不换较弱目标。属性/环境问题修复重跑，DUT缺陷保留Fail；旧输入证据不支持新版本。

数据技能仅为可选捷径：需要批量维护时加载`ext/formal/data`，通过原有RunSkillScript调用`formal_data.py prepare analysis`，把返回的结构化请求模板写入输出目录JSON文件，再调用`update --request-file`。不拼shell内嵌JSON或逐字段set，不改变已有Skill执行接口。完整调用与请求格式见`Guide_Doc/formal_data.md`。

技能关闭或目录缺失时，用ReadTextFile及普通文件编辑工具维护相同YAML子树；analysis/bugs先Check协调精确条目，再取得RunFormal当前真实证据。两条路径同等验收，不写run_results或运行状态，不改派生Markdown。

本指南仅按需提供方法，不是默认阶段完成仪式。目标齐备后SetCurrentStageJournal记录日志，再Complete；Check仅定位实际缺口。领域格式与完整例子见`Guide_Doc/env_analysis.md`。
