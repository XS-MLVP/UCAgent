
# 规范生成：GenSpec（Deprecated）

> **已弃用（deprecated）**：GenSpec 是旧版文档生成工作流示例，后续文档生成统一使用 [SpecGenerator](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/SpecGenerator/README.md)。本页保留供旧工作流参考。

GenSpec 将零散设计说明、CSV 检查点和 RTL 源码整理为结构化规格文档，适用于规范缺失、资料整合及验证前的功能梳理。它位于 `plugins/GenSpec/`，通过 `genspec.yaml` 复用 UCAgent 内置工具与 Checker。

SpecGenerator 的安装、输入准备和运行方式见其 README；当前工作流面向 XiangShan，使用源码与同版本、同配置的生成 RTL 证据，交付版本化文档。插件机制见[插件开发与发布](../03_develop/09_plugins.md)。

## 运行 Adder 案例

先安装 UCAgent、配置模型连接。在 UCAgent 仓库根目录执行：

```bash
mkdir -p output/genspec-adder
cp -R plugins/GenSpec/Adder output/genspec-adder/
ucagent output/genspec-adder Adder \
  --config plugins/GenSpec/genspec.yaml \
  --guid-doc-path plugins/GenSpec/SpecDoc/dut_spec_template.md \
  --output spec --backend langchain --tui --loop
```

`output/genspec-adder/Adder/` 是只读输入，生成文件写入 `output/genspec-adder/spec/`。
`--config` 选择示例工作流，`--guid-doc-path` 将规格指导模板复制到工作区的 `Guide_Doc/`。
GenSpec 使用配置文件启动，无需单独安装插件。

使用自己的模块时，将输入放入 `<workspace>/<DUT>/`，替换命令中的工作区和 `Adder`。
应提供设计说明及 `.v/.sv/.scala` 源码；最后的对比阶段还需
`<workspace>/<DUT>/<DUT>_functions_and_checks.csv`。

## 工作流程

工作流包含七个顶层阶段，其中功能分析分为三个子阶段：

| 阶段 | 任务与主要产物 | 验收方式 |
| --- | --- | --- |
| `draft_main_spec` | 整理文字资料，编写 `<DUT>_spec.md` | 二级标题及文件引用检查 |
| `draft_component_spec` | 为独立组件编写 `<DUT>_spec_<component>.md` | 批量检查；没有独立组件时允许为空 |
| `augment_with_code` | 逐文件读取源码，补全接口、时序、边界和待确认项 | 检查源码文件的读取记录 |
| `complete_subspecs` | 根据源码完善子组件规格 | 批量标题及引用检查 |
| `human_check` | 编写 `<DUT>_spec_summary.md`，提交人工审核 | 人工确认 |
| `functional_specification_analysis` | 依次定义 FG、FC、CK，写入 `<DUT>_functions_and_checks.md` | 标签结构检查 |
| `ref_function_line_map_generation` | 将参考 CSV 各行映射到新检查点，编写差异分析 | 文件行映射检查 |

以上产物路径均相对于 `OUT`，本例为 `spec/`。最后一步生成 `<DUT>_line_func_map.txt`
和 `<DUT>_line_map_analysis.md`，映射对象是原有检查点 CSV 的行。

主规格和子规格遵循 `Guide_Doc/dut_spec_template.md`。文件引用用
`<ref_file>相对工作区路径[:起始行-结束行]</ref_file>` 标注，引用文件必须存在。
无法确定的行为应标为待确认项；文件读取和结构检查不能证明文档语义准确。

在人工审核阶段，检查规格和摘要，修正遗漏后在 UCAgent 控制台执行 `hmcheck_pass`，
然后继续任务。设置 `HUMAN_CHECK_CK=true` 可额外要求功能检测点人工审核。

## 不同输入与运行方式

仓库中的 `Adder`、`DCache` 案例含参考检查点 CSV，`Sbuffer` 不含。对于没有参考 CSV 的输入，
使用 `--skip 9` 关闭最后的对比阶段。以下命令从 UCAgent 仓库根目录执行：

```bash
mkdir -p output/genspec-sbuffer
cp -R plugins/GenSpec/Sbuffer output/genspec-sbuffer/
ucagent output/genspec-sbuffer Sbuffer \
  --config plugins/GenSpec/genspec.yaml \
  --guid-doc-path plugins/GenSpec/SpecDoc/dut_spec_template.md \
  --output spec --skip 9 --backend langchain --tui --loop
```

使用外部 Agent 时，将 `--loop` 换为 `--mcp-server --no-embed-tools`。连接方式见
[MCP Server 模式](../02_usage/00_mcp.md)。

示例目录内保留原有 `make init_DCache`、`make spec_DCache` 和 `make spec_mcp_DCache`
入口；其中 `init_*` 会先清空该示例的 `output/`，已有产物时优先使用上面的独立工作区命令。

配置及完整产物见
[GenSpec README](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/GenSpec/README.md)。
需要改阶段时，遵循[工作流定制](../03_develop/03_workflow.md)中的列表覆盖规则，修改示例的 `genspec.yaml`。
