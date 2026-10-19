
# ACT4 privileged workflow 模板索引

这些 Markdown 是设计与填写模板，不是 ACT4 的汇编 writer template，也不是已验证资产。
选择插件工作流后，本目录随 Guide_Doc 自动复制到工作区。
`template: ""` 表示不自动渲染输出代码；人工或代理按阶段显式阅读并填写这些模板。

| 模板 | 使用阶段 | 产物/用途 |
| --- | --- | --- |
| [Coverpoints](privileged_coverpoints_template.md) | 01、02 | 请求边界、人类 testplan、SV 观察模型、coverage intent、mapping 交接 |
| [VM resources](privileged_vm_resource_template.md) | 03，04/05 复核 | profile、consumer、地址翻译、局部 blocker、实验隔离 |
| [Generator](privileged_test_generator_template.md) | 04，05 复核 | 冻结 API、注册参数、chunk、CSR/trap 与 VM 序列 |
| [Validation and handoff](privileged_validation_handoff_template.md) | 05-07 | 首选模型、attempt/fallback、证据配对、审查、manifest、最终报告 |

变量约定：`{OUT}` 是工作流输出根（通常 `unity_test`），`{DUT}` 是大小写敏感 suite；
`riscv-arch-test/` 是工作区中的 ACT4 副本。模板中路径相对运行 workspace，文档链接相对
当前 Markdown。占位文本、演示 target 和示例 XLEN 都要由实际证据替换。

先读[工作流指南](../ACT4_Privileged_Suite_Workflow_Guide.md)和
[checker 总览](../ACT4_Checker_Guide/README.md)。模板展示当前配置所要求的接口；
具体命令、宏、registry/helper 类型仍须以本轮冻结 ACT4 源码为准。
每阶段必需检查名从配置读取。不要把模板中的示例结论、命令或空清单作为已执行证据提交。

所有阶段统一按工作流指南第 4.2 节，复用 stage journal 维护计划、逐项进度、实际证据和
方案调整。先读当前所需资料再细化计划，在执行中更新；本目录不另设计划模板文件，
也不增加 checker 或审批。最终报告从 journal 汇总计划与实际结果，便于复盘。

首次 ACT4 写入前冻结 baseline；仅迭代本次新建 suite 资产。新依赖先更新 switch audit，
再生成/构建。stage 01-07 的 AI review 累积在同一文件，已完成阶段保持历史原样。
