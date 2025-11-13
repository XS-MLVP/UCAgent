
## 基于 UCAgent 生成 Spec

Spec 文档是进行芯片验证与回归管理的基础。很多团队在项目早期只有零散的设计备忘、接口列表或旧版论文，缺乏结构化、可复用的规格说明。GenSpec 示例展示了如何借助 UCAgent 的自定义配置把这些碎片化资料整合成系统化的 `{DUT}_spec.md`，并在持续迭代中保持更新。

---

### 前置准备

- **工作空间布局**：以 `workspace/<DUT>/` 作为芯片资料主目录，新生成的 `spec` 文档会输出到 `workspace/{OUT}/`（OUT默认为`unity_test`）。
- **初始资料收集**：整理现有的功能列表、接口定义、时序图、论文摘录等，统一放置在 `{DUT}/docs/` 或 README 中，便于后续引用。

---

### `genspec.yaml` 配置要点
`genspec.yaml` 负责告诉 UCAgent 如何组织任务。如需了解具体内容请查看该文件。
参考spec模板文件为 `SpecDoc/dut_spec_template.md`。

### 生成流程

1. **collect_existing_assets：整理现有资料，搭建主 Spec**  
	- 读取 `{DUT}/` 下的 Markdown、CSV 等文字资料，抽取功能概览、关键约束、外设依赖；
	- 按 `Guide_Doc/dut_spec_template.md` 的章节结构在 `{OUT}/{DUT}_spec.md` 中输出初稿，所有二级标题必须与模板一致；
	- 若发现功能独立的子模块，同时创建 `{OUT}/{DUT}_spec_<component>.md` 协助后续拆分；
	- `MarkDownHeadChecker` 自动校验目录结构是否符合模板。

2. **augment_with_code：解析源码补全细节**  
	- 按 `WalkFilesOneByOne` 的调度依次阅读 `{DUT}/` 下的 `.v/.sv/.scala` 文件；
	- 为每个模块补齐接口表、参数限制、复位流程、状态机描述以及正常/异常路径；
	- 将分析结果写回 `{OUT}/{DUT}_spec.md`，若属于子组件则同步更新对应的 `{OUT}/{DUT}_spec_<component>.md`；
	- 完成一份源码分析后通过 `Check` 进入下一份，直到所有源文件处理完毕。

3. **complete_subspecs：批量完善子组件 Spec**  
	- 逐个打开 `{OUT}/{DUT}_spec_<component>.md`，根据主 Spec 记录的“RTL源文件”清单深入补全；
	- 继续沿用模板规范，保持接口、功能与代码分析一致；
	- `BatchMarkDownHeadChecker` 对所有子 Spec 的标题结构进行批量验证。

4. **human_check：人工综合校验**  
	- 通读主 Spec 与各子 Spec，确认接口/功能/时序描述准确一致；
	- 标注待确认需求并在 `{OUT}/{DUT}_spec_summary.md` 写入检查摘要；
	- `HumanChecker` 仅提示需要人工确认，最终通过由使用者决定。

5. **functional_specification_analysis：提炼功能点与检测点**  
	- 在 `{OUT}/{DUT}_functions_and_checks.md` 中以 `<FG-*>`、`<FC-*>`、`<CK-*>` 标签分三步写出功能分组、功能点与检测点；
	- 三个子阶段依次由 `UnityChipCheckerLabelStructure` 校验标签结构与覆盖情况，保证后续验证计划能够引用。

6. **ref_function_line_map_generation：参考检查点新检查点差异分析**
    - 对比检查点差异
	- 原来的：`{DUT}/{DUT}_functions_and_checks.csv`
	- 新建的：`{OUT}/{DUT}_functions_and_checks.md`
	- 差异：`{OUT}/{DUT}_line_func_map.txt`

---

### 运行命令示例
```bash
# 准备环境(创建 output目录)
cp examples/GenSpec/
make init_DCache

# 以API方式运行UCAgent生成spec文档
make spec_DCache

# 以MCP方式运行UCAgent
make spec_mcp_DCache
```

通过以上流程，GenSpec 示例可帮助团队快速搭建结构化规格说明文档，增加git支持，可实现设计演进过程中保持文档的可追溯性和一致性。祝使用顺利！
