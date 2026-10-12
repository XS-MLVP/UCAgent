
# RTL2Spec 工作流与工具参考

安装和运行命令见 [README](../README.md)，实现结构、测试与打包方法见[开发与验证](development.md)。

## 工作流与验收

文档生成分为四个阶段：捕获或生成 RTL 证据、编写文档、源码语义复核、最终验收。XiangShan 工作流的实现结论来自 Chisel/Scala 源码与同 commit、同配置的 RTL；通用工作流的结论来自 `inputs/{DUT}/` 中已捕获并签名的 Verilog/SystemVerilog 源码。可选需求说明用于核对设计意图，无法确认的内容保留为 `OPEN-*`。

设计文档必须遵循模板规定的固定输出顺序：文档摘要、设计概览、功能行为、验证策略与 Testplan、形式化属性契约、Sign-off 与开放项、附录 A 至附录 E。正文按职责与边界、事务模型、数据/控制通路、资源冲突、时序与状态组织；验证策略记录采样工件，形式化契约记录 harness 边界，Sign-off 和场景使用结构化表格；完整扁平 I/O、参数、源码路径和证据集中在附录。完整要求见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md)和[文档模板](../src/rtl2spec/Guide_Doc/chip_design_document_template_zh.md)。

同一次运行中可继续修订草稿、同步 metadata 和验收。Mermaid 图直接保留在 Markdown 源码中，不生成 SVG、图形清单或其他图片文件。启动新一轮生成前选择空的输出目录，或由用户自行归档并清理旧产物，插件不会自动打包、删除或覆盖旧文件。

