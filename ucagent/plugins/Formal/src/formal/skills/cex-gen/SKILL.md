---
name: cex-gen
description: 根据原始形式化反例设计独立的引脚复现测试。
---

# 反例引脚测试

仅当当前任务启用反例测试阶段且有已核验RTL缺陷时使用。读取阶段规格、DUT公开接口与RunFormal返回的原始反例，不根据Bug描述自行发明输入序列。完整测试格式见 `Guide_Doc/counterexample.md`。

用普通文件工具填写阶段返回的测试骨架；每条目标使用精确完整属性身份，真实时序设计才配置真实时钟和复位。预期值依据独立核验的reference，不能用DUT自身输出作为预期。反例复现必须保留真实断言；没有确认Bug时按阶段无适用分支结束，不制造占位Bug或证据。

目标齐备后登记阶段日志并Complete，Check仅定位实际缺口。本技能是按需方法指导；默认阶段不声明Skill要求，不需要ListSkill/SetSkillUsage。已有RunSkillScript执行接口和脚本行为保持不变。
