
# 通用 RTL 输入与证据

将 Verilog/SystemVerilog 输入放在 `inputs/{DUT}/`。不要求香山、Scala、Chisel 或外部 HDL 构建工具。所有输入文件保持只读；`{OUT}` 是本次输出目录。

## 配置输入

简单输入可不提供配置文件：工具寻找唯一声明 DUT 的文件，以该文件作为编译单元，解析文件内宏及相对 include。若存在多个候选、跨文件宏、外部宏定义或参数覆盖，必须提供 `inputs/{DUT}/rtl2spec.json`，精确指定以下四个字段。配置名只是标签，实际配置以此文件及源码为准。

完整配置例：

```json
{
  "files": ["config.vh", "top.sv"],
  "include_dirs": ["include"],
  "defines": {"HAS_BUS": "1", "BUS_WIDTH": "16"},
  "parameters": {"DEPTH": 4}
}
```

所有路径相对于 `inputs/{DUT}`，files 顺序就是同一编译单元的宏可见顺序；只解析选定的 files 及其 include。files 必须非空且不得重复；路径须位于输入目录内，不接受绝对路径、`..` 或符号链接。工具先从当前源文件目录、再从 include_dirs 顺序寻找 include。defines 的值为单行对象宏字符串；parameters 的值为顶层整数参数覆盖，未声明的参数或 localparam 不可覆盖。

支持条件编译、对象宏、字面量 include；pyslang 解析并展开选定顶层，支持 ANSI/非 ANSI 端口、package/typedef、packed struct/enum、多维 packed/unpacked 数组及 HDL 常量表达式。函数宏、多行宏、接口/modport、动态数组、非整数端口类型和未知指令会在预检失败；提供可解析的输入及其配置依据后重试。解析与展开检查不代表综合、仿真或形式化通过。

预处理保留当前分支中生效的 `timescale`、`default_nettype`、`celldefine` 和 `endcelldefine`；例如 `default_nettype none` 下未声明的信号会阻止证据生成，不能用自动推断的 wire 掩盖输入错误。

ports.csv 的 range/packed_dimensions 为解析后的 packed 维度，width 为每个数组元素的 packed 位宽，unpacked_range/unpacked_dimensions 为固定数组维度；signedness 和 canonical_type 保留元素的 signed/unsigned 与 pyslang 展开的 canonical 类型，type 保留源码类型写法，完整 unpacked 维度以对应的 unpacked_dimensions 为准。附录 A 的方向/位宽使用 `I/8`、`O/16` 等形式；unpacked 数组追加真实维度，如 `I/8[0:3]`，不得遗漏数组维度；需要区分 signed、packed 布局或逻辑类型时，以 ports.csv 的完整字段为准。端口表骨架自动填写这些事实。manifest 的 tool_versions 记录 pyslang 版本；升级前端后需使用新的空输出目录重新获取证据。

## 本阶段操作

1. 先用 ReadTextFile 读取本阶段 reference_files；确认 `{OUT}` 无旧产物。
2. 读取输入和配置，运行 `RTL2SpecCommand(action="generic_evidence", module="ExampleBlock", config="Generic")`，按实际 DUT 名替换。该操作包含输入预检；失败时按具体文件与行号修复，需要单独排查时使用 `action="generic_preflight"`。
3. 读取 manifest、ports.csv、原始 RTL 和预处理视图；检查实际配置、端口和源码映射。
4. 读取真正支撑行为结论的依赖文件，用 `action="generic_related_sources", related_files=["helper.sv"]` 登记。路径相对 inputs/{DUT}，不重复登记顶层源文件。
5. 运行 `action="generic_ports"` 生成端口表骨架。记录结果后 Complete。

## 本阶段完成产物

```text
outputs/
  evidence/
    ExampleBlock.sv
    ExampleBlock.preprocessed.sv
    source_map.json
    ports.csv
    ports.md
    manifest.json
  logs/
    actions.jsonl
```

原始 RTL 按输入字节捕获；预处理视图只保留选定分支并展开对象宏/include。source_map.json 的每个元素将对应的预处理物理行映射到原文件 path 和 line。manifest 记录完整输入摘要、实际 files/include_dirs/defines/parameters、预处理视图摘要和端口信息；任何输入或配置变化都会使证据失效。

本阶段没有运行综合、仿真、SVA、formal 或 coverage。设计文档的完整示例见 Guide_Doc/generation-guide.md，固定结构见 Guide_Doc/chip_design_document_template_zh.md。
