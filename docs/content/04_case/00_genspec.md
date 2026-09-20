
# 规范生成：GenSpec（Deprecated）

> **已弃用（deprecated）**：GenSpec 是旧版文档生成插件，后续文档生成统一使用 [SpecGenerator](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/SpecGenerator/README.md)。本页保留供旧工作流参考。

GenSpec 将零散设计说明、CSV 检查点和 RTL 源码整理为结构化规格文档，适用于规范缺失、资料整合及验证前的功能梳理。它位于 `plugins/GenSpec/`，是复用 UCAgent 内置工具与 Checker 的可选插件。

SpecGenerator 的安装、输入准备和运行方式见其 README；当前工作流面向 XiangShan，使用源码与同版本、同配置的生成 RTL 证据，交付版本化文档。插件机制见[插件开发与发布](../03_develop/09_plugins.md)。

## 运行 Adder 案例

先安装 UCAgent、配置模型连接。在 UCAgent 仓库根目录执行：

```bash
python -m pip install ./plugins/GenSpec
ucagent --validate-plugin gen-spec

mkdir -p output/genspec-adder
cp -R plugins/GenSpec/cases/Adder output/genspec-adder/
ucagent output/genspec-adder Adder \
  --plugin gen-spec --plugin-workflow gen-spec:generate-spec \
  --output spec --backend langchain --tui --loop
```

`output/genspec-adder/Adder/` 是只读输入，生成文件写入 `output/genspec-adder/spec/`。
工作流会自动复制规格指导模板和所需核心 Guide_Doc，无需手动传入配置文件或指导文件路径。
调试源码时，将 `--plugin gen-spec` 替换为 `--plugin ./plugins/GenSpec`。

使用自己的模块时，将输入放入 `<workspace>/<DUT>/`，替换命令中的工作区和 `Adder`。
应提供设计说明及 `.v/.sv/.scala` 源码；开启最后的对比阶段时，还需
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
显式设置 `GENSPEC_COMPARE_REFERENCE=false`，仅关闭最后的对比阶段：

```bash
cd plugins/GenSpec
GENSPEC_COMPARE_REFERENCE=false make run CASE=Sbuffer
```

插件内的 `make run CASE=Adder` 会准备输入并启动任务；`make mcp CASE=DCache` 只启动 MCP
服务，供外部 Agent 连接。两者默认使用 `output/workspace_<CASE>`，可通过 `WORKSPACE`
改为独立工作区。MCP 连接方式见 [MCP Server 模式](../02_usage/00_mcp.md)。

配置、完整产物及本地验证命令见
[GenSpec README](https://github.com/XS-MLVP/UCAgent/blob/main/plugins/GenSpec/README.md)。
需要改阶段时，遵循[工作流定制](../03_develop/03_workflow.md)中的列表覆盖规则，在插件自身目录维护工作流和测试。
