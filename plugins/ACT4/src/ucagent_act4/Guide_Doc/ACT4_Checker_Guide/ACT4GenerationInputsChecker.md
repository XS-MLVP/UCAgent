
# ACT4GenerationInputsChecker

准备本轮原生 testplan、规范原文、公开规则与待发布条款绑定；用于两种生成工作流。

## 操作

先完成资源与环境阶段。预览候选，用 ACT4Resources list/read 确认实际规范路径，然后调用：

```text
Check(stage_args={"action":"discover"})
Check(stage_args={"action":"discover","manual_files":["src/priv/sstc.adoc"]})
Check(stage_args={"action":"prepare","manual_files":["src/priv/sstc.adoc"]})
Check()
Complete()
```

该示例仅适合 Sstc；完整产物契约和其他 suite 的选择方法见
`Guide_Doc/ACT4_Generation_Guide.md section 2`。原生计划不存在允许 new_suite，
但所选原文必须来自记录的 manual HEAD。规则 name/text 来自公开 JSON，或由 bind_rules
逐字绑定到冻结原文；后者明确标为待发布规则。独立规范不要求位于 src/。
非文本编码图的 text 可为空；通过 non_text_rules 与 rule_locations 回到原文核对图表和依赖，
不要编造公开规则文本，不能将来源局限解释为测试已验证。

## 验收与修复

普通 Check 核对收据及所有快照、ACT/manual HEAD 与所选源文件。不要手写收据或借用
其他运行的副本。原文或 HEAD 变化需恢复固定版本或新开一次运行。缺公开规则时调用
`Check(stage_args={"action":"bind_rules","rule_bindings":[...]})`，每项包含
name、source、start_line、end_line、text、upstream，完整示例见
`Guide_Doc/ACT4_Generation_Guide.md section 2`。不可将待发布规则伪称为已发布规则。
公开规则发布版本与 manual HEAD 独立，文本语义仍需核对，不能仅凭 ID 相同断言规范一致。

discover 不冻结也不完成输入；返回全部 native_plans 与需要阅读的规范候选。prepare 中的
manual_files 必须包含相关原文，其余候选通过 manual_exclusions 逐项说明。plan_paths 必须
保留全部已发现族成员，不能只选 common。规范引用不是规则定义，不得用引用位置冒充条款来源。
Complete 前遗漏可用 extend 增补完整文件/计划列表；失败保留原输入，成功保留原规则索引与绑定。
Complete 后不再修改范围。完整调用及分组映射格式见 `Guide_Doc/ACT4_Generation_Guide.md section 2`
和 `Guide_Doc/ACT4_Generation_Guide.md section 3`。
