
# ACT4GenerationInputsChecker

准备本轮原生 testplan、ISA 原文与正式规则快照；用于两种生成工作流。

## 操作

先完成资源与环境阶段。用 ACT4Resources list/read 确认实际规范路径，然后调用：

```text
Check(stage_args={"action":"prepare","manual_files":["src/priv/sstc.adoc"]})
Check()
Complete()
```

该示例仅适合 Sstc；完整产物契约和其他 suite 的选择方法见
`Guide_Doc/ACT4_Generation_Guide.md section 2`。原生计划不存在允许 new_suite，
但所选原文必须来自记录的 manual HEAD。规则 name/text 必须有正式 JSON 来源。
非文本编码图的 text 可为空；通过 non_text_rules 与 rule_locations 回到原文核对图表和依赖，
不要编造公开规则文本，不能将来源局限解释为测试已验证。

## 验收与修复

普通 Check 核对收据及所有快照、ACT/manual HEAD 与所选源文件。不要手写收据或借用
其他运行的副本。原文或 HEAD 变化需恢复固定版本或新开一次运行；缺规则需补齐可信来源。
公开规则发布版本与 manual HEAD 独立，文本语义仍需核对，不能仅凭 ID 相同断言规范一致。
