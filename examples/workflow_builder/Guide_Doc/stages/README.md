# Workflow Builder 阶段指导索引

本目录为主工作流 24 个阶段提供一对一的静态指导。文件名前两位数字对应
`config.yaml` 的零基数组下标；例如 `00_extract_requirements_and_plan.md` 对应
Stage 0，`01_design_workflow_build_config.md` 对应 Stage 1。每个阶段都把自己的文档
列入 `reference_files`，因此运行 Agent 必须使用 `ReadTextFile` 阅读后才能完成阶段。

这些文档属于维护者知识库，不属于运行产物。`Guide_Doc/` 位于 `un_write_dirs`，
运行 Agent 不得修改。一次运行结束后，维护者只有在复现并确认根因后才能增加 FAQ，
且必须同时记录现象、原始 Checker 返回、复现条件、根因、正确修改位置、回归方法和
适用版本。不要收录仅对某个 workspace 有效的绝对路径、手工补丁或绕过 Checker 的办法。

每份阶段文档至少包含阶段目标、读写边界、详细步骤、关键文件的最小可通过版本、
常见示例、Checker 条件、历史问题和持续规划追加要求。

运行中积累的项目决策不写入这里，而是通过 `WorkflowPlanAppender` 追加到
`wfgen/workflow_implementation_plan.md`。静态 FAQ 解释“以前通常哪里出错”，持续规划
记录“本次运行实际做了什么”，二者不能混用。

## 跨阶段历史问题

| 可观察现象 | 原始失败信息或证据 | 已确认根因 | 正确修改位置与回归 |
|---|---|---|---|
| 同一个业务工具在后续阶段反复从真实实现退化成 `_default_value` 骨架 | `make test_tools` 的原用例在再次调用生成器后失败，源码摘要发生变化 | 旧流程使用 `overwrite=true`，把“根据新 spec 更新实现”错误理解为“重新渲染整个源码” | 在 `WorkflowToolGenerator` 使用 `create_only`；仅生成状态摘要匹配的未修改骨架可用 `refresh_scaffold`。运行稳定性回归和完整 `make test_tools` |
| Agent 为运行 `make check_docs` 创建 `wfgen/run_checks.py`、根级 shell 脚本或迁移包脚本 | 发布清理报告发现非交付脚本，或迁移包包含运行期文件 | 外层 Agent 只有通用测试工具，没有受限的子工作流命令入口 | 使用外层 `WorkflowCommandRunner` 执行白名单 Make 目标；确需批处理时脚本只放子工作流根级 `tmp/`，完成后删除并运行 `make clean` |
| GuideDoc generator 要求英文标题，而文档 Checker 或中文写作要求使用中文标题 | spec 检查提示缺 `Purpose`，改成英文后又偏离中文交付要求 | 机器语义错误地绑定在展示标题字符串上 | 新 spec 为七个章节写固定 `id`，`heading` 使用中文；运行 guidedoc 生成与最终覆盖回归 |
| config spec 看似正确，但保留旧注册后最终 config 出现父工作流路径或未知变量 | 最终静态审查发现 `.//workflow/`、`{TARGET}` 或阶段契约与 workflow_spec 不一致 | 生成器只验证输入 spec，没有复核合并后的最终对象 | `WorkflowConfigGenerator` 在落盘前审查最终配置；修正权威 workflow_spec/config spec 后重新生成，禁止只改最终 YAML |
| 所有阶段记录都显示在同一个顶层章节下，HTML 标记能解析但人工阅读困难 | `workflow_implementation_plan.md` 只有隐藏的 `WFB-STAGE-PLAN` 边界，没有可见阶段标题 | 追加器只为 Checker 写了机器标记 | 新追加记录自动增加 `## 阶段 NN：stage_name`，继续保留摘要链；运行 living plan 回归 |
| Agent 为判断 YAML 类型、发布树或迁移 manifest 编写一次性脚本，脚本自身断言反复失败 | 临时脚本把 `stage` 的 list 当成 dict、用子串误判 `.workflow/`，或 manifest 与真实树比较不完整 | 稳定的结构审查被临时自然语言代码重复实现 | 使用 `WorkflowArtifactInspector` 的 `yaml_summary`、`release_tree`、`migration_manifest`；只有业务专属且现有工具无法表达的验证才允许放入根级 `tmp/`，使用后删除 |
| `WorkflowCommandRunner` 拒绝 `make check_example`、`make plan`、`make help`、`make package` | 安全白名单漏掉了确定、无参数的标准目标 | Agent 被迫创建包装脚本，增加错误和残留风险 | 直接调用新增白名单目标；仍禁止 Make 变量注入、多个目标、shell 组合和 `run`/`run_inc` 等递归运行目标 |
| acceptance 明确要求某个固定公开文件，但迁移 Checker 把它当成运行产物 | 必需文件和洁净度规则分别维护，出现 `output/README.md` 一类冲突 | Checker 使用硬编码必需清单或整目录禁止规则，没有读取 acceptance | `.workflow/acceptance_rules.yaml` 是必需公开路径唯一来源；固定 output 标记只允许 README.md/.gitkeep/.keep，其他 output 运行产物仍拒绝 |
| 子 UCAgent 在启动阶段报 `Unknown scheme` 或代理行为与 tmux 外 shell 不一致 | 继承了 tmux 全局 `ALL_PROXY=socks://...`，但只查看了 pane 局部环境或 `proxy_on` 在清理前提前返回 | 环境诊断来源不完整，httpx/OpenAI 客户端不接受该代理协议 | 先调用 `WorkflowEnvironmentPreflight`，同时检查当前进程和 tmux 全局代理；生成的 `proxy_on` 必须在 enabled/disabled 分支前清理 `all_proxy/ALL_PROXY` |
