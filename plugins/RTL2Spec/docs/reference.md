
# RTL2Spec 工作流与工具参考

安装和运行命令见 [README](../README.md)，实现结构、测试与打包方法见[开发与验证](development.md)。

## 工作流与验收

文档生成分为三个阶段：生成 RTL 证据、编写文档、验证与验收。实现结论来自 Chisel/Scala 源码与同 commit、同配置的 RTL；可选需求说明用于核对设计意图，无法确认的内容保留为 `OPEN-*`。

设计文档必须遵循模板规定的固定输出顺序：文档摘要、设计概览、功能行为、验证策略与 Testplan、形式化属性契约、Sign-off 与开放项、附录 A 至附录 E。正文按职责与边界、事务模型、数据/控制通路、资源冲突、时序与状态组织；验证策略记录采样工件，形式化契约记录 harness 边界，Sign-off 和场景使用结构化表格；完整扁平 I/O、参数、源码路径和证据集中在附录。完整要求见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](../src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。

同一次运行中可继续修订草稿、同步 metadata 和验收。Mermaid 图直接保留在 Markdown 源码中，不生成 SVG、图形清单或其他图片文件。启动新一轮生成前必须由用户自行归档并清理旧产物，插件不会自动打包、删除或覆盖旧文件。

产物路径固定，`--output` 指定 UCAgent 的输出与历史管理目录，不改变设计文档、质量报告和证据的路径。

## 后端配置

UCAgent 的 OpenCode 默认配置禁用原生 Shell 和工作区外访问。使用其他命令行后端时，先配置并验证同等限制；后端权限验证方法见[开发与验证](development.md#开发与验证)。

## 插件工具

UCAgent 在工作流中调用 `RTL2SpecCommand`，并通过 `Check`、`Complete` 验收阶段：

| action | 用途 |
| --- | --- |
| `preflight` | 检查模块、配置、源码和工具环境 |
| `evidence` | 生成 RTL、端口清单和基础证据 |
| `related_sources` | 记录实际参考的相关 Scala 模块、声明位置和源码哈希 |
| `metadata` | 同步事实元数据 |
| `validate` | 检查 Markdown 结构、证据、引用和 Mermaid 围栏 |
| `lint` | 执行最终检查，确认产物一致 |

调用时传入 `module` 和 `config`。需要把相关源码纳入证据时，先读取相关模块，再传入 `related_modules`：

```python
RTL2SpecCommand(action="evidence", module="Sbuffer", config="DefaultConfig")
RTL2SpecCommand(action="related_sources", module="Sbuffer", config="DefaultConfig", related_modules=["Helper"])
```

将 `Helper` 替换为本次确实读取的 XiangShan Scala class 名；若它支撑文档结论，就在正文引用对应的 `E-REL-*` 并在附录 C 定义，若只用于上下文核对，则只进入质量报告，不需要在正文中伪造引用。

单次命令上限一小时。只加载 `--plugin` 可复用工具和 Checker；选择 `--plugin-workflow` 才会启用文档工作流并复制 Guide_Doc。

## 常见问题

- **找不到插件或同名冲突**：确认 pip 与 ucagent 使用同一 Python 环境；源码调试使用 `--plugin /绝对路径/UCAgent/plugins/RTL2Spec`。
- **环境检查失败**：按诊断补齐工具或子模块，确认模块及配置 class 名正确；激活时要求 Bash、Git、Curl、Make 的 `--version` 能正常执行。
- **工具不可见**：检查 `tools.selected_tools` 与 `tools.ignore_tools`，勿屏蔽工作流所需工具。
- **验收失败**：按 `Check` 指出的文件和位置修复；修改事实字段后重新 `metadata`，修改 Mermaid 源码后重新 `validate`/`lint`。发现旧产物时先打包并清理模块输出目录。
- **相关模块证据缺失**：先读取实际支撑结论的 Scala 模块，再执行 `related_sources`；在正文引用生成的 `E-REL-*`，并把它加入附录 C。不要仅因为模块被顶层编译就把它列为参考模块。
- **修改插件资源后仍使用旧内容**：重新启动工作流并重新生成工作区的运行资源。