两条工作流都使用 UCAgent 的 `--output` 目录（工作流中为 `{OUT}`）：设计文档和质量报告位于目录根部，RTL、端口清单/骨架和 `manifest.json` 位于其 `evidence/` 子目录；复核记录与最终验收记录位于目录根部，调用耗时位于 `logs/actions.jsonl`，阶段起止时间与总耗时位于 `logs/stages.jsonl`。工具、阶段参考文件和验收均使用同一目录；完整布局与启动命令见 [README](../README.md#输出目录与验收)。

确定性检查从草稿阶段启用。完整字段、状态与引用规则见[生成指南](../src/rtl2spec/Guide_Doc/generation-guide.md#确定性验收规则)。规则允许多对多追溯、共享接口、有理由的不适用项及额外说明表；检查通过不代表实现语义或硬件功能正确。

## 后端配置

默认 Codex 的启动参数见 [README](../README.md#共同运行方式)。使用其他后端时，先配置并验证同等权限限制；后端权限验证方法见[开发与验证](development.md#开发与验证)。

## 插件工具

UCAgent 在工作流中调用 `RTL2SpecCommand`，并通过 `Check`、`Complete` 验收阶段：

| 香山 action | 通用 action | 用途 |
| --- | --- | --- |
| `preflight` | `generic_preflight` | 检查输入、配置和所需环境；不产生交付物 |
| `evidence` | `generic_evidence` | 生成或捕获 RTL、端口和签名证据；通用输入同时记录预处理配置与源码映射 |
| `related_sources` | `generic_related_sources` | 登记确实参考的相关 Scala 模块或输入文件 |
| `ports` | `generic_ports` | 根据当前证据生成 `evidence/ports.md`，只需补充逻辑分组和协议 |
| `metadata` | `generic_metadata` | 按字段/证据条目更新事实，保留无关文字和各源文件自己的摘要 |
| `validate` | `generic_validate` | 草稿诊断：字段/表格完整性、精确端口、ID 与跨表追溯、源码位置、签核声明及 Mermaid 围栏 |
| `review` | `generic_review` | 为当前文档生成 `semantic_review.json` 问题；相同基线保留答案，基线变化时创建新问题 |
| `lint` | `generic_lint` | 复核诊断：包含草稿检查，并验证每个行为的复核项、源码位置和当前摘要 |
| `finalize` | `generic_finalize` | 执行复核验收，自动更新报告，生成绑定最终工件的 `validation.json` |

正常路径为 evidence → related_sources（需要时）→ ports → 编写草稿 → metadata → 源码复核/review → finalize；各阶段记录日志后 Complete。validate/lint 用于需要诊断时，正常收尾不要求连续重复 validate、lint 和 Check。Check/Complete 始终核验当前内容；final 阶段还要求当前有效的验收记录。

复核记录格式与完整例子见 [源码复核指南](../src/rtl2spec/Guide_Doc/source-review-guide.md)。记录证明引用和复核项完整，不证明行为已通过动态或形式化验证。finalize 后不再手工回填验收结果；若修改设计或证据，先重新 metadata/review，再 finalize。

调用时传入 `module` 和 `config`。需要把相关源码纳入证据时，先读取相关模块，再传入 `related_modules`：

```python
RTL2SpecCommand(action="evidence", module="Sbuffer", config="DefaultConfig")
RTL2SpecCommand(action="related_sources", module="Sbuffer", config="DefaultConfig", related_modules=["Helper"])
RTL2SpecCommand(action="generic_evidence", module="GenericBlock", config="Generic")
RTL2SpecCommand(action="generic_related_sources", module="GenericBlock", config="Generic", related_files=["helper.sv"])
```

将 `Helper` 替换为本次确实读取的 XiangShan Scala class 名；若它支撑文档结论，就在正文引用对应的 `E-REL-*` 并在附录 C 定义，若只用于上下文核对，则只进入质量报告，不需要在正文中伪造引用。

通用工作流的 `related_files` 必须是 `inputs/GenericBlock/` 下的相对 POSIX 路径；工具会拒绝绝对路径、路径穿越、重复路径和顶层 RTL。输入目录发生变化后，旧 evidence 会失效，必须选择空的输出目录并重新开始一轮生成。

单次工具调用默认上限为 3660 秒。只加载 `--plugin` 可复用工具和 Checker；选择 `--plugin-workflow` 才会启用文档工作流并复制 Guide_Doc。修改插件资源后必须重新启动工作流，让新的 Guide_Doc 和工作流 YAML 被复制到工作区。

## 常见问题

- **找不到插件或同名冲突**：确认 pip 与 ucagent 使用同一 Python 环境；源码调试使用 `--plugin /绝对路径/UCAgent/plugins/RTL2Spec`。
- **环境检查失败**：XiangShan 工作流按诊断补齐工具或子模块，确认模块及配置 class 名正确；通用工作流检查 `inputs/{DUT}/rtl2spec.json` 指定的文件顺序、include、宏和参数；未提供配置时需要唯一顶层源文件。完整输入例见[通用输入指南](../src/rtl2spec/Guide_Doc/generic-generation-guide.md)。选择 XiangShan 工作流时要求 Bash、Git、Curl、Make 的 `--version` 能正常执行，通用工作流不依赖这组 XiangShan 工具链。
- **工具不可见**：检查 `tools.selected_tools` 与 `tools.ignore_tools`，勿屏蔽工作流所需工具。
- **验收失败**：按 `Check` 指出的文件和位置修复；按诊断选择草稿修订、metadata、review 或 finalize。`stale review` 表示文档/源码已变化，须重新复核；`stale acceptance` 表示交付物已变化，须重新验收。输入配置变化后应选择空输出目录重新捕获证据。
- **相关模块证据缺失**：XiangShan 工作流先读取实际支撑结论的 Scala 模块，再执行 `related_sources`；通用工作流先读取 `inputs/{DUT}/` 下的源码，再执行 `generic_related_sources`。在正文引用生成的 `E-REL-*`，并把它加入附录 C。不要仅因为文件存在就把它列为参考文件。
- **修改插件资源后仍使用旧内容**：重新启动工作流并重新生成工作区的运行资源。
